from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class FrameObservation(ContractModel):
    schema_version: Literal["frame-observation.v1"] = "frame-observation.v1"
    source_video_hash: str = Field(min_length=1)
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    duration_sec: float = Field(gt=0)
    image_size: tuple[int, int]
    camera_transform: dict[str, float] | None = None
    camera_reliability: float | None = Field(default=None, ge=0, le=1)
    blur_score: float | None = Field(default=None, ge=0, le=1)
    occlusion_context: str | None = None
    pipeline_version: str = Field(min_length=1)
    timing_provenance: Literal["source_pts", "legacy_approximate"] = "source_pts"
    frame_status: Literal["available", "duplicate_pts", "gap_after_previous", "discontinuity", "timestamp_unavailable"] = "available"
    gap_before_sec: float = Field(default=0, ge=0)
    source_image_size: tuple[int, int] | None = None
    tracking_proxy_size: tuple[int, int] | None = None

    @model_validator(mode="after")
    def valid_size(self) -> "FrameObservation":
        if self.image_size[0] <= 0 or self.image_size[1] <= 0:
            raise ValueError("image_size must be positive")
        if self.source_image_size is not None and (self.source_image_size[0] <= 0 or self.source_image_size[1] <= 0):
            raise ValueError("source_image_size must be positive")
        if self.tracking_proxy_size is not None and (self.tracking_proxy_size[0] <= 0 or self.tracking_proxy_size[1] <= 0):
            raise ValueError("tracking_proxy_size must be positive")
        if self.timing_provenance == "source_pts" and self.frame_status == "timestamp_unavailable":
            raise ValueError("timestamp-unavailable observations must be marked approximate")
        return self


class ObservationStream(ContractModel):
    schema_version: Literal["observation-stream.v1"] = "observation-stream.v1"
    source_video_hash: str = Field(min_length=1)
    source_index_fingerprint: str = Field(min_length=1)
    sampling_strategy: Literal["dense_source_order_low_resolution"] = "dense_source_order_low_resolution"
    observations: tuple[FrameObservation, ...] = ()
    exact_timestamps: bool = True

    @model_validator(mode="after")
    def observations_are_ordered(self) -> "ObservationStream":
        indexes = [item.source_frame_index for item in self.observations]
        if indexes != sorted(indexes):
            raise ValueError("observation stream must preserve source order")
        if any(item.source_video_hash != self.source_video_hash for item in self.observations):
            raise ValueError("observation source hashes must match stream")
        if self.exact_timestamps and any(item.timing_provenance != "source_pts" for item in self.observations):
            raise ValueError("exact observation streams cannot contain approximate timestamps")
        return self


class PhysicalMetricInput(ContractModel):
    """Timestamp-only input for V2 physical calculations."""

    observations: tuple[FrameObservation, ...] = Field(min_length=1)
    required_timestamp_status: Literal["exact"] = "exact"

    @model_validator(mode="after")
    def requires_exact_timestamps(self) -> "PhysicalMetricInput":
        if any(item.timing_provenance != "source_pts" or item.frame_status == "timestamp_unavailable" for item in self.observations):
            raise ValueError("physical metrics require exact source PTS observations")
        return self


def reject_legacy_physical_payload(payload: Mapping[str, Any]) -> None:
    forbidden = {"effective_fps", "sampled_frame_count", "average_fps", "frame_count"} & set(payload)
    if forbidden:
        raise ValueError("V2 physical metrics cannot accept sampled-frame or FPS-only timing: " + ", ".join(sorted(forbidden)))


def observation_stream_from_source_index(index: Any, *, pipeline_version: str, proxy_size: tuple[int, int]) -> ObservationStream:
    """Create the dense tracking stream from the canonical source index."""
    observations = tuple(
        FrameObservation(
            source_video_hash=index.source_video_hash,
            source_frame_index=frame.source_frame_index,
            pts_sec=frame.pts_sec if frame.pts_sec is not None else 0.0,
            duration_sec=frame.duration_sec or 0.000001,
            image_size=proxy_size,
            source_image_size=frame.image_size or (index.width, index.height),
            tracking_proxy_size=proxy_size,
            pipeline_version=pipeline_version,
            timing_provenance="source_pts" if frame.pts_sec is not None and index.timestamp_status == "exact" else "legacy_approximate",
            frame_status=frame.status,
            gap_before_sec=frame.gap_before_sec,
        )
        for frame in index.frames
    )
    return ObservationStream(
        source_video_hash=index.source_video_hash,
        source_index_fingerprint=index.fingerprint(),
        observations=observations,
        exact_timestamps=index.exact,
    )


