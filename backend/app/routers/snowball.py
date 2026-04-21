from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import MemorySuggestion, Skater, SnowballMemory
from app.schemas import (
    MemorySuggestionApplyRequest,
    MemorySuggestionPublic,
    SnowballChatRequest,
    SnowballChatResponse,
    SnowballMemoryCreate,
    SnowballMemoryPinUpdate,
    SnowballMemoryPublic,
    SnowballMemoryUpdate,
)
from app.services.snowball import (
    chat_with_snowball,
    create_memory,
    list_memories,
    list_pending_memory_suggestions,
    normalize_memory_category,
    normalize_memory_text,
    resolve_memory_expiration,
    serialize_memory,
    utcnow,
)


router = APIRouter(prefix="/api", tags=["snowball"])


async def _require_skater(session: AsyncSession, skater_id: str) -> Skater:
    skater = await session.get(Skater, skater_id)
    if skater is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    return skater


async def _require_memory(session: AsyncSession, skater_id: str, memory_id: str) -> SnowballMemory:
    memory = await session.get(SnowballMemory, memory_id)
    if memory is None or memory.skater_id != skater_id:
        raise HTTPException(status_code=404, detail="未找到这条冰宝记忆。")
    return memory


async def _require_suggestion(session: AsyncSession, skater_id: str, suggestion_id: str) -> MemorySuggestion:
    suggestion = await session.get(MemorySuggestion, suggestion_id)
    if suggestion is None or suggestion.skater_id != skater_id:
        raise HTTPException(status_code=404, detail="未找到这条记忆建议。")
    return suggestion


