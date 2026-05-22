from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any

from app.services.smoothing import smooth_keypoint_sequence
from app.services.target_lock import MANUAL_BBOX_MIN_SIDE, extract_pose_target_bbox


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


LANDMARK_NAMES = [
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
]

POSE_CONNECTIONS = [
    [11, 12],
    [11, 13],
    [13, 15],
    [12, 14],
    [14, 16],
    [11, 23],
    [12, 24],
    [23, 24],
    [23, 25],
    [25, 27],
    [27, 29],
    [29, 31],
    [24, 26],
    [26, 28],
    [28, 30],
    [30, 32],
    [0, 11],
    [0, 12],
]

_POSE_MODE_LOGGED = False
_POSE_MIN_ACCEPT_SCORE = 0.15
_POSE_CROP_PADDING_RATIO = 0.75
_POSE_PREDICTED_CROP_PADDING_RATIO = 1.15
_TRACKER_CANDIDATE_MIN_AREA_RATIO = 0.20
_TRACKER_CANDIDATE_MAX_AREA_RATIO = 6.0
_TRACKER_CANDIDATE_MIN_WIDTH_RATIO = 0.25
_TRACKER_CANDIDATE_MAX_WIDTH_RATIO = 4.0
_TRACKER_CANDIDATE_MIN_HEIGHT_RATIO = 0.25
_TRACKER_CANDIDATE_MAX_HEIGHT_RATIO = 4.0
_TRACKER_CANDIDATE_MIN_IOU = 0.10
_TRACKER_CANDIDATE_MIN_TRACKER_COVERAGE = 0.35
_TRACKER_CANDIDATE_MAX_CENTER_DISTANCE = 0.12
_MULTI_POSE_MAX_AREA_RATIO = 2.5
_MULTI_POSE_MAX_WIDTH_RATIO = 2.4
_MULTI_POSE_MAX_HEIGHT_RATIO = 2.8
_MULTI_POSE_MIN_IOU = 0.12
_MULTI_POSE_MIN_TRACKER_COVERAGE = 0.45
_KEYPOINT_VISIBILITY_THRESHOLD = 0.35
_KEYPOINT_ROI_PADDING_RATIO = 0.65
_KEYPOINT_MIN_ROI_COVERAGE = 0.42
_KEYPOINT_MIN_CORE_ROI_COVERAGE = 0.50
_KEYPOINT_STRICT_MIN_CORE_COUNT = 3
_KEYPOINT_STRICT_SMALL_TRACKER_HEIGHT = 0.14
_KEYPOINT_STRICT_MIN_CORE_COVERAGE = 0.75
_CROP_KEYPOINT_MIN_TRACKER_COVERAGE = 0.18
_TEMPORAL_CORE_JUMP_LIMIT = 0.16
_TRACKER_PREDICTION_HISTORY = 5
_MAX_DISPLAY_INTERPOLATION_GAP = 2
_MAX_DIAGNOSTIC_POSE_REJECTIONS = 6

CORE_KEYPOINT_IDS = [11, 12, 23, 24]


def _get_pose_runtime_config() -> tuple[int, str]:
    return int(os.getenv("POSE_NUM_POSES", "4")), os.getenv("MEDIAPIPE_POSE_TASK_PATH", "").strip()


def _resolve_model_path(task_model_path: str) -> Path | None:
    if not task_model_path:
        return None

    configured_path = Path(task_model_path)
    candidates: list[Path] = [configured_path]
    if task_model_path.startswith(("/", "\\")):
        candidates.append(PROJECT_ROOT / task_model_path.lstrip("/\\"))
    elif not configured_path.is_absolute():
        candidates.append(PROJECT_ROOT / configured_path)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[-1]


def get_pose_runtime_status() -> dict[str, Any]:
    num_poses, task_model_path = _get_pose_runtime_config()
    configured = bool(task_model_path)
    model_path = _resolve_model_path(task_model_path) if configured else None
    exists = bool(model_path and model_path.exists())
    if configured and exists:
        mode = "multi_pose"
        reason = "configured"
    elif configured:
        mode = "fallback_single_pose"
        reason = "missing_model_file"
    else:
        mode = "fallback_single_pose"
        reason = "model_path_not_set"

    return {
        "mode": mode,
        "configured": configured,
        "model_path": task_model_path or None,
        "model_exists": exists,
        "num_poses": num_poses,
        "reason": reason,
    }


def _empty_payload() -> dict[str, Any]:
    return {
        "connections": POSE_CONNECTIONS,
        "frames": [],
        "pose_diagnostics": {
            "mode": "empty",
            "total_frames": 0,
            "tracked_frames": 0,
            "lost_frames": 0,
            "low_confidence_frames": 0,
            "multi_pose_frames": 0,
            "single_pose_crop_frames": 0,
            "candidate_count_histogram": {},
            "frames": [],
        },
    }


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _crop_bounds(
    image_width: int,
    image_height: int,
    bbox: dict[str, float] | None,
    *,
    padding_ratio: float = 0.0,
) -> tuple[int, int, int, int]:
    if not bbox:
        return 0, 0, image_width, image_height
    normalized_x = max(0.0, min(1.0, float(bbox.get("x", 0.0))))
    normalized_y = max(0.0, min(1.0, float(bbox.get("y", 0.0))))
    normalized_width = max(MANUAL_BBOX_MIN_SIDE, min(1.0, float(bbox.get("width", 1.0))))
    normalized_height = max(MANUAL_BBOX_MIN_SIDE, min(1.0, float(bbox.get("height", 1.0))))
    if padding_ratio > 0.0:
        center_x = normalized_x + normalized_width / 2.0
        center_y = normalized_y + normalized_height / 2.0
        normalized_width = min(1.0, normalized_width * (1.0 + padding_ratio * 2.0))
        normalized_height = min(1.0, normalized_height * (1.0 + padding_ratio * 2.0))
        normalized_x = max(0.0, min(1.0 - normalized_width, center_x - normalized_width / 2.0))
        normalized_y = max(0.0, min(1.0 - normalized_height, center_y - normalized_height / 2.0))
    x = int(normalized_x * image_width)
    y = int(normalized_y * image_height)
    width = int(normalized_width * image_width)
    height = int(normalized_height * image_height)
    right = min(image_width, x + max(width, 1))
    bottom = min(image_height, y + max(height, 1))
    return x, y, right, bottom


