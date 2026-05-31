from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Literal

from app.services.analysis_errors import AnalysisErrorCode, classify_ai_failure
from app.services.action_profiles import get_jump_characteristics
from app.services.providers import (
    get_active_provider,
    get_vision_providers,
    request_dashscope_video_completion,
    request_doubao_vision_completion,
    request_mimo_video_completion,
    request_text_completion,
)
from app.services.report import clean_json_text
from app.services.snowball import build_memory_context
from app.services.video import FramePayload
from app.services.vision_fusion import fuse_vision_results_weighted
from app.services.vision_quality import apply_low_quality_policy
from app.services.vision_prompt_templates import build_specialized_vision_prompt
from app.services.vision_video_context import normalize_video_context_fields


logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = (
    "你是专业花样滑冰技术分析师，熟悉 ISU 评分体系和生物力学。"
    "你的输出必须严格遵循指定 JSON 格式，不得输出任何格式之外的文字。"
)

PROFILE_HINTS: dict[str, str] = {
    "jump": (
        "重点观察：① 起跳阶段膝关节弯曲深度（深蹲效果）"
        " ② 腾空阶段手臂是否快速收紧至胸前"
        " ③ 落冰阶段是否为单腿支撑、膝盖弯曲缓冲"
        " ④ 轴线是否保持垂直，无明显侧倾。"
    ),
    "spin": (
        "重点观察：① 旋转轴垂直度，是否存在前倾/后仰漂移"
        " ② 手臂/腿收紧与旋转加速的对应关系"
        " ③ 入转和出转冰刃切换是否流畅"
        " ④ 头部固定点（spotting）是否存在。"
    ),
    "spiral": (
        "重点观察：① 自由腿高度，理想应超过髋关节水平线"
        " ② 支撑腿膝盖是否完全伸直"
        " ③ 躯干稳定性，不应有明显晃动"
        " ④ 手臂姿态是否与身体轴线协调。"
    ),
    "step": (
        "重点观察：① 冰刃切换节奏是否与音乐/节拍匹配"
        " ② 膝盖推送力度，每步是否有明显 push"
        " ③ 上半身（肩/臂）是否过度摆动"
        " ④ 重心转移是否平稳，无明显身体侧倾。"
    ),
}

VALID_PHASES = {"准备", "起跳", "腾空", "落冰", "滑出", "旋转入", "旋转中", "旋转出", "步法", "不可分析"}
VALID_DATA_QUALITY_HINTS = {"good", "partial", "poor"}
VALID_CAMERA_VIEWS = {"front", "side", "diagonal_front", "diagonal_back", "unknown"}
VALID_FRAME_KEY_AGREEMENTS = {"T", "A", "L", "none", "shifted", "disagree", "unavailable"}
VALID_SUMMARY_KEY_AGREEMENTS = {"agree", "shifted", "disagree", "unavailable"}
DEFAULT_VISION_N_VOTES = 2


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


def _fallback_unavailable_payload(frame_payloads: list[FramePayload], reason: str) -> dict[str, Any]:
    return {
        "frame_analysis": [_fallback_frame(frame.frame_id) for frame in frame_payloads],
        "action_phase_summary": "AI 视觉分析暂不可用，以下评分基于生物力学数据。",
        "overall_raw_text": "",
        "fallback_used": True,
        "fallback_reason": reason,
        "data_quality_hint": "poor",
        "quality_flags": ["vision_ai_unavailable_fallback"],
    }


