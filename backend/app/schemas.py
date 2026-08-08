from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ReportIssue(BaseModel):
    category: str
    description: str
    severity: Severity
    phase: str | None = None
    frames: list[str] = Field(default_factory=list)


class ReportImprovement(BaseModel):
    target: str
    action: str


class StructuredReport(BaseModel):
    summary: str
    issues: list[ReportIssue] = Field(default_factory=list)
    improvements: list[ReportImprovement] = Field(default_factory=list)
    training_focus: str
    subscores: dict[str, int] = Field(default_factory=dict)
    score_breakdown: dict[str, Any] | None = None
    data_quality: str = "partial"
    user_note: str | None = None
    user_note_response: str | None = None
    action_confirmation: dict[str, Any] | None = None


class AnalysisUploadResponse(BaseModel):
    id: str
    status: str


class AnalysisRetryResponse(BaseModel):
    message: str


class AnalysisChatMessagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    role: str
    content: str
    created_at: datetime
    provider_id: str | None = None
    provider_name: str | None = None
    model_id: str | None = None
    selected_event_id: str | None = None
    facts_authority: str | None = None
    source_fact_hash: str | None = None


class AnalysisChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    provider_id: str | None = None
    selected_event_id: str | None = Field(default=None, max_length=80)


class AnalysisChatResponse(BaseModel):
    message: AnalysisChatMessagePublic
    messages: list[AnalysisChatMessagePublic] = Field(default_factory=list)
    suggested_action: dict[str, Any] | None = None


class AnalysisCorrectionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    kind: str
    payload: dict[str, Any]
    rationale: str | None = None
    source: str
    status: str
    original_snapshot: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None = None
    event_id: str | None = None
    facts_authority: str | None = None
    facts_schema_version: str | None = None
    source_fact_hash: str | None = None
    source_fact_revision: int | None = None
    source_pipeline_fingerprint: str | None = None
    generation_fingerprint: str | None = None
    invalidated_artifacts: list[str] = Field(default_factory=list)


class AnalysisCorrectionCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = Field(default=None, max_length=2000)
    source: str = Field(default="manual", max_length=24)
    status: str = Field(default="proposed", max_length=16)


class AnalysisCorrectionListResponse(BaseModel):
    corrections: list[AnalysisCorrectionPublic] = Field(default_factory=list)
    effective: dict[str, Any] = Field(default_factory=dict)


class AnalysisCorrectionMutationResponse(BaseModel):
    correction: AnalysisCorrectionPublic
    corrections: list[AnalysisCorrectionPublic] = Field(default_factory=list)
    effective: dict[str, Any] = Field(default_factory=dict)


class AnalysisChatShareRequest(BaseModel):
    message_ids: list[str] | None = None
    include_pending_corrections: bool = True


class AnalysisChatShareResponse(BaseModel):
    title: str
    text: str
    image_payload: dict[str, Any] = Field(default_factory=dict)


class AnalysisLogEntry(BaseModel):
    timestamp: str
    stage: str
    level: str
    message: str
    elapsed_s: float | None = None
    retry_from_stage: str | None = None
    error_code: str | None = None
    detail: str | None = None


class AnalysisListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skater_id: str | None = None
    session_id: str | None = None
    skater_name: str | None = None
    skill_category: str | None = None
    action_type: str
    action_subtype: str | None = None
    analysis_profile: str | None = None
    pipeline_version: str | None = None
    status: str
    force_score: int | None = None
    note: str | None = None
    highlight_quote: str | None = None
    quote_speaker: str | None = None
    created_at: datetime
    updated_at: datetime


class MediaSource(BaseModel):
    quality: str
    status: str
    width: int | None = None
    height: int | None = None
    url: str | None = None
    filename: str | None = None
    error: str | None = None


class MediaManifest(BaseModel):
    schema_version: str
    status: str
    sources: list[MediaSource] = Field(default_factory=list)
    source_timeline: dict[str, Any] | None = None


class AnalysisDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skater_id: str | None = None
    session_id: str | None = None
    skater_name: str | None = None
    skill_category: str | None = None
    action_type: str
    action_subtype: str | None = None
    analysis_profile: str | None = None
    retry_from_stage: str | None = None
    pipeline_version: str | None = None
    video_path: str
    media_manifest: MediaManifest | None = None
    status: str
    vision_raw: str | None = None
    vision_structured: dict[str, Any] | None = None
    vision_path_a: dict[str, Any] | None = None
    vision_path_b: dict[str, Any] | None = None
    cross_validation: dict[str, Any] | None = None
    report: StructuredReport | dict[str, Any] | None = None
    pose_data: dict[str, Any] | None = None
    bio_data: dict[str, Any] | None = None
    frame_motion_scores: dict[str, Any] | None = None
    video_temporal_diagnostics: dict[str, Any] | None = None
    processing_timings: dict[str, float] | None = None
    processing_logs: list[AnalysisLogEntry] = Field(default_factory=list)
    target_lock: dict[str, Any] | None = None
    target_lock_status: str | None = None
    action_window_start: float | None = None
    action_window_end: float | None = None
    manual_action_window_start: float | None = None
    manual_action_window_end: float | None = None
    source_duration_sec: float | None = None
    input_window_start_sec: float | None = None
    input_window_end_sec: float | None = None
    input_window_duration_sec: float | None = None
    input_window_mode: str | None = None
    input_window_truncated: bool = False
    input_window_reason: str | None = None
    source_fps: float | None = None
    is_slow_motion: bool = False
    force_score: int | None = None
    skill_node_id: str | None = None
    auto_unlocked_skill: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    error_message: str | None = None
    note: str | None = None
    facts_authority: str | None = None
    facts_schema_version: str | None = None
    source_fact_hash: str | None = None
    source_fact_revision: int | None = None
    source_pipeline_fingerprint: str | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisAutoEvalSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    created_at: datetime
    pipeline_version: str | None = None
    analysis_profile: str | None = None
    action_type: str
    auto_eval: dict[str, Any] | None = None
    key_frame_candidates: dict[str, Any] | None = None
    fusion_diagnostics: list[str] = Field(default_factory=list)


class DebugRunCreateResponse(BaseModel):
    id: str
    status: str


class DebugRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    mode: str
    source_type: str
    analysis_id: str | None = None
    action_type: str
    action_subtype: str | None = None
    analysis_profile: str | None = None
    note: str | None = None
    status: str
    summary: dict[str, Any] | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class DebugRunDetail(DebugRunSummary):
    video_path: str | None = None
    result_json: dict[str, Any] | None = None
    error_detail: str | None = None


class NoteUpdateRequest(BaseModel):
    note: str | None = None


class SkaterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    display_name: str
    avatar_emoji: str
    avatar_type: str
    birth_year: int
    current_level: str
    avatar_level: int
    total_xp: int
    current_streak: int
    longest_streak: int
    last_active_date: str | None = None
    is_default: bool
    level: str | None = None
    notes: str | None = None
    created_at: datetime


class ProgressPoint(BaseModel):
    id: str
    created_at: datetime
    skater_name: str | None = None
    action_type: str
    action_subtype: str | None = None
    force_score: int
    note: str | None = None
    comments: str | None = None
    summary: str


class ProgressStats(BaseModel):
    total_count: int
    latest_score: int | None = None
    best_score: int | None = None
    recent_five_average: float | None = None


class ProgressResponse(BaseModel):
    points: list[ProgressPoint]
    stats: ProgressStats


class ComparisonChange(BaseModel):
    category: str
    before_severity: Severity | None = None
    after_severity: Severity | None = None
    description: str


class CompareSummary(BaseModel):
    improved: list[ComparisonChange] = Field(default_factory=list)
    added: list[ComparisonChange] = Field(default_factory=list)
    unchanged: list[ComparisonChange] = Field(default_factory=list)


class CompareDelta(BaseModel):
    key: str
    label: str
    before: float | int | None = None
    after: float | int | None = None
    delta: float | int | None = None
    unit: str | None = None
    trend: str = "unavailable"
    available: bool = False


class CompareKeyframeSide(BaseModel):
    frame_id: str | None = None
    frame_url: str | None = None
    timestamp: float | None = None
    confidence: float | None = None
    source: str | None = None
    phase_label: str | None = None
    selection_reason: str | None = None
    pre_refine_timestamp: float | None = None
    refinement_method: str | None = None
    refinement_delta_sec: float | None = None
    quality_flags: list[str] = Field(default_factory=list)
    available: bool = False
    missing_reason: str | None = None
    source_frame_index: int | None = None
    source_pts: float | None = None
    timing_status: str = "unavailable"


