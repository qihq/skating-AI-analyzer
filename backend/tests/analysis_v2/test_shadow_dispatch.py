from __future__ import annotations

import asyncio
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.analysis_v2.config import RuntimeConfig, load_runtime_config
from app.analysis_v2.shadow_dispatch import (
    LegacyShadowDispatchRequest,
    LegacyShadowDispatcher,
)


def _config(tmp_path: Path, mode: str = "shadow") -> RuntimeConfig:
    env = {"SKATING_ANALYSIS_PIPELINE": mode}
    if mode != "legacy":
        env["V2_RUNTIME_ROOT"] = str(tmp_path / "runtime")
    return load_runtime_config(env, project_root=tmp_path)


def _request(snapshot: dict[str, object] | None = None) -> LegacyShadowDispatchRequest:
    return LegacyShadowDispatchRequest(
        analysis_id="analysis-1",
        source_identity={"analysis_id": "analysis-1", "video_hash": "video-sha256"},
        pipeline_fingerprint="sha256:pipeline",
        legacy_result=snapshot or {"status": "completed", "report": {"summary": "legacy"}},
    )


class ShadowDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_is_fire_and_forget_and_runner_receives_full_snapshot(self) -> None:
        tmp_path = self._temp_path()
        release = asyncio.Event()
        seen: list[dict[str, object]] = []

        class Runner:
            async def run(self, legacy_result, **kwargs):  # noqa: ANN001
                seen.append({"payload": legacy_result, "kwargs": kwargs})
                await release.wait()
                return SimpleNamespace(status="completed", run_id="run-1", error=None)

        dispatcher = LegacyShadowDispatcher(
            config_provider=lambda: _config(tmp_path),
            runner_factory=lambda _: Runner(),
            max_concurrency=1,
            max_pending=2,
        )
        snapshot = {"status": "completed", "report": {"summary": "legacy"}, "pose_data": {"count": 3}}

        receipt = dispatcher.dispatch(_request(snapshot))

        self.assertTrue(receipt.accepted)
        self.assertIsNotNone(receipt.task)
        assert receipt.task is not None
        self.assertFalse(receipt.task.done())
        await asyncio.sleep(0)
        self.assertEqual(seen[0]["payload"], snapshot)
        self.assertEqual(seen[0]["kwargs"], {
            "analysis_id": "analysis-1",
            "source_identity": {"analysis_id": "analysis-1", "video_hash": "video-sha256"},
            "pipeline_fingerprint": "sha256:pipeline",
        })
        release.set()
        outcome = await receipt.task
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.run_id, "run-1")


    async def test_runner_failure_is_swallowed_and_cannot_mutate_legacy_snapshot(self) -> None:
        tmp_path = self._temp_path()

        class MutatingFailureRunner:
            async def run(self, legacy_result, **_):  # noqa: ANN001
                legacy_result["status"] = "failed"
                legacy_result["report"]["summary"] = "shadow overwrite"
                raise RuntimeError("shadow failed")

        dispatcher = LegacyShadowDispatcher(
            config_provider=lambda: _config(tmp_path),
            runner_factory=lambda _: MutatingFailureRunner(),
        )
        snapshot = {"status": "completed", "report": {"summary": "authoritative legacy"}}
        before = deepcopy(snapshot)

        receipt = dispatcher.dispatch(_request(snapshot))
        self.assertIsNotNone(receipt.task)
        assert receipt.task is not None
        outcome = await receipt.task

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.error_type, "RuntimeError")
        self.assertEqual(snapshot, before)
        audit_files = list((tmp_path / "runtime" / "shadow" / "v2" / "audits").glob("dispatch-*.jsonl"))
        self.assertEqual(len(audit_files), 1)
        audit = json.loads(audit_files[0].read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(audit["kind"], "legacy_completion_shadow_dispatch_failure")
        self.assertEqual(audit["analysis_id"], "analysis-1")
        self.assertEqual(audit["error_type"], "RuntimeError")
        self.assertNotIn("authoritative legacy", audit_files[0].read_text(encoding="utf-8"))


    async def test_duplicate_dispatches_coalesce_to_one_runner_task(self) -> None:
        tmp_path = self._temp_path()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        class Runner:
            async def run(self, *_args, **_kwargs):
                nonlocal calls
                calls += 1
                started.set()
                await release.wait()
                return SimpleNamespace(status="completed", run_id="run-1", error=None)

        dispatcher = LegacyShadowDispatcher(
            config_provider=lambda: _config(tmp_path),
            runner_factory=lambda _: Runner(),
        )
        request = _request()

        first = dispatcher.dispatch(request)
        await started.wait()
        second = dispatcher.dispatch(request)

        self.assertTrue(first.accepted and second.accepted)
        self.assertTrue(second.coalesced)
        self.assertEqual(second.reason, "inflight_duplicate")
        self.assertIs(second.task, first.task)
        self.assertEqual(calls, 1)
        release.set()
        assert first.task is not None
        await first.task
        third = dispatcher.dispatch(request)
        self.assertTrue(third.coalesced)
        self.assertEqual(third.reason, "already_dispatched")
        self.assertEqual(calls, 1)


    async def test_dispatch_is_disabled_outside_isolated_shadow_runtime(self) -> None:
        tmp_path = self._temp_path()
        factory = AsyncMock()
        dispatcher = LegacyShadowDispatcher(
            config_provider=lambda: _config(tmp_path, "legacy"),
            runner_factory=factory,
        )

        receipt = dispatcher.dispatch(_request())

        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.reason, "shadow_disabled")
        self.assertIsNone(receipt.task)
        factory.assert_not_called()
        self.assertFalse((tmp_path / "runtime").exists())


    async def test_completed_legacy_hook_dispatches_detached_full_snapshot(self) -> None:
        # This focused boundary test avoids executing the large legacy pipeline:
        # the post-commit hook receives a full detached snapshot and never raises.
        import app.routers.analysis as analysis_router

        snapshot = analysis_router._legacy_shadow_snapshot(
            analysis_id="analysis-1",
            action_type="jump",
            action_subtype="single",
            analysis_profile="jump",
            pipeline_version="legacy-v1",
            report={"summary": "legacy complete"},
            vision_structured={"frames": [1]},
            vision_path_a={"path": "a"},
            vision_path_b={"path": "b"},
            cross_validation={"agreement": 1.0},
            pose_data={"source": "legacy"},
            bio_data={"air_time": 0.3},
            frame_motion_scores={"video_identity": {"sha256": "video-sha256"}},
            processing_timings={"total_s": 1.2},
            target_lock={"status": "locked"},
            action_window_start=0.0,
            action_window_end=1.0,
            source_fps=30.0,
            is_slow_motion=False,
            force_score=80,
            note="legacy note",
        )

        with patch.object(analysis_router, "dispatch_legacy_shadow_after_completion") as dispatch:
            analysis_router._dispatch_shadow_for_completed_legacy(
                analysis_id="analysis-1",
                snapshot=snapshot,
                video_identity={"sha256": "video-sha256"},
                pipeline_fingerprint="sha256:pipeline",
            )

        dispatch.assert_called_once()
        kwargs = dispatch.call_args.kwargs
        self.assertEqual(kwargs["analysis_id"], "analysis-1")
        self.assertEqual(kwargs["source_identity"]["video_hash"], "video-sha256")
        self.assertEqual(kwargs["legacy_result"]["authority"], "legacy")
        self.assertEqual(kwargs["legacy_result"]["report"], {"summary": "legacy complete"})
        self.assertEqual(kwargs["pipeline_fingerprint"], "sha256:pipeline")

    def _temp_path(self) -> Path:
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)
