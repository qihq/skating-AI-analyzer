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
PERSON_TRACKER_RELOCKED_FLAG = "person_tracker_relocked"
PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG = "person_tracker_anchor_not_first_frame"

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


def _center(xyxy: Sequence[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = [float(value) for value in xyxy]
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _center_distance(a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


class PersonBBoxTracker:
    """YOLO person detector + ByteTrack target association for sampled frame sequences."""

    def __init__(
        self,
        *,
        yolo_model: Any | None = None,
        byte_tracker_factory: Any | None = None,
        effective_fps: float | None = None,
    ) -> None:
        self._yolo_model = yolo_model
        self._byte_tracker_factory = byte_tracker_factory
        self._tracker: Any | None = None
        self._effective_fps = max(float(effective_fps or 5.0), 1.0)
        self._target_tracker_id: int | None = None
        self._last_known_xyxy: tuple[float, float, float, float] | None = None
        self._lost_frames = 0
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
        for frame_index, frame_path in enumerate(frames):
            frame = self._read_frame(frame_path)
            frame_h, frame_w = frame.shape[:2]
            if frame_index == 0 and self._last_known_xyxy is None:
                self._last_known_xyxy = _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)

            target_xyxy = self.process_frame(frame, self._last_known_xyxy)
            if target_xyxy is None:
                if PERSON_TRACKER_TARGET_LOST_FLAG not in self.quality_flags:
                    self.quality_flags.append(PERSON_TRACKER_TARGET_LOST_FLAG)
                target_xyxy = self._last_known_xyxy or _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)
            else:
                self._last_known_xyxy = target_xyxy

            tracked.append(_xyxy_to_bbox(target_xyxy, frame_w, frame_h))

        return tracked, list(dict.fromkeys(self.quality_flags))

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        seed_xyxy: Sequence[float] | None,
    ) -> tuple[float, float, float, float] | None:
        frame_h, frame_w = frame_bgr.shape[:2]
        raw_boxes = self._detect(frame_bgr)
        if not raw_boxes:
            self._lost_frames += 1
            return None

        tracked = self._update_tracks(raw_boxes)
        if len(tracked) == 0 or getattr(tracked, "tracker_id", None) is None:
            self._lost_frames += 1
            return None

        self._record_centers(tracked)
        if self._target_tracker_id is None:
            self._target_tracker_id = self._select_target(
                tracked,
                seed_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
                allow_static_filter=True,
            )
            if self._target_tracker_id is None:
                self._lost_frames += 1
                return None

        target_xyxy = self._xyxy_for_tracker_id(tracked, self._target_tracker_id)
        if target_xyxy is None:
            self._lost_frames += 1
            if self._lost_frames >= _RELOCK_AFTER_LOST_FRAMES:
                relocked = self._select_target(
                    tracked,
                    self._last_known_xyxy or seed_xyxy,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    allow_static_filter=True,
                )
                if relocked is not None:
                    self._target_tracker_id = relocked
                    target_xyxy = self._xyxy_for_tracker_id(tracked, relocked)
                    self._lost_frames = 0
                    if PERSON_TRACKER_RELOCKED_FLAG not in self.quality_flags:
                        self.quality_flags.append(PERSON_TRACKER_RELOCKED_FLAG)
            if target_xyxy is None:
                return None

        self._last_known_xyxy = target_xyxy
        self._lost_frames = 0
        return target_xyxy

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

    def _detect(self, frame_bgr: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        model = self._get_yolo_model()
        results = model(frame_bgr, classes=[0], conf=_YOLO_CONF_THRESHOLD, verbose=False)
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

    def _select_target(
        self,
        detections: Any,
        seed_xyxy: Sequence[float] | None,
        *,
        frame_w: int,
        frame_h: int,
        allow_static_filter: bool,
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
            if seed_xyxy is not None:
                distance = _center_distance(xyxy, seed_xyxy)
                if self._lost_frames > 0 and distance > diagonal * _MAX_RELOCK_DISTANCE_RATIO:
                    continue
                score = _iou(xyxy, seed_xyxy) + max(0.0, 1.0 - distance / max(diagonal, 1.0)) * 0.2
            else:
                cx, cy = _center(xyxy)
                frame_center_distance = ((cx - frame_w / 2.0) ** 2 + (cy - frame_h / 2.0) ** 2) ** 0.5
                score = 1.0 - frame_center_distance / max(diagonal / 2.0, 1.0)
            if score > best_score:
                best_id = tid
                best_score = score
        return best_id

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


def get_person_tracker_runtime_status() -> dict[str, Any]:
    configured_path = os.getenv(_YOLO_MODEL_PATH_ENV, "").strip()
    mounted_exists = _YOLO_MOUNTED_MODEL_PATH.exists()
    model_path = _resolve_yolo_model_path()
    model_exists = Path(model_path).exists() if model_path != _YOLO_MODEL_NAME else False
    if configured_path:
        reason = "configured" if model_exists else "missing_model_file"
        source = "env"
    elif mounted_exists:
        reason = "mounted_default"
        source = "mounted_default"
    else:
        reason = "auto_download_fallback"
        source = "ultralytics_auto_download"
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
    }


def _track_forward(
    frame_paths: Sequence[Path],
    initial_bbox: dict[str, Any],
    *,
    effective_fps: float | None,
) -> tuple[list[dict[str, float]], list[str]]:
    tracker = PersonBBoxTracker(effective_fps=effective_fps)
    return tracker.track_sequence(frame_paths, initial_bbox)


def track_person_bbox(
    frame_paths: Sequence[Path],
    initial_bbox: dict[str, Any],
    *,
    initial_frame_index: int = 0,
    effective_fps: float | None = None,
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
        return _track_forward(frames, normalized_initial, effective_fps=effective_fps)

    backward_frames = list(reversed(frames[: start_index + 1]))
    backward_tracked, backward_flags = _track_forward(
        backward_frames,
        normalized_initial,
        effective_fps=effective_fps,
    )
    forward_tracked, forward_flags = _track_forward(
        frames[start_index:],
        normalized_initial,
        effective_fps=effective_fps,
    )
    tracked = list(reversed(backward_tracked))[0:-1] + forward_tracked
    flags = list(dict.fromkeys([*backward_flags, *forward_flags, PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG]))
    return tracked, flags
