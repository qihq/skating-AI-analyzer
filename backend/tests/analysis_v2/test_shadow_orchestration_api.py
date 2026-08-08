from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.analysis_v2.config import load_runtime_config
from app.analysis_v2.shadow_contracts import ShadowReviewDecisionRequest, ShadowRunRequest, ShadowRetryRequest
from app.analysis_v2.shadow_store import ShadowArtifactStore
from app.routers import shadow
from app.routers import analysis_v2


def _config(tmp_path: Path):
    return load_runtime_config(
        {"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(tmp_path / "runtime")},
        project_root=tmp_path,
    )


def test_shadow_store_duplicate_requests_coalesce_and_stay_isolated(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ShadowArtifactStore(config)
    request = ShadowRunRequest(analysis_id="a1", source_video_hash="sha256:golden", config_fingerprint="cfg-1")

    first = store.create(request)
    second = store.create(request)

    assert first.run_id == second.run_id
    assert second.coalesced is True
    assert first.authority == "legacy"
    assert first.diagnostic_only is True
    assert first.stages[0].stage == "timebase"
    assert store.root.is_relative_to(config.runtime_root)
    assert not (config.runtime_paths["data"] / "skating-analyzer.db").exists()


def test_shadow_retry_resumes_from_requested_stage_and_invalidates_descendants(tmp_path: Path) -> None:
    store = ShadowArtifactStore(_config(tmp_path))
    run = store.create(ShadowRunRequest(analysis_id="a1"))
    store.update_stage(run.run_id, "timebase", status="complete", output_hash="tb")
    store.update_stage(run.run_id, "observations", status="complete", output_hash="obs")
    store.update_stage(run.run_id, "pose", status="failed", error="model unavailable")
    resumed = store.retry(run.run_id, "pose")

    assert resumed.status == "partial"
    assert resumed.retry_from_stage == "pose"
    assert resumed.stages[1].status == "complete"
    assert next(item for item in resumed.stages if item.stage == "pose").status == "invalid"
    assert resumed.stages[-1].status == "invalid"


def test_shadow_routes_require_parent_and_review_cannot_promote_legacy(tmp_path: Path) -> None:
    config = _config(tmp_path)
    session = AsyncMock()

    async def reject(*_args: object, **_kwargs: object) -> None:
        raise HTTPException(status_code=403, detail="parent required")

    with patch.object(shadow, "require_parent_pin", new=reject):
        with pytest.raises(HTTPException) as error:
            asyncio.run(shadow.require_shadow_parent(None, session))
    assert error.value.status_code == 403

    store = ShadowArtifactStore(config)
    run = store.create(ShadowRunRequest(analysis_id="a1"))
    bad = ShadowReviewDecisionRequest(
        stage="events",
        decision="promote_candidate",
        reviewer="parent",
        confirmation="confirm_shadow_review_decision",
    )
    with patch.object(shadow, "require_parent_pin", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as error:
            asyncio.run(shadow.add_shadow_review_decision(run.run_id, bad, None, store))
    assert error.value.status_code == 422

    accepted = ShadowReviewDecisionRequest(stage="events", decision="accept_shadow", reviewer="parent", confirmation="confirm_shadow_review_decision")
    with patch.object(shadow, "require_parent_pin", new=AsyncMock(return_value=None)):
        result = asyncio.run(shadow.add_shadow_review_decision(run.run_id, accepted, None, store))
    assert result["legacy_report_rewritten"] is False
    assert store.review_decisions(run.run_id)[0].authority == "shadow"
    assert store.review_decisions(run.run_id)[0].legacy_mutation is False


def test_shadow_retry_contract_requires_explicit_confirmation() -> None:
    with pytest.raises(Exception):
        ShadowRetryRequest.model_validate({"stage": "pose"})


def test_ordinary_experience_endpoint_never_reads_shadow_store(tmp_path: Path) -> None:
    store = ShadowArtifactStore(_config(tmp_path))
    store.create(ShadowRunRequest(analysis_id="a1", source_video_hash="sha256:private-golden"))
    session = AsyncMock()
    session.get = AsyncMock(return_value=type("AnalysisFixture", (), {"id": "a1", "status": "completed", "pipeline_version": "legacy", "report": {"summary": "legacy report"}, "processing_logs": []})())

    with patch.object(analysis_v2, "present_analysis_experience", return_value={"schema_version": "analysis-experience.v2", "analysis_id": "a1", "authority": "legacy", "pipeline_mode": "legacy", "source_pipeline_fingerprint": "legacy:a1", "diagnostic_only": False, "family_usable": True, "events": [], "claims": [], "review_tasks": []}), patch.object(store, "read", side_effect=AssertionError("ordinary endpoint must not read Shadow")):
        payload = asyncio.run(analysis_v2.get_analysis_experience_v2("a1", session))

    assert payload.authority == "legacy"
    assert payload.diagnostic_only is False
    assert "private-golden" not in payload.model_dump_json()


def test_shadow_store_persists_independent_fingerprints_and_recovery_cleanup(tmp_path: Path) -> None:
    store = ShadowArtifactStore(_config(tmp_path))
    request = ShadowRunRequest(
        analysis_id="a1",
        source_video_hash="sha256:video",
        model_fingerprint="model-1",
        config_fingerprint="config-1",
        prompt_fingerprint="prompt-1",
        contract_fingerprint="contract-1",
        legacy_stage_fingerprints={"timebase": "legacy-tb"},
    )
    run = store.create(request)
    assert run.model_fingerprint == "model-1"
    assert run.config_fingerprint == "config-1"
    assert run.prompt_fingerprint == "prompt-1"
    assert run.contract_fingerprint == "contract-1"
    assert run.legacy_stage_fingerprints == {"timebase": "legacy-tb"}
    store.update_stage(run.run_id, "timebase", status="complete", output_hash="tb", fingerprint="v2-tb")
    store.update_stage(run.run_id, "observations", status="running")
    recovered = store.recover_incomplete(run.run_id)
    assert recovered.retry_from_stage == "observations"
    assert recovered.stages[0].status == "complete"
    assert next(item for item in recovered.stages if item.stage == "observations").status == "invalid"
    stage = store._load(run.run_id).stage("timebase")
    reference, _ = store.canonical.write_artifact(run.run_id, "timebase", {"ok": True})
    assert Path(store._runtime_root / reference).is_file()
    removed = store.cleanup(run.run_id)
    assert reference in removed
    assert store.canonical.load_run(run.run_id).stage("timebase").status is not None


def test_shadow_store_legacy_diff_uses_attached_baseline(tmp_path: Path) -> None:
    store = ShadowArtifactStore(_config(tmp_path))
    run = store.create(ShadowRunRequest(analysis_id="a1", legacy_stage_fingerprints={"timebase": "legacy"}))
    store.update_stage(run.run_id, "timebase", status="complete", output_hash="v2", fingerprint="v2")
    first, diffs = store.stage_diffs(run.run_id)
    assert first == "timebase"
    assert diffs[0].status == "different"
    assert diffs[0].first_divergent is True
