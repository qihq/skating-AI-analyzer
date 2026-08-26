from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, model_validator

from app.analysis_v2.contracts import ContractModel


PROFILE_KEYS = ("jump", "spin", "step", "spiral")
SOURCE_ONLY_PHYSICAL_LOCALIZATION_VERSION = "source_only_physical_localization.v2"


class ProposalEvidenceSample(ContractModel):
    schema_version: Literal["proposal-evidence-sample.v1"] = "proposal-evidence-sample.v1"
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    camera_compensated_track_motion: float = Field(default=0, ge=0, le=1)
    pose_dynamics: float = Field(default=0, ge=0, le=1)
    ice_contact_proxy: float = Field(default=0, ge=0, le=1)
    periodicity: float = Field(default=0, ge=0, le=1)
    extension_hold: float = Field(default=0, ge=0, le=1)
    edge_complexity: float = Field(default=0, ge=0, le=1)
    semantic_hints: dict[str, float] = Field(default_factory=dict)
    tracking_observable: bool = True
    pose_observable: bool = False
    camera_reliability: float = Field(default=1, ge=0, le=1)
    provenance: tuple[str, ...] = ()

    @model_validator(mode="after")
    def bounded_hints(self) -> "ProposalEvidenceSample":
        if any(key not in PROFILE_KEYS or value < 0 or value > 1 for key, value in self.semantic_hints.items()):
            raise ValueError("semantic hints must be bounded family hints")
        return self


class EventProposal(ContractModel):
    schema_version: Literal["event-proposal.v1"] = "event-proposal.v1"
    event_id: str = Field(min_length=1)
    source_video_hash: str = Field(min_length=1)
    start_pts: float = Field(ge=0)
    end_pts: float = Field(ge=0)
    anchor_start_frame: int = Field(ge=0)
    anchor_end_frame: int = Field(ge=0)
    candidate_profile_scores: dict[str, float]
    proposed_profile: Literal["unknown"] = "unknown"
    status: Literal["pending_confirmation", "confirmed_window", "ignored", "ordinary_skating", "unknown"] = "pending_confirmation"
    tracking_coverage: float = Field(ge=0, le=1)
    pose_coverage: float = Field(ge=0, le=1)
    observability: Literal["observable", "partially_observable", "unobservable"]
    evidence_sources: tuple[str, ...] = ()
    provenance_fingerprint: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    parent_event_ids: tuple[str, ...] = ()
    superseded_event_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def ordered(self) -> "EventProposal":
        if self.end_pts <= self.start_pts or self.anchor_end_frame < self.anchor_start_frame:
            raise ValueError("proposal interval must be ordered")
        if set(self.candidate_profile_scores) != set(PROFILE_KEYS):
            raise ValueError("candidate scores must cover every family without classifying")
        if any(value < 0 or value > 1 for value in self.candidate_profile_scores.values()):
            raise ValueError("candidate profile scores must be bounded")
        return self


class EventProposalCollection(ContractModel):
    schema_version: Literal["event-proposal-collection.v1"] = "event-proposal-collection.v1"
    source_video_hash: str = Field(min_length=1)
    source_duration_sec: float = Field(gt=0)
    pipeline_fingerprint: str = Field(min_length=1)
    proposals: tuple[EventProposal, ...] = ()
    diagnostic_only: bool = True
    classifier_labels_consumed: Literal[False] = False
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def ordered_unique(self) -> "EventProposalCollection":
        ids = [item.event_id for item in self.proposals]
        if len(ids) != len(set(ids)):
            raise ValueError("proposal event IDs must be unique")
        if list(self.proposals) != sorted(self.proposals, key=lambda item: (item.start_pts, item.end_pts, item.event_id)):
            raise ValueError("proposals must be source-time ordered")
        return self


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _event_id(source_video_hash: str, start_frame: int, end_frame: int) -> str:
    digest = hashlib.sha256(f"{source_video_hash}:{start_frame}:{end_frame}:proposal-v1".encode()).hexdigest()[:20]
    return f"evt-{digest}"


