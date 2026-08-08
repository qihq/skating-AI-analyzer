"""End-to-end Shadow orchestration primitives.

This module deliberately has no SQLAlchemy/database dependency.  A Shadow run
is a rebuildable, versioned JSON artifact under the private V2 runtime.  The
legacy analysis result is passed through as an input and is never mutated.

The implementation is intentionally useful on its own (for a CLI, a router,
or a background worker).  The application can therefore add parent-authorized
endpoints without coupling Shadow state to the family ``Analysis`` row.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TypeVar

from app.analysis_v2.config import PipelineMode, RuntimeConfig
from app.analysis_v2.contamination_inventory import (
    FamilyContaminationInventory,
    SnapshotProvider,
    capture_family_inventory,
    compare_family_inventories,
)


logger = logging.getLogger(__name__)


# The order is a contract.  A stage may only consume artifacts from stages to
# its left; invalidating one stage consequently invalidates all descendants.
SHADOW_STAGE_ORDER: tuple[str, ...] = (
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

# Common names used by earlier slices and by API clients.  Keeping aliases in
# one place prevents slightly different spellings from producing cache forks.
SHADOW_STAGES = SHADOW_STAGE_ORDER
STAGE_ORDER = SHADOW_STAGE_ORDER
STAGE_ALIASES: dict[str, str] = {
    "observation": "observations",
    "detection": "candidates",
    "tracking": "identity",
    "path_review": "path_reviews",
    "path-a": "path_reviews",
    "path-b": "path_reviews",
    "fusion": "claims",
    "report": "claims",
}

STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "timebase": (),
    "observations": ("timebase",),
    "candidates": ("observations",),
    "identity": ("candidates",),
    "pose": ("identity",),
    "events": ("pose",),
    "moments": ("events",),
    "rotation": ("moments",),
    "path_reviews": ("identity", "pose", "events"),
    "claims": ("path_reviews", "moments", "rotation"),
}

# Pipeline-level fingerprints are retained separately because their change
# scopes are not identical.  A combined pipeline hash alone cannot explain
# why a cached decode stayed valid while a pose/report descendant reran.
FINGERPRINT_KEYS: tuple[str, ...] = (
    "source",
    "model",
    "config",
    "prompt",
    "contract",
)

FINGERPRINT_TO_STAGE: dict[str, str] = {
    "source": "timebase",
    "model": "candidates",
    "config": "candidates",
    "prompt": "path_reviews",
    "contract": "timebase",
}

# Dependency keys accepted by ``invalidation_for_changes``.  Values are the
# first stage whose output can no longer be trusted after that input changes.
CHANGE_TO_STAGE: dict[str, str] = {
    "source": "timebase",
    "source_video": "timebase",
    "source_hash": "timebase",
    "timebase": "timebase",
    "decode": "timebase",
    "observation": "observations",
    "observations": "observations",
    "candidate": "candidates",
    "candidates": "candidates",
    "detector": "candidates",
    "tracker": "candidates",
    "camera": "candidates",
    "identity": "identity",
    "identity_config": "identity",
    "pose": "pose",
    "pose_config": "pose",
    "pose_model": "pose",
    "event": "events",
    "events": "events",
    "classifier": "events",
    "moment": "moments",
    "moments": "moments",
    "rotation": "rotation",
    "rotation_config": "rotation",
    "path": "path_reviews",
    "path_review": "path_reviews",
    "path_reviews": "path_reviews",
    "provider": "path_reviews",
    # A generic model/config fingerprint can affect candidate generation and
    # every descendant.  More specific path/report keys below retain their
    # narrower invalidation scope.
    "model": "candidates",
    "model_fingerprint": "candidates",
    "config_fingerprint": "candidates",
    "path_model": "path_reviews",
    "prompt": "path_reviews",
    "path_prompt": "path_reviews",
    # A report prompt only changes claim/report rendering.  Tracking and all
    # source-derived stages remain reusable.
    "report_prompt": "claims",
    "report": "claims",
    "claims": "claims",
    "contract": "timebase",
    "contract_version": "timebase",
    "schema": "timebase",
}

REBUILDABLE_ARTIFACT_DIR = "artifacts"
SHADOW_LAYOUT_VERSION = "shadow-v2"
SHADOW_MANIFEST_FILENAME = "run.json"
SHADOW_AUDIT_FILENAME = "audit.jsonl"

# These names are intentionally descriptive and are used by the contamination
# sentinel and by callers constructing a family-data baseline.
CONTAMINATION_FAMILIES: tuple[str, ...] = (
    "chat_corrections",
    "plans_sessions",
    "growth_compare",
    "skills_xp",
    "memories",
    "chapters_annual",
    "shares_exports_notifications",
    "settings_providers",
    "published_completed_artifacts",
    "backup_inventory",
)


class ShadowStageStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYABLE = "retryable"
    INVALID = "invalid"
    CANCELLED = "cancelled"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> Any:
    """Return a JSON-safe, deterministic representation of ``value``."""
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_canonical(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, bytes):
        return {"__bytes_sha256__": hashlib.sha256(value).hexdigest(), "length": len(value)}
    return value


def content_hash(value: Any) -> str:
    """Compute a secret-free stable content hash for a stage input/output."""
    encoded = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_fingerprints(values: Mapping[str, Any] | None) -> dict[str, str]:
    """Normalize the five independent Shadow fingerprints.

    Fingerprints are intentionally persisted as separate values.  Callers may
    supply ``*_fingerprint`` spellings or the short contract keys; values are
    treated as opaque strings and never logged or expanded into raw paths.
    """
    if not values:
        return {}
    aliases = {
        "source_fingerprint": "source",
        "source_video_hash": "source",
        "model_fingerprint": "model",
        "config_fingerprint": "config",
        "prompt_fingerprint": "prompt",
        "contract_fingerprint": "contract",
    }
    output: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = aliases.get(str(raw_key), str(raw_key))
        if key not in FINGERPRINT_KEYS or raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            output[key] = value
    return output


def pipeline_fingerprint_for(values: Mapping[str, Any] | None) -> str:
    """Return a deterministic combined hash while retaining component hashes."""
    return content_hash({key: canonical_fingerprints(values).get(key) for key in FINGERPRINT_KEYS})


def _normalize_stage(name: str) -> str:
    normalized = str(name).strip().lower().replace(" ", "_")
    normalized = STAGE_ALIASES.get(normalized, normalized)
    if normalized not in SHADOW_STAGE_ORDER:
        raise ValueError(f"unknown Shadow stage: {name!r}")
    return normalized


def canonical_stage_fingerprints(values: Mapping[str, Any] | None) -> dict[str, str]:
    """Normalize optional legacy/V2 stage fingerprints to contract names."""
    if not values:
        return {}
    output: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        if raw_value is None:
            continue
        try:
            key = _normalize_stage(str(raw_key))
        except ValueError:
            # Unknown legacy labels are not allowed to create a comparison
            # branch.  They remain absent and therefore show as unavailable.
            continue
        value = str(raw_value).strip()
        if value:
            output[key] = value
    return output


def legacy_stage_fingerprints_from_snapshot(legacy_result: Mapping[str, Any] | None) -> dict[str, str]:
    """Build a sanitized, per-stage legacy baseline from a detached snapshot.

    The baseline contains hashes only.  It is intentionally derived from the
    whole legacy completion snapshot at the dispatch boundary so the Shadow
    diff can identify a first divergent stage without copying legacy report,
    source paths, labels, or family-facing rows into the Shadow artifact tree.
    Component selection mirrors the ten-stage contract and is conservative:
    when a legacy component is absent its hash still records that absence.
    """
    payload = dict(legacy_result or {})

    def component(*keys: str) -> dict[str, Any]:
        return {key: payload.get(key) for key in keys}

    values: dict[str, Any] = {
        "timebase": component(
            "source_fps",
            "is_slow_motion",
            "action_window_start",
            "action_window_end",
            "frame_motion_scores",
        ),
        "observations": component("frame_motion_scores", "processing_timings"),
        "candidates": component("target_lock", "frame_motion_scores"),
        "identity": component("target_lock", "pose_data"),
        "pose": component("pose_data", "target_lock"),
        "events": component(
            "analysis_profile",
            "action_type",
            "action_subtype",
            "action_window_start",
            "action_window_end",
            "vision_structured",
            "cross_validation",
        ),
        "moments": component("vision_structured", "bio_data", "cross_validation"),
        "rotation": component("bio_data", "vision_structured", "vision_path_b"),
        "path_reviews": component("vision_path_a", "vision_path_b", "target_lock"),
        "claims": component("report", "force_score", "note", "highlight_quote"),
    }
    return {stage: content_hash(values[stage]) for stage in SHADOW_STAGE_ORDER}


def stage_descendants(stage: str, *, include_self: bool = True) -> tuple[str, ...]:
    """Return a stage and all downstream stages in canonical order."""
    normalized = _normalize_stage(stage)
    start = SHADOW_STAGE_ORDER.index(normalized)
    return SHADOW_STAGE_ORDER[start:] if include_self else SHADOW_STAGE_ORDER[start + 1 :]


def invalidation_for_changes(changes: Iterable[str]) -> tuple[str, ...]:
    """Map changed source/model/config keys to invalidated stage descendants."""
    starts: list[str] = []
    for raw in changes:
        key = str(raw).strip().lower().replace("-", "_")
        # Support dotted configuration paths, e.g. ``pose.model``.
        key = key.split(".", 1)[0]
        if key in {"all", "everything", "pipeline"}:
            starts.append(SHADOW_STAGE_ORDER[0])
            continue
        if key in CHANGE_TO_STAGE:
            starts.append(CHANGE_TO_STAGE[key])
            continue
        # Unknown contract/config changes are conservative: only the final
        # claims are unsafe unless explicitly marked as source-affecting.
        starts.append("claims")
    if not starts:
        return ()
    first = min(SHADOW_STAGE_ORDER.index(_normalize_stage(item)) for item in starts)
    return SHADOW_STAGE_ORDER[first:]


def fingerprint_changes(
    previous: Mapping[str, str | None],
    current: Mapping[str, str | None],
) -> tuple[str, ...]:
    """Return stable change keys for the separately persisted fingerprints."""
    before = canonical_fingerprints(previous)
    after = canonical_fingerprints(current)
    return tuple(key for key in FINGERPRINT_KEYS if before.get(key, "") != after.get(key, ""))


def invalidation_for_fingerprint_changes(changes: Iterable[str]) -> tuple[str, ...]:
    starts = [FINGERPRINT_TO_STAGE.get(str(item).strip().lower().removesuffix("_fingerprint"), "claims") for item in changes]
    if not starts:
        return ()
    first = min(SHADOW_STAGE_ORDER.index(stage) for stage in starts)
    return SHADOW_STAGE_ORDER[first:]


def first_invalid_stage(stages: Sequence["ShadowStage"]) -> str | None:
    by_name = {_normalize_stage(item.name): item for item in stages}
    for name in SHADOW_STAGE_ORDER:
        item = by_name.get(name)
        if item is None or item.status is not ShadowStageStatus.COMPLETED:
            return name
    return None


@dataclass(frozen=True)
class ShadowStage:
    """Persisted checkpoint for one canonical Shadow stage."""

    name: str
    status: ShadowStageStatus = ShadowStageStatus.PENDING
    fingerprint: str = ""
    input_hash: str = ""
    output_hash: str = ""
    dependency_hashes: Mapping[str, str] = field(default_factory=dict)
    artifact_reference: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    retry_count: int = 0
    attempt: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    invalidated_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_stage(self.name))
        status = self.status if isinstance(self.status, ShadowStageStatus) else ShadowStageStatus(str(self.status))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "dependency_hashes", dict(self.dependency_hashes))
        if self.retry_count < 0 or self.attempt < 0:
            raise ValueError("retry_count and attempt must be non-negative")

    @property
    def is_valid(self) -> bool:
        return self.status is ShadowStageStatus.COMPLETED and bool(self.output_hash)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["dependency_hashes"] = dict(self.dependency_hashes)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ShadowStage":
        return cls(
            name=str(payload.get("name", "")),
            status=ShadowStageStatus(str(payload.get("status", ShadowStageStatus.PENDING.value))),
            fingerprint=str(payload.get("fingerprint", "")),
            input_hash=str(payload.get("input_hash", "")),
            output_hash=str(payload.get("output_hash", "")),
            dependency_hashes=dict(payload.get("dependency_hashes") or {}),
            artifact_reference=payload.get("artifact_reference"),
            error_code=payload.get("error_code"),
            error_detail=payload.get("error_detail"),
            retry_count=int(payload.get("retry_count", 0) or 0),
            attempt=int(payload.get("attempt", 0) or 0),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            invalidated_reason=payload.get("invalidated_reason"),
        )


# Friendly aliases for clients that use the design-document terminology.
StageCheckpoint = ShadowStage
ShadowStageCheckpoint = ShadowStage


@dataclass(frozen=True)
class ShadowRun:
    """Immutable JSON-friendly run manifest and stage checkpoints."""

    run_id: str
    analysis_id: str
    source_identity: Mapping[str, str]
    pipeline_fingerprint: str
    fingerprints: Mapping[str, str] = field(default_factory=dict)
    legacy_stage_fingerprints: Mapping[str, str] = field(default_factory=dict)
    status: str = "pending"
    stages: tuple[ShadowStage, ...] = ()
    legacy_authority: str = "legacy"
    layout_version: str = SHADOW_LAYOUT_VERSION
    artifact_root: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    queue_key: str | None = None
    audit_reference: str | None = None
    reviewer_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id or not self.analysis_id or not self.pipeline_fingerprint:
            raise ValueError("run_id, analysis_id, and pipeline_fingerprint are required")
        if self.legacy_authority != "legacy":
            raise ValueError("Shadow runs are always legacy-authoritative")
        object.__setattr__(self, "source_identity", dict(self.source_identity))
        object.__setattr__(self, "fingerprints", canonical_fingerprints(self.fingerprints))
        object.__setattr__(self, "legacy_stage_fingerprints", canonical_stage_fingerprints(self.legacy_stage_fingerprints))
        normalized: dict[str, ShadowStage] = {}
        for stage in self.stages:
            normalized[_normalize_stage(stage.name)] = stage
        ordered = tuple(normalized.get(name, ShadowStage(name=name)) for name in SHADOW_STAGE_ORDER)
        object.__setattr__(self, "stages", ordered)
        object.__setattr__(self, "reviewer_notes", tuple(str(item) for item in self.reviewer_notes))

    @classmethod
    def create(
        cls,
        *,
        analysis_id: str,
        source_identity: Mapping[str, str],
        pipeline_fingerprint: str,
        fingerprints: Mapping[str, str] | None = None,
        legacy_stage_fingerprints: Mapping[str, str] | None = None,
        run_id: str | None = None,
        queue_key: str | None = None,
    ) -> "ShadowRun":
        return cls(
            run_id=run_id or str(uuid.uuid4()),
            analysis_id=str(analysis_id),
            source_identity=source_identity,
            pipeline_fingerprint=str(pipeline_fingerprint),
            fingerprints=dict(fingerprints or {}),
            legacy_stage_fingerprints=dict(legacy_stage_fingerprints or {}),
            queue_key=queue_key or str(analysis_id),
        )

    @property
    def first_invalid_stage(self) -> str | None:
        return first_invalid_stage(self.stages)

    @property
    def completed(self) -> bool:
        return self.first_invalid_stage is None

    def stage(self, name: str) -> ShadowStage:
        normalized = _normalize_stage(name)
        return next(item for item in self.stages if item.name == normalized)

    def with_stage(self, stage: ShadowStage) -> "ShadowRun":
        normalized = _normalize_stage(stage.name)
        updated = tuple(stage if item.name == normalized else item for item in self.stages)
        status = self.status
        if stage.status in {ShadowStageStatus.FAILED, ShadowStageStatus.RETRYABLE}:
            status = "failed"
        elif all(item.status is ShadowStageStatus.COMPLETED for item in updated):
            status = "completed"
        elif stage.status is ShadowStageStatus.RUNNING:
            status = "running"
        elif status == "pending":
            status = "queued"
        return replace(self, stages=updated, status=status, updated_at=_now())

    def invalidate(self, stage: str, *, reason: str = "dependency_changed") -> "ShadowRun":
        invalidated = set(stage_descendants(stage))
        updated = tuple(
            replace(
                item,
                status=ShadowStageStatus.INVALID,
                output_hash="",
                artifact_reference=None,
                error_code="INVALIDATED",
                error_detail=reason,
                invalidated_reason=reason,
                completed_at=None,
            )
            if item.name in invalidated
            else item
            for item in self.stages
        )
        return replace(self, stages=updated, status="queued", updated_at=_now())

    def invalidate_for_changes(self, changes: Iterable[str]) -> "ShadowRun":
        invalidated = invalidation_for_changes(changes)
        if not invalidated:
            return self
        return self.invalidate(invalidated[0], reason=";".join(str(item) for item in changes))

    def with_fingerprints(self, fingerprints: Mapping[str, Any]) -> "ShadowRun":
        """Update component fingerprints and invalidate only their consumers."""
        # Partial updates are common (for example a pose model refresh).  Do
        # not erase unrelated source/contract fingerprints when one component
        # changes.
        updated_fingerprints = {
            **dict(self.fingerprints),
            **canonical_fingerprints(fingerprints),
        }
        changes = fingerprint_changes(self.fingerprints, updated_fingerprints)
        if not changes:
            return self
        updated = replace(
            self,
            fingerprints=updated_fingerprints,
            pipeline_fingerprint=pipeline_fingerprint_for(updated_fingerprints),
            queue_key=None,
            updated_at=_now(),
        )
        invalidated = invalidation_for_fingerprint_changes(changes)
        if not invalidated:
            return updated
        return updated.invalidate(
            invalidated[0],
            reason="fingerprints_changed:" + ",".join(changes),
        )

    def with_note(self, note: str) -> "ShadowRun":
        if not str(note).strip():
            return self
        return replace(self, reviewer_notes=(*self.reviewer_notes, str(note).strip()), updated_at=_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "shadow-run.v1",
            "layout_version": self.layout_version,
            "run_id": self.run_id,
            "analysis_id": self.analysis_id,
            "source_identity": dict(self.source_identity),
            "pipeline_fingerprint": self.pipeline_fingerprint,
            "fingerprints": dict(self.fingerprints),
            "legacy_stage_fingerprints": dict(self.legacy_stage_fingerprints),
            "status": self.status,
            "legacy_authority": self.legacy_authority,
            "artifact_root": self.artifact_root,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "queue_key": self.queue_key,
            "audit_reference": self.audit_reference,
            "reviewer_notes": list(self.reviewer_notes),
            "stages": [stage.to_dict() for stage in self.stages],
            "first_invalid_stage": self.first_invalid_stage,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ShadowRun":
        stages = payload.get("stages") or []
        return cls(
            run_id=str(payload["run_id"]),
            analysis_id=str(payload["analysis_id"]),
            source_identity=dict(payload.get("source_identity") or {}),
            pipeline_fingerprint=str(payload["pipeline_fingerprint"]),
            fingerprints=dict(payload.get("fingerprints") or {}),
            legacy_stage_fingerprints=dict(payload.get("legacy_stage_fingerprints") or {}),
            status=str(payload.get("status", "pending")),
            stages=tuple(ShadowStage.from_dict(item) for item in stages if isinstance(item, Mapping)),
            legacy_authority=str(payload.get("legacy_authority", "legacy")),
            layout_version=str(payload.get("layout_version", SHADOW_LAYOUT_VERSION)),
            artifact_root=payload.get("artifact_root"),
            created_at=str(payload.get("created_at", _now())),
            updated_at=str(payload.get("updated_at", _now())),
            queue_key=payload.get("queue_key"),
            audit_reference=payload.get("audit_reference"),
            reviewer_notes=tuple(payload.get("reviewer_notes") or ()),
        )


@dataclass(frozen=True)
class ShadowRunResult:
    status: str
    writes_performed: int
    artifact_references: tuple[str, ...]
    run_id: str | None = None
    first_invalid_stage: str | None = None
    coalesced: bool = False
    error: str | None = None


@dataclass(frozen=True)
class ShadowStageDiff:
    stage: str
    equal: bool
    first_divergent: bool = False
    left_status: str | None = None
    right_status: str | None = None
    left_fingerprint: str | None = None
    right_fingerprint: str | None = None
    left_input_hash: str | None = None
    right_input_hash: str | None = None
    left_output_hash: str | None = None
    right_output_hash: str | None = None
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class ShadowDiff:
    schema_version: str = "shadow-stage-diff.v1"
    left_run_id: str | None = None
    right_run_id: str | None = None
    first_divergent_stage: str | None = None
    stages: tuple[ShadowStageDiff, ...] = ()

    @property
    def equal(self) -> bool:
        return self.first_divergent_stage is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "left_run_id": self.left_run_id,
            "right_run_id": self.right_run_id,
            "first_divergent_stage": self.first_divergent_stage,
            "equal": self.equal,
            "stages": [stage.to_dict() for stage in self.stages],
        }


def diff_runs(left: ShadowRun, right: ShadowRun) -> ShadowDiff:
    """Compare two manifests and pinpoint the earliest differing stage."""
    results: list[ShadowStageDiff] = []
    first: str | None = None
    for name in SHADOW_STAGE_ORDER:
        a, b = left.stage(name), right.stage(name)
        reasons: list[str] = []
        if a.status != b.status:
            reasons.append("status")
        if a.fingerprint != b.fingerprint:
            reasons.append("fingerprint")
        if a.input_hash != b.input_hash:
            reasons.append("input_hash")
        if a.output_hash != b.output_hash:
            reasons.append("output_hash")
        if dict(a.dependency_hashes) != dict(b.dependency_hashes):
            reasons.append("dependency_hashes")
        equal = not reasons
        divergent = not equal and first is None
        if divergent:
            first = name
        results.append(
            ShadowStageDiff(
                stage=name,
                equal=equal,
                first_divergent=divergent,
                left_status=a.status.value,
                right_status=b.status.value,
                left_fingerprint=a.fingerprint,
                right_fingerprint=b.fingerprint,
                left_input_hash=a.input_hash,
                right_input_hash=b.input_hash,
                left_output_hash=a.output_hash,
                right_output_hash=b.output_hash,
                reasons=tuple(reasons),
            )
        )
    return ShadowDiff(left_run_id=left.run_id, right_run_id=right.run_id, first_divergent_stage=first, stages=tuple(results))


def diff_legacy_to_shadow(
    legacy_stage_fingerprints: Mapping[str, Any],
    shadow: ShadowRun,
) -> ShadowDiff:
    """Compare sanitized legacy stage fingerprints with one Shadow run.

    Legacy results are never copied into the Shadow artifact stream.  Callers
    provide only per-stage hashes, allowing this function to identify the
    first semantic divergence without exposing report fields or source media.
    """
    legacy = canonical_stage_fingerprints(legacy_stage_fingerprints)
    results: list[ShadowStageDiff] = []
    first: str | None = None
    for name in SHADOW_STAGE_ORDER:
        stage = shadow.stage(name)
        left = legacy.get(name)
        right = stage.fingerprint or stage.output_hash or None
        reasons: list[str] = []
        if left is None or right is None:
            equal = False if left != right else True
            if left is None and right is None:
                # No baseline and no result is genuinely unavailable, not a
                # claimed difference.
                status = "unavailable"
                equal = True
            else:
                status = "unexplained"
                reasons.append("missing_legacy_fingerprint" if left is None else "missing_shadow_output")
        else:
            equal = left == right
            status = "unchanged" if equal else "different"
            if not equal:
                reasons.append("stage_fingerprint")
        divergent = not equal and first is None
        if divergent:
            first = name
        results.append(
            ShadowStageDiff(
                stage=name,
                equal=equal,
                first_divergent=divergent,
                left_status="legacy",
                right_status=stage.status.value,
                left_fingerprint=left,
                right_fingerprint=right,
                left_output_hash=left,
                right_output_hash=stage.output_hash or None,
                reasons=tuple(reasons),
            )
        )
    return ShadowDiff(left_run_id="legacy", right_run_id=shadow.run_id, first_divergent_stage=first, stages=tuple(results))


stage_diff = diff_runs


class ShadowArtifactStore:
    """Atomic JSON store below ``<runtime>/shadow/v2`` only.

    The store never follows source references and never deletes anything
    outside its own ``runs`` directory.  Golden labels, videos, durable review
    records, and audit logs are therefore outside cleanup scope by construction.
    """

    def __init__(self, runtime_root: Path, *, layout_version: str = SHADOW_LAYOUT_VERSION) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        self.layout_version = str(layout_version)
        self.root = self.runtime_root / "shadow" / "v2"
        self.runs_root = self.root / "runs"
        self.audits_root = self.root / "audits"

    def _run_dir(self, run_id: str) -> Path:
        safe = str(run_id).strip()
        if not safe or Path(safe).name != safe or safe in {".", ".."} or any(part in safe for part in ("/", "\\")):
            raise ValueError("invalid Shadow run id")
        return self.runs_root / safe

    def ensure_layout(self) -> None:
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.audits_root.mkdir(parents=True, exist_ok=True)

    def save_run(self, run: ShadowRun) -> Path:
        self.ensure_layout()
        directory = self._run_dir(run.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        payload = run.to_dict()
        if not run.artifact_root:
            payload["artifact_root"] = str(Path("shadow") / "v2" / "runs" / run.run_id / REBUILDABLE_ARTIFACT_DIR)
        self._atomic_json(directory / SHADOW_MANIFEST_FILENAME, payload)
        return directory / SHADOW_MANIFEST_FILENAME

    def load_run(self, run_id: str) -> ShadowRun:
        path = self._run_dir(run_id) / SHADOW_MANIFEST_FILENAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ShadowRun.from_dict(payload)

    def _artifact_reference_exists(self, reference: str) -> bool:
        try:
            candidate = (self.runtime_root / str(reference)).resolve()
            candidate.relative_to(self.runtime_root)
        except (OSError, ValueError):
            return False
        return candidate.is_file()

    def has_run(self, run_id: str) -> bool:
        return (self._run_dir(run_id) / SHADOW_MANIFEST_FILENAME).is_file()

    def list_runs(self) -> tuple[ShadowRun, ...]:
        if not self.runs_root.exists():
            return ()
        runs: list[ShadowRun] = []
        for path in sorted(self.runs_root.glob(f"*/{SHADOW_MANIFEST_FILENAME}")):
            try:
                runs.append(ShadowRun.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
                continue
        return tuple(runs)

    def write_artifact(self, run_id: str, stage: str, payload: Any, *, suffix: str = "json") -> tuple[str, str]:
        stage = _normalize_stage(stage)
        directory = self._run_dir(run_id) / REBUILDABLE_ARTIFACT_DIR
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{stage}.{suffix.lstrip('.') or 'json'}"
        path = directory / filename
        if suffix.lower().lstrip(".") == "json":
            self._atomic_json(path, _canonical(payload))
        elif isinstance(payload, bytes):
            self._atomic_bytes(path, payload)
        else:
            self._atomic_bytes(path, str(payload).encode("utf-8"))
        return str(path.relative_to(self.runtime_root)).replace("\\", "/"), content_hash(payload)

    def read_artifact(self, run_id: str, stage: str, *, suffix: str = "json") -> Any:
        stage = _normalize_stage(stage)
        path = self._run_dir(run_id) / REBUILDABLE_ARTIFACT_DIR / f"{stage}.{suffix.lstrip('.') or 'json'}"
        if suffix.lower().lstrip(".") == "json":
            return json.loads(path.read_text(encoding="utf-8"))
        return path.read_bytes()

    def append_audit(self, run_id: str, event: Mapping[str, Any]) -> Path:
        self.ensure_layout()
        path = self.audits_root / f"{run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_canonical(event), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def cleanup_rebuildable(self, run_id: str) -> tuple[str, ...]:
        """Delete generated stage artifacts and invalidate their checkpoints.

        The manifest is durable, so deleting files without updating its stage
        references would leave a completed-looking run that cannot actually
        resume.  Mark the earliest checkpoint whose artifact is removed (and
        all descendants) invalid while retaining the manifest/audit/source and
        Golden data.
        """
        try:
            current = self.load_run(run_id)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            current = None
        artifact_dir = self._run_dir(run_id) / REBUILDABLE_ARTIFACT_DIR
        if not artifact_dir.exists():
            return ()
        removed: list[str] = []
        for path in artifact_dir.iterdir():
            # Do not recurse into arbitrary directories.  A malformed artifact
            # directory is retained for manual inspection rather than deleting
            # potentially durable data.
            if path.is_file() or path.is_symlink():
                removed.append(str(path.relative_to(self.runtime_root)).replace("\\", "/"))
                path.unlink()
        try:
            artifact_dir.rmdir()
        except OSError:
            pass
        if current is not None and removed:
            removed_set = set(removed)
            stale_stage = next(
                (
                    stage.name
                    for stage in current.stages
                    if stage.artifact_reference and stage.artifact_reference in removed_set
                ),
                None,
            )
            if stale_stage is not None:
                self.save_run(current.invalidate(stale_stage, reason="artifact_cleanup"))
        return tuple(sorted(removed))

    def delete_run(self, run_id: str, *, keep_audit: bool = True) -> tuple[str, ...]:
        """Remove a run's rebuildable directory, never source/golden data."""
        removed = list(self.cleanup_rebuildable(run_id))
        directory = self._run_dir(run_id)
        manifest = directory / SHADOW_MANIFEST_FILENAME
        if manifest.exists():
            manifest.unlink()
            removed.append(str(manifest.relative_to(self.runtime_root)).replace("\\", "/"))
        try:
            directory.rmdir()
        except OSError:
            pass
        if not keep_audit:
            audit = self.audits_root / f"{run_id}.jsonl"
            if audit.exists():
                audit.unlink()
                removed.append(str(audit.relative_to(self.runtime_root)).replace("\\", "/"))
        return tuple(sorted(removed))

    @staticmethod
    def _atomic_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _atomic_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


