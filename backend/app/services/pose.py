from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any

from app.services.target_lock import extract_pose_target_bbox


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
    return {"connections": POSE_CONNECTIONS, "frames": []}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _crop_bounds(image_width: int, image_height: int, bbox: dict[str, float] | None) -> tuple[int, int, int, int]:
    if not bbox:
        return 0, 0, image_width, image_height
    x = int(max(0.0, min(1.0, float(bbox.get("x", 0.0)))) * image_width)
    y = int(max(0.0, min(1.0, float(bbox.get("y", 0.0)))) * image_height)
    width = int(max(0.05, min(1.0, float(bbox.get("width", 1.0)))) * image_width)
    height = int(max(0.05, min(1.0, float(bbox.get("height", 1.0)))) * image_height)
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
        "width": round(max(0.05, right - left), 4),
        "height": round(max(0.05, bottom - top), 4),
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


def _bbox_iou(a: dict[str, float] | None, b: dict[str, float] | None) -> float:
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
    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    union_area = _bbox_area(a) + _bbox_area(b) - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


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
                "visibility": visibility if visibility >= 0.5 else 0.0,
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


def _score_candidate(
    bbox: dict[str, float] | None,
    visibility_sum: float,
    previous_bbox: dict[str, float] | None,
    motion_bbox: dict[str, float] | None,
) -> float:
    if not bbox:
        return -1.0
    iou_score = _bbox_iou(previous_bbox, bbox)
    motion_overlap = _bbox_iou(motion_bbox, bbox)
    center_x, center_y = _bbox_center(bbox)
    prev_x, prev_y = _bbox_center(previous_bbox if previous_bbox else motion_bbox)
    center_distance = abs(center_x - prev_x) + abs(center_y - prev_y)
    continuity_score = max(0.0, 1.0 - center_distance * 2.5)
    scale_delta = abs(_bbox_area(bbox) - _bbox_area(previous_bbox or motion_bbox)) if (previous_bbox or motion_bbox) else 0.0
    scale_score = max(0.0, 1.0 - scale_delta * 6.0)
    visibility_score = min(1.0, visibility_sum / 20.0)
    return round(
        (iou_score * 0.34)
        + (continuity_score * 0.22)
        + (scale_score * 0.14)
        + (visibility_score * 0.14)
        + (motion_overlap * 0.16),
        4,
    )


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


def extract_pose(frames_dir: str, target_lock: dict[str, Any] | None = None) -> dict[str, Any]:
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
    seed_bbox = _target_seed_bbox(target_lock)
    motion_bbox = _target_motion_region(target_lock)
    previous_bbox = seed_bbox
    lost_count = 0
    tasks_landmarker = _resolve_tasks_landmarker()
    single_pose = mp.solutions.pose.Pose(
        static_image_mode=True,
        model_complexity=1,
        enable_segmentation=False,
        min_detection_confidence=0.5,
    )

    try:
        for frame_path in frame_paths:
            image = cv2.imread(str(frame_path))
            if image is None:
                frames.append(
                    {
                        "frame": frame_path.name,
                        "keypoints": [],
                        "target_bbox": previous_bbox,
                        "tracking_confidence": 0.0,
                        "tracking_state": "lost",
                    }
                )
                continue

            image_height, image_width = image.shape[:2]
            candidate_results: list[dict[str, Any]] = []

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
                except Exception:
                    candidate_results = []

            if not candidate_results:
                left, top, right, bottom = _crop_bounds(image_width, image_height, seed_bbox or previous_bbox)
                cropped = image[top:bottom, left:right]
                if cropped.size > 0:
                    result = single_pose.process(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
                    if result.pose_landmarks:
                        bbox = seed_bbox or previous_bbox or {
                            "x": round(left / max(image_width, 1), 4),
                            "y": round(top / max(image_height, 1), 4),
                            "width": round((right - left) / max(image_width, 1), 4),
                            "height": round((bottom - top) / max(image_height, 1), 4),
                        }
                        candidate_results.append(
                            {
                                "bbox": bbox,
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
                                "source": "single_pose_crop",
                            }
                        )

            scored_candidates = [
                {
                    **candidate,
                    "score": _score_candidate(candidate.get("bbox"), float(candidate.get("visibility_sum", 0.0)), previous_bbox, motion_bbox),
                }
                for candidate in candidate_results
            ]
            scored_candidates.sort(key=lambda item: float(item.get("score", -1.0)), reverse=True)
            best_candidate = scored_candidates[0] if scored_candidates and float(scored_candidates[0].get("score", -1.0)) >= 0.15 else None

            if best_candidate is None:
                lost_count += 1
                frames.append(
                    {
                        "frame": frame_path.name,
                        "keypoints": [],
                        "target_bbox": previous_bbox,
                        "tracking_confidence": 0.0,
                        "tracking_state": "lost" if lost_count > 0 else "missing",
                        "pose_candidates": [
                            {
                                "bbox": candidate.get("bbox"),
                                "score": candidate.get("score"),
                                "source": candidate.get("source"),
                            }
                            for candidate in scored_candidates
                        ],
                    }
                )
                continue

            previous_bbox = best_candidate.get("bbox")
            lost_count = 0
            frames.append(
                {
                    "frame": frame_path.name,
                    "keypoints": best_candidate.get("keypoints", []),
                    "target_bbox": previous_bbox,
                    "tracking_confidence": round(float(best_candidate.get("score", 0.0)), 4),
                    "tracking_state": "tracked",
                    "pose_candidates": [
                        {
                            "bbox": candidate.get("bbox"),
                            "score": round(float(candidate.get("score", 0.0)), 4),
                            "source": candidate.get("source"),
                        }
                        for candidate in scored_candidates[:num_poses]
                    ],
                }
            )
    finally:
        single_pose.close()
        if tasks_landmarker is not None:
            tasks_landmarker.close()

    return {"connections": POSE_CONNECTIONS, "frames": frames}