def _activation(sample: ProposalEvidenceSample) -> float:
    # Semantic hints are deliberately capped: they can support a physical proposal,
    # but cannot create/localize an event on their own.
    semantic = min(max(sample.semantic_hints.values(), default=0.0), 0.35)
    if "source_only_adapter" in sample.provenance:
        motion = sample.camera_compensated_track_motion * sample.camera_reliability
        strong_state = max(
            sample.ice_contact_proxy if sample.ice_contact_proxy >= .55 else 0.0,
            sample.periodicity if sample.periodicity >= .45 else 0.0,
            sample.extension_hold if sample.extension_hold >= .42 else 0.0,
            sample.edge_complexity if sample.edge_complexity >= .48 else 0.0,
        )
        multi_signal_change = 0.0
        if sample.pose_dynamics >= .25 and motion >= .20 and sample.edge_complexity >= .30:
            multi_signal_change = .45 * sample.pose_dynamics + .25 * motion + .30 * sample.edge_complexity
        return max(.92 * strong_state, multi_signal_change, .10 * semantic)
    physical = max(
        sample.camera_compensated_track_motion * sample.camera_reliability,
        sample.pose_dynamics,
        sample.ice_contact_proxy,
        sample.periodicity,
        sample.extension_hold,
        sample.edge_complexity,
    )
    blended = (
        0.38 * sample.camera_compensated_track_motion * sample.camera_reliability
        + 0.30 * sample.pose_dynamics
        + 0.18 * sample.ice_contact_proxy
        + 0.14 * sample.periodicity
        + 0.16 * sample.extension_hold
        + 0.12 * sample.edge_complexity
        + 0.10 * semantic
    )
    return max(physical * 0.72, blended) if physical >= 0.12 else 0.0


def _source_only_localization_activation(sample: ProposalEvidenceSample) -> float:
    """Score a source-only physical co-occurrence without selecting a family.

    Source-only observations have no decoder-dense semantic labels. A localized
    proposal may still be formed when observable, identity-consistent motion
    co-occurs with observable pose dynamics. A single weak feature is deliberately
    not enough; the broad observation envelope remains the recall-only fallback.
    """
    if "source_only_adapter" not in sample.provenance:
        return 0.0
    motion = sample.camera_compensated_track_motion * sample.camera_reliability
    pose = sample.pose_dynamics
    edge = sample.edge_complexity
    if not (
        sample.tracking_observable
        and sample.pose_observable
        and motion >= 0.20
        and pose >= 0.15
    ):
        return 0.0
    return max(
        0.16,
        min(1.0, 0.50 * motion + 0.30 * pose + 0.20 * edge),
    )


def _proposal_activation(
    sample: ProposalEvidenceSample,
    *,
    source_only_localization_upgrade: bool,
) -> float:
    upgrade = _source_only_localization_activation(sample) if source_only_localization_upgrade else 0.0
    return max(_activation(sample), upgrade)


