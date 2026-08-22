from __future__ import annotations

"""Build evaluator proposal, classification and moment evidence from source observations.

The adapter intentionally consumes a small allowlist of raw source fields. It
does not read existing action labels, semantic moments, rotation outputs or
evaluation annotations.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.analysis_v2.action_classification import ActionClassificationEvidence
from app.analysis_v2.event_proposals import EventProposal, ProposalEvidenceSample
from app.analysis_v2.profile_moments import MomentEvidenceSample
from app.analysis_v2.rotation import (
    RotationEvidenceSample,
    TargetCropFrame,
    attach_crop_appearance,
    attach_optical_flow,
    extract_target_crop_appearance,
    extract_target_crop_optical_flow,
)


_CORE_JOINTS = frozenset({0, 11, 12, 23, 24, 27, 28})
_ROTATION_WINDOW_SEC = .9
_MAX_SOURCE_GAP_SEC = .22
_MIN_ROTATION_WINDOW_SAMPLES = 5
_MIN_ROTATION_RUN_SEC = .4


@dataclass(frozen=True)
class SourceEvidenceBundle:
    source_video_hash: str
    source_duration_sec: float
    source_timeline_fingerprint: str
    proposal_samples: tuple[ProposalEvidenceSample, ...]
    moment_samples: tuple[MomentEvidenceSample, ...]
    rotation_samples: tuple[RotationEvidenceSample, ...]
    temporal_samples: tuple[Mapping[str, float], ...]
    rotation_diagnostics: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SourceFrame:
    source_frame_index: int
    pts_sec: float
    path: Path | None
    motion: float
    tracking_state: str
    points: Mapping[int, Mapping[str, Any]]
    bbox: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class _AngularSignal:
    turns: float
    direction: int
    direction_agreement: float
    reliability: float


@dataclass(frozen=True)
class _CameraMotion:
    matrix: np.ndarray
    reliability: float


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clamp(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _number(value, default)))


def _records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _raw_source_payload(analysis: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = analysis.get("raw_diagnostics")
    return raw if isinstance(raw, Mapping) else analysis


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Mapping):
        return None
    x = _number(value.get("x", value.get("left")), -1)
    y = _number(value.get("y", value.get("top")), -1)
    if "width" in value or "height" in value:
        right = x + _number(value.get("width"), -1)
        bottom = y + _number(value.get("height"), -1)
    else:
        right = _number(value.get("right"), -1)
        bottom = _number(value.get("bottom"), -1)
    if x < 0 or y < 0 or right <= x or bottom <= y:
        return None
    return tuple(max(0.0, min(1.0, item)) for item in (x, y, right, bottom))  # type: ignore[return-value]


def _tracking_state(value: Any) -> str:
    state = str(value or "").strip().lower()
    if state in {"tracked", "relocked", "confirmed", "auto_locked", "locked", "manual"}:
        return "confirmed"
    if state in {"uncertain", "low_confidence", "reused", "pending"}:
        return "uncertain"
    return "lost"


def _visible_points(frame: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    return {
        int(point["id"]): point
        for point in _records(frame.get("keypoints"))
        if isinstance(point.get("id"), (int, float)) and _clamp(point.get("visibility", point.get("confidence", 0))) >= .35
    }


def _timeline(raw: Mapping[str, Any]) -> tuple[list[_SourceFrame], float, float]:
    motion = raw.get("motion_scores")
    if not isinstance(motion, Mapping):
        motion = raw.get("frame_motion_scores") if isinstance(raw.get("frame_motion_scores"), Mapping) else {}
    selected = _records(motion.get("selected"))
    pose_payload = raw.get("pose_data") if isinstance(raw.get("pose_data"), Mapping) else {}
    poses = _records(pose_payload.get("frames"))
    if not selected and poses:
        selected = [
            {
                "frame_id": str(item.get("frame") or f"frame_{index + 1:04d}").removesuffix(".jpg"),
                "source_frame_index": item.get("source_frame_index"),
                "timestamp": item.get("pts_sec", item.get("timestamp")),
                "motion_score": 0,
            }
            for index, item in enumerate(poses)
            if item.get("pts_sec", item.get("timestamp")) is not None
        ]
    pose_by_name = {str(item.get("frame") or "").removesuffix(".jpg"): item for item in poses}
    sampling = raw.get("sampling") if isinstance(raw.get("sampling"), Mapping) else {}
    source_fps = max(.001, _number(sampling.get("source_fps"), _number(sampling.get("effective_fps"), 30.0)))
    frame_paths = [Path(str(item)) for item in raw.get("frame_paths", ()) if str(item)] if isinstance(raw.get("frame_paths"), Sequence) else []
    paths_by_name = {path.stem: path for path in frame_paths}
    bboxes = _records(raw.get("bbox_per_frame"))
    peak = max((_number(item.get("motion_score")) for item in selected), default=0.0)
    motion_scale = max(peak, .01)
    frames: list[_SourceFrame] = []
    for index, item in enumerate(selected):
        name = str(item.get("frame_id") or f"frame_{index + 1:04d}").removesuffix(".jpg")
        pose = pose_by_name.get(name, poses[index] if index < len(poses) else {})
        raw_pts = item.get("pts_sec", item.get("timestamp"))
        if raw_pts is None:
            continue
        pts = max(0.0, _number(raw_pts))
        points = _visible_points(pose)
        raw_bbox = bboxes[index] if index < len(bboxes) else pose.get("target_bbox")
        state = _tracking_state(pose.get("tracking_state", pose.get("tracker_state")))
        frames.append(_SourceFrame(
            source_frame_index=max(0, int(_number(item.get("source_frame_index"), round(pts * source_fps)))),
            pts_sec=pts,
            path=paths_by_name.get(name),
            motion=_clamp(_number(item.get("motion_score")) / motion_scale),
            tracking_state=state,
            points=points,
            bbox=_bbox(raw_bbox),
        ))
    frames.sort(key=lambda item: (item.pts_sec, item.source_frame_index))
    duration = _number(
        motion.get("source_duration_sec"),
        _number(sampling.get("action_window_end", sampling.get("window_end_sec")), frames[-1].pts_sec if frames else .001),
    )
    if frames:
        duration = max(duration, frames[-1].pts_sec + 1 / source_fps)
    return frames, max(duration, .001), source_fps


def _point_pair(frame: _SourceFrame, left: int, right: int) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    return (frame.points[left], frame.points[right]) if left in frame.points and right in frame.points else None


def _center(frame: _SourceFrame) -> tuple[float, float] | None:
    points = [frame.points[index] for index in (11, 12, 23, 24) if index in frame.points]
    if len(points) < 2:
        return None
    return (
        sum(_number(point.get("x")) for point in points) / len(points),
        sum(_number(point.get("y")) for point in points) / len(points),
    )


def _height(frame: _SourceFrame) -> float | None:
    nose = frame.points.get(0)
    ankles = [frame.points[index] for index in (27, 28) if index in frame.points]
    if nose is None or not ankles:
        return None
    ankle_y = sum(_number(point.get("y")) for point in ankles) / len(ankles)
    value = abs(ankle_y - _number(nose.get("y")))
    return value if value >= .05 else None


def _orientation(frame: _SourceFrame, left: int, right: int) -> float | None:
    pair = _point_pair(frame, left, right)
    if pair is None:
        return None
    left_point, right_point = pair
    return math.atan2(
        _number(right_point.get("y")) - _number(left_point.get("y")),
        _number(right_point.get("x")) - _number(left_point.get("x")),
    )


def _pose_quality(frame: _SourceFrame) -> float:
    values = [_clamp(point.get("visibility", point.get("confidence", 0))) for index, point in frame.points.items() if index in _CORE_JOINTS]
    return sum(values) / len(values) if values else 0.0


def _axis_stability(frame: _SourceFrame) -> float:
    shoulders = _point_pair(frame, 11, 12)
    hips = _point_pair(frame, 23, 24)
    if shoulders is None or hips is None:
        return 0.0
    shoulder_center = tuple(sum(_number(point.get(axis)) for point in shoulders) / 2 for axis in ("x", "y"))
    hip_center = tuple(sum(_number(point.get(axis)) for point in hips) / 2 for axis in ("x", "y"))
    dx = abs(shoulder_center[0] - hip_center[0])
    dy = abs(shoulder_center[1] - hip_center[1])
    return _clamp(dy / max(dx + dy, 1e-6) * 1.15)


def _pose_dynamics(previous: _SourceFrame | None, current: _SourceFrame) -> float:
    if previous is None:
        return 0.0
    prior_center, center = _center(previous), _center(current)
    prior_height, height = _height(previous), _height(current)
    common = sorted(set(previous.points).intersection(current.points))
    if prior_center is None or center is None or prior_height is None or height is None or len(common) < 4:
        return 0.0
    distances = []
    for joint in common:
        before, after = previous.points[joint], current.points[joint]
        before_x = (_number(before.get("x")) - prior_center[0]) / prior_height
        before_y = (_number(before.get("y")) - prior_center[1]) / prior_height
        after_x = (_number(after.get("x")) - center[0]) / height
        after_y = (_number(after.get("y")) - center[1]) / height
        distances.append(math.hypot(after_x - before_x, after_y - before_y))
    return _clamp((sum(distances) / len(distances)) / .22)


def _joint_angle(first: Mapping[str, Any], vertex: Mapping[str, Any], third: Mapping[str, Any]) -> float | None:
    before = (_number(first.get("x")) - _number(vertex.get("x")), _number(first.get("y")) - _number(vertex.get("y")))
    after = (_number(third.get("x")) - _number(vertex.get("x")), _number(third.get("y")) - _number(vertex.get("y")))
    scale = math.hypot(*before) * math.hypot(*after)
    if scale <= 1e-9:
        return None
    cosine = max(-1.0, min(1.0, (before[0] * after[0] + before[1] * after[1]) / scale))
    return math.acos(cosine)


def _extension(frame: _SourceFrame) -> float:
    height = _height(frame)
    if height is None:
        return 0.0
    ankles = _point_pair(frame, 27, 28)
    if ankles is None:
        return 0.0
    leg_chains: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]] = []
    for hip, knee, ankle in ((23, 25, 27), (24, 26, 28)):
        if hip in frame.points and knee in frame.points and ankle in frame.points:
            leg_chains.append((frame.points[hip], frame.points[knee], frame.points[ankle]))
    if len(leg_chains) != 2:
        return 0.0
    ankle_lift = abs(_number(ankles[0].get("y")) - _number(ankles[1].get("y"))) / height
    ankle_separation = math.hypot(
        _number(ankles[0].get("x")) - _number(ankles[1].get("x")),
        _number(ankles[0].get("y")) - _number(ankles[1].get("y")),
    ) / height
    free_side = 0 if _number(ankles[0].get("y")) < _number(ankles[1].get("y")) else 1
    free_leg_angle = _joint_angle(*leg_chains[free_side])
    if free_leg_angle is None:
        return 0.0
    lift_score = _clamp((ankle_lift - .10) / .22)
    separation_score = _clamp((ankle_separation - .13) / .30)
    straight_score = _clamp((free_leg_angle - math.radians(145)) / math.radians(30))
    gate = min(lift_score, straight_score)
    return _clamp((.48 * lift_score + .27 * separation_score + .25 * straight_score) * gate)


def _sustained_scores(
    frames: Sequence[_SourceFrame],
    values: Sequence[float],
    *,
    threshold: float,
    min_duration_sec: float,
) -> list[float]:
    accepted = [0.0 for _ in values]
    runs: list[list[int]] = []
    active: list[int] = []
    for index, value in enumerate([*values, 0.0]):
        contiguous = (
            not active
            or index < len(frames) and frames[index].pts_sec - frames[active[-1]].pts_sec <= _MAX_SOURCE_GAP_SEC
        )
        if index < len(values) and value >= threshold and contiguous:
            active.append(index)
            continue
        if active:
            runs.append(active)
        active = [index] if index < len(values) and value >= threshold else []
    for run in runs:
        if len(run) < 2 or frames[run[-1]].pts_sec - frames[run[0]].pts_sec < min_duration_sec:
            continue
        for index in run:
            accepted[index] = values[index]
    return accepted


def _airborne_indices(frames: Sequence[_SourceFrame]) -> set[int]:
    ankle_y: list[float | None] = []
    centers: list[float | None] = []
    heights: list[float | None] = []
    for frame in frames:
        ankles = [frame.points[index] for index in (27, 28) if index in frame.points]
        ankle_y.append(sum(_number(point.get("y")) for point in ankles) / len(ankles) if ankles else None)
        center = _center(frame)
        centers.append(center[1] if center else None)
        heights.append(_height(frame))
    raised: list[bool] = []
    for index, (ankle, center, height) in enumerate(zip(ankle_y, centers, heights)):
        nearby = [value for pos, value in enumerate(ankle_y) if value is not None and abs(frames[pos].pts_sec - frames[index].pts_sec) <= 1.25]
        nearby_centers = [value for pos, value in enumerate(centers) if value is not None and abs(frames[pos].pts_sec - frames[index].pts_sec) <= 1.25]
        if ankle is None or center is None or height is None or len(nearby) < 5 or len(nearby_centers) < 5:
            raised.append(False)
            continue
        contact_baseline = float(np.percentile(nearby, 75))
        center_baseline = float(np.percentile(nearby_centers, 60))
        raised.append(contact_baseline - ankle >= .16 * height and center_baseline - center >= .10 * height)
    accepted: set[int] = set()
    start: int | None = None
    for index, value in enumerate([*raised, False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            prior = start > 0 and ankle_y[start - 1] is not None and heights[start - 1] is not None
            later = index < len(frames) and ankle_y[index] is not None and heights[index] is not None
            boundary_scale_ratio = (
                min(float(heights[start - 1]), float(heights[index])) / max(float(heights[start - 1]), float(heights[index]))
                if prior and later else 0.0
            )
            if index - start >= 2 and prior and later and boundary_scale_ratio >= .78:
                accepted.update(range(start, index))
            start = None
    return accepted


def _crop_bounds(frame: _SourceFrame) -> tuple[float, float, float, float] | None:
    visible = [point for point in frame.points.values() if _clamp(point.get("visibility", point.get("confidence", 0))) >= .35]
    boxes: list[tuple[float, float, float, float]] = []
    if visible:
        boxes.append((
            min(_number(point.get("x")) for point in visible),
            min(_number(point.get("y")) for point in visible),
            max(_number(point.get("x")) for point in visible),
            max(_number(point.get("y")) for point in visible),
        ))
    if frame.bbox is not None:
        boxes.append(frame.bbox)
    if not boxes:
        return None
    left = min(item[0] for item in boxes)
    top = min(item[1] for item in boxes)
    right = max(item[2] for item in boxes)
    bottom = max(item[3] for item in boxes)
    width, height = max(right - left, .04), max(bottom - top, .08)
    return (
        max(0.0, left - width * .25),
        max(0.0, top - height * .18),
        min(1.0, right + width * .25),
        min(1.0, bottom + height * .12),
    )


def _target_crops(frames: Sequence[_SourceFrame]) -> tuple[list[TargetCropFrame], list[np.ndarray], list[int]]:
    metadata: list[TargetCropFrame] = []
    crops: list[np.ndarray] = []
    positions: list[int] = []
    for position, frame in enumerate(frames):
        bounds = _crop_bounds(frame)
        if frame.path is None or bounds is None:
            continue
        image = cv2.imread(str(frame.path), cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            continue
        height, width = image.shape[:2]
        left, top, right, bottom = bounds
        x1, y1 = max(0, int(left * width)), max(0, int(top * height))
        x2, y2 = min(width, max(x1 + 1, int(math.ceil(right * width)))), min(height, max(y1 + 1, int(math.ceil(bottom * height))))
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        crops.append(cv2.resize(crop, (128, 192), interpolation=cv2.INTER_LINEAR))
        metadata.append(TargetCropFrame(source_frame_index=frame.source_frame_index, pts_sec=frame.pts_sec))
        positions.append(position)
    return metadata, crops, positions


def _background_mask(frame: _SourceFrame, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    mask = np.full((height, width), 255, dtype=np.uint8)
    bounds = _crop_bounds(frame)
    if bounds is not None:
        left, top, right, bottom = bounds
        pad_x = max(.02, (right - left) * .18)
        pad_y = max(.02, (bottom - top) * .12)
        x1 = max(0, int((left - pad_x) * width))
        y1 = max(0, int((top - pad_y) * height))
        x2 = min(width, int(math.ceil((right + pad_x) * width)))
        y2 = min(height, int(math.ceil((bottom + pad_y) * height)))
        cv2.rectangle(mask, (x1, y1), (x2, y2), 0, -1)
    border = max(2, int(min(height, width) * .015))
    mask[:border, :] = 0
    mask[-border:, :] = 0
    mask[:, :border] = 0
    mask[:, -border:] = 0
    return mask


def _camera_motion(
    previous: _SourceFrame,
    current: _SourceFrame,
    previous_image: np.ndarray | None,
    current_image: np.ndarray | None,
) -> _CameraMotion | None:
    if previous_image is None or current_image is None or previous_image.shape != current_image.shape:
        return None
    height, width = previous_image.shape[:2]
    previous_mask = _background_mask(previous, (height, width))
    points = cv2.goodFeaturesToTrack(
        previous_image,
        maxCorners=320,
        qualityLevel=.008,
        minDistance=5,
        mask=previous_mask,
        blockSize=5,
    )
    if points is None or len(points) < 12:
        return None
    tracked, status, errors = cv2.calcOpticalFlowPyrLK(
        previous_image,
        current_image,
        points,
        None,
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01),
    )
    if tracked is None or status is None:
        return None
    current_mask = _background_mask(current, (height, width))
    before: list[np.ndarray] = []
    after: list[np.ndarray] = []
    flattened_errors = errors.reshape(-1) if errors is not None else np.zeros(len(points), dtype=np.float32)
    for source, target, valid, error in zip(points.reshape(-1, 2), tracked.reshape(-1, 2), status.reshape(-1), flattened_errors):
        x, y = int(round(float(target[0]))), int(round(float(target[1])))
        if not valid or error > 32 or x < 0 or y < 0 or x >= width or y >= height or current_mask[y, x] == 0:
            continue
        before.append(source)
        after.append(target)
    if len(before) < 10:
        return None
    before_array = np.asarray(before, dtype=np.float32)
    after_array = np.asarray(after, dtype=np.float32)
    matrix, inliers = cv2.estimateAffinePartial2D(
        before_array,
        after_array,
        method=cv2.RANSAC,
        ransacReprojThreshold=max(1.5, min(height, width) * .008),
        maxIters=2000,
        confidence=.99,
        refineIters=10,
    )
    if matrix is None or inliers is None:
        return None
    accepted = inliers.reshape(-1).astype(bool)
    inlier_count = int(accepted.sum())
    inlier_ratio = inlier_count / len(before_array)
    scale = math.sqrt(max(0.0, float(np.linalg.det(matrix[:, :2]))))
    if inlier_count < 8 or inlier_ratio < .38 or not .72 <= scale <= 1.38:
        return None
    inlier_points = before_array[accepted]
    span_x = float(np.ptp(inlier_points[:, 0])) / max(width, 1)
    span_y = float(np.ptp(inlier_points[:, 1])) / max(height, 1)
    spatial_coverage = _clamp(math.sqrt(span_x * span_y) / .55)
    reliability = _clamp(.42 * inlier_ratio + .28 * min(1.0, inlier_count / 55) + .30 * spatial_coverage)
    if reliability < .30:
        return None
    return _CameraMotion(matrix=matrix, reliability=reliability)


def _target_geometry(frame: _SourceFrame, shape: tuple[int, int]) -> tuple[tuple[float, float], float] | None:
    height, width = shape
    bounds = frame.bbox
    center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2) if bounds is not None else _center(frame)
    normalized_height = bounds[3] - bounds[1] if bounds is not None else _height(frame)
    if center is None or normalized_height is None or normalized_height <= 0:
        return None
    return (center[0] * width, center[1] * height), normalized_height * height


def _camera_compensated_track_motion(
    frames: Sequence[_SourceFrame],
) -> tuple[list[float], list[float], list[str], list[tuple[float, float] | None]]:
    images = [cv2.imread(str(frame.path), cv2.IMREAD_GRAYSCALE) if frame.path is not None else None for frame in frames]
    velocities: list[tuple[float, float] | None] = [None for _ in frames]
    reliabilities = [0.0 for _ in frames]
    provenance = ["camera_motion_unobservable" for _ in frames]
    for index in range(1, len(frames)):
        previous, current = frames[index - 1], frames[index]
        previous_image, current_image = images[index - 1], images[index]
        estimate = _camera_motion(previous, current, previous_image, current_image)
        if estimate is None or previous_image is None or current_image is None:
            continue
        previous_geometry = _target_geometry(previous, previous_image.shape[:2])
        current_geometry = _target_geometry(current, current_image.shape[:2])
        if previous_geometry is None or current_geometry is None:
            continue
        previous_center, _previous_height = previous_geometry
        current_center, current_height = current_geometry
        predicted = estimate.matrix @ np.asarray([previous_center[0], previous_center[1], 1.0], dtype=np.float64)
        dt = current.pts_sec - previous.pts_sec
        if dt <= 0:
            continue
        velocities[index] = (
            (current_center[0] - float(predicted[0])) / max(current_height, 1.0) / dt,
            (current_center[1] - float(predicted[1])) / max(current_height, 1.0) / dt,
        )
        tracking_factor = 1.0 if current.tracking_state == "confirmed" else .55 if current.tracking_state == "uncertain" else 0.0
        reliabilities[index] = estimate.reliability * tracking_factor
        provenance[index] = "global_camera_motion_compensated"

    smoothed: list[tuple[float, float] | None] = [None for _ in frames]
    for index, frame in enumerate(frames):
        nearby = [
            velocities[position]
            for position in range(max(0, index - 1), min(len(frames), index + 2))
            if velocities[position] is not None
            and reliabilities[position] > 0
            and abs(frames[position].pts_sec - frame.pts_sec) <= _MAX_SOURCE_GAP_SEC
        ]
        if nearby:
            smoothed[index] = (
                float(np.median([value[0] for value in nearby])),
                float(np.median([value[1] for value in nearby])),
            )

    scores = [0.0 for _ in frames]
    for index in range(1, len(frames)):
        current_velocity = smoothed[index]
        if current_velocity is None or reliabilities[index] <= 0:
            continue
        previous_velocity = smoothed[index - 1]
        if previous_velocity is None:
            if index == 1 and frames[0].tracking_state == "confirmed":
                previous_velocity = (0.0, 0.0)
            else:
                continue
        velocity_change = math.hypot(
            current_velocity[0] - previous_velocity[0],
            current_velocity[1] - previous_velocity[1],
        )
        scores[index] = _clamp(velocity_change / .9)
    return scores, reliabilities, provenance, smoothed


def _wrap(value: float, period: float) -> float:
    return (value + period / 2) % period - period / 2


def _angular_signal(values: Sequence[float], *, period: float, reliability: float) -> _AngularSignal | None:
    if len(values) < _MIN_ROTATION_WINDOW_SAMPLES:
        return None
    deltas = [_wrap(current - previous, period) for previous, current in zip(values, values[1:])]
    signed = sum(deltas)
    travel = sum(abs(value) for value in deltas)
    if travel <= 1e-6:
        return None
    agreement = abs(signed) / travel
    turns = abs(signed) / (2 * math.pi)
    if turns < .07 or agreement < .55:
        return None
    return _AngularSignal(turns, 1 if signed > 0 else -1, agreement, _clamp(reliability * (.55 + .45 * agreement)))


def _flow_signal(samples: Sequence[RotationEvidenceSample]) -> _AngularSignal | None:
    present = [item for item in samples if item.optical_flow_rotation_rad is not None]
    if len(present) < _MIN_ROTATION_WINDOW_SAMPLES - 1:
        return None
    deltas = [float(item.optical_flow_rotation_rad) for item in present]
    signed, travel = sum(deltas), sum(abs(value) for value in deltas)
    if travel <= 1e-6:
        return None
    agreement = abs(signed) / travel
    turns = abs(signed) / (2 * math.pi)
    confidence = sum(item.optical_flow_confidence or 0 for item in present) / len(present)
    if turns < .07 or agreement < .55 or confidence < .18:
        return None
    return _AngularSignal(turns, 1 if signed > 0 else -1, agreement, _clamp(confidence * (.55 + .45 * agreement)))


def _combine_same_family(signals: Sequence[_AngularSignal]) -> _AngularSignal | None:
    if not signals:
        return None
    direction = max({item.direction for item in signals}, key=lambda value: sum(item.reliability for item in signals if item.direction == value))
    agreeing = [item for item in signals if item.direction == direction]
    if len(agreeing) < min(2, len(signals)):
        return None
    turns = sorted(item.turns for item in agreeing)[len(agreeing) // 2]
    reliability = sum(item.reliability for item in agreeing) / len(agreeing)
    agreement = sum(item.direction_agreement for item in agreeing) / len(agreeing)
    return _AngularSignal(turns, direction, agreement, reliability)


def _window_rotation(samples: Sequence[RotationEvidenceSample]) -> tuple[float, dict[str, Any]]:
    if len(samples) < _MIN_ROTATION_WINDOW_SAMPLES or samples[-1].pts_sec - samples[0].pts_sec < .45:
        return 0.0, {"reason": "insufficient_local_sampling", "families": {}}
    if max((current.pts_sec - previous.pts_sec for previous, current in zip(samples, samples[1:])), default=0) > _MAX_SOURCE_GAP_SEC:
        return 0.0, {"reason": "local_sampling_gap", "families": {}}

    pose_signals: list[_AngularSignal] = []
    for field in ("shoulder_orientation_rad", "hip_orientation_rad"):
        present = [item for item in samples if getattr(item, field) is not None]
        if len(present) < _MIN_ROTATION_WINDOW_SAMPLES:
            continue
        confidence = sum((item.pose_quality or 0) * (item.left_right_assignment_confidence or .5) for item in present) / len(present)
        signal = _angular_signal([float(getattr(item, field)) for item in present], period=2 * math.pi, reliability=confidence)
        if signal:
            pose_signals.append(signal)
    families: dict[str, _AngularSignal] = {}
    pose = _combine_same_family(pose_signals)
    if pose:
        families["pose_orientation"] = pose

    appearance_signals: list[_AngularSignal] = []
    for field, period in (("torso_appearance_phase_rad", 2 * math.pi), ("silhouette_orientation_rad", math.pi), ("limb_appearance_phase_rad", 2 * math.pi)):
        present = [item for item in samples if getattr(item, field) is not None]
        if len(present) < _MIN_ROTATION_WINDOW_SAMPLES:
            continue
        if field == "silhouette_orientation_rad":
            reliability = sum(item.silhouette_confidence or 0 for item in present) / len(present)
        else:
            reliability = .62
        signal = _angular_signal([float(getattr(item, field)) for item in present], period=period, reliability=reliability)
        if signal:
            appearance_signals.append(signal)
    appearance = _combine_same_family(appearance_signals)
    if appearance:
        families["target_crop_appearance"] = appearance
    flow = _flow_signal(samples)
    if flow:
        families["target_crop_motion"] = flow

    viable = {name: value for name, value in families.items() if value.reliability >= .18}
    direction_groups = {
        direction: {name: value for name, value in viable.items() if value.direction == direction}
        for direction in (-1, 1)
    }
    agreeing = max(direction_groups.values(), key=lambda items: sum(value.reliability for value in items.values()))
    if len(agreeing) < 2:
        return 0.0, {"reason": "insufficient_independent_signals", "families": _family_dump(families)}
    turns = [item.turns for item in agreeing.values()]
    if min(turns) / max(turns) < .42 and max(turns) - min(turns) > .12:
        return 0.0, {"reason": "conflicting_turn_hypotheses", "families": _family_dump(families)}
    movement = min(1.0, (sum(turns) / len(turns)) / .28)
    reliability = min(item.reliability for item in agreeing.values())
    direction_agreement = min(item.direction_agreement for item in agreeing.values())
    score = _clamp(.45 * movement + .30 * reliability + .25 * direction_agreement)
    return score, {"reason": "rotation_consensus", "families": _family_dump(families), "agreeing_families": sorted(agreeing)}


def _family_dump(families: Mapping[str, _AngularSignal]) -> dict[str, Any]:
    return {
        name: {
            "turns": round(value.turns, 5),
            "direction": value.direction,
            "direction_agreement": round(value.direction_agreement, 5),
            "reliability": round(value.reliability, 5),
        }
        for name, value in families.items()
    }


def _rotation_consensus(samples: Sequence[RotationEvidenceSample]) -> tuple[list[float], tuple[Mapping[str, Any], ...]]:
    raw_scores: list[float] = []
    diagnostics: list[dict[str, Any]] = []
    half = _ROTATION_WINDOW_SEC / 2
    for sample in samples:
        window = [item for item in samples if abs(item.pts_sec - sample.pts_sec) <= half]
        score, detail = _window_rotation(window)
        raw_scores.append(score)
        diagnostics.append({"source_frame_index": sample.source_frame_index, "pts_sec": sample.pts_sec, "raw_score": round(score, 5), **detail})

    final = [0.0 for _ in raw_scores]
    active: list[int] = []
    runs: list[list[int]] = []
    for index, score in enumerate([*raw_scores, 0.0]):
        contiguous = not active or samples[index].pts_sec - samples[active[-1]].pts_sec <= _MAX_SOURCE_GAP_SEC if index < len(samples) else False
        if score >= .45 and contiguous:
            active.append(index)
        else:
            if active:
                runs.append(active)
            active = [index] if score >= .45 and index < len(samples) else []
    for run in runs:
        duration = samples[run[-1]].pts_sec - samples[run[0]].pts_sec
        if len(run) >= _MIN_ROTATION_WINDOW_SAMPLES and duration >= _MIN_ROTATION_RUN_SEC:
            for index in run:
                final[index] = max(.55, raw_scores[index])
                diagnostics[index]["sustained"] = True
        else:
            for index in run:
                diagnostics[index]["sustained"] = False
                diagnostics[index]["reason"] = "rotation_consensus_not_sustained"
    return final, tuple(diagnostics)


def build_source_evidence(source_video_hash: str, analysis: Mapping[str, Any]) -> SourceEvidenceBundle:
    raw = _raw_source_payload(analysis)
    frames, duration, source_fps = _timeline(raw)
    timeline_payload = {"source": source_video_hash, "fps": source_fps, "pts": [round(item.pts_sec, 6) for item in frames]}
    timeline_fingerprint = "sha256:" + hashlib.sha256(json.dumps(timeline_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if not frames:
        return SourceEvidenceBundle(source_video_hash, duration, timeline_fingerprint, (), (), (), (), (), ("source_observations_absent",))

    airborne = _airborne_indices(frames)
    track_motion, camera_reliability, motion_provenance, track_velocities = _camera_compensated_track_motion(frames)
    extension_hold = _sustained_scores(
        frames,
        [_extension(frame) if frame.tracking_state == "confirmed" else 0.0 for frame in frames],
        threshold=.42,
        min_duration_sec=.38,
    )
    rotation_samples: list[RotationEvidenceSample] = []
    base_features: list[dict[str, float]] = []
    prior_velocity: tuple[float, float] | None = None
    for index, frame in enumerate(frames):
        previous = frames[index - 1] if index else None
        dt = frame.pts_sec - previous.pts_sec if previous else 0
        velocity = track_velocities[index]
        horizontal = _clamp(abs(velocity[0]) / 3.5) if velocity else 0.0
        vertical_velocity = -(velocity[1] if velocity else 0.0)
        edge_change = 0.0
        if velocity and prior_velocity:
            prior_norm = math.hypot(*prior_velocity)
            norm = math.hypot(*velocity)
            if prior_norm > .05 and norm > .05:
                cosine = max(-1.0, min(1.0, (prior_velocity[0] * velocity[0] + prior_velocity[1] * velocity[1]) / (prior_norm * norm)))
                edge_change = _clamp(math.acos(cosine) / (math.pi / 2))
        if velocity:
            prior_velocity = velocity
        dynamics = _pose_dynamics(previous, frame)
        extension = extension_hold[index]
        axis = _axis_stability(frame)
        step = _clamp(.45 * dynamics + .35 * horizontal + .20 * edge_change)
        base_features.append({
            "camera_compensated_track_motion": track_motion[index],
            "camera_reliability": camera_reliability[index],
            "pose_dynamics": dynamics,
            "horizontal_motion": horizontal,
            "vertical_velocity": max(-10.0, min(10.0, vertical_velocity)),
            "axis_stability": axis,
            "extension": extension,
            "edge_change": edge_change,
            "step_complexity": step,
        })
        rotation_samples.append(RotationEvidenceSample(
            source_frame_index=frame.source_frame_index,
            pts_sec=frame.pts_sec,
            phase="spin_main",
            frame_status="gap_after_previous" if dt > _MAX_SOURCE_GAP_SEC else "available",
            tracking_state=frame.tracking_state,  # type: ignore[arg-type]
            pose_quality=_pose_quality(frame),
            left_right_assignment_confidence=.72 if _orientation(frame, 11, 12) is not None and _orientation(frame, 23, 24) is not None else .35,
            shoulder_orientation_rad=_orientation(frame, 11, 12),
            hip_orientation_rad=_orientation(frame, 23, 24),
            upright_axis_confidence=axis,
            provenance=("source_pts", "confirmed_target_pose", "source_only_adapter"),
        ))

    crop_metadata, crops, _positions = _target_crops(frames)
    if crop_metadata:
        rotation_samples = list(attach_crop_appearance(rotation_samples, extract_target_crop_appearance(crop_metadata, crops)))
        rotation_samples = list(attach_optical_flow(rotation_samples, extract_target_crop_optical_flow(crop_metadata, crops)))
    periodicity, rotation_diagnostics = _rotation_consensus(rotation_samples)

    proposal_samples: list[ProposalEvidenceSample] = []
    moment_samples: list[MomentEvidenceSample] = []
    for index, (frame, features) in enumerate(zip(frames, base_features)):
        is_airborne = index in airborne
        contact_transition = is_airborne or index - 1 in airborne or index + 1 in airborne
        proposal_samples.append(ProposalEvidenceSample(
            source_frame_index=frame.source_frame_index,
            pts_sec=frame.pts_sec,
            camera_compensated_track_motion=features["camera_compensated_track_motion"],
            pose_dynamics=features["pose_dynamics"],
            ice_contact_proxy=.85 if contact_transition else .05,
            periodicity=periodicity[index],
            extension_hold=features["extension"],
            edge_complexity=features["step_complexity"],
            tracking_observable=frame.tracking_state != "lost",
            pose_observable=frame.tracking_state == "confirmed" and _pose_quality(frame) >= .45,
            camera_reliability=features["camera_reliability"],
            provenance=("source_pts", "source_only_adapter", motion_provenance[index], "confirmed_target_pose", "multi_signal_rotation_consensus" if periodicity[index] else "rotation_consensus_absent"),
        ))
        center = _center(frame)
        moment_samples.append(MomentEvidenceSample(
            source_frame_index=frame.source_frame_index,
            pts_sec=frame.pts_sec,
            frame_status=rotation_samples[index].frame_status,
            gap_before_sec=max(0.0, frame.pts_sec - frames[index - 1].pts_sec) if index else 0.0,
            tracking_state=frame.tracking_state,  # type: ignore[arg-type]
            pose_authoritative=frame.tracking_state == "confirmed" and _pose_quality(frame) >= .45,
            pose_quality=_pose_quality(frame),
            body_center_y=center[1] if center else None,
            vertical_velocity=features["vertical_velocity"],
            ice_contact=.15 if is_airborne else .82,
            airborne=.88 if is_airborne else .05,
            turning_motion=periodicity[index],
            rotation_periodicity=periodicity[index],
            axis_stability=features["axis_stability"],
            extension=features["extension"],
            edge_change=features["edge_change"],
            step_complexity=features["step_complexity"],
            motion_observable=frame.tracking_state != "lost",
            provenance=("source_pts", "source_only_adapter", "confirmed_target_pose"),
        ))
    warnings: list[str] = []
    if not crop_metadata:
        warnings.append("target_crop_evidence_absent")
    if not any(periodicity):
        warnings.append("rotation_consensus_absent")
    if not airborne:
        warnings.append("airborne_transition_absent")
    if not any(camera_reliability):
        warnings.append("global_camera_motion_unobservable")
    return SourceEvidenceBundle(
        source_video_hash=source_video_hash,
        source_duration_sec=duration,
        source_timeline_fingerprint=timeline_fingerprint,
        proposal_samples=tuple(proposal_samples),
        moment_samples=tuple(moment_samples),
        rotation_samples=tuple(rotation_samples),
        temporal_samples=tuple(base_features),
        rotation_diagnostics=rotation_diagnostics,
        warnings=tuple(warnings),
    )


def build_action_classification_evidence(bundle: SourceEvidenceBundle, proposal: EventProposal) -> ActionClassificationEvidence:
    positions = [
        index for index, sample in enumerate(bundle.proposal_samples)
        if proposal.start_pts <= sample.pts_sec <= proposal.end_pts
    ]
    samples = tuple(bundle.proposal_samples[index] for index in positions)
    moments = [bundle.moment_samples[index] for index in positions]
    temporal = [bundle.temporal_samples[index] for index in positions]

    def mean(values: Sequence[float | None]) -> float:
        present = [float(value) for value in values if value is not None]
        return sum(present) / len(present) if present else 0.0

    centers = [item.body_center_y for item in moments if item.body_center_y is not None]
    airborne = max((item.airborne or 0 for item in moments), default=0.0)
    vertical_excursion = _clamp((max(centers) - min(centers)) / .25) if centers and airborne >= .55 else 0.0
    periodic_values = [item.rotation_periodicity or 0 for item in moments]
    periodic_mean = mean(periodic_values)
    periodicity = _clamp(.65 * max(periodic_values, default=0.0) + .35 * periodic_mean)
    extension = mean([item.extension for item in moments]) * (1 - .8 * periodicity)
    features = {
        "motion": mean([item.camera_compensated_track_motion * item.camera_reliability for item in samples]),
        "pose_dynamics": mean([item.pose_dynamics for item in samples]),
        "ice_contact_proxy": max((item.ice_contact_proxy for item in samples), default=0.0),
        "periodicity": periodicity,
        "horizontal_motion": mean([item["horizontal_motion"] for item in temporal]),
        "vertical_excursion": vertical_excursion,
        "airborne_proxy": airborne,
        "turning_motion": periodicity,
        "contact_pattern": max((item.ice_contact_proxy for item in samples), default=0.0),
        "extension_proxy": extension,
        "axis_stability": mean([item.axis_stability for item in moments]),
        "step_complexity": mean([item.step_complexity for item in moments]),
    }
    return ActionClassificationEvidence(
        source_video_hash=bundle.source_video_hash,
        event_id=proposal.event_id,
        samples=samples,
        temporal_features={key: _clamp(value) for key, value in features.items()},
        tracking_coverage=proposal.tracking_coverage,
        pose_coverage=proposal.pose_coverage,
        observability=proposal.observability,
        evidence_sources=tuple(sorted({*proposal.evidence_sources, "source_only_adapter", "local_rotation_consensus"})),
        identity_confirmed=proposal.tracking_coverage >= .8,
    )
