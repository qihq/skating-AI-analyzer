from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, MemorySuggestion, SnowballMemory
from app.analysis_v2.fact_consumers import (
    FACTS_SCHEMA_VERSION,
    consumer_for_analysis,
    generation_fingerprint,
)
from app.services.providers import get_active_provider, request_text_completion
from app.services.report import clean_json_text
from app.services.snowball import is_memory_expired, utcnow


MEMORY_SUGGEST_SYSTEM_PROMPT = (
    "你是冰宝（IceBuddy），请分析训练报告并与现有长期记忆对比，提出记忆更新建议。"
    "长期记忆只保存稳定偏好、长期目标、反复出现的卡点、重要安全注意事项或已明确完成的目标。"
    "不要因为单次表现波动、一次性失败、画质问题或模型不确定结论就新增长期记忆。"
    "用户备注可以作为线索，但不能单独作为事实写入记忆。"
    "只输出 JSON 数组，不含任何 markdown 包裹。"
)


def _memory_text(memories: list[SnowballMemory]) -> str:
    if not memories:
        return "暂无长期记忆。"

    lines: list[str] = []
    now = utcnow()
    for memory in memories:
        status = "已过期" if is_memory_expired(memory, now) else ("固定" if memory.is_pinned else "普通")
        lines.append(f"- ID={memory.id} | {memory.title} | {memory.category} | {status} | {memory.content}")
    return "\n".join(lines)


def _fact_text(consumer) -> str:
    """Render only family-safe claims for the suggestion model.

    The model must not receive raw report/bio_data, Path A/B diagnostics, or
    unobservable/conflicting claims.  ``consumer_for_analysis`` has already
    applied the coaching permission and confirmed/observable gates.
    """
    if not consumer.facts:
        return "无可用于长期记忆的已确认事实。"
    lines: list[str] = []
    for fact in consumer.facts[:24]:
        value = fact.value
        if isinstance(value, dict):
            text = str(value.get("description") or value.get("text") or value).strip()
        else:
            text = str(value or "").strip()
        if not text:
            continue
        lines.append(f"- claim={fact.claim_type} event={fact.event_id or 'whole'} value={text}")
    return "\n".join(lines) or "无可用于长期记忆的已确认事实。"


def _normalize_suggestion(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    action = str(item.get("action", "")).strip().lower()
    if action not in {"add", "update", "expire"}:
        return None

    normalized: dict[str, Any] = {"action": action}
    if action == "add":
        title = str(item.get("title", "")).strip()
        content = str(item.get("content", "")).strip()
        category = str(item.get("category", "其他")).strip() or "其他"
        if not title or not content:
            return None
        normalized.update({"title": title, "content": content, "category": category})
        return normalized

    memory_id = str(item.get("memory_id", "")).strip()
    if not memory_id:
        return None

    normalized["memory_id"] = memory_id
    if action == "update":
        new_content = str(item.get("new_content", "")).strip()
        if not new_content:
            return None
        normalized["new_content"] = new_content
        if item.get("title") is not None:
            title = str(item.get("title", "")).strip()
            if title:
                normalized["title"] = title
        if item.get("category") is not None:
            category = str(item.get("category", "")).strip()
            if category:
                normalized["category"] = category
        return normalized

    reason = str(item.get("reason", "")).strip()
    normalized["reason"] = reason or "目标似乎已完成，建议设为过期。"
    return normalized


async def suggest_memory_updates(
    analysis_id: str,
    skater_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    analysis = await db.get(Analysis, analysis_id)
    if analysis is None or analysis.skater_id != skater_id:
        return []

    # A suggestion is a semantic artifact.  Resolve one authority once and
    # refuse Shadow/uncertain/unobservable evidence before contacting a model.
    try:
        consumer = consumer_for_analysis(analysis, "coaching")
    except (ValueError, TypeError):
        return []
    if consumer.authority != "legacy" and consumer.authority != "v2":
        return []
    if not consumer.facts:
        return []

    memories_result = await db.execute(
        select(SnowballMemory)
        .where(SnowballMemory.skater_id == skater_id)
        .order_by(SnowballMemory.updated_at.desc(), SnowballMemory.created_at.desc())
    )
    memories = list(memories_result.scalars().all())

    provider = await get_active_provider("report", db)
    raw_text = await request_text_completion(
        provider,
        temperature=0.2,
        max_tokens=800,
        messages=[
            {"role": "system", "content": MEMORY_SUGGEST_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "当前长期记忆：\n"
                    f"{_memory_text(memories)}\n\n"
                    "本次训练的已确认事实（同一 authority）：\n"
                    f"{_fact_text(consumer)}\n\n"
                    "请对比分析，输出建议数组，每条建议格式如下：\n"
                    "[\n"
                    '  {"action": "add", "title": "...", "content": "...", "category": "卡点|目标|总结|偏好|其他"},\n'
                    '  {"action": "update", "memory_id": "uuid", "new_content": "..."},\n'
                    '  {"action": "expire", "memory_id": "uuid", "reason": "目标似乎已完成，建议设为过期"}\n'
                    "]\n"
                    "若无建议则返回空数组 []。\n"
                    "最多输出 3 条建议，避免过度打扰。\n"
                    "如果本次报告只是普通一次复盘、没有稳定偏好/长期目标/反复卡点，请返回 []。"
                ),
            },
        ],
    )
    cleaned = clean_json_text(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    normalized = [item for item in (_normalize_suggestion(item) for item in parsed[:3]) if item is not None]
    await db.execute(delete(MemorySuggestion).where(MemorySuggestion.analysis_id == analysis_id))
    if not normalized:
        return []

    suggestion = MemorySuggestion(
        id=str(uuid4()),
        analysis_id=analysis_id,
        skater_id=skater_id,
        suggestions=normalized,
        is_reviewed=False,
        facts_authority=consumer.authority,
        facts_schema_version=FACTS_SCHEMA_VERSION,
        source_fact_hash=consumer.source_fact_hash,
        source_fact_revision=consumer.source_fact_revision,
        source_pipeline_fingerprint=consumer.source_pipeline_fingerprint,
        generation_fingerprint=generation_fingerprint(
            artifact_type="memory-suggestion",
            source_fact_hash=consumer.source_fact_hash,
            provider=provider.provider,
            model=provider.model_id,
            prompt_version="memory-suggestion.v2",
            extra={"analysis_id": consumer.analysis_id},
        ),
    )
    db.add(suggestion)
    await db.commit()
    return normalized
