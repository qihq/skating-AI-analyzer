from __future__ import annotations

import json
from typing import Any, Literal


SPECIALIZED_VISION_SYSTEM_PROMPT = (
    "你是一名专业花样滑冰技术分析师，熟悉 ISU 技术要素、儿童初级训练动作和基础运动生物力学。\n\n"
    "当前任务不是正式裁判评分，而是家用训练视频分析。请特别注意：\n"
    "- 学员是儿童初学者（Free Skate 1 级别），动作幅度小、控制力弱是正常的。\n"
    "- 对初学员要宽容评估：能完成基本动作流程即为合格，不要用成人竞技标准衡量。\n"
    "- pure_vision_subscores 评分校准（0-1 浮点数）：\n"
    "  0.6-0.7 = 基本达标（Free Skate 1 初学者正常水平，能完成动作流程）\n"
    "  0.5 = 略有不足，但动作基本完成\n"
    "  0.8+ = 表现良好\n"
    "  0.3-0.4 = 明显不足，需要重点改进（仅用于严重技术缺陷）\n"
    "- 重要：如果学员完成了跳跃/旋转/步法的基本流程，即使质量不高，也应给 0.5-0.6 分。\n"
    "- 视频可能是侧面、斜角、远距离或低清晰度。\n"
    "- 如果脚踝、冰刀或入跳弧线不可见，不要强行判断刃型。\n"
    "- 如果证据不足，请输出'不可判断'并降低 confidence。\n"
    "- 用户可能只知道动作大类，不知道具体动作名；如果 action_subtype 未指定或证据不足，不要强行猜成 Axel/Lutz/Flip 等细项。\n"
    "- 后端候选关键帧、动作 profile 和规则证据都是辅助线索，不是最终结论；与画面冲突时以可见证据为准并降低置信度。\n"
    "- 必须只输出 JSON。"
)


VisionOutputMode = Literal["frames", "video"]


def _subscore_contract() -> dict[str, float]:
    return {
        "takeoff_power": 0.0,
        "rotation_axis": 0.0,
        "arm_coordination": 0.0,
        "landing_absorption": 0.0,
        "core_stability": 0.0,
    }


def _observations_contract() -> dict[str, str]:
    return {
        "knee_bend": "\u5145\u5206|\u4e0d\u8db3|\u8fc7\u5ea6|\u4e0d\u53ef\u5224\u65ad|\u4e0d\u9002\u7528",
        "arm_position": "\u6b63\u786e|\u504f\u9ad8|\u504f\u4f4e|\u4e0d\u5bf9\u79f0|\u4e0d\u53ef\u5224\u65ad|\u4e0d\u9002\u7528",
        "axis_alignment": "\u5782\u76f4|\u524d\u503e|\u540e\u4ef0|\u4fa7\u503e|\u4e0d\u53ef\u5224\u65ad|\u4e0d\u9002\u7528",
        "blade_edge": "\u5916\u5203|\u5185\u5203|\u5e73\u5203|\u4e0d\u53ef\u5224\u65ad|\u4e0d\u9002\u7528",
        "core_stability": "\u7a33\u5b9a|\u8f7b\u5fae\u6643\u52a8|\u660e\u663e\u6643\u52a8|\u4e0d\u53ef\u5224\u65ad|\u4e0d\u9002\u7528",
        "landing_absorption": "\u826f\u597d|\u4e0d\u8db3|\u8fc7\u5ea6|\u4e0d\u53ef\u5224\u65ad|\u4e0d\u9002\u7528",
    }


def _frame_contract() -> dict[str, Any]:
    return {
        "frame_id": "frame_0001",
        "phase": "\u51c6\u5907|\u8d77\u8df3|\u817e\u7a7a|\u843d\u51b0|\u6ed1\u51fa|\u65cb\u8f6c\u5165|\u65cb\u8f6c\u4e2d|\u65cb\u8f6c\u51fa|\u6b65\u6cd5|\u4e0d\u53ef\u5206\u6790",
        "phase_confidence": 0.0,
        "key_frame_agreement": "T|A|L|none|shifted|disagree|unavailable",
        "observations": _observations_contract(),
        "issues": [],
        "positives": [],
        "confidence": 0.0,
    }