class CompareKeyframePair(BaseModel):
    key: str
    label: str
    before: CompareKeyframeSide
    after: CompareKeyframeSide
    delta_seconds: float | None = None
    before_offset_seconds: float | None = None
    after_offset_seconds: float | None = None
    relative_delta_seconds: float | None = None


class CompareVideoSide(BaseModel):
    analysis_id: str
    video_url: str | None = None
    available: bool = False
    missing_reason: str | None = None
    action_window_start: float | None = None
    action_window_end: float | None = None
    action_window_duration: float | None = None
    sync_start: float | None = None
    sync_duration: float | None = None
    is_slow_motion: bool = False
    source_fps: float | None = None
    source_timeline: dict[str, Any] | None = None


class CompareVideoPayload(BaseModel):
    before: CompareVideoSide
    after: CompareVideoSide
    sync_mode: str = "action_window_start"
    sync_anchor_key: str | None = None


class CompareQualityPayload(BaseModel):
    before_data_quality: str | None = None
    after_data_quality: str | None = None
    before_flags: list[str] = Field(default_factory=list)
    after_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    subtype_mismatch: bool = False
    skill_mismatch: bool = False


class CompareFactEvidence(BaseModel):
    """Definition-safe provenance for an analysis comparison.

    The ordinary comparison response may still carry legacy-compatible
    presentation fields, but a V2 result is interpreted exclusively from this
    envelope.  Excluded entries are retained so an unavailable/conflicting or
    cross-definition claim is never mistaken for a zero delta.
    """

    schema_version: str = "analysis-fact-comparison.v2"
    left_authority: str | None = None
    right_authority: str | None = None
    left_source_fact_hash: str | None = None
    right_source_fact_hash: str | None = None
    left_source_fact_revision: int | None = None
    right_source_fact_revision: int | None = None
    left_source_pipeline_fingerprint: str | None = None
    right_source_pipeline_fingerprint: str | None = None
    event_pairs: list[dict[str, Any]] = Field(default_factory=list)
    deltas: list[dict[str, Any]] = Field(default_factory=list)
    excluded: list[dict[str, Any]] = Field(default_factory=list)
    authority_mismatch: bool = False
    profile_mismatch: bool = False


class CompareVideoAiObservation(BaseModel):
    key: str
    label: str
    before: str | None = None
    after: str | None = None


class CompareVideoAiChange(BaseModel):
    category: str
    direction: str = "uncertain"
    description: str
    confidence: float | None = None


class CompareVideoAiReport(BaseModel):
    status: str
    provider: str | None = None
    model: str | None = None
    before_confidence: float | None = None
    after_confidence: float | None = None
    before_data_quality: str | None = None
    after_data_quality: str | None = None
    average_confidence: float | None = None
    summary: str
    observations: list[CompareVideoAiObservation] = Field(default_factory=list)
    changes: list[CompareVideoAiChange] = Field(default_factory=list)
    training_focus: str
    caveats: list[str] = Field(default_factory=list)


class AnalysisCompareResponse(BaseModel):
    analysis_a: AnalysisDetail
    analysis_b: AnalysisDetail
    score_delta: int | None = None
    summary: CompareSummary
    subscore_deltas: list[CompareDelta] = Field(default_factory=list)
    metric_deltas: list[CompareDelta] = Field(default_factory=list)
    keyframe_compare: list[CompareKeyframePair] = Field(default_factory=list)
    video_compare: CompareVideoPayload | None = None
    quality: CompareQualityPayload | None = None
    ai_narrative: str | None = None
    video_ai_report: CompareVideoAiReport | None = None
    fact_comparison: CompareFactEvidence | None = None


class AnalysisComparisonCreateRequest(BaseModel):
    id_a: str
    id_b: str


class AnalysisComparisonSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_a_id: str
    analysis_b_id: str
    skater_id: str | None = None
    skater_name: str | None = None
    action_type: str
    status: str
    score_delta: int | None = None
    ai_narrative: str | None = None
    error_message: str | None = None
    video_ai_status: str | None = None
    before_created_at: datetime | None = None
    after_created_at: datetime | None = None
    before_score: int | None = None
    after_score: int | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisComparisonDetail(AnalysisComparisonSummary):
    result: AnalysisCompareResponse | None = None
    video_ai_json: dict[str, Any] | None = None


