from __future__ import annotations

from app.analysis_v2.contracts import RotationEstimate
from app.analysis_v2.facts import AnalysisFactsV2
from app.analysis_v2.rotation_facts import rotation_fact_from_estimate, select_rotation_delta, select_rotation_fact


def estimate(event_id: str, *, value: float = 2, status: str = "exact") -> RotationEstimate:
    common = dict(
        event_id=event_id,
        profile="jump",
        confidence=.9 if status == "exact" else .4 if status == "range" else 0,
        value_convention="airborne_body_rotation",
        estimator_fingerprint="estimator",
        source_timeline_fingerprint="timeline",
    )
    if status == "exact":
        return RotationEstimate(status="exact", value_turns=value, class_turns=value, class_kind="integer", observability="observed", **common)
    if status == "range":
        return RotationEstimate(status="range", range_turns=(value - .5, value + .5), observability="partial", refusal_reason="signal_aliasing", review_required=True, **common)
    return RotationEstimate(status="unobservable", observability="unobservable", refusal_reason="occlusion", **common)


def facts(item: RotationEstimate, *, definition: str | None = None) -> AnalysisFactsV2:
    fact = rotation_fact_from_estimate(analysis_id=item.event_id, estimate=item, source_pipeline_fingerprint="pipeline")
    if definition is not None:
        fact = fact.model_copy(update={"definition_version": definition})
    return AnalysisFactsV2(analysis_id=item.event_id, authority="v2", facts=(fact,))


def test_only_confirmed_matching_rotation_facts_form_deltas_and_trends() -> None:
    result = select_rotation_delta(facts(estimate("left", value=1)), facts(estimate("right", value=2)))
    assert result["eligible"] is True
    assert result["delta_turns"] == 1
    mismatch = select_rotation_delta(facts(estimate("left", value=1)), facts(estimate("right", value=2), definition="future-definition"))
    assert mismatch["eligible"] is False
    assert mismatch["reason"] == "rotation_definition_unit_or_convention_mismatch"


def test_single_consumer_rejects_definition_or_convention_drift() -> None:
    base = facts(estimate("event"))
    fact = base.facts[0]
    wrong_definition = AnalysisFactsV2(
        analysis_id=base.analysis_id,
        authority="v2",
        facts=(fact.model_copy(update={"definition_version": "future-definition"}),),
    )
    wrong_convention = AnalysisFactsV2(
        analysis_id=base.analysis_id,
        authority="v2",
        facts=(fact.model_copy(update={"convention": "observed_spin_rotation"}),),
    )
    assert select_rotation_fact(wrong_definition, "monthly").reason == "rotation_definition_mismatch"
    assert select_rotation_fact(wrong_convention, "annual").reason == "rotation_convention_mismatch"


def test_spin_fact_uses_observed_spin_definition_bucket() -> None:
    item = estimate("spin").model_copy(update={
        "profile": "spin",
        "definition_version": "observed-spin-rotation.source-pts.v1",
        "value_convention": "observed_spin_rotation",
        "competition_convention": "not_applied",
        "competition_naming_turns": None,
        "competition_naming_class": None,
    })
    fact = rotation_fact_from_estimate(analysis_id="analysis", estimate=item, source_pipeline_fingerprint="pipeline")
    assert fact.definition_version == "observed-spin-rotation.source-pts.v1"
    assert fact.compatibility_group == "rotation/observed-spin/source-pts/v1"
    selected = select_rotation_fact(AnalysisFactsV2(analysis_id="analysis", authority="v2", facts=(fact,)), "progress")
    assert selected.eligible is True


def test_ranges_and_refusals_are_context_only_for_compare_progress_monthly_annual() -> None:
    for consumer in ("comparison", "progress", "monthly", "annual"):
        ranged = select_rotation_fact(facts(estimate("range", status="range")), consumer)
        refused = select_rotation_fact(facts(estimate("refused", status="unobservable")), consumer)
        assert ranged.eligible is False and ranged.reason == "rotation_range_context_only" and ranged.context
        assert refused.eligible is False and refused.reason == "rotation_unobservable_context_only" and refused.context


def test_v2_metric_name_and_bucket_do_not_collide_with_legacy_estimated_rotations() -> None:
    fact = facts(estimate("event")).facts[0]
    assert fact.claim_type == "airborne_body_rotation_turns_v1"
    assert fact.compatibility_group == "rotation/airborne-body/source-pts/v1"
    assert fact.claim_type != "estimated_rotations"
