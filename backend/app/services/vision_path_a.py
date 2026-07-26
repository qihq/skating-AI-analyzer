from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.providers import (
    ActiveProviderConfig,
    request_dashscope_video_completion,
    request_mimo_video_completion,
    request_text_completion,
)
from app.services.report import clean_json_text
from app.services.video import FramePayload
from app.services.vision import normalize_vision_payload
from app.services.vision_prompt_templates import build_specialized_vision_prompt
from app.services.vision_video_context import format_video_context_prompt_block, video_context_label


logger = logging.getLogger(__name__)

PATH_A_TEMPERATURE = 0.1
PATH_A_MAX_TOKENS_BASE = 1200
PATH_A_MAX_TOKENS_FRAME = 420
PATH_A_MAX_TOKENS_CAP = 10000
PATH_A_RESPONSE_FORMAT = {"type": "json_object"}
PATH_A_REPAIR_MAX_TOKENS = 3000

def _build_specialized_prompts(
    action_type: str,
    action_subtype: str | None,
    analysis_profile: str | None,
    profile_evidence: dict[str, Any] | None,
    motion_features: dict[str, Any] | list[Any] | None,
    skill_category: str | None = None,
    output_mode: Literal["frames", "video"] = "frames",
) -> tuple[str, str]:
    return build_specialized_vision_prompt(
        action_type=action_type,
        action_subtype=action_subtype,
        analysis_profile=analysis_profile,
        candidate_key_frames=None,
        motion_features=motion_features,
        biomechanics=None,
        profile_evidence=profile_evidence,
        skill_category=skill_category,
        output_mode=output_mode,
        include_biomechanics=False,
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
def _balanced_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for end in range(start, len(text)):
            current = text[end]
            if in_string:
                if escape:
                    escape = False
                elif current == "\\":
                    escape = True
                elif current == '"':
                    in_string = False
                continue

            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : end + 1])
                    break
    return candidates


def _parse_path_a_json(raw_text: str) -> tuple[dict[str, Any] | None, str]:
    if not raw_text or not raw_text.strip():
        return None, "empty"

    direct_candidates = [clean_json_text(raw_text), raw_text.strip()]
    for candidate in direct_candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed, "direct"
        except json.JSONDecodeError:
            pass

    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw_text, re.IGNORECASE)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            if isinstance(parsed, dict):
                return parsed, "code_fence"
        except json.JSONDecodeError:
            pass

    seen: set[str] = set()
    for source in (raw_text, clean_json_text(raw_text)):
        for candidate in _balanced_json_candidates(source):
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed, "balanced_object"
            except json.JSONDecodeError:
                continue

    return None, "failed"


def _load_path_a_payload_or_raise(raw_text: str) -> dict[str, Any]:
    parsed, method = _parse_path_a_json(raw_text)
    if isinstance(parsed, dict):
        if method != "direct":
            logger.info("Path A recovered non-standard JSON via %s.", method)
        return parsed

    cleaned = clean_json_text(raw_text or "")
    try:
        json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Path A JSON parse failed: %s; raw[:500]=%r", exc, cleaned[:500])
        raise AnalysisPipelineError(
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
            f"Path A JSON parse failed: {exc}: {cleaned[:500]}",
        ) from exc

    raise AnalysisPipelineError(
        AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
        f"Path A JSON parse failed: response is not a JSON object: {cleaned[:500]}",
    )


async def _repair_path_a_payload(
    provider: ActiveProviderConfig,
    *,
    raw_text: str,
    max_tokens: int,
) -> dict[str, Any] | None:
    if not raw_text or not raw_text.strip():
        return None

    repair_prompt = (
        "下面是一段花样滑冰 Path A 视觉分析模型输出，它本应是一个 JSON 对象，但可能有多余文字、截断、"
        "缺少逗号或括号不完整。请只修复 JSON 语法，不新增观察结论，不输出 Markdown。\n"
        "必须保留可识别的 frame_analysis、action_phase_summary、pure_vision_subscores、overall_raw_text 字段。\n\n"
        f"原始输出：\n{raw_text[:6000]}"
    )
    try:
        repaired = await request_text_completion(
            provider,
            temperature=0.0,
            max_tokens=min(PATH_A_REPAIR_MAX_TOKENS, max_tokens + 600),
            timeout=45.0,
            response_format=PATH_A_RESPONSE_FORMAT,
            messages=[
                {"role": "system", "content": "你是严格的 JSON 修复器，只输出一个合法 JSON 对象。"},
                {"role": "user", "content": repair_prompt},
            ],
        )
        parsed = _load_path_a_payload_or_raise(repaired)
        logger.info("Path A recovered malformed JSON through repair completion.")
        return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Path A JSON repair failed: %s", exc)
        return None


