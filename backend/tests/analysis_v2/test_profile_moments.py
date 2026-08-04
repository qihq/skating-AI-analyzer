from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.analysis_v2.contracts import EventMomentSet, KeyMoment
from app.analysis_v2.event_moment_facts import apply_event_moments, dismiss_event_moments, latest_applied_event_moments, migrate_legacy_keyframe_proposal, propose_event_moments
from app.analysis_v2.moment_selectors import select_compare_pair, select_profile_moment
from app.analysis_v2.profile_moments import MomentEvidenceSample, localize_profile_moments, reject_evaluation_leakage


def sample(index: int, **changes) -> MomentEvidenceSample:
    payload = dict(source_frame_index=index, pts_sec=index / 30, body_center_y=.5, ice_contact=.8, airborne=.1, pose_quality=.9, provenance=("confirmed_pose",))
    payload.update(changes)
    return MomentEvidenceSample(**payload)


def jump_samples(*, landing: bool = True) -> list[MomentEvidenceSample]:
    values = [sample(0), sample(1), sample(2, ice_contact=.2, airborne=.8, body_center_y=.45), sample(3, ice_contact=.1, airborne=.9, body_center_y=.35), sample(4, ice_contact=.1, airborne=.9, body_center_y=.25), sample(5, ice_contact=.2, airborne=.8, body_center_y=.35)]
    if landing:
        values.append(sample(6, ice_contact=.9, airborne=.1, body_center_y=.45))
    return values


def localize_jump(samples=None) -> EventMomentSet:
    return localize_profile_moments(event_id="event-jump", profile="jump", event_start_pts=0, event_end_pts=1, samples=samples or jump_samples(), source_timeline_fingerprint="timeline-fp")


def test_jump_tal_uses_exact_source_boundaries() -> None:
    result = localize_jump()
    assert result.completeness == "complete"
    assert [(item.semantic_key, item.source_frame_index) for item in result.moments] == [("takeoff", 2), ("apex", 4), ("landing", 6)]
    assert all("source_pts" in item.provenance for item in result.moments)


def test_missing_landing_refuses_without_synthetic_marker() -> None:
    result = localize_jump(jump_samples(landing=False))
    landing = result.moments[2]
    assert result.completeness == "incomplete"
    assert landing.status == "unavailable"
    assert landing.source_frame_index is None and landing.pts_sec is None
    assert select_profile_moment(result, consumer="share_thumbnail", semantic_key="landing") is None


def test_vfr_and_dropped_frames_preserve_pts_and_warnings() -> None:
    samples = jump_samples()
    samples[3] = samples[3].model_copy(update={"pts_sec": .123, "frame_status": "gap_after_previous", "gap_before_sec": .04})
    samples[4] = samples[4].model_copy(update={"pts_sec": .171})
    samples[5] = samples[5].model_copy(update={"pts_sec": .213})
    samples[6] = samples[6].model_copy(update={"pts_sec": .251})
    result = localize_jump(samples)
    assert result.moments[1].pts_sec == .171
    assert "source_decode_gap_or_discontinuity" in result.warnings


def test_unconfirmed_or_approximate_samples_cannot_create_moments() -> None:
    blocked = [item.model_copy(update={"tracking_state": "uncertain"}) for item in jump_samples()]
    result = localize_jump(blocked)
    assert result.completeness == "unobservable"
    assert all(item.status == "unavailable" for item in result.moments)
    approximate = [item.model_copy(update={"timing_provenance": "legacy_approximate"}) for item in jump_samples()]
    assert localize_jump(approximate).completeness == "unobservable"


def test_semantic_review_frames_cannot_be_ground_truth_or_prediction_input() -> None:
    samples = [item.model_copy(update={"semantic_review_keys": ("semantic_takeoff",)}) for item in jump_samples()]
    result = localize_jump(samples)
    assert result.semantic_labels_consumed is False
    assert "semantic_keyframes_retained_as_review_evidence_only" in result.warnings
    with pytest.raises(ValueError, match="evaluation-only"):
        reject_evaluation_leakage({"selected_semantic_frames": [{"timestamp": .1}]})
    with pytest.raises(ValueError, match="evaluation-only"):
        reject_evaluation_leakage({"nested": {"ground_truth_moments": {"takeoff": .1}}})


