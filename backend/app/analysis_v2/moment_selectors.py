from __future__ import annotations

"""One profile-specific source-time selector for downstream media consumers."""

from typing import Any, Literal

from pydantic import Field

from app.analysis_v2.contracts import ContractModel, EventMomentSet, KeyMoment


Consumer = Literal[
    "follow_up_chip", "monthly_representative", "annual_representative",
    "compare_pair", "report_thumbnail", "share_thumbnail", "pose_debug_link",
    "evidence_export",
]


class MomentMediaReference(ContractModel):
    schema_version: Literal["moment-media-reference.v1"] = "moment-media-reference.v1"
    event_id: str
    semantic_key: str
    definition_version: str
    source_frame_index: int = Field(ge=0)
    source_pts_sec: float = Field(ge=0)
    end_source_frame_index: int | None = Field(default=None, ge=0)
    end_source_pts_sec: float | None = Field(default=None, ge=0)
    observability: Literal["observed", "partial"]
    confidence: float = Field(ge=0, le=1)
    provenance: tuple[str, ...] = ()


PREFERRED_KEYS: dict[str, tuple[str, ...]] = {
    "jump": ("apex", "takeoff", "landing"),
    "spin": ("spin_main", "spin_entry", "spin_exit"),
    "spiral": ("spiral_hold", "spiral_entry", "spiral_exit"),
    "step": ("step_representative_1", "step_representative_2", "step_sequence_interval"),
}


def _reference(moment: KeyMoment) -> MomentMediaReference | None:
    if moment.status == "unavailable" or moment.source_frame_index is None or moment.pts_sec is None:
        return None
    return MomentMediaReference(
        event_id=moment.event_id,
        semantic_key=moment.semantic_key,
        definition_version=moment.definition_version,
        source_frame_index=moment.source_frame_index,
        source_pts_sec=moment.pts_sec,
        end_source_frame_index=moment.end_source_frame_index,
        end_source_pts_sec=moment.end_pts_sec,
        observability=moment.observability if moment.observability != "unobservable" else "partial",
        confidence=moment.confidence,
        provenance=moment.provenance,
    )


def select_profile_moment(
    moments: EventMomentSet,
    *, consumer: Consumer, semantic_key: str | None = None,
    allow_ambiguous_for_review: bool = False,
) -> MomentMediaReference | None:
    """Return an exact source reference or None; never synthesize/fallback."""
    candidates = {item.semantic_key: item for item in moments.moments}
    keys = (semantic_key,) if semantic_key else PREFERRED_KEYS[moments.profile]
    for key in keys:
        item = candidates.get(key)
        if item is None or item.status == "unavailable":
            continue
        if item.status == "ambiguous" and not (allow_ambiguous_for_review and consumer in {"follow_up_chip", "pose_debug_link", "evidence_export"}):
            continue
        return _reference(item)
    return None


def select_compare_pair(left: EventMomentSet, right: EventMomentSet, semantic_key: str) -> tuple[MomentMediaReference, MomentMediaReference] | None:
    if left.profile != right.profile or left.definition_version != right.definition_version:
        return None
    left_ref = select_profile_moment(left, consumer="compare_pair", semantic_key=semantic_key)
    right_ref = select_profile_moment(right, consumer="compare_pair", semantic_key=semantic_key)
    return (left_ref, right_ref) if left_ref is not None and right_ref is not None else None


def applied_moment_sets_from_record(record: Any) -> tuple[EventMomentSet, ...]:
    """Read the latest applied revision per event without touching legacy fields."""
    from app.analysis_v2.event_moment_facts import EventMomentProposalRevision

    stored = record.get("processing_logs") if isinstance(record, dict) else getattr(record, "processing_logs", None)
    latest: dict[tuple[str, int], EventMomentProposalRevision] = {}
    if isinstance(stored, list):
        for item in stored:
            if not isinstance(item, dict) or not isinstance(item.get("event_moment_proposal"), dict):
                continue
            proposal = EventMomentProposalRevision.model_validate(item["event_moment_proposal"])
            latest[(proposal.event_id, proposal.revision)] = proposal
    applied = [proposal for proposal in latest.values() if proposal.status == "applied"]
    latest_by_event: dict[str, EventMomentProposalRevision] = {}
    for proposal in applied:
        if proposal.event_id not in latest_by_event or proposal.revision > latest_by_event[proposal.event_id].revision:
            latest_by_event[proposal.event_id] = proposal
    return tuple(proposal.after for proposal in sorted(latest_by_event.values(), key=lambda item: (item.event_id, item.revision)))