# Shorter name expected by a few integrations.
ShadowStore = ShadowArtifactStore
ShadowArtifactLayout = ShadowArtifactStore


@dataclass(frozen=True)
class ContaminationSnapshot:
    schema_version: str = "shadow-contamination-snapshot.v1"
    hashes: Mapping[str, str] = field(default_factory=dict)
    captured_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "hashes", dict(self.hashes))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "captured_at": self.captured_at, "hashes": dict(self.hashes)}


@dataclass(frozen=True)
class ContaminationResult:
    schema_version: str = "shadow-contamination-result.v1"
    unchanged: bool = True
    changed: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    baseline: Mapping[str, str] = field(default_factory=dict)
    current: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "baseline", dict(self.baseline))
        object.__setattr__(self, "current", dict(self.current))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "unchanged": self.unchanged,
            "changed": list(self.changed),
            "excluded": list(self.excluded),
            "baseline": dict(self.baseline),
            "current": dict(self.current),
        }


def _hash_path(path: Path) -> str:
    if not path.exists():
        return content_hash({"missing": True})
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return "sha256:" + digest.hexdigest()
    entries: list[tuple[str, str]] = []
    for child in sorted(path.rglob("*")):
        if child.is_file():
            entries.append((str(child.relative_to(path)).replace("\\", "/"), _hash_path(child)))
    return content_hash(entries)