class TrackCandidate(ContractModel):
    schema_version: Literal["track-candidate.v1"] = "track-candidate.v1"
    candidate_id: str = Field(min_length=1)
    bbox: tuple[float, float, float, float]
    detector_score: float = Field(ge=0, le=1)
    short_track_id: str | None = None
    appearance_features: tuple[float, ...] | None = None
    pose_shape_features: tuple[float, ...] | None = None
    camera_compensated_motion: tuple[float, float] | None = None
    evidence_sources: tuple[str, ...] = ()
    quality_score: float | None = Field(default=None, ge=0, le=1)
    uncertainty_reasons: tuple[str, ...] = ()
    source_video_hash: str | None = None
    source_frame_index: int | None = Field(default=None, ge=0)
    pts_sec: float | None = Field(default=None, ge=0)
    provider_version: str = "candidate-provider.v1"
    model_fingerprint: str | None = None

    @model_validator(mode="after")
    def valid_bbox(self) -> "TrackCandidate":
        x1, y1, x2, y2 = self.bbox
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox must have positive area")
        return self


class CameraMotion(ContractModel):
    schema_version: Literal["camera-motion.v1"] = "camera-motion.v1"
    transform: dict[str, float] = Field(default_factory=dict)
    motion_type: Literal["static", "pan", "zoom", "shake", "mixed", "unknown"] = "unknown"
    reliability: float = Field(ge=0, le=1)
    feature_count: int = Field(default=0, ge=0)
    masked_feature_count: int = Field(default=0, ge=0)
    failure_reason: str | None = None


class CandidateQuality(ContractModel):
    schema_version: Literal["candidate-quality.v1"] = "candidate-quality.v1"
    blur: float = Field(ge=0, le=1)
    clipping: float = Field(ge=0, le=1)
    full_body_visibility: float = Field(ge=0, le=1)
    crowd_overlap: float = Field(ge=0, le=1)
    small_target: float = Field(ge=0, le=1)
    quality_score: float = Field(ge=0, le=1)
    strata: Literal["high", "medium", "low"]


class ShortTrackProposal(ContractModel):
    schema_version: Literal["short-track-proposal.v1"] = "short-track-proposal.v1"
    candidate_id: str = Field(min_length=1)
    short_track_id: str = Field(min_length=1)
    source_frame_indices: tuple[int, ...] = ()
    pts_sec: tuple[float, ...] = ()
    boxes: tuple[tuple[float, float, float, float], ...] = ()
    detector_scores: tuple[float, ...] = ()
    uncertainty: tuple[str, ...] = ()
    quality: CandidateQuality | None = None
    camera_motion: CameraMotion | None = None
    provider_provenance: tuple[str, ...] = ()


class DetectionProposalDiagnostics(ContractModel):
    schema_version: Literal["detection-proposal-diagnostics.v1"] = "detection-proposal-diagnostics.v1"
    status: Literal["not_run", "running", "unavailable", "failed", "complete"] = "not_run"
    provider: str = "unconfigured"
    detector: str = "unconfigured"
    tracker: str = "unconfigured"
    model_source: Literal["mounted", "default", "downloaded", "missing", "unknown"] = "unknown"
    model_hash: str | None = None
    dependency_ready: bool = False
    candidates: tuple[TrackCandidate, ...] = ()
    short_tracks: tuple[ShortTrackProposal, ...] = ()
    camera: tuple[CameraMotion, ...] = ()
    anchor_suggestions: tuple[str, ...] = ()
    candidate_recall: float | None = Field(default=None, ge=0, le=1)
    diagnostics_fingerprint: str = "unavailable"
    invalidation_scope: str = "shadow_diagnostics_only"
    ds918_compatible: bool | None = None
    candidate_recall_counts: dict[str, int] = Field(default_factory=dict)


