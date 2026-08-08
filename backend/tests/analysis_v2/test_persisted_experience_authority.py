from __future__ import annotations

from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2
from app.analysis_v2.presentation import present_analysis_experience


def test_default_experience_uses_persisted_v2_authority_without_legacy_mix() -> None:
    fact = AnalysisFactV2(
        analysis_id="analysis-v2",
        event_id="analysis-v2:event:0",
        claim_type="action_profile",
        value="spin",
        authority="v2",
        source_pipeline_fingerprint="sha256:pipeline",
        definition_version="deterministic-action-profile.v2",
        compatibility_group="action-profile/family/v2",
        confidence=0.9,
        sources=("deterministic",),
        source_fingerprints={"deterministic": "sha256:deterministic"},
        permissions={"family_display": True, "comparison": True},
    )
    facts = AnalysisFactsV2(analysis_id="analysis-v2", authority="v2", facts=(fact,))
    record = {
        "id": "analysis-v2",
        "pipeline_version": "legacy-should-not-render",
        "action_type": "jump",
        "report": {"summary": "legacy should not appear"},
        "bio_data": {"jump_metrics": {"estimated_rotations": 99}},
        "facts_authority": "v2",
        "source_fact_hash": facts.source_fact_hash,
        "analysis_facts": {"schema_version": "analysis-facts.v2", **facts.model_dump(mode="json")},
    }

    rendered = present_analysis_experience(record)

    assert rendered.authority == "v2"
    assert rendered.pipeline_mode == "v2"
    assert rendered.claims[0].value == "spin"
    assert rendered.claims[0].authority == "v2"
    assert all(claim.value != "legacy should not appear" for claim in rendered.claims)


def test_persisted_v2_facts_keep_multiple_event_ids_separate() -> None:
    facts = AnalysisFactsV2(
        analysis_id="analysis-multi",
        authority="v2",
        facts=(
            AnalysisFactV2(
                analysis_id="analysis-multi",
                event_id="analysis-multi:event:0",
                claim_type="action_profile",
                value="jump",
                authority="v2",
                source_pipeline_fingerprint="sha256:multi-pipeline",
                definition_version="deterministic-action-profile.v2",
                compatibility_group="action-profile/family/v2",
                confidence=0.9,
                sources=("deterministic",),
                source_fingerprints={"deterministic": "sha256:deterministic"},
            ),
            AnalysisFactV2(
                analysis_id="analysis-multi",
                event_id="analysis-multi:event:1",
                claim_type="action_profile",
                value="spin",
                authority="v2",
                source_pipeline_fingerprint="sha256:multi-pipeline",
                definition_version="deterministic-action-profile.v2",
                compatibility_group="action-profile/family/v2",
                confidence=0.9,
                sources=("deterministic",),
                source_fingerprints={"deterministic": "sha256:deterministic"},
            ),
        ),
    )
    rendered = present_analysis_experience(
        {
            "id": "analysis-multi",
            "facts_authority": "v2",
            "source_fact_hash": facts.source_fact_hash,
            "analysis_facts": {"schema_version": "analysis-facts.v2", **facts.model_dump(mode="json")},
            "action_type": "legacy-must-not-supply-event",
        }
    )

    assert [event.event_id for event in rendered.events] == [
        "analysis-multi:event:0",
        "analysis-multi:event:1",
    ]
    assert [event.profile for event in rendered.events] == ["jump", "spin"]
    assert [claim.event_id for claim in rendered.claims] == [
        "analysis-multi:event:0",
        "analysis-multi:event:1",
    ]


def test_presenter_keeps_single_canonical_event_when_proposal_and_analysis_claims_share_scope() -> None:
    facts = AnalysisFactsV2(
        analysis_id="analysis-single",
        authority="v2",
        facts=(
            AnalysisFactV2(
                analysis_id="analysis-single",
                event_id="analysis-single:event:0",
                claim_type="action_profile",
                value="jump",
                authority="v2",
                source_pipeline_fingerprint="sha256:single",
                definition_version="deterministic-action-profile.v2",
                compatibility_group="action-profile/family/v2",
                confidence=.8,
                sources=("deterministic",),
                source_fingerprints={"deterministic": "sha256:deterministic"},
            ),
            AnalysisFactV2(
                analysis_id="analysis-single",
                event_id="analysis-single:event:0",
                claim_type="event_window",
                value={"start_pts_sec": 1.0, "end_pts_sec": 2.0, "proposal_status": "pending_confirmation"},
                authority="v2",
                source_pipeline_fingerprint="sha256:single",
                definition_version="action-event-proposal.v1",
                compatibility_group="action-event/source-pts/v1",
                unit="source_pts",
                status="uncertain",
                observability="observable",
                confidence=.35,
                sources=("deterministic", "action_event_proposal"),
                source_fingerprints={"deterministic": "sha256:deterministic", "proposal": "sha256:proposal"},
            ),
        ),
    )
    rendered = present_analysis_experience({
        "id": "analysis-single",
        "facts_authority": "v2",
        "source_fact_hash": facts.source_fact_hash,
        "analysis_facts": {"schema_version": "analysis-facts.v2", **facts.model_dump(mode="json")},
    })
    assert [event.event_id for event in rendered.events] == ["analysis-single:event:0"]
    assert rendered.events[0].status == "uncertain"


def test_presenter_does_not_mark_unclassified_event_window_ambiguous() -> None:
    facts = AnalysisFactsV2(
        analysis_id="analysis-window",
        authority="v2",
        facts=(AnalysisFactV2(
            analysis_id="analysis-window",
            event_id="event-window",
            claim_type="event_window",
            value={"start_pts_sec": .2, "end_pts_sec": .8, "proposal_status": "pending_confirmation"},
            authority="v2",
            source_pipeline_fingerprint="sha256:window",
            definition_version="action-event-proposal.v1",
            compatibility_group="action-event/source-pts/v1",
            unit="source_pts",
            status="uncertain",
            observability="observable",
            confidence=.35,
            sources=("deterministic", "action_event_proposal"),
            source_fingerprints={"deterministic": "sha256:d", "proposal": "sha256:p"},
        ),),
    )
    rendered = present_analysis_experience({
        "id": "analysis-window",
        "facts_authority": "v2",
        "source_fact_hash": facts.source_fact_hash,
        "analysis_facts": {"schema_version": "analysis-facts.v2", **facts.model_dump(mode="json")},
    })
    event = rendered.events[0]
    assert event.profile == "unknown"
    assert event.state == "unknown"
    assert event.status == "uncertain"
