from __future__ import annotations

import pytest

from app.analysis_v2.action_classification import (
    ActionClassificationEvidence,
    DEFAULT_CONFIGS,
    classify_action,
    classifier_fingerprint,
    classifiers,
)
from app.analysis_v2.event_label_facts import apply_event_label_fact, dismiss_event_label_fact, latest_applied_event_label_fact, propose_event_label_fact
from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, FactPermission
from app.analysis_v2.event_proposals import ProposalEvidenceSample
from app.analysis_v2.profile_eligibility import growth_admission, profile_eligibility


def evidence(**changes):
    base = dict(
        source_video_hash="sha256:v",
        event_id="event-1",
        samples=(ProposalEvidenceSample(source_frame_index=i, pts_sec=i * .1, camera_compensated_track_motion=.45, pose_dynamics=.4, ice_contact_proxy=.4, periodicity=.8, pose_observable=True) for i in range(12)),
        temporal_features={},
        tracking_coverage=1,
        pose_coverage=1,
        observability="observable",
        evidence_sources=("motion", "pose"),
    )
    base.update(changes)
    return ActionClassificationEvidence(**base)


def jump_evidence(**changes):
    return evidence(
        samples=(ProposalEvidenceSample(source_frame_index=i, pts_sec=i * .1, camera_compensated_track_motion=.55, pose_dynamics=.55, ice_contact_proxy=.8, periodicity=.02, pose_observable=True) for i in range(12)),
        temporal_features={"airborne_proxy": 1, "vertical_excursion": 1, "ice_contact_proxy": 1, "periodicity": .02, "horizontal_motion": .05},
        **changes,
    )


def test_classifier_isolation_and_no_step_fallthrough() -> None:
    before = {profile: classifiers()[profile].config.fingerprint for profile in DEFAULT_CONFIGS}
    changed = dict(DEFAULT_CONFIGS)
    changed["jump"] = DEFAULT_CONFIGS["jump"].__class__("jump", "test-jump", (("airborne_proxy", 1.0),))
    after = {profile: classifiers(changed)[profile].config.fingerprint for profile in DEFAULT_CONFIGS}
    assert after["jump"] != before["jump"]
    assert after["spin"] == before["spin"]
    result = classify_action(evidence(observability="unobservable", pose_coverage=0))
    assert result.profile == "unknown"
    assert result.state == "unknown"


def test_missing_and_contradictory_evidence_are_visible() -> None:
    missing = classify_action(evidence(pose_coverage=0, temporal_features={"motion": 0}))
    assert missing.state in {"ambiguous", "unknown"}
    conflict = classify_action(evidence(path_a_support={"jump": .8}, path_a_contradictions={"jump": .8}))
    assert conflict.state == "ambiguous"
    assert conflict.evidence_summary["semantic_conflict"] is True


def test_path_a_is_bounded_semantics_and_cannot_supply_localization_alone() -> None:
    result = classify_action(evidence(samples=(), temporal_features={}, path_a_support={"jump": 1}, tracking_coverage=1, pose_coverage=1))
    jump = next(item for item in result.contributions if item.profile == "jump")
    path_a = next(item for item in jump.contributions if item.source == "path_a_bounded")
    assert path_a.value == .18
    assert path_a.contribution == pytest.approx(path_a.value * path_a.weight)
    assert result.state == "unknown"


def test_sparse_whole_video_envelope_cannot_be_high_confidence_identity() -> None:
    result = classify_action(evidence(evidence_sources=("sparse_observability_envelope",)))
    assert result.state == "ambiguous"
    assert result.confidence < .5
    assert result.evidence_summary["localization_is_broad"] is True


def test_subtype_is_underpowered_with_small_sample() -> None:
    result = classify_action(jump_evidence(
        subtype_candidates={"jump": (("toe_loop", .95),)},
        subtype_validation_n={"jump": {"toe_loop": 0}},
    ))
    assert result.subtype.underpowered is True
    assert result.subtype.state == "unknown"
    assert "validation N=0" in result.subtype.reason


def test_subtype_requires_declared_validation_n_before_confirmation() -> None:
    result = classify_action(jump_evidence(
        subtype_candidates={"jump": (("toe_loop", .95),)},
        subtype_validation_n={"jump": {"toe_loop": 20}},
    ))
    assert result.subtype.subtype == "toe_loop"
    assert result.subtype.state == "confirmed"
    assert result.subtype.underpowered is False


