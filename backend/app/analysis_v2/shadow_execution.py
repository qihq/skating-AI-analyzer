"""Parent-authorized execution bridge for persisted Shadow runs.

The Shadow API persists a run manifest before doing any work.  This module is
the small process-local bridge that turns that manifest into actual bounded
Shadow execution.  It intentionally keeps the legacy input detached and
ephemeral: only stage checkpoints, hashes, rebuildable artifact references,
and operational audit events are written by the orchestrator.

One coordinator is reused per event loop/runtime root.  Consequently create,
retry, and restart-recovery requests share the same ``ShadowOrchestrator``
queue and duplicate submissions for one run coalesce without ever blocking or
mutating the legacy analysis transaction.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.analysis_v2.config import PipelineMode, RuntimeConfig, load_runtime_config
from app.analysis_v2.orchestration import (
    FamilyInventoryCapture,
    SHADOW_STAGE_ORDER,
    ShadowArtifactStore as CanonicalShadowArtifactStore,
    ShadowOrchestrator,
    ShadowRun,
    ShadowRunResult,
    content_hash,
)
from app.analysis_v2.contamination_inventory import SnapshotProvider


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShadowExecutionReceipt:
    """Result of enqueueing a parent-authorized Shadow run."""

    accepted: bool
    run_id: str | None = None
    coalesced: bool = False
    reason: str | None = None
    task: asyncio.Task[ShadowRunResult] | None = field(default=None, compare=False, repr=False)


class ShadowExecutionCoordinator:
    """Submit persisted runs to one bounded local Shadow orchestrator."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        store: Any | None = None,
        max_pending: int = 8,
        contamination_provider: SnapshotProvider | None = None,
        contamination_capture: FamilyInventoryCapture | None = None,
    ) -> None:
        if config.pipeline_mode is not PipelineMode.SHADOW or not config.is_isolated or config.runtime_root is None:
            raise ValueError("Shadow execution requires an isolated shadow runtime")
        if max_pending < 1:
            raise ValueError("max_pending must be positive")
        self.config = config
        # The API adapter wraps the canonical store.  Accept either form so
        # this bridge remains useful to CLI/tests without another persistence
        # layout.
        self.store = getattr(store, "canonical", None) or store or CanonicalShadowArtifactStore(config.runtime_root)
        self.orchestrator = ShadowOrchestrator(
            config,
            store=self.store,
            contamination_provider=contamination_provider,
            contamination_capture=contamination_capture,
        )
        self.max_pending = int(max_pending)
        self._tasks: dict[str, asyncio.Task[ShadowRunResult]] = {}
        self._task_manifest_hash: dict[str, str] = {}
        self._resubmit: dict[str, tuple[Mapping[str, Any], Mapping[str, str], str | None]] = {}
        self._lock = asyncio.Lock()

    @property
    def inflight_run_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tasks))

    async def submit(
        self,
        run_id: str,
        legacy_result: Mapping[str, Any],
        *,
        source_identity: Mapping[str, str] | None = None,
        resubmit_if_inflight: bool = False,
    ) -> ShadowExecutionReceipt:
        """Queue a stored run, coalescing duplicate requests.

        The input mapping is deep-copied before task creation.  No caller-owned
        legacy object can therefore be mutated by a faulty stage adapter.
        """
        try:
            run = self.store.load_run(str(run_id))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return ShadowExecutionReceipt(accepted=False, run_id=str(run_id), reason="run_not_found")

        normalized_id = run.run_id
        # A completed run with all rebuildable outputs still present is already
        # authoritative for its Shadow diagnostics; a parent retry or cleanup
        # will invalidate/remove something before submitting again.
        if run.completed and self._artifacts_present(run):
            return ShadowExecutionReceipt(
                accepted=True,
                run_id=normalized_id,
                coalesced=True,
                reason="already_complete",
            )

        async with self._lock:
            existing = self._tasks.get(normalized_id)
            if existing is not None and not existing.done():
                # A parent retry/recovery may invalidate the manifest while a
                # previous attempt is still running.  Keep the current task
                # coalesced, but remember the newer input so its completion
                # automatically schedules one bounded follow-up pass instead
                # of letting stale checkpoint writes win the race.
                if resubmit_if_inflight:
                    self._resubmit[normalized_id] = (
                        copy.deepcopy(dict(legacy_result)),
                        dict(source_identity or {}),
                        run.first_invalid_stage,
                    )
                return ShadowExecutionReceipt(
                    accepted=True,
                    run_id=normalized_id,
                    coalesced=True,
                    reason="inflight_duplicate",
                    task=existing,
                )
            if len(self._tasks) >= self.max_pending:
                return ShadowExecutionReceipt(
                    accepted=False,
                    run_id=normalized_id,
                    reason="queue_full",
                )
            detached = copy.deepcopy(dict(legacy_result))
            identity = dict(source_identity or {})
            task = asyncio.create_task(
                self._execute(run, detached, identity),
                name=f"shadow-api:{run.analysis_id}:{run.run_id}",
            )
            self._tasks[normalized_id] = task
            self._task_manifest_hash[normalized_id] = content_hash(run.to_dict())
            task.add_done_callback(lambda completed, key=normalized_id: self._forget(key, completed))
            return ShadowExecutionReceipt(accepted=True, run_id=normalized_id, task=task)

    async def _execute(
        self,
        run: ShadowRun,
        legacy_result: Mapping[str, Any],
        source_identity: Mapping[str, str],
    ) -> ShadowRunResult:
        try:
            result = await self.orchestrator.run(
                legacy_result,
                analysis_id=run.analysis_id,
                source_identity=source_identity,
                pipeline_fingerprint=run.pipeline_fingerprint,
                run=run,
            )
            self.store.append_audit(
                run.run_id,
                {
                    "kind": "parent_shadow_execution",
                    "analysis_id": run.analysis_id,
                    "run_id": run.run_id,
                    "status": result.status,
                    "first_invalid_stage": result.first_invalid_stage,
                    "writes_performed": result.writes_performed,
                    "coalesced": result.coalesced,
                    "error": bool(result.error),
                },
            )
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # The route has already returned and legacy is unrelated.  Keep a
            # durable isolated audit, but never leak an exception into it.
            logger.warning("Shadow API execution failed for %s: %s", run.run_id, type(exc).__name__)
            try:
                self.store.append_audit(
                    run.run_id,
                    {
                        "kind": "parent_shadow_execution_failure",
                        "analysis_id": run.analysis_id,
                        "run_id": run.run_id,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                    },
                )
            except Exception:  # noqa: BLE001
                logger.debug("Could not write isolated Shadow execution audit", exc_info=True)
            return ShadowRunResult(
                status="failed",
                writes_performed=0,
                artifact_references=(),
                run_id=run.run_id,
                first_invalid_stage=run.first_invalid_stage,
                error=str(exc),
            )

    def _artifacts_present(self, run: ShadowRun) -> bool:
        for stage_name in SHADOW_STAGE_ORDER:
            stage = run.stage(stage_name)
            if not stage.artifact_reference:
                return False
            if not self.store._artifact_reference_exists(stage.artifact_reference):
                return False
        return True

    def _forget(self, run_id: str, task: asyncio.Task[ShadowRunResult]) -> None:
        if self._tasks.get(run_id) is task:
            self._tasks.pop(run_id, None)
            self._task_manifest_hash.pop(run_id, None)
            pending = self._resubmit.pop(run_id, None)
            if pending is not None:
                legacy_result, source_identity, retry_stage = pending
                # The callback runs on the owning event loop.  Re-entering
                # ``submit`` asynchronously keeps the callback non-blocking
                # and preserves the same coordinator queue/coalescing rules.
                asyncio.create_task(
                    self._requeue_after_stale_completion(
                        run_id,
                        legacy_result,
                        source_identity,
                        retry_stage,
                    ),
                    name=f"shadow-api-resume:{run_id}",
                )

    async def _requeue_after_stale_completion(
        self,
        run_id: str,
        legacy_result: Mapping[str, Any],
        source_identity: Mapping[str, str],
        retry_stage: str | None,
    ) -> None:
        """Restore an explicit retry invalidation if an older worker won a race."""
        if retry_stage:
            try:
                current = self.store.load_run(run_id)
                stage = current.stage(retry_stage)
                if stage.is_valid:
                    current = current.invalidate(retry_stage, reason="parent_retry_queued")
                    self.store.save_run(current)
                    self.store.append_audit(
                        run_id,
                        {"kind": "retry_requeue_after_stale_worker", "stage": retry_stage},
                    )
            except Exception:  # noqa: BLE001
                logger.debug("Could not restore Shadow retry checkpoint for %s", run_id, exc_info=True)
        await self.submit(run_id, legacy_result, source_identity=source_identity)

    async def drain(self) -> None:
        tasks = tuple(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.orchestrator.queue.drain()


# FastAPI creates a fresh dependency object for each request, but the event
# loop is shared by the application.  Weak loop keys avoid cross-loop asyncio
# primitive reuse in tests and during reloads.
_coordinators: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, ShadowExecutionCoordinator]] = weakref.WeakKeyDictionary()