def _candidate_scores(samples: Sequence[ProposalEvidenceSample]) -> dict[str, float]:
    def mean(values: Sequence[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    pose = mean([item.pose_dynamics for item in samples])
    contact = mean([item.ice_contact_proxy for item in samples])
    periodic = mean([item.periodicity for item in samples])
    motion = mean([item.camera_compensated_track_motion * item.camera_reliability for item in samples])
    extension = mean([item.extension_hold for item in samples])
    edge = mean([item.edge_complexity for item in samples])
    semantic = {key: min(mean([item.semantic_hints.get(key, 0.0) for item in samples]), 0.20) for key in PROFILE_KEYS}
    raw = {
        "jump": 0.36 * pose + 0.34 * contact + 0.20 * motion + semantic["jump"],
        "spin": 0.42 * periodic + 0.26 * pose + 0.16 * motion + semantic["spin"],
        "step": 0.36 * edge + 0.20 * periodic + 0.16 * contact + 0.14 * pose + semantic["step"],
        "spiral": 0.46 * extension + 0.20 * pose + 0.12 * motion + semantic["spiral"],
    }
    return {key: round(max(0.0, min(1.0, value)), 6) for key, value in raw.items()}


def _build_proposal(source_video_hash: str, samples: Sequence[ProposalEvidenceSample], *, start_pts: float, end_pts: float, source: str) -> EventProposal:
    tracking = sum(item.tracking_observable for item in samples) / len(samples)
    pose = sum(item.pose_observable for item in samples) / len(samples)
    observability = "observable" if tracking >= 0.8 and pose >= 0.5 else "partially_observable" if tracking > 0 or pose > 0 else "unobservable"
    start_frame = samples[0].source_frame_index
    end_frame = samples[-1].source_frame_index
    evidence_sources = tuple(sorted({source, *(part for item in samples for part in item.provenance)}))
    fingerprint_payload = {
        "source": source_video_hash,
        "frames": [start_frame, end_frame],
        "pts": [round(start_pts, 6), round(end_pts, 6)],
        "evidence": evidence_sources,
        "scores": _candidate_scores(samples),
    }
    return EventProposal(
        event_id=_event_id(source_video_hash, start_frame, end_frame),
        source_video_hash=source_video_hash,
        start_pts=round(start_pts, 6),
        end_pts=round(end_pts, 6),
        anchor_start_frame=start_frame,
        anchor_end_frame=end_frame,
        candidate_profile_scores=_candidate_scores(samples),
        tracking_coverage=round(tracking, 6),
        pose_coverage=round(pose, 6),
        observability=observability,
        evidence_sources=evidence_sources,
        provenance_fingerprint=_hash(fingerprint_payload),
    )


def generate_event_proposals(
    *,
    source_video_hash: str,
    source_duration_sec: float,
    samples: Sequence[ProposalEvidenceSample],
    pipeline_fingerprint: str,
    activation_threshold: float = 0.16,
    max_active_gap_sec: float = 0.32,
    distinct_valley_sec: float = 0.32,
    padding_sec: float = 0.20,
    source_only_localization_upgrade: bool = True,
) -> EventProposalCollection:
    ordered = sorted(samples, key=lambda item: (item.pts_sec, item.source_frame_index))
    active = []
    for item in ordered:
        legacy_activation = _activation(item)
        upgraded_activation = max(
            legacy_activation,
            _source_only_localization_activation(item) if source_only_localization_upgrade else 0.0,
        )
        active.append((item, legacy_activation, upgraded_activation))
    active = [item for item in active if item[2] >= activation_threshold]
    clusters: list[list[tuple[ProposalEvidenceSample, float, float]]] = []
    for item in active:
        if not clusters or item[0].pts_sec - clusters[-1][-1][0].pts_sec > max_active_gap_sec:
            clusters.append([item])
        else:
            clusters[-1].append(item)

    proposals: list[EventProposal] = []
    for active_cluster in clusters:
        cluster = [item for item, _, _ in active_cluster]
        legacy_active = any(legacy >= activation_threshold for _, legacy, _ in active_cluster)
        if not legacy_active and len({(item.pts_sec, item.source_frame_index) for item in cluster}) < 2:
            continue
        start = max(0.0, cluster[0].pts_sec - padding_sec)
        end = min(source_duration_sec, cluster[-1].pts_sec + padding_sec)
        if end - start < 0.18:
            end = min(source_duration_sec, start + 0.18)
        proposal = _build_proposal(source_video_hash, cluster, start_pts=start, end_pts=end, source="multi_signal_cluster")
        upgrade_contributed = any(
            legacy < activation_threshold <= upgraded
            for _, legacy, upgraded in active_cluster
        )
        if upgrade_contributed:
            proposal = proposal.model_copy(update={
                "evidence_sources": tuple(sorted({
                    *proposal.evidence_sources,
                    SOURCE_ONLY_PHYSICAL_LOCALIZATION_VERSION,
                })),
            })
        proposals.append(proposal)

    # Merge genuinely overlapping evidence, but retain a measurable valley between
    # consecutive events. This prevents jump->spin from becoming one action.
    merged: list[EventProposal] = []
    for proposal in proposals:
        if not merged or proposal.start_pts - merged[-1].end_pts >= distinct_valley_sec:
            merged.append(proposal)
            continue
        previous = merged[-1]
        if proposal.start_pts <= previous.end_pts:
            joined_samples = [
                item
                for item in ordered
                if previous.start_pts <= item.pts_sec <= proposal.end_pts
                and _proposal_activation(
                    item,
                    source_only_localization_upgrade=source_only_localization_upgrade,
                ) >= activation_threshold
            ]
            combined = _build_proposal(source_video_hash, joined_samples, start_pts=previous.start_pts, end_pts=max(previous.end_pts, proposal.end_pts), source="overlap_merge")
            combined_sources = combined.evidence_sources
            if any(
                SOURCE_ONLY_PHYSICAL_LOCALIZATION_VERSION in item.evidence_sources
                for item in (previous, proposal)
            ):
                combined_sources = tuple(sorted({
                    *combined_sources,
                    SOURCE_ONLY_PHYSICAL_LOCALIZATION_VERSION,
                }))
            merged[-1] = combined.model_copy(update={
                "evidence_sources": combined_sources,
                "superseded_event_ids": (previous.event_id, proposal.event_id),
            })
        else:
            merged.append(proposal)

    # Sparse legacy observations cannot localize a narrow event safely. Preserve
    # recall with an explicit unknown broad envelope, never a forced family label.
    observable_points = [item for item in ordered if item.tracking_observable]
    legacy_sparse = any("legacy_motion_fixture" in item.provenance for item in ordered)
    if legacy_sparse and len(ordered) < 120 and observable_points:
        coverage = sum(item.end_pts - item.start_pts for item in merged) / source_duration_sec if merged else 0.0
        if coverage < 0.8:
            broad = _build_proposal(source_video_hash, observable_points, start_pts=0.0, end_pts=source_duration_sec, source="sparse_observability_envelope")
            merged = [broad]

    # Source-only sampling is designed for family classification evidence, not
    # decoder-dense boundary refinement. When no localized physical cluster is
    # observable, retain an explicit unknown proposal over the observed source
    # timeline so proposal recall remains independent from classification and
    # downstream profile confirmation. This is not an event boundary claim.
    source_only = any("source_only_adapter" in item.provenance for item in ordered)
    localized_coverage = interval_union_coverage(merged, source_duration_sec)
    if source_only and len(observable_points) >= 2 and localized_coverage < 0.8:
        broad = _build_proposal(
            source_video_hash,
            observable_points,
            start_pts=observable_points[0].pts_sec,
            end_pts=source_duration_sec,
            source="unlocalized_observability_envelope",
        )
        merged = [broad.model_copy(update={"status": "unknown"}), *merged]

    return EventProposalCollection(
        source_video_hash=source_video_hash,
        source_duration_sec=source_duration_sec,
        pipeline_fingerprint=pipeline_fingerprint,
        proposals=tuple(sorted(merged, key=lambda item: (item.start_pts, item.end_pts, item.event_id))),
    )


def merge_proposals(collection: EventProposalCollection, event_ids: Sequence[str]) -> EventProposalCollection:
    selected = [item for item in collection.proposals if item.event_id in set(event_ids)]
    if len(selected) < 2:
        raise ValueError("merge requires at least two event IDs")
    ordered = sorted(selected, key=lambda item: item.start_pts)
    survivor = ordered[0]
    scores = {key: max(item.candidate_profile_scores[key] for item in ordered) for key in PROFILE_KEYS}
    updated = survivor.model_copy(update={
        "end_pts": max(item.end_pts for item in ordered),
        "anchor_end_frame": max(item.anchor_end_frame for item in ordered),
        "candidate_profile_scores": scores,
        "tracking_coverage": round(sum(item.tracking_coverage for item in ordered) / len(ordered), 6),
        "pose_coverage": round(sum(item.pose_coverage for item in ordered) / len(ordered), 6),
        "observability": "partially_observable" if any(item.observability != "observable" for item in ordered) else "observable",
        "revision": max(item.revision for item in ordered) + 1,
        "parent_event_ids": tuple(item.event_id for item in ordered),
        "superseded_event_ids": tuple(item.event_id for item in ordered[1:]),
        "evidence_sources": tuple(sorted({"human_merge", *(source for item in ordered for source in item.evidence_sources)})),
        "provenance_fingerprint": _hash({"operation": "merge", "events": [item.model_dump(mode="json") for item in ordered]}),
    })
    remaining = [item for item in collection.proposals if item.event_id not in set(event_ids)] + [updated]
    return collection.model_copy(update={"proposals": tuple(sorted(remaining, key=lambda item: (item.start_pts, item.end_pts, item.event_id))), "revision": collection.revision + 1})


def split_proposal(collection: EventProposalCollection, event_id: str, split_pts: float) -> EventProposalCollection:
    proposal = next((item for item in collection.proposals if item.event_id == event_id), None)
    if proposal is None or not proposal.start_pts < split_pts < proposal.end_pts:
        raise ValueError("split PTS must be inside the selected event")
    ratio = (split_pts - proposal.start_pts) / (proposal.end_pts - proposal.start_pts)
    split_frame = max(proposal.anchor_start_frame, min(proposal.anchor_end_frame, round(proposal.anchor_start_frame + ratio * (proposal.anchor_end_frame - proposal.anchor_start_frame))))
    left = proposal.model_copy(update={
        "end_pts": round(split_pts, 6), "anchor_end_frame": split_frame, "revision": proposal.revision + 1,
        "parent_event_ids": (proposal.event_id,), "evidence_sources": tuple(sorted({*proposal.evidence_sources, "human_split"})),
        "provenance_fingerprint": _hash({"operation": "split-left", "event": proposal.event_id, "pts": split_pts}),
    })
    right_id = _event_id(collection.source_video_hash, split_frame + 1, proposal.anchor_end_frame)
    right = proposal.model_copy(update={
        "event_id": right_id, "start_pts": round(split_pts, 6), "anchor_start_frame": min(proposal.anchor_end_frame, split_frame + 1),
        "revision": proposal.revision + 1, "parent_event_ids": (proposal.event_id,),
        "evidence_sources": tuple(sorted({*proposal.evidence_sources, "human_split"})),
        "provenance_fingerprint": _hash({"operation": "split-right", "event": proposal.event_id, "pts": split_pts}),
    })
    remaining = [item for item in collection.proposals if item.event_id != event_id] + [left, right]
    return collection.model_copy(update={"proposals": tuple(sorted(remaining, key=lambda item: (item.start_pts, item.end_pts, item.event_id))), "revision": collection.revision + 1})


def set_proposal_outcome(collection: EventProposalCollection, event_id: str, outcome: Literal["ignored", "ordinary_skating", "unknown", "confirmed_window"]) -> EventProposalCollection:
    if not any(item.event_id == event_id for item in collection.proposals):
        raise ValueError("event ID not found")
    proposals = tuple(item.model_copy(update={
        "status": outcome, "revision": item.revision + 1,
        "evidence_sources": tuple(sorted({*item.evidence_sources, "human_review"})),
        "provenance_fingerprint": _hash({"operation": outcome, "event": item.event_id, "revision": item.revision + 1}),
    }) if item.event_id == event_id else item for item in collection.proposals)
    return collection.model_copy(update={"proposals": proposals, "revision": collection.revision + 1})


def interval_union_coverage(proposals: Sequence[EventProposal], duration_sec: float) -> float:
    intervals = sorted((item.start_pts, item.end_pts) for item in proposals if item.status != "ignored")
    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return min(1.0, sum(end - start for start, end in merged) / max(duration_sec, 1e-9))
