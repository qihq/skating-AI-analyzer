import axios from "axios";

import { apiClient } from "../api/client";
import { AdvancedRuntimeCapabilities, AnalysisExperienceV2, decodeAnalysisExperienceV2, decodeRuntimeCapabilities, DetectionProposalDiagnostics, EventMomentSetV2, IdentityRevisionPreview, IdentityTimeline, RuntimeCapabilities } from "./contracts";

export type EventProposal = { event_id: string; source_video_hash: string; start_pts: number; end_pts: number; anchor_start_frame: number; anchor_end_frame: number; candidate_profile_scores: Record<string, number>; proposed_profile: "unknown"; status: "pending_confirmation" | "confirmed_window" | "ignored" | "ordinary_skating" | "unknown"; tracking_coverage: number; pose_coverage: number; observability: "observable" | "partially_observable" | "unobservable"; evidence_sources: string[]; provenance_fingerprint: string; revision: number; parent_event_ids: string[]; superseded_event_ids: string[] };
export type EventProposalCollection = { schema_version: "event-proposal-collection.v1"; source_video_hash: string; source_duration_sec: number; pipeline_fingerprint: string; proposals: EventProposal[]; diagnostic_only: boolean; classifier_labels_consumed: false; revision: number };
export type EventLabelFactRevision = { schema_version: "event-label-fact.v1"; analysis_id: string; event_id: string; revision: number; parent_revision: number | null; profile: "jump" | "spin" | "step" | "spiral" | null; subtype: string | null; state: "confirmed" | "ambiguous" | "unknown"; status: "proposed" | "applied" | "dismissed"; value: Record<string, unknown>; legacy_snapshot: Record<string, unknown>; human_provenance: Record<string, unknown>; created_at: string };
export type GrowthAdmissionReport = { schema_version: "growth-profile-admission.v1"; included_count: number; excluded_count: number; excluded_reasons: Record<string, number>; diagnostic_only: true };
export type EventMomentProposalRevision = { schema_version: "event-moment-proposal.v1"; analysis_id: string; event_id: string; revision: number; parent_revision: number | null; status: "proposed" | "applied" | "dismissed"; source: "manual" | "legacy_keyframe_correction" | "video_keyframe_rerun"; before: Record<string, unknown> | null; after: Record<string, unknown>; legacy_snapshot: Record<string, unknown>; human_provenance: Record<string, unknown>; invalidates: string[]; report_regeneration_required: boolean; created_at: string };
import { GoldenCatalogSummary, GoldenG2Status, GoldenReviewItem, GoldenSanitizedExport, GoldenSchemaInfo, GoldenWorkspace, PilotEvaluatorStatus, PilotProgress, PilotSanitizedResult } from "./golden-contracts";
import type { ShadowArtifactReference, ShadowArtifactResponse, ShadowCapabilitiesResponse, ShadowCleanupResponse, ShadowDecisionResponse, ShadowDiffResponse, ShadowRecoveryResponse, ShadowReviewDecision, ShadowRunListResponse, ShadowRunRequest, ShadowRunResponse, ShadowStage, ShadowStatusResponse } from "./shadow-contracts";

export async function fetchRuntimeCapabilities(): Promise<RuntimeCapabilities> {
  const response = await apiClient.get<unknown>("/capabilities", { timeout: 10_000 });
  return decodeRuntimeCapabilities(response.data);
}

export async function fetchAnalysisExperienceV2(analysisId: string): Promise<AnalysisExperienceV2> {
  const response = await apiClient.get<unknown>(`/analysis/${encodeURIComponent(analysisId)}/experience-v2`, { timeout: 10_000 });
  return decodeAnalysisExperienceV2(response.data);
}

