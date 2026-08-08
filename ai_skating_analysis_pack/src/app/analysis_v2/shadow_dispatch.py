"""Failure-isolated dispatch from a completed legacy analysis into Shadow.

The legacy pipeline calls this module only after its authoritative completion
transaction commits.  Dispatch is deliberately fire-and-forget: bounded work
runs on the current application event loop, duplicate completion notifications
share one task, and no result is ever written back to the family database.

Only opaque identifiers and execution status are written to the isolated
Shadow audit directory.  The legacy payload itself is copied in the background
before it is handed to a runner, so even a faulty runner cannot mutate the
objects used to persist the authoritative legacy report.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from app.analysis_v2.config import PipelineMode, RuntimeConfig
from app.analysis_v2.orchestration import ShadowArtifactStore, ShadowOrchestrator, content_hash


logger = logging.getLogger(__name__)


class LegacyShadowRunner(Protocol):
    async def run(
        self,
        legacy_result: Mapping[str, Any],
        *,
        analysis_id: str,
        source_identity: Mapping[str, str],
        pipeline_fingerprint: str,
    ) -> Any: ...


ConfigProvider = Callable[[], RuntimeConfig]
RunnerFactory = Callable[[RuntimeConfig], LegacyShadowRunner]


def _default_config_provider() -> RuntimeConfig:
    # Kept lazy to avoid a router import cycle.  ``app.main`` configures this
    # provider during startup, before an analysis can complete.
    from app.routers.capabilities import get_runtime_config

    return get_runtime_config()


def _default_runner_factory(config: RuntimeConfig) -> LegacyShadowRunner:
    return ShadowOrchestrator(config)


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class LegacyShadowDispatchRequest:
    analysis_id: str
    source_identity: Mapping[str, str]
    pipeline_fingerprint: str
    legacy_result: Mapping[str, Any]

    def __post_init__(self) -> None:
        analysis_id = str(self.analysis_id).strip()
        pipeline_fingerprint = str(self.pipeline_fingerprint).strip()
        if not analysis_id or not pipeline_fingerprint:
            raise ValueError("analysis_id and pipeline_fingerprint are required")
        object.__setattr__(self, "analysis_id", analysis_id)
        object.__setattr__(self, "pipeline_fingerprint", pipeline_fingerprint)
        object.__setattr__(self, "source_identity", dict(self.source_identity))
        object.__setattr__(self, "legacy_result", dict(self.legacy_result))

    @property
    def queue_key(self) -> str:
        return content_hash(
            {
                "analysis_id": self.analysis_id,
                "source_identity": dict(self.source_identity),
                "pipeline_fingerprint": self.pipeline_fingerprint,
            }
        )


@dataclass(frozen=True)
class LegacyShadowDispatchOutcome:
    status: str
    run_id: str | None = None
    error_type: str | None = None
    runner_reported_error: bool = False


@dataclass(frozen=True)
class LegacyShadowDispatchReceipt:
    accepted: bool
    coalesced: bool = False
    reason: str | None = None
    queue_key: str | None = None
    task: asyncio.Task[LegacyShadowDispatchOutcome] | None = field(default=None, compare=False, repr=False)


@dataclass
class _LoopState:
    semaphore: asyncio.Semaphore
    inflight: dict[str, asyncio.Task[LegacyShadowDispatchOutcome]] = field(default_factory=dict)
    completed: dict[str, LegacyShadowDispatchOutcome] = field(default_factory=dict)
    runners: dict[tuple[str, str], LegacyShadowRunner] = field(default_factory=dict)


class LegacyShadowDispatcher:
    """Bounded fire-and-forget adapter for legacy completion notifications."""

    def __init__(
        self,
        *,
        config_provider: ConfigProvider = _default_config_provider,
        runner_factory: RunnerFactory = _default_runner_factory,
        max_concurrency: int = 1,
        max_pending: int = 8,
    ) -> None:
        if max_concurrency < 1 or max_pending < 1:
            raise ValueError("Shadow dispatch limits must be positive")
        self._config_provider = config_provider
        self._runner_factory = runner_factory
        self._max_concurrency = int(max_concurrency)
        self._max_pending = int(max_pending)
        # Application and isolated-asyncio test loops must not share asyncio
        # synchronization primitives.  Weak keys also release stopped loops.
        self._states: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopState] = weakref.WeakKeyDictionary()

    def dispatch(self, request: LegacyShadowDispatchRequest) -> LegacyShadowDispatchReceipt:
        try:
            config = self._config_provider()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Shadow dispatch configuration is unavailable: %s", type(exc).__name__)
            return LegacyShadowDispatchReceipt(accepted=False, reason="runtime_not_configured")

        if (
            config.pipeline_mode is not PipelineMode.SHADOW
            or not config.is_isolated
            or config.runtime_root is None
        ):
            return LegacyShadowDispatchReceipt(accepted=False, reason="shadow_disabled")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return LegacyShadowDispatchReceipt(accepted=False, reason="no_running_event_loop")

        state = self._states.get(loop)
        if state is None:
            state = _LoopState(semaphore=asyncio.Semaphore(self._max_concurrency))
            self._states[loop] = state

        key = request.queue_key
        existing = state.inflight.get(key)
        if existing is not None:
            return LegacyShadowDispatchReceipt(
                accepted=True,
                coalesced=True,
                reason="inflight_duplicate",
                queue_key=key,
                task=existing,
            )
        if key in state.completed:
            return LegacyShadowDispatchReceipt(
                accepted=True,
                coalesced=True,
                reason="already_dispatched",
                queue_key=key,
            )
        if len(state.inflight) >= self._max_pending:
            self._schedule_rejection_audit(config, request, key, reason="queue_full")
            return LegacyShadowDispatchReceipt(accepted=False, reason="queue_full", queue_key=key)

        task = loop.create_task(
            self._execute(config, state, request, key),
            name=f"legacy-shadow:{request.analysis_id}",
        )
        state.inflight[key] = task
        task.add_done_callback(lambda completed, *, dispatch_key=key: self._forget(state, dispatch_key, completed))
        return LegacyShadowDispatchReceipt(accepted=True, queue_key=key, task=task)

    async def drain(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        state = self._states.get(loop)
        if state and state.inflight:
            await asyncio.gather(*tuple(state.inflight.values()), return_exceptions=True)

    async def _execute(
        self,
        config: RuntimeConfig,
        state: _LoopState,
        request: LegacyShadowDispatchRequest,
        key: str,
    ) -> LegacyShadowDispatchOutcome:
        audit_id = self._audit_id(key)
        async with state.semaphore:
            try:
                runner = self._runner(state, config)
                # Copying potentially large legacy evidence happens after the
                # legacy completion path has returned control to the loop.
                isolated_payload = copy.deepcopy(dict(request.legacy_result))
                result = await runner.run(
                    isolated_payload,
                    analysis_id=request.analysis_id,
                    source_identity=dict(request.source_identity),
                    pipeline_fingerprint=request.pipeline_fingerprint,
                )
                outcome = LegacyShadowDispatchOutcome(
                    status=str(getattr(result, "status", "completed")),
                    run_id=(str(getattr(result, "run_id")) if getattr(result, "run_id", None) else None),
                    runner_reported_error=bool(getattr(result, "error", None)),
                )
                state.completed[key] = outcome
                # Keep post-completion coalescing bounded as well; this is an
                # in-memory duplicate guard, never a durable family record.
                while len(state.completed) > self._max_pending:
                    state.completed.pop(next(iter(state.completed)), None)
                self._append_audit(
                    config,
                    audit_id,
                    {
                        "kind": "legacy_completion_shadow_dispatch",
                        "analysis_id": request.analysis_id,
                        "queue_key": key,
                        "status": outcome.status,
                        "run_id": outcome.run_id,
                        "runner_reported_error": outcome.runner_reported_error,
                    },
                )
                return outcome
            except Exception as exc:  # noqa: BLE001
                # This task never re-raises: an unhandled task exception must
                # not escape into the already-completed legacy lifecycle.
                outcome = LegacyShadowDispatchOutcome(status="failed", error_type=type(exc).__name__)
                self._append_audit(
                    config,
                    audit_id,
                    {
                        "kind": "legacy_completion_shadow_dispatch_failure",
                        "analysis_id": request.analysis_id,
                        "queue_key": key,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                    },
                )
                logger.warning(
                    "Analysis %s Shadow dispatch failed without changing legacy completion: %s",
                    request.analysis_id,
                    type(exc).__name__,
                )
                return outcome

    def _runner(self, state: _LoopState, config: RuntimeConfig) -> LegacyShadowRunner:
        key = (str(config.runtime_root), config.pipeline_mode.value)
        runner = state.runners.get(key)
        if runner is None:
            runner = self._runner_factory(config)
            state.runners[key] = runner
        return runner

    @staticmethod
    def _forget(
        state: _LoopState,
        key: str,
        task: asyncio.Task[LegacyShadowDispatchOutcome],
    ) -> None:
        if state.inflight.get(key) is task:
            state.inflight.pop(key, None)

    def _schedule_rejection_audit(
        self,
        config: RuntimeConfig,
        request: LegacyShadowDispatchRequest,
        key: str,
        *,
        reason: str,
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                asyncio.to_thread(
                    self._append_audit,
                    config,
                    self._audit_id(key),
                    {
                        "kind": "legacy_completion_shadow_dispatch_rejected",
                        "analysis_id": request.analysis_id,
                        "queue_key": key,
                        "status": "rejected",
                        "reason": reason,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("Could not schedule isolated Shadow rejection audit", exc_info=True)

    @staticmethod
    def _audit_id(key: str) -> str:
        digest = key.removeprefix("sha256:")[:32]
        return f"dispatch-{digest}"

    @staticmethod
    def _append_audit(
        config: RuntimeConfig,
        audit_id: str,
        event: Mapping[str, Any],
    ) -> None:
        try:
            if config.runtime_root is None or not config.is_isolated:
                return
            ShadowArtifactStore(config.runtime_root).append_audit(audit_id, event)
        except Exception:  # noqa: BLE001
            # Audit storage failure is operationally visible in service logs,
            # but it can never mutate or downgrade the family analysis.
            logger.warning("Could not write isolated Shadow dispatch audit", exc_info=True)


_default_dispatcher = LegacyShadowDispatcher(
    max_concurrency=_positive_int_env("V2_SHADOW_QUEUE_CONCURRENCY", 1),
    max_pending=_positive_int_env("V2_SHADOW_QUEUE_MAX_PENDING", 8),
)


def default_shadow_pipeline_fingerprint(legacy_result: Mapping[str, Any]) -> str:
    """Return a stable fallback until a full stage adapter supplies its own."""
    return content_hash(
        {
            "schema_version": "legacy-shadow-dispatch.v1",
            "legacy_pipeline_version": str(legacy_result.get("pipeline_version") or "unknown"),
            "contract_version": "shadow-orchestration.v1",
        }
    )


def dispatch_legacy_shadow_after_completion(
    *,
    analysis_id: str,
    source_identity: Mapping[str, str],
    legacy_result: Mapping[str, Any],
    pipeline_fingerprint: str | None = None,
) -> LegacyShadowDispatchReceipt:
    """Schedule Shadow work without awaiting it or changing legacy state."""
    try:
        request = LegacyShadowDispatchRequest(
            analysis_id=analysis_id,
            source_identity=source_identity,
            pipeline_fingerprint=pipeline_fingerprint or default_shadow_pipeline_fingerprint(legacy_result),
            legacy_result=legacy_result,
        )
        return _default_dispatcher.dispatch(request)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Analysis %s Shadow dispatch setup failed without changing legacy completion: %s",
            analysis_id,
            type(exc).__name__,
        )
        return LegacyShadowDispatchReceipt(accepted=False, reason="dispatch_setup_failed")


async def drain_legacy_shadow_dispatches() -> None:
    """Test/shutdown helper; ordinary legacy completion never awaits this."""
    await _default_dispatcher.drain()
