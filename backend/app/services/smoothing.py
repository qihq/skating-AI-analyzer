"""姿态关键点时序平滑与可见性插值。

职责: 在实际时间及可信同人连续段内执行居中局部拟合，保留独立的展示插值质量。
输入: 带同帧时间/身份的 frames，及仅供旧格式兼容的采样帧率。
输出: 保持点ID和画布坐标系的副本，附加 temporal/quality 来源。OneEuroFilter 留供既有关键帧消费者使用。
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

    Returns:
        通过 filter() 返回单个平滑后的数值。

    Raises:
        无。
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
        """Filter one numeric sample.

        Args:
            x: Current raw sample.
            t: Sample timestamp in seconds.

        Returns:
            Smoothed sample value.

        Raises:
            无。
        """
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


# Offline centered quadratic fit. Uniform-cadence kernel [-1,4,10,4,-1]/16
# preserves constant velocity/acceleration and removes alternating jitter.
# Two endpoints per segment and runs shorter than five remain unchanged.
# One-sample model spikes remain ambiguous without independent evidence.
PROCESSING_VERSION = "pose-temporal.v2"
MAX_CONTINUOUS_GAP_SECONDS = 0.5
MAX_INTERPOLATED_POINTS = 3


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def pose_temporal_segments(frames: list[dict[str, Any]], effective_fps: float) -> list[int | None]:
    """Bound processing to trusted, increasing actual-time/identity segments."""
    fps = _valid_effective_fps(effective_fps)
    explicit = any("timestamp" in f or "analysis_timestamp" in f or "temporal" in f for f in frames)
    segments: list[int | None] = []
    previous_time = None
    previous_identity = None
    previous_valid = False
    segment = -1
    for i, frame in enumerate(frames):
        temporal = dict(frame.get("temporal") or {})
        if "analysis_timestamp" in temporal:
            timestamp = finite_number(temporal["analysis_timestamp"])
            source = temporal.get("time_source", "unknown")
        elif "analysis_timestamp" in frame:
            timestamp = finite_number(frame["analysis_timestamp"])
            source = "frame_analysis_timestamp"
        elif "timestamp" in frame:
            timestamp = finite_number(frame["timestamp"])
            source = "frame_timestamp"
        elif not explicit:
            timestamp, source = i / fps, "legacy_effective_fps"
        else:
            timestamp, source = None, "unknown"
        identity = (frame.get("identity_id"), frame.get("tracker_id"))
        state_valid = (bool(frame.get("keypoints")) and
                       frame.get("tracking_state") in (None, "tracked") and
                       frame.get("input_binding_valid") is not False)
        increasing = timestamp is not None and (previous_time is None or timestamp > previous_time)
        valid = state_valid and increasing
        boundary = (not previous_valid or identity != previous_identity or
                    (timestamp is not None and previous_time is not None and
                     timestamp - previous_time > MAX_CONTINUOUS_GAP_SECONDS))
        if valid and boundary:
            segment += 1
        temporal.update(processing_version=PROCESSING_VERSION, time_source=source,
                        analysis_timestamp=timestamp, segment_id=segment if valid else None,
                        continuous=valid and not boundary)
        if not valid:
            temporal["boundary_reason"] = "unknown_or_nonincreasing_time" if not increasing else "untrusted_or_missing_target"
        elif boundary:
            temporal["boundary_reason"] = "segment_start_or_gap_or_identity_change"
        frame["temporal"] = temporal
        segments.append(segment if valid else None)
        previous_time, previous_identity, previous_valid = timestamp, identity, valid
    return segments


def _native(point: dict[str, Any]) -> bool:
    quality = point.get("quality") or {}
    return (not point.get("interpolated") and quality.get("analysis_usable") is not False and
            (finite_number(point.get("visibility")) or 0.) >= VISIBILITY_THRESHOLD and
            all(finite_number(point.get(axis)) is not None for axis in ("x", "y")))


def _fit_current(times: list[float], values: list[float]) -> float:
    import numpy as np
    offsets = np.asarray(times) - times[2]
    scale = max(abs(offsets))
    if scale <= MIN_DT_SECONDS:
        return values[2]
    design = np.column_stack((np.ones(5), offsets/scale, (offsets/scale)**2))
    weights = np.sqrt([1., 4., 6., 4., 1.])
    weighted = design * weights[:, None]
    if np.linalg.cond(weighted) > 1e6:
        return values[2]
    return float(np.linalg.lstsq(weighted, np.asarray(values)*weights, rcond=None)[0][0])


def smooth_keypoint_sequence(frames: list[dict[str, Any]], effective_fps: float) -> list[dict[str, Any]]:
    """Immutable-source time-aligned pose with independent display/analysis quality.

    Fit only five consecutive native points in one trusted segment. Missing
    points cannot enter the fit. Timestamp-weighted display interpolation has
    a three-point/.5-analysis-second cap and never upgrades native evidence.
    """
    output = copy.deepcopy(frames)
    segments = pose_temporal_segments(output, effective_fps)
    from app.services.limb_consistency import assess_limb_consistency
    limb_quality = assess_limb_consistency(output, segments, _native)
    by_id: dict[int, dict[int, dict[str, Any]]] = {}
    for i, frame in enumerate(output):
        for point in frame.get("keypoints", []):
            point_id = point.get("id")
            if isinstance(point_id, int):
                by_id.setdefault(point_id, {})[i] = point
    for point_id, series in by_id.items():
        raw = copy.deepcopy(series)
        native = {i for i, p in raw.items() if _native(p) and segments[i] is not None
                  and limb_quality.get((i, point_id), {}).get("status") != "uncertain"}
        for i, point in series.items():
            original = raw[i]
            coordinates = {a: finite_number(original.get(a)) for a in ("x", "y", "z")}
            quality = {"processing_version": PROCESSING_VERSION,
                       "raw_visibility": finite_number(original.get("visibility")),
                       "raw_coordinates": coordinates, "upstream_quality": original.get("quality"),
                       "source": "native_observation" if i in native else "low_visibility",
                       "analysis_usable": i in native}
            point["quality"] = quality
            point.update(coordinates)
            limb = limb_quality.get((i, point_id))
            if limb is not None:
                quality["limb_consistency"] = limb
            if limb is not None and limb["status"] == "uncertain":
                # Preserve the actual raw observation for transparent replay.
                # It must not be used as a smoothing/interpolation anchor.
                quality.update(source="limb_uncertain", analysis_usable=False)
                point["interpolated"] = False
                continue
            if i in native:
                point["interpolated"] = False
                window = list(range(i-2, i+3))
                if all(j in native and segments[j] == segments[i] for j in window):
                    times = [output[j]["temporal"]["analysis_timestamp"] for j in window]
                    for axis in ("x", "y"):
                        point[axis] = _fit_current(times, [float(raw[j][axis]) for j in window])
                    quality.update(source="smoothed_native", support_frame_indices=window)
                continue
            quality["source"] = "display_interpolation" if original.get("interpolated") else (
                "missing" if coordinates["x"] is None or coordinates["y"] is None else "low_visibility")
            if original.get("interpolated"):
                continue
            if _native(original) and segments[i] is None:
                # A clock failure must not erase a real current-frame observation.
                quality["source"] = "native_observation" if output[i].get("input_binding_valid") is not False and output[i].get("tracking_state") in (None, "tracked") else "untrusted_observation"
                point["interpolated"] = False
                continue
            point["interpolated"] = False
            before = max((j for j in native if j < i and segments[j] == segments[i]), default=None) if segments[i] is not None else None
            after = min((j for j in native if j > i and segments[j] == segments[i]), default=None) if segments[i] is not None else None
            if before is not None and after is not None:
                start = output[before]["temporal"]["analysis_timestamp"]
                end = output[after]["temporal"]["analysis_timestamp"]
                if (after-before-1 <= MAX_INTERPOLATED_POINTS and 0 < end-start <= MAX_CONTINUOUS_GAP_SECONDS
                        and not any(limb_quality.get((j, point_id), {}).get("status") == "uncertain"
                                    for j in range(before+1, after))):
                    ratio = (output[i]["temporal"]["analysis_timestamp"]-start)/(end-start)
                    for axis in ("x", "y", "z"):
                        a, b = finite_number(raw[before].get(axis)), finite_number(raw[after].get(axis))
                        point[axis] = a+(b-a)*ratio if a is not None and b is not None else None
                    point["interpolated"] = True
                    quality.update(source="display_interpolation", support_frame_indices=[before, after], ratio=ratio)
                    continue
            point.update(x=None, y=None, z=None)
    return output
