from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, SkaterSkill, SkillNode, TrainingSession
from app.schemas import GrowthFocus, GrowthMilestoneEvent, GrowthSummaryResponse


VERIFICATION_BY_SOURCE = {
    "parent": "parent_confirmed",
    "coach": "coach_confirmed",
}


async def build_growth_summary(
    session: AsyncSession,
    skater_id: str,
    *,
    now: datetime | None = None,
    milestone_limit: int = 8,
) -> GrowthSummaryResponse:
    as_of = now or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    month_start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    lesson_count = int(
        await session.scalar(select(func.count(TrainingSession.id)).where(TrainingSession.skater_id == skater_id)) or 0
    )
    completed_filter = (Analysis.skater_id == skater_id, Analysis.status == "completed")
    completed_analysis_count = int(
        await session.scalar(select(func.count(Analysis.id)).where(*completed_filter)) or 0
    )
    current_month_analysis_count = int(
        await session.scalar(
            select(func.count(Analysis.id)).where(*completed_filter, Analysis.created_at >= month_start)
        )
        or 0
    )
    latest_analysis = (
        await session.execute(
            select(
                Analysis.id,
                Analysis.action_type,
                Analysis.action_subtype,
                Analysis.skill_category,
                Analysis.report,
            )
            .where(*completed_filter)
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .limit(1)
        )
    ).first()

    unlocked_rows = list(
        (
            await session.execute(
                select(SkaterSkill, SkillNode)
                .join(SkillNode, SkillNode.id == SkaterSkill.skill_id)
                .where(SkaterSkill.skater_id == skater_id, SkaterSkill.unlocked_at.is_not(None))
                .order_by(SkaterSkill.unlocked_at.desc(), SkaterSkill.id.desc())
            )
        ).all()
    )
    unlocked_skill_ids = [progress.skill_id for progress, _node in unlocked_rows]
    source_rows = (
        list(
            (
                await session.execute(
                    select(Analysis.id, Analysis.auto_unlocked_skill)
                    .where(
                        Analysis.skater_id == skater_id,
                        Analysis.status == "completed",
                        Analysis.auto_unlocked_skill.in_(unlocked_skill_ids),
                    )
                    .order_by(Analysis.created_at.asc(), Analysis.id.asc())
                )
            ).all()
        )
        if unlocked_skill_ids
        else []
    )
    source_analysis_ids: dict[str, list[str]] = {}
    for analysis_id, skill_id in source_rows:
        if skill_id:
            source_analysis_ids.setdefault(skill_id, []).append(analysis_id)

    milestones = [
        GrowthMilestoneEvent(
            id=f"skill-unlock:{progress.id}",
            occurred_at=progress.unlocked_at,
            title=f"{node.name} unlocked",
            note=progress.unlock_note,
            verification=VERIFICATION_BY_SOURCE.get(progress.unlocked_by or "", "system_detected"),
            source_skill_id=node.id,
            source_analysis_ids=source_analysis_ids.get(node.id, []),
        )
        for progress, node in unlocked_rows[:milestone_limit]
        if progress.unlocked_at is not None
    ]

    report = latest_analysis.report if latest_analysis and isinstance(latest_analysis.report, dict) else {}
    focus_label = str(report.get("training_focus") or "").strip()
    if not focus_label and latest_analysis is not None:
        focus_label = latest_analysis.action_subtype or latest_analysis.skill_category or latest_analysis.action_type
    focus = None
    if latest_analysis is not None and focus_label:
        focus = GrowthFocus(
            label=focus_label,
            source_analysis_id=latest_analysis.id,
            quality=str(report.get("data_quality") or "partial"),
        )

    return GrowthSummaryResponse(
        skater_id=skater_id,
        as_of=as_of,
        lesson_count=lesson_count,
        completed_analysis_count=completed_analysis_count,
        current_month_analysis_count=current_month_analysis_count,
        milestone_count=len(unlocked_rows),
        latest_analysis_id=latest_analysis.id if latest_analysis else None,
        current_focus=focus,
        metric_definitions={
            "lesson_count": "Saved training sessions.",
            "completed_analysis_count": "Video analyses with completed status.",
            "current_month_analysis_count": "Completed video analyses in the current calendar month.",
            "milestone_count": "Skill records with an unlock timestamp.",
        },
        recent_milestones=milestones,
    )
