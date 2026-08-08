from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2
from app.routers import skaters


def _v2_record(*facts: AnalysisFactV2):
    fact_set = AnalysisFactsV2(analysis_id="v2-archive", authority="v2", facts=tuple(facts))
    return SimpleNamespace(
        id="v2-archive",
        skater_id="skater-1",
        session_id="session-1",
        skill_category="jump",
        action_type="legacy jump",
        action_subtype="legacy subtype",
        pipeline_version="legacy-pipeline",
        status="completed",
        report={"summary": "legacy summary"},
        note="legacy note",
        force_score=99,
        error_message=None,
        analysis_facts={"schema_version": "analysis-facts.v2", **fact_set.model_dump(mode="json")},
        facts_authority="v2",
        facts_schema_version="analysis-facts.v2",
        source_fact_hash=fact_set.source_fact_hash,
        source_fact_revision=1,
        source_pipeline_fingerprint="v2-pipeline",
        bio_data={"jump_metrics": {"estimated_rotations": 99}},
        frame_motion_scores=None,
        cross_validation=None,
        highlight_quote=None,
        quote_speaker=None,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        skill_node_id=None,
    )


def _fact(claim_type: str, value: object, *, event_id: str | None = "v2-archive:event:0") -> AnalysisFactV2:
    return AnalysisFactV2(
        analysis_id="v2-archive",
        event_id=event_id,
        claim_type=claim_type,
        value=value,
        authority="v2",
        source_pipeline_fingerprint="v2-pipeline",
        definition_version=f"{claim_type}.v2",
        compatibility_group=f"{claim_type}/v2",
        confidence=0.95,
        sources=("deterministic",),
        source_fingerprints={"deterministic": "sha256:deterministic"},
    )


def test_v2_archive_fields_do_not_fall_back_to_legacy_summary_or_score() -> None:
    analysis = _v2_record(_fact("action_profile", "spin"))

    fields = skaters._archive_analysis_fields(analysis)

    assert fields["action_type"] == "spin"
    assert fields["action_subtype"] is None
    assert fields["force_score"] is None
    assert fields["report_snippet"] == "暂无可用报告摘要。"


def test_v2_archive_fields_use_confirmed_same_authority_claims() -> None:
    analysis = _v2_record(_fact("action_profile", "jump"), _fact("action_label", "Waltz"), _fact("force_score", 82), _fact("report_summary", "V2 summary"))

    fields = skaters._archive_analysis_fields(analysis)

    assert fields == {
        "action_type": "jump",
        "action_subtype": "Waltz",
        "force_score": 82,
        "report_snippet": "V2 summary",
    }


def test_legacy_archive_fields_remain_whole_record_projection() -> None:
    analysis = SimpleNamespace(
        id="legacy-archive",
        action_type="jump",
        action_subtype="Toe Loop",
        pipeline_version="legacy-v1",
        status="completed",
        report={"summary": "Legacy summary"},
        note="legacy note",
        force_score=71,
        error_message=None,
        analysis_facts=None,
        facts_authority=None,
        source_fact_hash=None,
        bio_data=None,
        frame_motion_scores=None,
        cross_validation=None,
        highlight_quote=None,
        quote_speaker=None,
    )

    fields = skaters._archive_analysis_fields(analysis)

    assert fields["action_type"] == "jump"
    assert fields["action_subtype"] == "Toe Loop"
    assert fields["force_score"] == 71
    assert fields["report_snippet"] == "Legacy summary"


def test_session_detail_uses_same_authority_fields() -> None:
    analysis = _v2_record(_fact("action_profile", "spin"))
    fake_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [analysis]))
    session = SimpleNamespace(execute=AsyncMock(return_value=fake_result))
    training_session = SimpleNamespace(
        id="session-1",
        skater_id="skater-1",
        session_date=date(2026, 8, 1),
        location="rink",
        session_type="practice",
        duration_minutes=45,
        coach_present=False,
        note=None,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    detail = asyncio.run(skaters.build_session_detail(session, training_session))

    assert detail.analyses[0].action_type == "spin"
    assert detail.analyses[0].force_score is None
    assert detail.analyses[0].note is None