def _bbox_from_landmarks(landmarks: list[Any]) -> dict[str, float] | None:
    xs = [float(landmark.x) for landmark in landmarks]
    ys = [float(landmark.y) for landmark in landmarks]
    if not xs or not ys:
        return None
    left = _clamp(min(xs), 0.0, 1.0)
    top = _clamp(min(ys), 0.0, 1.0)
    right = _clamp(max(xs), 0.0, 1.0)
    bottom = _clamp(max(ys), 0.0, 1.0)
    return {
        "x": round(left, 4),
        "y": round(top, 4),
        "width": round(max(MANUAL_BBOX_MIN_SIDE, right - left), 4),
        "height": round(max(MANUAL_BBOX_MIN_SIDE, bottom - top), 4),
    }


def _bbox_center(bbox: dict[str, float] | None) -> tuple[float, float]:
    if not bbox:
        return 0.5, 0.5
    return (
        float(bbox.get("x", 0.0)) + float(bbox.get("width", 0.0)) / 2,
        float(bbox.get("y", 0.0)) + float(bbox.get("height", 0.0)) / 2,
    )


def _bbox_area(bbox: dict[str, float] | None) -> float:
    if not bbox:
        return 0.0
    return float(bbox.get("width", 0.0)) * float(bbox.get("height", 0.0))


def _bbox_width(bbox: dict[str, float] | None) -> float:
    if not bbox:
        return 0.0
    return float(bbox.get("width", 0.0))


def _bbox_height(bbox: dict[str, float] | None) -> float:
    if not bbox:
        return 0.0
    return float(bbox.get("height", 0.0))


def _bbox_center_distance(a: dict[str, float] | None, b: dict[str, float] | None) -> float:
    if not a or not b:
        return 0.0
    ax, ay = _bbox_center(a)
    bx, by = _bbox_center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _bbox_intersection_area(a: dict[str, float] | None, b: dict[str, float] | None) -> float:
    if not a or not b:
        return 0.0
    ax1 = float(a.get("x", 0.0))
    ay1 = float(a.get("y", 0.0))
    ax2 = ax1 + float(a.get("width", 0.0))
    ay2 = ay1 + float(a.get("height", 0.0))
    bx1 = float(b.get("x", 0.0))
    by1 = float(b.get("y", 0.0))
    bx2 = bx1 + float(b.get("width", 0.0))
    by2 = by1 + float(b.get("height", 0.0))
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    return (inter_x2 - inter_x1) * (inter_y2 - inter_y1)


def _bbox_coverage(inner: dict[str, float] | None, outer: dict[str, float] | None) -> float:
    inner_area = _bbox_area(inner)
    if inner_area <= 0.0:
        return 0.0
    return _bbox_intersection_area(inner, outer) / inner_area


def _bbox_iou(a: dict[str, float] | None, b: dict[str, float] | None) -> float:
    if not a or not b:
        return 0.0
    inter_area = _bbox_intersection_area(a, b)
    if inter_area <= 0.0:
        return 0.0
    union_area = _bbox_area(a) + _bbox_area(b) - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def _expand_bbox(bbox: dict[str, float] | None, padding_ratio: float) -> dict[str, float] | None:
    if not bbox:
        return None
    x = float(bbox.get("x", 0.0))
    y = float(bbox.get("y", 0.0))
    width = float(bbox.get("width", 0.0))
    height = float(bbox.get("height", 0.0))
    center_x = x + width / 2.0
    center_y = y + height / 2.0
    expanded_width = min(1.0, max(MANUAL_BBOX_MIN_SIDE, width * (1.0 + padding_ratio * 2.0)))
    expanded_height = min(1.0, max(MANUAL_BBOX_MIN_SIDE, height * (1.0 + padding_ratio * 2.0)))
    expanded_x = _clamp(center_x - expanded_width / 2.0, 0.0, 1.0 - expanded_width)
    expanded_y = _clamp(center_y - expanded_height / 2.0, 0.0, 1.0 - expanded_height)
    return {
        "x": round(expanded_x, 4),
        "y": round(expanded_y, 4),
        "width": round(expanded_width, 4),
        "height": round(expanded_height, 4),
    }


def _point_inside_bbox(point: dict[str, Any], bbox: dict[str, float] | None) -> bool:
    if not bbox:
        return True
    try:
        x = float(point.get("x"))
        y = float(point.get("y"))
    except (TypeError, ValueError):
        return False
    left = float(bbox.get("x", 0.0))
    top = float(bbox.get("y", 0.0))
    right = left + float(bbox.get("width", 0.0))
    bottom = top + float(bbox.get("height", 0.0))
    return left <= x <= right and top <= y <= bottom


