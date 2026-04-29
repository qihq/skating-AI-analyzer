from __future__ import annotations

from typing import Any


ANALYSIS_PROFILES = {"jump", "spin", "step", "spiral"}

ACTION_SUBTYPE_OPTIONS: dict[str, list[str]] = {
    "跳跃": ["未指定", "单跳", "连跳"],
    "旋转": ["未指定", "直立旋转", "蹲转", "燕式旋转", "联合旋转", "飞旋"],
    "步法": ["未指定", "步法序列", "燕式滑行", "螺旋线序列"],
    "自由滑": ["节目片段"],
}

SPIRAL_SUBTYPES = {"燕式滑行", "螺旋线序列"}
SPIN_SUBTYPES = {"直立旋转", "蹲转", "燕式旋转", "联合旋转", "飞旋"}
JUMP_SUBTYPES = {"单跳", "连跳"}


def normalize_action_subtype(action_type: str, action_subtype: str | None) -> str | None:
    options = ACTION_SUBTYPE_OPTIONS.get(action_type, [])
    if not options:
      return None
    subtype = (action_subtype or "").strip()
    if not subtype:
      return options[0]
    return subtype if subtype in options else options[0]


def infer_profile_hint(action_type: str, action_subtype: str | None) -> str:
    subtype = normalize_action_subtype(action_type, action_subtype)
    if subtype in SPIRAL_SUBTYPES:
        return "spiral"
    if subtype in SPIN_SUBTYPES:
        return "spin"
    if subtype in JUMP_SUBTYPES:
        return "jump"
    if action_type == "跳跃":
        return "jump"
    if action_type == "旋转":
        return "spin"
    if action_type == "步法":
        return "step"
    return "step"


def _max_vertical_range(pose_data: dict[str, Any] | None) -> float:
    if not isinstance(pose_data, dict):
        return 0.0
    trajectory = pose_data.get("com_trajectory")
    if isinstance(trajectory, dict):
        return float(trajectory.get("vertical_range", 0.0) or 0.0)

    frames = pose_data.get("frames", [])
    points: list[float] = []
    if not isinstance(frames, list):
        return 0.0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        keypoints = frame.get("keypoints", [])
        if not isinstance(keypoints, list):
            continue
        visible = [
            point
            for point in keypoints
            if isinstance(point, dict) and float(point.get("visibility", 0.0) or 0.0) >= 0.5 and point.get("id") in {11, 12, 23, 24}
        ]
        if not visible:
            continue
        points.append(sum(float(point.get("y", 0.0) or 0.0) for point in visible) / len(visible))
    return max(points) - min(points) if points else 0.0


def _motion_stats(frame_motion_scores: dict[str, Any] | None) -> tuple[float, float]:
    if not isinstance(frame_motion_scores, dict):
        return 0.0, 0.0
    scores = [float(score) for score in frame_motion_scores.get("scores", []) if isinstance(score, (int, float))]
    if not scores:
        return 0.0, 0.0
    max_motion = max(scores)
    avg_motion = sum(scores) / len(scores)
    return max_motion, avg_motion


def infer_analysis_profile(
    action_type: str,
    action_subtype: str | None,
    pose_data: dict[str, Any] | None = None,
    frame_motion_scores: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    subtype = normalize_action_subtype(action_type, action_subtype)
    hinted_profile = infer_profile_hint(action_type, subtype)
    max_motion, avg_motion = _motion_stats(frame_motion_scores)
    vertical_range = _max_vertical_range(pose_data)

    jump_gate = vertical_range >= 0.08 and max_motion >= 0.08
    spiral_gate = hinted_profile == "spiral" or (vertical_range <= 0.06 and avg_motion <= 0.09 and subtype in SPIRAL_SUBTYPES)

    evidence = {
        "action_type": action_type,
        "action_subtype": subtype,
        "profile_hint": hinted_profile,
        "max_motion_score": round(max_motion, 4),
        "avg_motion_score": round(avg_motion, 4),
        "com_vertical_range": round(vertical_range, 4),
        "jump_gate_passed": jump_gate,
        "spiral_gate_passed": spiral_gate,
        "negative_constraints": [],
    }

    if spiral_gate:
        evidence["negative_constraints"].append("燕式滑行/螺旋线不是跳跃，除非存在清晰腾空阶段")
        return "spiral", evidence
    if hinted_profile == "spin":
        return "spin", evidence
    if action_type == "步法":
        return "step", evidence
    if action_type == "自由滑":
        return "step", evidence
    if jump_gate and hinted_profile == "jump":
        return "jump", evidence

    if hinted_profile == "jump":
        evidence["negative_constraints"].append("未检测到足够明确的起跳/腾空证据，避免按跳跃处理")
    return "step", evidence
