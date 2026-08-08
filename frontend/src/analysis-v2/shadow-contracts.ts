export const SHADOW_STAGES = ["timebase", "observations", "candidates", "identity", "pose", "events", "moments", "rotation", "path_reviews", "claims"] as const;
export type ShadowStage = typeof SHADOW_STAGES[number];
export type ShadowRunStatus = "disabled" | "queued" | "running" | "complete" | "partial" | "failed" | "invalid" | "cancelled";
export type ShadowStageStatus = "pending" | "queued" | "running" | "complete" | "failed" | "invalid" | "skipped";
export type ShadowDiffStatus = "unchanged" | "different" | "unexplained" | "excluded" | "incompatible" | "unavailable";
export type ShadowDownstreamStatus = "would_change" | "excluded" | "incompatible" | "unchanged";

export interface ShadowStageState {
  schema_version: "shadow-stage.v1";
  stage: ShadowStage;
  status: ShadowStageStatus;
  fingerprint: string | null;
  input_hash: string | null;
  output_hash: string | null;
  dependency_hashes: Record<string, string>;
  error: string | null;
  retry_count: number;
  updated_at: string;
}

export interface ShadowStageDiff {
  schema_version: "shadow-stage-diff.v1";
  stage: ShadowStage;
  status: ShadowDiffStatus;
  legacy_fingerprint: string | null;
  v2_fingerprint: string | null;
  summary: string | null;
  details: Record<string, unknown>;
  first_divergent: boolean;
}

export interface ShadowArtifactReference {
  schema_version: "shadow-artifact-reference.v1";
  artifact_id: string;
  stage: ShadowStage;
  kind: string;
  relative_path: string;
  fingerprint: string | null;
  status: "rebuildable" | "missing" | "retained";
  created_at: string;
}

export interface ShadowReviewDecision {
  schema_version: "shadow-review-decision.v1";
  decision_id: string;
  run_id: string;
  stage: ShadowStage;
  decision: "accept_shadow" | "reject_shadow" | "defer" | "promote_candidate";
  reviewer: string;
  note: string | null;
  audited_at: string;
  authority: "shadow";
  legacy_mutation: false;
  promotion_scope: "shadow_only" | null;
}

export interface ShadowDownstreamImpact {
  consumer: string;
  status: ShadowDownstreamStatus;
  reason: string | null;
  executed: false;
}

export interface ShadowRunRecord {
  schema_version: "shadow-run.v1";
  run_id: string;
  analysis_id: string;
  status: ShadowRunStatus;
  authority: "legacy";
  diagnostic_only: true;
  pipeline_fingerprint: string | null;
  source_fingerprint: string | null;
  source_video_hash: string | null;
  model_fingerprint: string | null;
  config_fingerprint: string | null;
  prompt_fingerprint: string | null;
  contract_fingerprint: string | null;
  /** Optional for compatibility with manifests created before baseline hashes were added. */
  legacy_stage_fingerprints?: Record<string, string>;
  created_at: string;
  updated_at: string;
  requested_by: string;
  coalesced: boolean;
  retry_from_stage: ShadowStage | null;
  first_divergent_stage: ShadowStage | null;
  stages: ShadowStageState[];
  diffs: ShadowStageDiff[];
  artifacts: ShadowArtifactReference[];
  review_decisions: ShadowReviewDecision[];
  downstream: ShadowDownstreamImpact[];
  notes: Array<{ author: string; note: string; created_at: string }>;
  error: string | null;
}

export interface ShadowCapabilitiesResponse {
  schema_version: "shadow-orchestration.v1";
  enabled: boolean;
  runtime_mode: "legacy" | "shadow" | "v2";
  public_authority: "legacy";
  diagnostic_only: true;
  writes_user_data: false;
  isolated_runtime: boolean;
  stages: ShadowStage[];
}

export interface ShadowRecoveryResponse {
  schema_version: "shadow-orchestration.v1";
  run: ShadowRunRecord;
}

export interface ShadowCleanupResponse {
  schema_version: "shadow-orchestration.v1";
  run_id: string;
  removed: string[];
  retained: string[];
}

export interface ShadowRunRequest {
  analysis_id: string;
  source_fingerprint?: string | null;
  source_video_hash?: string | null;
  model_fingerprint?: string | null;
  config_fingerprint?: string | null;
  prompt_fingerprint?: string | null;
  contract_fingerprint?: string | null;
  legacy_stage_fingerprints?: Record<string, string>;
  note?: string | null;
  force?: boolean;
}

export interface ShadowRunResponse { schema_version: "shadow-orchestration.v1"; run: ShadowRunRecord }
export interface ShadowRunListResponse { schema_version: "shadow-orchestration.v1"; analysis_id: string; runs: ShadowRunRecord[] }
export interface ShadowStatusResponse { schema_version: "shadow-orchestration.v1"; status: ShadowRunStatus; runtime_mode: "legacy" | "shadow" | "v2"; public_authority: "legacy"; diagnostic_only: true; writes_user_data: false; run: ShadowRunRecord | null }
export interface ShadowDiffResponse { schema_version: "shadow-orchestration.v1"; run_id: string; analysis_id: string; first_divergent_stage: ShadowStage | null; stages: ShadowStageDiff[]; downstream: ShadowDownstreamImpact[] }
export interface ShadowArtifactResponse { schema_version: "shadow-orchestration.v1"; run_id: string; analysis_id: string; artifact: ShadowArtifactReference; content: Record<string, unknown> | null }
export interface ShadowDecisionResponse { schema_version: "shadow-orchestration.v1"; run_id: string; decision: ShadowReviewDecision; legacy_report_rewritten: false; run?: ShadowRunRecord | null }
