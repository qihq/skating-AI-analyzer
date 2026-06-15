from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from app.services.target_lock import MANUAL_BBOX_MIN_SIDE


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

PERSON_TRACKER_UNAVAILABLE_FLAG = "person_tracker_unavailable_fallback"
PERSON_TRACKER_FAILED_FLAG = "person_tracker_failed_fallback"
PERSON_TRACKER_TARGET_LOST_FLAG = "person_tracker_target_lost"
PERSON_TRACKER_TRANSIENT_LOSS_RECOVERED_FLAG = "person_tracker_transient_loss_recovered"
PERSON_TRACKER_FINAL_UNRECOVERED_FLAG = "person_tracker_final_unrecovered"
PERSON_TRACKER_RELOCKED_FLAG = "person_tracker_relocked"
PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG = "person_tracker_anchor_not_first_frame"
PERSON_TRACKER_CONTINUITY_REJECTED_FLAG = "person_tracker_continuity_rejected"
PERSON_TRACKER_RELOCK_PENDING_FLAG = "person_tracker_relock_pending"
PERSON_TRACKER_RELOCK_REJECTED_FLAG = "person_tracker_relock_rejected"
PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG = "person_tracker_detector_relock_pending"
PERSON_TRACKER_DETECTOR_RELOCKED_FLAG = "person_tracker_detector_relocked"
PERSON_TRACKER_LOCAL_ZOOM_RELOCK_ATTEMPTED_FLAG = "person_tracker_local_zoom_relock_attempted"
PERSON_TRACKER_LOCAL_ZOOM_RELOCK_REJECTED_FLAG = "person_tracker_local_zoom_relock_rejected"
PERSON_TRACKER_CONFIRMED_PARTIAL_RECOVERY_FLAG = "person_tracker_confirmed_partial_recovery"
PERSON_TRACKER_CONTINUITY_DETECTOR_RELOCK_ATTEMPTED_FLAG = "person_tracker_continuity_detector_relock_attempted"
PERSON_TRACKER_SUPPORT_ANCHOR_RECOVERED_FLAG = "person_tracker_support_anchor_recovered"
PERSON_TRACKER_SUPPORT_ANCHOR_REJECTED_FLAG = "person_tracker_support_anchor_rejected"
PERSON_TRACKER_SUPPORT_ANCHOR_HANDOFF_REUSED_FLAG = "person_tracker_support_anchor_handoff_reused"
PERSON_TRACKER_TINY_TARGET_LOW_POSE_TRACKING_RISK_FLAG = "person_tracker_tiny_target_low_pose_tracking_risk"
PERSON_TRACKER_MULTIPERSON_RELOCK_INSTABILITY_RISK_FLAG = "person_tracker_multiperson_relock_instability_risk"
PERSON_TRACKER_MANUAL_LOCK_RELOCK_BLOCKED_FLAG = "person_tracker_manual_lock_relock_blocked"
PERSON_TRACKER_MANUAL_LOCK_FALLBACK_BLOCKED_FLAG = "person_tracker_manual_lock_fallback_blocked"
PERSON_TRACKER_MANUAL_LOCK_IDENTITY_REJECTED_FLAG = "person_tracker_manual_lock_identity_rejected"
PERSON_TRACKER_MANUAL_LOCK_SUPPORT_ANCHOR_BLOCKED_FLAG = "person_tracker_manual_lock_support_anchor_blocked"

_YOLO_MODEL_NAME = "yolov8n.pt"
_YOLO_MODEL_PATH_ENV = "YOLO_PERSON_MODEL_PATH"
_YOLO_MOUNTED_MODEL_PATH = Path("/models") / _YOLO_MODEL_NAME
_YOLO_CONF_THRESHOLD = 0.40
_TRACK_ACTIVATION_THRESHOLD = 0.35
_LOST_TRACK_BUFFER = 30
_MINIMUM_MATCHING_THRESHOLD = 0.80
_STATIC_HISTORY = 6
_STATIC_DISPLACEMENT_RATIO = 0.02
_MAX_RELOCK_DISTANCE_RATIO = 0.25
_RELOCK_AFTER_LOST_FRAMES = 3
_TRACK_CENTER_JUMP_RATIO = 0.18
_TRACK_AREA_RATIO_RANGE = (0.33, 3.0)
_TRACK_ASPECT_RATIO_RANGE = (0.40, 2.50)
_MANUAL_LOCK_TRACK_CENTER_JUMP_RATIO = 0.10
_MANUAL_LOCK_SELECT_MIN_IOU = 0.01
_MANUAL_LOCK_SELECT_MIN_SEED_COVERAGE = 0.20
_MANUAL_LOCK_SELECT_MIN_CANDIDATE_COVERAGE = 0.20
_ASPECT_ONLY_MIN_REFERENCE_COVERAGE = 0.25
_ASPECT_ONLY_MIN_CANDIDATE_COVERAGE = 0.18
_ASPECT_ONLY_MAX_REFERENCE_DIAGONAL_RATIO = 0.90
_PARTIAL_TO_FULL_MIN_REFERENCE_COVERAGE = 0.65
_PARTIAL_TO_FULL_MAX_REFERENCE_DIAGONAL_RATIO = 0.90
_PARTIAL_TO_FULL_MAX_AREA_RATIO = 16.0
_PARTIAL_TO_FULL_TINY_MAX_AREA_RATIO = 64.0
_PARTIAL_TO_FULL_MIN_HEIGHT_RATIO = 1.20
_PARTIAL_TO_FULL_UNANCHORED_MAX_HEIGHT_RATIO = 3.0
_PARTIAL_TO_FULL_TINY_MIN_REFERENCE_COVERAGE = 0.35
_PARTIAL_TO_FULL_TINY_MAX_CANDIDATE_DIAGONAL_RATIO = 0.45
_PARTIAL_TO_FULL_HISTORY_MIN_AREA_RATIO = 1.75
_PARTIAL_TO_FULL_HISTORY_AREA_RATIO_RANGE = (0.45, 4.25)
_PARTIAL_TO_FULL_HISTORY_MAX_DIAGONAL_RATIO = 0.75
_PARTIAL_TO_FULL_HISTORY_MIN_IOU = 0.05
_PARTIAL_TO_FULL_HISTORY_MIN_REFERENCE_COVERAGE = 0.45
_PARTIAL_TO_FULL_HISTORY_MIN_CANDIDATE_COVERAGE = 0.30
_PARTIAL_TO_FULL_RECOVERY_MAX_AREA = 0.18
_PARTIAL_TO_FULL_RECOVERY_MAX_HEIGHT = 0.80
_PARTIAL_TO_FULL_RECOVERY_ASPECT_RANGE = (0.10, 0.75)
_CONFIRMED_TRACK_PARTIAL_RECOVERY_CONFIRMATION_FRAMES = 2
_CONFIRMED_TRACK_PARTIAL_RECOVERY_REFERENCE_MAX_AREA = 0.006
_CONFIRMED_TRACK_PARTIAL_RECOVERY_CANDIDATE_AREA_RANGE = (0.006, 0.050)
_CONFIRMED_TRACK_PARTIAL_RECOVERY_AREA_RATIO_RANGE = (3.0, 18.0)
_CONFIRMED_TRACK_PARTIAL_RECOVERY_HEIGHT_RATIO_RANGE = (2.0, 4.0)
_CONFIRMED_TRACK_PARTIAL_RECOVERY_MAX_CENTER_RATIO = 0.125
_CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_CANDIDATE_AREA_RANGE = (0.006, 0.050)
_CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_AREA_RATIO_RANGE = (2.0, 10.0)
_CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_HEIGHT_RATIO_RANGE = (1.10, 2.20)
_CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_ASPECT_RANGE = (0.25, 0.80)
_CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_MAX_CENTER_RATIO = 0.09
_FOREGROUND_GROWTH_REFERENCE_MIN_AREA = 0.018
_FOREGROUND_GROWTH_CANDIDATE_MIN_AREA = 0.060
_FOREGROUND_GROWTH_CANDIDATE_MIN_HEIGHT = 0.48
_FOREGROUND_GROWTH_MIN_AREA_RATIO = 1.45
_FOREGROUND_GROWTH_MIN_HEIGHT_RATIO = 1.60
_FOREGROUND_GROWTH_MAX_WIDTH_RATIO = 1.15
_FOREGROUND_GROWTH_MAX_ASPECT = 0.55
_FOREGROUND_GROWTH_MIN_TOP_EXPANSION = 0.05
_FOREGROUND_GROWTH_MIN_BOTTOM_EXPANSION = 0.10
_FOREGROUND_GROWTH_HISTORY_MIN_AREA_RATIO = 0.70
_FOREGROUND_GROWTH_HISTORY_MIN_HEIGHT_RATIO = 0.78
_FOREGROUND_GROWTH_HISTORY_MAX_CENTER_RATIO = 0.18
_RELOCK_CENTER_JUMP_RATIO = 0.10
_RELOCK_AREA_RATIO_RANGE = (0.50, 2.0)
_RELOCK_ASPECT_RATIO_RANGE = (0.67, 1.50)
_RELOCK_MIN_IOU = 0.03
_RELOCK_PREVIOUS_DIAGONAL_RATIO = 0.75
_RELOCK_CONFIRMATION_FRAMES = 2
_ACCEPTED_HISTORY = 5
_DETECTOR_RELOCK_MIN_CONFIDENCE = 0.35
_DETECTOR_RELOCK_CENTER_JUMP_RATIO = 0.12
_DETECTOR_RELOCK_AREA_RATIO_RANGE = (0.45, 2.20)
_DETECTOR_RELOCK_ASPECT_RATIO_RANGE = (0.55, 1.75)
_DETECTOR_RELOCK_MIN_IOU = 0.02
_DETECTOR_RELOCK_REFERENCE_DIAGONAL_RATIO = 1.10
_DETECTOR_RELOCK_CONFIRM_IOU = 0.15
_DETECTOR_RELOCK_CONFIRM_DISTANCE_RATIO = 0.55
_DETECTOR_RELOCK_SCALE_JUMP_MIN_CONFIDENCE = 0.70
_DETECTOR_RELOCK_SCALE_JUMP_MAX_CENTER_RATIO = 0.18
_DETECTOR_RELOCK_SCALE_JUMP_MAX_AREA_RATIO = 9.5
_DETECTOR_RELOCK_SCALE_JUMP_MAX_HEIGHT_RATIO = 3.0
_DETECTOR_RELOCK_NEAR_SHRINK_MIN_CONFIDENCE = 0.70
_DETECTOR_RELOCK_NEAR_SHRINK_AREA_RATIO_RANGE = (0.32, 0.70)
_DETECTOR_RELOCK_NEAR_SHRINK_MAX_CENTER_RATIO = 0.03
_DETECTOR_RELOCK_NEAR_SHRINK_MIN_IOU = 0.25
_DETECTOR_RELOCK_NEAR_SHRINK_MIN_COVERAGE = 0.35
_DETECTOR_RELOCK_NEAR_SHRINK_ASPECT_RANGE = (0.10, 0.65)
_DETECTOR_RELOCK_NEAR_SHRINK_HEIGHT_RANGE = (0.10, 0.70)
_DETECTOR_RELOCK_IDENTITY_DISTANCE_RATIO = 0.35
_DETECTOR_RELOCK_IDENTITY_REFERENCE_COVERAGE = 0.35
_DETECTOR_RELOCK_IDENTITY_CANDIDATE_COVERAGE = 0.25
_LOCAL_ZOOM_TINY_SCALE_RECOVERY_MIN_CONFIDENCE = 0.50
_LOCAL_ZOOM_TINY_SCALE_RECOVERY_MAX_REFERENCE_AREA = 0.0045
_LOCAL_ZOOM_TINY_SCALE_RECOVERY_AREA_RANGE = (0.006, 0.045)
_LOCAL_ZOOM_TINY_SCALE_RECOVERY_AREA_RATIO_RANGE = (3.0, 14.0)
_LOCAL_ZOOM_TINY_SCALE_RECOVERY_HEIGHT_RATIO_RANGE = (2.2, 4.5)
_LOCAL_ZOOM_TINY_SCALE_RECOVERY_MAX_CENTER_RATIO = 0.045
_LOCAL_ZOOM_TINY_SCALE_RECOVERY_MIN_REFERENCE_COVERAGE = 0.55
_LOCAL_ZOOM_TINY_SCALE_RECOVERY_ASPECT_RANGE = (0.08, 0.35)
_LOCAL_ZOOM_NEAR_FULL_RECOVERY_MIN_CONFIDENCE = 0.60
_LOCAL_ZOOM_NEAR_FULL_RECOVERY_MAX_REFERENCE_AREA = 0.0060
_LOCAL_ZOOM_NEAR_FULL_RECOVERY_AREA_RANGE = (0.020, 0.065)
_LOCAL_ZOOM_NEAR_FULL_RECOVERY_AREA_RATIO_RANGE = (8.0, 16.0)
_LOCAL_ZOOM_NEAR_FULL_RECOVERY_HEIGHT_RATIO_RANGE = (3.4, 5.2)
_LOCAL_ZOOM_NEAR_FULL_RECOVERY_MAX_CENTER_RATIO = 0.025
_LOCAL_ZOOM_NEAR_FULL_RECOVERY_ASPECT_RANGE = (0.30, 0.58)
_LOCAL_ZOOM_NEAR_FULL_RECOVERY_MIN_IOU = 0.05
_LOCAL_ZOOM_PADDING_RATIO = 1.50
_LOCAL_ZOOM_SCALE = 2.0
_LOCAL_ZOOM_MIN_CONFIDENCE = 0.35
_ZOOMED_CONTENT_PREVIEW_SCALE = 3.0
_ZOOMED_CONTENT_COLUMN_BRIGHTNESS = 20.0
_ZOOMED_CONTENT_TOP_RATIO = 0.20
_ZOOMED_CONTENT_BOTTOM_RATIO = 0.85
_ZOOMED_CONTENT_MIN_WIDTH_RATIO = 0.15
_INITIAL_BOOTSTRAP_MIN_SEED_COVERAGE = 0.35
_INITIAL_BOOTSTRAP_MAX_AREA_RATIO = 7.0
_INITIAL_BOOTSTRAP_MAX_WIDTH_RATIO = 2.25
_INITIAL_BOOTSTRAP_MAX_HEIGHT_RATIO = 2.75
_INITIAL_BOOTSTRAP_MAX_CENTER_DISTANCE_RATIO = 0.22
_INITIAL_BOOTSTRAP_TINY_SEED_MAX_AREA = 0.010
_INITIAL_BOOTSTRAP_TINY_SEED_MAX_CANDIDATE_AREA = 0.045
_INITIAL_BOOTSTRAP_TINY_SEED_MAX_WIDTH_RATIO = 3.0
_LONG_LOST_REACQUIRE_AFTER_FRAMES = 4
_LONG_LOST_MIN_CONFIDENCE = 0.45
_LONG_LOST_SINGLE_DETECTOR_MIN_CONFIDENCE = 0.68
_LONG_LOST_PENDING_DETECTOR_MIN_CONFIDENCE = 0.68
_LONG_LOST_ASPECT_RANGE = (0.12, 0.65)
_LONG_LOST_HEIGHT_RANGE = (0.10, 0.62)
_LONG_LOST_AREA_RANGE = (0.002, 0.14)
_LONG_LOST_MOVING_DISPLACEMENT_RATIO = 0.035
_LONG_LOST_STABLE_SMALL_REACQUIRE_AFTER_FRAMES = 8
_LONG_LOST_STABLE_SMALL_MIN_CONFIDENCE = 0.55
_LONG_LOST_STABLE_SMALL_HISTORY_FRAMES = 2
_LONG_LOST_STABLE_SMALL_REFERENCE_MAX_AREA = 0.0045
_LONG_LOST_STABLE_SMALL_AREA_RANGE = (0.0018, 0.0060)
_LONG_LOST_STABLE_SMALL_AREA_RATIO_RANGE = (0.55, 1.30)
_LONG_LOST_STABLE_SMALL_ASPECT_RANGE = (0.25, 0.65)
_LONG_LOST_STABLE_SMALL_HEIGHT_RANGE = (0.085, 0.16)
_LONG_LOST_STABLE_MOVING_SMALL_REACQUIRE_AFTER_FRAMES = 8
_LONG_LOST_STABLE_MOVING_SMALL_MIN_CONFIDENCE = 0.70
_LONG_LOST_STABLE_MOVING_SMALL_HISTORY_FRAMES = 3
_LONG_LOST_STABLE_MOVING_SMALL_MAX_REFERENCE_AREA = 0.012
_LONG_LOST_STABLE_MOVING_SMALL_AREA_RANGE = (0.0035, 0.014)
_LONG_LOST_STABLE_MOVING_SMALL_AREA_RATIO_RANGE = (0.45, 2.25)
_LONG_LOST_STABLE_MOVING_SMALL_ASPECT_RANGE = (0.35, 0.75)
_LONG_LOST_STABLE_MOVING_SMALL_HEIGHT_RANGE = (0.10, 0.20)
_LONG_LOST_STABLE_MOVING_SMALL_MAX_CENTER_RATIO = 0.125
_LONG_LOST_STABLE_MOVING_SMALL_MIN_DISPLACEMENT_RATIO = 0.010
_LONG_LOST_MOVING_FOREGROUND_REFERENCE_MAX_AREA = 0.018
_LONG_LOST_MOVING_FOREGROUND_MIN_AREA = 0.035
_LONG_LOST_MOVING_FOREGROUND_MIN_HEIGHT = 0.32
_LONG_LOST_MOVING_FOREGROUND_MIN_AREA_RATIO = 3.0
_LONG_LOST_MOVING_FOREGROUND_MIN_HEIGHT_RATIO = 1.70
_LONG_LOST_MOVING_FOREGROUND_MIN_CENTER_RATIO = 0.12
_LONG_LOST_MOVING_FOREGROUND_MAX_OVERLAP = 0.05
_SMALL_BODY_RELOCK_MIN_CONFIDENCE = 0.70
_SMALL_BODY_RELOCK_AREA_RATIO_RANGE = (0.20, 0.50)
_SMALL_BODY_RELOCK_MAX_CENTER_RATIO = 0.105
_SUPPORT_ANCHOR_MIN_CONFIDENCE = 0.55
_SUPPORT_ANCHOR_MAX_AREA = 0.020
_SUPPORT_ANCHOR_MAX_HEIGHT = 0.32
_SUPPORT_ANCHOR_AREA_RATIO_RANGE = (0.35, 2.85)
_SUPPORT_ANCHOR_ASPECT_RANGE = (0.10, 0.75)
_SUPPORT_ANCHOR_MAX_CENTER_RATIO = 0.24
_SUPPORT_ANCHOR_MAX_PREDICTION_CENTER_RATIO = 0.18
_SUPPORT_ANCHOR_WIDE_POSE_MAX_AREA = 0.032
_SUPPORT_ANCHOR_WIDE_POSE_MAX_AREA_RATIO = 3.25
_SUPPORT_ANCHOR_WIDE_POSE_ASPECT_RANGE = (0.75, 1.15)
_SUPPORT_ANCHOR_WIDE_POSE_MAX_CENTER_RATIO = 0.11
_SUPPORT_ANCHOR_WIDE_POSE_MAX_PREDICTION_CENTER_RATIO = 0.16
_SUPPORT_ANCHOR_FOREGROUND_MIN_AREA = 0.045
_SUPPORT_ANCHOR_FOREGROUND_MIN_HEIGHT = 0.36
_SUPPORT_ANCHOR_FOREGROUND_MIN_AREA_RATIO = 3.0
_SUPPORT_ANCHOR_FOREGROUND_MIN_HEIGHT_RATIO = 1.55
_SUPPORT_ANCHOR_HANDOFF_FRAMES = 2
_SUPPORT_ANCHOR_HANDOFF_MAX_CENTER_RATIO = 0.105
_SUPPORT_ANCHOR_HANDOFF_MIN_IOU = 0.02
_SUPPORT_ANCHOR_HANDOFF_MIN_COVERAGE = 0.25
_DETECTOR_RELOCK_SHRUNK_FRAGMENT_REFERENCE_MIN_AREA = 0.0035
_DETECTOR_RELOCK_SHRUNK_FRAGMENT_MAX_AREA_RATIO = 0.46
_DETECTOR_RELOCK_SHRUNK_FRAGMENT_MAX_HEIGHT_RATIO = 0.78
_DETECTOR_RELOCK_SHRUNK_FRAGMENT_MAX_WIDTH = 0.024
_DETECTOR_RELOCK_SHRUNK_FRAGMENT_MAX_COVERAGE = 0.08
_SAME_TRACK_SCALE_RECOVERY_MIN_CONFIDENCE = 0.60
_SAME_TRACK_SCALE_RECOVERY_MIN_HISTORY_DISPLACEMENT_RATIO = 0.020
_SAME_TRACK_SCALE_RECOVERY_AREA_RANGE = (0.004, 0.18)
_SAME_TRACK_SCALE_RECOVERY_AREA_RATIO_RANGE = (0.18, 8.50)
_SAME_TRACK_SCALE_RECOVERY_ASPECT_RANGE = (0.10, 0.85)
_SAME_TRACK_SCALE_RECOVERY_HEIGHT_RANGE = (0.10, 0.72)
_SAME_TRACK_SCALE_RECOVERY_MAX_PREDICTION_DISTANCE_RATIO = 0.18
_SAME_TRACK_SCALE_RECOVERY_MIN_PREDICTION_IOU = 0.02
_SAME_TRACK_SCALE_RECOVERY_MIN_PREDICTION_COVERAGE = 0.20
_PREDICTION_MAX_LOST_STEPS = 3
_PREDICTION_MAX_CENTER_SHIFT_RATIO = 0.20
_STATIC_RELOCK_NEAR_IOU = 0.35
_STATIC_RELOCK_NEAR_COVERAGE = 0.55
_STATIC_RELOCK_NEAR_DIAGONAL_RATIO = 0.45
_TERMINAL_LOSS_GRACE_FRAMES = 2
_TERMINAL_LOSS_GRACE_MIN_TRACKED_FRAMES = 8
_TERMINAL_LOSS_EXTENDED_GRACE_FRAMES = 4
_TERMINAL_LOSS_EXTENDED_GRACE_MIN_TRACKED_FRAMES = 16
_TERMINAL_LOSS_EXTENDED_GRACE_MAX_TERMINAL_RATIO = 0.125
_TERMINAL_LOSS_TAIL_GRACE_FRAMES = 6
_TERMINAL_LOSS_TAIL_GRACE_MIN_TRACKED_FRAMES = 12
_TERMINAL_LOSS_TAIL_GRACE_MAX_TERMINAL_RATIO = 0.25
_MAX_DIAGNOSTIC_REJECTED_CANDIDATES = 4
_RECOVERED_LOSS_STATES = {
    "relocked",
    "detector_relocked",
    "support_anchor_recovered",
    "support_anchor_handoff_reused",
    "tracked",
}
_UNRECOVERED_LOSS_STATES = {"lost_reused", "relock_rejected", "continuity_rejected"}


