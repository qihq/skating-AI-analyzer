from app.analysis_v2.comparison import compare_fact_sets, match_comparable_claim
from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, FactPermission


def _fact(*, analysis: str, event: str, value: float, definition: str = "score.v1", group: str = "score/jump/v1") -> AnalysisFactV2:
    return AnalysisFactV2(
        analysis_id=analysis,
        event_id=event,
        claim_type="quality_score",
        value=value,
        authority="v2",
        source_pipeline_fingerprint=f"fp:{analysis}",
        definition_version=definition,
        compatibility_group=group,
        unit="points",
        status="confirmed",
        observability="observable",
        permissions=FactPermission(comparison=True),
    )


def test_comparison_matches_events_and_compatible_definitions() -> None:
    left = AnalysisFactsV2(analysis_id="a", authority="v2", facts=(_fact(analysis="a", event="jump-1", value=70),))
    right = AnalysisFactsV2(analysis_id="b", authority="v2", facts=(_fact(analysis="b", event="jump-2", value=76),))
    match = match_comparable_claim(left, right, claim_type="quality_score", left_event_id="jump-1", right_event_id="jump-2")
    assert match.eligible is True
    assert match.delta == 6


def test_comparison_labels_cross_definition_and_refuses_delta() -> None:
    left = AnalysisFactsV2(analysis_id="a", authority="v2", facts=(_fact(analysis="a", event="e1", value=70),))
    right = AnalysisFactsV2(analysis_id="b", authority="v2", facts=(_fact(analysis="b", event="e2", value=80, definition="score.v2", group="score/jump/v2"),))
    result = compare_fact_sets(left, right, event_pairs=(("e1", "e2"),))
    assert result["deltas"] == []
    assert result["excluded"] == [{
        "claim_type": "quality_score",
        "left_event_id": "e1",
        "right_event_id": "e2",
        "reason": "cross_definition_delta_refused",
        "cross_definition": True,
    }]


def test_uncertain_or_shadow_ineligible_fact_cannot_form_delta() -> None:
    unsafe = _fact(analysis="a", event="e1", value=70).model_copy(
        update={"status": "uncertain", "permissions": FactPermission(comparison=False)}
    )
    left = AnalysisFactsV2(analysis_id="a", authority="v2", facts=(unsafe,))
    right = AnalysisFactsV2(analysis_id="b", authority="v2", facts=(_fact(analysis="b", event="e2", value=80),))
    match = match_comparable_claim(left, right, claim_type="quality_score", left_event_id="e1", right_event_id="e2")
    assert match.eligible is False
    assert match.reason == "missing_confirmed_comparable_claim"
