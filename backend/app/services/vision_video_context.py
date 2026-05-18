from __future__ import annotations

import json
from typing import Any

from app.services.video import FramePayload


PHASE_VERIFICATION_VALUES = {"agree", "shifted", "disagree", "uncertain"}


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return None
    return numeric


def _round_or_none(value: Any) -> float | None:
    numeric = _to_float(value)
    return round(numeric, 3) if numeric is not None else None


def _frame_context_from_record(
    record: dict[str, Any],
    *,
    video_temporal: dict[str, Any],
) -> dict[str, Any]:
    macro = video_temporal.get("macro_assessment") if isinstance(video_temporal.get("macro_assessment"), dict) else {}
    action = video_temporal.get("action_confirmation") if isinstance(video_temporal.get("action_confirmation"), dict) else {}
    context = {
        "confirmed_action": action.get("confirmed_action") or action.get("jump_type") or "不可分析",
        "phase_label": record.get("phase_label") or "",
        "timestamp_sec": _round_or_none(record.get("timestamp")),
        "phase_time_start": None,
        "phase_time_end": None,
        "key_moment": record.get("key_moment"),
        "macro_axis_overall": macro.get("axis_overall", ""),
        "camera_view": video_temporal.get("camera_view", "unknown"),
        "video_confidence": _round_or_none(video_temporal.get("confidence")),
    }
    phase_code = record.get("phase_code")
    segments = video_temporal.get("phase_segments")
    if isinstance(segments, list):
        segment = next(
            (
                item
                for item in segments
                if isinstance(item, dict)
                and item.get("phase_code") == phase_code
                and (
                    context["timestamp_sec"] is None
                    or (
                        _to_float(item.get("time_start")) is not None
                        and _to_float(item.get("time_end")) is not None
                        and float(item["time_start"]) <= float(context["timestamp_sec"]) <= float(item["time_end"])
                    )
                )
            ),
            None,
        )
        if isinstance(segment, dict):
            context["phase_time_start"] = _round_or_none(segment.get("time_start"))
            context["phase_time_end"] = _round_or_none(segment.get("time_end"))
            if not context["phase_label"]:
                context["phase_label"] = segment.get("phase_label") or ""
    return context


def build_video_context_by_frame(
    frame_payloads: list[FramePayload],
    *,
    video_temporal: dict[str, Any] | None = None,
    resolved_keyframes: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(video_temporal, dict) or not isinstance(resolved_keyframes, dict):
        return {}
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return {}

    by_frame: dict[str, dict[str, Any]] = {}
    frame_ids = {frame.frame_id for frame in frame_payloads}
    for record in selected:
        if not isinstance(record, dict):
            continue
        frame_id = str(record.get("frame_id") or "").strip()
        if frame_id and frame_id in frame_ids:
            by_frame[frame_id] = _frame_context_from_record(record, video_temporal=video_temporal)
    return by_frame


def format_video_context_prompt_block(video_context_by_frame: dict[str, dict[str, Any]] | None) -> str:
    if not video_context_by_frame:
        return ""
    return (
        "\n\n【video_context 语义帧上下文】\n"
        "这些图片来自视频 AI 阶段区间 + 运动密度 + 骨架候选仲裁后的语义关键帧。"
        "请不要从零猜阶段，而是在 video_context 中做帧级验证。\n"
        f"{json.dumps(video_context_by_frame, ensure_ascii=False, indent=2, sort_keys=True)}\n\n"
        "输出要求：每个 frame_analysis 项必须新增 phase_verification、conflict_with_video_context、video_context_note。\n"
        'phase_verification 只能是 "agree|shifted|disagree|uncertain"。\n'
        "可以挑战 video_context，但必须在 video_context_note 说明原因。\n"
        "刃面或入跳弧线不可见时必须输出“不可判断/不可判定”，不要猜 Lutz/Flip 内外刃。\n"
        "请使用 5-8 岁儿童训练标准，中文、鼓励性、训练导向。"
    )


def video_context_label(frame_id: str, video_context_by_frame: dict[str, dict[str, Any]] | None) -> str:
    context = (video_context_by_frame or {}).get(frame_id)
    if not isinstance(context, dict):
        return ""
    return "video_context: " + json.dumps(context, ensure_ascii=False, sort_keys=True)


def normalize_video_context_fields(frame: dict[str, Any], raw: dict[str, Any]) -> None:
    if raw.get("phase_verification") is not None:
        value = str(raw.get("phase_verification") or "").strip()
        frame["phase_verification"] = value if value in PHASE_VERIFICATION_VALUES else "uncertain"
    if raw.get("conflict_with_video_context") is not None:
        frame["conflict_with_video_context"] = bool(raw.get("conflict_with_video_context"))
    if raw.get("video_context_note") is not None:
        frame["video_context_note"] = str(raw.get("video_context_note") or "").strip()
