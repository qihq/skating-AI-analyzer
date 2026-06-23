from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.schemas import Severity
from app.services.analysis_errors import AnalysisErrorCode, classify_ai_failure
from app.services.providers import get_active_provider, request_text_completion
from app.services.snowball import build_memory_context
from app.services.llm_context import AnalysisPromptContext, render_prompt_context


logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = (
    "你是花样滑冰训练报告生成助手，面向儿童/青少年学员和家长输出可执行复盘。"
    "你必须基于结构化视觉、视频时序和骨架证据生成结论；用户备注只能作为线索，不能替代证据。"
    "你必须严格输出 JSON 对象，不要输出 Markdown，不要解释，不要使用 ```json 包裹。"
)

SUBSCORE_KEYS = [
    "takeoff_power",
    "rotation_axis",
    "arm_coordination",
    "landing_absorption",
    "core_stability",
]

SUBSCORE_WEIGHTS = {
    "takeoff_power": 0.25,
    "rotation_axis": 0.25,
    "arm_coordination": 0.15,
    "landing_absorption": 0.25,
    "core_stability": 0.10,
}

HIGH_CONF_THRESHOLD = 0.5
LOW_CONFIDENCE_NOTICE_THRESHOLD = 0.75
LOW_CONFIDENCE_NOTICE = "低置信度帧较多，结果仅供参考。"
REPORT_REQUEST_TIMEOUT_SECONDS = 120.0
REPORT_JSON_MAX_ATTEMPTS = 3
GENERIC_REPORT_TERMS = (
    "数据质量",
    "可分析信息有限",
    "结合教练观察",
    "轴心稳定",
    "落冰缓冲",
    "发力节奏",
    "软膝盖",
)
ACTIONABLE_DRILLS = {
    "jump": [
        ("起跳发力", "做 3 组墙边压膝-蹬伸-收臂节奏练习，每组 6 次，先听到稳定节奏再上冰连贯完成。"),
        ("空中轴心", "用半周小跳练习头肩髋叠直和双臂快速收到胸前，落地后保持 2 秒单脚滑出。"),
        ("落冰控制", "做单脚软膝落冰停住练习，要求落冰膝盖弯曲、上身不前扑，再逐步接滑出弧线。"),
    ],
    "spin": [
        ("旋转轴心", "先做两脚原地转体到单脚入转，要求头、肩、髋保持一条竖线，发现前倾就重新进入。"),
        ("旋转速度", "练习入转后 1 秒内收臂和收自由腿，每次只追求更快收紧，不急着增加圈数。"),
        ("旋转圈数", "用地面和冰上分段计数：进入、稳定旋转、退出分别拍手计时，先稳定 2 圈再冲 3 圈。"),
    ],
    "spiral": [
        ("浮足伸展", "扶墙做燕式 8 秒保持，浮足向后上方伸直、脚尖延伸，支撑腿膝盖不要软塌。"),
        ("速度保持", "进入前做 3 次渐进蹬冰，进入燕式后保持同一滑行弧线，不用抬腿高度换速度。"),
        ("姿态稳定", "做短距离燕式进入-保持-滑出分段练习，每段只改一个目标：肩平、髋正、浮足直。"),
    ],
    "step": [
        ("蹬冰力量", "用 6 步一组的前向有力蹬冰练习，要求每一步都能看到支撑腿压膝和完整推送。"),
        ("节奏控制", "配合节拍器做慢-中-快 3 档步法，先保证每步重心转移清楚，再增加速度。"),
        ("上身稳定", "做双臂固定的步法穿行练习，减少肩膀摆动，让转向主要来自膝盖和刃。"),
    ],
}


def clean_json_text(raw_text: str) -> str:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]

    return cleaned


def _clamp_score(value: object, default: int = 75) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        score = default
    return max(0, min(score, 100))


def _fallback_subscores() -> dict[str, int]:
    return {
        "takeoff_power": 75,
        "rotation_axis": 75,
        "arm_coordination": 75,
        "landing_absorption": 75,
        "core_stability": 75,
    }


def fuse_subscores(
    ai_subscores: dict[str, Any],
    bio_subscores: dict[str, Any] | None,
    quality_flags: list[str] | None = None,
) -> dict[str, int]:
    normalized_ai = {key: _clamp_score(ai_subscores.get(key), 75) for key in SUBSCORE_KEYS}
    if not bio_subscores:
        return normalized_ai

    warning_count = len(quality_flags or [])
    bio_weight = max(0.20, 0.60 - warning_count * 0.08)
    ai_weight = 1.0 - bio_weight

    fused: dict[str, int] = {}
    for key in SUBSCORE_KEYS:
        ai_score = normalized_ai[key]
        bio_score = _clamp_score(bio_subscores.get(key), ai_score)
        fused[key] = round(ai_score * ai_weight + bio_score * bio_weight)
    return fused


def calculate_force_score(report: dict[str, Any]) -> int:
    subscores = report.get("subscores") if isinstance(report.get("subscores"), dict) else {}
    if subscores:
        return round(
            sum(_clamp_score(subscores.get(key), 0) * weight for key, weight in SUBSCORE_WEIGHTS.items())
        )

    penalties = {
        Severity.high.value: 15,
        Severity.medium.value: 8,
        Severity.low.value: 3,
    }
    score = 100
    for issue in report.get("issues", []):
        score -= penalties.get(str(issue.get("severity", "")).lower(), 0)
    return max(score, 0)


def apply_child_score_floor(score: int, report: dict[str, Any], dual_path_meta: dict[str, Any] | None = None) -> int:
    data_quality = str(report.get("data_quality", "partial") or "partial").strip().lower()
    skeleton_signal = str((dual_path_meta or {}).get("skeleton_reliability_signal", "") or "").strip().lower()
    if data_quality == "poor" or skeleton_signal == "likely_wrong":
        return score

    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    has_safety_or_incomplete_risk = False
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        text = f"{issue.get('category', '')} {issue.get('description', '')}".lower()
        if any(
            marker in text
            for marker in (
                "安全",
                "摔",
                "跌倒",
                "未完成",
                "中断",
                "risk",
                "danger",
                "fall",
                "failed",
                "incomplete",
            )
        ):
            has_safety_or_incomplete_risk = True
            break
    if has_safety_or_incomplete_risk:
        return score

    if data_quality == "good":
        return max(score, 80)
    if data_quality == "partial":
        return max(score, 70)
    return score


