from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.providers import ActiveProviderConfig, request_dashscope_video_completion, request_text_completion
from app.services.report import clean_json_text
from app.services.video import FramePayload
from app.services.vision import normalize_vision_payload


logger = logging.getLogger(__name__)

PATH_A_TEMPERATURE = 0.1
PATH_A_MAX_TOKENS_BASE = 800
PATH_A_MAX_TOKENS_FRAME = 280
PATH_A_MAX_TOKENS_CAP = 8000

PATH_A_SYSTEM = (
    "你是拥有 10 年执教经验的花样滑冰专项教练，本次以场边肉眼观察的视角分析。"
    "**不引入任何骨架或测量数据**，只基于画面给出第一直觉判断。"
    "严格输出 JSON，禁止任何额外文字。"
)


def _build_user_prompt(
    action_type: str,
    action_subtype: str | None,
    analysis_profile: str | None,
    profile_evidence: dict[str, Any] | None,
    n_frames: int,
) -> str:
    ev = json.dumps(profile_evidence or {}, ensure_ascii=False)
    jump_evidence_instruction = (
        "JUMP_SUBTYPE_EVIDENCE: prioritize profile_evidence.jump_subtype_evidence for Lutz/Flip/Loop/Salchow/Axel clues. "
        "pre_takeoff_edge_score near 0 supports Lutz outside edge, near 1 supports Flip inside edge; low confidence means uncertain.\n"
    )
    return (
        f"分析以下【{action_type}】动作帧序列（共 {n_frames} 帧，按时间顺序排列）。\n"
        f"动作子类型：{action_subtype or '未指定'}\n"
        f"分析 profile：{analysis_profile or 'unknown'}\n"
        f"规则证据：{ev}\n"
        f"{jump_evidence_instruction}"
        "重要约束：燕式滑行/螺旋线不要误判为跳跃，除非存在清晰的起跳/腾空/落冰证据。\n\n"
        "**纯视觉判断**（不要假设任何测量数据），每一帧输出以下结构化数据：\n\n"
        '{"frame_analysis":[{"frame_id":"frame_0001",'
        '"phase":"准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",'
        '"observations":{"knee_bend":"充分|不足|过度|不适用",'
        '"arm_position":"正确|偏高|偏低|不对称|不适用",'
        '"axis_alignment":"垂直|前倾|后仰|侧倾|不适用",'
        '"blade_edge":"外刃|内刃|平刃|不适用",'
        '"core_stability":"稳定|轻微晃动|明显晃动|不适用",'
        '"landing_absorption":"良好|不足|过度|不适用"},'
        '"issues":["问题描述"],"positives":["优点描述"],"confidence":0.0}],'
        '"action_phase_summary":{"detected_phases":["起跳","腾空","落冰"],'
        '"weakest_phase":"最需改进的阶段","strongest_phase":"表现最好的阶段"},'
        '"pure_vision_subscores":{"takeoff_power":0,"rotation_axis":0,'
        '"arm_coordination":0,"landing_absorption":0,"core_stability":0},'
        '"overall_raw_text":"综合文字描述 2-3 句"}\n\n'
        "必须只输出 JSON。"
    )


def _build_video_user_prompt(
    action_type: str,
    action_subtype: str | None,
    analysis_profile: str | None,
    profile_evidence: dict[str, Any] | None,
    n_frames: int,
) -> str:
    base = _build_user_prompt(action_type, action_subtype, analysis_profile, profile_evidence, n_frames)
    return (
        base
        + "\n\n视频模式要求：按视频片段内秒数定位关键事件，优先返回 phase_segments，而不是逐帧 frame_id。"
        + "JSON schema: "
        + '{"phase_segments":[{"start_sec":0.2,"end_sec":0.6,"phase":"准备",'
        + '"observations":{},"issues":[],"positives":[],"confidence":0.8}],'
        + '"action_phase_summary":{"detected_phases":["起跳"],"weakest_phase":"落冰","strongest_phase":"起跳"},'
        + '"pure_vision_subscores":{"takeoff_power":0,"rotation_axis":0,"arm_coordination":0,'
        + '"landing_absorption":0,"core_stability":0},"overall_raw_text":"2-3句总结"}'
    )