def _fallback_config(runtime_root: Path) -> RuntimeConfig:
    return load_runtime_config(
        {"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(runtime_root)},
        project_root=runtime_root.parent,
    )


def get_shadow_execution_coordinator(
    config: RuntimeConfig | Any,
    *,
    store: Any | None = None,
    contamination_provider: SnapshotProvider | None = None,
    contamination_capture: FamilyInventoryCapture | None = None,
) -> ShadowExecutionCoordinator:
    """Return the event-loop/runtime-local coordinator singleton."""
    if not isinstance(config, RuntimeConfig):
        runtime_root = getattr(getattr(store, "canonical", store), "runtime_root", None)
        if runtime_root is None:
            raise ValueError("runtime configuration is required for Shadow execution")
        config = _fallback_config(Path(runtime_root))
    if config.runtime_root is None:
        raise ValueError("Shadow runtime root is required")
    loop = asyncio.get_running_loop()
    key = str(Path(config.runtime_root).resolve())
    state = _coordinators.setdefault(loop, {})
    coordinator = state.get(key)
    if coordinator is None:
        coordinator = ShadowExecutionCoordinator(
            config,
            store=store,
            contamination_provider=contamination_provider,
            contamination_capture=contamination_capture,
        )
        state[key] = coordinator
    elif contamination_provider is not None or contamination_capture is not None:
        # A loop/runtime singleton cannot safely swap its read boundary while
        # work is in flight.  Callers that need a different copied fixture
        # should use a fresh event loop/coordinator explicitly.
        raise ValueError("Shadow execution coordinator already exists for this runtime")
    return coordinator


async def drain_shadow_executions() -> None:
    """Drain all coordinators attached to the current event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    state = _coordinators.get(loop)
    if state:
        await asyncio.gather(*(coordinator.drain() for coordinator in state.values()), return_exceptions=True)


__all__ = [
    "ShadowExecutionCoordinator",
    "ShadowExecutionReceipt",
    "get_shadow_execution_coordinator",
    "drain_shadow_executions",
]
