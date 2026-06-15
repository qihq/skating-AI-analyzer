"""T/A/L key-frame candidate detection for jump analysis.

The detector is intentionally conservative: incomplete or noisy inputs return
low-confidence candidates with warnings instead of raising. Coordinates follow
MediaPipe image space, where smaller y means higher in the frame.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import math
from typing import Any, Iterable


DEFAULT_EFFECTIVE_FPS = 5.0
MIN_VISIBILITY = 0.3

SHOULDER_LEFT = 11
SHOULDER_RIGHT = 12
HIP_LEFT = 23
HIP_RIGHT = 24
KNEE_LEFT = 25
KNEE_RIGHT = 26
ANKLE_LEFT = 27
ANKLE_RIGHT = 28


CONFIDENCE_WEIGHTS = {
    "motion_peak_score": 0.10,
    "com_velocity_score": 0.34,
    "pose_visibility_score": 0.18,
    "knee_angle_change_score": 0.30,
    "phase_order_score": 0.08,
}
MISSING_POSE_CONFIDENCE_CAP = 0.55
MOTION_FALLBACK_UNRELIABLE_POSE_CONFIDENCE_CAP = 0.34
MOTION_FALLBACK_LOW_MOTION_CONFIDENCE_CAP = 0.34
TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_CONFIDENCE_CAP = 0.34
TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_MAX_VISIBILITY = 0.10
TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_MAX_TAKEOFF_TIMING = 0.05
TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_MAX_TAKEOFF_EVENT = 0.35
TAKEOFF_ANCHOR_TAIL_WINDOW_CONFIDENCE_CAP = 0.34
MOTION_FALLBACK_CROSS_SEGMENT_CONFIDENCE_CAP = 0.28
MOTION_FALLBACK_COMPRESSED_CONFIDENCE_CAP = 0.34
TEMPORAL_GEOMETRY_UNRELIABLE_CONFIDENCE_CAP = 0.49
TEMPORAL_GEOMETRY_COMPRESSED_CONFIDENCE_CAP = 0.34
WEAK_GEOMETRY_CONFIDENCE_CAP = 0.34
EXCLUDED_TRACKING_STATES = {"lost", "interpolated", "low_confidence"}
EXCLUDED_TRACKER_STATES = {
    "full_frame_yolo_relock_pending",
    "local_zoom_yolo_relock_pending",
    "relock_pending",
    "detector_relocked",
    "relocked",
    "continuity_rejected",
    "relock_rejected",
    "lost_reused",
}
MOTION_FALLBACK_MIN_PEAK_SCORE = 0.04
PARTIAL_TAL_LOW_MOTION_FALLBACK_MIN_PEAK_SCORE = 0.015
ORDERED_TAL_CONFIDENCE_FLOOR = 0.35
ORDERED_TAL_LOW_CONFIDENCE_MIN_RAW = 0.20
JUMP_MOTION_WINDOW_TOP_PEAK_RATIO = 0.85
JUMP_MOTION_WINDOW_CLUSTER_RATIO = 0.35
JUMP_MOTION_WINDOW_PRE_SEC = 0.45
JUMP_MOTION_WINDOW_POST_SEC = 2.05
JUMP_TAIL_MOTION_WINDOW_MIN_START_RATIO = 0.75
JUMP_TAIL_MOTION_WINDOW_MAX_SIGNAL_COUNT = 4
JUMP_TAIL_MOTION_WINDOW_MAX_PEAK_SCORE = 0.12
JUMP_TAIL_MOTION_WINDOW_TAKEOFF_EVENT_MAX = 0.42
JUMP_TAIL_MOTION_WINDOW_LANDING_CONTACT_MAX = 0.18
JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MIN_START_RATIO = 0.62
JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_SIGNAL_COUNT = 5
JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_TAL_SPAN_SEC = 0.36
JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_CORE_GAP_SEC = 0.18
JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_TAKEOFF_EVENT = 0.55
JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_LANDING_CONTACT = 0.35
JUMP_TAIL_MOTION_WINDOW_COMPRESSED_WEAK_TAKEOFF_EVENT = 0.42
JUMP_TAIL_MOTION_WINDOW_COMPRESSED_WEAK_APEX_COM = 0.50
SKELETON_DRIFT_MOTION_FALLBACK_APEX_MAX_GAP_SEC = 0.55
SKELETON_DRIFT_MOTION_FALLBACK_LANDING_MAX_GAP_SEC = 1.35
SKELETON_DRIFT_MOTION_FALLBACK_WEAK_LANDING_CONTACT = 0.18
SKELETON_DRIFT_MOTION_FALLBACK_LATE_WEAK_LANDING_GAP_SEC = 1.10
SKELETON_DRIFT_MOTION_FALLBACK_LATE_WEAK_APEX_GAP_SEC = 0.90
SKELETON_DRIFT_MOTION_FALLBACK_TAIL_RATIO = 0.35
SKELETON_DRIFT_MOTION_FALLBACK_TAIL_MIN_SCORE = 0.045
SKELETON_DRIFT_MOTION_FALLBACK_LOW_TAIL_EARLY_LANDING_MAX_APEX_GAP_SEC = 0.45
SKELETON_DRIFT_MOTION_FALLBACK_LOW_TAIL_EARLY_LANDING_MIN_SCORE = 0.035
SKELETON_DRIFT_MOTION_FALLBACK_LOW_TAIL_EARLY_LANDING_PEAK_RATIO = 0.85
MOTION_FALLBACK_RELIABLE_POSE_POST_SEC = 1.35
TAKEOFF_EARLY_APEX_GAP_SEC = 0.70
TAKEOFF_LATE_PLAUSIBLE_MIN_APEX_GAP_SEC = 0.05
TAKEOFF_LATE_PLAUSIBLE_MAX_APEX_GAP_SEC = 0.70
TAKEOFF_LATE_PLAUSIBLE_MIN_TIMING = 0.49
TAKEOFF_LATE_PLAUSIBLE_MIN_EVENT = 0.30
TAKEOFF_LATE_PLAUSIBLE_MIN_MOTION = 0.25
TAKEOFF_LATE_PLAUSIBLE_MIN_GEOMETRY = 0.45
TAKEOFF_LATE_PLAUSIBLE_MIN_EXTENSION = 0.12
TAKEOFF_LATE_PLAUSIBLE_MIN_CONFIDENCE = 0.40
TAKEOFF_LATE_PLAUSIBLE_MIN_RANK_RATIO = 0.78
TAKEOFF_LATE_PLAUSIBLE_MIN_SHIFT_SEC = 0.12
TAKEOFF_UNCLEAR_APEX_MIN_JOINT_TIMING = 0.20
TAKEOFF_UNCLEAR_APEX_SHORT_RESELECT_MAX_GAP_SEC = 1.05
TAKEOFF_COMPRESSED_RESELECT_FALLBACK_ORIGINAL_GAP_SEC = 1.20
TAKEOFF_COMPRESSED_RESELECT_FALLBACK_RESELECTED_GAP_SEC = 0.10
APEX_UNCLEAR_MOTION_MIN_RATIO = 0.42
APEX_UNCLEAR_MOTION_MIN_PEAK = 0.50
APEX_UNCLEAR_PRE_PEAK_SEC = 0.08
APEX_UNCLEAR_POST_PEAK_SEC = 0.42
APEX_UNCLEAR_TARGET_AFTER_PEAK_SEC = 0.14
APEX_MOTION_SUPPORTED_LOCAL_MIN_PROMINENCE_FLOOR = 0.006
APEX_MOTION_SUPPORTED_LOCAL_MIN_MIN_MOTION = 0.30
APEX_MOTION_SUPPORTED_LOCAL_MIN_MIN_TRAJECTORY = 0.005
WEAK_GEOMETRY_TAKEOFF_EVENT_MAX = 0.20
WEAK_GEOMETRY_TAKEOFF_JOINT_EXTENSION_MAX = 0.20
WEAK_GEOMETRY_TAKEOFF_JOINT_EVENT_MAX = 0.50
WEAK_GEOMETRY_LANDING_CONTACT_MAX = 0.30
WEAK_GEOMETRY_LANDING_JOINT_CONTACT_MAX = 0.36
WEAK_GEOMETRY_LANDING_CONTACT_HARD_MAX = 0.08
WEAK_GEOMETRY_LANDING_COMPONENT_HARD_MAX = 0.12
WEAK_GEOMETRY_LANDING_JOINT_COMPONENT_MAX = 0.12
WEAK_GEOMETRY_LANDING_ABSENT_MIN_APEX_GAP_SEC = 0.85
WEAK_GEOMETRY_APEX_COM_MAX = 0.35
WEAK_GEOMETRY_APEX_UNCLEAR_DESCENT_SUPPORT_MAX = 0.25
WEAK_LANDING_EARLY_CANDIDATE_UNTRUSTED_CONTACT_MAX = 0.55
WEAK_LANDING_EARLY_CANDIDATE_UNTRUSTED_KNEE_MAX = 0.22
WEAK_LANDING_EARLY_CANDIDATE_UNTRUSTED_DESCENT_MAX = 0.35
WEAK_GEOMETRY_MIN_FLAGS = 2
WEAK_TAL_TAKEOFF_APEX_GAP_SEC = 1.20
WEAK_TAL_APEX_LANDING_GAP_SEC = 1.00
WEAK_TAL_COMPRESSED_APEX_LANDING_GAP_SEC = 0.10
WEAK_TAL_COMPRESSED_APEX_LANDING_VISIBLE_SIGNAL_GAP_SEC = 0.14
WEAK_TAL_COMPRESSED_APEX_LANDING_WEAK_SIGNAL_GAP_SEC = 0.18
WEAK_TAL_COMPRESSED_APEX_LANDING_SIGNAL_GAP_SEC = 0.08
WEAK_TAL_COMPRESSED_CORE_TAKEOFF_APEX_GAP_SEC = 0.10
WEAK_TAL_COMPRESSED_CORE_APEX_LANDING_GAP_SEC = 0.16
WEAK_TAL_COMPRESSED_APEX_COM_MAX = 0.50
WEAK_TAL_COMPRESSED_TAKEOFF_APEX_SIGNAL_GAP_SEC = 0.08
WEAK_TAL_COMPRESSED_TAKEOFF_APEX_RESELECT_GAP_SEC = 0.08
WEAK_TAL_COMPRESSED_TAKEOFF_RESELECT_EVENT_MAX = 0.50
WEAK_TAL_COMPRESSED_TAKEOFF_RESELECT_EXTENSION_MAX = 0.20
WEAK_TAL_TAKEOFF_TIMING_MAX = 0.20
WEAK_TAL_LANDING_CONTACT_MAX = 0.20
WEAK_TAL_VISIBLE_COMPRESSED_LANDING_CONTACT_MAX = 0.65
WEAK_TAL_VISIBLE_COMPRESSED_APEX_MIN_VISIBILITY = 0.70
WEAK_TAL_LATE_LANDING_GAP_SEC = 1.00
WEAK_TAL_LATE_LANDING_TIMING_MAX = 0.05
WEAK_TAL_LATE_LANDING_MOTION_MAX = 0.15
WEAK_TAL_LATE_LANDING_KNEE_MAX = 0.12
WEAK_TAL_LATE_LANDING_CONTACT_MAX = 0.50
SPARSE_TAKEOFF_APEX_GAP_SEC = 0.90
SPARSE_TAKEOFF_MIN_SHIFT_SEC = 0.18
SPARSE_TAKEOFF_MIN_APEX_LEAD_SEC = 0.08
SPARSE_TAKEOFF_MAX_APEX_LEAD_SEC = 0.75
SPARSE_TAKEOFF_TARGET_APEX_LEAD_SEC = 0.42
SPARSE_TAKEOFF_TIMING_MAX = 0.25
SPARSE_TAKEOFF_MIN_MOTION_RATIO = 0.55
SPARSE_PREPEAK_TAKEOFF_COMPRESSED_APEX_GAP_SEC = 0.20
SPARSE_PREPEAK_TAKEOFF_MIN_SIGNAL_GAP_SEC = 0.45
SPARSE_PREPEAK_TAKEOFF_TARGET_APEX_LEAD_SEC = 0.56
SPARSE_PREPEAK_TAKEOFF_MIN_SELECTED_MOTION = 0.60
SPARSE_PREPEAK_TAKEOFF_MAX_PREVIOUS_MOTION_RATIO = 0.65
SPARSE_PREPEAK_TAKEOFF_MIN_SELECTED_COM_ASCENT = 0.55
SPARSE_PREPEAK_TAKEOFF_MIN_SELECTED_EVENT = 0.40
SPARSE_PREPEAK_TAKEOFF_MIN_SHIFT_SEC = 0.16
SPARSE_PREPEAK_TAKEOFF_CONFIDENCE_CAP = 0.58
WEAK_LANDING_CONTACT_EARLY_SELECTION_MAX = 0.12
WEAK_LANDING_FOOT_CONTACT_MAX = 0.12
WEAK_LANDING_FOOT_CONTACT_TOTAL_MAX = 0.36
WEAK_LANDING_EARLY_MOTION_MIN = 0.30
WEAK_LANDING_LATE_TIMING_MAX = 0.05
WEAK_LANDING_LATE_CONTACT_MAX = 0.42
WEAK_LANDING_EARLY_CONTACT_MIN = 0.18
WEAK_LANDING_EARLY_TIMING_MIN = 0.75
LANDING_STRONG_CONTACT_MIN_APEX_GAP_SEC = 0.08
LANDING_COMPRESSED_RESELECT_MIN_APEX_GAP_SEC = 0.12
LANDING_COMPRESSED_RESELECT_MAX_APEX_GAP_SEC = 0.85
LANDING_COMPRESSED_RESELECT_STRONG_ORIGINAL_CONTACT = 0.80
LANDING_COMPRESSED_RESELECT_MIN_CONTACT = 0.18
LANDING_COMPRESSED_RESELECT_MIN_CONTACT_RATIO = 0.35
LANDING_COMPRESSED_RESELECT_MIN_MOTION = 0.30
SPARSE_TRACK_MAX_TAL_GAP_SEC = 1.80
SPARSE_TRACK_MAX_SIGNAL_INDEX_GAP = 4
SPARSE_TRACK_MIN_TIME_GAP_SEC = 1.20
SPARSE_TRACK_WEAK_APEX_LANDING_GAP_SEC = 1.00
SPARSE_TRACK_WEAK_LANDING_CONTACT_MAX = 0.22
SPARSE_TRACK_CONFIDENCE_CAP = 0.34
MOTION_WINDOW_UNRELIABLE_STATE_MIN_COUNT = 2
MOTION_WINDOW_UNRELIABLE_STATE_MIN_RATIO = 0.20
MOTION_WINDOW_UNRELIABLE_PEAK_MATCH_TOLERANCE_SEC = 0.20
MOTION_WINDOW_CONTAMINATED_LANDING_CONTACT_MAX = 0.18
OCCLUDED_MOTION_PEAK_OVERRIDE_MIN_TAKEOFF_LAG_SEC = 0.55
OCCLUDED_MOTION_PEAK_OVERRIDE_PRE_SEC = 0.75
OCCLUDED_MOTION_PEAK_OVERRIDE_POST_SEC = 0.62
OCCLUDED_MOTION_PEAK_OVERRIDE_TAKEOFF_OFFSET_SEC = 0.56
OCCLUDED_MOTION_PEAK_OVERRIDE_APEX_OFFSET_SEC = 0.0
OCCLUDED_MOTION_PEAK_OVERRIDE_LANDING_OFFSET_SEC = 0.34
OCCLUDED_MOTION_PEAK_OVERRIDE_RECORD_SNAP_TOLERANCE_SEC = 0.10
OCCLUDED_MOTION_PEAK_OVERRIDE_CONFIDENCE_CAP = 0.34
MOTION_FALLBACK_RELIABLE_RECORD_MIN_COUNT = 3
MOTION_FALLBACK_LOCAL_TAKEOFF_APEX_MIN_GAP_SEC = 0.04
MOTION_FALLBACK_LOCAL_TAKEOFF_APEX_MAX_GAP_SEC = 1.10
MOTION_FALLBACK_LOCAL_APEX_LANDING_MIN_GAP_SEC = 0.04
MOTION_FALLBACK_LOCAL_APEX_LANDING_MAX_GAP_SEC = 1.45
MOTION_FALLBACK_LOCAL_MAX_TAL_SPAN_SEC = 1.80
MOTION_FALLBACK_COMPRESSED_TAL_SPAN_SEC = 0.32
MOTION_FALLBACK_COMPRESSED_CORE_GAP_SEC = 0.10
MOTION_FALLBACK_LOCAL_TARGET_TAKEOFF_APEX_GAP_SEC = 0.38
MOTION_FALLBACK_LOCAL_TARGET_APEX_LANDING_GAP_SEC = 0.62
MOTION_FALLBACK_TINY_TARGET_MAX_MEDIAN_WIDTH = 0.035
MOTION_FALLBACK_TINY_TARGET_MAX_MEDIAN_AREA = 0.006
MOTION_FALLBACK_TINY_TARGET_MAX_VISIBILITY = 0.08
MOTION_FALLBACK_FOREGROUND_RISK_CONFIDENCE_CAP = 0.34
TINY_TARGET_WEAK_GEOMETRY_CONFIDENCE_CAP = 0.34
TINY_TARGET_LOW_POSE_TRACKING_RISK_FLAG = "person_tracker_tiny_target_low_pose_tracking_risk"
MULTIPERSON_RELOCK_INSTABILITY_RISK_FLAG = "person_tracker_multiperson_relock_instability_risk"
MOTION_FALLBACK_DENSE_MIN_SCORE_COUNT = 12
MOTION_FALLBACK_DENSE_MIN_SELECTED_MULTIPLIER = 2.0
TAKEOFF_ANCHOR_TAIL_FALLBACK_MIN_DURATION_SEC = 6.0
TAKEOFF_ANCHOR_TAIL_FALLBACK_MIN_START_RATIO = 0.70
TAKEOFF_ANCHOR_TAIL_FALLBACK_MAX_VISIBILITY = 0.10
MAX_JUMP_MOTION_SEARCH_WINDOWS = 5
COMPRESSED_WEAK_WINDOW_RESELECT_MAX_AVG_CONFIDENCE = 0.55
COMPRESSED_WEAK_WINDOW_RESELECT_MIN_ALTERNATIVE_CONFIDENCE = 0.45
COMPRESSED_WEAK_WINDOW_EARLY_ALT_MIN_PEAK_RATIO = 0.95
COMPRESSED_WEAK_WINDOW_EARLY_ALT_MIN_GAP_SEC = 0.45
EARLY_WEAK_MOTION_WINDOW_CONFIDENCE_CAP = 0.34
EARLY_WEAK_MOTION_WINDOW_MAX_START_SEC = 1.0
EARLY_WEAK_MOTION_WINDOW_MAX_START_RATIO = 0.15
EARLY_WEAK_MOTION_WINDOW_MAX_END_RATIO = 0.60
EARLY_WEAK_MOTION_WINDOW_MIN_DURATION_SEC = 5.0
EARLY_WEAK_MOTION_WINDOW_MIN_LATER_GAP_SEC = 0.45
EARLY_WEAK_MOTION_WINDOW_MIN_LATER_PEAK_RATIO = 0.90
LATE_POSE_CORE_RESELECT_MIN_DURATION_SEC = 5.0
LATE_POSE_CORE_RESELECT_MAX_EARLY_WINDOW_END_RATIO = 0.60
LATE_POSE_CORE_RESELECT_BOUNDARY_GAP_SEC = 0.85
LATE_POSE_CORE_RESELECT_MAX_START_OVERLAP_SEC = 0.25
LATE_POSE_CORE_RESELECT_MIN_END_EXTENSION_SEC = 0.25
LATE_POSE_CORE_RESELECT_MAX_SELECTED_END_GAP_SEC = 0.20
LATE_POSE_CORE_RESELECT_MIN_SIGNAL_COUNT = 3
LATE_POSE_CORE_RESELECT_MIN_SPAN_SEC = 0.25
LATE_POSE_CORE_RESELECT_MAX_SPAN_SEC = 1.00
LATE_POSE_CORE_RESELECT_MIN_AVG_VISIBILITY = 0.70
LATE_POSE_CORE_RESELECT_MIN_TAIL_LEAD_SEC = 0.45
LATE_POSE_CORE_RESELECT_MAX_PEAK_RATIO = 0.75
LATE_POSE_CORE_RESELECT_MIN_AVG_CONFIDENCE = 0.38
LATE_POSE_CORE_RESELECT_MIN_APEX_CONFIDENCE = 0.38
LATE_POSE_CORE_RESELECT_MIN_LANDING_CONFIDENCE = 0.35
LATE_POSE_CORE_RESELECT_MIN_TAKEOFF_CONFIDENCE = 0.28
LATE_POSE_CORE_RESELECT_MIN_TAKEOFF_APEX_GAP_SEC = 0.12
LATE_POSE_CORE_RESELECT_MAX_TAKEOFF_APEX_GAP_SEC = 0.75


@dataclass(frozen=True)
class _Point:
    x: float
    y: float
    z: float
    visibility: float


@dataclass(frozen=True)
class _FrameSignal:
    index: int
    frame_id: str
    timestamp: float
    com_y: float | None
    hip_y: float | None
    ankle_y: float | None
    knee_angle: float | None
    motion_score: float | None
    visibility_score: float


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalized_score(value: float | None, warning: str, warnings: list[str]) -> float:
    numeric = _to_float(value)
    if numeric is None:
        warnings.append(warning)
        return 0.0
    return _clamp(numeric)


def calculate_key_frame_confidence(
    motion_peak_score: float | None,
    com_velocity_score: float | None,
    pose_visibility_score: float | None,
    knee_angle_change_score: float | None,
    phase_order_score: float | None,
    warnings: list[str] | None = None,
) -> float:
    """Calculate a normalized T/A/L key-frame confidence score.

    Args:
        motion_peak_score: Motion peak strength normalized to 0..1.
        com_velocity_score: COM trajectory/velocity evidence normalized to 0..1.
        pose_visibility_score: Pose landmark visibility normalized to 0..1.
        knee_angle_change_score: Knee extension/absorption evidence normalized to 0..1.
        phase_order_score: T/A/L ordering evidence normalized to 0..1.
        warnings: Optional list that receives missing-signal warning codes.

    Returns:
        Confidence clamped to ``0.0..1.0``. Missing signals contribute 0.0
        rather than being renormalized. Missing pose visibility additionally
        caps confidence at 0.55 because geometry cannot be trusted.
    """
    collected_warnings = warnings if warnings is not None else []
    pose_missing = _to_float(pose_visibility_score) is None
    scores = {
        "motion_peak_score": _normalized_score(motion_peak_score, "confidence_missing_motion_peak", collected_warnings),
        "com_velocity_score": _normalized_score(com_velocity_score, "confidence_missing_com_velocity", collected_warnings),
        "pose_visibility_score": _normalized_score(pose_visibility_score, "confidence_missing_pose_visibility", collected_warnings),
        "knee_angle_change_score": _normalized_score(knee_angle_change_score, "confidence_missing_knee_angle_change", collected_warnings),
        "phase_order_score": _normalized_score(phase_order_score, "confidence_missing_phase_order", collected_warnings),
    }
    confidence = sum(scores[key] * weight for key, weight in CONFIDENCE_WEIGHTS.items())
    if pose_missing:
        confidence = min(confidence, MISSING_POSE_CONFIDENCE_CAP)
    return round(_clamp(confidence), 3)


def _legacy_takeoff_rank_confidence(
    motion_peak_score: float,
    com_velocity_score: float,
    pose_visibility_score: float,
    knee_angle_change_score: float,
    phase_order_score: float,
) -> float:
    return _clamp(
        0.22 * _clamp(motion_peak_score)
        + 0.30 * _clamp(com_velocity_score)
        + 0.18 * _clamp(pose_visibility_score)
        + 0.22 * _clamp(knee_angle_change_score)
        + 0.08 * _clamp(phase_order_score)
    )


def _frame_stem(frame_name: Any) -> str:
    raw = str(frame_name or "")
    return raw[:-4] if raw.lower().endswith(".jpg") else raw


def _frame_number(frame_name: Any) -> int:
    digits = "".join(char for char in str(frame_name or "") if char.isdigit())
    return int(digits or "0")


def _empty_candidate(warnings: Iterable[str] | None = None) -> dict[str, Any]:
    return {
        "frame_id": None,
        "timestamp": None,
        "confidence": 0.0,
        "evidence": {},
        "warnings": list(warnings or []),
    }


def _candidate(
    signal: _FrameSignal,
    confidence: float,
    evidence: dict[str, Any],
    warnings: Iterable[str] | None = None,
) -> dict[str, Any]:
    return {
        "frame_id": signal.frame_id,
        "timestamp": round(signal.timestamp, 3),
        "confidence": round(_clamp(confidence), 3),
        "evidence": {
            "pose_index": signal.index,
            "motion_score": signal.motion_score,
            "visibility_score": round(signal.visibility_score, 3),
            **evidence,
        },
        "warnings": list(warnings or []),
    }


def _motion_only_candidate(
    record: tuple[int, str, float, float],
    role: str,
    confidence: float,
    normalized_motion: float,
    warnings: Iterable[str],
    *,
    extra_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index, frame_id, timestamp, motion_score = record
    signal = _FrameSignal(
        index=index,
        frame_id=frame_id,
        timestamp=timestamp,
        com_y=None,
        hip_y=None,
        ankle_y=None,
        knee_angle=None,
        motion_score=motion_score,
        visibility_score=0.0,
    )
    return _candidate(
        signal,
        confidence,
        {
            "signal_index": index,
            "motion_fallback": True,
            "motion_fallback_role": role,
            "motion_score": round(motion_score, 5),
            "normalized_motion_score": round(normalized_motion, 3),
            "score_components": {
                "motion_peak": round(normalized_motion, 3),
                "com_velocity": None,
                "pose_visibility": 0.0,
                "knee_angle_change": None,
                "phase_order": 1.0,
            },
            **(extra_evidence or {}),
        },
        warnings,
    )


def _pose_frame_state_by_frame(pose_data: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not isinstance(frames, list):
        return {}
    states: dict[str, dict[str, str]] = {}
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            continue
        frame_id = _frame_stem(frame.get("frame") or frame.get("frame_id") or f"frame_{index + 1:04d}")
        tracking_state = str(frame.get("tracking_state") or "tracked")
        tracker_state = str(frame.get("tracker_state") or "")
        states[frame_id] = {
            "tracking_state": tracking_state,
            "tracker_state": tracker_state,
        }
    return states


def _motion_record_unreliable_pose_state(
    record: tuple[int, str, float, float],
    frame_states: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    state = frame_states.get(_frame_stem(record[1]))
    if not isinstance(state, dict):
        return None
    tracking_state = state.get("tracking_state") or "tracked"
    tracker_state = state.get("tracker_state") or ""
    if tracking_state not in EXCLUDED_TRACKING_STATES and tracker_state not in EXCLUDED_TRACKER_STATES:
        return None
    return {
        "tracking_state": tracking_state,
        "tracker_state": tracker_state,
    }


def _motion_record_state_payload(
    record: tuple[int, str, float, float],
    state: dict[str, str],
) -> dict[str, Any]:
    return {
        "frame_id": record[1],
        "timestamp": round(record[2], 3),
        **state,
    }


def _pose_target_bbox_stats(pose_data: dict[str, Any] | None) -> dict[str, Any] | None:
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not isinstance(frames, list):
        return None

    widths: list[float] = []
    heights: list[float] = []
    areas: list[float] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        bbox = frame.get("target_bbox")
        if not isinstance(bbox, dict):
            continue
        width = _to_float(bbox.get("width", bbox.get("w")))
        height = _to_float(bbox.get("height", bbox.get("h")))
        if width is None or height is None or width <= 0.0 or height <= 0.0:
            continue
        widths.append(width)
        heights.append(height)
        areas.append(width * height)
    if not widths:
        return None

    def median(values: list[float]) -> float:
        ordered = sorted(values)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[midpoint]
        return (ordered[midpoint - 1] + ordered[midpoint]) / 2

    return {
        "frame_count": len(widths),
        "median_width": round(median(widths), 5),
        "median_height": round(median(heights), 5),
        "median_area": round(median(areas), 6),
        "min_area": round(min(areas), 6),
        "max_area": round(max(areas), 6),
    }


def _tiny_target_motion_fallback_diagnostic(
    pose_data: dict[str, Any] | None,
    candidates: dict[str, Any],
    *,
    max_score: float,
    compressed_fallback: bool,
) -> dict[str, Any] | None:
    bbox_stats = _pose_target_bbox_stats(pose_data)
    if not bbox_stats:
        return None
    median_width = _to_float(bbox_stats.get("median_width"))
    median_area = _to_float(bbox_stats.get("median_area"))
    tiny_target = (
        median_width is not None
        and median_area is not None
        and (
            median_width <= MOTION_FALLBACK_TINY_TARGET_MAX_MEDIAN_WIDTH
            or median_area <= MOTION_FALLBACK_TINY_TARGET_MAX_MEDIAN_AREA
        )
    )
    if not tiny_target:
        return None

    visibility_scores: list[float] = []
    candidate_timestamps: dict[str, float] = {}
    all_motion_only = True
    for role in ("T", "A", "L"):
        candidate = candidates.get(role)
        if not isinstance(candidate, dict):
            return None
        timestamp = _to_float(candidate.get("timestamp"))
        if timestamp is not None:
            candidate_timestamps[role] = round(timestamp, 3)
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
        if evidence.get("motion_fallback") is not True and "keyframe_candidates_motion_fallback" not in warnings:
            all_motion_only = False
        visibility = _to_float(evidence.get("visibility_score"))
        if visibility is None:
            score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
            visibility = _to_float(score_components.get("pose_visibility"))
        if visibility is not None:
            visibility_scores.append(visibility)
    if not all_motion_only or len(visibility_scores) < 3:
        return None
    max_visibility = max(visibility_scores)
    if max_visibility > MOTION_FALLBACK_TINY_TARGET_MAX_VISIBILITY:
        return None

    return {
        "bbox_stats": bbox_stats,
        "candidate_timestamps": candidate_timestamps,
        "max_candidate_visibility": round(max_visibility, 3),
        "max_motion_score": round(max_score, 5),
        "compressed": bool(compressed_fallback),
        "reason": "tiny_target_low_visibility_motion_only_fallback",
    }


def _pose_quality_flags(pose_data: dict[str, Any] | None) -> set[str]:
    if not isinstance(pose_data, dict):
        return set()
    raw_flags = pose_data.get("quality_flags")
    if not isinstance(raw_flags, list):
        return set()
    return {str(flag).strip() for flag in raw_flags if str(flag).strip()}


def _multiperson_relock_motion_fallback_diagnostic(
    pose_data: dict[str, Any] | None,
    *,
    max_score: float,
    compressed_fallback: bool,
) -> dict[str, Any] | None:
    if MULTIPERSON_RELOCK_INSTABILITY_RISK_FLAG not in _pose_quality_flags(pose_data):
        return None
    return {
        "reason": "multiperson_relock_instability_motion_only_fallback",
        "max_motion_score": round(max_score, 5),
        "compressed": bool(compressed_fallback),
    }


def _keypoint(
    keypoints: Any,
    index: int,
    *,
    min_visibility: float = MIN_VISIBILITY,
) -> _Point | None:
    if not isinstance(keypoints, list):
        return None

    raw: Any | None = None
    if index < len(keypoints) and isinstance(keypoints[index], dict):
        raw = keypoints[index]
    else:
        raw = next(
            (
                item
                for item in keypoints
                if isinstance(item, dict) and int(item.get("id", -1) or -1) == index
            ),
            None,
        )
    if not isinstance(raw, dict):
        return None

    x_value = _to_float(raw.get("x"))
    y_value = _to_float(raw.get("y"))
    if x_value is None or y_value is None:
        return None
    z_value = _to_float(raw.get("z")) or 0.0
    visibility = _to_float(raw.get("visibility"))
    if visibility is None:
        visibility = 1.0
    if visibility < min_visibility:
        return None
    return _Point(x=x_value, y=y_value, z=z_value, visibility=visibility)


def _visibility_score(keypoints: Any) -> float:
    if not isinstance(keypoints, list):
        return 0.0
    values: list[float] = []
    for index in (SHOULDER_LEFT, SHOULDER_RIGHT, HIP_LEFT, HIP_RIGHT, KNEE_LEFT, KNEE_RIGHT, ANKLE_LEFT, ANKLE_RIGHT):
        raw: Any | None = None
        if index < len(keypoints) and isinstance(keypoints[index], dict):
            raw = keypoints[index]
        else:
            raw = next(
                (
                    item
                    for item in keypoints
                    if isinstance(item, dict) and int(item.get("id", -1) or -1) == index
                ),
                None,
            )
        if isinstance(raw, dict) and raw.get("x") is not None and raw.get("y") is not None:
            values.append(_to_float(raw.get("visibility")) if _to_float(raw.get("visibility")) is not None else 1.0)
    return sum(values) / len(values) if values else 0.0


def _midpoint(a: _Point, b: _Point) -> _Point:
    return _Point(
        x=(a.x + b.x) / 2,
        y=(a.y + b.y) / 2,
        z=(a.z + b.z) / 2,
        visibility=(a.visibility + b.visibility) / 2,
    )


def _angle(a: _Point, b: _Point, c: _Point) -> float | None:
    ab = (a.x - b.x, a.y - b.y)
    cb = (c.x - b.x, c.y - b.y)
    mag_ab = math.hypot(*ab)
    mag_cb = math.hypot(*cb)
    if mag_ab <= 1e-9 or mag_cb <= 1e-9:
        return None
    cosine = _clamp((ab[0] * cb[0] + ab[1] * cb[1]) / (mag_ab * mag_cb), -1.0, 1.0)
    return math.degrees(math.acos(cosine))


def _com_y(keypoints: Any) -> tuple[float | None, float | None]:
    shoulders = [_keypoint(keypoints, SHOULDER_LEFT), _keypoint(keypoints, SHOULDER_RIGHT)]
    hips = [_keypoint(keypoints, HIP_LEFT), _keypoint(keypoints, HIP_RIGHT)]
    visible = [point for point in shoulders + hips if point is not None]
    hip_points = [point for point in hips if point is not None]
    com = sum(point.y for point in visible) / len(visible) if visible else None
    hip = sum(point.y for point in hip_points) / len(hip_points) if hip_points else None
    return com, hip


def _ankle_y(keypoints: Any) -> float | None:
    ankles = [_keypoint(keypoints, ANKLE_LEFT), _keypoint(keypoints, ANKLE_RIGHT)]
    visible = [point.y for point in ankles if point is not None]
    return sum(visible) / len(visible) if visible else None


def _knee_angle(keypoints: Any) -> float | None:
    left = [_keypoint(keypoints, index) for index in (HIP_LEFT, KNEE_LEFT, ANKLE_LEFT)]
    right = [_keypoint(keypoints, index) for index in (HIP_RIGHT, KNEE_RIGHT, ANKLE_RIGHT)]
    values = [
        angle
        for angle in (
            _angle(left[0], left[1], left[2]) if all(left) else None,
            _angle(right[0], right[1], right[2]) if all(right) else None,
        )
        if angle is not None
    ]
    return sum(values) / len(values) if values else None


def _valid_effective_fps(effective_fps: float | None) -> float:
    numeric = _to_float(effective_fps)
    if numeric is None or numeric <= 0:
        return DEFAULT_EFFECTIVE_FPS
    return numeric


def _selected_records(motion_scores: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[float]]:
    if not isinstance(motion_scores, dict):
        return {}, [], []

    selected = [item for item in motion_scores.get("selected", []) if isinstance(item, dict)]
    by_frame: dict[str, dict[str, Any]] = {}
    for item in selected:
        frame_id = _frame_stem(item.get("frame_id") or item.get("frame") or "")
        if frame_id:
            by_frame[frame_id] = item

    scores = [
        float(score)
        for score in motion_scores.get("scores", [])
        if isinstance(score, (int, float)) and not math.isnan(float(score)) and not math.isinf(float(score))
    ]
    return by_frame, selected, scores


def _motion_records(motion_scores: dict[str, Any] | None, effective_fps: float) -> list[tuple[int, str, float, float]]:
    if not isinstance(motion_scores, dict):
        return []

    _, selected, score_series = _selected_records(motion_scores)
    records: list[tuple[int, str, float, float]] = []
    if selected:
        for index, item in enumerate(selected):
            frame_id = _frame_stem(item.get("frame_id") or item.get("frame") or f"frame_{index + 1:04d}")
            score = _to_float(item.get("motion_score"))
            if score is None and index < len(score_series):
                score = score_series[index]
            if score is None:
                continue
            timestamp = _to_float(item.get("timestamp"))
            if timestamp is None:
                timestamp = index / effective_fps
            records.append((index, frame_id, timestamp, score))
        return records

    return [
        (index, f"frame_{index + 1:04d}", index / effective_fps, score)
        for index, score in enumerate(score_series)
    ]


def _dense_motion_score_records(
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    selected_records: list[tuple[int, str, float, float]],
) -> list[tuple[int, str, float, float]]:
    if not isinstance(motion_scores, dict):
        return []
    _, _, score_series = _selected_records(motion_scores)
    if len(score_series) < MOTION_FALLBACK_DENSE_MIN_SCORE_COUNT:
        return []
    if selected_records and len(score_series) < len(selected_records) * MOTION_FALLBACK_DENSE_MIN_SELECTED_MULTIPLIER:
        return []

    frame_rate = _to_float(motion_scores.get("frame_rate")) or _valid_effective_fps(effective_fps)
    if frame_rate <= 0.0:
        return []
    start = _to_float(motion_scores.get("window_start"))
    if start is None:
        start = _to_float(motion_scores.get("window_start_sec")) or 0.0

    def nearest_sampled_frame_id(timestamp: float, index: int) -> str:
        if not selected_records:
            return f"frame_{index + 1:04d}"
        nearest = min(selected_records, key=lambda record: (abs(record[2] - timestamp), -record[3], record[0]))
        return nearest[1]

    return [
        (index, nearest_sampled_frame_id(start + index / frame_rate, index), start + index / frame_rate, score)
        for index, score in enumerate(score_series)
    ]


def _apply_motion_record_filters(
    records: list[tuple[int, str, float, float]],
    *,
    time_bounds: tuple[float, float] | None,
    strict_time_bounds: bool,
    excluded_time_windows: list[tuple[float, float]] | None,
    frame_states: dict[str, dict[str, str]],
) -> tuple[list[tuple[int, str, float, float]] | None, bool, list[dict[str, Any]], list[dict[str, Any]]]:
    if len(records) < 3:
        return None, False, [], []

    bounds_applied = False
    if time_bounds is not None:
        start_ts, end_ts = time_bounds
        bounded = [record for record in records if start_ts <= record[2] <= end_ts]
        if len(bounded) >= 3:
            records = bounded
            bounds_applied = True
        elif strict_time_bounds:
            return None, bounds_applied, [], []

    excluded_records: list[dict[str, Any]] = []
    if excluded_time_windows:
        normalized_windows = [
            (min(start, end), max(start, end))
            for start, end in excluded_time_windows
            if _to_float(start) is not None and _to_float(end) is not None
        ]
        if normalized_windows:
            retained: list[tuple[int, str, float, float]] = []
            for record in records:
                if any(start <= record[2] <= end for start, end in normalized_windows):
                    excluded_records.append(
                        {
                            "frame_id": record[1],
                            "timestamp": round(record[2], 3),
                            "motion_score": round(record[3], 5),
                        }
                    )
                else:
                    retained.append(record)
            if len(retained) < 3:
                return None, bounds_applied, excluded_records, []
            records = retained

    filtered_unreliable_records: list[dict[str, Any]] = []
    if frame_states:
        reliable_records: list[tuple[int, str, float, float]] = []
        for record in records:
            unreliable_state = _motion_record_unreliable_pose_state(record, frame_states)
            if unreliable_state is None:
                reliable_records.append(record)
            else:
                filtered_unreliable_records.append(_motion_record_state_payload(record, unreliable_state))
        if len(reliable_records) >= MOTION_FALLBACK_RELIABLE_RECORD_MIN_COUNT:
            records = reliable_records

    return records, bounds_applied, excluded_records, filtered_unreliable_records


def _best_motion_record(records: list[tuple[int, str, float, float]], *, prefer_late: bool) -> tuple[int, str, float, float]:
    if prefer_late:
        return max(records, key=lambda item: (item[3], item[0]))
    return max(records, key=lambda item: (item[3], -item[0]))


def _legacy_motion_fallback_triplet(
    records: list[tuple[int, str, float, float]],
) -> tuple[tuple[int, str, float, float], tuple[int, str, float, float], tuple[int, str, float, float]]:
    peak_index = max(range(len(records)), key=lambda index: records[index][3])
    if 0 < peak_index < len(records) - 1:
        return (
            _best_motion_record(records[:peak_index], prefer_late=True),
            records[peak_index],
            _best_motion_record(records[peak_index + 1 :], prefer_late=False),
        )

    first_cut = max(1, len(records) // 3)
    second_cut = max(first_cut + 1, (len(records) * 2) // 3)
    second_cut = min(second_cut, len(records) - 1)
    return (
        _best_motion_record(records[:first_cut], prefer_late=True),
        _best_motion_record(records[first_cut:second_cut], prefer_late=True),
        _best_motion_record(records[second_cut:], prefer_late=False),
    )


def _motion_fallback_triplet_temporal_diagnostic(
    takeoff_record: tuple[int, str, float, float],
    apex_record: tuple[int, str, float, float],
    landing_record: tuple[int, str, float, float],
) -> dict[str, float | bool]:
    takeoff_apex_gap = apex_record[2] - takeoff_record[2]
    apex_landing_gap = landing_record[2] - apex_record[2]
    tal_span = landing_record[2] - takeoff_record[2]
    cross_segment = (
        takeoff_apex_gap < MOTION_FALLBACK_LOCAL_TAKEOFF_APEX_MIN_GAP_SEC
        or takeoff_apex_gap > MOTION_FALLBACK_LOCAL_TAKEOFF_APEX_MAX_GAP_SEC
        or apex_landing_gap < MOTION_FALLBACK_LOCAL_APEX_LANDING_MIN_GAP_SEC
        or apex_landing_gap > MOTION_FALLBACK_LOCAL_APEX_LANDING_MAX_GAP_SEC
        or tal_span > MOTION_FALLBACK_LOCAL_MAX_TAL_SPAN_SEC
    )
    compressed = (
        0.0 < tal_span <= MOTION_FALLBACK_COMPRESSED_TAL_SPAN_SEC
        or 0.0 < takeoff_apex_gap <= MOTION_FALLBACK_COMPRESSED_CORE_GAP_SEC
        or 0.0 < apex_landing_gap <= MOTION_FALLBACK_COMPRESSED_CORE_GAP_SEC
    )
    return {
        "takeoff_apex_gap_sec": round(takeoff_apex_gap, 3),
        "apex_landing_gap_sec": round(apex_landing_gap, 3),
        "tal_span_sec": round(tal_span, 3),
        "cross_segment": cross_segment,
        "compressed": compressed,
    }


def _local_motion_fallback_triplet(
    records: list[tuple[int, str, float, float]],
) -> tuple[tuple[int, str, float, float], tuple[int, str, float, float], tuple[int, str, float, float]] | None:
    if len(records) < 3:
        return None

    max_score = max(record[3] for record in records)
    low = min(record[3] for record in records)
    span = max(max_score - low, 1e-9)

    def normalized(record: tuple[int, str, float, float]) -> float:
        return _clamp((record[3] - low) / span) if span > 1e-9 else _clamp(record[3] / max(max_score, 1e-9))

    best: tuple[float, float, float, float, tuple[int, str, float, float], tuple[int, str, float, float], tuple[int, str, float, float]] | None = None
    for apex_index, apex_record in enumerate(records):
        takeoff_pool = [
            record
            for record in records[:apex_index]
            if MOTION_FALLBACK_LOCAL_TAKEOFF_APEX_MIN_GAP_SEC <= apex_record[2] - record[2] <= MOTION_FALLBACK_LOCAL_TAKEOFF_APEX_MAX_GAP_SEC
        ]
        landing_pool = [
            record
            for record in records[apex_index + 1 :]
            if MOTION_FALLBACK_LOCAL_APEX_LANDING_MIN_GAP_SEC <= record[2] - apex_record[2] <= MOTION_FALLBACK_LOCAL_APEX_LANDING_MAX_GAP_SEC
        ]
        if not takeoff_pool or not landing_pool:
            continue

        for takeoff_record in takeoff_pool:
            takeoff_apex_gap = apex_record[2] - takeoff_record[2]
            takeoff_timing = _clamp(
                1.0 - abs(takeoff_apex_gap - MOTION_FALLBACK_LOCAL_TARGET_TAKEOFF_APEX_GAP_SEC)
                / MOTION_FALLBACK_LOCAL_TAKEOFF_APEX_MAX_GAP_SEC
            )
            for landing_record in landing_pool:
                apex_landing_gap = landing_record[2] - apex_record[2]
                tal_span = landing_record[2] - takeoff_record[2]
                if tal_span > MOTION_FALLBACK_LOCAL_MAX_TAL_SPAN_SEC:
                    continue
                landing_timing = _clamp(
                    1.0 - abs(apex_landing_gap - MOTION_FALLBACK_LOCAL_TARGET_APEX_LANDING_GAP_SEC)
                    / MOTION_FALLBACK_LOCAL_APEX_LANDING_MAX_GAP_SEC
                )
                motion = (
                    0.28 * normalized(takeoff_record)
                    + 0.44 * normalized(apex_record)
                    + 0.28 * normalized(landing_record)
                )
                timing = 0.45 * takeoff_timing + 0.55 * landing_timing
                continuity = _clamp(1.0 - max(0.0, tal_span - 1.20) / max(MOTION_FALLBACK_LOCAL_MAX_TAL_SPAN_SEC - 1.20, 1e-9))
                score = 0.52 * motion + 0.36 * timing + 0.12 * continuity
                candidate = (
                    score,
                    apex_record[3],
                    -abs(tal_span - 1.0),
                    -takeoff_record[0],
                    takeoff_record,
                    apex_record,
                    landing_record,
                )
                if best is None or candidate > best:
                    best = candidate

    if best is None:
        return None
    return best[4], best[5], best[6]


def _motion_fallback_candidates(
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    quality_flags: list[str],
    *,
    min_peak_score: float = MOTION_FALLBACK_MIN_PEAK_SCORE,
    time_bounds: tuple[float, float] | None = None,
    strict_time_bounds: bool = False,
    frame_states: dict[str, dict[str, str]] | None = None,
    pose_data: dict[str, Any] | None = None,
    excluded_time_windows: list[tuple[float, float]] | None = None,
) -> dict[str, Any] | None:
    selected_records = _motion_records(motion_scores, effective_fps)
    if len(selected_records) < 3:
        return None
    frame_states = frame_states or {}
    filtered = _apply_motion_record_filters(
        selected_records,
        time_bounds=time_bounds,
        strict_time_bounds=strict_time_bounds,
        excluded_time_windows=excluded_time_windows,
        frame_states=frame_states,
    )
    records, bounds_applied, excluded_records, filtered_unreliable_records = filtered
    if records is None:
        return None
    dense_scores_applied = False
    dense_record_count = 0
    if excluded_records:
        dense_records = _dense_motion_score_records(motion_scores, effective_fps, selected_records)
        dense_record_count = len(dense_records)
        dense_filtered = _apply_motion_record_filters(
            dense_records,
            time_bounds=time_bounds,
            strict_time_bounds=strict_time_bounds,
            excluded_time_windows=excluded_time_windows,
            frame_states=frame_states,
        )
        dense_pool, dense_bounds_applied, dense_excluded_records, dense_unreliable_records = dense_filtered
        if dense_pool is not None and len(dense_pool) > len(records):
            records = dense_pool
            bounds_applied = bounds_applied or dense_bounds_applied
            excluded_records = dense_excluded_records or excluded_records
            filtered_unreliable_records = dense_unreliable_records or filtered_unreliable_records
            dense_scores_applied = True

    scores = [record[3] for record in records]
    max_score = max(scores)
    if max_score < min_peak_score:
        return None

    local_triplet = _local_motion_fallback_triplet(records)
    cross_segment_fallback = False
    if local_triplet is not None:
        takeoff_record, apex_record, landing_record = local_triplet
    else:
        takeoff_record, apex_record, landing_record = _legacy_motion_fallback_triplet(records)
        cross_segment_fallback = True
    temporal_diagnostic = _motion_fallback_triplet_temporal_diagnostic(takeoff_record, apex_record, landing_record)
    cross_segment_fallback = cross_segment_fallback or bool(temporal_diagnostic["cross_segment"])
    compressed_fallback = bool(temporal_diagnostic["compressed"])

    low = min(scores)
    span = max(max_score - low, 1e-9)
    absolute_motion_score = _clamp(max_score / 0.12)

    def confidence_for(record: tuple[int, str, float, float]) -> tuple[float, float]:
        normalized = _clamp((record[3] - low) / span) if span > 1e-9 else _clamp(record[3] / max(max_score, 1e-9))
        confidence = _clamp(0.36 + 0.12 * normalized + 0.08 * absolute_motion_score, high=0.54)
        return round(confidence, 3), normalized

    warning = "keyframe_candidates_motion_fallback"
    flags = [*quality_flags, warning, "tal_candidate_motion_fallback_low_precision"]
    if bounds_applied:
        flags.append("keyframe_candidates_motion_fallback_bounded_to_reliable_pose")
    if excluded_records:
        flags.append("keyframe_candidates_motion_fallback_excluded_rejected_tail_window")
    if dense_scores_applied:
        flags.append("keyframe_candidates_motion_fallback_dense_scores")
    if filtered_unreliable_records:
        flags.append("keyframe_candidates_motion_fallback_filtered_unreliable_pose_records")
    low_motion_fallback = max_score < MOTION_FALLBACK_MIN_PEAK_SCORE
    if low_motion_fallback:
        flags.append("tal_candidate_motion_fallback_low_motion")
        flags.append("tal_candidate_motion_fallback_low_motion_low_confidence")
    if cross_segment_fallback:
        flags.append("tal_candidate_motion_fallback_cross_segment_unreliable")
    if compressed_fallback:
        flags.append("tal_candidate_motion_fallback_compressed")
        flags.append("tal_candidate_temporal_geometry_unreliable")
        flags.append("tal_candidate_core_gap_compressed")
    candidates: dict[str, Any] = {"quality_flags": list(dict.fromkeys(flags))}
    if local_triplet is not None:
        candidates["motion_fallback_local_window"] = {
            "start_timestamp": round(takeoff_record[2], 3),
            "end_timestamp": round(landing_record[2], 3),
            **temporal_diagnostic,
        }
    else:
        candidates["motion_fallback_cross_segment_diagnostic"] = temporal_diagnostic
    if bounds_applied and time_bounds is not None:
        candidates["motion_fallback_time_bounds"] = {
            "start_timestamp": round(time_bounds[0], 3),
            "end_timestamp": round(time_bounds[1], 3),
        }
    if excluded_records:
        candidates["motion_fallback_excluded_rejected_tail_window"] = {
            "excluded_record_count": len(excluded_records),
            "excluded_records": excluded_records[:8],
        }
    if dense_scores_applied:
        candidates["motion_fallback_dense_scores"] = {
            "reason": "dense_scores_after_rejected_tail_window",
            "dense_record_count": dense_record_count,
            "used_record_count": len(records),
            "selected_record_count": len(selected_records),
        }
    if filtered_unreliable_records:
        candidates["motion_fallback_filtered_unreliable_pose_records"] = filtered_unreliable_records
    unreliable_pose_records: dict[str, dict[str, Any]] = {}
    for role, record in (("T", takeoff_record), ("A", apex_record), ("L", landing_record)):
        confidence, normalized = confidence_for(record)
        warnings = [warning, f"{role.lower()}_pose_signal_insufficient"]
        extra_evidence: dict[str, Any] = {
            "motion_fallback_temporal_geometry": temporal_diagnostic,
        }
        if dense_scores_applied:
            extra_evidence["motion_fallback_dense_score_record"] = {
                "thumb_index": record[0],
                "nearest_sampled_frame_id": record[1],
                "timestamp": round(record[2], 3),
                "reason": "dense_scores_after_rejected_tail_window",
            }
        if local_triplet is not None:
            extra_evidence["motion_fallback_local_window"] = {
                "start_timestamp": round(takeoff_record[2], 3),
                "end_timestamp": round(landing_record[2], 3),
            }
        if cross_segment_fallback:
            warnings.append("tal_candidate_motion_fallback_cross_segment_unreliable")
            raw_confidence = confidence
            confidence = min(confidence, MOTION_FALLBACK_CROSS_SEGMENT_CONFIDENCE_CAP)
            extra_evidence["motion_fallback_cross_segment_confidence_cap"] = {
                "raw_confidence": round(raw_confidence, 3),
                "cap": MOTION_FALLBACK_CROSS_SEGMENT_CONFIDENCE_CAP,
            }
        if compressed_fallback:
            warnings.append("tal_candidate_motion_fallback_compressed")
            raw_confidence = confidence
            confidence = min(confidence, MOTION_FALLBACK_COMPRESSED_CONFIDENCE_CAP)
            extra_evidence["motion_fallback_compressed_confidence_cap"] = {
                "raw_confidence": round(raw_confidence, 3),
                "cap": MOTION_FALLBACK_COMPRESSED_CONFIDENCE_CAP,
            }
        if low_motion_fallback:
            warnings.append("tal_candidate_motion_fallback_low_motion_low_confidence")
            raw_confidence = confidence
            confidence = min(confidence, MOTION_FALLBACK_LOW_MOTION_CONFIDENCE_CAP)
            extra_evidence["motion_fallback_low_motion_confidence_cap"] = {
                "raw_confidence": round(raw_confidence, 3),
                "cap": MOTION_FALLBACK_LOW_MOTION_CONFIDENCE_CAP,
                "max_motion_score": round(max_score, 5),
            }
        unreliable_pose_state = _motion_record_unreliable_pose_state(record, frame_states)
        if unreliable_pose_state is not None:
            unreliable_warning = "keyframe_candidates_motion_fallback_unreliable_pose_state"
            warnings.append(unreliable_warning)
            raw_confidence = confidence
            confidence = min(confidence, MOTION_FALLBACK_UNRELIABLE_POSE_CONFIDENCE_CAP)
            unreliable_pose_records[role] = {
                "frame_id": record[1],
                **unreliable_pose_state,
            }
            extra_evidence["motion_fallback_unreliable_pose_state"] = unreliable_pose_state
            extra_evidence["motion_fallback_unreliable_pose_confidence_cap"] = {
                "raw_confidence": round(raw_confidence, 3),
                "cap": MOTION_FALLBACK_UNRELIABLE_POSE_CONFIDENCE_CAP,
            }
        candidates[role] = _motion_only_candidate(
            record,
            role,
            confidence,
            normalized,
            warnings,
            extra_evidence=extra_evidence,
        )
    if unreliable_pose_records:
        flags = [
            *candidates["quality_flags"],
            "keyframe_candidates_motion_fallback_unreliable_pose_state",
            "tal_candidate_motion_fallback_unreliable_pose_low_confidence",
        ]
        candidates["quality_flags"] = list(dict.fromkeys(flags))
        candidates["motion_fallback_unreliable_pose_records"] = unreliable_pose_records
    tiny_target_diagnostic = _tiny_target_motion_fallback_diagnostic(
        pose_data,
        candidates,
        max_score=max_score,
        compressed_fallback=compressed_fallback,
    )
    if tiny_target_diagnostic is not None:
        risk_warning = "tal_candidate_motion_fallback_foreground_motion_risk"
        risk_flag = "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk"
        candidates["quality_flags"] = list(
            dict.fromkeys([*candidates["quality_flags"], risk_flag, risk_warning, "tal_candidate_confidence_low"])
        )
        candidates["motion_fallback_tiny_target_diagnostic"] = tiny_target_diagnostic
        for role in ("T", "A", "L"):
            candidate = candidates.get(role)
            if not isinstance(candidate, dict):
                continue
            _append_warning(candidate, risk_warning)
            evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
            evidence["motion_fallback_tiny_target_foreground_motion_risk"] = tiny_target_diagnostic
            candidate["evidence"] = evidence
            _cap_candidate_confidence(
                candidate,
                MOTION_FALLBACK_FOREGROUND_RISK_CONFIDENCE_CAP,
                risk_warning,
            )
    multiperson_relock_diagnostic = _multiperson_relock_motion_fallback_diagnostic(
        pose_data,
        max_score=max_score,
        compressed_fallback=compressed_fallback,
    )
    if multiperson_relock_diagnostic is not None:
        risk_warning = "tal_candidate_motion_fallback_foreground_motion_risk"
        risk_flag = "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk"
        candidates["quality_flags"] = list(
            dict.fromkeys([*candidates["quality_flags"], risk_flag, risk_warning, "tal_candidate_confidence_low"])
        )
        candidates["motion_fallback_multiperson_relock_diagnostic"] = multiperson_relock_diagnostic
        for role in ("T", "A", "L"):
            candidate = candidates.get(role)
            if not isinstance(candidate, dict):
                continue
            _append_warning(candidate, risk_warning)
            evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
            evidence["motion_fallback_multiperson_relock_instability_risk"] = multiperson_relock_diagnostic
            candidate["evidence"] = evidence
            _cap_candidate_confidence(
                candidate,
                MOTION_FALLBACK_FOREGROUND_RISK_CONFIDENCE_CAP,
                risk_warning,
            )
    if any((_to_float(candidates[role].get("confidence")) or 0.0) < 0.35 for role in ("T", "A", "L")):
        candidates["quality_flags"] = list(
            dict.fromkeys([*candidates["quality_flags"], "tal_candidate_confidence_low"])
        )
    return candidates


def _candidate_timestamps(
    *candidates: dict[str, Any],
) -> list[float]:
    timestamps: list[float] = []
    for candidate in candidates:
        timestamp = _to_float(candidate.get("timestamp")) if isinstance(candidate, dict) else None
        if timestamp is not None:
            timestamps.append(timestamp)
    return timestamps


def _nearest_motion_record(
    records: list[tuple[int, str, float, float]],
    target_timestamp: float,
) -> tuple[int, str, float, float]:
    return min(records, key=lambda record: (abs(record[2] - target_timestamp), -record[3], record[0]))


def _occluded_motion_peak_record(
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    frame_states: dict[str, dict[str, str]],
) -> tuple[tuple[int, str, float, float], list[dict[str, Any]], list[tuple[int, str, float, float]]] | None:
    records = _motion_records(motion_scores, effective_fps)
    if len(records) < 3:
        return None
    peak_record = max(records, key=lambda record: record[3])
    peak_unreliable = _motion_record_unreliable_pose_state(peak_record, frame_states)
    if peak_unreliable is None:
        return None

    start_ts = peak_record[2] - OCCLUDED_MOTION_PEAK_OVERRIDE_PRE_SEC
    end_ts = peak_record[2] + OCCLUDED_MOTION_PEAK_OVERRIDE_POST_SEC
    window_records = [record for record in records if start_ts <= record[2] <= end_ts]
    if len(window_records) < 3:
        return None

    unreliable_records: list[dict[str, Any]] = []
    for record in window_records:
        state = _motion_record_unreliable_pose_state(record, frame_states)
        if state is None:
            continue
        unreliable_records.append(_motion_record_state_payload(record, state))

    unreliable_ratio = len(unreliable_records) / len(window_records)
    if (
        len(unreliable_records) < MOTION_WINDOW_UNRELIABLE_STATE_MIN_COUNT
        or unreliable_ratio < MOTION_WINDOW_UNRELIABLE_STATE_MIN_RATIO
    ):
        return None
    return peak_record, unreliable_records, window_records


def _estimated_occluded_motion_candidate(
    records: list[tuple[int, str, float, float]],
    target_timestamp: float,
    role: str,
    peak_record: tuple[int, str, float, float],
    max_score: float,
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    nearest = _nearest_motion_record(records, target_timestamp)
    record_timestamp = nearest[2]
    if abs(record_timestamp - target_timestamp) <= OCCLUDED_MOTION_PEAK_OVERRIDE_RECORD_SNAP_TOLERANCE_SEC:
        candidate_timestamp = record_timestamp
        estimated_timestamp = False
    else:
        candidate_timestamp = target_timestamp
        estimated_timestamp = True
    normalized = _clamp(nearest[3] / max(max_score, 1e-9))
    confidence = min(
        _clamp(0.38 + 0.12 * normalized, high=0.50),
        OCCLUDED_MOTION_PEAK_OVERRIDE_CONFIDENCE_CAP,
    )
    candidate = _motion_only_candidate(
        (nearest[0], nearest[1], candidate_timestamp, nearest[3]),
        role,
        confidence,
        normalized,
        [
            "keyframe_candidates_motion_fallback",
            "keyframe_candidates_occluded_motion_peak_override",
            "keyframe_candidates_motion_fallback_unreliable_pose_state",
            "motion_window_occlusion_contaminated",
            f"{role.lower()}_pose_signal_occluded",
        ],
        extra_evidence={
            "occluded_motion_peak_override": diagnostic,
            "motion_window_occlusion_contamination": diagnostic,
            "motion_fallback_unreliable_pose_state": {
                "tracking_state": "tracked",
                "tracker_state": "occluded_motion_peak_window",
            },
            "nearest_motion_record_timestamp": round(record_timestamp, 3),
            "estimated_timestamp": estimated_timestamp,
        },
    )
    if estimated_timestamp:
        candidate["evidence"]["estimated_timestamp_sec"] = round(candidate_timestamp, 3)
        candidate["evidence"]["timestamp_estimate_offset_from_nearest_record_sec"] = round(
            candidate_timestamp - record_timestamp,
            3,
        )
    return candidate


def _occluded_motion_peak_override_candidates(
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    quality_flags: list[str],
    frame_states: dict[str, dict[str, str]],
    signals: list[_FrameSignal],
    search_window: tuple[int, int] | None,
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> dict[str, Any] | None:
    occluded_peak = _occluded_motion_peak_record(motion_scores, effective_fps, frame_states)
    if occluded_peak is None:
        return None
    peak_record, unreliable_records, window_records = occluded_peak
    if search_window is not None and signals:
        window_start = signals[search_window[0]].timestamp
        window_end = signals[search_window[1]].timestamp
        if not (window_start <= peak_record[2] <= window_end):
            return None
    candidate_times = _candidate_timestamps(takeoff, apex, landing)
    if not candidate_times:
        return None
    takeoff_ts = _to_float(takeoff.get("timestamp"))
    if takeoff_ts is None or takeoff_ts - peak_record[2] < OCCLUDED_MOTION_PEAK_OVERRIDE_MIN_TAKEOFF_LAG_SEC:
        return None
    if min(candidate_times) <= peak_record[2] + OCCLUDED_MOTION_PEAK_OVERRIDE_MIN_TAKEOFF_LAG_SEC:
        return None

    max_score = max((record[3] for record in _motion_records(motion_scores, effective_fps)), default=peak_record[3])
    target_timestamps = {
        "T": peak_record[2] - OCCLUDED_MOTION_PEAK_OVERRIDE_TAKEOFF_OFFSET_SEC,
        "A": peak_record[2] + OCCLUDED_MOTION_PEAK_OVERRIDE_APEX_OFFSET_SEC,
        "L": peak_record[2] + OCCLUDED_MOTION_PEAK_OVERRIDE_LANDING_OFFSET_SEC,
    }
    if not (target_timestamps["T"] < target_timestamps["A"] < target_timestamps["L"]):
        return None

    diagnostic = {
        "reason": "candidate_drifted_after_occluded_motion_peak",
        "peak_frame_id": peak_record[1],
        "peak_timestamp": round(peak_record[2], 3),
        "peak_motion_score": round(peak_record[3], 5),
        "window_start_timestamp": round(min(record[2] for record in window_records), 3),
        "window_end_timestamp": round(max(record[2] for record in window_records), 3),
        "window_record_count": len(window_records),
        "unreliable_state_count": len(unreliable_records),
        "unreliable_state_ratio": round(len(unreliable_records) / len(window_records), 3),
        "unreliable_records": unreliable_records,
        "rejected_candidate_timestamps": {
            "T": round(_to_float(takeoff.get("timestamp")) or 0.0, 3),
            "A": round(_to_float(apex.get("timestamp")) or 0.0, 3),
            "L": round(_to_float(landing.get("timestamp")) or 0.0, 3),
        },
        "estimated_offsets_sec": {
            "T": -OCCLUDED_MOTION_PEAK_OVERRIDE_TAKEOFF_OFFSET_SEC,
            "A": OCCLUDED_MOTION_PEAK_OVERRIDE_APEX_OFFSET_SEC,
            "L": OCCLUDED_MOTION_PEAK_OVERRIDE_LANDING_OFFSET_SEC,
        },
    }
    candidates: dict[str, Any] = {
        "quality_flags": list(
            dict.fromkeys(
                [
                    *quality_flags,
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_occluded_motion_peak_override",
                    "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    "tal_candidate_motion_fallback_unreliable_pose_low_confidence",
                    "tal_candidate_motion_window_occlusion_contaminated",
                    "tal_candidate_motion_window_unreliable_tracker_state",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_candidate_confidence_low",
                ]
            )
        ),
        "motion_fallback_occluded_motion_peak_override": diagnostic,
        "motion_fallback_unreliable_pose_records": {
            "T": {
                "frame_id": _nearest_motion_record(window_records, target_timestamps["T"])[1],
                "tracking_state": "tracked",
                "tracker_state": "occluded_motion_peak_window",
            },
            "A": {
                "frame_id": _nearest_motion_record(window_records, target_timestamps["A"])[1],
                "tracking_state": "tracked",
                "tracker_state": "occluded_motion_peak_window",
            },
            "L": {
                "frame_id": _nearest_motion_record(window_records, target_timestamps["L"])[1],
                "tracking_state": "tracked",
                "tracker_state": "occluded_motion_peak_window",
            },
        },
    }
    for role in ("T", "A", "L"):
        candidates[role] = _estimated_occluded_motion_candidate(
            window_records,
            target_timestamps[role],
            role,
            peak_record,
            max_score,
            diagnostic,
        )
    return candidates


def _reliable_signal_time_bounds(signals: list[_FrameSignal]) -> tuple[float, float] | None:
    if not signals:
        return None
    start_ts = min(signal.timestamp for signal in signals)
    end_ts = max(signal.timestamp for signal in signals) + MOTION_FALLBACK_RELIABLE_POSE_POST_SEC
    if end_ts <= start_ts:
        return None
    return start_ts, end_ts


def _candidate_motion_fallback_visibility(candidate: dict[str, Any]) -> tuple[bool, float | None]:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
    warning_values = {str(warning).strip() for warning in warnings if str(warning).strip()}
    motion_fallback = evidence.get("motion_fallback") is True or "keyframe_candidates_motion_fallback" in warning_values
    visibility = _to_float(evidence.get("visibility_score"))
    if visibility is None:
        score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
        visibility = _to_float(score_components.get("pose_visibility"))
    return motion_fallback, visibility


def _takeoff_anchor_tail_fallback_diagnostic(
    records: list[tuple[int, str, float, float]],
    candidates: dict[str, Any],
) -> dict[str, Any] | None:
    if len(records) < 3:
        return None
    timeline_start = min(record[2] for record in records)
    timeline_end = max(record[2] for record in records)
    duration = timeline_end - timeline_start
    if duration < TAKEOFF_ANCHOR_TAIL_FALLBACK_MIN_DURATION_SEC:
        return None

    takeoff = candidates.get("T")
    landing = candidates.get("L")
    if not isinstance(takeoff, dict) or not isinstance(landing, dict):
        return None
    takeoff_ts = _to_float(takeoff.get("timestamp"))
    landing_ts = _to_float(landing.get("timestamp"))
    if takeoff_ts is None or landing_ts is None:
        return None
    start_ratio = (takeoff_ts - timeline_start) / max(duration, 1e-9)
    if start_ratio < TAKEOFF_ANCHOR_TAIL_FALLBACK_MIN_START_RATIO:
        return None

    low_visibility_roles: list[str] = []
    for role in ("A", "L"):
        candidate = candidates.get(role)
        if not isinstance(candidate, dict):
            continue
        motion_fallback, visibility = _candidate_motion_fallback_visibility(candidate)
        if (
            motion_fallback
            and visibility is not None
            and visibility <= TAKEOFF_ANCHOR_TAIL_FALLBACK_MAX_VISIBILITY
        ):
            low_visibility_roles.append(role)
    if len(low_visibility_roles) < 2:
        return None

    peak = max(records, key=lambda record: record[3])
    return {
        "timeline_start": round(timeline_start, 3),
        "timeline_end": round(timeline_end, 3),
        "duration_sec": round(duration, 3),
        "fallback_start_timestamp": round(takeoff_ts, 3),
        "fallback_end_timestamp": round(landing_ts, 3),
        "fallback_start_ratio": round(start_ratio, 3),
        "low_visibility_motion_roles": low_visibility_roles,
        "global_peak_timestamp": round(peak[2], 3),
        "global_peak_motion_score": round(peak[3], 5),
        "reason": "late_takeoff_anchor_low_visibility_motion_tail",
    }


def _takeoff_anchor_low_visibility_weak_boundary_diagnostic(candidates: dict[str, Any]) -> dict[str, Any] | None:
    takeoff = candidates.get("T")
    if not isinstance(takeoff, dict):
        return None
    takeoff_evidence = takeoff.get("evidence") if isinstance(takeoff.get("evidence"), dict) else {}
    takeoff_components = (
        takeoff_evidence.get("score_components")
        if isinstance(takeoff_evidence.get("score_components"), dict)
        else {}
    )
    takeoff_timing = _to_float(takeoff_components.get("takeoff_timing"))
    takeoff_event = _to_float(takeoff_components.get("takeoff_event"))
    takeoff_weak = (
        (takeoff_timing is not None and takeoff_timing <= TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_MAX_TAKEOFF_TIMING)
        or (
            takeoff_event is not None
            and takeoff_event <= TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_MAX_TAKEOFF_EVENT
        )
    )
    if not takeoff_weak:
        return None

    low_visibility_roles: list[str] = []
    role_details: dict[str, dict[str, Any]] = {}
    for role in ("A", "L"):
        candidate = candidates.get(role)
        if not isinstance(candidate, dict):
            continue
        motion_fallback, visibility = _candidate_motion_fallback_visibility(candidate)
        if (
            not motion_fallback
            or visibility is None
            or visibility > TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_MAX_VISIBILITY
        ):
            continue
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        low_visibility_roles.append(role)
        role_details[role] = {
            "timestamp": round(_to_float(candidate.get("timestamp")) or 0.0, 3),
            "confidence": round(_to_float(candidate.get("confidence")) or 0.0, 3),
            "visibility_score": round(visibility, 3),
            "motion_score": round(_to_float(evidence.get("motion_score")) or 0.0, 5),
        }
    if len(low_visibility_roles) < 2:
        return None

    return {
        "reason": "takeoff_anchor_low_visibility_motion_only_boundary",
        "low_visibility_motion_roles": low_visibility_roles,
        "roles": role_details,
        "takeoff_timing": round(takeoff_timing, 3) if takeoff_timing is not None else None,
        "takeoff_event": round(takeoff_event, 3) if takeoff_event is not None else None,
        "cap": TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_CONFIDENCE_CAP,
    }


def _motion_fallback_from_takeoff_anchor(
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    takeoff_candidate: dict[str, Any],
    quality_flags: list[str],
    *,
    frame_states: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    takeoff_ts = _to_float(takeoff_candidate.get("timestamp"))
    if takeoff_ts is None:
        return None
    records = _motion_records(motion_scores, effective_fps)
    if len(records) < 3:
        return None
    later_records = [record for record in records if record[2] >= takeoff_ts]
    if len(later_records) < 2:
        return None

    max_score = max(record[3] for record in records)
    tail_floor = max(
        SKELETON_DRIFT_MOTION_FALLBACK_TAIL_MIN_SCORE,
        max_score * SKELETON_DRIFT_MOTION_FALLBACK_TAIL_RATIO,
    )
    apex_target = takeoff_ts + 0.25
    apex_pool = [
        record
        for record in later_records
        if record[2] >= takeoff_ts + 0.08
        and record[2] <= takeoff_ts + SKELETON_DRIFT_MOTION_FALLBACK_APEX_MAX_GAP_SEC
    ]
    if not apex_pool:
        return None
    max_later_score = max((record[3] for record in later_records), default=max_score)

    def motion_timing_score(record: tuple[int, str, float, float], target: float, max_gap: float) -> tuple[float, float, int]:
        timing = _clamp(1.0 - abs(record[2] - target) / max(max_gap, 1e-9))
        motion = _clamp(record[3] / max(max_later_score, 1e-9))
        combined = 0.62 * timing + 0.38 * motion
        return (combined, motion, -abs(record[0]))

    apex_record = max(
        apex_pool,
        key=lambda record: motion_timing_score(
            record,
            apex_target,
            SKELETON_DRIFT_MOTION_FALLBACK_APEX_MAX_GAP_SEC,
        ),
    )

    landing_target = takeoff_ts + 0.80
    strong_landing_pool = [
        record
        for record in later_records
        if record[2] >= apex_record[2] + 0.05
        and record[2] <= takeoff_ts + SKELETON_DRIFT_MOTION_FALLBACK_LANDING_MAX_GAP_SEC
        and record[3] >= tail_floor
    ]
    low_tail_early_landing_diagnostic: dict[str, Any] | None = None
    if strong_landing_pool:
        landing_pool = strong_landing_pool
    else:
        landing_pool = [
            record
            for record in later_records
            if record[2] >= apex_record[2] + 0.05
            and record[2] <= takeoff_ts + SKELETON_DRIFT_MOTION_FALLBACK_LANDING_MAX_GAP_SEC
        ]
        low_tail_pool = [
            record
            for record in landing_pool
            if record[2] <= apex_record[2] + SKELETON_DRIFT_MOTION_FALLBACK_LOW_TAIL_EARLY_LANDING_MAX_APEX_GAP_SEC
            and record[3] >= SKELETON_DRIFT_MOTION_FALLBACK_LOW_TAIL_EARLY_LANDING_MIN_SCORE
        ]
        low_tail_peak = max((record[3] for record in low_tail_pool), default=0.0)
        if low_tail_peak > 0.0:
            supported_low_tail_pool = [
                record
                for record in low_tail_pool
                if record[3] >= low_tail_peak * SKELETON_DRIFT_MOTION_FALLBACK_LOW_TAIL_EARLY_LANDING_PEAK_RATIO
            ]
            if supported_low_tail_pool:
                landing_pool = supported_low_tail_pool
                low_tail_early_landing_diagnostic = {
                    "reason": "early_landing_from_low_tail_motion_plateau",
                    "tail_floor": round(tail_floor, 5),
                    "low_tail_peak_motion_score": round(low_tail_peak, 5),
                    "candidate_count": len(supported_low_tail_pool),
                    "max_apex_landing_gap_sec": SKELETON_DRIFT_MOTION_FALLBACK_LOW_TAIL_EARLY_LANDING_MAX_APEX_GAP_SEC,
                }
    if not landing_pool:
        return None
    def landing_record_score(record: tuple[int, str, float, float]) -> tuple[float, float] | tuple[float, float, int]:
        if low_tail_early_landing_diagnostic is not None:
            return (-record[2], record[3])
        return motion_timing_score(
            record,
            landing_target,
            SKELETON_DRIFT_MOTION_FALLBACK_LANDING_MAX_GAP_SEC,
        )

    landing_record = max(landing_pool, key=landing_record_score)
    if not (takeoff_ts < apex_record[2] < landing_record[2]):
        return None

    scores = [record[3] for record in records]
    low = min(scores)
    span = max(max_score - low, 1e-9)

    def normalized(record: tuple[int, str, float, float]) -> float:
        return _clamp((record[3] - low) / span) if span > 1e-9 else _clamp(record[3] / max(max_score, 1e-9))

    flags = [
        *quality_flags,
        "keyframe_candidates_motion_fallback",
        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
        "tal_candidate_motion_fallback_low_precision",
    ]
    frame_states = frame_states or {}
    unreliable_pose_records: dict[str, dict[str, str]] = {}
    candidates: dict[str, Any] = {"quality_flags": list(dict.fromkeys(flags))}
    takeoff_record = (
        _candidate_index(takeoff_candidate) or 0,
        str(takeoff_candidate.get("frame_id") or ""),
        takeoff_ts,
        _to_float((takeoff_candidate.get("evidence") or {}).get("motion_score")) or 0.0
        if isinstance(takeoff_candidate.get("evidence"), dict)
        else 0.0,
    )
    candidates["T"] = dict(takeoff_candidate)
    warnings = candidates["T"].get("warnings") if isinstance(candidates["T"].get("warnings"), list) else []
    candidates["T"]["warnings"] = list(dict.fromkeys([*warnings, "keyframe_candidates_motion_fallback"]))
    for role, record in (("A", apex_record), ("L", landing_record)):
        norm = normalized(record)
        confidence = _clamp(0.44 + 0.14 * norm, high=0.58)
        warnings = ["keyframe_candidates_motion_fallback", f"{role.lower()}_pose_signal_drifted"]
        extra_evidence: dict[str, Any] = {}
        if role == "L" and low_tail_early_landing_diagnostic is not None:
            warnings.append("landing_low_tail_motion_plateau_early_contact")
            extra_evidence["motion_fallback_low_tail_early_landing"] = low_tail_early_landing_diagnostic
        unreliable_pose_state = _motion_record_unreliable_pose_state(record, frame_states)
        if unreliable_pose_state is not None:
            warning = "keyframe_candidates_motion_fallback_unreliable_pose_state"
            warnings.append(warning)
            raw_confidence = confidence
            confidence = min(confidence, MOTION_FALLBACK_UNRELIABLE_POSE_CONFIDENCE_CAP)
            unreliable_pose_records[role] = {
                "frame_id": record[1],
                **unreliable_pose_state,
            }
            extra_evidence["motion_fallback_unreliable_pose_state"] = unreliable_pose_state
            extra_evidence["motion_fallback_unreliable_pose_confidence_cap"] = {
                "raw_confidence": round(raw_confidence, 3),
                "cap": MOTION_FALLBACK_UNRELIABLE_POSE_CONFIDENCE_CAP,
            }
        candidates[role] = _motion_only_candidate(
            record,
            role,
            confidence,
            norm,
            warnings,
            extra_evidence=extra_evidence,
        )
    if unreliable_pose_records:
        flags = [
            *candidates["quality_flags"],
            "keyframe_candidates_motion_fallback_unreliable_pose_state",
            "tal_candidate_motion_fallback_unreliable_pose_low_confidence",
        ]
        candidates["quality_flags"] = list(dict.fromkeys(flags))
        candidates["motion_fallback_unreliable_pose_records"] = unreliable_pose_records
    weak_boundary_diagnostic = _takeoff_anchor_low_visibility_weak_boundary_diagnostic(candidates)
    if weak_boundary_diagnostic is not None:
        risk_warning = "tal_candidate_motion_fallback_low_visibility_weak_boundary"
        candidates["quality_flags"] = list(
            dict.fromkeys(
                [
                    *candidates["quality_flags"],
                    "keyframe_candidates_motion_fallback_low_visibility_weak_boundary",
                    risk_warning,
                    "tal_candidate_confidence_low",
                ]
            )
        )
        candidates["motion_fallback_low_visibility_weak_boundary"] = weak_boundary_diagnostic
        for role in ("T", "A", "L"):
            candidate = candidates.get(role)
            if not isinstance(candidate, dict):
                continue
            evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
            evidence["motion_fallback_low_visibility_weak_boundary"] = weak_boundary_diagnostic
            candidate["evidence"] = evidence
            _append_warning(candidate, risk_warning)
        for role in weak_boundary_diagnostic.get("low_visibility_motion_roles", []):
            candidate = candidates.get(role)
            if isinstance(candidate, dict):
                _cap_candidate_confidence(
                    candidate,
                    TAKEOFF_ANCHOR_LOW_VISIBILITY_WEAK_BOUNDARY_CONFIDENCE_CAP,
                    risk_warning,
                )
    tail_diagnostic = _takeoff_anchor_tail_fallback_diagnostic(records, candidates)
    if tail_diagnostic is not None:
        risk_warning = "tal_candidate_motion_fallback_tail_window"
        candidates["quality_flags"] = list(
            dict.fromkeys(
                [
                    *candidates["quality_flags"],
                    "keyframe_candidates_motion_fallback_takeoff_anchor_tail_window",
                    risk_warning,
                    "tal_candidate_confidence_low",
                ]
            )
        )
        candidates["motion_fallback_takeoff_anchor_tail_window"] = tail_diagnostic
        for role in ("T", "A", "L"):
            candidate = candidates.get(role)
            if not isinstance(candidate, dict):
                continue
            _append_warning(candidate, risk_warning)
            evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
            evidence["motion_fallback_takeoff_anchor_tail_window"] = tail_diagnostic
            candidate["evidence"] = evidence
            _cap_candidate_confidence(
                candidate,
                TAKEOFF_ANCHOR_TAIL_WINDOW_CONFIDENCE_CAP,
                risk_warning,
            )
    return candidates


def _motion_refined_sparse_takeoff(
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    takeoff_candidate: dict[str, Any],
    apex_candidate: dict[str, Any],
    frame_states: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    takeoff_ts = _to_float(takeoff_candidate.get("timestamp"))
    apex_ts = _to_float(apex_candidate.get("timestamp"))
    if takeoff_ts is None or apex_ts is None:
        return None
    if apex_ts - takeoff_ts < SPARSE_TAKEOFF_APEX_GAP_SEC:
        return None
    takeoff_components = (
        takeoff_candidate.get("evidence", {}).get("score_components", {})
        if isinstance(takeoff_candidate.get("evidence"), dict)
        else {}
    )
    if (
        (_to_float(takeoff_components.get("takeoff_timing")) or 0.0) > SPARSE_TAKEOFF_TIMING_MAX
        and (_to_float(takeoff_components.get("takeoff_event")) or 0.0) >= TAKEOFF_LATE_PLAUSIBLE_MIN_EVENT
    ):
        return None

    records = _motion_records(motion_scores, effective_fps)
    if len(records) < 3:
        return None
    max_motion = max((record[3] for record in records), default=0.0)
    if max_motion <= 0:
        return None
    lower_bound = takeoff_ts + SPARSE_TAKEOFF_MIN_SHIFT_SEC
    upper_bound = apex_ts - SPARSE_TAKEOFF_MIN_APEX_LEAD_SEC
    pool = [
        record
        for record in records
        if lower_bound <= record[2] <= upper_bound
        and SPARSE_TAKEOFF_MIN_APEX_LEAD_SEC <= apex_ts - record[2] <= SPARSE_TAKEOFF_MAX_APEX_LEAD_SEC
        and record[3] >= max_motion * SPARSE_TAKEOFF_MIN_MOTION_RATIO
    ]
    if not pool:
        return None

    def score_record(record: tuple[int, str, float, float]) -> tuple[float, float, float]:
        apex_lead = apex_ts - record[2]
        timing = _clamp(1.0 - abs(apex_lead - SPARSE_TAKEOFF_TARGET_APEX_LEAD_SEC) / SPARSE_TAKEOFF_TARGET_APEX_LEAD_SEC)
        motion = _clamp(record[3] / max_motion)
        return (0.58 * timing + 0.42 * motion, motion, record[2])

    record = max(pool, key=score_record)
    normalized_motion = _clamp(record[3] / max_motion)
    confidence = _clamp(0.42 + 0.18 * normalized_motion, high=0.58)
    warnings = [
        "keyframe_candidates_motion_fallback",
        "takeoff_sparse_pose_motion_refined",
        "t_pose_signal_sparse",
    ]
    unreliable_pose_state = _motion_record_unreliable_pose_state(record, frame_states)
    extra_evidence: dict[str, Any] = {
        "sparse_pose_takeoff_refinement": {
            "original_timestamp": round(takeoff_ts, 3),
            "apex_timestamp": round(apex_ts, 3),
            "original_apex_gap_sec": round(apex_ts - takeoff_ts, 3),
            "refined_apex_gap_sec": round(apex_ts - record[2], 3),
            "max_motion_score": round(max_motion, 5),
        }
    }
    if unreliable_pose_state is not None:
        warnings.append("keyframe_candidates_motion_fallback_unreliable_pose_state")
        raw_confidence = confidence
        confidence = min(confidence, MOTION_FALLBACK_UNRELIABLE_POSE_CONFIDENCE_CAP)
        extra_evidence["motion_fallback_unreliable_pose_state"] = unreliable_pose_state
        extra_evidence["motion_fallback_unreliable_pose_confidence_cap"] = {
            "raw_confidence": round(raw_confidence, 3),
            "cap": MOTION_FALLBACK_UNRELIABLE_POSE_CONFIDENCE_CAP,
        }
    return _motion_only_candidate(
        record,
        "T",
        confidence,
        normalized_motion,
        warnings,
        extra_evidence=extra_evidence,
    )


def _compressed_late_reselect_original_takeoff(
    takeoff_candidate: dict[str, Any],
) -> dict[str, Any] | None:
    evidence = takeoff_candidate.get("evidence") if isinstance(takeoff_candidate.get("evidence"), dict) else {}
    reselection = evidence.get("takeoff_late_plausible_reselection")
    if not isinstance(reselection, dict):
        return None

    original_gap = _to_float(reselection.get("original_apex_gap_sec"))
    reselected_gap = _to_float(reselection.get("reselected_apex_gap_sec"))
    if (
        original_gap is None
        or reselected_gap is None
        or original_gap < TAKEOFF_COMPRESSED_RESELECT_FALLBACK_ORIGINAL_GAP_SEC
        or reselected_gap > TAKEOFF_COMPRESSED_RESELECT_FALLBACK_RESELECTED_GAP_SEC
    ):
        return None

    original_candidate = reselection.get("original_candidate")
    if not isinstance(original_candidate, dict):
        return None
    original_ts = _to_float(original_candidate.get("timestamp"))
    original_frame_id = original_candidate.get("frame_id")
    if original_ts is None or not original_frame_id:
        return None

    restored = {
        "frame_id": str(original_frame_id),
        "timestamp": round(original_ts, 3),
        "confidence": _to_float(original_candidate.get("confidence")) or 0.0,
        "evidence": dict(original_candidate.get("evidence"))
        if isinstance(original_candidate.get("evidence"), dict)
        else {},
        "warnings": list(original_candidate.get("warnings"))
        if isinstance(original_candidate.get("warnings"), list)
        else [],
    }
    restored_evidence = restored["evidence"]
    restored_evidence["takeoff_compressed_late_reselection_restored_anchor"] = {
        "reselected_timestamp": round(_to_float(takeoff_candidate.get("timestamp")) or 0.0, 3),
        "original_apex_gap_sec": round(original_gap, 3),
        "reselected_apex_gap_sec": round(reselected_gap, 3),
    }
    restored["evidence"] = restored_evidence
    _append_warning(restored, "takeoff_compressed_late_reselection_restored_anchor")
    return restored


def _motion_score_at(
    index: int,
    frame_id: str,
    frame_count: int,
    by_frame: dict[str, dict[str, Any]],
    selected: list[dict[str, Any]],
    score_series: list[float],
) -> float | None:
    if frame_id in by_frame:
        value = _to_float(by_frame[frame_id].get("motion_score"))
        if value is not None:
            return value
    if index < len(selected):
        value = _to_float(selected[index].get("motion_score"))
        if value is not None:
            return value
    if not score_series:
        return None
    if len(score_series) == frame_count:
        return score_series[index]
    frame_number = _frame_number(frame_id)
    if 1 <= frame_number <= len(score_series):
        return score_series[frame_number - 1]
    if frame_count <= 1:
        return score_series[0]
    mapped = round(index * (len(score_series) - 1) / (frame_count - 1))
    return score_series[max(0, min(len(score_series) - 1, mapped))]


def _timestamp_at(
    frame: dict[str, Any],
    index: int,
    frame_id: str,
    fps: float,
    by_frame: dict[str, dict[str, Any]],
    selected: list[dict[str, Any]],
) -> float:
    if frame_id in by_frame:
        value = _to_float(by_frame[frame_id].get("timestamp"))
        if value is not None:
            return value
    if index < len(selected):
        value = _to_float(selected[index].get("timestamp"))
        if value is not None:
            return value
    for key in ("timestamp", "timestamp_sec", "time_sec"):
        value = _to_float(frame.get(key))
        if value is not None:
            return value
    return index / fps


def _build_signals(
    pose_data: dict[str, Any],
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
) -> list[_FrameSignal]:
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not isinstance(frames, list):
        return []

    by_frame, selected, score_series = _selected_records(motion_scores)
    signals: list[_FrameSignal] = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            continue
        tracking_state = str(frame.get("tracking_state") or "tracked")
        if tracking_state in EXCLUDED_TRACKING_STATES:
            continue
        tracker_state = str(frame.get("tracker_state") or "")
        if tracker_state in EXCLUDED_TRACKER_STATES:
            continue
        keypoints = frame.get("keypoints", [])
        frame_id = _frame_stem(frame.get("frame") or frame.get("frame_id") or f"frame_{index + 1:04d}")
        signals.append(
            _FrameSignal(
                index=index,
                frame_id=frame_id,
                timestamp=_timestamp_at(frame, index, frame_id, effective_fps, by_frame, selected),
                com_y=_com_y(keypoints)[0],
                hip_y=_com_y(keypoints)[1],
                ankle_y=_ankle_y(keypoints),
                knee_angle=_knee_angle(keypoints),
                motion_score=_motion_score_at(index, frame_id, len(frames), by_frame, selected, score_series),
                visibility_score=_visibility_score(keypoints),
            )
        )
    return signals


def _excluded_pose_frame_counts(pose_data: dict[str, Any] | None) -> dict[str, int]:
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not isinstance(frames, list):
        return {}
    counts: dict[str, int] = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        state = str(frame.get("tracking_state") or "tracked")
        if state in EXCLUDED_TRACKING_STATES:
            counts[state] = counts.get(state, 0) + 1
        tracker_state = str(frame.get("tracker_state") or "")
        if tracker_state in EXCLUDED_TRACKER_STATES:
            key = f"tracker_{tracker_state}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _smooth(values: list[float | None]) -> list[float | None]:
    smoothed: list[float | None] = []
    for index in range(len(values)):
        window = [
            values[item]
            for item in range(max(0, index - 1), min(len(values), index + 2))
            if values[item] is not None
        ]
        smoothed.append(sum(window) / len(window) if window else None)
    return smoothed


def _window_values(values: list[float | None], index: int, before: int, after: int) -> list[float]:
    return [
        float(values[item])
        for item in range(max(0, index - before), min(len(values), index + after + 1))
        if values[item] is not None
    ]


def _window_average(values: list[float | None], index: int, before: int, after: int) -> float | None:
    window = _window_values(values, index, before, after)
    return sum(window) / len(window) if window else None


def _reselect_compressed_landing_candidate(
    scored: list[tuple[float, float, int, dict[str, Any], list[str]]],
    selected: tuple[float, float, int, dict[str, Any], list[str]],
) -> tuple[float, float, int, dict[str, Any], list[str]]:
    _, selected_contact, selected_index, selected_evidence, _ = selected
    selected_gap = _to_float(selected_evidence.get("apex_gap_sec"))
    if selected_gap is None or selected_gap >= LANDING_COMPRESSED_RESELECT_MIN_APEX_GAP_SEC:
        return selected
    if (
        selected_gap >= LANDING_STRONG_CONTACT_MIN_APEX_GAP_SEC
        and selected_contact >= LANDING_COMPRESSED_RESELECT_STRONG_ORIGINAL_CONTACT
    ):
        return selected

    alternatives = [
        item
        for item in scored
        if item[2] > selected_index
        and LANDING_COMPRESSED_RESELECT_MIN_APEX_GAP_SEC
        <= (_to_float(item[3].get("apex_gap_sec")) or 0.0)
        <= LANDING_COMPRESSED_RESELECT_MAX_APEX_GAP_SEC
        and (
            item[1] >= LANDING_COMPRESSED_RESELECT_MIN_CONTACT
            or item[1] >= selected_contact + LANDING_COMPRESSED_RESELECT_MIN_CONTACT_RATIO
            or item[3]["score_components"]["motion_peak"] >= LANDING_COMPRESSED_RESELECT_MIN_MOTION
        )
    ]
    if not alternatives:
        return selected

    chosen = max(
        alternatives,
        key=lambda item: (
            item[1],
            item[3]["score_components"]["motion_peak"],
            item[0],
            -item[2],
        ),
    )
    evidence = dict(chosen[3])
    evidence["landing_compressed_gap_reselection"] = {
        "original_apex_gap_sec": round(selected_gap, 3),
        "original_signal_index": selected_index,
        "original_landing_contact": round(selected_contact, 3),
        "reselected_apex_gap_sec": round(_to_float(evidence.get("apex_gap_sec")) or 0.0, 3),
        "reselected_signal_index": chosen[2],
        "reselected_landing_contact": round(chosen[1], 3),
    }
    warnings = list(chosen[4])
    warnings.append("landing_reselected_from_compressed_apex_gap")
    return chosen[0], chosen[1], chosen[2], evidence, warnings


def _normalized_motion(signals: list[_FrameSignal]) -> list[float]:
    values = [signal.motion_score for signal in signals if signal.motion_score is not None]
    if not values:
        return [0.0 for _ in signals]
    low = min(values)
    high = max(values)
    if high - low <= 1e-9:
        return [0.0 if signal.motion_score is None else _clamp(signal.motion_score / max(high, 1e-9)) for signal in signals]
    return [0.0 if signal.motion_score is None else _clamp((signal.motion_score - low) / (high - low)) for signal in signals]


def _motion_search_windows(signals: list[_FrameSignal], *, limit: int = MAX_JUMP_MOTION_SEARCH_WINDOWS) -> list[tuple[int, int]]:
    scored = [
        (index, float(signal.motion_score), float(signal.timestamp))
        for index, signal in enumerate(signals)
        if signal.motion_score is not None
    ]
    if len(scored) < 3:
        return []
    max_score = max(score for _, score, _ in scored)
    if max_score < MOTION_FALLBACK_MIN_PEAK_SCORE:
        return []

    top_threshold = max_score * JUMP_MOTION_WINDOW_TOP_PEAK_RATIO
    cluster_threshold = max_score * JUMP_MOTION_WINDOW_CLUSTER_RATIO
    top_anchors = sorted(
        (item for item in scored if item[1] >= top_threshold),
        key=lambda item: (-item[1], item[2], item[0]),
    )
    secondary_anchors = sorted(
        (item for item in scored if cluster_threshold <= item[1] < top_threshold),
        key=lambda item: (-item[1], item[2], item[0]),
    )
    windows: list[tuple[int, int]] = []
    for _, _, anchor_time in [*top_anchors, *secondary_anchors]:
        cluster_times = [
            timestamp
            for _, score, timestamp in scored
            if score >= cluster_threshold and abs(timestamp - anchor_time) <= JUMP_MOTION_WINDOW_POST_SEC
        ]
        start_time = min(cluster_times, default=anchor_time) - JUMP_MOTION_WINDOW_PRE_SEC
        end_time = max(cluster_times, default=anchor_time) + JUMP_MOTION_WINDOW_POST_SEC
        start_index = next((index for index, signal in enumerate(signals) if signal.timestamp >= start_time), 0)
        end_index = next(
            (index - 1 for index, signal in enumerate(signals) if index > start_index and signal.timestamp > end_time),
            len(signals) - 1,
        )
        window = max(0, start_index), min(len(signals) - 1, end_index)
        if window[1] - window[0] + 1 < 3:
            continue
        if any(not (window[1] < existing[0] or existing[1] < window[0]) for existing in windows):
            continue
        windows.append(window)
        if len(windows) >= limit:
            break
    return windows


def _motion_search_window(signals: list[_FrameSignal]) -> tuple[int, int] | None:
    windows = _motion_search_windows(signals, limit=1)
    return windows[0] if windows else None


def _in_search_window(index: int, search_window: tuple[int, int] | None) -> bool:
    return search_window is None or search_window[0] <= index <= search_window[1]


def _motion_window_payload(signals: list[_FrameSignal], search_window: tuple[int, int]) -> dict[str, float | int]:
    return {
        "start_signal_index": search_window[0],
        "end_signal_index": search_window[1],
        "start_timestamp": round(signals[search_window[0]].timestamp, 3),
        "end_timestamp": round(signals[search_window[1]].timestamp, 3),
    }


def _motion_window_time_bounds(signals: list[_FrameSignal], search_window: tuple[int, int]) -> tuple[float, float]:
    return signals[search_window[0]].timestamp, signals[search_window[1]].timestamp


def _score_component(candidate: dict[str, Any], key: str) -> float:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
    return _to_float(components.get(key)) or 0.0


def _motion_window_contamination_flags(
    signals: list[_FrameSignal],
    search_window: tuple[int, int] | None,
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    frame_states: dict[str, dict[str, str]],
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> list[str]:
    if search_window is None:
        return []
    start_index, end_index = search_window
    window_signals = signals[start_index : end_index + 1]
    if len(window_signals) < 3:
        return []

    window_start = signals[start_index].timestamp
    window_end = signals[end_index].timestamp
    motion_records = _motion_records(motion_scores, effective_fps)
    if not motion_records:
        motion_records = [
            (signal.index, signal.frame_id, signal.timestamp, signal.motion_score or 0.0)
            for signal in signals
            if signal.motion_score is not None
        ]
    window_records = [record for record in motion_records if window_start <= record[2] <= window_end]
    if len(window_records) < 3:
        return []

    unreliable_records: list[dict[str, Any]] = []
    for record in window_records:
        state = _motion_record_unreliable_pose_state(record, frame_states)
        if state is None:
            continue
        unreliable_records.append(
            {
                "frame_id": record[1],
                "timestamp": round(record[2], 3),
                **state,
            }
        )
    unreliable_ratio = len(unreliable_records) / len(window_records)
    if (
        len(unreliable_records) < MOTION_WINDOW_UNRELIABLE_STATE_MIN_COUNT
        or unreliable_ratio < MOTION_WINDOW_UNRELIABLE_STATE_MIN_RATIO
    ):
        return []

    scored_records = [record for record in motion_records if record[3] is not None]
    if not scored_records:
        return []
    peak_record = max(scored_records, key=lambda record: record[3])
    peak_inside_window = window_start <= peak_record[2] <= window_end
    if not peak_inside_window:
        return []
    peak_matches_unreliable_record = any(
        abs(record[2] - peak_record[2]) <= MOTION_WINDOW_UNRELIABLE_PEAK_MATCH_TOLERANCE_SEC
        and _motion_record_unreliable_pose_state(record, frame_states) is not None
        for record in window_records
    )
    if not peak_matches_unreliable_record:
        return []

    landing_contact = _score_component(landing, "landing_contact")
    if landing_contact > MOTION_WINDOW_CONTAMINATED_LANDING_CONTACT_MAX:
        return []

    diagnostic = {
        "unreliable_state_count": len(unreliable_records),
        "window_record_count": len(window_records),
        "unreliable_state_ratio": round(unreliable_ratio, 3),
        "peak_timestamp": round(peak_record[2], 3),
        "peak_motion_score": round(peak_record[3], 5),
        "landing_contact": round(landing_contact, 3),
        "unreliable_records": unreliable_records,
    }
    for candidate in (takeoff, apex, landing):
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence["motion_window_occlusion_contamination"] = diagnostic
        candidate["evidence"] = evidence
        _append_warning(candidate, "motion_window_occlusion_contaminated")
    return [
        "tal_candidate_motion_window_occlusion_contaminated",
        "tal_candidate_motion_window_unreliable_tracker_state",
    ]


def _early_weak_motion_window_flags(
    signals: list[_FrameSignal],
    search_window: tuple[int, int] | None,
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    issue_flags: Iterable[str],
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> list[str]:
    if search_window is None or len(signals) < 3:
        return []

    issue_set = set(issue_flags)
    if "tal_candidate_weak_geometry" not in issue_set:
        return []

    start_index, end_index = search_window
    window_start = signals[start_index].timestamp
    window_end = signals[end_index].timestamp
    timeline_start = min(signal.timestamp for signal in signals)
    timeline_end = max(signal.timestamp for signal in signals)
    duration = timeline_end - timeline_start
    if duration < EARLY_WEAK_MOTION_WINDOW_MIN_DURATION_SEC:
        return []

    start_offset = window_start - timeline_start
    end_offset = window_end - timeline_start
    if (
        start_index > 0
        and start_offset > EARLY_WEAK_MOTION_WINDOW_MAX_START_SEC
        and start_offset / max(duration, 1e-9) > EARLY_WEAK_MOTION_WINDOW_MAX_START_RATIO
    ):
        return []
    if end_offset / max(duration, 1e-9) > EARLY_WEAK_MOTION_WINDOW_MAX_END_RATIO:
        return []

    motion_records = _motion_records(motion_scores, effective_fps)
    if not motion_records:
        motion_records = [
            (signal.index, signal.frame_id, signal.timestamp, signal.motion_score or 0.0)
            for signal in signals
            if signal.motion_score is not None
        ]
    if not motion_records:
        return []

    window_records = [record for record in motion_records if window_start <= record[2] <= window_end]
    later_records = [
        record
        for record in motion_records
        if record[2] >= window_end + EARLY_WEAK_MOTION_WINDOW_MIN_LATER_GAP_SEC
    ]
    if not window_records or not later_records:
        return []

    window_peak = max(window_records, key=lambda record: record[3])
    later_peak = max(later_records, key=lambda record: record[3])
    if later_peak[3] < window_peak[3] * EARLY_WEAK_MOTION_WINDOW_MIN_LATER_PEAK_RATIO:
        return []

    diagnostic = {
        "reason": "early_weak_geometry_window_with_later_motion_support",
        "window": _motion_window_payload(signals, search_window),
        "timeline_start": round(timeline_start, 3),
        "timeline_end": round(timeline_end, 3),
        "timeline_duration_sec": round(duration, 3),
        "window_peak_timestamp": round(window_peak[2], 3),
        "window_peak_motion_score": round(window_peak[3], 5),
        "later_peak_timestamp": round(later_peak[2], 3),
        "later_peak_motion_score": round(later_peak[3], 5),
        "later_to_window_peak_ratio": round(later_peak[3] / max(window_peak[3], 1e-9), 3),
        "issue_flags": sorted(issue_set),
    }
    for candidate in (takeoff, apex, landing):
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence["early_weak_motion_window"] = diagnostic
        candidate["evidence"] = evidence
        _cap_candidate_confidence(
            candidate,
            EARLY_WEAK_MOTION_WINDOW_CONFIDENCE_CAP,
            "tal_candidate_early_motion_window_weak_geometry",
        )
    return [
        "keyframe_candidates_early_motion_window_weak_geometry",
        "tal_candidate_early_motion_window_weak_geometry",
    ]


def _append_warning(candidate: dict[str, Any], warning: str) -> None:
    warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
    if warning not in warnings:
        candidate["warnings"] = [*warnings, warning]


def _cap_candidate_confidence(candidate: dict[str, Any], cap: float, warning: str) -> None:
    confidence = _to_float(candidate.get("confidence"))
    if confidence is not None and confidence > cap:
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence[f"{warning}_confidence_cap"] = {
            "raw_confidence": round(confidence, 3),
            "cap": round(cap, 3),
        }
        candidate["evidence"] = evidence
        candidate["confidence"] = round(cap, 3)
    _append_warning(candidate, warning)


def _sparse_track_stitched_tal_flags(
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> list[str]:
    takeoff_ts = _to_float(takeoff.get("timestamp"))
    apex_ts = _to_float(apex.get("timestamp"))
    landing_ts = _to_float(landing.get("timestamp"))
    if takeoff_ts is None or apex_ts is None or landing_ts is None:
        return []

    takeoff_index = _candidate_index(takeoff)
    apex_index = _candidate_index(apex)
    landing_index = _candidate_index(landing)
    apex_pose_index = _candidate_pose_index(apex)
    landing_pose_index = _candidate_pose_index(landing)
    if takeoff_index is None or apex_index is None or landing_index is None:
        return []

    apex_landing_gap = landing_ts - apex_ts
    signal_gap = landing_index - apex_index
    pose_gap = (
        landing_pose_index - apex_pose_index
        if apex_pose_index is not None and landing_pose_index is not None
        else signal_gap
    )
    if pose_gap <= SPARSE_TRACK_MAX_SIGNAL_INDEX_GAP:
        return []

    landing_contact = _score_component(landing, "landing_contact")
    apex_warnings = apex.get("warnings") if isinstance(apex.get("warnings"), list) else []
    weak_apex_landing = (
        apex_landing_gap >= SPARSE_TRACK_WEAK_APEX_LANDING_GAP_SEC
        and landing_contact <= SPARSE_TRACK_WEAK_LANDING_CONTACT_MAX
        and "apex_local_minimum_not_clear" in apex_warnings
    )
    sparse_time_gap = apex_landing_gap >= SPARSE_TRACK_MIN_TIME_GAP_SEC
    tal_span = landing_ts - takeoff_ts
    if tal_span <= SPARSE_TRACK_MAX_TAL_GAP_SEC and not sparse_time_gap:
        return []
    if not (weak_apex_landing or sparse_time_gap):
        return []

    diagnostic = {
        "tal_span_sec": round(tal_span, 3),
        "apex_landing_gap_sec": round(apex_landing_gap, 3),
        "apex_landing_signal_gap": signal_gap,
        "apex_landing_pose_gap": pose_gap,
        "landing_contact": round(landing_contact, 3),
    }
    for candidate in (takeoff, apex, landing):
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence["sparse_track_stitched_tal"] = diagnostic
        candidate["evidence"] = evidence
        _cap_candidate_confidence(candidate, SPARSE_TRACK_CONFIDENCE_CAP, "tal_candidate_sparse_track_stitched")
    return ["tal_candidate_sparse_track_stitched", "tal_candidate_unreliable_sparse_track_stitch"]


def _weak_geometry_flags(
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    takeoff_joint_weak = (
        _score_component(takeoff, "knee_extension") <= WEAK_GEOMETRY_TAKEOFF_JOINT_EXTENSION_MAX
        and _score_component(takeoff, "takeoff_event") < WEAK_GEOMETRY_TAKEOFF_JOINT_EVENT_MAX
    )
    if _score_component(takeoff, "takeoff_event") < WEAK_GEOMETRY_TAKEOFF_EVENT_MAX or takeoff_joint_weak:
        flags.append("tal_candidate_takeoff_geometry_weak")
        _append_warning(takeoff, "takeoff_geometry_weak")
    apex_warnings = apex.get("warnings") if isinstance(apex.get("warnings"), list) else []
    apex_evidence = apex.get("evidence") if isinstance(apex.get("evidence"), dict) else {}
    apex_descent_support = _to_float(apex_evidence.get("descent_support"))
    if (
        "apex_local_minimum_not_clear" in apex_warnings
        and (
            _score_component(apex, "com_velocity") < WEAK_GEOMETRY_APEX_COM_MAX
            or (
                apex_descent_support is not None
                and apex_descent_support <= WEAK_GEOMETRY_APEX_UNCLEAR_DESCENT_SUPPORT_MAX
            )
        )
    ):
        flags.append("tal_candidate_apex_geometry_weak")
        _append_warning(apex, "apex_geometry_weak")
    landing_components = [
        _score_component(landing, "ankle_return"),
        _score_component(landing, "knee_absorption"),
        _score_component(landing, "com_descent"),
    ]
    landing_joint_weak = (
        _score_component(landing, "ankle_return") <= WEAK_GEOMETRY_LANDING_JOINT_COMPONENT_MAX
        and _score_component(landing, "knee_absorption") <= WEAK_GEOMETRY_LANDING_JOINT_COMPONENT_MAX
        and _score_component(landing, "landing_contact") < WEAK_GEOMETRY_LANDING_JOINT_CONTACT_MAX
    )
    landing_warnings = landing.get("warnings") if isinstance(landing.get("warnings"), list) else []
    early_weak_landing = (
        "landing_weak_contact_early_candidate_selected" in landing_warnings
        and _score_component(landing, "landing_contact") <= WEAK_LANDING_EARLY_CANDIDATE_UNTRUSTED_CONTACT_MAX
        and _score_component(landing, "knee_absorption") <= WEAK_LANDING_EARLY_CANDIDATE_UNTRUSTED_KNEE_MAX
        and _score_component(landing, "com_descent") <= WEAK_LANDING_EARLY_CANDIDATE_UNTRUSTED_DESCENT_MAX
    )
    if (
        _score_component(landing, "landing_contact") < WEAK_GEOMETRY_LANDING_CONTACT_MAX
        or landing_joint_weak
        or early_weak_landing
    ):
        flags.append("tal_candidate_landing_geometry_weak")
        _append_warning(landing, "landing_geometry_weak")
    landing_evidence = landing.get("evidence") if isinstance(landing.get("evidence"), dict) else {}
    takeoff_evidence = takeoff.get("evidence") if isinstance(takeoff.get("evidence"), dict) else {}
    landing_apex_gap = _to_float(landing_evidence.get("apex_gap_sec"))
    if (
        _score_component(landing, "landing_contact") < WEAK_GEOMETRY_LANDING_CONTACT_HARD_MAX
        and max(landing_components, default=0.0) < WEAK_GEOMETRY_LANDING_COMPONENT_HARD_MAX
        and landing_apex_gap is not None
        and landing_apex_gap >= WEAK_GEOMETRY_LANDING_ABSENT_MIN_APEX_GAP_SEC
    ):
        flags.append("tal_candidate_landing_geometry_absent")
        _append_warning(landing, "landing_geometry_absent")
    if len(flags) >= WEAK_GEOMETRY_MIN_FLAGS:
        flags.append("tal_candidate_weak_geometry")
        diagnostic = {
            "reason": "multiple_weak_pose_geometry_signals",
            "flags": list(flags),
            "takeoff_event": round(_score_component(takeoff, "takeoff_event"), 3),
            "takeoff_knee_extension": round(_score_component(takeoff, "knee_extension"), 3),
            "apex_com_velocity": round(_score_component(apex, "com_velocity"), 3),
            "landing_contact": round(_score_component(landing, "landing_contact"), 3),
            "landing_ankle_return": round(_score_component(landing, "ankle_return"), 3),
            "landing_knee_absorption": round(_score_component(landing, "knee_absorption"), 3),
        }
        for candidate in (takeoff, apex, landing):
            evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
            evidence["weak_geometry_confidence_cap"] = diagnostic
            candidate["evidence"] = evidence
            _cap_candidate_confidence(candidate, WEAK_GEOMETRY_CONFIDENCE_CAP, "tal_candidate_weak_geometry")
    return flags


def _tiny_target_weak_geometry_flags(
    pose_data: dict[str, Any] | None,
    quality_flags: Iterable[str],
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> list[str]:
    flag_set = {str(flag) for flag in quality_flags}
    if "tal_candidate_weak_geometry" not in flag_set:
        return []

    bbox_stats = _pose_target_bbox_stats(pose_data)
    median_width = _to_float(bbox_stats.get("median_width")) if bbox_stats else None
    median_area = _to_float(bbox_stats.get("median_area")) if bbox_stats else None
    tiny_by_bbox = (
        median_width is not None
        and median_area is not None
        and (
            median_width <= MOTION_FALLBACK_TINY_TARGET_MAX_MEDIAN_WIDTH
            or median_area <= MOTION_FALLBACK_TINY_TARGET_MAX_MEDIAN_AREA
        )
    )
    tiny_by_tracker_risk = TINY_TARGET_LOW_POSE_TRACKING_RISK_FLAG in _pose_quality_flags(pose_data)
    if not tiny_by_bbox and not tiny_by_tracker_risk:
        return []

    diagnostic = {
        "reason": "tiny_target_weak_pose_geometry",
        "tiny_by_bbox": tiny_by_bbox,
        "tiny_by_tracker_risk": tiny_by_tracker_risk,
        "bbox_stats": bbox_stats or {},
        "candidate_flags": sorted(flag_set),
    }
    for candidate in (takeoff, apex, landing):
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence["tiny_target_weak_geometry"] = diagnostic
        candidate["evidence"] = evidence
        _cap_candidate_confidence(
            candidate,
            TINY_TARGET_WEAK_GEOMETRY_CONFIDENCE_CAP,
            "tal_candidate_tiny_target_weak_geometry",
        )
    return ["tal_candidate_tiny_target_weak_geometry"]


def _temporal_geometry_unreliable_flags(
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> list[str]:
    takeoff_ts = _to_float(takeoff.get("timestamp"))
    apex_ts = _to_float(apex.get("timestamp"))
    landing_ts = _to_float(landing.get("timestamp"))
    if takeoff_ts is None or apex_ts is None or landing_ts is None:
        return []

    takeoff_components = (
        takeoff.get("evidence", {}).get("score_components", {})
        if isinstance(takeoff.get("evidence"), dict)
        else {}
    )
    takeoff_evidence = takeoff.get("evidence") if isinstance(takeoff.get("evidence"), dict) else {}
    landing_components = (
        landing.get("evidence", {}).get("score_components", {})
        if isinstance(landing.get("evidence"), dict)
        else {}
    )
    takeoff_apex_gap = apex_ts - takeoff_ts
    apex_landing_gap = landing_ts - apex_ts
    weak_takeoff_timing = (
        takeoff_apex_gap >= WEAK_TAL_TAKEOFF_APEX_GAP_SEC
        and _to_float(takeoff_components.get("takeoff_timing")) is not None
        and (_to_float(takeoff_components.get("takeoff_timing")) or 0.0) <= WEAK_TAL_TAKEOFF_TIMING_MAX
    )
    weak_landing_timing = (
        apex_landing_gap >= WEAK_TAL_APEX_LANDING_GAP_SEC
        and (_to_float(landing_components.get("landing_contact")) or 0.0) <= WEAK_TAL_LANDING_CONTACT_MAX
    )
    apex_components = (
        apex.get("evidence", {}).get("score_components", {})
        if isinstance(apex.get("evidence"), dict)
        else {}
    )
    apex_warnings = apex.get("warnings") if isinstance(apex.get("warnings"), list) else []
    landing_warnings = landing.get("warnings") if isinstance(landing.get("warnings"), list) else []
    takeoff_warnings = takeoff.get("warnings") if isinstance(takeoff.get("warnings"), list) else []
    apex_has_weak_signal = (
        "apex_local_minimum_not_clear" in apex_warnings
        or "confidence_missing_knee_angle_change" in apex_warnings
        or (_to_float(apex_components.get("com_velocity")) or 0.0) <= WEAK_TAL_COMPRESSED_APEX_COM_MAX
        or (_to_float(apex_components.get("motion_peak")) or 0.0) <= 0.55
    )
    landing_has_weak_signal = (
        bool(set(landing_warnings) & {"ankle_return_weak", "knee_absorption_weak", "landing_geometry_weak"})
        or (_to_float(landing_components.get("landing_contact")) or 0.0) <= 0.75
        or (_to_float(landing_components.get("ankle_return")) or 0.0) <= 0.55
    )
    takeoff_late_reselection = isinstance(takeoff_evidence.get("takeoff_late_plausible_reselection"), dict)
    takeoff_has_weak_reselected_signal = (
        takeoff_late_reselection
        and (
            "knee_extension_weak" in (takeoff.get("warnings") if isinstance(takeoff.get("warnings"), list) else [])
            or (_to_float(takeoff_components.get("takeoff_event")) or 0.0)
            <= WEAK_TAL_COMPRESSED_TAKEOFF_RESELECT_EVENT_MAX
            or (_to_float(takeoff_components.get("knee_extension")) or 0.0)
            <= WEAK_TAL_COMPRESSED_TAKEOFF_RESELECT_EXTENSION_MAX
        )
    )
    takeoff_has_weak_signal = (
        bool(set(takeoff_warnings) & {"takeoff_geometry_weak", "knee_extension_weak", "com_ascent_weak"})
        or (_to_float(takeoff_components.get("takeoff_event")) or 0.0)
        <= WEAK_TAL_COMPRESSED_TAKEOFF_RESELECT_EVENT_MAX
        or (_to_float(takeoff_components.get("knee_extension")) or 0.0)
        <= WEAK_TAL_COMPRESSED_TAKEOFF_RESELECT_EXTENSION_MAX
    )
    compressed_takeoff_apex_timing = (
        0.0 <= takeoff_apex_gap <= WEAK_TAL_COMPRESSED_TAKEOFF_APEX_RESELECT_GAP_SEC
        and takeoff_has_weak_reselected_signal
    )
    compressed_weak_takeoff_apex_signal = (
        0.0 <= takeoff_apex_gap <= WEAK_TAL_COMPRESSED_TAKEOFF_APEX_SIGNAL_GAP_SEC
        and takeoff_has_weak_signal
        and apex_has_weak_signal
    )
    compressed_landing_timing = (
        0.0 <= apex_landing_gap <= WEAK_TAL_COMPRESSED_APEX_LANDING_GAP_SEC
        and (_to_float(landing_components.get("landing_contact")) or 0.0) <= WEAK_TAL_LANDING_CONTACT_MAX
        and takeoff_late_reselection
        and (
            "apex_local_minimum_not_clear" in apex_warnings
            or (_to_float(apex_components.get("com_velocity")) or 0.0) <= WEAK_TAL_COMPRESSED_APEX_COM_MAX
        )
    )
    compressed_core_timing = (
        0.0 <= takeoff_apex_gap <= WEAK_TAL_COMPRESSED_CORE_TAKEOFF_APEX_GAP_SEC
        and 0.0 <= apex_landing_gap <= WEAK_TAL_COMPRESSED_CORE_APEX_LANDING_GAP_SEC
        and (apex_has_weak_signal or landing_has_weak_signal)
    )
    compressed_apex_landing_signal = (
        0.0 <= apex_landing_gap <= WEAK_TAL_COMPRESSED_APEX_LANDING_SIGNAL_GAP_SEC
        and (apex_has_weak_signal or landing_has_weak_signal)
    )
    compressed_visible_apex_landing_signal = (
        0.0 <= apex_landing_gap <= WEAK_TAL_COMPRESSED_APEX_LANDING_VISIBLE_SIGNAL_GAP_SEC
        and "confidence_missing_knee_angle_change" in apex_warnings
        and (_to_float(apex_components.get("pose_visibility")) or 0.0)
        >= WEAK_TAL_VISIBLE_COMPRESSED_APEX_MIN_VISIBILITY
        and (_to_float(landing_components.get("landing_contact")) or 0.0)
        <= WEAK_TAL_VISIBLE_COMPRESSED_LANDING_CONTACT_MAX
    )
    compressed_weak_apex_landing_signal = (
        0.0 <= apex_landing_gap <= WEAK_TAL_COMPRESSED_APEX_LANDING_WEAK_SIGNAL_GAP_SEC
        and "apex_local_minimum_not_clear" in apex_warnings
        and (_to_float(apex_components.get("com_velocity")) or 0.0) <= WEAK_TAL_COMPRESSED_APEX_COM_MAX
        and landing_has_weak_signal
        and (_to_float(landing_components.get("landing_contact")) or 0.0) <= WEAK_TAL_LANDING_CONTACT_MAX
    )
    late_weak_landing_timing = (
        apex_landing_gap >= WEAK_TAL_LATE_LANDING_GAP_SEC
        and (_to_float(landing_components.get("landing_timing")) or 0.0) <= WEAK_TAL_LATE_LANDING_TIMING_MAX
        and (_to_float(landing_components.get("motion_peak")) or 0.0) <= WEAK_TAL_LATE_LANDING_MOTION_MAX
        and (_to_float(landing_components.get("knee_absorption")) or 0.0) <= WEAK_TAL_LATE_LANDING_KNEE_MAX
        and (_to_float(landing_components.get("landing_contact")) or 0.0) <= WEAK_TAL_LATE_LANDING_CONTACT_MAX
    )
    if not (
        weak_takeoff_timing
        or weak_landing_timing
        or compressed_takeoff_apex_timing
        or compressed_weak_takeoff_apex_signal
        or compressed_landing_timing
        or compressed_core_timing
        or compressed_apex_landing_signal
        or compressed_visible_apex_landing_signal
        or compressed_weak_apex_landing_signal
        or late_weak_landing_timing
    ):
        return []

    diagnostic = {
        "takeoff_apex_gap_sec": round(takeoff_apex_gap, 3),
        "apex_landing_gap_sec": round(apex_landing_gap, 3),
        "takeoff_timing": round(_to_float(takeoff_components.get("takeoff_timing")) or 0.0, 3),
        "takeoff_event": round(_to_float(takeoff_components.get("takeoff_event")) or 0.0, 3),
        "knee_extension": round(_to_float(takeoff_components.get("knee_extension")) or 0.0, 3),
        "landing_contact": round(_to_float(landing_components.get("landing_contact")) or 0.0, 3),
        "landing_timing": round(_to_float(landing_components.get("landing_timing")) or 0.0, 3),
        "landing_motion": round(_to_float(landing_components.get("motion_peak")) or 0.0, 3),
        "landing_knee_absorption": round(_to_float(landing_components.get("knee_absorption")) or 0.0, 3),
        "apex_com_velocity": round(_to_float(apex_components.get("com_velocity")) or 0.0, 3),
    }
    for candidate in (takeoff, apex, landing):
        _append_warning(candidate, "tal_candidate_temporal_geometry_unreliable")
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence["temporal_geometry_unreliable"] = diagnostic
        candidate["evidence"] = evidence
    flags = ["tal_candidate_temporal_geometry_unreliable"]
    if weak_takeoff_timing:
        flags.append("tal_candidate_takeoff_apex_gap_unreliable")
    if compressed_takeoff_apex_timing:
        flags.append("tal_candidate_takeoff_apex_gap_unreliable")
        flags.append("tal_candidate_takeoff_apex_gap_compressed")
    if compressed_weak_takeoff_apex_signal:
        flags.append("tal_candidate_takeoff_apex_gap_unreliable")
        flags.append("tal_candidate_takeoff_apex_gap_compressed")
    if weak_landing_timing:
        flags.append("tal_candidate_apex_landing_gap_unreliable")
    if compressed_landing_timing:
        flags.append("tal_candidate_apex_landing_gap_unreliable")
        flags.append("tal_candidate_apex_landing_gap_compressed")
    if compressed_apex_landing_signal:
        flags.append("tal_candidate_apex_landing_gap_unreliable")
        flags.append("tal_candidate_apex_landing_gap_compressed")
    if compressed_visible_apex_landing_signal:
        flags.append("tal_candidate_apex_landing_gap_unreliable")
        flags.append("tal_candidate_apex_landing_gap_compressed")
    if compressed_weak_apex_landing_signal:
        flags.append("tal_candidate_apex_landing_gap_unreliable")
        flags.append("tal_candidate_apex_landing_gap_compressed")
    if late_weak_landing_timing:
        flags.append("tal_candidate_apex_landing_gap_unreliable")
        flags.append("tal_candidate_late_weak_landing")
    if compressed_core_timing:
        flags.append("tal_candidate_apex_landing_gap_unreliable")
        flags.append("tal_candidate_core_gap_compressed")
    confidence_cap = (
        TEMPORAL_GEOMETRY_COMPRESSED_CONFIDENCE_CAP
        if (
            compressed_takeoff_apex_timing
            or compressed_weak_takeoff_apex_signal
            or compressed_landing_timing
            or compressed_core_timing
            or compressed_apex_landing_signal
            or compressed_visible_apex_landing_signal
            or compressed_weak_apex_landing_signal
        )
        else TEMPORAL_GEOMETRY_UNRELIABLE_CONFIDENCE_CAP
    )
    cap_warning = (
        "tal_candidate_compressed_temporal_geometry"
        if confidence_cap == TEMPORAL_GEOMETRY_COMPRESSED_CONFIDENCE_CAP
        else "tal_candidate_temporal_geometry_unreliable"
    )
    for candidate in (takeoff, apex, landing):
        _cap_candidate_confidence(candidate, confidence_cap, cap_warning)
    return flags


def _tail_motion_window_has_weak_geometry(
    signals: list[_FrameSignal],
    search_window: tuple[int, int] | None,
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> bool:
    if search_window is None or len(signals) < 8:
        return False
    start_index, end_index = search_window
    if end_index < len(signals) - 2:
        return False
    if start_index < int((len(signals) - 1) * JUMP_TAIL_MOTION_WINDOW_MIN_START_RATIO):
        return False
    if end_index - start_index + 1 > JUMP_TAIL_MOTION_WINDOW_MAX_SIGNAL_COUNT:
        return False
    window_peak = max((signals[index].motion_score or 0.0) for index in range(start_index, end_index + 1))
    if window_peak >= JUMP_TAIL_MOTION_WINDOW_MAX_PEAK_SCORE:
        return False

    weak_takeoff = (
        _score_component(takeoff, "knee_extension") < 0.15
        and _score_component(takeoff, "takeoff_event") < JUMP_TAIL_MOTION_WINDOW_TAKEOFF_EVENT_MAX
    )
    weak_landing = (
        _score_component(landing, "landing_contact") < JUMP_TAIL_MOTION_WINDOW_LANDING_CONTACT_MAX
        and max(
            _score_component(landing, "ankle_return"),
            _score_component(landing, "knee_absorption"),
            _score_component(landing, "com_descent"),
        )
        < 0.25
    )
    apex_warnings = apex.get("warnings") if isinstance(apex.get("warnings"), list) else []
    unclear_apex = (
        "apex_local_minimum_not_clear" in apex_warnings
        and _score_component(apex, "com_velocity") < 0.65
    )

    takeoff_ts = _to_float(takeoff.get("timestamp"))
    apex_ts = _to_float(apex.get("timestamp"))
    landing_ts = _to_float(landing.get("timestamp"))
    compressed_weak_core = False
    if takeoff_ts is not None and apex_ts is not None and landing_ts is not None:
        compressed_weak_core = (
            0.0 <= apex_ts - takeoff_ts <= JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_CORE_GAP_SEC
            and 0.0 <= landing_ts - apex_ts <= JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_CORE_GAP_SEC
            and 0.0 <= landing_ts - takeoff_ts <= JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_TAL_SPAN_SEC
            and _score_component(takeoff, "takeoff_event")
            <= JUMP_TAIL_MOTION_WINDOW_COMPRESSED_WEAK_TAKEOFF_EVENT
            and _score_component(takeoff, "knee_extension") < 0.15
            and "apex_local_minimum_not_clear" in apex_warnings
            and _score_component(apex, "com_velocity") <= JUMP_TAIL_MOTION_WINDOW_COMPRESSED_WEAK_APEX_COM
        )
    return (weak_landing and (weak_takeoff or unclear_apex)) or compressed_weak_core


def _tail_motion_window_compressed_core_diagnostic(
    signals: list[_FrameSignal],
    search_window: tuple[int, int] | None,
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> dict[str, Any] | None:
    if search_window is None or len(signals) < 8:
        return None
    start_index, end_index = search_window
    if end_index < len(signals) - 2:
        return None
    tail_start_ratio = start_index / max(len(signals) - 1, 1)
    if tail_start_ratio < JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MIN_START_RATIO:
        return None
    signal_count = end_index - start_index + 1
    if signal_count > JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_SIGNAL_COUNT:
        return None
    window_peak = max((signals[index].motion_score or 0.0) for index in range(start_index, end_index + 1))
    if window_peak >= JUMP_TAIL_MOTION_WINDOW_MAX_PEAK_SCORE:
        return None

    takeoff_ts = _to_float(takeoff.get("timestamp"))
    apex_ts = _to_float(apex.get("timestamp"))
    landing_ts = _to_float(landing.get("timestamp"))
    if (
        takeoff_ts is None
        or apex_ts is None
        or landing_ts is None
        or not (
            0.0 <= apex_ts - takeoff_ts <= JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_CORE_GAP_SEC
            and 0.0 <= landing_ts - apex_ts <= JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_CORE_GAP_SEC
            and 0.0 <= landing_ts - takeoff_ts <= JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_TAL_SPAN_SEC
        )
        or _score_component(takeoff, "takeoff_event") > JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_TAKEOFF_EVENT
        or _score_component(landing, "landing_contact") > JUMP_TAIL_MOTION_WINDOW_COMPRESSED_MAX_LANDING_CONTACT
    ):
        return None
    return {
        "reason": "tail_motion_window_compressed_core_tal",
        "tail_start_ratio": round(tail_start_ratio, 3),
        "window_signal_count": signal_count,
        "window_peak_motion_score": round(window_peak, 5),
        "takeoff_apex_gap_sec": round(apex_ts - takeoff_ts, 3),
        "apex_landing_gap_sec": round(landing_ts - apex_ts, 3),
        "tal_span_sec": round(landing_ts - takeoff_ts, 3),
        "takeoff_event": round(_score_component(takeoff, "takeoff_event"), 3),
        "landing_contact": round(_score_component(landing, "landing_contact"), 3),
    }


def _apply_tail_compressed_motion_window_diagnostic(
    signals: list[_FrameSignal],
    search_window: tuple[int, int] | None,
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> list[str]:
    diagnostic = _tail_motion_window_compressed_core_diagnostic(signals, search_window, takeoff, apex, landing)
    if diagnostic is None:
        return []
    for candidate in (takeoff, apex, landing):
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence["tail_motion_window_compressed_core"] = diagnostic
        candidate["evidence"] = evidence
        _append_warning(candidate, "tal_candidate_tail_motion_window_compressed_core")
    return [
        "tal_candidate_tail_motion_window_compressed_core",
        "tal_candidate_temporal_geometry_unreliable",
    ]


def _window_candidate_issue_flags(
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> set[str]:
    takeoff_copy = copy.deepcopy(takeoff)
    apex_copy = copy.deepcopy(apex)
    landing_copy = copy.deepcopy(landing)
    return set(
        _weak_geometry_flags(takeoff_copy, apex_copy, landing_copy)
        + _temporal_geometry_unreliable_flags(takeoff_copy, apex_copy, landing_copy)
        + _sparse_track_stitched_tal_flags(takeoff_copy, apex_copy, landing_copy)
    )


def _candidate_timestamp(candidate: dict[str, Any]) -> float | None:
    return _to_float(candidate.get("timestamp"))


def _candidate_average_confidence(candidates: Iterable[dict[str, Any]]) -> float:
    values = [
        value
        for candidate in candidates
        if (value := _to_float(candidate.get("confidence"))) is not None
    ]
    return sum(values) / len(values) if values else 0.0


def _candidate_triplet_is_ordered(
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
) -> bool:
    takeoff_ts = _candidate_timestamp(takeoff)
    apex_ts = _candidate_timestamp(apex)
    landing_ts = _candidate_timestamp(landing)
    return (
        takeoff_ts is not None
        and apex_ts is not None
        and landing_ts is not None
        and takeoff_ts < apex_ts < landing_ts
    )


def _candidate_triplet_span(
    takeoff: dict[str, Any],
    landing: dict[str, Any],
) -> float | None:
    takeoff_ts = _candidate_timestamp(takeoff)
    landing_ts = _candidate_timestamp(landing)
    if takeoff_ts is None or landing_ts is None:
        return None
    return landing_ts - takeoff_ts


def _window_candidate_reselection_score(
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
    flags: set[str],
) -> float:
    confidence = _candidate_average_confidence((takeoff, apex, landing))
    span = _candidate_triplet_span(takeoff, landing)
    span_score = 0.0 if span is None else _clamp(span / 0.80)
    penalty = 0.0
    penalty += 0.55 if "tal_candidate_temporal_geometry_unreliable" in flags else 0.0
    penalty += 0.40 if "tal_candidate_compressed_temporal_geometry" in {
        warning
        for candidate in (takeoff, apex, landing)
        for warning in (candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else [])
    } else 0.0
    penalty += 0.20 if "tal_candidate_weak_geometry" in flags else 0.0
    return confidence + 0.25 * span_score - penalty


def _compressed_weak_window_should_reselect(
    takeoff: dict[str, Any],
    apex: dict[str, Any],
    landing: dict[str, Any],
    flags: set[str],
) -> bool:
    if not _candidate_triplet_is_ordered(takeoff, apex, landing):
        return False
    span = _candidate_triplet_span(takeoff, landing)
    if span is None or span > 0.45:
        return False
    warnings = {
        warning
        for candidate in (takeoff, apex, landing)
        for warning in (candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else [])
    }
    weak_geometry = bool(
        flags
        & {
            "tal_candidate_takeoff_geometry_weak",
            "tal_candidate_apex_geometry_weak",
            "tal_candidate_landing_geometry_weak",
            "tal_candidate_weak_geometry",
        }
    )
    low_confidence = (
        _candidate_average_confidence((takeoff, apex, landing))
        <= COMPRESSED_WEAK_WINDOW_RESELECT_MAX_AVG_CONFIDENCE
    )
    return (
        "tal_candidate_temporal_geometry_unreliable" in flags
        and (weak_geometry or low_confidence)
        and (
            "tal_candidate_apex_landing_gap_compressed" in flags
            or "tal_candidate_core_gap_compressed" in flags
            or "tal_candidate_compressed_temporal_geometry" in warnings
        )
    )


def _window_peak_motion_score(signals: list[_FrameSignal], window: tuple[int, int] | None) -> float:
    if window is None or not signals:
        return 0.0
    start_index, end_index = window
    return max(
        (
            signals[index].motion_score or 0.0
            for index in range(max(0, start_index), min(len(signals), end_index + 1))
        ),
        default=0.0,
    )


def _early_alternative_needs_stronger_motion_support(
    signals: list[_FrameSignal],
    current_window: tuple[int, int],
    alternative_window: tuple[int, int] | None,
) -> bool:
    if alternative_window is None or not signals:
        return False
    current_start_ts = signals[current_window[0]].timestamp
    alternative_end_ts = signals[alternative_window[1]].timestamp
    if alternative_end_ts > current_start_ts - COMPRESSED_WEAK_WINDOW_EARLY_ALT_MIN_GAP_SEC:
        return False

    current_peak = _window_peak_motion_score(signals, current_window)
    alternative_peak = _window_peak_motion_score(signals, alternative_window)
    if current_peak <= 0.0:
        return False
    return alternative_peak < current_peak * COMPRESSED_WEAK_WINDOW_EARLY_ALT_MIN_PEAK_RATIO


def _late_pose_core_reselection(
    signals: list[_FrameSignal],
    rejected_tail_window: tuple[int, int] | None,
    selected_window: tuple[int, int] | None,
    smoothed_com: list[float | None],
    smoothed_knee: list[float | None],
    smoothed_ankle: list[float | None],
    motion_norm: list[float],
    detect_for_window: Any,
) -> tuple[tuple[int, int], dict[str, Any], dict[str, Any], dict[str, Any], int | None, dict[str, Any]] | None:
    if rejected_tail_window is None or selected_window is None or len(signals) < 8:
        return None
    timeline_start = min(signal.timestamp for signal in signals)
    timeline_end = max(signal.timestamp for signal in signals)
    duration = timeline_end - timeline_start
    if duration < LATE_POSE_CORE_RESELECT_MIN_DURATION_SEC:
        return None

    selected_end_ts = signals[selected_window[1]].timestamp
    selected_end_ratio = (selected_end_ts - timeline_start) / max(duration, 1e-9)
    if selected_end_ratio > LATE_POSE_CORE_RESELECT_MAX_EARLY_WINDOW_END_RATIO:
        return None

    tail_start_ts = signals[rejected_tail_window[0]].timestamp
    selected_peak = _window_peak_motion_score(signals, selected_window)
    tail_peak = _window_peak_motion_score(signals, rejected_tail_window)
    search_start_ts = max(
        selected_end_ts - LATE_POSE_CORE_RESELECT_MAX_START_OVERLAP_SEC,
        timeline_start,
    )
    search_end_ts = tail_start_ts - LATE_POSE_CORE_RESELECT_MIN_TAIL_LEAD_SEC
    if search_end_ts - search_start_ts < LATE_POSE_CORE_RESELECT_MIN_SPAN_SEC:
        return None

    start_candidates = [
        index
        for index, signal in enumerate(signals)
        if signal.timestamp >= search_start_ts
        and signal.timestamp <= search_end_ts
        and signal.com_y is not None
        and signal.knee_angle is not None
        and signal.visibility_score >= MIN_VISIBILITY
    ]
    if not start_candidates:
        return None
    best: tuple[float, tuple[int, int], dict[str, Any], dict[str, Any], dict[str, Any], int | None, dict[str, Any]] | None = None

    for start_index in start_candidates:
        if signals[start_index].timestamp - selected_end_ts > LATE_POSE_CORE_RESELECT_MAX_SELECTED_END_GAP_SEC:
            continue
        end_limit = min(
            len(signals) - 1,
            next(
                (
                    index - 1
                    for index, signal in enumerate(signals)
                    if index > start_index
                    and (
                        signal.timestamp - signals[start_index].timestamp
                        > LATE_POSE_CORE_RESELECT_MAX_SPAN_SEC
                    )
                ),
                len(signals) - 1,
            ),
        )
        for end_index in range(start_index + LATE_POSE_CORE_RESELECT_MIN_SIGNAL_COUNT - 1, end_limit + 1):
            if signals[end_index].timestamp > search_end_ts:
                break
            if signals[end_index].timestamp < selected_end_ts + LATE_POSE_CORE_RESELECT_MIN_END_EXTENSION_SEC:
                continue
            span_sec = signals[end_index].timestamp - signals[start_index].timestamp
            if span_sec < LATE_POSE_CORE_RESELECT_MIN_SPAN_SEC:
                continue
            window = (start_index, end_index)
            window_signals = signals[start_index : end_index + 1]
            visible = [signal.visibility_score for signal in window_signals if signal.visibility_score >= MIN_VISIBILITY]
            if len(visible) < LATE_POSE_CORE_RESELECT_MIN_SIGNAL_COUNT:
                continue
            avg_visibility = sum(visible) / len(visible)
            if avg_visibility < LATE_POSE_CORE_RESELECT_MIN_AVG_VISIBILITY:
                continue
            window_peak = _window_peak_motion_score(signals, window)
            if selected_peak > 0.0 and window_peak > selected_peak * LATE_POSE_CORE_RESELECT_MAX_PEAK_RATIO:
                continue

            takeoff, apex, landing, apex_index = detect_for_window(window)
            if not _candidate_triplet_is_ordered(takeoff, apex, landing):
                continue
            takeoff_ts = _candidate_timestamp(takeoff)
            apex_ts = _candidate_timestamp(apex)
            if takeoff_ts is None or apex_ts is None:
                continue
            takeoff_apex_gap = apex_ts - takeoff_ts
            if not (
                LATE_POSE_CORE_RESELECT_MIN_TAKEOFF_APEX_GAP_SEC
                <= takeoff_apex_gap
                <= LATE_POSE_CORE_RESELECT_MAX_TAKEOFF_APEX_GAP_SEC
            ):
                continue
            avg_confidence = _candidate_average_confidence((takeoff, apex, landing))
            if avg_confidence < LATE_POSE_CORE_RESELECT_MIN_AVG_CONFIDENCE:
                continue
            if (_to_float(takeoff.get("confidence")) or 0.0) < LATE_POSE_CORE_RESELECT_MIN_TAKEOFF_CONFIDENCE:
                continue
            if (_to_float(apex.get("confidence")) or 0.0) < LATE_POSE_CORE_RESELECT_MIN_APEX_CONFIDENCE:
                continue
            if (_to_float(landing.get("confidence")) or 0.0) < LATE_POSE_CORE_RESELECT_MIN_LANDING_CONFIDENCE:
                continue

            flags = _window_candidate_issue_flags(takeoff, apex, landing)
            if "tal_candidate_sparse_track_stitched" in flags:
                continue
            if "tal_candidate_takeoff_apex_gap_compressed" in flags:
                continue

            span = _candidate_triplet_span(takeoff, landing) or 0.0
            motion_quietness = 1.0 - _clamp(window_peak / max(selected_peak, 1e-9)) if selected_peak > 0.0 else 0.0
            proximity_to_tail = _clamp(1.0 - (tail_start_ts - signals[end_index].timestamp) / max(duration, 1e-9))
            score = (
                avg_confidence
                + 0.16 * _clamp(span / 0.80)
                + 0.12 * motion_quietness
                + 0.08 * proximity_to_tail
                + 0.05 * _clamp(avg_visibility)
                - 0.08 * len(flags)
            )
            diagnostic = {
                "reason": "late_pose_core_after_early_motion_window",
                "selected_window": _motion_window_payload(signals, selected_window),
                "rejected_tail_window": _motion_window_payload(signals, rejected_tail_window),
                "pose_core_window": _motion_window_payload(signals, window),
                "timeline_duration_sec": round(duration, 3),
                "selected_window_end_ratio": round(selected_end_ratio, 3),
                "selected_peak_motion_score": round(selected_peak, 5),
                "tail_peak_motion_score": round(tail_peak, 5),
                "pose_core_peak_motion_score": round(window_peak, 5),
                "pose_core_avg_visibility": round(avg_visibility, 3),
                "pose_core_avg_confidence": round(avg_confidence, 3),
                "pose_core_issue_flags": sorted(flags),
            }
            if best is None or score > best[0]:
                best = (score, window, takeoff, apex, landing, apex_index, diagnostic)

    if best is None:
        return None
    _, window, takeoff, apex, landing, apex_index, diagnostic = best
    for candidate in (takeoff, apex, landing):
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence["late_pose_core_reselection"] = diagnostic
        candidate["evidence"] = evidence
        _append_warning(candidate, "tal_candidate_late_pose_core_reselected")
    return window, takeoff, apex, landing, apex_index, diagnostic


def _reselect_from_noncompressed_motion_window(
    detections: list[tuple[tuple[int, int] | None, dict[str, Any], dict[str, Any], dict[str, Any], int | None]],
    signals: list[_FrameSignal],
) -> tuple[int, set[str]] | None:
    if len(detections) < 2:
        return None

    current_window, current_takeoff, current_apex, current_landing, _ = detections[0]
    if current_window is None:
        return None
    current_flags = _window_candidate_issue_flags(current_takeoff, current_apex, current_landing)
    if not _compressed_weak_window_should_reselect(current_takeoff, current_apex, current_landing, current_flags):
        return None
    current_score = _window_candidate_reselection_score(current_takeoff, current_apex, current_landing, current_flags)

    alternatives: list[tuple[float, int, set[str]]] = []
    for index, (window, takeoff, apex, landing, _) in enumerate(detections[1:], start=1):
        if _early_alternative_needs_stronger_motion_support(signals, current_window, window):
            continue
        if not _candidate_triplet_is_ordered(takeoff, apex, landing):
            continue
        flags = _window_candidate_issue_flags(takeoff, apex, landing)
        if "tal_candidate_apex_geometry_weak" in flags or "tal_candidate_core_gap_compressed" in flags:
            continue
        if _candidate_average_confidence((takeoff, apex, landing)) < COMPRESSED_WEAK_WINDOW_RESELECT_MIN_ALTERNATIVE_CONFIDENCE:
            continue
        score = _window_candidate_reselection_score(takeoff, apex, landing, flags)
        if score <= current_score + 0.10:
            continue
        alternatives.append((score, index, flags))

    if not alternatives:
        return None
    _, selected_index, selected_flags = max(alternatives, key=lambda item: (item[0], -item[1]))
    return selected_index, selected_flags


def _motion_bounded_unclear_apex_index(
    signals: list[_FrameSignal],
    smoothed_com: list[float | None],
    motion_norm: list[float] | None,
    valid: list[tuple[int, float]],
    search_window: tuple[int, int] | None,
) -> int | None:
    if (
        search_window is None
        or search_window[0] <= 0
        or motion_norm is None
        or len(motion_norm) != len(signals)
        or len(valid) < 3
    ):
        return None
    window_size = search_window[1] - search_window[0] + 1
    if window_size / max(len(signals), 1) > 0.75:
        return None
    valid_indices = {index for index, _ in valid}
    motion_items = [
        (index, motion_norm[index])
        for index in valid_indices
        if 0 <= index < len(motion_norm) and motion_norm[index] > 0.0
    ]
    if len(motion_items) < 2:
        return None

    peak_index, peak_motion = max(
        motion_items,
        key=lambda item: (item[1], -abs(item[0] - (search_window[0] if search_window else item[0]))),
    )
    if peak_motion < APEX_UNCLEAR_MOTION_MIN_PEAK:
        return None
    peak_ts = signals[peak_index].timestamp
    window_values = [value for _, value in valid]
    window_low = min(window_values)
    window_high = max(window_values)
    vertical_range = max(window_high - window_low, 1e-9)

    candidates: list[tuple[float, int]] = []
    for index, value in valid:
        if index <= 0 or index >= len(signals) - 1:
            continue
        dt = signals[index].timestamp - peak_ts
        if dt < -APEX_UNCLEAR_PRE_PEAK_SEC or dt > APEX_UNCLEAR_POST_PEAK_SEC:
            continue
        motion_score = motion_norm[index] / max(peak_motion, 1e-9)
        if motion_score < APEX_UNCLEAR_MOTION_MIN_RATIO:
            continue
        height_score = _clamp((window_high - value) / vertical_range)
        timing_score = _clamp(
            1.0 - abs(dt - APEX_UNCLEAR_TARGET_AFTER_PEAK_SEC) / max(APEX_UNCLEAR_POST_PEAK_SEC, 1e-9)
        )
        score = 0.40 * motion_score + 0.34 * timing_score + 0.26 * height_score
        candidates.append((score, index))

    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], -abs(signals[item[1]].timestamp - peak_ts), -item[1]))[1]


def _detect_apex(
    signals: list[_FrameSignal],
    smoothed_com: list[float | None],
    search_window: tuple[int, int] | None = None,
    motion_norm: list[float] | None = None,
) -> dict[str, Any]:
    valid = [
        (index, value)
        for index, value in enumerate(smoothed_com)
        if value is not None and _in_search_window(index, search_window)
    ]
    if len(valid) < 3:
        return _empty_candidate(["insufficient_com_signal"])

    raw_values = [signal.com_y for signal in signals if signal.com_y is not None]
    vertical_range = max(raw_values) - min(raw_values) if raw_values else 0.0
    prominence_floor = max(0.006, vertical_range * 0.10)
    local_minima: list[tuple[int, float, float, bool]] = []
    for index, value in valid:
        previous_values = [item for item in smoothed_com[max(0, index - 2) : index] if item is not None]
        next_values = [item for item in smoothed_com[index + 1 : index + 3] if item is not None]
        if not previous_values or not next_values:
            continue
        left_drop = min(previous_values) - value
        right_drop = min(next_values) - value
        surrounding = previous_values + next_values
        local_prominence = (sum(surrounding) / len(surrounding)) - value
        trajectory_score = min(
            _clamp((max(previous_values) - value) / max(vertical_range, 1e-9)),
            _clamp((max(next_values) - value) / max(vertical_range, 1e-9)),
        )
        motion_score = (
            motion_norm[index]
            if motion_norm is not None and 0 <= index < len(motion_norm)
            else 0.0
        )
        strict_minimum = local_prominence >= prominence_floor
        motion_supported_plateau_minimum = (
            local_prominence >= APEX_MOTION_SUPPORTED_LOCAL_MIN_PROMINENCE_FLOOR
            and motion_score >= APEX_MOTION_SUPPORTED_LOCAL_MIN_MIN_MOTION
            and trajectory_score >= APEX_MOTION_SUPPORTED_LOCAL_MIN_MIN_TRAJECTORY
        )
        if left_drop >= -1e-9 and right_drop >= -1e-9 and (strict_minimum or motion_supported_plateau_minimum):
            prominence_score = _clamp(local_prominence / max(prominence_floor, 1e-9))
            local_minima.append((index, prominence_score, trajectory_score, not strict_minimum))

    used_motion_bounded_fallback = False
    used_motion_supported_plateau_minimum = False
    if local_minima:
        selected_minimum = max(
            local_minima,
            key=lambda item: (item[1] * 0.65 + item[2] * 0.35, -(smoothed_com[item[0]] or 0.0)),
        )
        apex_index = selected_minimum[0]
        used_motion_supported_plateau_minimum = selected_minimum[3]
    else:
        inner_valid = [
            (index, value)
            for index, value in valid
            if 0 < index < len(smoothed_com) - 1
            and (
                search_window is None
                or search_window[0] < index < search_window[1]
                or len(valid) <= 3
            )
        ]
        motion_bounded_index = _motion_bounded_unclear_apex_index(
            signals,
            smoothed_com,
            motion_norm,
            inner_valid or valid,
            search_window,
        )
        if motion_bounded_index is not None:
            apex_index = motion_bounded_index
            used_motion_bounded_fallback = True
        else:
            apex_index = min(inner_valid or valid, key=lambda item: item[1])[0]

    left_values = _window_values(smoothed_com, apex_index, 4, 0)[:-1]
    right_values = _window_values(smoothed_com, apex_index, 0, 4)[1:]
    surrounding = left_values[-2:] + right_values[:2]
    local_prominence = (sum(surrounding) / len(surrounding) - (smoothed_com[apex_index] or 0.0)) if surrounding else 0.0
    ascent_support = _clamp((max(left_values) - (smoothed_com[apex_index] or 0.0)) / max(vertical_range, 1e-9)) if left_values else 0.0
    descent_support = _clamp((max(right_values) - (smoothed_com[apex_index] or 0.0)) / max(vertical_range, 1e-9)) if right_values else 0.0
    trajectory_score = min(ascent_support, descent_support)
    warnings: list[str] = []
    motion_score = 0.0 if signals[apex_index].motion_score is None else 0.5
    com_score = (
        0.40 * _clamp(vertical_range / 0.08)
        + 0.35 * _clamp(local_prominence / max(prominence_floor, 0.012))
        + 0.25 * trajectory_score
    )
    confidence = calculate_key_frame_confidence(
        motion_peak_score=motion_score,
        com_velocity_score=com_score,
        pose_visibility_score=signals[apex_index].visibility_score,
        knee_angle_change_score=None,
        phase_order_score=1.0,
        warnings=warnings,
    )
    if not local_minima:
        warnings.append("apex_local_minimum_not_clear")
    if used_motion_bounded_fallback:
        warnings.append("apex_motion_bounded_unclear_fallback")
    if used_motion_supported_plateau_minimum:
        warnings.append("apex_motion_supported_low_prominence_minimum")
    if apex_index == 0 or apex_index == len(signals) - 1:
        warnings.append("apex_at_signal_edge")
    if vertical_range < 0.025:
        warnings.append("com_vertical_range_low")
    return _candidate(
        signals[apex_index],
        confidence,
        {
            "com_y": signals[apex_index].com_y,
            "hip_y": signals[apex_index].hip_y,
            "smoothed_com_y": round(smoothed_com[apex_index], 5) if smoothed_com[apex_index] is not None else None,
            "vertical_range": round(vertical_range, 5),
            "local_prominence": round(local_prominence, 5),
            "local_minimum": any(item[0] == apex_index for item in local_minima),
            "motion_supported_low_prominence_minimum": used_motion_supported_plateau_minimum,
            "motion_bounded_unclear_apex": used_motion_bounded_fallback,
            "ascent_support": round(ascent_support, 3),
            "descent_support": round(descent_support, 3),
            "signal_index": apex_index,
            "score_components": {
                "motion_peak": round(motion_score, 3),
                "com_velocity": round(com_score, 3),
                "pose_visibility": round(signals[apex_index].visibility_score, 3),
                "knee_angle_change": None,
                "phase_order": 1.0,
            },
        },
        warnings,
    )


def _takeoff_timing_score_from_gap(apex_gap_sec: float) -> float:
    if 0.12 <= apex_gap_sec <= 0.55:
        return 1.0
    if apex_gap_sec < 0.12:
        return _clamp(apex_gap_sec / 0.12)
    return _clamp(1.0 - (apex_gap_sec - 0.55) / 0.55)


def _sparse_prepeak_estimated_takeoff(
    signals: list[_FrameSignal],
    motion_norm: list[float],
    takeoff: dict[str, Any],
    apex_index: int | None,
    search_window: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    takeoff_index = _candidate_index(takeoff)
    if apex_index is None or takeoff_index is None or takeoff_index <= 0 or takeoff_index >= len(signals):
        return None
    if len(motion_norm) != len(signals):
        return None
    if search_window is not None and takeoff_index - search_window[0] > 1:
        return None

    takeoff_ts = _to_float(takeoff.get("timestamp"))
    apex_ts = signals[apex_index].timestamp
    if takeoff_ts is None:
        return None
    apex_gap_sec = apex_ts - takeoff_ts
    if apex_gap_sec < 0.0 or apex_gap_sec > SPARSE_PREPEAK_TAKEOFF_COMPRESSED_APEX_GAP_SEC:
        return None

    cluster_start_index = takeoff_index
    while (
        cluster_start_index > 0
        and signals[cluster_start_index].motion_score is not None
        and signals[cluster_start_index - 1].motion_score is not None
        and signals[cluster_start_index].timestamp - signals[cluster_start_index - 1].timestamp
        <= SPARSE_PREPEAK_TAKEOFF_MIN_SHIFT_SEC
    ):
        cluster_start_index -= 1

    previous_index = next(
        (
            index
            for index in range(cluster_start_index - 1, -1, -1)
            if signals[index].motion_score is not None and signals[index].timestamp < takeoff_ts
        ),
        None,
    )
    if previous_index is None:
        return None
    previous_signal = signals[previous_index]
    cluster_start_signal = signals[cluster_start_index]
    signal_gap_sec = cluster_start_signal.timestamp - previous_signal.timestamp
    if signal_gap_sec < SPARSE_PREPEAK_TAKEOFF_MIN_SIGNAL_GAP_SEC:
        return None

    selected_motion = motion_norm[takeoff_index]
    previous_motion = motion_norm[previous_index]
    if selected_motion < SPARSE_PREPEAK_TAKEOFF_MIN_SELECTED_MOTION:
        return None
    if previous_motion > selected_motion * SPARSE_PREPEAK_TAKEOFF_MAX_PREVIOUS_MOTION_RATIO:
        return None

    evidence = takeoff.get("evidence") if isinstance(takeoff.get("evidence"), dict) else {}
    components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
    com_ascent = _to_float(components.get("com_ascent")) or 0.0
    takeoff_event = _to_float(components.get("takeoff_event")) or 0.0
    if (
        com_ascent < SPARSE_PREPEAK_TAKEOFF_MIN_SELECTED_COM_ASCENT
        and takeoff_event < SPARSE_PREPEAK_TAKEOFF_MIN_SELECTED_EVENT
    ):
        return None

    lower_bound = previous_signal.timestamp + SPARSE_PREPEAK_TAKEOFF_MIN_SHIFT_SEC
    upper_bound = takeoff_ts - SPARSE_PREPEAK_TAKEOFF_MIN_SHIFT_SEC
    if lower_bound >= upper_bound:
        return None
    estimated_ts = apex_ts - SPARSE_PREPEAK_TAKEOFF_TARGET_APEX_LEAD_SEC
    estimated_ts = max(lower_bound, min(upper_bound, estimated_ts))
    if not (previous_signal.timestamp < estimated_ts < takeoff_ts):
        return None

    refined = copy.deepcopy(takeoff)
    refined["timestamp"] = round(estimated_ts, 3)
    refined_evidence = refined.get("evidence") if isinstance(refined.get("evidence"), dict) else {}
    refined_components = (
        dict(refined_evidence.get("score_components"))
        if isinstance(refined_evidence.get("score_components"), dict)
        else {}
    )
    estimated_apex_gap = apex_ts - estimated_ts
    refined_components["takeoff_timing"] = round(_takeoff_timing_score_from_gap(estimated_apex_gap), 3)
    refined_evidence["score_components"] = refined_components
    refined_evidence["apex_gap_sec"] = round(estimated_apex_gap, 3)
    refined_evidence["estimated_timestamp_sec"] = round(estimated_ts, 3)
    refined_evidence["timestamp_estimate_offset_from_nearest_record_sec"] = round(estimated_ts - takeoff_ts, 3)
    refined_evidence["sparse_prepeak_takeoff_estimate"] = {
        "original_timestamp": round(takeoff_ts, 3),
        "estimated_timestamp": round(estimated_ts, 3),
        "apex_timestamp": round(apex_ts, 3),
        "original_apex_gap_sec": round(apex_gap_sec, 3),
        "estimated_apex_gap_sec": round(estimated_apex_gap, 3),
        "previous_timestamp": round(previous_signal.timestamp, 3),
        "cluster_start_timestamp": round(cluster_start_signal.timestamp, 3),
        "previous_motion_norm": round(previous_motion, 3),
        "selected_motion_norm": round(selected_motion, 3),
        "signal_gap_sec": round(signal_gap_sec, 3),
        "target_apex_lead_sec": SPARSE_PREPEAK_TAKEOFF_TARGET_APEX_LEAD_SEC,
    }
    refined["evidence"] = refined_evidence
    _cap_candidate_confidence(
        refined,
        SPARSE_PREPEAK_TAKEOFF_CONFIDENCE_CAP,
        "takeoff_sparse_prepeak_estimated",
    )
    _append_warning(refined, "t_pose_signal_sparse")
    return refined


def _detect_takeoff(
    signals: list[_FrameSignal],
    smoothed_com: list[float | None],
    smoothed_knee: list[float | None],
    motion_norm: list[float],
    apex_index: int | None,
    search_window: tuple[int, int] | None = None,
    *,
    apex_reliable: bool = True,
) -> dict[str, Any]:
    if apex_index is None or apex_index <= 0:
        return _empty_candidate(["takeoff_window_missing"])

    scored: list[tuple[float, float, float, float, float, float, int, dict[str, Any], list[str]]] = []
    start_index = max(1, search_window[0] if search_window is not None else 1)
    for index in range(start_index, apex_index):
        current_knee = smoothed_knee[index]
        current_com = smoothed_com[index]
        if current_knee is None and current_com is None:
            continue

        previous_knees = _window_values(smoothed_knee, index, 2, 0)[:-1]
        current_knees = _window_values(smoothed_knee, index, 0, 1)
        knee_extension = (
            max(0.0, max(current_knees) - min(previous_knees))
            if previous_knees and current_knees
            else 0.0
        )
        previous_com = _window_average(smoothed_com, index, 2, 0)
        next_com_values = _window_values(smoothed_com, index, 0, 2)
        next_com = min(next_com_values) if next_com_values else None
        com_ascent = max(0.0, previous_com - next_com) if previous_com is not None and next_com is not None else 0.0

        extension_score = _clamp(knee_extension / 25.0)
        ascent_score = _clamp(com_ascent / 0.035)
        apex_gap_sec = max(0.0, signals[apex_index].timestamp - signals[index].timestamp)
        timing_score = _takeoff_timing_score_from_gap(apex_gap_sec)
        warnings: list[str] = []
        score = calculate_key_frame_confidence(
            motion_peak_score=motion_norm[index],
            com_velocity_score=ascent_score,
            pose_visibility_score=signals[index].visibility_score,
            knee_angle_change_score=extension_score,
            phase_order_score=1.0,
            warnings=warnings,
        )
        if extension_score < 0.25:
            warnings.append("knee_extension_weak")
        if ascent_score < 0.25:
            warnings.append("com_ascent_weak")
        if timing_score < 0.50:
            warnings.append("takeoff_timing_window_weak")
        joint_extension_ascent = math.sqrt(max(extension_score, 0.0) * max(ascent_score, 0.0))
        combined_event_score = (
            0.34 * extension_score
            + 0.34 * ascent_score
            + 0.16 * joint_extension_ascent
            + 0.08 * motion_norm[index]
            + 0.08 * timing_score
        )
        legacy_event_score = 0.42 * extension_score + 0.38 * ascent_score + 0.12 * motion_norm[index] + 0.08 * timing_score
        evidence = {
            "knee_extension_deg": round(knee_extension, 3),
            "com_ascent_delta": round(com_ascent, 5),
            "apex_gap_sec": round(apex_gap_sec, 3),
            "motion_peak_score": round(motion_norm[index], 3),
            "signal_index": index,
            "score_components": {
                "motion_peak": round(motion_norm[index], 3),
                "com_velocity": round(ascent_score, 3),
                "pose_visibility": round(signals[index].visibility_score, 3),
                "knee_angle_change": round(extension_score, 3),
                "phase_order": 1.0,
                "knee_extension": round(extension_score, 3),
                "com_ascent": round(ascent_score, 3),
                "takeoff_timing": round(timing_score, 3),
                "takeoff_joint_extension_ascent": round(joint_extension_ascent, 3),
                "takeoff_legacy_event": round(legacy_event_score, 3),
                "takeoff_event": round(combined_event_score, 3),
            },
        }
        legacy_score = _legacy_takeoff_rank_confidence(
            motion_norm[index],
            ascent_score,
            signals[index].visibility_score,
            extension_score,
            1.0,
        )
        legacy_rank_score = legacy_score + legacy_event_score * 0.08
        recency_score = _clamp(1.0 - max(0.0, apex_gap_sec - 0.55) / 2.20)
        if apex_reliable:
            rank_score = (
                0.55 * score
                + 0.24 * combined_event_score
                + 0.16 * timing_score
                + 0.20 * recency_score * max(joint_extension_ascent, 0.35)
                + 0.06 * joint_extension_ascent
                + 0.03 * motion_norm[index]
            )
        else:
            joint_timing = max(joint_extension_ascent, 0.0) * max(timing_score, 0.0)
            geometry_timing = joint_timing
            if geometry_timing < TAKEOFF_UNCLEAR_APEX_MIN_JOINT_TIMING:
                low_geometry_penalty = _clamp(
                    geometry_timing / max(TAKEOFF_UNCLEAR_APEX_MIN_JOINT_TIMING, 1e-9),
                    high=1.0,
                )
            else:
                low_geometry_penalty = 1.0
            rank_score = (
                0.30 * legacy_rank_score
                + 0.26 * score
                + 0.26 * combined_event_score
                + 0.22 * timing_score
                + 0.24 * geometry_timing
                + 0.03 * motion_norm[index]
            ) * low_geometry_penalty
        timing_rank_score = score * (0.55 + 0.45 * timing_score) + combined_event_score * 0.22 + timing_score * 0.18
        evidence["score_components"]["takeoff_rank"] = round(rank_score, 3)
        evidence["score_components"]["takeoff_legacy_confidence"] = round(legacy_score, 3)
        evidence["score_components"]["takeoff_legacy_rank"] = round(legacy_rank_score, 3)
        evidence["score_components"]["takeoff_timing_rank"] = round(timing_rank_score, 3)
        if not apex_reliable:
            evidence["score_components"]["takeoff_unclear_apex_geometry_timing"] = round(geometry_timing, 3)
            evidence["score_components"]["takeoff_unclear_apex_geometry_penalty"] = round(low_geometry_penalty, 3)
        scored.append((rank_score, score, combined_event_score, timing_score, motion_norm[index], extension_score + ascent_score, index, evidence, warnings))

    if not scored:
        return _empty_candidate(["takeoff_signal_missing"])

    rank_score, score, _, _, _, _, index, evidence, warnings = max(
        scored,
        key=lambda item: (
            item[0],
            item[7]["score_components"]["takeoff_legacy_rank"],
            item[6],
        ),
    )
    legacy_best = max(scored, key=lambda item: (item[7]["score_components"]["takeoff_legacy_rank"], item[6]))
    original_rank_score = legacy_best[7]["score_components"]["takeoff_legacy_rank"]
    original_index = legacy_best[6]
    apex_ts = signals[apex_index].timestamp
    selected_gap_sec = apex_ts - signals[original_index].timestamp
    allow_late_reselection = apex_reliable or selected_gap_sec <= TAKEOFF_UNCLEAR_APEX_SHORT_RESELECT_MAX_GAP_SEC
    if allow_late_reselection and selected_gap_sec > TAKEOFF_EARLY_APEX_GAP_SEC:
        original_signal = signals[original_index]
        original_candidate_payload = {
            "frame_id": original_signal.frame_id,
            "timestamp": round(original_signal.timestamp, 3),
            "confidence": round(score, 3),
            "evidence": dict(evidence),
            "warnings": list(warnings),
        }
        late_candidates = [
            item
            for item in scored
            if item[6] > original_index
            and signals[item[6]].timestamp - signals[original_index].timestamp >= TAKEOFF_LATE_PLAUSIBLE_MIN_SHIFT_SEC
            and TAKEOFF_LATE_PLAUSIBLE_MIN_APEX_GAP_SEC
            <= apex_ts - signals[item[6]].timestamp
            <= TAKEOFF_LATE_PLAUSIBLE_MAX_APEX_GAP_SEC
            and item[3] >= TAKEOFF_LATE_PLAUSIBLE_MIN_TIMING
            and item[4] >= TAKEOFF_LATE_PLAUSIBLE_MIN_MOTION
            and item[5] >= TAKEOFF_LATE_PLAUSIBLE_MIN_GEOMETRY
            and item[7]["score_components"]["knee_extension"] >= TAKEOFF_LATE_PLAUSIBLE_MIN_EXTENSION
            and item[2] >= TAKEOFF_LATE_PLAUSIBLE_MIN_EVENT
            and item[1] >= TAKEOFF_LATE_PLAUSIBLE_MIN_CONFIDENCE
            and (
                item[0] >= rank_score * TAKEOFF_LATE_PLAUSIBLE_MIN_RANK_RATIO
                or item[7]["score_components"]["takeoff_timing_rank"]
                >= evidence["score_components"]["takeoff_timing_rank"] * TAKEOFF_LATE_PLAUSIBLE_MIN_RANK_RATIO
            )
        ]
        if late_candidates:
            rank_score, score, _, _, _, _, index, evidence, warnings = max(
                late_candidates,
                key=lambda item: (item[3], item[0], item[6]),
            )
            evidence["takeoff_late_plausible_reselection"] = {
                "original_timestamp": round(signals[original_index].timestamp, 3),
                "original_apex_gap_sec": round(selected_gap_sec, 3),
                "original_rank_score": round(original_rank_score, 3),
                "reselected_apex_gap_sec": round(apex_ts - signals[index].timestamp, 3),
                "original_candidate": original_candidate_payload,
            }
            warnings = [warning for warning in warnings if warning != "takeoff_timing_window_weak"]
            warnings.append("takeoff_reselected_from_late_plausible_candidate")
    elif allow_late_reselection and index != original_index and original_index < index:
        gap_sec = apex_ts - signals[index].timestamp
        original_signal = signals[original_index]
        original_candidate_payload = {
            "frame_id": original_signal.frame_id,
            "timestamp": round(original_signal.timestamp, 3),
            "confidence": round(score, 3),
            "evidence": dict(evidence),
            "warnings": list(warnings),
        }
        evidence["takeoff_late_plausible_reselection"] = {
            "original_timestamp": round(signals[original_index].timestamp, 3),
            "original_apex_gap_sec": round(apex_ts - signals[original_index].timestamp, 3),
            "original_rank_score": round(original_rank_score, 3),
            "reselected_apex_gap_sec": round(gap_sec, 3),
            "original_candidate": original_candidate_payload,
        }
        if "takeoff_timing_window_weak" not in warnings and gap_sec <= TAKEOFF_LATE_PLAUSIBLE_MAX_APEX_GAP_SEC:
            warnings.append("takeoff_reselected_from_late_plausible_candidate")
    sparse_prepeak_takeoff = _sparse_prepeak_estimated_takeoff(
        signals,
        motion_norm,
        _candidate(signals[index], score, evidence, warnings),
        apex_index,
        search_window,
    )
    if sparse_prepeak_takeoff is not None:
        return sparse_prepeak_takeoff
    if score < 0.35:
        warnings.append("takeoff_confidence_low")
    return _candidate(signals[index], score, evidence, warnings)


def _detect_landing(
    signals: list[_FrameSignal],
    smoothed_com: list[float | None],
    smoothed_ankle: list[float | None],
    smoothed_knee: list[float | None],
    motion_norm: list[float],
    apex_index: int | None,
    search_window: tuple[int, int] | None = None,
) -> dict[str, Any]:
    if apex_index is None or apex_index >= len(signals) - 1:
        return _empty_candidate(["landing_window_missing"])

    scored: list[tuple[float, float, int, dict[str, Any], list[str]]] = []
    end_index = min(len(signals) - 1, search_window[1] if search_window is not None else len(signals) - 1)
    for index in range(apex_index + 1, end_index + 1):
        current_ankle = smoothed_ankle[index]
        current_knee = smoothed_knee[index]
        current_com = smoothed_com[index]
        if current_ankle is None and current_knee is None and current_com is None:
            continue

        previous_ankle = _window_average(smoothed_ankle, index, 2, 0)
        next_ankle_values = _window_values(smoothed_ankle, index, 0, 1)
        next_ankle = max(next_ankle_values) if next_ankle_values else None
        ankle_return = max(0.0, next_ankle - previous_ankle) if next_ankle is not None and previous_ankle is not None else 0.0
        previous_knees = _window_values(smoothed_knee, index, 2, 0)
        current_knees = _window_values(smoothed_knee, index, 0, 1)
        knee_absorption = (
            max(0.0, max(previous_knees) - min(current_knees))
            if previous_knees and current_knees
            else 0.0
        )
        previous_com = _window_average(smoothed_com, index, 2, 0)
        next_com_values = _window_values(smoothed_com, index, 0, 2)
        next_com = max(next_com_values) if next_com_values else None
        com_descent = max(0.0, next_com - previous_com) if previous_com is not None and next_com is not None else 0.0

        ankle_score = _clamp(ankle_return / 0.035)
        knee_score = _clamp(knee_absorption / 22.0)
        descent_score = _clamp(com_descent / 0.035)
        com_velocity_score = 0.65 * ankle_score + 0.35 * descent_score
        apex_gap_sec = max(0.0, signals[index].timestamp - signals[apex_index].timestamp)
        if 0.12 <= apex_gap_sec <= 0.75:
            timing_score = 1.0
        elif apex_gap_sec < 0.12:
            timing_score = _clamp(apex_gap_sec / 0.12)
        else:
            timing_score = _clamp(1.0 - (apex_gap_sec - 0.75) / 0.75)
        contact_score = (
            0.34 * ankle_score
            + 0.30 * knee_score
            + 0.24 * descent_score
            + 0.08 * motion_norm[index]
            + 0.04 * timing_score
        )
        warnings: list[str] = []
        score = calculate_key_frame_confidence(
            motion_peak_score=motion_norm[index],
            com_velocity_score=com_velocity_score,
            pose_visibility_score=signals[index].visibility_score,
            knee_angle_change_score=knee_score,
            phase_order_score=1.0,
            warnings=warnings,
        )
        if ankle_score < 0.25:
            warnings.append("ankle_return_weak")
        if knee_score < 0.25:
            warnings.append("knee_absorption_weak")
        if descent_score < 0.25:
            warnings.append("com_descent_weak")
        if timing_score < 0.50:
            warnings.append("landing_timing_window_weak")
        evidence = {
            "ankle_return_delta": round(ankle_return, 5),
            "knee_absorption_deg": round(knee_absorption, 3),
            "com_descent_delta": round(com_descent, 5),
            "apex_gap_sec": round(apex_gap_sec, 3),
            "motion_peak_score": round(motion_norm[index], 3),
            "signal_index": index,
            "score_components": {
                "motion_peak": round(motion_norm[index], 3),
                "com_velocity": round(com_velocity_score, 3),
                "pose_visibility": round(signals[index].visibility_score, 3),
                "knee_angle_change": round(knee_score, 3),
                "phase_order": 1.0,
                "ankle_return": round(ankle_score, 3),
                "knee_absorption": round(knee_score, 3),
                "com_descent": round(descent_score, 3),
                "landing_timing": round(timing_score, 3),
                "landing_contact": round(contact_score, 3),
            },
        }
        scored.append((score, contact_score, index, evidence, warnings))

    if not scored:
        return _empty_candidate(["landing_signal_missing"])

    strong_contact = [
        item
        for item in scored
        if item[1] >= 0.48
        and item[3]["apex_gap_sec"] >= LANDING_STRONG_CONTACT_MIN_APEX_GAP_SEC
        and (
            item[3]["score_components"]["knee_absorption"] >= 0.25
            or item[3]["score_components"]["motion_peak"] >= 0.65
        )
    ]
    if strong_contact:
        score, _, index, evidence, warnings = max(strong_contact, key=lambda item: (-(item[2]), item[0]))
    elif (
        max(item[1] for item in scored) <= WEAK_LANDING_LATE_CONTACT_MAX
        and any(item[3]["score_components"]["landing_timing"] <= WEAK_LANDING_LATE_TIMING_MAX for item in scored)
    ):
        plausible_early = [
            item
            for item in scored
            if item[3]["score_components"]["landing_timing"] >= WEAK_LANDING_EARLY_TIMING_MIN
            and item[1] >= WEAK_LANDING_EARLY_CONTACT_MIN
        ]
        if plausible_early:
            score, _, index, evidence, warnings = max(
                plausible_early,
                key=lambda item: (
                    item[1],
                    item[3]["score_components"]["motion_peak"],
                    item[0],
                    -item[2],
                ),
            )
            warnings.append("landing_weak_contact_early_candidate_selected")
        else:
            score, _, index, evidence, warnings = max(scored, key=lambda item: (item[0] + item[1] * 0.08 - max(0, item[2] - apex_index) * 0.015, -item[2]))
    elif (
        max(item[1] for item in scored) <= WEAK_LANDING_FOOT_CONTACT_TOTAL_MAX
        and all(
            max(
                item[3]["score_components"]["ankle_return"],
                item[3]["score_components"]["com_descent"],
            )
            <= WEAK_LANDING_FOOT_CONTACT_MAX
            for item in scored
        )
    ):
        plausible_early_motion = [
            item
            for item in scored
            if 0.12 <= item[3]["apex_gap_sec"] <= 0.75
            and item[3]["score_components"]["motion_peak"] >= WEAK_LANDING_EARLY_MOTION_MIN
        ]
        if plausible_early_motion:
            score, _, index, evidence, warnings = max(
                plausible_early_motion,
                key=lambda item: (
                    item[3]["score_components"]["motion_peak"],
                    item[3]["score_components"]["landing_timing"],
                    -item[2],
                ),
            )
            warnings.append("landing_weak_foot_contact_motion_supported_early_candidate_selected")
        else:
            plausible_early = [
                item
                for item in scored
                if 0.12 <= item[3]["apex_gap_sec"] <= 0.85
            ]
            if plausible_early and all(item[1] <= WEAK_LANDING_CONTACT_EARLY_SELECTION_MAX for item in scored):
                score, _, index, evidence, warnings = max(
                    plausible_early,
                    key=lambda item: (item[1], item[3]["score_components"]["motion_peak"], -item[2]),
                )
                warnings.append("landing_weak_contact_early_candidate_selected")
            else:
                score, _, index, evidence, warnings = max(scored, key=lambda item: (item[0] + item[1] * 0.08 - max(0, item[2] - apex_index) * 0.015, -item[2]))
    elif all(item[1] <= WEAK_LANDING_CONTACT_EARLY_SELECTION_MAX for item in scored):
        plausible_early = [
            item
            for item in scored
            if 0.12 <= item[3]["apex_gap_sec"] <= 0.85
        ]
        if plausible_early:
            score, _, index, evidence, warnings = max(
                plausible_early,
                key=lambda item: (item[1], item[3]["score_components"]["motion_peak"], -item[2]),
            )
            warnings.append("landing_weak_contact_early_candidate_selected")
        else:
            score, _, index, evidence, warnings = max(scored, key=lambda item: (item[0] + item[1] * 0.08 - max(0, item[2] - apex_index) * 0.015, -item[2]))
    else:
        score, _, index, evidence, warnings = max(scored, key=lambda item: (item[0] + item[1] * 0.08 - max(0, item[2] - apex_index) * 0.015, -item[2]))
    selected_item = next((item for item in scored if item[2] == index), None)
    if selected_item is not None:
        score, _, index, evidence, warnings = _reselect_compressed_landing_candidate(scored, selected_item)
    if score < 0.35:
        warnings.append("landing_confidence_low")
    return _candidate(signals[index], score, evidence, warnings)


def _candidate_index(candidate: dict[str, Any]) -> int | None:
    evidence = candidate.get("evidence")
    if not isinstance(evidence, dict):
        return None
    signal_value = evidence.get("signal_index")
    if isinstance(signal_value, int):
        return signal_value
    value = evidence.get("pose_index")
    return int(value) if isinstance(value, int) else None


def _candidate_pose_index(candidate: dict[str, Any]) -> int | None:
    evidence = candidate.get("evidence")
    if not isinstance(evidence, dict):
        return None
    value = evidence.get("pose_index")
    return int(value) if isinstance(value, int) else None


def _apply_ordered_confidence_floor(candidates: Iterable[dict[str, Any]]) -> None:
    for candidate in candidates:
        confidence = _to_float(candidate.get("confidence"))
        if confidence is None or confidence >= ORDERED_TAL_CONFIDENCE_FLOOR:
            continue
        candidate_warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
        if "keyframe_candidates_motion_fallback_unreliable_pose_state" in candidate_warnings:
            continue
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        visibility = _to_float(evidence.get("visibility_score"))
        has_visible_ordered_candidate = (
            bool(candidate.get("frame_id"))
            and confidence >= ORDERED_TAL_LOW_CONFIDENCE_MIN_RAW
            and visibility is not None
            and visibility >= MIN_VISIBILITY
        )
        is_visible_landing_candidate = (
            bool(candidate.get("frame_id"))
            and visibility is not None
            and visibility >= MIN_VISIBILITY
            and any(str(warning).startswith(("ankle_return_", "knee_absorption_", "com_descent_", "landing_")) for warning in candidate_warnings)
        )
        if confidence < 0.30 and not has_visible_ordered_candidate and not is_visible_landing_candidate:
            continue
        candidate["confidence"] = ORDERED_TAL_CONFIDENCE_FLOOR
        warnings = candidate.get("warnings")
        if not isinstance(warnings, list):
            warnings = []
            candidate["warnings"] = warnings
        warnings.append("confidence_floor_from_ordered_tal")


def detect_key_frame_candidates(
    pose_data: dict[str, Any] | None,
    motion_scores: dict[str, Any] | None,
    analysis_profile: str,
    effective_fps: float,
) -> dict[str, Any]:
    """Detect jump takeoff, apex, and landing candidate frames.

    Args:
        pose_data: Pose payload with ``frames[*].keypoints``.
        motion_scores: Sampling payload containing ``selected`` and/or ``scores``.
        analysis_profile: Normalized profile. Only ``jump`` is detected.
        effective_fps: Sampling rate on the real action timeline.

    Returns:
        ``{"T": candidate, "A": candidate, "L": candidate, "quality_flags": []}``.
        Candidates always contain ``frame_id``, ``timestamp``, ``confidence``,
        ``evidence``, and ``warnings``. Missing signals are represented by
        ``frame_id=None`` with warnings.
    """
    quality_flags: list[str] = []

    if (analysis_profile or "").strip().lower() != "jump":
        warning = "keyframe_candidates_not_applicable_for_profile"
        return {
            "T": _empty_candidate([warning]),
            "A": _empty_candidate([warning]),
            "L": _empty_candidate([warning]),
            "quality_flags": [warning],
        }

    if not isinstance(pose_data, dict) or not isinstance(pose_data.get("frames"), list) or not pose_data.get("frames"):
        warning = "keyframe_candidates_missing_pose"
        return {
            "T": _empty_candidate([warning]),
            "A": _empty_candidate([warning]),
            "L": _empty_candidate([warning]),
            "quality_flags": [warning],
        }

    fps = _valid_effective_fps(effective_fps)
    excluded_counts = _excluded_pose_frame_counts(pose_data)
    if excluded_counts:
        quality_flags.append("keyframe_candidates_excluded_unreliable_pose_frames")
    frame_states = _pose_frame_state_by_frame(pose_data)
    signals = _build_signals(pose_data, motion_scores, fps)
    if not signals:
        fallback = _motion_fallback_candidates(
            motion_scores,
            fps,
            quality_flags + ["keyframe_candidates_insufficient_pose"],
            frame_states=frame_states,
            pose_data=pose_data,
        )
        if fallback is not None:
            fallback["excluded_pose_frames"] = excluded_counts
            return fallback
        warning = "keyframe_candidates_missing_pose"
        return {
            "T": _empty_candidate([warning]),
            "A": _empty_candidate([warning]),
            "L": _empty_candidate([warning]),
            "quality_flags": [warning],
        }

    valid_pose_count = sum(1 for signal in signals if signal.com_y is not None or signal.knee_angle is not None or signal.ankle_y is not None)
    low_visibility_count = sum(1 for signal in signals if signal.visibility_score < MIN_VISIBILITY)
    if valid_pose_count < 3:
        quality_flags.append("keyframe_candidates_insufficient_pose")
    if low_visibility_count > len(signals) / 2:
        quality_flags.append("keyframe_candidates_low_visibility")
    reliable_time_bounds = _reliable_signal_time_bounds(signals)
    if valid_pose_count < 3:
        fallback = _motion_fallback_candidates(
            motion_scores,
            fps,
            quality_flags,
            time_bounds=reliable_time_bounds,
            frame_states=frame_states,
            pose_data=pose_data,
        )
        if fallback is not None:
            fallback["excluded_pose_frames"] = excluded_counts
            return fallback

    smoothed_com = _smooth([signal.com_y for signal in signals])
    smoothed_knee = _smooth([signal.knee_angle for signal in signals])
    smoothed_ankle = _smooth([signal.ankle_y for signal in signals])
    motion_norm = _normalized_motion(signals)
    search_windows = _motion_search_windows(signals)
    search_window: tuple[int, int] | None = search_windows[0] if search_windows else None
    rejected_tail_motion_windows: list[tuple[float, float]] = []

    def detect_for_window(window: tuple[int, int] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int | None]:
        current_apex = _detect_apex(signals, smoothed_com, window, motion_norm)
        current_apex_index = _candidate_index(current_apex)
        apex_evidence = current_apex.get("evidence") if isinstance(current_apex.get("evidence"), dict) else {}
        apex_warnings = current_apex.get("warnings") if isinstance(current_apex.get("warnings"), list) else []
        current_apex_reliable = (
            bool(apex_evidence.get("local_minimum"))
            or bool(apex_evidence.get("motion_bounded_unclear_apex"))
            or "apex_local_minimum_not_clear" not in apex_warnings
        )
        current_takeoff = _detect_takeoff(
            signals,
            smoothed_com,
            smoothed_knee,
            motion_norm,
            current_apex_index,
            window,
            apex_reliable=current_apex_reliable,
        )
        current_landing = _detect_landing(
            signals,
            smoothed_com,
            smoothed_ankle,
            smoothed_knee,
            motion_norm,
            current_apex_index,
            window,
        )
        return current_takeoff, current_apex, current_landing, current_apex_index

    takeoff, apex, landing, apex_index = detect_for_window(search_window)
    if _tail_motion_window_has_weak_geometry(signals, search_window, takeoff, apex, landing):
        quality_flags.append("keyframe_candidates_tail_motion_window_rejected")
        first_rejected_tail_window = search_window
        if search_window is not None:
            rejected_tail_motion_windows.append(_motion_window_time_bounds(signals, search_window))
        replacement_found = False
        for alternate_window in search_windows[1:]:
            alternate_takeoff, alternate_apex, alternate_landing, alternate_apex_index = detect_for_window(alternate_window)
            if _tail_motion_window_has_weak_geometry(
                signals,
                alternate_window,
                alternate_takeoff,
                alternate_apex,
                alternate_landing,
            ):
                rejected_tail_motion_windows.append(_motion_window_time_bounds(signals, alternate_window))
                continue
            search_window = alternate_window
            takeoff, apex, landing, apex_index = (
                alternate_takeoff,
                alternate_apex,
                alternate_landing,
                alternate_apex_index,
            )
            quality_flags.append("keyframe_candidates_tail_motion_window_reselected")
            replacement_found = True
            break
        if not replacement_found:
            search_window = None
            takeoff, apex, landing, apex_index = detect_for_window(search_window)
        else:
            late_pose_core = _late_pose_core_reselection(
                signals,
                first_rejected_tail_window,
                search_window,
                smoothed_com,
                smoothed_knee,
                smoothed_ankle,
                motion_norm,
                detect_for_window,
            )
            if late_pose_core is not None:
                search_window, takeoff, apex, landing, apex_index, late_pose_core_diagnostic = late_pose_core
                quality_flags.append("keyframe_candidates_late_pose_core_reselected")
    if search_window is not None and len(search_windows) > 1:
        window_detections = [(search_window, takeoff, apex, landing, apex_index)]
        for alternate_window in search_windows:
            if alternate_window == search_window:
                continue
            alternate_takeoff, alternate_apex, alternate_landing, alternate_apex_index = detect_for_window(alternate_window)
            if _tail_motion_window_has_weak_geometry(
                signals,
                alternate_window,
                alternate_takeoff,
                alternate_apex,
                alternate_landing,
            ):
                continue
            window_detections.append(
                (
                    alternate_window,
                    alternate_takeoff,
                    alternate_apex,
                    alternate_landing,
                    alternate_apex_index,
                )
            )
        reselected_window = _reselect_from_noncompressed_motion_window(window_detections, signals)
        if reselected_window is not None:
            selected_index, _ = reselected_window
            original_window = window_detections[0][0]
            search_window, takeoff, apex, landing, apex_index = window_detections[selected_index]
            quality_flags.append("keyframe_candidates_compressed_weak_motion_window_reselected")
            reselection_diagnostic = {
                "reason": "compressed_weak_window_reselected_to_noncompressed_motion_window",
                "original_window": _motion_window_payload(signals, original_window)
                if original_window is not None
                else None,
                "selected_window": _motion_window_payload(signals, search_window),
            }
            for candidate in (takeoff, apex, landing):
                evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
                evidence["compressed_weak_motion_window_reselection"] = reselection_diagnostic
                candidate["evidence"] = evidence
    if search_window is not None:
        window_payload = _motion_window_payload(signals, search_window)
        for candidate in (takeoff, apex, landing):
            evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
            evidence["motion_cluster_window"] = window_payload
            candidate["evidence"] = evidence

    t_index = _candidate_index(takeoff)
    a_index = _candidate_index(apex)
    l_index = _candidate_index(landing)
    takeoff_ts = _to_float(takeoff.get("timestamp"))
    apex_ts = _to_float(apex.get("timestamp"))
    landing_ts = _to_float(landing.get("timestamp"))
    apex_warnings = apex.get("warnings") if isinstance(apex.get("warnings"), list) else []
    takeoff_evidence = takeoff.get("evidence") if isinstance(takeoff.get("evidence"), dict) else {}
    landing_evidence = landing.get("evidence") if isinstance(landing.get("evidence"), dict) else {}
    landing_components = landing_evidence.get("score_components") if isinstance(landing_evidence.get("score_components"), dict) else {}
    landing_motion_component = _to_float(landing_components.get("motion_peak")) or 0.0
    landing_contact_component = _to_float(landing_components.get("landing_contact")) or 0.0
    landing_confidence = _to_float(landing.get("confidence")) or 0.0
    apex_gap_after_takeoff = (
        apex_ts - takeoff_ts
        if takeoff_ts is not None and apex_ts is not None
        else None
    )
    landing_gap_after_takeoff = (
        landing_ts - takeoff_ts
        if takeoff_ts is not None and landing_ts is not None
        else None
    )
    landing_gap_after_apex = (
        landing_ts - apex_ts
        if apex_ts is not None and landing_ts is not None
        else None
    )
    weak_or_tail_landing_after_unclear_apex = (
        landing_gap_after_takeoff is not None
        and (
            landing_gap_after_takeoff > SKELETON_DRIFT_MOTION_FALLBACK_LANDING_MAX_GAP_SEC
            or (
                landing_gap_after_takeoff > 0.90
                and landing_motion_component < SKELETON_DRIFT_MOTION_FALLBACK_TAIL_RATIO
            )
            or (
                landing_gap_after_takeoff > 1.10
                and landing_contact_component < SKELETON_DRIFT_MOTION_FALLBACK_WEAK_LANDING_CONTACT
                and landing_confidence < ORDERED_TAL_CONFIDENCE_FLOOR
            )
        )
    )
    late_weak_landing_after_unclear_apex = (
        landing_gap_after_takeoff is not None
        and landing_gap_after_apex is not None
        and landing_gap_after_takeoff > SKELETON_DRIFT_MOTION_FALLBACK_LATE_WEAK_LANDING_GAP_SEC
        and landing_gap_after_apex > SKELETON_DRIFT_MOTION_FALLBACK_LATE_WEAK_APEX_GAP_SEC
        and landing_contact_component < SKELETON_DRIFT_MOTION_FALLBACK_WEAK_LANDING_CONTACT
        and landing_confidence < ORDERED_TAL_CONFIDENCE_FLOOR
    )
    skeleton_drifted_after_takeoff = (
        apex_gap_after_takeoff is not None
        and "apex_local_minimum_not_clear" in apex_warnings
        and (
            (
                apex_gap_after_takeoff > SKELETON_DRIFT_MOTION_FALLBACK_APEX_MAX_GAP_SEC
                and weak_or_tail_landing_after_unclear_apex
            )
            or late_weak_landing_after_unclear_apex
        )
    )
    occluded_peak_fallback = _occluded_motion_peak_override_candidates(
        motion_scores,
        fps,
        quality_flags,
        frame_states,
        signals,
        search_window,
        takeoff,
        apex,
        landing,
    )
    if occluded_peak_fallback is not None:
        occluded_peak_fallback["excluded_pose_frames"] = excluded_counts
        return occluded_peak_fallback

    if skeleton_drifted_after_takeoff:
        fallback = _motion_fallback_from_takeoff_anchor(
            motion_scores,
            fps,
            takeoff,
            quality_flags + ["tal_candidate_skeleton_drifted_after_takeoff"],
            frame_states=frame_states,
        )
        if fallback is not None:
            contamination_flags = _motion_window_contamination_flags(
                signals,
                search_window,
                motion_scores,
                fps,
                frame_states,
                fallback["T"],
                fallback["A"],
                fallback["L"],
            )
            fallback["quality_flags"] = list(dict.fromkeys([*fallback["quality_flags"], *contamination_flags]))
            fallback["excluded_pose_frames"] = excluded_counts
            return fallback

    original_takeoff_anchor = _compressed_late_reselect_original_takeoff(takeoff)
    if original_takeoff_anchor is not None:
        fallback = _motion_fallback_from_takeoff_anchor(
            motion_scores,
            fps,
            original_takeoff_anchor,
            quality_flags + ["tal_candidate_compressed_late_reselect_restored_takeoff_anchor"],
            frame_states=frame_states,
        )
        if fallback is not None:
            contamination_flags = _motion_window_contamination_flags(
                signals,
                search_window,
                motion_scores,
                fps,
                frame_states,
                fallback["T"],
                fallback["A"],
                fallback["L"],
            )
            fallback["quality_flags"] = list(dict.fromkeys([*fallback["quality_flags"], *contamination_flags]))
            fallback["excluded_pose_frames"] = excluded_counts
            return fallback

    sparse_takeoff = _motion_refined_sparse_takeoff(
        motion_scores,
        fps,
        takeoff,
        apex,
        frame_states,
    )
    if sparse_takeoff is not None:
        quality_flags.append("keyframe_candidates_sparse_takeoff_motion_refined")
        if "keyframe_candidates_motion_fallback_unreliable_pose_state" in sparse_takeoff.get("warnings", []):
            quality_flags.append("keyframe_candidates_motion_fallback_unreliable_pose_state")
            quality_flags.append("tal_candidate_motion_fallback_unreliable_pose_low_confidence")
        takeoff = sparse_takeoff
        t_index = _candidate_index(takeoff)
        takeoff_ts = _to_float(takeoff.get("timestamp"))
        takeoff_evidence = takeoff.get("evidence") if isinstance(takeoff.get("evidence"), dict) else {}
        apex_gap_after_takeoff = (
            apex_ts - takeoff_ts
            if takeoff_ts is not None and apex_ts is not None
            else None
        )
        landing_gap_after_takeoff = (
            landing_ts - takeoff_ts
            if takeoff_ts is not None and landing_ts is not None
            else None
        )

    compressed_weak_apex_landing = (
        landing_gap_after_apex is not None
        and 0.0 <= landing_gap_after_apex <= WEAK_TAL_COMPRESSED_APEX_LANDING_GAP_SEC
        and "apex_local_minimum_not_clear" in apex_warnings
        and landing_contact_component < WEAK_TAL_LANDING_CONTACT_MAX
        and isinstance(takeoff_evidence.get("takeoff_late_plausible_reselection"), dict)
    )
    if compressed_weak_apex_landing:
        fallback = _motion_fallback_from_takeoff_anchor(
            motion_scores,
            fps,
            takeoff,
            quality_flags + ["tal_candidate_apex_landing_gap_compressed"],
            frame_states=frame_states,
        )
        if fallback is not None:
            contamination_flags = _motion_window_contamination_flags(
                signals,
                search_window,
                motion_scores,
                fps,
                frame_states,
                fallback["T"],
                fallback["A"],
                fallback["L"],
            )
            fallback["quality_flags"] = list(dict.fromkeys([*fallback["quality_flags"], *contamination_flags]))
            fallback["excluded_pose_frames"] = excluded_counts
            return fallback

    if t_index is None or a_index is None or l_index is None:
        fallback = _motion_fallback_candidates(
            motion_scores,
            fps,
            quality_flags + ["tal_candidate_incomplete", "tal_order_unresolved"],
            min_peak_score=PARTIAL_TAL_LOW_MOTION_FALLBACK_MIN_PEAK_SCORE,
            time_bounds=reliable_time_bounds,
            frame_states=frame_states,
            pose_data=pose_data,
            excluded_time_windows=rejected_tail_motion_windows,
        )
        if fallback is not None:
            fallback["excluded_pose_frames"] = excluded_counts
            return fallback
        quality_flags.append("tal_candidate_incomplete")
        quality_flags.append("tal_order_unresolved")
    elif not (
        t_index < a_index < l_index
        or (
            takeoff_ts is not None
            and apex_ts is not None
            and landing_ts is not None
            and takeoff_ts < apex_ts < landing_ts
        )
    ):
        quality_flags.append("tal_order_invalid")
        message = "tal_order_invalid"
        takeoff["warnings"].append(message)
        apex["warnings"].append(message)
        landing["warnings"].append(message)
    else:
        _apply_ordered_confidence_floor((takeoff, apex, landing))

    takeoff_warnings = takeoff.get("warnings") if isinstance(takeoff.get("warnings"), list) else []
    if "takeoff_sparse_prepeak_estimated" in takeoff_warnings:
        quality_flags.append("keyframe_candidates_sparse_takeoff_prepeak_estimated")
    if any(candidate.get("confidence", 0.0) < 0.35 for candidate in (takeoff, apex, landing)):
        quality_flags.append("tal_candidate_confidence_low")
    quality_flags.extend(
        _motion_window_contamination_flags(
            signals,
            search_window,
            motion_scores,
            fps,
            frame_states,
            takeoff,
            apex,
            landing,
        )
    )
    weak_geometry_flags = _weak_geometry_flags(takeoff, apex, landing)
    quality_flags.extend(weak_geometry_flags)
    quality_flags.extend(_tiny_target_weak_geometry_flags(pose_data, quality_flags, takeoff, apex, landing))
    temporal_geometry_flags = _temporal_geometry_unreliable_flags(takeoff, apex, landing)
    quality_flags.extend(temporal_geometry_flags)
    quality_flags.extend(
        _early_weak_motion_window_flags(
            signals,
            search_window,
            motion_scores,
            fps,
            quality_flags,
            takeoff,
            apex,
            landing,
        )
    )
    quality_flags.extend(_sparse_track_stitched_tal_flags(takeoff, apex, landing))
    quality_flags.extend(_apply_tail_compressed_motion_window_diagnostic(signals, search_window, takeoff, apex, landing))
    if any(candidate.get("confidence", 0.0) < 0.35 for candidate in (takeoff, apex, landing)):
        quality_flags.append("tal_candidate_confidence_low")

    if (
        "tal_order_invalid" in quality_flags
        and (
            fallback := _motion_fallback_candidates(
                motion_scores,
                fps,
                quality_flags,
                time_bounds=reliable_time_bounds,
                frame_states=frame_states,
                pose_data=pose_data,
                excluded_time_windows=rejected_tail_motion_windows,
            )
        )
        is not None
    ):
        fallback["excluded_pose_frames"] = excluded_counts
        return fallback

    return {
        "T": takeoff,
        "A": apex,
        "L": landing,
        "excluded_pose_frames": excluded_counts,
        "quality_flags": list(dict.fromkeys(quality_flags)),
    }