@router.get("/skaters/{skater_id}/memories", response_model=list[SnowballMemoryPublic])
async def get_snowball_memories(
    skater_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[SnowballMemoryPublic]:
    await _require_skater(session, skater_id)
    memories = await list_memories(session, skater_id)
    now = utcnow()
    return [serialize_memory(memory, now) for memory in memories]


@router.post("/skaters/{skater_id}/memories", response_model=SnowballMemoryPublic, status_code=status.HTTP_201_CREATED)
async def create_snowball_memory(
    skater_id: str,
    payload: SnowballMemoryCreate,
    session: AsyncSession = Depends(get_session),
) -> SnowballMemoryPublic:
    await _require_skater(session, skater_id)
    try:
        memory = await create_memory(
            session,
            skater_id,
            title=payload.title,
            content=payload.content,
            category=payload.category,
            is_pinned=payload.is_pinned,
            expires_at=payload.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_memory(memory)


@router.patch("/skaters/{skater_id}/memories/{memory_id}", response_model=SnowballMemoryPublic)
async def update_snowball_memory(
    skater_id: str,
    memory_id: str,
    payload: SnowballMemoryUpdate,
    session: AsyncSession = Depends(get_session),
) -> SnowballMemoryPublic:
    await _require_skater(session, skater_id)
    memory = await _require_memory(session, skater_id, memory_id)

    updates = payload.model_dump(exclude_unset=True)
    if "title" in updates and updates["title"] is not None:
        memory.title = normalize_memory_text(updates["title"], memory.title) or memory.title
    if "content" in updates and updates["content"] is not None:
        memory.content = normalize_memory_text(updates["content"], memory.content) or memory.content
    if "category" in updates and updates["category"] is not None:
        memory.category = normalize_memory_category(updates["category"])
    if "is_pinned" in updates and updates["is_pinned"] is not None:
        memory.is_pinned = bool(updates["is_pinned"])
    if "expires_at" in updates:
        try:
            memory.expires_at = resolve_memory_expiration(updates["expires_at"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(memory)
    return serialize_memory(memory)


@router.delete("/skaters/{skater_id}/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_snowball_memory(
    skater_id: str,
    memory_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _require_skater(session, skater_id)
    memory = await _require_memory(session, skater_id, memory_id)
    await session.delete(memory)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/skaters/{skater_id}/memories/{memory_id}/pin", response_model=SnowballMemoryPublic)
async def pin_snowball_memory(
    skater_id: str,
    memory_id: str,
    payload: SnowballMemoryPinUpdate,
    session: AsyncSession = Depends(get_session),
) -> SnowballMemoryPublic:
    await _require_skater(session, skater_id)
    memory = await _require_memory(session, skater_id, memory_id)
    memory.is_pinned = (not memory.is_pinned) if payload.is_pinned is None else bool(payload.is_pinned)
    await session.commit()
    await session.refresh(memory)
    return serialize_memory(memory)


@router.get("/skaters/{skater_id}/memory-suggestions", response_model=list[MemorySuggestionPublic])
async def get_memory_suggestions(
    skater_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[MemorySuggestionPublic]:
    await _require_skater(session, skater_id)
    return await list_pending_memory_suggestions(session, skater_id)


@router.post("/skaters/{skater_id}/memory-suggestions/apply", response_model=list[SnowballMemoryPublic])
async def apply_memory_suggestions(
    skater_id: str,
    payload: MemorySuggestionApplyRequest,
    session: AsyncSession = Depends(get_session),
) -> list[SnowballMemoryPublic]:
    await _require_skater(session, skater_id)
    suggestion = await _require_suggestion(session, skater_id, payload.suggestion_id)
    now = utcnow()
    accepted_indices = sorted({index for index in payload.accepted_indices if index >= 0})
    applied_memories: list[SnowballMemory] = []

    for index in accepted_indices:
        if index >= len(suggestion.suggestions):
            continue
        item = suggestion.suggestions[index]
        if not isinstance(item, dict):
            continue

        action = str(item.get("action", "")).strip().lower()
        if action == "add":
            memory = SnowballMemory(
                skater_id=skater_id,
                title=normalize_memory_text(str(item.get("title", "")), "") or "",
                content=normalize_memory_text(str(item.get("content", "")), "") or "",
                category=normalize_memory_category(str(item.get("category", "其他"))),
                is_pinned=True,
            )
            session.add(memory)
            applied_memories.append(memory)
            continue

        memory_id = str(item.get("memory_id", "")).strip()
        if not memory_id:
            continue
        memory = await _require_memory(session, skater_id, memory_id)

        if action == "update":
            title = normalize_memory_text(item.get("title") if isinstance(item.get("title"), str) else None, memory.title)
            category = normalize_memory_category(item.get("category") if isinstance(item.get("category"), str) else memory.category)
            new_content = normalize_memory_text(str(item.get("new_content", "")), memory.content) or memory.content
            memory.title = title or memory.title
            memory.category = category
            memory.content = new_content
            applied_memories.append(memory)
        elif action == "expire":
            memory.expires_at = now
            applied_memories.append(memory)

    suggestion.is_reviewed = True
    await session.commit()

    refreshed: list[SnowballMemoryPublic] = []
    for memory in applied_memories:
        await session.refresh(memory)
        refreshed.append(serialize_memory(memory, now))
    return refreshed


@router.patch("/skaters/{skater_id}/memory-suggestions/{suggestion_id}/dismiss", response_model=MemorySuggestionPublic)
async def dismiss_memory_suggestion(
    skater_id: str,
    suggestion_id: str,
    session: AsyncSession = Depends(get_session),
) -> MemorySuggestionPublic:
    await _require_skater(session, skater_id)
    suggestion = await _require_suggestion(session, skater_id, suggestion_id)
    suggestion.is_reviewed = True
    await session.commit()
    await session.refresh(suggestion)
    return suggestion


@router.post("/snowball/chat", response_model=SnowballChatResponse)
async def snowball_chat(
    payload: SnowballChatRequest,
    session: AsyncSession = Depends(get_session),
) -> SnowballChatResponse:
    if payload.skater_id:
        await _require_skater(session, payload.skater_id)
    reply = await chat_with_snowball(
        skater_id=payload.skater_id,
        history=payload.history,
        message=payload.message,
        session=session,
    )
    return SnowballChatResponse(reply=reply)