def test_ambiguous_landing_preserves_competitors_and_reviewability() -> None:
    samples = jump_samples(landing=False)
    # Contact flickers on two adjacent original frames after the same airborne
    # segment; both remain as landing candidates for parent review.
    samples.extend([
        sample(6, pts_sec=6 / 30, ice_contact=.82, airborne=.1),
        sample(7, pts_sec=7 / 30, ice_contact=.2, airborne=.8),
        sample(8, pts_sec=8 / 30, ice_contact=.80, airborne=.1),
    ])
    result = localize_jump(samples)
    landing = result.moments[2]
    assert landing.status == "ambiguous"
    assert landing.review_resolvable is True
    assert len(landing.competing_candidates) >= 2


@pytest.mark.parametrize("profile,expected", [
    ("spin", ("spin_entry", "spin_main", "spin_exit")),
    ("spiral", ("spiral_entry", "spiral_hold", "spiral_exit")),
    ("step", ("step_sequence_interval", "step_representative_1", "step_representative_2", "step_representative_3")),
])
def test_profile_phase_exhaustiveness(profile: str, expected: tuple[str, ...]) -> None:
    samples = [MomentEvidenceSample(source_frame_index=i, pts_sec=i / 30, turning_motion=.7 if 2 <= i <= 7 else .3, rotation_periodicity=.8 if 3 <= i <= 6 else .1, axis_stability=.8, extension=.8 if 3 <= i <= 6 else .3, step_complexity=.7 if 2 <= i <= 8 else .1, edge_change=.7 if i in {2, 4, 6, 8} else .2) for i in range(11)]
    result = localize_profile_moments(event_id=f"event-{profile}", profile=profile, event_start_pts=0, event_end_pts=1, samples=samples, source_timeline_fingerprint="fp")
    assert result.expected_keys == expected
    assert tuple(item.semantic_key for item in result.moments) == expected


def test_order_validation_never_allows_synthetic_unavailable_marker() -> None:
    with pytest.raises(ValidationError):
        KeyMoment(event_id="e", semantic_key="landing", status="unavailable", source_frame_index=10, pts_sec=.3, definition_version="v", confidence=0, observability="unobservable")


def test_revisioned_moment_proposals_preserve_before_after_and_regeneration() -> None:
    first = propose_event_moments(analysis_id="a", event_id="event-jump", after=localize_jump())
    changed = localize_jump().model_copy(update={"completeness": "ambiguous"})
    second = propose_event_moments(analysis_id="a", event_id="event-jump", after=changed, parent=first)
    assert second.before == first.after
    assert second.after.revision == 2
    assert second.report_regeneration_required is True
    applied = apply_event_moments(second)
    assert latest_applied_event_moments([first, applied]) == applied
    assert latest_applied_event_moments([first, applied, dismiss_event_moments(applied)]) is None


def test_legacy_correction_and_rerun_keep_historical_snapshot_definition() -> None:
    legacy = {"key_frames": {"T": "frame_0010", "A": "frame_0012", "L": "frame_0014"}, "key_frame_timestamps": {"T": .3, "A": .4, "L": .5}}
    proposal = migrate_legacy_keyframe_proposal(analysis_id="a", event_id="event-jump", profile="jump", legacy_correction=legacy, adapted_after=localize_jump(), source="video_keyframe_rerun")
    assert proposal.legacy_snapshot["stored_payload"] == legacy
    assert proposal.legacy_snapshot["definition_version"] == "legacy-key-moment.v1"
    assert proposal.legacy_snapshot["reinterpretation_allowed"] is False


def test_downstream_selectors_use_profile_source_refs_and_definition_compatible_pairs() -> None:
    moments = localize_jump()
    ref = select_profile_moment(moments, consumer="monthly_representative")
    assert ref is not None and ref.semantic_key == "apex" and ref.source_frame_index == 4
    assert select_compare_pair(moments, moments, "takeoff") is not None
    changed = moments.model_copy(update={"definition_version": "jump-tal.source-contact.v2"})
    assert select_compare_pair(moments, changed, "takeoff") is None


def test_equivalent_transcode_source_pts_tolerance() -> None:
    original = localize_jump()
    transcoded = [item.model_copy(update={"pts_sec": item.pts_sec + (1 / 60)}) for item in jump_samples()]
    equivalent = localize_jump(transcoded)
    for left, right in zip(original.moments, equivalent.moments):
        assert left.pts_sec is not None and right.pts_sec is not None
        assert abs(left.pts_sec - right.pts_sec) <= 1 / 60 + 1e-9
