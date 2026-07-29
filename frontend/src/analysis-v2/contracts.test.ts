import { describe, expect, it } from "vitest";

import { decodeRuntimeCapabilities, legacyFallbackCapabilities } from "./contracts";

describe("runtime capability contract", () => {
  it("decodes a supported legacy-authoritative shadow response", () => {
    expect(
      decodeRuntimeCapabilities({
        schema_version: "runtime-capabilities.v1",
        supported_analysis_experience_schema_versions: [],
        runtime_mode: "shadow",
        public_authority: "legacy",
        analysis_experience_v2_enabled: false,
        parent_tools: { shadow: true, golden: true, diagnostics: true },
      }),
    ).toMatchObject({ runtimeMode: "shadow", publicAuthority: "legacy", compatible: true });
  });

  it("falls back to a complete legacy experience for an incompatible schema", () => {
    expect(decodeRuntimeCapabilities({ schema_version: "future" })).toEqual(legacyFallbackCapabilities("incompatible"));
  });

  it("never enables V2 components in shadow mode", () => {
    const result = decodeRuntimeCapabilities({
      schema_version: "runtime-capabilities.v1",
      supported_analysis_experience_schema_versions: [],
      runtime_mode: "shadow",
      public_authority: "legacy",
      analysis_experience_v2_enabled: false,
      parent_tools: { shadow: true, golden: true, diagnostics: true },
    });

    expect(result.enableV2Components).toBe(false);
  });
});
