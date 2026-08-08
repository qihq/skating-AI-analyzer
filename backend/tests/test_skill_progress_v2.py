from __future__ import annotations

from types import SimpleNamespace

from app.analysis_v2.facts import AnalysisFactV2
from app.services.skill_progress import _automation_fact_gate, _score_unlock_config


def _fact(*, claim_type: str, definition: str, compatibility: str, provenance: tuple[str, ...] = ()) -> AnalysisFactV2:
    return AnalysisFactV2(
        analysis_id="analysis-1",
        event_id="event-1",
        claim_type=claim_type,
        value="jump" if claim_type == "action_profile" else 80,
        authority="v2",
        source_pipeline_fingerprint="pipeline-fp",
        source_fact_revision=3,
        definition_version=definition,
        compatibility_group=compatibility,
        provenance=provenance,
    )


def _consumer(*facts: AnalysisFactV2) -> SimpleNamespace:
    return SimpleNamespace(
        authority="v2",
        source_fact_hash="fact-hash",
        source_fact_revision=3,
        source_pipeline_fingerprint="pipeline-fp",
        facts=facts,
    )


def _node(**rule: object) -> SimpleNamespace:
    return SimpleNamespace(
        unlock_config={
            "score": {"threshold": 70, "consecutive": 2, "action_type": "跳跃"},
            **rule,
        }
    )


def test_v2_automation_requires_versioned_matching_fact_definitions() -> None:
    score = _fact(claim_type="force_score", definition="force-score.v2", compatibility="force-score/100/v2")
    profile = _fact(claim_type="action_profile", definition="deterministic-action-profile.v2", compatibility="action-profile/family/v2")
    ok, reason, metadata = _automation_fact_gate(_consumer(score, profile), score, profile, _score_unlock_config(_node()))
    assert ok is True
    assert reason is None
    assert metadata["rule_version"] == "skill-unlock-rule.v2"
    assert metadata["source_fact_revision"] == 3

    incompatible = profile.model_copy(update={"definition_version": "deterministic-action-profile.v1"})
    ok, reason, _ = _automation_fact_gate(_consumer(score, incompatible), score, incompatible, _score_unlock_config(_node()))
    assert ok is False
    assert reason == "definition_version_mismatch"


def test_v2_automation_rejects_corrected_or_conflicted_facts() -> None:
    score = _fact(claim_type="force_score", definition="force-score.v2", compatibility="force-score/100/v2")
    profile = _fact(claim_type="action_profile", definition="deterministic-action-profile.v2", compatibility="action-profile/family/v2")

    corrected = profile.model_copy(update={"provenance": ("human_correction", "corrected-but-unconfirmed")})
    ok, reason, _ = _automation_fact_gate(_consumer(score, corrected), score, corrected, _score_unlock_config(_node()))
    assert ok is False
    assert reason == "blocked_provenance"

    conflicted = score.model_copy(update={"conflicts": ("path_a_vs_path_b",)})
    ok, reason, _ = _automation_fact_gate(_consumer(conflicted, profile), conflicted, profile, _score_unlock_config(_node()))
    assert ok is False
    assert reason == "fact_conflict"


def test_v2_automation_rejects_pinned_rule_definition_mismatch() -> None:
    score = _fact(claim_type="force_score", definition="force-score.v2", compatibility="force-score/100/v2")
    profile = _fact(claim_type="action_profile", definition="deterministic-action-profile.v2", compatibility="action-profile/family/v2")
    config = _score_unlock_config(_node(rule={"rule_version": "skill-unlock-rule.v2", "score_definition_version": "force-score.v3"}))
    ok, reason, _ = _automation_fact_gate(_consumer(score, profile), score, profile, config)
    assert ok is False
    assert reason == "score_definition_incompatible"


def test_v2_automation_rejects_unknown_rule_version() -> None:
    score = _fact(claim_type="force_score", definition="force-score.v2", compatibility="force-score/100/v2")
    profile = _fact(claim_type="action_profile", definition="deterministic-action-profile.v2", compatibility="action-profile/family/v2")
    config = _score_unlock_config(_node(rule={"rule_version": "skill-unlock-rule.v3"}))
    ok, reason, _ = _automation_fact_gate(_consumer(score, profile), score, profile, config)
    assert ok is False
    assert reason == "unsupported_rule_version"
