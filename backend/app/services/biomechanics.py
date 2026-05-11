from __future__ import annotations

import math
from typing import Any


FPS = 5
MAX_AIR_TIME_SECONDS = 1.5
MAX_HEIGHT_CM = 120.0
MAX_TAKEOFF_SPEED_MPS = 6.5
MAX_ROTATION_RPS = 6.0


def _empty_jump_metrics() -> dict[str, Any]:
    return {
        "air_time_seconds": None,
        "estimated_height_cm": None,
        "takeoff_speed_mps": None,
        "rotation_rps": None,
        "estimated_rotations": None,
        "probable_jump_type": "unknown",
    }


def _empty_analysis(
    knee_angles: list[dict[str, Any]] | None = None,
    trunk_tilts: list[dict[str, Any]] | None = None,
    arm_symmetry: list[dict[str, Any]] | None = None,
    *,
    analysis_profile: str = "jump",
) -> dict[str, Any]:
    return {
        "analysis_profile": analysis_profile,
        "knee_angles": knee_angles or [],
        "trunk_tilts": trunk_tilts or [],
        "arm_symmetry": arm_symmetry or [],
        "com_trajectory": {"points": [], "vertical_range": 0},
        "rotation_stability": {"average_tilt_degrees": None, "stability_score": 65},
        "bio_subscores": {
            "takeoff_power": 65,
            "rotation_axis": 65,
            "arm_coordination": 65,
            "landing_absorption": 65,
            "core_stability": 65,
        },
        "discipline_metrics": {},
        "quality_flags": [],
        "key_frames": {},
        "jump_metrics": _empty_jump_metrics() if analysis_profile == "jump" else None,
        "jump_metrics_status": "invalid" if analysis_profile == "jump" else "not_applicable",
        "jump_metrics_warning": "未检测到有效跳跃数据" if analysis_profile == "jump" else None,
    }


def _point(keypoints: list[dict[str, Any]], index: int) -> dict[str, float] | None:
    if index >= len(keypoints):
        return None
    raw = keypoints[index]
    if float(raw.get("visibility", 0.0)) < 0.5:
        return None
    return {"x": float(raw.get("x", 0.0)), "y": float(raw.get("y", 0.0)), "z": float(raw.get("z", 0.0))}


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _midpoint(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2}


def _reference_length(keypoints: list[dict[str, Any]]) -> float:
    """Use shoulder width to normalize the skater scale within the frame."""
    left_shoulder = _point(keypoints, 11)
    right_shoulder = _point(keypoints, 12)
    if not (left_shoulder and right_shoulder):
        return 0.0
    return _distance(left_shoulder, right_shoulder)


def _shoulder_hip_reference_length(keypoints: list[dict[str, Any]]) -> float:
    """Use shoulder-to-hip midpoint distance to normalize vertical motion."""
    left_shoulder = _point(keypoints, 11)
    right_shoulder = _point(keypoints, 12)
    left_hip = _point(keypoints, 23)
    right_hip = _point(keypoints, 24)
    if not all((left_shoulder, right_shoulder, left_hip, right_hip)):
        return 0.0
    shoulder_mid = _midpoint(left_shoulder, right_shoulder)
    hip_mid = _midpoint(left_hip, right_hip)
    return _distance(shoulder_mid, hip_mid)


def _angle(a: dict[str, float], b: dict[str, float], c: dict[str, float]) -> float:
    ab = (a["x"] - b["x"], a["y"] - b["y"])
    cb = (c["x"] - b["x"], c["y"] - b["y"])
    dot = ab[0] * cb[0] + ab[1] * cb[1]
    mag_ab = math.hypot(*ab)
    mag_cb = math.hypot(*cb)
    if mag_ab == 0 or mag_cb == 0:
        return 0.0
    cosine = max(-1.0, min(dot / (mag_ab * mag_cb), 1.0))
    return math.degrees(math.acos(cosine))


def _frame_number(frame_name: str) -> int:
    digits = "".join(char for char in frame_name if char.isdigit())
    return int(digits or "0")


