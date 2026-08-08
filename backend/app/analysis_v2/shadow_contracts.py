from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SHADOW_SCHEMA_VERSION = "shadow-orchestration.v1"
SHADOW_RUN_SCHEMA_VERSION = "shadow-run.v1"
SHADOW_STAGES: tuple[str, ...] = (
    "timebase",
    "observations",
    "candidates",
    "identity",
    "pose",
    "events",
    "moments",
    "rotation",
    "path_reviews",
    "claims",
)

StageName = Literal[
    "timebase",
    "observations",
    "candidates",
    "identity",
    "pose",
    "events",
    "moments",
    "rotation",
    "path_reviews",
    "claims",
]
StageStatus = Literal[
    "pending",
    "queued",
    "running",
    "complete",
    "failed",
    "invalid",
    "skipped",
]
RunStatus = Literal[
    "disabled",
    "queued",
    "running",
    "complete",
    "partial",
    "failed",
    "invalid",
    "cancelled",
]
DiffStatus = Literal[
    "unchanged",
    "different",
    "unexplained",
    "excluded",
    "incompatible",
    "unavailable",
]
ReviewDecisionKind = Literal[
    "accept_shadow",
    "reject_shadow",
    "defer",
    "promote_candidate",
]
DownstreamImpactKind = Literal["would_change", "excluded", "incompatible", "unchanged"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ShadowStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShadowRunRequest(ShadowStrictModel):
    analysis_id: str = Field(min_length=1, max_length=160)
    source_fingerprint: str | None = Field(default=None, max_length=256)
    source_video_hash: str | None = Field(default=None, max_length=256)
    model_fingerprint: str | None = Field(default=None, max_length=256)
    config_fingerprint: str | None = Field(default=None, max_length=256)
    prompt_fingerprint: str | None = Field(default=None, max_length=256)
    contract_fingerprint: str | None = Field(default=None, max_length=256)
    # Optional sanitized baseline fingerprints.  These are hashes only (never
    # raw legacy payloads) and let the parent diff identify the first stage at
    # which legacy and V2 disagree.
    legacy_stage_fingerprints: dict[str, str] = Field(default_factory=dict)
    requested_by: str = Field(default="parent", min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=500)
    force: bool = False

    @field_validator("analysis_id", "requested_by")
    @classmethod
    def no_path_tokens(cls, value: str) -> str:
        if value.strip() != value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("value must be a path-safe identifier")
        return value


class ShadowRetryRequest(ShadowStrictModel):
    stage: StageName | None = None
    reason: str | None = Field(default=None, max_length=500)
    requested_by: str = Field(default="parent", min_length=1, max_length=160)
    confirmation: Literal["confirm_shadow_retry"]


class ShadowReviewDecisionRequest(ShadowStrictModel):
    stage: StageName
    decision: ReviewDecisionKind
    reviewer: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)
    confirmation: Literal["confirm_shadow_review_decision"]
    # Promotion is deliberately restricted to the isolated Shadow authority.
    promotion_scope: Literal["shadow_only"] | None = None


class ShadowNoteRequest(ShadowStrictModel):
    note: str = Field(min_length=1, max_length=1000)
    author: str = Field(default="parent", min_length=1, max_length=160)


class ShadowFingerprintUpdateRequest(ShadowStrictModel):
    source_fingerprint: str | None = Field(default=None, max_length=256)
    model_fingerprint: str | None = Field(default=None, max_length=256)
    config_fingerprint: str | None = Field(default=None, max_length=256)
    prompt_fingerprint: str | None = Field(default=None, max_length=256)
    contract_fingerprint: str | None = Field(default=None, max_length=256)
    requested_by: str = Field(default="parent", min_length=1, max_length=160)
    confirmation: Literal["confirm_shadow_fingerprint_update"]


class ShadowCleanupResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    run_id: str
    removed: list[str]
    retained: list[str]


class ShadowStageState(ShadowStrictModel):
    schema_version: Literal["shadow-stage.v1"] = "shadow-stage.v1"
    stage: StageName
    status: StageStatus = "pending"
    fingerprint: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    dependency_hashes: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    retry_count: int = Field(default=0, ge=0)
    updated_at: str = Field(default_factory=utc_now)


