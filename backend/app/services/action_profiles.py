from __future__ import annotations

from typing import Any

from app.services.jump_features import compute_jump_evidence


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
JUMP_KEYWORDS = {"跳跃", "jump", "Axel", "Lutz", "Flip", "Loop", "Salchow", "Toe"}
SPIN_KEYWORDS = {"旋转", "spin", "Spin"}
SPIRAL_KEYWORDS = {"燕式", "螺旋线", "spiral", "Spiral"}
STEP_KEYWORDS = {"步法", "step", "Step"}

JUMP_CHARACTERISTICS: dict[str, dict[str, str]] = {
    "axel": {
        "takeoff_edge": "左刀前外刃起跳",
        "direction": "前向起跳，空中向右旋转",
        "key_check": "起跳腿（左腿）蹬冰后是否有明显前向跨步，而非向后起跳",
        "rotation_note": "单 Axel=1.5圈，双 Axel=2.5圈，圈数比同类多半圈",
    },
    "lutz": {
        "takeoff_edge": "左刀后外刃起跳（右脚 toe pick 辅助）",
        "direction": "后向起跳",
        "key_check": "重点检查是否发生刃型错误：起跳前外刃滑行变内刃（Flutz 错误）",
        "rotation_note": "常见错误：Flutz——外刃在起跳前瞬间偷换为内刃",
    },
    "flip": {
        "takeoff_edge": "左刀后内刃起跳（右脚 toe pick 辅助）",
        "direction": "后向起跳",
        "key_check": "与 Lutz 外形相似，区别在于起跳前冰刃为内刃",
        "rotation_note": "常见混淆：与 Lutz 起跳动作相似，需观察起跳前滑行路线",
    },
    "loop": {
        "takeoff_edge": "右刀后外刃起跳（无点冰辅助）",
        "direction": "后向起跳，双腿并拢",
        "key_check": "起跳时双腿并拢，右腿单腿承重，检查是否有提前开肩",
        "rotation_note": "纯刃跳，起跳瞬间双脚短暂并拢是识别标志",
    },
    "salchow": {
        "takeoff_edge": "左刀后内刃起跳（无点冰辅助）",
        "direction": "后向起跳",
        "key_check": "自由腿（右腿）向前大幅摆动辅助起跳，检查摆腿力度和时机",
        "rotation_note": "纯刃跳，自由腿摆动是起跳动力的关键来源",
    },
    "toe_loop": {
        "takeoff_edge": "右刀后外刃起跳（左脚 toe pick 辅助）",
        "direction": "后向起跳",
        "key_check": "点冰位置是否准确，点冰后是否快速收腿进入旋转轴",
        "rotation_note": "最常见的跳跃类型，也是连跳的常用后跳",
    },
}


def normalize_action_subtype(action_type: str, action_subtype: str | None) -> str | None:
    options = ACTION_SUBTYPE_OPTIONS.get(action_type, [])
    if not options:
        return None
    subtype = (action_subtype or "").strip()
    if not subtype:
        return options[0]
    return subtype if subtype in options else options[0]


def is_mixed_action_input(action_type: str, action_subtype: str | None) -> bool:
    subtype = (action_subtype or "").strip()
    return action_type == "自由滑" and (not subtype or subtype == "节目片段")


def infer_profile_from_input(action_type: str, action_subtype: str | None) -> str | None:
    if is_mixed_action_input(action_type, action_subtype):
        return None
    text = f"{action_type} {action_subtype or ''}".lower()
    if any(keyword.lower() in text for keyword in JUMP_KEYWORDS):
        return "jump"
    if any(keyword.lower() in text for keyword in SPIN_KEYWORDS):
        return "spin"
    if any(keyword.lower() in text for keyword in SPIRAL_KEYWORDS):
        return "spiral"
    if any(keyword.lower() in text for keyword in STEP_KEYWORDS):
        return "step"
    return None


def infer_profile_hint(action_type: str, action_subtype: str | None) -> str:
    canonical_profile = (action_type or "").strip().lower()
    if canonical_profile in ANALYSIS_PROFILES:
        return canonical_profile

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


def _normalize_jump_subtype_key(action_subtype: str) -> str:
    return (
        action_subtype.lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace("（", "(")
        .replace("）", ")")
    )