class PersonTrackerUnavailable(RuntimeError):
    """Raised when optional person-tracking dependencies are not installed or usable."""


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _normalize_bbox(bbox: dict[str, Any]) -> dict[str, float]:
    x = _clamp(float(bbox.get("x", 0.0) or 0.0), 0.0, 1.0)
    y = _clamp(float(bbox.get("y", 0.0) or 0.0), 0.0, 1.0)
    width = _clamp(float(bbox.get("width", bbox.get("w", 0.0)) or 0.0), MANUAL_BBOX_MIN_SIDE, 1.0 - x)
    height = _clamp(float(bbox.get("height", bbox.get("h", 0.0)) or 0.0), MANUAL_BBOX_MIN_SIDE, 1.0 - y)
    return {"x": round(x, 4), "y": round(y, 4), "width": round(width, 4), "height": round(height, 4)}


def _is_plausible_human_xyxy(candidate_xyxy: Sequence[float], *, frame_w: int, frame_h: int) -> bool:
    bbox = _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h)
    area = float(bbox["width"]) * float(bbox["height"])
    aspect = float(bbox["width"]) / max(float(bbox["height"]), MANUAL_BBOX_MIN_SIDE)
    height = float(bbox["height"])
    return (
        _LONG_LOST_AREA_RANGE[0] <= area <= _LONG_LOST_AREA_RANGE[1]
        and _LONG_LOST_ASPECT_RANGE[0] <= aspect <= _LONG_LOST_ASPECT_RANGE[1]
        and _LONG_LOST_HEIGHT_RANGE[0] <= height <= _LONG_LOST_HEIGHT_RANGE[1]
    )


def _is_initial_tiny_seed_bootstrap_candidate(
    candidate_xyxy: Sequence[float],
    reference_xyxy: Sequence[float],
    *,
    frame_w: int,
    frame_h: int,
    distance: float,
    frame_diagonal: float,
    candidate_width: float,
    reference_width: float,
    candidate_height: float,
    reference_height: float,
) -> bool:
    reference_area = _xyxy_area(reference_xyxy)
    candidate_area = _xyxy_area(candidate_xyxy)
    frame_area = max(float(frame_w * frame_h), 1.0)
    if reference_area <= 0.0 or candidate_area <= 0.0:
        return False
    if reference_area / frame_area > _INITIAL_BOOTSTRAP_TINY_SEED_MAX_AREA:
        return False
    if candidate_area / frame_area > _INITIAL_BOOTSTRAP_TINY_SEED_MAX_CANDIDATE_AREA:
        return False
    if candidate_area / reference_area > _INITIAL_BOOTSTRAP_MAX_AREA_RATIO:
        return False
    if distance > frame_diagonal * _INITIAL_BOOTSTRAP_MAX_CENTER_DISTANCE_RATIO:
        return False
    if candidate_width / reference_width > _INITIAL_BOOTSTRAP_TINY_SEED_MAX_WIDTH_RATIO:
        return False
    if candidate_height / reference_height > _INITIAL_BOOTSTRAP_MAX_HEIGHT_RATIO:
        return False
    return _is_plausible_human_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h)


def _is_plausible_partial_recovery_xyxy(candidate_xyxy: Sequence[float], *, frame_w: int, frame_h: int) -> bool:
    if _is_plausible_human_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h):
        return True
    bbox = _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h)
    area = float(bbox["width"]) * float(bbox["height"])
    aspect = float(bbox["width"]) / max(float(bbox["height"]), MANUAL_BBOX_MIN_SIDE)
    height = float(bbox["height"])
    return (
        _LONG_LOST_AREA_RANGE[0] <= area <= _PARTIAL_TO_FULL_RECOVERY_MAX_AREA
        and _PARTIAL_TO_FULL_RECOVERY_ASPECT_RANGE[0] <= aspect <= _PARTIAL_TO_FULL_RECOVERY_ASPECT_RANGE[1]
        and _LONG_LOST_HEIGHT_RANGE[0] <= height <= _PARTIAL_TO_FULL_RECOVERY_MAX_HEIGHT
    )


def _is_plausible_aspect_only_shape_change(
    candidate_xyxy: Sequence[float] | None,
    reference_xyxy: Sequence[float] | None,
    *,
    frame_w: int,
    frame_h: int,
    center_jump_ratio: float,
) -> bool:
    if candidate_xyxy is None or reference_xyxy is None:
        return False
    frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
    distance = _center_distance(candidate_xyxy, reference_xyxy)
    if distance > frame_diagonal * center_jump_ratio:
        return False
    reference_diagonal = max(_xyxy_diagonal(reference_xyxy), 1.0)
    return (
        _bbox_coverage(reference_xyxy, candidate_xyxy) >= _ASPECT_ONLY_MIN_REFERENCE_COVERAGE
        or _bbox_coverage(candidate_xyxy, reference_xyxy) >= _ASPECT_ONLY_MIN_CANDIDATE_COVERAGE
        or distance <= reference_diagonal * _ASPECT_ONLY_MAX_REFERENCE_DIAGONAL_RATIO
    )


def _is_plausible_partial_to_full_body_recovery(
    candidate_xyxy: Sequence[float] | None,
    reference_xyxy: Sequence[float] | None,
    *,
    frame_w: int,
    frame_h: int,
    history_xyxy: Sequence[Sequence[float]] | None = None,
    prediction_xyxy: Sequence[float] | None = None,
    require_anchor_support: bool = False,
) -> bool:
    if candidate_xyxy is None or reference_xyxy is None:
        return False
    reference_area = _xyxy_area(reference_xyxy)
    candidate_area = _xyxy_area(candidate_xyxy)
    if reference_area <= 0.0 or candidate_area <= 0.0:
        return False
    area_ratio = candidate_area / reference_area
    if area_ratio <= 1.0 or area_ratio > _PARTIAL_TO_FULL_TINY_MAX_AREA_RATIO:
        return False

    reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
    candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
    height_ratio = candidate_height / reference_height
    if height_ratio < _PARTIAL_TO_FULL_MIN_HEIGHT_RATIO:
        return False

    if not _is_plausible_partial_recovery_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h):
        return False

    reference_diagonal = max(_xyxy_diagonal(reference_xyxy), 1.0)
    reference_distance = _center_distance(candidate_xyxy, reference_xyxy)
    reference_coverage = _bbox_coverage(reference_xyxy, candidate_xyxy)
    if (
        not require_anchor_support
        and area_ratio <= _PARTIAL_TO_FULL_MAX_AREA_RATIO
        and reference_distance <= reference_diagonal * _PARTIAL_TO_FULL_MAX_REFERENCE_DIAGONAL_RATIO
        and reference_coverage >= _PARTIAL_TO_FULL_MIN_REFERENCE_COVERAGE
        and height_ratio <= _PARTIAL_TO_FULL_UNANCHORED_MAX_HEIGHT_RATIO
    ):
        return True

    candidate_diagonal = max(_xyxy_diagonal(candidate_xyxy), 1.0)
    if (
        not require_anchor_support
        and reference_coverage >= _PARTIAL_TO_FULL_TINY_MIN_REFERENCE_COVERAGE
        and reference_distance <= candidate_diagonal * _PARTIAL_TO_FULL_TINY_MAX_CANDIDATE_DIAGONAL_RATIO
        and height_ratio <= _PARTIAL_TO_FULL_UNANCHORED_MAX_HEIGHT_RATIO
    ):
        return True

    anchors: list[Sequence[float]] = []
    if prediction_xyxy is not None:
        anchors.append(prediction_xyxy)
    if history_xyxy:
        anchors.extend(history_xyxy)
    for anchor_xyxy in anchors:
        anchor_area = _xyxy_area(anchor_xyxy)
        if anchor_area <= 0.0:
            continue
        if anchor_area / reference_area < _PARTIAL_TO_FULL_HISTORY_MIN_AREA_RATIO:
            continue
        candidate_to_anchor_area = candidate_area / anchor_area
        if not (
            _PARTIAL_TO_FULL_HISTORY_AREA_RATIO_RANGE[0]
            <= candidate_to_anchor_area
            <= _PARTIAL_TO_FULL_HISTORY_AREA_RATIO_RANGE[1]
        ):
            continue
        anchor_diagonal = max(_xyxy_diagonal(anchor_xyxy), 1.0)
        if _center_distance(candidate_xyxy, anchor_xyxy) > anchor_diagonal * _PARTIAL_TO_FULL_HISTORY_MAX_DIAGONAL_RATIO:
            continue
        if _iou(candidate_xyxy, anchor_xyxy) >= _PARTIAL_TO_FULL_HISTORY_MIN_IOU:
            return True
        if _bbox_coverage(anchor_xyxy, candidate_xyxy) >= _PARTIAL_TO_FULL_HISTORY_MIN_REFERENCE_COVERAGE:
            return True
        if _bbox_coverage(candidate_xyxy, anchor_xyxy) >= _PARTIAL_TO_FULL_HISTORY_MIN_CANDIDATE_COVERAGE:
            return True
    return False


def _bbox_to_xyxy(bbox: dict[str, float], frame_width: int, frame_height: int) -> tuple[float, float, float, float]:
    normalized = _normalize_bbox(bbox)
    x1 = normalized["x"] * frame_width
    y1 = normalized["y"] * frame_height
    return (
        x1,
        y1,
        x1 + normalized["width"] * frame_width,
        y1 + normalized["height"] * frame_height,
    )


def _xyxy_to_bbox(xyxy: Sequence[float], frame_width: int, frame_height: int) -> dict[str, float]:
    x1, y1, x2, y2 = [float(value) for value in xyxy]
    left = _clamp(min(x1, x2) / max(frame_width, 1), 0.0, 1.0)
    top = _clamp(min(y1, y2) / max(frame_height, 1), 0.0, 1.0)
    right = _clamp(max(x1, x2) / max(frame_width, 1), 0.0, 1.0)
    bottom = _clamp(max(y1, y2) / max(frame_height, 1), 0.0, 1.0)
    return _normalize_bbox({"x": left, "y": top, "width": right - left, "height": bottom - top})


