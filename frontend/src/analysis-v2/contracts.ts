export type PipelineMode = "legacy" | "shadow" | "v2";
export type PublicAuthority = "legacy";
export type CapabilityLoadState = "loading" | "ready" | "fallback";

export interface RuntimeCapabilities {
  schemaVersion: "runtime-capabilities.v1";
  supportedAnalysisExperienceSchemaVersions: string[];
  runtimeMode: PipelineMode;
  publicAuthority: PublicAuthority;
  enableV2Components: boolean;
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

export type ExperienceAuthority = "legacy" | "v2";
export type ExperienceStatus = "confirmed" | "uncertain" | "unobservable";
export interface ExperienceClaim {
  analysisId: string;
  eventId: string | null;
  claimType: string;
  value: unknown;
  authority: ExperienceAuthority;
  sourcePipelineFingerprint: string;
  definitionVersion: string;
  unit: string | null;
  convention: string | null;
  status: ExperienceStatus;
  observability: "observable" | "partially_observable" | "unobservable";
  confidence: number | null;
}
export interface ExperienceEvent { eventId: string; profile: string; startPts: number | null; endPts: number | null; status: ExperienceStatus; observability: ExperienceClaim["observability"]; }
export interface ExperienceReviewTask { taskId: string; authority: ExperienceAuthority; kind: string; eventId: string | null; }
export type SourceTimelineStatus = "exact" | "approximate_legacy" | "unavailable";
export interface SourceTimelineFrame { sourceFrameIndex: number; ptsSec: number | null; durationSec: number | null; status: "available" | "duplicate_pts" | "gap_after_previous" | "discontinuity" | "timestamp_unavailable"; gapBeforeSec: number; }
export interface SourceTimeline { schemaVersion: "source-timeline.v1"; sourceVideoHash: string; durationSec: number | null; width: number; height: number; rotationDegrees: 0 | 90 | 180 | 270; timestampStatus: SourceTimelineStatus; frames: SourceTimelineFrame[]; decodeGaps: Array<{ previousFrameIndex: number; nextFrameIndex: number; previousPtsSec: number; nextPtsSec: number; missingDurationSec: number; reason: "dropped_frames" | "timestamp_discontinuity" }>; ptsDiscontinuities: number[]; fingerprint: string; }
export interface AnalysisExperienceV2 {
  schemaVersion: "analysis-experience.v2";
  analysisId: string;
  authority: ExperienceAuthority;
  pipelineMode: PipelineMode;
  sourcePipelineFingerprint: string;
  diagnosticOnly: boolean;
  familyUsable: boolean;
  events: ExperienceEvent[];
  claims: ExperienceClaim[];
  reviewTasks: ExperienceReviewTask[];
  sourceTimeline?: SourceTimeline | null;
}

export type ExperienceStatusLanguage = {
  code: "ready" | "diagnostic_only" | "unavailable" | "unsupported_schema" | "mixed_authority";
  authority: ExperienceAuthority | null;
  familyUsable: boolean;
  diagnosticOnly: boolean;
  message: string;
};

export function buildExperienceCacheKey(analysisId: string, authority: ExperienceAuthority, sourcePipelineFingerprint: string): string {
  if (!analysisId || !sourcePipelineFingerprint) throw new Error("cache identity is incomplete");
  return `analysis-experience.v2:${authority}:${sourcePipelineFingerprint}:${analysisId}`;
}

export function sourceTimelineFrameAt(timeline: SourceTimeline | null | undefined, timestamp: number): SourceTimelineFrame | null {
  if (!timeline || timeline.timestampStatus !== "exact" || !timeline.frames.length || !Number.isFinite(timestamp)) return null;
  return timeline.frames.filter((frame) => frame.ptsSec != null).reduce<SourceTimelineFrame | null>((best, frame) => !best || Math.abs((frame.ptsSec as number) - timestamp) < Math.abs((best.ptsSec as number) - timestamp) ? frame : best, null);
}

export function sourceTimelineFrameByIndex(timeline: SourceTimeline | null | undefined, sourceFrameIndex: number): SourceTimelineFrame | null {
  if (!timeline || !Number.isInteger(sourceFrameIndex) || sourceFrameIndex < 0) return null;
  return timeline.frames.find((frame) => frame.sourceFrameIndex === sourceFrameIndex) ?? null;
}

export function statusLanguageForPayload(value: unknown): ExperienceStatusLanguage {
  if (!value || typeof value !== "object" || (value as Record<string, unknown>).schema_version !== "analysis-experience.v2") {
    return { code: "unsupported_schema", authority: null, familyUsable: false, diagnosticOnly: true, message: "此分析版本暂不支持，无法安全显示新的分析结论。" };
  }
  const raw = value as Record<string, unknown>;
  if (raw.authority !== "legacy" && raw.authority !== "v2") return { code: "mixed_authority", authority: null, familyUsable: false, diagnosticOnly: true, message: "分析来源不一致，需要重新读取。" };
  const diagnosticOnly = raw.diagnostic_only === true;
  const familyUsable = raw.family_usable !== false && !diagnosticOnly;
  return { code: diagnosticOnly ? "diagnostic_only" : familyUsable ? "ready" : "unavailable", authority: raw.authority, familyUsable, diagnosticOnly, message: diagnosticOnly ? "仅供家长诊断查看，尚未用于家庭页面。" : familyUsable ? "分析结果可查看。" : "分析结果暂不可用。" };
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid analysis experience");
  return value as Record<string, unknown>;
}

function isExperienceStatus(value: unknown): value is ExperienceStatus {
  return value === "confirmed" || value === "uncertain" || value === "unobservable";
}

function isExperienceObservability(value: unknown): value is ExperienceClaim["observability"] {
  return value === "observable" || value === "partially_observable" || value === "unobservable";
}
function decodeSourceTimeline(value: unknown): SourceTimeline | null {
  if (value == null) return null;
  if (!value || typeof value !== "object") throw new Error("invalid source timeline");
  const raw = value as Record<string, unknown>;
  if (raw.schema_version !== "source-timeline.v1" || typeof raw.source_video_hash !== "string" || typeof raw.width !== "number" || typeof raw.height !== "number" || !Array.isArray(raw.frames) || !Array.isArray(raw.decode_gaps) || !Array.isArray(raw.pts_discontinuities) || typeof raw.fingerprint !== "string") throw new Error("invalid source timeline");
  const status = raw.timestamp_status;
  if (status !== "exact" && status !== "approximate_legacy" && status !== "unavailable") throw new Error("invalid source timeline status");
  return { schemaVersion: "source-timeline.v1", sourceVideoHash: raw.source_video_hash, durationSec: (raw.duration_sec as number | null) ?? null, width: raw.width, height: raw.height, rotationDegrees: raw.rotation_degrees as SourceTimeline["rotationDegrees"], timestampStatus: status, frames: raw.frames.map((item) => { const frame = record(item); return { sourceFrameIndex: Number(frame.source_frame_index), ptsSec: (frame.pts_sec as number | null) ?? null, durationSec: (frame.duration_sec as number | null) ?? null, status: frame.status as SourceTimelineFrame["status"], gapBeforeSec: Number(frame.gap_before_sec ?? 0) }; }), decodeGaps: raw.decode_gaps.map((item) => { const gap = record(item); return { previousFrameIndex: Number(gap.previous_frame_index), nextFrameIndex: Number(gap.next_frame_index), previousPtsSec: Number(gap.previous_pts_sec), nextPtsSec: Number(gap.next_pts_sec), missingDurationSec: Number(gap.missing_duration_sec), reason: gap.reason as "dropped_frames" | "timestamp_discontinuity" }; }), ptsDiscontinuities: raw.pts_discontinuities.map(Number), fingerprint: raw.fingerprint };
}
export function decodeAnalysisExperienceV2(value: unknown): AnalysisExperienceV2 {
  const raw = record(value);
  if (raw.schema_version !== "analysis-experience.v2" || (raw.authority !== "legacy" && raw.authority !== "v2") || !isPipelineMode(raw.pipeline_mode) || typeof raw.analysis_id !== "string" || typeof raw.source_pipeline_fingerprint !== "string") throw new Error("unsupported analysis experience schema");
  const events = (Array.isArray(raw.events) ? raw.events : []).map((item) => {
    const event = record(item);
    if (typeof event.event_id !== "string" || typeof event.profile !== "string" || !isExperienceStatus(event.status) || !isExperienceObservability(event.observability)) throw new Error("invalid experience event");
    if (event.start_pts !== undefined && event.start_pts !== null && typeof event.start_pts !== "number") throw new Error("invalid event start PTS");
    if (event.end_pts !== undefined && event.end_pts !== null && typeof event.end_pts !== "number") throw new Error("invalid event end PTS");
    return { eventId: event.event_id, profile: event.profile, startPts: (event.start_pts as number | null) ?? null, endPts: (event.end_pts as number | null) ?? null, status: event.status, observability: event.observability };
  });
  const claims = (Array.isArray(raw.claims) ? raw.claims : []).map((item) => { const c = record(item); if (c.authority !== raw.authority || c.analysis_id !== raw.analysis_id || typeof c.claim_type !== "string" || typeof c.source_pipeline_fingerprint !== "string" || (c.status !== undefined && !isExperienceStatus(c.status)) || (c.observability !== undefined && !isExperienceObservability(c.observability))) throw new Error("mixed or invalid claim authority"); return { analysisId: String(c.analysis_id), eventId: (c.event_id as string | null) ?? null, claimType: String(c.claim_type), value: c.value ?? null, authority: c.authority as ExperienceAuthority, sourcePipelineFingerprint: String(c.source_pipeline_fingerprint), definitionVersion: String(c.definition_version ?? ""), unit: (c.unit as string | null) ?? null, convention: (c.convention as string | null) ?? null, status: (c.status as ExperienceStatus) ?? "confirmed", observability: (c.observability as ExperienceClaim["observability"]) ?? "observable", confidence: (c.confidence as number | null) ?? null }; });
  const reviewTasks = (Array.isArray(raw.review_tasks) ? raw.review_tasks : []).map((item) => { const t = record(item); if (t.authority !== raw.authority || typeof t.task_id !== "string" || typeof t.kind !== "string") throw new Error("cross-authority or invalid review task"); return { taskId: t.task_id, authority: t.authority as ExperienceAuthority, kind: t.kind, eventId: (t.event_id as string | null) ?? null }; });
  return { schemaVersion: "analysis-experience.v2", analysisId: String(raw.analysis_id), authority: raw.authority as ExperienceAuthority, pipelineMode: raw.pipeline_mode as PipelineMode, sourcePipelineFingerprint: String(raw.source_pipeline_fingerprint), diagnosticOnly: Boolean(raw.diagnostic_only), familyUsable: raw.family_usable !== false, events, claims, reviewTasks, sourceTimeline: decodeSourceTimeline(raw.source_timeline) };
}
export function selectClaim(experience: AnalysisExperienceV2, claimType: string, identity?: { authority: ExperienceAuthority; sourcePipelineFingerprint: string }): ExperienceClaim | { status: "unobservable"; observability: "unobservable" } {
  if (identity && (identity.authority !== experience.authority || identity.sourcePipelineFingerprint !== experience.sourcePipelineFingerprint)) throw new Error("selector identity does not match experience");
  if (experience.claims.some((claim) => claim.authority !== experience.authority || claim.sourcePipelineFingerprint !== experience.sourcePipelineFingerprint)) throw new Error("mixed claim authority");
  return experience.claims.find((claim) => claim.claimType === claimType) ?? { status: "unobservable", observability: "unobservable" };
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
    raw.analysis_experience_v2_enabled !== true ||
    !raw.supported_analysis_experience_schema_versions.includes("analysis-experience.v2") ||
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
    enableV2Components: true,
    parentTools: {
      shadow: parentTools.shadow,
      golden: parentTools.golden,
      diagnostics: parentTools.diagnostics,
    },
    compatible: true,
  };
}
