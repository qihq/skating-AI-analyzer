from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from app.analysis_v2.contracts import TrackCandidate, ShortTrackProposal, CameraMotion
from app.analysis_v2.detection import build_proposal_diagnostics, score_candidate_quality, resolve_provider_config


def _bbox(value: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        x, y = float(value.get("x", 0)), float(value.get("y", 0))
        width, height = float(value.get("width", 0)), float(value.get("height", 0))
        if width <= 0 or height <= 0:
            return None
        return (x, y, x + width, y + height)
    except (TypeError, ValueError):
        return None


def evaluate_pilot12_detection(source: Path) -> dict[str, Any]:
    """Build deterministic candidate/proposal diagnostics from the imported 12-video snapshot.

    This intentionally consumes legacy detector output as a shadow fixture only; it does not
    select an identity or mutate analysis/family fields.
    """
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    proposals: list[dict[str, Any]] = []
    candidate_count = 0
    recall_counts = {"analyses_with_candidates": 0, "analyses_without_candidates": 0, "candidate_tracks": 0, "uncertain_candidates": 0}
    for analysis_id in sorted(payload):
        analysis = payload[analysis_id]
        lock = analysis.get("target_lock") if isinstance(analysis, Mapping) else None
        if not isinstance(lock, Mapping):
            continue
        candidates: list[TrackCandidate] = []
        for index, raw in enumerate(lock.get("candidates") or []):
            box = _bbox(raw.get("bbox") if isinstance(raw, Mapping) else None)
            if box is None:
                continue
            score = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
            quality = score_candidate_quality(box, (1, 1), blur=score)
            candidates.append(TrackCandidate(candidate_id=str(raw.get("id", f"{analysis_id}:candidate:{index}")), bbox=box, detector_score=score, short_track_id=f"{analysis_id}:track:{index}", quality_score=quality.quality_score, uncertainty_reasons=tuple(str(flag) for flag in raw.get("quality_flags", ())), evidence_sources=(str(raw.get("source", "legacy_fixture")),), model_fingerprint=resolve_provider_config({}).fingerprint()))
        candidate_count += len(candidates)
        if candidates:
            recall_counts["analyses_with_candidates"] += 1
        else:
            recall_counts["analyses_without_candidates"] += 1
        recall_counts["candidate_tracks"] += len(candidates)
        recall_counts["uncertain_candidates"] += sum(bool(candidate.uncertainty_reasons) for candidate in candidates)
        short_tracks = tuple(ShortTrackProposal(candidate_id=candidate.candidate_id, short_track_id=candidate.short_track_id or f"{analysis_id}:short:{index}", uncertainty=candidate.uncertainty_reasons, provider_provenance=("legacy_target_lock_candidates", "diagnostic_only")) for index, candidate in enumerate(candidates))
        camera = (CameraMotion(motion_type="unknown", reliability=0.0, failure_reason="background_features_not_recorded_in_legacy_fixture"),)
        diagnostics = build_proposal_diagnostics(candidates=candidates, short_tracks=short_tracks, camera=camera, config=resolve_provider_config({}), status="complete").model_copy(update={"candidate_recall_counts": recall_counts.copy()})
        proposals.append({"analysis_id": analysis_id, "diagnostics": diagnostics.model_dump(mode="json")})
    result = {"schema_version": "iteration7-pilot12-detection-evidence.v1", "fixture": str(source), "analysis_count": len(payload), "candidate_count": candidate_count, "proposal_count": len(proposals), "candidate_recall_counts": recall_counts, "proposals": proposals, "diagnostic_only": True, "identity_decisions": False}
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    result["result_fingerprint"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return result
