from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.providers import ActiveProviderConfig, request_text_completion
from app.services.report import clean_json_text
from app.services.video import FramePayload
from app.services.vision_video_context import format_video_context_prompt_block, video_context_label


logger = logging.getLogger(__name__)

PATH_B_TEMPERATURE = 0.25
PATH_B_MAX_FRAMES = 10
PATH_B_CONTEXT_WIN = 2
PATH_B_MAX_TOKENS_BASE = 1000
PATH_B_MAX_TOKENS_FRAME = 380
PATH_B_MAX_TOKENS_CAP = 8000

PATH_B_SYSTEM = (
    "你是花样滑冰生物力学分析专家。"
    "每帧图像已叠加 MediaPipe 骨架与角度数字（ASCII 标签：LKnee/RKnee/LElbow/RElbow）。"
    "请结合图像和文字测量值综合判断。"
    "严格输出 JSON，禁止任何额外文字。\n\n"
    "【评分校准 - 儿童初学者】\n"
    "学员是儿童初学者（Free Skate 1），评分标准必须相应调整：\n"
    "- subscores 评分：0.5 = 基本达标（初学者正常水平），0.3 = 略有不足但仍可接受，0.7+ = 表现良好。\n"
    "- top_issues 应聚焦最需改进的 1-2 个核心问题，用建设性语言描述，不要列举所有不足。\n"
    "- top_positives 应肯定学员做得好的地方，即使是很小的进步。\n"
    "- 用鼓励性语言替代批评性语言，例如用'建议加强'代替'严重不足'。"
)


def sample_frames_path_b(
    frame_payloads: list[FramePayload],
    key_stems: set[str] | None = None,
    n_context: int = PATH_B_CONTEXT_WIN,
    max_frames: int = PATH_B_MAX_FRAMES,
) -> list[FramePayload]:
    """Sample key frames with +/- context; fall back to uniform sampling."""
    cap = min(max_frames, len(frame_payloads))
    if not key_stems:
        if len(frame_payloads) <= cap:
            return list(frame_payloads)
        step = len(frame_payloads) / cap
        return [frame_payloads[int(i * step)] for i in range(cap)]

    selected: set[int] = set()
    for index, frame in enumerate(frame_payloads):
        if frame.frame_id in key_stems:
            selected.update(
                range(
                    max(0, index - n_context),
                    min(len(frame_payloads), index + n_context + 1),
                )
            )
    if not selected:
        return sample_frames_path_b(frame_payloads, None, n_context, max_frames)

    indices = sorted(selected)[:max_frames]
    return [frame_payloads[index] for index in indices]


def _build_bio_text(bio: dict[str, float] | None) -> str:
    if not bio:
        return ""

    parts = ["  [Measurements]"]
    for key, label, unit in [
        ("left_knee_angle", "LKnee", "deg"),
        ("right_knee_angle", "RKnee", "deg"),
        ("trunk_tilt_deg", "TrunkTilt", "deg(0=vertical)"),
        ("arm_symmetry", "ArmSym", "(1.0=symmetric)"),
    ]:
        value = bio.get(key)
        if value is None:
            continue
        try:
            parts.append(f"  {label}={float(value):.2f}{unit}")
        except (TypeError, ValueError):
            continue
    return "\n".join(parts) if len(parts) > 1 else ""


def _build_user_prompt(
    action_type: str,
    action_subtype: str | None,
    analysis_profile: str | None,
    profile_evidence: dict[str, Any] | None,
    jump_metrics_text: str,
    n_frames: int,
    skill_category: str | None = None,
    video_context_by_frame: dict[str, dict[str, Any]] | None = None,
) -> str:
    blocks: list[str] = []
    if analysis_profile or profile_evidence:
        blocks.append(
            "【动作识别已知信息 · 请勿推翻】\n"
            f"  分析 profile：{analysis_profile or 'unknown'}\n"
            f"  规则证据：{json.dumps(profile_evidence or {}, ensure_ascii=False)}\n"
            "  JUMP_SUBTYPE_EVIDENCE: prioritize jump_subtype_evidence; "
            "pre_takeoff_edge_score near 0 supports Lutz outside edge, near 1 supports Flip inside edge."
        )
    if jump_metrics_text:
        blocks.append(f"【整体生物力学摘要】\n  {jump_metrics_text}")
    grounding = ("\n\n".join(blocks) + "\n\n") if blocks else ""

    body = (
        f"分析【{action_type}】动作（共 {n_frames} 帧，骨架已叠加，按时间顺序）。\n"
        f"动作子类型：{action_subtype or '未指定'}\n\n"
        f"技能分类：{skill_category or '未指定'}\n\n"
        "每帧图像前附有该帧测量值，请结合数值和图像综合判断。\n\n"
        "【subscores 评分标准（0-1 浮点数）】\n"
        "0.6-0.7 = 基本达标（Free Skate 1 初学者正常水平）\n"
        "0.4-0.5 = 略有不足，但动作流程完整\n"
        "0.8+ = 表现良好\n"
        "0.2-0.3 = 明显不足，需要重点改进\n\n"
        "输出严格符合下方 schema 的 JSON：\n"
        '{"frame_analysis":[{"frame_id":"frame_0001",'
        '"phase":"准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",'
        '"bio_observations":{"knee_angle_assessment":"<=25字",'
        '"axis_assessment":"<=25字","arm_symmetry_assessment":"<=25字",'
        '"overall_bio_quality":"<=25字"},'
        '"confidence":0.0}],'
        '"action_phase_summary":{"detected_phases":[],"weakest_phase":"","strongest_phase":""},'
        '"subscores":{"takeoff_power":0.5,"rotation_axis":0.5,'
        '"arm_coordination":0.5,"landing_absorption":0.5,"core_stability":0.5},'
        '"top_issues":["最多3条，必须引用具体测量数值"],'
        '"top_positives":["最多2条，结合量化数据"]}\n\n'
        "必须只输出 JSON。"
    )
    return grounding + body + format_video_context_prompt_block(video_context_by_frame)


