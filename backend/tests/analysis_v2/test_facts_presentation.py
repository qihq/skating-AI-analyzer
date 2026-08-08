from __future__ import annotations

import copy

import pytest

from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, FactPermission, fact_hash
from app.analysis_v2.presentation import (
    AuthorityMismatchError,
    ReviewTaskV2,
    build_experience_v2,
    present_legacy_record,
)
from app.analysis_v2.fact_consumers import AnalysisFactConsumer, build_fact_consumer


def test_legacy_record_is_adapted_as_one_authority_without_mutating_source() -> None:
    record = {
        "id": "legacy-1",
        "action_type": "jump",
        "status": "completed",
        "pipeline_version": "legacy-2026",
        "report": {"summary": "Good landing", "subscores": {"force": 72}},
        "bio_data": {"key_frames": {"takeoff": 1.2}},
    }
    before = copy.deepcopy(record)

    experience = present_legacy_record(record)

    assert experience.authority == "legacy"
    assert experience.pipeline_mode == "legacy"
    assert experience.events[0].profile == "jump"
    assert {claim.claim_type for claim in experience.claims} >= {"report_summary", "force_score", "action_profile"}
    assert next(claim.value for claim in experience.claims if claim.claim_type == "report_summary") == "Good landing"
    assert all(claim.authority == "legacy" for claim in experience.claims)
    assert record == before


def test_legacy_record_preserves_non_english_action_name_without_claiming_v2_identity() -> None:
    record = {
        "id": "legacy-cn",
        "action_type": "自由滑",
        "pipeline_version": "legacy-2026",
    }

    experience = present_legacy_record(record)

    assert experience.events[0].profile == "自由滑"
    assert experience.events[0].state == "unknown"
    assert next(claim.value for claim in experience.claims if claim.claim_type == "action_profile") == "自由滑"


def test_missing_v2_claim_is_unavailable_and_never_filled_from_legacy() -> None:
    experience = build_experience_v2(
        analysis_id="v2-1",
        pipeline_mode="v2",
        source_pipeline_fingerprint="fp-v2",
        events=[],
        claims=[],
        requested_claim_types=["rotation"],
    )

    assert len(experience.claims) == 1
    assert experience.claims[0].claim_type == "rotation"
    assert experience.claims[0].status == "unobservable"
    assert experience.claims[0].value is None
    assert experience.claims[0].authority == "v2"


def test_mixed_authority_facts_are_rejected() -> None:
    legacy = AnalysisFactV2(
        analysis_id="a",
        claim_type="action",
        value="jump",
        authority="legacy",
        source_pipeline_fingerprint="legacy-fp",
        definition_version="action.v1",
    )
    v2 = legacy.model_copy(update={"authority": "v2", "source_pipeline_fingerprint": "v2-fp"})

    with pytest.raises(AuthorityMismatchError):
        AnalysisFactsV2(analysis_id="a", authority="legacy", facts=[legacy, v2])


def test_cross_authority_review_task_is_rejected() -> None:
    with pytest.raises(AuthorityMismatchError):
        build_experience_v2(
            analysis_id="a",
            pipeline_mode="v2",
            source_pipeline_fingerprint="fp",
            events=[],
            claims=[],
            review_tasks=[ReviewTaskV2(task_id="t", authority="legacy", kind="confirm_action")],
        )


def test_shadow_experience_is_diagnostic_only_and_not_family_usable() -> None:
    experience = build_experience_v2(
        analysis_id="shadow-1",
        pipeline_mode="shadow",
        source_pipeline_fingerprint="shadow-fp",
        events=[],
        claims=[
            AnalysisFactV2(
                analysis_id="shadow-1",
                claim_type="action",
                value="spin",
                authority="v2",
                source_pipeline_fingerprint="shadow-fp",
                definition_version="action.v1",
            )
        ],
    )

    assert experience.authority == "legacy"
    assert experience.diagnostic_only is True
    assert experience.family_usable is False
    assert all(claim.authority == "legacy" for claim in experience.claims)


def test_fact_hash_is_deterministic_and_permission_defaults_are_safe() -> None:
    fact = AnalysisFactV2(
        analysis_id="a",
        event_id="e",
        claim_type="rotation",
        value={"turns": 1.5},
        authority="v2",
        source_pipeline_fingerprint="fp",
        definition_version="rotation.v1",
        unit="turn",
        convention="axel-inclusive",
    )
    assert fact_hash(fact) == fact_hash(fact.model_copy(deep=True))
    assert fact.permissions == FactPermission()
    assert fact.source_fact_hash == fact_hash(fact)


