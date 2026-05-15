from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from app.services.providers import ActiveProviderConfig
from app.services.video import FramePayload, encode_frames
from app.services.vision_path_a import analyze_path_a
from app.services.vision_path_b import analyze_path_b


logger = logging.getLogger(__name__)

DUAL_PATH_TOTAL_TIMEOUT = 150.0


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
) -> DualPathResult:
    """
    Run dual-path analysis and cross validation.

    Path A keeps the hard-error contract from analyze_frames/analyze_path_a.
    Path B keeps a soft-error contract and returns {"error": "..."} on failure.
    """
    pose_by_stem = build_pose_by_stem(pose_data)
    if annotated_dir is None:
        annotated_dir = (frame_paths[0].parent.parent / "annotated") if frame_paths else Path("/tmp/annotated")

    connections = pose_data.get("connections") if isinstance(pose_data, dict) else None
    annotated_paths = annotate_frames_batch(
        frame_paths,
        pose_by_stem,
        annotated_dir,
        connections=connections if isinstance(connections, list) else None,
    )
    annotated_payloads = await encode_frames(annotated_paths, timestamps=timestamps)

    frame_stems = [payload.frame_id for payload in raw_frame_payloads]
    key_stems = extract_key_frame_stems(bio_data)
    bio_ctx = build_frame_bio_context(bio_data, frame_stems)
    jump_metrics_text = summarize_jump_metrics(bio_data)
    motion_features = _motion_features_for_prompt(frame_motion_scores)

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
            memory_context=memory_context,
            mode="video" if clip_path is not None else "frames",
            clip_path=clip_path,
            window_start_sec=window_start_sec,
        )

    async def _run_b() -> dict[str, Any]:
        return await analyze_path_b(
            action_type=action_type,
            annotated_frame_payloads=annotated_payloads,
            provider=provider_path_b,
            frame_bio_context=bio_ctx,
            key_frame_stems=key_stems,
            jump_metrics_text=jump_metrics_text,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            profile_evidence=profile_evidence,
            memory_context=memory_context,
        )

    try:
        path_a_result, path_b_result = await asyncio.wait_for(
            asyncio.gather(_run_a(), _run_b()),
            timeout=total_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Dual path total timeout > %.0fs, retrying Path A alone", total_timeout)
        path_a_result = await _run_a()
        path_b_result = {"path": "B", "error": "total_timeout"}

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
    }