class TrackState(ContractModel):
    schema_version: Literal["track-state.v1"] = "track-state.v1"
    state: Literal["confirmed", "uncertain", "lost"]
    bbox: tuple[float, float, float, float] | None = None
    identity_score: float = Field(ge=0, le=1)
    identity_margin: float | None = Field(default=None, ge=0, le=1)
    candidate_ids: tuple[str, ...] = ()
    bbox_source: Literal["measured", "stale", "fallback", "none"] = "measured"
    occlusion_state: str | None = None
    template_update_allowed: bool = False
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_state(self) -> "TrackState":
        if self.state == "confirmed":
            if self.bbox is None:
                raise ValueError("confirmed track requires bbox")
            x1, y1, x2, y2 = self.bbox
            if x2 <= x1 or y2 <= y1:
                raise ValueError("confirmed bbox must have positive area")
            if self.bbox_source in {"stale", "fallback", "none"}:
                raise ValueError("confirmed track cannot use stale/fallback bbox")
        return self


class IdentityFeatureReliability(ContractModel):
    """Reliability is recorded per signal so no single cue can take over."""

    schema_version: Literal["identity-feature-reliability.v1"] = "identity-feature-reliability.v1"
    appearance: float = Field(default=0, ge=0, le=1)
    body_shape: float = Field(default=0, ge=0, le=1)
    camera_motion: float = Field(default=0, ge=0, le=1)
    bbox_continuity: float = Field(default=0, ge=0, le=1)
    face: float = Field(default=0, ge=0, le=1)


class IdentityAnchor(ContractModel):
    schema_version: Literal["identity-anchor.v1"] = "identity-anchor.v1"
    anchor_id: str = Field(min_length=1)
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    bbox: tuple[float, float, float, float]
    provenance: Literal["manual", "manual_revision"] = "manual"
    revision: int = Field(default=1, ge=1)
    annotator: str = Field(min_length=1)
    quality_score: float = Field(ge=0, le=1)
    template_fingerprint: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_bbox(self) -> "IdentityAnchor":
        x1, y1, x2, y2 = self.bbox
        if x2 <= x1 or y2 <= y1:
            raise ValueError("identity anchor bbox must have positive area")
        return self


class IdentityEvidence(ContractModel):
    schema_version: Literal["identity-evidence.v1"] = "identity-evidence.v1"
    candidate_id: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    reliability: IdentityFeatureReliability = Field(default_factory=IdentityFeatureReliability)
    signal_scores: dict[str, float] = Field(default_factory=dict)
    reasons: tuple[str, ...] = ()


class IdentityTimelineSegment(ContractModel):
    schema_version: Literal["identity-timeline-segment.v1"] = "identity-timeline-segment.v1"
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    state: Literal["confirmed", "uncertain", "lost"]
    track_state: TrackState
    best_candidate_id: str | None = None
    second_candidate_id: str | None = None
    evidence: tuple[IdentityEvidence, ...] = ()
    direction: Literal["forward", "backward", "fused"] = "fused"
    conflict: bool = False
    template_update_frozen: bool = True
    bbox_is_display_hint: bool = False

    @model_validator(mode="after")
    def safe_state(self) -> "IdentityTimelineSegment":
        if self.state == "confirmed" and (self.track_state.state != "confirmed" or self.bbox_is_display_hint):
            raise ValueError("confirmed identity requires an authoritative measured track")
        if self.state != "confirmed" and self.track_state.state == "confirmed":
            raise ValueError("uncertain/lost identity cannot contain confirmed track state")
        if self.conflict and self.state == "confirmed":
            raise ValueError("identity conflicts must remain uncertain")
        return self


class IdentityConflictInterval(ContractModel):
    schema_version: Literal["identity-conflict-interval.v1"] = "identity-conflict-interval.v1"
    start_pts_sec: float = Field(ge=0)
    end_pts_sec: float = Field(ge=0)
    reason: Literal["forward_backward_conflict", "low_margin", "crossing", "false_relock", "recovery"]
    frame_indices: tuple[int, ...] = ()
    candidate_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def ordered(self) -> "IdentityConflictInterval":
        if self.end_pts_sec < self.start_pts_sec:
            raise ValueError("identity conflict interval must be ordered")
        return self


class IdentityAnchorRevision(ContractModel):
    schema_version: Literal["identity-anchor-revision.v1"] = "identity-anchor-revision.v1"
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    anchor_ids: tuple[str, ...] = ()
    invalidated_intervals: tuple[tuple[float, float], ...] = ()
    created_by: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    provenance: Literal["manual_confirmation", "additional_anchor", "system_relock"]


