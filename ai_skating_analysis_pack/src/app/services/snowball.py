from __future__ import annotations

import calendar
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import MemorySuggestion, Skater, SnowballMemory
from app.schemas import SnowballChatMessage, SnowballMemoryPublic
from app.services.providers import get_active_provider, request_text_completion


DEFAULT_MEMORIES = [
    {
        "title": "当前目标",
        "content": "华尔兹",
        "category": "目标",
        "is_pinned": True,
    },
    {
        "title": "提醒风格",
        "content": "更喜欢简洁、可执行的练习提示，而不是太长的说教。",
        "category": "偏好",
        "is_pinned": True,
    },
    {
        "title": "安全优先",
        "content": "涉及跳跃、旋转和高风险动作时，要优先提醒保护和线下教练确认。",
        "category": "总结",
        "is_pinned": True,
    },
]

SNOWBALL_SYSTEM_PROMPT = (
    "你是冰宝（IceBuddy），一只专业的花样滑冰 AI 教练助手。"
    "你的风格：简洁、可执行、鼓励性，像朋友一样直接。"
    "不说教，不废话。涉及高风险动作时优先建议线下教练确认。"
)

MEMORY_CATEGORY_FALLBACK = "其他"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_memory_text(value: str | None, fallback: str | None = None) -> str | None:
    if value is None:
        return fallback
    stripped = value.strip()
    if stripped:
        return stripped
    return fallback


def normalize_memory_category(value: str | None) -> str:
    return normalize_memory_text(value, MEMORY_CATEGORY_FALLBACK) or MEMORY_CATEGORY_FALLBACK


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def add_months(value: datetime, months: int) -> datetime:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def resolve_memory_expiration(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_datetime(value)

    normalized = value.strip().lower()
    if not normalized:
        return None
    now = utcnow()
    if normalized == "1m":
        return add_months(now, 1)
    if normalized == "3m":
        return add_months(now, 3)
    if normalized in {"never", "none", "null"}:
        return None

    try:
        if normalized.endswith("z"):
            normalized = normalized[:-1] + "+00:00"
        return _normalize_datetime(datetime.fromisoformat(normalized))
    except ValueError as exc:
        raise ValueError("expires_at 仅支持 null、'1m'、'3m' 或 ISO 时间字符串。") from exc


def is_memory_expired(memory: SnowballMemory, now: datetime | None = None) -> bool:
    if memory.expires_at is None:
        return False
    current = now or utcnow()
    expires_at = _normalize_datetime(memory.expires_at)
    return expires_at <= current


def is_memory_effectively_pinned(memory: SnowballMemory, now: datetime | None = None) -> bool:
    return bool(memory.is_pinned) and not is_memory_expired(memory, now)


def serialize_memory(memory: SnowballMemory, now: datetime | None = None) -> SnowballMemoryPublic:
    current = now or utcnow()
    expired = is_memory_expired(memory, current)
    return SnowballMemoryPublic(
        id=memory.id,
        skater_id=memory.skater_id,
        title=memory.title,
        content=memory.content,
        category=memory.category,
        is_pinned=bool(memory.is_pinned) and not expired,
        expires_at=memory.expires_at,
        is_expired=expired and bool(memory.is_pinned),
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


async def list_memories(session: AsyncSession, skater_id: str) -> list[SnowballMemory]:
    result = await session.execute(
        select(SnowballMemory)
        .where(SnowballMemory.skater_id == skater_id)
        .order_by(SnowballMemory.updated_at.desc(), SnowballMemory.created_at.desc())
    )
    memories = list(result.scalars().all())
    now = utcnow()
    return sorted(
        memories,
        key=lambda memory: (
            int(is_memory_effectively_pinned(memory, now)),
            memory.updated_at or memory.created_at,
            memory.created_at,
        ),
        reverse=True,
    )


async def create_memory(
    session: AsyncSession,
    skater_id: str,
    *,
    title: str,
    content: str,
    category: str,
    is_pinned: bool,
    expires_at: datetime | str | None = None,
) -> SnowballMemory:
    memory = SnowballMemory(
        id=str(uuid4()),
        skater_id=skater_id,
        title=normalize_memory_text(title, "") or "",
        content=normalize_memory_text(content, "") or "",
        category=normalize_memory_category(category),
        is_pinned=bool(is_pinned),
        expires_at=resolve_memory_expiration(expires_at),
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def seed_default_memories_for_skater(session: AsyncSession, skater: Skater) -> None:
    display_name = (skater.display_name or skater.name or "").strip().lower()
    if display_name not in {"坦坦", "tantan"}:
        return

    existing_result = await session.execute(select(SnowballMemory.id).where(SnowballMemory.skater_id == skater.id).limit(1))
    if existing_result.first() is not None:
        return

    for item in DEFAULT_MEMORIES:
        session.add(
            SnowballMemory(
                id=str(uuid4()),
                skater_id=skater.id,
                title=item["title"],
                content=item["content"],
                category=item["category"],
                is_pinned=item["is_pinned"],
            )
        )


async def seed_default_memories() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Skater))
        skaters = list(result.scalars().all())
        for skater in skaters:
            await seed_default_memories_for_skater(session, skater)
        await session.commit()


async def build_memory_context(skater_id: str | None, session: AsyncSession | None = None) -> str:
    if not skater_id:
        return ""

    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    try:
        now = utcnow()
        result = await session.execute(
            select(SnowballMemory)
            .where(
                SnowballMemory.skater_id == skater_id,
                SnowballMemory.is_pinned.is_(True),
                or_(SnowballMemory.expires_at.is_(None), SnowballMemory.expires_at > now),
            )
            .order_by(SnowballMemory.updated_at.desc(), SnowballMemory.created_at.desc())
        )
        memories = list(result.scalars().all())
        if not memories:
            return ""

        lines = ["---", "关于这位选手的长期背景信息："]
        lines.extend(f"[{memory.title}] {memory.content}" for memory in memories)
        lines.append("---")
        return "\n".join(lines)
    finally:
        if owns_session and session is not None:
            await session.close()


async def chat_with_snowball(
    *,
    skater_id: str | None,
    history: list[SnowballChatMessage],
    message: str,
    session: AsyncSession | None = None,
) -> str:
    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    try:
        provider = await get_active_provider("report", session)
        memory_context = await build_memory_context(skater_id, session)
        system_prompt = SNOWBALL_SYSTEM_PROMPT if not memory_context else f"{SNOWBALL_SYSTEM_PROMPT}\n\n{memory_context}"
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(
            {"role": item.role, "content": item.content.strip()}
            for item in history
            if item.role in {"user", "assistant"} and item.content.strip()
        )
        messages.append({"role": "user", "content": message.strip()})

        reply = await request_text_completion(
            provider,
            messages=messages,
            temperature=0.4,
            max_tokens=800,
        )
        return reply or "我在这儿。先告诉我你今天最想练哪一个动作。"
    finally:
        if owns_session and session is not None:
            await session.close()


async def list_pending_memory_suggestions(session: AsyncSession, skater_id: str) -> list[MemorySuggestion]:
    result = await session.execute(
        select(MemorySuggestion)
        .where(MemorySuggestion.skater_id == skater_id, MemorySuggestion.is_reviewed.is_(False))
        .order_by(MemorySuggestion.created_at.desc())
    )
    return list(result.scalars().all())