def _normalize_path_a_payload(
    parsed: dict[str, Any],
    frame_payloads: list[FramePayload],
) -> dict[str, Any]:
    """
    Keep the existing normalized vision schema, then explicitly add Path A fields.

    normalize_vision_payload intentionally preserves only the shared vision keys;
    this wrapper prevents Path A-only fields from being dropped silently.
    """
    normalized = normalize_vision_payload(parsed, frame_payloads)
    subs = parsed.get("pure_vision_subscores")
    normalized["pure_vision_subscores"] = subs if isinstance(subs, dict) else {}
    normalized["path"] = "A"
    normalized["path_desc"] = "纯视觉判断（与 analyze_frames schema 兼容）"
    return normalized


async def analyze_path_a(
    action_type: str,
    frame_payloads: list[FramePayload],
    provider: ActiveProviderConfig,
    *,
    action_subtype: str | None = None,
    analysis_profile: str | None = None,
    profile_evidence: dict[str, Any] | None = None,
    memory_context: str = "",
    mode: Literal["frames", "video"] = "video",
    clip_path: Path | None = None,
    window_start_sec: float = 0.0,
) -> dict[str, Any]:
    """
    Path A: pure vision analysis, called opt-in by the host.
    """
    if not frame_payloads:
        raise AnalysisPipelineError(
            AnalysisErrorCode.FRAME_EXTRACT_FAILED,
            "Path A 无可分析帧",
        )

    n_frames = len(frame_payloads)
    max_tokens = min(
        PATH_A_MAX_TOKENS_CAP,
        PATH_A_MAX_TOKENS_BASE + n_frames * PATH_A_MAX_TOKENS_FRAME,
    )

    system_prompt = PATH_A_SYSTEM if not memory_context else f"{PATH_A_SYSTEM}\n\n{memory_context}"
    user_text = _build_user_prompt(
        action_type,
        action_subtype,
        analysis_profile,
        profile_evidence,
        n_frames,
    )

    if mode == "video" and clip_path is not None:
        try:
            raw = await request_dashscope_video_completion(
                provider,
                video_path=clip_path,
                system_prompt=system_prompt,
                user_prompt=_build_video_user_prompt(
                    action_type,
                    action_subtype,
                    analysis_profile,
                    profile_evidence,
                    n_frames,
                ),
                temperature=0.0,
                max_tokens=max_tokens,
                timeout=180.0,
            )
            parsed = json.loads(clean_json_text(raw))
            normalized = normalize_vision_payload(parsed, frame_payloads, window_start_sec=window_start_sec) | {
                "pure_vision_subscores": parsed.get("pure_vision_subscores") if isinstance(parsed.get("pure_vision_subscores"), dict) else {},
                "path": "A",
                "path_desc": "纯视觉判断（Qwen-VL 视频模式）",
                "vision_mode": "video",
            }
            return normalized
        except Exception as exc:  # noqa: BLE001
            logger.warning("Path A native video mode failed, falling back to frames: %s", exc)

    content: list[dict[str, object]] = [{"type": "text", "text": user_text}]
    for frame in frame_payloads:
        content.append({"type": "text", "text": f"帧编号：{frame.frame_id} | 时间：{frame.timestamp_sec:.2f}s"})
        content.append({"type": "image_url", "image_url": {"url": frame.data_url}})

    raw = await request_text_completion(
        provider,
        temperature=PATH_A_TEMPERATURE,
        max_tokens=max_tokens,
        timeout=90.0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    )

    cleaned = clean_json_text(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Path A JSON parse failed: %s; raw[:500]=%r", exc, cleaned[:500])
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Path A JSON parse failed: {exc}: {cleaned[:500]}",
        ) from exc

    normalized = _normalize_path_a_payload(parsed, frame_payloads)
    if mode == "video" and clip_path is not None:
        flags = normalized.get("quality_flags") if isinstance(normalized.get("quality_flags"), list) else []
        if "vision_fallback_to_frames" not in flags:
            flags.append("vision_fallback_to_frames")
        normalized["quality_flags"] = flags
        normalized["vision_mode"] = "frames"
    return normalized
