export type GoldenCatalogStatus = "empty" | "ready" | "invalid-source" | "schema-incompatible";

export interface GoldenCatalogSummary {
  dataset_id: string;
  schema_version: "golden-dataset.v2";
  revision: number;
  status: GoldenCatalogStatus;
  source_count: number;
  event_count: number;
  profile_counts: GoldenCount[];
  observability_counts: GoldenCount[];
  strata_counts: GoldenCount[];
  duplicate_sources: string[];
}

export interface GoldenSchemaInfo {
  schema_version: "golden-dataset.v2";
  supported_schema_versions: string[];
  migration_policy: "future-v2-only";
  historical_debug_pool: "not-imported";
}

export type GoldenGatePolicyVersion = "golden-gate-policy.v2";
export type HistoricalGoldenGatePolicyVersion = "golden-gate-policy.v1" | GoldenGatePolicyVersion;
export type LimitedSampleEvidenceScope = "limited_sample";
export type GateRequirement = { count?: number; target?: number; issues?: string[]; passed: boolean };
export type GoldenGateTemplate = {
  gate: "G1";
  status: "not-run";
  gate_policy_version?: GoldenGatePolicyVersion;
  evidence_scope?: LimitedSampleEvidenceScope;
  required_source_videos?: number;
  required_valid_events?: number;
  profile_minimums?: Record<string, number>;
  required_new_events: number;
  pose_frame_range?: [number, number];
  g2_event_range?: [number, number];
  g2_profile_ranges?: Record<string, [number, number]>;
};

export type ResolvedGoldenGateTemplate = Required<GoldenGateTemplate>;

export const GOLDEN_GATE_POLICY_V2_DEFAULTS: ResolvedGoldenGateTemplate = {
  gate: "G1",
  status: "not-run",
  gate_policy_version: "golden-gate-policy.v2",
  evidence_scope: "limited_sample",
  required_source_videos: 18,
  required_valid_events: 18,
  profile_minimums: { jump: 10, spin: 4, step: 2, spiral: 2 },
  required_new_events: 18,
  pose_frame_range: [24, 40],
  g2_event_range: [24, 30],
  g2_profile_ranges: { jump: [10, 14], spin: [6, 8], step: [4, 5], spiral: [4, 5] },
};

export const LEGACY_G2_PROFILE_RANGES: Record<string, [number, number]> = {
  jump: [24, 32], spin: [16, 20], step: [12, 16], spiral: [8, 12],
};

export function resolveGoldenGateTemplate(template: GoldenGateTemplate): ResolvedGoldenGateTemplate {
  return {
    ...GOLDEN_GATE_POLICY_V2_DEFAULTS,
    ...template,
    profile_minimums: template.profile_minimums ?? GOLDEN_GATE_POLICY_V2_DEFAULTS.profile_minimums,
    pose_frame_range: template.pose_frame_range ?? GOLDEN_GATE_POLICY_V2_DEFAULTS.pose_frame_range,
    g2_event_range: template.g2_event_range ?? GOLDEN_GATE_POLICY_V2_DEFAULTS.g2_event_range,
    g2_profile_ranges: template.g2_profile_ranges ?? GOLDEN_GATE_POLICY_V2_DEFAULTS.g2_profile_ranges,
  };
}

export interface GoldenSanitizedExport {
  schema_version: "golden-sanitized-summary.v1";
  dataset_id: string;
  golden_schema_version: "golden-dataset.v2";
  revision: number;
  aggregate: {
    source_count: number;
    event_count: number;
    profile_counts: GoldenCount[];
    observability_counts: GoldenCount[];
    strata_counts: GoldenCount[];
  };
  redacted_aliases: string[];
  gate_template: GoldenGateTemplate;
}

export interface GoldenCount { key: string; count: number; }

