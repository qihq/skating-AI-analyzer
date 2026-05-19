from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analysis_errors import AnalysisErrorCode, classify_ai_failure
from app.services.providers import ActiveProviderConfig, get_active_provider, request_dashscope_video_completion


SCHEMA_VERSION = "video_temporal_v1"
DEFAULT_MODEL = "qwen3.6-plus"
VIDEO_TEMPORAL_TEMPERATURE = 0.0
VIDEO_TEMPORAL_MAX_TOKENS = 1600
VIDEO_TEMPORAL_TIMEOUT_SECONDS = 180.0
VALID_FALLBACK_RECOMMENDATIONS = {
    "use_video_timestamps",
    "use_skeleton_fallback",
    "use_sampled_frames",
    "use_existing_skeleton_timestamps",
    "manual_review",
}
VALID_DATA_QUALITY_HINTS = {"good", "partial", "poor"}

JUMP_PHASE_CODES = {"approach", "preparation", "takeoff", "air", "landing", "glide_out"}
SPIN_PHASE_CODES = {"spin_entry", "spin_main", "spin_exit"}
STEP_PHASE_CODES = {"step_sequence"}
SPIRAL_PHASE_CODES = {"spiral_entry", "spiral_hold", "spiral_exit"}
ALL_PHASE_CODES = JUMP_PHASE_CODES | SPIN_PHASE_CODES | STEP_PHASE_CODES | SPIRAL_PHASE_CODES

PHASE_LABELS = {
    "approach": "助滑",
    "preparation": "准备",
    "takeoff": "起跳",
    "air": "腾空",
    "landing": "落冰",
    "glide_out": "滑出",
    "spin_entry": "入转",
    "spin_main": "旋转中",
    "spin_exit": "出转",
    "step_sequence": "步法",
    "spiral_entry": "螺旋线进入",
    "spiral_hold": "螺旋线保持",
    "spiral_exit": "螺旋线退出",
}

PHASE_ALIASES = {
    "approach": "approach",
    "entry": "approach",
    "助滑": "approach",
    "进入": "approach",
    "preparation": "preparation",
    "prep": "preparation",
    "准备": "preparation",
    "takeoff": "takeoff",
    "take_off": "takeoff",
    "t": "takeoff",
    "起跳": "takeoff",
    "离冰": "takeoff",
    "air": "air",
    "flight": "air",
    "apex": "air",
    "a": "air",
    "腾空": "air",
    "空中": "air",
    "landing": "landing",
    "l": "landing",
    "落冰": "landing",
    "触冰": "landing",
    "glide_out": "glide_out",
    "exit": "glide_out",
    "滑出": "glide_out",
    "spin_entry": "spin_entry",
    "旋转入": "spin_entry",
    "入转": "spin_entry",
    "spin_main": "spin_main",
    "spin": "spin_main",
    "旋转中": "spin_main",
    "旋转": "spin_main",
    "spin_exit": "spin_exit",
    "旋转出": "spin_exit",
    "出转": "spin_exit",
    "step_sequence": "step_sequence",
    "step": "step_sequence",
    "steps": "step_sequence",
    "步法": "step_sequence",
    "步法序列": "step_sequence",
    "spiral_entry": "spiral_entry",
    "螺旋线进入": "spiral_entry",
    "spiral_hold": "spiral_hold",
    "spiral": "spiral_hold",
    "螺旋线": "spiral_hold",
    "燕式": "spiral_hold",
    "spiral_exit": "spiral_exit",
    "螺旋线退出": "spiral_exit",
}

ACTION_FAMILIES = {"jump", "spin", "step", "spiral", "unknown"}
CAMERA_VIEWS = {"front", "side", "diagonal_front", "diagonal_back", "rear", "unknown"}
KEY_MOMENT_KEYS = ("T_takeoff_sec", "A_air_sec", "L_landing_sec")
PHASE_KEY_MOMENTS = {
    "takeoff": "T_takeoff_sec",
    "air": "A_air_sec",
    "landing": "L_landing_sec",
}
SPIN_RESOLVER_PHASES = ("spin_entry", "spin_main", "spin_exit")
SPIRAL_RESOLVER_PHASES = ("spiral_entry", "spiral_hold", "spiral_exit")
MAX_RESOLVED_KEYFRAMES = 12
SKELETON_ANCHOR_CONFIDENCE = 0.65
SKELETON_FALLBACK_CONFIDENCE = 0.65
MOTION_SNAP_TOLERANCE_SECONDS = 0.18
FALLBACK_MOTION_WINDOW_SECONDS = 0.30
MOTION_PEAK_PHASES = {"takeoff", "landing"}
SEMANTIC_ORDER_MIN_GAP_SECONDS = 0.02


def _configured_max_resolved_keyframes() -> int:
    raw = os.getenv("VIDEO_TEMPORAL_MAX_FRAMES", str(MAX_RESOLVED_KEYFRAMES)).strip()
    try:
        value = int(raw)
    except ValueError:
        return MAX_RESOLVED_KEYFRAMES
    return max(1, min(value, MAX_RESOLVED_KEYFRAMES))


def _semantic_key_from_record(record: dict[str, Any]) -> str | None:
    key_moment = str(record.get("key_moment") or "")
    if key_moment.startswith("T_"):
        return "T"
    if key_moment.startswith("A_"):
        return "A"
    if key_moment.startswith("L_"):
        return "L"
    phase_code = str(record.get("phase_code") or "")
    if phase_code == "takeoff":
        return "T"
    if phase_code == "air":
        return "A"
    if phase_code == "landing":
        return "L"
    return None


