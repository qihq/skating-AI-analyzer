export type PipelineMode = "legacy" | "shadow" | "v2";
export type PublicAuthority = "legacy";
export type CapabilityLoadState = "loading" | "ready" | "fallback";

export interface RuntimeCapabilities {
  schemaVersion: "runtime-capabilities.v1";
  supportedAnalysisExperienceSchemaVersions: string[];
  runtimeMode: PipelineMode;
  publicAuthority: PublicAuthority;
  enableV2Components: false;
  parentTools: { shadow: boolean; golden: boolean; diagnostics: boolean };
  compatible: boolean;
  fallbackReason?: "loading" | "unavailable" | "incompatible";
}

export interface AdvancedRuntimeCapabilities {
  schema_version: "advanced-runtime-capabilities.v1";
  runtime_mode: PipelineMode;
  public_authority: PublicAuthority;
  shadow_status: "not_configured" | "disabled" | "ready";
  shadow_execution: "noop";
  writes_user_data: false;
  isolated_runtime: boolean;
  baseline_source_commit: string;
}

export function legacyFallbackCapabilities(
  reason: "loading" | "unavailable" | "incompatible",
): RuntimeCapabilities {
  return {
    schemaVersion: "runtime-capabilities.v1",
    supportedAnalysisExperienceSchemaVersions: [],
    runtimeMode: "legacy",
    publicAuthority: "legacy",
    enableV2Components: false,
    parentTools: { shadow: false, golden: false, diagnostics: false },
    compatible: false,
    fallbackReason: reason,
  };
}

function isPipelineMode(value: unknown): value is PipelineMode {
  return value === "legacy" || value === "shadow" || value === "v2";
}

export function decodeRuntimeCapabilities(value: unknown): RuntimeCapabilities {
  if (!value || typeof value !== "object") return legacyFallbackCapabilities("incompatible");
  const raw = value as Record<string, unknown>;
  const tools = raw.parent_tools;
  if (
    raw.schema_version !== "runtime-capabilities.v1" ||
    !Array.isArray(raw.supported_analysis_experience_schema_versions) ||
    !isPipelineMode(raw.runtime_mode) ||
    raw.public_authority !== "legacy" ||
    raw.analysis_experience_v2_enabled !== false ||
    !tools ||
    typeof tools !== "object"
  ) return legacyFallbackCapabilities("incompatible");
  const parentTools = tools as Record<string, unknown>;
  if (
    typeof parentTools.shadow !== "boolean" ||
    typeof parentTools.golden !== "boolean" ||
    typeof parentTools.diagnostics !== "boolean"
  ) return legacyFallbackCapabilities("incompatible");
  return {
    schemaVersion: "runtime-capabilities.v1",
    supportedAnalysisExperienceSchemaVersions: raw.supported_analysis_experience_schema_versions as string[],
    runtimeMode: raw.runtime_mode,
    publicAuthority: "legacy",
    enableV2Components: false,
    parentTools: {
      shadow: parentTools.shadow,
      golden: parentTools.golden,
      diagnostics: parentTools.diagnostics,
    },
    compatible: true,
  };
}
