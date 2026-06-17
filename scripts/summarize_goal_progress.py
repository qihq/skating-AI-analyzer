from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


TAL_KEYS = ("T", "A", "L")
CORE_TRACKER_FLAGS = (
    "person_tracker_target_lost",
    "person_tracker_relocked",
    "person_tracker_relock_rejected",
    "person_tracker_continuity_rejected",
    "person_tracker_detector_relocked",
    "person_tracker_detector_relock_pending",
    "person_tracker_transient_loss_recovered",
    "person_tracker_final_unrecovered",
    "person_tracker_tiny_target_low_pose_tracking_risk",
    "person_tracker_multiperson_relock_instability_risk",
    "person_tracker_manual_lock_identity_rejected",
    "person_tracker_manual_lock_relock_blocked",
    "person_tracker_manual_lock_fallback_blocked",
    "person_tracker_manual_lock_support_anchor_blocked",
)
POSE_IDENTITY_LOCK_FLAGS = (
    "pose_manual_lock_unreliable_tracker_blocked",
    "semantic_pose_manual_lock_unaligned_blank_pose",
)
SEMANTIC_MANUAL_LOCK_BLANK_POSE_FLAG = "semantic_pose_manual_lock_unaligned_blank_pose"
SEMANTIC_MANUAL_LOCK_BLANK_POSE_SOURCE = "semantic_manual_lock_blank_pose"
SEMANTIC_PREFIXES = ("video_temporal_quality_retry", "semantic_keyframe")
PROFILE_DECISION_PREFIXES = ("mixed_action_profile", "mixed_action_video_ai")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _video_name(row: dict[str, Any]) -> str:
    raw = str(row.get("video") or "").strip()
    if raw:
        return Path(raw).name
    return Path(str(row.get("video_path") or "")).name


def _analysis_profile(row: dict[str, Any]) -> str:
    raw = str(row.get("analysis_profile") or "").strip().lower()
    if raw == "step_sequence":
        return "step"
    return raw or "unknown"


def _list_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item).strip())]


def _merge_lists(*values: Any) -> list[str]:
    merged: list[str] = []
    for value in values:
        for item in _list_values(value):
            if item not in merged:
                merged.append(item)
    return merged


def _parse_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _pipeline_version_tuple(value: Any) -> tuple[int, int, int]:
    text = str(value or "").strip()
    if not text.startswith("v"):
        return (0, 0, 0)
    parts = text[1:].split(".")
    if len(parts) != 3:
        return (0, 0, 0)
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return (0, 0, 0)


def _timestamp_from_keyframes(source: Any, key: str) -> float | None:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if isinstance(value, dict):
        return _safe_float(value.get("timestamp"))
    return _safe_float(value)


def _semantic_identity_lock_flags_from_cross_validation(cross_validation: Any) -> list[str]:
    if not isinstance(cross_validation, dict):
        return []
    source = str(cross_validation.get("path_b_annotation_source") or "").strip()
    return [SEMANTIC_MANUAL_LOCK_BLANK_POSE_FLAG] if source == SEMANTIC_MANUAL_LOCK_BLANK_POSE_SOURCE else []


