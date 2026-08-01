import { describe, expect, it } from "vitest";

import { buildExperienceCacheKey, decodeAnalysisExperienceV2, decodeRuntimeCapabilities, legacyFallbackCapabilities, selectClaim, statusLanguageForPayload } from "./contracts";

describe("runtime capability contract", () => {
  it("decodes a supported legacy-authoritative shadow response", () => {
    expect(
      decodeRuntimeCapabilities({
        schema_version: "runtime-capabilities.v1",
        supported_analysis_experience_schema_versions: ["analysis-experience.v2"],
        runtime_mode: "shadow",
        public_authority: "legacy",
        analysis_experience_v2_enabled: true,
        parent_tools: { shadow: true, golden: true, diagnostics: true },
      }),
    ).toMatchObject({ runtimeMode: "shadow", publicAuthority: "legacy", enableV2Components: true, compatible: true });
  });

  it("falls back to a complete legacy experience for an incompatible schema", () => {
    expect(decodeRuntimeCapabilities({ schema_version: "future" })).toEqual(legacyFallbackCapabilities("incompatible"));
  });

  it("enables only the presenter-backed experience contract in shadow mode", () => {
    const result = decodeRuntimeCapabilities({
      schema_version: "runtime-capabilities.v1",
      supported_analysis_experience_schema_versions: ["analysis-experience.v2"],
      runtime_mode: "shadow",
      public_authority: "legacy",
      analysis_experience_v2_enabled: true,
      parent_tools: { shadow: true, golden: true, diagnostics: true },
    });

    expect(result.enableV2Components).toBe(true);
  });
});

describe("analysis experience v2 contract", () => {
  const base = {
    schema_version: "analysis-experience.v2",
    analysis_id: "a1",
    authority: "legacy",
    pipeline_mode: "legacy",
    source_pipeline_fingerprint: "legacy:v1",
    diagnostic_only: false,
    family_usable: true,
    events: [],
    claims: [],
    review_tasks: [],
    source_timeline: null,
  };

  it("decodes historical whole-record experience", () => {
    const decoded = decodeAnalysisExperienceV2({
      ...base,
      events: [{ event_id: "e1", profile: "jump", start_pts: 1, end_pts: 2, status: "confirmed", observability: "observable" }],
    });
    expect(decoded).toMatchObject({ analysisId: "a1", authority: "legacy" });
    expect(decoded.events).toEqual([{ eventId: "e1", profile: "jump", startPts: 1, endPts: 2, status: "confirmed", observability: "observable" }]);
  });

  it("rejects unsupported schema versions and mixed authorities", () => {
    expect(() => decodeAnalysisExperienceV2({ ...base, schema_version: "analysis-experience.v3" })).toThrow();
    expect(() => decodeAnalysisExperienceV2({ ...base, claims: [{ analysis_id: "a1", claim_type: "x", authority: "v2", source_pipeline_fingerprint: "x", definition_version: "x" }] })).toThrow();
    expect(() => decodeAnalysisExperienceV2({ ...base, events: [{ event_id: "e1", profile: "jump", status: "invalid", observability: "observable" }] })).toThrow();
    expect(() => decodeAnalysisExperienceV2({ ...base, review_tasks: [{ task_id: "t1", authority: "legacy" }] })).toThrow();
  });

  it("keeps missing V2 claims unavailable", () => {
    const decoded = decodeAnalysisExperienceV2({ ...base, authority: "v2", pipeline_mode: "v2" });
    expect(selectClaim(decoded, "rotation")).toEqual({ status: "unobservable", observability: "unobservable" });
  });

  it("builds an identity-bound cache key and exposes safe status language", () => {
    expect(buildExperienceCacheKey("a1", "v2", "fp-1")).toBe("analysis-experience.v2:v2:fp-1:a1");
    expect(statusLanguageForPayload({ schema_version: "future" })).toMatchObject({ code: "unsupported_schema", familyUsable: false, diagnosticOnly: true });
  });

  it("rejects selector authority or fingerprint mismatch", () => {
    const decoded = decodeAnalysisExperienceV2(base);
    expect(() => selectClaim(decoded, "action", { authority: "v2", sourcePipelineFingerprint: "v2:1" })).toThrow();
  });

  it("decodes exact source timeline identity and explicit gaps", () => {
    const decoded = decodeAnalysisExperienceV2({ ...base, source_timeline: { schema_version: "source-timeline.v1", source_video_hash: "sha256:video", duration_sec: 2, width: 1920, height: 1080, rotation_degrees: 90, timestamp_status: "exact", frames: [{ source_frame_index: 0, pts_sec: 0, duration_sec: .033, status: "available", gap_before_sec: 0 }], decode_gaps: [], pts_discontinuities: [], fingerprint: "fp" } });
    expect(decoded.sourceTimeline?.timestampStatus).toBe("exact");
    expect(decoded.sourceTimeline?.frames[0].sourceFrameIndex).toBe(0);
  });
});