def test_fact_permissions_cover_all_iteration_five_consumers() -> None:
    permissions = FactPermission().model_dump()

    assert set(permissions) == {
        "family_display",
        "coaching",
        "aggregation",
        "comparison",
        "correction",
        "automation",
        "share",
        "export",
    }


def test_fact_carries_revision_compatibility_and_source_references() -> None:
    fact = AnalysisFactV2(
        analysis_id="a",
        event_id="e",
        claim_type="rotation",
        value=1.5,
        authority="v2",
        source_pipeline_fingerprint="fp",
        source_fact_revision=3,
        definition_version="rotation.v1",
        compatibility_group="rotation/non-axel/turns",
        unit="turn",
        convention="non_axel_airborne",
        source_references=("event:e", "moment:takeoff"),
        sources=("deterministic_rotation", "target_clip_review"),
        source_fingerprints={"deterministic_rotation": "rotation:fp", "target_clip_review": "review:fp"},
    )

    assert fact.source_fact_revision == 3
    assert fact.compatibility_group == "rotation/non-axel/turns"
    assert fact.source_references == ("event:e", "moment:takeoff")
    assert fact.sources == ("deterministic_rotation", "target_clip_review")
    assert fact.source_fingerprints["target_clip_review"] == "review:fp"


def test_conflicted_fact_cannot_remain_confirmed() -> None:
    fact = AnalysisFactV2(
        analysis_id="a",
        event_id="e",
        claim_type="rotation",
        value={"range": [1.0, 1.5]},
        authority="v2",
        source_pipeline_fingerprint="fp",
        definition_version="rotation.v2",
        conflicts=("target clip and deterministic estimate disagree",),
    )

    assert fact.status == "uncertain"
    assert fact.observability == "partially_observable"


def test_generated_artifact_reference_binds_same_authority_fact_hash() -> None:
    from app.analysis_v2.facts import DerivedArtifactReferenceV2

    artifact = DerivedArtifactReferenceV2(
        artifact_type="training_plan",
        source_fact_schema_version="analysis-facts.v2",
        source_fact_hash="fact:123",
        source_fact_revision=4,
        authority="legacy",
        source_pipeline_fingerprint="legacy:v5",
        generation_fingerprint="generation:456",
    )

    assert artifact.authority == "legacy"
    assert artifact.source_fact_hash == "fact:123"


def test_fact_consumer_filters_by_permission_and_never_switches_authority() -> None:
    display_only = AnalysisFactV2(
        analysis_id="a",
        claim_type="report_summary",
        value="ok",
        authority="legacy",
        source_pipeline_fingerprint="legacy:v5",
        definition_version="report.v1",
    )
    coaching = display_only.model_copy(
        update={"claim_type": "force_score", "value": 72, "permissions": FactPermission(coaching=True)}
    )
    facts = AnalysisFactsV2(analysis_id="a", authority="legacy", facts=[display_only, coaching])

    consumer = build_fact_consumer(facts, "coaching")

    assert isinstance(consumer, AnalysisFactConsumer)
    assert consumer.authority == "legacy"
    assert [fact.claim_type for fact in consumer.facts] == ["force_score"]
    assert consumer.source_fact_hash == facts.source_fact_hash


def test_fact_consumer_rejects_interpolated_and_identity_blocked_pose_facts() -> None:
    safe = AnalysisFactV2(
        analysis_id="a",
        claim_type="joint_angle",
        value=25,
        authority="v2",
        source_pipeline_fingerprint="fp",
        definition_version="pose.v2",
        provenance=("measured",),
        permissions=FactPermission(coaching=True, aggregation=True),
    )
    interpolated = safe.model_copy(update={"value": None, "status": "uncertain", "observability": "partially_observable", "provenance": ("interpolated-display-only",), "permissions": FactPermission(family_display=True)})
    blocked = safe.model_copy(update={"value": None, "status": "uncertain", "observability": "partially_observable", "provenance": ("identity-blocked",), "permissions": FactPermission(family_display=True)})
    facts = AnalysisFactsV2(analysis_id="a", authority="v2", facts=[safe, interpolated, blocked])
    assert [fact.claim_type for fact in build_fact_consumer(facts, "coaching").facts] == ["joint_angle"]


def test_presenter_projects_same_authority_facts() -> None:
    from app.analysis_v2.presentation import project_analysis_facts

    record = {
        "id": "legacy-1",
        "action_type": "jump",
        "pipeline_version": "legacy-2026",
        "force_score": 72,
        "report": {"summary": "Good landing"},
    }

    experience = present_legacy_record(record)
    facts = project_analysis_facts(record)

    assert facts.authority == experience.authority
    assert facts.analysis_id == experience.analysis_id
    assert {fact.claim_type for fact in facts.facts} == {claim.claim_type for claim in experience.claims}