def get_jump_characteristics(action_subtype: str | None) -> dict[str, str] | None:
    if not action_subtype:
        return None

    normalized = _normalize_jump_subtype_key(action_subtype)
    normalized_characteristics = [
        (_normalize_jump_subtype_key(key), characteristics)
        for key, characteristics in JUMP_CHARACTERISTICS.items()
    ]

    for normalized_key, characteristics in normalized_characteristics:
        if normalized == normalized_key:
            return characteristics

    for normalized_key, characteristics in sorted(
        normalized_characteristics,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if normalized_key in normalized or normalized in normalized_key:
            return characteristics
    return None


def infer_jump_subtype_evidence(
    pose_data: dict[str, Any] | None,
    key_frames: dict[str, Any] | None,
    effective_fps: float | None,
) -> dict[str, Any]:
    """Infer weak geometric evidence for jump subtype prompts.

    Args:
        pose_data: Pose payload containing MediaPipe keypoints.
        key_frames: Biomechanics key-frame dict containing T/A/L.
        effective_fps: Effective sampling fps on the real action timeline.

    Returns:
        Jump evidence dictionary. Missing inputs return a quality flag instead of raising.

    Raises:
        无。
    """
    if not isinstance(pose_data, dict) or not isinstance(key_frames, dict):
        return {"quality_flags": ["jump_evidence_missing_inputs"]}
    return compute_jump_evidence(pose_data, key_frames, float(effective_fps or 5.0))


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
            if isinstance(point, dict)
            and float(point.get("visibility", 0.0) or 0.0) >= 0.5
            and point.get("id") in {11, 12, 23, 24}
        ]
        if not visible:
            continue
        points.append(sum(float(point.get("y", 0.0) or 0.0) for point in visible) / len(visible))
    return max(points) - min(points) if points else 0.0


def _person_height_normalized(pose_data: dict[str, Any] | None) -> float:
    """
    Estimate normalized person height using the Y distance from nose to ankle midpoint.
    Returns 0.0 when the height cannot be computed reliably.
    """
    if not isinstance(pose_data, dict):
        return 0.0

    frames = pose_data.get("frames", [])
    if not isinstance(frames, list):
        return 0.0

    heights: list[float] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue

        keypoints = frame.get("keypoints", [])
        if not isinstance(keypoints, list):
            continue

        nose = next(
            (
                point
                for point in keypoints
                if isinstance(point, dict)
                and point.get("id") == 0
                and float(point.get("visibility", 0.0) or 0.0) >= 0.5
            ),
            None,
        )
        left_ankle = next(
            (
                point
                for point in keypoints
                if isinstance(point, dict)
                and point.get("id") == 27
                and float(point.get("visibility", 0.0) or 0.0) >= 0.5
            ),
            None,
        )
        right_ankle = next(
            (
                point
                for point in keypoints
                if isinstance(point, dict)
                and point.get("id") == 28
                and float(point.get("visibility", 0.0) or 0.0) >= 0.5
            ),
            None,
        )
        if nose is None or (left_ankle is None and right_ankle is None):
            continue

        ankles = [point for point in (left_ankle, right_ankle) if point is not None]
        ankle_y = sum(float(point.get("y", 0.0) or 0.0) for point in ankles) / len(ankles)
        height = abs(ankle_y - float(nose.get("y", 0.0) or 0.0))
        if height > 0.05:
            heights.append(height)

    return sum(heights) / len(heights) if heights else 0.0


