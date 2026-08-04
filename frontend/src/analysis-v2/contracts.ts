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
  detector_configured?: string;
  detector_active?: string;
  tracker_configured?: string;
  tracker_active?: string;
  model_source?: string;
  model_hash?: string | null;
  dependency_ready?: boolean;
  legacy_options_characterized?: string[];
  v2_config_fingerprint?: string | null;
  invalidation_scope?: string;
  ds918_compatible?: boolean | null;
}

export interface DetectionProposalDiagnostics {
  schema_version: "detection-proposal-diagnostics.v1";
  status: "not_run" | "running" | "unavailable" | "failed" | "complete";
  provider: string;
  detector: string;
  tracker: string;
  model_source: string;
  model_hash: string | null;
  dependency_ready: boolean;
  candidates: Array<Record<string, unknown>>;
  short_tracks: Array<Record<string, unknown>>;
  camera: Array<Record<string, unknown>>;
  anchor_suggestions: string[];
  candidate_recall: number | null;
  diagnostics_fingerprint: string;
  invalidation_scope: string;
  ds918_compatible: boolean | null;
  candidate_recall_counts: Record<string, number>;
}

export function selectDetectionOverlays(diagnostics: DetectionProposalDiagnostics, sourceFrameIndex: number) {
  const candidates = diagnostics.candidates.filter((item) => item.source_frame_index === sourceFrameIndex);
  const shortTracks = diagnostics.short_tracks.filter((item) => Array.isArray(item.source_frame_indices) && item.source_frame_indices.includes(sourceFrameIndex));
  return { candidates, shortTracks, anchorSuggestions: diagnostics.anchor_suggestions };
}

export type ExperienceAuthority = "legacy" | "v2";
export type ExperienceStatus = "confirmed" | "uncertain" | "unobservable";
export type ActionClassificationState = "confirmed" | "ambiguous" | "unknown";
export type ActionProfile = "jump" | "spin" | "step" | "spiral" | "unknown";
export type KnownActionProfile = Exclude<ActionProfile, "unknown">;
export type JumpMomentKey = "takeoff" | "apex" | "landing";
export type SpinMomentKey = "spin_entry" | "spin_main" | "spin_exit";
export type SpiralMomentKey = "spiral_entry" | "spiral_hold" | "spiral_exit";
export type StepMomentKey = "step_sequence_interval" | "step_representative_1" | "step_representative_2" | "step_representative_3";
export type ProfileMomentKey = JumpMomentKey | SpinMomentKey | SpiralMomentKey | StepMomentKey;
export interface MomentCandidateV2 { sourceFrameIndex: number; ptsSec: number; endSourceFrameIndex: number | null; endPtsSec: number | null; score: number; observability: "observed" | "partial" | "unobservable"; evidence: string[]; provenance: string[]; warnings: string[]; }
export interface KeyMomentV2 { semanticKey: ProfileMomentKey; kind: "point" | "interval" | "representative"; status: "confirmed" | "ambiguous" | "unavailable"; sourceFrameIndex: number | null; ptsSec: number | null; endSourceFrameIndex: number | null; endPtsSec: number | null; definitionVersion: string; candidateEvidence: string[]; confidence: number; warnings: string[]; observability: "observed" | "partial" | "unobservable"; provenance: string[]; competingCandidates: MomentCandidateV2[]; reviewResolvable: boolean; }
export interface EventMomentSetV2 { schemaVersion: "event-moment-set.v1"; eventId: string; profile: KnownActionProfile; definitionVersion: string; moments: KeyMomentV2[]; expectedKeys: ProfileMomentKey[]; requiredKeys: ProfileMomentKey[]; presentKeys: ProfileMomentKey[]; missingKeys: ProfileMomentKey[]; completeness: "complete" | "incomplete" | "ambiguous" | "unobservable"; warnings: string[]; sourceTimelineFingerprint: string; stateMachineFingerprint: string; semanticLabelsConsumed: false; revision: number; }
export type ClassifiedActionIdentity =
  | { state: "confirmed"; profile: KnownActionProfile }
  | { state: "ambiguous"; profile: KnownActionProfile }
  | { state: "unknown"; profile: "unknown" };