export type GoldenProfile = "jump" | "spin" | "step" | "spiral" | "unknown";
export type GoldenObservability = "observable" | "uncertain" | "unobservable";
export type SourceMoment = { pts: number; source_frame_index?: number };
export type PhaseInterval = { start_pts: number; end_pts: number };
export type RotationLabel = {
  schema_version?: "rotation-label.v2";
  observed_turns_min: number;
  observed_turns_max: number;
  reported_turns: number | null;
  convention: "axel_includes_forward_takeoff" | "non_axel_airborne" | "unknown";
  observability: GoldenObservability;
  definition: "airborne_body_rotation" | "competition_naming" | "observed_spin_rotation";
  status: "exact" | "range" | "unobservable";
  value_turns: number | null;
  range_turns: [number, number] | null;
  review_start_pts: number | null;
  review_end_pts: number | null;
  review_method: "source_frame_step";
};
export type ChallengeInterval = { start_pts: number; end_pts: number; category: "crossing" | "occlusion" | "relock" | "exit_reentry" | "blur" | "compression" | "unknown"; observability: GoldenObservability };
export type JumpDetails = { takeoff?: SourceMoment | null; apex?: SourceMoment | null; landing?: SourceMoment | null; rotation?: RotationLabel | null };
export type SpinDetails = { entry?: PhaseInterval | null; main?: PhaseInterval | null; exit?: PhaseInterval | null; rotation?: RotationLabel | null };
export type IntervalDetails = { phase?: PhaseInterval | null; representative_moment?: SourceMoment | null };
export type PoseJoint = { joint: "nose" | "left_shoulder" | "right_shoulder" | "left_elbow" | "right_elbow" | "left_wrist" | "right_wrist" | "left_hip" | "right_hip" | "left_knee" | "right_knee" | "left_ankle" | "right_ankle"; x: number; y: number; visibility: number };
export type GoldenWorkspace = {
  dataset_id: string;
  revision: number;
  sources: Array<{ source_sha256: string; duration_pts: number; width: number; height: number; source_frame_count: number | null; display_rotation_degrees: 0 | 90 | 180 | 270; redacted_alias: string; recording_session_id: string; grouping_id: string; source_timeline?: { timestamp_status: "exact" | "approximate_legacy" | "unavailable"; frames: Array<{ source_frame_index: number; pts_sec: number | null; duration_sec: number | null; status: string; gap_before_sec: number }>; [key: string]: unknown } | null }>;
  events: GoldenEvent[];
  tracks: GoldenTrack[];
  poses: GoldenPose[];
};
export type GoldenEvent = { event_id: string; source_sha256: string; start_pts: number; end_pts: number; profile: GoldenProfile; subtype?: string | null; observability: GoldenObservability; strata: string[]; ambiguity_tags: string[]; failure_tags: string[]; annotator_confidence: number; main_skater_confirmed: boolean; split?: "development" | "validation" | "frozen_test" | null; challenge_intervals: ChallengeInterval[]; jump?: JumpDetails | null; spin?: SpinDetails | null; step?: IntervalDetails | null; spiral?: IntervalDetails | null; revision?: unknown; field_revisions?: Record<string, unknown> };
export type GoldenTrack = { label_id: string; event_id: string; source_sha256: string; source_frame_index?: number; pts: number; bbox: { left: number; top: number; right: number; bottom: number }; state: "confirmed" | "uncertain" | "lost"; revision?: unknown };
export type GoldenPose = { label_id: string; event_id: string; source_sha256: string; source_frame_index?: number; pts: number; joints: PoseJoint[]; observability: Exclude<GoldenObservability, "unobservable">; revision?: unknown };
export type GoldenReviewItem = { event_id: string; status: "incomplete" | "low-confidence" | "ambiguous" | "double-review-required"; message: string };

export type PilotEvaluatorState = "not_run" | "running" | "waiting_for_owner_labels" | "invalid_labels" | "failed" | "passed_for_pilot_only";
export type PilotGap = { key: string; count: number; target: number; missing: number };
export type PilotProgress = {
  gate: "G1";
  gate_policy_version?: GoldenGatePolicyVersion;
  evidence_scope?: LimitedSampleEvidenceScope;
  status: "waiting_for_owner_labels" | "ready_for_evaluator";
  diagnostic_only: true;
  release_claim: false;
  profiles: PilotGap[];
  scenes: PilotGap[];
  requirements: Record<string, GateRequirement>;
  next_actions?: string[];
  next_best_videos: string[];
};
export type PilotEvaluatorStatus = { status: PilotEvaluatorState; evaluator_version: string; diagnostic_only: true; message: string | null; result_fingerprint?: string | null; leakage_fields?: string[]; progress?: PilotProgress | null };
export type MetricRate = { numerator: number; denominator: number; rate: number | null; confidence_interval_95: [number, number] | null };
export type PilotSanitizedResult = {
  schema_version: "golden-pilot-sanitized-report.v1";
  evaluator_version: string;
  gate_policy_version?: HistoricalGoldenGatePolicyVersion;
  evidence_scope?: LimitedSampleEvidenceScope;
  dataset_id: string;
  dataset_fingerprint: string;
  pipeline_fingerprint: string;
  evaluation_masks: string[];
  run_scope?: "snapshot_diagnostic" | "formal_g1";
  diagnostic_only: true;
  release_claim: false;
  deterministic_fingerprint: string;
  repeatability: { deterministic: true; fingerprint: string };
  aggregate: Record<string, unknown>;
  failed_events: Array<{ alias: string; profile: GoldenProfile; strata: string[]; failure_codes: string[] }>;
};

export type GoldenG2Status = {
  schema_version: "golden-g2-status.v1";
  gate: "G2";
  gate_policy_version?: HistoricalGoldenGatePolicyVersion;
  evidence_scope?: LimitedSampleEvidenceScope;
  status: "collecting" | "ready_to_freeze" | "frozen_waiting_for_baseline" | "baseline_recorded";
  event_count: number;
  required_event_range: [number, number];
  profile_ranges?: Record<string, [number, number]>;
  distribution: {
    profiles: Record<string, number>;
    splits: Record<string, number>;
    strata: Record<string, number>;
    recording_session_count: number;
  };
  dataset_revision?: number | null;
  dataset_fingerprint?: string | null;
  legacy_pipeline_fingerprint?: string | null;
  baseline_result_fingerprint?: string | null;
  release_claim: false;
};

export function isPilotSanitizedResult(value: unknown): value is PilotSanitizedResult {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return record.schema_version === "golden-pilot-sanitized-report.v1" && record.diagnostic_only === true && record.release_claim === false &&
    typeof record.dataset_fingerprint === "string" && typeof record.pipeline_fingerprint === "string" && Array.isArray(record.evaluation_masks) &&
    typeof record.aggregate === "object" && record.aggregate !== null && Array.isArray(record.failed_events);
}

export function isGoldenCatalogSummary(value: unknown): value is GoldenCatalogSummary {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return record.schema_version === "golden-dataset.v2" &&
    (record.status === "empty" || record.status === "ready" || record.status === "invalid-source" || record.status === "schema-incompatible") &&
    typeof record.dataset_id === "string" && typeof record.revision === "number" &&
    typeof record.source_count === "number" && typeof record.event_count === "number" &&
    Array.isArray(record.duplicate_sources);
}
