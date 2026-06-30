import axios from "axios";

export type AnalysisStatus =
  | "pending"
  | "processing"
  | "extracting_frames"
  | "awaiting_target_selection"
  | "analyzing"
  | "generating_report"
  | "completed"
  | "failed";
export type IssueSeverity = "high" | "medium" | "low";
export type AvatarType = "zodiac_rat" | "zodiac_tiger" | "emoji";
export type MemoryExpiryPreset = "1m" | "3m" | "never";
export type AnalysisErrorCode =
  | "VIDEO_DECODE_FAILED"
  | "FRAME_EXTRACT_FAILED"
  | "AI_API_TIMEOUT"
  | "AI_API_AUTH_ERROR"
  | "AI_API_QUOTA_EXCEEDED"
  | "AI_API_CONTENT_FILTER"
  | "AI_RESPONSE_PARSE_FAIL"
  | "REPORT_SAVE_FAILED"
  | "TARGET_BBOX_INVALID"
  | "UNKNOWN_ERROR";

export interface ReportIssue {
  category: string;
  description: string;
  severity: IssueSeverity;
  phase?: string | null;
  frames?: string[];
}

export interface ReportImprovement {
  target: string;
  action: string;
}

export interface StructuredReport {
  summary: string;
  issues: ReportIssue[];
  improvements: ReportImprovement[];
  training_focus: string;
  subscores?: Record<string, number>;
  data_quality?: "good" | "partial" | "poor" | string;
  user_note?: string | null;
  user_note_response?: string | null;
  action_confirmation?: {
    action_family?: string | null;
    confirmed_action?: string | null;
    jump_type?: string | null;
    confidence?: number | null;
    notes?: string | null;
    [key: string]: unknown;
  } | null;
}

export interface BioData {
  key_frames?: {
    T?: string;
    A?: string;
    L?: string;
  };
  jump_metrics?: {
    air_time_seconds?: number | null;
    estimated_height_cm?: number | null;
    takeoff_speed_mps?: number | null;
    rotation_rps?: number | null;
  };
  jump_metrics_status?: "ok" | "invalid" | string;
  jump_metrics_warning?: string | null;
  bio_subscores?: Record<string, number>;
  [key: string]: unknown;
}

