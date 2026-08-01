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
    return AdvancedRuntimeCapabilities(
        runtime_mode=config.pipeline_mode,
        public_authority="legacy",
        shadow_status=status,
        isolated_runtime=config.is_isolated,
        baseline_source_commit="c291324c62bcc930f96f3429dcdc9521e060b516",
    )