class IdentityTimeline(ContractModel):
    schema_version: Literal["identity-timeline.v1"] = "identity-timeline.v1"
    identity_id: str = Field(min_length=1)
    state: Literal["confirmed", "uncertain", "lost"]
    segments: tuple[IdentityTimelineSegment, ...] = ()
    anchors: tuple[IdentityAnchor, ...] = ()
    anchor_revisions: tuple[IdentityAnchorRevision, ...] = ()
    conflicts: tuple[IdentityConflictInterval, ...] = ()
    confirmed_coverage: float = Field(default=0, ge=0, le=1)
    uncertain_coverage: float = Field(default=0, ge=0, le=1)
    lost_coverage: float = Field(default=0, ge=0, le=1)
    longest_lost_interval_sec: float = Field(default=0, ge=0)
    recommended_review_task: str | None = None
    diagnostic_only: bool = True

    @model_validator(mode="after")
    def coverage_is_bounded(self) -> "IdentityTimeline":
        if self.confirmed_coverage + self.uncertain_coverage + self.lost_coverage > 1.000001:
            raise ValueError("identity coverage totals cannot exceed one")
        return self


class JointObservation(ContractModel):
    x: float
    y: float
    confidence: float = Field(ge=0, le=1)
    provenance: Literal["measured", "smoothed", "interpolated", "missing"]
    source: Literal["measured", "smoothed", "interpolated", "missing"] | None = None
    coordinate_space: Literal["normalized", "pixel"] = "normalized"

    @model_validator(mode="after")
    def valid_provenance(self) -> "JointObservation":
        if self.source is not None and self.provenance == "interpolated" and self.source == "measured":
            raise ValueError("interpolated joint cannot claim measured source")
        if self.provenance == "missing" and self.confidence != 0:
            raise ValueError("missing joint confidence must be zero")
        return self


class PoseObservation(ContractModel):
    schema_version: Literal["pose-observation.v1"] = "pose-observation.v1"
    source_video_hash: str = Field(min_length=1)
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    track_state: TrackState
    joints: dict[str, JointObservation]
    person_scale: float | None = Field(default=None, gt=0)
    temporal_gap_sec: float = Field(default=0, ge=0)
    pose_quality: float | None = Field(default=None, ge=0, le=1)
    jitter_score: float | None = Field(default=None, ge=0, le=1)


class ActionEvent(ContractModel):
    schema_version: Literal["action-event.v1"] = "action-event.v1"
    event_id: str = Field(min_length=1)
    profile: Literal["jump", "spin", "step", "spiral", "unknown"]
    start_pts_sec: float = Field(ge=0)
    end_pts_sec: float = Field(ge=0)
    proposal_source: str | None = None
    proposal_score: float | None = Field(default=None, ge=0, le=1)
    classifier_evidence: tuple[str, ...] = ()
    tracking_coverage: float | None = Field(default=None, ge=0, le=1)
    pose_coverage: float | None = Field(default=None, ge=0, le=1)
    observability: Literal["observed", "partial", "unobservable"]
    confidence: float = Field(ge=0, le=1)
    calibration_version: str | None = None

    @model_validator(mode="after")
    def ordered_interval(self) -> "ActionEvent":
        if self.end_pts_sec < self.start_pts_sec:
            raise ValueError("event interval must be ordered")
        if self.observability == "unobservable" and self.confidence > 0:
            raise ValueError("unobservable event confidence must be zero")
        return self


class KeyMoment(ContractModel):
    schema_version: Literal["key-moment.v1"] = "key-moment.v1"
    event_id: str = Field(min_length=1)
    semantic_key: str = Field(min_length=1)
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    definition_version: str = Field(min_length=1)
    candidate_evidence: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)
    warnings: tuple[str, ...] = ()
    observability: Literal["observed", "partial", "unobservable"]


class RotationEstimate(ContractModel):
    schema_version: Literal["rotation-estimate.v1"] = "rotation-estimate.v1"
    pre_takeoff_rotation: float | None = None
    airborne_rotation: float | None = None
    post_landing_continuation: float | None = None
    total_observed_rotation: float | None = None
    rotation_class: str | None = None
    convention: Literal["axel", "non_axel", "unknown"] = "unknown"
    signal_estimates: dict[str, float] = {}
    reliability: float | None = Field(default=None, ge=0, le=1)
    fused_estimate: float | None = None
    fused_interval: tuple[float, float] | None = None
    observability: Literal["observed", "partial", "unobservable"] = "unobservable"
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def valid_interval(self) -> "RotationEstimate":
        if self.fused_interval is not None and self.fused_interval[1] < self.fused_interval[0]:
            raise ValueError("rotation interval must be ordered")
        if self.observability == "unobservable" and self.fused_estimate is not None:
            raise ValueError("unobservable rotation cannot have fused estimate")
        return self


