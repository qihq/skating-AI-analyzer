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

  it("enforces the V2 state/profile discriminated union", () => {
    expect(() => decodeAnalysisExperienceV2({ ...base, authority: "v2", pipeline_mode: "v2", events: [{ event_id: "e1", profile: "step", state: "unknown", status: "uncertain", observability: "observable" }] })).toThrow(/cannot carry/);
    expect(() => decodeAnalysisExperienceV2({ ...base, authority: "v2", pipeline_mode: "v2", events: [{ event_id: "e1", profile: "unknown", state: "confirmed", status: "confirmed", observability: "observable" }] })).toThrow(/known profile/);
    expect(decodeAnalysisExperienceV2({ ...base, authority: "v2", pipeline_mode: "v2", events: [{ event_id: "e1", profile: "step", state: "ambiguous", status: "uncertain", observability: "observable" }] }).events[0]).toMatchObject({ profile: "step", state: "ambiguous" });
  });

  it("decodes exact, range and refusal rotation exhaustively without rounding intervals", () => {
    const rotationBase = { schema_version: "rotation-estimate.v2", event_id: "e1", profile: "jump", definition_version: "airborne-body-rotation.source-pts.v1", competition_convention: "not_applied", competition_naming_turns: null, competition_naming_class: null, subtype_support: null, phases: [], signals: [], evidence_summary: [], conflicts: [], warnings: [], estimator_fingerprint: "estimator", source_timeline_fingerprint: "timeline", review_required: false };
    const exact = decodeAnalysisExperienceV2({ ...base, authority: "v2", pipeline_mode: "v2", events: [{ event_id: "e1", profile: "jump", state: "confirmed", start_pts: 0, end_pts: 1, status: "confirmed", observability: "observable", rotation: { ...rotationBase, status: "exact", value_turns: 2, range_turns: null, class_turns: 2, class_kind: "integer", confidence: .8, observability: "observed", refusal_reason: null, value_convention: "airborne_body_rotation" } }] });
    expect(exact.events[0].rotation?.status).toBe("exact");
    const range = decodeAnalysisExperienceV2({ ...base, authority: "v2", pipeline_mode: "v2", events: [{ event_id: "e1", profile: "jump", state: "confirmed", start_pts: 0, end_pts: 1, status: "uncertain", observability: "partially_observable", rotation: { ...rotationBase, status: "range", value_turns: null, range_turns: [1.5, 2.5], class_turns: null, class_kind: null, confidence: .4, observability: "partial", refusal_reason: "signal_aliasing", value_convention: "airborne_body_rotation", review_required: true } }] });
    expect(range.events[0].rotation?.status === "range" && range.events[0].rotation.rangeTurns).toEqual([1.5, 2.5]);
    expect(() => decodeAnalysisExperienceV2({ ...base, authority: "v2", pipeline_mode: "v2", events: [{ event_id: "e1", profile: "jump", state: "confirmed", start_pts: 0, end_pts: 1, status: "uncertain", observability: "partially_observable", rotation: { ...rotationBase, status: "range", value_turns: null, range_turns: [1.5, 2.5], class_turns: 2, class_kind: "integer", confidence: .4, observability: "partial", refusal_reason: "signal_aliasing", value_convention: "airborne_body_rotation" } }] })).toThrow(/inconsistent/);
    expect(() => decodeAnalysisExperienceV2({ ...base, authority: "v2", pipeline_mode: "v2", events: [{ event_id: "e1", profile: "spin", state: "confirmed", start_pts: 0, end_pts: 1, status: "confirmed", observability: "observable", rotation: { ...rotationBase, profile: "spin", status: "exact", value_turns: 2, range_turns: null, class_turns: 2, class_kind: "integer", confidence: .8, observability: "observed", refusal_reason: null, value_convention: "airborne_body_rotation" } }] })).toThrow(/must match/);
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

  it("decodes identity state and forward/backward conflicts", () => {
    const decoded = decodeAnalysisExperienceV2({ ...base, identity: { schema_version: "identity-timeline.v1", identity_id: "main-skater", state: "uncertain", confirmed_coverage: .5, uncertain_coverage: .5, lost_coverage: 0, longest_lost_interval_sec: 0, recommended_review_task: "confirm_main_skater_anchor", conflicts: [{ schema_version: "identity-conflict-interval.v1", start_pts_sec: 1, end_pts_sec: 2, reason: "forward_backward_conflict", frame_indices: [30], candidate_ids: ["a", "b"] }], anchor_revisions: [], segments: [], anchors: [] } });
    expect(decoded.identity?.state).toBe("uncertain");
    expect(decoded.identity?.conflicts[0].reason).toBe("forward_backward_conflict");
  });
});