def _iou(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    if a is None or b is None:
        return 0.0
    ax1, ay1, ax2, ay2 = [float(value) for value in a]
    bx1, by1, bx2, by2 = [float(value) for value in b]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _intersection_area(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    if a is None or b is None:
        return 0.0
    ax1, ay1, ax2, ay2 = [float(value) for value in a]
    bx1, by1, bx2, by2 = [float(value) for value in b]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)


def _bbox_coverage(inner: Sequence[float] | None, outer: Sequence[float] | None) -> float:
    inner_area = _xyxy_area(inner)
    if inner_area <= 0.0:
        return 0.0
    return _intersection_area(inner, outer) / inner_area


def _center(xyxy: Sequence[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = [float(value) for value in xyxy]
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _center_distance(a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _xyxy_area(xyxy: Sequence[float] | None) -> float:
    if xyxy is None:
        return 0.0
    x1, y1, x2, y2 = [float(value) for value in xyxy]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _xyxy_aspect_ratio(xyxy: Sequence[float] | None) -> float:
    if xyxy is None:
        return 0.0
    x1, y1, x2, y2 = [float(value) for value in xyxy]
    height = max(1.0, y2 - y1)
    return max(0.0, x2 - x1) / height


def _xyxy_diagonal(xyxy: Sequence[float] | None) -> float:
    if xyxy is None:
        return 0.0
    x1, y1, x2, y2 = [float(value) for value in xyxy]
    return (max(0.0, x2 - x1) ** 2 + max(0.0, y2 - y1) ** 2) ** 0.5


def _clamp_xyxy(xyxy: Sequence[float], frame_w: int, frame_h: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = [float(value) for value in xyxy]
    left = _clamp(min(x1, x2), 0.0, float(frame_w))
    top = _clamp(min(y1, y2), 0.0, float(frame_h))
    right = _clamp(max(x1, x2), 0.0, float(frame_w))
    bottom = _clamp(max(y1, y2), 0.0, float(frame_h))
    return left, top, right, bottom


def _expand_xyxy(xyxy: Sequence[float], frame_w: int, frame_h: int, padding_ratio: float) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = _clamp_xyxy(xyxy, frame_w, frame_h)
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    center_x, center_y = _center((x1, y1, x2, y2))
    expanded_width = min(float(frame_w), width * (1.0 + padding_ratio * 2.0))
    expanded_height = min(float(frame_h), height * (1.0 + padding_ratio * 2.0))
    left = int(_clamp(center_x - expanded_width / 2.0, 0.0, max(0.0, frame_w - expanded_width)))
    top = int(_clamp(center_y - expanded_height / 2.0, 0.0, max(0.0, frame_h - expanded_height)))
    right = int(_clamp(left + expanded_width, left + 1.0, float(frame_w)))
    bottom = int(_clamp(top + expanded_height, top + 1.0, float(frame_h)))
    return left, top, right, bottom


def _add_flag(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def _candidate_geometry_diagnostic(
    candidate_xyxy: Sequence[float] | None,
    *,
    frame_w: int,
    frame_h: int,
    reference_xyxy: Sequence[float] | None = None,
    prediction_xyxy: Sequence[float] | None = None,
) -> dict[str, Any]:
    if candidate_xyxy is None:
        return {}

    frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
    frame_area = max(float(frame_w * frame_h), 1.0)
    candidate_area = _xyxy_area(candidate_xyxy)
    out: dict[str, Any] = {
        "area": round(candidate_area / frame_area, 6),
        "aspect_ratio": round(_xyxy_aspect_ratio(candidate_xyxy), 4),
    }
    if reference_xyxy is not None:
        reference_area = _xyxy_area(reference_xyxy)
        reference_distance = _center_distance(candidate_xyxy, reference_xyxy)
        out.update(
            {
                "reference_area": round(reference_area / frame_area, 6),
                "area_ratio": round(candidate_area / max(reference_area, 1.0), 4),
                "center_distance_ratio": round(reference_distance / max(frame_diagonal, 1.0), 4),
                "reference_diagonal_distance_ratio": round(
                    reference_distance / max(_xyxy_diagonal(reference_xyxy), 1.0),
                    4,
                ),
                "iou": round(_iou(candidate_xyxy, reference_xyxy), 4),
                "reference_coverage": round(_bbox_coverage(reference_xyxy, candidate_xyxy), 4),
                "candidate_coverage": round(_bbox_coverage(candidate_xyxy, reference_xyxy), 4),
            }
        )
    if prediction_xyxy is not None:
        prediction_distance = _center_distance(candidate_xyxy, prediction_xyxy)
        out.update(
            {
                "prediction_center_distance_ratio": round(prediction_distance / max(frame_diagonal, 1.0), 4),
                "prediction_diagonal_distance_ratio": round(
                    prediction_distance / max(_xyxy_diagonal(prediction_xyxy), 1.0),
                    4,
                ),
                "prediction_iou": round(_iou(candidate_xyxy, prediction_xyxy), 4),
            }
        )
    return out


def _rejected_candidate_diagnostic(
    candidate_xyxy: Sequence[float],
    *,
    frame_w: int,
    frame_h: int,
    reasons: Sequence[str],
    tracker_id: int | None = None,
    source: str | None = None,
    confidence: float | None = None,
    reference_xyxy: Sequence[float] | None = None,
    prediction_xyxy: Sequence[float] | None = None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "bbox": _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h),
        "reasons": list(dict.fromkeys(reasons)),
    }
    if tracker_id is not None:
        diagnostic["tracker_id"] = int(tracker_id)
    if source:
        diagnostic["source"] = source
    if confidence is not None:
        diagnostic["candidate_confidence"] = round(float(confidence), 4)
    diagnostic.update(
        _candidate_geometry_diagnostic(
            candidate_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            reference_xyxy=reference_xyxy,
            prediction_xyxy=prediction_xyxy,
        )
    )
    return diagnostic


def _frame_diagnostic(
    *,
    frame_index: int,
    frame_path: Path | None,
    state: str,
    frame_w: int,
    frame_h: int,
    bbox_xyxy: Sequence[float] | None,
    tracker_id: int | None,
    lost_frames: int,
    candidate_tracker_id: int | None = None,
    rejected_reasons: Sequence[str] | None = None,
    rejected_candidates: Sequence[dict[str, Any]] | None = None,
    prediction_xyxy: Sequence[float] | None = None,
    pending_relock_xyxy: Sequence[float] | None = None,
    relock_source: str | None = None,
    local_crop_bounds: Sequence[int] | None = None,
    candidate_confidence: float | None = None,
    candidate_xyxy: Sequence[float] | None = None,
    reference_xyxy: Sequence[float] | None = None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "frame_index": frame_index,
        "state": state,
        "tracker_id": tracker_id,
        "candidate_tracker_id": candidate_tracker_id,
        "lost_frames": lost_frames,
        "bbox": _xyxy_to_bbox(bbox_xyxy, frame_w, frame_h) if bbox_xyxy is not None else None,
    }
    if frame_path is not None:
        diagnostic["frame"] = frame_path.name
    if rejected_reasons:
        diagnostic["rejected_reasons"] = list(rejected_reasons)
    if rejected_candidates:
        diagnostic["rejected_candidates"] = list(rejected_candidates)[:_MAX_DIAGNOSTIC_REJECTED_CANDIDATES]
    if prediction_xyxy is not None:
        diagnostic["prediction_bbox"] = _xyxy_to_bbox(prediction_xyxy, frame_w, frame_h)
    if pending_relock_xyxy is not None:
        diagnostic["pending_relock_bbox"] = _xyxy_to_bbox(pending_relock_xyxy, frame_w, frame_h)
    if relock_source:
        diagnostic["relock_source"] = relock_source
    if local_crop_bounds is not None:
        diagnostic["local_crop_bounds"] = [int(value) for value in local_crop_bounds]
    if candidate_confidence is not None:
        diagnostic["candidate_confidence"] = round(float(candidate_confidence), 4)
    if candidate_xyxy is not None:
        diagnostic["candidate_bbox"] = _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h)
        candidate_geometry = _candidate_geometry_diagnostic(
            candidate_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            reference_xyxy=reference_xyxy,
            prediction_xyxy=prediction_xyxy,
        )
        if candidate_geometry:
            diagnostic["candidate_geometry"] = candidate_geometry
    return diagnostic


def _diagnostic_state_counts(diagnostics: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    return counts


def _is_unrecovered_loss_state(state: str) -> bool:
    return state in _UNRECOVERED_LOSS_STATES or state.endswith("_relock_pending") or state == "relock_pending"


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
        or tracked_frames < _TERMINAL_LOSS_GRACE_MIN_TRACKED_FRAMES
    ):
        return False
    if terminal_loss_frames <= _TERMINAL_LOSS_GRACE_FRAMES:
        return True
    terminal_ratio = terminal_loss_frames / max(total_frames, 1)
    if (
        terminal_loss_frames <= _TERMINAL_LOSS_EXTENDED_GRACE_FRAMES
        and tracked_frames >= _TERMINAL_LOSS_EXTENDED_GRACE_MIN_TRACKED_FRAMES
        and terminal_ratio <= _TERMINAL_LOSS_EXTENDED_GRACE_MAX_TERMINAL_RATIO
    ):
        return True
    return (
        terminal_loss_frames <= _TERMINAL_LOSS_TAIL_GRACE_FRAMES
        and tracked_frames >= _TERMINAL_LOSS_TAIL_GRACE_MIN_TRACKED_FRAMES
        and terminal_ratio <= _TERMINAL_LOSS_TAIL_GRACE_MAX_TERMINAL_RATIO
    )


def _loss_recovery_summary(diagnostics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    counts = _diagnostic_state_counts(diagnostics)
    loss_frames = sum(count for state, count in counts.items() if _is_unrecovered_loss_state(state))
    recovered_frames = sum(count for state, count in counts.items() if state in _RECOVERED_LOSS_STATES)
    final_state = str(diagnostics[-1].get("state") or "unknown") if diagnostics else "unknown"
    raw_final_unrecovered = _is_unrecovered_loss_state(final_state)
    terminal_loss_frames = 0
    for item in reversed(diagnostics):
        state = str(item.get("state") or "unknown")
        if _is_unrecovered_loss_state(state):
            terminal_loss_frames += 1
            continue
        break
    tracked_frames = sum(count for state, count in counts.items() if state in _RECOVERED_LOSS_STATES)
    terminal_loss_graced = _terminal_loss_graced(
        raw_final_unrecovered=raw_final_unrecovered,
        terminal_loss_frames=terminal_loss_frames,
        tracked_frames=tracked_frames,
        total_frames=len(diagnostics),
    )
    final_unrecovered = raw_final_unrecovered and not terminal_loss_graced
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
        "transient_loss_recovered": loss_frames > 0 and recovered_frames > 0 and not final_unrecovered,
    }


class PersonBBoxTracker:
    """YOLO person detector + ByteTrack target association for sampled frame sequences."""

    def __init__(
        self,
        *,
        yolo_model: Any | None = None,
        byte_tracker_factory: Any | None = None,
        effective_fps: float | None = None,
        manual_lock_mode: bool = False,
    ) -> None:
        self._yolo_model = yolo_model
        self._byte_tracker_factory = byte_tracker_factory
        self._tracker: Any | None = None
        self._effective_fps = max(float(effective_fps or 5.0), 1.0)
        self._manual_lock_mode = bool(manual_lock_mode)
        self._target_tracker_id: int | None = None
        self._last_known_xyxy: tuple[float, float, float, float] | None = None
        self._lost_frames = 0
        self._pending_relock_tracker_id: int | None = None
        self._pending_relock_count = 0
        self._pending_detector_relock_xyxy: tuple[float, float, float, float] | None = None
        self._pending_detector_relock_source: str | None = None
        self._pending_detector_relock_count = 0
        self._detector_relock_pending_identity_confirmation = False
        self._pending_confirmed_partial_recovery_tracker_id: int | None = None
        self._pending_confirmed_partial_recovery_xyxy: tuple[float, float, float, float] | None = None
        self._pending_confirmed_partial_recovery_count = 0
        self._support_anchor_handoff_xyxy: tuple[float, float, float, float] | None = None
        self._support_anchor_handoff_frame_index: int | None = None
        self._accepted_xyxy_history: list[tuple[int, tuple[float, float, float, float]]] = []
        self._center_history: dict[int, list[tuple[float, float]]] = {}
        self.quality_flags: list[str] = []

    def track_sequence(
        self,
        frame_paths: Sequence[Path],
        initial_bbox: dict[str, Any],
    ) -> tuple[list[dict[str, float]], list[str]]:
        frames = list(frame_paths)
        if not frames:
            return [], []

        tracked: list[dict[str, float]] = []
        states: list[dict[str, Any]] = []
        for frame_index, frame_path in enumerate(frames):
            frame = self._read_frame(frame_path)
            frame_h, frame_w = frame.shape[:2]
            if frame_index == 0 and self._last_known_xyxy is None:
                self._last_known_xyxy = _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)

            target_xyxy = self.process_frame(frame, self._last_known_xyxy)
            if target_xyxy is None:
                _add_flag(self.quality_flags, PERSON_TRACKER_TARGET_LOST_FLAG)
                target_xyxy = self._last_known_xyxy or _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)
                states.append({"state": "lost_reused"})
            else:
                self._last_known_xyxy = target_xyxy
                states.append({"state": "tracked"})

            tracked.append(_xyxy_to_bbox(target_xyxy, frame_w, frame_h))

        if _loss_recovery_summary(states).get("final_unrecovered"):
            _add_flag(self.quality_flags, PERSON_TRACKER_FINAL_UNRECOVERED_FLAG)

        return tracked, list(dict.fromkeys(self.quality_flags))

    def track_sequence_detailed(
        self,
        frame_paths: Sequence[Path],
        initial_bbox: dict[str, Any],
        *,
        support_anchor_bboxes_by_frame: dict[int, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, float]], list[str], list[dict[str, Any]]]:
        frames = list(frame_paths)
        if not frames:
            return [], [], []

        tracked: list[dict[str, float]] = []
        diagnostics: list[dict[str, Any]] = []
        for frame_index, frame_path in enumerate(frames):
            frame = self._read_frame(frame_path)
            frame_h, frame_w = frame.shape[:2]
            if frame_index == 0 and self._last_known_xyxy is None:
                self._last_known_xyxy = _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)

            target_xyxy, diagnostic = self.process_frame_detailed(
                frame,
                self._last_known_xyxy,
                frame_index=frame_index,
                frame_path=frame_path,
                support_anchor_bbox=(
                    support_anchor_bboxes_by_frame.get(frame_index)
                    if isinstance(support_anchor_bboxes_by_frame, dict)
                    else None
                ),
            )
            if target_xyxy is None:
                _add_flag(self.quality_flags, PERSON_TRACKER_TARGET_LOST_FLAG)
                target_xyxy = self._last_known_xyxy or _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)
                diagnostic["bbox"] = _xyxy_to_bbox(target_xyxy, frame_w, frame_h)
            else:
                self._last_known_xyxy = target_xyxy

            tracked.append(_xyxy_to_bbox(target_xyxy, frame_w, frame_h))
            diagnostics.append(diagnostic)

        summary = _loss_recovery_summary(diagnostics)
        if summary.get("transient_loss_recovered"):
            _add_flag(self.quality_flags, PERSON_TRACKER_TRANSIENT_LOSS_RECOVERED_FLAG)
        if summary.get("final_unrecovered"):
            _add_flag(self.quality_flags, PERSON_TRACKER_FINAL_UNRECOVERED_FLAG)
        if diagnostics:
            diagnostics[-1]["sequence_summary"] = summary

        return tracked, list(dict.fromkeys(self.quality_flags)), diagnostics

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        seed_xyxy: Sequence[float] | None,
    ) -> tuple[float, float, float, float] | None:
        target_xyxy, _ = self.process_frame_detailed(frame_bgr, seed_xyxy)
        return target_xyxy

    def process_frame_detailed(
        self,
        frame_bgr: np.ndarray,
        seed_xyxy: Sequence[float] | None,
        *,
        frame_index: int = 0,
        frame_path: Path | None = None,
        support_anchor_bbox: dict[str, Any] | None = None,
    ) -> tuple[tuple[float, float, float, float] | None, dict[str, Any]]:
        frame_h, frame_w = frame_bgr.shape[:2]
        fallback_xyxy = tuple(float(value) for value in (self._last_known_xyxy or seed_xyxy)) if (self._last_known_xyxy or seed_xyxy) is not None else None
        support_anchor_xyxy = self._support_anchor_xyxy(
            support_anchor_bbox,
            frame_w=frame_w,
            frame_h=frame_h,
        )
        raw_boxes = self._detect(frame_bgr)
        if not raw_boxes:
            self._lost_frames += 1
            self._clear_pending_confirmed_partial_recovery()
            prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
            anchor_result = self._maybe_recover_from_support_anchor(
                support_anchor_bbox,
                support_anchor_xyxy,
                fallback_xyxy or seed_xyxy,
                prediction_xyxy,
                frame_index=frame_index,
                frame_path=frame_path,
                frame_w=frame_w,
                frame_h=frame_h,
                base_reasons=["no_person_detections"],
            )
            if anchor_result is not None:
                return anchor_result
            support_anchor_rejection = self._support_anchor_rejected_candidate_diagnostic(
                support_anchor_bbox,
                support_anchor_xyxy,
                fallback_xyxy or seed_xyxy,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            )
            return self._handle_lost_with_detector_relock(
                frame_bgr,
                raw_boxes,
                fallback_xyxy,
                seed_xyxy,
                frame_index=frame_index,
                frame_path=frame_path,
                frame_w=frame_w,
                frame_h=frame_h,
                base_reasons=["no_person_detections"],
                prediction_xyxy=prediction_xyxy,
                extra_rejected_candidates=[support_anchor_rejection] if support_anchor_rejection else None,
            )

        tracked = self._update_tracks(raw_boxes)
        if len(tracked) == 0 or getattr(tracked, "tracker_id", None) is None:
            self._lost_frames += 1
            self._clear_pending_confirmed_partial_recovery()
            prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
            anchor_result = self._maybe_recover_from_support_anchor(
                support_anchor_bbox,
                support_anchor_xyxy,
                fallback_xyxy or seed_xyxy,
                prediction_xyxy,
                frame_index=frame_index,
                frame_path=frame_path,
                frame_w=frame_w,
                frame_h=frame_h,
                base_reasons=["no_active_tracks"],
            )
            if anchor_result is not None:
                return anchor_result
            support_anchor_rejection = self._support_anchor_rejected_candidate_diagnostic(
                support_anchor_bbox,
                support_anchor_xyxy,
                fallback_xyxy or seed_xyxy,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            )
            return self._handle_lost_with_detector_relock(
                frame_bgr,
                raw_boxes,
                fallback_xyxy,
                seed_xyxy,
                frame_index=frame_index,
                frame_path=frame_path,
                frame_w=frame_w,
                frame_h=frame_h,
                base_reasons=["no_active_tracks"],
                prediction_xyxy=prediction_xyxy,
                extra_rejected_candidates=[support_anchor_rejection] if support_anchor_rejection else None,
            )

        self._record_centers(tracked)
        if self._target_tracker_id is None:
            current_support_selection_xyxy = (
                support_anchor_xyxy
                if self._support_anchor_is_usable(
                    support_anchor_bbox,
                    support_anchor_xyxy,
                    self._last_known_xyxy or seed_xyxy,
                    self._predict_next_xyxy(frame_w, frame_h),
                    frame_w=frame_w,
                    frame_h=frame_h,
                )
                else None
            )
            handoff_seed_xyxy = self._support_anchor_handoff_seed(frame_index)
            selection_seed_xyxy = current_support_selection_xyxy or handoff_seed_xyxy or seed_xyxy
            strict_seed_xyxy = current_support_selection_xyxy or handoff_seed_xyxy
            self._target_tracker_id = self._select_target(
                tracked,
                selection_seed_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
                allow_static_filter=True,
                support_anchor_handoff_xyxy=strict_seed_xyxy,
                manual_lock_mode=self._manual_lock_mode,
            )
            if self._target_tracker_id is None:
                self._lost_frames += 1
                prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
                anchor_result = self._maybe_recover_from_support_anchor(
                    support_anchor_bbox,
                    support_anchor_xyxy,
                    self._last_known_xyxy or seed_xyxy,
                    prediction_xyxy,
                    frame_index=frame_index,
                    frame_path=frame_path,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    base_reasons=["initial_target_not_found"],
                )
                if anchor_result is not None:
                    return anchor_result
                if handoff_seed_xyxy is not None:
                    _add_flag(self.quality_flags, PERSON_TRACKER_SUPPORT_ANCHOR_HANDOFF_REUSED_FLAG)
                    return None, _frame_diagnostic(
                        frame_index=frame_index,
                        frame_path=frame_path,
                        state="support_anchor_handoff_reused",
                        frame_w=frame_w,
                        frame_h=frame_h,
                        bbox_xyxy=fallback_xyxy,
                        tracker_id=None,
                        lost_frames=self._lost_frames,
                        rejected_reasons=["initial_target_not_found"],
                        prediction_xyxy=prediction_xyxy,
                    )
                return None, _frame_diagnostic(
                    frame_index=frame_index,
                    frame_path=frame_path,
                    state="lost_reused",
                    frame_w=frame_w,
                    frame_h=frame_h,
                    bbox_xyxy=fallback_xyxy,
                    tracker_id=None,
                    lost_frames=self._lost_frames,
                    rejected_reasons=["initial_target_not_found"],
                )
            if strict_seed_xyxy is not None:
                self._clear_support_anchor_handoff()

        target_xyxy = self._xyxy_for_tracker_id(tracked, self._target_tracker_id)
        if target_xyxy is None:
            self._lost_frames += 1
            self._clear_pending_confirmed_partial_recovery()
            prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
            anchor_result = self._maybe_recover_from_support_anchor(
                support_anchor_bbox,
                support_anchor_xyxy,
                fallback_xyxy or seed_xyxy,
                prediction_xyxy,
                frame_index=frame_index,
                frame_path=frame_path,
                frame_w=frame_w,
                frame_h=frame_h,
                base_reasons=["target_track_missing"],
            )
            if anchor_result is not None:
                return anchor_result
            support_anchor_rejection = self._support_anchor_rejected_candidate_diagnostic(
                support_anchor_bbox,
                support_anchor_xyxy,
                fallback_xyxy or seed_xyxy,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            )
            if self._lost_frames >= _RELOCK_AFTER_LOST_FRAMES:
                if self._manual_lock_mode:
                    relocked = None
                    relock_rejections: list[dict[str, Any]] = []
                    _add_flag(self.quality_flags, PERSON_TRACKER_MANUAL_LOCK_RELOCK_BLOCKED_FLAG)
                else:
                    relocked, relock_rejections = self._select_relock_candidate(
                        tracked,
                        self._last_known_xyxy or seed_xyxy,
                        frame_w=frame_w,
                        frame_h=frame_h,
                    )
                if relocked is not None:
                    pending_relock_xyxy = self._xyxy_for_tracker_id(tracked, relocked)
                    if relocked == self._pending_relock_tracker_id:
                        self._pending_relock_count += 1
                    else:
                        self._pending_relock_tracker_id = relocked
                        self._pending_relock_count = 1
                    _add_flag(self.quality_flags, PERSON_TRACKER_RELOCK_PENDING_FLAG)

                    if self._pending_relock_count >= _RELOCK_CONFIRMATION_FRAMES:
                        self._target_tracker_id = relocked
                        target_xyxy = self._xyxy_for_tracker_id(tracked, relocked)
                        self._lost_frames = 0
                        self._clear_pending_relock()
                        self._clear_pending_detector_relock()
                        self._detector_relock_pending_identity_confirmation = False
                        _add_flag(self.quality_flags, PERSON_TRACKER_RELOCKED_FLAG)
                        self._last_known_xyxy = target_xyxy
                        return target_xyxy, _frame_diagnostic(
                            frame_index=frame_index,
                            frame_path=frame_path,
                            state="relocked",
                            frame_w=frame_w,
                            frame_h=frame_h,
                            bbox_xyxy=target_xyxy,
                            tracker_id=self._target_tracker_id,
                            candidate_tracker_id=relocked,
                            lost_frames=self._lost_frames,
                        )
                    return None, _frame_diagnostic(
                        frame_index=frame_index,
                        frame_path=frame_path,
                        state="relock_pending",
                        frame_w=frame_w,
                        frame_h=frame_h,
                        bbox_xyxy=fallback_xyxy,
                        tracker_id=self._target_tracker_id,
                        candidate_tracker_id=relocked,
                        lost_frames=self._lost_frames,
                        pending_relock_xyxy=pending_relock_xyxy,
                        rejected_candidates=relock_rejections,
                    )
                if (
                    self._lost_frames >= _LONG_LOST_REACQUIRE_AFTER_FRAMES
                    and self._pending_detector_relock_xyxy is not None
                ):
                    detector_xyxy, detector_diagnostic = self._handle_lost_with_detector_relock(
                        frame_bgr,
                        raw_boxes,
                        fallback_xyxy,
                        seed_xyxy,
                        frame_index=frame_index,
                        frame_path=frame_path,
                        frame_w=frame_w,
                        frame_h=frame_h,
                        base_reasons=["no_candidate_passed_relock_gate"],
                        prediction_xyxy=prediction_xyxy,
                        extra_rejected_candidates=[support_anchor_rejection] if support_anchor_rejection else None,
                    )
                    if detector_diagnostic.get("state") != "lost_reused":
                        return detector_xyxy, detector_diagnostic
                    detector_rejections = detector_diagnostic.get("rejected_candidates")
                    if isinstance(detector_rejections, list):
                        relock_rejections = [*relock_rejections, *detector_rejections]
                if support_anchor_rejection is not None:
                    relock_rejections = [support_anchor_rejection, *relock_rejections]
                _add_flag(self.quality_flags, PERSON_TRACKER_RELOCK_REJECTED_FLAG)
                self._clear_pending_relock()
                return None, _frame_diagnostic(
                    frame_index=frame_index,
                    frame_path=frame_path,
                    state="relock_rejected",
                    frame_w=frame_w,
                    frame_h=frame_h,
                    bbox_xyxy=fallback_xyxy,
                    tracker_id=self._target_tracker_id,
                    lost_frames=self._lost_frames,
                    rejected_reasons=(
                        ["manual_lock_relock_blocked"]
                        if self._manual_lock_mode
                        else ["no_candidate_passed_relock_gate"]
                    ),
                    rejected_candidates=relock_rejections,
                )
            if target_xyxy is None:
                return self._handle_lost_with_detector_relock(
                    frame_bgr,
                    raw_boxes,
                    fallback_xyxy,
                    seed_xyxy,
                    frame_index=frame_index,
                    frame_path=frame_path,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    base_reasons=["target_track_missing"],
                    prediction_xyxy=prediction_xyxy,
                )

        continuity_reasons = self._confirmed_track_rejection_reasons(
            target_xyxy,
            self._last_known_xyxy or seed_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        )
        if (
            continuity_reasons
            and not self._manual_lock_mode
            and self._same_track_scale_recovery_allowed(
                target_xyxy,
                self._last_known_xyxy or seed_xyxy,
                self._target_tracker_id,
                tracked,
                frame_w=frame_w,
                frame_h=frame_h,
            )
        ):
            continuity_reasons = [
                reason
                for reason in continuity_reasons
                if reason not in {"center_jump", "area_ratio", "aspect_ratio"}
            ]
        if (
            continuity_reasons
            and not self._manual_lock_mode
            and self._confirmed_partial_recovery_ready(
                target_xyxy,
                self._last_known_xyxy or seed_xyxy,
                continuity_reasons,
                frame_w=frame_w,
                frame_h=frame_h,
            )
        ):
            continuity_reasons = []
            _add_flag(self.quality_flags, PERSON_TRACKER_CONFIRMED_PARTIAL_RECOVERY_FLAG)
        if continuity_reasons:
            self._lost_frames += 1
            _add_flag(self.quality_flags, PERSON_TRACKER_CONTINUITY_REJECTED_FLAG)
            self._clear_pending_relock()
            prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
            anchor_result = self._maybe_recover_from_support_anchor(
                support_anchor_bbox,
                support_anchor_xyxy,
                self._last_known_xyxy or seed_xyxy,
                prediction_xyxy,
                frame_index=frame_index,
                frame_path=frame_path,
                frame_w=frame_w,
                frame_h=frame_h,
                base_reasons=["continuity_rejected", *continuity_reasons],
            )
            if anchor_result is not None:
                return anchor_result
            support_anchor_rejection = self._support_anchor_rejected_candidate_diagnostic(
                support_anchor_bbox,
                support_anchor_xyxy,
                self._last_known_xyxy or seed_xyxy,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            )
            rejected_track_candidate = _rejected_candidate_diagnostic(
                target_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
                tracker_id=self._target_tracker_id,
                reasons=continuity_reasons,
                reference_xyxy=self._last_known_xyxy or seed_xyxy,
                prediction_xyxy=prediction_xyxy,
            )
            rejected_candidates = [rejected_track_candidate]
            if support_anchor_rejection is not None:
                rejected_candidates.append(support_anchor_rejection)
            if self._has_alternative_detector_box(raw_boxes, target_xyxy, frame_w=frame_w, frame_h=frame_h):
                _add_flag(self.quality_flags, PERSON_TRACKER_CONTINUITY_DETECTOR_RELOCK_ATTEMPTED_FLAG)
                detector_xyxy, detector_diagnostic = self._handle_lost_with_detector_relock(
                    frame_bgr,
                    raw_boxes,
                    fallback_xyxy,
                    seed_xyxy,
                    frame_index=frame_index,
                    frame_path=frame_path,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    base_reasons=["continuity_rejected", *continuity_reasons],
                    prediction_xyxy=prediction_xyxy,
                    ignored_detector_xyxy=target_xyxy,
                    allow_local_zoom=False,
                    mark_relock_rejected_on_failure=False,
                )
                detector_state = str(detector_diagnostic.get("state") or "")
                if detector_state != "lost_reused":
                    detector_rejected_candidates = detector_diagnostic.get("rejected_candidates")
                    if isinstance(detector_rejected_candidates, list):
                        detector_diagnostic["rejected_candidates"] = [
                            rejected_track_candidate,
                            *detector_rejected_candidates,
                        ][:_MAX_DIAGNOSTIC_REJECTED_CANDIDATES]
                    else:
                        detector_diagnostic["rejected_candidates"] = [rejected_track_candidate]
                    detector_diagnostic["continuity_rejected_candidate_bbox"] = _xyxy_to_bbox(target_xyxy, frame_w, frame_h)
                    detector_diagnostic["continuity_rejected_reasons"] = list(continuity_reasons)
                    return detector_xyxy, detector_diagnostic

                detector_rejected_candidates = detector_diagnostic.get("rejected_candidates")
                if isinstance(detector_rejected_candidates, list):
                    rejected_candidates.extend(detector_rejected_candidates)
            return None, _frame_diagnostic(
                frame_index=frame_index,
                frame_path=frame_path,
                state="continuity_rejected",
                frame_w=frame_w,
                frame_h=frame_h,
                bbox_xyxy=fallback_xyxy,
                tracker_id=self._target_tracker_id,
                lost_frames=self._lost_frames,
                rejected_reasons=continuity_reasons,
                rejected_candidates=rejected_candidates,
                prediction_xyxy=prediction_xyxy,
                candidate_xyxy=target_xyxy,
                reference_xyxy=self._last_known_xyxy or seed_xyxy,
            )

        self._last_known_xyxy = target_xyxy
        self._record_accepted_bbox(frame_index, target_xyxy)
        self._lost_frames = 0
        self._clear_pending_relock()
        self._clear_pending_detector_relock()
        self._clear_pending_confirmed_partial_recovery()
        self._detector_relock_pending_identity_confirmation = False
        return target_xyxy, _frame_diagnostic(
            frame_index=frame_index,
            frame_path=frame_path,
            state="tracked",
            frame_w=frame_w,
            frame_h=frame_h,
            bbox_xyxy=target_xyxy,
            tracker_id=self._target_tracker_id,
            lost_frames=self._lost_frames,
        )

    def _support_anchor_xyxy(
        self,
        support_anchor: dict[str, Any] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> tuple[float, float, float, float] | None:
        if not isinstance(support_anchor, dict):
            return None
        bbox = support_anchor.get("bbox") if isinstance(support_anchor.get("bbox"), dict) else support_anchor
        if not isinstance(bbox, dict):
            return None
        try:
            return _bbox_to_xyxy(_normalize_bbox(bbox), frame_w, frame_h)
        except (TypeError, ValueError):
            return None

    def _support_anchor_confidence(self, support_anchor: dict[str, Any] | None) -> float | None:
        if not isinstance(support_anchor, dict):
            return None
        try:
            value = support_anchor.get("confidence")
            if value is None and isinstance(support_anchor.get("bbox"), dict):
                value = support_anchor.get("support_confidence")
            if value is None:
                return None
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        return confidence if confidence == confidence else None

    def _support_anchor_foreground_scale_jump(
        self,
        support_anchor_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if reference_xyxy is None:
            return False
        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        anchor_area = _xyxy_area(support_anchor_xyxy)
        if reference_area <= 0.0 or anchor_area <= 0.0:
            return False
        normalized_anchor_area = anchor_area / frame_area
        if normalized_anchor_area < _SUPPORT_ANCHOR_FOREGROUND_MIN_AREA:
            return False

        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        anchor_height = max(1.0, float(support_anchor_xyxy[3]) - float(support_anchor_xyxy[1]))
        normalized_anchor_height = anchor_height / max(float(frame_h), 1.0)
        if normalized_anchor_height < _SUPPORT_ANCHOR_FOREGROUND_MIN_HEIGHT:
            return False

        return (
            anchor_area / reference_area >= _SUPPORT_ANCHOR_FOREGROUND_MIN_AREA_RATIO
            and anchor_height / reference_height >= _SUPPORT_ANCHOR_FOREGROUND_MIN_HEIGHT_RATIO
        )

    def _support_anchor_rejection_reasons(
        self,
        support_anchor: dict[str, Any] | None,
        support_anchor_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> list[str]:
        if support_anchor_xyxy is None:
            return ["missing_support_anchor_bbox"]
        if self._manual_lock_mode:
            return ["manual_lock_support_anchor_blocked"]

        reasons: list[str] = []
        confidence = self._support_anchor_confidence(support_anchor)
        if confidence is not None and confidence < _SUPPORT_ANCHOR_MIN_CONFIDENCE:
            reasons.append("low_confidence")

        frame_area = max(float(frame_w * frame_h), 1.0)
        anchor_area = _xyxy_area(support_anchor_xyxy)
        normalized_anchor_area = anchor_area / frame_area
        if normalized_anchor_area <= 0.0 or normalized_anchor_area > _SUPPORT_ANCHOR_MAX_AREA:
            reasons.append("area")

        bbox = _xyxy_to_bbox(support_anchor_xyxy, frame_w, frame_h)
        anchor_height = float(bbox["height"])
        if anchor_height > _SUPPORT_ANCHOR_MAX_HEIGHT:
            reasons.append("height")
        aspect = _xyxy_aspect_ratio(support_anchor_xyxy)
        if not (_SUPPORT_ANCHOR_ASPECT_RANGE[0] <= aspect <= _SUPPORT_ANCHOR_ASPECT_RANGE[1]):
            reasons.append("aspect_ratio")

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        if reference_xyxy is not None:
            reference_area = _xyxy_area(reference_xyxy)
            if reference_area > 0.0:
                area_ratio = anchor_area / reference_area
                if (
                    area_ratio < _SUPPORT_ANCHOR_AREA_RATIO_RANGE[0]
                    or area_ratio > _SUPPORT_ANCHOR_AREA_RATIO_RANGE[1]
                ):
                    reasons.append("area_ratio")
            if _center_distance(support_anchor_xyxy, reference_xyxy) > frame_diagonal * _SUPPORT_ANCHOR_MAX_CENTER_RATIO:
                reasons.append("center_jump")
            if self._support_anchor_foreground_scale_jump(
                support_anchor_xyxy,
                reference_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                reasons.append("foreground_scale_jump")

        if prediction_xyxy is not None and _center_distance(
            support_anchor_xyxy,
            prediction_xyxy,
        ) > frame_diagonal * _SUPPORT_ANCHOR_MAX_PREDICTION_CENTER_RATIO:
            if reference_xyxy is None or _center_distance(
                support_anchor_xyxy,
                reference_xyxy,
            ) > frame_diagonal * _SUPPORT_ANCHOR_MAX_CENTER_RATIO:
                reasons.append("far_from_prediction")

        if reasons and self._support_anchor_wide_pose_recovery_allowed(
            support_anchor,
            support_anchor_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        ):
            reasons = [
                reason
                for reason in reasons
                if reason not in {"area", "height", "aspect_ratio", "area_ratio", "far_from_prediction"}
            ]

        return list(dict.fromkeys(reasons))

    def _support_anchor_wide_pose_recovery_allowed(
        self,
        support_anchor: dict[str, Any] | None,
        support_anchor_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        confidence = self._support_anchor_confidence(support_anchor)
        if confidence is not None and confidence < _SUPPORT_ANCHOR_MIN_CONFIDENCE:
            return False
        if reference_xyxy is None and prediction_xyxy is None:
            return False
        if reference_xyxy is not None and self._support_anchor_foreground_scale_jump(
            support_anchor_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        ):
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        frame_area = max(float(frame_w * frame_h), 1.0)
        anchor_area = _xyxy_area(support_anchor_xyxy)
        if anchor_area <= 0.0:
            return False
        normalized_anchor_area = anchor_area / frame_area
        if normalized_anchor_area > _SUPPORT_ANCHOR_WIDE_POSE_MAX_AREA:
            return False

        aspect = _xyxy_aspect_ratio(support_anchor_xyxy)
        if not (
            _SUPPORT_ANCHOR_WIDE_POSE_ASPECT_RANGE[0]
            <= aspect
            <= _SUPPORT_ANCHOR_WIDE_POSE_ASPECT_RANGE[1]
        ):
            return False

        if reference_xyxy is not None:
            reference_area = _xyxy_area(reference_xyxy)
            if reference_area <= 0.0:
                return False
            area_ratio = anchor_area / reference_area
            if area_ratio > _SUPPORT_ANCHOR_WIDE_POSE_MAX_AREA_RATIO:
                return False
            if _center_distance(support_anchor_xyxy, reference_xyxy) <= frame_diagonal * _SUPPORT_ANCHOR_WIDE_POSE_MAX_CENTER_RATIO:
                return True

        return bool(
            prediction_xyxy is not None
            and _center_distance(support_anchor_xyxy, prediction_xyxy)
            <= frame_diagonal * _SUPPORT_ANCHOR_WIDE_POSE_MAX_PREDICTION_CENTER_RATIO
        )

    def _support_anchor_is_usable(
        self,
        support_anchor: dict[str, Any] | None,
        support_anchor_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if support_anchor is None and support_anchor_xyxy is None:
            return False
        return not self._support_anchor_rejection_reasons(
            support_anchor,
            support_anchor_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        )

    def _support_anchor_rejected_candidate_diagnostic(
        self,
        support_anchor: dict[str, Any] | None,
        support_anchor_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> dict[str, Any] | None:
        if support_anchor_xyxy is None:
            return None
        reasons = self._support_anchor_rejection_reasons(
            support_anchor,
            support_anchor_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        )
        if not reasons:
            return None
        return _rejected_candidate_diagnostic(
            support_anchor_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            source="target_lock_support_anchor",
            confidence=self._support_anchor_confidence(support_anchor),
            reasons=reasons,
            reference_xyxy=reference_xyxy,
            prediction_xyxy=prediction_xyxy,
        )

    def _maybe_recover_from_support_anchor(
        self,
        support_anchor: dict[str, Any] | None,
        support_anchor_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_index: int,
        frame_path: Path | None,
        frame_w: int,
        frame_h: int,
        base_reasons: Sequence[str],
    ) -> tuple[tuple[float, float, float, float] | None, dict[str, Any]] | None:
        if support_anchor is None and support_anchor_xyxy is None:
            return None

        reasons = self._support_anchor_rejection_reasons(
            support_anchor,
            support_anchor_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        )
        if reasons:
            if "manual_lock_support_anchor_blocked" in reasons:
                _add_flag(self.quality_flags, PERSON_TRACKER_MANUAL_LOCK_SUPPORT_ANCHOR_BLOCKED_FLAG)
            _add_flag(self.quality_flags, PERSON_TRACKER_SUPPORT_ANCHOR_REJECTED_FLAG)
            return None

        assert support_anchor_xyxy is not None
        recovered_xyxy = tuple(float(value) for value in support_anchor_xyxy)
        self._last_known_xyxy = recovered_xyxy
        self._record_accepted_bbox(frame_index, recovered_xyxy)
        self._lost_frames = 0
        self._target_tracker_id = None
        self._clear_pending_relock()
        self._clear_pending_detector_relock()
        self._clear_pending_confirmed_partial_recovery()
        self._detector_relock_pending_identity_confirmation = False
        self._support_anchor_handoff_xyxy = recovered_xyxy
        self._support_anchor_handoff_frame_index = frame_index
        _add_flag(self.quality_flags, PERSON_TRACKER_SUPPORT_ANCHOR_RECOVERED_FLAG)
        return recovered_xyxy, _frame_diagnostic(
            frame_index=frame_index,
            frame_path=frame_path,
            state="support_anchor_recovered",
            frame_w=frame_w,
            frame_h=frame_h,
            bbox_xyxy=recovered_xyxy,
            tracker_id=self._target_tracker_id,
            lost_frames=self._lost_frames,
            rejected_reasons=list(base_reasons),
            prediction_xyxy=prediction_xyxy,
            relock_source="target_lock_support_anchor",
            candidate_confidence=self._support_anchor_confidence(support_anchor),
            candidate_xyxy=recovered_xyxy,
            reference_xyxy=reference_xyxy,
        )

    def _read_frame(self, frame_path: Path) -> np.ndarray:
        try:
            import cv2  # type: ignore
        except Exception as exc:  # pragma: no cover - cv2 is already a hard project dependency.
            raise PersonTrackerUnavailable("OpenCV is not available for person tracking.") from exc

        frame = cv2.imread(str(frame_path))
        if frame is None:
            raise RuntimeError(f"Could not read frame for person tracking: {frame_path}")
        return frame

    def _get_yolo_model(self) -> Any:
        if self._yolo_model is None:
            try:
                from ultralytics import YOLO  # type: ignore
            except Exception as exc:
                raise PersonTrackerUnavailable("ultralytics is not installed.") from exc
            self._yolo_model = YOLO(_resolve_yolo_model_path())
        return self._yolo_model

    def _get_tracker(self) -> Any:
        if self._tracker is None:
            if self._byte_tracker_factory is not None:
                self._tracker = self._byte_tracker_factory(self._effective_fps)
            else:
                self._tracker = _create_byte_tracker(self._effective_fps)
        return self._tracker

    def _detect(self, frame_bgr: np.ndarray, *, conf_threshold: float = _YOLO_CONF_THRESHOLD) -> list[tuple[float, float, float, float, float]]:
        model = self._get_yolo_model()
        results = model(frame_bgr, classes=[0], conf=conf_threshold, verbose=False)
        boxes: list[tuple[float, float, float, float, float]] = []
        for result in results:
            for box in getattr(result, "boxes", []):
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                boxes.append((float(x1), float(y1), float(x2), float(y2), conf))
        return boxes

    def _update_tracks(self, raw_boxes: Sequence[tuple[float, float, float, float, float]]) -> Any:
        try:
            import supervision as sv  # type: ignore
        except Exception as exc:
            raise PersonTrackerUnavailable("supervision is not installed.") from exc

        xyxy = np.array([[box[0], box[1], box[2], box[3]] for box in raw_boxes], dtype=np.float32)
        confidence = np.array([box[4] for box in raw_boxes], dtype=np.float32)
        class_id = np.zeros(len(raw_boxes), dtype=int)
        detections = sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)
        return self._get_tracker().update_with_detections(detections)

    def _record_centers(self, detections: Any) -> None:
        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is None:
            return
        for index, tracker_id in enumerate(tracker_ids):
            tid = int(tracker_id)
            history = self._center_history.setdefault(tid, [])
            history.append(_center(detections.xyxy[index]))
            if len(history) > _STATIC_HISTORY:
                del history[:-_STATIC_HISTORY]

    def _is_static_candidate(self, tracker_id: int, frame_w: int) -> bool:
        history = self._center_history.get(tracker_id, [])
        if len(history) < _STATIC_HISTORY:
            return False
        xs = [point[0] for point in history[-_STATIC_HISTORY:]]
        ys = [point[1] for point in history[-_STATIC_HISTORY:]]
        displacement = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        return displacement < frame_w * _STATIC_DISPLACEMENT_RATIO

    def _static_relock_candidate_is_near_reference(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
    ) -> bool:
        if reference_xyxy is None:
            return False
        reference_diagonal = max(_xyxy_diagonal(reference_xyxy), 1.0)
        distance = _center_distance(candidate_xyxy, reference_xyxy)
        if distance > reference_diagonal * _STATIC_RELOCK_NEAR_DIAGONAL_RATIO:
            return False
        return (
            _iou(candidate_xyxy, reference_xyxy) >= _STATIC_RELOCK_NEAR_IOU
            or _bbox_coverage(reference_xyxy, candidate_xyxy) >= _STATIC_RELOCK_NEAR_COVERAGE
            or _bbox_coverage(candidate_xyxy, reference_xyxy) >= _STATIC_RELOCK_NEAR_COVERAGE
        )

    def _clear_pending_relock(self) -> None:
        self._pending_relock_tracker_id = None
        self._pending_relock_count = 0

    def _clear_pending_detector_relock(self) -> None:
        self._pending_detector_relock_xyxy = None
        self._pending_detector_relock_source = None
        self._pending_detector_relock_count = 0

    def _clear_pending_confirmed_partial_recovery(self) -> None:
        self._pending_confirmed_partial_recovery_tracker_id = None
        self._pending_confirmed_partial_recovery_xyxy = None
        self._pending_confirmed_partial_recovery_count = 0

    def _clear_support_anchor_handoff(self) -> None:
        self._support_anchor_handoff_xyxy = None
        self._support_anchor_handoff_frame_index = None

    def _support_anchor_handoff_seed(self, frame_index: int) -> tuple[float, float, float, float] | None:
        if self._support_anchor_handoff_xyxy is None or self._support_anchor_handoff_frame_index is None:
            return None
        if frame_index - self._support_anchor_handoff_frame_index > _SUPPORT_ANCHOR_HANDOFF_FRAMES:
            self._clear_support_anchor_handoff()
            return None
        return self._support_anchor_handoff_xyxy

    def _candidate_matches_support_anchor_handoff(
        self,
        candidate_xyxy: Sequence[float],
        handoff_xyxy: Sequence[float],
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        if _center_distance(candidate_xyxy, handoff_xyxy) <= frame_diagonal * _SUPPORT_ANCHOR_HANDOFF_MAX_CENTER_RATIO:
            return True
        if _iou(candidate_xyxy, handoff_xyxy) >= _SUPPORT_ANCHOR_HANDOFF_MIN_IOU:
            return True
        return max(
            _bbox_coverage(handoff_xyxy, candidate_xyxy),
            _bbox_coverage(candidate_xyxy, handoff_xyxy),
        ) >= _SUPPORT_ANCHOR_HANDOFF_MIN_COVERAGE

    def _record_accepted_bbox(self, frame_index: int, xyxy: Sequence[float] | None) -> None:
        if xyxy is None:
            return
        self._accepted_xyxy_history.append((int(frame_index), tuple(float(value) for value in xyxy)))
        if len(self._accepted_xyxy_history) > _ACCEPTED_HISTORY:
            del self._accepted_xyxy_history[:-_ACCEPTED_HISTORY]

    def _predict_next_xyxy(self, frame_w: int, frame_h: int) -> tuple[float, float, float, float] | None:
        if len(self._accepted_xyxy_history) < 2:
            return self._last_known_xyxy
        first_index, first_bbox = self._accepted_xyxy_history[0]
        last_index, last_bbox = self._accepted_xyxy_history[-1]
        span = max(last_index - first_index, 1)
        steps = min(max(self._lost_frames, 1), _PREDICTION_MAX_LOST_STEPS)
        dx = (last_bbox[0] - first_bbox[0]) / span * steps
        dy = (last_bbox[1] - first_bbox[1]) / span * steps
        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        max_shift = frame_diagonal * _PREDICTION_MAX_CENTER_SHIFT_RATIO
        shift_distance = (dx**2 + dy**2) ** 0.5
        if shift_distance > max_shift > 0.0:
            scale = max_shift / shift_distance
            dx *= scale
            dy *= scale
        predicted = (last_bbox[0] + dx, last_bbox[1] + dy, last_bbox[2] + dx, last_bbox[3] + dy)
        return _clamp_xyxy(predicted, frame_w, frame_h)

    def _accepted_history_xyxy(self, *, exclude_last: bool = False) -> list[tuple[float, float, float, float]]:
        history = [bbox for _frame_index, bbox in self._accepted_xyxy_history]
        if exclude_last and history:
            return history[:-1]
        return history

    def _is_partial_to_full_recovery(
        self,
        candidate_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
        prediction_xyxy: Sequence[float] | None = None,
        exclude_latest_history: bool = False,
        require_anchor_support: bool = False,
    ) -> bool:
        return _is_plausible_partial_to_full_body_recovery(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            history_xyxy=self._accepted_history_xyxy(exclude_last=exclude_latest_history),
            prediction_xyxy=prediction_xyxy,
            require_anchor_support=require_anchor_support,
        )

    def _foreground_growth_has_history_support(
        self,
        candidate_xyxy: Sequence[float],
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        candidate_area = _xyxy_area(candidate_xyxy)
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        for history_xyxy in self._accepted_history_xyxy(exclude_last=True):
            history_area = _xyxy_area(history_xyxy)
            history_height = max(1.0, float(history_xyxy[3]) - float(history_xyxy[1]))
            if history_area < candidate_area * _FOREGROUND_GROWTH_HISTORY_MIN_AREA_RATIO:
                continue
            if history_height < candidate_height * _FOREGROUND_GROWTH_HISTORY_MIN_HEIGHT_RATIO:
                continue
            if _center_distance(candidate_xyxy, history_xyxy) <= frame_diagonal * _FOREGROUND_GROWTH_HISTORY_MAX_CENTER_RATIO:
                return True
            if _iou(candidate_xyxy, history_xyxy) >= _DETECTOR_RELOCK_MIN_IOU:
                return True
        return False

    def _is_unanchored_foreground_height_growth(
        self,
        candidate_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if candidate_xyxy is None or reference_xyxy is None:
            return False

        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False

        normalized_reference_area = reference_area / frame_area
        normalized_candidate_area = candidate_area / frame_area
        if normalized_reference_area < _FOREGROUND_GROWTH_REFERENCE_MIN_AREA:
            return False
        if normalized_candidate_area < _FOREGROUND_GROWTH_CANDIDATE_MIN_AREA:
            return False

        reference_width = max(1.0, float(reference_xyxy[2]) - float(reference_xyxy[0]))
        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        candidate_width = max(1.0, float(candidate_xyxy[2]) - float(candidate_xyxy[0]))
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        area_ratio = candidate_area / reference_area
        height_ratio = candidate_height / reference_height
        width_ratio = candidate_width / reference_width
        candidate_bbox = _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h)
        reference_bbox = _xyxy_to_bbox(reference_xyxy, frame_w, frame_h)
        candidate_height_norm = float(candidate_bbox["height"])
        candidate_aspect = _xyxy_aspect_ratio(candidate_xyxy)
        top_expansion = float(reference_bbox["y"]) - float(candidate_bbox["y"])
        bottom_expansion = (
            float(candidate_bbox["y"])
            + float(candidate_bbox["height"])
            - float(reference_bbox["y"])
            - float(reference_bbox["height"])
        )

        if area_ratio < _FOREGROUND_GROWTH_MIN_AREA_RATIO:
            return False
        if height_ratio < _FOREGROUND_GROWTH_MIN_HEIGHT_RATIO:
            return False
        if width_ratio > _FOREGROUND_GROWTH_MAX_WIDTH_RATIO:
            return False
        if candidate_height_norm < _FOREGROUND_GROWTH_CANDIDATE_MIN_HEIGHT:
            return False
        if candidate_aspect > _FOREGROUND_GROWTH_MAX_ASPECT:
            return False
        if (
            top_expansion < _FOREGROUND_GROWTH_MIN_TOP_EXPANSION
            and bottom_expansion < _FOREGROUND_GROWTH_MIN_BOTTOM_EXPANSION
        ):
            return False
        return not self._foreground_growth_has_history_support(
            candidate_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        )

    def _same_track_scale_recovery_allowed(
        self,
        candidate_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        tracker_id: int | None,
        detections: Any,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if candidate_xyxy is None or reference_xyxy is None or tracker_id is None:
            return False
        if len(self._accepted_xyxy_history) < 2:
            return False

        detection_index: int | None = None
        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is not None:
            for index, current_tracker_id in enumerate(tracker_ids):
                if int(current_tracker_id) == int(tracker_id):
                    detection_index = index
                    break
        if detection_index is None:
            return False

        confidence = self._detection_confidence(detections, detection_index)
        if confidence is None or confidence < _SAME_TRACK_SCALE_RECOVERY_MIN_CONFIDENCE:
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        center_history = self._center_history.get(int(tracker_id), [])
        recent_centers = center_history[-min(len(center_history), _STATIC_HISTORY) :]
        if len(recent_centers) < 2:
            return False
        xs = [point[0] for point in recent_centers]
        ys = [point[1] for point in recent_centers]
        displacement = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        if displacement < frame_diagonal * _SAME_TRACK_SCALE_RECOVERY_MIN_HISTORY_DISPLACEMENT_RATIO:
            return False

        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False
        normalized_candidate_area = candidate_area / frame_area
        if not (
            _SAME_TRACK_SCALE_RECOVERY_AREA_RANGE[0]
            <= normalized_candidate_area
            <= _SAME_TRACK_SCALE_RECOVERY_AREA_RANGE[1]
        ):
            return False

        area_ratio = candidate_area / reference_area
        if not (
            _SAME_TRACK_SCALE_RECOVERY_AREA_RATIO_RANGE[0]
            <= area_ratio
            <= _SAME_TRACK_SCALE_RECOVERY_AREA_RATIO_RANGE[1]
        ):
            return False

        aspect = _xyxy_aspect_ratio(candidate_xyxy)
        if not (
            _SAME_TRACK_SCALE_RECOVERY_ASPECT_RANGE[0]
            <= aspect
            <= _SAME_TRACK_SCALE_RECOVERY_ASPECT_RANGE[1]
        ):
            return False
        candidate_height = (float(candidate_xyxy[3]) - float(candidate_xyxy[1])) / max(float(frame_h), 1.0)
        if not (
            _SAME_TRACK_SCALE_RECOVERY_HEIGHT_RANGE[0]
            <= candidate_height
            <= _SAME_TRACK_SCALE_RECOVERY_HEIGHT_RANGE[1]
        ):
            return False

        prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
        anchors = [anchor for anchor in (prediction_xyxy, reference_xyxy) if anchor is not None]
        if not anchors:
            return False
        for anchor_xyxy in anchors:
            if (
                _center_distance(candidate_xyxy, anchor_xyxy)
                <= frame_diagonal * _SAME_TRACK_SCALE_RECOVERY_MAX_PREDICTION_DISTANCE_RATIO
            ):
                if _iou(candidate_xyxy, anchor_xyxy) >= _SAME_TRACK_SCALE_RECOVERY_MIN_PREDICTION_IOU:
                    return True
                if _bbox_coverage(anchor_xyxy, candidate_xyxy) >= _SAME_TRACK_SCALE_RECOVERY_MIN_PREDICTION_COVERAGE:
                    return True
                if _bbox_coverage(candidate_xyxy, anchor_xyxy) >= _SAME_TRACK_SCALE_RECOVERY_MIN_PREDICTION_COVERAGE:
                    return True
        return False

    def _continuity_rejection_reasons(
        self,
        candidate_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
        center_jump_ratio: float = _TRACK_CENTER_JUMP_RATIO,
        area_ratio_range: tuple[float, float] = _TRACK_AREA_RATIO_RANGE,
        aspect_ratio_range: tuple[float, float] = _TRACK_ASPECT_RATIO_RANGE,
        allow_seed_bootstrap: bool = False,
        require_anchor_supported_partial_to_full: bool = False,
        allow_partial_to_full_recovery: bool = True,
        allow_aspect_only_shape_change: bool = True,
    ) -> list[str]:
        if candidate_xyxy is None or reference_xyxy is None:
            return []

        reasons: list[str] = []
        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        distance = _center_distance(candidate_xyxy, reference_xyxy)
        reference_coverage = _bbox_coverage(reference_xyxy, candidate_xyxy)
        reference_width = max(1.0, float(reference_xyxy[2]) - float(reference_xyxy[0]))
        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        candidate_width = max(1.0, float(candidate_xyxy[2]) - float(candidate_xyxy[0]))
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        seed_bootstrap_context = allow_seed_bootstrap and not self._accepted_xyxy_history
        standard_bootstrap_allowed = (
            seed_bootstrap_context
            and reference_coverage >= _INITIAL_BOOTSTRAP_MIN_SEED_COVERAGE
            and distance <= frame_diagonal * _INITIAL_BOOTSTRAP_MAX_CENTER_DISTANCE_RATIO
            and candidate_width / reference_width <= _INITIAL_BOOTSTRAP_MAX_WIDTH_RATIO
            and candidate_height / reference_height <= _INITIAL_BOOTSTRAP_MAX_HEIGHT_RATIO
        )
        tiny_seed_bootstrap_allowed = (
            seed_bootstrap_context
            and _is_initial_tiny_seed_bootstrap_candidate(
                candidate_xyxy,
                reference_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
                distance=distance,
                frame_diagonal=frame_diagonal,
                candidate_width=candidate_width,
                reference_width=reference_width,
                candidate_height=candidate_height,
                reference_height=reference_height,
            )
        )
        bootstrap_allowed = standard_bootstrap_allowed or tiny_seed_bootstrap_allowed
        if distance > frame_diagonal * center_jump_ratio and not bootstrap_allowed:
            reasons.append("center_jump")

        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area > 0 and candidate_area > 0:
            area_ratio = candidate_area / reference_area
            if area_ratio < area_ratio_range[0] or area_ratio > area_ratio_range[1]:
                partial_to_full_allowed = (
                    allow_partial_to_full_recovery
                    and not bootstrap_allowed
                    and self._is_partial_to_full_recovery(
                        candidate_xyxy,
                        reference_xyxy,
                        frame_w=frame_w,
                        frame_h=frame_h,
                        prediction_xyxy=self._predict_next_xyxy(frame_w, frame_h),
                        exclude_latest_history=True,
                        require_anchor_support=require_anchor_supported_partial_to_full,
                    )
                )
                if not (
                    (bootstrap_allowed and area_ratio <= _INITIAL_BOOTSTRAP_MAX_AREA_RATIO)
                    or partial_to_full_allowed
                ):
                    reasons.append("area_ratio")

        reference_aspect = _xyxy_aspect_ratio(reference_xyxy)
        candidate_aspect = _xyxy_aspect_ratio(candidate_xyxy)
        if reference_aspect > 0 and candidate_aspect > 0:
            aspect_ratio = candidate_aspect / reference_aspect
            if aspect_ratio < aspect_ratio_range[0] or aspect_ratio > aspect_ratio_range[1]:
                aspect_shape_change_allowed = (
                    allow_aspect_only_shape_change
                    and not bootstrap_allowed
                    and not reasons
                    and _is_plausible_aspect_only_shape_change(
                        candidate_xyxy,
                        reference_xyxy,
                        frame_w=frame_w,
                        frame_h=frame_h,
                        center_jump_ratio=center_jump_ratio,
                    )
                )
                if not bootstrap_allowed and not aspect_shape_change_allowed:
                    reasons.append("aspect_ratio")
        if self._is_unanchored_foreground_height_growth(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        ):
            reasons.append("foreground_height_growth")
        return reasons

    def _confirmed_track_rejection_reasons(
        self,
        candidate_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> list[str]:
        return self._continuity_rejection_reasons(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            center_jump_ratio=(
                _MANUAL_LOCK_TRACK_CENTER_JUMP_RATIO
                if self._manual_lock_mode
                else _TRACK_CENTER_JUMP_RATIO
            ),
            allow_seed_bootstrap=True,
            require_anchor_supported_partial_to_full=self._detector_relock_pending_identity_confirmation,
            allow_partial_to_full_recovery=not self._manual_lock_mode,
            allow_aspect_only_shape_change=not self._manual_lock_mode,
        )

    def _confirmed_partial_recovery_ready(
        self,
        candidate_xyxy: Sequence[float] | None,
        reference_xyxy: Sequence[float] | None,
        reasons: Sequence[str],
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        tracker_id = self._target_tracker_id
        if tracker_id is None or candidate_xyxy is None or reference_xyxy is None:
            self._clear_pending_confirmed_partial_recovery()
            return False
        reason_set = set(reasons)
        if reason_set not in ({"area_ratio"}, {"area_ratio", "aspect_ratio"}):
            self._clear_pending_confirmed_partial_recovery()
            return False
        if self._detector_relock_pending_identity_confirmation and not self._is_partial_to_full_recovery(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            prediction_xyxy=self._predict_next_xyxy(frame_w, frame_h),
            exclude_latest_history=True,
            require_anchor_support=True,
        ):
            self._clear_pending_confirmed_partial_recovery()
            return False
        geometry_supported = self._confirmed_partial_recovery_geometry_supported(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        )
        if not geometry_supported and reason_set == {"area_ratio", "aspect_ratio"}:
            geometry_supported = self._confirmed_small_shape_recovery_geometry_supported(
                candidate_xyxy,
                reference_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            )
        if not geometry_supported:
            self._clear_pending_confirmed_partial_recovery()
            return False

        candidate_tuple = tuple(float(value) for value in candidate_xyxy)
        if (
            self._pending_confirmed_partial_recovery_tracker_id == tracker_id
            and self._pending_confirmed_partial_recovery_xyxy is not None
        ):
            pending_xyxy = self._pending_confirmed_partial_recovery_xyxy
            pending_diagonal = max(_xyxy_diagonal(pending_xyxy), 1.0)
            same_candidate = (
                _iou(candidate_tuple, pending_xyxy) >= _DETECTOR_RELOCK_CONFIRM_IOU
                or _center_distance(candidate_tuple, pending_xyxy)
                <= pending_diagonal * _DETECTOR_RELOCK_CONFIRM_DISTANCE_RATIO
            )
            if same_candidate:
                self._pending_confirmed_partial_recovery_count += 1
            else:
                self._pending_confirmed_partial_recovery_xyxy = candidate_tuple
                self._pending_confirmed_partial_recovery_count = 1
        else:
            self._pending_confirmed_partial_recovery_tracker_id = tracker_id
            self._pending_confirmed_partial_recovery_xyxy = candidate_tuple
            self._pending_confirmed_partial_recovery_count = 1

        return (
            self._pending_confirmed_partial_recovery_count
            >= _CONFIRMED_TRACK_PARTIAL_RECOVERY_CONFIRMATION_FRAMES
        )

    def _confirmed_partial_recovery_geometry_supported(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float],
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if not _is_plausible_partial_recovery_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h):
            return False

        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False
        normalized_reference_area = reference_area / frame_area
        normalized_candidate_area = candidate_area / frame_area
        if normalized_reference_area > _CONFIRMED_TRACK_PARTIAL_RECOVERY_REFERENCE_MAX_AREA:
            return False
        if not (
            _CONFIRMED_TRACK_PARTIAL_RECOVERY_CANDIDATE_AREA_RANGE[0]
            <= normalized_candidate_area
            <= _CONFIRMED_TRACK_PARTIAL_RECOVERY_CANDIDATE_AREA_RANGE[1]
        ):
            return False

        area_ratio = candidate_area / reference_area
        if not (
            _CONFIRMED_TRACK_PARTIAL_RECOVERY_AREA_RATIO_RANGE[0]
            <= area_ratio
            <= _CONFIRMED_TRACK_PARTIAL_RECOVERY_AREA_RATIO_RANGE[1]
        ):
            return False

        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        height_ratio = candidate_height / reference_height
        if not (
            _CONFIRMED_TRACK_PARTIAL_RECOVERY_HEIGHT_RATIO_RANGE[0]
            <= height_ratio
            <= _CONFIRMED_TRACK_PARTIAL_RECOVERY_HEIGHT_RATIO_RANGE[1]
        ):
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        return (
            _center_distance(candidate_xyxy, reference_xyxy)
            <= frame_diagonal * _CONFIRMED_TRACK_PARTIAL_RECOVERY_MAX_CENTER_RATIO
        )

    def _confirmed_small_shape_recovery_geometry_supported(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float],
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False
        normalized_reference_area = reference_area / frame_area
        normalized_candidate_area = candidate_area / frame_area
        if normalized_reference_area > _CONFIRMED_TRACK_PARTIAL_RECOVERY_REFERENCE_MAX_AREA:
            return False
        if not (
            _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_CANDIDATE_AREA_RANGE[0]
            <= normalized_candidate_area
            <= _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_CANDIDATE_AREA_RANGE[1]
        ):
            return False

        area_ratio = candidate_area / reference_area
        if not (
            _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_AREA_RATIO_RANGE[0]
            <= area_ratio
            <= _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_AREA_RATIO_RANGE[1]
        ):
            return False

        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        height_ratio = candidate_height / reference_height
        if not (
            _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_HEIGHT_RATIO_RANGE[0]
            <= height_ratio
            <= _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_HEIGHT_RATIO_RANGE[1]
        ):
            return False

        aspect = _xyxy_aspect_ratio(candidate_xyxy)
        if not (
            _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_ASPECT_RANGE[0]
            <= aspect
            <= _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_ASPECT_RANGE[1]
        ):
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        return (
            _center_distance(candidate_xyxy, reference_xyxy)
            <= frame_diagonal * _CONFIRMED_TRACK_SMALL_SHAPE_RECOVERY_MAX_CENTER_RATIO
        )

    def _detector_relock_rejection_reasons(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
        confidence: float,
        source: str = "full_frame_yolo_relock",
        relax_long_lost_single_candidate: bool = False,
    ) -> list[str]:
        reasons = self._continuity_rejection_reasons(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            center_jump_ratio=_DETECTOR_RELOCK_CENTER_JUMP_RATIO,
            area_ratio_range=_DETECTOR_RELOCK_AREA_RATIO_RANGE,
            aspect_ratio_range=_DETECTOR_RELOCK_ASPECT_RATIO_RANGE,
        )
        if confidence < _DETECTOR_RELOCK_MIN_CONFIDENCE:
            reasons.append("low_confidence")

        anchor_supported_partial_to_full = reference_xyxy is not None and self._is_partial_to_full_recovery(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            prediction_xyxy=prediction_xyxy,
            exclude_latest_history=True,
            require_anchor_support=True,
        )

        if source == "full_frame_yolo_relock" and not self._full_frame_detector_relock_has_identity_support(
            candidate_xyxy,
            reference_xyxy,
            prediction_xyxy,
        ):
            if not anchor_supported_partial_to_full:
                reasons.append("weak_identity_support")

        if reference_xyxy is not None:
            reference_distance = _center_distance(candidate_xyxy, reference_xyxy)
            reference_diagonal = max(_xyxy_diagonal(reference_xyxy), 1.0)
            reference_iou = _iou(candidate_xyxy, reference_xyxy)
            if (
                reference_iou < _DETECTOR_RELOCK_MIN_IOU
                and reference_distance > reference_diagonal * _DETECTOR_RELOCK_REFERENCE_DIAGONAL_RATIO
                and not anchor_supported_partial_to_full
            ):
                reasons.append("far_from_reference")

        if prediction_xyxy is not None:
            prediction_distance = _center_distance(candidate_xyxy, prediction_xyxy)
            prediction_diagonal = max(_xyxy_diagonal(prediction_xyxy), 1.0)
            prediction_iou = _iou(candidate_xyxy, prediction_xyxy)
            if (
                prediction_iou < _DETECTOR_RELOCK_MIN_IOU
                and prediction_distance > prediction_diagonal * _DETECTOR_RELOCK_REFERENCE_DIAGONAL_RATIO
                and not anchor_supported_partial_to_full
            ):
                reasons.append("far_from_prediction")

        if anchor_supported_partial_to_full:
            reasons = [reason for reason in reasons if reason not in {"area_ratio", "center_jump", "aspect_ratio"}]

        local_zoom_tiny_scale_recovery = source == "local_zoom_yolo_relock" and self._is_local_zoom_tiny_scale_recovery(
            candidate_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            confidence=confidence,
        )
        if local_zoom_tiny_scale_recovery and anchor_supported_partial_to_full:
            reasons = [reason for reason in reasons if reason in {"low_confidence"}]

        local_zoom_near_full_recovery = source == "local_zoom_yolo_relock" and self._is_local_zoom_near_full_recovery(
            candidate_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            confidence=confidence,
        )
        if local_zoom_near_full_recovery and set(reasons).issubset({"area_ratio"}):
            reasons = []

        near_prediction_scale_shrink = self._is_near_prediction_scale_shrink_recovery(
            candidate_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            confidence=confidence,
        )
        if near_prediction_scale_shrink and not any(
            reason in reasons
            for reason in {"center_jump", "weak_identity_support", "far_from_reference", "far_from_prediction"}
        ):
            reasons = [reason for reason in reasons if reason not in {"area_ratio", "aspect_ratio"}]

        if self._is_detector_relock_shrunk_fragment(
            candidate_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        ):
            reasons.append("shrunk_fragment")

        if (
            confidence >= _DETECTOR_RELOCK_SCALE_JUMP_MIN_CONFIDENCE
            and "aspect_ratio" not in reasons
            and "center_jump" not in reasons
            and "far_from_reference" not in reasons
            and "far_from_prediction" not in reasons
        ):
            frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
            distance_to_prediction = (
                _center_distance(candidate_xyxy, prediction_xyxy)
                if prediction_xyxy is not None
                else float("inf")
            )
            distance_to_reference = (
                _center_distance(candidate_xyxy, reference_xyxy)
                if reference_xyxy is not None
                else float("inf")
            )
            reference_area = _xyxy_area(reference_xyxy)
            prediction_area = _xyxy_area(prediction_xyxy)
            area_reference = prediction_area if prediction_area > 0 else reference_area
            area_ratio = _xyxy_area(candidate_xyxy) / max(area_reference, 1.0)
            reference_height = (
                max(1.0, float(prediction_xyxy[3]) - float(prediction_xyxy[1]))
                if prediction_xyxy is not None
                else (
                    max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
                    if reference_xyxy is not None
                    else 1.0
                )
            )
            candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
            height_ratio = candidate_height / reference_height
            if (
                min(distance_to_prediction, distance_to_reference) <= frame_diagonal * _DETECTOR_RELOCK_SCALE_JUMP_MAX_CENTER_RATIO
                and area_ratio <= _DETECTOR_RELOCK_SCALE_JUMP_MAX_AREA_RATIO
                and height_ratio <= _DETECTOR_RELOCK_SCALE_JUMP_MAX_HEIGHT_RATIO
            ):
                reasons = [reason for reason in reasons if reason != "area_ratio"]

        if self._lost_frames >= _LONG_LOST_REACQUIRE_AFTER_FRAMES and confidence >= _LONG_LOST_MIN_CONFIDENCE:
            if _is_plausible_human_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h):
                clearable_reasons = {"center_jump", "area_ratio", "aspect_ratio"}
                if source == "local_zoom_yolo_relock" or relax_long_lost_single_candidate:
                    clearable_reasons.update({"far_from_reference", "far_from_prediction"})
                if relax_long_lost_single_candidate:
                    clearable_reasons.add("weak_identity_support")
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in clearable_reasons
                ]

        return list(dict.fromkeys(reasons))

    def _is_detector_relock_shrunk_fragment(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if reference_xyxy is None:
            return False

        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False
        if reference_area / frame_area < _DETECTOR_RELOCK_SHRUNK_FRAGMENT_REFERENCE_MIN_AREA:
            return False

        candidate_width = max(1.0, float(candidate_xyxy[2]) - float(candidate_xyxy[0]))
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        normalized_width = candidate_width / max(float(frame_w), 1.0)
        area_ratio = candidate_area / reference_area
        height_ratio = candidate_height / reference_height
        if not (
            area_ratio <= _DETECTOR_RELOCK_SHRUNK_FRAGMENT_MAX_AREA_RATIO
            and height_ratio <= _DETECTOR_RELOCK_SHRUNK_FRAGMENT_MAX_HEIGHT_RATIO
            and normalized_width <= _DETECTOR_RELOCK_SHRUNK_FRAGMENT_MAX_WIDTH
        ):
            return False

        overlap_support = max(
            _iou(candidate_xyxy, reference_xyxy),
            _bbox_coverage(reference_xyxy, candidate_xyxy),
            _bbox_coverage(candidate_xyxy, reference_xyxy),
        )
        return overlap_support < _DETECTOR_RELOCK_SHRUNK_FRAGMENT_MAX_COVERAGE

    def _is_local_zoom_tiny_scale_recovery(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
        confidence: float,
    ) -> bool:
        if reference_xyxy is None:
            return False
        if confidence < _LOCAL_ZOOM_TINY_SCALE_RECOVERY_MIN_CONFIDENCE:
            return False

        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False
        normalized_reference_area = reference_area / frame_area
        normalized_candidate_area = candidate_area / frame_area
        if normalized_reference_area > _LOCAL_ZOOM_TINY_SCALE_RECOVERY_MAX_REFERENCE_AREA:
            return False
        if not (
            _LOCAL_ZOOM_TINY_SCALE_RECOVERY_AREA_RANGE[0]
            <= normalized_candidate_area
            <= _LOCAL_ZOOM_TINY_SCALE_RECOVERY_AREA_RANGE[1]
        ):
            return False

        area_ratio = candidate_area / reference_area
        if not (
            _LOCAL_ZOOM_TINY_SCALE_RECOVERY_AREA_RATIO_RANGE[0]
            <= area_ratio
            <= _LOCAL_ZOOM_TINY_SCALE_RECOVERY_AREA_RATIO_RANGE[1]
        ):
            return False

        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        height_ratio = candidate_height / reference_height
        if not (
            _LOCAL_ZOOM_TINY_SCALE_RECOVERY_HEIGHT_RATIO_RANGE[0]
            <= height_ratio
            <= _LOCAL_ZOOM_TINY_SCALE_RECOVERY_HEIGHT_RATIO_RANGE[1]
        ):
            return False

        aspect = _xyxy_aspect_ratio(candidate_xyxy)
        if not (
            _LOCAL_ZOOM_TINY_SCALE_RECOVERY_ASPECT_RANGE[0]
            <= aspect
            <= _LOCAL_ZOOM_TINY_SCALE_RECOVERY_ASPECT_RANGE[1]
        ):
            return False

        reference_coverage = _bbox_coverage(reference_xyxy, candidate_xyxy)
        prediction_coverage = _bbox_coverage(prediction_xyxy, candidate_xyxy) if prediction_xyxy is not None else 0.0
        if max(reference_coverage, prediction_coverage) < _LOCAL_ZOOM_TINY_SCALE_RECOVERY_MIN_REFERENCE_COVERAGE:
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        reference_distance = _center_distance(candidate_xyxy, reference_xyxy)
        prediction_distance = (
            _center_distance(candidate_xyxy, prediction_xyxy)
            if prediction_xyxy is not None
            else reference_distance
        )
        return min(reference_distance, prediction_distance) <= frame_diagonal * _LOCAL_ZOOM_TINY_SCALE_RECOVERY_MAX_CENTER_RATIO

    def _is_local_zoom_near_full_recovery(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
        confidence: float,
    ) -> bool:
        if reference_xyxy is None:
            return False
        if confidence < _LOCAL_ZOOM_NEAR_FULL_RECOVERY_MIN_CONFIDENCE:
            return False

        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False
        normalized_reference_area = reference_area / frame_area
        normalized_candidate_area = candidate_area / frame_area
        if normalized_reference_area > _LOCAL_ZOOM_NEAR_FULL_RECOVERY_MAX_REFERENCE_AREA:
            return False
        if not (
            _LOCAL_ZOOM_NEAR_FULL_RECOVERY_AREA_RANGE[0]
            <= normalized_candidate_area
            <= _LOCAL_ZOOM_NEAR_FULL_RECOVERY_AREA_RANGE[1]
        ):
            return False

        area_ratio = candidate_area / reference_area
        if not (
            _LOCAL_ZOOM_NEAR_FULL_RECOVERY_AREA_RATIO_RANGE[0]
            <= area_ratio
            <= _LOCAL_ZOOM_NEAR_FULL_RECOVERY_AREA_RATIO_RANGE[1]
        ):
            return False

        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        height_ratio = candidate_height / reference_height
        if not (
            _LOCAL_ZOOM_NEAR_FULL_RECOVERY_HEIGHT_RATIO_RANGE[0]
            <= height_ratio
            <= _LOCAL_ZOOM_NEAR_FULL_RECOVERY_HEIGHT_RATIO_RANGE[1]
        ):
            return False

        aspect = _xyxy_aspect_ratio(candidate_xyxy)
        if not (
            _LOCAL_ZOOM_NEAR_FULL_RECOVERY_ASPECT_RANGE[0]
            <= aspect
            <= _LOCAL_ZOOM_NEAR_FULL_RECOVERY_ASPECT_RANGE[1]
        ):
            return False
        if _iou(candidate_xyxy, reference_xyxy) < _LOCAL_ZOOM_NEAR_FULL_RECOVERY_MIN_IOU:
            return False

        anchors = [anchor for anchor in (prediction_xyxy, reference_xyxy) if anchor is not None]
        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        return any(
            _center_distance(candidate_xyxy, anchor_xyxy)
            <= frame_diagonal * _LOCAL_ZOOM_NEAR_FULL_RECOVERY_MAX_CENTER_RATIO
            for anchor_xyxy in anchors
        )

    def _is_near_prediction_scale_shrink_recovery(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
        confidence: float,
    ) -> bool:
        if confidence < _DETECTOR_RELOCK_NEAR_SHRINK_MIN_CONFIDENCE:
            return False
        anchors = [anchor for anchor in (prediction_xyxy, reference_xyxy) if anchor is not None]
        if not anchors:
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        frame_area = max(float(frame_w * frame_h), 1.0)
        candidate_area = _xyxy_area(candidate_xyxy)
        if candidate_area <= 0:
            return False

        bbox = _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h)
        aspect = _xyxy_aspect_ratio(candidate_xyxy)
        height = float(bbox["height"])
        normalized_area = candidate_area / frame_area
        if not (_LONG_LOST_AREA_RANGE[0] <= normalized_area <= _LONG_LOST_AREA_RANGE[1]):
            return False
        if not (_DETECTOR_RELOCK_NEAR_SHRINK_ASPECT_RANGE[0] <= aspect <= _DETECTOR_RELOCK_NEAR_SHRINK_ASPECT_RANGE[1]):
            return False
        if not (_DETECTOR_RELOCK_NEAR_SHRINK_HEIGHT_RANGE[0] <= height <= _DETECTOR_RELOCK_NEAR_SHRINK_HEIGHT_RANGE[1]):
            return False

        for anchor_xyxy in anchors:
            anchor_area = _xyxy_area(anchor_xyxy)
            if anchor_area <= 0:
                continue
            area_ratio = candidate_area / anchor_area
            if not (
                _DETECTOR_RELOCK_NEAR_SHRINK_AREA_RATIO_RANGE[0]
                <= area_ratio
                <= _DETECTOR_RELOCK_NEAR_SHRINK_AREA_RATIO_RANGE[1]
            ):
                continue
            if _center_distance(candidate_xyxy, anchor_xyxy) > frame_diagonal * _DETECTOR_RELOCK_NEAR_SHRINK_MAX_CENTER_RATIO:
                continue
            if _iou(candidate_xyxy, anchor_xyxy) >= _DETECTOR_RELOCK_NEAR_SHRINK_MIN_IOU:
                return True
            if _bbox_coverage(anchor_xyxy, candidate_xyxy) >= _DETECTOR_RELOCK_NEAR_SHRINK_MIN_COVERAGE:
                return True
            if _bbox_coverage(candidate_xyxy, anchor_xyxy) >= _DETECTOR_RELOCK_NEAR_SHRINK_MIN_COVERAGE:
                return True
        return False

    def _full_frame_detector_relock_has_identity_support(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
    ) -> bool:
        anchors = [anchor for anchor in (prediction_xyxy, reference_xyxy) if anchor is not None]
        if not anchors:
            return False

        for anchor_xyxy in anchors:
            anchor_diagonal = max(_xyxy_diagonal(anchor_xyxy), 1.0)
            if _center_distance(candidate_xyxy, anchor_xyxy) <= anchor_diagonal * _DETECTOR_RELOCK_IDENTITY_DISTANCE_RATIO:
                return True
            if _iou(candidate_xyxy, anchor_xyxy) >= _DETECTOR_RELOCK_MIN_IOU:
                return True
            if _bbox_coverage(anchor_xyxy, candidate_xyxy) >= _DETECTOR_RELOCK_IDENTITY_REFERENCE_COVERAGE:
                return True
            if _bbox_coverage(candidate_xyxy, anchor_xyxy) >= _DETECTOR_RELOCK_IDENTITY_CANDIDATE_COVERAGE:
                return True
        return False

    def _long_lost_pending_detector_relock_allowed(
        self,
        candidate_xyxy: Sequence[float],
        confidence: float,
        *,
        frame_w: int,
        frame_h: int,
        source: str,
    ) -> bool:
        if source != "full_frame_yolo_relock":
            return False
        if self._lost_frames < _LONG_LOST_REACQUIRE_AFTER_FRAMES:
            return False
        if confidence < _LONG_LOST_PENDING_DETECTOR_MIN_CONFIDENCE:
            return False
        if not self._is_same_detector_relock_candidate(candidate_xyxy, source):
            return False
        return _is_plausible_human_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h)

    def _select_detector_relock_candidate(
        self,
        boxes: Sequence[tuple[float, float, float, float, float]],
        *,
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        frame_w: int,
        frame_h: int,
        source: str,
        relax_long_lost_single_candidate: bool = False,
    ) -> tuple[tuple[float, float, float, float] | None, float | None, list[dict[str, Any]]]:
        if reference_xyxy is None and prediction_xyxy is None:
            return None, None, []

        rejected: list[dict[str, Any]] = []
        best_xyxy: tuple[float, float, float, float] | None = None
        best_confidence: float | None = None
        best_score = -1.0
        reference = prediction_xyxy or reference_xyxy
        diagonal = (frame_w**2 + frame_h**2) ** 0.5
        for raw_box in boxes:
            candidate_xyxy = _clamp_xyxy(raw_box[:4], frame_w, frame_h)
            confidence = float(raw_box[4])
            relax_identity = (
                relax_long_lost_single_candidate
                and source == "full_frame_yolo_relock"
                and self._long_lost_single_detector_reacquire_allowed(
                    boxes,
                    candidate_xyxy,
                    confidence,
                    frame_w=frame_w,
                    frame_h=frame_h,
                )
            )
            reasons = self._detector_relock_rejection_reasons(
                candidate_xyxy,
                reference_xyxy,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
                confidence=confidence,
                source=source,
                relax_long_lost_single_candidate=relax_identity,
            )
            if reasons and self._long_lost_pending_detector_relock_allowed(
                candidate_xyxy,
                confidence,
                frame_w=frame_w,
                frame_h=frame_h,
                source=source,
            ):
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in {"center_jump", "weak_identity_support", "far_from_reference", "far_from_prediction"}
                ]
            if reasons:
                rejected.append(
                    _rejected_candidate_diagnostic(
                        candidate_xyxy,
                        frame_w=frame_w,
                        frame_h=frame_h,
                        source=source,
                        confidence=confidence,
                        reasons=reasons,
                        reference_xyxy=reference_xyxy,
                        prediction_xyxy=prediction_xyxy,
                    )
                )
                continue

            distance = _center_distance(candidate_xyxy, reference) if reference is not None else 0.0
            score = (
                _iou(candidate_xyxy, prediction_xyxy)
                + _iou(candidate_xyxy, reference_xyxy)
                + max(0.0, 1.0 - distance / max(diagonal, 1.0)) * 0.2
                + confidence * 0.1
            )
            if score > best_score:
                best_xyxy = candidate_xyxy
                best_confidence = confidence
                best_score = score
        return best_xyxy, best_confidence, rejected

    def _local_zoom_relock_boxes(
        self,
        frame_bgr: np.ndarray,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> tuple[list[tuple[float, float, float, float, float]], list[int] | None]:
        if prediction_xyxy is None:
            return [], None
        left, top, right, bottom = _expand_xyxy(prediction_xyxy, frame_w, frame_h, _LOCAL_ZOOM_PADDING_RATIO)
        crop = frame_bgr[top:bottom, left:right]
        if crop.size <= 0:
            return [], [left, top, right, bottom]
        try:
            import cv2  # type: ignore
        except Exception:
            return [], [left, top, right, bottom]
        zoomed = cv2.resize(crop, None, fx=_LOCAL_ZOOM_SCALE, fy=_LOCAL_ZOOM_SCALE, interpolation=cv2.INTER_LINEAR)
        zoom_boxes = self._detect(zoomed, conf_threshold=_LOCAL_ZOOM_MIN_CONFIDENCE)
        mapped: list[tuple[float, float, float, float, float]] = []
        for x1, y1, x2, y2, confidence in zoom_boxes:
            mapped.append(
                (
                    left + x1 / _LOCAL_ZOOM_SCALE,
                    top + y1 / _LOCAL_ZOOM_SCALE,
                    left + x2 / _LOCAL_ZOOM_SCALE,
                    top + y2 / _LOCAL_ZOOM_SCALE,
                    confidence,
                )
            )
        return mapped, [left, top, right, bottom]

    def _is_same_detector_relock_candidate(self, candidate_xyxy: Sequence[float], source: str) -> bool:
        if self._pending_detector_relock_xyxy is None or self._pending_detector_relock_source != source:
            return False
        iou = _iou(candidate_xyxy, self._pending_detector_relock_xyxy)
        distance = _center_distance(candidate_xyxy, self._pending_detector_relock_xyxy)
        diagonal = max(_xyxy_diagonal(self._pending_detector_relock_xyxy), 1.0)
        return iou >= _DETECTOR_RELOCK_CONFIRM_IOU or distance <= diagonal * _DETECTOR_RELOCK_CONFIRM_DISTANCE_RATIO

    def _same_detector_box_as_rejected_track(
        self,
        candidate_xyxy: Sequence[float],
        rejected_track_xyxy: Sequence[float] | None,
    ) -> bool:
        if rejected_track_xyxy is None:
            return False
        if _iou(candidate_xyxy, rejected_track_xyxy) >= 0.55:
            return True
        rejected_area = _xyxy_area(rejected_track_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if rejected_area <= 0.0 or candidate_area <= 0.0:
            return False
        area_ratio = candidate_area / rejected_area
        rejected_diagonal = max(_xyxy_diagonal(rejected_track_xyxy), 1.0)
        return (
            0.50 <= area_ratio <= 2.0
            and _center_distance(candidate_xyxy, rejected_track_xyxy) <= rejected_diagonal * 0.25
        )

    def _has_alternative_detector_box(
        self,
        raw_boxes: Sequence[tuple[float, float, float, float, float]],
        rejected_track_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        return any(
            not self._same_detector_box_as_rejected_track(
                _clamp_xyxy(raw_box[:4], frame_w, frame_h),
                rejected_track_xyxy,
            )
            for raw_box in raw_boxes
        )

    def _confirm_detector_relock(
        self,
        candidate_xyxy: tuple[float, float, float, float],
        source: str,
        confidence: float | None,
        *,
        frame_index: int,
        frame_path: Path | None,
        frame_w: int,
        frame_h: int,
        fallback_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        local_crop_bounds: Sequence[int] | None,
        rejected_candidates: Sequence[dict[str, Any]],
    ) -> tuple[tuple[float, float, float, float] | None, dict[str, Any]]:
        if self._is_same_detector_relock_candidate(candidate_xyxy, source):
            self._pending_detector_relock_count += 1
        else:
            self._pending_detector_relock_xyxy = candidate_xyxy
            self._pending_detector_relock_source = source
            self._pending_detector_relock_count = 1

        _add_flag(self.quality_flags, PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG)
        pending_state = "local_zoom_yolo_relock_pending" if source == "local_zoom_yolo_relock" else "full_frame_yolo_relock_pending"
        if self._pending_detector_relock_count < _RELOCK_CONFIRMATION_FRAMES:
            return None, _frame_diagnostic(
                frame_index=frame_index,
                frame_path=frame_path,
                state=pending_state,
                frame_w=frame_w,
                frame_h=frame_h,
                bbox_xyxy=fallback_xyxy,
                tracker_id=self._target_tracker_id,
                lost_frames=self._lost_frames,
                rejected_candidates=rejected_candidates,
                prediction_xyxy=prediction_xyxy,
                pending_relock_xyxy=candidate_xyxy,
                relock_source=source,
                local_crop_bounds=local_crop_bounds,
                candidate_confidence=confidence,
            )

        self._last_known_xyxy = candidate_xyxy
        self._record_accepted_bbox(frame_index, candidate_xyxy)
        self._lost_frames = 0
        self._clear_pending_relock()
        self._clear_pending_detector_relock()
        self._target_tracker_id = None
        self._detector_relock_pending_identity_confirmation = True
        _add_flag(self.quality_flags, PERSON_TRACKER_DETECTOR_RELOCKED_FLAG)
        return candidate_xyxy, _frame_diagnostic(
            frame_index=frame_index,
            frame_path=frame_path,
            state="detector_relocked",
            frame_w=frame_w,
            frame_h=frame_h,
            bbox_xyxy=candidate_xyxy,
            tracker_id=self._target_tracker_id,
            lost_frames=self._lost_frames,
            rejected_candidates=rejected_candidates,
            prediction_xyxy=prediction_xyxy,
            relock_source=source,
            local_crop_bounds=local_crop_bounds,
            candidate_confidence=confidence,
            candidate_xyxy=candidate_xyxy,
            reference_xyxy=fallback_xyxy,
        )

    def _handle_lost_with_detector_relock(
        self,
        frame_bgr: np.ndarray,
        raw_boxes: Sequence[tuple[float, float, float, float, float]],
        fallback_xyxy: Sequence[float] | None,
        seed_xyxy: Sequence[float] | None,
        *,
        frame_index: int,
        frame_path: Path | None,
        frame_w: int,
        frame_h: int,
        base_reasons: Sequence[str],
        prediction_xyxy: Sequence[float] | None,
        ignored_detector_xyxy: Sequence[float] | None = None,
        allow_local_zoom: bool = True,
        mark_relock_rejected_on_failure: bool = True,
        extra_rejected_candidates: Sequence[dict[str, Any] | None] | None = None,
    ) -> tuple[tuple[float, float, float, float] | None, dict[str, Any]]:
        self._clear_pending_relock()
        reference_xyxy = self._last_known_xyxy or fallback_xyxy or seed_xyxy
        rejected_candidates: list[dict[str, Any]] = [
            item for item in (extra_rejected_candidates or []) if isinstance(item, dict)
        ]
        if self._manual_lock_mode:
            self._clear_pending_detector_relock()
            _add_flag(self.quality_flags, PERSON_TRACKER_MANUAL_LOCK_RELOCK_BLOCKED_FLAG)
            if mark_relock_rejected_on_failure:
                _add_flag(self.quality_flags, PERSON_TRACKER_RELOCK_REJECTED_FLAG)
            return None, _frame_diagnostic(
                frame_index=frame_index,
                frame_path=frame_path,
                state="lost_reused",
                frame_w=frame_w,
                frame_h=frame_h,
                bbox_xyxy=fallback_xyxy,
                tracker_id=self._target_tracker_id,
                lost_frames=self._lost_frames,
                rejected_reasons=["manual_lock_relock_blocked", *list(base_reasons)],
                rejected_candidates=rejected_candidates,
                prediction_xyxy=prediction_xyxy,
                relock_source="manual_lock",
            )
        base_reason_set = set(base_reasons)
        relax_full_frame_single = (
            "no_active_tracks" in base_reason_set
            or (
                "no_candidate_passed_relock_gate" in base_reason_set
                and self._pending_detector_relock_xyxy is not None
            )
        )
        full_frame_boxes = [
            raw_box
            for raw_box in raw_boxes
            if not self._same_detector_box_as_rejected_track(
                _clamp_xyxy(raw_box[:4], frame_w, frame_h),
                ignored_detector_xyxy,
            )
        ]
        candidate_xyxy, confidence, rejected = self._select_detector_relock_candidate(
            full_frame_boxes,
            reference_xyxy=reference_xyxy,
            prediction_xyxy=prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            source="full_frame_yolo_relock",
            relax_long_lost_single_candidate=relax_full_frame_single,
        )
        rejected_candidates.extend(rejected)
        if candidate_xyxy is not None:
            return self._confirm_detector_relock(
                candidate_xyxy,
                "full_frame_yolo_relock",
                confidence,
                frame_index=frame_index,
                frame_path=frame_path,
                frame_w=frame_w,
                frame_h=frame_h,
                fallback_xyxy=fallback_xyxy,
                prediction_xyxy=prediction_xyxy,
                local_crop_bounds=None,
                rejected_candidates=rejected_candidates,
            )

        local_crop_bounds: list[int] | None = None
        local_boxes: list[tuple[float, float, float, float, float]] = []
        if allow_local_zoom and prediction_xyxy is not None:
            _add_flag(self.quality_flags, PERSON_TRACKER_LOCAL_ZOOM_RELOCK_ATTEMPTED_FLAG)
            local_boxes, local_crop_bounds = self._local_zoom_relock_boxes(
                frame_bgr,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            )
            candidate_xyxy, confidence, rejected = self._select_detector_relock_candidate(
                local_boxes,
                reference_xyxy=reference_xyxy,
                prediction_xyxy=prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
                source="local_zoom_yolo_relock",
            )
            rejected_candidates.extend(rejected)
            if candidate_xyxy is not None:
                return self._confirm_detector_relock(
                    candidate_xyxy,
                    "local_zoom_yolo_relock",
                    confidence,
                    frame_index=frame_index,
                    frame_path=frame_path,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    fallback_xyxy=fallback_xyxy,
                    prediction_xyxy=prediction_xyxy,
                    local_crop_bounds=local_crop_bounds,
                    rejected_candidates=rejected_candidates,
                )
            _add_flag(self.quality_flags, PERSON_TRACKER_LOCAL_ZOOM_RELOCK_REJECTED_FLAG)

        self._clear_pending_detector_relock()
        if mark_relock_rejected_on_failure:
            _add_flag(self.quality_flags, PERSON_TRACKER_RELOCK_REJECTED_FLAG)
        return None, _frame_diagnostic(
            frame_index=frame_index,
            frame_path=frame_path,
            state="lost_reused",
            frame_w=frame_w,
            frame_h=frame_h,
            bbox_xyxy=fallback_xyxy,
            tracker_id=self._target_tracker_id,
            lost_frames=self._lost_frames,
            rejected_reasons=list(base_reasons),
            rejected_candidates=rejected_candidates,
            prediction_xyxy=prediction_xyxy,
            relock_source="local_zoom_yolo_relock" if local_boxes else "full_frame_yolo_relock",
            local_crop_bounds=local_crop_bounds,
        )

    def _relock_rejection_reasons(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> list[str]:
        reasons = self._continuity_rejection_reasons(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            center_jump_ratio=_RELOCK_CENTER_JUMP_RATIO,
            area_ratio_range=_RELOCK_AREA_RATIO_RANGE,
            aspect_ratio_range=_RELOCK_ASPECT_RATIO_RANGE,
        )
        if reference_xyxy is not None:
            iou = _iou(candidate_xyxy, reference_xyxy)
            distance = _center_distance(candidate_xyxy, reference_xyxy)
            previous_diagonal = max(_xyxy_diagonal(reference_xyxy), 1.0)
            partial_to_full_allowed = self._is_partial_to_full_recovery(
                candidate_xyxy,
                reference_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
                prediction_xyxy=self._predict_next_xyxy(frame_w, frame_h),
                exclude_latest_history=True,
            )
            if (
                iou < _RELOCK_MIN_IOU
                and distance > previous_diagonal * _RELOCK_PREVIOUS_DIAGONAL_RATIO
                and not partial_to_full_allowed
            ):
                reasons.append("low_iou_and_far_from_previous_bbox")
        return reasons

    def _select_target(
        self,
        detections: Any,
        seed_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
        allow_static_filter: bool,
        support_anchor_handoff_xyxy: Sequence[float] | None = None,
        manual_lock_mode: bool = False,
    ) -> int | None:
        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is None:
            return None

        best_id: int | None = None
        best_score = -1.0
        diagonal = (frame_w**2 + frame_h**2) ** 0.5
        for index, tracker_id in enumerate(tracker_ids):
            tid = int(tracker_id)
            xyxy = tuple(float(value) for value in detections.xyxy[index])
            if allow_static_filter and self._is_static_candidate(tid, frame_w):
                continue
            if support_anchor_handoff_xyxy is not None and not self._candidate_matches_support_anchor_handoff(
                xyxy,
                support_anchor_handoff_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                continue
            if seed_xyxy is not None:
                distance = _center_distance(xyxy, seed_xyxy)
                if self._lost_frames > 0 and distance > diagonal * _MAX_RELOCK_DISTANCE_RATIO:
                    continue
                seed_coverage = _bbox_coverage(seed_xyxy, xyxy)
                candidate_coverage = _bbox_coverage(xyxy, seed_xyxy)
                if (
                    manual_lock_mode
                    and _iou(xyxy, seed_xyxy) < _MANUAL_LOCK_SELECT_MIN_IOU
                    and seed_coverage < _MANUAL_LOCK_SELECT_MIN_SEED_COVERAGE
                    and candidate_coverage < _MANUAL_LOCK_SELECT_MIN_CANDIDATE_COVERAGE
                ):
                    _add_flag(self.quality_flags, PERSON_TRACKER_MANUAL_LOCK_IDENTITY_REJECTED_FLAG)
                    continue
                score = (
                    _iou(xyxy, seed_xyxy) * 0.45
                    + seed_coverage * 0.45
                    + candidate_coverage * 0.05
                    + max(0.0, 1.0 - distance / max(diagonal, 1.0)) * 0.15
                )
            else:
                cx, cy = _center(xyxy)
                frame_center_distance = ((cx - frame_w / 2.0) ** 2 + (cy - frame_h / 2.0) ** 2) ** 0.5
                score = 1.0 - frame_center_distance / max(diagonal / 2.0, 1.0)
            if score > best_score:
                best_id = tid
                best_score = score
        return best_id

    def _select_relock_candidate(
        self,
        detections: Any,
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> tuple[int | None, list[dict[str, Any]]]:
        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is None or reference_xyxy is None:
            return None, []

        best_id: int | None = None
        best_score = -1.0
        rejected: list[dict[str, Any]] = []
        diagonal = (frame_w**2 + frame_h**2) ** 0.5
        prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
        confidence_values = getattr(detections, "confidence", None)
        for index, tracker_id in enumerate(tracker_ids):
            tid = int(tracker_id)
            xyxy = tuple(float(value) for value in detections.xyxy[index])
            confidence: float | None = None
            if confidence_values is not None and index < len(confidence_values):
                try:
                    confidence = float(confidence_values[index])
                except (TypeError, ValueError):
                    confidence = None
            reasons: list[str] = []
            if self._is_static_candidate(tid, frame_w) and not self._static_relock_candidate_is_near_reference(xyxy, reference_xyxy):
                reasons.append("static_candidate")
            reasons.extend(self._relock_rejection_reasons(xyxy, reference_xyxy, frame_w=frame_w, frame_h=frame_h))
            if (
                reasons
                and self._lost_frames >= _LONG_LOST_REACQUIRE_AFTER_FRAMES
                and self._long_lost_reacquire_allowed(detections, index, frame_w=frame_w, frame_h=frame_h)
            ):
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in {"center_jump", "area_ratio", "aspect_ratio"}
                ]
                foreground_scale_jump = self._long_lost_moving_candidate_is_foreground_scale_jump(
                    xyxy,
                    reference_xyxy,
                    frame_w=frame_w,
                    frame_h=frame_h,
                )
                if (
                    self._long_lost_moving_reacquire_allowed(detections, index, frame_w=frame_w, frame_h=frame_h)
                    and not foreground_scale_jump
                ):
                    reasons = [
                        reason
                        for reason in reasons
                        if reason != "low_iou_and_far_from_previous_bbox"
                    ]
                elif foreground_scale_jump:
                    reasons.append("foreground_scale_jump")
            if reasons and self._long_lost_stable_small_reacquire_allowed(
                detections,
                index,
                reference_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in {"center_jump", "area_ratio", "aspect_ratio", "low_iou_and_far_from_previous_bbox"}
                ]
            if reasons and self._long_lost_stable_moving_small_reacquire_allowed(
                detections,
                index,
                reference_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in {"center_jump", "area_ratio", "aspect_ratio", "low_iou_and_far_from_previous_bbox"}
                ]
            if reasons and self._small_body_relock_recovery_allowed(
                detections,
                index,
                reference_xyxy,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in {"center_jump", "area_ratio", "aspect_ratio", "low_iou_and_far_from_previous_bbox"}
                ]
            if reasons:
                rejected.append(
                    _rejected_candidate_diagnostic(
                        xyxy,
                        frame_w=frame_w,
                        frame_h=frame_h,
                        tracker_id=tid,
                        confidence=confidence,
                        reasons=reasons,
                        reference_xyxy=reference_xyxy,
                        prediction_xyxy=prediction_xyxy,
                    )
                )
                continue

            distance = _center_distance(xyxy, reference_xyxy)
            score = _iou(xyxy, reference_xyxy) + max(0.0, 1.0 - distance / max(diagonal, 1.0)) * 0.2
            if score > best_score:
                best_id = tid
                best_score = score
        return best_id, rejected

    def _long_lost_reacquire_allowed(self, detections: Any, index: int, *, frame_w: int, frame_h: int) -> bool:
        confidence = getattr(detections, "confidence", None)
        if confidence is not None and index < len(confidence):
            try:
                if float(confidence[index]) < _LONG_LOST_MIN_CONFIDENCE:
                    return False
            except (TypeError, ValueError):
                return False

        xyxy = tuple(float(value) for value in detections.xyxy[index])
        bbox = _xyxy_to_bbox(xyxy, frame_w, frame_h)
        area = float(bbox["width"]) * float(bbox["height"])
        aspect = float(bbox["width"]) / max(float(bbox["height"]), MANUAL_BBOX_MIN_SIDE)
        height = float(bbox["height"])
        if not (_LONG_LOST_AREA_RANGE[0] <= area <= _LONG_LOST_AREA_RANGE[1]):
            return False
        if not (_LONG_LOST_ASPECT_RANGE[0] <= aspect <= _LONG_LOST_ASPECT_RANGE[1]):
            return False
        if not (_LONG_LOST_HEIGHT_RANGE[0] <= height <= _LONG_LOST_HEIGHT_RANGE[1]):
            return False

        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is None:
            return False
        history = self._center_history.get(int(tracker_ids[index]), [])
        return len(history) >= 2 or confidence is not None

    def _long_lost_single_detector_reacquire_allowed(
        self,
        boxes: Sequence[tuple[float, float, float, float, float]],
        candidate_xyxy: Sequence[float],
        confidence: float,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if self._lost_frames < _LONG_LOST_REACQUIRE_AFTER_FRAMES:
            return False
        if confidence < _LONG_LOST_SINGLE_DETECTOR_MIN_CONFIDENCE:
            return False
        if not _is_plausible_human_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h):
            return False

        plausible_count = 0
        for raw_box in boxes:
            raw_confidence = float(raw_box[4])
            if raw_confidence < _LONG_LOST_MIN_CONFIDENCE:
                continue
            raw_xyxy = _clamp_xyxy(raw_box[:4], frame_w, frame_h)
            if _is_plausible_human_xyxy(raw_xyxy, frame_w=frame_w, frame_h=frame_h):
                plausible_count += 1
                if plausible_count > 1:
                    return False
        return plausible_count == 1

    def _long_lost_moving_reacquire_allowed(self, detections: Any, index: int, *, frame_w: int, frame_h: int) -> bool:
        if self._lost_frames < _LONG_LOST_REACQUIRE_AFTER_FRAMES:
            return False
        if not self._long_lost_reacquire_allowed(detections, index, frame_w=frame_w, frame_h=frame_h):
            return False

        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is None:
            return False
        history = self._center_history.get(int(tracker_ids[index]), [])
        if len(history) < 2:
            return False
        recent = history[-min(len(history), _STATIC_HISTORY) :]
        xs = [point[0] for point in recent]
        ys = [point[1] for point in recent]
        displacement = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        return displacement >= frame_diagonal * _LONG_LOST_MOVING_DISPLACEMENT_RATIO

    def _long_lost_moving_candidate_is_foreground_scale_jump(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if reference_xyxy is None:
            return False
        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False
        normalized_reference_area = reference_area / frame_area
        normalized_candidate_area = candidate_area / frame_area
        if (
            normalized_reference_area > _LONG_LOST_MOVING_FOREGROUND_REFERENCE_MAX_AREA
            or normalized_candidate_area < _LONG_LOST_MOVING_FOREGROUND_MIN_AREA
        ):
            return False

        reference_height = max(1.0, float(reference_xyxy[3]) - float(reference_xyxy[1]))
        candidate_height = max(1.0, float(candidate_xyxy[3]) - float(candidate_xyxy[1]))
        normalized_candidate_height = candidate_height / max(float(frame_h), 1.0)
        if normalized_candidate_height < _LONG_LOST_MOVING_FOREGROUND_MIN_HEIGHT:
            return False
        area_ratio = candidate_area / reference_area
        height_ratio = candidate_height / reference_height
        if (
            area_ratio < _LONG_LOST_MOVING_FOREGROUND_MIN_AREA_RATIO
            or height_ratio < _LONG_LOST_MOVING_FOREGROUND_MIN_HEIGHT_RATIO
        ):
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        if _center_distance(candidate_xyxy, reference_xyxy) < frame_diagonal * _LONG_LOST_MOVING_FOREGROUND_MIN_CENTER_RATIO:
            return False
        return max(
            _iou(candidate_xyxy, reference_xyxy),
            _bbox_coverage(reference_xyxy, candidate_xyxy),
            _bbox_coverage(candidate_xyxy, reference_xyxy),
        ) < _LONG_LOST_MOVING_FOREGROUND_MAX_OVERLAP

    def _long_lost_stable_small_reacquire_allowed(
        self,
        detections: Any,
        index: int,
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if self._lost_frames < _LONG_LOST_STABLE_SMALL_REACQUIRE_AFTER_FRAMES or reference_xyxy is None:
            return False

        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is None:
            return False
        tracker_id = int(tracker_ids[index])
        history = self._center_history.get(tracker_id, [])
        if len(history) < _LONG_LOST_STABLE_SMALL_HISTORY_FRAMES:
            return False

        confidence = self._detection_confidence(detections, index)
        if confidence is None or confidence < _LONG_LOST_STABLE_SMALL_MIN_CONFIDENCE:
            return False

        candidate_xyxy = tuple(float(value) for value in detections.xyxy[index])
        if not self._long_lost_stable_small_geometry_supported(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        ):
            return False

        supported_count = 0
        for candidate_index in range(len(detections.xyxy)):
            candidate_confidence = self._detection_confidence(detections, candidate_index)
            if candidate_confidence is None or candidate_confidence < _LONG_LOST_STABLE_SMALL_MIN_CONFIDENCE:
                continue
            other_xyxy = tuple(float(value) for value in detections.xyxy[candidate_index])
            if self._long_lost_stable_small_geometry_supported(
                other_xyxy,
                reference_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                supported_count += 1
                if supported_count > 1:
                    return False
        return supported_count == 1

    def _long_lost_stable_small_geometry_supported(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float],
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False

        normalized_reference_area = reference_area / frame_area
        normalized_candidate_area = candidate_area / frame_area
        if normalized_reference_area > _LONG_LOST_STABLE_SMALL_REFERENCE_MAX_AREA:
            return False
        if not (
            _LONG_LOST_STABLE_SMALL_AREA_RANGE[0]
            <= normalized_candidate_area
            <= _LONG_LOST_STABLE_SMALL_AREA_RANGE[1]
        ):
            return False

        area_ratio = candidate_area / reference_area
        if not (
            _LONG_LOST_STABLE_SMALL_AREA_RATIO_RANGE[0]
            <= area_ratio
            <= _LONG_LOST_STABLE_SMALL_AREA_RATIO_RANGE[1]
        ):
            return False

        bbox = _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h)
        aspect = _xyxy_aspect_ratio(candidate_xyxy)
        height = float(bbox["height"])
        return (
            _LONG_LOST_STABLE_SMALL_ASPECT_RANGE[0] <= aspect <= _LONG_LOST_STABLE_SMALL_ASPECT_RANGE[1]
            and _LONG_LOST_STABLE_SMALL_HEIGHT_RANGE[0] <= height <= _LONG_LOST_STABLE_SMALL_HEIGHT_RANGE[1]
        )

    def _long_lost_stable_moving_small_reacquire_allowed(
        self,
        detections: Any,
        index: int,
        reference_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if self._lost_frames < _LONG_LOST_STABLE_MOVING_SMALL_REACQUIRE_AFTER_FRAMES or reference_xyxy is None:
            return False

        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is None:
            return False
        tracker_id = int(tracker_ids[index])
        if not self._long_lost_stable_moving_small_history_supported(
            tracker_id,
            frame_w=frame_w,
            frame_h=frame_h,
        ):
            return False

        confidence = self._detection_confidence(detections, index)
        if confidence is None or confidence < _LONG_LOST_STABLE_MOVING_SMALL_MIN_CONFIDENCE:
            return False

        candidate_xyxy = tuple(float(value) for value in detections.xyxy[index])
        if not self._long_lost_stable_moving_small_geometry_supported(
            candidate_xyxy,
            reference_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        ):
            return False

        supported_count = 0
        for candidate_index in range(len(detections.xyxy)):
            candidate_confidence = self._detection_confidence(detections, candidate_index)
            if candidate_confidence is None or candidate_confidence < _LONG_LOST_STABLE_MOVING_SMALL_MIN_CONFIDENCE:
                continue
            other_tracker_id = int(tracker_ids[candidate_index])
            if not self._long_lost_stable_moving_small_history_supported(
                other_tracker_id,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                continue
            other_xyxy = tuple(float(value) for value in detections.xyxy[candidate_index])
            if self._long_lost_stable_moving_small_geometry_supported(
                other_xyxy,
                reference_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                supported_count += 1
                if supported_count > 1:
                    return False
        return supported_count == 1

    def _long_lost_stable_moving_small_history_supported(
        self,
        tracker_id: int,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        history = self._center_history.get(tracker_id, [])
        if len(history) < _LONG_LOST_STABLE_MOVING_SMALL_HISTORY_FRAMES:
            return False
        recent = history[-_LONG_LOST_STABLE_MOVING_SMALL_HISTORY_FRAMES:]
        xs = [point[0] for point in recent]
        ys = [point[1] for point in recent]
        displacement = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        return displacement >= frame_diagonal * _LONG_LOST_STABLE_MOVING_SMALL_MIN_DISPLACEMENT_RATIO

    def _long_lost_stable_moving_small_geometry_supported(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float],
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        frame_area = max(float(frame_w * frame_h), 1.0)
        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False

        normalized_reference_area = reference_area / frame_area
        normalized_candidate_area = candidate_area / frame_area
        if normalized_reference_area > _LONG_LOST_STABLE_MOVING_SMALL_MAX_REFERENCE_AREA:
            return False
        if not (
            _LONG_LOST_STABLE_MOVING_SMALL_AREA_RANGE[0]
            <= normalized_candidate_area
            <= _LONG_LOST_STABLE_MOVING_SMALL_AREA_RANGE[1]
        ):
            return False

        area_ratio = candidate_area / reference_area
        if not (
            _LONG_LOST_STABLE_MOVING_SMALL_AREA_RATIO_RANGE[0]
            <= area_ratio
            <= _LONG_LOST_STABLE_MOVING_SMALL_AREA_RATIO_RANGE[1]
        ):
            return False

        bbox = _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h)
        aspect = _xyxy_aspect_ratio(candidate_xyxy)
        height = float(bbox["height"])
        if not (
            _LONG_LOST_STABLE_MOVING_SMALL_ASPECT_RANGE[0]
            <= aspect
            <= _LONG_LOST_STABLE_MOVING_SMALL_ASPECT_RANGE[1]
            and _LONG_LOST_STABLE_MOVING_SMALL_HEIGHT_RANGE[0]
            <= height
            <= _LONG_LOST_STABLE_MOVING_SMALL_HEIGHT_RANGE[1]
        ):
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        return (
            _center_distance(candidate_xyxy, reference_xyxy)
            <= frame_diagonal * _LONG_LOST_STABLE_MOVING_SMALL_MAX_CENTER_RATIO
        )

    def _small_body_relock_recovery_allowed(
        self,
        detections: Any,
        index: int,
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if self._lost_frames < _RELOCK_AFTER_LOST_FRAMES or reference_xyxy is None:
            return False

        confidence = self._detection_confidence(detections, index)
        if confidence is None or confidence < _SMALL_BODY_RELOCK_MIN_CONFIDENCE:
            return False

        candidate_xyxy = tuple(float(value) for value in detections.xyxy[index])
        if not self._small_body_relock_geometry_supported(
            candidate_xyxy,
            reference_xyxy,
            prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
        ):
            return False

        supported_count = 0
        for candidate_index in range(len(detections.xyxy)):
            candidate_confidence = self._detection_confidence(detections, candidate_index)
            if candidate_confidence is None or candidate_confidence < _SMALL_BODY_RELOCK_MIN_CONFIDENCE:
                continue
            other_xyxy = tuple(float(value) for value in detections.xyxy[candidate_index])
            if self._small_body_relock_geometry_supported(
                other_xyxy,
                reference_xyxy,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
            ):
                supported_count += 1
                if supported_count > 1:
                    return False
        return supported_count == 1

    def _detection_confidence(self, detections: Any, index: int) -> float | None:
        confidence = getattr(detections, "confidence", None)
        if confidence is None or index >= len(confidence):
            return None
        try:
            return float(confidence[index])
        except (TypeError, ValueError):
            return None

    def _small_body_relock_geometry_supported(
        self,
        candidate_xyxy: Sequence[float],
        reference_xyxy: Sequence[float],
        prediction_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
    ) -> bool:
        if not _is_plausible_human_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h):
            return False

        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area <= 0.0 or candidate_area <= 0.0:
            return False
        area_ratio = candidate_area / reference_area
        if not (
            _SMALL_BODY_RELOCK_AREA_RATIO_RANGE[0]
            <= area_ratio
            <= _SMALL_BODY_RELOCK_AREA_RATIO_RANGE[1]
        ):
            return False

        frame_diagonal = (frame_w**2 + frame_h**2) ** 0.5
        anchors = [reference_xyxy]
        if prediction_xyxy is not None:
            anchors.append(prediction_xyxy)
        return min(_center_distance(candidate_xyxy, anchor_xyxy) for anchor_xyxy in anchors) <= (
            frame_diagonal * _SMALL_BODY_RELOCK_MAX_CENTER_RATIO
        )

    def _xyxy_for_tracker_id(self, detections: Any, target_tracker_id: int) -> tuple[float, float, float, float] | None:
        tracker_ids = getattr(detections, "tracker_id", None)
        if tracker_ids is None:
            return None
        for index, tracker_id in enumerate(tracker_ids):
            if int(tracker_id) == target_tracker_id:
                return tuple(float(value) for value in detections.xyxy[index])
        return None


def _create_byte_tracker(effective_fps: float) -> Any:
    try:
        import supervision as sv  # type: ignore
    except Exception as exc:
        raise PersonTrackerUnavailable("supervision is not installed.") from exc

    tracker_cls = getattr(sv, "ByteTrack", None) or getattr(sv, "ByteTracker", None)
    if tracker_cls is None:
        raise PersonTrackerUnavailable("supervision ByteTrack API is not available.")

    kwargs = {
        "track_activation_threshold": _TRACK_ACTIVATION_THRESHOLD,
        "lost_track_buffer": _LOST_TRACK_BUFFER,
        "minimum_matching_threshold": _MINIMUM_MATCHING_THRESHOLD,
        "frame_rate": max(int(round(effective_fps)), 1),
    }
    try:
        return tracker_cls(**kwargs)
    except TypeError:
        legacy_kwargs = {
            "track_thresh": _TRACK_ACTIVATION_THRESHOLD,
            "track_buffer": _LOST_TRACK_BUFFER,
            "match_thresh": _MINIMUM_MATCHING_THRESHOLD,
            "frame_rate": max(int(round(effective_fps)), 1),
        }
        return tracker_cls(**legacy_kwargs)


def _resolve_yolo_model_path() -> str:
    configured_path = os.getenv(_YOLO_MODEL_PATH_ENV, "").strip()
    if configured_path:
        candidate = Path(configured_path)
        if candidate.exists():
            return str(candidate)
        if configured_path.startswith(("/", "\\")):
            project_candidate = PROJECT_ROOT / configured_path.lstrip("/\\")
            if project_candidate.exists():
                return str(project_candidate)
        elif not candidate.is_absolute():
            project_candidate = PROJECT_ROOT / candidate
            if project_candidate.exists():
                return str(project_candidate)
        return configured_path
    if _YOLO_MOUNTED_MODEL_PATH.exists():
        return str(_YOLO_MOUNTED_MODEL_PATH)
    return _YOLO_MODEL_NAME


def _zoomed_content_crop_bounds(frame_bgr: np.ndarray) -> tuple[int, int, int, int]:
    frame_h, frame_w = frame_bgr.shape[:2]
    left = 0
    right = frame_w
    try:
        import cv2  # type: ignore

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        content_columns = np.flatnonzero(gray.mean(axis=0) > _ZOOMED_CONTENT_COLUMN_BRIGHTNESS)
        if len(content_columns) > 0:
            candidate_left = int(content_columns[0])
            candidate_right = int(content_columns[-1]) + 1
            if (candidate_right - candidate_left) >= frame_w * _ZOOMED_CONTENT_MIN_WIDTH_RATIO:
                left = candidate_left
                right = candidate_right
    except Exception:
        left = 0
        right = frame_w

    top = int(frame_h * _ZOOMED_CONTENT_TOP_RATIO)
    bottom = int(frame_h * _ZOOMED_CONTENT_BOTTOM_RATIO)
    if bottom <= top:
        top = 0
        bottom = frame_h
    return left, top, right, bottom


def _detect_zoomed_content_person_boxes(
    tracker: PersonBBoxTracker,
    frame_bgr: np.ndarray,
    *,
    min_confidence: float,
) -> tuple[list[tuple[float, float, float, float, float]], list[int] | None]:
    try:
        import cv2  # type: ignore
    except Exception:
        return [], None

    frame_h, frame_w = frame_bgr.shape[:2]
    left, top, right, bottom = _zoomed_content_crop_bounds(frame_bgr)
    crop = frame_bgr[top:bottom, left:right]
    if crop.size <= 0:
        return [], [left, top, right, bottom]

    zoomed = cv2.resize(
        crop,
        None,
        fx=_ZOOMED_CONTENT_PREVIEW_SCALE,
        fy=_ZOOMED_CONTENT_PREVIEW_SCALE,
        interpolation=cv2.INTER_CUBIC,
    )
    zoom_boxes = tracker._detect(zoomed, conf_threshold=min_confidence)
    mapped: list[tuple[float, float, float, float, float]] = []
    for x1, y1, x2, y2, confidence in zoom_boxes:
        mapped.append(
            _clamp_xyxy(
                (
                    left + x1 / _ZOOMED_CONTENT_PREVIEW_SCALE,
                    top + y1 / _ZOOMED_CONTENT_PREVIEW_SCALE,
                    left + x2 / _ZOOMED_CONTENT_PREVIEW_SCALE,
                    top + y2 / _ZOOMED_CONTENT_PREVIEW_SCALE,
                ),
                frame_w,
                frame_h,
            )
            + (confidence,)
        )
    return mapped, [left, top, right, bottom]


def get_person_tracker_runtime_status() -> dict[str, Any]:
    dependency_status: dict[str, bool] = {"ultralytics": False, "supervision": False, "torchvision": False}
    dependency_errors: dict[str, str] = {}
    try:
        import ultralytics  # type: ignore  # noqa: F401

        dependency_status["ultralytics"] = True
    except Exception as exc:  # noqa: BLE001
        dependency_errors["ultralytics"] = f"{type(exc).__name__}: {exc}"
    try:
        import supervision as sv  # type: ignore

        dependency_status["supervision"] = bool(getattr(sv, "ByteTrack", None) or getattr(sv, "ByteTracker", None))
        if not dependency_status["supervision"]:
            dependency_errors["supervision"] = "ByteTrack API is not available"
    except Exception as exc:  # noqa: BLE001
        dependency_errors["supervision"] = f"{type(exc).__name__}: {exc}"
    try:
        import torchvision  # type: ignore  # noqa: F401

        dependency_status["torchvision"] = True
    except Exception as exc:  # noqa: BLE001
        dependency_errors["torchvision"] = f"{type(exc).__name__}: {exc}"

    configured_path = os.getenv(_YOLO_MODEL_PATH_ENV, "").strip()
    mounted_exists = _YOLO_MOUNTED_MODEL_PATH.exists()
    model_path = _resolve_yolo_model_path()
    model_exists = Path(model_path).exists() if model_path != _YOLO_MODEL_NAME else False
    dependencies_ready = all(dependency_status.values())
    if configured_path:
        reason = "configured" if model_exists else "missing_model_file"
        source = "env"
    elif mounted_exists:
        reason = "mounted_default"
        source = "mounted_default"
    else:
        reason = "auto_download_fallback"
        source = "ultralytics_auto_download"
    if not dependencies_ready:
        reason = "missing_dependencies"
    return {
        "mode": "yolo_bytetrack",
        "configured": bool(configured_path),
        "model_path": model_path,
        "model_exists": model_exists,
        "mounted_default_path": str(_YOLO_MOUNTED_MODEL_PATH),
        "mounted_default_exists": mounted_exists,
        "env_var": _YOLO_MODEL_PATH_ENV,
        "source": source,
        "reason": reason,
        "dependencies_ready": dependencies_ready,
        "dependency_status": dependency_status,
        "dependency_errors": dependency_errors,
    }


def detect_person_candidates(
    frame_path: Path,
    *,
    min_confidence: float = _YOLO_CONF_THRESHOLD,
    include_zoomed_small_targets: bool = False,
) -> list[dict[str, Any]]:
    """Detect person candidates in a single preview frame for target-lock bootstrap."""

    tracker = PersonBBoxTracker()
    frame = tracker._read_frame(frame_path)
    frame_h, frame_w = frame.shape[:2]
    raw_boxes: list[tuple[tuple[float, float, float, float, float], str, list[int] | None]] = [
        (raw_box, "yolo_preview", None)
        for raw_box in tracker._detect(frame, conf_threshold=min_confidence)
    ]
    if include_zoomed_small_targets:
        zoom_boxes, crop_bounds = _detect_zoomed_content_person_boxes(
            tracker,
            frame,
            min_confidence=min_confidence,
        )
        raw_boxes.extend((raw_box, "yolo_zoomed_content", crop_bounds) for raw_box in zoom_boxes)

    candidates: list[dict[str, Any]] = []
    for index, (raw_box, source, crop_bounds) in enumerate(raw_boxes, start=1):
        x1, y1, x2, y2, confidence = raw_box
        xyxy = _clamp_xyxy((x1, y1, x2, y2), frame_w, frame_h)
        bbox = _xyxy_to_bbox(xyxy, frame_w, frame_h)
        area = float(bbox.get("width", 0.0)) * float(bbox.get("height", 0.0))
        candidate = {
            "id": f"candidate_{index}",
            "bbox": bbox,
            "confidence": round(float(confidence), 4),
            "source": source,
            "area": round(area, 6),
        }
        if crop_bounds is not None:
            candidate["zoom_crop_bounds"] = crop_bounds
            candidate["zoom_scale"] = _ZOOMED_CONTENT_PREVIEW_SCALE
        candidates.append(candidate)
    candidates.sort(key=lambda item: (float(item.get("confidence", 0.0)), float(item.get("area", 0.0))), reverse=True)
    return candidates


def _track_forward(
    frame_paths: Sequence[Path],
    initial_bbox: dict[str, Any],
    *,
    effective_fps: float | None,
    manual_lock_mode: bool = False,
) -> tuple[list[dict[str, float]], list[str]]:
    tracked, flags, _ = _track_forward_detailed(
        frame_paths,
        initial_bbox,
        effective_fps=effective_fps,
        manual_lock_mode=manual_lock_mode,
    )
    return tracked, flags


def _track_forward_detailed(
    frame_paths: Sequence[Path],
    initial_bbox: dict[str, Any],
    *,
    effective_fps: float | None,
    support_anchor_bboxes_by_frame: dict[int, dict[str, Any]] | None = None,
    manual_lock_mode: bool = False,
) -> tuple[list[dict[str, float]], list[str], list[dict[str, Any]]]:
    tracker = PersonBBoxTracker(effective_fps=effective_fps, manual_lock_mode=manual_lock_mode)
    return tracker.track_sequence_detailed(
        frame_paths,
        initial_bbox,
        support_anchor_bboxes_by_frame=support_anchor_bboxes_by_frame,
    )


def track_person_bbox(
    frame_paths: Sequence[Path],
    initial_bbox: dict[str, Any],
    *,
    initial_frame_index: int = 0,
    effective_fps: float | None = None,
    manual_lock_mode: bool = False,
) -> tuple[list[dict[str, float]], list[str]]:
    """Track the selected person across sampled frames using YOLO + ByteTrack.

    Returns normalized bboxes compatible with pose.extract_pose(..., bbox_per_frame=...).
    Optional dependency failures are raised as PersonTrackerUnavailable so callers can
    fall back to the existing CSRT tracker.
    """

    frames = list(frame_paths)
    if not frames:
        return [], []

    normalized_initial = _normalize_bbox(initial_bbox)
    start_index = max(0, min(int(initial_frame_index or 0), len(frames) - 1))
    if start_index == 0:
        return _track_forward(
            frames,
            normalized_initial,
            effective_fps=effective_fps,
            manual_lock_mode=manual_lock_mode,
        )

    backward_frames = list(reversed(frames[: start_index + 1]))
    backward_tracked, backward_flags = _track_forward(
        backward_frames,
        normalized_initial,
        effective_fps=effective_fps,
        manual_lock_mode=manual_lock_mode,
    )
    forward_tracked, forward_flags = _track_forward(
        frames[start_index:],
        normalized_initial,
        effective_fps=effective_fps,
        manual_lock_mode=manual_lock_mode,
    )
    tracked = list(reversed(backward_tracked))[0:-1] + forward_tracked
    flags = list(dict.fromkeys([*backward_flags, *forward_flags, PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG]))
    return tracked, flags


def track_person_bbox_detailed(
    frame_paths: Sequence[Path],
    initial_bbox: dict[str, Any],
    *,
    initial_frame_index: int = 0,
    effective_fps: float | None = None,
    support_anchor_bboxes_by_frame: dict[int, dict[str, Any]] | None = None,
    manual_lock_mode: bool = False,
) -> tuple[list[dict[str, float]], list[str], list[dict[str, Any]]]:
    """Detailed variant of track_person_bbox for analysis/debug diagnostics."""

    frames = list(frame_paths)
    if not frames:
        return [], [], []

    normalized_initial = _normalize_bbox(initial_bbox)
    start_index = max(0, min(int(initial_frame_index or 0), len(frames) - 1))
    if start_index == 0:
        return _track_forward_detailed(
            frames,
            normalized_initial,
            effective_fps=effective_fps,
            support_anchor_bboxes_by_frame=support_anchor_bboxes_by_frame,
            manual_lock_mode=manual_lock_mode,
        )

    backward_frames = list(reversed(frames[: start_index + 1]))
    support_by_frame = support_anchor_bboxes_by_frame if isinstance(support_anchor_bboxes_by_frame, dict) else {}
    backward_support = {
        start_index - frame_index: anchor
        for frame_index, anchor in support_by_frame.items()
        if 0 <= frame_index <= start_index
    }
    forward_support = {
        frame_index - start_index: anchor
        for frame_index, anchor in support_by_frame.items()
        if start_index <= frame_index < len(frames)
    }
    backward_tracked, backward_flags, backward_diagnostics = _track_forward_detailed(
        backward_frames,
        normalized_initial,
        effective_fps=effective_fps,
        support_anchor_bboxes_by_frame=backward_support,
        manual_lock_mode=manual_lock_mode,
    )
    forward_tracked, forward_flags, forward_diagnostics = _track_forward_detailed(
        frames[start_index:],
        normalized_initial,
        effective_fps=effective_fps,
        support_anchor_bboxes_by_frame=forward_support,
        manual_lock_mode=manual_lock_mode,
    )
    tracked = list(reversed(backward_tracked))[0:-1] + forward_tracked
    diagnostics = list(reversed(backward_diagnostics))[0:-1] + forward_diagnostics
    for frame_index, diagnostic in enumerate(diagnostics):
        diagnostic.pop("sequence_summary", None)
        diagnostic["frame_index"] = frame_index
        if frame_index < len(frames):
            diagnostic["frame"] = frames[frame_index].name
    summary = _loss_recovery_summary(diagnostics)
    if diagnostics:
        diagnostics[-1]["sequence_summary"] = summary
    raw_flags = [*backward_flags, *forward_flags, PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG]
    if not summary.get("final_unrecovered"):
        raw_flags = [flag for flag in raw_flags if flag != PERSON_TRACKER_FINAL_UNRECOVERED_FLAG]
    if summary.get("transient_loss_recovered"):
        raw_flags.append(PERSON_TRACKER_TRANSIENT_LOSS_RECOVERED_FLAG)
    if summary.get("final_unrecovered"):
        raw_flags.append(PERSON_TRACKER_FINAL_UNRECOVERED_FLAG)
    flags = list(dict.fromkeys(raw_flags))
    return tracked, flags, diagnostics
