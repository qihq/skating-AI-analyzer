from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MonthlyChapter
from app.services.monthly_facts import build_monthly_fact_snapshot, monthly_source_hash
from app.services.providers import get_active_provider, request_text_completion

logger = logging.getLogger(__name__)

PROMPT_VERSION = "monthly_chapter.v1"

FORBIDDEN_CLAIM_PHRASES = ("受伤", "恐惧", "疲劳诊断", "一定能升级", "教练确认")

# Maximum character counts enforced by the validator.
MAX_NARRATIVE_LENGTH = 1600


class GeneratedChapterError(Exception):
    """Raised when a model's response does not satisfy the chapter contract."""


async def build_chapter_facts(
    session: AsyncSession,
    skater_id: str,
    year_month: str,
    *,
    now: datetime | None = None,
) -> MonthlyChapter:
    """Create (or regenerate) a facts_ready revision for the skater/month.

    If a published revision exists, a new revision number is allocated so the
    previously published chapter remains immutable. Otherwise the most recent
    non-published revision is replaced by reusing its slot when no generation
    has happened yet.
    """
    from app.models import MonthlyChapter  # local import keeps module importable

    generated_at = now or datetime.now(timezone.utc)
    snapshot = await build_monthly_fact_snapshot(session, skater_id, year_month, now=generated_at)
    source_hash = monthly_source_hash(snapshot)

    next_revision = await _next_revision_number(session, skater_id, year_month)

    chapter = MonthlyChapter(
        skater_id=skater_id,
        year_month=year_month,
        revision=next_revision,
        status="facts_ready",
        fact_snapshot=snapshot,
        source_hash=source_hash,
        quality_flags=list(snapshot.get("quality_flags", [])),
        representative_frames=list(snapshot.get("representative_frames", [])),
    )
    session.add(chapter)
    await session.commit()
    await session.refresh(chapter)
    return chapter