def _pose_identity_lock_flags_from_row(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    for key in ("pose_quality_flags", "data_quality_flags"):
        values = row.get(key)
        if isinstance(values, list):
            flags.extend(str(flag) for flag in values if str(flag).strip() in POSE_IDENTITY_LOCK_FLAGS)
    flags.extend(_semantic_identity_lock_flags_from_cross_validation(row.get("cross_validation")))
    return list(dict.fromkeys(flags))


def _batch_row_to_diagnostic(row: dict[str, Any]) -> dict[str, Any]:
    keyframes = row.get("keyframes") if isinstance(row.get("keyframes"), dict) else {}
    auto_eval = row.get("auto_eval") if isinstance(row.get("auto_eval"), dict) else {}
    row_quality_flags = _list_values(row.get("quality_flags"))
    auto_eval_quality_flags = _list_values(auto_eval.get("data_quality_flags"))
    pose = row.get("pose") if isinstance(row.get("pose"), dict) else {}
    pose_quality_flags = _list_values(pose.get("quality_flags"))
    semantic_identity_lock_flags = _semantic_identity_lock_flags_from_cross_validation(row.get("cross_validation"))
    pose_identity_lock_flags = list(
        dict.fromkeys([flag for flag in pose_quality_flags if flag in POSE_IDENTITY_LOCK_FLAGS] + semantic_identity_lock_flags)
    )
    timestamps = {key: _timestamp_from_keyframes(keyframes, key) for key in TAL_KEYS}
    candidate_timestamps: dict[str, float | None] = {}
    for key in TAL_KEYS:
        evidence = keyframes.get(f"{key}_candidate_evidence")
        if isinstance(evidence, dict):
            candidate_timestamps[key] = _safe_float(evidence.get("timestamp"))
        else:
            candidate_timestamps[key] = None
    return {
        "video": _video_name(row),
        "analysis_id": row.get("analysis_id"),
        "status": row.get("status"),
        "analysis_profile": row.get("analysis_profile"),
        "force_score": row.get("force_score"),
        "pipeline_version": row.get("pipeline_version"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "profile_keyframe_summary": {
            "complete": bool(keyframes.get("profile_keyframe_complete")),
            "coverage_score": _safe_float(keyframes.get("profile_keyframe_coverage_score")),
        },
        "bio_timestamps": timestamps,
        "effective_resolved_timestamps": timestamps,
        "candidate_timestamps": candidate_timestamps,
        "bio_effective_resolved_delta": {key: 0.0 for key in TAL_KEYS if timestamps.get(key) is not None},
        "candidate_effective_resolved_delta": {},
        "trusted_candidate_effective_resolved_delta": {},
        "keyframe_candidate_flags": _list_values(keyframes.get("quality_flags")),
        "semantic_flags": row_quality_flags,
        "pose_quality_flags": pose_quality_flags,
        "data_quality_flags": _merge_lists(row_quality_flags, auto_eval_quality_flags, pose_identity_lock_flags),
        "target_quality_flags": _list_values((row.get("target") or {}).get("quality_flags") if isinstance(row.get("target"), dict) else []),
        "target_manual_review_flags": [],
        "target_auto_lock_blocked_flags": [],
        "target_tracking_risk_flags": [],
        "tracker_rejection_reason_counts": {},
    }


def _rows_from_payload(path: Path, payload: Any, *, unique: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        source_key = "unique_by_video_rows" if unique and isinstance(payload.get("unique_by_video_rows"), list) else "rows"
        if isinstance(payload.get(source_key), list):
            rows = [dict(row) for row in payload[source_key] if isinstance(row, dict)]
        elif isinstance(payload.get("videos"), list):
            rows = [_batch_row_to_diagnostic(row) for row in payload["videos"] if isinstance(row, dict)]
    elif isinstance(payload, list):
        rows = [_batch_row_to_diagnostic(row) for row in payload if isinstance(row, dict)]
    for row in rows:
        row.setdefault("_source_file", path.name)
    return rows


def _load_rows(paths: list[Path], *, unique: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_index, path in enumerate(paths):
        source_rows = _rows_from_payload(path, _read_json(path), unique=unique)
        for source_row_index, row in enumerate(source_rows):
            row["_source_index"] = source_index
            row["_source_row_index"] = source_row_index
        rows.extend(source_rows)
    return rows


def _row_status_rank(row: dict[str, Any]) -> int:
    status = str(row.get("status") or "").strip().lower()
    if status == "completed":
        return 3
    if status == "awaiting_target_selection":
        return 2
    if status in {"failed", "error"}:
        return 1
    return 0


def _row_recency_key(row: dict[str, Any]) -> tuple[float, tuple[int, int, int], int, int, int]:
    timestamp = _parse_timestamp(row.get("updated_at"))
    if timestamp is None:
        timestamp = _parse_timestamp(row.get("created_at"))
    return (
        timestamp if timestamp is not None else -1.0,
        _pipeline_version_tuple(row.get("pipeline_version")),
        _row_status_rank(row),
        int(_safe_float(row.get("_source_index")) or 0),
        int(_safe_float(row.get("_source_row_index")) or 0),
    )


def _latest_rows_by_video(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    no_video_rows: list[dict[str, Any]] = []
    for row in rows:
        video = _video_name(row)
        if not video:
            no_video_rows.append(row)
            continue
        previous = latest.get(video)
        if previous is None or _row_recency_key(row) >= _row_recency_key(previous):
            latest[video] = row
    return [*latest.values(), *no_video_rows]


def _delta_bucket(delta: float | None, threshold: float) -> str:
    if delta is None:
        return "missing"
    if delta < -threshold:
        return "early"
    if delta > threshold:
        return "late"
    return "within"


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _delta_stats(rows: list[dict[str, Any]], field: str, *, threshold: float) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for key in TAL_KEYS:
        values: list[float] = []
        direction_counts: Counter[str] = Counter()
        for row in rows:
            delta_map = row.get(field) if isinstance(row.get(field), dict) else {}
            delta = _safe_float(delta_map.get(key))
            direction_counts[_delta_bucket(delta, threshold)] += 1
            if delta is not None:
                values.append(delta)
        stats[key] = {
            "count": len(values),
            "avg_signed_sec": _average(values),
            "avg_abs_sec": _average([abs(value) for value in values]),
            "max_abs_sec": round(max((abs(value) for value in values), default=0.0), 3) if values else None,
            "direction_counts": dict(direction_counts),
        }
    return stats


def _motion_peak_stats(rows: list[dict[str, Any]], field: str) -> dict[str, float | None]:
    stats: dict[str, float | None] = {}
    for key in TAL_KEYS:
        values: list[float] = []
        for row in rows:
            delta_map = row.get(field) if isinstance(row.get(field), dict) else {}
            delta = _safe_float(delta_map.get(key))
            if delta is not None:
                values.append(abs(delta))
        stats[key] = _average(values)
    return stats


def _counter_from_rows(rows: list[dict[str, Any]], field: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(_list_values(row.get(field)))
    return counts


def _tracker_flag_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        flags = set(_list_values(row.get("target_quality_flags"))) | set(_list_values(row.get("data_quality_flags")))
        for flag in CORE_TRACKER_FLAGS:
            if flag in flags:
                counts[flag] += 1
    return {flag: counts.get(flag, 0) for flag in CORE_TRACKER_FLAGS}


def _pose_identity_lock_flag_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        flags = set(_pose_identity_lock_flags_from_row(row))
        for flag in POSE_IDENTITY_LOCK_FLAGS:
            if flag in flags:
                counts[flag] += 1
    return {flag: counts.get(flag, 0) for flag in POSE_IDENTITY_LOCK_FLAGS}


def _pose_identity_lock_samples(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in rows:
        pose_flags = _pose_identity_lock_flags_from_row(row)
        tracker_flags = [
            flag
            for flag in _list_values(row.get("target_quality_flags"))
            if flag in CORE_TRACKER_FLAGS or flag.startswith("person_tracker_manual_lock_")
        ]
        if not pose_flags and not any(flag.startswith("person_tracker_manual_lock_") for flag in tracker_flags):
            continue
        samples.append(
            {
                "video": row.get("video"),
                "analysis_id": row.get("analysis_id"),
                "status": row.get("status"),
                "analysis_profile": _analysis_profile(row),
                "pose_identity_lock_flags": pose_flags,
                "target_quality_flags": tracker_flags,
                "pose_tracked_ratio": row.get("pose_tracked_ratio"),
                "tracker_loss_ratio": row.get("tracker_loss_ratio"),
                "tracker_rejection_reason_counts": row.get("tracker_rejection_reason_counts"),
            }
        )
    return samples[:limit]


def _tracker_rejection_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        reasons = row.get("tracker_rejection_reason_counts")
        if not isinstance(reasons, dict):
            continue
        for reason, count in reasons.items():
            numeric = int(_safe_float(count) or 0)
            if numeric > 0:
                counts[str(reason)] += numeric
    return counts


def _profile_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    completed: Counter[str] = Counter()
    complete_counts: Counter[str] = Counter()
    for row in rows:
        if row.get("status") != "completed":
            continue
        profile = _analysis_profile(row)
        completed[profile] += 1
        summary = row.get("profile_keyframe_summary") if isinstance(row.get("profile_keyframe_summary"), dict) else {}
        coverage = _safe_float(summary.get("coverage_score"))
        if coverage is not None:
            values[profile].append(coverage)
        if summary.get("complete") is True:
            complete_counts[profile] += 1
    return {
        profile: {
            "completed": completed[profile],
            "average_coverage": _average(values.get(profile, [])),
            "complete_rate": round(complete_counts[profile] / completed[profile], 3) if completed[profile] else None,
        }
        for profile in sorted(completed)
    }


def _jump_samples(rows: list[dict[str, Any]], *, threshold: float, limit: int) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in rows:
        candidate_delta = row.get("candidate_effective_resolved_delta")
        candidate_delta = candidate_delta if isinstance(candidate_delta, dict) else {}
        abs_values = [abs(value) for key in TAL_KEYS if (value := _safe_float(candidate_delta.get(key))) is not None]
        max_abs = max(abs_values, default=None)
        if max_abs is None:
            continue
        samples.append(
            {
                "video": row.get("video"),
                "analysis_id": row.get("analysis_id"),
                "force_score": row.get("force_score"),
                "max_abs_candidate_final_delta_sec": round(max_abs, 3),
                "candidate_delta_status": {
                    key: _delta_bucket(_safe_float(candidate_delta.get(key)), threshold) for key in TAL_KEYS
                },
                "candidate_effective_resolved_delta": {
                    key: _safe_float(candidate_delta.get(key)) for key in TAL_KEYS
                },
                "candidate_delta_untrusted": bool(row.get("candidate_delta_untrusted")),
                "candidate_delta_untrusted_reasons": _list_values(row.get("candidate_delta_untrusted_reasons")),
                "keyframe_candidate_flags": _list_values(row.get("keyframe_candidate_flags")),
                "semantic_flags": _list_values(row.get("semantic_flags")),
                "target_tracking_risk_flags": _list_values(row.get("target_tracking_risk_flags")),
            }
        )
    return sorted(samples, key=lambda item: item["max_abs_candidate_final_delta_sec"], reverse=True)[:limit]


def _profile_stability(rows: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    by_video: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        video = _video_name(row)
        if video:
            by_video[video].append(row)

    drift_groups: list[dict[str, Any]] = []
    for video, video_rows in by_video.items():
        if len(video_rows) < 2:
            continue
        profile_counts = Counter(_analysis_profile(row) for row in video_rows)
        if len(profile_counts) <= 1:
            continue
        unstable_tal_membership = "jump" in profile_counts and any(
            profile != "jump" for profile in profile_counts
        )
        drift_groups.append(
            {
                "video": video,
                "run_count": len(video_rows),
                "profile_counts": dict(profile_counts),
                "unstable_tal_membership": unstable_tal_membership,
                "runs": [
                    {
                        "analysis_id": row.get("analysis_id"),
                        "source_file": row.get("_source_file"),
                        "analysis_profile": _analysis_profile(row),
                        "force_score": row.get("force_score"),
                    }
                    for row in video_rows
                ],
            }
        )

    drift_groups.sort(
        key=lambda item: (
            bool(item.get("unstable_tal_membership")),
            item.get("run_count") or 0,
            item.get("video") or "",
        ),
        reverse=True,
    )
    return {
        "profile_drift_group_count": len(drift_groups),
        "unstable_tal_membership_count": sum(
            1 for group in drift_groups if group.get("unstable_tal_membership")
        ),
        "profile_drift_samples": drift_groups[:limit],
    }


def _compare_url(analysis_id_a: Any, analysis_id_b: Any, frontend_url: str) -> str | None:
    id_a = str(analysis_id_a or "").strip()
    id_b = str(analysis_id_b or "").strip()
    if not id_a or not id_b:
        return None
    return f"{frontend_url.rstrip('/')}/compare/{id_a}/{id_b}"


def _same_profile_compare_candidates(
    rows: list[dict[str, Any]],
    *,
    frontend_url: str,
    limit_per_profile: int,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("status") != "completed":
            continue
        if not str(row.get("analysis_id") or "").strip():
            continue
        by_profile[_analysis_profile(row)].append(row)

    candidates: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for profile, profile_rows in sorted(by_profile.items()):
        profile_rows = sorted(profile_rows, key=lambda item: str(item.get("video") or ""))
        pairs: list[dict[str, Any]] = []
        for left_index in range(len(profile_rows)):
            for right_index in range(left_index + 1, len(profile_rows)):
                left = profile_rows[left_index]
                right = profile_rows[right_index]
                left_score = _safe_float(left.get("force_score"))
                right_score = _safe_float(right.get("force_score"))
                left_summary = left.get("profile_keyframe_summary") if isinstance(left.get("profile_keyframe_summary"), dict) else {}
                right_summary = right.get("profile_keyframe_summary") if isinstance(right.get("profile_keyframe_summary"), dict) else {}
                left_coverage = _safe_float(left_summary.get("coverage_score"))
                right_coverage = _safe_float(right_summary.get("coverage_score"))
                pairs.append(
                    {
                        "video_a": left.get("video"),
                        "video_b": right.get("video"),
                        "analysis_id_a": left.get("analysis_id"),
                        "analysis_id_b": right.get("analysis_id"),
                        "compare_url": _compare_url(left.get("analysis_id"), right.get("analysis_id"), frontend_url),
                        "force_score_a": left_score,
                        "force_score_b": right_score,
                        "force_score_delta": (
                            round(right_score - left_score, 3)
                            if left_score is not None and right_score is not None
                            else None
                        ),
                        "profile_keyframe_coverage_a": left_coverage,
                        "profile_keyframe_coverage_b": right_coverage,
                        "profile_keyframe_coverage_delta": (
                            round(right_coverage - left_coverage, 3)
                            if left_coverage is not None and right_coverage is not None
                            else None
                        ),
                    }
                )
        largest_delta = sorted(
            pairs,
            key=lambda item: (
                abs(item.get("force_score_delta") or 0.0),
                abs(item.get("profile_keyframe_coverage_delta") or 0.0),
                str(item.get("video_a") or ""),
                str(item.get("video_b") or ""),
            ),
            reverse=True,
        )
        closest_match = sorted(
            pairs,
            key=lambda item: (
                abs(item.get("force_score_delta") or 0.0),
                abs(item.get("profile_keyframe_coverage_delta") or 0.0),
                str(item.get("video_a") or ""),
                str(item.get("video_b") or ""),
            ),
        )
        limit = max(0, int(limit_per_profile))
        candidates[profile] = {
            "largest_delta": largest_delta[:limit],
            "closest_match": closest_match[:limit],
        }
    return candidates


def summarize_goal_progress(
    paths: list[Path],
    *,
    unique: bool = False,
    latest_by_video: bool = False,
    threshold: float = 0.1,
    sample_limit: int = 12,
    frontend_url: str = "http://localhost:8080",
) -> dict[str, Any]:
    loaded_rows = _load_rows(paths, unique=unique)
    rows = _latest_rows_by_video(loaded_rows) if latest_by_video else loaded_rows
    completed = [row for row in rows if row.get("status") == "completed"]
    jump_rows = [row for row in completed if _analysis_profile(row) == "jump"]
    semantic_flags = Counter(
        flag
        for row in completed
        for flag in _list_values(row.get("semantic_flags"))
        if flag.startswith(SEMANTIC_PREFIXES)
    )
    profile_decision_flags = Counter(
        flag
        for row in completed
        for flag in _list_values(row.get("data_quality_flags"))
        if flag.startswith(PROFILE_DECISION_PREFIXES)
    )
    candidate_untrusted_reasons = Counter(
        reason
        for row in jump_rows
        for reason in _list_values(row.get("candidate_delta_untrusted_reasons"))
    )
    return {
        "input_files": [str(path) for path in paths],
        "loaded_row_count": len(loaded_rows),
        "latest_by_video": latest_by_video,
        "row_count": len(rows),
        "completed_count": len(completed),
        "status_counts": dict(Counter(str(row.get("status") or "unknown") for row in rows)),
        "profile_counts": dict(Counter(_analysis_profile(row) for row in rows)),
        "completed_profile_counts": dict(Counter(_analysis_profile(row) for row in completed)),
        "profile_keyframe_coverage": _profile_coverage(rows),
        "profile_stability": _profile_stability(completed, limit=sample_limit),
        "same_profile_compare_candidates": _same_profile_compare_candidates(
            completed,
            frontend_url=frontend_url,
            limit_per_profile=sample_limit,
        ),
        "jump_tal": {
            "row_count": len(jump_rows),
            "bio_vs_effective_resolved_delta": _delta_stats(jump_rows, "bio_effective_resolved_delta", threshold=threshold),
            "candidate_vs_effective_resolved_delta": _delta_stats(
                jump_rows,
                "candidate_effective_resolved_delta",
                threshold=threshold,
            ),
            "trusted_candidate_vs_effective_resolved_delta": _delta_stats(
                jump_rows,
                "trusted_candidate_effective_resolved_delta",
                threshold=threshold,
            ),
            "bio_to_nearest_motion_peak_abs_avg_sec": _motion_peak_stats(jump_rows, "bio_motion_peak_delta"),
            "candidate_to_nearest_motion_peak_abs_avg_sec": _motion_peak_stats(
                jump_rows,
                "candidate_motion_peak_delta",
            ),
            "resolved_to_nearest_motion_peak_abs_avg_sec": _motion_peak_stats(
                jump_rows,
                "effective_resolved_motion_peak_delta",
            ),
            "candidate_delta_untrusted_count": sum(1 for row in jump_rows if row.get("candidate_delta_untrusted")),
            "top_candidate_delta_untrusted_reasons": dict(candidate_untrusted_reasons.most_common(20)),
            "top_keyframe_candidate_flags": dict(_counter_from_rows(jump_rows, "keyframe_candidate_flags").most_common(20)),
            "top_semantic_retry_flags": dict(semantic_flags.most_common(20)),
            "top_profile_decision_flags": dict(profile_decision_flags.most_common(20)),
            "largest_candidate_offset_samples": _jump_samples(jump_rows, threshold=threshold, limit=sample_limit),
        },
        "tracking": {
            "core_tracker_flag_counts": _tracker_flag_counts(completed),
            "pose_identity_lock_flag_counts": _pose_identity_lock_flag_counts(completed),
            "pose_identity_lock_samples": _pose_identity_lock_samples(completed, limit=sample_limit),
            "top_tracker_rejection_reasons": dict(_tracker_rejection_counts(completed).most_common(20)),
            "top_target_tracking_risk_flags": dict(_counter_from_rows(completed, "target_tracking_risk_flags").most_common(20)),
            "top_target_manual_review_flags": dict(_counter_from_rows(rows, "target_manual_review_flags").most_common(20)),
            "top_target_auto_lock_blocked_flags": dict(
                _counter_from_rows(rows, "target_auto_lock_blocked_flags").most_common(20)
            ),
        },
    }


def _write_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Skating Goal Progress Summary",
        "",
        f"- Loaded rows: {summary['loaded_row_count']}",
        f"- Rows: {summary['row_count']}",
        f"- Completed: {summary['completed_count']}",
        f"- Latest by video: {summary['latest_by_video']}",
        f"- Profiles: {json.dumps(summary['completed_profile_counts'], ensure_ascii=False, sort_keys=True)}",
        "- T/A/L is evaluated only for analysis_profile=jump; non-jump rows use profile keyframe coverage.",
        "- Same-profile compare candidates link to /compare/:id_a/:id_b for manual review.",
        "",
        "## Profile Keyframe Coverage",
        "",
        json.dumps(summary["profile_keyframe_coverage"], ensure_ascii=False, indent=2),
        "",
        "## Profile Stability",
        "",
        json.dumps(summary["profile_stability"], ensure_ascii=False, indent=2),
        "",
        "## Same Profile Compare Candidates",
        "",
        json.dumps(summary["same_profile_compare_candidates"], ensure_ascii=False, indent=2),
        "",
        "## Jump T/A/L Candidate Offset",
        "",
        "Final bio/resolved timestamps are the report-facing T/A/L. Raw candidates are shown separately because low-trust candidates can be rejected or replaced by semantic/keyframe reuse.",
        "",
        "### Final Bio vs Effective Resolved",
        "",
        json.dumps(summary["jump_tal"]["bio_vs_effective_resolved_delta"], ensure_ascii=False, indent=2),
        "",
        "### Raw Candidate vs Effective Resolved",
        "",
        json.dumps(summary["jump_tal"]["candidate_vs_effective_resolved_delta"], ensure_ascii=False, indent=2),
        "",
        "### Trusted Candidate vs Effective Resolved",
        "",
        json.dumps(summary["jump_tal"]["trusted_candidate_vs_effective_resolved_delta"], ensure_ascii=False, indent=2),
        "",
        "### Motion Peak Abs Avg Delta",
        "",
        json.dumps(
            {
                "bio": summary["jump_tal"]["bio_to_nearest_motion_peak_abs_avg_sec"],
                "candidate": summary["jump_tal"]["candidate_to_nearest_motion_peak_abs_avg_sec"],
                "resolved": summary["jump_tal"]["resolved_to_nearest_motion_peak_abs_avg_sec"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Jump Candidate Untrusted Reasons",
        "",
        json.dumps(summary["jump_tal"]["top_candidate_delta_untrusted_reasons"], ensure_ascii=False, indent=2),
        "",
        "## Semantic/Retry Flags",
        "",
        json.dumps(summary["jump_tal"]["top_semantic_retry_flags"], ensure_ascii=False, indent=2),
        "",
        "## Mixed Action Profile Decision Flags",
        "",
        json.dumps(summary["jump_tal"]["top_profile_decision_flags"], ensure_ascii=False, indent=2),
        "",
        "## Tracker Flags",
        "",
        json.dumps(summary["tracking"]["core_tracker_flag_counts"], ensure_ascii=False, indent=2),
        "",
        "## Pose Identity Lock Flags",
        "",
        json.dumps(
            {
                "counts": summary["tracking"]["pose_identity_lock_flag_counts"],
                "samples": summary["tracking"]["pose_identity_lock_samples"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Target Lock Manual/Blocked Flags",
        "",
        json.dumps(
            {
                "manual_review": summary["tracking"]["top_target_manual_review_flags"],
                "auto_lock_blocked": summary["tracking"]["top_target_auto_lock_blocked_flags"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Largest Jump Candidate Offset Samples",
        "",
        json.dumps(summary["jump_tal"]["largest_candidate_offset_samples"], ensure_ascii=False, indent=2),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize current skating-analysis goal progress from batch diagnostics.")
    parser.add_argument("json_paths", nargs="+", type=Path)
    parser.add_argument("--unique", action="store_true", help="Use unique_by_video_rows when present.")
    parser.add_argument(
        "--latest-by-video",
        action="store_true",
        help="After loading rows, keep only the latest row per video using updated_at/created_at, pipeline version, and input order.",
    )
    parser.add_argument("--threshold", type=float, default=0.1, help="Delta threshold in seconds for within/early/late.")
    parser.add_argument("--sample-limit", type=int, default=12)
    parser.add_argument("--frontend-url", default="http://localhost:8080")
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()

    summary = summarize_goal_progress(
        args.json_paths,
        unique=args.unique,
        latest_by_video=args.latest_by_video,
        threshold=args.threshold,
        sample_limit=args.sample_limit,
        frontend_url=args.frontend_url,
    )
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        _write_markdown(summary, args.output_md)
    if not args.output_json and not args.output_md:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "row_count": summary["row_count"],
                    "loaded_row_count": summary["loaded_row_count"],
                    "latest_by_video": summary["latest_by_video"],
                    "completed_count": summary["completed_count"],
                    "completed_profile_counts": summary["completed_profile_counts"],
                    "output_json": str(args.output_json) if args.output_json else None,
                    "output_md": str(args.output_md) if args.output_md else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
