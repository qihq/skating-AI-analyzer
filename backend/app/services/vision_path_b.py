from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from app.services.action_profiles import profile_warning_from_evidence
from app.services.providers import ActiveProviderConfig, request_text_completion
from app.services.report import clean_json_text
from app.services.video import FramePayload
from app.services.vision_video_context import format_video_context_prompt_block, video_context_label
from app.analysis_v2.path_review import build_path_b_v2_prompt, normalize_path_b_measurements


logger = logging.getLogger(__name__)

PATH_B_TEMPERATURE = 0.25
PATH_B_MAX_FRAMES = int(os.getenv("PATH_B_MAX_FRAMES", "16"))
PATH_B_CONTEXT_WIN = 2
PATH_B_CORE_PHASE_QUOTA = int(os.getenv("PATH_B_CORE_PHASE_QUOTA", "3"))
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


@dataclass(slots=True)
class PathBFrameSelection:
    frames: list[FramePayload]
    per_stage_count: dict[str, int]
    sources: list[str]
    omitted_context_count: int
    cap_reason: str
    evidence_context_by_frame: dict[str, str]


def _nearest_payload_index(frame_payloads: list[FramePayload], timestamp: float, *, tolerance: float = 0.18) -> int | None:
    if not frame_payloads:
        return None
    index, frame = min(enumerate(frame_payloads), key=lambda item: abs(item[1].timestamp_sec - timestamp))
    return index if abs(frame.timestamp_sec - timestamp) <= tolerance else None