export type PoseJointProvenance = "measured" | "smoothed" | "interpolated-display-only" | "missing" | "clipped" | "identity-blocked";
export type PoseAvailabilityStatus = "available" | "partial" | "unavailable" | "blocked";
export interface PoseAvailabilitySummary {
  schema_version: "pose-availability-summary.v1";
  status: PoseAvailabilityStatus;
  frame_count: number;
  authoritative_frame_count: number;
  measured_joint_count: number;
  smoothed_joint_count: number;
  interpolated_display_only_count: number;
  missing_joint_count: number;
  identity_blocked_frame_count: number;
  clipped_joint_count: number;
  usable_joint_mask: Record<string, boolean>;
  per_phase_quality: Record<string, number | null>;
  left_right_assignment_uncertainty: number | null;
  source_method: string;
  model_fingerprint: string | null;
}
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
type ExperienceEventFields = { eventId: string; subtype?: string | null; startPts: number | null; endPts: number | null; status: ExperienceStatus; observability: ExperienceClaim["observability"]; pose?: PoseAvailabilitySummary | null; candidateProfileScores?: Record<string, number>; proposalStatus?: "legacy" | "pending_confirmation" | "confirmed_window" | "ignored" | "ordinary_skating" | "unknown"; trackingCoverage?: number | null; poseCoverage?: number | null; provenanceFingerprint?: string | null; revision?: number; evidenceSummary?: Record<string, unknown>; confirmationTask?: string | null; definitionVersion?: string; moments?: EventMomentSetV2 | null; momentDefinitionVersion?: string | null; momentCompleteness?: EventMomentSetV2["completeness"] | null; };
export type ExperienceEvent = ExperienceEventFields & (ClassifiedActionIdentity | { profile: string; state?: undefined });
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
  identity?: IdentityTimeline | null;
  pose?: PoseAvailabilitySummary | null;
}

export type IdentityState = "confirmed" | "uncertain" | "lost";
export interface IdentityConflictInterval { schema_version: "identity-conflict-interval.v1"; start_pts_sec: number; end_pts_sec: number; reason: string; frame_indices: number[]; candidate_ids: string[]; }
export interface IdentityAnchorRevision { schema_version: "identity-anchor-revision.v1"; revision: number; parent_revision: number | null; anchor_ids: string[]; invalidated_intervals: Array<[number, number]>; created_by: string; created_at: string; provenance: string; }
export interface IdentityTimeline { schema_version: "identity-timeline.v1"; identity_id: string; state: IdentityState; confirmed_coverage: number; uncertain_coverage: number; lost_coverage: number; longest_lost_interval_sec: number; recommended_review_task: string | null; conflicts: IdentityConflictInterval[]; anchor_revisions: IdentityAnchorRevision[]; segments: Array<{ source_frame_index: number; pts_sec: number; state: IdentityState; conflict: boolean; bbox_is_display_hint: boolean; track_state: { bbox: [number, number, number, number] | null; bbox_source: string; identity_score: number; identity_margin: number | null } }>; anchors: Array<{ anchor_id: string; source_frame_index: number; pts_sec: number; bbox: [number, number, number, number]; revision: number; quality_score: number }>;
}
export interface IdentityRevisionPreview { schema_version: "identity-revision-preview.v1"; analysis_id: string; current_revision: number; next_revision: number; invalidated_intervals: Array<[number, number]>; anchor: IdentityTimeline["anchors"][number]; identity: IdentityTimeline | null; diagnostic_only: true; }

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
function isActionClassificationState(value: unknown): value is ActionClassificationState {
  return value === "confirmed" || value === "ambiguous" || value === "unknown";
}
function isActionProfile(value: unknown): value is ActionProfile {
  return value === "jump" || value === "spin" || value === "step" || value === "spiral" || value === "unknown";
}

function isProfileMomentKey(value: unknown): value is ProfileMomentKey {
  return typeof value === "string" && ["takeoff", "apex", "landing", "spin_entry", "spin_main", "spin_exit", "spiral_entry", "spiral_hold", "spiral_exit", "step_sequence_interval", "step_representative_1", "step_representative_2", "step_representative_3"].includes(value);
}

function decodeMomentCandidate(value: unknown): MomentCandidateV2 {
  const raw = record(value);
  if (raw.schema_version !== "moment-candidate.v1" || typeof raw.source_frame_index !== "number" || typeof raw.pts_sec !== "number" || typeof raw.score !== "number" || !Array.isArray(raw.evidence) || !Array.isArray(raw.provenance) || !Array.isArray(raw.warnings)) throw new Error("invalid moment candidate");
  return { sourceFrameIndex: raw.source_frame_index, ptsSec: raw.pts_sec, endSourceFrameIndex: typeof raw.end_source_frame_index === "number" ? raw.end_source_frame_index : null, endPtsSec: typeof raw.end_pts_sec === "number" ? raw.end_pts_sec : null, score: raw.score, observability: raw.observability as MomentCandidateV2["observability"], evidence: raw.evidence.map(String), provenance: raw.provenance.map(String), warnings: raw.warnings.map(String) };
}