async def _next_revision_number(session: AsyncSession, skater_id: str, year_month: str) -> int:
    existing = (
        await session.execute(
            select(MonthlyChapter.revision)
            .where(MonthlyChapter.skater_id == skater_id, MonthlyChapter.year_month == year_month)
            .order_by(desc(MonthlyChapter.revision))
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is None:
        return 1
    return int(existing) + 1


async def latest_chapter(session: AsyncSession, skater_id: str, year_month: str) -> MonthlyChapter | None:
    result = await session.execute(
        select(MonthlyChapter)
        .where(MonthlyChapter.skater_id == skater_id, MonthlyChapter.year_month == year_month)
        .order_by(desc(MonthlyChapter.revision))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _fact_ids(snapshot: dict[str, Any]) -> set[str]:
    return {str(fact.get("id")) for fact in snapshot.get("facts", []) if isinstance(fact, dict)}


def validate_generated_chapter(payload: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate a model-generated chapter payload against the snapshot.

    Raises GeneratedChapterError when required fields are missing, fact IDs are
    unknown, the quote text is not copied verbatim, the narrative exceeds 1600
    characters, or a forbidden claim phrase is present without a matching fact.
    """
    if not isinstance(payload, dict):
        raise GeneratedChapterError("生成结果不是 JSON 对象。")

    for required in ("title", "narrative", "highlights", "quality_note"):
        if required not in payload:
            raise GeneratedChapterError(f"缺少必需字段：{required}")

    title = str(payload.get("title") or "").strip()
    narrative = str(payload.get("narrative") or "")
    if not title:
        raise GeneratedChapterError("标题不能为空。")
    if not narrative.strip():
        raise GeneratedChapterError("叙事不能为空。")
    if len(narrative) > MAX_NARRATIVE_LENGTH:
        raise GeneratedChapterError(f"叙事长度不能超过 {MAX_NARRATIVE_LENGTH} 个字符。")

    highlights = payload.get("highlights")
    if not isinstance(highlights, list) or not highlights:
        raise GeneratedChapterError("highlights 必须为非空数组。")

    fact_ids = _fact_ids(snapshot)
    for highlight in highlights:
        if not isinstance(highlight, dict):
            raise GeneratedChapterError("highlights 条目必须是对象。")
        text = str(highlight.get("text") or "").strip()
        ids = highlight.get("fact_ids")
        if not text:
            raise GeneratedChapterError("highlight 文本不能为空。")
        if not isinstance(ids, list) or not ids:
            raise GeneratedChapterError("highlight 至少需要引用一个事实 ID。")
        for fact_id in ids:
            if str(fact_id) not in fact_ids:
                raise GeneratedChapterError(f"引用了未知事实 ID：{fact_id}")

    quote_fact_id = payload.get("quote_fact_id")
    quote_text = ""
    if quote_fact_id is not None:
        quote_text = _lookup_quote_text(snapshot, str(quote_fact_id))
        if quote_text is None:
            raise GeneratedChapterError(f"quote_fact_id 引用了未知/非金句事实：{quote_fact_id}")
        # The narrative/highlights must include the verbatim quote somewhere.
        if quote_text not in narrative and not any(
            quote_text in str(h.get("text") or "") for h in highlights if isinstance(h, dict)
        ):
            raise GeneratedChapterError("金句必须逐字写入叙事或亮点。")

    quality_note = str(payload.get("quality_note") or "")
    if len(quality_note) > 400:
        raise GeneratedChapterError("quality_note 过长。")

    # Forbidden claim phrases: allowed only when the exact phrase appears in a
    # supplied fact's text (verbatim exception granted by evidence).
    full_text = narrative + "\n" + title + "\n" + "\n".join(
        str(h.get("text") or "") for h in highlights if isinstance(h, dict)
    )
    fact_text_blob = "\n".join(
        str(fact.get("text") or "") for fact in snapshot.get("facts", []) if isinstance(fact, dict)
    )
    for phrase in FORBIDDEN_CLAIM_PHRASES:
        if phrase in full_text and phrase not in fact_text_blob:
            raise GeneratedChapterError(f"不允许的结论性表述：{phrase}")

    return payload


def _lookup_quote_text(snapshot: dict[str, Any], fact_id: str) -> str | None:
    for fact in snapshot.get("facts", []):
        if isinstance(fact, dict) and str(fact.get("id")) == fact_id and fact.get("kind") == "quote":
            return str(fact.get("text") or "")
    return None


def _chapter_system_prompt(snapshot: dict[str, Any]) -> str:
    facts = snapshot.get("facts", [])
    fact_lines = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        fact_lines.append(
            f"- id={fact.get('id')} kind={fact.get('kind')} text={fact.get('text', '')!s}"
        )
    return (
        "你是儿童花滑成长月度章节的写作助手。你只会收到一条确定性的事实快照，不能访问视频或原始数据库行。"
        "请基于事实快照生成家长可读的月度章节。要求：\n"
        "1. 所有亮点(highlights)必须引用快照中存在的事实 ID，不得编造未给出的事实。\n"
        "2. 不得推断受伤、恐惧、疲劳诊断、一定能升级或教练已确认等结论；除非事实文本中已逐字出现该表述。\n"
        "3. 金句(quote_fact_id)必须从快照中原样摘录，写入叙事或亮点。\n"
        "4. 叙事不超过 1600 字，语气温暖谨慎；当事实不足以支撑趋势结论时如实在 quality_note 中说明。\n"
        "5. 只返回 JSON，不要附加其他文字。\n"
        "事实快照：\n" + "\n".join(fact_lines)
    )


async def generate_chapter_text(
    session: AsyncSession,
    chapter: MonthlyChapter,
) -> dict[str, Any]:
    """Call the report provider to generate a chapter payload from the facts.

    On provider failure the chapter stays facts_ready and the caller raises a
    502/503 — the snapshot is never deleted.
    """
    snapshot = chapter.fact_snapshot if isinstance(chapter.fact_snapshot, dict) else {}
    messages = [
        {"role": "system", "content": _chapter_system_prompt(snapshot)},
        {
            "role": "user",
            "content": (
                "请基于上面的确定性事实快照，生成本月成长章节 JSON："
                "title(标题)、narrative(叙事)、highlights(亮点数组，每项含 text 与 fact_ids)、"
                "quote_fact_id(可选，引用的金句事实 ID)、quality_note(数据质量说明)。"
            ),
        },
    ]

    provider = await get_active_provider("report", session)
    raw = await request_text_completion(
        provider,
        messages=messages,
        temperature=0.3,
        max_tokens=1800,
        response_format={"type": "json_object"},
    )

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise GeneratedChapterError("生成结果不是合法 JSON。") from exc

    validate_generated_chapter(payload, snapshot)

    chapter.generated_payload = payload
    chapter.draft_text = _compose_draft_text(payload)
    chapter.status = "generated"
    chapter.prompt_version = PROMPT_VERSION
    chapter.provider_id = provider.id
    chapter.provider_name = provider.name
    chapter.model_id = provider.model_id
    chapter.updated_at = datetime.now(timezone.utc)
    return payload


def _compose_draft_text(payload: dict[str, Any]) -> str:
    title = str(payload.get("title") or "").strip()
    narrative = str(payload.get("narrative") or "").strip()
    highlights = payload.get("highlights") if isinstance(payload.get("highlights"), list) else []
    lines = [title, "", narrative]
    highlight_texts = [str(h.get("text") or "").strip() for h in highlights if isinstance(h, dict) and str(h.get("text") or "").strip()]
    if highlight_texts:
        lines.append("")
        lines.append("本月亮点：")
        for text in highlight_texts:
            lines.append(f"· {text}")
    quality = str(payload.get("quality_note") or "").strip()
    if quality:
        lines.append("")
        lines.append(f"说明：{quality}")
    return "\n".join(lines)