def calc_knee_angle(keypoints: list[dict[str, Any]], frame_idx: int) -> dict[str, Any]:
    left = [_point(keypoints, index) for index in (23, 25, 27)]
    right = [_point(keypoints, index) for index in (24, 26, 28)]
    left_angle = _angle(*left) if all(left) else None
    right_angle = _angle(*right) if all(right) else None
    values = [value for value in [left_angle, right_angle] if value is not None]
    return {"frame_idx": frame_idx, "left": left_angle, "right": right_angle, "min_angle": min(values) if values else None}


def calc_trunk_tilt(keypoints: list[dict[str, Any]], frame_idx: int) -> dict[str, Any]:
    shoulders = [_point(keypoints, 11), _point(keypoints, 12)]
    hips = [_point(keypoints, 23), _point(keypoints, 24)]
    if not all(shoulders + hips):
        return {"frame_idx": frame_idx, "tilt_degrees": None}
    shoulder_mid = _midpoint(shoulders[0], shoulders[1])
    hip_mid = _midpoint(hips[0], hips[1])
    dx = shoulder_mid["x"] - hip_mid["x"]
    dy = hip_mid["y"] - shoulder_mid["y"]
    tilt = abs(math.degrees(math.atan2(dx, max(dy, 0.001))))
    return {"frame_idx": frame_idx, "tilt_degrees": tilt}


def calc_arm_symmetry(keypoints: list[dict[str, Any]], frame_idx: int) -> dict[str, Any]:
    reference_length = _reference_length(keypoints)
    if reference_length < 0.01:
        return {"frame_idx": frame_idx, "symmetry": None}

    left_shoulder = _point(keypoints, 11)
    right_shoulder = _point(keypoints, 12)
    left_wrist = _point(keypoints, 15)
    right_wrist = _point(keypoints, 16)
    if not all([left_shoulder, right_shoulder, left_wrist, right_wrist]):
        return {"frame_idx": frame_idx, "symmetry": None}

    left_distance = _distance(left_wrist, left_shoulder) / reference_length
    right_distance = _distance(right_wrist, right_shoulder) / reference_length
    symmetry = max(0.0, 1.0 - abs(left_distance - right_distance))
    return {"frame_idx": frame_idx, "symmetry": symmetry}


def calc_center_of_mass_trajectory(pose_data: dict[str, Any]) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    y_values: list[float] = []
    reference_lengths: list[float] = []
    for frame in pose_data.get("frames", []):
        keypoints = frame.get("keypoints", [])
        hips = [_point(keypoints, 23), _point(keypoints, 24)]
        shoulders = [_point(keypoints, 11), _point(keypoints, 12)]
        visible = [point for point in hips + shoulders if point is not None]
        if not visible:
            continue
        y_value = sum(point["y"] for point in visible) / len(visible)
        points.append(
            {
                "frame": frame.get("frame", ""),
                "x": sum(point["x"] for point in visible) / len(visible),
                "y": y_value,
            }
        )
        y_values.append(y_value)

        reference_length = _shoulder_hip_reference_length(keypoints)
        if reference_length >= 0.01:
            reference_lengths.append(reference_length)

    if y_values and reference_lengths:
        average_reference = sum(reference_lengths) / len(reference_lengths)
        vertical_range = (max(y_values) - min(y_values)) / average_reference
    else:
        vertical_range = 0.0
    return {"points": points, "vertical_range": vertical_range}


def _normalize_frame_name(frame: str) -> str:
    return PathLikeFrame(frame).stem