class TrainingPlanSession(BaseModel):
    id: str
    title: str
    duration: str
    description: str
    is_office_trainable: bool
    completed: bool = False
    related_issue: str | None = None
    parent_tip: str | None = None


class TrainingDay(BaseModel):
    day: int
    theme: str
    sessions: list[TrainingPlanSession] = Field(default_factory=list)


class TrainingPlanPayload(BaseModel):
    title: str
    focus_skill: str
    days: list[TrainingDay]
    generation_source: str | None = None
    generation_status: str | None = None
    generation_note: str | None = None


class TrainingPlanDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    skater_id: str
    plan_json: TrainingPlanPayload
    created_at: datetime
    facts_authority: str | None = None
    facts_schema_version: str | None = None
    source_fact_hash: str | None = None
    source_fact_revision: int | None = None
    source_pipeline_fingerprint: str | None = None
    generation_fingerprint: str | None = None
    source_updated: bool = False


class TrainingPlanRevisionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    analysis_id: str
    skater_id: str
    revision: int
    plan_json: TrainingPlanPayload
    facts_authority: str | None = None
    facts_schema_version: str | None = None
    source_fact_hash: str | None = None
    source_fact_revision: int | None = None
    source_pipeline_fingerprint: str | None = None
    generation_fingerprint: str | None = None
    created_at: datetime


class UpdatePlanSessionRequest(BaseModel):
    completed: bool


class ExtendPlanBody(BaseModel):
    completed_days: list[int] = Field(default_factory=list)


class ArchiveStats(BaseModel):
    total_records: int
    recent_7days: int
    current_streak: int
    monthly_sessions: int


class ArchiveTimelineEntry(BaseModel):
    id: str
    created_at: datetime
    entry_type: str
    status: str
    skater_id: str | None = None
    skater_name: str | None = None
    skater_avatar_type: str | None = None
    skater_avatar_emoji: str | None = None
    skill_category: str | None = None
    action_type: str
    action_subtype: str | None = None
    skill_node_id: str | None = None
    force_score: int | None = None
    report_snippet: str
    analysis_id: str
    session_id: str | None = None
    session_date: date | None = None
    session_location: str | None = None
    session_type: str | None = None
    session_duration_minutes: int | None = None


class ArchiveResponse(BaseModel):
    stats: ArchiveStats
    timeline: list[ArchiveTimelineEntry]
    limit: int | None = None
    offset: int = 0
    has_more: bool = False


class GrowthFocus(BaseModel):
    label: str
    source_analysis_id: str
    quality: str
    # Populated when no confirmed, aggregation-eligible fact could support
    # the focus.  The public growth surface uses this to explain exclusion
    # without exposing raw legacy/V2 payloads.
    excluded_reason: str | None = None


class GrowthMilestoneEvent(BaseModel):
    id: str
    occurred_at: datetime
    type: str = "skill_unlock"
    title: str
    note: str | None = None
    verification: str
    source_skill_id: str
    source_analysis_ids: list[str] = Field(default_factory=list)
    evidence_quality: str = "persisted"


class GrowthSummaryResponse(BaseModel):
    schema_version: int = 1
    skater_id: str
    as_of: datetime
    lesson_count: int
    completed_analysis_count: int
    current_month_analysis_count: int
    milestone_count: int
    latest_analysis_id: str | None = None
    current_focus: GrowthFocus | None = None
    metric_definitions: dict[str, str]
    recent_milestones: list[GrowthMilestoneEvent] = Field(default_factory=list)


class TrainingSessionBase(BaseModel):
    session_date: date
    location: str = "冰场"
    session_type: str = "上冰"
    duration_minutes: int | None = None
    coach_present: bool = False
    note: str | None = None


class TrainingSessionCreate(TrainingSessionBase):
    pass


class TrainingSessionUpdate(BaseModel):
    session_date: date | None = None
    location: str | None = None
    session_type: str | None = None
    duration_minutes: int | None = None
    coach_present: bool | None = None
    note: str | None = None


class AnalysisSessionUpdateRequest(BaseModel):
    session_id: str | None = None


