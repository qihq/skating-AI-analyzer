from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import MonthlyChapter, Skater
from app.schemas import MonthlyChapterPatchRequest, MonthlyChapterPublic
from app.services.monthly_chapters import (
    GeneratedChapterError,
    build_chapter_facts,
    generate_chapter_text,
    latest_chapter,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/growth", tags=["growth"])

FINAL_TEXT_MAX_LEN = 2400
NARRATIVE_MAX_LEN = 1600


async def _require_skater(session: AsyncSession, skater_id: str) -> Skater:
    skater = await session.get(Skater, skater_id)
    if skater is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    return skater


async def _require_chapter(session: AsyncSession, chapter_id: str) -> MonthlyChapter:
    chapter = await session.get(MonthlyChapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="未找到该月度章节。")
    return chapter


@router.post(
    "/skaters/{skater_id}/chapters/{year_month}/facts",
    response_model=MonthlyChapterPublic,
    status_code=201,
)
async def create_chapter_facts(
    skater_id: str,
    year_month: str,
    session: AsyncSession = Depends(get_session),
) -> MonthlyChapterPublic:
    await _require_skater(session, skater_id)
    try:
        chapter = await build_chapter_facts(session, skater_id, year_month)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MonthlyChapterPublic.model_validate(chapter)


@router.post(
    "/chapters/{chapter_id}/generate",
    response_model=MonthlyChapterPublic,
)
async def generate_chapter(
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
) -> MonthlyChapterPublic:
    chapter = await _require_chapter(session, chapter_id)
    if chapter.status == "published":
        raise HTTPException(status_code=409, detail="已发布的章节不可重新生成，请新建修订。")

    # Re-derive the snapshot to keep generation deterministic. If sources
    # changed after facts were created, we still generate from the stored
    # snapshot so the chapter stays internally consistent.
    snapshot = chapter.fact_snapshot if isinstance(chapter.fact_snapshot, dict) else {}
    if not snapshot:
        raise HTTPException(status_code=409, detail="该章节尚无可用于生成的议题事实。")

    try:
        await generate_chapter_text(session, chapter)
    except GeneratedChapterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except RuntimeError as exc:
        # Provider not configured -> 503 actionable.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - provider transport errors
        logger.warning("Monthly chapter generation failed for %s", chapter_id, exc_info=True)
        raise HTTPException(status_code=502, detail="生成失败，事实快照已保留，请稍后重试或检查供应商配置。") from exc

    await session.commit()
    await session.refresh(chapter)
    return MonthlyChapterPublic.model_validate(chapter)


@router.get(
    "/skaters/{skater_id}/chapters",
    response_model=list[MonthlyChapterPublic],
)
async def list_chapters(
    skater_id: str,
    year_month: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[MonthlyChapterPublic]:
    await _require_skater(session, skater_id)
    stmt = select(MonthlyChapter).where(MonthlyChapter.skater_id == skater_id)
    if year_month:
        stmt = stmt.where(MonthlyChapter.year_month == year_month)
    stmt = stmt.order_by(MonthlyChapter.year_month.desc(), MonthlyChapter.revision.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [MonthlyChapterPublic.model_validate(row) for row in rows]


@router.get(
    "/chapters/{chapter_id}",
    response_model=MonthlyChapterPublic,
)
async def get_chapter(
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
) -> MonthlyChapterPublic:
    chapter = await _require_chapter(session, chapter_id)
    return MonthlyChapterPublic.model_validate(chapter)


@router.patch(
    "/chapters/{chapter_id}",
    response_model=MonthlyChapterPublic,
)
async def patch_chapter(
    chapter_id: str,
    payload: MonthlyChapterPatchRequest,
    session: AsyncSession = Depends(get_session),
) -> MonthlyChapterPublic:
    chapter = await _require_chapter(session, chapter_id)
    if chapter.status == "published":
        raise HTTPException(status_code=409, detail="已发布的章节不可修改。")

    if payload.final_text is not None:
        text = payload.final_text.strip()
        if len(text) > FINAL_TEXT_MAX_LEN:
            raise HTTPException(status_code=400, detail=f"最终文字不能超过 {FINAL_TEXT_MAX_LEN} 个字符。")
        chapter.final_text = text or None

    await session.commit()
    await session.refresh(chapter)
    return MonthlyChapterPublic.model_validate(chapter)


@router.post(
    "/chapters/{chapter_id}/publish",
    response_model=MonthlyChapterPublic,
)
async def publish_chapter(
    chapter_id: str,
    session: AsyncSession = Depends(get_session),
) -> MonthlyChapterPublic:
    chapter = await _require_chapter(session, chapter_id)
    if chapter.status == "published":
        return MonthlyChapterPublic.model_validate(chapter)

    from datetime import datetime, timezone

    final_text = (chapter.final_text or "").strip()
    if not final_text:
        draft_text = (chapter.draft_text or "").strip()
        if not draft_text:
            raise HTTPException(status_code=400, detail="发布前需要填写最终文字或生成初稿。")
        chapter.final_text = draft_text
        final_text = draft_text

    if len(final_text) > FINAL_TEXT_MAX_LEN:
        raise HTTPException(status_code=400, detail=f"最终文字不能超过 {FINAL_TEXT_MAX_LEN} 个字符。")

    chapter.status = "published"
    chapter.published_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(chapter)
    return MonthlyChapterPublic.model_validate(chapter)