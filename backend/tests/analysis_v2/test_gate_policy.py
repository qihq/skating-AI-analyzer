import pytest

from app.analysis_v2.evaluation.gate_policy import (
    CountRange,
    GOLDEN_GATE_POLICY,
    LEGACY_GATE_POLICY_VERSION,
    artifact_gate_policy_version,
    artifact_uses_current_policy,
    classify_limited_sample_evidence,
    gate_policy_summary,
    limited_sample_gate_metadata,
)


def test_policy_v2_contains_the_approved_thresholds() -> None:
    policy = GOLDEN_GATE_POLICY
    assert policy.schema_version == "golden-gate-policy.v2"
    assert policy.effective_date == "2026-08-15"
    assert policy.g1_source_video_minimum == 18
    assert policy.g1_valid_event_minimum == 18
    assert policy.g1_profile_minimums == {"jump": 10, "spin": 4, "step": 2, "spiral": 2}
    assert policy.g1_recording_session_minimum == 5
    assert policy.g1_delayed_review_minimum == 2
    assert policy.g2_event_range.model_dump() == {"minimum": 24, "maximum": 30}
    assert {key: value.model_dump() for key, value in policy.g2_profile_ranges.items()} == {
        "jump": {"minimum": 10, "maximum": 14},
        "spin": {"minimum": 6, "maximum": 8},
        "step": {"minimum": 4, "maximum": 5},
        "spiral": {"minimum": 4, "maximum": 5},
    }
    assert policy.pose_frame_range.model_dump() == {"minimum": 24, "maximum": 40}
    assert policy.subtype_reporting_minimum == 4
    assert policy.subtype_reporting_target == 6


def test_policy_summary_returns_a_detached_serializable_copy() -> None:
    first = gate_policy_summary()
    first["g1_profile_minimums"]["jump"] = 999
    second = gate_policy_summary()
    assert second["g1_profile_minimums"]["jump"] == 10


def test_count_range_rejects_an_inverted_policy() -> None:
    with pytest.raises(ValueError, match="maximum must be greater than or equal to minimum"):
        CountRange(minimum=30, maximum=24)


def test_unversioned_artifacts_remain_legacy_without_rewriting_them() -> None:
    assert LEGACY_GATE_POLICY_VERSION == "golden-gate-policy.v1"
    assert artifact_gate_policy_version({}) == "golden-gate-policy.v1"
    assert artifact_uses_current_policy({}) is False
    assert artifact_gate_policy_version({"gate_policy_version": "golden-gate-policy.v2"}) == "golden-gate-policy.v2"
    assert artifact_uses_current_policy({"gate_policy_version": "golden-gate-policy.v2"}) is True


def test_limited_sample_evidence_never_becomes_a_broad_release_claim() -> None:
    assert classify_limited_sample_evidence(0, False, True) == ("insufficient_sample", False)
    assert classify_limited_sample_evidence(4, True, False) == ("blocked_waiting_for_frozen_candidate", False)
    assert classify_limited_sample_evidence(4, True, True) == ("limited_sample_candidate_pass", True)
    assert classify_limited_sample_evidence(4, False, True) == ("diagnostic_failed_or_insufficient", False)
    assert limited_sample_gate_metadata(4, True, True) == {
        "gate_policy_version": "golden-gate-policy.v2",
        "evidence_scope": "limited_sample",
        "status": "limited_sample_candidate_pass",
        "gate_passed": True,
        "release_claim": False,
    }