def _fallback(error: str) -> dict[str, Any]:
    return {
        "path": "B",
        "error": error,
        "frame_analysis": [],
        "subscores": {},
        "action_phase_summary": {"detected_phases": [], "weakest_phase": "", "strongest_phase": ""},
        "top_issues": [],
        "top_positives": [],
    }


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    if not raw_text or not raw_text.strip():
        return None

    cleaned = clean_json_text(raw_text)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw_text, re.IGNORECASE)
    if match:
        try:
            parsed = json.loads(match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    for start, char in enumerate(raw_text):
        if char != "{":
            continue
        depth = 0
        for end in range(start, len(raw_text)):
            if raw_text[end] == "{":
                depth += 1
            elif raw_text[end] == "}":
                depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(raw_text[start : end + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    break
    return None


def _path_b_temperature(provider: ActiveProviderConfig) -> float:
    if getattr(provider, "provider", "") == "mimo":
        return 0.0
    return PATH_B_TEMPERATURE


async def analyze_path_b(
    action_type: str,
    annotated_frame_payloads: list[FramePayload],
    provider: ActiveProviderConfig,
    *,
    frame_bio_context: dict[str, dict[str, float]] | None = None,
    key_frame_stems: set[str] | None = None,
    jump_metrics_text: str = "",
    action_subtype: str | None = None,
    analysis_profile: str | None = None,
    profile_evidence: dict[str, Any] | None = None,
    memory_context: str = "",
    skill_category: str | None = None,
    video_context_by_frame: dict[str, dict[str, Any]] | None = None,
    preserve_all_frames: bool = False,
) -> dict[str, Any]:
    """
    Path B: annotated skeleton frames plus biomechanical numeric grounding.

    Soft-failure contract: any error returns a dict with an "error" field.
    """
    if not annotated_frame_payloads:
        return _fallback("no frames")

    try:
        frames = list(annotated_frame_payloads) if preserve_all_frames else sample_frames_path_b(annotated_frame_payloads, key_frame_stems)
        n_frames = len(frames)
        if n_frames == 0:
            return _fallback("sampling produced 0 frames")

        max_tokens = min(
            PATH_B_MAX_TOKENS_CAP,
            PATH_B_MAX_TOKENS_BASE + n_frames * PATH_B_MAX_TOKENS_FRAME,
        )

        system_prompt = PATH_B_SYSTEM if not memory_context else f"{PATH_B_SYSTEM}\n\n{memory_context}"
        user_text = _build_user_prompt(
            action_type,
            action_subtype,
            analysis_profile,
            profile_evidence,
            jump_metrics_text,
            n_frames,
            skill_category,
            video_context_by_frame,
        )

        bio_context = frame_bio_context or {}
        content: list[dict[str, object]] = [{"type": "text", "text": user_text}]
        for frame in frames:
            label = f"帧编号：{frame.frame_id} | 时间：{frame.timestamp_sec:.2f}s"
            bio_text = _build_bio_text(bio_context.get(frame.frame_id))
            if bio_text:
                label += "\n" + bio_text
            context_label = video_context_label(frame.frame_id, video_context_by_frame)
            if context_label:
                label += "\n" + context_label
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {"url": frame.data_url}})

        raw = await request_text_completion(
            provider,
            temperature=_path_b_temperature(provider),
            max_tokens=max_tokens,
            timeout=90.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        )

        parsed = _extract_json_object(raw)
        if parsed is None:
            cleaned = clean_json_text(raw)
            logger.warning("Path B JSON parse failed; raw[:500]=%r", cleaned[:500])
            return _fallback("json_parse: no valid JSON object found")
        if not isinstance(parsed, dict):
            return _fallback("response is not a dict")

        parsed["path"] = "B"
        parsed["path_desc"] = "量化 grounding（骨架帧 + bio 数值）"
        parsed["n_frames"] = n_frames
        parsed.setdefault("frame_analysis", [])
        parsed.setdefault("subscores", {})
        parsed.setdefault(
            "action_phase_summary",
            {"detected_phases": [], "weakest_phase": "", "strongest_phase": ""},
        )
        parsed.setdefault("top_issues", [])
        parsed.setdefault("top_positives", [])
        return parsed

    except Exception as exc:  # noqa: BLE001
        logger.error("Path B soft-failure: %s", exc, exc_info=True)
        return _fallback(str(exc))
