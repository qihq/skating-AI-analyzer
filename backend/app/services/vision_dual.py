from __future__ import annotations

import asyncio
import base64
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

from app.services.bio_context import (
    build_frame_bio_context,
    extract_key_frame_stems,
    summarize_jump_metrics,
)
from app.services.cross_validator import (
    CrossValidationReport,
    compute_blend_weights,
    cross_validate,
)
from app.services.frame_annotator import annotate_frames_batch, build_pose_by_stem
from app.services.llm_context import AnalysisPromptContext, render_prompt_context
from app.services.providers import ActiveProviderConfig
from app.services.pose import extract_pose
from app.services.video import FramePayload, encode_frames
from app.services.vision_path_a import analyze_path_a
from app.services.vision_path_b import PATH_B_MAX_FRAMES, analyze_path_b, sample_frames_path_b
from app.services.video_temporal import semantic_keyframes_are_reliable
from app.services.vision_video_context import build_video_context_by_frame


logger = logging.getLogger(__name__)

DUAL_PATH_TOTAL_TIMEOUT = 150.0
PATH_B_TIMEOUT = 120.0
PATH_B_IMAGE_MAX_WIDTH = 640
PATH_B_IMAGE_JPEG_QUALITY = 72


def _motion_features_for_prompt(frame_motion_scores: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(frame_motion_scores, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in ("sample_count", "quality_flags", "analysis_profile_hint", "selected"):
        value = frame_motion_scores.get(key)
        if value is not None:
            summary[key] = value
    scores = frame_motion_scores.get("scores")
    if isinstance(scores, list):
        numeric_scores = [float(score) for score in scores if isinstance(score, (int, float))]
        summary["scores"] = numeric_scores[:20]
        if numeric_scores:
            summary["score_summary"] = {
                "count": len(numeric_scores),
                "max": round(max(numeric_scores), 4),
                "min": round(min(numeric_scores), 4),
                "avg": round(sum(numeric_scores) / len(numeric_scores), 4),
            }
    return summary


def _uses_semantic_keyframes(resolved_keyframes: dict[str, Any] | None) -> bool:
    return semantic_keyframes_are_reliable(resolved_keyframes)


def _semantic_pose_for_annotation(
    frame_paths: list[Path],
    work_dir: Path,
    *,
    effective_fps: float | None = None,
) -> dict[str, Any]:
    pose_input_dir = work_dir / "_semantic_pose_input"
    if pose_input_dir.exists():
        shutil.rmtree(pose_input_dir, ignore_errors=True)
    pose_input_dir.mkdir(parents=True, exist_ok=True)
    rename_map: dict[str, str] = {}
    for index, frame_path in enumerate(frame_paths, start=1):
        target = pose_input_dir / f"frame_{index:04d}.jpg"
        shutil.copy2(frame_path, target)
        rename_map[target.name] = frame_path.name

    pose_payload = extract_pose(str(pose_input_dir), effective_fps=effective_fps)
    frames = pose_payload.get("frames") if isinstance(pose_payload, dict) else None
    if isinstance(frames, list):
        remapped: list[dict[str, Any]] = []
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            item = dict(frame)
            frame_name = item.get("frame")
            if isinstance(frame_name, str) and frame_name in rename_map:
                item["frame"] = rename_map[frame_name]
            remapped.append(item)
        pose_payload = {**pose_payload, "frames": remapped}
    return pose_payload if isinstance(pose_payload, dict) else {"frames": [], "connections": []}


def _compress_frame_payloads_for_path_b(
    frame_paths: list[Path],
    payloads: list[FramePayload],
    *,
    max_width: int = PATH_B_IMAGE_MAX_WIDTH,
    jpeg_quality: int = PATH_B_IMAGE_JPEG_QUALITY,
) -> list[FramePayload]:
    by_stem = {path.stem: path for path in frame_paths}
    compressed: list[FramePayload] = []
    for payload in payloads:
        frame_path = by_stem.get(payload.frame_id)
        if frame_path is None:
            compressed.append(payload)
            continue
        image = cv2.imread(str(frame_path))
        if image is None:
            compressed.append(payload)
            continue
        height, width = image.shape[:2]
        if width > max_width:
            scale = max_width / float(width)
            image = cv2.resize(image, (max_width, max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
        if not ok:
            compressed.append(payload)
            continue
        compressed.append(
            FramePayload(
                frame_id=payload.frame_id,
                data_url=f"data:image/jpeg;base64,{base64.b64encode(encoded.tobytes()).decode('utf-8')}",
                timestamp_sec=payload.timestamp_sec,
            )
        )
    return compressed


@dataclass(slots=True)
class DualPathResult:
    path_a: dict[str, Any]
    path_b: dict[str, Any] | None
    validation: CrossValidationReport
    blend_weights: tuple[float, float]
    dual_path_meta: dict[str, Any]
    annotated_dir: Path | None
    used_key_frames: set[str]


async def analyze_frames_dual(
    action_type: str,
    frame_paths: list[Path],
    raw_frame_payloads: list[FramePayload],
    pose_data: dict[str, Any] | None,
    bio_data: dict[str, Any] | None,
    provider_path_a: ActiveProviderConfig,
    provider_path_b: ActiveProviderConfig,
    *,
    frame_motion_scores: dict[str, Any] | None = None,
    action_subtype: str | None = None,
    analysis_profile: str | None = None,
    profile_evidence: dict[str, Any] | None = None,
    memory_context: str = "",
    annotated_dir: Path | None = None,
    timestamps: dict[str, float] | None = None,
    clip_path: Path | None = None,
    window_start_sec: float = 0.0,
    total_timeout: float = DUAL_PATH_TOTAL_TIMEOUT,
    path_b_timeout: float = PATH_B_TIMEOUT,
    skill_category: str | None = None,
    prompt_context: AnalysisPromptContext | None = None,
    video_temporal: dict[str, Any] | None = None,
    resolved_keyframes: dict[str, Any] | None = None,
) -> DualPathResult:
    """
    Run dual-path analysis and cross validation.

    Path A keeps the hard-error contract from analyze_frames/analyze_path_a.
    Path B keeps a soft-error contract and returns {"error": "..."} on failure.
    """
    if annotated_dir is None:
        annotated_dir = (frame_paths[0].parent.parent / "annotated") if frame_paths else Path("/tmp/annotated")

    uses_semantic_keyframes = _uses_semantic_keyframes(resolved_keyframes)
    annotation_pose_data = pose_data
    annotation_source = "main_pose"
    if uses_semantic_keyframes:
        try:
            effective_fps = None
            if isinstance(frame_motion_scores, dict):
                raw_fps = frame_motion_scores.get("effective_fps")
                effective_fps = float(raw_fps) if isinstance(raw_fps, (int, float)) else None
            annotation_pose_data = await asyncio.to_thread(
                _semantic_pose_for_annotation,
                frame_paths,
                annotated_dir.parent,
                effective_fps=effective_fps,
            )
            annotation_source = "semantic_light_pose"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Semantic frame light pose failed; Path B will use original semantic frames: %s", exc)
            annotation_pose_data = {"frames": [], "connections": []}
            annotation_source = "semantic_pose_failed_original_frames"

    pose_by_stem = build_pose_by_stem(annotation_pose_data)
    connections = annotation_pose_data.get("connections") if isinstance(annotation_pose_data, dict) else None
    annotated_paths = annotate_frames_batch(
        frame_paths,
        pose_by_stem,
        annotated_dir,
        connections=connections if isinstance(connections, list) else None,
    )
    annotated_payloads = await encode_frames(annotated_paths, timestamps=timestamps)
    compressed_annotated_payloads = _compress_frame_payloads_for_path_b(annotated_paths, annotated_payloads)
    video_context_by_frame = build_video_context_by_frame(
        raw_frame_payloads,
        video_temporal=video_temporal,
        resolved_keyframes=resolved_keyframes,
    )

    frame_stems = [payload.frame_id for payload in raw_frame_payloads]
    key_stems = extract_key_frame_stems(bio_data)
    path_b_payloads = (
        compressed_annotated_payloads
        if uses_semantic_keyframes
        else sample_frames_path_b(compressed_annotated_payloads, key_stems, max_frames=PATH_B_MAX_FRAMES)
    )
    bio_ctx = build_frame_bio_context(bio_data, frame_stems)
    jump_metrics_text = summarize_jump_metrics(bio_data)
    motion_features = _motion_features_for_prompt(frame_motion_scores)
    rendered_context = (
        render_prompt_context(prompt_context, include_bio=True)
        if prompt_context is not None
        else memory_context
    )

    async def _run_a() -> dict[str, Any]:
        return await analyze_path_a(
            action_type=action_type,
            frame_payloads=raw_frame_payloads,
            provider=provider_path_a,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            profile_evidence=profile_evidence,
            bio_data=bio_data,
            motion_features=motion_features,
            memory_context=rendered_context,
            mode="video" if clip_path is not None else "frames",
            clip_path=clip_path,
            window_start_sec=window_start_sec,
            skill_category=skill_category,
            video_context_by_frame=video_context_by_frame,
        )

    async def _run_b() -> dict[str, Any]:
        if not path_b_payloads:
            return {
                "path": "B",
                "error": "skipped_no_annotated_frames",
                "n_frames": 0,
                "frame_analysis": [],
            }
        return await analyze_path_b(
            action_type=action_type,
            annotated_frame_payloads=path_b_payloads,
            provider=provider_path_b,
            frame_bio_context=bio_ctx,
            key_frame_stems=key_stems,
            jump_metrics_text=jump_metrics_text,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            profile_evidence=profile_evidence,
            memory_context=rendered_context,
            skill_category=skill_category,
            video_context_by_frame=video_context_by_frame,
            preserve_all_frames=uses_semantic_keyframes,
        )

    path_a_task = asyncio.create_task(_run_a())
    path_b_task = asyncio.create_task(_run_b())
    try:
        path_b_result = await asyncio.wait_for(path_b_task, timeout=path_b_timeout)
    except asyncio.TimeoutError:
        logger.warning("Path B timeout > %.0fs; continuing with Path A result", path_b_timeout)
        path_b_result = {
            "path": "B",
            "error": "path_b_timeout",
            "timeout_seconds": round(float(path_b_timeout), 3),
            "n_frames": len(path_b_payloads),
            "annotated_frame_count": len(path_b_payloads),
            "frame_analysis": [],
        }
    try:
        path_a_result = await asyncio.wait_for(path_a_task, timeout=total_timeout)
    except asyncio.TimeoutError:
        logger.warning("Path A timeout > %.0fs; using error result", total_timeout)
        path_a_result = {"path": "A", "error": "path_a_timeout"}

    validation = cross_validate(path_a_result, path_b_result)
    weights = compute_blend_weights(validation)
    fusion_diagnostics = validation.fusion_diagnostics

    dual_meta: dict[str, Any] = {
        "overall_agreement_rate": validation.overall_agreement_rate,
        "skeleton_reliability_signal": validation.skeleton_reliability_signal,
        "recommended_path": validation.recommended_path,
        "conflict_fields": validation.conflict_fields,
        "conflict_summary": validation.conflict_summary,
        "weight_a": weights[0],
        "weight_b": weights[1],
        "path_b_subscores": (path_b_result or {}).get("subscores"),
        "path_b_failed": bool(path_b_result and path_b_result.get("error")),
        "path_b_annotation_source": annotation_source,
        "path_b_preserve_all_frames": uses_semantic_keyframes,
        "raw_frame_count": len(raw_frame_payloads),
        "annotated_frame_count": len(path_b_payloads),
        "annotated_frame_count_raw": len(annotated_payloads),
        "fusion_diagnostics": fusion_diagnostics,
        "conflict_level": fusion_diagnostics.get("conflict_level", "none"),
        "downgraded_reasons": fusion_diagnostics.get("downgraded_reasons", []),
        "needs_human_review": bool(fusion_diagnostics.get("needs_human_review", False)),
    }

    return DualPathResult(
        path_a=path_a_result,
        path_b=path_b_result,
        validation=validation,
        blend_weights=weights,
        dual_path_meta=dual_meta,
        annotated_dir=annotated_dir,
        used_key_frames=key_stems,
    )


def dual_path_summary(result: DualPathResult) -> dict[str, Any]:
    """Return a compact JSON-serializable summary for frontend display."""
    validation = result.validation
    return {
        "agreement_rate": validation.overall_agreement_rate,
        "skeleton_signal": validation.skeleton_reliability_signal,
        "recommended": validation.recommended_path,
        "weight_a": result.blend_weights[0],
        "weight_b": result.blend_weights[1],
        "conflict_fields": validation.conflict_fields,
        "summary_text": validation.conflict_summary,
        "path_b_failed": result.dual_path_meta.get("path_b_failed", False),
        "fusion_diagnostics": result.dual_path_meta.get("fusion_diagnostics", {}),
        "conflict_level": result.dual_path_meta.get("conflict_level", "none"),
        "downgraded_reasons": result.dual_path_meta.get("downgraded_reasons", []),
        "needs_human_review": result.dual_path_meta.get("needs_human_review", False),
        "n_frames_a": len(result.path_a.get("frame_analysis") or []),
        "n_frames_b": (result.path_b or {}).get("n_frames", 0),
        "raw_frame_count": result.dual_path_meta.get("raw_frame_count", 0),
        "annotated_frame_count": result.dual_path_meta.get("annotated_frame_count", 0),
    }
