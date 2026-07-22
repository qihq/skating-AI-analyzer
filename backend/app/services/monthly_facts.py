from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, SkaterSkill, SkillNode, TrainingSession


MONTH_REGEX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Jump metric units used for comparable metric facts. Only metrics with a known
# unit are surfaced — unknown keys would be uninterpretable trend noise.
_METRIC_UNITS: dict[str, str] = {
    "air_time_seconds": "s",
    "estimated_height_cm": "cm",
    "takeoff_speed_mps": "m/s",
    "rotation_rps": "rps",
    "estimated_rotations": "rotations",
}

_METRIC_LABELS: dict[str, str] = {
    "air_time_seconds": "腾空时间",
    "estimated_height_cm": "估算起跳高度",
    "takeoff_speed_mps": "起跳速度",
    "rotation_rps": "旋转角速度",
    "estimated_rotations": "估算旋转圈数",
}

_QUALITY_OK = {"good", "partial"}
_VERIFICATION_BY_SOURCE = {"parent": "parent_confirmed", "coach": "coach_confirmed"}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _month_boundaries(year_month: str) -> tuple[datetime, datetime]:
    """Return inclusive start and exclusive next-month boundary in UTC."""
    parts = year_month.split("-")
    year = int(parts[0])
    month = int(parts[1])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end_year = year + (1 if month == 12 else 0)
    end_month = 1 if month == 12 else month + 1
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)
    return start, end


def _normalize_category(raw: Any) -> str:
    return str(raw or "").strip().lower() or "其他"


def _report(analysis: Analysis) -> dict[str, Any]:
    report = analysis.report
    return report if isinstance(report, dict) else {}


def _data_quality(report: dict[str, Any]) -> str:
    return str(report.get("data_quality") or "partial").strip().lower()


def _build_session_count(
    analyses: list[Analysis],
    session_by_id: dict[str, TrainingSession],
    start: datetime,
    end: datetime,
) -> tuple[int, list[str]]:
    distinct_sessions: set[str] = set()
    session_ids: list[str] = []
    for analysis in analyses:
        session_id = analysis.session_id
        if not session_id:
            continue
        session = session_by_id.get(session_id)
        if session is None:
            continue
        session_dt = _utc(session.session_date if isinstance(session.session_date, datetime) else None)
        # session_date is a DATE -> treat midnight UTC for boundary comparison.
        if isinstance(session.session_date, datetime):
            effective = _utc(session.session_date) or start
        else:
            # build datetime at midnight utc for the date
            d = session.session_date
            effective = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        if start <= effective < end:
            if session_id not in distinct_sessions:
                distinct_sessions.add(session_id)
                session_ids.append(session_id)
    return len(distinct_sessions), session_ids


def _comparable_metrics(
    analyses: list[Analysis],
) -> list[dict[str, Any]]:
    """Group jump metrics by (action_subtype, metric, unit).

    Emit a fact only when two or more records share subtype + metric + unit and
    acceptable data quality (data_quality != poor + jump_metrics_status ok).
    """
    buckets: dict[tuple[str | None, str, str], list[tuple[str, float | int]]] = {}
    for analysis in analyses:
        report = _report(analysis)
        if _data_quality(report) == "poor":
            continue
        bio = analysis.bio_data if isinstance(analysis.bio_data, dict) else {}
        metrics = bio.get("jump_metrics") if isinstance(bio, dict) else None
        status = str(bio.get("jump_metrics_status") or "").strip().lower() if isinstance(bio, dict) else ""
        if not isinstance(metrics, dict) or status not in {"ok", "valid", "good"}:
            continue
        subtype = (analysis.action_subtype or "").strip() or None
        for key, value in metrics.items():
            if key not in _METRIC_UNITS:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            bucket_key = (subtype, key, _METRIC_UNITS[key])
            buckets.setdefault(bucket_key, []).append((analysis.id, float(value)))

    facts: list[dict[str, Any]] = []
    for (subtype, metric, unit), entries in sorted(
        buckets.items(), key=lambda item: (item[0][1] or "", item[0][1] or "")
    ):
        if len(entries) < 2:
            continue
        entries_sorted = sorted(entries, key=lambda entry: entry[0])
        before = entries_sorted[0][1]
        after = entries_sorted[-1][1]
        facts.append(
            {
                "id": f"metric:{subtype or 'unknown'}:{metric}",
                "kind": "metric",
                "metric": metric,
                "label": _METRIC_LABELS.get(metric, metric),
                "unit": unit,
                "action_subtype": subtype,
                "before": before,
                "after": after,
                "sample_count": len(entries_sorted),
                "source_analysis_ids": [entry[0] for entry in entries_sorted],
            }
        )
    return facts


