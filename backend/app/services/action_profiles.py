from __future__ import annotations

import copy
import math
from typing import Any

from app.services.jump_features import compute_jump_evidence
from app.services.pose_quality import analysis_point
from app.services.pose_observations import (
    frame_usable as _routing_frame_usable,
    observation_slots as _routing_observations,
)


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


def _max_vertical_range(
    pose_data: dict[str, Any] | None,
    motion_metadata: dict[str, Any] | None = None,
) -> float:
    # Recompute from observations: an unattributed CoM cache cannot override
    # point quality, identity, or time boundaries in saved frames.
    ranges: list[float] = []
    current: list[float] = []
    for frame in _routing_observations(pose_data, motion_metadata):
        points = [analysis_point(frame.get("keypoints"), k, .5) for k in (11, 12, 23, 24)] if frame else []
        if not points or any(p is None for p in points):
            if current:
                ranges.append(max(current) - min(current))
                current = []
            continue
        current.append(sum(float(p["y"]) for p in points) / len(points))
    if current:
        ranges.append(max(current) - min(current))
    return max(ranges, default=0.)


def _person_height_normalized(
    pose_data: dict[str, Any] | None,
    motion_metadata: dict[str, Any] | None = None,
) -> float:
    """Nose-to-bilateral-ankle height from usable same-frame observations."""
    heights: list[float] = []
    for frame in _routing_observations(pose_data, motion_metadata):
        if frame is None:
            continue
        points = [analysis_point(frame.get("keypoints"), k, .5) for k in (0, 27, 28)]
        if any(p is None for p in points):
            continue
        nose, left, right = points
        height = abs((float(left["y"]) + float(right["y"])) / 2 - float(nose["y"]))
        if height > .05:
            heights.append(height)
    return sum(heights) / len(heights) if heights else 0.


def _trusted_ankle_y(frame: Any) -> float | None:
    if not _routing_frame_usable(frame):
        return None
    ankles = [analysis_point(frame.get("keypoints"), k, .4) for k in (27, 28)]
    if any(p is None for p in ankles):
        return None
    return sum(float(p["y"]) for p in ankles) / 2



