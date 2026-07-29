from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.analysis_v2.config import PipelineMode, RuntimeConfig


@dataclass(frozen=True)
class ShadowRunResult:
    status: str
    writes_performed: int
    artifact_references: tuple[str, ...]


class ShadowOrchestrator(Protocol):
    async def run(self, legacy_result: Mapping[str, Any]) -> ShadowRunResult: ...


class NoOpShadowOrchestrator:
    """Iteration 0 boundary: proves dispatch safety without persisting or computing V2 data."""

    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config

    async def run(self, legacy_result: Mapping[str, Any]) -> ShadowRunResult:
        del legacy_result
        status = "ready" if self._config.pipeline_mode is PipelineMode.SHADOW else "disabled"
        return ShadowRunResult(status=status, writes_performed=0, artifact_references=())