def _segment_contract() -> dict[str, Any]:
    return {
        "start_sec": 0.0,
        "end_sec": 0.0,
        "phase": "\u51c6\u5907|\u8d77\u8df3|\u817e\u7a7a|\u843d\u51b0|\u6ed1\u51fa|\u65cb\u8f6c\u5165|\u65cb\u8f6c\u4e2d|\u65cb\u8f6c\u51fa|\u6b65\u6cd5|\u4e0d\u53ef\u5206\u6790",
        "observations": _observations_contract(),
        "issues": [],
        "positives": [],
        "confidence": 0.0,
    }


def build_specialized_vision_schema(output_mode: VisionOutputMode) -> dict[str, Any]:
    if output_mode not in ("frames", "video"):
        raise ValueError(f"Unsupported vision output mode: {output_mode}")

    payload: dict[str, Any] = {
        "data_quality_hint": "good|partial|poor",
        "camera_view": "front|side|diagonal_front|diagonal_back|unknown",
        "camera_view_confidence": 0.0,
        "action_phase_summary": {
            "detected_phases": [],
            "weakest_phase": "",
            "strongest_phase": "",
            "key_frame_agreement": {
                "T": "agree|shifted|disagree|unavailable",
                "A": "agree|shifted|disagree|unavailable",
                "L": "agree|shifted|disagree|unavailable",
            },
        },
        "pure_vision_subscores": _subscore_contract(),
        "element_confidence": 0.0,
        "overall_raw_text": "2-3\u53e5\u4e2d\u6587\u603b\u7ed3",
    }
    payload["frame_analysis" if output_mode == "frames" else "phase_segments"] = [
        _frame_contract() if output_mode == "frames" else _segment_contract()
    ]
    return payload