function decodeEventMoments(value: unknown): EventMomentSetV2 {
  const raw = record(value);
  if (raw.schema_version !== "event-moment-set.v1" || typeof raw.event_id !== "string" || !isActionProfile(raw.profile) || raw.profile === "unknown" || !Array.isArray(raw.moments) || !Array.isArray(raw.expected_keys) || !Array.isArray(raw.present_keys) || !Array.isArray(raw.missing_keys) || raw.semantic_labels_consumed !== false) throw new Error("invalid event moment set");
  const moments = raw.moments.map((value) => { const moment = record(value); if (moment.schema_version !== "key-moment.v2" || !isProfileMomentKey(moment.semantic_key) || !Array.isArray(moment.competing_candidates) || !Array.isArray(moment.warnings) || !Array.isArray(moment.provenance) || !Array.isArray(moment.candidate_evidence)) throw new Error("invalid key moment"); return { semanticKey: moment.semantic_key, kind: moment.kind as KeyMomentV2["kind"], status: moment.status as KeyMomentV2["status"], sourceFrameIndex: typeof moment.source_frame_index === "number" ? moment.source_frame_index : null, ptsSec: typeof moment.pts_sec === "number" ? moment.pts_sec : null, endSourceFrameIndex: typeof moment.end_source_frame_index === "number" ? moment.end_source_frame_index : null, endPtsSec: typeof moment.end_pts_sec === "number" ? moment.end_pts_sec : null, definitionVersion: String(moment.definition_version), candidateEvidence: moment.candidate_evidence.map(String), confidence: Number(moment.confidence), warnings: moment.warnings.map(String), observability: moment.observability as KeyMomentV2["observability"], provenance: moment.provenance.map(String), competingCandidates: moment.competing_candidates.map(decodeMomentCandidate), reviewResolvable: moment.review_resolvable === true }; });
  return { schemaVersion: "event-moment-set.v1", eventId: raw.event_id, profile: raw.profile, definitionVersion: String(raw.definition_version), moments, expectedKeys: raw.expected_keys.filter(isProfileMomentKey), requiredKeys: Array.isArray(raw.required_keys) ? raw.required_keys.filter(isProfileMomentKey) : raw.expected_keys.filter(isProfileMomentKey), presentKeys: raw.present_keys.filter(isProfileMomentKey), missingKeys: raw.missing_keys.filter(isProfileMomentKey), completeness: raw.completeness as EventMomentSetV2["completeness"], warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [], sourceTimelineFingerprint: String(raw.source_timeline_fingerprint), stateMachineFingerprint: String(raw.state_machine_fingerprint), semanticLabelsConsumed: false, revision: Number(raw.revision) };
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
    if (typeof event.event_id !== "string" || (typeof event.profile !== "string") || !isExperienceStatus(event.status) || !isExperienceObservability(event.observability)) throw new Error("invalid experience event");
    if (event.state !== undefined && !isActionClassificationState(event.state)) throw new Error("invalid action classification state");
    if (raw.authority === "v2" && raw.pipeline_mode === "v2") {
      if (event.state === "unknown" && event.profile !== "unknown") throw new Error("unknown V2 event cannot carry a family profile");
      if ((event.state === "confirmed" || event.state === "ambiguous") && !isActionProfile(event.profile)) throw new Error("classified V2 event requires a known profile");
      if ((event.state === "confirmed" || event.state === "ambiguous") && event.profile === "unknown") throw new Error("classified V2 event requires a known profile");
    }
    if (event.start_pts !== undefined && event.start_pts !== null && typeof event.start_pts !== "number") throw new Error("invalid event start PTS");
    if (event.end_pts !== undefined && event.end_pts !== null && typeof event.end_pts !== "number") throw new Error("invalid event end PTS");
    const decoded = { eventId: event.event_id, profile: event.profile, startPts: (event.start_pts as number | null) ?? null, endPts: (event.end_pts as number | null) ?? null, status: event.status, observability: event.observability } as ExperienceEvent;
    if (event.subtype !== undefined) decoded.subtype = (event.subtype as string | null) ?? null;
    if (event.state !== undefined) decoded.state = event.state as ActionClassificationState;
    if (event.pose != null) decoded.pose = decodePoseAvailability(event.pose);
    if (event.candidate_profile_scores != null) decoded.candidateProfileScores = record(event.candidate_profile_scores) as Record<string, number>;
    if (event.proposal_status != null) decoded.proposalStatus = event.proposal_status as ExperienceEvent["proposalStatus"];
    if (typeof event.tracking_coverage === "number") decoded.trackingCoverage = event.tracking_coverage;
    if (typeof event.pose_coverage === "number") decoded.poseCoverage = event.pose_coverage;
    if (typeof event.provenance_fingerprint === "string") decoded.provenanceFingerprint = event.provenance_fingerprint;
    if (typeof event.revision === "number") decoded.revision = event.revision;
    if (event.evidence_summary != null) decoded.evidenceSummary = record(event.evidence_summary);
    if (event.confirmation_task === null || typeof event.confirmation_task === "string") decoded.confirmationTask = event.confirmation_task as string | null;
    if (typeof event.definition_version === "string") decoded.definitionVersion = event.definition_version;
    if (event.moments != null) decoded.moments = decodeEventMoments(event.moments);
    if (event.moment_definition_version === null || typeof event.moment_definition_version === "string") decoded.momentDefinitionVersion = event.moment_definition_version as string | null;
    if (event.moment_completeness === null || event.moment_completeness === "complete" || event.moment_completeness === "incomplete" || event.moment_completeness === "ambiguous" || event.moment_completeness === "unobservable") decoded.momentCompleteness = event.moment_completeness as EventMomentSetV2["completeness"] | null;
    return decoded;
  });
  const claims = (Array.isArray(raw.claims) ? raw.claims : []).map((item) => { const c = record(item); if (c.authority !== raw.authority || c.analysis_id !== raw.analysis_id || typeof c.claim_type !== "string" || typeof c.source_pipeline_fingerprint !== "string" || (c.status !== undefined && !isExperienceStatus(c.status)) || (c.observability !== undefined && !isExperienceObservability(c.observability))) throw new Error("mixed or invalid claim authority"); return { analysisId: String(c.analysis_id), eventId: (c.event_id as string | null) ?? null, claimType: String(c.claim_type), value: c.value ?? null, authority: c.authority as ExperienceAuthority, sourcePipelineFingerprint: String(c.source_pipeline_fingerprint), definitionVersion: String(c.definition_version ?? ""), unit: (c.unit as string | null) ?? null, convention: (c.convention as string | null) ?? null, status: (c.status as ExperienceStatus) ?? "confirmed", observability: (c.observability as ExperienceClaim["observability"]) ?? "observable", confidence: (c.confidence as number | null) ?? null }; });
  const reviewTasks = (Array.isArray(raw.review_tasks) ? raw.review_tasks : []).map((item) => { const t = record(item); if (t.authority !== raw.authority || typeof t.task_id !== "string" || typeof t.kind !== "string") throw new Error("cross-authority or invalid review task"); return { taskId: t.task_id, authority: t.authority as ExperienceAuthority, kind: t.kind, eventId: (t.event_id as string | null) ?? null }; });
  const identity = raw.identity == null ? null : raw.identity as IdentityTimeline;
  if (identity && (identity.state !== "confirmed" && identity.state !== "uncertain" && identity.state !== "lost")) throw new Error("invalid identity state");
  const pose = raw.pose == null ? null : decodePoseAvailability(raw.pose);
  return { schemaVersion: "analysis-experience.v2", analysisId: String(raw.analysis_id), authority: raw.authority as ExperienceAuthority, pipelineMode: raw.pipeline_mode as PipelineMode, sourcePipelineFingerprint: String(raw.source_pipeline_fingerprint), diagnosticOnly: Boolean(raw.diagnostic_only), familyUsable: raw.family_usable !== false, events, claims, reviewTasks, sourceTimeline: decodeSourceTimeline(raw.source_timeline), identity, pose };
}