def _detect_airborne_frames(pose_data: dict[str, Any] | None) -> int:
    """
    Count a continuous ankle-rise interval bounded by contact-like frames.

    A global body-center range is not enough: camera tilt, zoom and a skater
    travelling through perspective can all move the pose vertically.  This
    gate therefore requires at least two consecutive raised-ankle frames plus
    visible contact-like observations before and after the interval.
    """
    if not isinstance(pose_data, dict):
        return 0

    frames = pose_data.get("frames", [])
    if not isinstance(frames, list):
        return 0

    ankle_y_series: list[float] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue

        keypoints = frame.get("keypoints", [])
        if not isinstance(keypoints, list):
            continue

        ankles = [
            point
            for point in keypoints
            if isinstance(point, dict)
            and point.get("id") in {27, 28}
            and float(point.get("visibility", 0.0) or 0.0) >= 0.4
        ]
        if not ankles:
            continue

        ankle_y_series.append(sum(float(point.get("y", 0.0) or 0.0) for point in ankles) / len(ankles))

    if len(ankle_y_series) < 3:
        return 0

    baseline_count = max(1, len(ankle_y_series) // 5)
    baseline = sum(ankle_y_series[:baseline_count]) / baseline_count
    airborne_threshold = baseline * 0.85
    raised = [ankle_y < airborne_threshold for ankle_y in ankle_y_series]
    contact_threshold = baseline * 0.95
    detected = 0
    run_start: int | None = None
    for index, is_raised in enumerate([*raised, False]):
        if is_raised and run_start is None:
            run_start = index
            continue
        if is_raised or run_start is None:
            continue
        run_end = index
        has_prior_contact = any(value >= contact_threshold for value in ankle_y_series[:run_start])
        has_later_contact = any(value >= contact_threshold for value in ankle_y_series[run_end:])
        if run_end - run_start >= 2 and has_prior_contact and has_later_contact:
            detected += run_end - run_start
        run_start = None
    return detected


def _detect_rotation_signal(pose_data: dict[str, Any] | None) -> float:
    """
    Detect repeated changes in the body's internal left/right orientation.

    Translation of the hip center is deliberately excluded because ordinary
    skating across the frame is not rotation.  A usable signal needs at least
    two left/right orientation transitions, which is the minimum evidence for
    a repeated turn rather than one direction change.
    """
    if not isinstance(pose_data, dict):
        return 0.0

    frames = pose_data.get("frames", [])
    if not isinstance(frames, list):
        return 0.0

    orientation_states: list[int] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue

        keypoints = frame.get("keypoints", [])
        if not isinstance(keypoints, list):
            continue

        points = {
            int(point.get("id")): point
            for point in keypoints
            if isinstance(point, dict)
            and point.get("id") in {11, 12, 23, 24}
            and float(point.get("visibility", 0.0) or 0.0) >= 0.4
        }
        pair_states: list[int] = []
        for left_id, right_id in ((11, 12), (23, 24)):
            left = points.get(left_id)
            right = points.get(right_id)
            if left is None or right is None:
                continue
            delta_x = float(left.get("x", 0.0) or 0.0) - float(right.get("x", 0.0) or 0.0)
            if abs(delta_x) < 0.002:
                continue
            pair_states.append(1 if delta_x > 0 else -1)
        if not pair_states or abs(sum(pair_states)) != len(pair_states):
            continue
        orientation_states.append(pair_states[0])

    if len(orientation_states) < 4:
        return 0.0

    collapsed = [orientation_states[0]]
    for state in orientation_states[1:]:
        if state != collapsed[-1]:
            collapsed.append(state)
    transitions = len(collapsed) - 1
    if transitions < 2:
        return 0.0
    coverage = len(orientation_states) / len(frames)
    return round(min(1.0, transitions / 4.0) * coverage, 4)


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
    mixed_action_input = is_mixed_action_input(action_type, subtype)
    max_motion, avg_motion = _motion_stats(frame_motion_scores)
    vertical_range = _max_vertical_range(pose_data)
    person_height = _person_height_normalized(pose_data)
    airborne_frames = _detect_airborne_frames(pose_data)
    rotation_signal = _detect_rotation_signal(pose_data)
    relative_vertical = vertical_range / person_height if person_height > 0.05 else 0.0

    jump_geometry_candidate = (
        relative_vertical >= 0.12 and max_motion >= 0.06
        if person_height > 0.05
        else vertical_range >= 0.05 and max_motion >= 0.06
    )
    jump_gate = airborne_frames >= 2
    spiral_gate = hinted_profile == "spiral" or (
        vertical_range <= 0.06 and avg_motion <= 0.09 and subtype in SPIRAL_SUBTYPES
    )

    evidence = {
        "action_type": action_type,
        "action_subtype": subtype,
        "profile_hint": hinted_profile,
        "max_motion_score": round(max_motion, 4),
        "avg_motion_score": round(avg_motion, 4),
        "com_vertical_range": round(vertical_range, 4),
        "person_height_reference": round(person_height, 4),
        "relative_vertical_range": round(relative_vertical, 4) if person_height > 0.05 else 0.0,
        "airborne_frames_detected": airborne_frames,
        "jump_geometry_candidate": jump_geometry_candidate,
        "hip_rotation_signal": rotation_signal,
        "jump_gate_passed": jump_gate,
        "spiral_gate_passed": spiral_gate,
        "quality_flags": [],
        "negative_constraints": [],
        "mixed_action_input": mixed_action_input,
    }

    if mixed_action_input:
        evidence["profile_hint"] = "mixed_auto"
        mixed_jump_gate = jump_gate
        evidence["mixed_jump_gate_passed"] = mixed_jump_gate
        if mixed_jump_gate:
            evidence["profile_confidence"] = "medium"
            evidence["quality_flags"].append("mixed_action_profile_inferred_jump_from_motion")
            return "jump", evidence
        if rotation_signal >= 0.15 and max_motion >= 0.04:
            evidence["profile_confidence"] = "medium"
            evidence["quality_flags"].append("mixed_action_profile_inferred_spin_from_rotation")
            return "spin", evidence
        evidence["profile_confidence"] = "low"
        evidence["quality_flags"].append("mixed_action_profile_defaulted_step")
        return "step", evidence

    if spiral_gate:
        evidence["negative_constraints"].append("燕式滑行/螺旋线不是跳跃，除非存在清晰腾空阶段")
        return "spiral", evidence
    if hinted_profile == "spin":
        if rotation_signal < 0.15:
            evidence["profile_confidence"] = "low"
            evidence["quality_flags"].append("spin_rotation_signal_weak")
            evidence["negative_constraints"].append(
                f"髋部旋转信号弱（{rotation_signal:.3f}），可能不是旋转或存在视角遮挡"
            )
        return "spin", evidence
    if action_type == "步法":
        return "step", evidence
    if action_type == "自由滑":
        return "step", evidence
    if jump_gate and hinted_profile == "jump":
        return "jump", evidence

    if hinted_profile == "jump":
        evidence["negative_constraints"].append(
            "几何证据不足（CoM 垂直范围低、无腾空帧检测），但用户填写了跳跃，保留 jump profile"
        )
        evidence["quality_flags"].append("jump_gate_not_passed")
        evidence["profile_confidence"] = "low"
        return "jump", evidence

    return "step", evidence