class TrainingSessionPublic(TrainingSessionBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skater_id: str
    created_at: datetime


class TrainingSessionDetail(TrainingSessionPublic):
    analyses: list[AnalysisListItem] = Field(default_factory=list)


class PoseFrameKeypoint(BaseModel):
    id: int
    name: str
    x: float
    y: float
    z: float
    visibility: float


class TargetBBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class PoseFrame(BaseModel):
    frame: str
    keypoints: list[PoseFrameKeypoint]
    target_bbox: TargetBBox | None = None
    tracking_confidence: float | None = None
    tracking_state: str | None = None
    tracker_state: str | None = None
    tracker_lost_frames: int | None = None
    pose_candidates: list[dict[str, Any]] = Field(default_factory=list)


class TargetCandidate(BaseModel):
    id: str
    bbox: TargetBBox
    confidence: float
    source: str
    quality_flags: list[str] = Field(default_factory=list)
    support_count: int | None = None
    support_frame_count: int | None = None
    support_confidence: float | None = None
    anchor_frame: str | None = None
    anchor_index: int | None = None
    support_anchor_frames: list[str] = Field(default_factory=list)
    support_center_span: float | None = None
    support_avg_area: float | None = None
    support_motion_anchor_hits: int | None = None
    multiperson_ambiguous_frame_count: int | None = None
    multiperson_competitor_count: int | None = None
    multiperson_same_anchor_competitor_count: int | None = None
    multiperson_selected_pair_frame_count: int | None = None
    multiperson_selected_pair_competitor_count: int | None = None
    multiperson_other_frame_ambiguous_count: int | None = None
    multiperson_nearest_center_distance: float | None = None
    multiperson_max_competitor_confidence: float | None = None
    multiperson_ignored_fragment_count: int | None = None


class TargetPreviewResponse(BaseModel):
    analysis_id: str
    status: str
    auto_candidate_id: str | None = None
    lock_confidence: float
    preview_frame: str | None = None
    preview_frame_url: str | None = None
    preview_frame_index: int | None = None
    candidates: list[TargetCandidate] = Field(default_factory=list)
    target_lock_status: str | None = None


class TargetLockRequest(BaseModel):
    candidate_id: str | None = None
    x: float | None = None
    y: float | None = None
    manual_bbox: TargetBBox | None = None


class DebugGoldenLabelRequest(BaseModel):
    skater_id: str | None = Field(default=None, max_length=120)
    action_type: str | None = Field(default=None, max_length=40)
    action_subtype: str | None = Field(default=None, max_length=80)
    analysis_profile: str | None = Field(default=None, max_length=40)
    stratum: str = Field(default="unspecified", max_length=80)
    fps: float | None = None
    keyframes: dict[str, float | None] = Field(default_factory=dict)
    target_bboxes: dict[str, TargetBBox] = Field(default_factory=dict)
    tracking_anchors: list["GoldenTrackingAnchor"] = Field(default_factory=list)
    action_window_start_sec: float | None = None
    action_window_end_sec: float | None = None
    expected_review_flags: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=4000)


class GoldenKeyframe(BaseModel):
    timestamp_sec: float
    source_frame_id: str | None = None


class GoldenTrackingAnchor(BaseModel):
    anchor_id: str | None = None
    timestamp_sec: float
    source_frame_id: str
    bbox: TargetBBox


class GoldenOverrideApplyRequest(BaseModel):
    debug_run_id: str
    label_revision: int = Field(ge=1)


class GoldenOverrideApplyResponse(BaseModel):
    analysis_id: str
    status: str
    retry_from_stage: str
    applied_revision: int
    report_path: str
    already_processing: bool = False


class DebugGoldenLabelResponse(DebugGoldenLabelRequest):
    id: str
    video_path: str | None = None
    prediction_path: str | None = None
    label_path: str | None = None
    manifest_path: str | None = None
    source_type: str | None = None
    source_analysis_id: str | None = None
    debug_run_mode: str | None = None
    debug_run_status: str | None = None
    manifest_schema_version: int = 1
    exists: bool = False
    revision: int = 0
    applied_revision: int | None = None
    applied_at: str | None = None
    label_quality_flags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class PoseResponse(BaseModel):
    connections: list[list[int]]
    frames: list[PoseFrame]
    frame_urls: dict[str, str]
    frame_timestamps: dict[str, float] = Field(default_factory=dict)
    effective_fps: float | None = None
    pose_diagnostics: dict[str, Any] | None = None
    source_timeline: dict[str, Any] | None = None