function decodePoseAvailability(value: unknown): PoseAvailabilitySummary {
  const raw = record(value);
  const status = raw.status;
  if (raw.schema_version !== "pose-availability-summary.v1" || status !== "available" && status !== "partial" && status !== "unavailable" && status !== "blocked" || typeof raw.frame_count !== "number" || typeof raw.authoritative_frame_count !== "number" || !record(raw.usable_joint_mask) || !record(raw.per_phase_quality)) throw new Error("invalid pose availability summary");
  return {
    schema_version: "pose-availability-summary.v1",
    status,
    frame_count: raw.frame_count,
    authoritative_frame_count: raw.authoritative_frame_count,
    measured_joint_count: Number(raw.measured_joint_count ?? 0),
    smoothed_joint_count: Number(raw.smoothed_joint_count ?? 0),
    interpolated_display_only_count: Number(raw.interpolated_display_only_count ?? 0),
    missing_joint_count: Number(raw.missing_joint_count ?? 0),
    identity_blocked_frame_count: Number(raw.identity_blocked_frame_count ?? 0),
    clipped_joint_count: Number(raw.clipped_joint_count ?? 0),
    usable_joint_mask: raw.usable_joint_mask as Record<string, boolean>,
    per_phase_quality: raw.per_phase_quality as Record<string, number | null>,
    left_right_assignment_uncertainty: typeof raw.left_right_assignment_uncertainty === "number" ? raw.left_right_assignment_uncertainty : null,
    source_method: String(raw.source_method ?? "unknown"),
    model_fingerprint: typeof raw.model_fingerprint === "string" ? raw.model_fingerprint : null,
  };
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
