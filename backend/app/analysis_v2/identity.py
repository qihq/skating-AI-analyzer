from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol, Sequence

from app.analysis_v2.contracts import (
    IdentityAnchor,
    IdentityAnchorRevision,
    IdentityConflictInterval,
    IdentityEvidence,
    IdentityFeatureReliability,
    IdentityTimeline,
    IdentityTimelineSegment,
    TrackState,
)

IDENTITY_SIGNALS = ("appearance", "body_shape", "camera_motion", "bbox_continuity", "face")


@dataclass(frozen=True)
class IdentityWeights:
    appearance: float = 0.30
    body_shape: float = 0.20
    camera_motion: float = 0.20
    bbox_continuity: float = 0.25
    face: float = 0.05

    def normalized(self, reliability: IdentityFeatureReliability) -> dict[str, float]:
        raw = {name: getattr(self, name) * getattr(reliability, name) for name in IDENTITY_SIGNALS}
        total = sum(raw.values())
        return {name: value / total for name, value in raw.items()} if total else {name: 0.0 for name in IDENTITY_SIGNALS}


@dataclass(frozen=True)
class IdentityTemplateBank:
    immutable_manual: tuple[str, ...]
    short_term_adaptive: tuple[str, ...] = ()

    def update_adaptive(self, fingerprint: str, *, allowed: bool) -> "IdentityTemplateBank":
        if not allowed:
            return self
        recent = (*self.short_term_adaptive[-7:], fingerprint)
        return IdentityTemplateBank(immutable_manual=self.immutable_manual, short_term_adaptive=recent)


class FaceEvidenceProvider(Protocol):
    enabled: bool

    def compare(self, anchor: IdentityAnchor, candidate_crop: object) -> tuple[float, float]:
        """Return (similarity, reliability); identity fusion remains authoritative."""


def immutable_template_fingerprint(anchor: IdentityAnchor) -> str:
    return hashlib.sha256(f"{anchor.anchor_id}|{anchor.source_frame_index}|{anchor.bbox}".encode()).hexdigest()


def score_identity_evidence(candidate_id: str, signal_scores: Mapping[str, float], reliability: IdentityFeatureReliability, *, weights: IdentityWeights = IdentityWeights(), reasons: Sequence[str] = ()) -> IdentityEvidence:
    clean = {name: max(0.0, min(1.0, float(signal_scores.get(name, 0.0)))) for name in IDENTITY_SIGNALS}
    effective = weights.normalized(reliability)
    score = sum(clean[name] * effective[name] for name in IDENTITY_SIGNALS)
    return IdentityEvidence(candidate_id=candidate_id, score=max(0.0, min(1.0, score)), reliability=reliability, signal_scores=clean, reasons=tuple(reasons))


def classify_identity(ranked: Sequence[IdentityEvidence], *, margin_threshold: float = 0.12, score_threshold: float = 0.62, crossing: bool = False, recovery: bool = False, stabilization: bool = False, bbox_source: str = "measured") -> tuple[str, IdentityEvidence | None, float, tuple[str, ...]]:
    if not ranked:
        return "lost", None, 0.0, ("no_candidate",)
    ordered = sorted(ranked, key=lambda item: item.score, reverse=True)
    best = ordered[0]
    second = ordered[1].score if len(ordered) > 1 else 0.0
    margin = max(0.0, best.score - second)
    reasons: list[str] = []
    if bbox_source != "measured": reasons.append("display_hint_not_authoritative")
    if crossing: reasons.append("crossing_guard")
    if recovery: reasons.append("uncertain_recovery")
    if stabilization: reasons.append("relock_stabilization")
    if bbox_source != "measured" or crossing or recovery or stabilization or best.score < score_threshold or margin < margin_threshold:
        if best.score < score_threshold: reasons.append("low_identity_score")
        if margin < margin_threshold: reasons.append("low_identity_margin")
        return "uncertain", best, margin, tuple(dict.fromkeys(reasons))
    return "confirmed", best, margin, tuple(reasons)