def capture_contamination(paths: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> ContaminationSnapshot:
    """Hash family data before/after a Shadow run without exposing its bytes.

    Values may be filesystem paths, mappings, JSON-compatible values, or bytes.
    The function records only SHA-256 digests and therefore is safe to persist
    in an isolated audit record.
    """
    items = paths.items() if isinstance(paths, Mapping) else paths
    hashes: dict[str, str] = {}
    for name, value in items:
        key = str(name)
        if isinstance(value, (str, Path)):
            candidate = Path(value)
            hashes[key] = _hash_path(candidate) if candidate.exists() else content_hash({"value": str(value)})
        else:
            hashes[key] = content_hash(value)
    return ContaminationSnapshot(hashes=hashes)


def verify_contamination(
    before: ContaminationSnapshot | Mapping[str, str],
    after: ContaminationSnapshot | Mapping[str, str],
    *,
    excluded: Iterable[str] = (),
) -> ContaminationResult:
    baseline = dict(before.hashes if isinstance(before, ContaminationSnapshot) else before)
    current = dict(after.hashes if isinstance(after, ContaminationSnapshot) else after)
    excluded_set = {str(item) for item in excluded}
    keys = set(baseline) | set(current)
    changed = tuple(sorted(key for key in keys if key not in excluded_set and baseline.get(key) != current.get(key)))
    return ContaminationResult(unchanged=not changed, changed=changed, excluded=tuple(sorted(excluded_set)), baseline=baseline, current=current)


class ShadowContaminationSentinel:
    """Capture/verify family boundaries and reject unexpected mutation."""

    families: tuple[str, ...] = CONTAMINATION_FAMILIES

    def __init__(self, paths: Mapping[str, Any] | None = None, *, excluded: Iterable[str] = ()) -> None:
        self.paths = dict(paths or {})
        self.excluded = tuple(str(item) for item in excluded)

    def capture(self, paths: Mapping[str, Any] | None = None) -> ContaminationSnapshot:
        return capture_contamination(paths if paths is not None else self.paths)

    def verify(self, before: ContaminationSnapshot, after: ContaminationSnapshot) -> ContaminationResult:
        return verify_contamination(before, after, excluded=self.excluded)

    def assert_clean(self, before: ContaminationSnapshot, after: ContaminationSnapshot) -> ContaminationResult:
        result = self.verify(before, after)
        if not result.unchanged:
            raise ShadowContaminationError("Shadow contamination detected: " + ", ".join(result.changed))
        return result


class ShadowContaminationError(RuntimeError):
    pass


T = TypeVar("T")
ShadowWork = Callable[[], Awaitable[T] | T]


class ShadowQueueFull(RuntimeError):
    pass


class BoundedShadowQueue:
    """Small bounded async queue with duplicate-request coalescing.

    ``submit`` returns the result of the shared in-flight task.  Calls with the
    same key while a run is queued/running await that same task rather than
    launching duplicate V2 work.  The queue does not interact with the legacy
    request path.
    """

    def __init__(self, *, max_concurrency: int = 1, max_pending: int = 16) -> None:
        if max_concurrency < 1 or max_pending < 1:
            raise ValueError("queue limits must be positive")
        self.max_concurrency = int(max_concurrency)
        self.max_pending = int(max_pending)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()
        self._coalesced = 0

    @property
    def inflight_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._inflight))

    @property
    def coalesced_count(self) -> int:
        return self._coalesced

    async def submit(self, key: str, work: ShadowWork[T]) -> T:
        normalized = str(key).strip()
        if not normalized:
            raise ValueError("queue key is required")
        async with self._lock:
            existing = self._inflight.get(normalized)
            if existing is not None:
                self._coalesced += 1
                task = existing
            else:
                if len(self._inflight) >= self.max_pending:
                    raise ShadowQueueFull("Shadow queue is full")
                task = asyncio.create_task(self._execute(work), name=f"shadow:{normalized}")
                self._inflight[normalized] = task
                task.add_done_callback(lambda _: self._inflight.pop(normalized, None))
        return await asyncio.shield(task)

    enqueue = submit

    async def _execute(self, work: ShadowWork[T]) -> T:
        async with self._semaphore:
            result = work()
            if inspect.isawaitable(result):
                return await result
            return result

    async def drain(self) -> None:
        tasks = tuple(self._inflight.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


ShadowQueue = BoundedShadowQueue
BoundedLocalShadowQueue = BoundedShadowQueue


class ShadowStageHandler(Protocol):
    async def __call__(self, *, run: ShadowRun, stage: ShadowStage, inputs: Mapping[str, Any]) -> Any: ...


FamilyInventoryCapture = Callable[
    [],
    FamilyContaminationInventory | Awaitable[FamilyContaminationInventory],
]


class ShadowOrchestrator:
    """Filesystem-backed Shadow runner used by parent-authorized surfaces."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        store: ShadowArtifactStore | None = None,
        queue: BoundedShadowQueue | None = None,
        contamination_provider: SnapshotProvider | None = None,
        contamination_capture: FamilyInventoryCapture | None = None,
    ) -> None:
        if contamination_provider is not None and contamination_capture is not None:
            raise ValueError("provide contamination_provider or contamination_capture, not both")
        self._config = config
        self.store = store or (ShadowArtifactStore(config.runtime_root) if config.runtime_root else None)
        self.queue = queue or BoundedShadowQueue(max_concurrency=1, max_pending=8)
        self._contamination_provider = contamination_provider
        self._contamination_capture = contamination_capture

    def create_run(
        self,
        *,
        analysis_id: str,
        source_identity: Mapping[str, str],
        pipeline_fingerprint: str,
        fingerprints: Mapping[str, str] | None = None,
        legacy_stage_fingerprints: Mapping[str, str] | None = None,
        run_id: str | None = None,
    ) -> ShadowRun:
        if self._config.pipeline_mode is not PipelineMode.SHADOW:
            raise RuntimeError("Shadow orchestration is disabled outside shadow mode")
        run = ShadowRun.create(
            analysis_id=analysis_id,
            source_identity=_manifest_source_identity(source_identity),
            pipeline_fingerprint=pipeline_fingerprint,
            fingerprints=fingerprints,
            legacy_stage_fingerprints=legacy_stage_fingerprints,
            run_id=run_id,
            queue_key=f"{analysis_id}:{pipeline_fingerprint}",
        )
        if self.store:
            self.store.save_run(run)
        return run

    async def run(
        self,
        legacy_result: Mapping[str, Any],
        *,
        analysis_id: str | None = None,
        source_identity: Mapping[str, str] | None = None,
        pipeline_fingerprint: str | None = None,
        fingerprints: Mapping[str, str] | None = None,
        legacy_stage_fingerprints: Mapping[str, str] | None = None,
        stage_handlers: Mapping[str, ShadowWork[Any]] | None = None,
        run: ShadowRun | None = None,
    ) -> ShadowRunResult:
        """Run stage handlers while preserving the detached legacy mapping.

        A default deterministic adapter factory is used when callers do not
        supply handlers.  ``source_path`` is an explicitly ephemeral input for
        that factory and is never persisted in the Shadow manifest/artifacts.
        """
        if self._config.pipeline_mode is not PipelineMode.SHADOW:
            return ShadowRunResult(status="disabled", writes_performed=0, artifact_references=())
        isolated_legacy_result = copy.deepcopy(dict(legacy_result))
        ephemeral_source_identity = dict(source_identity or {})
        if run is None:
            run = self.create_run(
                analysis_id=str(analysis_id or "unknown-analysis"),
                source_identity=ephemeral_source_identity or {"analysis_id": str(analysis_id or "unknown-analysis")},
                pipeline_fingerprint=str(pipeline_fingerprint or "shadow:unfingerprinted"),
                fingerprints=fingerprints,
                legacy_stage_fingerprints=legacy_stage_fingerprints or legacy_stage_fingerprints_from_snapshot(isolated_legacy_result),
            )
        if stage_handlers is None:
            from app.analysis_v2.shadow_pipeline import build_default_stage_handlers

            stage_handlers = build_default_stage_handlers(
                legacy_result=isolated_legacy_result,
                source_identity=ephemeral_source_identity,
                config=self._config,
            )
        handlers = {(_normalize_stage(name)): handler for name, handler in stage_handlers.items()}
        key = run.queue_key or f"{run.analysis_id}:{run.pipeline_fingerprint}"

        async def execute() -> ShadowRunResult:
            current = run
            writes = 0
            references: list[str] = []
            stage_outputs: dict[str, Any] = {}
            contamination_before: FamilyContaminationInventory | None = None
            result: ShadowRunResult | None = None
            try:
                contamination_before = await self._capture_contamination_inventory(
                    current.run_id,
                    phase="before",
                )
                try:
                    for name in SHADOW_STAGE_ORDER:
                        stage = current.stage(name)
                        checkpoint_loaded = False
                        if stage.is_valid:
                            if stage.artifact_reference:
                                references.append(stage.artifact_reference)
                                if self.store:
                                    try:
                                        stage_outputs[name] = self.store.read_artifact(current.run_id, name)
                                        checkpoint_loaded = True
                                    except (OSError, ValueError, KeyError, json.JSONDecodeError):
                                        # A missing rebuildable artifact invalidates
                                        # this checkpoint and immediately resumes at
                                        # this stage.  Do not ``continue`` after the
                                        # invalidation: doing so would leave a
                                        # completed-looking manifest that can never
                                        # rebuild after cleanup/restart.
                                        current = current.invalidate(name, reason="artifact_missing")
                                        self._persist(current)
                                        stage = current.stage(name)
                            else:
                                # A store-backed completed checkpoint without a
                                # reference is not reusable.  This can occur after
                                # a crash between artifact and manifest writes.
                                if self.store:
                                    current = current.invalidate(name, reason="artifact_reference_missing")
                                    self._persist(current)
                                    stage = current.stage(name)
                                else:
                                    checkpoint_loaded = True
                            if checkpoint_loaded:
                                # Reuse only when all recorded dependency hashes
                                # still match the upstream checkpoints.  This is a
                                # defensive guard for manually edited manifests or
                                # partial recovery, and keeps invalidation scoped to
                                # the first genuinely stale stage.
                                dependencies_match = all(
                                    current.stage(dep).output_hash == expected
                                    for dep, expected in stage.dependency_hashes.items()
                                )
                                if dependencies_match:
                                    continue
                                current = current.invalidate(name, reason="dependency_hash_changed")
                                self._persist(current)
                                stage = current.stage(name)
                        handler = handlers.get(name)
                        if handler is None:
                            # No handler is a valid partial Shadow run.  It remains
                            # resumable and does not pretend to have V2 evidence.
                            continue
                        input_payload = {"stage": name, "source_identity": current.source_identity, "pipeline_fingerprint": current.pipeline_fingerprint, "dependencies": {dep: current.stage(dep).output_hash for dep in STAGE_DEPENDENCIES[name]}, "stage_outputs": {dep: stage_outputs[dep] for dep in STAGE_DEPENDENCIES[name] if dep in stage_outputs}}
                        input_hash = content_hash(input_payload)
                        dependency_hashes = {
                            dep: current.stage(dep).output_hash
                            for dep in STAGE_DEPENDENCIES[name]
                            if current.stage(dep).output_hash
                        }
                        running = replace(
                            stage,
                            status=ShadowStageStatus.RUNNING,
                            input_hash=input_hash,
                            dependency_hashes=dependency_hashes,
                            attempt=stage.attempt + 1,
                            started_at=_now(),
                            error_code=None,
                            error_detail=None,
                            invalidated_reason=None,
                        )
                        current = current.with_stage(running)
                        self._persist(current)
                        output = handler() if not _handler_accepts_context(handler) else handler(run=current, stage=running, inputs=input_payload)  # type: ignore[misc]
                        if inspect.isawaitable(output):
                            output = await output
                        # Keep dependency values available for later handlers but
                        # never expose them through the manifest except as hashes.
                        stage_outputs[name] = copy.deepcopy(output)
                        reference = None
                        output_hash = content_hash(output)
                        if self.store:
                            reference, output_hash = self.store.write_artifact(current.run_id, name, output)
                            writes += 1
                            references.append(reference)
                        completed = replace(running, status=ShadowStageStatus.COMPLETED, output_hash=output_hash, fingerprint=content_hash({"stage": name, "pipeline": current.pipeline_fingerprint, "output": output}), artifact_reference=reference, completed_at=_now())
                        current = current.with_stage(completed)
                        self._persist(current)
                    result = ShadowRunResult(status=current.status, writes_performed=writes, artifact_references=tuple(references), run_id=current.run_id, first_invalid_stage=current.first_invalid_stage)
                except asyncio.CancelledError:
                    cancelled_name = next(
                        (
                            item.name
                            for item in current.stages
                            if item.status is ShadowStageStatus.RUNNING
                        ),
                        current.first_invalid_stage or SHADOW_STAGE_ORDER[-1],
                    )
                    cancelled = current.stage(cancelled_name)
                    cancelled = replace(
                        cancelled,
                        status=ShadowStageStatus.CANCELLED,
                        error_code="CANCELLED",
                        error_detail="shadow_execution_cancelled",
                        retry_count=cancelled.retry_count + 1,
                    )
                    current = replace(
                        current.with_stage(cancelled),
                        status="cancelled",
                        updated_at=_now(),
                    )
                    self._persist(current)
                    if self.store:
                        self.store.append_audit(
                            current.run_id,
                            {
                                "kind": "stage_cancelled",
                                "stage": cancelled_name,
                                "retryable": True,
                            },
                        )
                    result = ShadowRunResult(
                        status="cancelled",
                        writes_performed=writes,
                        artifact_references=tuple(references),
                        run_id=current.run_id,
                        first_invalid_stage=cancelled_name,
                        error="shadow_execution_cancelled",
                    )
                except Exception as exc:
                    failed_name = current.first_invalid_stage or SHADOW_STAGE_ORDER[-1]
                    failed = current.stage(failed_name)
                    current = current.with_stage(replace(failed, status=ShadowStageStatus.RETRYABLE, error_code=type(exc).__name__, error_detail=str(exc), retry_count=failed.retry_count + 1))
                    self._persist(current)
                    if self.store:
                        self.store.append_audit(current.run_id, {"kind": "stage_failure", "stage": failed_name, "error": type(exc).__name__, "detail": str(exc), "retryable": True})
                    result = ShadowRunResult(status="failed", writes_performed=writes, artifact_references=tuple(references), run_id=current.run_id, first_invalid_stage=failed_name, error=str(exc))
            finally:
                # A cancellation after a before-capture must still leave a
                # complete hash-only before/after audit.  The outer capture is
                # intentionally outside the nested stage handler try so a
                # cancellation during capture itself simply propagates without
                # fabricating an incomplete sentinel result.
                if contamination_before is not None:
                    await self._audit_contamination_inventory(current.run_id, contamination_before)
            if result is None:
                raise RuntimeError("Shadow execution ended without a result")
            return result

        return await self.queue.submit(key, execute)

    async def _capture_contamination_inventory(
        self,
        run_id: str,
        *,
        phase: str,
    ) -> FamilyContaminationInventory | None:
        """Capture injected family state without discovering a DB or runtime.

        The hook is disabled unless a caller supplies an explicit read-only
        provider or capture callback.  Capture failures are recorded only in
        the isolated Shadow audit and never change the legacy or Shadow result.
        """
        if self._contamination_provider is None and self._contamination_capture is None:
            return None
        try:
            value: FamilyContaminationInventory | Awaitable[FamilyContaminationInventory]
            if self._contamination_capture is not None:
                value = self._contamination_capture()
            else:
                assert self._contamination_provider is not None
                value = capture_family_inventory(self._contamination_provider)
            inventory = await value if inspect.isawaitable(value) else value
            if not isinstance(inventory, FamilyContaminationInventory):
                raise TypeError("contamination capture must return FamilyContaminationInventory")
            return inventory
        except Exception as exc:  # noqa: BLE001
            self._append_contamination_audit(
                run_id,
                {
                    "kind": "family_contamination_sentinel_capture_error",
                    "phase": phase,
                    "error_type": type(exc).__name__,
                },
            )
            return None

    async def _audit_contamination_inventory(
        self,
        run_id: str,
        before: FamilyContaminationInventory | None,
    ) -> None:
        if before is None:
            return
        after = await self._capture_contamination_inventory(run_id, phase="after")
        if after is None:
            return
        try:
            comparison = compare_family_inventories(before, after)
            self._append_contamination_audit(
                run_id,
                {
                    "kind": "family_contamination_sentinel",
                    "schema_version": comparison.schema_version,
                    "unchanged": comparison.unchanged,
                    "changed_domains": list(comparison.changed_domains),
                    "changed_components": {
                        name: list(values)
                        for name, values in comparison.changed_components.items()
                    },
                    "before_family_hashes": dict(before.family_hashes),
                    "after_family_hashes": dict(after.family_hashes),
                    "before_component_hashes": {
                        name: dict(values) for name, values in before.component_hashes.items()
                    },
                    "after_component_hashes": {
                        name: dict(values) for name, values in after.component_hashes.items()
                    },
                    "before_hash": comparison.before_hash,
                    "after_hash": comparison.after_hash,
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._append_contamination_audit(
                run_id,
                {
                    "kind": "family_contamination_sentinel_compare_error",
                    "error_type": type(exc).__name__,
                },
            )

    def _append_contamination_audit(self, run_id: str, event: Mapping[str, Any]) -> None:
        if not self.store:
            return
        try:
            self.store.append_audit(run_id, event)
        except Exception:  # noqa: BLE001
            # Sentinel evidence must never become a family/legacy failure.
            logger.warning("Could not write isolated contamination audit for %s", run_id, exc_info=True)

    def _persist(self, run: ShadowRun) -> None:
        if self.store:
            self.store.save_run(run)

    def resume(self, run: ShadowRun | str) -> str | None:
        current = self.store.load_run(run) if isinstance(run, str) and self.store else run
        if not isinstance(current, ShadowRun):
            raise ValueError("a ShadowRun or stored run id is required")
        return current.first_invalid_stage

    def invalidate(self, run: ShadowRun | str, stage: str, *, reason: str = "dependency_changed") -> ShadowRun:
        current = self.store.load_run(run) if isinstance(run, str) and self.store else run
        if not isinstance(current, ShadowRun):
            raise ValueError("a ShadowRun or stored run id is required")
        updated = current.invalidate(stage, reason=reason)
        self._persist(updated)
        if self.store:
            self.store.append_audit(updated.run_id, {"kind": "invalidation", "stage": _normalize_stage(stage), "reason": reason})
        return updated

    def invalidate_for_changes(self, run: ShadowRun | str, changes: Iterable[str]) -> ShadowRun:
        current = self.store.load_run(run) if isinstance(run, str) and self.store else run
        if not isinstance(current, ShadowRun):
            raise ValueError("a ShadowRun or stored run id is required")
        change_list = tuple(str(item) for item in changes)
        updated = current.invalidate_for_changes(change_list)
        self._persist(updated)
        if self.store and updated is not current:
            self.store.append_audit(updated.run_id, {"kind": "invalidation", "changes": list(change_list), "invalidated": list(invalidation_for_changes(change_list))})
        return updated

    def diff(self, left: ShadowRun | str, right: ShadowRun | str) -> ShadowDiff:
        left_run = self.store.load_run(left) if isinstance(left, str) and self.store else left
        right_run = self.store.load_run(right) if isinstance(right, str) and self.store else right
        if not isinstance(left_run, ShadowRun) or not isinstance(right_run, ShadowRun):
            raise ValueError("diff requires ShadowRun objects or stored run ids")
        return diff_runs(left_run, right_run)

    def cleanup(self, run: ShadowRun | str) -> tuple[str, ...]:
        if not self.store:
            return ()
        run_id = run.run_id if isinstance(run, ShadowRun) else str(run)
        removed = self.store.cleanup_rebuildable(run_id)
        self.store.append_audit(run_id, {"kind": "cleanup", "removed": list(removed), "retained": [SHADOW_MANIFEST_FILENAME, SHADOW_AUDIT_FILENAME, "golden", "source", "reviews", "corrections"]})
        return removed


def _handler_accepts_context(handler: Any) -> bool:
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return False
    return any(parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.name in {"run", "stage", "inputs"} for parameter in signature.parameters.values())


def _manifest_source_identity(source_identity: Mapping[str, Any]) -> dict[str, str]:
    """Remove ephemeral/private path hints before persisting a run manifest."""
    forbidden = {"source_path", "video_path", "path", "private_path", "local_path"}
    return {
        str(key): str(value)
        for key, value in source_identity.items()
        if str(key) not in forbidden and value not in (None, "")
    }


class NoOpShadowOrchestrator:
    """Compatibility boundary retained for Iteration 0 callers/tests."""

    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config

    async def run(self, legacy_result: Mapping[str, Any]) -> ShadowRunResult:
        del legacy_result
        status = "ready" if self._config.pipeline_mode is PipelineMode.SHADOW else "disabled"
        return ShadowRunResult(status=status, writes_performed=0, artifact_references=())


class ShadowRunner(Protocol):
    async def run(self, legacy_result: Mapping[str, Any]) -> ShadowRunResult: ...


def load_golden_fixture(path: Path) -> dict[str, Any]:
    """Read a private Golden manifest as a test fixture, without copying it."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "golden-dataset.v2":
        raise ValueError("invalid Golden V2 fixture")
    return payload


def golden_fixture_summary(path: Path) -> dict[str, Any]:
    payload = load_golden_fixture(path)
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    return {
        "schema_version": payload["schema_version"],
        "revision": (payload.get("revision") or {}).get("revision"),
        "source_count": len(sources),
        "event_count": len(events),
        "track_count": len(payload.get("tracks") or []),
        "pose_count": len(payload.get("poses") or []),
        "profiles": {profile: sum(1 for event in events if event.get("profile") == profile) for profile in sorted({event.get("profile") for event in events})},
        "fixture_fingerprint": content_hash(payload),
    }
