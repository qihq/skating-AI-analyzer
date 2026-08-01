from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

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

    @model_validator(mode="after")
    def valid_size(self) -> "FrameObservation":
        if self.image_size[0] <= 0 or self.image_size[1] <= 0:
            raise ValueError("image_size must be positive")
        return self


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

    @model_validator(mode="after")
    def valid_bbox(self) -> "TrackCandidate":
        x1, y1, x2, y2 = self.bbox
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox must have positive area")
        return self


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