def _find_descent_start(points: list[dict[str, Any]], apex_index: int) -> int:
    takeoff_index = max(0, apex_index - max(1, len(points) // 5))
    for index in range(1, apex_index + 1):
        if points[index]["y"] < points[index - 1]["y"]:
            return index - 1
    return takeoff_index


def _find_ascent_start(points: list[dict[str, Any]], apex_index: int) -> int:
    landing_index = min(len(points) - 1, apex_index + max(1, len(points) // 5))
    for index in range(apex_index + 1, len(points)):
        if points[index]["y"] > points[index - 1]["y"]:
            landing_index = index
        if index - apex_index >= max(2, len(points) // 4):
            break
    return landing_index


def _hip_midpoint(frame: dict[str, Any]) -> dict[str, float] | None:
    keypoints = frame.get("keypoints", [])
    left_hip = _point(keypoints, 23)
    right_hip = _point(keypoints, 24)
    if not (left_hip and right_hip):
        return None
    return _midpoint(left_hip, right_hip)


def _find_max_hip_x_delta(frames: list[dict[str, Any]]) -> int | None:
    best_index: int | None = None
    best_delta = 0.0
    previous_hip: dict[str, float] | None = None

    for index, frame in enumerate(frames):
        current_hip = _hip_midpoint(frame)
        if current_hip is None:
            continue
        if previous_hip is not None:
            delta = abs(current_hip["x"] - previous_hip["x"])
            if delta > best_delta:
                best_delta = delta
                best_index = index
        previous_hip = current_hip

    return best_index


def _free_leg_ankle_y(frame: dict[str, Any]) -> float | None:
    keypoints = frame.get("keypoints", [])
    ankles = [_point(keypoints, 27), _point(keypoints, 28)]
    visible = [point["y"] for point in ankles if point is not None]
    if not visible:
        return None
    return min(visible)


def _find_free_leg_peak(frames: list[dict[str, Any]]) -> int | None:
    best_index: int | None = None
    best_y: float | None = None

    for index, frame in enumerate(frames):
        ankle_y = _free_leg_ankle_y(frame)
        if ankle_y is None:
            continue
        if best_y is None or ankle_y < best_y:
            best_y = ankle_y
            best_index = index

    return best_index


def detect_key_frames(
    com_trajectory: dict[str, Any],
    pose_data: dict[str, Any],
    analysis_profile: str = "jump",
) -> dict[str, str]:
    points = com_trajectory.get("points", [])
    if len(points) < 3:
        return {}

    if analysis_profile == "jump":
        apex_index = min(range(len(points)), key=lambda index: points[index]["y"])
        takeoff_index = _find_descent_start(points, apex_index)
        landing_index = _find_ascent_start(points, apex_index)
        return {
            "T": _normalize_frame_name(points[takeoff_index]["frame"]),
            "A": _normalize_frame_name(points[apex_index]["frame"]),
            "L": _normalize_frame_name(points[landing_index]["frame"]),
        }

    frames = pose_data.get("frames", [])
    if analysis_profile == "spin":
        max_delta_index = _find_max_hip_x_delta(frames)
        if max_delta_index is None:
            return {}
        start_index = max(0, max_delta_index - 1)
        end_index = min(len(frames) - 1, max_delta_index + 1)
        return {
            "旋转入": _normalize_frame_name(str(frames[start_index].get("frame", ""))),
            "旋转中": _normalize_frame_name(str(frames[max_delta_index].get("frame", ""))),
            "旋转出": _normalize_frame_name(str(frames[end_index].get("frame", ""))),
        }

    if analysis_profile in ("spiral", "step"):
        peak_index = _find_free_leg_peak(frames)
        if peak_index is None:
            return {}
        return {"峰值": _normalize_frame_name(str(frames[peak_index].get("frame", "")))}

    return {}


class PathLikeFrame:
    def __init__(self, frame: str) -> None:
        self.stem = frame[:-4] if frame.endswith(".jpg") else frame


def calc_rotation_axis_stability(pose_data: dict[str, Any], start_frame: int, end_frame: int) -> dict[str, Any]:
    tilts: list[float] = []
    for frame in pose_data.get("frames", []):
        frame_idx = _frame_number(str(frame.get("frame", "")))
        if start_frame <= frame_idx <= end_frame:
            tilt = calc_trunk_tilt(frame.get("keypoints", []), frame_idx).get("tilt_degrees")
            if tilt is not None:
                tilts.append(float(tilt))
    average_tilt = sum(tilts) / len(tilts) if tilts else None
    stability_score = 65 if average_tilt is None else max(0, min(100, round(100 - average_tilt * 2)))
    return {"average_tilt_degrees": average_tilt, "stability_score": stability_score}


def _normalized_angle_delta(current_angle: float, previous_angle: float) -> float:
    delta = current_angle - previous_angle
    while delta <= -math.pi:
        delta += 2 * math.pi
    while delta > math.pi:
        delta -= 2 * math.pi
    return delta


def _rotation_rps(pose_data: dict[str, Any], start_frame: int, end_frame: int) -> float:
    angles: list[float] = []
    for frame in pose_data.get("frames", []):
        frame_idx = _frame_number(str(frame.get("frame", "")))
        if start_frame <= frame_idx <= end_frame:
            left = _point(frame.get("keypoints", []), 11)
            right = _point(frame.get("keypoints", []), 12)
            if left and right:
                angles.append(math.atan2(right["y"] - left["y"], right["x"] - left["x"]))
    if len(angles) < 2:
        return 0.0

    total_rotation = 0.0
    for previous_angle, current_angle in zip(angles, angles[1:]):
        total_rotation += abs(_normalized_angle_delta(current_angle, previous_angle))

    total_turns = total_rotation / (2 * math.pi)
    duration = max((end_frame - start_frame) / FPS, 1 / FPS)
    return round(total_turns / duration, 2)


def estimate_jump_rotations(
    rotation_rps: float | None,
    air_time_seconds: float | None,
) -> dict[str, Any]:
    if rotation_rps is None or air_time_seconds is None:
        return {"estimated_rotations": None, "probable_jump_type": "unknown"}

    rotations = rotation_rps * air_time_seconds

    thresholds = [
        (0.8, 1.8, "单圈跳 (1T/1S/1Lo/1F/1Lz)"),
        (1.8, 2.8, "双圈跳 (2A/2T/2S/2Lo/2F/2Lz)"),
        (2.8, 3.8, "三圈跳 (3A/3T/3S/3Lo/3F/3Lz)"),
        (3.8, 5.0, "四圈跳 (4T/4S/4Lo/4F/4Lz)"),
    ]
    probable = "unknown"
    for low, high, label in thresholds:
        if low <= rotations < high:
            probable = label
            break

    return {
        "estimated_rotations": round(rotations, 2),
        "probable_jump_type": probable,
    }


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _invalid_metrics(reason: str) -> dict[str, Any]:
    return {
        "jump_metrics": _empty_jump_metrics(),
        "jump_metrics_status": "invalid",
        "jump_metrics_warning": reason,
    }


def sanitize_biomechanics_data(bio_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(bio_data, dict):
        return _empty_analysis()

    analysis_profile = str(bio_data.get("analysis_profile", "jump") or "jump")
    if analysis_profile != "jump":
        sanitized = dict(bio_data)
        sanitized["jump_metrics"] = None
        sanitized["jump_metrics_status"] = "not_applicable"
        sanitized["jump_metrics_warning"] = None
        sanitized.setdefault("discipline_metrics", {})
        sanitized.setdefault("quality_flags", [])
        return sanitized

    sanitized = dict(bio_data)
    key_frames = sanitized.get("key_frames")
    metrics = sanitized.get("jump_metrics")
    if not isinstance(metrics, dict):
        sanitized.update(_invalid_metrics("未检测到有效跳跃数据"))
        return sanitized

    metric_values = {
        "air_time_seconds": _to_float(metrics.get("air_time_seconds")),
        "estimated_height_cm": _to_float(metrics.get("estimated_height_cm")),
        "takeoff_speed_mps": _to_float(metrics.get("takeoff_speed_mps")),
        "rotation_rps": _to_float(metrics.get("rotation_rps")),
    }

    warning: str | None = None
    if not isinstance(key_frames, dict) or not all(key_frames.get(label) for label in ("T", "A", "L")):
        warning = "关键帧检测异常"
    elif any(value is None for value in metric_values.values()):
        warning = "关键指标缺失"
    else:
        air_time = metric_values["air_time_seconds"]
        height = metric_values["estimated_height_cm"]
        takeoff_speed = metric_values["takeoff_speed_mps"]
        rotation = metric_values["rotation_rps"]
        if air_time is None or air_time <= 0 or air_time > MAX_AIR_TIME_SECONDS:
            warning = "滞空时间检测异常"
        elif height is None or height <= 0 or height > MAX_HEIGHT_CM:
            warning = "跳跃高度检测异常"
        elif takeoff_speed is None or takeoff_speed <= 0 or takeoff_speed > MAX_TAKEOFF_SPEED_MPS:
            warning = "起跳速度检测异常"
        elif rotation is None or rotation <= 0 or rotation > MAX_ROTATION_RPS:
            warning = "转速检测异常"

    if warning:
        sanitized.update(_invalid_metrics(warning))
        return sanitized

    sanitized["jump_metrics"] = {
        "air_time_seconds": round(metric_values["air_time_seconds"], 2),
        "estimated_height_cm": round(metric_values["estimated_height_cm"], 1),
        "takeoff_speed_mps": round(metric_values["takeoff_speed_mps"], 2),
        "rotation_rps": round(metric_values["rotation_rps"], 2),
        **estimate_jump_rotations(
            metric_values["rotation_rps"],
            metric_values["air_time_seconds"],
        ),
    }
    sanitized["jump_metrics_status"] = "ok"
    sanitized["jump_metrics_warning"] = None
    return sanitized


def _score_from_values(values: list[float], ideal: float, tolerance: float, invert: bool = False) -> int:
    if not values:
        return 65
    average = sum(values) / len(values)
    distance = abs(average - ideal)
    score = 100 - (distance / tolerance) * 35
    if invert:
        score = 100 - average
    return max(40, min(100, round(score)))


def _spiral_discipline_metrics(
    trunk_tilts: list[dict[str, Any]],
    knee_angles: list[dict[str, Any]],
    arm_symmetry: list[dict[str, Any]],
    com_trajectory: dict[str, Any],
) -> dict[str, Any]:
    tilts = [float(item["tilt_degrees"]) for item in trunk_tilts if item.get("tilt_degrees") is not None]
    knees = [float(item["min_angle"]) for item in knee_angles if item.get("min_angle") is not None]
    symmetries = [float(item["symmetry"]) for item in arm_symmetry if item.get("symmetry") is not None]
    vertical_range = float(com_trajectory.get("vertical_range", 0.0) or 0.0)
    return {
        "trunk_pitch_degrees": round(sum(tilts) / len(tilts), 2) if tilts else None,
        "free_leg_extension_degrees": round((sum(knees) / len(knees)) - 20, 2) if knees else None,
        "hip_shoulder_alignment": round((sum(symmetries) / len(symmetries)) * 100, 1) if symmetries else None,
        "glide_stability": max(0, min(100, round(100 - vertical_range * 300))) if vertical_range else 65,
        "support_leg_stability": max(0, min(100, round(100 - abs((sum(knees) / len(knees)) - 155)))) if knees else 65,
    }


def analyze_biomechanics(pose_data: dict[str, Any], action_type: str, analysis_profile: str = "jump") -> dict[str, Any]:
    del action_type

    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not frames:
        return _empty_analysis(analysis_profile=analysis_profile)

    knee_angles = []
    trunk_tilts = []
    arm_symmetry = []
    for index, frame in enumerate(frames, start=1):
        keypoints = frame.get("keypoints", [])
        knee_angles.append(calc_knee_angle(keypoints, index))
        trunk_tilts.append(calc_trunk_tilt(keypoints, index))
        arm_symmetry.append(calc_arm_symmetry(keypoints, index))

    com_trajectory = calc_center_of_mass_trajectory(pose_data)
    if not com_trajectory["points"]:
        return _empty_analysis(knee_angles, trunk_tilts, arm_symmetry, analysis_profile=analysis_profile)

    if analysis_profile != "jump":
        key_frames = detect_key_frames(com_trajectory, pose_data, analysis_profile)
        tilt_values = [item["tilt_degrees"] for item in trunk_tilts if item.get("tilt_degrees") is not None]
        symmetries = [item["symmetry"] for item in arm_symmetry if item.get("symmetry") is not None]
        bio_subscores = {
            "takeoff_power": 65,
            "rotation_axis": 65,
            "arm_coordination": max(40, min(100, round((sum(symmetries) / len(symmetries)) * 100))) if symmetries else 65,
            "landing_absorption": 65,
            "core_stability": _score_from_values(tilt_values, 15, 30),
        }
        return sanitize_biomechanics_data(
            {
                "analysis_profile": analysis_profile,
                "knee_angles": knee_angles,
                "trunk_tilts": trunk_tilts,
                "arm_symmetry": arm_symmetry,
                "com_trajectory": com_trajectory,
                "rotation_stability": {"average_tilt_degrees": None, "stability_score": 65},
                "bio_subscores": bio_subscores,
                "discipline_metrics": _spiral_discipline_metrics(trunk_tilts, knee_angles, arm_symmetry, com_trajectory),
                "quality_flags": [],
                "key_frames": key_frames,
                "jump_metrics": None,
                "jump_metrics_status": "not_applicable",
                "jump_metrics_warning": None,
            }
        )

    key_frames = detect_key_frames(com_trajectory, pose_data, analysis_profile)
    if not key_frames:
        return _empty_analysis(knee_angles, trunk_tilts, arm_symmetry, analysis_profile=analysis_profile)

    start_frame = _frame_number(key_frames.get("T", "frame_0001"))
    end_frame = _frame_number(key_frames.get("L", f"frame_{len(frames):04d}"))
    rotation_stability = calc_rotation_axis_stability(pose_data, start_frame, end_frame)

    min_knees = [item["min_angle"] for item in knee_angles if item.get("min_angle") is not None]
    tilts = [item["tilt_degrees"] for item in trunk_tilts if item.get("tilt_degrees") is not None]
    symmetries = [item["symmetry"] for item in arm_symmetry if item.get("symmetry") is not None]

    air_time_frames = max(end_frame - start_frame, 0)
    air_time_seconds = round(air_time_frames / FPS, 2)
    estimated_height_cm = round(0.5 * 9.8 * (air_time_seconds / 2) ** 2 * 100, 1) if air_time_seconds else None
    takeoff_speed_mps = round((2 * 9.8 * estimated_height_cm / 100) ** 0.5, 2) if estimated_height_cm else None

    bio_subscores = {
        "takeoff_power": _score_from_values(min_knees, 145, 55),
        "rotation_axis": int(rotation_stability.get("stability_score", 65)),
        "arm_coordination": max(40, min(100, round((sum(symmetries) / len(symmetries)) * 100))) if symmetries else 65,
        "landing_absorption": _score_from_values(min_knees[-5:], 135, 50) if min_knees else 65,
        "core_stability": _score_from_values(tilts, 8, 25),
    }

    return sanitize_biomechanics_data(
        {
            "analysis_profile": analysis_profile,
            "knee_angles": knee_angles,
            "trunk_tilts": trunk_tilts,
            "arm_symmetry": arm_symmetry,
            "com_trajectory": com_trajectory,
            "rotation_stability": rotation_stability,
            "bio_subscores": bio_subscores,
            "discipline_metrics": {},
            "quality_flags": [],
            "key_frames": key_frames,
            "jump_metrics": {
                "air_time_seconds": air_time_seconds,
                "estimated_height_cm": estimated_height_cm,
                "takeoff_speed_mps": takeoff_speed_mps,
                "rotation_rps": _rotation_rps(pose_data, start_frame, end_frame),
            },
        }
    )
