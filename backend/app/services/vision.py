from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.providers import extract_message_text, get_active_provider
from app.services.report import clean_json_text
from app.services.snowball import build_memory_context
from app.services.video import FramePayload


logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = (
    "你是专业花样滑冰技术分析师，熟悉 ISU 评分体系和生物力学。"
    "你的输出必须严格遵循指定 JSON 格式，不得输出任何格式之外的文字。"
)

VALID_PHASES = {"准备", "起跳", "腾空", "落冰", "滑出", "旋转入", "旋转中", "旋转出", "步法", "不可分析"}


def _fallback_frame(frame_id: str) -> dict[str, Any]:
    return {
        "frame_id": frame_id,
        "phase": "不可分析",
        "observations": {
            "knee_bend": "不适用",
            "arm_position": "不适用",
            "axis_alignment": "不适用",
            "blade_edge": "不适用",
            "core_stability": "不适用",
            "landing_absorption": "不适用",
        },
        "issues": [],
        "positives": [],
        "confidence": 0.0,
    }


def normalize_vision_payload(payload: dict[str, Any], frame_payloads: list[FramePayload]) -> dict[str, Any]:
    by_frame = {
        str(item.get("frame_id", "")): item
        for item in payload.get("frame_analysis", [])
        if isinstance(item, dict)
    }

    frame_analysis: list[dict[str, Any]] = []
    for frame in frame_payloads:
        raw = by_frame.get(frame.frame_id, {})
        normalized = _fallback_frame(frame.frame_id)
        if isinstance(raw, dict):
            normalized["phase"] = raw.get("phase") if raw.get("phase") in VALID_PHASES else normalized["phase"]
            observations = raw.get("observations") if isinstance(raw.get("observations"), dict) else {}
            normalized["observations"].update({key: str(value) for key, value in observations.items()})
            normalized["issues"] = [str(item) for item in raw.get("issues", []) if item]
            normalized["positives"] = [str(item) for item in raw.get("positives", []) if item]
            try:
                normalized["confidence"] = max(0.0, min(float(raw.get("confidence", 0.0)), 1.0))
            except (TypeError, ValueError):
                normalized["confidence"] = 0.0
        frame_analysis.append(normalized)

    summary = payload.get("action_phase_summary") if isinstance(payload.get("action_phase_summary"), dict) else {}
    detected_phases = [
        str(phase)
        for phase in summary.get("detected_phases", [])
        if str(phase) in VALID_PHASES and str(phase) != "不可分析"
    ]

    return {
        "frame_analysis": frame_analysis,
        "action_phase_summary": {
            "detected_phases": detected_phases,
            "weakest_phase": str(summary.get("weakest_phase", "不可分析")),
            "strongest_phase": str(summary.get("strongest_phase", "不可分析")),
        },
        "overall_raw_text": str(payload.get("overall_raw_text", "")).strip(),
    }


async def analyze_frames(
    action_type: str,
    frame_payloads: list[FramePayload],
    skater_id: str | None = None,
) -> dict[str, Any]:
    provider = await get_active_provider("vision")
    client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=90.0, max_retries=0)
    extra_body = {"enable_thinking": False} if provider.model_id == "qwen3.6-plus" else None
    memory_context = await build_memory_context(skater_id)
    system_prompt = VISION_SYSTEM_PROMPT if not memory_context else f"{VISION_SYSTEM_PROMPT}\n\n{memory_context}"

    user_prompt = (
        f"分析以下【{action_type}】动作帧序列（共 {len(frame_payloads)} 帧，按时间顺序排列）。\n\n"
        "对每一帧，输出以下结构化数据：\n\n"
        "{\n"
        '  "frame_analysis": [\n'
        "    {\n"
        '      "frame_id": "frame_0001",\n'
        '      "phase": "准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",\n'
        '      "observations": {\n'
        '        "knee_bend": "充分|不足|过度|不适用",\n'
        '        "arm_position": "正确|偏高|偏低|不对称|不适用",\n'
        '        "axis_alignment": "垂直|前倾|后仰|侧倾|不适用",\n'
        '        "blade_edge": "外刃|内刃|平刃|不适用",\n'
        '        "core_stability": "稳定|轻微晃动|明显晃动|不适用",\n'
        '        "landing_absorption": "良好|不足|过度|不适用"\n'
        "      },\n"
        '      "issues": ["问题描述1"],\n'
        '      "positives": ["优点描述1"],\n'
        '      "confidence": 0.0\n'
        "    }\n"
        "  ],\n"
        '  "action_phase_summary": {\n'
        '    "detected_phases": ["起跳", "腾空", "落冰"],\n'
        '    "weakest_phase": "最需改进的阶段",\n'
        '    "strongest_phase": "表现最好的阶段"\n'
        "  },\n"
        '  "overall_raw_text": "综合文字描述 2-3 句"\n'
        "}\n\n"
        "必须只输出 JSON。"
    )

    content: list[dict[str, object]] = [{"type": "text", "text": user_prompt}]
    for frame in frame_payloads:
        content.append({"type": "text", "text": f"帧编号：{frame.frame_id}"})
        content.append({"type": "image_url", "image_url": {"url": frame.data_url}})

    response = await client.chat.completions.create(
        model=provider.model_id,
        temperature=0.1,
        max_tokens=3500,
        extra_body=extra_body,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    )

    raw_content = extract_message_text(response.choices[0].message.content)
    cleaned = clean_json_text(raw_content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Vision JSON parse failed: %s", exc)
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Vision JSON parse failed: {exc}: {cleaned[:500]}",
        ) from exc
        parsed = {
            "frame_analysis": [_fallback_frame(frame.frame_id) for frame in frame_payloads],
            "action_phase_summary": {
                "detected_phases": [],
                "weakest_phase": "不可分析",
                "strongest_phase": "不可分析",
            },
            "overall_raw_text": raw_content[:500],
        }

    return normalize_vision_payload(parsed, frame_payloads)
