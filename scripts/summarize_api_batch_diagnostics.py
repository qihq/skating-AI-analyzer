from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_OUTPUT_DIR = Path("tmp") / "api-batch-skate-analysis"
WINDOWS_1252_CONTROL_CHARS = {
    0x80: "\u20ac",
    0x82: "\u201a",
    0x83: "\u0192",
    0x84: "\u201e",
    0x85: "\u2026",
    0x86: "\u2020",
    0x87: "\u2021",
    0x88: "\u02c6",
    0x89: "\u2030",
    0x8A: "\u0160",
    0x8B: "\u2039",
    0x8C: "\u0152",
    0x8E: "\u017d",
    0x91: "\u2018",
    0x92: "\u2019",
    0x93: "\u201c",
    0x94: "\u201d",
    0x95: "\u2022",
    0x96: "\u2013",
    0x97: "\u2014",
    0x98: "\u02dc",
    0x99: "\u2122",
    0x9A: "\u0161",
    0x9B: "\u203a",
    0x9C: "\u0153",
    0x9E: "\u017e",
    0x9F: "\u0178",
}


def _windows_1252_mojibake(value: str) -> str:
    return "".join(
        WINDOWS_1252_CONTROL_CHARS.get(byte, chr(byte))
        for byte in value.encode("utf-8")
    )


def _legacy_text_aliases(*values: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in values:
        variants = (
            value,
            value.encode("utf-8").decode("latin-1"),
            _windows_1252_mojibake(value),
        )
        for variant in variants:
            if variant not in aliases:
                aliases.append(variant)
    return tuple(aliases)


CORE_TRACKER_FLAGS = {
    "person_tracker_target_lost",
    "person_tracker_transient_loss_recovered",
    "person_tracker_relocked",
    "person_tracker_relock_rejected",
    "person_tracker_continuity_rejected",
    "person_tracker_detector_relocked",
    "person_tracker_detector_relock_pending",
    "person_tracker_local_zoom_relock_attempted",
    "person_tracker_local_zoom_relock_rejected",
    "person_tracker_final_unrecovered",
    "person_tracker_tiny_target_low_pose_tracking_risk",
    "person_tracker_multiperson_relock_instability_risk",
    "person_tracker_manual_lock_identity_rejected",
    "person_tracker_manual_lock_relock_blocked",
    "person_tracker_manual_lock_fallback_blocked",
    "person_tracker_manual_lock_support_anchor_blocked",
}
POSE_IDENTITY_LOCK_FLAGS = {
    "pose_manual_lock_unreliable_tracker_blocked",
    "semantic_pose_manual_lock_unaligned_blank_pose",
}
SEMANTIC_MANUAL_LOCK_BLANK_POSE_FLAG = "semantic_pose_manual_lock_unaligned_blank_pose"
SEMANTIC_MANUAL_LOCK_BLANK_POSE_SOURCE = "semantic_manual_lock_blank_pose"
DERIVED_TARGET_TRACKING_RISK_FLAGS = {
    "person_tracker_tiny_target_low_pose_tracking_risk",
    "person_tracker_multiperson_relock_instability_risk",
}
TRACKER_HIGH_LOSS_RATIO_THRESHOLD = 0.25
TINY_TARGET_LOW_POSE_TRACKING_RISK_FLAG = "person_tracker_tiny_target_low_pose_tracking_risk"
MULTIPERSON_RELOCK_INSTABILITY_RISK_FLAG = "person_tracker_multiperson_relock_instability_risk"
MULTIPERSON_FULL_FRAME_MOTION_RISK_FLAG = "target_lock_multiperson_full_frame_motion_risk"
TINY_TARGET_RISK_MAX_AREA = 0.0035
TINY_TARGET_RISK_MAX_HEIGHT = 0.10
TINY_TARGET_RISK_MAX_POSE_TRACKED_RATIO = 0.65
TINY_TARGET_RISK_MIN_TRACKER_LOSS_RATIO = 0.35
MULTIPERSON_RELOCK_RISK_MIN_LOSS_RATIO = 0.25
MULTIPERSON_RELOCK_RISK_MAX_POSE_TRACKED_RATIO = 0.70
TERMINAL_LOSS_GRACE_FRAMES = 2
TERMINAL_LOSS_GRACE_MIN_TRACKED_FRAMES = 8
TERMINAL_LOSS_EXTENDED_GRACE_FRAMES = 4
TERMINAL_LOSS_EXTENDED_GRACE_MIN_TRACKED_FRAMES = 16
TERMINAL_LOSS_EXTENDED_GRACE_MAX_TERMINAL_RATIO = 0.125
TERMINAL_LOSS_TAIL_GRACE_FRAMES = 6
TERMINAL_LOSS_TAIL_GRACE_MIN_TRACKED_FRAMES = 12
TERMINAL_LOSS_TAIL_GRACE_MAX_TERMINAL_RATIO = 0.25
RECOVERED_TRACKER_STATES = {
    "tracked",
    "relocked",
    "detector_relocked",
    "support_anchor_recovered",
    "support_anchor_handoff_reused",
}
UNRECOVERED_TRACKER_STATES = {"lost_reused", "relock_rejected", "continuity_rejected"}
HARD_TRACKER_REJECTION_STATES = {"relock_rejected", "continuity_rejected"}
SEMANTIC_PREFIXES = ("video_temporal_quality_retry", "semantic_keyframe")
TAL_KEYS = ("T", "A", "L")
PROFILE_ALIASES = {
    "step_sequence": "step",
}
KNOWN_ANALYSIS_PROFILES = {"jump", "spin", "step", "spiral"}
PROFILE_KEYFRAME_KEYS = {
    "jump": TAL_KEYS,
    "spin": ("\u65cb\u8f6c\u5165", "\u65cb\u8f6c\u4e2d", "\u65cb\u8f6c\u51fa"),
    "spiral": ("\u5cf0\u503c",),
    "step": ("\u6b65\u6cd5\u5e8f\u5217",),
}
PROFILE_KEYFRAME_ALIASES = {
    "\u65cb\u8f6c\u5165": _legacy_text_aliases("\u65cb\u8f6c\u5165"),
    "\u65cb\u8f6c\u4e2d": _legacy_text_aliases("\u65cb\u8f6c\u4e2d"),
    "\u65cb\u8f6c\u51fa": _legacy_text_aliases("\u65cb\u8f6c\u51fa"),
    "\u5cf0\u503c": _legacy_text_aliases("\u5cf0\u503c"),
    "\u6b65\u6cd5\u5e8f\u5217": _legacy_text_aliases("\u6b65\u6cd5\u5e8f\u5217", "\u5cf0\u503c"),
}
PROFILE_PHASE_KEY_MAP = {
    "takeoff": "T",
    "air": "A",
    "landing": "L",
    "spin_entry": "\u65cb\u8f6c\u5165",
    "spin_main": "\u65cb\u8f6c\u4e2d",
    "spin_exit": "\u65cb\u8f6c\u51fa",
    "spiral_hold": "\u5cf0\u503c",
    "step_sequence": "\u6b65\u6cd5\u5e8f\u5217",
}
CONTAMINATED_CANDIDATE_FLAGS = {
    "keyframe_candidates_motion_fallback_takeoff_anchor_tail_window",
    "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
    "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "tal_candidate_motion_fallback_tail_window",
}
NON_ACTIONABLE_KEYFRAME_CANDIDATE_FLAGS = {
    "keyframe_candidates_not_applicable_for_profile",
}
CANDIDATE_DELTA_UNTRUSTED_FLAGS = CONTAMINATED_CANDIDATE_FLAGS | {
    "keyframe_candidates_tail_motion_window_reselected",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "keyframe_candidates_motion_fallback_low_visibility_weak_boundary",
    "tal_candidate_motion_fallback_low_precision",
    "tal_candidate_motion_fallback_low_visibility_weak_boundary",
    "tal_candidate_skeleton_drifted_after_takeoff",
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_takeoff_apex_gap_unreliable",
    "tal_candidate_takeoff_apex_gap_compressed",
    "tal_candidate_apex_landing_gap_unreliable",
    "tal_candidate_apex_landing_gap_compressed",
    "tal_candidate_core_gap_compressed",
    "tal_candidate_tail_motion_window_compressed_core",
    "tal_candidate_landing_geometry_weak",
    "tal_candidate_late_weak_landing",
    "tal_candidate_takeoff_geometry_weak",
    "tal_candidate_apex_geometry_weak",
    "tal_candidate_weak_geometry",
    "tal_candidate_tiny_target_weak_geometry",
    "tal_candidate_landing_geometry_absent",
    "keyframe_candidates_early_motion_window_weak_geometry",
    "tal_candidate_early_motion_window_weak_geometry",
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_unreliable_sparse_track_stitch",
}
FULL_FRAME_MOTION_PEAK_CONTAMINATION_RISK_FLAGS = {
    "target_lock_zoomed_multiperson_manual_review",
    "target_lock_zoomed_multiperson_scale_competitor_manual_review",
    "target_lock_zoomed_multiperson_background_auto_lock_allowed",
    "target_lock_zoomed_multiperson_background_auto_lock_blocked_small_moving_risk",
    "target_lock_zoomed_multiperson_background_auto_lock_blocked_large_moving_risk",
    "target_lock_zoomed_multiperson_background_auto_lock_blocked_dispersed_small_risk",
    TINY_TARGET_LOW_POSE_TRACKING_RISK_FLAG,
    MULTIPERSON_RELOCK_INSTABILITY_RISK_FLAG,
    MULTIPERSON_FULL_FRAME_MOTION_RISK_FLAG,
}
TARGET_REVIEW_REASON_FLAG_PREFIXES = (
    "target_lock_zoomed_multiperson_review_",
    "target_lock_foreground_context_review_",
)
FULL_FRAME_MOTION_PEAK_CONTAMINATION_MIN_OFFSET_SEC = 0.75
FULL_FRAME_MOTION_PEAK_CONTAMINATION_MIN_SCORE = 0.12
FULL_FRAME_MOTION_PEAK_CONTAMINATION_MIN_PEAK_RATIO = 2.5
FULL_FRAME_MOTION_PEAK_CONTAMINATION_CORE_TOLERANCE_SEC = 0.12


def _safe_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric and numeric not in {float("inf"), float("-inf")} else None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _get_json(base_url: str, path: str, *, timeout: float) -> dict[str, Any]:
    request = Request(f"{base_url.rstrip('/')}{path}", headers={"X-Parent-Request": "true"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _batch_items(paths: list[Path]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        payload = _read_json(path)
        if isinstance(payload.get("rows"), list) and not isinstance(payload.get("videos"), list):
            for row in payload["rows"]:
                if not isinstance(row, dict):
                    continue
                key = (str(row.get("analysis_id") or ""), str(row.get("video") or ""))
                if key in seen:
                    continue
                seen.add(key)
                merged = dict(row)
                merged.setdefault("batch_file", path.name)
                merged["_batch_file"] = str(merged.get("batch_file") or path.name)
                merged["_precomputed_diagnostics"] = True
                items.append(merged)
            continue
        for item in payload.get("videos", []) if isinstance(payload.get("videos"), list) else []:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("analysis_id") or ""), str(item.get("video") or ""))
            if key in seen:
                continue
            seen.add(key)
            merged = dict(item)
            merged["_batch_file"] = path.name
            if any(isinstance(merged.get(key), dict) for key in ("keyframes", "target", "pose", "video_temporal")):
                merged["_precomputed_diagnostics"] = True
            items.append(merged)
    return items


def _flags(*sources: Any) -> list[str]:
    out: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        raw = source.get("quality_flags")
        if not isinstance(raw, list):
            continue
        for value in raw:
            text = str(value).strip()
            if text and text not in out:
                out.append(text)
    return out


def _semantic_flags(analysis: dict[str, Any]) -> list[str]:
    bio = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    candidates = bio.get("key_frame_candidates") if isinstance(bio.get("key_frame_candidates"), dict) else {}
    vt = analysis.get("video_temporal_diagnostics") if isinstance(analysis.get("video_temporal_diagnostics"), dict) else {}
    resolved = _resolved_keyframes(analysis)
    values = _flags(candidates, vt, resolved)
    retry_flags = vt.get("retry_rejection_flags") if isinstance(vt.get("retry_rejection_flags"), list) else []
    values.extend(str(flag) for flag in retry_flags if str(flag).strip())
    return list(dict.fromkeys(flag for flag in values if flag.startswith(SEMANTIC_PREFIXES)))


def _semantic_candidate_conflict_summary(analysis: dict[str, Any]) -> dict[str, Any] | None:
    resolved = _resolved_keyframes(analysis)
    conflict = resolved.get("semantic_candidate_tal_conflict")
    if not isinstance(conflict, dict):
        return None
    motion_window_conflict = (
        conflict.get("motion_window_conflict")
        if isinstance(conflict.get("motion_window_conflict"), dict)
        else {}
    )
    evidence = conflict.get("candidate_conflict_evidence")
    if not isinstance(evidence, dict):
        evidence = motion_window_conflict.get("candidate_conflict_evidence") if isinstance(motion_window_conflict, dict) else None
    evidence = evidence if isinstance(evidence, dict) else {}
    motion_context = evidence.get("motion_context") if isinstance(evidence.get("motion_context"), dict) else {}
    labels = motion_context.get("diagnostic_labels") if isinstance(motion_context.get("diagnostic_labels"), list) else []
    semantic_window = motion_context.get("semantic_window") if isinstance(motion_context.get("semantic_window"), dict) else {}
    candidate_window = motion_context.get("candidate_window") if isinstance(motion_context.get("candidate_window"), dict) else {}
    return {
        "decision": conflict.get("decision"),
        "takeoff_anchor_core_conflict": bool(conflict.get("takeoff_anchor_core_conflict")),
        "conflict_keys": evidence.get("conflict_keys") if isinstance(evidence.get("conflict_keys"), list) else [],
        "diagnostic_labels": [str(label) for label in labels if str(label).strip()],
        "untrusted_candidate_reasons": (
            [str(reason) for reason in evidence.get("untrusted_candidate_reasons") if str(reason).strip()]
            if isinstance(evidence.get("untrusted_candidate_reasons"), list)
            else []
        ),
        "anchor_deltas_sec": evidence.get("anchor_deltas_sec") if isinstance(evidence.get("anchor_deltas_sec"), dict) else {},
        "candidate_span_sec": evidence.get("candidate_span_sec"),
        "semantic_span_sec": evidence.get("semantic_span_sec"),
        "global_peak_timestamp": motion_context.get("global_peak_timestamp"),
        "global_peak_motion_score": motion_context.get("global_peak_motion_score"),
        "semantic_peak_ratio": semantic_window.get("peak_ratio"),
        "candidate_peak_ratio": candidate_window.get("peak_ratio"),
        "motion_window_conflict_decision": (
            conflict.get("decision")
            if isinstance(motion_window_conflict, dict) and motion_window_conflict
            else None
        ),
    }


def _tracker_flags(analysis: dict[str, Any]) -> list[str]:
    target_lock = analysis.get("target_lock") if isinstance(analysis.get("target_lock"), dict) else {}
    return [flag for flag in _flags(target_lock) if flag.startswith("person_tracker_") or flag.startswith("target_lock_")]


def _data_quality_flags(analysis: dict[str, Any]) -> list[str]:
    bio = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    auto_eval = analysis.get("auto_eval") if isinstance(analysis.get("auto_eval"), dict) else {}
    values = _flags(analysis, bio)
    raw_auto_eval = auto_eval.get("data_quality_flags")
    if isinstance(raw_auto_eval, list):
        values.extend(str(flag).strip() for flag in raw_auto_eval if str(flag).strip())
    return list(dict.fromkeys(values))


def _pose_quality_flags(analysis: dict[str, Any]) -> list[str]:
    pose = analysis.get("pose_data") if isinstance(analysis.get("pose_data"), dict) else {}
    return _flags(pose)


def _cross_validation(analysis: dict[str, Any]) -> dict[str, Any]:
    return analysis.get("cross_validation") if isinstance(analysis.get("cross_validation"), dict) else {}


def _semantic_identity_lock_flags_from_cross_validation(cross_validation: dict[str, Any]) -> list[str]:
    source = str(cross_validation.get("path_b_annotation_source") or "").strip()
    return [SEMANTIC_MANUAL_LOCK_BLANK_POSE_FLAG] if source == SEMANTIC_MANUAL_LOCK_BLANK_POSE_SOURCE else []


def _semantic_identity_lock_flags(analysis: dict[str, Any]) -> list[str]:
    return _semantic_identity_lock_flags_from_cross_validation(_cross_validation(analysis))


def _pose_identity_lock_flags_from_row_values(*values: Any) -> list[str]:
    flags: list[str] = []
    for value in values:
        if not isinstance(value, list):
            continue
        flags.extend(str(flag) for flag in value if str(flag).strip() in POSE_IDENTITY_LOCK_FLAGS)
    return list(dict.fromkeys(flags))


def _state_counts(items: Any, key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                counts[str(item.get(key) or "unknown")] += 1
    return dict(counts)


def _is_unrecovered_tracker_state(state: str) -> bool:
    return state in UNRECOVERED_TRACKER_STATES or state.endswith("_relock_pending") or state == "relock_pending"


def _terminal_loss_graced(
    *,
    raw_final_unrecovered: bool,
    terminal_loss_frames: int,
    tracked_frames: int,
    total_frames: int,
) -> bool:
    if (
        not raw_final_unrecovered
        or terminal_loss_frames <= 0
        or tracked_frames < TERMINAL_LOSS_GRACE_MIN_TRACKED_FRAMES
    ):
        return False
    if terminal_loss_frames <= TERMINAL_LOSS_GRACE_FRAMES:
        return True
    terminal_ratio = terminal_loss_frames / max(total_frames, 1)
    if (
        terminal_loss_frames <= TERMINAL_LOSS_EXTENDED_GRACE_FRAMES
        and tracked_frames >= TERMINAL_LOSS_EXTENDED_GRACE_MIN_TRACKED_FRAMES
        and terminal_ratio <= TERMINAL_LOSS_EXTENDED_GRACE_MAX_TERMINAL_RATIO
    ):
        return True
    return (
        terminal_loss_frames <= TERMINAL_LOSS_TAIL_GRACE_FRAMES
        and tracked_frames >= TERMINAL_LOSS_TAIL_GRACE_MIN_TRACKED_FRAMES
        and terminal_ratio <= TERMINAL_LOSS_TAIL_GRACE_MAX_TERMINAL_RATIO
    )


def _tracker_sequence_summary(diagnostics: Any) -> dict[str, Any]:
    if not isinstance(diagnostics, list) or not diagnostics:
        return {}
    counts = _state_counts(diagnostics, "state")
    loss_frames = sum(count for state, count in counts.items() if _is_unrecovered_tracker_state(state))
    recovered_frames = sum(count for state, count in counts.items() if state in RECOVERED_TRACKER_STATES)
    last = diagnostics[-1] if isinstance(diagnostics[-1], dict) else {}
    final_state = str((last or {}).get("state") or "unknown")
    raw_final_unrecovered = _is_unrecovered_tracker_state(final_state)
    terminal_loss_frames = 0
    for item in reversed(diagnostics):
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "unknown")
        if _is_unrecovered_tracker_state(state):
            terminal_loss_frames += 1
            continue
        break
    tracked_frames = sum(count for state, count in counts.items() if state in RECOVERED_TRACKER_STATES)
    terminal_loss_graced = _terminal_loss_graced(
        raw_final_unrecovered=raw_final_unrecovered,
        terminal_loss_frames=terminal_loss_frames,
        tracked_frames=tracked_frames,
        total_frames=len(diagnostics),
    )
    final_unrecovered = raw_final_unrecovered and not terminal_loss_graced
    transient_loss_recovered = (
        loss_frames > 0
        and (
            counts.get("relocked", 0) > 0
            or counts.get("detector_relocked", 0) > 0
            or counts.get("support_anchor_recovered", 0) > 0
        )
        and not final_unrecovered
    )
    return {
        "state_counts": counts,
        "loss_frames": loss_frames,
        "recovered_frames": recovered_frames,
        "tracked_frames": tracked_frames,
        "total_frames": len(diagnostics),
        "final_state": final_state,
        "terminal_loss_frames": terminal_loss_frames,
        "terminal_loss_graced": terminal_loss_graced,
        "final_unrecovered": final_unrecovered,
        "transient_loss_recovered": transient_loss_recovered,
    }


def _renormalize_cached_tracker_sequence(row: dict[str, Any]) -> None:
    summary = row.get("tracker_sequence_summary") if isinstance(row.get("tracker_sequence_summary"), dict) else {}
    counts = summary.get("state_counts") if isinstance(summary.get("state_counts"), dict) else {}
    if not counts and isinstance(row.get("tracker_state_counts"), dict):
        counts = row["tracker_state_counts"]

    flags = [
        str(flag)
        for flag in row.get("target_quality_flags", [])
        if str(flag).strip()
    ] if isinstance(row.get("target_quality_flags"), list) else []
    if not summary and not counts:
        row["tracker_final_unrecovered"] = "person_tracker_final_unrecovered" in flags
        row["tracker_transient_loss_recovered"] = (
            "person_tracker_transient_loss_recovered" in flags
            and not row["tracker_final_unrecovered"]
        )
        row["target_quality_flags"] = list(dict.fromkeys(flags))
        return

    final_state = str(summary.get("final_state") or "")
    raw_final_unrecovered = (
        _is_unrecovered_tracker_state(final_state)
        if final_state
        else bool(summary.get("final_unrecovered") or "person_tracker_final_unrecovered" in flags)
    )
    terminal_loss_frames = int(_safe_float(summary.get("terminal_loss_frames")) or 0)
    cached_tracked_frames = int(_safe_float(summary.get("tracked_frames")) or 0)
    counted_tracked_frames = sum(int(count or 0) for state, count in counts.items() if state in RECOVERED_TRACKER_STATES)
    tracked_frames = max(cached_tracked_frames, counted_tracked_frames)
    total_frames = int(
        _safe_float(summary.get("total_frames"))
        or _safe_float(row.get("tracker_total_frames"))
        or sum(int(count or 0) for count in counts.values())
    )
    loss_frames = _safe_float(summary.get("loss_frames"))
    if loss_frames is None and counts:
        loss_frames = float(sum(int(count or 0) for state, count in counts.items() if _is_unrecovered_tracker_state(str(state))))
    recovered_frames = int(
        max(
            _safe_float(summary.get("recovered_frames")) or 0.0,
            int(counts.get("relocked", 0) or 0)
            + int(counts.get("detector_relocked", 0) or 0)
            + int(counts.get("support_anchor_recovered", 0) or 0)
            + int(counts.get("support_anchor_handoff_reused", 0) or 0),
        )
    )

    terminal_loss_graced = _terminal_loss_graced(
        raw_final_unrecovered=raw_final_unrecovered,
        terminal_loss_frames=terminal_loss_frames,
        tracked_frames=tracked_frames,
        total_frames=total_frames,
    )
    final_unrecovered = raw_final_unrecovered and not terminal_loss_graced
    transient_loss_recovered = bool(
        not final_unrecovered
        and (
            (loss_frames and loss_frames > 0 and recovered_frames > 0)
            or "person_tracker_transient_loss_recovered" in flags
        )
    )

    updated = dict(summary)
    updated.update(
        {
            "state_counts": counts,
            "terminal_loss_graced": terminal_loss_graced,
            "final_unrecovered": final_unrecovered,
            "transient_loss_recovered": transient_loss_recovered,
            "recovered_frames": recovered_frames,
        }
    )
    if tracked_frames:
        updated["tracked_frames"] = tracked_frames
    if total_frames:
        updated["total_frames"] = total_frames
    if loss_frames is not None:
        updated["loss_frames"] = loss_frames
    row["tracker_sequence_summary"] = updated
    row["tracker_final_unrecovered"] = final_unrecovered
    row["tracker_transient_loss_recovered"] = transient_loss_recovered

    if loss_frames is not None:
        row["tracker_loss_frames"] = loss_frames
    if total_frames:
        row["tracker_total_frames"] = float(total_frames)
        if loss_frames is not None:
            row["tracker_loss_ratio"] = round(float(loss_frames) / float(total_frames), 4)

    flags = [
        flag
        for flag in flags
        if flag not in {"person_tracker_final_unrecovered", "person_tracker_transient_loss_recovered"}
    ]
    if final_unrecovered:
        flags.append("person_tracker_final_unrecovered")
    if transient_loss_recovered:
        flags.append("person_tracker_transient_loss_recovered")
    row["target_quality_flags"] = list(dict.fromkeys(flags))


def _tracker_rejection_reason_counts(diagnostics: Any) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if not isinstance(diagnostics, list):
        return {}
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        counted_candidate_reasons = False
        rejected_candidates = item.get("rejected_candidates")
        if isinstance(rejected_candidates, list):
            for candidate in rejected_candidates:
                if not isinstance(candidate, dict):
                    continue
                reasons = candidate.get("reasons")
                if not isinstance(reasons, list):
                    continue
                for reason in reasons:
                    text = str(reason).strip()
                    if text:
                        counts[text] += 1
                        counted_candidate_reasons = True
        if counted_candidate_reasons:
            continue
        rejected_reasons = item.get("rejected_reasons")
        if not isinstance(rejected_reasons, list):
            continue
        for reason in rejected_reasons:
            text = str(reason).strip()
            if text:
                counts[text] += 1
    return dict(counts)


def _bbox_area(bbox: Any) -> float | None:
    if not isinstance(bbox, dict):
        return None
    width = _safe_float(bbox.get("width"))
    height = _safe_float(bbox.get("height"))
    if width is None or height is None:
        return None
    return round(max(0.0, width) * max(0.0, height), 6)


def _selected_target_candidate(target_lock: dict[str, Any]) -> dict[str, Any]:
    candidates = target_lock.get("candidates") if isinstance(target_lock.get("candidates"), list) else []
    selected_id = str(target_lock.get("selected_candidate_id") or "").strip()
    selected = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and selected_id and str(item.get("id") or "").strip() == selected_id
        ),
        None,
    )
    if not isinstance(selected, dict) and candidates:
        selected = next((item for item in candidates if isinstance(item, dict)), None)
    return selected if isinstance(selected, dict) else {}


