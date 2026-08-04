from __future__ import annotations

"""Revisioned action-label facts used by the V2 correction boundary."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ActionProfile = Literal["jump", "spin", "step", "spiral"]
ClassificationState = Literal["confirmed", "ambiguous", "unknown"]


LabelStatus = Literal["proposed", "applied", "dismissed"]


class EventLabelFactRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["event-label-fact.v1"] = "event-label-fact.v1"
    analysis_id: str
    event_id: str
    revision: int = Field(ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    profile: ActionProfile | None
    subtype: str | None
    state: ClassificationState
    status: LabelStatus
    value: dict[str, Any]
    legacy_snapshot: dict[str, Any]
    human_provenance: dict[str, Any]
    created_at: str

    @model_validator(mode="after")
    def profile_matches_state(self) -> "EventLabelFactRevision":
        if self.state == "unknown" and self.profile is not None:
            raise ValueError("unknown event-label fact cannot carry a profile")
        if self.state != "unknown" and self.profile is None:
            raise ValueError("confirmed or ambiguous event-label fact requires a profile")
        return self


def propose_event_label_fact(
    *, analysis_id: str, event_id: str, profile: ActionProfile | None, subtype: str | None,
    state: ClassificationState = "ambiguous", parent: EventLabelFactRevision | None = None,
    legacy_snapshot: dict[str, Any] | None = None, reviewer: str = "parent",
) -> EventLabelFactRevision:
    revision = (parent.revision + 1) if parent else 1
    return EventLabelFactRevision(
        analysis_id=analysis_id, event_id=event_id, revision=revision,
        parent_revision=parent.revision if parent else None, profile=profile, subtype=subtype,
        state=state, status="proposed", value={"profile": profile, "subtype": subtype, "state": state},
        legacy_snapshot=dict(legacy_snapshot or (parent.legacy_snapshot if parent else {})),
        human_provenance={"reviewer": reviewer, "kind": "event_label_fact", "source": "human_revision"},
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def apply_event_label_fact(revision: EventLabelFactRevision, *, reviewer: str = "parent") -> EventLabelFactRevision:
    return revision.model_copy(update={"status": "applied", "human_provenance": {**revision.human_provenance, "applied_by": reviewer}})


def dismiss_event_label_fact(revision: EventLabelFactRevision, *, reviewer: str = "parent") -> EventLabelFactRevision:
    return revision.model_copy(update={"status": "dismissed", "human_provenance": {**revision.human_provenance, "dismissed_by": reviewer}})


def latest_applied_event_label_fact(revisions: list[EventLabelFactRevision]) -> EventLabelFactRevision | None:
    latest_by_revision: dict[int, EventLabelFactRevision] = {}
    for item in revisions:
        latest_by_revision[item.revision] = item
    applied = [item for item in latest_by_revision.values() if item.status == "applied"]
    return max(applied, key=lambda item: item.revision) if applied else None
