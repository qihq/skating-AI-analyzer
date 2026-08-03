import axios from "axios";

import { apiClient } from "../api/client";
import { AdvancedRuntimeCapabilities, AnalysisExperienceV2, decodeAnalysisExperienceV2, decodeRuntimeCapabilities, DetectionProposalDiagnostics, IdentityRevisionPreview, IdentityTimeline, RuntimeCapabilities } from "./contracts";

export type EventProposal = { event_id: string; source_video_hash: string; start_pts: number; end_pts: number; anchor_start_frame: number; anchor_end_frame: number; candidate_profile_scores: Record<string, number>; proposed_profile: "unknown"; status: "pending_confirmation" | "confirmed_window" | "ignored" | "ordinary_skating" | "unknown"; tracking_coverage: number; pose_coverage: number; observability: "observable" | "partially_observable" | "unobservable"; evidence_sources: string[]; provenance_fingerprint: string; revision: number; parent_event_ids: string[]; superseded_event_ids: string[] };
export type EventProposalCollection = { schema_version: "event-proposal-collection.v1"; source_video_hash: string; source_duration_sec: number; pipeline_fingerprint: string; proposals: EventProposal[]; diagnostic_only: boolean; classifier_labels_consumed: false; revision: number };
import { GoldenCatalogSummary, GoldenG2Status, GoldenReviewItem, GoldenSanitizedExport, GoldenSchemaInfo, GoldenWorkspace, PilotEvaluatorStatus, PilotProgress, PilotSanitizedResult } from "./golden-contracts";

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

export async function fetchAdvancedRuntimeCapabilities(parentPin: string): Promise<AdvancedRuntimeCapabilities> {
  const response = await apiClient.get<AdvancedRuntimeCapabilities>("/capabilities/advanced", {
    headers: { "X-Parent-Pin": parentPin }, timeout: 10_000,
  });
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

export async function attestGoldenReview(parentPin: string, eventId: string, payload: { reviewer_alias: string; review_type: "delayed_relabel" | "ambiguous_rotation" | "frozen_identity_crossing"; note?: string | null }): Promise<void> {
  await apiClient.post(`/golden/v2/events/${encodeURIComponent(eventId)}/review-attestations`, payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
}
