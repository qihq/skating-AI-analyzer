from __future__ import annotations

import json
from typing import Any


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


SPECIALIZED_VISION_JSON_SCHEMA = """{
  "data_quality_hint": "good|partial|poor",
  "camera_view": "front|side|diagonal_front|diagonal_back|unknown",
  "camera_view_confidence": 0.0,
  "frame_analysis": [
    {
      "frame_id": "frame_0001",
      "phase": "准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",
      "phase_confidence": 0.0,
      "key_frame_agreement": "T|A|L|none|shifted|disagree|unavailable",
      "observations": {
        "knee_bend": "充分|不足|过度|不可判断|不适用",
        "arm_position": "正确|偏高|偏低|不对称|不可判断|不适用",
        "axis_alignment": "垂直|前倾|后仰|侧倾|不可判断|不适用",
        "blade_edge": "外刃|内刃|平刃|不可判断|不适用",
        "landing_absorption": "良好|不足|过度|不可判断|不适用"
      },
      "issues": [],
      "positives": [],
      "confidence": 0.0
    }
  ],
  "action_phase_summary": {
    "detected_phases": [],
    "weakest_phase": "",
    "strongest_phase": "",
    "key_frame_agreement": {
      "T": "agree|shifted|disagree|unavailable",
      "A": "agree|shifted|disagree|unavailable",
      "L": "agree|shifted|disagree|unavailable"
    }
  },
  "element_confidence": 0.0,
  "overall_raw_text": "2-3句中文总结"
}"""


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
) -> tuple[str, str]:
    """Build a reusable figure-skating specialized vision prompt.

    The function is intentionally pure so Path A and generic vision calls can
    use it without database or provider dependencies.
    """
    normalized_profile = (analysis_profile or "unknown").strip() or "unknown"
    normalized_subtype = (action_subtype or "未指定").strip() or "未指定"

    user_prompt = (
        "【动作信息】\n"
        f"action_type: {action_type}\n"
        f"action_subtype: {normalized_subtype}\n"
        f"analysis_profile: {normalized_profile}\n"
        f"skill_category: {skill_category or '未指定'}\n"
        "skater_level: Free Skate 1\n\n"
        "【后端自动关键帧候选】\n"
        "candidate_key_frames:\n"
        f"{_json_for_prompt(candidate_key_frames)}\n\n"
        "【运动与姿态证据】\n"
        "motion_features:\n"
        f"{_json_for_prompt(motion_features)}\n\n"
        "biomechanics:\n"
        f"{_json_for_prompt(biomechanics)}\n\n"
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
        "- issues 和 positives 必须来自可见画面、候选帧或骨架数据，不要把用户备注当作事实。\n\n"
        "【jump profile 补充规则】\n"
        "- 当 analysis_profile=jump 时，T/A/L 候选帧是后端自动证据，不是最终结论；请结合画面保守确认。\n"
        '- 如果脚踝、冰刀或入跳弧线不可见，必须令 observations.blade_edge="不可判断"。\n'
        "- 如果刃型不可见或关键入跳证据不足，必须令 element_confidence<=0.55，并在 issues 中说明低置信度原因。\n\n"
        "【输出 JSON】\n"
        "JSON schema:\n"
        f"{SPECIALIZED_VISION_JSON_SCHEMA}"
    )
    return SPECIALIZED_VISION_SYSTEM_PROMPT, user_prompt