def _clamped_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _enum_or(value: Any, allowed: set[str], fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in allowed else fallback


def _normalize_summary_key_frame_agreement(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, str] = {}
    for key in ("T", "A", "L"):
        if key in value:
            normalized[key] = _enum_or(value.get(key), VALID_SUMMARY_KEY_AGREEMENTS, "unavailable")
    return normalized or None


def _frame_analysis_from_phase_segments(
    payload: dict[str, Any],
    frame_payloads: list[FramePayload],
    window_start_sec: float,
) -> list[dict[str, Any]]:
    segments = payload.get("phase_segments")
    if not isinstance(segments, list):
        return []

    # Detect if segments use absolute timestamps (>= window_start_sec) or relative timestamps (< window_start_sec)
    first_seg_start = float(segments[0].get("start_sec", 0)) if segments else 0.0
    use_absolute = first_seg_start >= window_start_sec and window_start_sec > 0

    out: list[dict[str, Any]] = []
    for frame in frame_payloads:
        ts = frame.timestamp_sec if use_absolute else max(0.0, frame.timestamp_sec - window_start_sec)
        selected = next(
            (
                segment
                for segment in segments
                if isinstance(segment, dict)
                and isinstance(segment.get("start_sec"), (int, float))
                and isinstance(segment.get("end_sec"), (int, float))
                and float(segment["start_sec"]) <= ts <= float(segment["end_sec"])
            ),
            {},
        )
        item = {"frame_id": frame.frame_id}
        if isinstance(selected, dict):
            item.update(
                {
                    "phase": selected.get("phase"),
                    "observations": selected.get("observations") if isinstance(selected.get("observations"), dict) else {},
                    "issues": selected.get("issues") if isinstance(selected.get("issues"), list) else [],
                    "positives": selected.get("positives") if isinstance(selected.get("positives"), list) else [],
                    "confidence": selected.get("confidence", payload.get("confidence", 0.7)),
                }
            )
        out.append(item)
    return out


def normalize_vision_payload(
    payload: dict[str, Any],
    frame_payloads: list[FramePayload],
    *,
    window_start_sec: float = 0.0,
) -> dict[str, Any]:
    if "frame_analysis" not in payload and isinstance(payload.get("phase_segments"), list):
        payload = {**payload, "frame_analysis": _frame_analysis_from_phase_segments(payload, frame_payloads, window_start_sec)}

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
            if raw.get("phase_confidence") is not None:
                normalized["phase_confidence"] = _clamped_float(raw.get("phase_confidence"))
            if raw.get("key_frame_agreement") is not None:
                normalized["key_frame_agreement"] = _enum_or(
                    raw.get("key_frame_agreement"),
                    VALID_FRAME_KEY_AGREEMENTS,
                    "unavailable",
                )
            normalize_video_context_fields(normalized, raw)
        frame_analysis.append(normalized)

    raw_summary = payload.get("action_phase_summary")
    summary = raw_summary if isinstance(raw_summary, dict) else {}
    detected_phases = [
        str(phase)
        for phase in summary.get("detected_phases", [])
        if str(phase) in VALID_PHASES and str(phase) != "不可分析"
    ]

    data_quality_hint = str(payload.get("data_quality_hint", "")).strip().lower()
    if data_quality_hint not in VALID_DATA_QUALITY_HINTS:
        data_quality_hint = ""
    camera_view = _enum_or(payload.get("camera_view"), VALID_CAMERA_VIEWS, "unknown")
    camera_view_confidence = _clamped_float(payload.get("camera_view_confidence"))

    fallback_reason = str(payload.get("fallback_reason", "")).strip()

    normalized_summary: dict[str, Any] | str = {
        "detected_phases": detected_phases,
        "weakest_phase": str(summary.get("weakest_phase", "不可分析")),
        "strongest_phase": str(summary.get("strongest_phase", "不可分析")),
    }
    if payload.get("fallback_used") and isinstance(raw_summary, str) and raw_summary.strip():
        normalized_summary = raw_summary.strip()
    elif isinstance(normalized_summary, dict):
        key_agreement = _normalize_summary_key_frame_agreement(summary.get("key_frame_agreement"))
        if key_agreement is not None:
            normalized_summary["key_frame_agreement"] = key_agreement

    normalized_payload = {
        "frame_analysis": frame_analysis,
        "action_phase_summary": normalized_summary,
        "overall_raw_text": str(payload.get("overall_raw_text", "")).strip(),
        "camera_view": camera_view,
        "camera_view_confidence": camera_view_confidence,
    }
    if isinstance(payload.get("phase_segments"), list):
        normalized_payload["phase_segments"] = payload["phase_segments"]
    if data_quality_hint:
        normalized_payload["data_quality_hint"] = data_quality_hint
    if fallback_reason:
        normalized_payload["fallback_reason"] = fallback_reason
    if payload.get("fallback_used") is not None:
        normalized_payload["fallback_used"] = bool(payload.get("fallback_used"))
    if isinstance(payload.get("quality_flags"), list):
        normalized_payload["quality_flags"] = [str(flag) for flag in payload.get("quality_flags", []) if flag]
    if payload.get("pose_visibility") is not None:
        try:
            normalized_payload["pose_visibility"] = max(0.0, min(float(payload.get("pose_visibility")), 1.0))
        except (TypeError, ValueError):
            pass

    return normalized_payload


def _token_set(value: str) -> set[str]:
    compact = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    tokens = {token for token in compact.split() if token}
    if tokens:
        return tokens
    return set(value.lower())


def _is_similar_text(left: str, right: str, threshold: float = 0.7) -> bool:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return left.strip() == right.strip()
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return bool(union) and intersection / union >= threshold


def _dedupe_texts(items: list[Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        if any(_is_similar_text(text, existing) for existing in out):
            continue
        out.append(text)
    return out


def _candidate_key_frames_from_bio(bio_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(bio_data, dict):
        return {}
    candidates = bio_data.get("key_frame_candidates")
    if isinstance(candidates, dict):
        return candidates
    key_frames = bio_data.get("key_frames")
    if isinstance(key_frames, dict):
        return key_frames
    return {}


def _build_specialized_prompts(
    action_type: str,
    action_subtype: str | None,
    analysis_profile: str | None,
    profile_evidence: dict[str, Any] | None,
    bio_data: dict[str, Any] | None,
    motion_features: dict[str, Any] | list[Any] | None,
) -> tuple[str, str]:
    return build_specialized_vision_prompt(
        action_type=action_type,
        action_subtype=action_subtype,
        analysis_profile=analysis_profile,
        candidate_key_frames=_candidate_key_frames_from_bio(bio_data),
        motion_features=motion_features,
        biomechanics=bio_data,
        profile_evidence=profile_evidence,
    )


def _build_specialized_video_prompt(user_prompt: str) -> str:
    video_rules = (
        "\n\n【视频模式 - 强制要求】\n"
        "1. 你必须只输出一个 JSON 对象，不要输出任何 JSON 之外的文字、解释、markdown 或代码块标记。\n"
        "2. 即使画面模糊、角度不佳、无法判断动作，也必须输出完整 JSON，将 phase 设为“不可分析”、confidence 设为 0。\n"
        "3. 不要输出自然语言段落代替 JSON。不要在 JSON 前后添加任何说明。\n"
        "4. 按视频片段内的秒数定位关键事件，不要编造逐帧 frame_id。\n"
        "5. 优先使用 phase_segments 字段：\n"
    )
    example_good = json.dumps(
        {
            "phase_segments": [
                {"start_sec": 0.2, "end_sec": 0.6, "phase": "准备", "observations": {}, "issues": [], "positives": [], "confidence": 0.8}
            ],
            "data_quality_hint": "good",
            "camera_view": "side",
            "camera_view_confidence": 0.8,
            "action_phase_summary": {"detected_phases": ["跳跃"], "weakest_phase": "落冰", "strongest_phase": "跳跃"},
            "overall_raw_text": "2-3句总结",
        },
        ensure_ascii=False,
    )
    example_poor = json.dumps(
        {
            "phase_segments": [],
            "data_quality_hint": "poor",
            "camera_view": "unknown",
            "camera_view_confidence": 0.0,
            "action_phase_summary": {"detected_phases": [], "weakest_phase": "", "strongest_phase": ""},
            "overall_raw_text": "你对视频的观察总结",
        },
        ensure_ascii=False,
    )
    return (
        user_prompt
        + video_rules
        + example_good
        + "\n6. 如果完全无法分析，最低限度输出：\n"
        + example_poor
    )



def _choose_phase_with_votes(
    frame_votes: list[str],
    previous_phase: str,
    transitions: dict[str, set[str]] | None,
) -> str:
    counts: dict[str, int] = {}
    for phase in frame_votes:
        if phase in VALID_PHASES:
            counts[phase] = counts.get(phase, 0) + 1
    if not counts:
        return previous_phase if previous_phase in VALID_PHASES else "不可分析"

    max_count = max(counts.values())
    candidates = [phase for phase, count in counts.items() if count == max_count]
    if len(candidates) == 1:
        return candidates[0]

    allowed = transitions.get(previous_phase, set()) if transitions else set()
    for phase in candidates:
        if phase in allowed:
            return phase
    return candidates[0]


def _merge_vision_results_legacy(
    results: list[dict[str, Any]],
    frame_payloads: list[FramePayload],
    analysis_profile: str | None = None,
) -> dict[str, Any]:
    """
    Merge multiple normalized vision payloads into one self-consistent result.

    Args:
        results: Normalized vision payloads from independent LLM calls.
        frame_payloads: Canonical frame order.
        analysis_profile: Optional profile used for phase tie-breaking.

    Returns:
        Merged normalized payload with vote metadata.

    Raises:
        ValueError: When no valid result is supplied.
    """
    if not results:
        raise ValueError("No valid vision votes to merge.")

    from app.services.phase_smoother import VALID_TRANSITIONS

    transitions = VALID_TRANSITIONS.get(analysis_profile or "", {})
    provider_votes = [
        str(result.get("provider_name") or result.get("provider") or f"vote_{index + 1}")
        for index, result in enumerate(results)
    ]
    by_result: list[dict[str, dict[str, Any]]] = []
    for result in results:
        by_frame = {
            str(item.get("frame_id", "")): item
            for item in result.get("frame_analysis", [])
            if isinstance(item, dict)
        }
        by_result.append(by_frame)

    merged_frames: list[dict[str, Any]] = []
    vote_frames: dict[str, dict[str, int]] = {}
    previous_phase = "不可分析"
    for frame in frame_payloads:
        vote_items = [by_frame.get(frame.frame_id, {}) for by_frame in by_result]
        phase_votes = [str(item.get("phase", "")) for item in vote_items if isinstance(item, dict)]
        phase_counts: dict[str, int] = {}
        for phase in phase_votes:
            if phase in VALID_PHASES:
                phase_counts[phase] = phase_counts.get(phase, 0) + 1
        phase = _choose_phase_with_votes(phase_votes, previous_phase, transitions)

        observations: dict[str, str] = {}
        issues: list[Any] = []
        positives: list[Any] = []
        confidences: list[float] = []
        for item in vote_items:
            if not isinstance(item, dict):
                continue
            raw_observations = item.get("observations")
            if isinstance(raw_observations, dict):
                observations.update({str(key): str(value) for key, value in raw_observations.items()})
            issues.extend(item.get("issues", []) if isinstance(item.get("issues"), list) else [])
            positives.extend(item.get("positives", []) if isinstance(item.get("positives"), list) else [])
            try:
                confidences.append(max(0.0, min(float(item.get("confidence", 0.0)), 1.0)))
            except (TypeError, ValueError):
                continue

        merged_frames.append(
            {
                "frame_id": frame.frame_id,
                "phase": phase,
                "phase_votes": phase_counts,
                "observations": observations,
                "issues": _dedupe_texts(issues),
                "positives": _dedupe_texts(positives),
                "confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
            }
        )
        vote_frames[frame.frame_id] = phase_counts
        previous_phase = phase

    detected_phases: list[str] = []
    for frame in merged_frames:
        phase = str(frame.get("phase", ""))
        if phase in VALID_PHASES and phase != "不可分析" and phase not in detected_phases:
            detected_phases.append(phase)

    quality_flags: list[str] = []
    for result in results:
        flags = result.get("quality_flags") if isinstance(result.get("quality_flags"), list) else []
        for flag in flags:
            text = str(flag)
            if text and text not in quality_flags:
                quality_flags.append(text)
    quality_flags.append("vision_self_consistency_vote")

    data_quality_hints = [str(r.get("data_quality_hint", "")).strip() for r in results if r.get("data_quality_hint")]
    merged_quality_hint = ""
    if "poor" in data_quality_hints:
        merged_quality_hint = "poor"
    elif "partial" in data_quality_hints:
        merged_quality_hint = "partial"
    elif "good" in data_quality_hints:
        merged_quality_hint = "good"

    merged: dict[str, Any] = {
        "frame_analysis": merged_frames,
        "action_phase_summary": {
            "detected_phases": detected_phases,
            "weakest_phase": str((results[0].get("action_phase_summary") or {}).get("weakest_phase", "不可分析"))
            if isinstance(results[0].get("action_phase_summary"), dict)
            else "不可分析",
            "strongest_phase": str((results[0].get("action_phase_summary") or {}).get("strongest_phase", "不可分析"))
            if isinstance(results[0].get("action_phase_summary"), dict)
            else "不可分析",
        },
        "overall_raw_text": "\n".join(str(result.get("overall_raw_text", "")).strip() for result in results if result.get("overall_raw_text")).strip(),
        "quality_flags": quality_flags,
        "vote_metadata": {
            "n_votes_requested": len(results),
            "n_votes_valid": len(results),
            "providers": provider_votes,
            "phase_votes": vote_frames,
        },
    }
    if merged_quality_hint:
        merged["data_quality_hint"] = merged_quality_hint
    fallback_reasons = [str(r.get("fallback_reason", "")).strip() for r in results if r.get("fallback_reason")]
    if fallback_reasons:
        merged["fallback_reason"] = fallback_reasons[0]
        merged["fallback_used"] = True
    return merged


def _merge_vision_results(
    results: list[dict[str, Any]],
    frame_payloads: list[FramePayload],
    analysis_profile: str | None = None,
    bio_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Merge normalized vision payloads with weighted fusion, falling back to legacy voting.

    The returned frame payload keeps legacy-compatible fields such as phase_votes,
    averaged confidence, and aggregated issues while using weighted fusion for the
    final phase decision and audit metadata.
    """
    legacy = _merge_vision_results_legacy(results, frame_payloads, analysis_profile)
    try:
        fusion = fuse_vision_results_weighted(results, bio_data, analysis_profile)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Weighted vision fusion failed, falling back to legacy vote merge: %s", exc)
        flags = legacy.get("quality_flags") if isinstance(legacy.get("quality_flags"), list) else []
        if "vision_weighted_fusion_fallback_to_vote" not in flags:
            flags.append("vision_weighted_fusion_fallback_to_vote")
        legacy["quality_flags"] = flags
        return legacy

    legacy_frames = {
        str(frame.get("frame_id", "")): frame
        for frame in legacy.get("frame_analysis", [])
        if isinstance(frame, dict)
    }
    fused_frames: list[dict[str, Any]] = []
    for frame in fusion.get("final_frame_analysis", []):
        if not isinstance(frame, dict):
            continue
        frame_id = str(frame.get("frame_id", ""))
        legacy_frame = legacy_frames.get(frame_id, {})
        fused_frames.append(
            {
                **legacy_frame,
                "frame_id": frame_id,
                "phase": frame.get("phase", legacy_frame.get("phase", "ä¸å¯åˆ†æž")),
                "phase_votes": legacy_frame.get("phase_votes", frame.get("phase_votes", {})),
                "phase_scores": frame.get("phase_scores", {}),
                "fusion_evidence": frame.get("fusion_evidence", {}),
                "confidence": legacy_frame.get("confidence", frame.get("confidence", 0.0)),
            }
        )

    if not fused_frames:
        return legacy

    quality_flags = legacy.get("quality_flags") if isinstance(legacy.get("quality_flags"), list) else []
    if "vision_weighted_fusion" not in quality_flags:
        quality_flags.append("vision_weighted_fusion")

    vote_metadata = legacy.get("vote_metadata") if isinstance(legacy.get("vote_metadata"), dict) else {}
    vote_metadata = {
        **vote_metadata,
        "fusion_version": fusion.get("fusion_version"),
        "conflict_level": fusion.get("conflict_level"),
    }

    return {
        **legacy,
        "frame_analysis": fused_frames,
        "action_phase_summary": fusion.get("action_phase_summary", legacy.get("action_phase_summary")),
        "quality_flags": quality_flags,
        "vote_metadata": vote_metadata,
        "fusion_version": fusion.get("fusion_version"),
        "fusion_decisions": fusion.get("fusion_decisions", []),
        "fusion_model_results": fusion.get("model_results", []),
        "conflict_level": fusion.get("conflict_level", "none"),
    }


def _attach_quality_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    return apply_low_quality_policy(
        payload,
        data_quality_hint=payload.get("data_quality_hint"),
        camera_view=payload.get("camera_view"),
        pose_visibility=payload.get("pose_visibility"),
    )


def _extract_json_from_raw(raw_text: str) -> dict[str, Any] | None:
    """Aggressively extract a JSON object from raw LLM response text.

    Handles cases where the model wraps JSON in markdown, adds preamble text,
    or returns a partially valid JSON structure.
    """
    if not raw_text or not raw_text.strip():
        return None

    cleaned = clean_json_text(raw_text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    import re

    json_block_pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
    match = re.search(json_block_pattern, raw_text, re.IGNORECASE)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    brace_starts = [i for i, ch in enumerate(raw_text) if ch == "{"]
    for start in brace_starts:
        depth = 0
        for end in range(start, len(raw_text)):
            if raw_text[end] == "{":
                depth += 1
            elif raw_text[end] == "}":
                depth -= 1
            if depth == 0:
                candidate = raw_text[start : end + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    break
    return None


def _build_fallback_from_text(raw_text: str, frame_payloads: list[FramePayload]) -> dict[str, Any]:
    """Build a minimal structured payload from raw text when JSON extraction fails.

    Preserves the model's textual observations as overall_raw_text and marks
    all frames as not analyzable with zero confidence.
    """
    text = raw_text.strip()
    if len(text) > 2000:
        text = text[:2000] + "..."

    return {
        "frame_analysis": [_fallback_frame(frame.frame_id) for frame in frame_payloads],
        "action_phase_summary": {
            "detected_phases": [],
            "weakest_phase": "",
            "strongest_phase": "",
        },
        "overall_raw_text": text,
        "data_quality_hint": "poor",
        "camera_view": "unknown",
        "camera_view_confidence": 0.0,
        "fallback_used": True,
        "fallback_reason": AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL.value,
        "quality_flags": ["vision_raw_text_fallback"],
    }


async def _single_frames_vision_call(
    provider: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    frame_payloads: list[FramePayload],
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    content: list[dict[str, object]] = [{"type": "text", "text": user_prompt}]
    for frame in frame_payloads:
        content.append({"type": "text", "text": f"帧编号：{frame.frame_id}"})
        content.append({"type": "image_url", "image_url": {"url": frame.data_url}})

    raw_content = await request_text_completion(
        provider,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=90.0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    )
    cleaned = clean_json_text(raw_content)
    parsed: dict[str, Any] | None = None
    json_extract_method = "direct"

    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            parsed = None
            json_extract_method = "direct_non_dict"
    except json.JSONDecodeError:
        parsed = None
        json_extract_method = "direct_parse_failed"

    if parsed is None:
        extracted = _extract_json_from_raw(raw_content)
        if isinstance(extracted, dict):
            parsed = extracted
            json_extract_method = "aggressive_extract"
            logger.info("Frame vision returned non-standard JSON; recovered via aggressive extraction.")

    if parsed is None:
        logger.warning("Frame vision returned unparseable response; using text fallback. raw: %s", cleaned[:300])
        parsed = _build_fallback_from_text(raw_content or "", frame_payloads)
        json_extract_method = "text_fallback"

    normalized = normalize_vision_payload(parsed, frame_payloads)
    normalized["_raw_response"] = raw_content[:5000] if raw_content else ""
    normalized["_json_extract_method"] = json_extract_method
    return normalized


async def analyze_frames(
    action_type: str,
    frame_payloads: list[FramePayload],
    skater_id: str | None = None,
    *,
    action_subtype: str | None = None,
    analysis_profile: str | None = None,
    profile_evidence: dict[str, Any] | None = None,
    bio_data: dict[str, Any] | None = None,
    motion_features: dict[str, Any] | list[Any] | None = None,
    mode: Literal["frames", "video"] = "video",
    clip_path: Path | None = None,
    window_start_sec: float = 0.0,
    n_votes: int = DEFAULT_VISION_N_VOTES,
    vote_temperature: float = 0.2,
) -> dict[str, Any]:
    """
    Analyze sampled frames with the configured vision provider.

    Args:
        action_type: User-facing action type.
        frame_payloads: Sampled frame images encoded as data URLs.
        skater_id: Optional skater id for memory context.
        action_subtype: Optional jump subtype.
        analysis_profile: Inferred profile such as jump/spin/spiral.
        profile_evidence: Rule evidence used by profile inference.
        bio_data: Optional biomechanics payload used as prompt evidence.
        motion_features: Optional motion sampling/features payload used as prompt evidence.
        mode: Prefer native short-clip video analysis or legacy frame analysis.
        clip_path: Optional action-window mp4 clip for video mode.
        window_start_sec: Source-video second corresponding to clip-relative 0.0.
        n_votes: Number of independent frame-mode votes. Temporarily defaults to 2.
        vote_temperature: Sampling temperature for vote diversity.

    Returns:
        Normalized vision payload. If AI is unavailable, returns a minimal fallback payload.

    Raises:
        No provider exception is intentionally propagated; failures are logged and returned as fallback data.
    """
    try:
        try:
            providers = await get_vision_providers()
        except Exception:  # noqa: BLE001
            providers = [await get_active_provider("vision")]
        provider = providers[0]
        memory_context = await build_memory_context(skater_id)
    except Exception as exc:  # noqa: BLE001
        failure = classify_ai_failure(exc).code.value
        logger.warning("Vision provider unavailable, using fallback: %s", exc)
        return _attach_quality_diagnostics(normalize_vision_payload(_fallback_unavailable_payload(frame_payloads, failure), frame_payloads))

    system_prompt = VISION_SYSTEM_PROMPT if not memory_context else f"{VISION_SYSTEM_PROMPT}\n\n{memory_context}"
    max_tokens = min(8000, 400 + len(frame_payloads) * 250)

    evidence_text = json.dumps(profile_evidence or {}, ensure_ascii=False)
    jump_evidence_instruction = (
        "JUMP_SUBTYPE_EVIDENCE: when profile is jump, prioritize profile_evidence.jump_subtype_evidence for subtype clues. "
        "toe_pick_pulse indicates toe-assisted jumps; feet_together_at_takeoff supports Loop; "
        "free_leg_swing_amplitude supports Salchow; approach_direction=forward supports Axel; "
        "pre_takeoff_edge_score near 0 supports Lutz outside edge, near 1 supports Flip inside edge. "
        "If evidence confidence is low or conflicts with image evidence, state the uncertainty explicitly.\n"
    )
    profile_key = (analysis_profile or "jump").strip().lower()
    profile_hint = PROFILE_HINTS.get(profile_key, PROFILE_HINTS["jump"])
    jump_chars = get_jump_characteristics(action_subtype)
    user_prompt = (
        f"分析以下【{action_type}】动作帧序列（共 {len(frame_payloads)} 帧，按时间顺序排列）。\n"
        f"动作子类型：{action_subtype or '未指定'}\n"
        f"分析 profile：{analysis_profile or 'unknown'}\n"
        f"{profile_hint}\n"
        f"规则证据：{evidence_text}\n"
        f"{jump_evidence_instruction}"
        "重要约束：如果是燕式滑行/螺旋线，不要误判为跳跃，除非存在清晰的起跳、腾空、落冰证据。\n\n"
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
        "每帧的 issues 和 positives 各不超过 2 条，每条不超过 30 字。\n"
        "必须只输出 JSON，禁止任何解释文字。"
    )
    if jump_chars and profile_key == "jump":
        user_prompt += (
            "\n跳跃类型专项信息：\n"
            f"  起跳刃型：{jump_chars['takeoff_edge']}\n"
            f"  方向特征：{jump_chars['direction']}\n"
            f"  重点检查：{jump_chars['key_check']}\n"
            f"  圈数说明：{jump_chars['rotation_note']}\n"
        )

    system_prompt, user_prompt = _build_specialized_prompts(
        action_type,
        action_subtype,
        analysis_profile,
        profile_evidence,
        bio_data,
        motion_features,
    )
    if memory_context:
        system_prompt = f"{system_prompt}\n\n{memory_context}"
    video_prompt = _build_specialized_video_prompt(user_prompt)

    if mode == "video" and clip_path is not None:
        async def _single_video_call(video_provider: Any) -> dict[str, Any]:
            if getattr(video_provider, "provider", "") == "qwen":
                raw_content = await request_dashscope_video_completion(
                    video_provider,
                    video_path=clip_path,
                    system_prompt=system_prompt,
                    user_prompt=video_prompt,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    timeout=180.0,
                )
            elif getattr(video_provider, "provider", "") == "doubao":
                raw_content = await request_doubao_vision_completion(
                    video_provider,
                    video_path=clip_path,
                    system_prompt=system_prompt,
                    user_prompt=video_prompt,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    timeout=180.0,
                )
            elif getattr(video_provider, "provider", "") == "mimo":
                raw_content = await request_mimo_video_completion(
                    video_provider,
                    video_path=clip_path,
                    system_prompt=system_prompt,
                    user_prompt=video_prompt,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    timeout=180.0,
                )
            else:
                raise RuntimeError(f"Unsupported native video provider: {getattr(video_provider, 'provider', '')}")

            provider_name = str(getattr(video_provider, "name", getattr(video_provider, "provider", "unknown")))
            provider_id = str(getattr(video_provider, "provider", "unknown"))

            parsed: dict[str, Any] | None = None
            json_extract_method = "direct"

            cleaned = clean_json_text(raw_content)
            try:
                parsed = json.loads(cleaned)
                if not isinstance(parsed, dict):
                    parsed = None
                    json_extract_method = "direct_non_dict"
            except json.JSONDecodeError:
                parsed = None
                json_extract_method = "direct_parse_failed"

            if parsed is None:
                extracted = _extract_json_from_raw(raw_content)
                if isinstance(extracted, dict):
                    parsed = extracted
                    json_extract_method = "aggressive_extract"
                    logger.info(
                        "Video provider %s returned non-standard JSON; recovered via aggressive extraction.",
                        provider_name,
                    )

            if parsed is None:
                logger.warning(
                    "Video provider %s returned unparseable response (len=%d); using text fallback.",
                    provider_name,
                    len(raw_content or ""),
                )
                parsed = _build_fallback_from_text(raw_content or "", frame_payloads)
                json_extract_method = "text_fallback"

            normalized = normalize_vision_payload(parsed, frame_payloads, window_start_sec=window_start_sec)
            normalized["provider"] = provider_id
            normalized["provider_name"] = provider_name
            normalized["_raw_response"] = raw_content[:5000] if raw_content else ""
            normalized["_json_extract_method"] = json_extract_method
            return normalized

        video_vote_results = await asyncio.gather(
            *[_single_video_call(candidate) for candidate in providers],
            return_exceptions=True,
        )
        video_votes: list[dict[str, Any]] = []
        for result in video_vote_results:
            if isinstance(result, dict):
                video_votes.append(result)
            else:
                logger.warning("Vision native video provider failed, continuing with remaining slots: %s", result)

        if len(video_votes) == 1:
            normalized = _attach_quality_diagnostics(video_votes[0])
            flags = normalized.get("quality_flags") if isinstance(normalized.get("quality_flags"), list) else []
            normalized["quality_flags"] = flags
            normalized["vision_mode"] = "video"
            normalized["vote_metadata"] = {
                "n_votes_requested": len(providers),
                "n_votes_valid": 1,
                "providers": [str(normalized.get("provider_name") or normalized.get("provider") or "vision")],
                "phase_votes": {
                    str(frame.get("frame_id", "")): {str(frame.get("phase", "ä¸å¯åˆ†æž")): 1}
                    for frame in normalized.get("frame_analysis", [])
                    if isinstance(frame, dict)
                },
            }
            return normalized
        if len(video_votes) > 1:
            normalized = _attach_quality_diagnostics(_merge_vision_results(video_votes, frame_payloads, analysis_profile, bio_data))
            normalized["vote_metadata"]["n_votes_requested"] = len(providers)
            normalized["vision_mode"] = "video_voted"
            normalized["_raw_responses"] = [
                {
                    "provider": str(v.get("provider_name", "")),
                    "raw": v.get("_raw_response", ""),
                    "extract_method": v.get("_json_extract_method", "unknown"),
                }
                for v in video_votes
                if isinstance(v, dict)
            ]
            return normalized

        logger.warning("All vision native video providers failed, falling back to frames.")

    vote_count = len(providers) if len(providers) > 1 else max(1, min(int(n_votes), 5))
    requested_providers = providers if len(providers) > 1 else [provider for _ in range(vote_count)]
    vote_tasks = [
        _single_frames_vision_call(
            candidate,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            frame_payloads=frame_payloads,
            max_tokens=max_tokens,
            temperature=vote_temperature if vote_count > 1 else 0.1,
        )
        for candidate in requested_providers
    ]
    vote_results = await asyncio.gather(*vote_tasks, return_exceptions=True)
    valid_votes: list[dict[str, Any]] = []
    for candidate, result in zip(requested_providers, vote_results, strict=False):
        if isinstance(result, dict):
            result["provider"] = str(getattr(candidate, "provider", "unknown"))
            result["provider_name"] = str(getattr(candidate, "name", result["provider"]))
            valid_votes.append(result)
    if not valid_votes:
        first_error = next((result for result in vote_results if isinstance(result, Exception)), RuntimeError("no votes"))
        logger.warning("Vision AI vote requests all failed, using fallback: %s", first_error)
        reason = (
            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL.value
            if isinstance(first_error, json.JSONDecodeError)
            else classify_ai_failure(first_error).code.value
        )
        return _attach_quality_diagnostics(
            normalize_vision_payload(
                _fallback_unavailable_payload(frame_payloads, reason),
                frame_payloads,
            )
        )

    if len(valid_votes) == 1:
        normalized = _attach_quality_diagnostics(valid_votes[0])
        normalized["vote_metadata"] = {
            "n_votes_requested": vote_count,
            "n_votes_valid": 1,
            "providers": [str(normalized.get("provider_name") or normalized.get("provider") or "vision")],
            "phase_votes": {
                str(frame.get("frame_id", "")): {str(frame.get("phase", "不可分析")): 1}
                for frame in normalized.get("frame_analysis", [])
                if isinstance(frame, dict)
            },
        }
    else:
        normalized = _attach_quality_diagnostics(_merge_vision_results(valid_votes, frame_payloads, analysis_profile, bio_data))
        normalized["vote_metadata"]["n_votes_requested"] = vote_count
        normalized["_raw_responses"] = [
            {
                "provider": str(v.get("provider_name", "")),
                "raw": v.get("_raw_response", ""),
                "extract_method": v.get("_json_extract_method", "unknown"),
            }
            for v in valid_votes
            if isinstance(v, dict)
        ]
    if mode == "video" and clip_path is not None:
        flags = normalized.get("quality_flags") if isinstance(normalized.get("quality_flags"), list) else []
        if "vision_fallback_to_frames" not in flags:
            flags.append("vision_fallback_to_frames")
        normalized["quality_flags"] = flags
        normalized["vision_mode"] = "frames"
    elif vote_count > 1:
        normalized["vision_mode"] = "frames_provider_voted" if len(providers) > 1 else "frames_voted"
    return normalized