def _visible_keypoints(keypoints: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(keypoints, list):
        return []
    visible: list[dict[str, Any]] = []
    for point in keypoints:
        if not isinstance(point, dict):
            continue
        try:
            visibility = float(point.get("visibility", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if visibility >= _KEYPOINT_VISIBILITY_THRESHOLD and point.get("x") is not None and point.get("y") is not None:
            visible.append(point)
    return visible


def _keypoint_roi_metrics(
    keypoints: list[dict[str, Any]] | None,
    tracker_bbox: dict[str, float] | None,
) -> dict[str, Any]:
    visible = _visible_keypoints(keypoints)
    roi = _expand_bbox(tracker_bbox, _KEYPOINT_ROI_PADDING_RATIO)
    if not visible or not roi:
        return {
            "keypoint_roi_coverage": None,
            "core_roi_coverage": None,
            "visible_keypoints": len(visible),
            "visible_core_keypoints": 0,
            "core_center": None,
            "visible_keypoint_bbox": None,
        }

    inside = [point for point in visible if _point_inside_bbox(point, roi)]
    core = [point for point in visible if int(point.get("id", -1)) in CORE_KEYPOINT_IDS]
    core_inside = [point for point in core if _point_inside_bbox(point, roi)]
    core_center = None
    if core:
        core_center = {
            "x": round(sum(float(point.get("x", 0.0) or 0.0) for point in core) / len(core), 4),
            "y": round(sum(float(point.get("y", 0.0) or 0.0) for point in core) / len(core), 4),
        }
    visible_bbox = _bbox_from_keypoints(visible)
    return {
        "keypoint_roi_coverage": round(len(inside) / max(len(visible), 1), 4),
        "core_roi_coverage": round(len(core_inside) / max(len(core), 1), 4) if core else None,
        "visible_keypoints": len(visible),
        "visible_core_keypoints": len(core),
        "core_center": core_center,
        "visible_keypoint_bbox": visible_bbox,
    }


def _core_center_bbox(core_center: dict[str, float] | None) -> dict[str, float] | None:
    if not core_center:
        return None
    return {
        "x": float(core_center.get("x", 0.0)),
        "y": float(core_center.get("y", 0.0)),
        "width": MANUAL_BBOX_MIN_SIDE,
        "height": MANUAL_BBOX_MIN_SIDE,
    }


def _bbox_from_keypoints(keypoints: list[dict[str, Any]]) -> dict[str, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for point in keypoints:
        try:
            x = float(point.get("x"))
            y = float(point.get("y"))
        except (TypeError, ValueError):
            continue
        xs.append(_clamp(x, 0.0, 1.0))
        ys.append(_clamp(y, 0.0, 1.0))
    if not xs or not ys:
        return None
    left = min(xs)
    top = min(ys)
    right = max(xs)
    bottom = max(ys)
    return {
        "x": round(left, 4),
        "y": round(top, 4),
        "width": round(max(MANUAL_BBOX_MIN_SIDE, right - left), 4),
        "height": round(max(MANUAL_BBOX_MIN_SIDE, bottom - top), 4),
    }


def _visibility_sum(landmarks: list[Any]) -> float:
    return sum(float(getattr(landmark, "visibility", 0.0) or 0.0) for landmark in landmarks)


def _map_landmarks_to_keypoints(
    landmarks: list[Any],
    *,
    crop_left: int,
    crop_top: int,
    crop_width: int,
    crop_height: int,
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    keypoints: list[dict[str, Any]] = []
    for index, landmark in enumerate(landmarks):
        visibility = float(getattr(landmark, "visibility", 0.0) or 0.0)
        normalized_x = (crop_left + float(landmark.x) * max(crop_width, 1)) / max(image_width, 1)
        normalized_y = (crop_top + float(landmark.y) * max(crop_height, 1)) / max(image_height, 1)
        keypoints.append(
            {
                "id": index,
                "name": LANDMARK_NAMES[index] if index < len(LANDMARK_NAMES) else f"landmark_{index}",
                "x": float(normalized_x),
                "y": float(normalized_y),
                "z": float(landmark.z),
                "visibility": visibility,
            }
        )
    return keypoints


def _target_seed_bbox(target_lock: dict[str, Any] | None) -> dict[str, float] | None:
    return extract_pose_target_bbox(target_lock)


def _target_motion_region(target_lock: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(target_lock, dict):
        return None
    bbox = target_lock.get("selected_bbox")
    return bbox if isinstance(bbox, dict) else None


def _bbox_for_frame(bbox_per_frame: list[dict[str, float]] | None, frame_index: int) -> dict[str, float] | None:
    if not bbox_per_frame:
        return None
    if frame_index < len(bbox_per_frame):
        bbox = bbox_per_frame[frame_index]
        return bbox if isinstance(bbox, dict) else None
    bbox = bbox_per_frame[-1]
    return bbox if isinstance(bbox, dict) else None


def _increment_histogram(histogram: dict[str, int], value: int) -> None:
    key = str(value)
    histogram[key] = histogram.get(key, 0) + 1


def _score_candidate(
    bbox: dict[str, float] | None,
    visibility_sum: float,
    previous_bbox: dict[str, float] | None,
    motion_bbox: dict[str, float] | None,
    seed_bbox: dict[str, float] | None = None,
) -> float:
    if not bbox:
        return -1.0
    iou_score = _bbox_iou(previous_bbox, bbox)
    motion_overlap = _bbox_iou(motion_bbox, bbox)
    seed_overlap = _bbox_iou(seed_bbox, bbox) if seed_bbox else 0.0
    center_x, center_y = _bbox_center(bbox)
    prev_x, prev_y = _bbox_center(previous_bbox if previous_bbox else motion_bbox)
    center_distance = abs(center_x - prev_x) + abs(center_y - prev_y)
    continuity_score = max(0.0, 1.0 - center_distance * 2.5)
    scale_delta = abs(_bbox_area(bbox) - _bbox_area(previous_bbox or motion_bbox)) if (previous_bbox or motion_bbox) else 0.0
    scale_score = max(0.0, 1.0 - scale_delta * 6.0)
    visibility_score = min(1.0, visibility_sum / 20.0)
    base = (
        (iou_score * 0.28)
        + (continuity_score * 0.18)
        + (scale_score * 0.10)
        + (visibility_score * 0.12)
        + (motion_overlap * 0.12)
        + (seed_overlap * 0.20)
    )
    # 手动锁定时，如果候选与用户框完全不重叠，强行降权——避免镜头里另一位滑行者抢走骨架。
    if seed_bbox and seed_overlap <= 0.0:
        base *= 0.25
    return round(base, 4)


def _has_target_overlap(
    bbox: dict[str, float] | None,
    previous_bbox: dict[str, float] | None,
    tracker_bbox: dict[str, float] | None,
    seed_bbox: dict[str, float] | None,
) -> bool:
    if not bbox:
        return False
    references = [item for item in (tracker_bbox, previous_bbox, seed_bbox) if item]
    if not references:
        return True
    return any(_bbox_iou(bbox, reference) > 0.0 for reference in references)


def _tracker_candidate_rejection_reasons(
    bbox: dict[str, float] | None,
    tracker_bbox: dict[str, float] | None,
) -> list[str]:
    if not bbox or not tracker_bbox:
        return []

    reasons: list[str] = []
    tracker_area = _bbox_area(tracker_bbox)
    candidate_area = _bbox_area(bbox)
    if tracker_area > 0.0 and candidate_area > 0.0:
        area_ratio = candidate_area / tracker_area
        if area_ratio < _TRACKER_CANDIDATE_MIN_AREA_RATIO or area_ratio > _TRACKER_CANDIDATE_MAX_AREA_RATIO:
            reasons.append("tracker_area_ratio")

    tracker_width = _bbox_width(tracker_bbox)
    candidate_width = _bbox_width(bbox)
    if tracker_width > 0.0 and candidate_width > 0.0:
        width_ratio = candidate_width / tracker_width
        if width_ratio < _TRACKER_CANDIDATE_MIN_WIDTH_RATIO or width_ratio > _TRACKER_CANDIDATE_MAX_WIDTH_RATIO:
            reasons.append("tracker_width_ratio")

    tracker_height = _bbox_height(tracker_bbox)
    candidate_height = _bbox_height(bbox)
    if tracker_height > 0.0 and candidate_height > 0.0:
        height_ratio = candidate_height / tracker_height
        if height_ratio < _TRACKER_CANDIDATE_MIN_HEIGHT_RATIO or height_ratio > _TRACKER_CANDIDATE_MAX_HEIGHT_RATIO:
            reasons.append("tracker_height_ratio")

    iou = _bbox_iou(bbox, tracker_bbox)
    tracker_coverage = _bbox_coverage(tracker_bbox, bbox)
    if iou < _TRACKER_CANDIDATE_MIN_IOU and tracker_coverage < _TRACKER_CANDIDATE_MIN_TRACKER_COVERAGE:
        reasons.append("tracker_overlap")

    if _bbox_center_distance(bbox, tracker_bbox) > _TRACKER_CANDIDATE_MAX_CENTER_DISTANCE:
        reasons.append("tracker_center_distance")

    return reasons


def _multi_pose_rejection_reasons(
    bbox: dict[str, float] | None,
    tracker_bbox: dict[str, float] | None,
) -> list[str]:
    if not bbox or not tracker_bbox:
        return []

    reasons: list[str] = []
    tracker_area = _bbox_area(tracker_bbox)
    candidate_area = _bbox_area(bbox)
    if tracker_area > 0.0 and candidate_area > 0.0 and candidate_area / tracker_area > _MULTI_POSE_MAX_AREA_RATIO:
        reasons.append("oversized_multi_pose_candidate")

    tracker_width = _bbox_width(tracker_bbox)
    candidate_width = _bbox_width(bbox)
    if tracker_width > 0.0 and candidate_width > 0.0 and candidate_width / tracker_width > _MULTI_POSE_MAX_WIDTH_RATIO:
        reasons.append("oversized_multi_pose_candidate")

    tracker_height = _bbox_height(tracker_bbox)
    candidate_height = _bbox_height(bbox)
    if tracker_height > 0.0 and candidate_height > 0.0 and candidate_height / tracker_height > _MULTI_POSE_MAX_HEIGHT_RATIO:
        reasons.append("oversized_multi_pose_candidate")

    if _bbox_iou(bbox, tracker_bbox) < _MULTI_POSE_MIN_IOU and _bbox_coverage(tracker_bbox, bbox) < _MULTI_POSE_MIN_TRACKER_COVERAGE:
        reasons.append("oversized_multi_pose_candidate")
    return list(dict.fromkeys(reasons))


def _keypoint_rejection_reasons(
    candidate: dict[str, Any],
    tracker_bbox: dict[str, float] | None,
) -> tuple[list[str], dict[str, Any]]:
    metrics = _keypoint_roi_metrics(candidate.get("keypoints"), tracker_bbox)
    if not tracker_bbox:
        return [], metrics

    reasons: list[str] = []
    keypoint_coverage = metrics.get("keypoint_roi_coverage")
    core_coverage = metrics.get("core_roi_coverage")
    if isinstance(keypoint_coverage, (int, float)) and keypoint_coverage < _KEYPOINT_MIN_ROI_COVERAGE:
        reasons.append("keypoint_roi_coverage")
    if isinstance(core_coverage, (int, float)) and core_coverage < _KEYPOINT_MIN_CORE_ROI_COVERAGE:
        reasons.append("keypoint_roi_coverage")

    core_center_bbox = _core_center_bbox(metrics.get("core_center"))
    roi = _expand_bbox(tracker_bbox, _KEYPOINT_ROI_PADDING_RATIO)
    if core_center_bbox and roi and not _point_inside_bbox({"x": core_center_bbox["x"], "y": core_center_bbox["y"]}, roi):
        reasons.append("core_center_outside_roi")

    source = str(candidate.get("source") or "")
    visible_core = metrics.get("visible_core_keypoints")
    tracker_height = _bbox_height(tracker_bbox)
    if source.startswith("single_pose") and tracker_height <= _KEYPOINT_STRICT_SMALL_TRACKER_HEIGHT:
        if isinstance(visible_core, int) and visible_core < _KEYPOINT_STRICT_MIN_CORE_COUNT:
            reasons.append("core_keypoints_insufficient")
        if isinstance(core_coverage, (int, float)) and core_coverage < _KEYPOINT_STRICT_MIN_CORE_COVERAGE:
            reasons.append("keypoint_roi_coverage")
        visible_bbox = metrics.get("visible_keypoint_bbox") if isinstance(metrics.get("visible_keypoint_bbox"), dict) else None
        if (
            isinstance(visible_core, int)
            and visible_core < _KEYPOINT_STRICT_MIN_CORE_COUNT
            and visible_bbox
            and _bbox_coverage(tracker_bbox, visible_bbox) < _CROP_KEYPOINT_MIN_TRACKER_COVERAGE
        ):
            reasons.append("crop_keypoint_spread")

    return list(dict.fromkeys(reasons)), metrics


def _candidate_rejection_reasons(
    candidate: dict[str, Any],
    *,
    previous_bbox: dict[str, float] | None,
    tracker_bbox: dict[str, float] | None,
    seed_bbox: dict[str, float] | None,
    previous_core_center: dict[str, float] | None = None,
) -> list[str]:
    bbox = candidate.get("bbox")
    reasons: list[str] = []
    if not _has_target_overlap(bbox, previous_bbox, tracker_bbox, seed_bbox):
        reasons.append("target_overlap")
    reasons.extend(_tracker_candidate_rejection_reasons(bbox, tracker_bbox))
    if candidate.get("source") == "tasks_multi_pose":
        reasons.extend(_multi_pose_rejection_reasons(bbox, tracker_bbox))
    keypoint_reasons, metrics = _keypoint_rejection_reasons(candidate, tracker_bbox)
    candidate["candidate_validation"] = metrics
    reasons.extend(keypoint_reasons)
    current_core_center = metrics.get("core_center")
    if previous_core_center and current_core_center:
        distance = _bbox_center_distance(_core_center_bbox(previous_core_center), _core_center_bbox(current_core_center))
        if distance > _TEMPORAL_CORE_JUMP_LIMIT:
            reasons.append("temporal_pose_jump")
    return list(dict.fromkeys(reasons))


def _diagnostic_candidate_summary(candidate: dict[str, Any], reasons: list[str] | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "bbox": candidate.get("bbox"),
        "source": candidate.get("source"),
        "candidate_validation": candidate.get("candidate_validation"),
    }
    if "score" in candidate:
        try:
            summary["score"] = round(float(candidate.get("score", 0.0)), 4)
        except (TypeError, ValueError):
            summary["score"] = candidate.get("score")
    if reasons:
        summary["reasons"] = list(reasons)
    return summary


def _candidate_priority(candidate: dict[str, Any]) -> int:
    source = candidate.get("source")
    if source == "single_pose_crop":
        return 0
    if source == "single_pose_predicted_crop":
        return 1
    return 2


def _score_pose_candidate(
    candidate: dict[str, Any],
    *,
    reference_bbox: dict[str, float] | None,
    current_tracker_bbox: dict[str, float] | None,
    motion_bbox: dict[str, float] | None,
    seed_bbox: dict[str, float] | None,
) -> dict[str, Any]:
    return {
        **candidate,
        "score": _score_candidate(
            candidate.get("bbox"),
            float(candidate.get("visibility_sum", 0.0)),
            reference_bbox,
            current_tracker_bbox or motion_bbox,
            seed_bbox=seed_bbox,
        ),
    }


def _run_single_pose_crop(
    single_pose: Any,
    image: Any,
    image_width: int,
    image_height: int,
    bbox: dict[str, float] | None,
    *,
    cv2_module: Any,
    padding_ratio: float,
    source: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    left, top, right, bottom = _crop_bounds(image_width, image_height, bbox, padding_ratio=padding_ratio)
    attempt = {
        "source": source,
        "bbox": bbox,
        "crop_bounds": [left, top, right, bottom],
        "success": False,
    }
    cropped = image[top:bottom, left:right]
    if cropped.size <= 0:
        attempt["reason"] = "empty_crop"
        return None, attempt

    result = single_pose.process(cv2_module.cvtColor(cropped, cv2_module.COLOR_BGR2RGB))
    if not result.pose_landmarks:
        attempt["reason"] = "no_pose_landmarks"
        return None, attempt

    candidate_bbox = bbox or {
        "x": round(left / max(image_width, 1), 4),
        "y": round(top / max(image_height, 1), 4),
        "width": round((right - left) / max(image_width, 1), 4),
        "height": round((bottom - top) / max(image_height, 1), 4),
    }
    candidate = {
        "bbox": candidate_bbox,
        "visibility_sum": _visibility_sum(result.pose_landmarks.landmark),
        "keypoints": _map_landmarks_to_keypoints(
            result.pose_landmarks.landmark,
            crop_left=left,
            crop_top=top,
            crop_width=max(right - left, 1),
            crop_height=max(bottom - top, 1),
            image_width=image_width,
            image_height=image_height,
        ),
        "source": source,
    }
    attempt["success"] = True
    return candidate, attempt


def _frame_number_from_name(frame_name: str | None) -> int | None:
    if not frame_name:
        return None
    digits = "".join(char for char in frame_name if char.isdigit())
    return int(digits) if digits else None


def _predict_bbox_from_history(
    bbox_history: list[tuple[int, dict[str, float]]],
    frame_index: int,
) -> dict[str, float] | None:
    if len(bbox_history) < 2:
        return None
    recent = bbox_history[-_TRACKER_PREDICTION_HISTORY:]
    first_index, first_bbox = recent[0]
    last_index, last_bbox = recent[-1]
    span = max(last_index - first_index, 1)
    steps = max(frame_index - last_index, 1)
    predicted = {
        "x": float(last_bbox.get("x", 0.0)) + (float(last_bbox.get("x", 0.0)) - float(first_bbox.get("x", 0.0))) / span * steps,
        "y": float(last_bbox.get("y", 0.0)) + (float(last_bbox.get("y", 0.0)) - float(first_bbox.get("y", 0.0))) / span * steps,
        "width": float(last_bbox.get("width", 0.0)),
        "height": float(last_bbox.get("height", 0.0)),
    }
    width = _clamp(predicted["width"], MANUAL_BBOX_MIN_SIDE, 1.0)
    height = _clamp(predicted["height"], MANUAL_BBOX_MIN_SIDE, 1.0)
    return {
        "x": round(_clamp(predicted["x"], 0.0, 1.0 - width), 4),
        "y": round(_clamp(predicted["y"], 0.0, 1.0 - height), 4),
        "width": round(width, 4),
        "height": round(height, 4),
    }


def _interpolate_number(before: Any, after: Any, ratio: float) -> float | None:
    try:
        before_value = float(before)
        after_value = float(after)
    except (TypeError, ValueError):
        return None
    return before_value + (after_value - before_value) * ratio


def _interpolate_keypoints_for_display(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    ratio: float,
) -> list[dict[str, Any]]:
    by_id_after = {int(point.get("id", -1)): point for point in after if isinstance(point, dict)}
    interpolated: list[dict[str, Any]] = []
    for point in before:
        if not isinstance(point, dict):
            continue
        point_id = int(point.get("id", -1))
        next_point = by_id_after.get(point_id)
        if next_point is None:
            continue
        item = dict(point)
        for axis in ("x", "y", "z"):
            value = _interpolate_number(point.get(axis), next_point.get(axis), ratio)
            if value is not None:
                item[axis] = value
        item["visibility"] = 0.0
        item["interpolated"] = True
        interpolated.append(item)
    return interpolated


def _interpolate_bbox_for_display(
    before: dict[str, float] | None,
    after: dict[str, float] | None,
    ratio: float,
) -> dict[str, float] | None:
    if not before or not after:
        return before or after
    return {
        key: round(float(before.get(key, 0.0)) + (float(after.get(key, 0.0)) - float(before.get(key, 0.0))) * ratio, 4)
        for key in ("x", "y", "width", "height")
    }


def _apply_short_gap_interpolation(
    frames: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    max_gap: int = _MAX_DISPLAY_INTERPOLATION_GAP,
) -> tuple[int, int]:
    interpolated_count = 0
    index = 0
    while index < len(frames):
        frame = frames[index]
        if frame.get("tracking_state") != "lost":
            index += 1
            continue

        gap_start = index
        while index < len(frames) and frames[index].get("tracking_state") == "lost":
            index += 1
        gap_end = index
        gap_size = gap_end - gap_start
        before_index = gap_start - 1
        after_index = gap_end
        if gap_size > max_gap or before_index < 0 or after_index >= len(frames):
            continue

        before = frames[before_index]
        after = frames[after_index]
        if before.get("tracking_state") != "tracked" or after.get("tracking_state") != "tracked":
            continue
        before_keypoints = before.get("keypoints") if isinstance(before.get("keypoints"), list) else []
        after_keypoints = after.get("keypoints") if isinstance(after.get("keypoints"), list) else []
        if not before_keypoints or not after_keypoints:
            continue

        for offset, frame_index in enumerate(range(gap_start, gap_end), start=1):
            ratio = offset / (gap_size + 1)
            frames[frame_index]["keypoints"] = _interpolate_keypoints_for_display(before_keypoints, after_keypoints, ratio)
            frames[frame_index]["target_bbox"] = _interpolate_bbox_for_display(before.get("target_bbox"), after.get("target_bbox"), ratio)
            frames[frame_index]["tracking_state"] = "interpolated"
            frames[frame_index]["tracking_confidence"] = 0.05
            frames[frame_index]["pose_candidates"] = []
            if frame_index < len(diagnostics):
                diagnostics[frame_index]["tracking_state"] = "interpolated"
                diagnostics[frame_index]["tracking_confidence"] = 0.05
                diagnostics[frame_index]["reason"] = "pose_interpolated"
                diagnostics[frame_index]["selected_source"] = "interpolated"
                diagnostics[frame_index]["output_bbox"] = frames[frame_index].get("target_bbox")
            interpolated_count += 1
    lost_count = sum(1 for frame in frames if frame.get("tracking_state") == "lost")
    return interpolated_count, lost_count


def _resolve_tasks_landmarker() -> Any | None:
    num_poses, task_model_path = _get_pose_runtime_config()
    if not task_model_path:
        return None
    model_path = _resolve_model_path(task_model_path)
    if model_path is None:
        return None
    if not model_path.exists():
        logger.warning("pose mode = fallback_single_pose (model file not found at %s)", model_path)
        return None
    try:
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        options = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path)),
            num_poses=num_poses,
            min_pose_detection_confidence=0.35,
            min_pose_presence_confidence=0.35,
            min_tracking_confidence=0.35,
            output_segmentation_masks=False,
        )
        return vision.PoseLandmarker.create_from_options(options)
    except Exception:
        logger.warning("pose mode = fallback_single_pose (failed to initialize multi-pose landmarker)", exc_info=True)
        return None


def log_pose_runtime_mode() -> None:
    global _POSE_MODE_LOGGED
    if _POSE_MODE_LOGGED:
        return

    status = get_pose_runtime_status()
    if status["reason"] == "model_path_not_set":
        logger.info("pose mode = fallback_single_pose (MEDIAPIPE_POSE_TASK_PATH is not set)")
        _POSE_MODE_LOGGED = True
        return

    if status["reason"] == "missing_model_file":
        logger.warning("pose mode = fallback_single_pose (model file not found at %s)", status["model_path"])
        _POSE_MODE_LOGGED = True
        return

    logger.info("pose mode = multi_pose (model=%s, num_poses=%s)", status["model_path"], status["num_poses"])
    _POSE_MODE_LOGGED = True


def extract_pose(
    frames_dir: str,
    target_lock: dict[str, Any] | None = None,
    bbox_per_frame: list[dict[str, float]] | None = None,
    effective_fps: float | None = None,
) -> dict[str, Any]:
    """从抽样帧中提取目标选手骨骼关键点。

    Args:
        frames_dir: 抽样帧目录。
        target_lock: 兼容旧流程的目标锁定 payload。
        bbox_per_frame: tracker 输出的逐帧目标 bbox，优先用于裁剪和候选打分。

    Returns:
        包含 connections、frames 和逐帧目标跟踪信息的 pose payload。

    Raises:
        无。MediaPipe/OpenCV 不可用时返回空 payload。
    """
    num_poses, _ = _get_pose_runtime_config()
    frame_paths = sorted(Path(frames_dir).glob("frame_*.jpg"))
    if not frame_paths:
        return _empty_payload()

    try:
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore
    except Exception:
        return _empty_payload()

    frames: list[dict[str, Any]] = []
    diagnostic_frames: list[dict[str, Any]] = []
    candidate_count_histogram: dict[str, int] = {}
    multi_pose_frames = 0
    single_pose_crop_frames = 0
    tracked_frames = 0
    lost_frames = 0
    low_confidence_frames = 0
    seed_bbox = _bbox_for_frame(bbox_per_frame, 0) or _target_seed_bbox(target_lock)
    motion_bbox = _target_motion_region(target_lock)
    previous_bbox = seed_bbox
    previous_core_center: dict[str, float] | None = None
    tracker_bbox_history: list[tuple[int, dict[str, float]]] = []
    lost_count = 0
    tasks_landmarker = _resolve_tasks_landmarker()
    pose_mode = "multi_pose" if tasks_landmarker is not None else "single_pose_crop"
    single_pose = mp.solutions.pose.Pose(
        static_image_mode=True,
        model_complexity=1,
        enable_segmentation=False,
        min_detection_confidence=0.5,
    )

    try:
        for frame_index, frame_path in enumerate(frame_paths):
            image = cv2.imread(str(frame_path))
            current_tracker_bbox = _bbox_for_frame(bbox_per_frame, frame_index)
            reference_bbox = current_tracker_bbox or previous_bbox or seed_bbox
            if image is None:
                lost_frames += 1
                low_confidence_frames += 1
                _increment_histogram(candidate_count_histogram, 0)
                frames.append(
                    {
                        "frame": frame_path.name,
                        "keypoints": [],
                        "target_bbox": reference_bbox,
                        "tracking_confidence": 0.0,
                        "tracking_state": "lost",
                    }
                )
                diagnostic_frames.append(
                    {
                        "frame": frame_path.name,
                        "frame_index": frame_index,
                        "tracker_bbox": current_tracker_bbox,
                        "reference_bbox": reference_bbox,
                        "selected_bbox": reference_bbox,
                        "tracking_state": "lost",
                        "tracking_confidence": 0.0,
                        "candidate_count": 0,
                        "scored_candidate_count": 0,
                        "rejected_candidate_count": 0,
                        "selected_source": None,
                        "reason": "image_read_failed",
                    }
                )
                continue

            image_height, image_width = image.shape[:2]
            candidate_results: list[dict[str, Any]] = []
            rejected_candidates: list[dict[str, Any]] = []
            crop_attempts: list[dict[str, Any]] = []
            predicted_bbox: dict[str, float] | None = None
            pose_reference_source = "tracker_bbox" if current_tracker_bbox else "previous_pose"

            if current_tracker_bbox:
                tracker_bbox_history.append((frame_index, current_tracker_bbox))

            crop_candidate, crop_attempt = _run_single_pose_crop(
                single_pose,
                image,
                image_width,
                image_height,
                reference_bbox,
                cv2_module=cv2,
                padding_ratio=_POSE_CROP_PADDING_RATIO if current_tracker_bbox else 0.0,
                source="single_pose_crop",
            )
            crop_attempts.append(crop_attempt)
            if crop_candidate is not None:
                candidate_results.append(crop_candidate)
                single_pose_crop_frames += 1

            if current_tracker_bbox is None or lost_count > 0:
                predicted_bbox = _predict_bbox_from_history(tracker_bbox_history, frame_index)
                if predicted_bbox is not None and predicted_bbox != reference_bbox:
                    predicted_candidate, predicted_attempt = _run_single_pose_crop(
                        single_pose,
                        image,
                        image_width,
                        image_height,
                        predicted_bbox,
                        cv2_module=cv2,
                        padding_ratio=_POSE_PREDICTED_CROP_PADDING_RATIO,
                        source="single_pose_predicted_crop",
                    )
                    predicted_attempt["predicted_bbox"] = predicted_bbox
                    crop_attempts.append(predicted_attempt)
                    if predicted_candidate is not None:
                        candidate_results.append(predicted_candidate)
                        pose_reference_source = "tracker_motion_predicted"

            if tasks_landmarker is not None:
                try:
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                    detect_result = tasks_landmarker.detect(mp_image)
                    for landmarks in detect_result.pose_landmarks:
                        bbox = _bbox_from_landmarks(landmarks)
                        if not bbox:
                            continue
                        candidate_results.append(
                            {
                                "bbox": bbox,
                                "visibility_sum": _visibility_sum(landmarks),
                                "keypoints": _map_landmarks_to_keypoints(
                                    landmarks,
                                    crop_left=0,
                                    crop_top=0,
                                    crop_width=image_width,
                                    crop_height=image_height,
                                    image_width=image_width,
                                    image_height=image_height,
                                ),
                                "source": "tasks_multi_pose",
                            }
                        )
                    if candidate_results:
                        multi_pose_frames += 1
                except Exception:
                    pass

            filtered_candidates: list[dict[str, Any]] = []
            for candidate in candidate_results:
                validation_tracker_bbox = current_tracker_bbox or predicted_bbox
                rejection_reasons = _candidate_rejection_reasons(
                    candidate,
                    previous_bbox=previous_bbox,
                    tracker_bbox=validation_tracker_bbox,
                    seed_bbox=seed_bbox,
                    previous_core_center=previous_core_center,
                )
                if rejection_reasons:
                    rejected_candidates.append(_diagnostic_candidate_summary(candidate, rejection_reasons))
                    continue
                filtered_candidates.append(candidate)

            candidate_results = filtered_candidates

            scored_candidates = [
                _score_pose_candidate(
                    candidate,
                    reference_bbox=reference_bbox,
                    current_tracker_bbox=current_tracker_bbox or predicted_bbox,
                    motion_bbox=motion_bbox,
                    seed_bbox=seed_bbox,
                )
                for candidate in candidate_results
            ]
            scored_candidates.sort(key=lambda item: (_candidate_priority(item), -float(item.get("score", -1.0))))
            best_candidate = (
                scored_candidates[0]
                if scored_candidates and float(scored_candidates[0].get("score", -1.0)) >= _POSE_MIN_ACCEPT_SCORE
                else None
            )
            _increment_histogram(candidate_count_histogram, len(candidate_results) + len(rejected_candidates))

            if best_candidate is None:
                lost_count += 1
                lost_frames += 1
                low_confidence_frames += 1
                output_bbox = current_tracker_bbox or previous_bbox or reference_bbox
                frames.append(
                    {
                        "frame": frame_path.name,
                        "keypoints": [],
                        "target_bbox": output_bbox,
                        "tracking_confidence": 0.0,
                        "tracking_state": "lost" if lost_count > 0 else "missing",
                        "pose_candidates": [
                            _diagnostic_candidate_summary(candidate)
                            for candidate in scored_candidates
                        ],
                    }
                )
                diagnostic_frames.append(
                    {
                        "frame": frame_path.name,
                        "frame_index": frame_index,
                        "tracker_bbox": current_tracker_bbox,
                        "reference_bbox": reference_bbox,
                        "selected_bbox": previous_bbox,
                        "output_bbox": output_bbox,
                        "tracking_state": "lost" if lost_count > 0 else "missing",
                        "tracking_confidence": 0.0,
                        "candidate_count": len(candidate_results),
                        "scored_candidate_count": len(scored_candidates),
                        "rejected_candidate_count": len(rejected_candidates) + max(0, len(candidate_results) - len(scored_candidates)),
                        "selected_source": None,
                        "pose_reference_source": pose_reference_source,
                        "crop_attempts": crop_attempts,
                        "candidate_validation": None,
                        "reason": "crop_retry_exhausted" if crop_attempts else None,
                        "rejected_candidates": rejected_candidates[:_MAX_DIAGNOSTIC_POSE_REJECTIONS],
                        "top_candidates": [
                            _diagnostic_candidate_summary(candidate)
                            for candidate in scored_candidates[:num_poses]
                        ],
                    }
                )
                continue

            previous_bbox = best_candidate.get("bbox")
            previous_core_center = (best_candidate.get("candidate_validation") or {}).get("core_center")
            lost_count = 0
            confidence = round(float(best_candidate.get("score", 0.0)), 4)
            output_bbox = current_tracker_bbox or previous_bbox
            tracked_frames += 1
            if confidence < 0.2:
                low_confidence_frames += 1
            frames.append(
                {
                    "frame": frame_path.name,
                    "keypoints": best_candidate.get("keypoints", []),
                    "target_bbox": output_bbox,
                    "tracking_confidence": confidence,
                    "tracking_state": "tracked",
                    "pose_candidates": [
                        _diagnostic_candidate_summary(candidate)
                        for candidate in scored_candidates[:num_poses]
                    ],
                }
            )
            diagnostic_frames.append(
                {
                    "frame": frame_path.name,
                    "frame_index": frame_index,
                    "tracker_bbox": current_tracker_bbox,
                        "reference_bbox": reference_bbox,
                        "selected_bbox": previous_bbox,
                        "output_bbox": output_bbox,
                        "tracking_state": "tracked",
                        "tracking_confidence": confidence,
                        "candidate_count": len(candidate_results),
                        "scored_candidate_count": len(scored_candidates),
                        "rejected_candidate_count": len(rejected_candidates) + max(0, len(candidate_results) - len(scored_candidates)),
                        "selected_source": best_candidate.get("source"),
                        "pose_reference_source": pose_reference_source,
                        "crop_attempts": crop_attempts,
                        "candidate_validation": best_candidate.get("candidate_validation"),
                        "rejected_candidates": rejected_candidates[:_MAX_DIAGNOSTIC_POSE_REJECTIONS],
                        "top_candidates": [
                            _diagnostic_candidate_summary(candidate)
                            for candidate in scored_candidates[:num_poses]
                        ],
                    }
                )
    finally:
        single_pose.close()
        if tasks_landmarker is not None:
            tasks_landmarker.close()

    quality_flags: list[str] = []
    interpolated_frames, remaining_lost_frames = _apply_short_gap_interpolation(frames, diagnostic_frames)
    if interpolated_frames:
        quality_flags.append("pose_interpolated")
    try:
        frames = smooth_keypoint_sequence(frames, effective_fps or 5.0)
    except Exception:
        logger.warning("pose smoothing failed; using raw keypoints", exc_info=True)
        quality_flags.append("pose_smoothing_failed_fallback")

    payload: dict[str, Any] = {
        "connections": POSE_CONNECTIONS,
        "frames": frames,
        "pose_diagnostics": {
            "mode": pose_mode,
            "total_frames": len(frames),
            "tracked_frames": sum(1 for frame in frames if frame.get("tracking_state") == "tracked"),
            "lost_frames": remaining_lost_frames,
            "interpolated_frames": interpolated_frames,
            "low_confidence_frames": sum(
                1
                for frame in frames
                if isinstance(frame.get("tracking_confidence"), (int, float)) and float(frame.get("tracking_confidence", 0.0)) < 0.2
            ),
            "multi_pose_frames": multi_pose_frames,
            "single_pose_crop_frames": single_pose_crop_frames,
            "candidate_count_histogram": candidate_count_histogram,
            "frames": diagnostic_frames,
        },
    }
    if quality_flags:
        payload["quality_flags"] = quality_flags
    return payload
