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
    data_quality: str = "partial"


class AnalysisUploadResponse(BaseModel):
    id: str
    status: str


class AnalysisRetryResponse(BaseModel):
    message: str


class AnalysisListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skater_id: str | None = None
    session_id: str | None = None
    skater_name: str | None = None
    skill_category: str | None = None
    action_type: str
    status: str
    force_score: int | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skater_id: str | None = None
    session_id: str | None = None
    skater_name: str | None = None
    skill_category: str | None = None
    action_type: str
    video_path: str
    status: str
    vision_raw: str | None = None
    vision_structured: dict[str, Any] | None = None
    report: StructuredReport | dict[str, Any] | None = None
    pose_data: dict[str, Any] | None = None
    bio_data: dict[str, Any] | None = None
    frame_motion_scores: dict[str, Any] | None = None
    action_window_start: float | None = None
    action_window_end: float | None = None
    source_fps: float | None = None
    is_slow_motion: bool = False
    force_score: int | None = None
    skill_node_id: str | None = None
    auto_unlocked_skill: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    error_message: str | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime


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
    action_type: str
    force_score: int
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


class AnalysisCompareResponse(BaseModel):
    analysis_a: AnalysisDetail
    analysis_b: AnalysisDetail
    score_delta: int
    summary: CompareSummary


class TrainingPlanSession(BaseModel):
    id: str
    title: str
    duration: str
    description: str
    is_office_trainable: bool
    completed: bool = False


class TrainingDay(BaseModel):
    day: int
    theme: str
    sessions: list[TrainingPlanSession] = Field(default_factory=list)


class TrainingPlanPayload(BaseModel):
    title: str
    focus_skill: str
    days: list[TrainingDay]


class TrainingPlanDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    skater_id: str
    plan_json: TrainingPlanPayload
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
    skill_category: str | None = None
    action_type: str
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


class PoseFrame(BaseModel):
    frame: str
    keypoints: list[PoseFrameKeypoint]


class PoseResponse(BaseModel):
    connections: list[list[int]]
    frames: list[PoseFrame]
    frame_urls: dict[str, str]


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


class ProviderTestResponse(BaseModel):
    success: bool
    detail: str


class ApiConnectionTestResponse(BaseModel):
    status: str
    latency_ms: int | None = None
    error_code: str | None = None
    message: str | None = None
    failed_stage: str | None = None


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


class MemorySuggestionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    skater_id: str
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    is_reviewed: bool
    created_at: datetime


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
