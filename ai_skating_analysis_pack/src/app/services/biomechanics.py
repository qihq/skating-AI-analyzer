"""花滑生物力学指标计算。

职责: 从姿态关键点估算关键帧、跳跃指标、专项指标与五维生物力学子分。
输入: MediaPipe 风格 pose_data、动作类型、分析 profile 与采样时间上下文。
输出: 可持久化的 bio_data 字典，包含 quality_flags、jump_metrics 和 sampling_context。
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np

from app.services.keyframe_candidates import detect_key_frame_candidates


DEFAULT_EFFECTIVE_FPS = 5.0
MAX_AIR_TIME_SECONDS = 1.5
MAX_HEIGHT_CM = 120.0
MAX_TAKEOFF_SPEED_MPS = 6.5
MAX_ROTATION_RPS = 6.0
KEYFRAME_CANDIDATE_RESTORE_BLOCKING_FLAGS = {
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "keyframe_candidates_motion_fallback_tail_window",
    "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
    "keyframe_candidates_motion_fallback_takeoff_anchor_tail_window",
    "tal_candidate_apex_landing_gap_compressed",
    "tal_candidate_apex_landing_gap_unreliable",
    "tal_candidate_compressed_temporal_geometry",
    "tal_candidate_core_gap_compressed",
    "tal_candidate_landing_geometry_absent",
    "tal_candidate_motion_fallback_compressed",
    "tal_candidate_motion_fallback_cross_segment_unreliable",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "tal_candidate_motion_fallback_low_precision",
    "tal_candidate_motion_fallback_tail_window",
    "tal_candidate_incomplete",
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_skeleton_drifted_after_takeoff",
    "tal_candidate_takeoff_apex_gap_compressed",
    "tal_candidate_takeoff_apex_gap_unreliable",
    "tal_candidate_temporal_geometry_unreliable",
    "tal_order_unresolved",
    "tal_candidate_unreliable_sparse_track_stitch",
    "tal_candidate_weak_geometry",
}
WEAK_TAKEOFF_APEX_RESTORE_MAX_GAP_SEC = 0.10
WEAK_TAKEOFF_APEX_WARNINGS = {
    "apex_local_minimum_not_clear",
    "apex_motion_bounded_unclear_fallback",
    "apex_geometry_weak",
}
BOUNDED_MOTION_FALLBACK_RESTORE_FLAGS = {
    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "tal_candidate_motion_fallback_low_precision",
    "tal_candidate_skeleton_drifted_after_takeoff",
}
DENSE_TAIL_WINDOW_BOUNDED_MOTION_FALLBACK_RESTORE_FLAGS = {
    "keyframe_candidates_motion_fallback",
    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
    "keyframe_candidates_motion_fallback_excluded_rejected_tail_window",
    "keyframe_candidates_motion_fallback_dense_scores",
}
DENSE_TAIL_WINDOW_BOUNDED_MOTION_FALLBACK_ALLOWED_BLOCKING_FLAGS = {
    "tal_candidate_incomplete",
    "tal_order_unresolved",
}
MIN_BOUNDED_MOTION_FALLBACK_RESTORE_CONFIDENCE = 0.4
MIN_BOUNDED_MOTION_FALLBACK_RESTORE_AVG_CONFIDENCE = 0.5
MIN_DENSE_TAIL_WINDOW_BOUNDED_MOTION_FALLBACK_RESTORE_AVG_CONFIDENCE = 0.48
MIN_BOUNDED_MOTION_FALLBACK_PHASE_GAP_SEC = 0.12
MAX_BOUNDED_MOTION_FALLBACK_TAL_SPAN_SEC = 1.8
DEGRADED_SEMANTIC_SYNC_MIN_CONFIDENCE = 0.60
DEGRADED_SEMANTIC_SYNC_MIN_PHASE_CONFIDENCE = 0.50
DEGRADED_SEMANTIC_SYNC_MIN_TAL_SPAN_SEC = 0.25
DEGRADED_SEMANTIC_SYNC_MAX_TAL_SPAN_SEC = 2.0
DEGRADED_SEMANTIC_SYNC_SUPPORT_FLAGS = {
    "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
    "semantic_keyframes_tracker_final_loss_motion_fallback_ignored",
    "semantic_keyframes_weak_refinement_late_candidate_conflict_ignored_low_visibility_no_pose_support",
    "video_temporal_resolver_coherent_tal_used",
}
DEGRADED_SEMANTIC_SYNC_REASON_FLAGS = {
    "bio_key_frames_not_synced_tracker_final_loss_motion_fallback": (
        "bio_key_frames_degraded_semantic_tracker_final_loss_motion_fallback"
    ),
    "bio_key_frames_not_synced_tracker_final_loss_weak_geometry": (
        "bio_key_frames_degraded_semantic_tracker_final_loss_weak_geometry"
    ),
    "bio_key_frames_not_synced_unreliable_resolved_keyframes": (
        "bio_key_frames_degraded_semantic_unreliable_resolved_keyframes"
    ),
    "bio_key_frames_not_synced_unresolved_semantic_tal_conflict": (
        "bio_key_frames_degraded_semantic_unresolved_semantic_tal_conflict"
    ),
    "bio_key_frames_not_synced_incomplete_resolved_tal": (
        "bio_key_frames_degraded_semantic_incomplete_resolved_tal"
    ),
}


def _empty_jump_metrics() -> dict[str, Any]:
    return {
        "air_time_seconds": None,
        "estimated_height_cm": None,
        "takeoff_speed_mps": None,
        "rotation_rps": None,
        "estimated_rotations": None,
        "probable_jump_type": "unknown",
    }


def _empty_analysis(
    knee_angles: list[dict[str, Any]] | None = None,
    trunk_tilts: list[dict[str, Any]] | None = None,
    arm_symmetry: list[dict[str, Any]] | None = None,
    *,
    analysis_profile: str = "jump",
    sampling_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "analysis_profile": analysis_profile,
        "sampling_context": sampling_context or {},
        "knee_angles": knee_angles or [],
        "trunk_tilts": trunk_tilts or [],
        "arm_symmetry": arm_symmetry or [],
        "com_trajectory": {"points": [], "vertical_range": 0},
        "rotation_stability": {"average_tilt_degrees": None, "stability_score": 65},
        "bio_subscores": {
            "takeoff_power": 65,
            "rotation_axis": 65,
            "arm_coordination": 65,
            "landing_absorption": 65,
            "core_stability": 65,
        },
        "discipline_metrics": {},
        "quality_flags": [],
        "key_frames": {},
        "jump_metrics": _empty_jump_metrics() if analysis_profile == "jump" else None,
        "jump_metrics_status": "invalid" if analysis_profile == "jump" else "not_applicable",
        "jump_metrics_warning": "未检测到有效跳跃数据" if analysis_profile == "jump" else None,
    }


def _point(keypoints: list[dict[str, Any]], index: int) -> dict[str, float] | None:
    if index >= len(keypoints):
        return None
    raw = keypoints[index]
    if raw.get("x") is None or raw.get("y") is None:
        return None
    visibility = float(raw.get("visibility", 0.0))
    if bool(raw.get("interpolated", False)) and visibility < 0.3:
        return None
    return {"x": float(raw.get("x", 0.0)), "y": float(raw.get("y", 0.0)), "z": float(raw.get("z", 0.0))}


def _biomechanics_frames(pose_data: dict[str, Any]) -> list[dict[str, Any]]:
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not isinstance(frames, list):
        return []
    return [
        frame
        for frame in frames
        if isinstance(frame, dict) and frame.get("tracking_state") not in {"interpolated", "lost", "low_confidence"}
    ]


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _midpoint(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2}


def _reference_length(keypoints: list[dict[str, Any]]) -> float:
    """Use shoulder width to normalize the skater scale within the frame."""
    left_shoulder = _point(keypoints, 11)
    right_shoulder = _point(keypoints, 12)
    if not (left_shoulder and right_shoulder):
        return 0.0
    return _distance(left_shoulder, right_shoulder)


def _shoulder_hip_reference_length(keypoints: list[dict[str, Any]]) -> float:
    """Use shoulder-to-hip midpoint distance to normalize vertical motion."""
    left_shoulder = _point(keypoints, 11)
    right_shoulder = _point(keypoints, 12)
    left_hip = _point(keypoints, 23)
    right_hip = _point(keypoints, 24)
    if not all((left_shoulder, right_shoulder, left_hip, right_hip)):
        return 0.0
    shoulder_mid = _midpoint(left_shoulder, right_shoulder)
    hip_mid = _midpoint(left_hip, right_hip)
    return _distance(shoulder_mid, hip_mid)


def _angle(a: dict[str, float], b: dict[str, float], c: dict[str, float]) -> float:
    ab = (a["x"] - b["x"], a["y"] - b["y"])
    cb = (c["x"] - b["x"], c["y"] - b["y"])
    dot = ab[0] * cb[0] + ab[1] * cb[1]
    mag_ab = math.hypot(*ab)
    mag_cb = math.hypot(*cb)
    if mag_ab == 0 or mag_cb == 0:
        return 0.0
    cosine = max(-1.0, min(dot / (mag_ab * mag_cb), 1.0))
    return math.degrees(math.acos(cosine))


def _frame_number(frame_name: str) -> int:
    digits = "".join(char for char in frame_name if char.isdigit())
    return int(digits or "0")


def calc_knee_angle(keypoints: list[dict[str, Any]], frame_idx: int) -> dict[str, Any]:
    left = [_point(keypoints, index) for index in (23, 25, 27)]
    right = [_point(keypoints, index) for index in (24, 26, 28)]
    left_angle = _angle(*left) if all(left) else None
    right_angle = _angle(*right) if all(right) else None
    values = [value for value in [left_angle, right_angle] if value is not None]
    return {"frame_idx": frame_idx, "left": left_angle, "right": right_angle, "min_angle": min(values) if values else None}


def calc_trunk_tilt(keypoints: list[dict[str, Any]], frame_idx: int) -> dict[str, Any]:
    shoulders = [_point(keypoints, 11), _point(keypoints, 12)]
    hips = [_point(keypoints, 23), _point(keypoints, 24)]
    if not all(shoulders + hips):
        return {"frame_idx": frame_idx, "tilt_degrees": None}
    shoulder_mid = _midpoint(shoulders[0], shoulders[1])
    hip_mid = _midpoint(hips[0], hips[1])
    dx = shoulder_mid["x"] - hip_mid["x"]
    dy = hip_mid["y"] - shoulder_mid["y"]
    tilt = abs(math.degrees(math.atan2(dx, max(dy, 0.001))))
    return {"frame_idx": frame_idx, "tilt_degrees": tilt}


def calc_arm_symmetry(keypoints: list[dict[str, Any]], frame_idx: int) -> dict[str, Any]:
    reference_length = _reference_length(keypoints)
    if reference_length < 0.01:
        return {"frame_idx": frame_idx, "symmetry": None}

    left_shoulder = _point(keypoints, 11)
    right_shoulder = _point(keypoints, 12)
    left_wrist = _point(keypoints, 15)
    right_wrist = _point(keypoints, 16)
    if not all([left_shoulder, right_shoulder, left_wrist, right_wrist]):
        return {"frame_idx": frame_idx, "symmetry": None}

    left_distance = _distance(left_wrist, left_shoulder) / reference_length
    right_distance = _distance(right_wrist, right_shoulder) / reference_length
    symmetry = max(0.0, 1.0 - abs(left_distance - right_distance))
    return {"frame_idx": frame_idx, "symmetry": symmetry}


def calc_center_of_mass_trajectory(pose_data: dict[str, Any]) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    y_values: list[float] = []
    reference_lengths: list[float] = []
    for frame in _biomechanics_frames(pose_data):
        keypoints = frame.get("keypoints", [])
        hips = [_point(keypoints, 23), _point(keypoints, 24)]
        shoulders = [_point(keypoints, 11), _point(keypoints, 12)]
        visible = [point for point in hips + shoulders if point is not None]
        if not visible:
            continue
        y_value = sum(point["y"] for point in visible) / len(visible)
        points.append(
            {
                "frame": frame.get("frame", ""),
                "x": sum(point["x"] for point in visible) / len(visible),
                "y": y_value,
            }
        )
        y_values.append(y_value)

        reference_length = _shoulder_hip_reference_length(keypoints)
        if reference_length >= 0.01:
            reference_lengths.append(reference_length)

    if y_values and reference_lengths:
        average_reference = sum(reference_lengths) / len(reference_lengths)
        vertical_range = (max(y_values) - min(y_values)) / average_reference
    else:
        vertical_range = 0.0
    return {"points": points, "vertical_range": vertical_range}


def _normalize_frame_name(frame: str) -> str:
    return PathLikeFrame(frame).stem


def _key_for_resolved_record(record: dict[str, Any]) -> str | None:
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
    if phase_code in {"spin_entry", "spin_main", "spin_exit"}:
        return {
            "spin_entry": "旋转入",
            "spin_main": "旋转中",
            "spin_exit": "旋转出",
        }[phase_code]
    if phase_code in {"spiral_hold", "step_sequence"}:
        return "峰值" if phase_code == "spiral_hold" else "步法序列"
    return None


def _resolved_keyframe_maps(resolved_keyframes: dict[str, Any] | None) -> tuple[dict[str, str], dict[str, float]]:
    selected = resolved_keyframes.get("selected") if isinstance(resolved_keyframes, dict) else None
    if not isinstance(selected, list):
        return {}, {}

    frames: dict[str, str] = {}
    timestamps: dict[str, float] = {}
    for record in selected:
        if not isinstance(record, dict):
            continue
        key = _key_for_resolved_record(record)
        frame_id = _normalize_frame_name(str(record.get("frame_id") or ""))
        if key is None or not frame_id:
            continue
        frames[key] = frame_id
        timestamp = _to_float(record.get("timestamp"))
        if timestamp is not None:
            timestamps[key] = round(timestamp, 3)
    return frames, timestamps


def _resolved_late_pose_core_candidate_fallback_can_sync(
    bio_data: dict[str, Any],
    resolved_keyframes: dict[str, Any],
) -> bool:
    candidates = bio_data.get("key_frame_candidates")
    if not isinstance(candidates, dict):
        return False
    candidate_flags = {
        str(flag).strip()
        for flag in candidates.get("quality_flags", [])
        if str(flag).strip()
    }
    if "keyframe_candidates_late_pose_core_reselected" not in candidate_flags:
        return False
    if str(resolved_keyframes.get("source") or "") != "skeleton_fallback":
        return False
    if "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates" not in {
        str(flag).strip()
        for flag in resolved_keyframes.get("quality_flags", [])
        if isinstance(resolved_keyframes.get("quality_flags"), list) and str(flag).strip()
    }:
        return False
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return False
    core_records = [
        record
        for record in selected
        if isinstance(record, dict) and _key_for_resolved_record(record) in {"T", "A", "L"}
    ]
    return (
        len(core_records) >= 3
        and all(str(record.get("selection_reason") or "") == "fallback_to_keyframe_candidates" for record in core_records[:3])
    )


def _candidate_keyframe_maps(bio_data: dict[str, Any]) -> tuple[dict[str, str], dict[str, float], list[float]]:
    candidates = bio_data.get("key_frame_candidates")
    if not isinstance(candidates, dict):
        return {}, {}, []
    frames: dict[str, str] = {}
    timestamps: dict[str, float] = {}
    confidences: list[float] = []
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            continue
        frame_id = _normalize_frame_name(str(candidate.get("frame_id") or ""))
        if frame_id:
            frames[key] = frame_id
        timestamp = _to_float(candidate.get("timestamp"))
        if timestamp is not None:
            timestamps[key] = round(timestamp, 3)
        confidence = _to_float(candidate.get("confidence"))
        if confidence is not None:
            confidences.append(confidence)
    return frames, timestamps, confidences


def _bio_quality_flag_set(bio_data: dict[str, Any]) -> set[str]:
    flags: set[str] = set()
    raw_flags = bio_data.get("quality_flags") if isinstance(bio_data.get("quality_flags"), list) else []
    flags.update(str(flag).strip() for flag in raw_flags if str(flag).strip())

    candidates = bio_data.get("key_frame_candidates")
    if not isinstance(candidates, dict):
        return flags
    candidate_flags = candidates.get("quality_flags") if isinstance(candidates.get("quality_flags"), list) else []
    flags.update(str(flag).strip() for flag in candidate_flags if str(flag).strip())
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            continue
        warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
        flags.update(str(flag).strip() for flag in warnings if str(flag).strip())
    return flags


def _candidate_warnings(bio_data: dict[str, Any], key: str) -> set[str]:
    candidates = bio_data.get("key_frame_candidates")
    if not isinstance(candidates, dict):
        return set()
    candidate = candidates.get(key)
    if not isinstance(candidate, dict):
        return set()
    warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
    return {str(flag).strip() for flag in warnings if str(flag).strip()}


def _candidate_restore_blocked_by_weak_takeoff_apex(bio_data: dict[str, Any]) -> bool:
    candidates = bio_data.get("key_frame_candidates")
    if not isinstance(candidates, dict):
        return False
    flags = _bio_quality_flag_set(bio_data)
    if "tal_candidate_takeoff_geometry_weak" not in flags and "takeoff_geometry_weak" not in flags:
        return False

    takeoff = candidates.get("T")
    apex = candidates.get("A")
    if not isinstance(takeoff, dict) or not isinstance(apex, dict):
        return False
    takeoff_ts = _to_float(takeoff.get("timestamp"))
    apex_ts = _to_float(apex.get("timestamp"))
    if takeoff_ts is None or apex_ts is None:
        return False
    if not (0.0 <= apex_ts - takeoff_ts <= WEAK_TAKEOFF_APEX_RESTORE_MAX_GAP_SEC):
        return False

    apex_warnings = _candidate_warnings(bio_data, "A")
    if not (apex_warnings & WEAK_TAKEOFF_APEX_WARNINGS):
        return False
    takeoff_warnings = _candidate_warnings(bio_data, "T")
    return bool(takeoff_warnings & {"takeoff_geometry_weak", "knee_extension_weak", "com_ascent_weak"})


def _candidate_keyframes_are_restoreable(bio_data: dict[str, Any]) -> bool:
    flags = _bio_quality_flag_set(bio_data)
    _, timestamps, confidences = _candidate_keyframe_maps(bio_data)
    if len(confidences) < 3:
        return False
    if _candidate_restore_blocked_by_weak_takeoff_apex(bio_data):
        return False
    if flags & KEYFRAME_CANDIDATE_RESTORE_BLOCKING_FLAGS:
        return _candidate_keyframes_are_bounded_motion_fallback_restoreable(
            bio_data,
            flags=flags,
            timestamps=timestamps,
            confidences=confidences,
        )
    return len(confidences) >= 3


def _candidate_keyframes_are_bounded_motion_fallback_restoreable(
    bio_data: dict[str, Any],
    *,
    flags: set[str] | None = None,
    timestamps: dict[str, float] | None = None,
    confidences: list[float] | None = None,
) -> bool:
    flags = flags if flags is not None else _bio_quality_flag_set(bio_data)
    if not flags & BOUNDED_MOTION_FALLBACK_RESTORE_FLAGS:
        return False
    if _bio_tracker_final_unrecovered(flags):
        return False
    dense_tail_window_fallback = _candidate_is_dense_tail_window_bounded_motion_fallback(flags)
    allowed_blocking_flags = set(BOUNDED_MOTION_FALLBACK_RESTORE_FLAGS)
    if dense_tail_window_fallback:
        allowed_blocking_flags.update(DENSE_TAIL_WINDOW_BOUNDED_MOTION_FALLBACK_ALLOWED_BLOCKING_FLAGS)
    hard_blocking_flags = KEYFRAME_CANDIDATE_RESTORE_BLOCKING_FLAGS - allowed_blocking_flags
    if flags & hard_blocking_flags:
        return False

    frames, inferred_timestamps, inferred_confidences = _candidate_keyframe_maps(bio_data)
    timestamps = timestamps if timestamps is not None else inferred_timestamps
    confidences = confidences if confidences is not None else inferred_confidences
    if not {"T", "A", "L"}.issubset(frames) or not {"T", "A", "L"}.issubset(timestamps):
        return False
    if len(confidences) < 3:
        return False
    if min(confidences) < MIN_BOUNDED_MOTION_FALLBACK_RESTORE_CONFIDENCE:
        return False
    avg_confidence_threshold = (
        MIN_DENSE_TAIL_WINDOW_BOUNDED_MOTION_FALLBACK_RESTORE_AVG_CONFIDENCE
        if dense_tail_window_fallback
        else MIN_BOUNDED_MOTION_FALLBACK_RESTORE_AVG_CONFIDENCE
    )
    if (sum(confidences) / len(confidences)) < avg_confidence_threshold:
        return False

    takeoff = timestamps["T"]
    apex = timestamps["A"]
    landing = timestamps["L"]
    if not (takeoff < apex < landing):
        return False
    if (apex - takeoff) < MIN_BOUNDED_MOTION_FALLBACK_PHASE_GAP_SEC:
        return False
    if (landing - apex) < MIN_BOUNDED_MOTION_FALLBACK_PHASE_GAP_SEC:
        return False
    if (landing - takeoff) > MAX_BOUNDED_MOTION_FALLBACK_TAL_SPAN_SEC:
        return False
    return True


def _candidate_is_dense_tail_window_bounded_motion_fallback(flags: set[str]) -> bool:
    return DENSE_TAIL_WINDOW_BOUNDED_MOTION_FALLBACK_RESTORE_FLAGS.issubset(flags)


def _selected_resolved_core_records(resolved_keyframes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return {}
    records: dict[str, dict[str, Any]] = {}
    for record in selected:
        if not isinstance(record, dict):
            continue
        key = _key_for_resolved_record(record)
        if key in {"T", "A", "L"}:
            records[key] = record
    return records


def _raw_jump_keyframes_complete(bio_data: dict[str, Any]) -> bool:
    raw_frames = bio_data.get("raw_biomechanics_key_frames")
    return isinstance(raw_frames, dict) and {"T", "A", "L"}.issubset(raw_frames)


def _degraded_semantic_keyframes_can_fill_bio(
    bio_data: dict[str, Any],
    resolved_keyframes: dict[str, Any],
    *,
    analysis_profile: str | None,
    frames: dict[str, str],
    timestamps: dict[str, float],
) -> bool:
    profile = str(analysis_profile or bio_data.get("analysis_profile") or "").strip().lower()
    if profile != "jump":
        return False
    flags = _bio_quality_flag_set(bio_data)
    degraded_semantic_already_synced = "bio_key_frames_synced_from_degraded_semantic_keyframes" in flags
    if _candidate_keyframes_are_restoreable(bio_data):
        return False
    if _raw_jump_keyframes_complete(bio_data) and not degraded_semantic_already_synced:
        return False
    source = str(resolved_keyframes.get("source") or "").strip()
    if source not in {"video_ai_refined", "blended"}:
        return False
    if not {"T", "A", "L"}.issubset(frames) or not {"T", "A", "L"}.issubset(timestamps):
        return False
    takeoff = timestamps["T"]
    apex = timestamps["A"]
    landing = timestamps["L"]
    if not (takeoff < apex < landing):
        return False
    if not (DEGRADED_SEMANTIC_SYNC_MIN_TAL_SPAN_SEC <= landing - takeoff <= DEGRADED_SEMANTIC_SYNC_MAX_TAL_SPAN_SEC):
        return False

    raw_flags = resolved_keyframes.get("quality_flags")
    flags = {str(flag) for flag in raw_flags if isinstance(flag, str)} if isinstance(raw_flags, list) else set()
    if "semantic_keyframes_unreliable_candidate_early_takeoff_conflict" in flags:
        return False
    if "semantic_keyframes_unreliable_fallback_to_sampled_frames" not in flags:
        return False
    if not (flags & DEGRADED_SEMANTIC_SYNC_SUPPORT_FLAGS):
        return False

    confidence = _to_float(resolved_keyframes.get("confidence"))
    if confidence is None or confidence < DEGRADED_SEMANTIC_SYNC_MIN_CONFIDENCE:
        return False
    records = _selected_resolved_core_records(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(records):
        return False
    for record in records.values():
        reason = str(record.get("selection_reason") or "")
        if not reason.startswith("video_phase_range_"):
            return False
        phase_confidence = _to_float(record.get("confidence"))
        if phase_confidence is None or phase_confidence < DEGRADED_SEMANTIC_SYNC_MIN_PHASE_CONFIDENCE:
            return False
    return True


def _sync_resolved_keyframe_maps_into_bio(
    bio_data: dict[str, Any],
    resolved_keyframes: dict[str, Any],
    *,
    frames: dict[str, str],
    timestamps: dict[str, float],
    degraded_semantic: bool = False,
) -> dict[str, Any]:
    updated = dict(bio_data)
    existing = updated.get("key_frames") if isinstance(updated.get("key_frames"), dict) else {}
    if existing and existing != frames and "raw_biomechanics_key_frames" not in updated:
        updated["raw_biomechanics_key_frames"] = dict(existing)
    updated["key_frames"] = frames
    if timestamps:
        updated["key_frame_timestamps"] = timestamps
    updated["key_frame_source"] = str(resolved_keyframes.get("source") or "resolved_keyframes")
    confidence = _to_float(resolved_keyframes.get("confidence"))
    if confidence is not None:
        updated["key_frame_confidence"] = round(confidence, 3)

    flags = updated.get("quality_flags") if isinstance(updated.get("quality_flags"), list) else []
    next_flags = [
        flag
        for flag in flags
        if not (isinstance(flag, str) and flag.startswith("bio_key_frames_not_synced_"))
    ]
    if "bio_key_frames_synced_from_resolved_keyframes" not in next_flags:
        next_flags.append("bio_key_frames_synced_from_resolved_keyframes")
    if degraded_semantic and "bio_key_frames_synced_from_degraded_semantic_keyframes" not in next_flags:
        next_flags.append("bio_key_frames_synced_from_degraded_semantic_keyframes")
    resolved_flags = {
        str(flag)
        for flag in (resolved_keyframes.get("quality_flags") or [])
        if isinstance(flag, str)
    }
    if (
        "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted" in resolved_flags
        and "bio_key_frames_synced_from_long_unresolved_visual_tal" not in next_flags
    ):
        next_flags.append("bio_key_frames_synced_from_long_unresolved_visual_tal")
    updated["quality_flags"] = next_flags
    return updated


def _bio_has_tracker_final_loss_motion_fallback(bio_data: dict[str, Any]) -> bool:
    flags = _bio_quality_flag_set(bio_data)
    if not _bio_tracker_final_unrecovered(flags):
        return False
    fallback_low_precision = (
        "tal_candidate_motion_fallback_low_precision" in flags
        or "tal_candidate_incomplete" in flags
        or "tal_order_unresolved" in flags
        or "tal_candidate_skeleton_drifted_after_takeoff" in flags
    )
    motion_fallback = (
        "keyframe_candidates_motion_fallback" in flags
        or "keyframe_candidates_motion_fallback_from_takeoff_anchor" in flags
    )
    return fallback_low_precision and motion_fallback


def _bio_tracker_final_unrecovered(flags: set[str]) -> bool:
    return (
        "person_tracker_final_unrecovered" in flags
        or "person_tracker_final_loss_unrecovered" in flags
        or (
            "person_tracker_target_lost" in flags
            and "person_tracker_transient_loss_recovered" not in flags
            and (
                "person_tracker_relock_rejected" in flags
                or "person_tracker_relock_pending" in flags
                or "person_tracker_continuity_rejected" in flags
            )
        )
    )


def _bio_has_tracker_final_loss_weak_geometry(bio_data: dict[str, Any]) -> bool:
    flags = _bio_quality_flag_set(bio_data)
    if not _bio_tracker_final_unrecovered(flags):
        return False
    return "tal_candidate_weak_geometry" in flags


def _bio_has_absent_landing_geometry_only(bio_data: dict[str, Any]) -> bool:
    flags = _bio_quality_flag_set(bio_data)
    if not _bio_tracker_final_unrecovered(flags):
        return False
    if "tal_candidate_landing_geometry_absent" not in flags or "tal_candidate_weak_geometry" not in flags:
        return False
    stronger_unreliable_flags = {
        "keyframe_candidates_motion_fallback",
        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
        "tal_candidate_motion_fallback_low_precision",
        "tal_candidate_incomplete",
        "tal_order_unresolved",
        "tal_candidate_skeleton_drifted_after_takeoff",
    }
    return not bool(flags & stronger_unreliable_flags)


def _resolved_accepted_absent_landing_geometry(resolved_keyframes: dict[str, Any]) -> bool:
    raw_flags = resolved_keyframes.get("quality_flags")
    flags = {str(flag) for flag in raw_flags if isinstance(flag, str)} if isinstance(raw_flags, list) else set()
    accepted_flags = {
        "semantic_keyframes_candidate_tal_conflict_ignored_weak_geometry",
        "semantic_keyframes_tracker_final_loss_weak_semantic_motion_ignored",
    }
    if not flags & accepted_flags:
        return False
    for key in ("semantic_candidate_tal_conflict", "semantic_tracker_final_loss_weak_semantic_motion"):
        diagnostic = resolved_keyframes.get(key)
        if not isinstance(diagnostic, dict):
            continue
        if str(diagnostic.get("decision") or "") in {
            "ignored_absent_landing_geometry_candidate",
            "ignored_retry_absent_landing_geometry_candidate",
        }:
            return True
    return False


def _tracker_final_loss_motion_fallback_unreliable(bio_data: dict[str, Any], resolved_keyframes: dict[str, Any]) -> bool:
    source = str(resolved_keyframes.get("source") or "").strip()
    if source not in {"video_ai_refined", "blended"}:
        return False
    raw_flags = resolved_keyframes.get("quality_flags")
    flags = {str(flag) for flag in raw_flags if isinstance(flag, str)} if isinstance(raw_flags, list) else set()
    if "semantic_keyframes_tracker_final_loss_motion_fallback_ignored" in flags:
        diagnostic = resolved_keyframes.get("semantic_tracker_final_loss_motion_fallback")
        if isinstance(diagnostic, dict) and str(diagnostic.get("decision") or "") in {
            "ignored_reliable_pose_bounded_motion_fallback",
            "ignored_unbounded_motion_fallback",
            "ignored_reused_semantic_over_low_visibility_bounded_motion_fallback",
        }:
            return False
    if "semantic_keyframes_tracker_final_loss_visual_tal_promoted" in flags:
        diagnostic = resolved_keyframes.get("semantic_tracker_final_loss_visual_promotion")
        if isinstance(diagnostic, dict) and str(diagnostic.get("decision") or "") == "promoted_visible_video_tal_over_low_visibility_motion_fallback":
            return False
    if "semantic_keyframes_phase_range_visual_tal_promoted" in flags:
        diagnostic = resolved_keyframes.get("semantic_phase_range_visual_promotion")
        if (
            isinstance(diagnostic, dict)
            and str(diagnostic.get("decision") or "")
            == "promoted_video_phase_range_tal_over_low_visibility_motion_fallback"
        ):
            return False
    if "semantic_keyframes_reused_from_matching_video" in flags and (
        "semantic_keyframes_reused_ignored_low_visibility_bounded_motion_fallback" in flags
        or "semantic_keyframes_reuse_candidate_conflict_ignored_insufficient_pose_low_visibility_fallback" in flags
        or "semantic_keyframes_reused_over_long_unresolved_motion_fallback" in flags
        or "semantic_keyframes_reused_ignored_long_unresolved_motion_fallback" in flags
        or "semantic_keyframes_reuse_candidate_conflict_ignored_long_unresolved_motion_fallback" in flags
    ):
        return False
    if "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted" in flags:
        diagnostic = resolved_keyframes.get("semantic_long_unresolved_motion_fallback_partial_promotion")
        if (
            isinstance(diagnostic, dict)
            and str(diagnostic.get("decision") or "") == "promoted_partial_video_tal_over_long_unresolved_motion_fallback"
        ):
            return False
    return _bio_has_tracker_final_loss_motion_fallback(bio_data)


def _tracker_final_loss_weak_geometry_unreliable(bio_data: dict[str, Any], resolved_keyframes: dict[str, Any]) -> bool:
    source = str(resolved_keyframes.get("source") or "").strip()
    if source not in {"video_ai_refined", "blended"}:
        return False
    if _bio_has_absent_landing_geometry_only(bio_data) and _resolved_accepted_absent_landing_geometry(resolved_keyframes):
        return False
    return _bio_has_tracker_final_loss_weak_geometry(bio_data)


def _restore_biomechanics_key_frames(
    bio_data: dict[str, Any],
    *,
    flag: str,
    analysis_profile: str | None,
) -> dict[str, Any]:
    updated = dict(bio_data)
    profile = str(analysis_profile or bio_data.get("analysis_profile") or "").strip().lower()
    candidate_frames, candidate_timestamps, candidate_confidences = _candidate_keyframe_maps(bio_data)
    restore_candidates = _candidate_keyframes_are_restoreable(bio_data)
    restored_frames = candidate_frames if restore_candidates else {}
    restored_timestamps = candidate_timestamps if restore_candidates else {}
    restored_confidence = (
        round(sum(candidate_confidences) / len(candidate_confidences), 3)
        if restore_candidates and candidate_confidences
        else None
    )
    restored_source = "biomechanics_candidates"

    if profile == "jump" and (not restore_candidates or not {"T", "A", "L"}.issubset(restored_frames)):
        raw_frames = bio_data.get("raw_biomechanics_key_frames")
        restored_frames = dict(raw_frames) if isinstance(raw_frames, dict) else {}
        restored_timestamps = {}
        restored_confidence = None
        restored_source = "raw_biomechanics_key_frames"

    if restored_frames and (profile != "jump" or {"T", "A", "L"}.issubset(restored_frames)):
        updated["key_frames"] = restored_frames
        if restored_timestamps:
            updated["key_frame_timestamps"] = restored_timestamps
        else:
            updated.pop("key_frame_timestamps", None)
        updated["key_frame_source"] = restored_source
        if restored_confidence is not None:
            updated["key_frame_confidence"] = restored_confidence
        else:
            updated.pop("key_frame_confidence", None)
        updated.pop("raw_biomechanics_key_frames", None)
    elif profile == "jump":
        updated["key_frames"] = {}
        updated.pop("key_frame_timestamps", None)
        updated.pop("key_frame_source", None)
        updated.pop("key_frame_confidence", None)
        updated.pop("raw_biomechanics_key_frames", None)

    flags = updated.get("quality_flags") if isinstance(updated.get("quality_flags"), list) else []
    next_flags = [item for item in flags if item != "bio_key_frames_synced_from_resolved_keyframes"]
    if flag not in next_flags:
        next_flags.append(flag)
    if (
        _bio_has_tracker_final_loss_motion_fallback(bio_data)
        or _bio_has_tracker_final_loss_weak_geometry(bio_data)
    ) and "tal_candidate_unreliable_tracker_final_loss" not in next_flags:
        next_flags.append("tal_candidate_unreliable_tracker_final_loss")
    if not restore_candidates and "bio_key_frames_not_restored_unreliable_candidates" not in next_flags:
        next_flags.append("bio_key_frames_not_restored_unreliable_candidates")
    if (
        restore_candidates
        and _candidate_keyframes_are_bounded_motion_fallback_restoreable(bio_data)
        and "bio_key_frames_restored_bounded_motion_fallback" not in next_flags
    ):
        next_flags.append("bio_key_frames_restored_bounded_motion_fallback")
    updated["quality_flags"] = next_flags
    return updated


def sync_key_frames_from_resolved_keyframes(
    bio_data: dict[str, Any],
    resolved_keyframes: dict[str, Any] | None,
    *,
    analysis_profile: str | None = None,
) -> dict[str, Any]:
    """Align legacy bio_data.key_frames with reliable semantic selections.

    ``key_frame_candidates`` remains the skeleton/motion evidence.  Once the
    semantic resolver has selected reliable frames used for vision/reporting,
    the legacy ``key_frames`` field should point at those same frames.  If the
    semantic selection is rejected and the pipeline falls back to sampled
    frames, keep the biomechanics frames instead of propagating rejected T/A/L
    into smoothing, prompts, reports, or compare views.
    """
    if not isinstance(bio_data, dict):
        return bio_data

    if not isinstance(resolved_keyframes, dict):
        return bio_data

    try:
        from app.services.video_temporal import (
            resolved_keyframes_accept_insufficient_pose_low_visibility_fallback,
            semantic_keyframes_are_reliable,
        )
    except Exception:  # noqa: BLE001
        resolved_keyframes_accept_insufficient_pose_low_visibility_fallback = None  # type: ignore[assignment]
        semantic_keyframes_are_reliable = None  # type: ignore[assignment]

    resolved_flags = set(
        str(flag)
        for flag in resolved_keyframes.get("quality_flags", [])
        if isinstance(resolved_keyframes.get("quality_flags"), list)
    )
    accepted_unreliable_pose_motion_fallback = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_unreliable_pose_fallback" in resolved_flags
    )
    accepted_near_candidate_motion_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate" in resolved_flags
    )
    accepted_weak_temporal_geometry_motion_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_weak_temporal_geometry" in resolved_flags
    )
    accepted_early_approach_motion_peak_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_early_approach_motion_peak" in resolved_flags
    )
    accepted_phase_range_late_reanchor_motion_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor" in resolved_flags
    )
    accepted_reused_phase_range_late_reanchor_motion_conflict = (
        "semantic_keyframes_reuse_motion_cluster_conflict_ignored_phase_range_late_reanchor" in resolved_flags
    )
    accepted_tracker_final_loss_visual_promotion = (
        "semantic_keyframes_tracker_final_loss_visual_tal_promoted" in resolved_flags
    )
    accepted_phase_range_visual_promotion = (
        "semantic_keyframes_phase_range_visual_tal_promoted" in resolved_flags
    )
    accepted_distant_full_context_visual_promotion = (
        "semantic_keyframes_distant_full_context_visual_tal_promoted" in resolved_flags
    )
    accepted_main_motion_supported_weak_geometry_conflict = (
        "semantic_keyframes_candidate_tal_conflict_ignored_main_motion_supported_weak_geometry"
        in resolved_flags
    )
    accepted_insufficient_pose_low_visibility_fallback = (
        callable(resolved_keyframes_accept_insufficient_pose_low_visibility_fallback)
        and resolved_keyframes_accept_insufficient_pose_low_visibility_fallback(resolved_keyframes)
    )
    accepted_late_pose_core_candidate_fallback = _resolved_late_pose_core_candidate_fallback_can_sync(
        bio_data,
        resolved_keyframes,
    )
    frames, timestamps = _resolved_keyframe_maps(resolved_keyframes)

    def restore_or_sync_degraded(flag: str) -> dict[str, Any]:
        if _degraded_semantic_keyframes_can_fill_bio(
            bio_data,
            resolved_keyframes,
            analysis_profile=analysis_profile,
            frames=frames,
            timestamps=timestamps,
        ):
            updated = _sync_resolved_keyframe_maps_into_bio(
                bio_data,
                resolved_keyframes,
                frames=frames,
                timestamps=timestamps,
                degraded_semantic=True,
            )
            flags = updated.get("quality_flags") if isinstance(updated.get("quality_flags"), list) else []
            next_flags = list(flags)
            degraded_reason_flag = DEGRADED_SEMANTIC_SYNC_REASON_FLAGS.get(flag, flag)
            if degraded_reason_flag not in next_flags:
                next_flags.append(degraded_reason_flag)
            if (
                _bio_has_tracker_final_loss_motion_fallback(bio_data)
                or _bio_has_tracker_final_loss_weak_geometry(bio_data)
            ) and "tal_candidate_unreliable_tracker_final_loss" not in next_flags:
                next_flags.append("tal_candidate_unreliable_tracker_final_loss")
            if "bio_key_frames_not_restored_unreliable_candidates" not in next_flags:
                next_flags.append("bio_key_frames_not_restored_unreliable_candidates")
            updated["quality_flags"] = next_flags
            return updated
        return _restore_biomechanics_key_frames(
            bio_data,
            flag=flag,
            analysis_profile=analysis_profile,
        )

    if (
        "semantic_keyframes_unreliable_fallback_to_sampled_frames" in resolved_flags
        and not accepted_unreliable_pose_motion_fallback
        and not accepted_near_candidate_motion_conflict
        and not accepted_weak_temporal_geometry_motion_conflict
        and not accepted_early_approach_motion_peak_conflict
        and not accepted_phase_range_late_reanchor_motion_conflict
        and not accepted_reused_phase_range_late_reanchor_motion_conflict
        and not accepted_tracker_final_loss_visual_promotion
        and not accepted_phase_range_visual_promotion
        and not accepted_distant_full_context_visual_promotion
        and not accepted_main_motion_supported_weak_geometry_conflict
        and not accepted_insufficient_pose_low_visibility_fallback
        and not accepted_late_pose_core_candidate_fallback
        and _tracker_final_loss_motion_fallback_unreliable(bio_data, resolved_keyframes)
    ):
        return restore_or_sync_degraded("bio_key_frames_not_synced_tracker_final_loss_motion_fallback")
    if (
        "semantic_keyframes_unreliable_fallback_to_sampled_frames" in resolved_flags
        and not accepted_unreliable_pose_motion_fallback
        and not accepted_near_candidate_motion_conflict
        and not accepted_weak_temporal_geometry_motion_conflict
        and not accepted_early_approach_motion_peak_conflict
        and not accepted_phase_range_late_reanchor_motion_conflict
        and not accepted_reused_phase_range_late_reanchor_motion_conflict
        and not accepted_tracker_final_loss_visual_promotion
        and not accepted_phase_range_visual_promotion
        and not accepted_distant_full_context_visual_promotion
        and not accepted_main_motion_supported_weak_geometry_conflict
        and not accepted_insufficient_pose_low_visibility_fallback
        and not accepted_late_pose_core_candidate_fallback
        and _tracker_final_loss_weak_geometry_unreliable(bio_data, resolved_keyframes)
    ):
        return restore_or_sync_degraded("bio_key_frames_not_synced_tracker_final_loss_weak_geometry")
    if (
        "semantic_keyframes_unreliable_fallback_to_sampled_frames" in resolved_flags
        and not accepted_unreliable_pose_motion_fallback
        and not accepted_near_candidate_motion_conflict
        and not accepted_weak_temporal_geometry_motion_conflict
        and not accepted_early_approach_motion_peak_conflict
        and not accepted_phase_range_late_reanchor_motion_conflict
        and not accepted_reused_phase_range_late_reanchor_motion_conflict
        and not accepted_tracker_final_loss_visual_promotion
        and not accepted_phase_range_visual_promotion
        and not accepted_distant_full_context_visual_promotion
        and not accepted_main_motion_supported_weak_geometry_conflict
        and not accepted_insufficient_pose_low_visibility_fallback
        and not accepted_late_pose_core_candidate_fallback
    ):
        return restore_or_sync_degraded("bio_key_frames_not_synced_unreliable_resolved_keyframes")

    unresolved_conflict = (
        (
            "video_temporal_quality_retry_skeleton_tal_conflict" in resolved_flags
            or "video_temporal_quality_retry_motion_cluster_conflict" in resolved_flags
            or "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in resolved_flags
        )
        and "video_temporal_quality_retry_used" not in resolved_flags
        and "video_temporal_quality_retry_motion_cluster_fallback_used" not in resolved_flags
        and "video_temporal_resolver_motion_cluster_fallback_used" not in resolved_flags
        and "video_temporal_quality_retry_motion_cluster_conflict_ignored_unreliable_pose_fallback" not in resolved_flags
        and "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate" not in resolved_flags
        and "video_temporal_quality_retry_motion_cluster_conflict_ignored_weak_temporal_geometry" not in resolved_flags
        and "video_temporal_quality_retry_motion_cluster_conflict_ignored_early_approach_motion_peak" not in resolved_flags
        and "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor" not in resolved_flags
        and "semantic_keyframes_reuse_motion_cluster_conflict_ignored_phase_range_late_reanchor" not in resolved_flags
        and "semantic_keyframes_tracker_final_loss_visual_tal_promoted" not in resolved_flags
        and "semantic_keyframes_phase_range_visual_tal_promoted" not in resolved_flags
        and "semantic_keyframes_distant_full_context_visual_tal_promoted" not in resolved_flags
        and "semantic_keyframes_candidate_tal_conflict_ignored_main_motion_supported_weak_geometry" not in resolved_flags
        and not accepted_insufficient_pose_low_visibility_fallback
        and not accepted_late_pose_core_candidate_fallback
    )
    if unresolved_conflict:
        return restore_or_sync_degraded("bio_key_frames_not_synced_unresolved_semantic_tal_conflict")

    if (
        not accepted_insufficient_pose_low_visibility_fallback
        and not accepted_main_motion_supported_weak_geometry_conflict
        and not accepted_late_pose_core_candidate_fallback
        and _tracker_final_loss_motion_fallback_unreliable(bio_data, resolved_keyframes)
    ):
        return restore_or_sync_degraded("bio_key_frames_not_synced_tracker_final_loss_motion_fallback")
    if (
        not accepted_insufficient_pose_low_visibility_fallback
        and not accepted_main_motion_supported_weak_geometry_conflict
        and not accepted_late_pose_core_candidate_fallback
        and _tracker_final_loss_weak_geometry_unreliable(bio_data, resolved_keyframes)
    ):
        return restore_or_sync_degraded("bio_key_frames_not_synced_tracker_final_loss_weak_geometry")

    profile = str(analysis_profile or bio_data.get("analysis_profile") or "").strip().lower()
    if profile == "jump" and frames and not {"T", "A", "L"}.issubset(frames):
        return restore_or_sync_degraded("bio_key_frames_not_synced_incomplete_resolved_tal")

    if (
        callable(semantic_keyframes_are_reliable)
        and not semantic_keyframes_are_reliable(resolved_keyframes)
        and not accepted_late_pose_core_candidate_fallback
    ):
        return restore_or_sync_degraded("bio_key_frames_not_synced_unreliable_resolved_keyframes")

    if not frames:
        return bio_data

    if profile == "jump" and not {"T", "A", "L"}.issubset(frames):
        return restore_or_sync_degraded("bio_key_frames_not_synced_incomplete_resolved_tal")

    return _sync_resolved_keyframe_maps_into_bio(
        bio_data,
        resolved_keyframes,
        frames=frames,
        timestamps=timestamps,
    )


def _find_descent_start(points: list[dict[str, Any]], apex_index: int) -> int:
    takeoff_index = max(0, apex_index - max(1, len(points) // 5))
    for index in range(1, apex_index + 1):
        if points[index]["y"] < points[index - 1]["y"]:
            return index - 1
    return takeoff_index


def _find_ascent_start(points: list[dict[str, Any]], apex_index: int) -> int:
    landing_index = min(len(points) - 1, apex_index + max(1, len(points) // 5))
    for index in range(apex_index + 1, len(points)):
        if points[index]["y"] > points[index - 1]["y"]:
            landing_index = index
        if index - apex_index >= max(2, len(points) // 4):
            break
    return landing_index


def _hip_midpoint(frame: dict[str, Any]) -> dict[str, float] | None:
    keypoints = frame.get("keypoints", [])
    left_hip = _point(keypoints, 23)
    right_hip = _point(keypoints, 24)
    if not (left_hip and right_hip):
        return None
    return _midpoint(left_hip, right_hip)


def _find_max_hip_x_delta(frames: list[dict[str, Any]]) -> int | None:
    best_index: int | None = None
    best_delta = 0.0
    previous_hip: dict[str, float] | None = None

    for index, frame in enumerate(frames):
        current_hip = _hip_midpoint(frame)
        if current_hip is None:
            continue
        if previous_hip is not None:
            delta = abs(current_hip["x"] - previous_hip["x"])
            if delta > best_delta:
                best_delta = delta
                best_index = index
        previous_hip = current_hip

    return best_index


def _free_leg_ankle_y(frame: dict[str, Any]) -> float | None:
    keypoints = frame.get("keypoints", [])
    ankles = [_point(keypoints, 27), _point(keypoints, 28)]
    visible = [point["y"] for point in ankles if point is not None]
    if not visible:
        return None
    return min(visible)


def _find_free_leg_peak(frames: list[dict[str, Any]]) -> int | None:
    best_index: int | None = None
    best_y: float | None = None

    for index, frame in enumerate(frames):
        ankle_y = _free_leg_ankle_y(frame)
        if ankle_y is None:
            continue
        if best_y is None or ankle_y < best_y:
            best_y = ankle_y
            best_index = index

    return best_index


def detect_key_frames(
    com_trajectory: dict[str, Any],
    pose_data: dict[str, Any],
    analysis_profile: str = "jump",
) -> dict[str, str]:
    points = com_trajectory.get("points", [])
    if len(points) < 3:
        return {}

    if analysis_profile == "jump":
        apex_index = min(range(len(points)), key=lambda index: points[index]["y"])
        takeoff_index = _find_descent_start(points, apex_index)
        landing_index = _find_ascent_start(points, apex_index)
        return {
            "T": _normalize_frame_name(points[takeoff_index]["frame"]),
            "A": _normalize_frame_name(points[apex_index]["frame"]),
            "L": _normalize_frame_name(points[landing_index]["frame"]),
        }

    frames = _biomechanics_frames(pose_data)
    if analysis_profile == "spin":
        max_delta_index = _find_max_hip_x_delta(frames)
        if max_delta_index is None:
            return {}
        start_index = max(0, max_delta_index - 1)
        end_index = min(len(frames) - 1, max_delta_index + 1)
        return {
            "旋转入": _normalize_frame_name(str(frames[start_index].get("frame", ""))),
            "旋转中": _normalize_frame_name(str(frames[max_delta_index].get("frame", ""))),
            "旋转出": _normalize_frame_name(str(frames[end_index].get("frame", ""))),
        }

    if analysis_profile in ("spiral", "step"):
        peak_index = _find_free_leg_peak(frames)
        if peak_index is None:
            return {}
        return {"峰值": _normalize_frame_name(str(frames[peak_index].get("frame", "")))}

    return {}


class PathLikeFrame:
    def __init__(self, frame: str) -> None:
        self.stem = frame[:-4] if frame.endswith(".jpg") else frame


def calc_rotation_axis_stability(pose_data: dict[str, Any], start_frame: int, end_frame: int) -> dict[str, Any]:
    tilts: list[float] = []
    for frame in _biomechanics_frames(pose_data):
        frame_idx = _frame_number(str(frame.get("frame", "")))
        if start_frame <= frame_idx <= end_frame:
            tilt = calc_trunk_tilt(frame.get("keypoints", []), frame_idx).get("tilt_degrees")
            if tilt is not None:
                tilts.append(float(tilt))
    average_tilt = sum(tilts) / len(tilts) if tilts else None
    stability_score = 65 if average_tilt is None else max(0, min(100, round(100 - average_tilt * 2)))
    return {"average_tilt_degrees": average_tilt, "stability_score": stability_score}


def _normalized_angle_delta(current_angle: float, previous_angle: float) -> float:
    delta = current_angle - previous_angle
    while delta <= -math.pi:
        delta += 2 * math.pi
    while delta > math.pi:
        delta -= 2 * math.pi
    return delta


def _valid_effective_fps(effective_fps: float | None) -> float:
    try:
        numeric = float(effective_fps)
    except (TypeError, ValueError):
        return DEFAULT_EFFECTIVE_FPS
    if math.isnan(numeric) or math.isinf(numeric) or numeric <= 0:
        return DEFAULT_EFFECTIVE_FPS
    return numeric


def _build_sampling_context(
    effective_fps: float,
    source_fps: float | None,
    window_seconds: float | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {"effective_fps": round(effective_fps, 3)}
    if source_fps is not None:
        context["source_fps"] = round(float(source_fps), 3)
    if window_seconds is not None:
        context["window_seconds"] = round(float(window_seconds), 3)
    return context


def _rotation_rps(pose_data: dict[str, Any], start_frame: int, end_frame: int, effective_fps: float) -> float:
    angles: list[float] = []
    for frame in _biomechanics_frames(pose_data):
        frame_idx = _frame_number(str(frame.get("frame", "")))
        if start_frame <= frame_idx <= end_frame:
            left = _point(frame.get("keypoints", []), 11)
            right = _point(frame.get("keypoints", []), 12)
            if left and right:
                angles.append(math.atan2(right["y"] - left["y"], right["x"] - left["x"]))
    if len(angles) < 2:
        return 0.0

    # 设计说明: MediaPipe 肩点角度会在 -pi/pi 边界跳变，先解缠绕再按首尾角差估算真实旋转量。
    unwrapped = np.unwrap(np.array(angles, dtype=float))
    total_rotation = abs(float(unwrapped[-1] - unwrapped[0]))
    if total_rotation < 1e-6:
        total_rotation = sum(abs(_normalized_angle_delta(current, previous)) for previous, current in zip(angles, angles[1:]))

    total_turns = total_rotation / (2 * math.pi)
    duration = max((len(angles) - 1) / effective_fps, 1 / effective_fps)
    return round(total_turns / duration, 2)


def estimate_jump_rotations(
    rotation_rps: float | None,
    air_time_seconds: float | None,
) -> dict[str, Any]:
    if rotation_rps is None or air_time_seconds is None:
        return {"estimated_rotations": None, "probable_jump_type": "unknown"}

    rotations = rotation_rps * air_time_seconds

    thresholds = [
        (0.8, 1.8, "单圈跳 (1T/1S/1Lo/1F/1Lz)"),
        (1.8, 2.8, "双圈跳 (2A/2T/2S/2Lo/2F/2Lz)"),
        (2.8, 3.8, "三圈跳 (3A/3T/3S/3Lo/3F/3Lz)"),
        (3.8, 5.0, "四圈跳 (4T/4S/4Lo/4F/4Lz)"),
    ]
    probable = "unknown"
    for low, high, label in thresholds:
        if low <= rotations < high:
            probable = label
            break

    return {
        "estimated_rotations": round(rotations, 2),
        "probable_jump_type": probable,
    }


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _invalid_metrics(reason: str) -> dict[str, Any]:
    return {
        "jump_metrics": _empty_jump_metrics(),
        "jump_metrics_status": "invalid",
        "jump_metrics_warning": reason,
    }


def sanitize_biomechanics_data(bio_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(bio_data, dict):
        return _empty_analysis()

    analysis_profile = str(bio_data.get("analysis_profile", "jump") or "jump")
    if analysis_profile != "jump":
        sanitized = dict(bio_data)
        sanitized["jump_metrics"] = None
        sanitized["jump_metrics_status"] = "not_applicable"
        sanitized["jump_metrics_warning"] = None
        sanitized.setdefault("discipline_metrics", {})
        sanitized.setdefault("quality_flags", [])
        return sanitized

    sanitized = dict(bio_data)
    key_frames = sanitized.get("key_frames")
    metrics = sanitized.get("jump_metrics")
    if not isinstance(metrics, dict):
        sanitized.update(_invalid_metrics("未检测到有效跳跃数据"))
        return sanitized

    metric_values = {
        "air_time_seconds": _to_float(metrics.get("air_time_seconds")),
        "estimated_height_cm": _to_float(metrics.get("estimated_height_cm")),
        "takeoff_speed_mps": _to_float(metrics.get("takeoff_speed_mps")),
        "rotation_rps": _to_float(metrics.get("rotation_rps")),
    }

    warning: str | None = None
    if not isinstance(key_frames, dict) or not all(key_frames.get(label) for label in ("T", "A", "L")):
        warning = "关键帧检测异常"
    elif any(value is None for value in metric_values.values()):
        warning = "关键指标缺失"
    else:
        air_time = metric_values["air_time_seconds"]
        height = metric_values["estimated_height_cm"]
        takeoff_speed = metric_values["takeoff_speed_mps"]
        rotation = metric_values["rotation_rps"]
        if air_time is None or air_time <= 0 or air_time > MAX_AIR_TIME_SECONDS:
            warning = "滞空时间检测异常"
        elif height is None or height <= 0 or height > MAX_HEIGHT_CM:
            warning = "跳跃高度检测异常"
        elif takeoff_speed is None or takeoff_speed <= 0 or takeoff_speed > MAX_TAKEOFF_SPEED_MPS:
            warning = "起跳速度检测异常"
        elif rotation is None or rotation <= 0 or rotation > MAX_ROTATION_RPS:
            warning = "转速检测异常"

    if warning:
        sanitized.update(_invalid_metrics(warning))
        return sanitized

    sanitized["jump_metrics"] = {
        "air_time_seconds": round(metric_values["air_time_seconds"], 2),
        "estimated_height_cm": round(metric_values["estimated_height_cm"], 1),
        "takeoff_speed_mps": round(metric_values["takeoff_speed_mps"], 2),
        "rotation_rps": round(metric_values["rotation_rps"], 2),
        **estimate_jump_rotations(
            metric_values["rotation_rps"],
            metric_values["air_time_seconds"],
        ),
    }
    sanitized["jump_metrics_status"] = "ok"
    sanitized["jump_metrics_warning"] = None
    return sanitized


def attach_key_frame_candidates(
    bio_data: dict[str, Any],
    pose_data: dict[str, Any] | None,
    motion_scores: dict[str, Any] | None,
    analysis_profile: str,
    effective_fps: float | None,
) -> dict[str, Any]:
    """Return biomechanics payload with T/A/L key-frame candidates attached.

    The legacy ``key_frames`` field is left untouched. Candidate detection is
    additive so older consumers can keep reading ``key_frames`` while newer
    evaluation paths inspect ``key_frame_candidates``.
    """
    updated = dict(bio_data) if isinstance(bio_data, dict) else {}
    try:
        updated["key_frame_candidates"] = detect_key_frame_candidates(
            pose_data,
            motion_scores,
            analysis_profile,
            _valid_effective_fps(effective_fps),
        )
    except Exception as exc:  # noqa: BLE001
        warning = "keyframe_candidates_detection_failed"
        updated["key_frame_candidates"] = {
            "T": {"frame_id": None, "timestamp": None, "confidence": 0.0, "evidence": {}, "warnings": [warning]},
            "A": {"frame_id": None, "timestamp": None, "confidence": 0.0, "evidence": {}, "warnings": [warning]},
            "L": {"frame_id": None, "timestamp": None, "confidence": 0.0, "evidence": {}, "warnings": [warning]},
            "quality_flags": [warning],
            "error": str(exc),
        }
    return updated


def _score_from_values(values: list[float], ideal: float, tolerance: float, invert: bool = False) -> int:
    if not values:
        return 65
    average = sum(values) / len(values)
    distance = abs(average - ideal)
    score = 100 - (distance / tolerance) * 35
    if invert:
        score = 100 - average
    return max(40, min(100, round(score)))


def _spiral_discipline_metrics(
    trunk_tilts: list[dict[str, Any]],
    knee_angles: list[dict[str, Any]],
    arm_symmetry: list[dict[str, Any]],
    com_trajectory: dict[str, Any],
) -> dict[str, Any]:
    tilts = [float(item["tilt_degrees"]) for item in trunk_tilts if item.get("tilt_degrees") is not None]
    knees = [float(item["min_angle"]) for item in knee_angles if item.get("min_angle") is not None]
    symmetries = [float(item["symmetry"]) for item in arm_symmetry if item.get("symmetry") is not None]
    vertical_range = float(com_trajectory.get("vertical_range", 0.0) or 0.0)
    return {
        "trunk_pitch_degrees": round(sum(tilts) / len(tilts), 2) if tilts else None,
        "free_leg_extension_degrees": round((sum(knees) / len(knees)) - 20, 2) if knees else None,
        "hip_shoulder_alignment": round((sum(symmetries) / len(symmetries)) * 100, 1) if symmetries else None,
        "glide_stability": max(0, min(100, round(100 - vertical_range * 300))) if vertical_range else 65,
        "support_leg_stability": max(0, min(100, round(100 - abs((sum(knees) / len(knees)) - 155)))) if knees else 65,
    }


def _non_jump_bio_subscores(discipline_metrics: dict[str, Any], arm_symmetry: list[dict[str, Any]]) -> dict[str, int]:
    symmetries = [float(item["symmetry"]) for item in arm_symmetry if item.get("symmetry") is not None]
    arm_score = max(40, min(100, round((sum(symmetries) / len(symmetries)) * 100))) if symmetries else 65
    glide_stability = _to_float(discipline_metrics.get("glide_stability"))
    support_leg_stability = _to_float(discipline_metrics.get("support_leg_stability"))
    hip_shoulder_alignment = _to_float(discipline_metrics.get("hip_shoulder_alignment"))

    rotation_axis = round(glide_stability) if glide_stability is not None else 65
    landing_absorption = round(support_leg_stability) if support_leg_stability is not None else 65
    core_stability = round(hip_shoulder_alignment) if hip_shoulder_alignment is not None else rotation_axis
    takeoff_power_values = [value for value in (glide_stability, support_leg_stability) if value is not None]
    takeoff_power = round(sum(takeoff_power_values) / len(takeoff_power_values)) if takeoff_power_values else 65

    return {
        "takeoff_power": max(0, min(100, takeoff_power)),
        "rotation_axis": max(0, min(100, rotation_axis)),
        "arm_coordination": max(0, min(100, arm_score)),
        "landing_absorption": max(0, min(100, landing_absorption)),
        "core_stability": max(0, min(100, core_stability)),
    }


def analyze_biomechanics(
    pose_data: dict[str, Any],
    action_type: str,
    analysis_profile: str = "jump",
    *,
    effective_fps: float | None = None,
    source_fps: float | None = None,
    window_seconds: float | None = None,
) -> dict[str, Any]:
    """Analyze pose landmarks into biomechanics metrics.

    Args:
        pose_data: Pose payload with per-frame keypoints.
        action_type: Original action type label from the analysis request.
        analysis_profile: Normalized profile such as jump, spin, step, or spiral.
        effective_fps: Sampling frame rate on the real action timeline.
        source_fps: Source video frame rate for reporting context.
        window_seconds: Action-window duration on the real action timeline.

    Returns:
        Sanitized biomechanics payload suitable for persistence and report generation.

    Raises:
        No expected runtime exceptions; invalid or incomplete pose data returns an empty analysis payload.
    """
    del action_type
    if effective_fps is None:
        warnings.warn(
            "analyze_biomechanics() default effective_fps=5.0 is deprecated; pass sampling metadata.",
            DeprecationWarning,
            stacklevel=2,
        )
    normalized_effective_fps = _valid_effective_fps(effective_fps)
    sampling_context = _build_sampling_context(normalized_effective_fps, source_fps, window_seconds)

    frames = _biomechanics_frames(pose_data)
    if not frames:
        return _empty_analysis(analysis_profile=analysis_profile, sampling_context=sampling_context)

    knee_angles = []
    trunk_tilts = []
    arm_symmetry = []
    for index, frame in enumerate(frames, start=1):
        keypoints = frame.get("keypoints", [])
        knee_angles.append(calc_knee_angle(keypoints, index))
        trunk_tilts.append(calc_trunk_tilt(keypoints, index))
        arm_symmetry.append(calc_arm_symmetry(keypoints, index))

    com_trajectory = calc_center_of_mass_trajectory(pose_data)
    if not com_trajectory["points"]:
        return _empty_analysis(knee_angles, trunk_tilts, arm_symmetry, analysis_profile=analysis_profile, sampling_context=sampling_context)

    if analysis_profile != "jump":
        key_frames = detect_key_frames(com_trajectory, pose_data, analysis_profile)
        discipline_metrics = _spiral_discipline_metrics(trunk_tilts, knee_angles, arm_symmetry, com_trajectory)
        bio_subscores = _non_jump_bio_subscores(discipline_metrics, arm_symmetry)
        return sanitize_biomechanics_data(
            {
                "analysis_profile": analysis_profile,
                "sampling_context": sampling_context,
                "knee_angles": knee_angles,
                "trunk_tilts": trunk_tilts,
                "arm_symmetry": arm_symmetry,
                "com_trajectory": com_trajectory,
                "rotation_stability": {"average_tilt_degrees": None, "stability_score": 65},
                "bio_subscores": bio_subscores,
                "discipline_metrics": discipline_metrics,
                "quality_flags": [],
                "key_frames": key_frames,
                "jump_metrics": None,
                "jump_metrics_status": "not_applicable",
                "jump_metrics_warning": None,
            }
        )

    key_frames = detect_key_frames(com_trajectory, pose_data, analysis_profile)
    if not key_frames:
        return _empty_analysis(knee_angles, trunk_tilts, arm_symmetry, analysis_profile=analysis_profile, sampling_context=sampling_context)

    start_frame = _frame_number(key_frames.get("T", "frame_0001"))
    end_frame = _frame_number(key_frames.get("L", f"frame_{len(frames):04d}"))
    rotation_stability = calc_rotation_axis_stability(pose_data, start_frame, end_frame)

    min_knees = [item["min_angle"] for item in knee_angles if item.get("min_angle") is not None]
    tilts = [item["tilt_degrees"] for item in trunk_tilts if item.get("tilt_degrees") is not None]
    symmetries = [item["symmetry"] for item in arm_symmetry if item.get("symmetry") is not None]

    air_time_frames = max(end_frame - start_frame, 0)
    air_time_seconds = round(air_time_frames / normalized_effective_fps, 2)
    estimated_height_cm = round(0.5 * 9.8 * (air_time_seconds / 2) ** 2 * 100, 1) if air_time_seconds else None
    takeoff_speed_mps = round((2 * 9.8 * estimated_height_cm / 100) ** 0.5, 2) if estimated_height_cm else None

    bio_subscores = {
        "takeoff_power": _score_from_values(min_knees, 145, 55),
        "rotation_axis": int(rotation_stability.get("stability_score", 65)),
        "arm_coordination": max(40, min(100, round((sum(symmetries) / len(symmetries)) * 100))) if symmetries else 65,
        "landing_absorption": _score_from_values(min_knees[-5:], 135, 50) if min_knees else 65,
        "core_stability": _score_from_values(tilts, 8, 25),
    }

    return sanitize_biomechanics_data(
        {
            "analysis_profile": analysis_profile,
            "sampling_context": sampling_context,
            "knee_angles": knee_angles,
            "trunk_tilts": trunk_tilts,
            "arm_symmetry": arm_symmetry,
            "com_trajectory": com_trajectory,
            "rotation_stability": rotation_stability,
            "bio_subscores": bio_subscores,
            "discipline_metrics": {},
            "quality_flags": [],
            "key_frames": key_frames,
            "jump_metrics": {
                "air_time_seconds": air_time_seconds,
                "estimated_height_cm": estimated_height_cm,
                "takeoff_speed_mps": takeoff_speed_mps,
                "rotation_rps": _rotation_rps(pose_data, start_frame, end_frame, normalized_effective_fps),
            },
        }
    )