class ProviderBase(BaseModel):
    slot: str
    name: str
    provider: str
    base_url: str
    model_id: str
    vision_model: str | None = None
    notes: str | None = None


class ProviderCreate(ProviderBase):
    api_key: str


class ProviderUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model_id: str | None = None
    vision_model: str | None = None
    api_key: str | None = None
    notes: str | None = None


class ProviderPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slot: str
    name: str
    provider: str
    base_url: str
    model_id: str
    vision_model: str | None = None
    api_key: str
    is_active: bool
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    v2_role: str
    fingerprint: str


class ProviderMetricPublic(BaseModel):
    provider: str
    sample_count: int
    json_valid_rate: float
    avg_effective_weight: float
    conflict_rate: float
    failure_rate: float
    recommendation: str | None = None


class ProviderTestResponse(BaseModel):
    success: bool
    detail: str


class VisionVoteConfig(BaseModel):
    primary_provider_id: str | None = None
    secondary_provider_id: str | None = None
    scope: str = "legacy_vision_only"
    applies_to_v2_fusion: bool = False


class ApiConnectionTestResponse(BaseModel):
    status: str
    latency_ms: int | None = None
    error_code: str | None = None
    message: str | None = None
    failed_stage: str | None = None


class PoseRuntimeStatusResponse(BaseModel):
    mode: str
    configured: bool
    model_path: str | None = None
    model_exists: bool
    num_poses: int
    reason: str
    source_method: str | None = None
    model_hash: str | None = None
    model_version: str | None = None
    legacy_use: bool = True
    v2_use: bool = False
    dependent_artifact_invalidation: str | None = None
    active: bool = True
    fallback: bool = False


class PersonTrackerRuntimeStatusResponse(BaseModel):
    mode: str
    configured: bool
    model_path: str
    model_exists: bool
    mounted_default_path: str
    mounted_default_exists: bool
    env_var: str
    source: str
    reason: str
    dependencies_ready: bool = False
    dependency_status: dict[str, bool] = Field(default_factory=dict)
    dependency_errors: dict[str, str] = Field(default_factory=dict)


class BackupFilePublic(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime


class BackupListResponse(BaseModel):
    items: list[BackupFilePublic] = Field(default_factory=list)


class BackupCreateRequest(BaseModel):
    label: str | None = None


class BackupRestoreRequest(BaseModel):
    filename: str


class BackupActionResponse(BaseModel):
    success: bool = True
    detail: str
    filename: str


class HealthResponse(BaseModel):
    status: str


class PinPayload(BaseModel):
    pin: str = Field(min_length=4, max_length=6)


class HasPinResponse(BaseModel):
    has_pin: bool
    pin_length: int = 4


class VerifyPinResponse(BaseModel):
    valid: bool


class ChangePinRequest(BaseModel):
    old_pin: str = Field(min_length=4, max_length=6)
    new_pin: str = Field(min_length=4, max_length=6)


class ChangePinResponse(BaseModel):
    success: bool
    reason: str | None = None


class SkillNodePublic(BaseModel):
    id: str
    chapter: str
    chapter_order: int
    stage: int
    stage_name: str
    group_name: str
    name: str
    emoji: str
    action_type: str | None = None
    xp: int
    requires: list[str] = Field(default_factory=list)
    status: str
    attempt_count: int = 0
    best_score: int = 0
    unlocked_by: str | None = None
    unlock_config: dict[str, Any] | None = None
    is_parent_only: bool = False
    unlocked_at: datetime | None = None
    unlock_source: str | None = None
    unlock_note: str | None = None
    last_analysis_score: int | None = None


class SkillMutationResponse(BaseModel):
    success: bool = True
    skill: SkillNodePublic


class SkillRecentResponse(BaseModel):
    items: list[SkillNodePublic] = Field(default_factory=list)


class LearningPathGroupResponse(BaseModel):
    group_name: str
    nodes_total: int
    nodes_unlocked: int
    nodes: list[SkillNodePublic] = Field(default_factory=list)


class LearningPathStageResponse(BaseModel):
    stage: int
    name: str
    description: str
    progress_pct: int
    counts: dict[str, int] = Field(default_factory=dict)
    groups: list[LearningPathGroupResponse] = Field(default_factory=list)


class LearningPathResponse(BaseModel):
    stages: list[LearningPathStageResponse] = Field(default_factory=list)
    current_stage: int


class SkaterUpdateRequest(BaseModel):
    display_name: str | None = None
    avatar_emoji: str | None = None
    birth_year: int | None = None


class SkillUnlockRequest(BaseModel):
    note: str | None = None


class SystemInfoResponse(BaseModel):
    version: str
    db_size_bytes: int
    uploads_size_bytes: int


class StorageStatsResponse(BaseModel):
    uploads_mb: float
    archive_mb: float
    backups_mb: float
    total_mb: float
    archived_count: int


class SnowballMemoryBase(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)
    category: str = Field(default="其他", min_length=1, max_length=32)
    is_pinned: bool = False
    expires_at: datetime | str | None = None


class SnowballMemoryCreate(SnowballMemoryBase):
    pass


class SnowballMemoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=32)
    is_pinned: bool | None = None
    expires_at: datetime | str | None = None