def test_custom_classifier_threshold_is_used_only_for_its_profile_decision() -> None:
    changed = dict(DEFAULT_CONFIGS)
    jump = DEFAULT_CONFIGS["jump"]
    changed["jump"] = jump.__class__(
        jump.profile,
        "test-jump-high-threshold",
        jump.feature_weights,
        confirmation_threshold=.99,
        margin_threshold=jump.margin_threshold,
        minimum_evidence=jump.minimum_evidence,
        subtype_minimum_evidence=jump.subtype_minimum_evidence,
    )
    sample = jump_evidence()
    default = classify_action(sample)
    selected = classify_action(sample, configs=changed)
    assert default.profile == "jump"
    assert selected.state != "confirmed"
    assert selected.contributions[0].config_fingerprint != default.contributions[0].config_fingerprint


@pytest.mark.parametrize("consumer", ["training_plan", "filters", "progress_grouping", "comparison", "skill_matching", "monthly_facts", "memory_suggestions", "growth_admission"])
def test_every_downstream_profile_boundary_rejects_ambiguous(consumer: str) -> None:
    ambiguous = AnalysisFactV2(analysis_id="a", event_id="e", claim_type="action_profile", value="jump", authority="v2", source_pipeline_fingerprint="fp", definition_version="profile.v1", status="uncertain", permissions=FactPermission(family_display=True, aggregation=True, comparison=True, coaching=True))
    facts = AnalysisFactsV2(analysis_id="a", authority="v2", facts=[ambiguous])
    assert profile_eligibility(facts, consumer).eligible is False


def test_revisioned_event_label_fact_keeps_history_and_provenance() -> None:
    first = propose_event_label_fact(analysis_id="a", event_id="e", profile="jump", subtype=None, legacy_snapshot={"action_type": "step"})
    second = propose_event_label_fact(analysis_id="a", event_id="e", profile="spin", subtype=None, parent=first)
    assert second.revision == 2
    assert second.parent_revision == 1
    assert second.legacy_snapshot["action_type"] == "step"
    assert apply_event_label_fact(second).status == "applied"
    assert dismiss_event_label_fact(second).status == "dismissed"


def test_dismissed_revision_is_no_longer_the_latest_applied_fact() -> None:
    proposed = propose_event_label_fact(analysis_id="a", event_id="e", profile="jump", subtype=None)
    applied = apply_event_label_fact(proposed)
    dismissed = dismiss_event_label_fact(applied)
    assert latest_applied_event_label_fact([proposed, applied]) == applied
    assert latest_applied_event_label_fact([proposed, applied, dismissed]) is None


def test_event_label_fact_state_and_profile_are_discriminated() -> None:
    with pytest.raises(ValueError, match="cannot carry a profile"):
        propose_event_label_fact(analysis_id="a", event_id="e", profile="jump", subtype=None, state="unknown")
    with pytest.raises(ValueError, match="requires a profile"):
        propose_event_label_fact(analysis_id="a", event_id="e", profile=None, subtype=None, state="confirmed")


def test_facts_exclude_unknown_or_ambiguous_profiles_from_consumers() -> None:
    ambiguous = AnalysisFactV2(analysis_id="a", event_id="e", claim_type="action_profile", value="jump", authority="v2", source_pipeline_fingerprint="fp", definition_version="profile.v1", status="uncertain", permissions=FactPermission(aggregation=True))
    facts = AnalysisFactsV2(analysis_id="a", authority="v2", facts=[ambiguous])
    assert facts.confirmed_profile() is None
    assert facts.profile_eligibility()["reason"] == "ambiguous_profile"
    assert profile_eligibility(facts, "comparison").eligible is False
    assert growth_admission([facts])["excluded_reasons"] == {"ambiguous_profile": 1}
    assert profile_eligibility(facts, "automatic_skill_unlock").reason == "v2_automatic_unlock_disabled_until_iteration14"


def test_growth_requires_aggregation_permission_and_excludes_shadow() -> None:
    confirmed = AnalysisFactV2(
        analysis_id="a",
        event_id="e",
        claim_type="action_profile",
        value="jump",
        authority="v2",
        source_pipeline_fingerprint="fp",
        definition_version="profile.v1",
        permissions=FactPermission(family_display=True, aggregation=True),
    )
    facts = AnalysisFactsV2(analysis_id="a", authority="v2", facts=[confirmed])
    assert growth_admission([facts])["included_count"] == 1
    assert growth_admission([facts], diagnostic_fact_set_ids=["a"])["excluded_reasons"] == {"shadow_diagnostic": 1}

    display_only = confirmed.model_copy(update={"permissions": FactPermission(family_display=True)})
    display_facts = AnalysisFactsV2(analysis_id="a", authority="v2", facts=[display_only])
    assert growth_admission([display_facts])["excluded_reasons"] == {"profile_not_eligible": 1}