def select_stage_balanced_frames(
    frame_payloads: list[FramePayload],
    evidence_frames: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
    max_frames: int = PATH_B_MAX_FRAMES,
) -> PathBFrameSelection:
    """Reserve stage quotas before adding chronological context frames."""
    cap = min(max(max_frames, 1), len(frame_payloads))
    evidence = evidence_frames.get("records") if isinstance(evidence_frames, dict) else None
    if not isinstance(evidence, list):
        frames = sample_frames_path_b(frame_payloads, None, max_frames=cap)
        return PathBFrameSelection(frames, {}, [], max(0, len(frame_payloads) - len(frames)), "legacy_uniform_fallback", {})

    required_by_profile = {
        "jump": ("takeoff", "air", "landing"),
        "spin": ("spin_entry", "spin_main", "spin_exit"),
        "spiral": ("spiral_entry", "spiral_hold", "spiral_exit"),
        "step": ("step_sequence",),
    }
    required = required_by_profile.get(str(analysis_profile or "").lower(), ())
    source_order = {"resolved_semantic": 0, "mimo_key_moment": 1, "pose_candidate": 2, "mimo_phase": 3, "mimo_retry": 4, "partial_semantic": 5}
    by_phase: dict[str, list[tuple[int, dict[str, Any]]]] = {phase: [] for phase in required}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        phase = str(item.get("phase") or "")
        if phase not in by_phase:
            continue
        try:
            timestamp = float(item.get("timestamp"))
        except (TypeError, ValueError):
            continue
        index = _nearest_payload_index(frame_payloads, timestamp)
        if index is not None:
            by_phase[phase].append((index, item))

    selected: list[int] = []
    evidence_context: dict[str, list[str]] = {}
    sources: set[str] = set()
    per_stage_count: dict[str, int] = {}
    for phase in required:
        candidates = sorted(by_phase[phase], key=lambda item: (source_order.get(str(item[1].get("source")), 9), item[0]))
        phase_count = 0
        for index, item in candidates:
            if index in selected or phase_count >= PATH_B_CORE_PHASE_QUOTA or len(selected) >= cap:
                continue
            selected.append(index)
            phase_count += 1
            source = str(item.get("source") or "unknown")
            sources.add(source)
            evidence_context.setdefault(frame_payloads[index].frame_id, []).append(
                f"evidence={source}; phase={phase}; reason={item.get('selection_reason') or 'stage_quota'}"
            )
        if phase_count:
            per_stage_count[phase] = phase_count

    if not selected:
        frames = sample_frames_path_b(frame_payloads, None, max_frames=cap)
        return PathBFrameSelection(frames, {}, [], max(0, len(frame_payloads) - len(frames)), "no_phase_evidence_uniform_fallback", {})

    for position in range(cap):
        if len(selected) >= cap:
            break
        index = round(position * (len(frame_payloads) - 1) / max(cap - 1, 1))
        if index not in selected:
            selected.append(index)
    selected = sorted(selected)
    frames = [frame_payloads[index] for index in selected]
    return PathBFrameSelection(
        frames,
        per_stage_count,
        sorted(sources),
        max(0, len(frame_payloads) - len(frames)),
        "stage_quota_cap" if len(frames) >= cap else "stage_quota_under_cap",
        {frame_id: " | ".join(labels) for frame_id, labels in evidence_context.items()},
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
    evidence_context_by_frame: dict[str, str] | None = None,
) -> str:
    blocks: list[str] = []
    if analysis_profile or profile_evidence:
        route_warning = profile_warning_from_evidence(profile_evidence or {})
        blocks.append(
            "【动作分类路由线索 · 不是已确认动作】\n"
            f"  分析路由：{analysis_profile or '未明确'}\n"
            f"  路由边界：{route_warning or '路由只决定分析重点，不能当作动作事实。'}\n"
            f"  规则证据（仅作线索，不能自行证明动作）：{json.dumps(profile_evidence or {}, ensure_ascii=False)}\n"
            "  证据规则：analysis_profile、用户标签和规则证据只决定分析关注点，不等于已确认动作；"
            "只有独立可见证据（离地/腾空/落冰、刃型、旋转轴、连续姿态等）才能支持跳跃、旋转及其细项。\n"
            "  证据规则：jump_features 或几何候选不能循环确证 jump；若与画面独立证据冲突，以画面为准并降低 confidence。\n"
            "  证据规则：路由为步法/旋转/燕式时不得否定画面中独立可见的跳跃；路由为跳跃时也不得据此写具体跳种、周数或单双跳。\n"
            "  JUMP_SUBTYPE_EVIDENCE: 只有存在独立可见的起跳/刃型证据时，"
            "pre_takeoff_edge_score near 0 may support Lutz outside edge, near 1 may support Flip inside edge."
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
    evidence_lines = [f"- {frame_id}: {label}" for frame_id, label in (evidence_context_by_frame or {}).items()]
    evidence_block = "\n【阶段取帧证据】\n" + "\n".join(evidence_lines) if evidence_lines else ""
    return grounding + body + evidence_block + format_video_context_prompt_block(video_context_by_frame)


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
    evidence_context_by_frame: dict[str, str] | None = None,
    preserve_all_frames: bool = False,
    v2_mode: bool = False,
    structured_measurements: list[dict[str, Any]] | dict[str, Any] | None = None,
    required_joints: tuple[str, ...] | list[str] = (),
    identity_state: str = "unknown",
    source_fingerprints: dict[str, str] | None = None,
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

        if v2_mode:
            system_prompt, user_text = build_path_b_v2_prompt(
                # Keep the metric key at the V2 boundary.  Passing ``dict.values``
                # loses the source-linked claim name and turns scalar entries
                # into untraceable generic measurements.
                structured_measurements=structured_measurements,
                required_joints=required_joints,
                identity_state=identity_state,
            )
            if memory_context:
                # Memory can contain family context, but must not become an
                # additional technical source in the V2 reviewer prompt.
                system_prompt = f"{system_prompt}\n\nFamily context (non-evidence): {memory_context}"
        else:
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
                evidence_context_by_frame,
            )

        bio_context = frame_bio_context or {}
        content: list[dict[str, object]] = [{"type": "text", "text": user_text}]
        for frame in frames:
            label = f"帧编号：{frame.frame_id} | 时间：{frame.timestamp_sec:.2f}s"
            bio_text = "" if v2_mode else _build_bio_text(bio_context.get(frame.frame_id))
            if bio_text:
                label += "\n" + bio_text
            context_label = "" if v2_mode else video_context_label(frame.frame_id, video_context_by_frame)
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
        if v2_mode:
            measurement_records: list[dict[str, Any]] = []
            if isinstance(structured_measurements, dict):
                for key, value in structured_measurements.items():
                    if isinstance(value, dict):
                        measurement_records.append({"claim_type": key, **value})
                    else:
                        measurement_records.append({"claim_type": key, "value": value, "provenance": "measured"})
            elif isinstance(structured_measurements, list):
                measurement_records.extend(item for item in structured_measurements if isinstance(item, dict))
            # If no explicit source-linked measurements were supplied, model
            # prose cannot promote a technical claim into V2 evidence.
            claims = normalize_path_b_measurements(
                measurement_records,
                identity_state=identity_state,
                required_joints=required_joints,
                source_fingerprints=source_fingerprints,
            )
            parsed["v2_mode"] = True
            parsed["evidence_claims"] = [claim.model_dump(mode="json") for claim in claims]
            # This envelope marker is written after parsing the provider
            # response, so provider JSON cannot self-attest deterministic
            # provenance.  The fusion adapter uses it to retain the explicit
            # deterministic_measurement source only for these local claims.
            parsed["evidence_claims_origin"] = "structured_measurement_adapter.v1"
            parsed["provenance_summary"] = {
                "identity_state": identity_state,
                "required_joints": list(required_joints),
                "measurement_count": len(measurement_records),
                "suppressed_claim_count": sum(1 for claim in claims if claim.status == "unobservable"),
            }
        return parsed

    except Exception as exc:  # noqa: BLE001
        logger.error("Path B soft-failure: %s", exc, exc_info=True)
        return _fallback(str(exc))
