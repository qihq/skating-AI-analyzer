from __future__ import annotations

import json
import re
from typing import Any

from app.schemas import Severity
from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.providers import get_active_provider, request_text_completion
from app.services.snowball import build_memory_context


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
LOW_CONFIDENCE_NOTICE = "低置信度帧较多，结果仅供参考。"
REPORT_REQUEST_TIMEOUT_SECONDS = 120.0


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
    if isinstance(bio_data, dict) and bio_data.get("key_frames"):
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


def summarize_vision_for_report(vision_structured: dict[str, Any]) -> dict[str, Any]:
    frames = vision_structured.get("frame_analysis", []) if isinstance(vision_structured, dict) else []
    normalized_frames = [frame for frame in frames if isinstance(frame, dict)]
    high_conf_frames = [
        frame for frame in normalized_frames if float(frame.get("confidence", 0.0) or 0.0) >= HIGH_CONF_THRESHOLD
    ]
    low_conf_count = len(normalized_frames) - len(high_conf_frames)
    fallback_to_all_frames = False

    if len(high_conf_frames) < 3:
        high_conf_frames = normalized_frames
        low_conf_count = 0
        fallback_to_all_frames = True

    all_low_confidence = bool(normalized_frames) and all(
        float(frame.get("confidence", 0.0) or 0.0) < HIGH_CONF_THRESHOLD for frame in normalized_frames
    )

    summary: dict[str, Any] = {
        "reliable_frames": high_conf_frames,
        "low_confidence_frame_count": low_conf_count,
        "overall_raw_text": vision_structured.get("overall_raw_text", "") if isinstance(vision_structured, dict) else "",
        "total_frame_count": len(normalized_frames),
        "high_confidence_threshold": HIGH_CONF_THRESHOLD,
        "fallback_to_all_frames": fallback_to_all_frames,
        "all_low_confidence": all_low_confidence,
    }
    if isinstance(vision_structured, dict):
        summary["action_phase_summary"] = vision_structured.get("action_phase_summary", {})
        if vision_structured.get("data_quality_hint") is not None:
            summary["data_quality_hint"] = vision_structured.get("data_quality_hint")
        if vision_structured.get("fallback_reason") is not None:
            summary["fallback_reason"] = vision_structured.get("fallback_reason")

    if low_conf_count > 0 or all_low_confidence:
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
        report["summary"] = f"{summary} {reliability_note}".strip()

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


async def generate_report(
    action_type: str,
    vision_structured: dict[str, Any],
    bio_data: dict[str, Any] | None = None,
    skater_id: str | None = None,
) -> dict[str, Any]:
    provider = await get_active_provider("report")
    memory_context = await build_memory_context(skater_id)
    system_prompt = REPORT_SYSTEM_PROMPT if not memory_context else f"{REPORT_SYSTEM_PROMPT}\n\n{memory_context}"
    vision_summary = summarize_vision_for_report(vision_structured)

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
        "视觉置信规则：优先使用 reliable_frames 中的高置信帧观察。"
        "如果 low_confidence_frame_count 大于 0，请在 summary 中明确提醒“低置信度帧较多，结果仅供参考”，"
        "并避免过度肯定的结论。如果 fallback_to_all_frames 为 true，请指出高置信帧不足。\n\n"
        f"用于生成报告的视觉摘要：\n{json.dumps(vision_summary, ensure_ascii=False)}\n\n"
        f"骨骼几何指标：\n{json.dumps(bio_data or {}, ensure_ascii=False)}"
    )

    raw_content = await request_text_completion(
        provider,
        temperature=0.25,
        max_tokens=1800,
        timeout=REPORT_REQUEST_TIMEOUT_SECONDS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    cleaned = clean_json_text(raw_content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Report JSON parse failed: {exc}: {cleaned[:500]}",
        ) from exc

    parsed["data_quality"] = _resolve_report_data_quality(parsed, vision_structured)

    report = _apply_low_confidence_notice(normalize_report(parsed, bio_data), vision_summary)
    if not report["summary"] or not report["training_focus"]:
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Report payload missing required fields: {cleaned[:500]}",
        )
    return report
