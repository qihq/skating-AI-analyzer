from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DATA_DIR, UPLOADS_DIR, get_session
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


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_current_streak(records: list[Analysis]) -> int:
    if not records:
        return 0

    dates = sorted({as_utc(record.created_at).date() for record in records}, reverse=True)
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
    result = await session.execute(select(Skater).order_by(Skater.is_default.desc(), Skater.created_at.asc()))
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


@router.get("/{skater_id}/archive", response_model=ArchiveResponse)
async def get_skater_archive(skater_id: str, session: AsyncSession = Depends(get_session)) -> ArchiveResponse:
    skater = await session.get(Skater, skater_id)
    if skater is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")

    result = await session.execute(
        select(Analysis, TrainingSession)
        .outerjoin(TrainingSession, Analysis.session_id == TrainingSession.id)
        .where(Analysis.skater_id == skater_id)
        .order_by(Analysis.created_at.desc())
    )
    rows = result.all()
    records = [analysis for analysis, _ in rows]

    now = datetime.now(timezone.utc)
    recent_7days = sum(1 for record in records if now - as_utc(record.created_at) <= timedelta(days=7))
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_sessions = await session.scalar(
        select(func.count(TrainingSession.id)).where(
            TrainingSession.skater_id == skater_id,
            TrainingSession.session_date >= month_start.date(),
        )
    )

    stats = ArchiveStats(
        total_records=len(records),
        recent_7days=recent_7days,
        current_streak=calculate_current_streak(records),
        monthly_sessions=int(monthly_sessions or 0),
    )

    timeline = [
        ArchiveTimelineEntry(
            id=analysis.id,
            created_at=analysis.created_at,
            status=analysis.status,
            entry_type="冰宝（IceBuddy）诊断",
            skill_category=analysis.skill_category or "未分类",
            action_type=analysis.action_type,
            force_score=analysis.force_score,
            report_snippet=build_report_snippet(analysis),
            analysis_id=analysis.id,
            session_id=analysis.session_id,
            session_date=training_session.session_date if training_session else None,
            session_location=training_session.location if training_session else None,
            session_type=training_session.session_type if training_session else None,
            session_duration_minutes=training_session.duration_minutes if training_session else None,
        )
        for analysis, training_session in rows
    ]

    return ArchiveResponse(stats=stats, timeline=timeline)


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
    return SystemInfoResponse(
        version=APP_VERSION,
        db_size_bytes=directory_size_bytes(database_path),
        uploads_size_bytes=directory_size_bytes(UPLOADS_DIR),
    )


@admin_router.get("/storage-stats", response_model=StorageStatsResponse)
async def get_storage_stats() -> StorageStatsResponse:
    return StorageStatsResponse(**build_storage_stats())


@admin_router.get("/backups", response_model=BackupListResponse)
async def get_backups() -> BackupListResponse:
    return BackupListResponse(items=list_backups())


@admin_router.post("/backups", response_model=BackupActionResponse)
async def create_backup(payload: BackupCreateRequest) -> BackupActionResponse:
    backup_path = create_manual_backup(payload.label)
    return BackupActionResponse(
        detail="备份已创建。",
        filename=backup_path.name,
    )


@admin_router.post("/backups/restore", response_model=BackupActionResponse)
async def restore_backup_route(payload: BackupRestoreRequest) -> BackupActionResponse:
    try:
        backup_path = restore_backup(payload.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return BackupActionResponse(
        detail="备份已恢复，建议刷新页面确认最新数据。",
        filename=backup_path.name,
    )
