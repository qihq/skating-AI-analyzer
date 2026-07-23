from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MonthlyChapter, Skater, SkaterSkill, SkillNode
from app.services.monthly_facts import monthly_source_hash


class AnnualCollectionValidationError(ValueError):
    """Raised when requested annual source records cannot form a safe snapshot."""


def annual_source_hash(snapshot: dict[str, Any]) -> str:
    canonical = copy.deepcopy(snapshot)
    canonical.pop("generated_at", None)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _chapter_snapshot(chapter: MonthlyChapter) -> dict[str, Any]:
    facts = chapter.fact_snapshot if isinstance(chapter.fact_snapshot, dict) else {}
    frames = chapter.representative_frames if isinstance(chapter.representative_frames, list) else []
    safe_frames = [
        {
            "analysis_id": str(frame.get("analysis_id") or ""),
            "frame_id": str(frame.get("frame_id") or ""),
            "timestamp": frame.get("timestamp"),
            "phase": str(frame.get("phase") or ""),
            "evidence_source": str(frame.get("evidence_source") or ""),
        }
        for frame in frames
        if isinstance(frame, dict) and frame.get("analysis_id") and frame.get("frame_id")
    ]
    quote_facts = [
        {
            "id": str(fact.get("id") or ""),
            "text": str(fact.get("text") or ""),
            "speaker": fact.get("speaker"),
        }
        for fact in facts.get("facts", [])
        if isinstance(fact, dict) and fact.get("kind") == "quote"
    ]
    coverage = facts.get("coverage") if isinstance(facts.get("coverage"), dict) else {}
    return {
        "id": chapter.id,
        "year_month": chapter.year_month,
        "revision": chapter.revision,
        "final_text": (chapter.final_text or "").strip(),
        "fact_source_hash": chapter.source_hash,
        "fact_schema_version": str(facts.get("schema_version") or "unknown"),
        "coverage": {
            "sessions": int(coverage.get("sessions") or 0),
            "completed_analyses": int(coverage.get("completed_analyses") or 0),
            "comparable_metrics": int(coverage.get("comparable_metrics") or 0),
        },
        "quote_facts": quote_facts,
        "representative_frames": safe_frames,
        "media_mode": "with_frames" if safe_frames else "text_only",
    }


async def build_annual_snapshot(
    session: AsyncSession,
    skater_id: str,
    year: int,
    chapter_ids: list[str],
    milestone_ids: list[str],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if year < 2000 or year > 2100:
        raise AnnualCollectionValidationError("year must be within 2000-2100")
    if not chapter_ids:
        raise AnnualCollectionValidationError("select at least one published monthly chapter")
    if len(chapter_ids) != len(set(chapter_ids)):
        raise AnnualCollectionValidationError("chapter IDs must not repeat")
    if len(milestone_ids) != len(set(milestone_ids)):
        raise AnnualCollectionValidationError("milestone IDs must not repeat")
    if await session.get(Skater, skater_id) is None:
        raise AnnualCollectionValidationError("skater does not exist")

    chapters = list(
        (
            await session.execute(select(MonthlyChapter).where(MonthlyChapter.id.in_(chapter_ids)))
        ).scalars().all()
    )
    if len(chapters) != len(chapter_ids):
        raise AnnualCollectionValidationError("one or more chapters do not exist")
    selected_chapters = {chapter.id: chapter for chapter in chapters}
    ordered_chapters: list[MonthlyChapter] = []
    for chapter_id in chapter_ids:
        chapter = selected_chapters[chapter_id]
        if chapter.skater_id != skater_id or chapter.status != "published" or not chapter.final_text:
            raise AnnualCollectionValidationError("chapters must be published by the selected skater")
        if not chapter.year_month.startswith(f"{year}-"):
            raise AnnualCollectionValidationError("chapters must belong to the selected year")
        if not isinstance(chapter.fact_snapshot, dict) or not chapter.source_hash:
            raise AnnualCollectionValidationError("chapters require immutable fact provenance")
        if monthly_source_hash(chapter.fact_snapshot) != chapter.source_hash:
            raise AnnualCollectionValidationError("chapter fact snapshot source hash does not match")
        ordered_chapters.append(chapter)
    ordered_chapters.sort(key=lambda item: (item.year_month, item.revision, item.id))

    milestone_rows = list(
        (
            await session.execute(
                select(SkaterSkill, SkillNode)
                .join(SkillNode, SkillNode.id == SkaterSkill.skill_id)
                .where(SkaterSkill.skater_id == skater_id, SkaterSkill.id.in_(milestone_ids))
            )
        ).all()
    ) if milestone_ids else []
    if len(milestone_rows) != len(milestone_ids):
        raise AnnualCollectionValidationError("one or more milestones do not belong to the selected skater")
    for progress, _node in milestone_rows:
        if progress.unlocked_at is None or progress.unlocked_at.year != year:
            raise AnnualCollectionValidationError("milestones must belong to the selected year")

    milestone_items = [
        {
            "id": progress.id,
            "skill_id": node.id,
            "title": node.name,
            "occurred_at": progress.unlocked_at.isoformat() if progress.unlocked_at else None,
            "note": progress.unlock_note,
            "verification": {"parent": "parent_confirmed", "coach": "coach_confirmed"}.get(
                progress.unlocked_by or "", "system_detected"
            ),
        }
        for progress, node in milestone_rows
        if progress.unlocked_at is not None
    ]
    milestone_items.sort(key=lambda item: (item["occurred_at"] or "", item["id"]))
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    chapter_items = [_chapter_snapshot(chapter) for chapter in ordered_chapters]
    return {
        "schema_version": "annual_collection.v1",
        "skater_id": skater_id,
        "year": year,
        "generated_at": generated_at.isoformat(),
        "chapters": chapter_items,
        "milestones": milestone_items,
        "coverage": {
            "published_chapter_count": len(chapter_items),
            "text_only_chapter_count": sum(1 for item in chapter_items if item["media_mode"] == "text_only"),
            "selected_milestone_count": len(milestone_items),
        },
        "metric_definitions": {
            "sessions": "Saved training sessions in the chapter month.",
            "completed_analyses": "Completed video analyses in the chapter month.",
            "comparable_metrics": "Metrics with compatible units and sufficient samples in the chapter month.",
        },
    }