def semantic_keyframes_are_reliable(resolved_keyframes: dict[str, Any] | None) -> bool:
    if not isinstance(resolved_keyframes, dict):
        return False
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list) or not selected:
        return False
    quality_flags = [flag for flag in (resolved_keyframes.get("quality_flags") or []) if isinstance(flag, str)]
    if any(
        flag
        in {
            "semantic_frame_extract_failed",
            "semantic_keyframe_refinement_order_rejected",
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
        }
        for flag in quality_flags
    ):
        return False
    source = resolved_keyframes.get("source")
    anchors: dict[str, float] = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _semantic_key_from_record(item)
        timestamp = _to_float(item.get("timestamp"))
        if key in {"T", "A", "L"} and timestamp is not None:
            anchors[key] = timestamp
    if {"T", "A", "L"}.issubset(anchors) and not (
        anchors["T"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["A"]
        and anchors["A"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["L"]
    ):
        return False
    if source in {"video_ai_refined", "blended"}:
        return True
    if source != "skeleton_fallback":
        return False

    anchors = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _semantic_key_from_record(item)
        timestamp = _to_float(item.get("timestamp"))
        confidence = _candidate_confidence(item)
        if key in {"T", "A", "L"} and timestamp is not None and confidence >= SKELETON_FALLBACK_CONFIDENCE:
            anchors[key] = timestamp
    return (
        {"T", "A", "L"}.issubset(anchors)
        and anchors["T"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["A"]
        and anchors["A"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["L"]
    )


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    numeric = _to_float(value)
    if numeric is None:
        numeric = default
    return round(max(0.0, min(1.0, numeric)), 3)


def _optional_time(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return round(numeric, 3)


def _string(value: Any, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_flags(*sources: Any) -> list[str]:
    flags: list[str] = []
    for source in sources:
        if not isinstance(source, list):
            continue
        for flag in source:
            text = str(flag).strip()
            if text and text not in flags:
                flags.append(text)
    return flags


def _parse_raw_payload(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    if isinstance(raw, dict):
        return raw, []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None, ["video_temporal_invalid_json"]
        if isinstance(parsed, dict):
            return parsed, []
        return None, ["video_temporal_payload_not_object"]
    return None, ["video_temporal_payload_not_object"]


def _fallback_video_temporal_payload(
    *,
    provider: str,
    model: str,
    reason: str,
    quality_flags: list[str],
    detail: str = "",
) -> dict[str, Any]:
    flags = _merge_flags(quality_flags)
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": _string(provider, "unknown"),
        "model": _string(model, DEFAULT_MODEL),
        "valid": False,
        "action_confirmation": {
            "action_family": "unknown",
            "confirmed_action": "不可分析",
            "jump_type": "",
            "confidence": 0.0,
            "notes": detail,
        },
        "phase_segments": [],
        "key_moments": {key: None for key in KEY_MOMENT_KEYS},
        "macro_assessment": _normalize_macro_assessment({}),
        "overall_impression": "",
        "camera_view": "unknown",
        "data_quality_hint": "poor",
        "confidence": 0.0,
        "fallback_recommendation": "use_existing_skeleton_timestamps",
        "fallback_reason": reason,
        "quality_flags": flags,
        "validation": {
            "valid": False,
            "errors": flags,
            "warnings": [],
        },
    }


def _normalize_action_family(value: Any) -> str:
    text = _string(value).lower()
    aliases = {
        "jump": "jump",
        "jumps": "jump",
        "跳跃": "jump",
        "spin": "spin",
        "spins": "spin",
        "旋转": "spin",
        "step": "step",
        "steps": "step",
        "step_sequence": "step",
        "步法": "step",
        "spiral": "spiral",
        "spirals": "spiral",
        "spiral_line": "spiral",
        "螺旋线": "spiral",
        "燕式": "spiral",
    }
    return aliases.get(text, "unknown")


def _normalize_phase_code(value: Any) -> str:
    text = _string(value)
    if not text:
        return "unknown"
    compact = text.strip().lower().replace(" ", "_").replace("-", "_")
    return PHASE_ALIASES.get(text, PHASE_ALIASES.get(compact, compact if compact in ALL_PHASE_CODES else "unknown"))


def _phase_codes_for_family(action_family: str) -> set[str]:
    if action_family == "jump":
        return JUMP_PHASE_CODES
    if action_family == "spin":
        return SPIN_PHASE_CODES
    if action_family == "step":
        return STEP_PHASE_CODES
    if action_family == "spiral":
        return SPIRAL_PHASE_CODES
    return ALL_PHASE_CODES


def _infer_action_family(action_confirmation: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    family = _normalize_action_family(action_confirmation.get("action_family"))
    if family != "unknown":
        return family
    confirmed = _string(action_confirmation.get("confirmed_action") or action_confirmation.get("jump_type")).lower()
    if confirmed in {"axel", "lutz", "flip", "loop", "salchow", "toe loop", "toe_loop"}:
        return "jump"
    codes = {segment.get("phase_code") for segment in segments if isinstance(segment, dict)}
    if codes & JUMP_PHASE_CODES:
        return "jump"
    if codes & SPIN_PHASE_CODES:
        return "spin"
    if codes & SPIRAL_PHASE_CODES:
        return "spiral"
    if codes & STEP_PHASE_CODES:
        return "step"
    return "unknown"


def _normalize_action_confirmation(raw: dict[str, Any]) -> dict[str, Any]:
    action = raw.get("action_confirmation")
    if not isinstance(action, dict):
        action = {}
    return {
        "action_family": _normalize_action_family(action.get("action_family") or raw.get("action_family")),
        "confirmed_action": _string(action.get("confirmed_action") or raw.get("confirmed_action") or "不可分析"),
        "jump_type": _string(action.get("jump_type") or raw.get("jump_type") or ""),
        "confidence": _clamp_confidence(action.get("confidence", raw.get("confidence", 0.0))),
        "notes": _string(action.get("notes")),
    }


def _normalize_phase_segments(raw: dict[str, Any], flags: list[str]) -> list[dict[str, Any]]:
    segments = raw.get("phase_segments")
    if not isinstance(segments, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            flags.append(f"video_temporal_phase_{index}_not_object")
            continue
        phase_code = _normalize_phase_code(segment.get("phase_code") or segment.get("phase") or segment.get("phase_label"))
        if phase_code == "unknown":
            flags.append(f"video_temporal_phase_{index}_unknown_code")
        normalized.append(
            {
                "phase_code": phase_code,
                "phase_label": _string(segment.get("phase_label"), PHASE_LABELS.get(phase_code, "不可分析")),
                "time_start": _optional_time(segment.get("time_start", segment.get("start_sec"))),
                "time_end": _optional_time(segment.get("time_end", segment.get("end_sec"))),
                "key_frame_hint": _optional_time(
                    segment.get("key_frame_hint", segment.get("keyframe_hint", segment.get("representative_sec")))
                ),
                "confidence": _clamp_confidence(segment.get("confidence", raw.get("confidence", 0.0))),
                "observations": _list_of_strings(segment.get("observations")),
                "issues": _list_of_strings(segment.get("issues")),
            }
        )
    return normalized


def _normalize_key_moments(raw: dict[str, Any]) -> dict[str, float | None]:
    source = raw.get("key_moments")
    if not isinstance(source, dict):
        source = {}
    aliases = {
        "T_takeoff_sec": ("T_takeoff_sec", "T", "takeoff_sec", "t_takeoff_sec"),
        "A_air_sec": ("A_air_sec", "A", "air_sec", "apex_sec", "a_air_sec"),
        "L_landing_sec": ("L_landing_sec", "L", "landing_sec", "l_landing_sec"),
    }
    normalized: dict[str, float | None] = {}
    for output_key, input_keys in aliases.items():
        value = None
        for input_key in input_keys:
            if input_key in source:
                value = source.get(input_key)
                break
            if input_key in raw:
                value = raw.get(input_key)
                break
        normalized[output_key] = _optional_time(value)
    return normalized


def _normalize_macro_assessment(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw.get("macro_assessment")
    if not isinstance(source, dict):
        source = {}
    return {
        "timing_rhythm": _string(source.get("timing_rhythm")),
        "speed_flow": _string(source.get("speed_flow")),
        "axis_overall": _string(source.get("axis_overall")),
        "entry_quality": _string(source.get("entry_quality")),
        "exit_or_landing_quality": _string(source.get("exit_or_landing_quality")),
        "top_strengths": _list_of_strings(source.get("top_strengths")),
        "top_issues": _list_of_strings(source.get("top_issues")),
    }


def build_video_temporal_prompts(
    *,
    action_type: str,
    action_subtype: str | None = None,
    video_duration_sec: float | None = None,
    source_fps: float | None = None,
    skater_level: str = "儿童初级 / Free Skate 1",
    model: str = DEFAULT_MODEL,
) -> tuple[str, str]:
    """
    Build the Qwen 3.6 Plus video-temporal prompts for semantic phase localization.
    """
    duration_text = "unknown" if video_duration_sec is None else f"{max(0.0, float(video_duration_sec)):.2f}"
    fps_text = "unknown" if source_fps is None else f"{max(0.0, float(source_fps)):.2f}"
    model_text = DEFAULT_MODEL if not _string(model) or model in {"qwen-vl-max-latest"} else _string(model)

    system_prompt = (
        "你是一名专业花样滑冰技术分析师，熟悉儿童初级训练、ISU 技术要素、基础运动生物力学和视频时间定位。\n\n"
        "你的任务是直接分析完整动作视频，输出动作阶段的时间区间、动作类型确认、宏观技术评价和整体印象。\n\n"
        "要求：\n"
        "1. 只输出一个合法 JSON 对象，不要输出 Markdown、解释或代码块。\n"
        "2. 所有时间戳单位为秒，基于源视频从 0.000 秒开始的播放时间轴。\n"
        "3. 如果无法判断，使用 null 或 “不可分析”，不要编造。\n"
        "4. 目标学员为 5-8 岁儿童，评价要使用儿童训练标准，不使用成人竞技标准。\n"
        "5. 你只负责视频宏观时序和整体质量判断，不输出骨架测量数值。\n"
        "6. 对高速跳跃动作，给出阶段区间，不要假装能锁定单个绝对精确帧。\n"
        "7. 时间保留两位小数，尽量精确到 0.1 秒以内；T/A/L 关键时刻误差应尽量控制在 0.2 秒以内。\n"
        "8. T = 最后一只脚离冰的瞬间，A = 身体重心达到最高点的瞬间，L = 冰刀首次接触冰面的瞬间。"
    )

    schema_hint = {
        "schema_version": SCHEMA_VERSION,
        "action_confirmation": {
            "action_family": "jump|spin|step|spiral|unknown",
            "confirmed_action": "Axel|Lutz|Flip|Loop|Salchow|Toe Loop|spin|step_sequence|spiral|不可分析",
            "jump_type": "Axel|Lutz|Flip|Loop|Salchow|Toe Loop|",
            "confidence": 0.0,
            "notes": "",
        },
        "phase_segments": [
            {
                "phase_code": "approach|preparation|takeoff|air|landing|glide_out|spin_entry|spin_main|spin_exit|step_sequence|spiral_entry|spiral_hold|spiral_exit",
                "phase_label": "起跳",
                "time_start": 0.0,
                "time_end": 0.0,
                "key_frame_hint": 0.0,
                "confidence": 0.0,
                "observations": [],
                "issues": [],
            }
        ],
        "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
        "macro_assessment": {
            "timing_rhythm": "",
            "speed_flow": "",
            "axis_overall": "",
            "entry_quality": "",
            "exit_or_landing_quality": "",
            "top_strengths": [],
            "top_issues": [],
        },
        "overall_impression": "",
        "camera_view": "front|side|diagonal_front|diagonal_back|rear|unknown",
        "data_quality_hint": "good|partial|poor",
        "confidence": 0.0,
        "fallback_recommendation": "use_video_timestamps|use_sampled_frames|manual_review",
        "quality_flags": [],
    }

    user_prompt = (
        "请分析这段花样滑冰训练视频。\n\n"
        "已知信息：\n"
        f"- action_type_hint: {_string(action_type, 'unknown')}\n"
        f"- action_subtype_hint: {_string(action_subtype, 'unknown')}\n"
        f"- skater_level: {skater_level}\n"
        f"- video_duration_sec: {duration_text}\n"
        f"- source_fps: {fps_text}\n"
        f"- model: {model_text}\n\n"
        "需要覆盖的动作类型：\n"
        "- 跳跃：Lutz, Flip, Loop, Salchow, Toe Loop, Axel\n"
        "- 非跳跃：旋转、步法、螺旋线\n\n"
        "请完成：\n"
        "1. 确认实际动作类型和子类型。\n"
        "2. 输出每个动作阶段的 time_start/time_end。\n"
        "3. 对每个关键阶段输出 key_frame_hint，表示该阶段最有代表性的时间点。\n"
        "4. 对跳跃给出 T/A/L 建议时间：T = 最后一只脚离冰的瞬间，A = 身体重心达到最高点的瞬间，L = 冰刀首次接触冰面的瞬间。\n"
        "5. 输出宏观技术评价：节奏、速度、轴心、入跳/入转、落冰/出转/滑出、整体流畅度。\n"
        "6. 输出整体印象和置信度。\n"
        "7. 如果主滑行者不清楚、多人遮挡、画面太远或动作不完整，请降低 confidence 并说明原因。\n\n"
        "只输出 JSON，schema_version 必须为 \"video_temporal_v1\"。\n"
        f"简洁 JSON schema 示例：{json.dumps(schema_hint, ensure_ascii=False, separators=(',', ':'))}"
    )
    return system_prompt, user_prompt


def normalize_video_temporal_payload(raw: Any, provider: str, model: str) -> dict[str, Any]:
    """
    Normalize model output into the video_temporal_v1 contract.

    The function is intentionally forgiving: malformed inputs return a diagnostic
    payload with valid=False instead of raising, so callers can fall back to the
    existing sampled-frame pipeline.
    """
    parsed, parse_flags = _parse_raw_payload(raw)
    if parsed is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "provider": _string(provider, "unknown"),
            "model": _string(model, DEFAULT_MODEL),
            "valid": False,
            "action_confirmation": {
                "action_family": "unknown",
                "confirmed_action": "不可分析",
                "jump_type": "",
                "confidence": 0.0,
                "notes": "",
            },
            "phase_segments": [],
            "key_moments": {key: None for key in KEY_MOMENT_KEYS},
            "macro_assessment": _normalize_macro_assessment({}),
            "overall_impression": "",
            "camera_view": "unknown",
            "data_quality_hint": "poor",
            "confidence": 0.0,
            "fallback_recommendation": "use_sampled_frames",
            "quality_flags": parse_flags,
            "validation": {
                "valid": False,
                "errors": parse_flags,
                "warnings": [],
            },
        }

    flags = _merge_flags(parsed.get("quality_flags"), parse_flags)
    action_confirmation = _normalize_action_confirmation(parsed)
    phase_segments = _normalize_phase_segments(parsed, flags)
    action_confirmation["action_family"] = _infer_action_family(action_confirmation, phase_segments)

    data_quality_hint = _string(parsed.get("data_quality_hint"), "partial").lower()
    if data_quality_hint not in VALID_DATA_QUALITY_HINTS:
        data_quality_hint = "partial"
        flags.append("video_temporal_invalid_data_quality_hint")

    camera_view = _string(parsed.get("camera_view"), "unknown")
    if camera_view not in CAMERA_VIEWS:
        camera_view = "unknown"
        flags.append("video_temporal_invalid_camera_view")

    fallback_recommendation = _string(parsed.get("fallback_recommendation"), "use_video_timestamps")
    if fallback_recommendation not in VALID_FALLBACK_RECOMMENDATIONS:
        fallback_recommendation = "use_sampled_frames"
        flags.append("video_temporal_invalid_fallback_recommendation")

    if parsed.get("schema_version") != SCHEMA_VERSION:
        flags.append("video_temporal_schema_version_normalized")

    return {
        "schema_version": SCHEMA_VERSION,
        "provider": _string(provider, "unknown"),
        "model": _string(model, DEFAULT_MODEL),
        "valid": True,
        "action_confirmation": action_confirmation,
        "phase_segments": phase_segments,
        "key_moments": _normalize_key_moments(parsed),
        "macro_assessment": _normalize_macro_assessment(parsed),
        "overall_impression": _string(parsed.get("overall_impression") or parsed.get("overall_raw_text")),
        "camera_view": camera_view,
        "data_quality_hint": data_quality_hint,
        "confidence": _clamp_confidence(parsed.get("confidence", action_confirmation.get("confidence", 0.0))),
        "fallback_recommendation": fallback_recommendation,
        "quality_flags": _merge_flags(flags),
    }


def _video_temporal_failure_flag(exc: Exception) -> str:
    failure = classify_ai_failure(exc)
    if failure.code == AnalysisErrorCode.AI_API_TIMEOUT:
        return "video_temporal_timeout"
    if failure.code == AnalysisErrorCode.AI_API_QUOTA_EXCEEDED:
        return "video_temporal_budget_exceeded"
    if failure.code == AnalysisErrorCode.AI_API_AUTH_ERROR:
        return "video_temporal_auth_error"
    return "video_temporal_provider_error"


def _qwen_temporal_provider(provider: ActiveProviderConfig) -> ActiveProviderConfig:
    return ActiveProviderConfig(
        id=provider.id,
        slot=provider.slot,
        name=provider.name,
        provider=provider.provider,
        base_url=provider.base_url,
        model_id=DEFAULT_MODEL,
        vision_model=provider.vision_model,
        api_key=provider.api_key,
        notes=provider.notes,
    )


def _shift_video_temporal_timestamps(payload: dict[str, Any], offset_sec: float) -> dict[str, Any]:
    offset = _to_float(offset_sec)
    if offset is None or abs(offset) < 1e-6:
        return payload

    shifted = dict(payload)
    shifted["timestamp_offset_sec"] = round(offset, 3)

    segments: list[dict[str, Any]] = []
    for segment in payload.get("phase_segments") or []:
        if not isinstance(segment, dict):
            continue
        item = dict(segment)
        for key in ("time_start", "time_end", "key_frame_hint"):
            value = _to_float(item.get(key))
            if value is not None:
                item[key] = round(value + offset, 3)
        segments.append(item)
    shifted["phase_segments"] = segments

    key_moments = payload.get("key_moments")
    if isinstance(key_moments, dict):
        shifted_moments: dict[str, Any] = {}
        for key, value in key_moments.items():
            timestamp = _to_float(value)
            shifted_moments[key] = round(timestamp + offset, 3) if timestamp is not None else None
        shifted["key_moments"] = shifted_moments
    return shifted


async def analyze_video_temporal(
    video_path: Path,
    *,
    action_type: str,
    action_subtype: str | None = None,
    video_duration_sec: float | None = None,
    source_video_duration_sec: float | None = None,
    source_fps: float | None = None,
    timestamp_offset_sec: float = 0.0,
    analyzed_video_kind: str = "source",
    session: AsyncSession | None = None,
    provider: ActiveProviderConfig | None = None,
    timeout: float = VIDEO_TEMPORAL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Run Qwen 3.6 Plus video semantic phase localization.

    This is a soft-fail API: every provider, timeout, budget, and parse failure
    returns a diagnostic payload so the existing skeleton/sample-frame path can
    continue.
    """
    try:
        active_provider = provider or await get_active_provider("vision", session)
    except Exception as exc:  # noqa: BLE001
        flag = _video_temporal_failure_flag(exc)
        return _fallback_video_temporal_payload(
            provider="unknown",
            model=DEFAULT_MODEL,
            reason=flag,
            quality_flags=[flag],
            detail=str(exc),
        )

    provider_name = _string(getattr(active_provider, "provider", ""), "unknown").lower()
    if provider_name != "qwen":
        return _fallback_video_temporal_payload(
            provider=provider_name,
            model=DEFAULT_MODEL,
            reason="video_temporal_provider_not_qwen",
            quality_flags=["video_temporal_provider_not_qwen"],
            detail="Video temporal localization v1 only uses qwen.",
        )

    qwen_provider = _qwen_temporal_provider(active_provider)
    system_prompt, user_prompt = build_video_temporal_prompts(
        action_type=action_type,
        action_subtype=action_subtype,
        video_duration_sec=video_duration_sec,
        source_fps=source_fps,
        model=DEFAULT_MODEL,
    )

    try:
        raw = await request_dashscope_video_completion(
            qwen_provider,
            video_path=video_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=VIDEO_TEMPORAL_TEMPERATURE,
            max_tokens=VIDEO_TEMPORAL_MAX_TOKENS,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        flag = _video_temporal_failure_flag(exc)
        return _fallback_video_temporal_payload(
            provider="qwen",
            model=DEFAULT_MODEL,
            reason=flag,
            quality_flags=[flag],
            detail=str(exc),
        )

    normalized = normalize_video_temporal_payload(raw, provider="qwen", model=DEFAULT_MODEL)
    if not normalized.get("valid"):
        flags = _merge_flags(normalized.get("quality_flags"), ["video_temporal_parse_failed"])
        normalized["quality_flags"] = flags
        normalized["fallback_recommendation"] = "use_existing_skeleton_timestamps"
        normalized["fallback_reason"] = "video_temporal_parse_failed"
        normalized["valid"] = False
        normalized["validation"] = {
            "valid": False,
            "errors": flags,
            "warnings": [],
        }
        return normalized

    normalized["analyzed_video_kind"] = _string(analyzed_video_kind, "source")
    normalized["analyzed_video_path"] = str(video_path)
    normalized["timestamp_offset_sec"] = round(float(timestamp_offset_sec or 0.0), 3)
    shifted = _shift_video_temporal_timestamps(normalized, float(timestamp_offset_sec or 0.0))

    validation_duration = source_video_duration_sec
    if validation_duration is None and video_duration_sec is not None:
        validation_duration = float(video_duration_sec) + max(0.0, float(timestamp_offset_sec or 0.0))

    if validation_duration is not None:
        return validate_video_temporal_payload(shifted, duration_sec=validation_duration)
    return shifted


def _candidate_timestamp(candidate: Any) -> float | None:
    if not isinstance(candidate, dict):
        return None
    for key in ("timestamp", "timestamp_sec", "time_sec"):
        value = _to_float(candidate.get(key))
        if value is not None:
            return value
    return None


def _candidate_confidence(candidate: Any) -> float:
    if not isinstance(candidate, dict):
        return 0.0
    return _clamp_confidence(candidate.get("confidence"), default=0.0)


def _skeleton_candidates(skeleton_timestamps: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(skeleton_timestamps, dict):
        return {}
    source = skeleton_timestamps.get("key_frame_candidates")
    if isinstance(source, dict):
        return {str(key): value for key, value in source.items() if isinstance(value, dict)}
    return {str(key): value for key, value in skeleton_timestamps.items() if key in {"T", "A", "L"} and isinstance(value, dict)}


def _motion_selected_records(motion_scores: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(motion_scores, dict):
        return []
    selected = motion_scores.get("selected")
    if isinstance(selected, list):
        return [item for item in selected if isinstance(item, dict)]
    return []


def _motion_records_from_scores(motion_scores: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(motion_scores, dict):
        return []

    scores = [
        float(score)
        for score in motion_scores.get("scores", [])
        if isinstance(score, (int, float)) and not math.isnan(float(score)) and not math.isinf(float(score))
    ]
    frame_rate = _to_float(motion_scores.get("frame_rate"))
    window_start = _to_float(motion_scores.get("window_start"))
    if scores and frame_rate is not None and frame_rate > 0 and window_start is not None:
        return [
            {
                "timestamp": round(window_start + (index / frame_rate), 3),
                "motion_score": round(score, 4),
                "source": "motion_score_series",
            }
            for index, score in enumerate(scores)
        ]

    return _motion_selected_records(motion_scores)


def _motion_score_value(record: dict[str, Any]) -> float:
    value = _to_float(record.get("motion_score"))
    return value if value is not None else 0.0


def _records_in_range(records: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        timestamp = _to_float(record.get("timestamp"))
        if timestamp is not None and start <= timestamp <= end:
            out.append(record)
    return out


def _motion_peak_in_range(records: list[dict[str, Any]], start: float, end: float) -> float | None:
    candidates = _records_in_range(records, start, end)
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (_motion_score_value(item), -abs((_to_float(item.get("timestamp")) or start) - ((start + end) / 2))))
    return _to_float(best.get("timestamp"))


def _motion_peak_near(records: list[dict[str, Any]], target: float, start: float, end: float, tolerance: float = MOTION_SNAP_TOLERANCE_SECONDS) -> float | None:
    candidates = _records_in_range(records, max(start, target - tolerance), min(end, target + tolerance))
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (_motion_score_value(item), -abs((_to_float(item.get("timestamp")) or target) - target)))
    phase_peak = max((_motion_score_value(item) for item in _records_in_range(records, start, end)), default=0.0)
    best_score = _motion_score_value(best)
    if phase_peak > 0 and best_score < max(0.35, phase_peak * 0.50):
        return None
    timestamp = _to_float(best.get("timestamp"))
    return timestamp if timestamp is not None and abs(timestamp - target) <= tolerance else None


def _phase_code_for_skeleton_label(label: str) -> str:
    return {"T": "takeoff", "A": "air", "L": "landing"}[label]


def _resolve_skeleton_candidate_timestamp(
    *,
    label: str,
    candidate: dict[str, Any],
    motion_records: list[dict[str, Any]],
    start: float,
    end: float,
    fallback: bool = False,
) -> tuple[float | None, str, list[str]]:
    flags: list[str] = []
    timestamp = _candidate_timestamp(candidate)
    if timestamp is None or timestamp < start or timestamp > end:
        return None, "skeleton_candidate_invalid", flags

    phase_code = _phase_code_for_skeleton_label(label)
    confidence = _candidate_confidence(candidate)
    required_confidence = SKELETON_FALLBACK_CONFIDENCE if fallback else SKELETON_ANCHOR_CONFIDENCE
    if confidence < required_confidence:
        flags.append(f"video_temporal_resolver_skeleton_{label.lower()}_below_anchor_confidence")
        return None, "skeleton_candidate_below_anchor_confidence", flags

    if phase_code in MOTION_PEAK_PHASES:
        snapped = _motion_peak_near(motion_records, timestamp, start, end)
        if snapped is not None:
            reason = "skeleton_fallback_motion_peak" if fallback else f"video_phase_range_skeleton_{phase_code}_motion_peak"
            return snapped, reason, flags
        reason = "skeleton_fallback_candidate" if fallback else f"video_phase_range_skeleton_{phase_code}_anchor"
        return timestamp, reason, flags

    if confidence >= required_confidence:
        reason = "skeleton_fallback_apex_preserved" if fallback else "video_phase_range_skeleton_apex"
        return timestamp, reason, flags

    flags.append(f"video_temporal_resolver_skeleton_{label.lower()}_below_anchor_confidence")
    return None, "skeleton_candidate_below_anchor_confidence", flags


def _fallback_skeleton_selected(
    candidates: dict[str, dict[str, Any]],
    *,
    video_duration_sec: float,
    max_frames: int,
    motion_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    selected: list[dict[str, Any]] = []
    flags: list[str] = []
    for index, (label, key_moment) in enumerate(
        (("T", "T_takeoff_sec"), ("A", "A_air_sec"), ("L", "L_landing_sec")),
        start=1,
    ):
        candidate = candidates.get(label)
        if not isinstance(candidate, dict):
            continue
        raw_timestamp = _candidate_timestamp(candidate)
        if raw_timestamp is None or raw_timestamp < 0 or raw_timestamp > video_duration_sec:
            continue
        start = max(0.0, raw_timestamp - FALLBACK_MOTION_WINDOW_SECONDS)
        end = min(video_duration_sec, raw_timestamp + FALLBACK_MOTION_WINDOW_SECONDS)
        timestamp, reason, candidate_flags = _resolve_skeleton_candidate_timestamp(
            label=label,
            candidate=candidate,
            motion_records=motion_records,
            start=start,
            end=end,
            fallback=True,
        )
        flags.extend(candidate_flags)
        if timestamp is None:
            continue
        phase_code = _phase_code_for_skeleton_label(label)
        selected.append(
            {
                "frame_id": f"semantic_{index:04d}",
                "timestamp": round(timestamp, 3),
                "phase_code": phase_code,
                "phase_label": PHASE_LABELS[phase_code],
                "key_moment": key_moment,
                "selection_reason": reason,
                "confidence": _candidate_confidence(candidate),
            }
        )
        if len(selected) >= max_frames:
            break
    return selected, flags


def _valid_video_temporal_for_resolver(video_ai_result: dict[str, Any] | None, duration_sec: float) -> dict[str, Any] | None:
    if not isinstance(video_ai_result, dict):
        return None
    if video_ai_result.get("schema_version") == SCHEMA_VERSION and "validation" in video_ai_result:
        return video_ai_result
    if video_ai_result.get("schema_version") == SCHEMA_VERSION:
        return validate_video_temporal_payload(video_ai_result, duration_sec)
    normalized = normalize_video_temporal_payload(video_ai_result, provider=str(video_ai_result.get("provider") or "unknown"), model=str(video_ai_result.get("model") or DEFAULT_MODEL))
    return validate_video_temporal_payload(normalized, duration_sec)


def _resolver_phase_order(analysis_profile: str | None, video_ai_result: dict[str, Any]) -> list[dict[str, Any]]:
    segments = [segment for segment in video_ai_result.get("phase_segments", []) if isinstance(segment, dict)]
    profile = str(analysis_profile or "").strip().lower()
    if profile == "jump":
        priority = {"takeoff": 0, "air": 1, "landing": 2, "preparation": 3, "glide_out": 4, "approach": 5}
    elif profile == "spin":
        priority = {code: index for index, code in enumerate(SPIN_RESOLVER_PHASES)}
    elif profile == "spiral":
        priority = {code: index for index, code in enumerate(SPIRAL_RESOLVER_PHASES)}
    elif profile == "step":
        priority = {"step_sequence": 0}
    else:
        priority = {}
    return sorted(segments, key=lambda segment: priority.get(str(segment.get("phase_code")), 99))


def _resolve_segment_timestamp(
    segment: dict[str, Any],
    *,
    source: str,
    video_ai_result: dict[str, Any],
    skeleton_candidates: dict[str, dict[str, Any]],
    motion_records: list[dict[str, Any]],
) -> tuple[float | None, str, str | None, list[str]]:
    flags: list[str] = []
    phase_code = str(segment.get("phase_code") or "")
    start = _to_float(segment.get("time_start"))
    end = _to_float(segment.get("time_end"))
    hint = _to_float(segment.get("key_frame_hint"))
    if start is None or end is None or end <= start:
        return None, "invalid_phase_range", PHASE_KEY_MOMENTS.get(phase_code), ["video_temporal_resolver_invalid_phase_range"]

    key_moment = PHASE_KEY_MOMENTS.get(phase_code)
    skeleton_label = {"T_takeoff_sec": "T", "A_air_sec": "A", "L_landing_sec": "L"}.get(key_moment or "")
    skeleton_candidate = skeleton_candidates.get(skeleton_label or "")
    if isinstance(skeleton_candidate, dict):
        skeleton_ts = _candidate_timestamp(skeleton_candidate)
        skeleton_conf = _candidate_confidence(skeleton_candidate)
        if skeleton_ts is not None and start <= skeleton_ts <= end:
            timestamp, reason, skeleton_flags = _resolve_skeleton_candidate_timestamp(
                label=skeleton_label or "",
                candidate=skeleton_candidate,
                motion_records=motion_records,
                start=start,
                end=end,
            )
            flags.extend(skeleton_flags)
            if timestamp is not None:
                return timestamp, reason, key_moment, flags
            if skeleton_conf < SKELETON_ANCHOR_CONFIDENCE:
                flags.append("video_temporal_resolver_skeleton_candidate_not_used")

    if source == "video_ai_refined":
        key_value = _to_float(video_ai_result.get("key_moments", {}).get(key_moment)) if key_moment else None
        if key_value is not None and start <= key_value <= end:
            if phase_code in MOTION_PEAK_PHASES:
                nearest = _motion_peak_near(motion_records, key_value, start, end)
                if nearest is not None:
                    return nearest, "video_phase_range_key_moment_motion_peak", key_moment, flags
            else:
                return key_value, "video_phase_range_key_moment_apex", key_moment, flags

    if phase_code in MOTION_PEAK_PHASES:
        peak = _motion_peak_in_range(motion_records, start, end)
        if peak is not None:
            return peak, "video_phase_range_motion_peak", key_moment, flags

    if hint is not None and start <= hint <= end:
        return hint, "video_phase_range_key_hint", key_moment, flags

    center = round((start + end) / 2, 3)
    flags.append("video_temporal_resolver_used_phase_center")
    return center, "video_phase_range_center_fallback", key_moment, flags


def resolve_semantic_keyframes(
    video_ai_result: dict[str, Any] | None,
    skeleton_timestamps: dict[str, Any] | None,
    motion_scores: dict[str, Any] | None,
    *,
    video_duration_sec: float,
    analysis_profile: str | None,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """
    Convert semantic video intervals into exact frame timestamps for FFmpeg.
    """
    flags: list[str] = []
    resolved_budget = _configured_max_resolved_keyframes() if max_frames is None else max_frames
    max_frames = max(1, min(int(resolved_budget), MAX_RESOLVED_KEYFRAMES))
    duration = _to_float(video_duration_sec)
    if duration is None or duration <= 0:
        duration = 0.0
        flags.append("video_temporal_resolver_invalid_duration")

    normalized_video = _valid_video_temporal_for_resolver(video_ai_result, duration) if duration > 0 else None
    skeleton_candidates = _skeleton_candidates(skeleton_timestamps)
    motion_records = _motion_records_from_scores(motion_scores)

    confidence = _clamp_confidence(normalized_video.get("confidence") if isinstance(normalized_video, dict) else 0.0)
    fallback_selected, fallback_flags = _fallback_skeleton_selected(
        skeleton_candidates,
        video_duration_sec=duration,
        max_frames=max_frames,
        motion_records=motion_records,
    )
    flags.extend(fallback_flags)
    validation = normalized_video.get("validation") if isinstance(normalized_video, dict) and isinstance(normalized_video.get("validation"), dict) else {}
    explicit_video_fallback = (
        isinstance(normalized_video, dict)
        and normalized_video.get("fallback_recommendation") != "use_video_timestamps"
        and not validation.get("errors")
    )
    if not isinstance(normalized_video, dict) or confidence < 0.55 or explicit_video_fallback:
        if not isinstance(normalized_video, dict):
            flags.append("video_temporal_resolver_missing_video_ai")
        elif confidence < 0.55:
            flags.append("video_temporal_resolver_low_video_confidence")
        else:
            flags.append("video_temporal_resolver_video_fallback_recommended")
        return {
            "source": "skeleton_fallback",
            "confidence": confidence,
            "quality_flags": _merge_flags(flags),
            "selected": fallback_selected,
            "video_ai": normalized_video or {},
        }

    source = "video_ai_refined" if confidence >= 0.80 else "blended"
    if normalized_video.get("fallback_recommendation") != "use_video_timestamps":
        source = "blended"
        flags.append("video_temporal_resolver_video_fallback_recommended")
    if "video_temporal_tal_order_invalid" in normalized_video.get("quality_flags", []):
        source = "blended"
        flags.append("video_temporal_resolver_tal_order_blended")
    if validation.get("valid") is False and confidence < 0.80:
        flags.append("video_temporal_resolver_video_validation_not_clean")

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for segment in _resolver_phase_order(analysis_profile, normalized_video):
        if len(selected) >= max_frames:
            flags.append("video_temporal_resolver_frame_budget_trimmed")
            break
        if _clamp_confidence(segment.get("confidence")) < 0.60 or segment.get("valid") is False:
            flags.append(f"video_temporal_resolver_phase_{segment.get('phase_code')}_fallback")
            continue
        timestamp, reason, key_moment, segment_flags = _resolve_segment_timestamp(
            segment,
            source=source,
            video_ai_result=normalized_video,
            skeleton_candidates=skeleton_candidates,
            motion_records=motion_records,
        )
        flags.extend(segment_flags)
        if timestamp is None:
            continue
        if timestamp < 0 or timestamp > duration:
            flags.append("video_temporal_resolver_timestamp_out_of_bounds")
            continue
        phase_code = str(segment.get("phase_code") or "")
        dedupe_key = (phase_code, round(timestamp, 3))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        selected.append(
            {
                "frame_id": f"semantic_{len(selected) + 1:04d}",
                "timestamp": round(timestamp, 3),
                "phase_code": phase_code,
                "phase_label": str(segment.get("phase_label") or PHASE_LABELS.get(phase_code, "不可分析")),
                "key_moment": key_moment,
                "selection_reason": reason,
                "confidence": _clamp_confidence(segment.get("confidence"), default=confidence),
            }
        )

    if not selected and fallback_selected:
        flags.append("video_temporal_resolver_no_semantic_selection")
        source = "skeleton_fallback"
        selected = fallback_selected
    elif not selected:
        flags.append("video_temporal_resolver_no_selected_frames")

    return {
        "source": source,
        "confidence": confidence,
        "quality_flags": _merge_flags(flags),
        "selected": selected[:max_frames],
        "video_ai": normalized_video,
    }


def _phase_contains_time(segment: dict[str, Any], timestamp: float | None) -> bool:
    if timestamp is None:
        return False
    start = _to_float(segment.get("time_start"))
    end = _to_float(segment.get("time_end"))
    return start is not None and end is not None and start <= timestamp <= end


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def validate_video_temporal_payload(payload: dict[str, Any], duration_sec: float) -> dict[str, Any]:
    """
    Validate a normalized video temporal payload.

    Returns a copy of the payload plus validation diagnostics. It never raises on
    bad model data; callers should inspect valid and quality_flags.
    """
    out = dict(payload) if isinstance(payload, dict) else {}
    errors: list[str] = []
    warnings: list[str] = []
    flags = _merge_flags(out.get("quality_flags"))

    duration = _to_float(duration_sec)
    if duration is None or duration <= 0:
        duration = 0.0
        errors.append("video_temporal_invalid_duration")

    if not isinstance(payload, dict):
        errors.append("video_temporal_payload_not_object")
        out = {
            "schema_version": SCHEMA_VERSION,
            "provider": "unknown",
            "model": DEFAULT_MODEL,
            "action_confirmation": {
                "action_family": "unknown",
                "confirmed_action": "不可分析",
                "jump_type": "",
                "confidence": 0.0,
                "notes": "",
            },
            "phase_segments": [],
            "key_moments": {key: None for key in KEY_MOMENT_KEYS},
            "macro_assessment": _normalize_macro_assessment({}),
            "overall_impression": "",
            "camera_view": "unknown",
            "data_quality_hint": "poor",
            "confidence": 0.0,
            "fallback_recommendation": "use_sampled_frames",
        }

    if out.get("schema_version") != SCHEMA_VERSION:
        errors.append("video_temporal_invalid_schema_version")

    confidence = _clamp_confidence(out.get("confidence"))
    out["confidence"] = confidence
    if confidence < 0.55:
        warnings.append("video_temporal_low_confidence")
    if confidence < 0.80:
        warnings.append("video_temporal_not_high_confidence")

    fallback_recommendation = _string(out.get("fallback_recommendation"), "use_sampled_frames")
    if fallback_recommendation != "use_video_timestamps":
        warnings.append("video_temporal_fallback_recommended")

    action_confirmation = out.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        action_confirmation = _normalize_action_confirmation({})
        out["action_confirmation"] = action_confirmation
        errors.append("video_temporal_missing_action_confirmation")
    action_family = _normalize_action_family(action_confirmation.get("action_family"))
    action_confirmation["action_family"] = action_family
    action_confirmation["confidence"] = _clamp_confidence(action_confirmation.get("confidence"))

    segments = out.get("phase_segments")
    if not isinstance(segments, list) or not segments:
        errors.append("video_temporal_missing_phase_segments")
        segments = []
    valid_phase_codes = _phase_codes_for_family(action_family)
    normalized_segments: list[dict[str, Any]] = []
    previous_start: float | None = None
    previous_end: float | None = None
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            errors.append(f"video_temporal_phase_{index}_not_object")
            continue
        item = dict(segment)
        item["confidence"] = _clamp_confidence(item.get("confidence"))
        code = _normalize_phase_code(item.get("phase_code"))
        item["phase_code"] = code
        start = _to_float(item.get("time_start"))
        end = _to_float(item.get("time_end"))
        hint = _to_float(item.get("key_frame_hint"))

        phase_valid = True
        if code not in valid_phase_codes:
            phase_valid = False
            errors.append(f"video_temporal_phase_{index}_invalid_code")
        if start is None or end is None:
            phase_valid = False
            errors.append(f"video_temporal_phase_{index}_missing_time")
        elif start < 0 or end > duration or end <= start:
            phase_valid = False
            errors.append(f"video_temporal_phase_{index}_invalid_time_range")
        if hint is not None and start is not None and end is not None and not (start <= hint <= end):
            warnings.append(f"video_temporal_phase_{index}_hint_outside_range")
        if item["confidence"] < 0.60:
            warnings.append(f"video_temporal_phase_{index}_low_confidence")
        if previous_start is not None and start is not None and previous_end is not None:
            overlap = min(previous_end, end if end is not None else previous_end) - max(previous_start, start)
            if overlap > 0.25:
                warnings.append(f"video_temporal_phase_{index}_overlaps_previous")
        previous_start = start if start is not None else previous_start
        previous_end = end if end is not None else previous_end
        item["valid"] = phase_valid and item["confidence"] >= 0.60
        normalized_segments.append(item)
    out["phase_segments"] = normalized_segments

    key_moments = out.get("key_moments")
    if not isinstance(key_moments, dict):
        key_moments = {key: None for key in KEY_MOMENT_KEYS}
        out["key_moments"] = key_moments
    for key in KEY_MOMENT_KEYS:
        value = _to_float(key_moments.get(key))
        key_moments[key] = round(value, 3) if value is not None else None
        if value is not None and (value < 0 or value > duration):
            warnings.append(f"video_temporal_{key}_out_of_bounds")

    if action_family == "jump":
        t_value = _to_float(key_moments.get("T_takeoff_sec"))
        a_value = _to_float(key_moments.get("A_air_sec"))
        l_value = _to_float(key_moments.get("L_landing_sec"))
        if t_value is not None and a_value is not None and l_value is not None and not (t_value < a_value < l_value):
            warnings.append("video_temporal_tal_order_invalid")
        segment_by_code = {segment.get("phase_code"): segment for segment in normalized_segments if isinstance(segment, dict)}
        if t_value is not None and not _phase_contains_time(segment_by_code.get("takeoff", {}), t_value):
            warnings.append("video_temporal_T_takeoff_outside_takeoff_phase")
        if a_value is not None and not _phase_contains_time(segment_by_code.get("air", {}), a_value):
            warnings.append("video_temporal_A_air_outside_air_phase")
        if l_value is not None and not _phase_contains_time(segment_by_code.get("landing", {}), l_value):
            warnings.append("video_temporal_L_landing_outside_landing_phase")

    for item in errors:
        _append_once(flags, item)
    for item in warnings:
        _append_once(flags, item)

    valid = not errors and confidence >= 0.55 and fallback_recommendation == "use_video_timestamps"
    out["valid"] = valid
    out["quality_flags"] = flags
    out["validation"] = {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "duration_sec": duration,
    }
    if not valid and out.get("fallback_recommendation") == "use_video_timestamps":
        out["fallback_recommendation"] = "use_sampled_frames"
    return out