async def _parse_or_repair_path_a_payload(
    provider: ActiveProviderConfig,
    raw_text: str,
    *,
    max_tokens: int,
) -> dict[str, Any]:
    try:
        return _load_path_a_payload_or_raise(raw_text)
    except AnalysisPipelineError as exc:
        if exc.code != AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL:
            raise
        repaired = await _repair_path_a_payload(provider, raw_text=raw_text, max_tokens=max_tokens)
        if repaired is not None:
            return repaired
        raise


async def analyze_path_a(
    action_type: str,
    frame_payloads: list[FramePayload],
    provider: ActiveProviderConfig,
    *,
    action_subtype: str | None = None,
    analysis_profile: str | None = None,
    profile_evidence: dict[str, Any] | None = None,
    bio_data: dict[str, Any] | None = None,
    motion_features: dict[str, Any] | list[Any] | None = None,
    memory_context: str = "",
    mode: Literal["frames", "video"] = "video",
    clip_path: Path | None = None,
    window_start_sec: float = 0.0,
    skill_category: str | None = None,
    video_context_by_frame: dict[str, dict[str, Any]] | None = None,
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

    system_prompt, user_text = _build_specialized_prompts(
        action_type,
        action_subtype,
        analysis_profile,
        profile_evidence,
        motion_features,
        skill_category=skill_category,
        output_mode="video" if mode == "video" and clip_path is not None else "frames",
    )
    context_block = format_video_context_prompt_block(
        video_context_by_frame,
        include_skeleton_provenance=False,
        output_mode="video" if mode == "video" and clip_path is not None else "frames",
    )
    if context_block:
        user_text = f"{user_text}{context_block}"
    if memory_context:
        system_prompt = f"{system_prompt}\n\n{memory_context}"

    if mode == "video" and clip_path is not None:
        try:
            provider_name = getattr(provider, "provider", "")
            video_user_prompt = user_text
            if provider_name == "qwen":
                raw = await request_dashscope_video_completion(
                    provider,
                    video_path=clip_path,
                    system_prompt=system_prompt,
                    user_prompt=video_user_prompt,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    timeout=180.0,
                )
            elif provider_name == "mimo":
                raw = await request_mimo_video_completion(
                    provider,
                    video_path=clip_path,
                    system_prompt=system_prompt,
                    user_prompt=video_user_prompt,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    response_format=PATH_A_RESPONSE_FORMAT,
                    timeout=180.0,
                )
            else:
                raise AnalysisPipelineError(
                    AnalysisErrorCode.UNKNOWN_ERROR,
                    f"Path A native video mode does not support provider={provider_name}.",
                )
            parsed = await _parse_or_repair_path_a_payload(provider, raw, max_tokens=max_tokens)
            normalized = normalize_vision_payload(parsed, frame_payloads, window_start_sec=window_start_sec) | {
                "pure_vision_subscores": parsed.get("pure_vision_subscores") if isinstance(parsed.get("pure_vision_subscores"), dict) else {},
                "path": "A",
                "path_desc": "纯视觉判断（Qwen-VL 视频模式）",
                "vision_mode": "video",
            }
            return normalized
        except Exception as exc:  # noqa: BLE001
            logger.warning("Path A native video mode failed, falling back to frames: %s", exc)
            system_prompt, user_text = _build_specialized_prompts(
                action_type,
                action_subtype,
                analysis_profile,
                profile_evidence,
                motion_features,
                skill_category=skill_category,
                output_mode="frames",
            )
            context_block = format_video_context_prompt_block(
                video_context_by_frame,
                include_skeleton_provenance=False,
                output_mode="frames",
            )
            if context_block:
                user_text = f"{user_text}{context_block}"
            if memory_context:
                system_prompt = f"{system_prompt}\n\n{memory_context}"

    content: list[dict[str, object]] = [{"type": "text", "text": user_text}]
    for frame in frame_payloads:
        content.append({"type": "text", "text": f"帧编号：{frame.frame_id} | 时间：{frame.timestamp_sec:.2f}s"})
        context_label = video_context_label(frame.frame_id, video_context_by_frame)
        if context_label:
            content.append({"type": "text", "text": context_label})
        content.append({"type": "image_url", "image_url": {"url": frame.data_url}})

    raw = await request_text_completion(
        provider,
        temperature=PATH_A_TEMPERATURE,
        max_tokens=max_tokens,
        timeout=90.0,
        response_format=PATH_A_RESPONSE_FORMAT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    )

    parsed = await _parse_or_repair_path_a_payload(provider, raw, max_tokens=max_tokens)

    normalized = _normalize_path_a_payload(parsed, frame_payloads)
    if mode == "video" and clip_path is not None:
        flags = normalized.get("quality_flags") if isinstance(normalized.get("quality_flags"), list) else []
        if "vision_fallback_to_frames" not in flags:
            flags.append("vision_fallback_to_frames")
        normalized["quality_flags"] = flags
        normalized["vision_mode"] = "frames"
    return normalized