def _milestone_facts(
    AnalysesForUnlock: dict[str, list[str]],
    unlocked_in_month: list[tuple[SkaterSkill, SkillNode]],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for progress, node in sorted(unlocked_in_month, key=lambda item: (_utc(item[0].unlocked_at) or datetime.max.replace(tzinfo=timezone.utc)), reverse=True):
        verification = _VERIFICATION_BY_SOURCE.get(progress.unlocked_by or "", "system_detected")
        analysis_ids = AnalysesForUnlock.get(node.id, [])
        facts.append(
            {
                "id": f"milestone:{node.id}",
                "kind": "milestone",
                "text": f"{node.name}已点亮",
                "verification": verification,
                "skill_id": node.id,
                "source_analysis_ids": analysis_ids,
            }
        )
    return facts


def _recurring_facts(
    analyses: list[Analysis],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build recurring observation + training focus facts.

    A recurring observation requires the same normalized category in at least
    two reports whose data_quality != poor. Training focus follows the same
    recurrency rule.
    """
    category_counts: dict[str, list[tuple[str, datetime]]] = {}
    focus_counts: dict[str, list[tuple[str, datetime]]] = {}
    for analysis in sorted(analyses, key=lambda a: (_utc(a.created_at) or datetime.min.replace(tzinfo=timezone.utc), a.id)):
        report = _report(analysis)
        if _data_quality(report) == "poor":
            continue
        for issue in report.get("issues", []) if isinstance(report.get("issues"), list) else []:
            if not isinstance(issue, dict):
                continue
            category = _normalize_category(issue.get("category"))
            category_counts.setdefault(category, []).append((analysis.id, _utc(analysis.created_at) or datetime.min.replace(tzinfo=timezone.utc)))
        focus = str(report.get("training_focus") or "").strip()
        if focus:
            focus_counts.setdefault(focus, []).append((analysis.id, _utc(analysis.created_at) or datetime.min.replace(tzinfo=timezone.utc)))

    observation_facts: list[dict[str, Any]] = []
    for category, entries in sorted(category_counts.items()):
        if len(entries) < 2:
            continue
        observation_facts.append(
            {
                "id": f"observation:{category}",
                "kind": "observation",
                "category": category,
                "occurrence_count": len(entries),
                "source_analysis_ids": [entry[0] for entry in entries],
            }
        )

    focus_facts: list[dict[str, Any]] = []
    if len(focus_counts) >= 1:
        # Use the most recent focus that recurs across at least two nonpoor reports.
        recurring = sorted(
            ((focus, entries) for focus, entries in focus_counts.items() if len(entries) >= 2),
            key=lambda item: item[1][-1][1],
            reverse=True,
        )
        if recurring:
            focus, entries = recurring[0]
            focus_facts.append(
                {
                    "id": "training_focus",
                    "kind": "focus",
                    "category": focus,
                    "occurrence_count": len(entries),
                    "source_analysis_ids": [entry[0] for entry in entries],
                }
            )
    return observation_facts, focus_facts


def _quote_facts(analyses: list[Analysis]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for analysis in sorted(analyses, key=lambda a: (_utc(a.created_at) or datetime.min.replace(tzinfo=timezone.utc), a.id)):
        quote = (analysis.highlight_quote or "").strip()
        if not quote:
            continue
        speaker = (analysis.quote_speaker or "").strip() or None
        facts.append(
            {
                "id": f"quote:{analysis.id}",
                "kind": "quote",
                "text": quote,
                "speaker": speaker,
                "source_analysis_id": analysis.id,
            }
        )
    return facts


def _representative_frames(
    analyses: list[Analysis],
    milestone_source_analysis_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Select at most four representative frame references.

    Prefer milestone-linked analyses, then good-quality analyses. Store frame
    metadata only — never image bytes.
    """
    milestone_set = set(milestone_source_analysis_ids)
    candidates: list[tuple[int, Analysis, str, str, float]] = []
    for analysis in analyses:
        report = _report(analysis)
        quality = _data_quality(report)
        priority = 0
        if analysis.id in milestone_set:
            priority = 0
        elif quality == "good":
            priority = 1
        elif quality == "partial":
            priority = 2
        else:
            continue
        bio = analysis.bio_data if isinstance(analysis.bio_data, dict) else None
        candidates_obj = bio.get("key_frame_candidates") if bio else None
        timestamps = bio.get("key_frame_timestamps") if bio else None
        if not isinstance(candidates_obj, dict):
            continue
        # Prefer the landing phase when available, else first available.
        for phase_code in ("L", "A", "T"):
            candidate = candidates_obj.get(phase_code)
            if not isinstance(candidate, dict):
                continue
            frame_id = str(candidate.get("frame_id") or "").strip()
            if not frame_id:
                continue
            ts = timestamps.get(phase_code) if isinstance(timestamps, dict) else None
            ts_value = float(ts) if isinstance(ts, (int, float)) else 0.0
            label = {"L": "落冰", "A": "腾空", "T": "起跳"}.get(phase_code, phase_code)
            evidence = "milestone" if priority == 0 else quality
            candidates.append((priority, analysis, frame_id, label, ts_value))
            break

    candidates.sort(key=lambda item: (item[0], _utc(item[1].created_at) or datetime.min.replace(tzinfo=timezone.utc)))
    selected: list[dict[str, Any]] = []
    seen_analyses: set[str] = set()
    for _priority, analysis, frame_id, label, ts in candidates:
        if analysis.id in seen_analyses:
            continue
        seen_analyses.add(analysis.id)
        selected.append(
            {
                "analysis_id": analysis.id,
                "frame_id": frame_id,
                "timestamp": ts,
                "phase": label,
                "evidence_source": "milestone" if analysis.id in milestone_set else "quality",
            }
        )
        if len(selected) >= 4:
            break
    return selected


def _canonical_snapshot_for_hash(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(snapshot)
    payload.pop("generated_at", None)
    return payload


def monthly_source_hash(snapshot: dict[str, Any]) -> str:
    payload = _canonical_snapshot_for_hash(snapshot)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def build_monthly_fact_snapshot(
    session: AsyncSession,
    skater_id: str,
    year_month: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not MONTH_REGEX.match(year_month or ""):
        raise HTTPException(status_code=400, detail="year_month 必须为 YYYY-MM 格式。")

    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    start, end = _month_boundaries(year_month)

    # Only the columns needed — never videos, pose arrays, logs, or raw vision.
    analyses_raw = (
        await session.execute(
            select(Analysis).where(
                Analysis.skater_id == skater_id,
                Analysis.status == "completed",
                Analysis.created_at >= start,
                Analysis.created_at < end,
            )
        )
    ).scalars().all()
    analyses = list(analyses_raw)

    # Distinct sessions within the month.
    session_ids = {analysis.session_id for analysis in analyses if analysis.session_id}
    sessions_by_id: dict[str, TrainingSession] = {}
    if session_ids:
        rows = (
            await session.execute(
                select(TrainingSession).where(TrainingSession.id.in_(session_ids))
            )
        ).scalars().all()
        sessions_by_id = {row.id: row for row in rows}
    session_count, source_session_ids = _build_session_count(analyses, sessions_by_id, start, end)

    # Skill unlocks within the month.
    unlocked_raw = (
        await session.execute(
            select(SkaterSkill, SkillNode)
            .join(SkillNode, SkillNode.id == SkaterSkill.skill_id)
            .where(SkaterSkill.skater_id == skater_id, SkaterSkill.unlocked_at.is_not(None))
            .order_by(SkaterSkill.unlocked_at.desc(), SkaterSkill.id.desc())
        )
    ).all()
    unlocked_in_month: list[tuple[SkaterSkill, SkillNode]] = []
    unlock_skill_ids: list[str] = []
    for progress, node in unlocked_raw:
        unlocked_at = _utc(progress.unlocked_at)
        if unlocked_at is not None and start <= unlocked_at < end:
            unlocked_in_month.append((progress, node))
            unlock_skill_ids.append(node.id)
    source_analysis_by_skill: dict[str, list[str]] = {}
    if unlock_skill_ids:
        source_rows = (
            await session.execute(
                select(Analysis.id, Analysis.auto_unlocked_skill)
                .where(
                    Analysis.skater_id == skater_id,
                    Analysis.status == "completed",
                    Analysis.auto_unlocked_skill.in_(unlock_skill_ids),
                )
                .order_by(Analysis.created_at.asc(), Analysis.id.asc())
            )
        ).all()
        for analysis_id, skill_id in source_rows:
            if skill_id:
                source_analysis_by_skill.setdefault(skill_id, []).append(analysis_id)

    milestone_facts = _milestone_facts(
        source_analysis_by_skill,
        unlocked_in_month,
    )
    milestone_source_analysis_ids = [
        aid for fact in milestone_facts for aid in fact.get("source_analysis_ids", [])
    ]

    completed_count = len(analyses)
    metric_facts = _comparable_metrics(analyses)
    observation_facts, focus_facts = _recurring_facts(analyses)
    quote_facts = _quote_facts(analyses)

    coverage = {
        "sessions": session_count,
        "completed_analyses": completed_count,
        "comparable_metrics": len(metric_facts),
    }

    quality_flags: list[str] = []
    if metric_facts:
        # trend evidence present
        pass
    else:
        quality_flags.append("insufficient_comparable_evidence")

    # Deterministic fact ordering:
    # counts, comparable metrics, milestones, recurring observations, quotes.
    facts: list[dict[str, Any]] = []
    facts.append(
        {
            "id": "session_count",
            "kind": "count",
            "text": f"本月记录 {session_count} 次训练课次",
            "value": session_count,
        }
    )
    if completed_count > 0:
        facts.append(
            {
                "id": "completed_analysis_count",
                "kind": "count",
                "text": f"本月完成 {completed_count} 次动作分析",
                "value": completed_count,
            }
        )
    facts.extend(metric_facts)
    facts.extend(milestone_facts)
    facts.extend(observation_facts)
    facts.extend(focus_facts)
    facts.extend(quote_facts)

    representative_frames = _representative_frames(analyses, milestone_source_analysis_ids)

    source_analysis_ids = sorted({analysis.id for analysis in analyses})
    source_skill_ids = sorted({fact["skill_id"] for fact in milestone_facts if "skill_id" in fact})

    snapshot = {
        "schema_version": "monthly_facts.v1",
        "skater_id": skater_id,
        "year_month": year_month,
        "generated_at": generated_at.isoformat(),
        "coverage": coverage,
        "facts": facts,
        "source_analysis_ids": source_analysis_ids,
        "source_session_ids": sorted(source_session_ids),
        "source_skill_ids": source_skill_ids,
        "quality_flags": quality_flags,
        "representative_frames": representative_frames,
    }
    return snapshot