def _target_candidate_summary(target_lock: dict[str, Any]) -> dict[str, Any]:
    candidate = _selected_target_candidate(target_lock)
    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else target_lock.get("selected_bbox")
    bbox_width = _safe_float(bbox.get("width")) if isinstance(bbox, dict) else None
    bbox_height = _safe_float(bbox.get("height")) if isinstance(bbox, dict) else None
    bbox_aspect = (
        round(bbox_width / bbox_height, 4)
        if bbox_width is not None and bbox_height is not None and bbox_height > 0
        else None
    )
    return {
        "id": candidate.get("id") or target_lock.get("selected_candidate_id"),
        "source": candidate.get("source"),
        "confidence": _safe_float(candidate.get("confidence")),
        "bbox_width": bbox_width,
        "bbox_height": bbox_height,
        "bbox_aspect": bbox_aspect,
        "bbox_area": _bbox_area(bbox),
        "support_count": candidate.get("support_count"),
        "support_frame_count": candidate.get("support_frame_count"),
        "support_confidence": _safe_float(candidate.get("support_confidence")),
        "support_anchor_frames": (
            candidate.get("support_anchor_frames")
            if isinstance(candidate.get("support_anchor_frames"), list)
            else []
        ),
        "support_center_span": _safe_float(candidate.get("support_center_span")),
        "support_avg_area": _safe_float(candidate.get("support_avg_area")),
        "support_motion_anchor_hits": candidate.get("support_motion_anchor_hits"),
        "multiperson_ambiguous_frame_count": candidate.get("multiperson_ambiguous_frame_count"),
        "multiperson_competitor_count": candidate.get("multiperson_competitor_count"),
        "multiperson_same_anchor_competitor_count": candidate.get("multiperson_same_anchor_competitor_count"),
        "multiperson_selected_pair_frame_count": candidate.get("multiperson_selected_pair_frame_count"),
        "multiperson_selected_pair_competitor_count": candidate.get("multiperson_selected_pair_competitor_count"),
        "multiperson_other_frame_ambiguous_count": candidate.get("multiperson_other_frame_ambiguous_count"),
        "multiperson_nearest_center_distance": _safe_float(candidate.get("multiperson_nearest_center_distance")),
        "multiperson_max_competitor_confidence": _safe_float(candidate.get("multiperson_max_competitor_confidence")),
        "multiperson_ignored_fragment_count": candidate.get("multiperson_ignored_fragment_count"),
        "anchor_frame": candidate.get("anchor_frame"),
        "anchor_index": candidate.get("anchor_index"),
        "quality_flags": candidate.get("quality_flags") if isinstance(candidate.get("quality_flags"), list) else [],
    }


def _target_manual_review_flags(flags: list[str]) -> list[str]:
    return [
        flag
        for flag in flags
        if "auto_lock_blocked" not in str(flag)
        and (
            str(flag).endswith("_manual_review")
        or str(flag).endswith("_low_support_manual_review")
        or str(flag).endswith("_low_confidence")
        )
    ]


def _target_auto_lock_blocked_flags(flags: list[str]) -> list[str]:
    return [flag for flag in flags if "auto_lock_blocked" in str(flag)]


def _target_review_reason_flags(flags: list[str]) -> list[str]:
    return [
        flag
        for flag in flags
        if any(str(flag).startswith(prefix) for prefix in TARGET_REVIEW_REASON_FLAG_PREFIXES)
    ]


def _target_lock_from_preview(preview: dict[str, Any]) -> dict[str, Any]:
    candidates = preview.get("candidates") if isinstance(preview.get("candidates"), list) else []
    auto_candidate_id = str(preview.get("auto_candidate_id") or "").strip()
    selected = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and auto_candidate_id and str(item.get("id") or "").strip() == auto_candidate_id
        ),
        None,
    )
    if not isinstance(selected, dict):
        selected = next((item for item in candidates if isinstance(item, dict)), None)
    quality_flags = selected.get("quality_flags") if isinstance(selected, dict) and isinstance(selected.get("quality_flags"), list) else []
    return {
        "status": preview.get("target_lock_status"),
        "selected_candidate_id": auto_candidate_id or (selected.get("id") if isinstance(selected, dict) else None),
        "selected_bbox": selected.get("bbox") if isinstance(selected, dict) else None,
        "lock_confidence": preview.get("lock_confidence"),
        "candidates": candidates,
        "quality_flags": quality_flags,
        "target_preview_refreshed": True,
    }