def _json_for_prompt(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def build_specialized_vision_prompt(
    action_type: str,
    action_subtype: str | None = None,
    analysis_profile: str | None = None,
    candidate_key_frames: dict[str, Any] | list[Any] | None = None,
    motion_features: dict[str, Any] | list[Any] | None = None,
    biomechanics: dict[str, Any] | None = None,
    profile_evidence: dict[str, Any] | None = None,
    skill_category: str | None = None,
    output_mode: VisionOutputMode = "frames",
    include_biomechanics: bool = True,
) -> tuple[str, str]:
    """Build a reusable figure-skating specialized vision prompt.

    The function is intentionally pure so Path A and generic vision calls can
    use it without database or provider dependencies.
    """
    normalized_profile = (analysis_profile or "unknown").strip() or "unknown"
    normalized_subtype = (action_subtype or "\u672a\u6307\u5b9a").strip() or "\u672a\u6307\u5b9a"
    schema = json.dumps(build_specialized_vision_schema(output_mode), ensure_ascii=False, indent=2)
    system_prompt = SPECIALIZED_VISION_SYSTEM_PROMPT
    if not include_biomechanics:
        system_prompt += "\n- 这是纯视觉模式：不引入骨架或测量数据。"
    biomechanics_section = (
        "biomechanics:\n"
        f"{_json_for_prompt(biomechanics)}\n\n"
        if include_biomechanics
        else ""
    )
    video_rules = (
        "\u3010\u89c6\u9891\u6a21\u5f0f - \u5f3a\u5236\u8981\u6c42\u3011\n"
        "1. \u5fc5\u987b\u53ea\u8f93\u51fa\u4e00\u4e2a JSON \u5bf9\u8c61\uff0c\u4e0d\u8981\u8f93\u51fa JSON \u4e4b\u5916\u7684\u6587\u5b57\u3001\u89e3\u91ca\u3001markdown \u6216\u4ee3\u7801\u5757\u6807\u8bb0\u3002\n"
        "2. \u5373\u4f7f\u753b\u9762\u6a21\u7cca\u3001\u89d2\u5ea6\u4e0d\u4f73\u6216\u65e0\u6cd5\u5224\u65ad\u52a8\u4f5c\uff0c\u4e5f\u5fc5\u987b\u8f93\u51fa\u5b8c\u6574 JSON\uff1b\u5c06 phase \u8bbe\u4e3a\u201c\u4e0d\u53ef\u5206\u6790\u201d\u3001confidence \u8bbe\u4e3a 0\u3002\n"
        "3. \u6309\u89c6\u9891\u7247\u6bb5\u5185\u7684\u79d2\u6570\u5b9a\u4f4d\u5173\u952e\u4e8b\u4ef6\uff0c\u4e0d\u8981\u7f16\u9020\u9010\u5e27 frame_id\u3002\n"
        "4. \u4f7f\u7528 phase_segments \u5b57\u6bb5\uff0c\u4e0d\u8981\u4f7f\u7528 frame_analysis\u3002\n\n"
        if output_mode == "video"
        else ""
    )

    candidate_key_frame_section = (
        "【后端自动关键帧候选】\n"
        "candidate_key_frames:\n"
        f"{_json_for_prompt(candidate_key_frames)}\n\n"
        if candidate_key_frames is not None
        else ""
    )
    evidence_rule = (
        "- issues 和 positives 必须来自可见画面、候选帧或骨架数据，不要把用户备注当作事实。\n\n"
        if include_biomechanics
        else "- issues 和 positives 必须来自可见画面、运动线索或视频语义上下文，不要把用户备注当作事实。\n\n"
    )
    user_prompt = (
        "【动作信息】\n"
        f"action_type: {action_type}\n"
        f"action_subtype: {normalized_subtype}\n"
        f"analysis_profile: {normalized_profile}\n"
        f"skill_category: {skill_category or '未指定'}\n"
        "skater_level: Free Skate 1\n\n"
        f"{candidate_key_frame_section}"
        "【运动与姿态证据】\n"
        "motion_features:\n"
        f"{_json_for_prompt(motion_features)}\n\n"
        f"{biomechanics_section}"
        "profile_evidence:\n"
        f"{_json_for_prompt(profile_evidence)}\n\n"
        "【分析步骤】\n"
        "1. 判断画面质量：good / partial / poor。\n"
        "2. 判断拍摄角度：front / side / diagonal_front / diagonal_back / unknown。\n"
        "3. 先确认实际动作大类；若只看到自由滑、滑行、步法或螺旋线，不要为了满足跳跃 schema 编造起跳/腾空/落冰。\n"
        "4. 对每帧判断阶段。\n"
        "5. 对 T/A/L 候选帧给出 agree / shifted / disagree / unavailable；非跳跃动作必须使用 unavailable 或 none。\n"
        "6. 对儿童训练水平做保守判断，不使用成人竞技标准。\n"
        "7. 输出低置信度原因，不要编造不可见细节。\n\n"
        "【不确定性规则】\n"
        "- action_subtype=未指定 表示用户不知道细项；仅在画面证据清楚时才给具体子类型。\n"
        "- 如果画面只支持动作大类，请把具体刃型、周数或跳跃细项写为不可判断，并把 confidence 降低。\n"
        f"{evidence_rule}"
        "【jump profile 补充规则】\n"
        "- 当 analysis_profile=jump 时，T/A/L 候选帧是后端自动证据，不是最终结论；请结合画面保守确认。\n"
        '- 如果脚踝、冰刀或入跳弧线不可见，必须令 observations.blade_edge="不可判断"。\n'
        "- 如果刃型不可见或关键入跳证据不足，必须令 element_confidence<=0.55，并在 issues 中说明低置信度原因。\n\n"
        "【输出 JSON】\n"
        f"{video_rules}"
        "JSON schema:\n"
        f"{schema}"
    )
    return system_prompt, user_prompt
