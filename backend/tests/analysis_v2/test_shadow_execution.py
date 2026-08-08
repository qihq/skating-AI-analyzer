from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.analysis_v2.config import load_runtime_config
from app.analysis_v2.contamination_inventory import FAMILY_DOMAIN_SPECS, MappingSnapshotProvider
from app.analysis_v2.orchestration import ShadowArtifactStore, ShadowRunResult
from app.analysis_v2.shadow_contracts import ShadowRecoveryResponse, ShadowRetryRequest, ShadowRunRequest
from app.analysis_v2.shadow_execution import ShadowExecutionCoordinator, drain_shadow_executions
from app.routers import shadow


def _config(tmp_path: Path):
    return load_runtime_config(
        {"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(tmp_path / "runtime")},
        project_root=tmp_path,
    )


def test_coordinator_reuses_one_bounded_task_for_duplicate_requests(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = _config(tmp_path)
        store = ShadowArtifactStore(config.runtime_root or tmp_path / "runtime")
        # Create/save through the canonical manifest so the coordinator is
        # tested independently from FastAPI dependency injection.
        from app.analysis_v2.orchestration import ShadowRun

        run = ShadowRun.create(
            analysis_id="analysis-1",
            source_identity={"video_hash": "sha256:video"},
            pipeline_fingerprint="pipeline-1",
        )
        store.save_run(run)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        class FakeOrchestrator:
            queue = SimpleNamespace(drain=AsyncMock())

            async def run(self, legacy_result, **kwargs):
                nonlocal calls
                calls += 1
                assert legacy_result["authority"] == "legacy"
                started.set()
                await release.wait()
                return ShadowRunResult(
                    status="completed",
                    writes_performed=1,
                    artifact_references=(),
                    run_id=kwargs["run"].run_id,
                )

        coordinator = ShadowExecutionCoordinator(config, store=store)
        coordinator.orchestrator = FakeOrchestrator()  # type: ignore[assignment]
        first = asyncio.create_task(coordinator.submit(run.run_id, {"authority": "legacy"}))
        await started.wait()
        second = await coordinator.submit(run.run_id, {"authority": "legacy"})
        assert second.accepted is True
        assert second.coalesced is True
        assert calls == 1
        release.set()
        first_receipt = await first
        assert first_receipt.task is not None
        await first_receipt.task
        assert calls == 1

    asyncio.run(scenario())


def test_coordinator_accepts_explicit_contamination_provider_without_auto_discovery(tmp_path: Path) -> None:
    config = _config(tmp_path)
    tables: dict[str, object] = {}
    logical: dict[str, object] = {}
    files: dict[str, object] = {}
    for spec in FAMILY_DOMAIN_SPECS.values():
        tables.update({name: [] for name in spec.tables})
        logical.update({name: {"stable": True} for name in spec.logical})
        files.update({name: [] for name in spec.files})
    provider = MappingSnapshotProvider(tables=tables, logical=logical, files=files)

    coordinator = ShadowExecutionCoordinator(config, contamination_provider=provider)

    assert coordinator.orchestrator._contamination_provider is provider


def test_parent_create_retry_and_recover_enqueue_execution(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = shadow.ShadowArtifactStore(config)
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    coordinator = SimpleNamespace(submit=AsyncMock(return_value=SimpleNamespace(accepted=True, reason=None)))
    request = ShadowRunRequest(analysis_id="a1", source_video_hash="sha256:video")

    with patch.object(shadow, "get_shadow_execution_coordinator", return_value=coordinator):
        created = asyncio.run(shadow.create_shadow_run(request, None, store, session, config))
        assert created.run.status == "queued"
        assert coordinator.submit.await_count == 1

        retry_request = ShadowRetryRequest(
            stage="pose",
            requested_by="parent",
            confirmation="confirm_shadow_retry",
        )
        retried = asyncio.run(shadow.retry_shadow_run(created.run.run_id, retry_request, None, store, session, config))
        assert retried.run.retry_from_stage == "pose"
        assert coordinator.submit.await_count == 2

        recovered = asyncio.run(shadow.recover_shadow_run(created.run.run_id, None, store, session, config))
        assert isinstance(recovered, ShadowRecoveryResponse)
        assert coordinator.submit.await_count == 3


def test_api_source_path_is_ephemeral_and_not_manifested(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = _config(tmp_path)
        source = config.runtime_paths["uploads"] / "clip.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"fixture")

        class AnalysisFixture:
            id = "a1"
            status = "completed"
            action_type = "jump"
            action_subtype = None
            analysis_profile = "jump"
            pipeline_version = "legacy"
            report = {}
            vision_structured = {}
            vision_path_a = {}
            vision_path_b = {}
            cross_validation = {}
            pose_data = {}
            bio_data = {}
            frame_motion_scores = {"video_identity": {"sha256": "sha256:fixture"}}
            processing_timings = {}
            target_lock = {}
            action_window_start = 0.0
            action_window_end = 1.0
            source_fps = 30.0
            is_slow_motion = False
            force_score = None
            note = None
            video_path = str(source)

        session = AsyncMock()
        session.get = AsyncMock(return_value=AnalysisFixture())
        store = shadow.ShadowArtifactStore(config)
        coordinator = SimpleNamespace(submit=AsyncMock(return_value=SimpleNamespace(accepted=True, reason=None)))
        with patch.object(shadow, "get_shadow_execution_coordinator", return_value=coordinator):
            response = await shadow.create_shadow_run(
                ShadowRunRequest(analysis_id="a1", source_video_hash="sha256:fixture"),
                None,
                store,
                session,
                config,
            )
        manifest = (config.runtime_root / "shadow" / "v2" / "runs" / response.run.run_id / "run.json").read_text(encoding="utf-8")
        assert str(source) not in manifest
        assert len(response.run.legacy_stage_fingerprints) == 10
        identity = coordinator.submit.await_args.kwargs["source_identity"]
        assert identity["source_path"] == str(source.resolve())

    asyncio.run(scenario())


def test_explicit_api_legacy_baseline_is_not_overwritten(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = shadow.ShadowArtifactStore(config)
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    coordinator = SimpleNamespace(submit=AsyncMock(return_value=SimpleNamespace(accepted=True, reason=None)))
    request = ShadowRunRequest(
        analysis_id="a1",
        source_video_hash="sha256:video",
        legacy_stage_fingerprints={"timebase": "explicit-baseline"},
    )

    with patch.object(shadow, "get_shadow_execution_coordinator", return_value=coordinator):
        response = asyncio.run(shadow.create_shadow_run(request, None, store, session, config))

    assert response.run.legacy_stage_fingerprints == {"timebase": "explicit-baseline"}


def test_drain_shadow_executions_is_safe_without_pending_work() -> None:
    asyncio.run(drain_shadow_executions())
