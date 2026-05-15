from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.schemas import Severity
from app.services.analysis_errors import AnalysisErrorCode, classify_ai_failure
from app.services.providers import get_active_provider, request_text_completion
from app.services.snowball import build_memory_context


logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = (
    "你是花样滑冰训练报告生成助手。"
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
    }


def _resolve_report_data_quality(payload: dict[str, Any], vision_structured: dict[str, Any]) -> str:
    report_quality = str(payload.get("data_quality", "partial")).strip().lower() or "partial"
    if report_quality not in {"good", "partial", "poor"}:
        report_quality = "partial"

    vision_quality = str(vision_structured.get("data_quality_hint", "")).strip().lower()
    if vision_quality == "poor":
        return "poor"
    if vision_quality == "partial" and report_quality == "good":
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
        "\n注意：subscores 字段由后端融合计算，你不要自行加权。\n"
        "请根据骨架信号设置 data_quality：\n"
        "  reliable → good / uncertain → partial / likely_wrong → poor\n"
        "若 likely_wrong，请在 issues 末尾追加一条 severity=medium 的提示\n"
        "（category='追踪质量'，description 建议用户重选目标）。\n"
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


def _fallback_report(action_type: str, vision_structured: dict[str, Any], bio_data: dict[str, Any] | None = None) -> dict[str, Any]:
    vision_summary = summarize_vision_for_report(vision_structured)
    frame_analysis = vision_summary.get("reliable_frames", [])
    issues: list[dict[str, object]] = []
    for frame in frame_analysis:
        if not isinstance(frame, dict):
            continue
        for issue in frame.get("issues", [])[:1]:
            issues.append(
                {
                    "category": f"{frame.get('phase', '动作')}阶段",
                    "description": str(issue),
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

    payload = {
        "summary": f"本次{action_type}复盘已结合结构化视觉和骨骼几何指标生成。整体动作可继续围绕轴心、发力节奏和落冰稳定性微调。",
        "issues": issues,
        "improvements": [
            {"target": "轴心稳定", "action": "用短时、低冲击的分段练习保持头肩髋对齐。"},
            {"target": "落冰缓冲", "action": "练习轻落地和软膝盖停住，优先保证安全稳定。"},
        ],
        "training_focus": "本阶段重点是稳定轴心和提高落冰控制。",
        "subscores": _fallback_subscores(),
        "data_quality": "partial",
    }
    return _apply_low_confidence_notice(normalize_report(payload, bio_data), vision_summary)


def _fallback_report_after_parse_failure(
    action_type: str,
    vision_structured: dict[str, Any],
    bio_data: dict[str, Any] | None,
    detail: str,
) -> dict[str, Any]:
    report = _fallback_report(action_type, vision_structured, bio_data)
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
) -> dict[str, Any]:
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
        memory_context = await build_memory_context(skater_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Report provider unavailable, using biomechanics fallback: %s", exc)
        failure = classify_ai_failure(exc)
        return _fallback_report_after_ai_failure(action_type, bio_data, failure.detail, failure.code.value)

    system_prompt = REPORT_SYSTEM_PROMPT if not memory_context else f"{REPORT_SYSTEM_PROMPT}\n\n{memory_context}"
    vision_summary = summarize_vision_for_report(vision_structured)
    dual_block = _build_dual_path_report_context(dual_path_meta)

    user_prompt = (
        f"请根据花样滑冰【{action_type}】结构化帧分析和骨骼几何指标，生成结构化训练报告。\n\n"
        "返回 JSON 必须包含：\n"
        "{\n"
        '  "summary": "总体评价 2-3 句",\n'
        '  "issues": [{"category":"问题类别","description":"具体描述","severity":"high|medium|low","phase":"落冰","frames":["frame_0012"]}],\n'
        '  "improvements": [{"target":"针对的问题","action":"具体改进动作"}],\n'
        '  "training_focus": "本阶段训练重点",\n'
        '  "subscores": {"takeoff_power":0,"rotation_axis":0,"arm_coordination":0,"landing_absorption":0,"core_stability":0},\n'
        '  "data_quality": "good|partial|poor"\n'
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
        f"用于生成报告的视觉摘要：\n{json.dumps(vision_summary, ensure_ascii=False)}\n\n"
        f"骨骼几何指标：\n{json.dumps(bio_data or {}, ensure_ascii=False)}"
        + dual_block
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
            return _fallback_report_after_ai_failure(action_type, bio_data, failure.detail, failure.code.value)

        cleaned = clean_json_text(raw_content)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            last_failure_detail = (
                f"Report JSON parse failed on attempt {attempt}/{REPORT_JSON_MAX_ATTEMPTS}: "
                f"{exc}: {cleaned[:500]}"
            )
            continue

        parsed["data_quality"] = _resolve_report_data_quality(parsed, vision_structured)

        report = _apply_low_confidence_notice(normalize_report(parsed, bio_data), vision_summary)
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
    )
