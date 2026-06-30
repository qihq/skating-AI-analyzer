from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load

from app.database import DATA_DIR, UPLOADS_DIR, get_session, run_db_read_with_retry
from app.models import Analysis, Skater, TrainingSession
from app.schemas import (
    ArchiveResponse,
    ArchiveStats,
    ArchiveTimelineEntry,
    BackupActionResponse,
    BackupCreateRequest,
    BackupListResponse,
    BackupRestoreRequest,
    LearningPathResponse,
    SkaterPublic,
    SkaterUpdateRequest,
    SkillMutationResponse,
    SkillNodePublic,
    SkillRecentResponse,
    SkillUnlockRequest,
    StorageStatsResponse,
    SystemInfoResponse,
    TrainingSessionCreate,
    TrainingSessionDetail,
    TrainingSessionPublic,
    TrainingSessionUpdate,
)
from app.services.archive_policy import build_storage_stats, create_manual_backup, list_backups, restore_backup
from app.services.skills import build_learning_path, get_skater_skill_payloads, lock_skill, unlock_skill


router = APIRouter(prefix="/api/skaters", tags=["skaters"])
session_router = APIRouter(prefix="/api/sessions", tags=["sessions"])
system_router = APIRouter(prefix="/api/system", tags=["system"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
APP_VERSION = "0.5.0"


def skater_display_name(skater: Skater) -> str:
    return skater.display_name or skater.name


def directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(file_path.stat().st_size for file_path in path.rglob("*") if file_path.is_file())


def build_report_snippet(analysis: Analysis) -> str:
    if analysis.report and isinstance(analysis.report, dict):
        summary = str(analysis.report.get("summary", "")).strip()
        if summary:
            return summary[:120]
    if analysis.error_message:
        return f"分析失败：{analysis.error_message}"[:120]
    if analysis.note:
        return analysis.note[:120]
    return "暂无报告摘要。"


def archive_timeline_entry(
    analysis: Analysis,
    training_session: TrainingSession | None = None,
    skater: Skater | None = None,
) -> ArchiveTimelineEntry:
    return ArchiveTimelineEntry(
        id=analysis.id,
        created_at=analysis.created_at,
        status=analysis.status,
        entry_type="冰宝（IceBuddy）诊断",
        skater_id=analysis.skater_id,
        skater_name=skater_display_name(skater) if skater else None,
        skater_avatar_type=skater.avatar_type if skater else None,
        skater_avatar_emoji=skater.avatar_emoji if skater else None,
        skill_category=analysis.skill_category or "未分类",
        action_type=analysis.action_type,
        action_subtype=analysis.action_subtype,
        skill_node_id=analysis.skill_node_id,
        force_score=analysis.force_score,
        report_snippet=build_report_snippet(analysis),
        analysis_id=analysis.id,
        session_id=analysis.session_id,
        session_date=training_session.session_date if training_session else None,
        session_location=training_session.location if training_session else None,
        session_type=training_session.session_type if training_session else None,
        session_duration_minutes=training_session.duration_minutes if training_session else None,
    )


def archive_timeline_entry_from_row(row: Any) -> ArchiveTimelineEntry:
    report_snippet = str(row.note or "").strip()
    if not report_snippet:
        report_snippet = "分析进行中，请稍后查看报告。" if row.status != "completed" else "暂无训练备注。"
    return ArchiveTimelineEntry(
        id=row.id,
        created_at=row.created_at,
        status=row.status,
        entry_type="冰宝（IceBuddy）诊断",
        skater_id=row.skater_id,
        skater_name=str(row.skater_display_name or row.skater_name or "").strip() or None,
        skater_avatar_type=row.skater_avatar_type,
        skater_avatar_emoji=row.skater_avatar_emoji,
        skill_category=row.skill_category or "未分类",
        action_type=row.action_type,
        action_subtype=row.action_subtype,
        skill_node_id=None,
        force_score=row.force_score,
        report_snippet=report_snippet[:120],
        analysis_id=row.id,
        session_id=row.session_id,
        session_date=row.session_date,
        session_location=row.session_location,
        session_type=row.session_type,
        session_duration_minutes=row.session_duration_minutes,
    )


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_current_streak(records: list[Analysis]) -> int:
    return calculate_current_streak_from_datetimes([record.created_at for record in records])


def calculate_current_streak_from_datetimes(values: list[datetime]) -> int:
    return calculate_current_streak_from_dates([as_utc(value).date() for value in values])


def calculate_current_streak_from_dates(values: list[date]) -> int:
    if not values:
        return 0

    dates = sorted(set(values), reverse=True)
    today = datetime.now(timezone.utc).date()
    if dates[0] < today - timedelta(days=1):
        return 0

    streak = 1
    cursor = dates[0]
    for date_value in dates[1:]:
        if cursor - date_value == timedelta(days=1):
            streak += 1
            cursor = date_value
        else:
            break
    return streak


def normalize_archive_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return as_utc(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


async def build_archive_stats(session: AsyncSession, skater_id: str | None = None) -> ArchiveStats:
    now = datetime.now(timezone.utc)
    where_clauses: list[str] = []
    params: dict[str, object] = {"recent_cutoff": now - timedelta(days=7)}
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_sessions_query = select(func.count(TrainingSession.id)).where(
        TrainingSession.session_date >= month_start.date(),
    )
    if skater_id:
        where_clauses.append("skater_id = :skater_id")
        params["skater_id"] = skater_id
        monthly_sessions_query = monthly_sessions_query.where(TrainingSession.skater_id == skater_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    recent_where_sql = f"{where_sql} AND created_at >= :recent_cutoff" if where_sql else "WHERE created_at >= :recent_cutoff"
    total_result = await run_db_read_with_retry(
        lambda: session.execute(text(f"SELECT COUNT(*) FROM analysis_list_items {where_sql}"), params),
        context="archive_stats:total",
    )
    recent_result = await run_db_read_with_retry(
        lambda: session.execute(text(f"SELECT COUNT(*) FROM analysis_list_items {recent_where_sql}"), params),
        context="archive_stats:recent",
    )
    dates_result = await run_db_read_with_retry(
        lambda: session.execute(
            text(
                f"""
                SELECT DISTINCT date(created_at) AS archive_date
                FROM analysis_list_items
                {where_sql}
                ORDER BY archive_date DESC
                LIMIT 90
                """
            ),
            {key: value for key, value in params.items() if key == "skater_id"},
        ),
        context="archive_stats:dates",
    )
    active_dates = [
        archive_date
        for archive_date in (normalize_archive_date(value) for value in dates_result.scalars().all())
        if archive_date is not None
    ]
    return ArchiveStats(
        total_records=int(total_result.scalar_one() or 0),
        recent_7days=int(recent_result.scalar_one() or 0),
        current_streak=calculate_current_streak_from_dates(active_dates),
        monthly_sessions=int(await session.scalar(monthly_sessions_query) or 0),
    )


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def session_summary(training_session: TrainingSession) -> TrainingSessionPublic:
    return TrainingSessionPublic.model_validate(training_session)


async def build_session_detail(session: AsyncSession, training_session: TrainingSession) -> TrainingSessionDetail:
    result = await session.execute(
        select(Analysis).where(Analysis.session_id == training_session.id).order_by(Analysis.created_at.desc())
    )
    analyses = result.scalars().all()
    return TrainingSessionDetail(
        **session_summary(training_session).model_dump(),
        analyses=[
            {
                "id": analysis.id,
                "skater_id": analysis.skater_id,
                "session_id": analysis.session_id,
                "skater_name": None,
                "skill_category": analysis.skill_category,
                "action_type": analysis.action_type,
                "status": analysis.status,
                "force_score": analysis.force_score,
                "note": analysis.note,
                "created_at": analysis.created_at,
                "updated_at": analysis.updated_at,
            }
            for analysis in analyses
        ],
    )


@router.get("/", response_model=list[SkaterPublic])
async def list_skaters(session: AsyncSession = Depends(get_session)) -> list[SkaterPublic]:
    result = await run_db_read_with_retry(
        lambda: session.execute(select(Skater).order_by(Skater.is_default.desc(), Skater.created_at.asc())),
        context="list_skaters",
    )
    return list(result.scalars().all())


@router.patch("/{skater_id}", response_model=SkaterPublic)
async def update_skater(
    skater_id: str,
    payload: SkaterUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> SkaterPublic:
    skater = await session.get(Skater, skater_id)
    if skater is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")

    updates = payload.model_dump(exclude_unset=True)
    if "display_name" in updates and updates["display_name"] is not None:
        skater.display_name = updates["display_name"].strip() or skater.display_name
    if "avatar_emoji" in updates and updates["avatar_emoji"] is not None:
        skater.avatar_emoji = updates["avatar_emoji"].strip()[:4] or skater.avatar_emoji
    if "birth_year" in updates and updates["birth_year"] is not None:
        skater.birth_year = updates["birth_year"]

    await session.commit()
    await session.refresh(skater)
    return skater


@router.get("/{skater_id}/sessions", response_model=list[TrainingSessionPublic])
async def list_training_sessions(skater_id: str, session: AsyncSession = Depends(get_session)) -> list[TrainingSessionPublic]:
    if await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")

    result = await session.execute(
        select(TrainingSession)
        .where(TrainingSession.skater_id == skater_id)
        .order_by(TrainingSession.session_date.desc(), TrainingSession.created_at.desc())
    )
    return [session_summary(item) for item in result.scalars().all()]


@router.post("/{skater_id}/sessions", response_model=TrainingSessionPublic)
async def create_training_session(
    skater_id: str,
    payload: TrainingSessionCreate,
    session: AsyncSession = Depends(get_session),
) -> TrainingSessionPublic:
    if await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")

    training_session = TrainingSession(
        skater_id=skater_id,
        session_date=payload.session_date,
        location=payload.location.strip() or "冰场",
        session_type=payload.session_type.strip() or "上冰",
        duration_minutes=payload.duration_minutes,
        coach_present=payload.coach_present,
        note=normalize_optional_text(payload.note),
    )
    session.add(training_session)
    await session.commit()
    await session.refresh(training_session)
    return session_summary(training_session)


@router.get("/{skater_id}/skills", response_model=list[SkillNodePublic])
async def get_skater_skills(skater_id: str, session: AsyncSession = Depends(get_session)) -> list[SkillNodePublic]:
    if await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    payloads = await get_skater_skill_payloads(session, skater_id)
    await session.commit()
    return [SkillNodePublic(**payload) for payload in payloads]


@router.get("/{skater_id}/skills/recent", response_model=SkillRecentResponse)
async def get_recent_skills(skater_id: str, session: AsyncSession = Depends(get_session)) -> SkillRecentResponse:
    if await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    skills = await get_skater_skill_payloads(session, skater_id)
    await session.commit()
    recent = sorted(
        [skill for skill in skills if skill["unlocked_at"]],
        key=lambda item: item["unlocked_at"],
        reverse=True,
    )[:8]
    return SkillRecentResponse(items=[SkillNodePublic(**payload) for payload in recent])


@router.post("/{skater_id}/skills/{skill_id}/unlock", response_model=SkillMutationResponse)
async def unlock_skater_skill(
    skater_id: str,
    skill_id: str,
    payload: SkillUnlockRequest,
    session: AsyncSession = Depends(get_session),
) -> SkillMutationResponse:
    if await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    try:
        skill_payload = await unlock_skill(session, skater_id, skill_id, source="parent", note=payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return SkillMutationResponse(skill=SkillNodePublic(**skill_payload))


@router.post("/{skater_id}/skills/{skill_id}/lock", response_model=SkillMutationResponse)
async def lock_skater_skill(
    skater_id: str,
    skill_id: str,
    session: AsyncSession = Depends(get_session),
) -> SkillMutationResponse:
    if await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    try:
        payload = await lock_skill(session, skater_id, skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return SkillMutationResponse(skill=SkillNodePublic(**payload))


@router.get("/{skater_id}/learning-path", response_model=LearningPathResponse)
async def get_learning_path(skater_id: str, session: AsyncSession = Depends(get_session)) -> LearningPathResponse:
    if await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    payload = await build_learning_path(session, skater_id)
    await session.commit()
    return LearningPathResponse(**payload)


@router.get("/archive", response_model=ArchiveResponse)
async def get_archive(
    limit: Annotated[int, Query(ge=1, le=500)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
    skater_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> ArchiveResponse:
    skater_id = skater_id if isinstance(skater_id, str) and skater_id.strip() else None
    if skater_id and await session.get(Skater, skater_id) is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")

    where_sql = ""
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if skater_id:
        where_sql = "WHERE ali.skater_id = :skater_id"
        params["skater_id"] = skater_id

    list_query = text(
        f"""
        SELECT
            ali.analysis_id AS id,
            ali.created_at,
            ali.status,
            ali.skater_id,
            s.display_name AS skater_display_name,
            s.name AS skater_name,
            s.avatar_type AS skater_avatar_type,
            s.avatar_emoji AS skater_avatar_emoji,
            ali.skill_category,
            ali.action_type,
            ali.action_subtype,
            ali.force_score,
            ali.note,
            ali.session_id,
            ts.session_date,
            ts.location AS session_location,
            ts.session_type,
            ts.duration_minutes AS session_duration_minutes
        FROM analysis_list_items AS ali
        LEFT JOIN training_sessions AS ts ON ts.id = ali.session_id
        LEFT JOIN skaters AS s ON s.id = ali.skater_id
        {where_sql}
        ORDER BY ali.created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    count_query = text(f"SELECT COUNT(*) FROM analysis_list_items AS ali {where_sql}")

    result = await run_db_read_with_retry(
        lambda: session.execute(list_query, params),
        context="archive:list",
    )
    rows = list(result.all())
    total_result = await run_db_read_with_retry(
        lambda: session.execute(count_query, {key: value for key, value in params.items() if key == "skater_id"}),
        context="archive:count",
    )
    total_records = int(total_result.scalar_one() or 0)
    stats = await build_archive_stats(session, skater_id)

    return ArchiveResponse(
        stats=stats,
        timeline=[archive_timeline_entry_from_row(row) for row in rows],
        limit=limit,
        offset=offset,
        has_more=offset + len(rows) < total_records,
    )


@router.get("/{skater_id}/archive", response_model=ArchiveResponse)
async def get_skater_archive(
    skater_id: str,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_session),
) -> ArchiveResponse:
    skater = await session.get(Skater, skater_id)
    if skater is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")

    params: dict[str, object] = {"skater_id": skater_id, "offset": offset}
    limit_sql = ""
    if limit is not None:
        params["limit"] = limit
        limit_sql = "LIMIT :limit"

    list_query = text(
        f"""
        SELECT
            ali.analysis_id AS id,
            ali.created_at,
            ali.status,
            ali.skater_id,
            :skater_display_name AS skater_display_name,
            :skater_name AS skater_name,
            :skater_avatar_type AS skater_avatar_type,
            :skater_avatar_emoji AS skater_avatar_emoji,
            ali.skill_category,
            ali.action_type,
            ali.action_subtype,
            ali.force_score,
            ali.note,
            ali.session_id,
            ts.session_date,
            ts.location AS session_location,
            ts.session_type,
            ts.duration_minutes AS session_duration_minutes
        FROM analysis_list_items AS ali
        LEFT JOIN training_sessions AS ts ON ts.id = ali.session_id
        WHERE ali.skater_id = :skater_id
        ORDER BY ali.created_at DESC
        {limit_sql} OFFSET :offset
        """
    )
    params.update(
        {
            "skater_display_name": skater.display_name,
            "skater_name": skater.name,
            "skater_avatar_type": skater.avatar_type,
            "skater_avatar_emoji": skater.avatar_emoji,
        }
    )

    result = await run_db_read_with_retry(
        lambda: session.execute(list_query, params),
        context="skater_archive:list",
    )
    rows = list(result.all())
    count_result = await run_db_read_with_retry(
        lambda: session.execute(text("SELECT COUNT(*) FROM analysis_list_items WHERE skater_id = :skater_id"), {"skater_id": skater_id}),
        context="skater_archive:count",
    )
    total_records = int(count_result.scalar_one() or 0)

    stats = await build_archive_stats(session, skater_id)
    timeline = [archive_timeline_entry_from_row(row) for row in rows]

    return ArchiveResponse(
        stats=stats,
        timeline=timeline,
        limit=limit,
        offset=offset,
        has_more=limit is not None and offset + len(timeline) < total_records,
    )


@session_router.get("/{session_id}", response_model=TrainingSessionDetail)
async def get_training_session(session_id: str, session: AsyncSession = Depends(get_session)) -> TrainingSessionDetail:
    training_session = await session.get(TrainingSession, session_id)
    if training_session is None:
        raise HTTPException(status_code=404, detail="未找到该训练课次。")
    return await build_session_detail(session, training_session)


@session_router.patch("/{session_id}", response_model=TrainingSessionPublic)
async def update_training_session(
    session_id: str,
    payload: TrainingSessionUpdate,
    session: AsyncSession = Depends(get_session),
) -> TrainingSessionPublic:
    training_session = await session.get(TrainingSession, session_id)
    if training_session is None:
        raise HTTPException(status_code=404, detail="未找到该训练课次。")

    updates = payload.model_dump(exclude_unset=True)
    if "session_date" in updates:
        training_session.session_date = updates["session_date"]
    if "location" in updates and updates["location"] is not None:
        training_session.location = updates["location"].strip() or training_session.location
    if "session_type" in updates and updates["session_type"] is not None:
        training_session.session_type = updates["session_type"].strip() or training_session.session_type
    if "duration_minutes" in updates:
        training_session.duration_minutes = updates["duration_minutes"]
    if "coach_present" in updates:
        training_session.coach_present = bool(updates["coach_present"])
    if "note" in updates:
        training_session.note = normalize_optional_text(updates["note"])

    await session.commit()
    await session.refresh(training_session)
    return session_summary(training_session)


@session_router.delete("/{session_id}", response_model=dict[str, bool])
async def delete_training_session(session_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    training_session = await session.get(TrainingSession, session_id)
    if training_session is None:
        raise HTTPException(status_code=404, detail="未找到该训练课次。")

    result = await session.execute(select(Analysis).where(Analysis.session_id == session_id))
    for analysis in result.scalars().all():
        analysis.session_id = None

    await session.delete(training_session)
    await session.commit()
    return {"success": True}


@system_router.get("/info", response_model=SystemInfoResponse)
async def get_system_info() -> SystemInfoResponse:
    database_path = DATA_DIR / "skating-analyzer.db"
    db_size_bytes, uploads_size_bytes = await asyncio.gather(
        asyncio.to_thread(directory_size_bytes, database_path),
        asyncio.to_thread(directory_size_bytes, UPLOADS_DIR),
    )
    return SystemInfoResponse(
        version=APP_VERSION,
        db_size_bytes=db_size_bytes,
        uploads_size_bytes=uploads_size_bytes,
    )


@admin_router.get("/storage-stats", response_model=StorageStatsResponse)
async def get_storage_stats() -> StorageStatsResponse:
    return StorageStatsResponse(**await asyncio.to_thread(build_storage_stats))


@admin_router.get("/backups", response_model=BackupListResponse)
async def get_backups() -> BackupListResponse:
    return BackupListResponse(items=await asyncio.to_thread(list_backups))


@admin_router.post("/backups", response_model=BackupActionResponse)
async def create_backup(payload: BackupCreateRequest) -> BackupActionResponse:
    backup_path = await asyncio.to_thread(create_manual_backup, payload.label)
    return BackupActionResponse(
        detail="备份已创建。",
        filename=backup_path.name,
    )


@admin_router.post("/backups/restore", response_model=BackupActionResponse)
async def restore_backup_route(payload: BackupRestoreRequest) -> BackupActionResponse:
    try:
        backup_path = await asyncio.to_thread(restore_backup, payload.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return BackupActionResponse(
        detail="备份已恢复，建议刷新页面确认最新数据。",
        filename=backup_path.name,
    )
