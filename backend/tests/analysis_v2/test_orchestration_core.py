from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.analysis_v2.config import load_runtime_config
from app.analysis_v2.contamination_inventory import FAMILY_DOMAIN_SPECS, MappingSnapshotProvider
from app.analysis_v2.orchestration import (
    BoundedShadowQueue,
    ShadowArtifactStore,
    ShadowContaminationSentinel,
    ShadowOrchestrator,
    ShadowRun,
    ShadowStage,
    ShadowStageStatus,
    content_hash,
    diff_legacy_to_shadow,
    diff_runs,
    fingerprint_changes,
    golden_fixture_summary,
    invalidation_for_changes,
    invalidation_for_fingerprint_changes,
)


def _shadow_config(tmp_path: Path):
    return load_runtime_config(
        {"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(tmp_path / "runtime")},
        project_root=tmp_path,
    )


def test_stage_contract_and_selective_invalidation() -> None:
    run = ShadowRun.create(
        analysis_id="analysis-1",
        source_identity={"video_hash": "sha256:video"},
        pipeline_fingerprint="sha256:pipeline",
    )
    completed = run
    for stage in completed.stages:
        completed = completed.with_stage(
            ShadowStage(
                stage.name,
                status=ShadowStageStatus.COMPLETED,
                input_hash=content_hash({"in": stage.name}),
                output_hash=content_hash({"out": stage.name}),
                fingerprint=f"fp:{stage.name}",
            )
        )
    assert completed.completed
    invalidated = completed.invalidate_for_changes(("pose_config",))
    assert invalidated.first_invalid_stage == "pose"
    assert invalidated.stage("identity").status is ShadowStageStatus.COMPLETED
    assert invalidated.stage("pose").status is ShadowStageStatus.INVALID
    assert invalidated.stage("claims").status is ShadowStageStatus.INVALID
    assert invalidation_for_changes(("report_prompt",)) == ("claims",)
    assert invalidation_for_changes(("source_video",)) == (
        "timebase",
        "observations",
        "candidates",
        "identity",
        "pose",
        "events",
        "moments",
        "rotation",
        "path_reviews",
        "claims",
    )


def test_diff_pinpoints_first_divergence() -> None:
    left = ShadowRun.create(analysis_id="a", source_identity={"video_hash": "v"}, pipeline_fingerprint="p")
    right = left
    for name in ("timebase", "observations"):
        state = ShadowStage(name, status=ShadowStageStatus.COMPLETED, output_hash=f"{name}-out", fingerprint=f"{name}-fp")
        left = left.with_stage(state)
        right = right.with_stage(state)
    left = left.with_stage(ShadowStage("candidates", status=ShadowStageStatus.COMPLETED, output_hash="left", fingerprint="same"))
    right = right.with_stage(ShadowStage("candidates", status=ShadowStageStatus.COMPLETED, output_hash="right", fingerprint="same"))
    result = diff_runs(left, right)
    assert result.first_divergent_stage == "candidates"
    assert result.stages[2].first_divergent is True
    assert result.stages[3].first_divergent is False
    assert "output_hash" in result.stages[2].reasons


def test_bounded_queue_coalesces_duplicate_work() -> None:
    async def scenario() -> None:
        queue = BoundedShadowQueue(max_concurrency=1, max_pending=2)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def work() -> str:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "ok"

        first = asyncio.create_task(queue.submit("same", work))
        await started.wait()
        second = asyncio.create_task(queue.submit("same", work))
        await asyncio.sleep(0)
        release.set()
        assert await first == "ok"
        assert await second == "ok"
        assert calls == 1
        assert queue.coalesced_count == 1

    asyncio.run(scenario())


def test_shadow_run_writes_only_private_artifacts_and_resumes(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = _shadow_config(tmp_path)
        store = ShadowArtifactStore(config.runtime_root or tmp_path / "runtime")
        orchestrator = ShadowOrchestrator(config, store=store)
        run = orchestrator.create_run(
            analysis_id="analysis-1",
            source_identity={"video_hash": "sha256:video"},
            pipeline_fingerprint="sha256:pipeline",
        )
        legacy = {"report": {"summary": "legacy"}, "bio_data": {"air_time": 0.4}}

        async def timebase():
            return {"fingerprint": "source-timebase"}

        first = await orchestrator.run(legacy, run=run, stage_handlers={"timebase": timebase})
        assert first.status == "running"
        assert legacy["report"]["summary"] == "legacy"
        saved = store.load_run(run.run_id)
        reference = saved.stage("timebase").artifact_reference
        assert reference is not None
        artifact = Path(config.runtime_root or tmp_path) / reference
        assert artifact.is_file()
        assert artifact.is_relative_to(config.runtime_root or tmp_path)

        for name in ("observations", "candidates", "identity"):
            saved = saved.with_stage(ShadowStage(name, status=ShadowStageStatus.COMPLETED, output_hash=f"{name}-out"))
        resumed = orchestrator.invalidate_for_changes(saved, ("pose_config",))
        assert resumed.first_invalid_stage == "pose"
        removed = orchestrator.cleanup(resumed)
        assert removed
        # Cleanup removed the timebase artifact too, so its durable checkpoint
        # is invalidated along with descendants and can be rebuilt later.
        assert store.load_run(run.run_id).stage("timebase").status is ShadowStageStatus.INVALID

    asyncio.run(scenario())


def test_cleanup_invalidates_missing_artifact_and_resume_rebuilds_from_first_stage(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = _shadow_config(tmp_path)
        store = ShadowArtifactStore(config.runtime_root or tmp_path / "runtime")
        orchestrator = ShadowOrchestrator(config, store=store)
        calls: list[str] = []

        async def handler(*, run: ShadowRun, stage: ShadowStage, inputs: dict[str, object]) -> dict[str, object]:
            del run, inputs
            calls.append(stage.name)
            return {"stage": stage.name, "stable": True}

        run = orchestrator.create_run(
            analysis_id="analysis-resume",
            source_identity={"video_hash": "sha256:video"},
            pipeline_fingerprint="sha256:pipeline",
        )
        first = await orchestrator.run(
            {"analysis_id": "analysis-resume", "report": {"summary": "legacy"}},
            run=run,
            stage_handlers={name: handler for name in (
                "timebase", "observations", "candidates", "identity", "pose",
                "events", "moments", "rotation", "path_reviews", "claims",
            )},
        )
        assert first.status == "completed"
        calls.clear()
        removed = orchestrator.cleanup(run.run_id)
        assert removed
        stored = store.load_run(run.run_id)
        # Cleanup retains the durable manifest but invalidates the earliest
        # checkpoint whose rebuildable artifact was removed.
        assert stored.first_invalid_stage == "timebase"

        resumed = await orchestrator.run(
            {"analysis_id": "analysis-resume", "report": {"summary": "legacy"}},
            run=stored,
            stage_handlers={name: handler for name in (
                "timebase", "observations", "candidates", "identity", "pose",
                "events", "moments", "rotation", "path_reviews", "claims",
            )},
        )
        assert resumed.status == "completed"
        assert calls == [
            "timebase", "observations", "candidates", "identity", "pose",
            "events", "moments", "rotation", "path_reviews", "claims",
        ]

    asyncio.run(scenario())


def test_contamination_sentinel_detects_changes_and_allows_isolated_audit(tmp_path: Path) -> None:
    family = tmp_path / "family.json"
    family.write_text(json.dumps({"stable": True}), encoding="utf-8")
    sentinel = ShadowContaminationSentinel({"growth_compare": family}, excluded=("shadow_audit",))
    before = sentinel.capture()
    after = sentinel.capture()
    assert sentinel.verify(before, after).unchanged
    family.write_text(json.dumps({"stable": False}), encoding="utf-8")
    changed = sentinel.verify(before, sentinel.capture())
    assert changed.unchanged is False
    assert changed.changed == ("growth_compare",)


def test_orchestrator_injected_family_sentinel_writes_hash_only_isolated_audit(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = _shadow_config(tmp_path)
        store = ShadowArtifactStore(config.runtime_root or tmp_path / "runtime")
        tables: dict[str, object] = {}
        logical: dict[str, object] = {}
        files: dict[str, object] = {}
        for spec in FAMILY_DOMAIN_SPECS.values():
            tables.update({name: [{"id": f"{name}-1", "stable": True}] for name in spec.tables})
            logical.update({name: {"stable": True, "secret": "must-not-enter-audit"} for name in spec.logical})
            files.update({name: [{"path": f"{name}.bin", "sha256": "a" * 64}] for name in spec.files})
        provider = MappingSnapshotProvider(tables=tables, logical=logical, files=files)
        orchestrator = ShadowOrchestrator(config, store=store, contamination_provider=provider)
        run = orchestrator.create_run(
            analysis_id="analysis-sentinel",
            source_identity={"video_hash": "sha256:video"},
            pipeline_fingerprint="sha256:pipeline",
        )

        async def mutate_family_fixture() -> dict[str, bool]:
            logical["growth_aggregate_state"] = {"stable": False, "secret": "must-not-enter-audit"}
            return {"ok": True}

        result = await orchestrator.run(
            {"analysis_id": "analysis-sentinel", "authority": "legacy"},
            run=run,
            stage_handlers={"timebase": mutate_family_fixture},
        )
        assert result.status == "running"

        audit_path = store.audits_root / f"{run.run_id}.jsonl"
        audit_text = audit_path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in audit_text.splitlines()]
        sentinel = next(item for item in events if item["kind"] == "family_contamination_sentinel")
        assert sentinel["unchanged"] is False
        assert sentinel["changed_domains"] == ["growth_compare"]
        assert sentinel["changed_components"] == {
            "growth_compare": ["logical:growth_aggregate_state"]
        }
        assert sentinel["before_hash"].startswith("sha256:")
        assert sentinel["after_hash"].startswith("sha256:")
        assert "must-not-enter-audit" not in audit_text

    asyncio.run(scenario())


def test_orchestrator_contamination_capture_callback_is_async_and_fail_soft(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = _shadow_config(tmp_path)
        store = ShadowArtifactStore(config.runtime_root or tmp_path / "runtime")
        calls = 0

        async def capture() -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                return object()  # invalid return is audited and ignored
            raise RuntimeError("fixture capture unavailable")

        orchestrator = ShadowOrchestrator(config, store=store, contamination_capture=capture)
        run = orchestrator.create_run(
            analysis_id="analysis-callback",
            source_identity={"video_hash": "sha256:video"},
            pipeline_fingerprint="sha256:pipeline",
        )

        result = await orchestrator.run({"authority": "legacy"}, run=run, stage_handlers={})
        assert result.status == "pending"
        events = [
            json.loads(line)
            for line in (store.audits_root / f"{run.run_id}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert any(item["kind"] == "family_contamination_sentinel_capture_error" for item in events)

    asyncio.run(scenario())


def test_cancelled_shadow_stage_records_checkpoint_and_after_contamination_capture(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = _shadow_config(tmp_path)
        store = ShadowArtifactStore(config.runtime_root or tmp_path / "runtime")
        tables: dict[str, object] = {}
        logical: dict[str, object] = {}
        files: dict[str, object] = {}
        for spec in FAMILY_DOMAIN_SPECS.values():
            tables.update({name: [] for name in spec.tables})
            logical.update({name: {"stable": True} for name in spec.logical})
            files.update({name: [] for name in spec.files})
        provider = MappingSnapshotProvider(tables=tables, logical=logical, files=files)
        orchestrator = ShadowOrchestrator(config, store=store, contamination_provider=provider)
        run = orchestrator.create_run(
            analysis_id="analysis-cancelled",
            source_identity={"video_hash": "sha256:video"},
            pipeline_fingerprint="sha256:pipeline",
        )
        release = asyncio.Event()

        async def hanging_handler() -> dict[str, bool]:
            await release.wait()
            return {"ok": True}

        task = asyncio.create_task(
            orchestrator.run(
                {"authority": "legacy"},
                run=run,
                stage_handlers={"timebase": hanging_handler},
            )
        )
        while store.load_run(run.run_id).stage("timebase").status is not ShadowStageStatus.RUNNING:
            await asyncio.sleep(0)
        worker = next(iter(orchestrator.queue._inflight.values()))
        worker.cancel()
        result = await task
        assert result.status == "cancelled"
        stored = store.load_run(run.run_id)
        assert stored.stage("timebase").status is ShadowStageStatus.CANCELLED
        assert stored.first_invalid_stage == "timebase"
        audit_path = store.audits_root / f"{run.run_id}.jsonl"
        events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
        assert any(item.get("kind") == "stage_cancelled" for item in events)
        sentinel = next(item for item in events if item.get("kind") == "family_contamination_sentinel")
        assert sentinel["unchanged"] is True

    asyncio.run(scenario())


def test_pilot_golden_fixture_is_read_only_and_fingerprintable() -> None:
    path = Path(r"C:\Users\qihq\Documents\skating-analyzer-v2-runtime\test-data\pilot-12-run-20260801\golden\v2\manifest.json")
    if not path.is_file():
        pytest.skip("private pilot Golden fixture is not mounted")
    summary = golden_fixture_summary(path)
    assert summary["schema_version"] == "golden-dataset.v2"
    assert summary["revision"] == 51
    assert summary["source_count"] == 12
    assert summary["event_count"] == 12
    assert summary["track_count"] == 54
    assert summary["pose_count"] == 0
    assert summary["profiles"] == {"jump": 6, "spin": 3, "spiral": 1, "step": 2}


def test_independent_fingerprints_keep_unrelated_descendants_reusable() -> None:
    run = ShadowRun.create(
        analysis_id="a",
        source_identity={"video_hash": "video"},
        pipeline_fingerprint="pipeline",
        fingerprints={"source": "src-1", "model": "model-1", "config": "cfg-1", "prompt": "prompt-1", "contract": "contract-1"},
    )
    completed = run
    for stage in completed.stages:
        completed = completed.with_stage(ShadowStage(stage.name, status=ShadowStageStatus.COMPLETED, output_hash=f"out:{stage.name}", fingerprint=f"fp:{stage.name}"))
    updated = completed.with_fingerprints({"prompt": "prompt-2"})
    assert updated.fingerprints["source"] == "src-1"
    assert updated.stage("timebase").status is ShadowStageStatus.COMPLETED
    assert updated.stage("rotation").status is ShadowStageStatus.COMPLETED
    assert updated.stage("path_reviews").status is ShadowStageStatus.INVALID
    assert updated.first_invalid_stage == "path_reviews"
    assert fingerprint_changes(completed.fingerprints, updated.fingerprints) == ("prompt",)
    assert invalidation_for_fingerprint_changes(("prompt",)) == ("path_reviews", "claims")


def test_legacy_shadow_diff_identifies_first_unexplained_stage() -> None:
    run = ShadowRun.create(
        analysis_id="a",
        source_identity={"video_hash": "video"},
        pipeline_fingerprint="pipeline",
        legacy_stage_fingerprints={"timebase": "tb", "observations": "obs", "candidates": "legacy-candidates"},
    )
    run = run.with_stage(ShadowStage("timebase", status=ShadowStageStatus.COMPLETED, output_hash="tb", fingerprint="tb"))
    run = run.with_stage(ShadowStage("observations", status=ShadowStageStatus.COMPLETED, output_hash="obs", fingerprint="obs"))
    run = run.with_stage(ShadowStage("candidates", status=ShadowStageStatus.COMPLETED, output_hash="v2-candidates", fingerprint="v2-candidates"))
    result = diff_legacy_to_shadow(run.legacy_stage_fingerprints, run)
    assert result.first_divergent_stage == "candidates"
    assert result.stages[2].first_divergent is True
    assert result.stages[2].equal is False
