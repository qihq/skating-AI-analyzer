"""跳跃种类几何证据提取。

职责: 从姿态序列和 T/A/L 关键帧中提取 Lutz/Flip 等跳跃判别的弱几何线索。
输入: pose_data、key_frames 与有效采样帧率。
输出: 可注入视觉 prompt 的 jump_subtype_evidence 字典。
"""
from __future__ import annotations

import math
from typing import Any


ANKLE_LEFT = 27
ANKLE_RIGHT = 28
HIP_LEFT = 23
HIP_RIGHT = 24
SHOULDER_LEFT = 11
SHOULDER_RIGHT = 12
TOE_PULSE_THRESHOLD = 0.04
MIN_CONFIDENCE = 0.5


def _frame_number(frame_name: str) -> int:
    digits = "".join(char for char in frame_name if char.isdigit())
    return int(digits or "0")


def _keypoint(keypoints: list[dict[str, Any]], index: int, min_visibility: float = 0.3) -> dict[str, float] | None:
    if index >= len(keypoints):
        return None
    raw = keypoints[index]
    if raw.get("x") is None or raw.get("y") is None:
        return None
    visibility = float(raw.get("visibility", 0.0) or 0.0)
    if visibility < min_visibility and not raw.get("interpolated"):
        return None
    return {
        "x": float(raw.get("x", 0.0) or 0.0),
        "y": float(raw.get("y", 0.0) or 0.0),
        "z": float(raw.get("z", 0.0) or 0.0),
        "visibility": visibility,
    }


def _midpoint(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2, "z": (a["z"] + b["z"]) / 2}


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _sample_window(
    frames: list[dict[str, Any]],
    takeoff_index: int,
    effective_fps: float,
    seconds: float,
) -> list[tuple[int, dict[str, Any]]]:
    count = max(1, round(seconds * max(effective_fps, 1e-6)))
    start = max(0, takeoff_index - count)
    return list(enumerate(frames[start : takeoff_index + 1], start=start))


