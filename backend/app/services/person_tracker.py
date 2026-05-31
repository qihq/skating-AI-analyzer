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
PERSON_TRACKER_CONTINUITY_REJECTED_FLAG = "person_tracker_continuity_rejected"
PERSON_TRACKER_RELOCK_PENDING_FLAG = "person_tracker_relock_pending"
PERSON_TRACKER_RELOCK_REJECTED_FLAG = "person_tracker_relock_rejected"
PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG = "person_tracker_detector_relock_pending"
PERSON_TRACKER_DETECTOR_RELOCKED_FLAG = "person_tracker_detector_relocked"
PERSON_TRACKER_LOCAL_ZOOM_RELOCK_ATTEMPTED_FLAG = "person_tracker_local_zoom_relock_attempted"
PERSON_TRACKER_LOCAL_ZOOM_RELOCK_REJECTED_FLAG = "person_tracker_local_zoom_relock_rejected"

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
_LONG_LOST_REACQUIRE_AFTER_FRAMES = 4
_LONG_LOST_MIN_CONFIDENCE = 0.45
_LONG_LOST_ASPECT_RANGE = (0.12, 0.65)
_LONG_LOST_HEIGHT_RANGE = (0.10, 0.62)
_LONG_LOST_AREA_RANGE = (0.002, 0.14)
_MAX_DIAGNOSTIC_REJECTED_CANDIDATES = 4


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
    return diagnostic


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
        self._pending_relock_tracker_id: int | None = None
        self._pending_relock_count = 0
        self._pending_detector_relock_xyxy: tuple[float, float, float, float] | None = None
        self._pending_detector_relock_source: str | None = None
        self._pending_detector_relock_count = 0
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
        for frame_index, frame_path in enumerate(frames):
            frame = self._read_frame(frame_path)
            frame_h, frame_w = frame.shape[:2]
            if frame_index == 0 and self._last_known_xyxy is None:
                self._last_known_xyxy = _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)

            target_xyxy = self.process_frame(frame, self._last_known_xyxy)
            if target_xyxy is None:
                _add_flag(self.quality_flags, PERSON_TRACKER_TARGET_LOST_FLAG)
                target_xyxy = self._last_known_xyxy or _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)
            else:
                self._last_known_xyxy = target_xyxy

            tracked.append(_xyxy_to_bbox(target_xyxy, frame_w, frame_h))

        return tracked, list(dict.fromkeys(self.quality_flags))

    def track_sequence_detailed(
        self,
        frame_paths: Sequence[Path],
        initial_bbox: dict[str, Any],
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
            )
            if target_xyxy is None:
                _add_flag(self.quality_flags, PERSON_TRACKER_TARGET_LOST_FLAG)
                target_xyxy = self._last_known_xyxy or _bbox_to_xyxy(_normalize_bbox(initial_bbox), frame_w, frame_h)
                diagnostic["bbox"] = _xyxy_to_bbox(target_xyxy, frame_w, frame_h)
            else:
                self._last_known_xyxy = target_xyxy

            tracked.append(_xyxy_to_bbox(target_xyxy, frame_w, frame_h))
            diagnostics.append(diagnostic)

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
    ) -> tuple[tuple[float, float, float, float] | None, dict[str, Any]]:
        frame_h, frame_w = frame_bgr.shape[:2]
        fallback_xyxy = tuple(float(value) for value in (self._last_known_xyxy or seed_xyxy)) if (self._last_known_xyxy or seed_xyxy) is not None else None
        raw_boxes = self._detect(frame_bgr)
        if not raw_boxes:
            self._lost_frames += 1
            prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
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
            )

        tracked = self._update_tracks(raw_boxes)
        if len(tracked) == 0 or getattr(tracked, "tracker_id", None) is None:
            self._lost_frames += 1
            prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
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
            )

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

        target_xyxy = self._xyxy_for_tracker_id(tracked, self._target_tracker_id)
        if target_xyxy is None:
            self._lost_frames += 1
            prediction_xyxy = self._predict_next_xyxy(frame_w, frame_h)
            if self._lost_frames >= _RELOCK_AFTER_LOST_FRAMES:
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
                    rejected_reasons=["no_candidate_passed_relock_gate"],
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
        if continuity_reasons:
            self._lost_frames += 1
            _add_flag(self.quality_flags, PERSON_TRACKER_CONTINUITY_REJECTED_FLAG)
            self._clear_pending_relock()
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
            )

        self._last_known_xyxy = target_xyxy
        self._record_accepted_bbox(frame_index, target_xyxy)
        self._lost_frames = 0
        self._clear_pending_relock()
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

    def _clear_pending_relock(self) -> None:
        self._pending_relock_tracker_id = None
        self._pending_relock_count = 0

    def _clear_pending_detector_relock(self) -> None:
        self._pending_detector_relock_xyxy = None
        self._pending_detector_relock_source = None
        self._pending_detector_relock_count = 0

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
        steps = max(self._lost_frames, 1)
        dx = (last_bbox[0] - first_bbox[0]) / span * steps
        dy = (last_bbox[1] - first_bbox[1]) / span * steps
        predicted = (last_bbox[0] + dx, last_bbox[1] + dy, last_bbox[2] + dx, last_bbox[3] + dy)
        return _clamp_xyxy(predicted, frame_w, frame_h)

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
        bootstrap_allowed = (
            allow_seed_bootstrap
            and not self._accepted_xyxy_history
            and reference_coverage >= _INITIAL_BOOTSTRAP_MIN_SEED_COVERAGE
            and distance <= frame_diagonal * _INITIAL_BOOTSTRAP_MAX_CENTER_DISTANCE_RATIO
            and candidate_width / reference_width <= _INITIAL_BOOTSTRAP_MAX_WIDTH_RATIO
            and candidate_height / reference_height <= _INITIAL_BOOTSTRAP_MAX_HEIGHT_RATIO
        )
        if distance > frame_diagonal * center_jump_ratio and not bootstrap_allowed:
            reasons.append("center_jump")

        reference_area = _xyxy_area(reference_xyxy)
        candidate_area = _xyxy_area(candidate_xyxy)
        if reference_area > 0 and candidate_area > 0:
            area_ratio = candidate_area / reference_area
            if area_ratio < area_ratio_range[0] or area_ratio > area_ratio_range[1]:
                if not (bootstrap_allowed and area_ratio <= _INITIAL_BOOTSTRAP_MAX_AREA_RATIO):
                    reasons.append("area_ratio")

        reference_aspect = _xyxy_aspect_ratio(reference_xyxy)
        candidate_aspect = _xyxy_aspect_ratio(candidate_xyxy)
        if reference_aspect > 0 and candidate_aspect > 0:
            aspect_ratio = candidate_aspect / reference_aspect
            if aspect_ratio < aspect_ratio_range[0] or aspect_ratio > aspect_ratio_range[1]:
                if not bootstrap_allowed:
                    reasons.append("aspect_ratio")
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
            allow_seed_bootstrap=True,
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

        if reference_xyxy is not None:
            reference_distance = _center_distance(candidate_xyxy, reference_xyxy)
            reference_diagonal = max(_xyxy_diagonal(reference_xyxy), 1.0)
            reference_iou = _iou(candidate_xyxy, reference_xyxy)
            if reference_iou < _DETECTOR_RELOCK_MIN_IOU and reference_distance > reference_diagonal * _DETECTOR_RELOCK_REFERENCE_DIAGONAL_RATIO:
                reasons.append("far_from_reference")

        if prediction_xyxy is not None:
            prediction_distance = _center_distance(candidate_xyxy, prediction_xyxy)
            prediction_diagonal = max(_xyxy_diagonal(prediction_xyxy), 1.0)
            prediction_iou = _iou(candidate_xyxy, prediction_xyxy)
            if prediction_iou < _DETECTOR_RELOCK_MIN_IOU and prediction_distance > prediction_diagonal * _DETECTOR_RELOCK_REFERENCE_DIAGONAL_RATIO:
                reasons.append("far_from_prediction")

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
            if min(distance_to_prediction, distance_to_reference) <= frame_diagonal * _DETECTOR_RELOCK_SCALE_JUMP_MAX_CENTER_RATIO:
                reasons = [reason for reason in reasons if reason != "area_ratio"]

        if self._lost_frames >= _RELOCK_AFTER_LOST_FRAMES and confidence >= _DETECTOR_RELOCK_MIN_CONFIDENCE:
            if _is_plausible_human_xyxy(candidate_xyxy, frame_w=frame_w, frame_h=frame_h):
                reasons = [
                    reason
                    for reason in reasons
                    if reason not in {"center_jump", "area_ratio", "aspect_ratio", "far_from_reference", "far_from_prediction"}
                ]

        return list(dict.fromkeys(reasons))

    def _select_detector_relock_candidate(
        self,
        boxes: Sequence[tuple[float, float, float, float, float]],
        *,
        reference_xyxy: Sequence[float] | None,
        prediction_xyxy: Sequence[float] | None,
        frame_w: int,
        frame_h: int,
        source: str,
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
            reasons = self._detector_relock_rejection_reasons(
                candidate_xyxy,
                reference_xyxy,
                prediction_xyxy,
                frame_w=frame_w,
                frame_h=frame_h,
                confidence=confidence,
            )
            if reasons:
                rejected.append(
                    {
                        "bbox": _xyxy_to_bbox(candidate_xyxy, frame_w, frame_h),
                        "source": source,
                        "candidate_confidence": round(confidence, 4),
                        "reasons": reasons,
                    }
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
    ) -> tuple[tuple[float, float, float, float] | None, dict[str, Any]]:
        self._clear_pending_relock()
        reference_xyxy = self._last_known_xyxy or fallback_xyxy or seed_xyxy
        rejected_candidates: list[dict[str, Any]] = []
        candidate_xyxy, confidence, rejected = self._select_detector_relock_candidate(
            raw_boxes,
            reference_xyxy=reference_xyxy,
            prediction_xyxy=prediction_xyxy,
            frame_w=frame_w,
            frame_h=frame_h,
            source="full_frame_yolo_relock",
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
        if prediction_xyxy is not None:
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
            if iou < _RELOCK_MIN_IOU and distance > previous_diagonal * _RELOCK_PREVIOUS_DIAGONAL_RATIO:
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
                seed_coverage = _bbox_coverage(seed_xyxy, xyxy)
                candidate_coverage = _bbox_coverage(xyxy, seed_xyxy)
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
        for index, tracker_id in enumerate(tracker_ids):
            tid = int(tracker_id)
            xyxy = tuple(float(value) for value in detections.xyxy[index])
            reasons: list[str] = []
            if self._is_static_candidate(tid, frame_w):
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
                    if reason not in {"center_jump", "area_ratio", "aspect_ratio", "low_iou_and_far_from_previous_bbox"}
                ]
            if reasons:
                rejected.append(
                    {
                        "tracker_id": tid,
                        "bbox": _xyxy_to_bbox(xyxy, frame_w, frame_h),
                        "reasons": list(dict.fromkeys(reasons)),
                    }
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
) -> tuple[list[dict[str, float]], list[str]]:
    tracked, flags, _ = _track_forward_detailed(frame_paths, initial_bbox, effective_fps=effective_fps)
    return tracked, flags


def _track_forward_detailed(
    frame_paths: Sequence[Path],
    initial_bbox: dict[str, Any],
    *,
    effective_fps: float | None,
) -> tuple[list[dict[str, float]], list[str], list[dict[str, Any]]]:
    tracker = PersonBBoxTracker(effective_fps=effective_fps)
    return tracker.track_sequence_detailed(frame_paths, initial_bbox)


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


def track_person_bbox_detailed(
    frame_paths: Sequence[Path],
    initial_bbox: dict[str, Any],
    *,
    initial_frame_index: int = 0,
    effective_fps: float | None = None,
) -> tuple[list[dict[str, float]], list[str], list[dict[str, Any]]]:
    """Detailed variant of track_person_bbox for analysis/debug diagnostics."""

    frames = list(frame_paths)
    if not frames:
        return [], [], []

    normalized_initial = _normalize_bbox(initial_bbox)
    start_index = max(0, min(int(initial_frame_index or 0), len(frames) - 1))
    if start_index == 0:
        return _track_forward_detailed(frames, normalized_initial, effective_fps=effective_fps)

    backward_frames = list(reversed(frames[: start_index + 1]))
    backward_tracked, backward_flags, backward_diagnostics = _track_forward_detailed(
        backward_frames,
        normalized_initial,
        effective_fps=effective_fps,
    )
    forward_tracked, forward_flags, forward_diagnostics = _track_forward_detailed(
        frames[start_index:],
        normalized_initial,
        effective_fps=effective_fps,
    )
    tracked = list(reversed(backward_tracked))[0:-1] + forward_tracked
    diagnostics = list(reversed(backward_diagnostics))[0:-1] + forward_diagnostics
    for frame_index, diagnostic in enumerate(diagnostics):
        diagnostic["frame_index"] = frame_index
        if frame_index < len(frames):
            diagnostic["frame"] = frames[frame_index].name
    flags = list(dict.fromkeys([*backward_flags, *forward_flags, PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG]))
    return tracked, flags, diagnostics
