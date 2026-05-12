"""
冰宝（IceBuddy）记忆更新建议模块（独立版）。

职责：
- 分析训练报告，与现有长期记忆对比
- 提出记忆更新建议（add/update/expire）

独立版说明：原版依赖 SQLAlchemy 查询/写入 MemorySuggestion 表。
本独立版提供纯函数逻辑，不依赖数据库。
"""
from __future__ import annotations

import json
from typing import Any

from src.quality_assessment.report import clean_json_text
from src.utils.providers import get_active_provider, request_text_completion


MEMORY_SUGGEST_SYSTEM_PROMPT = (
    "你是冰宝（IceBuddy），请分析训练报告并与现有长期记忆对比，提出记忆更新建议。"
    "只输出 JSON 数组，不含任何 markdown 包裹。"
)


def _memory_text(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "暂无长期记忆。"
    lines: list[str] = []
    for memory in memories:
        status = "固定" if memory.get("is_pinned") else "普通"
        lines.append(f"- {memory.get('title', '')} | {memory.get('category', '')} | {status} | {memory.get('content', '')}")
    return "\n".join(lines)


def _issues_text(report: dict[str, Any]) -> str:
    issues = report.get("issues", [])
    if not isinstance(issues, list) or not issues:
        return "无明显问题。"
    lines: list[str] = []
    for item in issues[:5]:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip() or "未分类问题"
        description = str(item.get("description", "")).strip() or "无描述"
        lines.append(f"- {category}: {description}")
    return "\n".join(lines) or "无明显问题。"


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
        return normalized
    reason = str(item.get("reason", "")).strip()
    normalized["reason"] = reason or "目标似乎已完成，建议设为过期。"
    return normalized


async def suggest_memory_updates(
    action_type: str,
    report: dict[str, Any],
    memories: list[dict[str, Any]] | None = None,
    skater_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    独立版记忆建议：接受报告和记忆列表，返回建议数组。
    不依赖数据库。
    """
    if not report:
        return []

    provider = await get_active_provider("report")
    raw_text = await request_text_completion(
        provider, temperature=0.2, max_tokens=800,
        messages=[
            {"role": "system", "content": MEMORY_SUGGEST_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"当前长期记忆：\n{_memory_text(memories or [])}\n\n"
                f"本次训练报告：\n"
                f"- 动作类型：{action_type}\n"
                f"- 总体评价：{report.get('summary', '')}\n"
                f"- 主要问题：{_issues_text(report)}\n"
                f"- 训练重点：{report.get('training_focus', '')}\n\n"
                "请对比分析，输出建议数组，每条建议格式如下：\n"
                '[\n  {"action": "add", "title": "...", "content": "...", "category": "卡点|目标|总结|偏好|其他"},\n'
                '  {"action": "update", "memory_id": "uuid", "new_content": "..."},\n'
                '  {"action": "expire", "memory_id": "uuid", "reason": "..."}\n]\n'
                "若无建议则返回空数组 []。最多输出 3 条建议。"
            )}])

    cleaned = clean_json_text(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in (_normalize_suggestion(item) for item in parsed[:3]) if item is not None]