class SnowballMemoryPinUpdate(BaseModel):
    is_pinned: bool | None = None


class SnowballMemoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skater_id: str
    title: str
    content: str
    category: str
    is_pinned: bool
    expires_at: datetime | None = None
    is_expired: bool = False
    created_at: datetime
    updated_at: datetime
    facts_authority: str | None = None
    facts_schema_version: str | None = None
    source_fact_hash: str | None = None
    source_fact_revision: int | None = None
    source_pipeline_fingerprint: str | None = None
    generation_fingerprint: str | None = None
    facts_authority: str | None = None
    facts_schema_version: str | None = None
    source_fact_hash: str | None = None
    source_fact_revision: int | None = None
    source_pipeline_fingerprint: str | None = None
    generation_fingerprint: str | None = None


class MemorySuggestionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    skater_id: str
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    is_reviewed: bool
    created_at: datetime
    facts_authority: str | None = None
    facts_schema_version: str | None = None
    source_fact_hash: str | None = None
    source_fact_revision: int | None = None
    source_pipeline_fingerprint: str | None = None
    generation_fingerprint: str | None = None


class MemorySuggestionApplyRequest(BaseModel):
    suggestion_id: str
    accepted_indices: list[int] = Field(default_factory=list)


class SnowballChatMessage(BaseModel):
    role: str
    content: str


class SnowballChatRequest(BaseModel):
    skater_id: str | None = None
    message: str = Field(min_length=1)
    history: list[SnowballChatMessage] = Field(default_factory=list)


class SnowballChatResponse(BaseModel):
    reply: str


class MonthlyChapterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skater_id: str
    year_month: str
    revision: int
    title: str = ""
    parent_revision_id: str | None = None
    status: str
    fact_snapshot: dict[str, Any]
    source_hash: str
    generated_payload: dict[str, Any] | None = None
    draft_text: str | None = None
    final_text: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    representative_frames: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    deleted_at: datetime | None = None


class MonthlyChapterPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    final_text: str | None = Field(default=None, max_length=2400)


class MonthlyChapterRevisionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    final_text: str | None = Field(default=None, max_length=2400)


class AnnualCollectionCreateRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=1)
    milestone_ids: list[str] = Field(default_factory=list)
    title: str | None = Field(default=None, max_length=200)


class AnnualCollectionRevisionRequest(AnnualCollectionCreateRequest):
    pass


class AnnualCollectionPreview(BaseModel):
    snapshot: dict[str, Any]
    source_hash: str
    coverage: dict[str, int]


class AnnualMilestonePublic(BaseModel):
    id: str
    title: str
    occurred_at: datetime
    note: str | None = None
    verification: str


class AnnualCollectionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skater_id: str
    year: int
    revision: int
    parent_revision_id: str | None = None
    status: str
    title: str
    selected_chapter_ids: list[str] = Field(default_factory=list)
    selected_milestone_ids: list[str] = Field(default_factory=list)
    snapshot: dict[str, Any]
    source_hash: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class AnnualExportPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    collection_id: str
    status: str
    renderer_version: str
    asset_relative_path: str | None = None
    file_sha256: str | None = None
    page_count: int | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
