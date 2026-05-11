"""LLM 报告生成：基于视觉分析和生物力学指标生成结构化训练报告。已解耦，可独立使用。"""
from __future__ import annotations

import json
import re
from typing import Any

from skating_vision.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from skating_vision.providers import ActiveProviderConfig, request_text_completion

REPORT_SYSTEM_PROMPT = "你是花样滑冰训练报告生成助手。你必须严格输出 JSON 对象，不要输出 Markdown，不要解释，不要使用 ```json 包裹。"
SUBSCORE_KEYS = ["takeoff_power", "rotation_axis", "arm_coordination", "landing_absorption", "core_stability"]
SUBSCORE_WEIGHTS = {"takeoff_power": 0.25, "rotation_axis": 0.25, "arm_coordination": 0.15, "landing_absorption": 0.25, "core_stability": 0.10}


def clean_json_text(raw: str) -> str:
    c = raw.strip()
    c = re.sub(r"^```json\s*", "", c, flags=re.IGNORECASE)
    c = re.sub(r"^```\s*", "", c)
    c = re.sub(r"\s*```$", "", c)
    if c.startswith("{") and c.endswith("}"):
        return c
    s, e = c.find("{"), c.rfind("}")
    return c[s:e + 1] if s != -1 and e != -1 and e > s else c


def _clamp(v: object, d: int = 75) -> int:
    try:
        return max(0, min(int(round(float(v))), 100))
    except (TypeError, ValueError):
        return d


def _fallback_sub() -> dict[str, int]:
    return {k: 75 for k in SUBSCORE_KEYS}


def fuse_subscores(ai: dict[str, Any], bio: dict[str, Any] | None) -> dict[str, int]:
    na = {k: _clamp(ai.get(k), 75) for k in SUBSCORE_KEYS}
    if not bio:
        return na
    return {k: round(na[k] * 0.4 + _clamp(bio.get(k), na[k]) * 0.6) for k in SUBSCORE_KEYS}


def calculate_force_score(report: dict[str, Any]) -> int:
    subs = report.get("subscores") if isinstance(report.get("subscores"), dict) else {}
    if subs:
        return round(sum(_clamp(subs.get(k), 0) * w for k, w in SUBSCORE_WEIGHTS.items()))
    sev = {"high": 15, "medium": 8, "low": 3}
    s = 100
    for i in report.get("issues", []):
        s -= sev.get(str(i.get("severity", "")).lower(), 0)
    return max(s, 0)


def normalize_report(payload: dict[str, Any], bio_data: dict[str, Any] | None = None) -> dict[str, Any]:
    issues = []
    for i in payload.get("issues", []):
        if not isinstance(i, dict):
            continue
        sev = str(i.get("severity", "low")).lower()
        if sev not in {"high", "medium", "low"}:
            sev = "low"
        fr = i.get("frames", [])
        issues.append({"category": str(i.get("category", "")).strip() or "技术问题", "description": str(i.get("description", "")).strip(),
                        "severity": sev, "phase": str(i.get("phase", "")).strip() or None, "frames": [str(f) for f in fr] if isinstance(fr, list) else []})
    imps = []
    for i in payload.get("improvements", []):
        if isinstance(i, dict):
            imps.append({"target": str(i.get("target", "")).strip(), "action": str(i.get("action", "")).strip()})
    bio_sub = None
    if isinstance(bio_data, dict) and bio_data.get("key_frames"):
        bio_sub = bio_data.get("bio_subscores") if isinstance(bio_data.get("bio_subscores"), dict) else None
    return {
        "summary": str(payload.get("summary", "")).strip(), "issues": issues, "improvements": imps,
        "training_focus": str(payload.get("training_focus", "")).strip(),
        "subscores": fuse_subscores(payload.get("subscores", {}) if isinstance(payload.get("subscores"), dict) else {}, bio_sub),
        "data_quality": str(payload.get("data_quality", "partial")).strip() or "partial",
    }


async def generate_report(
    action_type: str,
    vision_structured: dict[str, Any],
    provider: ActiveProviderConfig,
    bio_data: dict[str, Any] | None = None,
    memory_context: str = "",
) -> dict[str, Any]:
    sys = REPORT_SYSTEM_PROMPT if not memory_context else f"{REPORT_SYSTEM_PROMPT}\n\n{memory_context}"
    raw = await request_text_completion(provider, temperature=0.25, max_tokens=1800, messages=[
        {"role": "system", "content": sys},
        {"role": "user", "content": (
            f"请根据花样滑冰【{action_type}】结构化帧分析和骨骼几何指标，生成结构化训练报告。\n\n"
            '返回 JSON 必须包含：\n{"summary":"总体评价 2-3 句","issues":[{"category":"问题类别","description":"具体描述","severity":"high|medium|low","phase":"落冰","frames":["frame_0012"]}],'
            '"improvements":[{"target":"针对的问题","action":"具体改进动作"}],"training_focus":"本阶段训练重点",'
            '"subscores":{"takeoff_power":0,"rotation_axis":0,"arm_coordination":0,"landing_absorption":0,"core_stability":0},"data_quality":"good|partial|poor"}\n\n'
            f"结构化帧分析：\n{json.dumps(vision_structured, ensure_ascii=False)}\n\n骨骼几何指标：\n{json.dumps(bio_data or {}, ensure_ascii=False)}"
        )},
    ])
    cleaned = clean_json_text(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AnalysisPipelineError(AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL, f"Report JSON parse failed: {exc}: {cleaned[:500]}") from exc
    report = normalize_report(parsed, bio_data)
    if not report["summary"] or not report["training_focus"]:
        raise AnalysisPipelineError(AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL, f"Report missing fields: {cleaned[:500]}")
    return report