def _takeoff_index(frames: list[dict[str, Any]], key_frames: dict[str, Any]) -> int:
    takeoff_name = str(key_frames.get("T") or "")
    takeoff_number = _frame_number(takeoff_name)
    if takeoff_number:
        for index, frame in enumerate(frames):
            if _frame_number(str(frame.get("frame", ""))) == takeoff_number:
                return index
        return max(0, min(len(frames) - 1, takeoff_number - 1))
    return max(0, len(frames) // 3)


def _com(frame: dict[str, Any]) -> dict[str, float] | None:
    keypoints = frame.get("keypoints", [])
    if not isinstance(keypoints, list):
        return None
    points = [
        point
        for point in (
            _keypoint(keypoints, SHOULDER_LEFT),
            _keypoint(keypoints, SHOULDER_RIGHT),
            _keypoint(keypoints, HIP_LEFT),
            _keypoint(keypoints, HIP_RIGHT),
        )
        if point is not None
    ]
    if not points:
        return None
    return {
        "x": sum(point["x"] for point in points) / len(points),
        "y": sum(point["y"] for point in points) / len(points),
        "z": sum(point["z"] for point in points) / len(points),
    }


def _shoulder_width(frame: dict[str, Any]) -> float:
    keypoints = frame.get("keypoints", [])
    if not isinstance(keypoints, list):
        return 0.0
    left = _keypoint(keypoints, SHOULDER_LEFT)
    right = _keypoint(keypoints, SHOULDER_RIGHT)
    return _distance(left, right) if left and right else 0.0


def _takeoff_foot(window: list[tuple[int, dict[str, Any]]]) -> tuple[str, float]:
    left_score = 0.0
    right_score = 0.0
    samples = 0
    for _, frame in window:
        keypoints = frame.get("keypoints", [])
        if not isinstance(keypoints, list):
            continue
        left = _keypoint(keypoints, ANKLE_LEFT, 0.0)
        right = _keypoint(keypoints, ANKLE_RIGHT, 0.0)
        if not left or not right:
            continue
        left_score += left["visibility"] + max(0.0, -left["z"]) * 0.2
        right_score += right["visibility"] + max(0.0, -right["z"]) * 0.2
        samples += 1
    if samples == 0:
        return "unknown", 0.0
    total = left_score + right_score
    confidence = abs(left_score - right_score) / total if total > 0 else 0.0
    if confidence < 0.08:
        return "unknown", round(confidence, 3)
    return ("left" if left_score > right_score else "right"), round(min(1.0, confidence * 4), 3)


def _ankle_series(window: list[tuple[int, dict[str, Any]]], ankle_index: int) -> list[float]:
    values: list[float] = []
    for _, frame in window:
        keypoints = frame.get("keypoints", [])
        point = _keypoint(keypoints, ankle_index, 0.0) if isinstance(keypoints, list) else None
        if point is not None:
            values.append(point["y"])
    return values


def _toe_pick(window: list[tuple[int, dict[str, Any]]]) -> tuple[bool, float, float]:
    strengths: list[float] = []
    for ankle_index in (ANKLE_LEFT, ANKLE_RIGHT):
        values = _ankle_series(window, ankle_index)
        if len(values) < 3:
            continue
        deltas = [values[index] - values[index - 1] for index in range(1, len(values))]
        for previous, current in zip(deltas, deltas[1:]):
            # 设计说明: 图像坐标 y 向下增大，点冰表现为脚踝短促下探后回弹。
            if previous > TOE_PULSE_THRESHOLD and current < -TOE_PULSE_THRESHOLD:
                strengths.append(min(abs(previous), abs(current)))
    strength = max(strengths) if strengths else 0.0
    confidence = min(1.0, strength / max(TOE_PULSE_THRESHOLD, 1e-6))
    return strength >= TOE_PULSE_THRESHOLD, round(strength, 4), round(confidence, 3)


def _feet_together(frame: dict[str, Any]) -> tuple[bool, float, float]:
    keypoints = frame.get("keypoints", [])
    if not isinstance(keypoints, list):
        return False, 0.0, 0.0
    left = _keypoint(keypoints, ANKLE_LEFT)
    right = _keypoint(keypoints, ANKLE_RIGHT)
    shoulder_width = _shoulder_width(frame)
    if not left or not right or shoulder_width < 1e-6:
        return False, 0.0, 0.0
    ratio = _distance(left, right) / shoulder_width
    confidence = max(0.0, min(1.0, (0.45 - ratio) / 0.25))
    return ratio < 0.3, round(ratio, 4), round(confidence, 3)


def _free_leg_swing(window: list[tuple[int, dict[str, Any]]]) -> tuple[float, float]:
    amplitudes: list[float] = []
    for hip_index, ankle_index in ((HIP_LEFT, ANKLE_LEFT), (HIP_RIGHT, ANKLE_RIGHT)):
        angles: list[float] = []
        for _, frame in window:
            keypoints = frame.get("keypoints", [])
            if not isinstance(keypoints, list):
                continue
            hip = _keypoint(keypoints, hip_index)
            ankle = _keypoint(keypoints, ankle_index)
            if hip and ankle:
                angles.append(math.atan2(ankle["y"] - hip["y"], ankle["x"] - hip["x"]))
        if len(angles) >= 2:
            amplitudes.append(max(angles) - min(angles))
    amplitude = max((abs(value) for value in amplitudes), default=0.0)
    confidence = min(1.0, amplitude / 0.35)
    return round(amplitude, 4), round(confidence, 3)


def _body_facing(frame: dict[str, Any]) -> tuple[float, float] | None:
    keypoints = frame.get("keypoints", [])
    if not isinstance(keypoints, list):
        return None
    left = _keypoint(keypoints, SHOULDER_LEFT)
    right = _keypoint(keypoints, SHOULDER_RIGHT)
    if not left or not right:
        return None
    shoulder_axis = (right["x"] - left["x"], right["y"] - left["y"])
    return -shoulder_axis[1], shoulder_axis[0]


def _approach_direction(window: list[tuple[int, dict[str, Any]]]) -> tuple[str, float]:
    points = [(index, _com(frame), _body_facing(frame)) for index, frame in window]
    valid = [(index, com, facing) for index, com, facing in points if com is not None and facing is not None]
    if len(valid) < 2:
        return "unknown", 0.0
    _, first_com, _ = valid[0]
    _, last_com, facing = valid[-1]
    if first_com is None or last_com is None or facing is None:
        return "unknown", 0.0
    velocity = (last_com["x"] - first_com["x"], last_com["y"] - first_com["y"])
    velocity_norm = math.hypot(*velocity)
    facing_norm = math.hypot(*facing)
    if velocity_norm < 1e-6 or facing_norm < 1e-6:
        return "unknown", 0.0
    cosine = (velocity[0] * facing[0] + velocity[1] * facing[1]) / (velocity_norm * facing_norm)
    confidence = min(1.0, abs(cosine))
    return ("forward" if cosine >= 0 else "backward"), round(confidence, 3)


def _edge_score(window: list[tuple[int, dict[str, Any]]]) -> tuple[float, str, float]:
    points = [(_com(frame), _body_facing(frame)) for _, frame in window]
    valid = [(com, facing) for com, facing in points if com is not None and facing is not None]
    if len(valid) < 3:
        return 0.5, "unknown", 0.0

    com_points = [item[0] for item in valid if item[0] is not None]
    facing = valid[-1][1]
    if len(com_points) < 3 or facing is None:
        return 0.5, "unknown", 0.0
    p0 = com_points[0]
    p1 = com_points[len(com_points) // 2]
    p2 = com_points[-1]
    v1 = (p1["x"] - p0["x"], p1["y"] - p0["y"])
    v2 = (p2["x"] - p1["x"], p2["y"] - p1["y"])
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    facing_cross = facing[0] * v2[1] - facing[1] * v2[0]
    signal = cross * (1 if facing_cross >= 0 else -1)
    magnitude = abs(signal) / max(math.hypot(*v1) * math.hypot(*v2), 1e-6)
    confidence = min(1.0, magnitude * 4)
    if confidence < 0.5:
        return 0.5, "unknown", round(confidence, 3)
    score = 0.5 + (0.5 * max(-1.0, min(1.0, signal / max(abs(signal), 1e-6))))
    label = "likely_inside_edge" if score > 0.5 else "likely_outside_edge"
    return round(score, 3), label, round(confidence, 3)


def compute_jump_evidence(
    pose_data: dict[str, Any],
    key_frames: dict[str, Any],
    effective_fps: float,
) -> dict[str, Any]:
    """Compute weak geometric evidence for jump subtype recognition.

    Args:
        pose_data: Pose payload containing per-frame keypoints.
        key_frames: Biomechanics key frame labels, especially T.
        effective_fps: Sampling rate on the real action timeline.

    Returns:
        Evidence dictionary safe to serialize into LLM prompts.

    Raises:
        无。输入不足时返回 unknown/低置信度字段。
    """
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not isinstance(frames, list) or not frames:
        return {"quality_flags": ["jump_evidence_insufficient_pose"]}

    fps = max(float(effective_fps or 5.0), 1e-6)
    takeoff_idx = _takeoff_index(frames, key_frames if isinstance(key_frames, dict) else {})
    takeoff_frame = frames[takeoff_idx]
    short_window = _sample_window(frames, takeoff_idx, fps, 0.2)
    approach_window = _sample_window(frames, takeoff_idx, fps, 0.5)

    takeoff_foot, takeoff_foot_confidence = _takeoff_foot(short_window)
    toe_pick_pulse, toe_pick_strength, toe_pick_confidence = _toe_pick(short_window)
    feet_together, feet_distance_ratio, feet_confidence = _feet_together(takeoff_frame)
    swing_amplitude, swing_confidence = _free_leg_swing(approach_window)
    approach_direction, approach_confidence = _approach_direction(approach_window)
    edge_score, edge_label, edge_confidence = _edge_score(approach_window)

    evidence: dict[str, Any] = {
        "takeoff_foot": takeoff_foot if takeoff_foot_confidence >= MIN_CONFIDENCE else "unknown",
        "takeoff_foot_confidence": takeoff_foot_confidence,
        "toe_pick_pulse": toe_pick_pulse and toe_pick_confidence >= MIN_CONFIDENCE,
        "toe_pick_strength": toe_pick_strength,
        "toe_pick_confidence": toe_pick_confidence,
        "feet_together_at_takeoff": feet_together and feet_confidence >= MIN_CONFIDENCE,
        "feet_distance_shoulder_ratio": feet_distance_ratio,
        "feet_together_confidence": feet_confidence,
        "free_leg_swing_amplitude": swing_amplitude,
        "free_leg_swing_confidence": swing_confidence,
        "approach_direction": approach_direction if approach_confidence >= MIN_CONFIDENCE else "unknown",
        "approach_direction_confidence": approach_confidence,
        "pre_takeoff_edge_score": edge_score if edge_confidence >= MIN_CONFIDENCE else 0.5,
        "pre_takeoff_edge_label": edge_label if edge_confidence >= MIN_CONFIDENCE else "unknown",
        "pre_takeoff_edge_confidence": edge_confidence,
        "quality_flags": [],
    }
    if edge_confidence < MIN_CONFIDENCE:
        evidence["quality_flags"].append("jump_edge_signal_weak")
    return evidence