class EvidenceClaim(ContractModel):
    schema_version: Literal["evidence-claim.v1"] = "evidence-claim.v1"
    claim_type: str = Field(min_length=1)
    value: Any
    sources: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)
    observability: Literal["observed", "partial", "unobservable"]
    status: Literal["confirmed", "uncertain", "unobservable"]
    model_fingerprint: str | None = None
    configuration_fingerprint: str | None = None
    prompt_fingerprint: str | None = None
    contract_version: str = "contracts.v1"

    @model_validator(mode="after")
    def valid_status(self) -> "EvidenceClaim":
        if self.status == "unobservable" and self.confidence != 0:
            raise ValueError("unobservable claim confidence must be zero")
        return self


def adapt_legacy_sampled_frames(
    records: Sequence[Mapping[str, Any]],
    *,
    source_video_hash: str,
    pipeline_version: str,
) -> tuple[FrameObservation, ...]:
    """Convert legacy sampled-frame metadata for shadow comparison only."""
    output = []
    for fallback_index, record in enumerate(records):
        output.append(
            FrameObservation(
                source_video_hash=source_video_hash,
                source_frame_index=int(record.get("frame_index", fallback_index)),
                pts_sec=max(0.0, float(record.get("timestamp", record.get("pts", 0.0)))),
                duration_sec=max(0.000001, float(record.get("duration", 1 / 30))),
                image_size=(int(record.get("width", 1)), int(record.get("height", 1))),
                pipeline_version=pipeline_version,
                timing_provenance="legacy_approximate",
            )
        )
    return tuple(output)


def adapt_legacy_track_states(records: Sequence[Mapping[str, Any]]) -> tuple[TrackState, ...]:
    output = []
    for record in records:
        raw_bbox = record.get("bbox")
        bbox = tuple(float(value) for value in raw_bbox) if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4 else None
        output.append(
            TrackState(
                state="uncertain" if bbox is not None else "lost",
                bbox=bbox,
                identity_score=max(0.0, min(1.0, float(record.get("confidence", 0.0)))),
                bbox_source="measured" if bbox is not None else "none",
                reasons=("legacy_shadow_adapter",),
            )
        )
    return tuple(output)


def adapt_legacy_pose_observations(
    records: Sequence[Mapping[str, Any]],
    *,
    source_video_hash: str,
    tracks: Sequence[TrackState] = (),
) -> tuple[PoseObservation, ...]:
    output = []
    for index, record in enumerate(records):
        raw_joints = record.get("joints") if isinstance(record.get("joints"), Mapping) else {}
        joints = {
            str(name): JointObservation(
                x=float(value.get("x", 0.0)),
                y=float(value.get("y", 0.0)),
                confidence=max(0.0, min(1.0, float(value.get("confidence", 0.0)))),
                provenance="measured",
                source="measured",
            )
            for name, value in raw_joints.items()
            if isinstance(value, Mapping)
        }
        track = tracks[index] if index < len(tracks) else TrackState(
            state="lost", identity_score=0.0, bbox_source="none", reasons=("legacy_shadow_adapter",)
        )
        output.append(
            PoseObservation(
                source_video_hash=source_video_hash,
                source_frame_index=int(record.get("frame_index", index)),
                pts_sec=max(0.0, float(record.get("timestamp", record.get("pts", 0.0)))),
                track_state=track,
                joints=joints,
            )
        )
    return tuple(output)


def adapt_legacy_key_moments(
    key_frames: Mapping[str, Any],
    timestamps: Mapping[str, Any],
    *,
    event_id: str,
) -> tuple[KeyMoment, ...]:
    output = []
    for semantic_key in sorted(set(key_frames) | set(timestamps)):
        frame_id = str(key_frames.get(semantic_key, ""))
        match = re.search(r"(\d+)$", frame_id)
        output.append(
            KeyMoment(
                event_id=event_id,
                semantic_key=semantic_key,
                source_frame_index=int(match.group(1)) if match else 0,
                pts_sec=max(0.0, float(timestamps.get(semantic_key, 0.0))),
                definition_version="legacy-key-moment.v1",
                confidence=0.5,
                warnings=("legacy_approximate_timing",),
                observability="partial",
            )
        )
    return tuple(output)
