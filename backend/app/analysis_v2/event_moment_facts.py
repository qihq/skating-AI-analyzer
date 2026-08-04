from __future__ import annotations

"""Revisioned, event-scoped moment proposals.

These records replace V2 mutations of legacy whole-analysis T/A/L fields.  A
legacy snapshot is retained verbatim for history/rollback and is never
reinterpreted as a new definition.
"""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from app.analysis_v2.contracts import ContractModel, EventMomentSet


ProposalStatus = Literal["proposed", "applied", "dismissed"]
ProposalSource = Literal["manual", "legacy_keyframe_correction", "video_keyframe_rerun"]


class EventMomentProposalRevision(ContractModel):
    schema_version: Literal["event-moment-proposal.v1"] = "event-moment-proposal.v1"
    analysis_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    status: ProposalStatus = "proposed"
    source: ProposalSource
    before: EventMomentSet | None = None
    after: EventMomentSet
    legacy_snapshot: dict[str, Any] = Field(default_factory=dict)
    human_provenance: dict[str, Any] = Field(default_factory=dict)
    invalidates: tuple[str, ...] = (
        "analysis_experience_v2",
        "analysis_facts_v2",
        "report",
        "share_thumbnail",
        "representative_media",
        "compare_moment_pairs",
        "evidence_export",
    )
    report_regeneration_required: bool = True
    created_at: str

    @model_validator(mode="after")
    def valid_revision(self) -> "EventMomentProposalRevision":
        if self.after.event_id != self.event_id or (self.before is not None and self.before.event_id != self.event_id):
            raise ValueError("moment proposal snapshots must be event-scoped")
        if self.parent_revision is not None and self.parent_revision >= self.revision:
            raise ValueError("parent revision must precede the proposal revision")
        if self.source in {"legacy_keyframe_correction", "video_keyframe_rerun"} and not self.legacy_snapshot:
            raise ValueError("legacy migrations must preserve their original snapshot")
        return self


def propose_event_moments(
    *, analysis_id: str, event_id: str, after: EventMomentSet,
    source: ProposalSource = "manual", parent: EventMomentProposalRevision | None = None,
    before: EventMomentSet | None = None, legacy_snapshot: dict[str, Any] | None = None,
    reviewer: str = "parent",
) -> EventMomentProposalRevision:
    revision = (parent.revision + 1) if parent else 1
    effective_before = before or (parent.after if parent else None)
    return EventMomentProposalRevision(
        analysis_id=analysis_id,
        event_id=event_id,
        revision=revision,
        parent_revision=parent.revision if parent else None,
        source=source,
        before=effective_before,
        after=after.model_copy(update={"revision": revision}),
        legacy_snapshot=dict(legacy_snapshot or (parent.legacy_snapshot if parent else {})),
        human_provenance={"reviewer": reviewer, "kind": "event_moment_proposal", "source": "human_revision"},
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def apply_event_moments(revision: EventMomentProposalRevision, *, reviewer: str = "parent") -> EventMomentProposalRevision:
    return revision.model_copy(update={"status": "applied", "human_provenance": {**revision.human_provenance, "applied_by": reviewer}})


def dismiss_event_moments(revision: EventMomentProposalRevision, *, reviewer: str = "parent") -> EventMomentProposalRevision:
    return revision.model_copy(update={"status": "dismissed", "human_provenance": {**revision.human_provenance, "dismissed_by": reviewer}})


def latest_applied_event_moments(revisions: list[EventMomentProposalRevision]) -> EventMomentProposalRevision | None:
    latest_by_revision = {item.revision: item for item in revisions}
    applied = [item for item in latest_by_revision.values() if item.status == "applied"]
    return max(applied, key=lambda item: item.revision) if applied else None


def migrate_legacy_keyframe_proposal(
    *, analysis_id: str, event_id: str, profile: Literal["jump", "spin", "step", "spiral"],
    legacy_correction: dict[str, Any], adapted_after: EventMomentSet,
    source: Literal["legacy_keyframe_correction", "video_keyframe_rerun"],
    parent: EventMomentProposalRevision | None = None,
) -> EventMomentProposalRevision:
    """Wrap an existing correction/rerun without mutating its T/A/L snapshot."""
    return propose_event_moments(
        analysis_id=analysis_id,
        event_id=event_id,
        after=adapted_after,
        source=source,
        parent=parent,
        legacy_snapshot={
            "profile_at_creation": profile,
            "stored_payload": legacy_correction,
            "definition_version": "legacy-key-moment.v1",
            "reinterpretation_allowed": False,
        },
    )
