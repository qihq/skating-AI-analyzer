from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.pilot_evaluator import EventPrediction, PilotPredictionBundle


def build_pilot_prediction_bundle(
    dataset: GoldenDatasetV2,
    analyses_by_source: Mapping[str, Mapping[str, Any]],
    *,
    pipeline_fingerprint: str,
    evaluation_masks: Sequence[str],
) -> PilotPredictionBundle:
    """Adapt safe, source-keyed legacy API fields into the pilot wire contract.

    The adapter deliberately does not copy video paths, frames, labels, or any
    source-specific raw artifact. Missing API rows remain missing predictions.
    """
    predictions: list[EventPrediction] = []
    for event in sorted(dataset.events, key=lambda item: (item.source_sha256, item.event_id)):
        analysis = analyses_by_source.get(event.source_sha256)
        if not isinstance(analysis, Mapping):
            continue
        profile = str(analysis.get("analysis_profile") or "unknown").strip().lower()
        if profile not in {"jump", "spin", "step", "spiral"}:
            profile = "unknown"
        diagnostics = analysis.get("video_temporal_diagnostics")
        diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
        confidence = _profile_confidence(analysis)
        input_payload = {
            "stage_status": _safe_text(analysis.get("status")),
            "provider": _safe_text(diagnostics.get("video_ai_provider")),
            "model": _safe_text(diagnostics.get("video_ai_model")),
            "fallback_reason": _safe_text(diagnostics.get("fallback_reason")),
            "used_semantic_frames": bool(diagnostics.get("used_semantic_frames", False)),
            "used_legacy_sampled_frames": bool(diagnostics.get("used_legacy_sampled_frames", False)),
            "provider_error": _safe_text(analysis.get("error_code")),
        }
        predictions.append(
            EventPrediction.model_validate(
                {
                    "source_sha256": event.source_sha256,
                    "event_id": event.event_id,
                    "predicted_profile": profile,
                    "confidence": confidence,
                    "input_fields": ["legacy.analysis_profile", "legacy.video_temporal_diagnostics"],
                    "input_payload": input_payload,
                }
            )
        )
    return PilotPredictionBundle.model_validate(
        {
            "pipeline_fingerprint": pipeline_fingerprint,
            "evaluation_masks": list(evaluation_masks),
            "predictions": [item.model_dump(mode="json") for item in predictions],
        }
    )


def _profile_confidence(analysis: Mapping[str, Any]) -> float:
    bio = analysis.get("bio_data")
    evidence = bio.get("profile_evidence") if isinstance(bio, Mapping) else None
    value = evidence.get("profile_confidence") if isinstance(evidence, Mapping) else None
    return {"high": 0.8, "medium": 0.6, "low": 0.4}.get(str(value).lower(), 0.2)


def _safe_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
