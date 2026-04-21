from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, Skater, SkaterSkill, SkillNode
from app.services.skills import ensure_skater_skill_rows, refresh_skater_profile, is_unlocked


def _score_unlock_config(node: SkillNode) -> dict[str, int] | None:
    config = node.unlock_config if isinstance(node.unlock_config, dict) else {}
    score_config = config.get("score") if isinstance(config.get("score"), dict) else config
    if not isinstance(score_config, dict):
        return None

    threshold = int(score_config.get("threshold", 0))
    consecutive = max(int(score_config.get("consecutive", 1)), 1)
    return {"threshold": threshold, "consecutive": consecutive}


async def auto_update_skill_progress(analysis_id: str, db: AsyncSession) -> None:
    analysis = await db.get(Analysis, analysis_id)
    if analysis is None:
        return

    if not analysis.skill_node_id or not analysis.skater_id or analysis.force_score is None:
        return

    skater = await db.get(Skater, analysis.skater_id)
    node = await db.get(SkillNode, analysis.skill_node_id)
    if skater is None or node is None:
        return

    await ensure_skater_skill_rows(db, skater)
    row_result = await db.execute(
        select(SkaterSkill).where(SkaterSkill.skater_id == skater.id, SkaterSkill.skill_id == node.id).limit(1)
    )
    row = row_result.scalar_one_or_none()
    if row is None:
        return

    analysis.auto_unlocked_skill = None

    current_score = max(int(analysis.force_score or 0), 0)
    row.best_score = max(row.best_score or 0, current_score)

    unlock_config = _score_unlock_config(node)
    if unlock_config is None:
        await refresh_skater_profile(db, skater.id)
        return

    threshold = unlock_config["threshold"]
    consecutive = unlock_config["consecutive"]

    if current_score < threshold:
        await refresh_skater_profile(db, skater.id)
        return

    row.attempt_count = max(row.attempt_count or 0, 0) + 1

    if row.attempt_count >= consecutive:
        previously_unlocked = is_unlocked(row.status)
        row.status = "unlocked"
        row.unlocked_by = "auto"
        row.unlocked_at = row.unlocked_at or datetime.now(timezone.utc)
        if not previously_unlocked:
            analysis.auto_unlocked_skill = node.id
    elif row.status == "locked":
        row.status = "attempting"

    await refresh_skater_profile(db, skater.id)
