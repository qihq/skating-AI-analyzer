from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.analysis_v2.config import PipelineMode, RuntimeConfig


class ParentToolCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shadow: bool
    golden: bool
    diagnostics: bool


class RuntimeCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["runtime-capabilities.v1"] = "runtime-capabilities.v1"
    supported_analysis_experience_schema_versions: list[str]
    runtime_mode: PipelineMode
    public_authority: Literal["legacy"]
    analysis_experience_v2_enabled: Literal[True] = True
    parent_tools: ParentToolCapabilities


class AdvancedRuntimeCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["advanced-runtime-capabilities.v1"] = "advanced-runtime-capabilities.v1"
    runtime_mode: PipelineMode
    public_authority: Literal["legacy"]
    shadow_status: Literal["not_configured", "disabled", "ready"]
    shadow_execution: Literal["noop"] = "noop"
    writes_user_data: Literal[False] = False
    isolated_runtime: bool
    baseline_source_commit: str
    detector_configured: str = "yolo"
    detector_active: str = "unavailable"
    tracker_configured: str = "bytetrack"
    tracker_active: str = "unavailable"
    model_source: str = "unknown"
    model_hash: str | None = None
    dependency_ready: bool = False
    legacy_options_characterized: list[str] = []
    v2_config_fingerprint: str | None = None
    invalidation_scope: str = "shadow_diagnostics_only"
    ds918_compatible: bool | None = None


def build_public_capabilities(config: RuntimeConfig) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        supported_analysis_experience_schema_versions=["analysis-experience.v2"],
        runtime_mode=config.pipeline_mode,
        public_authority="legacy",
        parent_tools=ParentToolCapabilities(shadow=True, golden=True, diagnostics=True),
    )


def build_advanced_capabilities(config: RuntimeConfig) -> AdvancedRuntimeCapabilities:
    if config.pipeline_mode is PipelineMode.LEGACY:
        status = "disabled"
    elif not config.is_isolated:
        status = "not_configured"
    else:
        status = "ready"
    from app.analysis_v2.detection import PERSON_TRACKER_OPTIONS, resolve_provider_config
    provider = resolve_provider_config()
    return AdvancedRuntimeCapabilities(
        runtime_mode=config.pipeline_mode,
        public_authority="legacy",
        shadow_status=status,
        isolated_runtime=config.is_isolated,
        baseline_source_commit="c291324c62bcc930f96f3429dcdc9521e060b516",
        detector_configured=provider.detector,
        detector_active=provider.detector if provider.dependency_ready else "unavailable",
        tracker_configured=provider.tracker,
        tracker_active=provider.tracker if provider.dependency_ready else "unavailable",
        model_source=provider.model_source,
        model_hash=provider.model_hash,
        dependency_ready=provider.dependency_ready,
        legacy_options_characterized=list(PERSON_TRACKER_OPTIONS),
        v2_config_fingerprint=provider.fingerprint(),
        ds918_compatible=True,
    )