export async function fetchAnalysisExperienceV2Diagnostic(parentPin: string, analysisId: string): Promise<AnalysisExperienceV2> {
  const response = await apiClient.get<unknown>(`/analysis/${encodeURIComponent(analysisId)}/experience-v2/diagnostic`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return decodeAnalysisExperienceV2(response.data);
}

export async function fetchEventProposals(parentPin: string, analysisId: string): Promise<EventProposalCollection> {
  const response = await apiClient.get<EventProposalCollection>(`/analysis/${encodeURIComponent(analysisId)}/event-proposals`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function mutateEventProposals(parentPin: string, analysisId: string, payload: { operation: "merge" | "split" | "ignore" | "ordinary_skating" | "unknown" | "confirm"; event_id?: string; event_ids?: string[]; split_pts?: number; expected_revision: number; scope: "event" | "analysis"; confirmation: "confirm_event_proposal_revision" }): Promise<EventProposalCollection> {
  const response = await apiClient.post<EventProposalCollection>(`/analysis/${encodeURIComponent(analysisId)}/event-proposals/mutate`, payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchEventLabelFacts(parentPin: string, analysisId: string, eventId: string): Promise<EventLabelFactRevision[]> {
  const response = await apiClient.get<EventLabelFactRevision[]>(`/analysis/${encodeURIComponent(analysisId)}/events/${encodeURIComponent(eventId)}/label-facts`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function proposeEventLabelFact(parentPin: string, analysisId: string, eventId: string, payload: { profile: "jump" | "spin" | "step" | "spiral" | null; subtype?: string | null; state: "confirmed" | "ambiguous" | "unknown"; reviewer: string; expected_revision: number; confirmation: "propose_event_label_fact" }): Promise<EventLabelFactRevision> {
  const response = await apiClient.post<EventLabelFactRevision>(`/analysis/${encodeURIComponent(analysisId)}/events/${encodeURIComponent(eventId)}/label-facts`, payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function applyEventLabelFact(parentPin: string, analysisId: string, eventId: string, revision: number): Promise<EventLabelFactRevision> {
  const response = await apiClient.post<EventLabelFactRevision>(`/analysis/${encodeURIComponent(analysisId)}/events/${encodeURIComponent(eventId)}/label-facts/${revision}/apply`, null, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function dismissEventLabelFact(parentPin: string, analysisId: string, eventId: string, revision: number): Promise<EventLabelFactRevision> {
  const response = await apiClient.post<EventLabelFactRevision>(`/analysis/${encodeURIComponent(analysisId)}/events/${encodeURIComponent(eventId)}/label-facts/${revision}/dismiss`, null, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGrowthAdmission(parentPin: string, analysisIds: string[]): Promise<GrowthAdmissionReport> {
  const response = await apiClient.post<GrowthAdmissionReport>("/analysis/growth-admission", { analysis_ids: analysisIds }, { headers: { "X-Parent-Pin": parentPin }, timeout: 60_000 });
  return response.data;
}

export async function fetchEventMomentProposals(parentPin: string, analysisId: string, eventId: string): Promise<EventMomentProposalRevision[]> {
  const response = await apiClient.get<EventMomentProposalRevision[]>(`/analysis/${encodeURIComponent(analysisId)}/events/${encodeURIComponent(eventId)}/moment-proposals`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function proposeEventMoments(parentPin: string, analysisId: string, eventId: string, after: EventMomentSetV2, reviewer: string, expectedRevision: number): Promise<EventMomentProposalRevision> {
  const payload = {
    after: {
      schema_version: after.schemaVersion, event_id: after.eventId, profile: after.profile, definition_version: after.definitionVersion,
      moments: after.moments.map((item) => ({ schema_version: "key-moment.v2", event_id: after.eventId, semantic_key: item.semanticKey, kind: item.kind, status: item.status, source_frame_index: item.sourceFrameIndex, pts_sec: item.ptsSec, end_source_frame_index: item.endSourceFrameIndex, end_pts_sec: item.endPtsSec, definition_version: item.definitionVersion, candidate_evidence: item.candidateEvidence, confidence: item.confidence, warnings: item.warnings, observability: item.observability, provenance: item.provenance, competing_candidates: item.competingCandidates.map((candidate) => ({ schema_version: "moment-candidate.v1", source_frame_index: candidate.sourceFrameIndex, pts_sec: candidate.ptsSec, end_source_frame_index: candidate.endSourceFrameIndex, end_pts_sec: candidate.endPtsSec, score: candidate.score, observability: candidate.observability, evidence: candidate.evidence, provenance: candidate.provenance, warnings: candidate.warnings })), review_resolvable: item.reviewResolvable })),
      expected_keys: after.expectedKeys, required_keys: after.requiredKeys, present_keys: after.presentKeys, missing_keys: after.missingKeys, completeness: after.completeness, warnings: after.warnings, source_timeline_fingerprint: after.sourceTimelineFingerprint, state_machine_fingerprint: after.stateMachineFingerprint, semantic_labels_consumed: false, revision: after.revision,
    }, reviewer, expected_revision: expectedRevision, confirmation: "propose_event_moments",
  };
  const response = await apiClient.post<EventMomentProposalRevision>(`/analysis/${encodeURIComponent(analysisId)}/events/${encodeURIComponent(eventId)}/moment-proposals`, payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function applyEventMomentProposal(parentPin: string, analysisId: string, eventId: string, revision: number): Promise<EventMomentProposalRevision> {
  const response = await apiClient.post<EventMomentProposalRevision>(`/analysis/${encodeURIComponent(analysisId)}/events/${encodeURIComponent(eventId)}/moment-proposals/${revision}/apply`, null, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function dismissEventMomentProposal(parentPin: string, analysisId: string, eventId: string, revision: number): Promise<EventMomentProposalRevision> {
  const response = await apiClient.post<EventMomentProposalRevision>(`/analysis/${encodeURIComponent(analysisId)}/events/${encodeURIComponent(eventId)}/moment-proposals/${revision}/dismiss`, null, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchAnalysisSourceFrameImage(parentPin: string, analysisId: string, sourceFrameIndex: number): Promise<string> {
  const response = await apiClient.get<Blob>(`/analysis/${encodeURIComponent(analysisId)}/source-frames/${sourceFrameIndex}/image`, { headers: { "X-Parent-Pin": parentPin }, responseType: "blob", timeout: 60_000 });
  return URL.createObjectURL(response.data);
}

export async function fetchAdvancedRuntimeCapabilities(parentPin: string): Promise<AdvancedRuntimeCapabilities> {
  const response = await apiClient.get<AdvancedRuntimeCapabilities>("/capabilities/advanced", {
    headers: { "X-Parent-Pin": parentPin }, timeout: 10_000,
  });
  return response.data;
}

function shadowHeaders(parentPin: string) { return { headers: { "X-Parent-Pin": parentPin }, timeout: 15_000 }; }

export async function fetchShadowCapabilities(parentPin: string): Promise<ShadowCapabilitiesResponse> {
  const response = await apiClient.get<ShadowCapabilitiesResponse>("/shadow/capabilities", shadowHeaders(parentPin));
  return response.data;
}

export async function createShadowRun(parentPin: string, payload: ShadowRunRequest): Promise<ShadowRunResponse> {
  const response = await apiClient.post<ShadowRunResponse>("/shadow/runs", payload, shadowHeaders(parentPin));
  return response.data;
}

export async function fetchShadowRuns(parentPin: string, analysisId: string): Promise<ShadowRunListResponse> {
  const response = await apiClient.get<ShadowRunListResponse>(`/shadow/analyses/${encodeURIComponent(analysisId)}/runs`, shadowHeaders(parentPin));
  return response.data;
}

export async function fetchShadowStatus(parentPin: string, runId: string): Promise<ShadowStatusResponse> {
  const response = await apiClient.get<ShadowStatusResponse>(`/shadow/runs/${encodeURIComponent(runId)}/status`, shadowHeaders(parentPin));
  return response.data;
}

export async function fetchShadowDiff(parentPin: string, runId: string): Promise<ShadowDiffResponse> {
  const response = await apiClient.get<ShadowDiffResponse>(`/shadow/runs/${encodeURIComponent(runId)}/diff`, shadowHeaders(parentPin));
  return response.data;
}

export async function fetchShadowArtifact(parentPin: string, runId: string, artifactId: string): Promise<ShadowArtifactResponse> {
  const response = await apiClient.get<ShadowArtifactResponse>(`/shadow/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`, shadowHeaders(parentPin));
  return response.data;
}

export async function retryShadowRun(parentPin: string, runId: string, payload: { stage?: ShadowStage | null; reason?: string | null; confirmation: "confirm_shadow_retry" }): Promise<ShadowRunResponse> {
  const response = await apiClient.post<ShadowRunResponse>(`/shadow/runs/${encodeURIComponent(runId)}/retry`, payload, shadowHeaders(parentPin));
  return response.data;
}

export async function recoverShadowRun(parentPin: string, runId: string): Promise<ShadowRecoveryResponse> {
  const response = await apiClient.post<ShadowRecoveryResponse>(`/shadow/runs/${encodeURIComponent(runId)}/recover`, {}, shadowHeaders(parentPin));
  return response.data;
}

export async function cleanupShadowRun(parentPin: string, runId: string): Promise<ShadowCleanupResponse> {
  const response = await apiClient.post<ShadowCleanupResponse>(`/shadow/runs/${encodeURIComponent(runId)}/cleanup`, {}, shadowHeaders(parentPin));
  return response.data;
}

export async function updateShadowFingerprints(parentPin: string, runId: string, payload: {
  source_fingerprint?: string | null;
  model_fingerprint?: string | null;
  config_fingerprint?: string | null;
  prompt_fingerprint?: string | null;
  contract_fingerprint?: string | null;
  requested_by?: string;
  confirmation: "confirm_shadow_fingerprint_update";
}): Promise<ShadowRunResponse> {
  const response = await apiClient.post<ShadowRunResponse>(`/shadow/runs/${encodeURIComponent(runId)}/fingerprints`, payload, shadowHeaders(parentPin));
  return response.data;
}

export async function fetchShadowArtifacts(parentPin: string, runId: string): Promise<ShadowArtifactReference[]> {
  const response = await apiClient.get<ShadowArtifactReference[]>(`/shadow/runs/${encodeURIComponent(runId)}/artifacts`, shadowHeaders(parentPin));
  return response.data;
}

export async function fetchShadowReviewDecisions(parentPin: string, runId: string): Promise<ShadowReviewDecision[]> {
  const response = await apiClient.get<ShadowReviewDecision[]>(`/shadow/runs/${encodeURIComponent(runId)}/review-decisions`, shadowHeaders(parentPin));
  return response.data;
}

export async function submitShadowReviewDecision(parentPin: string, runId: string, payload: { stage: ShadowStage; decision: "accept_shadow" | "reject_shadow" | "defer" | "promote_candidate"; reviewer: string; note?: string | null; confirmation: "confirm_shadow_review_decision"; promotion_scope?: "shadow_only" }): Promise<ShadowDecisionResponse> {
  const response = await apiClient.post<ShadowDecisionResponse>(`/shadow/runs/${encodeURIComponent(runId)}/review-decisions`, payload, shadowHeaders(parentPin));
  return response.data;
}

export async function addShadowNote(parentPin: string, runId: string, note: string, author = "parent") {
  const response = await apiClient.post<{ schema_version: "shadow-orchestration.v1"; run_id: string; notes: Array<{ author: string; note: string; created_at: string }> }>(`/shadow/runs/${encodeURIComponent(runId)}/notes`, { note, author }, shadowHeaders(parentPin));
  return response.data;
}

export async function fetchDetectionObservations(parentPin: string, analysisId: string): Promise<DetectionProposalDiagnostics> {
  const response = await apiClient.get<DetectionProposalDiagnostics>(`/analysis/${encodeURIComponent(analysisId)}/observations`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchIdentityTimeline(parentPin: string, analysisId: string): Promise<IdentityTimeline | null> {
  const response = await apiClient.get<IdentityTimeline | null>(`/analysis/${encodeURIComponent(analysisId)}/identity`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function previewIdentityAnchorRevision(parentPin: string, analysisId: string, payload: { source_frame_index: number; pts_sec: number; bbox: [number, number, number, number]; annotator: string; quality_score: number; expected_revision: number; invalidated_interval?: [number, number] | null }): Promise<IdentityRevisionPreview> {
  const response = await apiClient.post<IdentityRevisionPreview>(`/analysis/${encodeURIComponent(analysisId)}/identity/anchors/preview`, payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function confirmIdentityAnchorRevision(parentPin: string, analysisId: string, payload: { source_frame_index: number; pts_sec: number; bbox: [number, number, number, number]; annotator: string; quality_score: number; expected_revision: number; preview_revision: number; confirmation: "confirm_identity_anchor_revision"; invalidated_interval?: [number, number] | null }): Promise<IdentityRevisionPreview> {
  const response = await apiClient.post<IdentityRevisionPreview>(`/analysis/${encodeURIComponent(analysisId)}/identity/anchors/confirm`, payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchPilot12DetectionDiagnostics(parentPin: string): Promise<Record<string, unknown>> {
  const response = await apiClient.get<Record<string, unknown>>("/analysis/pilot12-detection", { headers: { "X-Parent-Pin": parentPin }, timeout: 60_000 });
  return response.data;
}

export async function fetchGoldenCatalog(parentPin: string): Promise<GoldenCatalogSummary> {
  const response = await apiClient.get<GoldenCatalogSummary>("/golden/v2/catalog", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenSchema(parentPin: string): Promise<GoldenSchemaInfo> {
  const response = await apiClient.get<GoldenSchemaInfo>("/golden/v2/schema", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenSanitizedExport(parentPin: string): Promise<GoldenSanitizedExport> {
  const response = await apiClient.get<GoldenSanitizedExport>("/golden/v2/sanitized-export", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenG2Status(parentPin: string): Promise<GoldenG2Status> {
  const response = await apiClient.get<GoldenG2Status>("/golden/v2/g2/status", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenWorkspace(parentPin: string): Promise<GoldenWorkspace> {
  const response = await apiClient.get<GoldenWorkspace>("/golden/v2/workspace", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenReviewQueue(parentPin: string): Promise<GoldenReviewItem[]> {
  const response = await apiClient.get<GoldenReviewItem[]>("/golden/v2/review-queue", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenSourceFrame(parentPin: string, sourceHash: string, frameIndex: number) {
  const response = await apiClient.get<{ source_frame_index: number; pts: number; duration: number | null }>(`/golden/v2/sources/${sourceHash}/frames/${frameIndex}`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return { sourceFrameIndex: response.data.source_frame_index, pts: response.data.pts, duration: response.data.duration };
}

export async function fetchGoldenSourceFrameByPts(parentPin: string, sourceHash: string, pts: number) {
  const response = await apiClient.get<{ source_frame_index: number; pts: number; duration: number | null }>(`/golden/v2/sources/${encodeURIComponent(sourceHash)}/frames/by-pts`, { params: { pts }, headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return { sourceFrameIndex: response.data.source_frame_index, pts: response.data.pts, duration: response.data.duration };
}

export async function fetchGoldenSourceFrameImageUrl(parentPin: string, sourceHash: string, frameIndex: number): Promise<string> {
  const response = await apiClient.get<Blob>(`/golden/v2/sources/${encodeURIComponent(sourceHash)}/frames/${frameIndex}/image`, { headers: { "X-Parent-Pin": parentPin }, responseType: "blob", timeout: 60_000 });
  return URL.createObjectURL(response.data);
}

export async function fetchGoldenSourceMediaUrl(parentPin: string, sourceHash: string): Promise<string> {
  const response = await apiClient.get<Blob>(`/golden/v2/sources/${sourceHash}/media`, {
    headers: { "X-Parent-Pin": parentPin }, responseType: "blob", timeout: 600_000,
  });
  return URL.createObjectURL(response.data);
}

export async function saveGoldenAnnotations(parentPin: string, payload: { expected_revision: number; annotator_alias: string; change_note?: string | null; events: unknown[]; tracks: unknown[]; poses: unknown[] }): Promise<GoldenWorkspace> {
  const response = await apiClient.put<GoldenWorkspace>("/golden/v2/annotations", payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function importGoldenSource(parentPin: string, form: FormData): Promise<GoldenWorkspace["sources"][number]> {
  const response = await apiClient.post<GoldenWorkspace["sources"][number]>("/golden/v2/sources/import", form, { headers: { "X-Parent-Pin": parentPin }, timeout: 60_000 });
  return response.data;
}

export async function updateGoldenSource(parentPin: string, sourceHash: string, payload: { expected_revision: number; annotator_alias: string; recording_session_id: string; grouping_id: string; redacted_alias: string }): Promise<GoldenWorkspace> {
  const response = await apiClient.patch<GoldenWorkspace>(`/golden/v2/sources/${encodeURIComponent(sourceHash)}`, payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function deleteGoldenSource(parentPin: string, sourceHash: string, payload: { expected_revision: number; annotator_alias: string; confirmation: "delete_source_and_labels" }): Promise<GoldenWorkspace> {
  const response = await apiClient.delete<GoldenWorkspace>(`/golden/v2/sources/${encodeURIComponent(sourceHash)}`, { headers: { "X-Parent-Pin": parentPin }, data: payload, timeout: 10_000 });
  return response.data;
}

export async function fetchPilotProgress(parentPin: string): Promise<PilotProgress> {
  const response = await apiClient.get<PilotProgress>("/golden/v2/evaluator/progress", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchPilotEvaluatorStatus(parentPin: string): Promise<PilotEvaluatorStatus> {
  const response = await apiClient.get<PilotEvaluatorStatus>("/golden/v2/evaluator/status", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchPilotEvaluatorResult(parentPin: string): Promise<PilotSanitizedResult | null> {
  try {
    const response = await apiClient.get<PilotSanitizedResult>("/golden/v2/evaluator/result", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) return null;
    throw error;
  }
}

export async function fetchPilotEventDiagnostic(parentPin: string, alias: string): Promise<Record<string, unknown>> {
  const response = await apiClient.get<Record<string, unknown>>(`/golden/v2/evaluator/events/${encodeURIComponent(alias)}`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function attestGoldenReview(parentPin: string, eventId: string, payload: { reviewer_alias: string; review_type: "delayed_relabel" | "ambiguous_rotation" | "frozen_identity_crossing"; note?: string | null; rotation_definition?: "airborne_body_rotation" | "competition_naming" | "observed_spin_rotation" | null; review_start_pts?: number | null; review_end_pts?: number | null; review_method?: "source_frame_step" }): Promise<void> {
  await apiClient.post(`/golden/v2/events/${encodeURIComponent(eventId)}/review-attestations`, payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
}
