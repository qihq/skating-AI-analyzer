"""姿态关键点时序平滑与可见性插值。

职责: 对逐帧 MediaPipe 关键点执行 One-Euro 去抖，并在短时遮挡时补齐坐标。
输入: pose.py 输出的 frames 列表与有效采样帧率。
输出: 保持原 payload 结构的平滑 frames，插值点会附加 interpolated 标记。
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any


VISIBILITY_THRESHOLD = 0.5
MIN_DT_SECONDS = 1e-6


@dataclass
class OneEuroFilter:
    """One-Euro Filter，适合人体关键点时序去抖。

    Args:
        min_cutoff: 静止或低速状态下的最小截止频率。
        beta: 速度自适应系数，动作越快保留越多高频变化。
        d_cutoff: 导数低通滤波截止频率。
    """
    min_cutoff: float = 1.0
    beta: float = 0.05
    d_cutoff: float = 1.0
    _prev_x: float | None = None
    _prev_dx: float = 0.0
    _prev_t: float | None = None

    def _alpha(self, cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, t: float) -> float:
        """Filter one numeric sample."""
        if self._prev_t is None or self._prev_x is None:
            self._prev_x = x
            self._prev_t = t
            return x
        dt = max(t - self._prev_t, MIN_DT_SECONDS)
        dx = (x - self._prev_x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self._prev_dx
        # 设计说明: min_cutoff=1.0、beta=0.05 在静止落冰阶段强平滑，
        # 高速旋转/腾空阶段随速度放宽截止频率，避免真实动作被过度抹平。
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self._prev_x
        self._prev_x = x_hat
        self._prev_dx = dx_hat
        self._prev_t = t
        return x_hat


def _valid_effective_fps(effective_fps: float | None) -> float:
    try:
        value = float(effective_fps)
    except (TypeError, ValueError):
        return 5.0
    if math.isnan(value) or math.isinf(value) or value <= 0:
        return 5.0
    return value


def _keypoint_by_id(keypoints: list[dict[str, Any]], keypoint_id: int) -> dict[str, Any] | None:
    for keypoint in keypoints:
        if int(keypoint.get("id", -1)) == keypoint_id:
            return keypoint
    if keypoint_id < len(keypoints):
        return keypoints[keypoint_id]
    return None


def _visible_indices(values: list[dict[str, Any] | None]) -> list[int]:
    return [
        index
        for index, keypoint in enumerate(values)
        if keypoint is not None and float(keypoint.get("visibility", 0.0) or 0.0) >= VISIBILITY_THRESHOLD
    ]


def _interpolate_value(before: dict[str, Any], after: dict[str, Any], ratio: float, axis: str) -> float:
    return float(before.get(axis, 0.0) or 0.0) + (float(after.get(axis, 0.0) or 0.0) - float(before.get(axis, 0.0) or 0.0)) * ratio


def _interpolate_keypoint(
    values: list[dict[str, Any] | None],
    frame_index: int,
    visible: list[int],
) -> dict[str, Any] | None:
    current = values[frame_index]
    if current is not None and float(current.get("visibility", 0.0) or 0.0) >= VISIBILITY_THRESHOLD:
        result = dict(current)
        result["interpolated"] = bool(result.get("interpolated", False))
        return result

    previous_candidates = [index for index in visible if index < frame_index]
    next_candidates = [index for index in visible if index > frame_index]
    if not previous_candidates or not next_candidates:
        return dict(current) if current is not None else None

    previous_index = previous_candidates[-1]
    next_index = next_candidates[0]
    previous = values[previous_index]
    next_keypoint = values[next_index]
    if previous is None or next_keypoint is None:
        return dict(current) if current is not None else None

    ratio = (frame_index - previous_index) / max(next_index - previous_index, 1)
    interpolated = dict(current or previous)
    interpolated["x"] = _interpolate_value(previous, next_keypoint, ratio, "x")
    interpolated["y"] = _interpolate_value(previous, next_keypoint, ratio, "y")
    interpolated["z"] = _interpolate_value(previous, next_keypoint, ratio, "z")
    interpolated["visibility"] = float((current or {}).get("visibility", 0.0) or 0.0)
    interpolated["interpolated"] = True
    return interpolated


def smooth_keypoint_sequence(frames: list[dict[str, Any]], effective_fps: float) -> list[dict[str, Any]]:
    """Smooth and interpolate pose keypoints across frames.

    Args:
        frames: Pose frames containing keypoints in MediaPipe 33-point format.
        effective_fps: Sampling rate on the real action timeline.

    Returns:
        A deep-copied frame list with smoothed x/y coordinates and interpolation markers.
    """
    if not frames:
        return []

    fps = _valid_effective_fps(effective_fps)
    smoothed_frames = copy.deepcopy(frames)
    max_keypoint_count = max(
        (len(frame.get("keypoints", [])) for frame in smoothed_frames if isinstance(frame.get("keypoints", []), list)),
        default=0,
    )
    if max_keypoint_count == 0:
        return smoothed_frames

    for keypoint_id in range(max_keypoint_count):
        series = [
            _keypoint_by_id(frame.get("keypoints", []), keypoint_id)
            if isinstance(frame.get("keypoints", []), list)
            else None
            for frame in smoothed_frames
        ]
        visible = _visible_indices(series)
        if not visible:
            for frame in smoothed_frames:
                keypoints = frame.get("keypoints", [])
                if not isinstance(keypoints, list):
                    continue
                keypoint = _keypoint_by_id(keypoints, keypoint_id)
                if keypoint is None:
                    continue
                keypoint["x"] = None
                keypoint["y"] = None
                keypoint["z"] = None
                keypoint["interpolated"] = False
            continue

        x_filter = OneEuroFilter()
        y_filter = OneEuroFilter()
        for frame_index, frame in enumerate(smoothed_frames):
            keypoints = frame.get("keypoints", [])
            if not isinstance(keypoints, list):
                continue
            keypoint = _keypoint_by_id(keypoints, keypoint_id)
            if keypoint is None:
                continue

            prepared = _interpolate_keypoint(series, frame_index, visible)
            if prepared is None:
                continue

            timestamp = frame_index / fps
            keypoint.update(prepared)
            keypoint["x"] = x_filter.filter(float(prepared.get("x", 0.0) or 0.0), timestamp)
            keypoint["y"] = y_filter.filter(float(prepared.get("y", 0.0) or 0.0), timestamp)

    return smoothed_frames
