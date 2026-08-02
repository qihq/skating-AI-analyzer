from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routers import analysis_v2


def _analysis() -> SimpleNamespace:
    return SimpleNamespace(id="a1", status="completed")


def test_experience_endpoint_adapts_historical_legacy_record_without_shadow() -> None:
    session = AsyncMock()
    session.add = lambda *_args, **_kwargs: None
    session.get = AsyncMock(return_value=_analysis())
    payload = {
        "schema_version": "analysis-experience.v2",
        "analysis_id": "a1",
        "authority": "legacy",
        "pipeline_mode": "shadow",
        "source_pipeline_fingerprint": "legacy:a1",
        "diagnostic_only": True,
        "family_usable": False,
        "review_tasks": [],
        "events": [],
        "claims": [],
    }
    with patch.object(analysis_v2, "present_analysis_experience", return_value=payload):
        result = asyncio.run(analysis_v2.get_analysis_experience_v2("a1", session))
    assert result.authority == "legacy"
    assert result.pipeline_mode == "shadow"
    assert result.diagnostic_only is True
    assert result.family_usable is False


def test_experience_endpoint_uses_whole_record_presenter_without_keyword_mismatch() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(
        id="a1",
        status="completed",
        action_type="jump",
        pipeline_version="legacy-2026",
        report={"summary": "Good landing"},
    ))

    result = asyncio.run(analysis_v2.get_analysis_experience_v2("a1", session))

    assert result.authority == "legacy"
    assert result.pipeline_mode == "legacy"
    assert {claim.claim_type for claim in result.claims} >= {"action_profile", "report_summary"}


def test_diagnostic_endpoint_requires_parent_and_keeps_authority_consistent() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_analysis())

    async def reject(*_args: object, **_kwargs: object) -> None:
        raise HTTPException(status_code=403, detail="parent required")

    with patch.object(analysis_v2, "require_parent_pin", new=reject):
        with pytest.raises(HTTPException) as error:
            asyncio.run(analysis_v2.get_analysis_experience_v2_diagnostic("a1", None, session))
    assert error.value.status_code == 403

    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)), patch.object(
        analysis_v2,
        "present_analysis_experience",
        return_value={"schema_version": "analysis-experience.v2", "analysis_id": "a1", "authority": "legacy", "pipeline_mode": "shadow", "source_pipeline_fingerprint": "legacy:a1", "diagnostic_only": True, "family_usable": False, "events": [], "claims": [], "review_tasks": []},
    ):
        result = asyncio.run(analysis_v2.get_analysis_experience_v2_diagnostic("a1", "1234", session))
    assert result.authority == "legacy"
    assert result.diagnostic_only is True


def test_identity_revision_preview_requires_parent_and_preserves_causal_scope() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=_analysis())
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)):
        result = asyncio.run(analysis_v2.preview_identity_anchor_revision(
            "a1",
            analysis_v2.IdentityAnchorRequest(source_frame_index=10, pts_sec=.33, bbox=(.1, .1, .2, .3), annotator="parent", quality_score=.9, expected_revision=2, invalidated_interval=(1.0, 2.0)),
            None,
            session,
        ))
    assert result.diagnostic_only is True
    assert result.next_revision == 3
    assert result.invalidated_intervals == ((1.0, 2.0),)


def test_identity_anchor_confirmation_is_parent_authorized_and_audited() -> None:
    analysis = _analysis()
    analysis.processing_logs = []
    session = AsyncMock()
    session.add = lambda *_args, **_kwargs: None
    session.get = AsyncMock(return_value=analysis)
    session.commit = AsyncMock()
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)):
        result = asyncio.run(analysis_v2.confirm_identity_anchor_revision(
            "a1",
            analysis_v2.IdentityAnchorConfirmRequest(source_frame_index=10, pts_sec=.33, bbox=(.1, .1, .2, .3), annotator="parent", quality_score=.9, expected_revision=1, preview_revision=2, confirmation="confirm_identity_anchor_revision", invalidated_interval=(1.0, 2.0)),
            None,
            session,
        ))
    assert result.next_revision == 2
    assert analysis.processing_logs[-1]["identity_audit"]["legacy_mutation"] is False
    session.commit.assert_awaited_once()