def _with_refreshed_target_preview(
    analysis: dict[str, Any],
    preview: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(preview, dict):
        return analysis
    original_target = analysis.get("target_lock") if isinstance(analysis.get("target_lock"), dict) else {}
    refreshed = dict(analysis)
    preview_target = _target_lock_from_preview(preview)
    preserved_tracker_flags = [
        str(flag)
        for flag in original_target.get("quality_flags", [])
        if isinstance(flag, str) and flag.startswith("person_tracker_")
    ]
    preview_flags = [
        str(flag)
        for flag in preview_target.get("quality_flags", [])
        if isinstance(flag, str) and str(flag).strip()
    ]
    merged_target = dict(preview_target)
    for key in ("person_tracker_diagnostics",):
        if key in original_target and key not in merged_target:
            merged_target[key] = original_target[key]
    merged_target["quality_flags"] = list(dict.fromkeys([*preview_flags, *preserved_tracker_flags]))
    refreshed["target_lock"] = merged_target
    refreshed["target_lock_status"] = preview.get("target_lock_status") or analysis.get("target_lock_status")
    return refreshed


def _motion_records(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    motion = analysis.get("frame_motion_scores") if isinstance(analysis.get("frame_motion_scores"), dict) else {}
    selected = motion.get("selected") if isinstance(motion.get("selected"), list) else []
    records = [item for item in selected if isinstance(item, dict)]
    return records


def _top_motion_peaks(records: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    sorted_records = sorted(records, key=lambda item: _safe_float(item.get("motion_score")) or 0.0, reverse=True)
    out: list[dict[str, Any]] = []
    for item in sorted_records[:limit]:
        out.append(
            {
                "frame_id": item.get("frame_id") or item.get("frame"),
                "timestamp": _safe_float(item.get("timestamp")),
                "motion_score": _safe_float(item.get("motion_score")),
            }
        )
    return out


def _analysis_profile(analysis_or_row: dict[str, Any]) -> str:
    raw = str(analysis_or_row.get("analysis_profile") or "").strip().lower()
    raw = PROFILE_ALIASES.get(raw, raw)
    return raw if raw in KNOWN_ANALYSIS_PROFILES else "unknown"


def _profile_keyframe_keys(analysis_profile: str | None) -> tuple[str, ...]:
    profile = str(analysis_profile or "").strip().lower()
    return PROFILE_KEYFRAME_KEYS.get(profile, TAL_KEYS)


def _profile_keyframe_aliases(key: str) -> tuple[str, ...]:
    return PROFILE_KEYFRAME_ALIASES.get(key, (key,))


def _profile_keyframe_value(source: dict[str, Any], key: str) -> Any:
    for alias in _profile_keyframe_aliases(key):
        value = source.get(alias)
        if value is not None:
            return value
    return None


def _profile_timestamp_map(analysis: dict[str, Any]) -> dict[str, float | None]:
    bio = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    raw = bio.get("key_frame_timestamps") if isinstance(bio.get("key_frame_timestamps"), dict) else {}
    key_frames = bio.get("key_frames") if isinstance(bio.get("key_frames"), dict) else {}
    keys = set(_profile_keyframe_keys(_analysis_profile(analysis))) | set(TAL_KEYS)
    keys.update(str(key) for key in raw.keys())
    keys.update(str(key) for key in key_frames.keys())
    return {key: _safe_float(raw.get(key)) for key in sorted(keys)}


def _profile_keyframe_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    profile = _analysis_profile(analysis)
    expected_keys = _profile_keyframe_keys(profile)
    bio = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    key_frames = bio.get("key_frames") if isinstance(bio.get("key_frames"), dict) else {}
    timestamps = _profile_timestamp_map(analysis)
    present_keys = [
        key
        for key in expected_keys
        if _profile_keyframe_value(key_frames, key) or _profile_keyframe_value(timestamps, key) is not None
    ]
    return {
        "expected_keys": list(expected_keys),
        "present_keys": present_keys,
        "missing_keys": [key for key in expected_keys if key not in present_keys],
        "complete": bool(expected_keys) and len(present_keys) == len(expected_keys),
        "coverage_score": round(len(present_keys) / max(len(expected_keys), 1), 4),
    }


def _timestamps_from_bio(analysis: dict[str, Any]) -> dict[str, float | None]:
    bio = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    raw = bio.get("key_frame_timestamps") if isinstance(bio.get("key_frame_timestamps"), dict) else {}
    if raw:
        return {key: _safe_float(raw.get(key)) for key in ("T", "A", "L")}

    key_frames = bio.get("key_frames") if isinstance(bio.get("key_frames"), dict) else {}
    if not key_frames:
        return {key: None for key in ("T", "A", "L")}

    timestamp_by_frame = {
        str(record.get("frame_id") or record.get("frame") or "").rsplit(".", 1)[0]: _safe_float(record.get("timestamp"))
        for record in _motion_records(analysis)
        if isinstance(record, dict)
    }
    raw = {
        key: timestamp_by_frame.get(str(frame_id).rsplit(".", 1)[0])
        for key, frame_id in key_frames.items()
        if key in {"T", "A", "L"}
    }
    return {key: _safe_float(raw.get(key)) for key in ("T", "A", "L")}


def _timestamps_from_keyframe_candidates(analysis: dict[str, Any]) -> dict[str, float | None]:
    bio = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    candidates = bio.get("key_frame_candidates") if isinstance(bio.get("key_frame_candidates"), dict) else {}
    return {
        key: (
            _safe_float(candidates.get(key, {}).get("timestamp"))
            if isinstance(candidates.get(key), dict)
            else None
        )
        for key in ("T", "A", "L")
    }


def _semantic_selected(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    vt = analysis.get("video_temporal_diagnostics") if isinstance(analysis.get("video_temporal_diagnostics"), dict) else {}
    selected = vt.get("selected_semantic_frames") if isinstance(vt.get("selected_semantic_frames"), list) else []
    if selected:
        return [item for item in selected if isinstance(item, dict)]
    resolved = _resolved_keyframes(analysis)
    selected = resolved.get("selected") if isinstance(resolved.get("selected"), list) else []
    return [item for item in selected if isinstance(item, dict)]


def _resolved_keyframes(analysis: dict[str, Any]) -> dict[str, Any]:
    cross_validation = (
        analysis.get("cross_validation")
        if isinstance(analysis.get("cross_validation"), dict)
        else {}
    )
    resolved = cross_validation.get("resolved_keyframes")
    if isinstance(resolved, dict) and resolved:
        return resolved
    resolved = analysis.get("resolved_keyframes")
    if isinstance(resolved, dict) and resolved:
        return resolved
    motion = analysis.get("frame_motion_scores") if isinstance(analysis.get("frame_motion_scores"), dict) else {}
    resolved = motion.get("resolved_keyframes") if isinstance(motion.get("resolved_keyframes"), dict) else {}
    return resolved if isinstance(resolved, dict) else {}


def _semantic_key_for_record(record: dict[str, Any]) -> str | None:
    key_moment = str(record.get("key_moment") or "").strip()
    if key_moment.startswith("T_"):
        return "T"
    if key_moment.startswith("A_"):
        return "A"
    if key_moment.startswith("L_"):
        return "L"
    phase_code = str(record.get("phase_code") or "").strip()
    if phase_code == "takeoff":
        return "T"
    if phase_code == "air":
        return "A"
    if phase_code == "landing":
        return "L"
    return None


def _semantic_tal_timestamps(analysis: dict[str, Any]) -> dict[str, float | None]:
    out = {"T": None, "A": None, "L": None}
    for item in _semantic_selected(analysis):
        key = _semantic_key_for_record(item)
        if key and out[key] is None:
            out[key] = _safe_float(item.get("timestamp"))
    return out


def _resolved_tal_timestamps(analysis: dict[str, Any]) -> dict[str, float | None]:
    out = {"T": None, "A": None, "L": None}
    selected = _resolved_keyframes(analysis).get("selected")
    for item in selected if isinstance(selected, list) else []:
        if not isinstance(item, dict):
            continue
        key = _semantic_key_for_record(item)
        if key and out[key] is None:
            out[key] = _safe_float(item.get("timestamp"))
    return out


def _uses_semantic_frames(analysis: dict[str, Any]) -> bool:
    vt = analysis.get("video_temporal_diagnostics")
    if isinstance(vt, dict) and "used_semantic_frames" in vt:
        return bool(vt.get("used_semantic_frames"))
    resolved = _resolved_keyframes(analysis)
    flags = resolved.get("quality_flags") if isinstance(resolved.get("quality_flags"), list) else []
    return not any(
        str(flag)
        in {
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            "semantic_keyframe_refinement_order_rejected",
            "semantic_keyframes_unreliable_after_refinement",
            "semantic_keyframes_unreliable_after_visibility_check",
            "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
        }
        for flag in flags
    )


def _nearest_motion_delta(timestamp: float | None, peaks: list[dict[str, Any]]) -> float | None:
    if timestamp is None or not peaks:
        return None
    times = [_safe_float(item.get("timestamp")) for item in peaks]
    times = [value for value in times if value is not None]
    if not times:
        return None
    return round(timestamp - min(times, key=lambda item: abs(item - timestamp)), 3)


def _delta_map(a: dict[str, float | None], b: dict[str, float | None]) -> dict[str, float | None]:
    return {
        key: (
            round(a[key] - b[key], 3)
            if a.get(key) is not None and b.get(key) is not None
            else None
        )
        for key in ("T", "A", "L")
    }


def _has_tal_timestamp(timestamps: dict[str, float | None]) -> bool:
    return any(timestamps.get(key) is not None for key in ("T", "A", "L"))


def _tal_core_window(timestamps: dict[str, float | None]) -> tuple[float, float] | None:
    start = timestamps.get("T")
    end = timestamps.get("L")
    if start is None or end is None or end <= start:
        return None
    return (start, end)


def _motion_peak_score_in_window(
    records: list[dict[str, Any]],
    start: float,
    end: float,
    *,
    tolerance: float = 0.0,
) -> float | None:
    values = [
        _safe_float(record.get("motion_score"))
        for record in records
        if (
            _safe_float(record.get("timestamp")) is not None
            and start - tolerance <= (_safe_float(record.get("timestamp")) or 0.0) <= end + tolerance
        )
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _full_frame_motion_peak_contamination(
    *,
    motion_records: list[dict[str, Any]],
    top_motion_peaks: list[dict[str, Any]],
    timestamps: dict[str, float | None],
    target_quality_flags: list[str],
) -> dict[str, Any] | None:
    window = _tal_core_window(timestamps)
    if window is None or not top_motion_peaks:
        return None
    flag_set = {str(flag) for flag in target_quality_flags if str(flag).strip()}
    risk_flags = sorted(flag_set & FULL_FRAME_MOTION_PEAK_CONTAMINATION_RISK_FLAGS)
    if not risk_flags:
        return None

    strongest = max(top_motion_peaks, key=lambda item: _safe_float(item.get("motion_score")) or 0.0)
    peak_timestamp = _safe_float(strongest.get("timestamp"))
    peak_score = _safe_float(strongest.get("motion_score"))
    if peak_timestamp is None or peak_score is None:
        return None
    core_start, core_end = window
    if peak_timestamp < core_start:
        direction = "early"
        offset_sec = core_start - peak_timestamp
    elif peak_timestamp > core_end:
        direction = "late"
        offset_sec = peak_timestamp - core_end
    else:
        return None
    if offset_sec < FULL_FRAME_MOTION_PEAK_CONTAMINATION_MIN_OFFSET_SEC:
        return None
    if peak_score < FULL_FRAME_MOTION_PEAK_CONTAMINATION_MIN_SCORE:
        return None

    core_peak = _motion_peak_score_in_window(
        motion_records,
        core_start,
        core_end,
        tolerance=FULL_FRAME_MOTION_PEAK_CONTAMINATION_CORE_TOLERANCE_SEC,
    )
    if core_peak is None or core_peak <= 0.0:
        return None
    ratio = peak_score / core_peak
    if ratio < FULL_FRAME_MOTION_PEAK_CONTAMINATION_MIN_PEAK_RATIO:
        return None

    return {
        "peak_timestamp": round(peak_timestamp, 3),
        "peak_motion_score": round(peak_score, 5),
        "core_window": {"start_sec": round(core_start, 3), "end_sec": round(core_end, 3)},
        "core_peak_motion_score": round(core_peak, 5),
        "peak_to_core_ratio": round(ratio, 3),
        "lead_sec": round(core_start - peak_timestamp, 3),
        "offset_sec": round(offset_sec, 3),
        "direction": direction,
        "risk_flags": risk_flags,
    }


def _trusted_motion_peak_delta(
    delta: dict[str, float | None],
    *,
    contaminated: bool,
    candidate_delta_untrusted: bool = False,
) -> dict[str, float | None]:
    return _empty_tal_delta() if contaminated or candidate_delta_untrusted else delta


def _threshold_flags(deltas: dict[str, float | None], *, threshold: float = 0.1) -> dict[str, str | None]:
    flags: dict[str, str | None] = {}
    for key in ("T", "A", "L"):
        value = deltas.get(key)
        if not isinstance(value, (int, float)):
            flags[key] = None
        elif abs(value) <= threshold:
            flags[key] = "within"
        elif value < 0:
            flags[key] = "early"
        else:
            flags[key] = "late"
    return flags


def _empty_tal_delta() -> dict[str, None]:
    return {key: None for key in ("T", "A", "L")}


def _candidate_delta_untrusted_reasons(candidate_flags: list[str]) -> list[str]:
    return sorted(set(candidate_flags) & CANDIDATE_DELTA_UNTRUSTED_FLAGS)


def _candidate_warning_values(candidate: dict[str, Any]) -> set[str]:
    warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
    return {str(warning) for warning in warnings if str(warning).strip()}


def _candidate_component_value(candidate: dict[str, Any], name: str) -> float | None:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
    return _safe_float(components.get(name))


def _candidate_structural_untrusted_reasons(candidates: dict[str, Any]) -> list[str]:
    reasons: set[str] = set()
    takeoff = candidates.get("T") if isinstance(candidates.get("T"), dict) else {}
    apex = candidates.get("A") if isinstance(candidates.get("A"), dict) else {}
    landing = candidates.get("L") if isinstance(candidates.get("L"), dict) else {}
    if "takeoff_geometry_weak" in _candidate_warning_values(takeoff):
        reasons.add("tal_candidate_takeoff_geometry_weak")
    if "apex_geometry_weak" in _candidate_warning_values(apex):
        reasons.add("tal_candidate_apex_geometry_weak")
    if "landing_geometry_weak" in _candidate_warning_values(landing):
        reasons.add("tal_candidate_landing_geometry_weak")

    landing_contact = _candidate_component_value(landing, "landing_contact")
    if (
        landing_contact is not None
        and landing_contact <= 0.22
        and _candidate_component_value(landing, "ankle_return") is not None
        and (_candidate_component_value(landing, "ankle_return") or 0.0) <= 0.35
        and _candidate_component_value(landing, "knee_absorption") is not None
        and (_candidate_component_value(landing, "knee_absorption") or 0.0) <= 0.10
    ):
        reasons.add("tal_candidate_landing_geometry_weak")
    return sorted(reasons)


def _trusted_candidate_delta(
    delta: dict[str, float | None],
    *,
    candidate_delta_untrusted: bool,
) -> dict[str, float | None]:
    return _empty_tal_delta() if candidate_delta_untrusted else delta


def _normalize_precomputed_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["analysis_profile"] = _analysis_profile(normalized)
    target = normalized.get("target") if isinstance(normalized.get("target"), dict) else {}
    pose = normalized.get("pose") if isinstance(normalized.get("pose"), dict) else {}
    keyframes = normalized.get("keyframes") if isinstance(normalized.get("keyframes"), dict) else {}
    video_temporal = (
        normalized.get("video_temporal") if isinstance(normalized.get("video_temporal"), dict) else {}
    )
    cross_validation = normalized.get("cross_validation") if isinstance(normalized.get("cross_validation"), dict) else {}
    semantic_identity_lock_flags = _semantic_identity_lock_flags_from_cross_validation(cross_validation)
    source_quality_flags = [
        str(flag)
        for flag in normalized.get("quality_flags", [])
        if str(flag).strip()
    ] if isinstance(normalized.get("quality_flags"), list) else []
    source_derived_risk_flags = [
        flag for flag in source_quality_flags if flag in DERIVED_TARGET_TRACKING_RISK_FLAGS
    ]
    if "target_quality_flags" not in normalized and isinstance(target.get("quality_flags"), list):
        normalized["target_quality_flags"] = [str(flag) for flag in target["quality_flags"] if str(flag).strip()]
    if isinstance(normalized.get("target_quality_flags"), list):
        normalized["target_quality_flags"] = [
            str(flag)
            for flag in normalized["target_quality_flags"]
            if str(flag).strip()
            and str(flag) not in DERIVED_TARGET_TRACKING_RISK_FLAGS
        ]
    if "tracker_state_counts" not in normalized and isinstance(target.get("tracker_state_counts"), dict):
        normalized["tracker_state_counts"] = dict(target["tracker_state_counts"])
    if "tracker_rejection_reason_counts" not in normalized:
        diagnostics = normalized.get("person_tracker_diagnostics")
        if not isinstance(diagnostics, list) and isinstance(target.get("person_tracker_diagnostics"), list):
            diagnostics = target.get("person_tracker_diagnostics")
        if isinstance(diagnostics, list):
            normalized["tracker_rejection_reason_counts"] = _tracker_rejection_reason_counts(diagnostics)
    if "target_status" not in normalized and target.get("status") is not None:
        normalized["target_status"] = target.get("status")
    if "target_lock_confidence" not in normalized and target.get("lock_confidence") is not None:
        normalized["target_lock_confidence"] = _safe_float(target.get("lock_confidence"))
    if "pose_tracked_ratio" not in normalized and pose.get("tracked_ratio") is not None:
        normalized["pose_tracked_ratio"] = _safe_float(pose.get("tracked_ratio"))
    if "pose_lost_ratio" not in normalized and pose.get("lost_ratio") is not None:
        normalized["pose_lost_ratio"] = _safe_float(pose.get("lost_ratio"))
    if "pose_low_confidence_ratio" not in normalized and pose.get("low_confidence_ratio") is not None:
        normalized["pose_low_confidence_ratio"] = _safe_float(pose.get("low_confidence_ratio"))
    if "pose_quality_flags" not in normalized and isinstance(pose.get("quality_flags"), list):
        normalized["pose_quality_flags"] = [str(flag) for flag in pose["quality_flags"] if str(flag).strip()]
    existing_pose_flags = (
        [str(flag) for flag in normalized["pose_quality_flags"] if str(flag).strip()]
        if isinstance(normalized.get("pose_quality_flags"), list)
        else []
    )
    normalized["pose_quality_flags"] = list(dict.fromkeys([*existing_pose_flags, *semantic_identity_lock_flags]))
    if "keyframe_candidate_flags" not in normalized and isinstance(keyframes.get("quality_flags"), list):
        normalized["keyframe_candidate_flags"] = [str(flag) for flag in keyframes["quality_flags"] if str(flag).strip()]
    if "semantic_flags" not in normalized:
        semantic_flags = []
        if isinstance(video_temporal.get("quality_flags"), list):
            semantic_flags.extend(str(flag) for flag in video_temporal["quality_flags"] if str(flag).strip())
        if isinstance(video_temporal.get("retry_rejection_flags"), list):
            semantic_flags.extend(str(flag) for flag in video_temporal["retry_rejection_flags"] if str(flag).strip())
        normalized["semantic_flags"] = [
            flag for flag in dict.fromkeys(semantic_flags) if flag.startswith(SEMANTIC_PREFIXES)
        ]
    if "data_quality_flags" not in normalized:
        flags = []
        if isinstance(normalized.get("quality_flags"), list):
            flags.extend(str(flag) for flag in normalized["quality_flags"] if str(flag).strip())
        if isinstance(normalized.get("pose_quality_flags"), list):
            flags.extend(
                str(flag)
                for flag in normalized["pose_quality_flags"]
                if str(flag).strip() in POSE_IDENTITY_LOCK_FLAGS
            )
        auto_eval = normalized.get("auto_eval") if isinstance(normalized.get("auto_eval"), dict) else {}
        if isinstance(auto_eval.get("data_quality_flags"), list):
            flags.extend(str(flag) for flag in auto_eval["data_quality_flags"] if str(flag).strip())
        normalized["data_quality_flags"] = [
            flag for flag in dict.fromkeys(flags) if flag not in DERIVED_TARGET_TRACKING_RISK_FLAGS
        ]
    elif isinstance(normalized.get("data_quality_flags"), list):
        flags = [
            str(flag)
            for flag in normalized["data_quality_flags"]
            if str(flag).strip() and str(flag) not in DERIVED_TARGET_TRACKING_RISK_FLAGS
        ]
        if isinstance(normalized.get("pose_quality_flags"), list):
            flags.extend(
                str(flag)
                for flag in normalized["pose_quality_flags"]
                if str(flag).strip() in POSE_IDENTITY_LOCK_FLAGS
            )
        normalized["data_quality_flags"] = list(dict.fromkeys(flags))
    _renormalize_cached_tracker_sequence(normalized)
    if "profile_keyframe_summary" not in normalized:
        expected_keys = list(_profile_keyframe_keys(normalized["analysis_profile"]))
        present_keys: list[str] = []
        profile_keyframes = (
            keyframes.get("profile_keyframes")
            if isinstance(keyframes.get("profile_keyframes"), dict)
            else {}
        )
        for key in expected_keys:
            record = (
                _profile_keyframe_value(profile_keyframes, key)
                if isinstance(profile_keyframes, dict)
                else None
            )
            if isinstance(record, dict) and (record.get("frame_id") or record.get("timestamp") is not None):
                present_keys.append(key)
            elif record is not None:
                present_keys.append(key)
        if not present_keys and isinstance(keyframes.get("profile_keyframe_coverage_score"), (int, float)):
            expected_count = len(expected_keys)
            covered_count = round(float(keyframes["profile_keyframe_coverage_score"]) * expected_count)
            present_keys = expected_keys[:covered_count]
        normalized["profile_keyframe_summary"] = {
            "expected_keys": expected_keys,
            "present_keys": present_keys,
            "missing_keys": [key for key in expected_keys if key not in present_keys],
            "complete": bool(expected_keys) and len(present_keys) == len(expected_keys),
            "coverage_score": round(len(present_keys) / max(len(expected_keys), 1), 4),
        }
    if "effective_resolved_timestamps" not in normalized:
        raw_resolved_ts = (
            normalized.get("raw_resolved_timestamps")
            if isinstance(normalized.get("raw_resolved_timestamps"), dict)
            else {}
        )
        resolved_ts = (
            normalized.get("resolved_timestamps")
            if isinstance(normalized.get("resolved_timestamps"), dict)
            else {}
        )
        bio_ts = (
            normalized.get("bio_timestamps")
            if isinstance(normalized.get("bio_timestamps"), dict)
            else {}
        )
        uses_semantic_frames = normalized.get("video_temporal_used_semantic_frames")
        if uses_semantic_frames is False:
            normalized["effective_resolved_timestamps"] = dict(resolved_ts)
            if _has_tal_timestamp(raw_resolved_ts):
                normalized["resolved_timestamps"] = dict(raw_resolved_ts)
        elif _has_tal_timestamp(resolved_ts):
            normalized["effective_resolved_timestamps"] = dict(resolved_ts)
        else:
            normalized["effective_resolved_timestamps"] = dict(bio_ts)
    if (
        "bio_effective_resolved_delta" not in normalized
        and isinstance(normalized.get("bio_timestamps"), dict)
        and isinstance(normalized.get("effective_resolved_timestamps"), dict)
    ):
        normalized["bio_effective_resolved_delta"] = _delta_map(
            normalized["bio_timestamps"],
            normalized["effective_resolved_timestamps"],
        )
    if (
        "candidate_effective_resolved_delta" not in normalized
        and isinstance(normalized.get("candidate_timestamps"), dict)
        and isinstance(normalized.get("effective_resolved_timestamps"), dict)
    ):
        normalized["candidate_effective_resolved_delta"] = _delta_map(
            normalized["candidate_timestamps"],
            normalized["effective_resolved_timestamps"],
        )
    target_risk_flags = list(
        dict.fromkeys([*_target_tracking_risk_flags(normalized), *source_derived_risk_flags])
    )
    full_frame_motion_peak_risk_flags = _full_frame_motion_peak_risk_flags(normalized)
    normalized["target_tracking_risk_flags"] = target_risk_flags
    if full_frame_motion_peak_risk_flags:
        normalized["full_frame_motion_peak_risk_flags"] = full_frame_motion_peak_risk_flags
    if target_risk_flags or full_frame_motion_peak_risk_flags:
        existing_target_flags = [
            str(flag)
            for flag in normalized.get("target_quality_flags", [])
            if str(flag).strip()
        ] if isinstance(normalized.get("target_quality_flags"), list) else []
        normalized["target_quality_flags"] = list(
            dict.fromkeys([*existing_target_flags, *target_risk_flags, *full_frame_motion_peak_risk_flags])
        )
        existing_data_flags = [
            str(flag)
            for flag in normalized.get("data_quality_flags", [])
            if str(flag).strip()
        ] if isinstance(normalized.get("data_quality_flags"), list) else []
        normalized["data_quality_flags"] = list(
            dict.fromkeys([*existing_data_flags, *target_risk_flags])
        )
    candidate_flags = [
        str(flag)
        for flag in normalized.get("keyframe_candidate_flags", [])
        if str(flag).strip()
    ] if isinstance(normalized.get("keyframe_candidate_flags"), list) else []
    candidate_motion_contaminated = bool(set(candidate_flags) & CONTAMINATED_CANDIDATE_FLAGS) or bool(
        normalized.get("candidate_motion_contaminated")
    )
    if candidate_motion_contaminated:
        normalized["candidate_motion_contaminated"] = True
    untrusted_reasons = set(_candidate_delta_untrusted_reasons(candidate_flags))
    existing_reasons = normalized.get("candidate_delta_untrusted_reasons")
    if isinstance(existing_reasons, list):
        untrusted_reasons.update(str(reason) for reason in existing_reasons if str(reason).strip())
    if candidate_motion_contaminated and not untrusted_reasons:
        untrusted_reasons.add("candidate_motion_contaminated")
    candidate_timestamps = (
        normalized.get("candidate_timestamps") if isinstance(normalized.get("candidate_timestamps"), dict) else {}
    )
    if candidate_timestamps and any(candidate_timestamps.get(key) is None for key in ("T", "A", "L")):
        untrusted_reasons.add("candidate_timestamps_incomplete")
    candidate_delta_untrusted = bool(untrusted_reasons) or bool(normalized.get("candidate_delta_untrusted"))
    normalized["candidate_delta_untrusted"] = candidate_delta_untrusted
    normalized["candidate_delta_untrusted_reasons"] = sorted(untrusted_reasons)
    if candidate_delta_untrusted:
        normalized["trusted_candidate_semantic_delta"] = _empty_tal_delta()
        normalized["trusted_candidate_resolved_delta"] = _empty_tal_delta()
        normalized["trusted_candidate_effective_resolved_delta"] = _empty_tal_delta()
    elif "trusted_candidate_effective_resolved_delta" not in normalized:
        candidate_effective_delta = normalized.get("candidate_effective_resolved_delta")
        normalized["trusted_candidate_effective_resolved_delta"] = (
            dict(candidate_effective_delta) if isinstance(candidate_effective_delta, dict) else _empty_tal_delta()
        )
    contamination = normalized.get("full_frame_motion_peak_contamination")
    if not isinstance(contamination, dict):
        timestamps = (
            normalized.get("effective_resolved_timestamps")
            if isinstance(normalized.get("effective_resolved_timestamps"), dict)
            else normalized.get("resolved_timestamps")
            if isinstance(normalized.get("resolved_timestamps"), dict)
            else normalized.get("semantic_timestamps")
            if isinstance(normalized.get("semantic_timestamps"), dict)
            else normalized.get("bio_timestamps")
            if isinstance(normalized.get("bio_timestamps"), dict)
            else {}
        )
        top_peaks = normalized.get("top_motion_peaks") if isinstance(normalized.get("top_motion_peaks"), list) else []
        contamination = _full_frame_motion_peak_contamination(
            motion_records=[item for item in top_peaks if isinstance(item, dict)],
            top_motion_peaks=[item for item in top_peaks if isinstance(item, dict)],
            timestamps=timestamps,
            target_quality_flags=[
                str(flag)
                for flag in normalized.get("target_quality_flags", [])
                if str(flag).strip()
            ] if isinstance(normalized.get("target_quality_flags"), list) else [],
        )
    if contamination is not None:
        normalized["full_frame_motion_peak_contamination"] = contamination
    motion_peak_contaminated = contamination is not None or bool(normalized.get("full_frame_motion_peak_contaminated"))
    normalized["full_frame_motion_peak_contaminated"] = motion_peak_contaminated
    for delta_key, trusted_key in (
        ("bio_motion_peak_delta", "trusted_bio_motion_peak_delta"),
        ("candidate_motion_peak_delta", "trusted_candidate_motion_peak_delta"),
        ("semantic_motion_peak_delta", "trusted_semantic_motion_peak_delta"),
        ("resolved_motion_peak_delta", "trusted_resolved_motion_peak_delta"),
        ("effective_resolved_motion_peak_delta", "trusted_effective_resolved_motion_peak_delta"),
    ):
        force_recompute = trusted_key == "trusted_candidate_motion_peak_delta" and candidate_delta_untrusted
        if isinstance(normalized.get(trusted_key), dict) and not motion_peak_contaminated and not force_recompute:
            continue
        delta = normalized.get(delta_key)
        normalized[trusted_key] = _trusted_motion_peak_delta(
            delta if isinstance(delta, dict) else {},
            contaminated=motion_peak_contaminated,
            candidate_delta_untrusted=trusted_key == "trusted_candidate_motion_peak_delta"
            and candidate_delta_untrusted,
        )
    for delta_key, status_key in (
        ("bio_semantic_delta", "bio_semantic_delta_status"),
        ("bio_resolved_delta", "bio_resolved_delta_status"),
        ("bio_effective_resolved_delta", "bio_effective_resolved_delta_status"),
        ("candidate_semantic_delta", "candidate_semantic_delta_status"),
        ("candidate_resolved_delta", "candidate_resolved_delta_status"),
        ("candidate_effective_resolved_delta", "candidate_effective_resolved_delta_status"),
        ("trusted_candidate_semantic_delta", "trusted_candidate_semantic_delta_status"),
        ("trusted_candidate_resolved_delta", "trusted_candidate_resolved_delta_status"),
        ("trusted_candidate_effective_resolved_delta", "trusted_candidate_effective_resolved_delta_status"),
    ):
        force_recompute = candidate_delta_untrusted and delta_key.startswith("trusted_candidate_")
        if isinstance(normalized.get(status_key), dict) and not force_recompute:
            continue
        delta = normalized.get(delta_key)
        normalized[status_key] = _threshold_flags(delta if isinstance(delta, dict) else {})
    if not isinstance(normalized.get("target_review_reason_flags"), list):
        target_flags = normalized.get("target_quality_flags")
        normalized["target_review_reason_flags"] = _target_review_reason_flags(
            target_flags if isinstance(target_flags, list) else []
        )
    target_flags = normalized.get("target_quality_flags")
    target_flags = target_flags if isinstance(target_flags, list) else []
    if not isinstance(normalized.get("target_manual_review_flags"), list):
        normalized["target_manual_review_flags"] = _target_manual_review_flags(target_flags)
    if "target_manual_review_required" not in normalized:
        normalized["target_manual_review_required"] = any("_manual_review" in str(flag) for flag in target_flags)
    if not isinstance(normalized.get("target_auto_lock_blocked_flags"), list):
        normalized["target_auto_lock_blocked_flags"] = _target_auto_lock_blocked_flags(target_flags)
    if "target_auto_lock_blocked" not in normalized:
        normalized["target_auto_lock_blocked"] = any("auto_lock_blocked" in str(flag) for flag in target_flags)
    return normalized


def _target_tracking_risk_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if _tiny_target_tracking_risk(row):
        flags.append(TINY_TARGET_LOW_POSE_TRACKING_RISK_FLAG)
    if _multiperson_relock_instability_risk(row):
        flags.append(MULTIPERSON_RELOCK_INSTABILITY_RISK_FLAG)
    return flags


def _full_frame_motion_peak_risk_flags(row: dict[str, Any]) -> list[str]:
    if _multiperson_risk_context(row):
        return [MULTIPERSON_FULL_FRAME_MOTION_RISK_FLAG]
    return []


def _tiny_target_tracking_risk(row: dict[str, Any]) -> bool:
    candidate = row.get("target_selected_candidate") if isinstance(row.get("target_selected_candidate"), dict) else {}
    bbox_area = _safe_float(candidate.get("bbox_area"))
    bbox_height = _safe_float(candidate.get("bbox_height"))
    if bbox_height is None:
        raw_bbox = candidate.get("bbox")
        if isinstance(raw_bbox, dict):
            bbox_height = _safe_float(raw_bbox.get("height"))
    tiny_target = (
        (bbox_area is not None and bbox_area <= TINY_TARGET_RISK_MAX_AREA)
        or (bbox_height is not None and bbox_height <= TINY_TARGET_RISK_MAX_HEIGHT)
    )
    if not tiny_target:
        return False

    pose_ratio = _safe_float(row.get("pose_tracked_ratio"))
    summary = row.get("tracker_sequence_summary") if isinstance(row.get("tracker_sequence_summary"), dict) else {}
    loss_frames = _safe_float(summary.get("loss_frames"))
    total_frames = _safe_float(summary.get("total_frames"))
    loss_ratio = loss_frames / total_frames if loss_frames is not None and total_frames and total_frames > 0 else None
    tracker_flags = {
        str(flag)
        for flag in row.get("target_quality_flags", [])
        if str(flag).strip()
    } if isinstance(row.get("target_quality_flags"), list) else set()
    state_counts = summary.get("state_counts") if isinstance(summary.get("state_counts"), dict) else {}
    if not state_counts and isinstance(row.get("tracker_state_counts"), dict):
        state_counts = row["tracker_state_counts"]
    confirmed_relocks = int(state_counts.get("relocked", 0) or 0) + int(state_counts.get("detector_relocked", 0) or 0)
    hard_rejections = sum(int(state_counts.get(state, 0) or 0) for state in HARD_TRACKER_REJECTION_STATES)
    terminal_lost = str(summary.get("final_state") or "") in UNRECOVERED_TRACKER_STATES and not bool(
        summary.get("terminal_loss_graced")
    )
    tracker_unstable = (
        confirmed_relocks > 0
        or hard_rejections > 0
        or terminal_lost
        or bool(tracker_flags & {"person_tracker_relock_rejected", "person_tracker_continuity_rejected"})
    )
    if (
        (pose_ratio is not None and pose_ratio < TINY_TARGET_RISK_MAX_POSE_TRACKED_RATIO)
        or (loss_ratio is not None and loss_ratio >= TINY_TARGET_RISK_MIN_TRACKER_LOSS_RATIO)
        or tracker_unstable
    ):
        return True
    return False


def _multiperson_relock_instability_risk(row: dict[str, Any]) -> bool:
    if not _multiperson_risk_context(row):
        return False

    summary = row.get("tracker_sequence_summary") if isinstance(row.get("tracker_sequence_summary"), dict) else {}
    state_counts = summary.get("state_counts") if isinstance(summary.get("state_counts"), dict) else {}
    relock_events = sum(
        int(state_counts.get(state, 0) or 0)
        for state in (
            "relocked",
            "detector_relocked",
            "relock_pending",
            "full_frame_yolo_relock_pending",
            "local_zoom_yolo_relock_pending",
        )
    )
    confirmed_relocks = int(state_counts.get("relocked", 0) or 0) + int(state_counts.get("detector_relocked", 0) or 0)
    rejected_events = int(state_counts.get("relock_rejected", 0) or 0) + int(state_counts.get("lost_reused", 0) or 0)
    loss_ratio = _safe_float(row.get("tracker_loss_ratio"))
    if loss_ratio is None:
        loss_frames = _safe_float(summary.get("loss_frames"))
        total_frames = _safe_float(summary.get("total_frames"))
        loss_ratio = loss_frames / total_frames if loss_frames is not None and total_frames and total_frames > 0 else None
    pose_ratio = _safe_float(row.get("pose_tracked_ratio"))
    high_loss = loss_ratio is not None and loss_ratio >= MULTIPERSON_RELOCK_RISK_MIN_LOSS_RATIO
    low_pose_tracking = pose_ratio is not None and pose_ratio < MULTIPERSON_RELOCK_RISK_MAX_POSE_TRACKED_RATIO
    repeated_relock = relock_events >= 3 and confirmed_relocks >= 1
    unstable_rejections = rejected_events >= 2 and relock_events >= 2
    return (high_loss or low_pose_tracking) and (repeated_relock or unstable_rejections)


def _multiperson_risk_context(row: dict[str, Any]) -> bool:
    flags = {
        str(flag)
        for flag in row.get("target_quality_flags", [])
        if str(flag).strip()
    } if isinstance(row.get("target_quality_flags"), list) else set()
    if flags & {
        "target_lock_zoomed_multiperson_manual_review",
        "target_lock_zoomed_multiperson_scale_competitor_manual_review",
    }:
        return True

    candidate = row.get("target_selected_candidate") if isinstance(row.get("target_selected_candidate"), dict) else {}
    try:
        ambiguous_frames = int(candidate.get("multiperson_ambiguous_frame_count") or 0)
        competitor_count = int(candidate.get("multiperson_competitor_count") or 0)
        other_ambiguous = int(candidate.get("multiperson_other_frame_ambiguous_count") or 0)
    except (TypeError, ValueError):
        return False
    return (ambiguous_frames >= 3 and competitor_count >= 6) or (other_ambiguous >= 2 and competitor_count >= 4)


def _analysis_row(item: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    analysis_profile = _analysis_profile(analysis)
    profile_keyframe_summary = _profile_keyframe_summary(analysis)
    bio_ts = _timestamps_from_bio(analysis)
    candidate_ts = _timestamps_from_keyframe_candidates(analysis)
    semantic_ts = _semantic_tal_timestamps(analysis)
    raw_resolved_ts = _resolved_tal_timestamps(analysis)
    uses_semantic_frames = _uses_semantic_frames(analysis)
    resolved_ts = raw_resolved_ts
    effective_resolved_ts = raw_resolved_ts if uses_semantic_frames else dict(bio_ts)
    motion_records = _motion_records(analysis)
    peaks = _top_motion_peaks(motion_records)
    target_lock = analysis.get("target_lock") if isinstance(analysis.get("target_lock"), dict) else {}
    target_candidate = _target_candidate_summary(target_lock)
    diagnostics = target_lock.get("person_tracker_diagnostics") if isinstance(target_lock.get("person_tracker_diagnostics"), list) else []
    tracker_sequence_summary = _tracker_sequence_summary(diagnostics)
    tracker_flags = _tracker_flags(analysis)
    if tracker_sequence_summary:
        if tracker_sequence_summary.get("final_unrecovered"):
            if "person_tracker_final_unrecovered" not in tracker_flags:
                tracker_flags.append("person_tracker_final_unrecovered")
        else:
            tracker_flags = [flag for flag in tracker_flags if flag != "person_tracker_final_unrecovered"]
    if (
        tracker_sequence_summary.get("transient_loss_recovered")
        and "person_tracker_transient_loss_recovered" not in tracker_flags
    ):
        tracker_flags.append("person_tracker_transient_loss_recovered")
    pose = analysis.get("pose_data") if isinstance(analysis.get("pose_data"), dict) else {}
    pose_diag = pose.get("pose_diagnostics") if isinstance(pose.get("pose_diagnostics"), dict) else {}
    semantic_identity_lock_flags = _semantic_identity_lock_flags(analysis)
    pose_flags = list(dict.fromkeys([*_pose_quality_flags(analysis), *semantic_identity_lock_flags]))
    data_quality_flags = list(
        dict.fromkeys([
            *_data_quality_flags(analysis),
            *[flag for flag in pose_flags if flag in POSE_IDENTITY_LOCK_FLAGS],
        ])
    )
    candidate_flags = []
    bio = analysis.get("bio_data") if isinstance(analysis.get("bio_data"), dict) else {}
    candidates = bio.get("key_frame_candidates") if isinstance(bio.get("key_frame_candidates"), dict) else {}
    if isinstance(candidates.get("quality_flags"), list):
        candidate_flags = [str(flag) for flag in candidates["quality_flags"] if str(flag).strip()]
    candidate_motion_contaminated = bool(set(candidate_flags) & CONTAMINATED_CANDIDATE_FLAGS)
    candidate_delta_untrusted_reasons = sorted(
        set(_candidate_delta_untrusted_reasons(candidate_flags))
        | set(_candidate_structural_untrusted_reasons(candidates))
    )
    candidate_delta_untrusted = bool(candidate_delta_untrusted_reasons)
    bio_semantic_delta = _delta_map(bio_ts, semantic_ts)
    bio_resolved_delta = _delta_map(bio_ts, resolved_ts)
    bio_effective_resolved_delta = _delta_map(bio_ts, effective_resolved_ts)
    candidate_semantic_delta = _delta_map(candidate_ts, semantic_ts)
    candidate_resolved_delta = _delta_map(candidate_ts, resolved_ts)
    candidate_effective_resolved_delta = _delta_map(candidate_ts, effective_resolved_ts)
    trusted_candidate_semantic_delta = _trusted_candidate_delta(
        candidate_semantic_delta,
        candidate_delta_untrusted=candidate_delta_untrusted,
    )
    trusted_candidate_resolved_delta = _trusted_candidate_delta(
        candidate_resolved_delta,
        candidate_delta_untrusted=candidate_delta_untrusted,
    )
    trusted_candidate_effective_resolved_delta = _trusted_candidate_delta(
        candidate_effective_resolved_delta,
        candidate_delta_untrusted=candidate_delta_untrusted,
    )
    semantic_motion_peak_delta = {key: _nearest_motion_delta(semantic_ts.get(key), peaks) for key in ("T", "A", "L")}
    resolved_motion_peak_delta = {key: _nearest_motion_delta(resolved_ts.get(key), peaks) for key in ("T", "A", "L")}
    effective_resolved_motion_peak_delta = {
        key: _nearest_motion_delta(effective_resolved_ts.get(key), peaks) for key in ("T", "A", "L")
    }
    semantic_candidate_conflict_summary = _semantic_candidate_conflict_summary(analysis)
    pose_tracked_ratio = round(
        float(pose_diag.get("tracked_frames") or 0) / max(float(pose_diag.get("total_frames") or 0), 1.0),
        4,
    )
    tracker_loss_frames = _safe_float(tracker_sequence_summary.get("loss_frames"))
    tracker_total_frames = _safe_float(tracker_sequence_summary.get("total_frames"))
    tracker_loss_ratio = (
        round(tracker_loss_frames / tracker_total_frames, 4)
        if tracker_loss_frames is not None and tracker_total_frames is not None and tracker_total_frames > 0
        else None
    )
    row = {
        "batch_file": item.get("_batch_file"),
        "video": item.get("video") or Path(str(analysis.get("video_path") or "")).name,
        "analysis_id": analysis.get("id") or item.get("analysis_id"),
        "status": analysis.get("status"),
        "analysis_profile": analysis_profile,
        "profile_keyframe_summary": profile_keyframe_summary,
        "pipeline_version": analysis.get("pipeline_version"),
        "force_score": analysis.get("force_score"),
        "created_at": analysis.get("created_at") or item.get("created_at"),
        "updated_at": analysis.get("updated_at") or item.get("updated_at"),
        "target_status": target_lock.get("status") or analysis.get("target_lock_status"),
        "target_lock_confidence": _safe_float(target_lock.get("lock_confidence")),
        "target_selected_candidate_id": target_lock.get("selected_candidate_id"),
        "target_selected_candidate": target_candidate,
        "target_quality_flags": tracker_flags,
        "target_preview_refreshed": bool(target_lock.get("target_preview_refreshed")),
        "target_preview_candidate_count": (
            len(target_lock.get("candidates"))
            if isinstance(target_lock.get("candidates"), list)
            else None
        ),
        "tracker_state_counts": _state_counts(diagnostics, "state"),
        "tracker_sequence_summary": tracker_sequence_summary,
        "tracker_loss_ratio": tracker_loss_ratio,
        "tracker_loss_frames": tracker_loss_frames,
        "tracker_total_frames": tracker_total_frames,
        "tracker_final_unrecovered": bool(tracker_sequence_summary.get("final_unrecovered")),
        "tracker_transient_loss_recovered": bool(tracker_sequence_summary.get("transient_loss_recovered")),
        "tracker_rejection_reason_counts": _tracker_rejection_reason_counts(diagnostics),
        "pose_tracked_ratio": pose_tracked_ratio,
        "bio_timestamps": bio_ts,
        "candidate_timestamps": candidate_ts,
        "semantic_timestamps": semantic_ts,
        "raw_resolved_timestamps": raw_resolved_ts,
        "resolved_timestamps": resolved_ts,
        "effective_resolved_timestamps": effective_resolved_ts,
        "bio_semantic_delta": bio_semantic_delta,
        "bio_resolved_delta": bio_resolved_delta,
        "bio_effective_resolved_delta": bio_effective_resolved_delta,
        "candidate_semantic_delta": candidate_semantic_delta,
        "candidate_resolved_delta": candidate_resolved_delta,
        "candidate_effective_resolved_delta": candidate_effective_resolved_delta,
        "trusted_candidate_semantic_delta": trusted_candidate_semantic_delta,
        "trusted_candidate_resolved_delta": trusted_candidate_resolved_delta,
        "trusted_candidate_effective_resolved_delta": trusted_candidate_effective_resolved_delta,
        "bio_semantic_delta_status": _threshold_flags(bio_semantic_delta),
        "bio_resolved_delta_status": _threshold_flags(bio_resolved_delta),
        "bio_effective_resolved_delta_status": _threshold_flags(bio_effective_resolved_delta),
        "candidate_semantic_delta_status": _threshold_flags(candidate_semantic_delta),
        "candidate_resolved_delta_status": _threshold_flags(candidate_resolved_delta),
        "candidate_effective_resolved_delta_status": _threshold_flags(candidate_effective_resolved_delta),
        "trusted_candidate_semantic_delta_status": _threshold_flags(trusted_candidate_semantic_delta),
        "trusted_candidate_resolved_delta_status": _threshold_flags(trusted_candidate_resolved_delta),
        "trusted_candidate_effective_resolved_delta_status": _threshold_flags(
            trusted_candidate_effective_resolved_delta
        ),
        "bio_motion_peak_delta": {key: _nearest_motion_delta(bio_ts.get(key), peaks) for key in ("T", "A", "L")},
        "candidate_motion_peak_delta": {key: _nearest_motion_delta(candidate_ts.get(key), peaks) for key in ("T", "A", "L")},
        "semantic_motion_peak_delta": semantic_motion_peak_delta,
        "resolved_motion_peak_delta": resolved_motion_peak_delta,
        "effective_resolved_motion_peak_delta": effective_resolved_motion_peak_delta,
        "top_motion_peaks": peaks,
        "keyframe_candidate_flags": candidate_flags,
        "candidate_motion_contaminated": candidate_motion_contaminated,
        "candidate_delta_untrusted": candidate_delta_untrusted,
        "candidate_delta_untrusted_reasons": candidate_delta_untrusted_reasons,
        "pose_quality_flags": pose_flags,
        "data_quality_flags": data_quality_flags,
        "semantic_flags": _semantic_flags(analysis),
        "semantic_candidate_conflict_summary": semantic_candidate_conflict_summary,
        "video_temporal_resolver_source": (
            analysis.get("video_temporal_diagnostics", {}).get("resolver_source")
            if isinstance(analysis.get("video_temporal_diagnostics"), dict)
            else None
        ),
        "video_temporal_used_semantic_frames": uses_semantic_frames,
    }
    target_risk_flags = _target_tracking_risk_flags(row)
    row["target_tracking_risk_flags"] = target_risk_flags
    full_frame_motion_peak_risk_flags = _full_frame_motion_peak_risk_flags(row)
    row["full_frame_motion_peak_risk_flags"] = full_frame_motion_peak_risk_flags
    if target_risk_flags or full_frame_motion_peak_risk_flags:
        row["target_quality_flags"] = list(
            dict.fromkeys([*row["target_quality_flags"], *target_risk_flags, *full_frame_motion_peak_risk_flags])
        )
    full_frame_motion_peak_contamination = _full_frame_motion_peak_contamination(
        motion_records=motion_records,
        top_motion_peaks=peaks,
        timestamps=(
            effective_resolved_ts
            if _has_tal_timestamp(effective_resolved_ts)
            else resolved_ts
            if _has_tal_timestamp(resolved_ts)
            else semantic_ts
        ),
        target_quality_flags=row["target_quality_flags"],
    )
    row["full_frame_motion_peak_contaminated"] = full_frame_motion_peak_contamination is not None
    row["full_frame_motion_peak_contamination"] = full_frame_motion_peak_contamination
    row["trusted_bio_motion_peak_delta"] = _trusted_motion_peak_delta(
        row["bio_motion_peak_delta"],
        contaminated=row["full_frame_motion_peak_contaminated"],
    )
    row["trusted_candidate_motion_peak_delta"] = _trusted_motion_peak_delta(
        row["candidate_motion_peak_delta"],
        contaminated=row["full_frame_motion_peak_contaminated"],
        candidate_delta_untrusted=candidate_delta_untrusted,
    )
    row["trusted_semantic_motion_peak_delta"] = _trusted_motion_peak_delta(
        row["semantic_motion_peak_delta"],
        contaminated=row["full_frame_motion_peak_contaminated"],
    )
    row["trusted_resolved_motion_peak_delta"] = _trusted_motion_peak_delta(
        row["resolved_motion_peak_delta"],
        contaminated=row["full_frame_motion_peak_contaminated"],
    )
    row["trusted_effective_resolved_motion_peak_delta"] = _trusted_motion_peak_delta(
        row["effective_resolved_motion_peak_delta"],
        contaminated=row["full_frame_motion_peak_contaminated"],
    )
    row["target_manual_review_required"] = any("_manual_review" in flag for flag in row["target_quality_flags"])
    row["target_manual_review_flags"] = _target_manual_review_flags(row["target_quality_flags"])
    row["target_auto_lock_blocked"] = any("auto_lock_blocked" in flag for flag in row["target_quality_flags"])
    row["target_auto_lock_blocked_flags"] = _target_auto_lock_blocked_flags(row["target_quality_flags"])
    row["target_review_reason_flags"] = _target_review_reason_flags(row["target_quality_flags"])
    return row


def _latest_rows_by_video(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_video: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        video = str(row.get("video") or "").strip()
        if not video:
            video = f"analysis:{row.get('analysis_id') or len(order)}"
        if video not in latest_by_video:
            order.append(video)
        latest_by_video[video] = row
    return [latest_by_video[video] for video in order]


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(row.get("status") or "unknown") for row in rows)
    target_statuses = Counter(str(row.get("target_status") or "unknown") for row in rows)
    tracker_flags = Counter(
        flag
        for row in rows
        for flag in row.get("target_quality_flags", [])
        if str(flag).startswith("person_tracker_")
    )
    target_manual_review_flags = Counter(flag for row in rows for flag in row.get("target_manual_review_flags", []))
    target_auto_lock_blocked_flags = Counter(flag for row in rows for flag in row.get("target_auto_lock_blocked_flags", []))
    target_review_reason_flags = Counter(flag for row in rows for flag in row.get("target_review_reason_flags", []))
    target_tracking_risk_flags = Counter(flag for row in rows for flag in row.get("target_tracking_risk_flags", []))
    semantic_flags = Counter(flag for row in rows for flag in row.get("semantic_flags", []))
    keyframe_flags = Counter(flag for row in rows for flag in row.get("keyframe_candidate_flags", []))
    pose_identity_lock_flags = Counter(
        flag
        for row in rows
        for flag in dict.fromkeys([*row.get("pose_quality_flags", []), *row.get("data_quality_flags", [])])
        if flag in POSE_IDENTITY_LOCK_FLAGS
    )
    actionable_keyframe_flags = Counter(
        flag
        for row in rows
        for flag in row.get("keyframe_candidate_flags", [])
        if flag not in NON_ACTIONABLE_KEYFRAME_CANDIDATE_FLAGS
    )
    data_quality_flags = Counter(flag for row in rows for flag in row.get("data_quality_flags", []))
    semantic_candidate_conflict_decisions = Counter()
    semantic_candidate_conflict_labels = Counter()
    semantic_candidate_conflict_untrusted_reasons = Counter()
    tracker_states = Counter()
    tracker_rejection_reasons = Counter()
    tracker_recovery_counts = Counter()
    for row in rows:
        tracker_states.update(row.get("tracker_state_counts", {}))
        tracker_rejection_reasons.update(row.get("tracker_rejection_reason_counts", {}))
        candidate_conflict = row.get("semantic_candidate_conflict_summary")
        if isinstance(candidate_conflict, dict):
            decision = str(candidate_conflict.get("decision") or "").strip()
            if decision:
                semantic_candidate_conflict_decisions[decision] += 1
            semantic_candidate_conflict_labels.update(
                str(label)
                for label in candidate_conflict.get("diagnostic_labels", [])
                if str(label).strip()
            )
            semantic_candidate_conflict_untrusted_reasons.update(
                str(reason)
                for reason in candidate_conflict.get("untrusted_candidate_reasons", [])
                if str(reason).strip()
            )
        summary = row.get("tracker_sequence_summary") if isinstance(row.get("tracker_sequence_summary"), dict) else {}
        if summary.get("transient_loss_recovered"):
            tracker_recovery_counts["transient_loss_recovered"] += 1
        if summary.get("final_unrecovered"):
            tracker_recovery_counts["final_unrecovered"] += 1
        if isinstance(row.get("tracker_loss_ratio"), (int, float)) and row.get("tracker_loss_ratio") >= TRACKER_HIGH_LOSS_RATIO_THRESHOLD:
            tracker_recovery_counts["high_loss_ratio"] += 1

    completed = [row for row in rows if row.get("status") == "completed"]

    def row_has_tal_evidence(row: dict[str, Any]) -> bool:
        for field in (
            "bio_timestamps",
            "candidate_timestamps",
            "semantic_timestamps",
            "raw_resolved_timestamps",
            "resolved_timestamps",
            "effective_resolved_timestamps",
            "bio_motion_peak_delta",
            "candidate_motion_peak_delta",
            "semantic_motion_peak_delta",
            "resolved_motion_peak_delta",
            "effective_resolved_motion_peak_delta",
            "bio_semantic_delta",
            "bio_resolved_delta",
            "bio_effective_resolved_delta",
            "candidate_semantic_delta",
            "candidate_resolved_delta",
            "candidate_effective_resolved_delta",
        ):
            values = row.get(field)
            if isinstance(values, dict) and any(values.get(key) is not None for key in TAL_KEYS):
                return True
        return False

    def is_tal_metric_row(row: dict[str, Any]) -> bool:
        profile = _analysis_profile(row)
        return profile == "jump" or (profile == "unknown" and row_has_tal_evidence(row))

    completed_jump = [row for row in completed if is_tal_metric_row(row)]
    profile_counts = Counter(_analysis_profile(row) for row in rows)
    completed_profile_counts = Counter(_analysis_profile(row) for row in completed)
    profile_keyframe_coverage_values: dict[str, list[float]] = defaultdict(list)
    profile_keyframe_complete_counts: Counter[str] = Counter()
    for row in completed:
        profile = _analysis_profile(row)
        summary = row.get("profile_keyframe_summary") if isinstance(row.get("profile_keyframe_summary"), dict) else {}
        coverage = summary.get("coverage_score")
        if isinstance(coverage, (int, float)):
            profile_keyframe_coverage_values[profile].append(float(coverage))
        if summary.get("complete"):
            profile_keyframe_complete_counts[profile] += 1
    candidate_delta_untrusted_reasons = Counter(
        reason for row in completed for reason in row.get("candidate_delta_untrusted_reasons", [])
    )
    repeat_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in completed:
        repeat_groups[str(row.get("video") or "")].append(row)
    repeat_summary: list[dict[str, Any]] = []
    for video, group in repeat_groups.items():
        if len(group) < 2:
            continue
        first = group[0]
        for later in group[1:]:
            first_ts = first.get("bio_timestamps", {})
            later_ts = later.get("bio_timestamps", {})
            first_effective_ts = first.get("effective_resolved_timestamps", {})
            later_effective_ts = later.get("effective_resolved_timestamps", {})
            first_resolved_ts = first.get("resolved_timestamps", {})
            later_resolved_ts = later.get("resolved_timestamps", {})
            repeat_summary.append(
                {
                    "video": video,
                    "analysis_id_a": first.get("analysis_id"),
                    "analysis_id_b": later.get("analysis_id"),
                    "pipeline_version_a": first.get("pipeline_version"),
                    "pipeline_version_b": later.get("pipeline_version"),
                    "same_pipeline_version": first.get("pipeline_version") == later.get("pipeline_version"),
                    "force_score_delta": (
                        later.get("force_score") - first.get("force_score")
                        if isinstance(later.get("force_score"), (int, float))
                        and isinstance(first.get("force_score"), (int, float))
                        else None
                    ),
                    "tal_delta": {
                        key: (
                            round((later_ts.get(key) or 0.0) - (first_ts.get(key) or 0.0), 3)
                            if later_ts.get(key) is not None and first_ts.get(key) is not None
                            else None
                        )
                        for key in ("T", "A", "L")
                    },
                    "effective_tal_delta": {
                        key: (
                            round((later_effective_ts.get(key) or 0.0) - (first_effective_ts.get(key) or 0.0), 3)
                            if isinstance(later_effective_ts, dict)
                            and isinstance(first_effective_ts, dict)
                            and later_effective_ts.get(key) is not None
                            and first_effective_ts.get(key) is not None
                            else None
                        )
                        for key in ("T", "A", "L")
                    },
                    "resolved_tal_delta": {
                        key: (
                            round((later_resolved_ts.get(key) or 0.0) - (first_resolved_ts.get(key) or 0.0), 3)
                            if isinstance(later_resolved_ts, dict)
                            and isinstance(first_resolved_ts, dict)
                            and later_resolved_ts.get(key) is not None
                            and first_resolved_ts.get(key) is not None
                            else None
                        )
                        for key in ("T", "A", "L")
                    },
                }
            )

    def tal_completed_rows() -> list[dict[str, Any]]:
        return completed_jump

    def average_abs_delta(key: str, field: str) -> float | None:
        values = [
            abs(row.get(field, {}).get(key))
            for row in tal_completed_rows()
            if isinstance(row.get(field, {}).get(key), (int, float))
        ]
        return round(sum(values) / len(values), 3) if values else None

    def max_abs_delta(key: str, field: str) -> float | None:
        values = [
            abs(row.get(field, {}).get(key))
            for row in tal_completed_rows()
            if isinstance(row.get(field, {}).get(key), (int, float))
        ]
        return round(max(values), 3) if values else None

    def delta_direction_counts(field: str) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for key in ("T", "A", "L"):
            counts = {"within": 0, "early": 0, "late": 0, "missing": 0}
            for row in tal_completed_rows():
                status = row.get(field, {}).get(key) if isinstance(row.get(field), dict) else None
                if status in counts:
                    counts[str(status)] += 1
                else:
                    counts["missing"] += 1
            out[key] = counts
        return out

    def profile_keyframe_average_coverage() -> dict[str, float | None]:
        return {
            profile: (
                round(sum(values) / len(values), 4)
                if values
                else None
            )
            for profile, values in sorted(profile_keyframe_coverage_values.items())
        }

    def profile_keyframe_complete_rate() -> dict[str, float | None]:
        return {
            profile: (
                round(profile_keyframe_complete_counts.get(profile, 0) / count, 4)
                if count
                else None
            )
            for profile, count in sorted(completed_profile_counts.items())
        }

    def repeat_extrema(*, same_pipeline_only: bool = False) -> dict[str, Any]:
        tal_values: dict[str, list[float]] = defaultdict(list)
        effective_tal_values: dict[str, list[float]] = defaultdict(list)
        resolved_tal_values: dict[str, list[float]] = defaultdict(list)
        force_values: list[float] = []
        for item in repeat_summary:
            if same_pipeline_only and item.get("same_pipeline_version") is not True:
                continue
            if isinstance(item.get("force_score_delta"), (int, float)):
                force_values.append(abs(float(item["force_score_delta"])))
            tal_delta = item.get("tal_delta") if isinstance(item.get("tal_delta"), dict) else {}
            for key in ("T", "A", "L"):
                value = tal_delta.get(key)
                if isinstance(value, (int, float)):
                    tal_values[key].append(abs(float(value)))
            effective_tal_delta = item.get("effective_tal_delta") if isinstance(item.get("effective_tal_delta"), dict) else {}
            for key in ("T", "A", "L"):
                value = effective_tal_delta.get(key)
                if isinstance(value, (int, float)):
                    effective_tal_values[key].append(abs(float(value)))
            resolved_tal_delta = item.get("resolved_tal_delta") if isinstance(item.get("resolved_tal_delta"), dict) else {}
            for key in ("T", "A", "L"):
                value = resolved_tal_delta.get(key)
                if isinstance(value, (int, float)):
                    resolved_tal_values[key].append(abs(float(value)))
        return {
            "max_abs_force_score_delta": round(max(force_values), 3) if force_values else None,
            "max_abs_tal_delta": {
                key: round(max(tal_values[key]), 3) if tal_values.get(key) else None
                for key in ("T", "A", "L")
            },
            "max_abs_effective_tal_delta": {
                key: round(max(effective_tal_values[key]), 3) if effective_tal_values.get(key) else None
                for key in ("T", "A", "L")
            },
            "max_abs_resolved_tal_delta": {
                key: round(max(resolved_tal_values[key]), 3) if resolved_tal_values.get(key) else None
                for key in ("T", "A", "L")
            },
        }

    def average_row_value(field: str) -> float | None:
        values = [row.get(field) for row in rows if isinstance(row.get(field), (int, float))]
        return round(sum(float(value) for value in values) / len(values), 4) if values else None

    def max_row_value(field: str) -> float | None:
        values = [row.get(field) for row in rows if isinstance(row.get(field), (int, float))]
        return round(max(float(value) for value in values), 4) if values else None

    def average_candidate_value(field: str) -> float | None:
        values = []
        for row in rows:
            candidate = row.get("target_selected_candidate")
            if not isinstance(candidate, dict):
                continue
            value = candidate.get(field)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return round(sum(values) / len(values), 4) if values else None

    def max_candidate_value(field: str) -> float | None:
        values = []
        for row in rows:
            candidate = row.get("target_selected_candidate")
            if not isinstance(candidate, dict):
                continue
            value = candidate.get(field)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return round(max(values), 4) if values else None

    def manual_review_samples(limit: int = 20) -> list[dict[str, Any]]:
        samples = []
        for row in rows:
            if not row.get("target_manual_review_required"):
                continue
            candidate = row.get("target_selected_candidate") if isinstance(row.get("target_selected_candidate"), dict) else {}
            samples.append(
                {
                    "video": row.get("video"),
                    "analysis_id": row.get("analysis_id"),
                    "target_status": row.get("target_status"),
                    "lock_confidence": row.get("target_lock_confidence"),
                    "candidate_count": row.get("target_preview_candidate_count"),
                    "selected_candidate_id": row.get("target_selected_candidate_id"),
                    "manual_review_flags": row.get("target_manual_review_flags"),
                    "auto_lock_blocked_flags": row.get("target_auto_lock_blocked_flags"),
                    "review_reason_flags": row.get("target_review_reason_flags"),
                    "support_count": candidate.get("support_count"),
                    "support_frame_count": candidate.get("support_frame_count"),
                    "support_confidence": candidate.get("support_confidence"),
                    "support_center_span": candidate.get("support_center_span"),
                    "support_avg_area": candidate.get("support_avg_area"),
                    "support_motion_anchor_hits": candidate.get("support_motion_anchor_hits"),
                    "multiperson_ambiguous_frame_count": candidate.get("multiperson_ambiguous_frame_count"),
                    "multiperson_competitor_count": candidate.get("multiperson_competitor_count"),
                    "multiperson_same_anchor_competitor_count": candidate.get("multiperson_same_anchor_competitor_count"),
                    "multiperson_selected_pair_frame_count": candidate.get("multiperson_selected_pair_frame_count"),
                    "multiperson_other_frame_ambiguous_count": candidate.get("multiperson_other_frame_ambiguous_count"),
                    "multiperson_nearest_center_distance": candidate.get("multiperson_nearest_center_distance"),
                    "multiperson_max_competitor_confidence": candidate.get("multiperson_max_competitor_confidence"),
                }
            )
        return samples[:limit]

    def target_tracking_risk_samples(limit: int = 20) -> list[dict[str, Any]]:
        samples = []
        for row in rows:
            risk_flags = row.get("target_tracking_risk_flags")
            if not isinstance(risk_flags, list) or not risk_flags:
                continue
            candidate = row.get("target_selected_candidate") if isinstance(row.get("target_selected_candidate"), dict) else {}
            summary = row.get("tracker_sequence_summary") if isinstance(row.get("tracker_sequence_summary"), dict) else {}
            total_frames = _safe_float(summary.get("total_frames"))
            loss_frames = _safe_float(summary.get("loss_frames"))
            samples.append(
                {
                    "video": row.get("video"),
                    "analysis_id": row.get("analysis_id"),
                    "analysis_profile": row.get("analysis_profile"),
                    "risk_flags": risk_flags,
                    "pose_tracked_ratio": row.get("pose_tracked_ratio"),
                    "tracker_loss_ratio": (
                        round(loss_frames / total_frames, 4)
                        if loss_frames is not None and total_frames is not None and total_frames > 0
                        else None
                    ),
                    "tracker_state_counts": row.get("tracker_state_counts"),
                    "bbox_area": candidate.get("bbox_area"),
                    "bbox_height": candidate.get("bbox_height"),
                    "bbox_width": candidate.get("bbox_width"),
                    "support_frame_count": candidate.get("support_frame_count"),
                    "support_confidence": candidate.get("support_confidence"),
                    "multiperson_competitor_count": candidate.get("multiperson_competitor_count"),
                    "manual_review_flags": row.get("target_manual_review_flags"),
                    "tracker_rejection_reason_counts": row.get("tracker_rejection_reason_counts"),
                }
            )
        return samples[:limit]

    def tracker_loss_samples(limit: int = 20) -> list[dict[str, Any]]:
        samples = []
        for row in completed:
            loss_ratio = row.get("tracker_loss_ratio")
            final_unrecovered = bool(row.get("tracker_final_unrecovered"))
            transient_recovered = bool(row.get("tracker_transient_loss_recovered"))
            if not final_unrecovered and not transient_recovered and not isinstance(loss_ratio, (int, float)):
                continue
            if isinstance(loss_ratio, (int, float)) and loss_ratio <= 0.0 and not final_unrecovered:
                continue
            samples.append(
                {
                    "video": row.get("video"),
                    "analysis_id": row.get("analysis_id"),
                    "pose_tracked_ratio": row.get("pose_tracked_ratio"),
                    "tracker_loss_ratio": loss_ratio,
                    "tracker_loss_frames": row.get("tracker_loss_frames"),
                    "tracker_total_frames": row.get("tracker_total_frames"),
                    "tracker_final_unrecovered": final_unrecovered,
                    "tracker_transient_loss_recovered": transient_recovered,
                    "tracker_state_counts": row.get("tracker_state_counts"),
                    "tracker_rejection_reason_counts": row.get("tracker_rejection_reason_counts"),
                    "target_manual_review_flags": row.get("target_manual_review_flags"),
                    "target_selected_candidate_id": row.get("target_selected_candidate_id"),
                }
            )
        samples.sort(
            key=lambda item: (
                1 if item.get("tracker_final_unrecovered") else 0,
                float(item.get("tracker_loss_ratio") or 0.0),
                0.0 - float(item.get("pose_tracked_ratio") or 0.0),
            ),
            reverse=True,
        )
        return samples[:limit]

    def pose_identity_lock_samples(limit: int = 20) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for row in rows:
            flags = [
                flag
                for flag in [*row.get("pose_quality_flags", []), *row.get("data_quality_flags", [])]
                if flag in POSE_IDENTITY_LOCK_FLAGS
            ]
            target_flags = [
                flag
                for flag in row.get("target_quality_flags", [])
                if flag in CORE_TRACKER_FLAGS or str(flag).startswith("person_tracker_manual_lock_")
            ] if isinstance(row.get("target_quality_flags"), list) else []
            if not flags and not any(str(flag).startswith("person_tracker_manual_lock_") for flag in target_flags):
                continue
            samples.append(
                {
                    "video": row.get("video"),
                    "analysis_id": row.get("analysis_id"),
                    "status": row.get("status"),
                    "analysis_profile": row.get("analysis_profile"),
                    "pose_identity_lock_flags": list(dict.fromkeys(flags)),
                    "target_quality_flags": target_flags,
                    "pose_tracked_ratio": row.get("pose_tracked_ratio"),
                    "tracker_loss_ratio": row.get("tracker_loss_ratio"),
                    "tracker_state_counts": row.get("tracker_state_counts"),
                    "tracker_rejection_reason_counts": row.get("tracker_rejection_reason_counts"),
                }
            )
        return samples[:limit]

    def full_frame_motion_peak_contamination_samples(limit: int = 20) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for row in completed:
            contamination = row.get("full_frame_motion_peak_contamination")
            if not isinstance(contamination, dict):
                continue
            samples.append(
                {
                    "video": row.get("video"),
                    "analysis_id": row.get("analysis_id"),
                    "peak_timestamp": contamination.get("peak_timestamp"),
                    "peak_motion_score": contamination.get("peak_motion_score"),
                    "core_window": contamination.get("core_window"),
                    "core_peak_motion_score": contamination.get("core_peak_motion_score"),
                    "peak_to_core_ratio": contamination.get("peak_to_core_ratio"),
                    "lead_sec": contamination.get("lead_sec"),
                    "offset_sec": contamination.get("offset_sec"),
                    "direction": contamination.get("direction"),
                    "risk_flags": contamination.get("risk_flags"),
                    "semantic_timestamps": row.get("semantic_timestamps"),
                    "resolved_timestamps": row.get("resolved_timestamps"),
                }
            )
        samples.sort(
            key=lambda item: (
                float(item.get("peak_to_core_ratio") or 0.0),
                float(item.get("offset_sec") or abs(float(item.get("lead_sec") or 0.0))),
            ),
            reverse=True,
        )
        return samples[:limit]

    def profile_keyframe_samples(limit: int = 20) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for row in completed:
            summary = row.get("profile_keyframe_summary") if isinstance(row.get("profile_keyframe_summary"), dict) else {}
            if summary.get("complete"):
                continue
            samples.append(
                {
                    "video": row.get("video"),
                    "analysis_id": row.get("analysis_id"),
                    "analysis_profile": _analysis_profile(row),
                    "expected_keys": summary.get("expected_keys"),
                    "present_keys": summary.get("present_keys"),
                    "missing_keys": summary.get("missing_keys"),
                    "coverage_score": summary.get("coverage_score"),
                    "semantic_flags": row.get("semantic_flags"),
                    "target_quality_flags": row.get("target_quality_flags"),
                }
            )
        samples.sort(
            key=lambda item: (
                float(item.get("coverage_score") or 0.0),
                str(item.get("analysis_profile") or ""),
                str(item.get("video") or ""),
            )
        )
        return samples[:limit]

    return {
        "total": len(rows),
        "status_counts": dict(statuses),
        "target_status_counts": dict(target_statuses),
        "completed": len(completed),
        "analysis_profile_counts": dict(profile_counts),
        "completed_analysis_profile_counts": dict(completed_profile_counts),
        "tal_metric_profile": "jump",
        "tal_metric_completed_count": len(completed_jump),
        "profile_keyframe_average_coverage": profile_keyframe_average_coverage(),
        "profile_keyframe_complete_rate": profile_keyframe_complete_rate(),
        "profile_keyframe_incomplete_samples": profile_keyframe_samples(),
        "awaiting_target_selection": statuses.get("awaiting_target_selection", 0),
        "target_preview_refreshed_count": sum(1 for row in rows if row.get("target_preview_refreshed")),
        "target_manual_review_required_count": sum(1 for row in rows if row.get("target_manual_review_required")),
        "target_auto_lock_blocked_count": sum(1 for row in rows if row.get("target_auto_lock_blocked")),
        "target_tracking_risk_count": sum(1 for row in rows if row.get("target_tracking_risk_flags")),
        "top_target_manual_review_flags": target_manual_review_flags.most_common(20),
        "top_target_auto_lock_blocked_flags": target_auto_lock_blocked_flags.most_common(20),
        "top_target_review_reason_flags": target_review_reason_flags.most_common(20),
        "top_target_tracking_risk_flags": target_tracking_risk_flags.most_common(20),
        "target_lock_confidence_summary": {
            "average": average_row_value("target_lock_confidence"),
            "max": max_row_value("target_lock_confidence"),
        },
        "target_preview_candidate_count_summary": {
            "average": average_row_value("target_preview_candidate_count"),
            "max": max_row_value("target_preview_candidate_count"),
        },
        "target_selected_candidate_metric_summary": {
            field: {
                "average": average_candidate_value(field),
                "max": max_candidate_value(field),
            }
            for field in (
                "bbox_area",
                "bbox_width",
                "bbox_height",
                "bbox_aspect",
                "support_count",
                "support_frame_count",
                "support_confidence",
                "support_center_span",
                "support_avg_area",
                "support_motion_anchor_hits",
                "multiperson_ambiguous_frame_count",
                "multiperson_competitor_count",
                "multiperson_same_anchor_competitor_count",
                "multiperson_selected_pair_frame_count",
                "multiperson_other_frame_ambiguous_count",
                "multiperson_nearest_center_distance",
                "multiperson_max_competitor_confidence",
            )
        },
        "target_manual_review_samples": manual_review_samples(),
        "target_tracking_risk_samples": target_tracking_risk_samples(),
        "top_tracker_flags": tracker_flags.most_common(30),
        "core_tracker_flag_counts": {flag: tracker_flags.get(flag, 0) for flag in sorted(CORE_TRACKER_FLAGS)},
        "pose_identity_lock_flag_counts": {flag: pose_identity_lock_flags.get(flag, 0) for flag in sorted(POSE_IDENTITY_LOCK_FLAGS)},
        "pose_identity_lock_samples": pose_identity_lock_samples(),
        "tracker_state_counts": dict(tracker_states),
        "top_tracker_rejection_reasons": tracker_rejection_reasons.most_common(30),
        "tracker_recovery_counts": dict(tracker_recovery_counts),
        "tracker_loss_summary": {
            "target_lost_flag_count": tracker_flags.get("person_tracker_target_lost", 0),
            "transient_loss_recovered_count": tracker_recovery_counts.get("transient_loss_recovered", 0),
            "final_unrecovered_count": tracker_recovery_counts.get("final_unrecovered", 0),
            "high_loss_ratio_count": tracker_recovery_counts.get("high_loss_ratio", 0),
            "high_loss_ratio_threshold": TRACKER_HIGH_LOSS_RATIO_THRESHOLD,
        },
        "tracker_loss_samples": tracker_loss_samples(),
        "full_frame_motion_peak_contaminated_count": sum(
            1 for row in completed if row.get("full_frame_motion_peak_contaminated")
        ),
        "full_frame_motion_peak_contamination_samples": full_frame_motion_peak_contamination_samples(),
        "candidate_motion_contaminated_count": sum(1 for row in completed if row.get("candidate_motion_contaminated")),
        "candidate_delta_untrusted_count": sum(1 for row in completed if row.get("candidate_delta_untrusted")),
        "top_candidate_delta_untrusted_reasons": candidate_delta_untrusted_reasons.most_common(30),
        "top_semantic_retry_flags": semantic_flags.most_common(40),
        "semantic_candidate_conflict_decision_counts": semantic_candidate_conflict_decisions.most_common(30),
        "semantic_candidate_conflict_label_counts": semantic_candidate_conflict_labels.most_common(30),
        "semantic_candidate_conflict_untrusted_reason_counts": semantic_candidate_conflict_untrusted_reasons.most_common(30),
        "top_keyframe_candidate_flags": keyframe_flags.most_common(30),
        "top_actionable_keyframe_candidate_flags": actionable_keyframe_flags.most_common(30),
        "top_data_quality_flags": data_quality_flags.most_common(50),
        "average_abs_bio_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "bio_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_candidate_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "candidate_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_semantic_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "semantic_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_resolved_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "resolved_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_effective_resolved_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "effective_resolved_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_trusted_bio_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "trusted_bio_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_trusted_candidate_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "trusted_candidate_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_trusted_semantic_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "trusted_semantic_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_trusted_resolved_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "trusted_resolved_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_trusted_effective_resolved_to_nearest_motion_peak_delta": {
            key: average_abs_delta(key, "trusted_effective_resolved_motion_peak_delta") for key in ("T", "A", "L")
        },
        "average_abs_bio_minus_semantic_delta": {
            key: average_abs_delta(key, "bio_semantic_delta") for key in ("T", "A", "L")
        },
        "average_abs_bio_minus_resolved_delta": {
            key: average_abs_delta(key, "bio_resolved_delta") for key in ("T", "A", "L")
        },
        "average_abs_bio_minus_effective_resolved_delta": {
            key: average_abs_delta(key, "bio_effective_resolved_delta") for key in ("T", "A", "L")
        },
        "average_abs_candidate_minus_semantic_delta": {
            key: average_abs_delta(key, "candidate_semantic_delta") for key in ("T", "A", "L")
        },
        "average_abs_candidate_minus_resolved_delta": {
            key: average_abs_delta(key, "candidate_resolved_delta") for key in ("T", "A", "L")
        },
        "average_abs_candidate_minus_effective_resolved_delta": {
            key: average_abs_delta(key, "candidate_effective_resolved_delta") for key in ("T", "A", "L")
        },
        "average_abs_trusted_candidate_minus_semantic_delta": {
            key: average_abs_delta(key, "trusted_candidate_semantic_delta") for key in ("T", "A", "L")
        },
        "average_abs_trusted_candidate_minus_resolved_delta": {
            key: average_abs_delta(key, "trusted_candidate_resolved_delta") for key in ("T", "A", "L")
        },
        "average_abs_trusted_candidate_minus_effective_resolved_delta": {
            key: average_abs_delta(key, "trusted_candidate_effective_resolved_delta") for key in ("T", "A", "L")
        },
        "max_abs_bio_minus_semantic_delta": {
            key: max_abs_delta(key, "bio_semantic_delta") for key in ("T", "A", "L")
        },
        "max_abs_bio_minus_resolved_delta": {
            key: max_abs_delta(key, "bio_resolved_delta") for key in ("T", "A", "L")
        },
        "max_abs_bio_minus_effective_resolved_delta": {
            key: max_abs_delta(key, "bio_effective_resolved_delta") for key in ("T", "A", "L")
        },
        "max_abs_candidate_minus_semantic_delta": {
            key: max_abs_delta(key, "candidate_semantic_delta") for key in ("T", "A", "L")
        },
        "max_abs_candidate_minus_resolved_delta": {
            key: max_abs_delta(key, "candidate_resolved_delta") for key in ("T", "A", "L")
        },
        "max_abs_candidate_minus_effective_resolved_delta": {
            key: max_abs_delta(key, "candidate_effective_resolved_delta") for key in ("T", "A", "L")
        },
        "max_abs_trusted_candidate_minus_semantic_delta": {
            key: max_abs_delta(key, "trusted_candidate_semantic_delta") for key in ("T", "A", "L")
        },
        "max_abs_trusted_candidate_minus_resolved_delta": {
            key: max_abs_delta(key, "trusted_candidate_resolved_delta") for key in ("T", "A", "L")
        },
        "max_abs_trusted_candidate_minus_effective_resolved_delta": {
            key: max_abs_delta(key, "trusted_candidate_effective_resolved_delta") for key in ("T", "A", "L")
        },
        "bio_semantic_delta_direction_counts": delta_direction_counts("bio_semantic_delta_status"),
        "bio_resolved_delta_direction_counts": delta_direction_counts("bio_resolved_delta_status"),
        "bio_effective_resolved_delta_direction_counts": delta_direction_counts("bio_effective_resolved_delta_status"),
        "candidate_semantic_delta_direction_counts": delta_direction_counts("candidate_semantic_delta_status"),
        "candidate_resolved_delta_direction_counts": delta_direction_counts("candidate_resolved_delta_status"),
        "candidate_effective_resolved_delta_direction_counts": delta_direction_counts(
            "candidate_effective_resolved_delta_status"
        ),
        "trusted_candidate_semantic_delta_direction_counts": delta_direction_counts("trusted_candidate_semantic_delta_status"),
        "trusted_candidate_resolved_delta_direction_counts": delta_direction_counts("trusted_candidate_resolved_delta_status"),
        "trusted_candidate_effective_resolved_delta_direction_counts": delta_direction_counts(
            "trusted_candidate_effective_resolved_delta_status"
        ),
        "repeat_summary": repeat_summary,
        "repeat_extrema": repeat_extrema(),
        "repeat_extrema_same_pipeline": repeat_extrema(same_pipeline_only=True),
    }


def _write_outputs(output_dir: Path, label: str, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{label}-diagnostics.json"
    md_path = output_dir / f"{label}-diagnostics.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    aggregate = payload["aggregate"]
    unique_aggregate = payload.get("unique_by_video_aggregate")
    unique_lines: list[str] = []
    if isinstance(unique_aggregate, dict):
        unique_lines = [
            "## Unique By Video Summary",
            "",
            json.dumps(
                {
                    "total": unique_aggregate.get("total"),
                    "completed": unique_aggregate.get("completed"),
                    "awaiting_target_selection": unique_aggregate.get("awaiting_target_selection"),
                    "status_counts": unique_aggregate.get("status_counts"),
                    "target_status_counts": unique_aggregate.get("target_status_counts"),
                    "analysis_profile_counts": unique_aggregate.get("analysis_profile_counts"),
                    "completed_analysis_profile_counts": unique_aggregate.get(
                        "completed_analysis_profile_counts"
                    ),
                    "tal_metric_completed_count": unique_aggregate.get("tal_metric_completed_count"),
                    "profile_keyframe_average_coverage": unique_aggregate.get(
                        "profile_keyframe_average_coverage"
                    ),
                    "profile_keyframe_complete_rate": unique_aggregate.get("profile_keyframe_complete_rate"),
                    "target_manual_review_required_count": unique_aggregate.get(
                        "target_manual_review_required_count"
                    ),
                    "target_tracking_risk_count": unique_aggregate.get("target_tracking_risk_count"),
                    "core_tracker_flag_counts": unique_aggregate.get("core_tracker_flag_counts"),
                    "pose_identity_lock_flag_counts": unique_aggregate.get("pose_identity_lock_flag_counts"),
                    "top_semantic_retry_flags": unique_aggregate.get("top_semantic_retry_flags"),
                    "candidate_semantic_delta_direction_counts": unique_aggregate.get(
                        "candidate_semantic_delta_direction_counts"
                    ),
                    "candidate_effective_resolved_delta_direction_counts": unique_aggregate.get(
                        "candidate_effective_resolved_delta_direction_counts"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "",
        ]
    lines = [
        "# API Batch Diagnostics",
        "",
        f"- Label: {label}",
        f"- Generated: {payload['generated_at']}",
        f"- Total rows: {aggregate['total']}",
        f"- Unique videos: {unique_aggregate['total'] if isinstance(unique_aggregate, dict) else aggregate['total']}",
        f"- Completed: {aggregate['completed']}",
        f"- TAL metric profile: {aggregate['tal_metric_profile']}",
        f"- TAL metric completed count: {aggregate['tal_metric_completed_count']}",
        "- Non-jump keyframes are evaluated by profile coverage, not by T/A/L.",
        f"- Awaiting target selection: {aggregate['awaiting_target_selection']}",
        f"- Target manual review required: {aggregate['target_manual_review_required_count']}",
        f"- Target auto-lock blocked: {aggregate['target_auto_lock_blocked_count']}",
        f"- Target tracking risk: {aggregate['target_tracking_risk_count']}",
        f"- Full-frame motion peak contaminated: {aggregate['full_frame_motion_peak_contaminated_count']}",
        f"- Candidate motion contaminated: {aggregate['candidate_motion_contaminated_count']}",
        f"- Candidate delta untrusted: {aggregate['candidate_delta_untrusted_count']}",
        "",
        "## Status Counts",
        "",
        json.dumps(aggregate["status_counts"], ensure_ascii=False, indent=2),
        "",
        "## Target Lock Status Counts",
        "",
        json.dumps(aggregate["target_status_counts"], ensure_ascii=False, indent=2),
        "",
        "## Analysis Profile Counts",
        "",
        json.dumps(aggregate["analysis_profile_counts"], ensure_ascii=False, indent=2),
        "",
        "## Completed Analysis Profile Counts",
        "",
        json.dumps(aggregate["completed_analysis_profile_counts"], ensure_ascii=False, indent=2),
        "",
        "## Profile Keyframe Coverage",
        "",
        json.dumps(
            {
                "average_coverage": aggregate["profile_keyframe_average_coverage"],
                "complete_rate": aggregate["profile_keyframe_complete_rate"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Profile Keyframe Incomplete Samples",
        "",
        json.dumps(aggregate["profile_keyframe_incomplete_samples"], ensure_ascii=False, indent=2),
        "",
        *unique_lines,
        "## Target Manual Review Flags",
        "",
        json.dumps(aggregate["top_target_manual_review_flags"], ensure_ascii=False, indent=2),
        "",
        "## Target Auto-Lock Blocked Flags",
        "",
        json.dumps(aggregate["top_target_auto_lock_blocked_flags"], ensure_ascii=False, indent=2),
        "",
        "## Target Review Reason Flags",
        "",
        json.dumps(aggregate["top_target_review_reason_flags"], ensure_ascii=False, indent=2),
        "",
        "## Target Tracking Risk Flags",
        "",
        json.dumps(aggregate["top_target_tracking_risk_flags"], ensure_ascii=False, indent=2),
        "",
        "## Target Candidate Metrics",
        "",
        json.dumps(aggregate["target_selected_candidate_metric_summary"], ensure_ascii=False, indent=2),
        "",
        "## Target Manual Review Samples",
        "",
        json.dumps(aggregate["target_manual_review_samples"], ensure_ascii=False, indent=2),
        "",
        "## Target Tracking Risk Samples",
        "",
        json.dumps(aggregate["target_tracking_risk_samples"], ensure_ascii=False, indent=2),
        "",
        "## Core Tracker Flags",
        "",
        json.dumps(aggregate["core_tracker_flag_counts"], ensure_ascii=False, indent=2),
        "",
        "## Pose Identity Lock Flags",
        "",
        json.dumps(
            {
                "counts": aggregate["pose_identity_lock_flag_counts"],
                "samples": aggregate["pose_identity_lock_samples"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Top Tracker Flags",
        "",
        json.dumps(aggregate["top_tracker_flags"], ensure_ascii=False, indent=2),
        "",
        "## Tracker Loss Summary",
        "",
        json.dumps(aggregate["tracker_loss_summary"], ensure_ascii=False, indent=2),
        "",
        "## Tracker Loss Samples",
        "",
        json.dumps(aggregate["tracker_loss_samples"], ensure_ascii=False, indent=2),
        "",
        "## Full-Frame Motion Peak Contamination Samples",
        "",
        json.dumps(aggregate["full_frame_motion_peak_contamination_samples"], ensure_ascii=False, indent=2),
        "",
        "## Top Tracker Rejection Reasons",
        "",
        json.dumps(aggregate["top_tracker_rejection_reasons"], ensure_ascii=False, indent=2),
        "",
        "## Top Semantic/Retry Flags",
        "",
        json.dumps(aggregate["top_semantic_retry_flags"], ensure_ascii=False, indent=2),
        "",
        "## Semantic Candidate Conflict Decisions",
        "",
        json.dumps(aggregate["semantic_candidate_conflict_decision_counts"], ensure_ascii=False, indent=2),
        "",
        "## Semantic Candidate Conflict Labels",
        "",
        json.dumps(aggregate["semantic_candidate_conflict_label_counts"], ensure_ascii=False, indent=2),
        "",
        "## Semantic Candidate Conflict Untrusted Reasons",
        "",
        json.dumps(aggregate["semantic_candidate_conflict_untrusted_reason_counts"], ensure_ascii=False, indent=2),
        "",
        "## Top Keyframe Candidate Flags",
        "",
        json.dumps(aggregate["top_keyframe_candidate_flags"], ensure_ascii=False, indent=2),
        "",
        "## Top Actionable Keyframe Candidate Flags",
        "",
        json.dumps(aggregate["top_actionable_keyframe_candidate_flags"], ensure_ascii=False, indent=2),
        "",
        "## Top Candidate Delta Untrusted Reasons",
        "",
        json.dumps(aggregate["top_candidate_delta_untrusted_reasons"], ensure_ascii=False, indent=2),
        "",
        "## Top Data Quality Flags",
        "",
        json.dumps(aggregate["top_data_quality_flags"], ensure_ascii=False, indent=2),
        "",
        "## Avg |Bio - Nearest Motion Peak| Seconds",
        "",
        json.dumps(aggregate["average_abs_bio_to_nearest_motion_peak_delta"], ensure_ascii=False, indent=2),
        "",
        "## Avg |Candidate - Nearest Motion Peak| Seconds",
        "",
        json.dumps(aggregate["average_abs_candidate_to_nearest_motion_peak_delta"], ensure_ascii=False, indent=2),
        "",
        "## Avg |Semantic - Nearest Motion Peak| Seconds",
        "",
        json.dumps(aggregate["average_abs_semantic_to_nearest_motion_peak_delta"], ensure_ascii=False, indent=2),
        "",
        "## Avg |Resolved - Nearest Motion Peak| Seconds",
        "",
        json.dumps(aggregate["average_abs_resolved_to_nearest_motion_peak_delta"], ensure_ascii=False, indent=2),
        "",
        "## Avg |Effective Resolved - Nearest Motion Peak| Seconds",
        "",
        json.dumps(
            aggregate["average_abs_effective_resolved_to_nearest_motion_peak_delta"],
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Trusted Avg |Bio - Nearest Motion Peak| Seconds",
        "",
        json.dumps(aggregate["average_abs_trusted_bio_to_nearest_motion_peak_delta"], ensure_ascii=False, indent=2),
        "",
        "## Trusted Avg |Candidate - Nearest Motion Peak| Seconds",
        "",
        json.dumps(aggregate["average_abs_trusted_candidate_to_nearest_motion_peak_delta"], ensure_ascii=False, indent=2),
        "",
        "## Trusted Avg |Semantic - Nearest Motion Peak| Seconds",
        "",
        json.dumps(aggregate["average_abs_trusted_semantic_to_nearest_motion_peak_delta"], ensure_ascii=False, indent=2),
        "",
        "## Trusted Avg |Resolved - Nearest Motion Peak| Seconds",
        "",
        json.dumps(aggregate["average_abs_trusted_resolved_to_nearest_motion_peak_delta"], ensure_ascii=False, indent=2),
        "",
        "## Trusted Avg |Effective Resolved - Nearest Motion Peak| Seconds",
        "",
        json.dumps(
            aggregate["average_abs_trusted_effective_resolved_to_nearest_motion_peak_delta"],
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Bio - Semantic Delta Direction",
        "",
        json.dumps(aggregate["bio_semantic_delta_direction_counts"], ensure_ascii=False, indent=2),
        "",
        "## Bio - Resolved Delta Direction (True Semantic Selection)",
        "",
        json.dumps(aggregate["bio_resolved_delta_direction_counts"], ensure_ascii=False, indent=2),
        "",
        "## Bio - Effective Resolved Delta Direction (Final Output/Fallback)",
        "",
        json.dumps(aggregate["bio_effective_resolved_delta_direction_counts"], ensure_ascii=False, indent=2),
        "",
        "## Candidate - Semantic Delta Direction",
        "",
        json.dumps(aggregate["candidate_semantic_delta_direction_counts"], ensure_ascii=False, indent=2),
        "",
        "## Candidate - Resolved Delta Direction (True Semantic Selection)",
        "",
        json.dumps(aggregate["candidate_resolved_delta_direction_counts"], ensure_ascii=False, indent=2),
        "",
        "## Candidate - Effective Resolved Delta Direction (Final Output/Fallback)",
        "",
        json.dumps(aggregate["candidate_effective_resolved_delta_direction_counts"], ensure_ascii=False, indent=2),
        "",
        "## Trusted Candidate - Semantic Delta Direction",
        "",
        json.dumps(aggregate["trusted_candidate_semantic_delta_direction_counts"], ensure_ascii=False, indent=2),
        "",
        "## Trusted Candidate - Resolved Delta Direction (True Semantic Selection)",
        "",
        json.dumps(aggregate["trusted_candidate_resolved_delta_direction_counts"], ensure_ascii=False, indent=2),
        "",
        "## Trusted Candidate - Effective Resolved Delta Direction (Final Output/Fallback)",
        "",
        json.dumps(
            aggregate["trusted_candidate_effective_resolved_delta_direction_counts"],
            ensure_ascii=False,
            indent=2,
        ),
        "",
        "## Repeat Summary",
        "",
        json.dumps(aggregate["repeat_summary"], ensure_ascii=False, indent=2),
        "",
        "## Repeat Extrema",
        "",
        json.dumps(aggregate["repeat_extrema"], ensure_ascii=False, indent=2),
        "",
        "## Repeat Extrema Same Pipeline",
        "",
        json.dumps(aggregate["repeat_extrema_same_pipeline"], ensure_ascii=False, indent=2),
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Summarize keyframe/tracker diagnostics from API batch JSON files.")
    parser.add_argument("batch_json", nargs="+", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default=datetime.now().strftime("diagnostics-%Y%m%d-%H%M%S"))
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--skip-fetch", action="store_true", help="Use only summary rows in batch JSON; less detailed.")
    parser.add_argument(
        "--refresh-target-preview",
        action="store_true",
        help="Fetch current target-preview diagnostics for each analysis and summarize those target-lock flags/candidates.",
    )
    args = parser.parse_args()

    items = _batch_items(args.batch_json)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in items:
        analysis_id = str(item.get("analysis_id") or "")
        try:
            if args.skip_fetch and item.get("_precomputed_diagnostics"):
                row = _normalize_precomputed_row(item)
                row.pop("_precomputed_diagnostics", None)
                rows.append(row)
                continue
            analysis = item if args.skip_fetch or not analysis_id else _get_json(args.base_url, f"/api/analysis/{analysis_id}", timeout=args.timeout)
            if args.refresh_target_preview and analysis_id and not args.skip_fetch:
                preview = _get_json(args.base_url, f"/api/analysis/{analysis_id}/target-preview", timeout=args.timeout)
                analysis = _with_refreshed_target_preview(analysis, preview)
            rows.append(_analysis_row(item, analysis))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            failures.append(
                {
                    "video": item.get("video"),
                    "analysis_id": analysis_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    unique_rows = _latest_rows_by_video(rows)
    payload = {
        "label": args.label,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "batch_files": [str(path) for path in args.batch_json],
        "aggregate": _aggregate(rows),
        "unique_by_video_aggregate": _aggregate(unique_rows),
        "unique_by_video_rows": unique_rows,
        "rows": rows,
        "fetch_failures": failures,
    }
    _write_outputs(args.output_dir, args.label, payload)
    print(
        json.dumps(
            {
                "aggregate": payload["aggregate"],
                "unique_by_video_aggregate": payload["unique_by_video_aggregate"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    if failures:
        print(json.dumps({"fetch_failures": failures}, ensure_ascii=False, indent=2), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
