"""T/A/L key-frame candidate detection for jump analysis.

The detector is intentionally conservative: incomplete or noisy inputs return
low-confidence candidates with warnings instead of raising. Coordinates follow
MediaPipe image space, where smaller y means higher in the frame.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    "motion_peak_score": 0.30,
    "com_velocity_score": 0.25,
    "pose_visibility_score": 0.20,
    "knee_angle_change_score": 0.15,
    "phase_order_score": 0.10,
}
MISSING_POSE_CONFIDENCE_CAP = 0.55
EXCLUDED_TRACKING_STATES = {"lost", "interpolated", "low_confidence"}
MOTION_FALLBACK_MIN_PEAK_SCORE = 0.04
PARTIAL_TAL_LOW_MOTION_FALLBACK_MIN_PEAK_SCORE = 0.015
ORDERED_TAL_CONFIDENCE_FLOOR = 0.35
ORDERED_TAL_LOW_CONFIDENCE_MIN_RAW = 0.20


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
        },
        warnings,
    )


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


def _best_motion_record(records: list[tuple[int, str, float, float]], *, prefer_late: bool) -> tuple[int, str, float, float]:
    if prefer_late:
        return max(records, key=lambda item: (item[3], item[0]))
    return max(records, key=lambda item: (item[3], -item[0]))


def _motion_fallback_candidates(
    motion_scores: dict[str, Any] | None,
    effective_fps: float,
    quality_flags: list[str],
    *,
    min_peak_score: float = MOTION_FALLBACK_MIN_PEAK_SCORE,
) -> dict[str, Any] | None:
    records = _motion_records(motion_scores, effective_fps)
    if len(records) < 3:
        return None

    scores = [record[3] for record in records]
    max_score = max(scores)
    if max_score < min_peak_score:
        return None

    peak_index = max(range(len(records)), key=lambda index: records[index][3])
    if 0 < peak_index < len(records) - 1:
        takeoff_record = _best_motion_record(records[:peak_index], prefer_late=True)
        apex_record = records[peak_index]
        landing_record = _best_motion_record(records[peak_index + 1 :], prefer_late=False)
    else:
        first_cut = max(1, len(records) // 3)
        second_cut = max(first_cut + 1, (len(records) * 2) // 3)
        second_cut = min(second_cut, len(records) - 1)
        takeoff_record = _best_motion_record(records[:first_cut], prefer_late=True)
        apex_record = _best_motion_record(records[first_cut:second_cut], prefer_late=True)
        landing_record = _best_motion_record(records[second_cut:], prefer_late=False)

    low = min(scores)
    span = max(max_score - low, 1e-9)
    absolute_motion_score = _clamp(max_score / 0.12)

    def confidence_for(record: tuple[int, str, float, float]) -> tuple[float, float]:
        normalized = _clamp((record[3] - low) / span) if span > 1e-9 else _clamp(record[3] / max(max_score, 1e-9))
        confidence = _clamp(0.36 + 0.12 * normalized + 0.08 * absolute_motion_score, high=0.54)
        return round(confidence, 3), normalized

    warning = "keyframe_candidates_motion_fallback"
    flags = [*quality_flags, warning, "tal_candidate_motion_fallback_low_precision"]
    if max_score < MOTION_FALLBACK_MIN_PEAK_SCORE:
        flags.append("tal_candidate_motion_fallback_low_motion")
    candidates: dict[str, Any] = {"quality_flags": list(dict.fromkeys(flags))}
    for role, record in (("T", takeoff_record), ("A", apex_record), ("L", landing_record)):
        confidence, normalized = confidence_for(record)
        candidates[role] = _motion_only_candidate(
            record,
            role,
            confidence,
            normalized,
            [warning, f"{role.lower()}_pose_signal_insufficient"],
        )
    return candidates


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


def _normalized_motion(signals: list[_FrameSignal]) -> list[float]:
    values = [signal.motion_score for signal in signals if signal.motion_score is not None]
    if not values:
        return [0.0 for _ in signals]
    low = min(values)
    high = max(values)
    if high - low <= 1e-9:
        return [0.0 if signal.motion_score is None else _clamp(signal.motion_score / max(high, 1e-9)) for signal in signals]
    return [0.0 if signal.motion_score is None else _clamp((signal.motion_score - low) / (high - low)) for signal in signals]


def _detect_apex(signals: list[_FrameSignal], smoothed_com: list[float | None]) -> dict[str, Any]:
    valid = [(index, value) for index, value in enumerate(smoothed_com) if value is not None]
    if len(valid) < 3:
        return _empty_candidate(["insufficient_com_signal"])

    local_minima: list[int] = []
    for index, value in valid:
        previous_values = [item for item in smoothed_com[max(0, index - 2) : index] if item is not None]
        next_values = [item for item in smoothed_com[index + 1 : index + 3] if item is not None]
        if previous_values and next_values and value <= min(previous_values) and value <= min(next_values):
            local_minima.append(index)

    apex_index = min(local_minima or [index for index, _ in valid], key=lambda item: smoothed_com[item] or float("inf"))
    raw_values = [signal.com_y for signal in signals if signal.com_y is not None]
    vertical_range = max(raw_values) - min(raw_values) if raw_values else 0.0
    surrounding = [
        smoothed_com[item]
        for item in range(max(0, apex_index - 2), min(len(smoothed_com), apex_index + 3))
        if item != apex_index and smoothed_com[item] is not None
    ]
    local_prominence = (sum(surrounding) / len(surrounding) - (smoothed_com[apex_index] or 0.0)) if surrounding else 0.0
    warnings: list[str] = []
    motion_score = 0.0 if signals[apex_index].motion_score is None else 0.5
    com_score = 0.65 * _clamp(vertical_range / 0.08) + 0.35 * _clamp(local_prominence / 0.035)
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
            "local_minimum": apex_index in local_minima,
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


def _detect_takeoff(
    signals: list[_FrameSignal],
    smoothed_com: list[float | None],
    smoothed_knee: list[float | None],
    motion_norm: list[float],
    apex_index: int | None,
) -> dict[str, Any]:
    if apex_index is None or apex_index <= 0:
        return _empty_candidate(["takeoff_window_missing"])

    scored: list[tuple[float, int, dict[str, Any], list[str]]] = []
    for index in range(1, apex_index):
        current_knee = smoothed_knee[index]
        previous_knee = smoothed_knee[index - 1]
        current_com = smoothed_com[index]
        previous_com = smoothed_com[index - 1]
        next_com = smoothed_com[index + 1] if index + 1 < len(smoothed_com) else None
        if current_knee is None and current_com is None:
            continue

        knee_extension = max(0.0, (current_knee or 0.0) - previous_knee) if previous_knee is not None and current_knee is not None else 0.0
        ascent_parts = []
        if previous_com is not None and current_com is not None:
            ascent_parts.append(max(0.0, previous_com - current_com))
        if current_com is not None and next_com is not None:
            ascent_parts.append(max(0.0, current_com - next_com))
        com_ascent = sum(ascent_parts) / len(ascent_parts) if ascent_parts else 0.0

        extension_score = _clamp(knee_extension / 25.0)
        ascent_score = _clamp(com_ascent / 0.035)
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
        evidence = {
            "knee_extension_deg": round(knee_extension, 3),
            "com_ascent_delta": round(com_ascent, 5),
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
            },
        }
        scored.append((score, index, evidence, warnings))

    if not scored:
        return _empty_candidate(["takeoff_signal_missing"])

    score, index, evidence, warnings = max(scored, key=lambda item: (item[0], -abs((apex_index or 0) - item[1])))
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
) -> dict[str, Any]:
    if apex_index is None or apex_index >= len(signals) - 1:
        return _empty_candidate(["landing_window_missing"])

    scored: list[tuple[float, int, dict[str, Any], list[str]]] = []
    for index in range(apex_index + 1, len(signals)):
        current_ankle = smoothed_ankle[index]
        previous_ankle = smoothed_ankle[index - 1] if index > 0 else None
        current_knee = smoothed_knee[index]
        previous_knee = smoothed_knee[index - 1] if index > 0 else None
        current_com = smoothed_com[index]
        previous_com = smoothed_com[index - 1] if index > 0 else None
        next_com = smoothed_com[index + 1] if index + 1 < len(smoothed_com) else None
        if current_ankle is None and current_knee is None and current_com is None:
            continue

        ankle_return = max(0.0, current_ankle - previous_ankle) if current_ankle is not None and previous_ankle is not None else 0.0
        knee_absorption = max(0.0, previous_knee - current_knee) if current_knee is not None and previous_knee is not None else 0.0
        descent_parts = []
        if previous_com is not None and current_com is not None:
            descent_parts.append(max(0.0, current_com - previous_com))
        if current_com is not None and next_com is not None:
            descent_parts.append(max(0.0, next_com - current_com))
        com_descent = sum(descent_parts) / len(descent_parts) if descent_parts else 0.0

        ankle_score = _clamp(ankle_return / 0.035)
        knee_score = _clamp(knee_absorption / 22.0)
        descent_score = _clamp(com_descent / 0.035)
        com_velocity_score = 0.65 * ankle_score + 0.35 * descent_score
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
        evidence = {
            "ankle_return_delta": round(ankle_return, 5),
            "knee_absorption_deg": round(knee_absorption, 3),
            "com_descent_delta": round(com_descent, 5),
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
            },
        }
        scored.append((score, index, evidence, warnings))

    if not scored:
        return _empty_candidate(["landing_signal_missing"])

    score, index, evidence, warnings = max(scored, key=lambda item: (item[0], -item[1]))
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


def _apply_ordered_confidence_floor(candidates: Iterable[dict[str, Any]]) -> None:
    for candidate in candidates:
        confidence = _to_float(candidate.get("confidence"))
        if confidence is None or confidence >= ORDERED_TAL_CONFIDENCE_FLOOR:
            continue
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        visibility = _to_float(evidence.get("visibility_score"))
        has_visible_ordered_candidate = (
            bool(candidate.get("frame_id"))
            and confidence >= ORDERED_TAL_LOW_CONFIDENCE_MIN_RAW
            and visibility is not None
            and visibility >= MIN_VISIBILITY
        )
        if confidence < 0.30 and not has_visible_ordered_candidate:
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
    signals = _build_signals(pose_data, motion_scores, fps)
    if not signals:
        fallback = _motion_fallback_candidates(motion_scores, fps, quality_flags + ["keyframe_candidates_insufficient_pose"])
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
    if valid_pose_count < 3:
        fallback = _motion_fallback_candidates(motion_scores, fps, quality_flags)
        if fallback is not None:
            fallback["excluded_pose_frames"] = excluded_counts
            return fallback

    smoothed_com = _smooth([signal.com_y for signal in signals])
    smoothed_knee = _smooth([signal.knee_angle for signal in signals])
    smoothed_ankle = _smooth([signal.ankle_y for signal in signals])
    motion_norm = _normalized_motion(signals)

    apex = _detect_apex(signals, smoothed_com)
    apex_index = _candidate_index(apex)
    takeoff = _detect_takeoff(signals, smoothed_com, smoothed_knee, motion_norm, apex_index)
    landing = _detect_landing(signals, smoothed_com, smoothed_ankle, smoothed_knee, motion_norm, apex_index)

    t_index = _candidate_index(takeoff)
    a_index = _candidate_index(apex)
    l_index = _candidate_index(landing)
    if t_index is None or a_index is None or l_index is None:
        fallback = _motion_fallback_candidates(
            motion_scores,
            fps,
            quality_flags + ["tal_candidate_incomplete", "tal_order_unresolved"],
            min_peak_score=PARTIAL_TAL_LOW_MOTION_FALLBACK_MIN_PEAK_SCORE,
        )
        if fallback is not None:
            fallback["excluded_pose_frames"] = excluded_counts
            return fallback
        quality_flags.append("tal_candidate_incomplete")
        quality_flags.append("tal_order_unresolved")
    elif not (t_index < a_index < l_index):
        quality_flags.append("tal_order_invalid")
        message = "tal_order_invalid"
        takeoff["warnings"].append(message)
        apex["warnings"].append(message)
        landing["warnings"].append(message)
    else:
        _apply_ordered_confidence_floor((takeoff, apex, landing))

    if any(candidate.get("confidence", 0.0) < 0.35 for candidate in (takeoff, apex, landing)):
        quality_flags.append("tal_candidate_confidence_low")

    if (
        "tal_order_invalid" in quality_flags
        and (fallback := _motion_fallback_candidates(motion_scores, fps, quality_flags)) is not None
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