def _detect_airborne_frames(
    pose_data: dict[str, Any] | None,
    motion_metadata: dict[str, Any] | None = None,
) -> int:
    """Count contact-bounded ankle-rise candidates within usable segments."""
    observations = [_trusted_ankle_y(frame) for frame in _routing_observations(pose_data, motion_metadata)]

    segments: list[list[float]] = []
    current_segment: list[float] = []
    for value in observations:
        if value is None:
            if current_segment:
                segments.append(current_segment)
                current_segment = []
        else:
            current_segment.append(value)
    if current_segment:
        segments.append(current_segment)

    detected = 0
    for segment in segments:
        if len(segment) < 4:
            continue
        baseline_count = max(1, len(segment) // 5)
        baseline = sum(segment[:baseline_count]) / baseline_count
        airborne_threshold = baseline * 0.85
        contact_threshold = baseline * 0.95
        raised = [ankle_y < airborne_threshold for ankle_y in segment]
        run_start: int | None = None
        for index, is_raised in enumerate([*raised, False]):
            if is_raised and run_start is None:
                run_start = index
                continue
            if is_raised or run_start is None:
                continue
            run_end = index
            has_prior_contact = any(value >= contact_threshold for value in segment[:run_start])
            has_later_contact = any(value >= contact_threshold for value in segment[run_end:])
            if run_end - run_start >= 2 and has_prior_contact and has_later_contact:
                detected += run_end - run_start
            run_start = None
    return detected


def _detect_rotation_signal(
    pose_data: dict[str, Any] | None,
    motion_metadata: dict[str, Any] | None = None,
) -> float:
    """Repeated internal orientation changes, never across rejected slots."""
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not isinstance(frames, list) or not frames:
        return 0.
    segments: list[list[int]] = []
    states: list[int] = []
    for frame in _routing_observations(pose_data, motion_metadata):
        pairs: list[int] = []
        if frame is not None:
            points = {k: analysis_point(frame.get("keypoints"), k, .4) for k in (11, 12, 23, 24)}
            for left_id, right_id in ((11, 12), (23, 24)):
                left, right = points[left_id], points[right_id]
                if left is None or right is None:
                    break
                delta = float(left["x"]) - float(right["x"])
                if abs(delta) < .002:
                    break
                pairs.append(1 if delta > 0 else -1)
        if len(pairs) != 2 or pairs[0] != pairs[1]:
            if states:
                segments.append(states)
                states = []
            continue
        states.append(pairs[0])
    if states:
        segments.append(states)
    signals = []
    for states in segments:
        transitions = sum(a != b for a, b in zip(states, states[1:]))
        if len(states) >= 4 and transitions >= 2:
            signals.append(min(1., transitions / 4.) * len(states) / len(frames))
    return round(max(signals, default=0.), 4)


def _motion_stats(frame_motion_scores: dict[str, Any] | None) -> tuple[float, float]:
    if not isinstance(frame_motion_scores, dict):
        return 0.0, 0.0
    scores = [float(score) for score in frame_motion_scores.get("scores", []) if isinstance(score, (int, float))]
    if not scores:
        return 0.0, 0.0
    max_motion = max(scores)
    avg_motion = sum(scores) / len(scores)
    return max_motion, avg_motion


def _dedupe_values(values: list[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(value)
    return output


def profile_warning_from_evidence(profile_evidence: dict[str, Any] | None) -> str:
    """Render a family-readable boundary warning from profile routing evidence.

    The warning deliberately speaks about routing/candidate evidence rather than
    exposing internal enum or flag names. It never turns a route into a confirmed
    action, jump count, or a claim that the skater did not jump.
    """
    if not isinstance(profile_evidence, dict) or not profile_evidence:
        return ""

    flags = profile_evidence.get("quality_flags")
    flag_set = {str(flag) for flag in flags} if isinstance(flags, list) else set()
    hint = str(profile_evidence.get("profile_hint") or "").strip().lower()
    mixed = bool(profile_evidence.get("mixed_action_input")) or hint == "mixed_auto"
    ambiguous = bool(profile_evidence.get("jump_spin_ambiguous")) or "jump_spin_ambiguous" in flag_set
    jump_gate = bool(profile_evidence.get("jump_gate_passed"))
    mixed_jump_gate = bool(profile_evidence.get("mixed_jump_gate_passed"))
    confidence = str(profile_evidence.get("profile_confidence") or "").strip().lower()
    parts: list[str] = []

    if mixed and ambiguous:
        parts.append(
            "原始骨架出现旋转线索，但证据不足以区分跳跃与旋转；"
            "不能确认动作类型、具体圈数或单跳/连跳，也不能排除跳跃。"
        )
    elif mixed and mixed_jump_gate:
        parts.append(
            "原始骨架检测到腾空候选，但只能作为线索，"
            "不能确认冰刀已离地、具体跳种、周数或单跳/连跳。"
        )
    elif mixed:
        parts.append(
            "原始骨架未检测到明确跳跃或旋转线索；仅凭这些线索不能判断当前动作，"
            "且未检出不代表视频中没有跳跃，不能据此否定跳跃。"
        )
    elif hint == "jump":
        if jump_gate:
            parts.append(
                "用户输入标签决定按跳跃方向路由分析；本次腾空门槛通过只作辅助候选，"
                "不代表动作已自动确认，具体跳种、周数和单跳/连跳仍需独立证据。"
            )
        else:
            parts.append(
                "用户输入标签决定按跳跃方向路由分析；本次未检测到明确腾空证据，"
                "不能确认跳跃动作、具体跳种或周数。"
            )
    elif hint == "spin":
        if confidence == "low" or "spin_rotation_signal_weak" in flag_set:
            parts.append("本次按旋转方向路由分析，旋转线索偏弱，不能确认具体旋转类型、周数或完成质量。")
        else:
            parts.append("本次按旋转方向路由分析，但路由结果不等同于已确认具体旋转动作或周数。")
    elif hint == "spiral":
        parts.append("本次按燕式滑行/螺旋线方向路由分析，路由结果不等同于已确认具体动作或完成质量。")
    elif hint == "step":
        parts.append("本次按步法方向路由分析，路由结果不等同于已确认具体步法类型；未检出不代表没有跳跃。")
    else:
        parts.append("当前动作分类仅作为分析路由，不代表已确认具体动作或周数。")

    recovered_family = next(
        (
            profile_evidence.get(key)
            for key in ("video_ai_action_family", "recovered_action_family", "video_action_family")
            if profile_evidence.get(key)
        ),
        None,
    )
    if recovered_family:
        parts.append(
            "视频语义家族恢复信息只作补充线索，不改变原始骨架的置信度、腾空门槛或动作确认状态。"
        )

    if profile_evidence.get("jump_geometry_candidate") is True and not mixed:
        parts.append("几何指标只提供跳跃候选线索，不能循环证明已发生跳跃。")

    return " ".join(parts)


def attach_profile_evidence(
    bio_data: dict[str, Any],
    profile_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Attach routing evidence to bio data without mutating either input.

    The returned dict is safe to attach repeatedly during restore/retry: old
    quality flags are preserved, new flags are merged with de-duplication, and
    the same evidence always produces the same warning. Profile booleans and
    counts are copied verbatim; this helper never promotes route evidence into a
    confirmed action.
    """
    base = dict(bio_data) if isinstance(bio_data, dict) else {}
    evidence_copy = copy.deepcopy(profile_evidence) if isinstance(profile_evidence, dict) else {}

    existing_flags = base.get("quality_flags")
    merged_flags: list[Any] = list(existing_flags) if isinstance(existing_flags, list) else []
    evidence_flags = evidence_copy.get("quality_flags")
    if isinstance(evidence_flags, list):
        merged_flags.extend(evidence_flags)
    base["quality_flags"] = _dedupe_values(merged_flags)

    base["profile_evidence"] = evidence_copy
    warning = profile_warning_from_evidence(evidence_copy)
    if warning:
        base["profile_warning"] = warning

    # jump_metrics_warning is an older consumer-facing field. Keep it untouched
    # when present; profile_warning is additive and does not replace it.
    return base


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
    airborne_frames = _detect_airborne_frames(pose_data, frame_motion_scores)
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
        "profile_route_only": False,
        "jump_spin_ambiguous": False,
    }

    if mixed_action_input:
        evidence["profile_hint"] = "mixed_auto"
        evidence["profile_route_only"] = True
        mixed_jump_gate = jump_gate
        evidence["mixed_jump_gate_passed"] = mixed_jump_gate
        if mixed_jump_gate:
            evidence["profile_confidence"] = "medium"
            evidence["quality_flags"].append("mixed_action_profile_inferred_jump_from_motion")
            evidence["negative_constraints"].append(
                "自动检测到腾空/离地候选，仅作为跳跃路由线索，不等同于冰刀离冰事实或已确认跳跃；"
                "具体跳种、周数、单跳/连跳仍需独立画面证据确认。"
            )
            return "jump", evidence
        if rotation_signal >= 0.15 and max_motion >= 0.04:
            evidence["profile_confidence"] = "low"
            evidence["jump_spin_ambiguous"] = True
            evidence["quality_flags"].append("mixed_action_profile_inferred_spin_from_rotation")
            evidence["quality_flags"].append("jump_spin_ambiguous")
            evidence["negative_constraints"].append(
                "当前证据不足以区分跳跃与旋转，旋转线索只能支持按旋转方向路由分析；"
                "旋转线索不能排除跳跃，也不能确认旋转动作、周数或单跳/连跳。"
            )
            return "spin", evidence
        evidence["profile_confidence"] = "low"
        evidence["quality_flags"].append("mixed_action_profile_defaulted_step")
        evidence["negative_constraints"].append(
            "未检测到明确的跳跃或旋转线索时默认按步法路由分析；"
            "未检出不代表视频中没有跳跃，不能据此否定跳跃。"
        )
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
        evidence["profile_route_only"] = True
        evidence["negative_constraints"].append(
            "用户标签决定按跳跃路由分析，腾空门槛只作辅助候选，不代表动作已自动确认；"
            "具体跳种、周数或单跳/连跳仍需独立证据。"
        )
        return "jump", evidence

    if hinted_profile == "jump":
        evidence["profile_route_only"] = True
        evidence["negative_constraints"].append(
            "几何证据不足（CoM 垂直范围低、无腾空帧检测），但用户填写了跳跃，保留 jump profile；"
            "用户标签只决定路由方向，不是自动动作确认"
        )
        evidence["quality_flags"].append("jump_gate_not_passed")
        evidence["profile_confidence"] = "low"
        return "jump", evidence

    return "step", evidence
