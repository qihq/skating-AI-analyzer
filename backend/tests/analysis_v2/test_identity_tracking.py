from app.analysis_v2.contracts import IdentityAnchor, IdentityFeatureReliability, IdentityTimelineSegment, TrackState
from app.analysis_v2.identity import classify_identity, create_anchor_revision, fuse_directional_segments, immutable_template_fingerprint, score_identity_evidence


def _segment(frame: int, candidate: str, *, state: str = "confirmed", direction: str = "forward"):
    track = TrackState(state=state, bbox=(.1, .1, .2, .3) if state == "confirmed" else None, identity_score=.8 if state == "confirmed" else 0, identity_margin=.3 if state == "confirmed" else 0, bbox_source="measured" if state == "confirmed" else "none")
    evidence = (score_identity_evidence(candidate, {"appearance": .9, "body_shape": .8, "camera_motion": .8, "bbox_continuity": .9}, IdentityFeatureReliability(appearance=1, body_shape=.8, camera_motion=.8, bbox_continuity=1)),)
    return IdentityTimelineSegment(source_frame_index=frame, pts_sec=frame / 30, state=state, track_state=track, best_candidate_id=candidate, evidence=evidence, direction=direction, template_update_frozen=True)


def test_margin_and_single_signal_safety():
    evidence = [score_identity_evidence("a", {"appearance": 1}, IdentityFeatureReliability(appearance=1)), score_identity_evidence("b", {"appearance": .95}, IdentityFeatureReliability(appearance=1))]
    state, _, margin, reasons = classify_identity(evidence)
    assert state == "uncertain" and margin < .12 and "low_identity_margin" in reasons


def test_forward_backward_conflict_is_uncertain():
    fused, conflicts = fuse_directional_segments([_segment(3, "a")], [_segment(3, "b", direction="backward")])
    assert fused[0].state == "uncertain" and fused[0].conflict and conflicts[0].reason == "forward_backward_conflict"


def test_stale_box_cannot_confirm():
    evidence = [score_identity_evidence("a", {"appearance": 1, "bbox_continuity": 1}, IdentityFeatureReliability(appearance=1, bbox_continuity=1))]
    state, _, _, reasons = classify_identity(evidence, bbox_source="stale")
    assert state == "uncertain" and "display_hint_not_authoritative" in reasons


def test_manual_template_is_immutable_and_anchor_revision_is_causal():
    anchor = IdentityAnchor(anchor_id="a1", source_frame_index=10, pts_sec=.33, bbox=(.1, .1, .2, .3), annotator="parent", quality_score=.9, template_fingerprint="pending")
    anchor = anchor.model_copy(update={"template_fingerprint": immutable_template_fingerprint(anchor)})
    revision = create_anchor_revision(revision=2, parent_revision=1, anchor_ids=(anchor.anchor_id,), invalidated_intervals=((1.0, 2.0),), created_by="parent")
    assert anchor.revision == 1 and revision.invalidated_intervals == ((1.0, 2.0),)