export interface FusionDiagnostics {
  conflict_level?: "none" | "low" | "medium" | "high" | string;
  downgraded_reasons?: string[];
  needs_human_review?: boolean;
  key_frame_order_invalid?: boolean;
  weighted_fusion?: {
    available?: boolean;
    fusion_version?: string | null;
    conflict_level?: "none" | "low" | "medium" | "high" | string;
    downgraded_reasons?: string[];
  };
  path_a?: Record<string, unknown>;
  path_b?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface CrossValidationData {
  fusion_diagnostics?: FusionDiagnostics;
  conflict_level?: "none" | "low" | "medium" | "high" | string;
  downgraded_reasons?: string[];
  needs_human_review?: boolean;
  auto_eval?: {
    key_frame_order_valid?: boolean | null;
    phase_sequence_valid?: boolean | null;
    data_quality_flags?: string[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface VisionStructuredData {
  data_quality_hint?: "good" | "partial" | "poor" | string;
  fusion_version?: string;
  conflict_level?: "none" | "low" | "medium" | "high" | string;
  quality_flags?: string[];
  [key: string]: unknown;
}

export interface PoseKeypoint {
  id: number;
  name: string;
  x: number;
  y: number;
  z: number;
  visibility: number;
  interpolated?: boolean;
}

export interface PoseFrame {
  frame: string;
  keypoints: PoseKeypoint[];
  target_bbox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  } | null;
  tracking_confidence?: number | null;
  tracking_state?: string | null;
  pose_candidates?: Record<string, unknown>[];
}

export interface PoseResponse {
  connections: number[][];
  frames: PoseFrame[];
  frame_urls: Record<string, string>;
  pose_diagnostics?: Record<string, unknown> | null;
}

export interface AnalysisListItem {
  id: string;
  skater_id: string | null;
  session_id: string | null;
  skater_name: string | null;
  skill_category: string | null;
  action_type: string;
  action_subtype: string | null;
  analysis_profile: string | null;
  pipeline_version: string | null;
  status: AnalysisStatus;
  force_score: number | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnalysisDetail extends AnalysisListItem {
  video_path: string;
  vision_raw: string | null;
  vision_structured: VisionStructuredData | null;
  vision_path_a: Record<string, unknown> | null;
  vision_path_b: Record<string, unknown> | null;
  cross_validation: CrossValidationData | null;
  report: StructuredReport | null;
  pose_data: PoseResponse | null;
  bio_data: BioData | null;
  frame_motion_scores: Record<string, unknown> | null;
  video_temporal_diagnostics: VideoTemporalDiagnostics | null;
  pipeline_version: string | null;
  retry_from_stage: string | null;
  processing_timings: Record<string, number> | null;
  processing_logs: AnalysisLogEntry[];
  target_lock: Record<string, unknown> | null;
  target_lock_status: string | null;
  action_window_start: number | null;
  action_window_end: number | null;
  manual_action_window_start: number | null;
  manual_action_window_end: number | null;
  source_duration_sec: number | null;
  input_window_start_sec: number | null;
  input_window_end_sec: number | null;
  input_window_duration_sec: number | null;
  input_window_mode: string | null;
  input_window_truncated: boolean;
  input_window_reason: string | null;
  source_fps: number | null;
  is_slow_motion: boolean;
  skill_node_id: string | null;
  auto_unlocked_skill: string | null;
  error_code: AnalysisErrorCode | null;
  error_detail: string | null;
  error_message: string | null;
}

export interface AnalysisChatMessage {
  id: string;
  analysis_id: string;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
  provider_id?: string | null;
  provider_name?: string | null;
  model_id?: string | null;
}

export interface AnalysisChatResponse {
  message: AnalysisChatMessage;
  messages: AnalysisChatMessage[];
  suggested_action?: {
    kind: "full_video_reanalysis" | string;
    label: string;
    reset_target_lock?: boolean;
    [key: string]: unknown;
  } | null;
}

export interface AnalysisCorrection {
  id: string;
  analysis_id: string;
  kind: "action_label" | "keyframes" | "report_note" | "report_regeneration" | "target_lock" | string;
  payload: Record<string, unknown>;
  rationale: string | null;
  source: "manual" | "chat_suggestion" | string;
  status: "proposed" | "applied" | "dismissed" | string;
  original_snapshot: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  applied_at: string | null;
}

export interface AnalysisCorrectionListResponse {
  corrections: AnalysisCorrection[];
  effective: Record<string, unknown>;
}

export interface AnalysisCorrectionMutationResponse extends AnalysisCorrectionListResponse {
  correction: AnalysisCorrection;
}

export interface AnalysisCorrectionCreatePayload {
  kind: string;
  payload: Record<string, unknown>;
  rationale?: string | null;
  source?: string;
  status?: string;
}

export interface AnalysisChatShareResponse {
  title: string;
  text: string;
  image_payload: {
    analysis_id?: string;
    title?: string;
    score?: number | null;
    summary?: string;
    question?: string;
    answer?: string;
    applied_corrections?: string[];
    pending_corrections?: string[];
    report_url?: string;
    [key: string]: unknown;
  };
}

export interface SelectedSemanticFrame {
  frame_id?: string | null;
  timestamp?: number | null;
  phase_code?: string | null;
  phase_label?: string | null;
  key_moment?: string | null;
  selection_reason?: string | null;
  selection_status?: string | null;
  partial_semantic_frame?: boolean | null;
  pre_refine_timestamp?: number | null;
  refinement_method?: string | null;
  refinement_delta_sec?: number | null;
}

export interface VideoTemporalDiagnostics {
  video_ai_model?: string | null;
  video_ai_provider?: string | null;
  video_ai_confidence?: number | null;
  video_ai_ran?: boolean;
  video_ai_video_url?: string | null;
  raw_response_excerpt?: string | null;
  raw_response_length?: number | null;
  raw_response_truncated?: boolean | null;
  parse_error_detail?: string | null;
  timestamp_source?: string | null;
  resolver_source?: string | null;
  resolved_confidence?: number | null;
  selected_semantic_frames?: SelectedSemanticFrame[];
  partial_semantic_frames?: SelectedSemanticFrame[];
  fallback_reason?: string | null;
  quality_flags?: string[];
  retry_rejection_flags?: string[];
  used_semantic_frames?: boolean;
  used_legacy_sampled_frames?: boolean;
}

export interface AnalysisLogEntry {
  timestamp: string;
  stage: string;
  level: string;
  message: string;
  elapsed_s?: number | null;
  retry_from_stage?: string | null;
  error_code?: string | null;
  detail?: string | null;
}

export interface UploadResponse {
  id: string;
  status: AnalysisStatus;
}

export interface TargetCandidate {
  id: string;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  confidence: number;
  source: string;
}

export interface TargetBBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TargetPreviewResponse {
  analysis_id: string;
  status: AnalysisStatus | string;
  auto_candidate_id: string | null;
  lock_confidence: number;
  preview_frame: string | null;
  preview_frame_index: number | null;
  preview_frame_url: string | null;
  candidates: TargetCandidate[];
  target_lock_status: string | null;
}

export interface UploadProgress {
  loaded: number;
  total: number;
  percent: number;
}

export interface RetryAnalysisResponse {
  message: string;
}

export interface AnalysisExportResponse {
  text: string;
}

export interface Skater {
  id: string;
  name: string;
  display_name: string;
  avatar_emoji: string;
  avatar_type: AvatarType;
  birth_year: number;
  current_level: string;
  avatar_level: number;
  total_xp: number;
  current_streak: number;
  longest_streak: number;
  last_active_date: string | null;
  is_default: boolean;
  level: string | null;
  notes: string | null;
  created_at: string;
}

export type SkillStatus = "locked" | "attempting" | "in_progress" | "unlocked";

export interface SkillNode {
  id: string;
  chapter: string;
  chapter_order: number;
  stage: number;
  stage_name: string;
  group_name: string;
  name: string;
  emoji: string;
  action_type: string | null;
  xp: number;
  requires: string[];
  status: SkillStatus;
  attempt_count: number;
  best_score: number;
  unlocked_by: string | null;
  unlock_config: Record<string, unknown> | null;
  is_parent_only: boolean;
  unlocked_at: string | null;
  unlock_source: string | null;
  unlock_note: string | null;
  last_analysis_score: number | null;
}

export interface SkillMutationResponse {
  success: boolean;
  skill: SkillNode;
}

export interface LearningPathGroup {
  group_name: string;
  nodes_total: number;
  nodes_unlocked: number;
  nodes: SkillNode[];
}

export interface LearningPathStage {
  stage: number;
  name: string;
  description: string;
  progress_pct: number;
  counts: Record<string, number>;
  groups: LearningPathGroup[];
}

export interface LearningPathResponse {
  stages: LearningPathStage[];
  current_stage: number;
}

export interface SystemInfo {
  version: string;
  db_size_bytes: number;
  uploads_size_bytes: number;
}

export interface StorageStats {
  uploads_mb: number;
  archive_mb: number;
  backups_mb: number;
  total_mb: number;
  archived_count: number;
}

export interface ProviderPublic {
  id: string;
  slot: string;
  name: string;
  provider: string;
  base_url: string;
  model_id: string;
  vision_model: string | null;
  api_key: string;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderUpdatePayload {
  name?: string;
  provider?: string;
  base_url?: string;
  model_id?: string;
  vision_model?: string | null;
  api_key?: string;
  notes?: string | null;
}

export interface ProviderCreatePayload {
  slot: string;
  name: string;
  provider: string;
  base_url: string;
  model_id: string;
  vision_model?: string | null;
  api_key: string;
  notes?: string | null;
}

export interface VisionVoteConfig {
  primary_provider_id: string | null;
  secondary_provider_id: string | null;
}

export interface ProviderMetricPublic {
  provider: string;
  sample_count: number;
  json_valid_rate: number;
  avg_effective_weight: number;
  conflict_rate: number;
  failure_rate: number;
  recommendation: string | null;
}

export interface AutoEvalSnapshotSummary {
  analysis_id: string;
  created_at: string;
  pipeline_version: string | null;
  analysis_profile: string | null;
  action_type: string;
  auto_eval: {
    key_frame_order_valid?: boolean | null;
    phase_sequence_valid?: boolean | null;
    high_confidence_conflicts?: number | null;
    data_quality_flags?: string[] | null;
    [key: string]: unknown;
  } | null;
  key_frame_candidates: Record<string, unknown> | null;
  fusion_diagnostics: string[];
}

export type DebugRunMode = "local_pose_keyframes" | "video_ai_keyframes";
export type DebugRunStatus = "pending" | "processing" | "awaiting_target_selection" | "completed" | "failed";
export type DebugRunSourceType = "analysis" | "upload";

export interface DebugRunSummary {
  id: string;
  mode: DebugRunMode | string;
  source_type: DebugRunSourceType | string;
  analysis_id: string | null;
  action_type: string;
  action_subtype: string | null;
  analysis_profile: string | null;
  note: string | null;
  status: DebugRunStatus | string;
  summary: Record<string, unknown> | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface DebugRunDetail extends DebugRunSummary {
  video_path: string | null;
  result_json: Record<string, unknown> | null;
  error_detail: string | null;
}

export interface DebugRunCreateResponse {
  id: string;
  status: DebugRunStatus | string;
}

export interface DebugRunCreatePayload {
  analysisId?: string | null;
  file?: File | null;
  actionType?: string | null;
  actionSubtype?: string | null;
  analysisProfile?: string | null;
  manualActionWindowStartSec?: string | number | null;
  manualActionWindowEndSec?: string | number | null;
  note?: string | null;
}

export interface ComparisonChange {
  category: string;
  before_severity: IssueSeverity | null;
  after_severity: IssueSeverity | null;
  description: string;
}

export interface CompareDelta {
  key: string;
  label: string;
  before: number | null;
  after: number | null;
  delta: number | null;
  unit: string | null;
  trend: "up" | "down" | "flat" | "unavailable" | string;
  available: boolean;
}

export interface CompareKeyframeSide {
  frame_id: string | null;
  frame_url: string | null;
  timestamp: number | null;
  confidence: number | null;
  source?: string | null;
  phase_label?: string | null;
  selection_reason?: string | null;
  pre_refine_timestamp?: number | null;
  refinement_method?: string | null;
  refinement_delta_sec?: number | null;
  quality_flags?: string[];
  available: boolean;
  missing_reason: string | null;
}

export interface CompareKeyframePair {
  key: string;
  label: string;
  before: CompareKeyframeSide;
  after: CompareKeyframeSide;
  delta_seconds?: number | null;
  before_offset_seconds?: number | null;
  after_offset_seconds?: number | null;
  relative_delta_seconds?: number | null;
}

export interface CompareVideoSide {
  analysis_id: string;
  video_url: string | null;
  available: boolean;
  missing_reason: string | null;
  action_window_start: number | null;
  action_window_end: number | null;
  action_window_duration: number | null;
  sync_start: number | null;
  sync_duration?: number | null;
  is_slow_motion: boolean;
  source_fps: number | null;
}

export interface CompareVideoPayload {
  before: CompareVideoSide;
  after: CompareVideoSide;
  sync_mode: string;
  sync_anchor_key?: string | null;
}

export interface CompareQualityPayload {
  before_data_quality: string | null;
  after_data_quality: string | null;
  before_flags: string[];
  after_flags: string[];
  warnings: string[];
  subtype_mismatch?: boolean;
  skill_mismatch?: boolean;
}

export interface AnalysisCompareResponse {
  analysis_a: AnalysisDetail;
  analysis_b: AnalysisDetail;
  score_delta: number;
  summary: {
    improved: ComparisonChange[];
    added: ComparisonChange[];
    unchanged: ComparisonChange[];
  };
  subscore_deltas: CompareDelta[];
  metric_deltas: CompareDelta[];
  keyframe_compare: CompareKeyframePair[];
  video_compare: CompareVideoPayload | null;
  quality: CompareQualityPayload | null;
  ai_narrative: string | null;
}

export interface AnalysisComparisonSummary {
  id: string;
  analysis_a_id: string;
  analysis_b_id: string;
  skater_id: string | null;
  skater_name: string | null;
  action_type: string;
  status: "pending" | "processing" | "completed" | "failed" | string;
  score_delta: number | null;
  ai_narrative: string | null;
  error_message: string | null;
  video_ai_status: string | null;
  before_created_at: string | null;
  after_created_at: string | null;
  before_score: number | null;
  after_score: number | null;
  created_at: string;
  updated_at: string;
}

export interface AnalysisComparisonDetail extends AnalysisComparisonSummary {
  result: AnalysisCompareResponse | null;
  video_ai_json: Record<string, unknown> | null;
}

export interface ProgressPoint {
  id: string;
  created_at: string;
  action_type: string;
  force_score: number;
  summary: string;
}

export interface ProgressResponse {
  points: ProgressPoint[];
  stats: {
    total_count: number;
    latest_score: number | null;
    best_score: number | null;
    recent_five_average: number | null;
  };
}

export interface TrainingPlanSession {
  id: string;
  title: string;
  duration: string;
  description: string;
  is_office_trainable: boolean;
  completed: boolean;
  related_issue?: string | null;
  parent_tip?: string | null;
}

export interface TrainingDay {
  day: number;
  theme: string;
  sessions: TrainingPlanSession[];
}

export interface TrainingPlanPayload {
  title: string;
  focus_skill: string;
  days: TrainingDay[];
  generation_source?: "ai" | "fallback" | string | null;
  generation_status?: "ai" | "fallback" | "generating" | string | null;
  generation_note?: string | null;
}

export interface TrainingPlanDetail {
  id: string;
  analysis_id: string;
  skater_id: string;
  plan_json: TrainingPlanPayload;
  created_at: string;
}

export interface ArchiveResponse {
  stats: {
    total_records: number;
    recent_7days: number;
    current_streak: number;
    monthly_sessions: number;
  };
  timeline: Array<{
    id: string;
    created_at: string;
    status: AnalysisStatus;
    skater_id?: string | null;
    skater_name?: string | null;
    skater_avatar_type?: Skater["avatar_type"] | null;
    skater_avatar_emoji?: Skater["avatar_emoji"] | null;
    entry_type: string;
    skill_category: string | null;
    action_type: string;
    action_subtype?: string | null;
    skill_node_id?: string | null;
    force_score: number | null;
    report_snippet: string;
    analysis_id: string;
    session_id: string | null;
    session_date: string | null;
    session_location: string | null;
    session_type: string | null;
    session_duration_minutes: number | null;
  }>;
  limit?: number | null;
  offset?: number;
  has_more?: boolean;
}

export interface SessionPayload {
  session_date: string;
  location: string;
  session_type: string;
  duration_minutes: number | null;
  coach_present: boolean;
  note: string | null;
}

export interface TrainingSessionRecord extends SessionPayload {
  id: string;
  skater_id: string;
  created_at: string;
}

export interface TrainingSessionDetail extends TrainingSessionRecord {
  analyses: AnalysisListItem[];
}

export interface SnowballMemory {
  id: string;
  skater_id: string;
  title: string;
  content: string;
  category: string;
  is_pinned: boolean;
  expires_at: string | null;
  is_expired: boolean;
  created_at: string;
  updated_at: string;
}

export interface SnowballMemoryPayload {
  title: string;
  content: string;
  category: string;
  is_pinned: boolean;
  expires_at: string | null;
}

export interface MemorySuggestion {
  id: string;
  analysis_id: string;
  skater_id: string;
  suggestions: Array<Record<string, unknown>>;
  is_reviewed: boolean;
  created_at: string;
}

export interface SnowballChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface SnowballChatResponse {
  reply: string;
}

export interface HasPinResponse {
  has_pin: boolean;
  pin_length: number;
}

export interface VerifyPinResponse {
  valid: boolean;
}

export interface ChangePinResponse {
  success: boolean;
  reason?: string | null;
}

export interface BackupFile {
  filename: string;
  size_bytes: number;
  created_at: string;
}

export interface BackupActionResponse {
  success: boolean;
  detail: string;
  filename: string;
}

export interface ApiConnectionTestResponse {
  status: "ok" | "error";
  latency_ms: number | null;
  error_code: AnalysisErrorCode | null;
  message: string | null;
  failed_stage: string | null;
}

export interface PoseRuntimeStatus {
  mode: string;
  configured: boolean;
  model_path: string | null;
  model_exists: boolean;
  num_poses: number;
  reason: string;
}

export interface PersonTrackerRuntimeStatus {
  mode: string;
  configured: boolean;
  model_path: string;
  model_exists: boolean;
  mounted_default_path: string;
  mounted_default_exists: boolean;
  env_var: string;
  source: string;
  reason: string;
  dependencies_ready?: boolean;
  dependency_status?: Record<string, boolean>;
  dependency_errors?: Record<string, string>;
}

export const apiClient = axios.create({
  baseURL: "/api",
  timeout: 600000,
});

export function uploadAnalysis(
  formData: FormData,
  options?: {
    onProgress?: (progress: UploadProgress) => void;
    signal?: AbortSignal;
  },
) {
  return new Promise<UploadResponse>((resolve, reject) => {
    const request = new XMLHttpRequest();
    const url = `${apiClient.defaults.baseURL ?? ""}/analysis/upload`;

    request.open("POST", url, true);
    request.timeout = typeof apiClient.defaults.timeout === "number" ? apiClient.defaults.timeout : 600000;
    request.withCredentials = apiClient.defaults.withCredentials ?? false;
    request.responseType = "json";

    request.upload.onprogress = (event) => {
      if (!event.lengthComputable || !options?.onProgress) {
        return;
      }
      const total = event.total;
      const loaded = Math.min(event.loaded, total);
      options.onProgress({
        loaded,
        total,
        percent: total > 0 ? Math.round((loaded / total) * 100) : 0,
      });
    };

    request.onload = () => {
      const responseData = request.response ?? (request.responseText ? JSON.parse(request.responseText) : null);
      if (request.status >= 200 && request.status < 300) {
        resolve(responseData as UploadResponse);
        return;
      }

      reject({
        response: {
          status: request.status,
          data: responseData,
        },
      });
    };

    request.onerror = () => {
      reject(new Error("Network Error"));
    };

    request.ontimeout = () => {
      reject(new Error("Timeout"));
    };

    if (options?.signal) {
      if (options.signal.aborted) {
        request.abort();
        reject(new DOMException("Aborted", "AbortError"));
        return;
      }

      options.signal.addEventListener(
        "abort",
        () => {
          request.abort();
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    }

    request.send(formData);
  });
}

export async function fetchAnalysis(id: string, options?: { isParentRequest?: boolean }) {
  const response = await apiClient.get<AnalysisDetail>(`/analysis/${id}`, {
    params: options?.isParentRequest ? { is_parent_request: true } : undefined,
  });
  return response.data;
}

export async function retryAnalysis(id: string, options?: { retryFrom?: string | null; resetTargetLock?: boolean }) {
  const response = await apiClient.post<RetryAnalysisResponse>(`/analysis/${id}/retry`, undefined, {
    params: {
      retry_from: options?.retryFrom || undefined,
      reset_target_lock: options?.resetTargetLock || undefined,
    },
  });
  return response.data;
}

export async function rerunVideoAIKeyframes(id: string) {
  const response = await apiClient.post<AnalysisCorrectionMutationResponse>(`/analysis/${id}/chat/video-keyframes-rerun`);
  return response.data;
}

export async function exportAnalysis(id: string) {
  const response = await apiClient.post<string>(`/analysis/${id}/export`, undefined, {
    responseType: "text",
  });
  return {
    text: response.data,
  } satisfies AnalysisExportResponse;
}

export async function deleteAnalysis(id: string, parentPin: string) {
  await apiClient.delete(`/analysis/${id}`, {
    headers: {
      "X-Parent-Pin": parentPin,
    },
  });
}

export async function fetchAnalysisPose(id: string) {
  const response = await apiClient.get<PoseResponse>(`/analysis/${id}/pose`);
  return response.data;
}

export async function fetchAnalysisChatMessages(id: string) {
  const response = await apiClient.get<AnalysisChatMessage[]>(`/analysis/${id}/chat/messages`);
  return response.data;
}

export async function sendAnalysisChatMessage(id: string, message: string, providerId?: string | null) {
  const response = await apiClient.post<AnalysisChatResponse>(`/analysis/${id}/chat`, {
    message,
    provider_id: providerId || null,
  });
  return response.data;
}

export async function fetchAnalysisCorrections(id: string) {
  const response = await apiClient.get<AnalysisCorrectionListResponse>(`/analysis/${id}/corrections`);
  return response.data;
}

export async function createAnalysisCorrection(id: string, payload: AnalysisCorrectionCreatePayload) {
  const response = await apiClient.post<AnalysisCorrectionMutationResponse>(`/analysis/${id}/corrections`, payload);
  return response.data;
}

export async function applyAnalysisCorrection(id: string, correctionId: string) {
  const response = await apiClient.post<AnalysisCorrectionMutationResponse>(`/analysis/${id}/corrections/${correctionId}/apply`);
  return response.data;
}

export async function dismissAnalysisCorrection(id: string, correctionId: string) {
  const response = await apiClient.post<AnalysisCorrectionMutationResponse>(`/analysis/${id}/corrections/${correctionId}/dismiss`);
  return response.data;
}

export async function regenerateReportFromCorrections(id: string) {
  const response = await apiClient.post<AnalysisCorrectionMutationResponse>(`/analysis/${id}/corrections/regenerate-report`);
  return response.data;
}

export async function shareAnalysisChat(id: string, options?: { message_ids?: string[]; include_pending_corrections?: boolean }) {
  const response = await apiClient.post<AnalysisChatShareResponse>(`/analysis/${id}/chat/share`, options ?? {});
  return response.data;
}

export async function fetchTargetPreview(id: string) {
  const response = await apiClient.get<TargetPreviewResponse>(`/analysis/${id}/target-preview`);
  return response.data;
}

export async function confirmTargetLock(
  id: string,
  payload: { candidate_id?: string | null; x?: number; y?: number; manual_bbox?: TargetBBox | null },
) {
  const response = await apiClient.post<AnalysisDetail>(`/analysis/${id}/target-lock`, payload);
  return response.data;
}

export async function fetchAnalyses(params?: { action_type?: string; skater_id?: string; limit?: number; offset?: number }) {
  const response = await apiClient.get<AnalysisListItem[] | { value?: AnalysisListItem[]; items?: AnalysisListItem[]; analyses?: AnalysisListItem[] }>("/analysis/", { params });
  const data = response.data;
  if (Array.isArray(data)) {
    return data;
  }
  return data.value ?? data.items ?? data.analyses ?? [];
}

export async function fetchAnalysisCompare(idA: string, idB: string) {
  const response = await apiClient.get<AnalysisCompareResponse>("/analysis/compare", {
    params: { id_a: idA, id_b: idB, _ts: Date.now() },
  });
  return response.data;
}

export async function createAnalysisComparison(idA: string, idB: string) {
  const response = await apiClient.post<AnalysisComparisonDetail>("/analysis/comparisons", {
    id_a: idA,
    id_b: idB,
  });
  return response.data;
}

export async function fetchAnalysisComparisons(params?: {
  skater_id?: string;
  action_type?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) {
  const response = await apiClient.get<AnalysisComparisonSummary[]>("/analysis/comparisons", { params });
  return response.data;
}

export async function fetchAnalysisComparison(id: string) {
  const response = await apiClient.get<AnalysisComparisonDetail>(`/analysis/comparisons/${id}`, {
    params: { _ts: Date.now() },
  });
  return response.data;
}

export async function retryAnalysisComparison(id: string) {
  const response = await apiClient.post<AnalysisComparisonDetail>(`/analysis/comparisons/${id}/retry`);
  return response.data;
}

export async function fetchProgress(params?: { action_type?: string; skater_id?: string }) {
  const response = await apiClient.get<ProgressResponse>("/analysis/progress", { params });
  return response.data;
}

export async function createPlan(analysisId: string, options?: { force?: boolean }) {
  const response = await apiClient.post<TrainingPlanDetail>(`/analysis/${analysisId}/plan`, null, {
    params: options?.force ? { force: true } : undefined,
  });
  return response.data;
}

export async function fetchAnalysisPlan(analysisId: string) {
  const response = await apiClient.get<TrainingPlanDetail>(`/analysis/${analysisId}/plan`);
  return response.data;
}

export async function fetchPlan(planId: string) {
  const response = await apiClient.get<TrainingPlanDetail>(`/plan/${planId}`);
  return response.data;
}

export async function fetchLatestPlanForSkater(skaterId: string) {
  const response = await apiClient.get<TrainingPlanDetail>(`/plan/skater/${skaterId}/latest`);
  return response.data;
}

export async function updatePlanSession(planId: string, sessionId: string, completed: boolean) {
  const response = await apiClient.patch<TrainingPlanDetail>(`/plan/${planId}/session/${sessionId}`, {
    completed,
  });
  return response.data;
}

export async function extendPlan(planId: string, completed_days: number[]) {
  const response = await apiClient.post<TrainingPlanDetail>(`/plan/${planId}/extend`, {
    completed_days,
  });
  return response.data;
}

export async function fetchSkaters() {
  const response = await apiClient.get<Skater[]>("/skaters/");
  return response.data;
}

export async function fetchArchive(skaterId: string, params?: { limit?: number; offset?: number }) {
  const response = await apiClient.get<ArchiveResponse>(`/skaters/${skaterId}/archive`, { params });
  return response.data;
}

export async function fetchArchiveSummary(params?: { limit?: number; offset?: number; skater_id?: string | null }) {
  const response = await apiClient.get<ArchiveResponse>("/skaters/archive", { params });
  return response.data;
}

export async function fetchTrainingSessions(skaterId: string) {
  const response = await apiClient.get<TrainingSessionRecord[]>(`/skaters/${skaterId}/sessions`);
  return response.data;
}

export async function createTrainingSession(skaterId: string, payload: SessionPayload) {
  const response = await apiClient.post<TrainingSessionRecord>(`/skaters/${skaterId}/sessions`, payload);
  return response.data;
}

export async function fetchTrainingSession(sessionId: string) {
  const response = await apiClient.get<TrainingSessionDetail>(`/sessions/${sessionId}`);
  return response.data;
}

export async function updateTrainingSession(sessionId: string, payload: Partial<SessionPayload>) {
  const response = await apiClient.patch<TrainingSessionRecord>(`/sessions/${sessionId}`, payload);
  return response.data;
}

export async function deleteTrainingSession(sessionId: string) {
  const response = await apiClient.delete<{ success: boolean }>(`/sessions/${sessionId}`);
  return response.data;
}

export async function updateAnalysisSession(analysisId: string, sessionId: string | null) {
  const response = await apiClient.patch<AnalysisDetail>(`/analysis/${analysisId}/session`, { session_id: sessionId });
  return response.data;
}

export async function fetchHasPin() {
  const response = await apiClient.get<HasPinResponse>("/auth/has-pin");
  return response.data;
}

export async function setupPin(pin: string) {
  const response = await apiClient.post<HasPinResponse>("/auth/setup-pin", { pin });
  return response.data;
}

export async function verifyPin(pin: string) {
  const response = await apiClient.post<VerifyPinResponse>("/auth/verify-pin", { pin });
  return response.data;
}

export async function changePin(oldPin: string, newPin: string) {
  const response = await apiClient.post<ChangePinResponse>("/auth/change-pin", {
    old_pin: oldPin,
    new_pin: newPin,
  });
  return response.data;
}

export async function fetchSkaterSkills(skaterId: string) {
  const response = await apiClient.get<SkillNode[]>(`/skaters/${skaterId}/skills`);
  return response.data;
}

export async function fetchLearningPath(skaterId: string) {
  const response = await apiClient.get<LearningPathResponse>(`/skaters/${skaterId}/learning-path`);
  return response.data;
}

export async function unlockSkaterSkill(skaterId: string, skillId: string, note?: string) {
  const response = await apiClient.post<SkillMutationResponse>(`/skaters/${skaterId}/skills/${skillId}/unlock`, { note });
  return response.data;
}

export async function lockSkaterSkill(skaterId: string, skillId: string) {
  const response = await apiClient.post<SkillMutationResponse>(`/skaters/${skaterId}/skills/${skillId}/lock`);
  return response.data;
}

export async function updateSkater(
  skaterId: string,
  payload: { display_name?: string; avatar_emoji?: string; birth_year?: number },
) {
  const response = await apiClient.patch<Skater>(`/skaters/${skaterId}`, payload);
  return response.data;
}

export async function fetchProviders() {
  const response = await apiClient.get<ProviderPublic[]>("/providers/");
  return response.data;
}

export async function fetchVisionVoteConfig() {
  const response = await apiClient.get<VisionVoteConfig>("/providers/vision-vote/config");
  return response.data;
}

export async function fetchProviderMetrics(params?: { days?: number; analysis_profile?: string | null }) {
  const response = await apiClient.get<ProviderMetricPublic[]>("/providers/metrics", {
    params: {
      days: params?.days ?? 30,
      analysis_profile: params?.analysis_profile ?? undefined,
    },
  });
  return response.data;
}

export async function fetchAutoEvalSnapshots(params?: {
  limit?: number;
  analysis_profile?: string | null;
  action_type?: string | null;
}) {
  const response = await apiClient.get<AutoEvalSnapshotSummary[]>("/analysis/auto-eval/snapshots", {
    params: {
      limit: params?.limit ?? 50,
      analysis_profile: params?.analysis_profile ?? undefined,
      action_type: params?.action_type ?? undefined,
    },
  });
  return response.data;
}

export async function fetchDebugRuns(params?: { limit?: number }) {
  const response = await apiClient.get<DebugRunSummary[]>("/debug/runs", {
    params: { limit: params?.limit ?? 50 },
  });
  return response.data;
}

export async function fetchDebugRun(id: string) {
  const response = await apiClient.get<DebugRunDetail>(`/debug/runs/${id}`);
  return response.data;
}

export async function deleteDebugRun(id: string) {
  await apiClient.delete(`/debug/runs/${id}`);
}

function buildDebugRunFormData(payload: DebugRunCreatePayload) {
  const formData = new FormData();
  if (payload.analysisId) {
    formData.append("analysis_id", payload.analysisId);
  }
  if (payload.file) {
    formData.append("file", payload.file);
  }
  if (payload.actionType) {
    formData.append("action_type", payload.actionType);
  }
  if (payload.actionSubtype) {
    formData.append("action_subtype", payload.actionSubtype);
  }
  if (payload.analysisProfile) {
    formData.append("analysis_profile", payload.analysisProfile);
  }
  if (payload.manualActionWindowStartSec != null && payload.manualActionWindowEndSec != null) {
    formData.append("manual_action_window_start_sec", String(payload.manualActionWindowStartSec));
    formData.append("manual_action_window_end_sec", String(payload.manualActionWindowEndSec));
  }
  if (payload.note) {
    formData.append("note", payload.note);
  }
  return formData;
}

export async function createLocalDebugRun(payload: DebugRunCreatePayload) {
  const response = await apiClient.post<DebugRunCreateResponse>("/debug/runs/local-pose-keyframes", buildDebugRunFormData(payload));
  return response.data;
}

export async function createVideoAiDebugRun(payload: DebugRunCreatePayload) {
  const response = await apiClient.post<DebugRunCreateResponse>("/debug/runs/video-ai-keyframes", buildDebugRunFormData(payload));
  return response.data;
}

export async function confirmDebugTargetLock(
  id: string,
  payload: { candidate_id?: string | null; x?: number; y?: number; manual_bbox?: TargetBBox | null },
) {
  const response = await apiClient.post<DebugRunCreateResponse>(`/debug/runs/${id}/target-lock`, payload);
  return response.data;
}

export async function updateVisionVoteConfig(payload: VisionVoteConfig) {
  const response = await apiClient.put<VisionVoteConfig>("/providers/vision-vote/config", payload);
  return response.data;
}

export async function createProvider(payload: ProviderCreatePayload) {
  const response = await apiClient.post<ProviderPublic>("/providers/", payload);
  return response.data;
}

export async function activateProvider(providerId: string) {
  const response = await apiClient.patch<ProviderPublic>(`/providers/${providerId}/activate`);
  return response.data;
}

export async function updateProvider(providerId: string, payload: ProviderUpdatePayload) {
  const response = await apiClient.patch<ProviderPublic>(`/providers/${providerId}`, payload);
  return response.data;
}

export async function testProvider(providerId: string) {
  const response = await apiClient.post<{ success: boolean; detail: string }>(`/providers/${providerId}/test`);
  return response.data;
}

export async function fetchMemories(skaterId: string) {
  const response = await apiClient.get<SnowballMemory[]>(`/skaters/${skaterId}/memories`);
  return response.data;
}

export async function createMemory(skaterId: string, payload: SnowballMemoryPayload) {
  const response = await apiClient.post<SnowballMemory>(`/skaters/${skaterId}/memories`, payload);
  return response.data;
}

export async function updateMemory(skaterId: string, memoryId: string, payload: Partial<SnowballMemoryPayload>) {
  const response = await apiClient.patch<SnowballMemory>(`/skaters/${skaterId}/memories/${memoryId}`, payload);
  return response.data;
}

export async function deleteMemory(skaterId: string, memoryId: string) {
  await apiClient.delete(`/skaters/${skaterId}/memories/${memoryId}`);
}

export async function toggleMemoryPin(skaterId: string, memoryId: string, isPinned?: boolean) {
  const response = await apiClient.patch<SnowballMemory>(`/skaters/${skaterId}/memories/${memoryId}/pin`, {
    is_pinned: isPinned,
  });
  return response.data;
}

export async function fetchMemorySuggestions(skaterId: string) {
  const response = await apiClient.get<MemorySuggestion[]>(`/skaters/${skaterId}/memory-suggestions`);
  return response.data;
}

export async function applyMemorySuggestions(skaterId: string, suggestionId: string, acceptedIndices: number[]) {
  const response = await apiClient.post<SnowballMemory[]>(`/skaters/${skaterId}/memory-suggestions/apply`, {
    suggestion_id: suggestionId,
    accepted_indices: acceptedIndices,
  });
  return response.data;
}

export async function dismissMemorySuggestion(skaterId: string, suggestionId: string) {
  const response = await apiClient.patch<MemorySuggestion>(`/skaters/${skaterId}/memory-suggestions/${suggestionId}/dismiss`);
  return response.data;
}

export async function chatWithSnowball(payload: {
  skater_id?: string | null;
  message: string;
  history: SnowballChatMessage[];
}) {
  const response = await apiClient.post<SnowballChatResponse>("/snowball/chat", payload);
  return response.data;
}

export async function fetchSystemInfo() {
  const response = await apiClient.get<SystemInfo>("/system/info");
  return response.data;
}

export async function fetchStorageStats() {
  const response = await apiClient.get<StorageStats>("/admin/storage-stats");
  return response.data;
}

export async function testActiveApiConnection() {
  const response = await apiClient.get<ApiConnectionTestResponse>("/settings/test-api");
  return response.data;
}

export async function fetchPoseRuntimeStatus() {
  const response = await apiClient.get<PoseRuntimeStatus>("/settings/pose-runtime");
  return response.data;
}

export async function fetchPersonTrackerRuntimeStatus() {
  const response = await apiClient.get<PersonTrackerRuntimeStatus>("/settings/person-tracker-runtime");
  return response.data;
}

export async function fetchBackups() {
  const response = await apiClient.get<{ items: BackupFile[] }>("/admin/backups");
  return response.data.items;
}

export async function createBackup(label?: string) {
  const response = await apiClient.post<BackupActionResponse>("/admin/backups", { label: label || null });
  return response.data;
}

export async function restoreBackup(filename: string) {
  const response = await apiClient.post<BackupActionResponse>("/admin/backups/restore", { filename });
  return response.data;
}