def fuse_directional_segments(forward: Sequence[IdentityTimelineSegment], backward: Sequence[IdentityTimelineSegment]) -> tuple[tuple[IdentityTimelineSegment, ...], tuple[IdentityConflictInterval, ...]]:
    by_frame: dict[int, list[IdentityTimelineSegment]] = {}
    for item in (*forward, *backward): by_frame.setdefault(item.source_frame_index, []).append(item)
    fused: list[IdentityTimelineSegment] = []
    conflicts: list[IdentityConflictInterval] = []
    conflict_frames: list[int] = []
    for frame_index in sorted(by_frame):
        items = by_frame[frame_index]
        if len(items) == 1:
            fused.append(items[0].model_copy(update={"direction": "fused", "template_update_frozen": True})); continue
        left, right = items[0], items[1]
        if left.best_candidate_id != right.best_candidate_id or left.state != right.state:
            conflict_frames.append(frame_index)
            track = TrackState(state="uncertain", bbox=None, identity_score=0, identity_margin=0, bbox_source="none", reasons=("forward_backward_conflict",))
            fused.append(IdentityTimelineSegment(source_frame_index=frame_index, pts_sec=max(left.pts_sec, right.pts_sec), state="uncertain", track_state=track, best_candidate_id=left.best_candidate_id, second_candidate_id=right.best_candidate_id, evidence=left.evidence + right.evidence, direction="fused", conflict=True, template_update_frozen=True))
        else:
            chosen = left if left.track_state.state == "confirmed" else right
            fused.append(chosen.model_copy(update={"direction": "fused", "template_update_frozen": True}))
    if conflict_frames:
        points = [next(item.pts_sec for item in fused if item.source_frame_index == idx) for idx in conflict_frames]
        candidates = tuple(dict.fromkeys(item.best_candidate_id for item in (*forward, *backward) if item.best_candidate_id))
        conflicts.append(IdentityConflictInterval(start_pts_sec=min(points), end_pts_sec=max(points), reason="forward_backward_conflict", frame_indices=tuple(conflict_frames), candidate_ids=candidates))
    return tuple(fused), tuple(conflicts)


def build_identity_timeline(segments: Sequence[IdentityTimelineSegment], *, identity_id: str = "main-skater", anchors: Sequence[IdentityAnchor] = (), anchor_revisions: Sequence[IdentityAnchorRevision] = (), conflicts: Sequence[IdentityConflictInterval] = (), diagnostic_only: bool = True) -> IdentityTimeline:
    ordered = tuple(sorted(segments, key=lambda item: item.source_frame_index)); total = len(ordered) or 1
    counts = {state: sum(item.state == state for item in ordered) / total for state in ("confirmed", "uncertain", "lost")}
    longest = 0.0; run_start: float | None = None
    for item in ordered:
        if item.state == "lost": run_start = item.pts_sec if run_start is None else run_start; longest = max(longest, item.pts_sec - run_start)
        else: run_start = None
    state = "confirmed" if counts["confirmed"] else "uncertain" if counts["uncertain"] else "lost"
    task = "confirm_main_skater_anchor" if conflicts or state != "confirmed" else None
    return IdentityTimeline(identity_id=identity_id, state=state, segments=ordered, anchors=tuple(anchors), anchor_revisions=tuple(anchor_revisions), conflicts=tuple(conflicts), confirmed_coverage=counts["confirmed"], uncertain_coverage=counts["uncertain"], lost_coverage=counts["lost"], longest_lost_interval_sec=max(0.0, longest), recommended_review_task=task, diagnostic_only=diagnostic_only)


def create_anchor_revision(*, revision: int, parent_revision: int | None, anchor_ids: Sequence[str], invalidated_intervals: Sequence[tuple[float, float]], created_by: str, provenance: str = "additional_anchor") -> IdentityAnchorRevision:
    return IdentityAnchorRevision(revision=revision, parent_revision=parent_revision, anchor_ids=tuple(anchor_ids), invalidated_intervals=tuple(invalidated_intervals), created_by=created_by, created_at=datetime.now(timezone.utc).isoformat(), provenance=provenance)


def replace_causal_interval(timeline: IdentityTimeline, replacement: Sequence[IdentityTimelineSegment], *, start_pts_sec: float, end_pts_sec: float, revision: IdentityAnchorRevision, anchors: Sequence[IdentityAnchor]) -> IdentityTimeline:
    if end_pts_sec < start_pts_sec:
        raise ValueError("causal interval must be ordered")
    unaffected = [item for item in timeline.segments if not start_pts_sec <= item.pts_sec <= end_pts_sec]
    merged = sorted((*unaffected, *replacement), key=lambda item: item.source_frame_index)
    return build_identity_timeline(merged, identity_id=timeline.identity_id, anchors=(*timeline.anchors, *anchors), anchor_revisions=(*timeline.anchor_revisions, revision), conflicts=tuple(item for item in timeline.conflicts if item.end_pts_sec < start_pts_sec or item.start_pts_sec > end_pts_sec), diagnostic_only=timeline.diagnostic_only)
