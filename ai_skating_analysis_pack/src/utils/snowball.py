"""
冰宝（IceBuddy）长期记忆上下文构建模块（独立版）。

职责：
- 构建注入到 AI System Prompt 的长期记忆上下文
- 提供冰宝角色 System Prompt

独立版说明：原版依赖 SQLAlchemy 查询 SnowballMemory 表。
本独立版接受内存中的记忆列表，或返回空上下文。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SNOWBALL_SYSTEM_PROMPT = (
    "你是冰宝（IceBuddy），一只专业的花样滑冰 AI 教练助手。"
    "你的风格：简洁、可执行、鼓励性，像朋友一样直接。"
    "不说教，不废话。涉及高风险动作时优先建议线下教练确认。"
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def build_memory_context(skater_id: str | None, memories: list[dict[str, Any]] | None = None) -> str:
    """
    构建长期记忆上下文文本块，注入到 AI System Prompt 末尾。

    参数：
        skater_id: 选手 ID（独立版中仅用于日志标识）
        memories: 记忆列表，每项包含 title, content, is_pinned 字段。
                  若为 None，返回空字符串。

    返回：
        格式化的记忆文本块，如：
        ---
        关于这位选手的长期背景信息：
        [当前目标] 华尔兹
        [提醒风格] 更喜欢简洁、可执行的练习提示
        ---
    """
    if not memories:
        return ""

    pinned = [m for m in memories if m.get("is_pinned")]
    if not pinned:
        return ""

    lines = ["---", "关于这位选手的长期背景信息："]
    lines.extend(f"[{m.get('title', '')}] {m.get('content', '')}" for m in pinned if m.get("title"))
    lines.append("---")
    return "\n".join(lines)
