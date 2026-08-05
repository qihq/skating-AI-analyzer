from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


GOLDEN_DATASET_SCHEMA_VERSION = "golden-dataset.v2"
GOLDEN_SUPPORTED_SCHEMA_VERSIONS = (GOLDEN_DATASET_SCHEMA_VERSION,)

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=160)]


class GoldenContractError(ValueError):
    """Raised when a Golden V2 document cannot be safely interpreted."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenRevisionMetadata(_StrictModel):
    revision: int = Field(ge=1)
    schema_version: Literal["golden-dataset.v2"] = GOLDEN_DATASET_SCHEMA_VERSION
    annotator_alias: ShortText
    provenance: Literal["created", "human_annotation", "migration", "repair"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parent_revision: int | None = Field(default=None, ge=1)
    change_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def revision_has_valid_parent(self) -> "GoldenRevisionMetadata":
        if self.parent_revision is not None and self.parent_revision >= self.revision:
            raise ValueError("parent_revision must be less than revision")
        if self.revision == 1 and self.parent_revision is not None:
            raise ValueError("initial revision cannot have a parent_revision")
        if self.revision > 1 and self.parent_revision != self.revision - 1:
            raise ValueError("revisions must advance from the immediate prior revision")
        return self


class SourceTimebase(_StrictModel):
    numerator: int = Field(gt=0)
    denominator: int = Field(gt=0)
    source_fps: float | None = Field(default=None, gt=0, le=1_000)
    is_vfr: bool


class GoldenSourceVideo(_StrictModel):
    source_sha256: Sha256
    duration_pts: float = Field(gt=0)
    width: int = Field(gt=0, le=20_000)
    height: int = Field(gt=0, le=20_000)
    timebase: SourceTimebase
    private_source_reference: ShortText
    recording_session_id: Identifier
    grouping_id: Identifier
    redacted_alias: ShortText
    perceptual_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{16,128}$")
    source_frame_count: int | None = Field(default=None, ge=1)
    average_fps: float | None = Field(default=None, gt=0, le=1_000)
    nominal_fps: float | None = Field(default=None, gt=0, le=1_000)
    display_rotation_degrees: Literal[0, 90, 180, 270] = 0
    source_timeline: dict[str, object] | None = None


class SourceMoment(_StrictModel):
    pts: float = Field(ge=0)
    source_frame_index: int | None = Field(default=None, ge=0)


class PhaseInterval(_StrictModel):
    start_pts: float = Field(ge=0)
    end_pts: float = Field(ge=0)

    @model_validator(mode="after")
    def time_order_is_valid(self) -> "PhaseInterval":
        if self.end_pts <= self.start_pts:
            raise ValueError("phase end_pts must be after start_pts")
        return self


class RotationLabel(_StrictModel):
    schema_version: Literal["rotation-label.v2"] = "rotation-label.v2"
    observed_turns_min: float = Field(ge=0, le=12)
    observed_turns_max: float = Field(ge=0, le=12)
    reported_turns: float | None = Field(default=None, ge=0, le=12)
    convention: Literal["axel_includes_forward_takeoff", "non_axel_airborne", "unknown"]
    observability: Literal["observable", "uncertain", "unobservable"]
    definition: Literal["airborne_body_rotation", "competition_naming", "observed_spin_rotation"] | None = None
    status: Literal["exact", "range", "unobservable"] | None = None
    value_turns: float | None = Field(default=None, ge=0, le=12)
    range_turns: tuple[float, float] | None = None
    review_start_pts: float | None = Field(default=None, ge=0)
    review_end_pts: float | None = Field(default=None, ge=0)
    review_method: Literal["source_frame_step"] = "source_frame_step"

    @model_validator(mode="after")
    def rotation_range_is_consistent(self) -> "RotationLabel":
        if self.observed_turns_max < self.observed_turns_min:
            raise ValueError("rotation maximum must not be lower than minimum")
        if self.reported_turns is not None and not (
            self.observed_turns_min <= self.reported_turns <= self.observed_turns_max
        ):
            raise ValueError("reported_turns must be inside the observed rotation range")
        if self.observability == "unobservable" and self.reported_turns is not None:
            raise ValueError("unobservable rotation cannot report an exact turn count")
        definition = self.definition
        if definition is None:
            definition = "competition_naming" if self.convention == "axel_includes_forward_takeoff" else "airborne_body_rotation"
            object.__setattr__(self, "definition", definition)
        if self.convention == "axel_includes_forward_takeoff" and definition != "competition_naming":
            raise ValueError("Axel competition naming cannot be stored as airborne body rotation")
        if self.convention == "non_axel_airborne" and definition != "airborne_body_rotation":
            raise ValueError("non-Axel airborne labels require the airborne body rotation definition")
        status = self.status
        if status is None:
            status = "unobservable" if self.observability == "unobservable" else "exact" if self.reported_turns is not None and self.observed_turns_min == self.observed_turns_max else "range"
            object.__setattr__(self, "status", status)
        if status == "exact":
            value = self.value_turns if self.value_turns is not None else self.reported_turns
            if value is None or self.observability != "observable" or self.observed_turns_min != self.observed_turns_max:
                raise ValueError("exact rotation labels require one clear observed value")
            object.__setattr__(self, "value_turns", value)
            if self.range_turns is not None:
                raise ValueError("exact rotation labels cannot carry a range")
        elif status == "range":
            interval = self.range_turns or (self.observed_turns_min, self.observed_turns_max)
            if interval[0] < 0 or interval[1] < interval[0] or interval[0] == interval[1] or self.observability == "unobservable":
                raise ValueError("partial rotation labels require an ordered non-zero interval")
            object.__setattr__(self, "range_turns", interval)
            object.__setattr__(self, "value_turns", None)
            object.__setattr__(self, "reported_turns", None)
        else:
            if self.observability != "unobservable" or self.value_turns is not None or self.range_turns is not None:
                raise ValueError("unobservable rotation labels cannot carry values")
            object.__setattr__(self, "reported_turns", None)
        if (self.review_start_pts is None) != (self.review_end_pts is None):
            raise ValueError("rotation review interval requires both source PTS endpoints")
        if self.review_start_pts is not None and self.review_end_pts is not None and self.review_end_pts <= self.review_start_pts:
            raise ValueError("rotation review interval must be ordered")
        return self


class JumpEventDetails(_StrictModel):
    takeoff: SourceMoment | None = None
    apex: SourceMoment | None = None
    landing: SourceMoment | None = None
    rotation: RotationLabel | None = None

    @model_validator(mode="after")
    def jump_moments_are_ordered(self) -> "JumpEventDetails":
        moments = [self.takeoff, self.apex, self.landing]
        pts = [moment.pts for moment in moments if moment is not None]
        if pts != sorted(pts) or len(pts) != len(set(pts)):
            raise ValueError("jump T/A/L moments must be strictly ordered")
        return self


class SpinEventDetails(_StrictModel):
    entry: PhaseInterval | None = None
    main: PhaseInterval | None = None
    exit: PhaseInterval | None = None
    rotation: RotationLabel | None = None

    @model_validator(mode="after")
    def spin_phases_are_ordered(self) -> "SpinEventDetails":
        phases = [phase for phase in (self.entry, self.main, self.exit) if phase is not None]
        for previous, current in zip(phases, phases[1:]):
            if current.start_pts < previous.end_pts:
                raise ValueError("spin entry, main, and exit phases must not overlap")
        return self


class IntervalEventDetails(_StrictModel):
    phase: PhaseInterval | None = None
    representative_moment: SourceMoment | None = None

    @model_validator(mode="after")
    def representative_moment_is_in_phase(self) -> "IntervalEventDetails":
        if self.representative_moment is not None and self.phase is None:
            raise ValueError("representative moment requires a phase interval")
        if self.phase is not None and self.representative_moment is not None:
            if not self.phase.start_pts <= self.representative_moment.pts <= self.phase.end_pts:
                raise ValueError("representative moment must be inside its phase")
        return self


class ChallengeInterval(_StrictModel):
    start_pts: float = Field(ge=0)
    end_pts: float = Field(ge=0)
    category: Literal["crossing", "occlusion", "relock", "exit_reentry", "blur", "compression", "unknown"]
    observability: Literal["observable", "uncertain", "unobservable"]

    @model_validator(mode="after")
    def challenge_time_order_is_valid(self) -> "ChallengeInterval":
        if self.end_pts <= self.start_pts:
            raise ValueError("challenge end_pts must be after start_pts")
        return self


class GoldenEventLabel(_StrictModel):
    event_id: Identifier
    source_sha256: Sha256
    start_pts: float = Field(ge=0)
    end_pts: float = Field(ge=0)
    profile: Literal["jump", "spin", "step", "spiral", "unknown"]
    subtype: ShortText | None = None
    strata: list[ShortText] = Field(default_factory=list, max_length=24)
    observability: Literal["observable", "uncertain", "unobservable"]
    ambiguity_tags: list[ShortText] = Field(default_factory=list, max_length=24)
    failure_tags: list[ShortText] = Field(default_factory=list, max_length=24)
    annotator_confidence: float = Field(ge=0, le=1)
    main_skater_confirmed: bool
    split: Literal["development", "validation", "frozen_test"] | None = None
    challenge_intervals: list[ChallengeInterval] = Field(default_factory=list, max_length=32)
    jump: JumpEventDetails | None = None
    spin: SpinEventDetails | None = None
    step: IntervalEventDetails | None = None
    spiral: IntervalEventDetails | None = None
    revision: GoldenRevisionMetadata
    # Each confirmed field is independently auditable even when one save updates several fields.
    field_revisions: dict[str, GoldenRevisionMetadata] = Field(default_factory=dict)

    @model_validator(mode="after")
    def event_is_self_consistent(self) -> "GoldenEventLabel":
        if self.end_pts <= self.start_pts:
            raise ValueError("event end_pts must be after start_pts")
        profile_details = {"jump": self.jump, "spin": self.spin, "step": self.step, "spiral": self.spiral}
        if self.profile in profile_details:
            if any(value is not None for key, value in profile_details.items() if key != self.profile):
                raise ValueError("event details must match its profile")
        elif any(value is not None for value in profile_details.values()):
            raise ValueError("unknown events cannot carry profile-specific details")
        if self.observability == "unobservable" and any(value is not None for value in profile_details.values()):
            raise ValueError("unobservable events cannot fabricate profile-specific labels")
        self._validate_event_window()
        return self

    def _validate_event_window(self) -> None:
        moments: list[SourceMoment] = []
        intervals: list[PhaseInterval] = []
        if self.jump:
            moments.extend(value for value in (self.jump.takeoff, self.jump.apex, self.jump.landing) if value)
            if self.jump.rotation and self.jump.rotation.review_start_pts is not None and self.jump.rotation.review_end_pts is not None:
                intervals.append(PhaseInterval(start_pts=self.jump.rotation.review_start_pts, end_pts=self.jump.rotation.review_end_pts))
        if self.spin:
            intervals.extend(value for value in (self.spin.entry, self.spin.main, self.spin.exit) if value)
            if self.spin.rotation and self.spin.rotation.review_start_pts is not None and self.spin.rotation.review_end_pts is not None:
                intervals.append(PhaseInterval(start_pts=self.spin.rotation.review_start_pts, end_pts=self.spin.rotation.review_end_pts))
        for detail in (self.step, self.spiral):
            if detail:
                if detail.phase:
                    intervals.append(detail.phase)
                if detail.representative_moment:
                    moments.append(detail.representative_moment)
        if any(not self.start_pts <= moment.pts <= self.end_pts for moment in moments):
            raise ValueError("event moment must be inside the event interval")
        if any(interval.start_pts < self.start_pts or interval.end_pts > self.end_pts for interval in intervals):
            raise ValueError("event phase must be inside the event interval")
        if any(
            interval.start_pts < self.start_pts or interval.end_pts > self.end_pts
            for interval in self.challenge_intervals
        ):
            raise ValueError("challenge interval must be inside the event interval")


class NormalizedBBox(_StrictModel):
    left: float = Field(ge=0, le=1)
    top: float = Field(ge=0, le=1)
    right: float = Field(ge=0, le=1)
    bottom: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def bbox_has_area(self) -> "NormalizedBBox":
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("bounding box must have positive normalized area")
        return self


class GoldenTrackLabel(_StrictModel):
    label_id: Identifier
    event_id: Identifier
    source_sha256: Sha256
    source_frame_index: int | None = Field(default=None, ge=0)
    pts: float = Field(ge=0)
    bbox: NormalizedBBox
    state: Literal["confirmed", "uncertain", "lost"]
    revision: GoldenRevisionMetadata


class PoseJointLabel(_StrictModel):
    joint: Literal[
        "nose", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
        "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
    ]
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    visibility: float = Field(ge=0, le=1)


class GoldenPoseLabel(_StrictModel):
    label_id: Identifier
    event_id: Identifier
    source_sha256: Sha256
    source_frame_index: int | None = Field(default=None, ge=0)
    pts: float = Field(ge=0)
    joints: list[PoseJointLabel] = Field(min_length=1, max_length=13)
    observability: Literal["observable", "uncertain", "unobservable"]
    revision: GoldenRevisionMetadata

    @model_validator(mode="after")
    def pose_joints_are_unique_and_observable(self) -> "GoldenPoseLabel":
        names = [joint.joint for joint in self.joints]
        if len(names) != len(set(names)):
            raise ValueError("pose joints must not be duplicated")
        if self.observability == "unobservable":
            raise ValueError("unobservable pose labels must be omitted instead of fabricated")
        return self


class GoldenDatasetV2(_StrictModel):
    dataset_id: Identifier
    schema_version: Literal["golden-dataset.v2"] = GOLDEN_DATASET_SCHEMA_VERSION
    revision: GoldenRevisionMetadata
    sources: list[GoldenSourceVideo] = Field(default_factory=list, max_length=500)
    events: list[GoldenEventLabel] = Field(default_factory=list, max_length=1_000)
    tracks: list[GoldenTrackLabel] = Field(default_factory=list, max_length=20_000)
    poses: list[GoldenPoseLabel] = Field(default_factory=list, max_length=5_000)

    @model_validator(mode="after")
    def dataset_references_are_consistent(self) -> "GoldenDatasetV2":
        source_ids = [source.source_sha256 for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source SHA-256 values must be unique")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event IDs must be unique")
        source_by_hash = {source.source_sha256: source for source in self.sources}
        events_by_id = {event.event_id: event for event in self.events}
        label_ids = [label.label_id for label in [*self.tracks, *self.poses]]
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("track and pose label IDs must be unique")
        for event in self.events:
            source = source_by_hash.get(event.source_sha256)
            if source is None:
                raise ValueError("event references an unknown source")
            if event.end_pts > source.duration_pts:
                raise ValueError("event exceeds source duration")
        for label in [*self.tracks, *self.poses]:
            event = events_by_id.get(label.event_id)
            if event is None or label.source_sha256 != event.source_sha256:
                raise ValueError("track and pose labels must reference their event source")
            if not event.start_pts <= label.pts <= event.end_pts:
                raise ValueError("track and pose labels must be inside their event")
        return self