def normalize_report(payload: dict[str, Any], bio_data: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_issues: list[dict[str, object]] = []
    for issue in payload.get("issues", []):
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity", Severity.low.value)).lower()
        if severity not in {Severity.high.value, Severity.medium.value, Severity.low.value}:
            severity = Severity.low.value
        frames = issue.get("frames", [])
        normalized_issues.append(
            {
                "category": str(issue.get("category", "")).strip() or "技术问题",
                "description": str(issue.get("description", "")).strip(),
                "severity": severity,
                "phase": str(issue.get("phase", "")).strip() or None,
                "frames": [str(frame) for frame in frames] if isinstance(frames, list) else [],
            }
        )

    normalized_improvements: list[dict[str, str]] = []
    for item in payload.get("improvements", []):
        if not isinstance(item, dict):
            continue
        normalized_improvements.append(
            {
                "target": str(item.get("target", "")).strip(),
                "action": str(item.get("action", "")).strip(),
            }
        )

    bio_subscores = None
    quality_flags: list[str] | None = None
    if isinstance(bio_data, dict):
        bio_subscores = bio_data.get("bio_subscores") if isinstance(bio_data.get("bio_subscores"), dict) else None
        quality_flags = bio_data.get("quality_flags") if isinstance(bio_data.get("quality_flags"), list) else []

    user_note = payload.get("user_note")
    if user_note is None:
        user_note = payload.get("note")
    action_confirmation = payload.get("action_confirmation")

    return {
        "summary": str(payload.get("summary", "")).strip(),
        "issues": normalized_issues,
        "improvements": normalized_improvements,
        "training_focus": str(payload.get("training_focus", "")).strip(),
        "subscores": fuse_subscores(
            payload.get("subscores", {}) if isinstance(payload.get("subscores"), dict) else {},
            bio_subscores,
            quality_flags=quality_flags,
        ),
        "data_quality": str(payload.get("data_quality", "partial")).strip() or "partial",
        "user_note": str(user_note).strip() if isinstance(user_note, str) and user_note.strip() else None,
        "user_note_response": (
            str(payload.get("user_note_response")).strip()
            if isinstance(payload.get("user_note_response"), str) and str(payload.get("user_note_response")).strip()
            else None
        ),
        "action_confirmation": action_confirmation if isinstance(action_confirmation, dict) else None,
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm_key(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value).lower())


def _dedupe_strings(values: list[Any], *, limit: int = 6) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if not text:
            continue
        key = _norm_key(text)
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def _analysis_profile_from_context(
    action_type: str,
    prompt_context: AnalysisPromptContext | None,
    dual_path_meta: dict[str, Any] | None = None,
) -> str:
    if prompt_context is not None and prompt_context.analysis_profile:
        profile = _text(prompt_context.analysis_profile).lower()
        if profile:
            return "step" if profile == "steps" else profile
    meta_profile = _text((dual_path_meta or {}).get("analysis_profile")).lower()
    if meta_profile:
        return "step" if meta_profile == "steps" else meta_profile
    action = _text(action_type)
    if "旋" in action:
        return "spin"
    if "燕" in action or "螺旋" in action:
        return "spiral"
    if "步" in action or "蹬" in action:
        return "step"
    return "jump"


def _phase_from_text(text: str, profile: str) -> str | None:
    phase_tokens = [
        "起跳",
        "腾空",
        "落冰",
        "滑出",
        "旋转入",
        "旋转中",
        "旋转出",
        "旋转进入",
        "旋转进行",
        "旋转退出",
        "燕式进入",
        "燕式保持",
        "燕式滑出",
        "准备",
        "步法",
    ]
    for token in phase_tokens:
        if token in text:
            return token
    defaults = {
        "spin": "旋转中",
        "spiral": "燕式保持",
        "step": "步法",
        "jump": "起跳",
    }
    return defaults.get(profile)


def _category_from_issue(text: str, profile: str) -> str:
    if any(token in text for token in ("浮足", "自由腿", "抬腿", "伸直")):
        return "浮足伸展"
    if any(token in text for token in ("速度", "转速", "圈", "周数")):
        return "旋转速度" if profile == "spin" else "速度保持"
    if any(token in text for token in ("轴", "前倾", "后仰", "侧倾", "躯干")):
        return "旋转轴心" if profile == "spin" else "轴心控制"
    if any(token in text for token in ("起跳", "蹬伸", "蹬冰", "发力")):
        return "起跳发力" if profile == "jump" else "蹬冰力量"
    if any(token in text for token in ("手臂", "收臂")):
        return "手臂协调"
    if any(token in text for token in ("落冰", "缓冲", "滑出")):
        return "落冰控制"
    return {
        "spin": "旋转质量",
        "spiral": "燕式姿态",
        "step": "步法质量",
    }.get(profile, "技术问题")


def _issue_from_text(text: str, profile: str, *, source: str = "结构化证据") -> dict[str, object]:
    phase = _phase_from_text(text, profile)
    return {
        "category": _category_from_issue(text, profile),
        "description": text,
        "severity": Severity.medium.value,
        "phase": phase,
        "frames": [],
        "source": source,
    }


def _path_b_evidence(dual_path_meta: dict[str, Any] | None) -> dict[str, Any]:
    meta = dual_path_meta if isinstance(dual_path_meta, dict) else {}
    path_b = meta.get("path_b_evidence")
    return path_b if isinstance(path_b, dict) else {}


def _video_temporal_evidence(dual_path_meta: dict[str, Any] | None) -> dict[str, Any]:
    meta = dual_path_meta if isinstance(dual_path_meta, dict) else {}
    temporal = meta.get("video_temporal")
    return temporal if isinstance(temporal, dict) else {}


def _action_confirmation_from_meta(dual_path_meta: dict[str, Any] | None) -> dict[str, Any] | None:
    temporal = _video_temporal_evidence(dual_path_meta)
    action = temporal.get("action_confirmation")
    if not isinstance(action, dict):
        return None
    confirmed = _text(action.get("confirmed_action") or action.get("jump_type"))
    family = _text(action.get("action_family"))
    notes = _text(action.get("notes"))
    confidence_raw = action.get("confidence")
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = None
    if not any((confirmed, family, notes, confidence is not None)):
        return None
    return {
        "action_family": family or None,
        "confirmed_action": confirmed or "不可分析",
        "jump_type": _text(action.get("jump_type")) or None,
        "confidence": confidence,
        "notes": notes or None,
    }


def _action_confirmation_text(action_confirmation: dict[str, Any] | None, action_type: str) -> str:
    if not isinstance(action_confirmation, dict):
        return f"只能确认大类为{action_type}，暂不能可靠确认具体细项。"
    confirmed = _text(action_confirmation.get("confirmed_action") or action_confirmation.get("jump_type"))
    if not confirmed or confirmed == "不可分析":
        return f"只能确认大类为{action_type}，暂不能可靠确认具体细项。"
    confidence = action_confirmation.get("confidence")
    try:
        percent = round(float(confidence) * 100)
    except (TypeError, ValueError):
        percent = None
    confidence_text = f"，置信度约 {percent}%" if percent is not None else ""
    notes = _text(action_confirmation.get("notes"))
    note_text = f"；{notes}" if notes else ""
    return f"视频语义更倾向识别为 {confirmed}{confidence_text}{note_text}"


def _landing_explanation_from_report(report: dict[str, Any]) -> str:
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    landing_related: list[str] = []
    fallback: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        description = _text(issue.get("description"))
        if not description:
            continue
        text = f"{issue.get('category', '')} {issue.get('phase', '')} {description}"
        if any(token in text for token in ("落冰", "滑出", "轴心", "前倾", "侧倾", "失衡", "不稳")):
            landing_related.append(description)
        else:
            fallback.append(description)
    chosen = landing_related[:2] or fallback[:2]
    if not chosen:
        return "落冰不稳的原因需要结合画面和骨架继续复核。"
    return "落冰不稳主要和" + "；".join(chosen) + "有关。"


def _user_note_response(
    *,
    report: dict[str, Any],
    action_type: str,
    prompt_context: AnalysisPromptContext | None,
    dual_path_meta: dict[str, Any] | None,
) -> str | None:
    note = _text(prompt_context.user_note if prompt_context is not None else None)
    if not note:
        return None
    existing = _text(report.get("user_note_response"))
    if existing and note in existing:
        return existing

    parts = [f"家长/学员备注提到：{note}"]
    if any(token in note for token in ("哪个动作", "什么动作", "具体", "跳种", "动作")):
        parts.append(_action_confirmation_text(report.get("action_confirmation"), action_type))
    if any(token in note for token in ("落冰", "不稳", "为什么", "原因")):
        parts.append(_landing_explanation_from_report(report))
    if len(parts) == 1:
        focus = _text(report.get("training_focus") or report.get("summary"))
        if focus:
            parts.append(f"本次报告已把这条备注作为训练关注点，优先复核：{focus}")
    return " ".join(parts)


def _collect_path_b_issue_texts(dual_path_meta: dict[str, Any] | None) -> list[str]:
    path_b = _path_b_evidence(dual_path_meta)
    values: list[Any] = []
    if isinstance(path_b.get("top_issues"), list):
        values.extend(path_b["top_issues"])
    for frame in path_b.get("frame_analysis", []) if isinstance(path_b.get("frame_analysis"), list) else []:
        if isinstance(frame, dict) and isinstance(frame.get("issues"), list):
            values.extend(frame["issues"][:2])
    return _dedupe_strings(values, limit=5)


def _collect_temporal_issue_texts(dual_path_meta: dict[str, Any] | None) -> list[str]:
    temporal = _video_temporal_evidence(dual_path_meta)
    values: list[Any] = []
    macro = temporal.get("macro_assessment")
    if isinstance(macro, dict) and isinstance(macro.get("top_issues"), list):
        values.extend(macro["top_issues"])
    for segment in temporal.get("phase_segments", []) if isinstance(temporal.get("phase_segments"), list) else []:
        if isinstance(segment, dict):
            issues = segment.get("issues")
            if isinstance(issues, list):
                values.extend(issues[:1])
    return _dedupe_strings(values, limit=4)


def _collect_frame_issue_texts(vision_summary: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for frame in vision_summary.get("reliable_frames", []) if isinstance(vision_summary.get("reliable_frames"), list) else []:
        if isinstance(frame, dict) and isinstance(frame.get("issues"), list):
            values.extend(frame["issues"][:1])
    return _dedupe_strings(values, limit=4)


def _meaningful_report_issues(report: dict[str, Any]) -> list[dict[str, object]]:
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        description = _text(issue.get("description"))
        category = _text(issue.get("category"))
        if not description:
            continue
        generic_score = sum(1 for term in GENERIC_REPORT_TERMS if term in description or term in category)
        if generic_score >= 2 and len(description) < 36:
            continue
        key = _norm_key(description)
        if key in seen:
            continue
        seen.add(key)
        output.append(issue)
    return output[:5]


def _synthesize_issues_from_evidence(
    action_type: str,
    vision_summary: dict[str, Any],
    dual_path_meta: dict[str, Any] | None,
    prompt_context: AnalysisPromptContext | None,
) -> list[dict[str, object]]:
    profile = _analysis_profile_from_context(action_type, prompt_context, dual_path_meta)
    texts = (
        _collect_path_b_issue_texts(dual_path_meta)
        + _collect_temporal_issue_texts(dual_path_meta)
        + _collect_frame_issue_texts(vision_summary)
    )
    issues: list[dict[str, object]] = []
    seen: set[str] = set()
    for text in _dedupe_strings(texts, limit=5):
        key = _norm_key(text)
        if key in seen:
            continue
        seen.add(key)
        issues.append(_issue_from_text(text, profile))
        if len(issues) >= 3:
            break
    return issues


def _is_generic_improvement(item: dict[str, Any]) -> bool:
    target = _text(item.get("target"))
    action = _text(item.get("action"))
    if not target or not action:
        return True
    joined = f"{target} {action}"
    hits = sum(1 for term in GENERIC_REPORT_TERMS if term in joined)
    return hits >= 2 and len(action) < 40


def _drills_for_issue(issue: dict[str, object], profile: str) -> list[tuple[str, str]]:
    category = _text(issue.get("category"))
    description = _text(issue.get("description"))
    drills = ACTIONABLE_DRILLS.get(profile) or ACTIONABLE_DRILLS["jump"]
    matched = [
        drill
        for drill in drills
        if any(token in f"{category}{description}" for token in drill[0].split())
        or drill[0] in f"{category}{description}"
    ]
    return matched or drills


def _synthesize_improvements(
    issues: list[dict[str, object]],
    *,
    action_type: str,
    prompt_context: AnalysisPromptContext | None,
    dual_path_meta: dict[str, Any] | None,
) -> list[dict[str, str]]:
    profile = _analysis_profile_from_context(action_type, prompt_context, dual_path_meta)
    improvements: list[dict[str, str]] = []
    seen: set[str] = set()
    source_issues = issues or [_issue_from_text("", profile)]
    for issue in source_issues:
        for target, action in _drills_for_issue(issue, profile):
            key = _norm_key(f"{target}{action}")
            if key in seen:
                continue
            seen.add(key)
            improvements.append({"target": target, "action": action})
            break
        if len(improvements) >= 3:
            break
    for target, action in ACTIONABLE_DRILLS.get(profile, ACTIONABLE_DRILLS["jump"]):
        if len(improvements) >= 3:
            break
        key = _norm_key(f"{target}{action}")
        if key not in seen:
            seen.add(key)
            improvements.append({"target": target, "action": action})
    return improvements


def _summary_from_evidence(
    action_type: str,
    issues: list[dict[str, object]],
    *,
    prompt_context: AnalysisPromptContext | None,
    dual_path_meta: dict[str, Any] | None,
) -> str:
    profile = _analysis_profile_from_context(action_type, prompt_context, dual_path_meta)
    labels = {
        "jump": "跳跃",
        "spin": "旋转",
        "spiral": "燕式滑行",
        "step": "步法",
    }
    if not issues:
        return f"本次{labels.get(profile, action_type)}动作流程可继续复核，训练上先保留基础节奏和姿态控制。"
    main = "；".join(_text(issue.get("description")) for issue in issues[:2] if _text(issue.get("description")))
    focus = {
        "jump": "起跳发力、空中轴心和落冰滑出",
        "spin": "入转收紧、轴心直立和有效圈数",
        "spiral": "浮足伸展、支撑腿稳定和滑行速度",
        "step": "蹬冰力量、重心转移和节奏",
    }.get(profile, "核心技术细节")
    return f"本次{labels.get(profile, action_type)}可确认的主要问题是：{main}。后续训练重点放在{focus}。"


def _refine_report_with_structured_evidence(
    report: dict[str, Any],
    *,
    action_type: str,
    vision_summary: dict[str, Any],
    dual_path_meta: dict[str, Any] | None,
    prompt_context: AnalysisPromptContext | None,
) -> dict[str, Any]:
    refined = dict(report)
    action_confirmation = _action_confirmation_from_meta(dual_path_meta)
    if action_confirmation and not isinstance(refined.get("action_confirmation"), dict):
        refined["action_confirmation"] = action_confirmation
    if prompt_context is not None and prompt_context.user_note:
        refined["user_note"] = prompt_context.user_note

    existing_issues = _meaningful_report_issues(refined)
    evidence_issues = _synthesize_issues_from_evidence(action_type, vision_summary, dual_path_meta, prompt_context)

    merged_issues: list[dict[str, object]] = []
    seen: set[str] = set()
    for issue in [*existing_issues, *evidence_issues]:
        description = _text(issue.get("description")) if isinstance(issue, dict) else ""
        if not description:
            continue
        key = _norm_key(description)
        if key in seen:
            continue
        seen.add(key)
        merged_issues.append(issue)
        if len(merged_issues) >= 3:
            break
    if merged_issues:
        refined["issues"] = merged_issues

    improvements = [
        item
        for item in refined.get("improvements", [])
        if isinstance(item, dict) and not _is_generic_improvement(item)
    ][:3]
    if len(improvements) < 2 or not merged_issues:
        improvements = _synthesize_improvements(
            merged_issues,
            action_type=action_type,
            prompt_context=prompt_context,
            dual_path_meta=dual_path_meta,
        )
    refined["improvements"] = improvements

    summary = _text(refined.get("summary"))
    generic_summary = not summary or sum(1 for term in GENERIC_REPORT_TERMS if term in summary) >= 3
    if generic_summary and merged_issues:
        refined["summary"] = _summary_from_evidence(
            action_type,
            merged_issues,
            prompt_context=prompt_context,
            dual_path_meta=dual_path_meta,
        )

    focus = _text(refined.get("training_focus"))
    if not focus or sum(1 for term in GENERIC_REPORT_TERMS if term in focus) >= 2:
        target_names = "、".join(item["target"] for item in improvements[:2] if item.get("target"))
        if target_names:
            refined["training_focus"] = f"本阶段优先训练{target_names}，每次只挑一个目标复盘。"

    note_response = _user_note_response(
        report=refined,
        action_type=action_type,
        prompt_context=prompt_context,
        dual_path_meta=dual_path_meta,
    )
    if note_response:
        refined["user_note_response"] = note_response

    return refined


def _resolve_report_data_quality(
    payload: dict[str, Any],
    vision_structured: dict[str, Any],
    dual_path_meta: dict[str, Any] | None = None,
) -> str:
    report_quality = str(payload.get("data_quality", "partial")).strip().lower() or "partial"
    if report_quality not in {"good", "partial", "poor"}:
        report_quality = "partial"

    vision_quality = str(vision_structured.get("data_quality_hint", "")).strip().lower()
    if vision_quality == "poor":
        return "poor"
    if vision_quality == "partial" and report_quality == "good":
        return "partial"
    meta = dual_path_meta if isinstance(dual_path_meta, dict) else {}
    conflict_level = str(meta.get("conflict_level", "")).strip().lower()
    needs_human_review = bool(meta.get("needs_human_review"))
    if (needs_human_review or conflict_level in {"high", "severe"}) and report_quality == "good":
        return "partial"
    return report_quality


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return "0%"


def _build_dual_path_report_context(dual_path_meta: dict[str, Any] | None) -> str:
    if not dual_path_meta:
        return ""

    conflict_fields = dual_path_meta.get("conflict_fields", [])
    if not isinstance(conflict_fields, list):
        conflict_fields = []

    path_b_evidence = _path_b_evidence(dual_path_meta)
    path_b_context = ""
    if path_b_evidence:
        compact_path_b = {
            "top_issues": path_b_evidence.get("top_issues") if isinstance(path_b_evidence.get("top_issues"), list) else [],
            "top_positives": path_b_evidence.get("top_positives") if isinstance(path_b_evidence.get("top_positives"), list) else [],
            "action_phase_summary": path_b_evidence.get("action_phase_summary") if isinstance(path_b_evidence.get("action_phase_summary"), dict) else {},
            "frame_analysis": [
                {
                    "frame_id": frame.get("frame_id"),
                    "phase": frame.get("phase"),
                    "bio_observations": frame.get("bio_observations") if isinstance(frame.get("bio_observations"), dict) else {},
                    "issues": frame.get("issues") if isinstance(frame.get("issues"), list) else [],
                }
                for frame in (path_b_evidence.get("frame_analysis") or [])
                if isinstance(frame, dict)
            ][:6],
        }
        path_b_context = (
            "Path B 可直接用于报告的问题/优点证据：\n"
            f"  {json.dumps(compact_path_b, ensure_ascii=False)}\n"
            "当 Path A 失败或问题列表过泛时，必须优先使用 Path B top_issues 生成 issues 和 improvements。\n"
        )

    return (
        "\n\n=== 双路交叉验证参考 ===\n"
        f"两路一致率：{_format_percent(dual_path_meta.get('overall_agreement_rate'))}\n"
        f"骨架追踪信号：{dual_path_meta.get('skeleton_reliability_signal', 'unknown')}"
        "（reliable=可信 / uncertain=存疑 / likely_wrong=追踪有问题）\n"
        f"推荐参考路径：{dual_path_meta.get('recommended_path', 'blend')}\n"
        f"冲突维度：{', '.join(str(field) for field in conflict_fields) or '无'}\n"
        f"分歧描述：{dual_path_meta.get('conflict_summary', '')}\n"
        "Path B 量化分析子分参考：\n"
        f"  {json.dumps(dual_path_meta.get('path_b_subscores') or {}, ensure_ascii=False)}\n"
        f"{path_b_context}"
        "\n注意：subscores 字段由后端融合计算，你不要自行加权。\n"
        "请根据骨架信号设置 data_quality：\n"
        "  reliable → good / uncertain → partial / likely_wrong → poor\n"
        "若 likely_wrong，请在 issues 末尾追加一条 severity=medium 的提示\n"
        "（category='追踪质量'，description 建议用户重选目标）。\n"
    )


def _compact_video_temporal_payload(video_temporal: dict[str, Any]) -> dict[str, Any]:
    action_confirmation = video_temporal.get("action_confirmation")
    macro_assessment = video_temporal.get("macro_assessment")
    return {
        "schema_version": video_temporal.get("schema_version"),
        "provider": video_temporal.get("provider"),
        "model": video_temporal.get("model"),
        "confidence": video_temporal.get("confidence"),
        "fallback_recommendation": video_temporal.get("fallback_recommendation"),
        "quality_flags": video_temporal.get("quality_flags") if isinstance(video_temporal.get("quality_flags"), list) else [],
        "camera_view": video_temporal.get("camera_view"),
        "data_quality_hint": video_temporal.get("data_quality_hint"),
        "action_confirmation": action_confirmation if isinstance(action_confirmation, dict) else {},
        "key_moments": video_temporal.get("key_moments") if isinstance(video_temporal.get("key_moments"), dict) else {},
        "phase_segments": [
            {
                "phase_code": segment.get("phase_code"),
                "phase_label": segment.get("phase_label"),
                "time_start": segment.get("time_start"),
                "time_end": segment.get("time_end"),
                "key_frame_hint": segment.get("key_frame_hint"),
                "confidence": segment.get("confidence"),
            }
            for segment in (video_temporal.get("phase_segments") or [])
            if isinstance(segment, dict)
        ][:8],
        "macro_assessment": macro_assessment if isinstance(macro_assessment, dict) else {},
        "overall_impression": video_temporal.get("overall_impression", ""),
    }


def _compact_resolved_keyframes_payload(resolved_keyframes: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": resolved_keyframes.get("source"),
        "confidence": resolved_keyframes.get("confidence"),
        "quality_flags": resolved_keyframes.get("quality_flags") if isinstance(resolved_keyframes.get("quality_flags"), list) else [],
        "selected": [
            {
                "frame_id": item.get("frame_id"),
                "timestamp": item.get("timestamp"),
                "phase_code": item.get("phase_code"),
                "phase_label": item.get("phase_label"),
                "key_moment": item.get("key_moment"),
                "selection_reason": item.get("selection_reason"),
            }
            for item in (resolved_keyframes.get("selected") or [])
            if isinstance(item, dict)
        ][:12],
    }


def _collect_video_context_conflicts(vision_structured: dict[str, Any]) -> list[dict[str, Any]]:
    frames = vision_structured.get("frame_analysis") if isinstance(vision_structured, dict) else None
    if not isinstance(frames, list):
        return []
    conflicts: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict) or not bool(frame.get("conflict_with_video_context")):
            continue
        conflicts.append(
            {
                "frame_id": frame.get("frame_id"),
                "phase": frame.get("phase"),
                "conflict_with_video_context": True,
                "phase_verification": frame.get("phase_verification", "uncertain"),
                "video_context_note": frame.get("video_context_note", ""),
                "issues": frame.get("issues") if isinstance(frame.get("issues"), list) else [],
            }
        )
    return conflicts[:8]


def _build_video_temporal_report_context(
    vision_structured: dict[str, Any],
    dual_path_meta: dict[str, Any] | None,
) -> str:
    meta = dual_path_meta if isinstance(dual_path_meta, dict) else {}
    video_temporal = meta.get("video_temporal")
    resolved_keyframes = meta.get("resolved_keyframes")
    conflicts = _collect_video_context_conflicts(vision_structured)

    if not isinstance(video_temporal, dict) and not isinstance(resolved_keyframes, dict) and not conflicts:
        return ""

    payload: dict[str, Any] = {
        "video_temporal": _compact_video_temporal_payload(video_temporal) if isinstance(video_temporal, dict) else {},
        "resolved_keyframes": (
            _compact_resolved_keyframes_payload(resolved_keyframes) if isinstance(resolved_keyframes, dict) else {}
        ),
        "image_video_context_conflicts": conflicts,
    }
    return (
        "\n\n=== 视频语义时序融合参考 ===\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "三层证据使用规则：\n"
        "1. 视频路 video_temporal.macro_assessment 和 overall_impression 只负责动作时序、节奏、速度流动、整体轴心与出入动作质量。\n"
        "2. 图片路 frame_analysis 负责语义关键帧上的姿态、刃面、轴心、膝踝缓冲、手臂协调等帧级微观结论。\n"
        "3. MediaPipe/bio_data 负责角度、重心、旋转、稳定性等数值证据；不要把视频 AI 当作逐帧裁判。\n"
        "冲突处理：若 conflict_with_video_context 为 true 或 phase_verification 为 shifted/disagree，"
        "图片路优先但保留差异，报告中说明视频路宏观判断与图片帧级观察的不同。\n"
        "若冲突严重、resolved_keyframes.source 为 skeleton_fallback 或数据质量标记较多，"
        "请将 data_quality 降为 partial 或 poor，避免输出过度确定结论。\n"
    )


def _frame_confidence(frame: dict[str, Any]) -> float:
    try:
        return max(0.0, min(float(frame.get("confidence", 0.0) or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _is_analyzable_frame(frame: dict[str, Any]) -> bool:
    phase = str(frame.get("phase", "")).strip()
    if phase and phase != "不可分析":
        return True
    for key in ("issues", "positives"):
        if isinstance(frame.get(key), list) and frame.get(key):
            return True
    observations = frame.get("observations")
    if not isinstance(observations, dict):
        return False
    uncertain_values = {"", "不可判断", "不适用", "unknown", "unavailable", "none", "n/a"}
    return any(str(value).strip().lower() not in uncertain_values for value in observations.values())


def _should_apply_low_confidence_notice(
    *,
    normalized_frames: list[dict[str, Any]],
    low_conf_count: int,
    all_low_confidence: bool,
    fallback_used: bool,
) -> bool:
    if fallback_used or all_low_confidence:
        return True
    if not normalized_frames:
        return False
    low_conf_ratio = low_conf_count / len(normalized_frames)
    return low_conf_ratio >= LOW_CONFIDENCE_NOTICE_THRESHOLD


def summarize_vision_for_report(vision_structured: dict[str, Any]) -> dict[str, Any]:
    frames = vision_structured.get("frame_analysis", []) if isinstance(vision_structured, dict) else []
    normalized_frames = [frame for frame in frames if isinstance(frame, dict)]
    high_conf_frames = [frame for frame in normalized_frames if _frame_confidence(frame) >= HIGH_CONF_THRESHOLD]
    low_conf_count = len(normalized_frames) - len(high_conf_frames)
    fallback_to_all_frames = False

    if len(high_conf_frames) < 3:
        high_conf_frames = normalized_frames
        fallback_to_all_frames = True

    all_low_confidence = bool(normalized_frames) and all(
        _frame_confidence(frame) < HIGH_CONF_THRESHOLD for frame in normalized_frames
    )
    analyzable_count = sum(1 for frame in normalized_frames if _is_analyzable_frame(frame))
    fallback_used = bool(vision_structured.get("fallback_used")) if isinstance(vision_structured, dict) else False
    apply_low_confidence_notice = _should_apply_low_confidence_notice(
        normalized_frames=normalized_frames,
        low_conf_count=low_conf_count,
        all_low_confidence=all_low_confidence,
        fallback_used=fallback_used,
    )

    summary: dict[str, Any] = {
        "reliable_frames": high_conf_frames,
        "low_confidence_frame_count": low_conf_count,
        "low_confidence_frame_ratio": round(low_conf_count / len(normalized_frames), 3) if normalized_frames else 0.0,
        "overall_raw_text": vision_structured.get("overall_raw_text", "") if isinstance(vision_structured, dict) else "",
        "total_frame_count": len(normalized_frames),
        "analyzable_frame_count": analyzable_count,
        "high_confidence_threshold": HIGH_CONF_THRESHOLD,
        "fallback_to_all_frames": fallback_to_all_frames,
        "all_low_confidence": all_low_confidence,
        "apply_low_confidence_notice": apply_low_confidence_notice,
    }
    if isinstance(vision_structured, dict):
        summary["action_phase_summary"] = vision_structured.get("action_phase_summary", {})
        if vision_structured.get("data_quality_hint") is not None:
            summary["data_quality_hint"] = vision_structured.get("data_quality_hint")
        if vision_structured.get("camera_view") is not None:
            summary["camera_view"] = vision_structured.get("camera_view")
        if vision_structured.get("conservative_policy") is not None:
            summary["conservative_policy"] = vision_structured.get("conservative_policy")
        if vision_structured.get("fallback_reason") is not None:
            summary["fallback_reason"] = vision_structured.get("fallback_reason")
        pure_vision_subscores = vision_structured.get("pure_vision_subscores")
        if isinstance(pure_vision_subscores, dict) and pure_vision_subscores:
            summary["pure_vision_subscores"] = pure_vision_subscores

    if apply_low_confidence_notice:
        summary["reliability_note"] = LOW_CONFIDENCE_NOTICE
    elif fallback_to_all_frames:
        summary["reliability_note"] = "高置信度帧不足 3 帧，已退回使用全部帧。"
    else:
        summary["reliability_note"] = "报告优先基于高置信度帧生成。"
    return summary


def _apply_low_confidence_notice(report: dict[str, Any], vision_summary: dict[str, Any]) -> dict[str, Any]:
    reliability_note = str(vision_summary.get("reliability_note", "")).strip()
    if reliability_note != LOW_CONFIDENCE_NOTICE:
        return report

    summary = str(report.get("summary", "")).strip()
    if reliability_note not in summary:
        summary = f"{summary} {reliability_note}".strip()
    report["summary"] = summary

    if report.get("data_quality") == "good":
        report["data_quality"] = "partial"
    return report


def _fallback_report(
    action_type: str,
    vision_structured: dict[str, Any],
    bio_data: dict[str, Any] | None = None,
    *,
    dual_path_meta: dict[str, Any] | None = None,
    prompt_context: AnalysisPromptContext | None = None,
) -> dict[str, Any]:
    vision_summary = summarize_vision_for_report(vision_structured)
    frame_analysis = vision_summary.get("reliable_frames", [])
    issues: list[dict[str, object]] = _synthesize_issues_from_evidence(
        action_type,
        vision_summary,
        dual_path_meta,
        prompt_context,
    )
    for frame in frame_analysis:
        if not isinstance(frame, dict):
            continue
        for issue in frame.get("issues", [])[:1]:
            issue_text = str(issue)
            if any(_norm_key(issue_text) == _norm_key(existing.get("description")) for existing in issues):
                continue
            issues.append(
                {
                    "category": f"{frame.get('phase', '动作')}阶段",
                    "description": issue_text,
                    "severity": "medium",
                    "phase": str(frame.get("phase", "")),
                    "frames": [str(frame.get("frame_id", ""))],
                }
            )
        if len(issues) >= 3:
            break

    if not issues:
        issues = [
            {
                "category": "数据质量",
                "description": "当前视频可分析信息有限，建议结合教练观察复核。",
                "severity": "low",
                "phase": None,
                "frames": [],
            }
        ]

    synthesized_improvements = _synthesize_improvements(
        issues,
        action_type=action_type,
        prompt_context=prompt_context,
        dual_path_meta=dual_path_meta,
    )
    payload = {
        "summary": _summary_from_evidence(
            action_type,
            issues,
            prompt_context=prompt_context,
            dual_path_meta=dual_path_meta,
        ),
        "issues": issues,
        "improvements": synthesized_improvements,
        "training_focus": (
            f"本阶段优先训练{'、'.join(item['target'] for item in synthesized_improvements[:2])}，每次只挑一个目标复盘。"
            if synthesized_improvements
            else "本阶段重点是先稳定动作流程，再逐项修正技术细节。"
        ),
        "subscores": _fallback_subscores(),
        "data_quality": "partial",
    }
    action_confirmation = _action_confirmation_from_meta(dual_path_meta)
    if action_confirmation:
        payload["action_confirmation"] = action_confirmation
    if prompt_context is not None and prompt_context.user_note:
        payload["user_note"] = prompt_context.user_note
    note_response = _user_note_response(
        report=payload,
        action_type=action_type,
        prompt_context=prompt_context,
        dual_path_meta=dual_path_meta,
    )
    if note_response:
        payload["user_note_response"] = note_response
    return _apply_low_confidence_notice(normalize_report(payload, bio_data), vision_summary)


def _fallback_report_after_parse_failure(
    action_type: str,
    vision_structured: dict[str, Any],
    bio_data: dict[str, Any] | None,
    detail: str,
    *,
    dual_path_meta: dict[str, Any] | None = None,
    prompt_context: AnalysisPromptContext | None = None,
) -> dict[str, Any]:
    report = _fallback_report(
        action_type,
        vision_structured,
        bio_data,
        dual_path_meta=dual_path_meta,
        prompt_context=prompt_context,
    )
    report["fallback_reason"] = AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL.value
    report["fallback_detail"] = detail[:500]
    if report.get("data_quality") == "good":
        report["data_quality"] = "partial"
    return report


QUALITY_FLAG_DESCRIPTIONS = {
    "vision_ai_unavailable_fallback": "AI 视觉分析暂不可用，报告主要基于生物力学数据。",
    "pose_smoothing_failed_fallback": "骨架平滑失败，部分姿态指标可信度降低。",
    "target_tracking_uncertain": "目标跟踪存在不确定性，建议复核选人结果。",
}


def _format_subscore_label(key: str) -> str:
    labels = {
        "takeoff_power": "起跳发力",
        "rotation_axis": "旋转轴心",
        "arm_coordination": "手臂配合",
        "landing_absorption": "落冰缓冲",
        "core_stability": "核心稳定",
    }
    return labels.get(key, key)


def _fallback_report_after_ai_failure(
    action_type: str,
    bio_data: dict[str, Any] | None,
    detail: str,
    reason: str = AnalysisErrorCode.AI_API_TIMEOUT.value,
    *,
    vision_structured: dict[str, Any] | None = None,
    dual_path_meta: dict[str, Any] | None = None,
    prompt_context: AnalysisPromptContext | None = None,
) -> dict[str, Any]:
    has_structured_evidence = bool(
        _collect_path_b_issue_texts(dual_path_meta)
        or _collect_temporal_issue_texts(dual_path_meta)
        or _collect_frame_issue_texts(summarize_vision_for_report(vision_structured))
        if isinstance(vision_structured, dict)
        else False
    )
    if isinstance(vision_structured, dict) and has_structured_evidence:
        report = _fallback_report(
            action_type,
            vision_structured,
            bio_data,
            dual_path_meta=dual_path_meta,
            prompt_context=prompt_context,
        )
        report["fallback_used"] = True
        report["fallback_reason"] = reason
        report["fallback_detail"] = detail[:500]
        return report

    bio_subscores = bio_data.get("bio_subscores") if isinstance(bio_data, dict) else None
    subscores = {
        key: _clamp_score((bio_subscores or {}).get(key), _fallback_subscores()[key])
        for key in SUBSCORE_KEYS
    }
    score_text = " / ".join(f"{_format_subscore_label(key)} {subscores[key]}" for key in SUBSCORE_KEYS)
    quality_flags = bio_data.get("quality_flags") if isinstance(bio_data, dict) and isinstance(bio_data.get("quality_flags"), list) else []
    issues = [QUALITY_FLAG_DESCRIPTIONS.get(str(flag), str(flag)) for flag in quality_flags if flag]

    return {
        "summary": f"{action_type}动作生物力学评分:{score_text}",
        "issues": issues,
        "improvements": [],
        "training_focus": [],
        "subscores": subscores,
        "data_quality": "degraded_no_ai",
        "fallback_used": True,
        "fallback_reason": reason,
        "fallback_detail": detail[:500],
    }


def _is_deepseek_v4_provider(provider: Any) -> bool:
    model_id = str(getattr(provider, "model_id", "")).strip().lower()
    provider_name = str(getattr(provider, "provider", "")).strip().lower()
    return model_id.startswith("deepseek-v4-") or (provider_name == "deepseek" and model_id.startswith("deepseek-v4"))


def _report_response_format(provider: Any) -> dict[str, str] | None:
    if _is_deepseek_v4_provider(provider):
        return {"type": "json_object"}
    return None


async def generate_report(
    action_type: str,
    vision_structured: dict[str, Any],
    bio_data: dict[str, Any] | None = None,
    skater_id: str | None = None,
    *,
    dual_path_meta: dict[str, Any] | None = None,
    prompt_context: AnalysisPromptContext | None = None,
) -> dict[str, Any]:
    """
    Generate a structured training report.

    Args:
        action_type: User-facing action type.
        vision_structured: Normalized vision analysis payload.
        bio_data: Optional biomechanics data.
        skater_id: Optional skater id for memory context.
        dual_path_meta: Optional dual-path validation metadata.

    Returns:
        A normalized AI report, or a degraded biomechanics-only report when AI is unavailable.

    Raises:
        No AI provider exception is intentionally propagated; failures become fallback reports.
    """
    try:
        provider = await get_active_provider("report")
        memory_context = "" if prompt_context is not None else await build_memory_context(skater_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report provider unavailable, using biomechanics fallback: %s", exc)
        failure = classify_ai_failure(exc)
        return _fallback_report_after_ai_failure(
            action_type,
            bio_data,
            failure.detail,
            failure.code.value,
            vision_structured=vision_structured,
            dual_path_meta=dual_path_meta,
            prompt_context=prompt_context,
        )

    system_prompt = REPORT_SYSTEM_PROMPT if not memory_context else f"{REPORT_SYSTEM_PROMPT}\n\n{memory_context}"
    context_block = (
        "\n\n=== 统一分析上下文 ===\n" + render_prompt_context(prompt_context, include_bio=False)
        if prompt_context is not None
        else ""
    )
    vision_summary = summarize_vision_for_report(vision_structured)
    dual_block = _build_dual_path_report_context(dual_path_meta)
    video_temporal_block = _build_video_temporal_report_context(vision_structured, dual_path_meta)

    user_prompt = (
        f"请根据花样滑冰【{action_type}】结构化帧分析和骨骼几何指标，生成结构化训练报告。\n\n"
        "返回 JSON 必须包含：\n"
        "{\n"
        '  "summary": "总体评价 2-3 句",\n'
        '  "issues": [{"category":"问题类别","description":"具体描述","severity":"high|medium|low","phase":"落冰","frames":["frame_0012"]}],\n'
        '  "improvements": [{"target":"针对的问题","action":"具体改进动作"}],\n'
        '  "training_focus": "本阶段训练重点",\n'
        '  "subscores": {"takeoff_power":0,"rotation_axis":0,"arm_coordination":0,"landing_absorption":0,"core_stability":0},\n'
        '  "data_quality": "good|partial|poor",\n'
        '  "action_confirmation": {"action_family":"jump|spin|spiral|step|unknown","confirmed_action":"具体动作名或不可分析","confidence":0.0,"notes":"证据说明"},\n'
        '  "user_note_response": "如用户备注/comments 提问，必须用 1-2 句直接回应；若证据不足，明确说明只能确认到哪一层级。"\n'
        "}\n\n"
        "评分要求：subscores 每项为 0-100 的整数；优先参考骨骼几何指标，无法判断则给 partial。\n"
        "视觉评分参考：视觉摘要中的 pure_vision_subscores（0-1 小数）是纯视觉分析的评分，"
        "请将其乘以 100 作为重要参考，与骨骼几何指标综合判断。"
        "当骨骼数据缺失时，以视觉评分为主要依据。\n"
        "当 jump_metrics 中某项指标为 null 时，说明该指标无法从视频中测量，不代表技术差——"
        "请根据可见的动作阶段和姿态给分，不要因为数据缺失而扣分。"
        "例如 rotation_axis 指标缺失时，应根据空中姿态判断，给 50-60 分作为中性基线。\n"
        "评分对象说明：本系统主要服务青少年/儿童学员。若画面中可见学员体型明显偏小或处于学习阶段，"
        "请以该学员当前水平的合理基准给分，而不是以成年高水平选手为参照——"
        "完成 70-80 分表示该技术动作对其年龄段而言达成度尚可；"
        "只有出现明显技术错误或安全风险才扣到 60 分以下。同时仍按 ISU 体系指出真实存在的技术问题。\n"
        "视觉置信规则：优先使用 reliable_frames 中的高置信帧观察；"
        "当 fallback_to_all_frames 为 true 但 reliable_frames 仍包含可分析动作、问题或优点时，必须继续给出可执行的技术结论。\n"
        "质量表达要求：不要让 summary 只剩画质、视角或骨架不确定性。"
        "summary 必须先说明可确认的动作阶段、主要技术问题和训练方向；"
        "质量限制只作为补充说明。只有 apply_low_confidence_notice 为 true 时，才在 summary 末尾加入“低置信度帧较多，结果仅供参考”。\n"
        "当 data_quality_hint 为 partial/poor 或 camera_view 受限时，请区分“可确认的动作问题”和“不可确认的细节”；"
        "不可确认的刃型、周数或完成质量可以写入 issues，但不能替代训练建议。\n\n"
        "动作不确定性要求：如果 action_subtype 未指定、用户只知道动作大类，或 evidence 不足以确认具体跳种/旋转/步法名称，"
        "请使用动作大类和阶段来描述问题，不要编造具体细项。"
        "只有在视觉摘要、视频时序或 profile_evidence 明确支持时，才把 Lutz/Flip/Axel 等具体名称写进 summary/issues。\n"
        "用户备注/comments 要体现在关注点和训练建议中，但必须标注为“家长/学员备注提到...”或只作为训练重点线索，"
        "不要把备注里的感受写成已验证技术事实。"
        "如果 comments 是问题（例如“具体是哪个动作”“为什么落冰不稳”），必须在 user_note_response 中逐条直接回答；"
        "具体动作名必须优先参考视频时序的 action_confirmation，证据不足时写“只能确认大类/不可可靠确认具体细项”。\n\n"
        "问题与建议质量要求：issues 必须至少 2 条可执行技术问题，优先引用 Path B top_issues 或帧级 issues；"
        "不要只写“数据质量有限”。improvements 必须逐条对应具体问题，写成可以当天训练的动作或分段练习；"
        "不要输出泛化的“稳定轴心/软膝盖”模板，除非同时说明具体练习方法、阶段、次数和儿童安全边界。"
        "所有训练建议必须低冲击、短时长、可由家长或教练安全监督；不要安排负重、Bosu、旋转椅或痛苦拉伸。\n\n"
        f"用于生成报告的视觉摘要：\n{json.dumps(vision_summary, ensure_ascii=False)}\n\n"
        f"骨骼几何指标：\n{json.dumps(bio_data or {}, ensure_ascii=False)}"
        + context_block
        + dual_block
        + video_temporal_block
    )
    user_prompt += (
        "\n\nOutput constraints: return exactly one valid JSON object. "
        "The first character must be { and the last character must be }. "
        "Do not output reasoning, Markdown, code fences, or any text outside the JSON object."
    )

    response_format = _report_response_format(provider)
    temperature = 0.15 if _is_deepseek_v4_provider(provider) else 0.25
    last_failure_detail = "Report JSON parse failed before any model response."

    for attempt in range(1, REPORT_JSON_MAX_ATTEMPTS + 1):
        try:
            raw_content = await request_text_completion(
                provider,
                temperature=temperature,
                max_tokens=1800,
                timeout=REPORT_REQUEST_TIMEOUT_SECONDS,
                response_format=response_format,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Report AI request failed after retries, using biomechanics fallback: %s", exc)
            failure = classify_ai_failure(exc)
            return _fallback_report_after_ai_failure(
                action_type,
                bio_data,
                failure.detail,
                failure.code.value,
                vision_structured=vision_structured,
                dual_path_meta=dual_path_meta,
                prompt_context=prompt_context,
            )

        cleaned = clean_json_text(raw_content)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            last_failure_detail = (
                f"Report JSON parse failed on attempt {attempt}/{REPORT_JSON_MAX_ATTEMPTS}: "
                f"{exc}: {cleaned[:500]}"
            )
            continue

        parsed["data_quality"] = _resolve_report_data_quality(parsed, vision_structured, dual_path_meta)

        if prompt_context is not None and prompt_context.user_note:
            parsed["user_note"] = prompt_context.user_note

        report = _apply_low_confidence_notice(normalize_report(parsed, bio_data), vision_summary)
        report = _refine_report_with_structured_evidence(
            report,
            action_type=action_type,
            vision_summary=vision_summary,
            dual_path_meta=dual_path_meta,
            prompt_context=prompt_context,
        )
        if report["summary"] and report["training_focus"]:
            if attempt > 1:
                report["report_retry_count"] = attempt - 1
            return report

        last_failure_detail = (
            f"Report payload missing required fields on attempt {attempt}/{REPORT_JSON_MAX_ATTEMPTS}: {cleaned[:500]}"
        )

    return _fallback_report_after_parse_failure(
        action_type,
        vision_structured,
        bio_data,
        last_failure_detail,
        dual_path_meta=dual_path_meta,
        prompt_context=prompt_context,
    )
