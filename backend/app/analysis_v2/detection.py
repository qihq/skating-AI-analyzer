from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.analysis_v2.contracts import (
    CameraMotion,
    CandidateQuality,
    DetectionProposalDiagnostics,
    TrackCandidate,
    ShortTrackProposal,
)


PERSON_TRACKER_OPTIONS = (
    "PERSON_TRACKER_APPEARANCE_RELOCK", "PERSON_TRACKER_APPEARANCE_RELOCK_THRESHOLD",
    "PERSON_TRACKER_APPEARANCE_RELOCK_SOFT", "PERSON_TRACKER_APPEARANCE_RELOCK_SOFT_FLOOR",
    "PERSON_TRACKER_APPEARANCE_RELOCK_SOFT_WEIGHT", "PERSON_TRACKER_MANUAL_LOCK_SELF_HEAL",
    "PERSON_TRACKER_MANUAL_LOCK_SELF_HEAL_MIN_LOST_FRAMES", "PERSON_TRACKER_LEGACY_MODE",
)


@dataclass(frozen=True)
class DetectionProviderConfig:
    detector: str = "yolo"
    tracker: str = "bytetrack"
    model_source: str = "unknown"
    model_hash: str | None = None
    dependency_ready: bool = False
    legacy_options: tuple[str, ...] = PERSON_TRACKER_OPTIONS

    def fingerprint(self) -> str:
        payload = "|".join((self.detector, self.tracker, self.model_source, self.model_hash or "", str(self.dependency_ready), *self.legacy_options))
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def resolve_provider_config(env: Mapping[str, str] | None = None) -> DetectionProviderConfig:
    values = env or os.environ
    model = values.get("YOLO_PERSON_MODEL_PATH", "").strip()
    source = "mounted" if model and os.path.exists(model) else ("missing" if model else "default")
    model_hash = None
    if model and os.path.isfile(model):
        digest = hashlib.sha256()
        with open(model, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        model_hash = "sha256:" + digest.hexdigest()
    dependency_ready = False
    try:
        import ultralytics  # type: ignore  # noqa: F401
        import supervision as sv  # type: ignore
        import torchvision  # type: ignore  # noqa: F401
        dependency_ready = bool(getattr(sv, "ByteTrack", None) or getattr(sv, "ByteTracker", None))
    except Exception:
        dependency_ready = False
    try:
        from app.services.person_tracker import get_person_tracker_runtime_status
        status = get_person_tracker_runtime_status()
        source_map = {"mounted_default": "mounted", "ultralytics_auto_download": "downloaded", "env": "mounted", "default": "default"}
        source = source_map.get(str(status.get("source")), source)
        if model and not os.path.exists(model):
            source = "missing"
        dependency_ready = bool(status.get("dependencies_ready"))
    except Exception:
        pass
    return DetectionProviderConfig(model_source=source, model_hash=model_hash, dependency_ready=dependency_ready)


def estimate_camera_motion(previous: Sequence[tuple[float, float]], current: Sequence[tuple[float, float]], *, feature_count: int | None = None) -> CameraMotion:
    count = feature_count if feature_count is not None else min(len(previous), len(current))
    if count < 3:
        return CameraMotion(motion_type="unknown", reliability=0.0, feature_count=count, failure_reason="insufficient_background_features")
    dx = sum(current[i][0] - previous[i][0] for i in range(count)) / count
    dy = sum(current[i][1] - previous[i][1] for i in range(count)) / count
    spread = sum(abs((current[i][0] - previous[i][0]) - dx) + abs((current[i][1] - previous[i][1]) - dy) for i in range(count)) / count
    reliability = max(0.0, min(1.0, count / 20.0 * (1.0 - min(1.0, spread / 50.0))))
    motion_type = "shake" if spread > 20 else ("pan" if abs(dx) + abs(dy) > 2 else "static")
    return CameraMotion(transform={"dx": dx, "dy": dy}, motion_type=motion_type, reliability=reliability, feature_count=count, masked_feature_count=count)


def estimate_camera_motion_from_matches(matches: Sequence[tuple[tuple[float, float], tuple[float, float]]], *, masked: int = 0) -> CameraMotion:
    previous = [pair[0] for pair in matches]
    current = [pair[1] for pair in matches]
    result = estimate_camera_motion(previous, current, feature_count=len(matches))
    return result.model_copy(update={"masked_feature_count": max(0, masked), "failure_reason": result.failure_reason if masked >= len(matches) else None})


def preserve_short_tracks(records: Sequence[Mapping[str, Any]], *, source_video_hash: str | None = None) -> tuple[ShortTrackProposal, ...]:
    """Wrap detector records without collapsing crossing or dropout candidates."""
    output: list[ShortTrackProposal] = []
    for index, record in enumerate(records):
        boxes: list[tuple[float, float, float, float]] = []
        for raw in record.get("boxes", ()) if isinstance(record.get("boxes"), Sequence) else ():
            if isinstance(raw, Sequence) and len(raw) == 4:
                boxes.append(tuple(float(value) for value in raw))
        output.append(ShortTrackProposal(candidate_id=str(record.get("candidate_id", f"candidate:{index}")), short_track_id=str(record.get("short_track_id", f"short:{index}")), source_frame_indices=tuple(int(value) for value in record.get("source_frame_indices", ()) if int(value) >= 0), pts_sec=tuple(float(value) for value in record.get("pts_sec", ())), boxes=tuple(boxes), detector_scores=tuple(float(value) for value in record.get("detector_scores", ())), uncertainty=tuple(str(value) for value in record.get("uncertainty", ())), provider_provenance=("yolo", "bytetrack", "source_pts")))
    return tuple(output)


def score_candidate_quality(bbox: tuple[float, float, float, float], image_size: tuple[int, int], *, blur: float = 1.0, crowd_overlap: float = 0.0) -> CandidateQuality:
    width, height = image_size
    x1, y1, x2, y2 = bbox
    area = max(0.0, (x2 - x1) * (y2 - y1)) / max(1.0, width * height)
    clipping = float(x1 <= 0 or y1 <= 0 or x2 >= width or y2 >= height)
    full_body = max(0.0, min(1.0, (y2 - y1) / max(1.0, height) * 2.0))
    small = max(0.0, min(1.0, 1.0 - area * 20.0))
    quality = max(0.0, min(1.0, 0.35 * blur + 0.3 * full_body + 0.2 * (1 - clipping) + 0.15 * (1 - crowd_overlap)))
    strata = "high" if quality >= 0.7 else "medium" if quality >= 0.4 else "low"
    return CandidateQuality(blur=blur, clipping=clipping, full_body_visibility=full_body, crowd_overlap=crowd_overlap, small_target=small, quality_score=quality, strata=strata)


def build_proposal_diagnostics(*, candidates: Sequence[TrackCandidate] = (), short_tracks: Sequence[ShortTrackProposal] = (), camera: Sequence[CameraMotion] = (), config: DetectionProviderConfig | None = None, status: str = "complete") -> DetectionProposalDiagnostics:
    provider = config or resolve_provider_config({})
    ranked = sorted(candidates, key=lambda item: (item.quality_score if item.quality_score is not None else item.detector_score, item.candidate_id), reverse=True)
    fingerprint = hashlib.sha256("|".join(item.canonical_json() for item in ranked).encode()).hexdigest()
    return DetectionProposalDiagnostics(status=status, provider="v2-candidate-provider", detector=provider.detector, tracker=provider.tracker, model_source=provider.model_source, model_hash=provider.model_hash, dependency_ready=provider.dependency_ready, candidates=tuple(ranked), short_tracks=tuple(short_tracks), camera=tuple(camera), anchor_suggestions=tuple(item.candidate_id for item in ranked[:5]), diagnostics_fingerprint="sha256:" + fingerprint, ds918_compatible=True)
