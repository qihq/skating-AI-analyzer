from __future__ import annotations

import pytest

from app.analysis_v2.evaluation.g8_moments import evaluate_g8_moments
from app.analysis_v2.profile_moments import MomentEvidenceSample, localize_profile_moments


def prediction(event_id: str = "jump-1"):
    samples = []
    for index, pts in enumerate((0, .05, .10, .15, .20, .25, .30)):
        samples.append(MomentEvidenceSample(source_frame_index=index, pts_sec=pts, body_center_y=(.5, .5, .45, .3, .2, .32, .45)[index], ice_contact=(.8, .8, .2, .1, .1, .2, .9)[index], airborne=(.1, .1, .8, .9, .9, .8, .1)[index], pose_quality=.9))
    return localize_profile_moments(event_id=event_id, profile="jump", event_start_pts=0, event_end_pts=.5, samples=samples, source_timeline_fingerprint="fp")


def labels():
    return [{"event_id": "jump-1", "profile": "jump", "observability": "observable", "moments": {"takeoff": {"pts": .1}, "apex": {"pts": .2}, "landing": {"pts": .3}}, "event_core_tracking_coverage": .96, "strata": ["60fps", "clear"]}]


def test_g8_reports_each_moment_completeness_refusal_ci_strata_and_tracking() -> None:
    result = evaluate_g8_moments(labels=labels(), predictions={"jump-1": prediction()}, candidate_fingerprint="candidate-v1", dataset_frozen=False, validation_calibrated=True)
    assert result["gate_passed"] is False
    assert result["status"] == "blocked_waiting_for_frozen_candidate"
    assert result["jump"]["median_absolute_error_sec"] == 0
    assert result["jump"]["p95_absolute_error_sec"] == 0
    assert result["jump"]["completeness"]["denominator"] == 3
    assert result["jump"]["refusal"]["numerator"] == 0
    assert set(result["jump"]["each_moment"]) == {"takeoff", "apex", "landing"}
    assert result["jump"]["event_core_tracking_coverage"]["mean"] == .96
    assert result["strata"]["60fps"]["denominator"] == 1


def test_formal_pass_requires_frozen_and_validation_calibrated_once() -> None:
    result = evaluate_g8_moments(labels=labels(), predictions={"jump-1": prediction()}, candidate_fingerprint="candidate-v1", dataset_frozen=True, validation_calibrated=True)
    assert result["status"] == "limited_sample_candidate_pass"
    assert result["gate_passed"] is True
    assert result["release_claim"] is False
    assert result["gate_policy_version"] == "golden-gate-policy.v2"
    assert result["evidence_scope"] == "limited_sample"
    assert result["frozen_candidate_runs"] == 1


def test_empty_g8_dataset_is_insufficient_sample() -> None:
    result = evaluate_g8_moments(labels=[], predictions={}, candidate_fingerprint="candidate-v1", dataset_frozen=True, validation_calibrated=True)
    assert result["status"] == "insufficient_sample"
    assert result["gate_passed"] is False
    assert result["release_claim"] is False


def test_evaluator_rejects_resolved_semantic_or_golden_prediction_payload() -> None:
    payload = prediction().model_dump(mode="json")
    payload["resolved_semantic_labels"] = {"takeoff": .1}
    with pytest.raises(ValueError, match="evaluation-only"):
        evaluate_g8_moments(labels=labels(), predictions={"jump-1": payload}, candidate_fingerprint="candidate-v1", dataset_frozen=False, validation_calibrated=False)