class ShadowStageDiff(ShadowStrictModel):
    schema_version: Literal["shadow-stage-diff.v1"] = "shadow-stage-diff.v1"
    stage: StageName
    status: DiffStatus = "unavailable"
    legacy_fingerprint: str | None = None
    v2_fingerprint: str | None = None
    summary: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    first_divergent: bool = False


class ShadowArtifactReference(ShadowStrictModel):
    schema_version: Literal["shadow-artifact-reference.v1"] = "shadow-artifact-reference.v1"
    artifact_id: str
    stage: StageName
    kind: str = "stage-output"
    relative_path: str
    fingerprint: str | None = None
    status: Literal["rebuildable", "missing", "retained"] = "rebuildable"
    created_at: str = Field(default_factory=utc_now)


class ShadowReviewDecision(ShadowStrictModel):
    schema_version: Literal["shadow-review-decision.v1"] = "shadow-review-decision.v1"
    decision_id: str
    run_id: str
    stage: StageName
    decision: ReviewDecisionKind
    reviewer: str
    note: str | None = None
    audited_at: str = Field(default_factory=utc_now)
    authority: Literal["shadow"] = "shadow"
    legacy_mutation: Literal[False] = False
    promotion_scope: Literal["shadow_only"] | None = None


class ShadowDownstreamImpact(ShadowStrictModel):
    consumer: str
    status: DownstreamImpactKind
    reason: str | None = None
    executed: Literal[False] = False


class ShadowRunRecord(ShadowStrictModel):
    schema_version: Literal["shadow-run.v1"] = "shadow-run.v1"
    run_id: str
    analysis_id: str
    status: RunStatus = "queued"
    authority: Literal["legacy"] = "legacy"
    diagnostic_only: Literal[True] = True
    pipeline_fingerprint: str | None = None
    source_fingerprint: str | None = None
    source_video_hash: str | None = None
    model_fingerprint: str | None = None
    config_fingerprint: str | None = None
    prompt_fingerprint: str | None = None
    contract_fingerprint: str | None = None
    legacy_stage_fingerprints: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    requested_by: str = "parent"
    coalesced: bool = False
    retry_from_stage: StageName | None = None
    first_divergent_stage: StageName | None = None
    stages: list[ShadowStageState] = Field(default_factory=list)
    diffs: list[ShadowStageDiff] = Field(default_factory=list)
    artifacts: list[ShadowArtifactReference] = Field(default_factory=list)
    review_decisions: list[ShadowReviewDecision] = Field(default_factory=list)
    downstream: list[ShadowDownstreamImpact] = Field(default_factory=list)
    notes: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None


class ShadowRecoveryResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    run: ShadowRunRecord


class ShadowRunResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    run: ShadowRunRecord


class ShadowRunListResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    analysis_id: str
    runs: list[ShadowRunRecord]


class ShadowStatusResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    status: RunStatus
    runtime_mode: Literal["legacy", "shadow", "v2"]
    public_authority: Literal["legacy"] = "legacy"
    diagnostic_only: Literal[True] = True
    writes_user_data: Literal[False] = False
    run: ShadowRunRecord | None = None


class ShadowDiffResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    run_id: str
    analysis_id: str
    first_divergent_stage: StageName | None
    stages: list[ShadowStageDiff]
    downstream: list[ShadowDownstreamImpact]


class ShadowArtifactResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    run_id: str
    analysis_id: str
    artifact: ShadowArtifactReference
    content: dict[str, Any] | None = None


class ShadowDecisionResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    run_id: str
    decision: ShadowReviewDecision
    legacy_report_rewritten: Literal[False] = False
    # Kept optional for clients that used the pre-typed response envelope.
    run: ShadowRunRecord | None = None

    # Keep direct-call compatibility with the pre-typed router response while
    # FastAPI/OpenAPI now exposes the explicit contract above.
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class ShadowNoteResponse(ShadowStrictModel):
    schema_version: Literal["shadow-orchestration.v1"] = SHADOW_SCHEMA_VERSION
    run_id: str
    notes: list[dict[str, str]]
