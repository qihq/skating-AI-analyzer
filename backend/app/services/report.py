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


def fuse_subscores(ai_subscores: dict[str, Any], bio_subscores: dict[str, Any] | None) -> dict[str, int]:
    normalized_ai = {key: _clamp_score(ai_subscores.get(key), 75) for key in SUBSCORE_KEYS}
    if not bio_subscores:
        return normalized_ai

    fused: dict[str, int] = {}
    for key in SUBSCORE_KEYS:
        ai_score = normalized_ai[key]
        bio_score = _clamp_score(bio_subscores.get(key), ai_score)
        fused[key] = round(ai_score * 0.4 + bio_score * 0.6)
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
    if isinstance(bio_data, dict) and bio_data.get("key_frames"):
        bio_subscores = bio_data.get("bio_subscores") if isinstance(bio_data.get("bio_subscores"), dict) else None

    return {
        "summary": str(payload.get("summary", "")).strip(),
        "issues": normalized_issues,
        "improvements": normalized_improvements,
        "training_focus": str(payload.get("training_focus", "")).strip(),
        "subscores": fuse_subscores(payload.get("subscores", {}) if isinstance(payload.get("subscores"), dict) else {}, bio_subscores),
        "data_quality": str(payload.get("data_quality", "partial")).strip() or "partial",
    }


def _fallback_report(action_type: str, vision_structured: dict[str, Any], bio_data: dict[str, Any] | None = None) -> dict[str, Any]:
    frame_analysis = vision_structured.get("frame_analysis", []) if isinstance(vision_structured, dict) else []
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
    return normalize_report(payload, bio_data)


async def generate_report(
    action_type: str,
    vision_structured: dict[str, Any],
    bio_data: dict[str, Any] | None = None,
    skater_id: str | None = None,
) -> dict[str, Any]:
    provider = await get_active_provider("report")
    memory_context = await build_memory_context(skater_id)
    system_prompt = REPORT_SYSTEM_PROMPT if not memory_context else f"{REPORT_SYSTEM_PROMPT}\n\n{memory_context}"

    raw_content = await request_text_completion(
        provider,
        temperature=0.25,
        max_tokens=1800,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
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
                    "评分要求：subscores 每项为 0-100 的整数；优先参考骨骼几何指标，无法判断则给 partial。\n\n"
                    f"结构化帧分析：\n{json.dumps(vision_structured, ensure_ascii=False)}\n\n"
                    f"骨骼几何指标：\n{json.dumps(bio_data or {}, ensure_ascii=False)}"
                ),
            },
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

    report = normalize_report(parsed, bio_data)
    if not report["summary"] or not report["training_focus"]:
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Report payload missing required fields: {cleaned[:500]}",
        )
    return report
