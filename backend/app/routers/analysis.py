from __future__ import annotations

import logging
import asyncio
import json
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Sequence
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.database import (
    AsyncSessionLocal,
    SQLITE_WRITE_RETRY_ATTEMPTS,
    SQLITE_WRITE_RETRY_BASE_SECONDS,
    UPLOADS_DIR,
    get_session,
    is_transient_sqlite_write_error,
    run_db_read_with_retry,
    run_db_write_with_retry,
)
from app.models import Analysis, Skater, TrainingPlan, TrainingSession
from app.schemas import (
    AnalysisCompareResponse,
    AnalysisAutoEvalSnapshot,
    AnalysisDetail,
    AnalysisListItem,
    AnalysisRetryResponse,
    AnalysisSessionUpdateRequest,
    AnalysisUploadResponse,
    CompareDelta,
    CompareKeyframePair,
    CompareKeyframeSide,
    CompareQualityPayload,
    CompareSummary,
    CompareVideoPayload,
    CompareVideoSide,
    ComparisonChange,
    ExtendPlanBody,
    NoteUpdateRequest,
    ProgressPoint,
    ProgressResponse,
    ProgressStats,
    PoseResponse,
    TargetLockRequest,
    TargetPreviewResponse,
    TrainingPlanDetail,
    UpdatePlanSessionRequest,
)
from app.services.action_profiles import (
    infer_analysis_profile,
    infer_jump_subtype_evidence,
    infer_profile_from_input,
    infer_profile_hint,
    is_mixed_action_input,
    normalize_action_subtype,
)
from app.services.analysis_errors import (
    AnalysisErrorCode,
    AnalysisPipelineError,
    classify_ai_failure,
    classify_video_failure,
    friendly_error_title,
    stringify_exception,
)
from app.services.auth import get_parent_auth, validate_pin, verify_pin_hash
from app.services.auto_eval import AUTO_EVAL_VERSION, build_auto_eval_payload
from app.services.biomechanics import (
    analyze_biomechanics,
    attach_key_frame_candidates,
    sanitize_biomechanics_data,
    sync_key_frames_from_resolved_keyframes,
)
from app.services.bbox_tracker import track_bbox
from app.services.person_tracker import (
    PERSON_TRACKER_FAILED_FLAG,
    PERSON_TRACKER_FINAL_UNRECOVERED_FLAG,
    PERSON_TRACKER_MANUAL_LOCK_FALLBACK_BLOCKED_FLAG,
    PERSON_TRACKER_MANUAL_LOCK_SUPPORT_ANCHOR_BLOCKED_FLAG,
    PERSON_TRACKER_MULTIPERSON_RELOCK_INSTABILITY_RISK_FLAG,
    PERSON_TRACKER_TARGET_LOST_FLAG,
    PERSON_TRACKER_TINY_TARGET_LOW_POSE_TRACKING_RISK_FLAG,
    PERSON_TRACKER_UNAVAILABLE_FLAG,
    PersonTrackerUnavailable,
    detect_person_candidates,
    track_person_bbox_detailed,
)
from app.services.plan import PlanGenerationError, build_fallback_plan, extend_training_plan, generate_training_plan
from app.services.memory_suggest import suggest_memory_updates
from app.services.phase_smoother import smooth_phases
from app.services.pipeline_version import CURRENT_PIPELINE_VERSION
from app.services.pose import extract_pose
from app.services.llm_context import build_analysis_prompt_context
from app.services.report import apply_child_score_floor, calculate_force_score, generate_report
from app.services.skill_progress import auto_update_skill_progress
from app.services.skills import sync_skater_progress
from app.services.target_lock import (
    build_target_lock_payload,
    build_target_preview,
    candidate_matches_target_anchor,
    frame_names_from_dir,
    resolve_manual_candidate,
    select_stable_target_candidate,
    target_preview_anchor_frame_indices,
)
from app.services.video import (
    VideoInputWindow,
    VideoSamplingMetadata,
    attach_input_window_payload,
    build_video_input_window,
    build_timestamp_map,
    build_processing_frames_dir,
    build_upload_paths,
    cleanup_processing_dir,
    compute_video_sha256,
    cut_action_window_ai_clip,
    encode_frames,
    extract_motion_sampled_frames,
    extract_precise_frames_at_timestamps,
    precheck_video,
    persist_frames,
    restore_sampled_frames,
    save_upload_file,
)
from app.services.semantic_keyframe_pipeline import (
    SemanticKeyframePipelineResult,
    effective_timestamp_source,
    merge_frame_motion_payload,
    resolve_semantic_keyframe_pipeline,
    retry_video_temporal_if_needed,
    start_video_temporal_task,
    validate_semantic_keyframes_against_current_evidence,
)
from app.services.video_temporal import (
    resolved_keyframes_accept_insufficient_pose_low_visibility_fallback,
    semantic_keyframes_are_reliable,
)
from app.services.vision_dual import analyze_frames_dual, dual_path_summary
from app.services.providers import get_active_provider, request_text_completion


router = APIRouter(prefix="/api/analysis", tags=["analysis"])
plan_router = APIRouter(prefix="/api/plan", tags=["plan"])
frames_router = APIRouter(prefix="/api/frames", tags=["frames"])

VALID_ACTION_TYPES = {"跳跃", "旋转", "步法", "自由滑"}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
SUBSCORE_COMPARE_LABELS = {
    "takeoff_power": "起跳发力",
    "rotation_axis": "旋转轴心",
    "arm_coordination": "手臂配合",
    "landing_absorption": "落冰缓冲",
    "core_stability": "核心稳定",
}
JUMP_METRIC_COMPARE_LABELS = {
    "air_time_seconds": ("滞空时间", "s"),
    "estimated_height_cm": ("跳跃高度", "cm"),
    "takeoff_speed_mps": ("起跳速度", "m/s"),
    "rotation_rps": ("转速", "rev/s"),
    "estimated_rotations": ("估算周数", "圈"),
}
NON_JUMP_METRIC_LABELS = {
    "glide_stability": ("滑行稳定", "分"),
    "support_leg_stability": ("支撑腿稳定", "分"),
    "hip_shoulder_alignment": ("髋肩对齐", "分"),
    "trunk_pitch_degrees": ("躯干倾角", "°"),
}
COMPARE_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
COMPARE_SAME_VIDEO_KEYFRAME_STABILITY_SECONDS = 0.10
COMPARE_SAME_VIDEO_SCORE_STABILITY_DELTA = 1.0
COMPARE_SAME_VIDEO_SUBSCORE_STABILITY_DELTA = 1.0
COMPARE_SAME_VIDEO_METRIC_STABILITY_DELTA = 0.10
MIXED_ACTION_AUTO_LOCK_INPUT_PROFILE = "step"
SUPPORTED_VIDEO_AI_PROFILES = {"jump", "spin", "spiral", "step"}
SEMANTIC_REUSE_PROFILE_PHASES = {
    "spin": ("spin_entry", "spin_main", "spin_exit"),
    "spiral": ("spiral_entry", "spiral_hold", "spiral_exit"),
    "step": ("step_sequence",),
}
SEMANTIC_REUSE_PROFILE_REQUIRED_PHASES = {
    "spin": ("spin_entry", "spin_main", "spin_exit"),
    "spiral": ("spiral_hold",),
    "step": ("step_sequence",),
}
MIXED_ACTION_JUMP_RECOVERY_MAX_ROTATION_SIGNAL = 0.12
MIXED_ACTION_JUMP_RECOVERY_MIN_RELATIVE_VERTICAL = 0.35
MIXED_ACTION_JUMP_RECOVERY_MIN_AVG_CANDIDATE_CONFIDENCE = 0.32
MIXED_ACTION_JUMP_RECOVERY_MIN_CORE_GAP_SECONDS = 0.04
MIXED_ACTION_JUMP_RECOVERY_MAX_TAL_SPAN_SECONDS = 2.50
MIXED_ACTION_JUMP_RECOVERY_REJECT_CANDIDATE_FLAGS = {
    "tal_order_invalid",
    "tal_order_unresolved",
    "tal_candidate_confidence_low",
    "tal_candidate_incomplete",
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_tiny_target_weak_geometry",
    "keyframe_candidates_excluded_unreliable_pose_frames",
    "keyframe_candidates_missing_pose",
    "keyframe_candidates_not_applicable_for_profile",
}
MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_MIN_CONFIDENCE = 0.82
MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_MAX_ROTATION_SIGNAL = 0.18
MIXED_ACTION_VIDEO_AI_NON_JUMP_OVERRIDE_STRONG_SKELETON_MIN_CONFIDENCE = 0.86
MIXED_ACTION_VIDEO_AI_NON_JUMP_OVERRIDE_STRONG_SKELETON_MIN_AIRBORNE_FRAMES = 4
MIXED_ACTION_VIDEO_AI_NON_JUMP_OVERRIDE_STRONG_SKELETON_MIN_RELATIVE_VERTICAL = 0.45
MIXED_ACTION_VIDEO_AI_NON_JUMP_OVERRIDE_STRONG_SKELETON_MAX_ROTATION_SIGNAL = 0.20
MIXED_ACTION_PROFILE_REUSE_MIN_PIPELINE_VERSION = "v5.2.246"
MIXED_ACTION_PROFILE_REUSE_LOW_VIDEO_AI_CONFIDENCE = 0.70
MIXED_ACTION_PROFILE_REUSE_MIN_MATCHES = 2
MIXED_ACTION_PROFILE_REUSE_MIN_RATIO = 0.67
MIXED_ACTION_PROFILE_REUSE_MIN_VIDEO_AI_BACKED = 1
MIXED_ACTION_PRIOR_NON_JUMP_GUARD_MIN_RATIO = 0.50
MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_MIN_CURRENT_CONFIDENCE = 0.70
MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_MIN_BACKED_COUNT = 2
MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_MIN_BEST_CONFIDENCE = 0.85
MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_WEAK_JUMP_CANDIDATE_FLAGS = {
    "tal_candidate_confidence_low",
    "tal_candidate_incomplete",
    "tal_candidate_skeleton_drifted_after_takeoff",
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_weak_geometry",
    "tal_order_unresolved",
    "keyframe_candidates_motion_fallback",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "keyframe_candidates_motion_fallback_takeoff_anchor_tail_window",
    "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
    "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
    "keyframe_candidates_motion_fallback_unreliable_pose_state",
    "tal_candidate_motion_fallback_low_precision",
}
MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_REJECT_FLAGS = {
    "video_temporal_not_high_confidence",
    "video_temporal_fallback_recommended",
    "video_temporal_low_confidence",
    "severe_visual_obstruction",
    "low_resolution",
    "frequent_occlusion",
    "motion_blur",
    "unclear_subject",
}
MIXED_ACTION_WEAK_VIDEO_AI_JUMP_FLAGS = {
    "mixed_action_video_ai_jump_profile_low_confidence",
    "mixed_action_video_ai_jump_profile_rejected_low_quality",
    "mixed_action_video_ai_jump_profile_rejected_rotation_conflict",
}
MIXED_ACTION_SKELETON_JUMP_KEEP_MIN_AVG_CANDIDATE_CONFIDENCE = 0.58
MIXED_ACTION_SKELETON_JUMP_HARD_MIN_AVG_CANDIDATE_CONFIDENCE = 0.50
MIXED_ACTION_SKELETON_JUMP_SUBTYPE_SUPPORT_MIN_CONFIDENCE = 0.50
MIXED_ACTION_MATCHING_JUMP_HISTORY_MIN_CURRENT_VIDEO_AI_CONFIDENCE = 0.70
MIXED_ACTION_SKELETON_JUMP_WEAK_CANDIDATE_FLAGS = {
    "tal_candidate_confidence_low",
    "tal_candidate_incomplete",
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_weak_geometry",
    "tal_candidate_takeoff_geometry_weak",
    "tal_candidate_landing_geometry_weak",
    "tal_order_unresolved",
}
MIXED_ACTION_SKELETON_JUMP_MAX_ROTATION_SIGNAL_WHEN_VIDEO_WEAK = 0.24
logger = logging.getLogger(__name__)
PIPELINE_STAGES = ["extract_frames", "pose", "biomechanics", "vision", "report"]
COMPARE_NARRATIVE_SYSTEM_PROMPT = (
    "你是儿童花样滑冰复盘助手。用中文给家长解释两次同动作对比，只输出自然语言，不要 Markdown。"
    "必须温和、具体、可执行；不要夸大进步，不要把低质量或低置信数据说成确定事实。"
    "如果动作子类型未知或两次细项不完全一致，请用动作大类/阶段描述，不要编造具体动作名。"
)
MAX_ANALYSIS_LOG_ENTRIES = 200
CONFIRMED_TARGET_LOCK_STATUSES = {"auto_locked", "locked", "manual"}
STALE_ANALYSIS_TIMEOUT_SECONDS = 600
VIDEO_TEMPORAL_WAIT_TIMEOUT_SECONDS = 210.0
ANALYSIS_DB_WRITE_RETRY_ATTEMPTS = SQLITE_WRITE_RETRY_ATTEMPTS
ANALYSIS_DB_WRITE_RETRY_BASE_SECONDS = SQLITE_WRITE_RETRY_BASE_SECONDS
VIDEO_IDENTITY_VERSION = "video_identity_v1"
SEMANTIC_REUSE_MIN_PIPELINE_VERSION = "v5.2.60"
SEMANTIC_REUSE_UNSTABLE_SOURCE_FLAGS = {
    "semantic_frame_extract_failed",
    "semantic_keyframe_core_foreground_occlusion",
    "semantic_keyframe_core_foreground_occlusion_repaired",
    "semantic_keyframes_unreliable_after_refinement",
    "semantic_keyframes_unreliable_after_visibility_check",
    "semantic_keyframes_unreliable_candidate_motion_window_conflict",
    "semantic_keyframes_unreliable_candidate_takeoff_single_conflict",
    "semantic_keyframes_unreliable_candidate_early_takeoff_conflict",
    "semantic_keyframes_unreliable_candidate_tal_conflict",
    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
    "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
    "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
    "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
    "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
    "video_temporal_quality_retry_late_drift_rejected",
    "video_temporal_quality_retry_motion_cluster_conflict",
    "video_temporal_quality_retry_rejected",
    "video_temporal_quality_retry_skeleton_tal_conflict",
    "video_temporal_quality_retry_skeleton_tal_conflict_rejected",
    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
}
SEMANTIC_REUSE_LONG_UNRESOLVED_ALLOWED_SOURCE_FLAGS = {
    "semantic_keyframe_core_foreground_occlusion_repaired",
    "video_temporal_quality_retry_rejected",
}
SEMANTIC_REUSE_VISUAL_PROMOTION_ALLOWED_SOURCE_FLAGS = {
    "semantic_keyframes_unreliable_after_refinement",
    "semantic_keyframes_unreliable_candidate_tal_conflict",
    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
    "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
    "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
    "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
    "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
    "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
}
SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_REQUIRED_SOURCE_FLAGS = {
    "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry",
    "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
    "semantic_keyframes_unreliable_after_refinement",
    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
    "video_temporal_quality_retry_motion_cluster_conflict",
}
SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_ALLOWED_SOURCE_FLAGS = {
    "semantic_keyframes_unreliable_after_refinement",
    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
    "video_temporal_quality_retry_motion_cluster_conflict",
    "video_temporal_quality_retry_rejected",
}
SEMANTIC_REUSE_PHASE_RANGE_LATE_REANCHOR_SOURCE_FLAGS = {
    "semantic_keyframes_phase_range_late_reanchored",
    "video_temporal_resolver_phase_range_late_reanchored",
    "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
    "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor",
}
SEMANTIC_REUSE_FOREGROUND_OCCLUSION_REPAIRED_ALLOWED_SOURCE_FLAGS = {
    "semantic_keyframe_core_foreground_occlusion_repaired",
    "video_temporal_quality_retry_rejected",
    "video_temporal_quality_retry_skeleton_tal_conflict",
}
SEMANTIC_REUSE_INSUFFICIENT_POSE_LOW_VISIBILITY_ALLOWED_SOURCE_FLAGS = {
    "video_temporal_quality_retry_motion_cluster_conflict",
    "video_temporal_quality_retry_rejected",
}
SEMANTIC_REUSE_DEGRADED_SEMANTIC_LOW_VISIBILITY_ALLOWED_SOURCE_FLAGS = {
    "semantic_keyframes_unreliable_after_refinement",
    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
    "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
    "video_temporal_quality_retry_rejected",
}
SEMANTIC_REUSE_DEGRADED_SEMANTIC_LOW_VISIBILITY_ACCEPTED_FLAGS = {
    "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_candidate_tal_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_reuse_candidate_conflict_ignored_insufficient_pose_low_visibility_fallback",
}
SEMANTIC_REUSE_DEGRADED_SEMANTIC_LOW_VISIBILITY_MIN_SOURCE_CONFIDENCE = 0.55
SEMANTIC_REUSE_DEGRADED_SEMANTIC_LOW_VISIBILITY_MIN_PHASE_CONFIDENCE = 0.50
SEMANTIC_REUSE_CLEAN_VIDEO_TAL_MIN_SOURCE_CONFIDENCE = 0.85
SEMANTIC_REUSE_CLEAN_VIDEO_TAL_MIN_PHASE_CONFIDENCE = 0.85
SEMANTIC_REUSE_CLEAN_VIDEO_TAL_MIN_TAL_SPAN_SEC = 0.25
SEMANTIC_REUSE_CLEAN_VIDEO_TAL_MAX_TAL_SPAN_SEC = 1.50
SEMANTIC_REUSE_CLEAN_VIDEO_TAL_LATE_CANDIDATE_MIN_SHIFT_SEC = 0.75
SEMANTIC_REUSE_CLEAN_VIDEO_TAL_LATE_CANDIDATE_MAX_CONFIDENCE = 0.40
SEMANTIC_REUSE_SPARSE_TRACK_STITCHED_REQUIRED_CANDIDATE_FLAGS = {
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_unreliable_sparse_track_stitch",
}
SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_SOURCE_CONFIDENCE = 0.75
SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_PHASE_CONFIDENCE = 0.70
SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_ACTION_CONFIDENCE = 0.75
SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_TAL_SPAN_SEC = 0.25
SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC = 1.50
SEMANTIC_REUSE_FOREGROUND_OCCLUSION_REPAIRED_MAX_SUPPORTED_MEAN_DELTA_SEC = 0.50
SEMANTIC_REUSE_FOREGROUND_OCCLUSION_REPAIRED_MAX_SUPPORTED_DELTA_SEC = 0.75
SEMANTIC_REUSE_SOURCE_PENALTY_FLAGS = {
    "semantic_keyframe_refinement_order_rejected",
    "semantic_keyframe_refinement_phase_rejected",
}
SEMANTIC_REUSE_CURRENT_CANDIDATE_MIN_SUPPORTED_KEYS = 2
SEMANTIC_REUSE_POSE_SUPPORT_MIN_VISIBILITY = 0.25
SEMANTIC_REUSE_LOW_VISIBILITY_MAX_POSE_VISIBILITY = 0.08
SEMANTIC_REUSE_MISSING_DELTA_SECONDS = 999.0
SEMANTIC_REUSE_LONG_UNRESOLVED_MOTION_FALLBACK_MIN_TAL_SPAN_SEC = 2.20
SEMANTIC_REUSE_POSE_SIGNAL_COMPONENTS = {
    "knee_angle_change",
    "knee_extension",
    "com_ascent",
    "ankle_return",
    "knee_absorption",
    "com_descent",
}
SEMANTIC_REUSE_RANKING_UNRELIABLE_CANDIDATE_FLAGS = {
    "keyframe_candidates_motion_fallback",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "keyframe_candidates_motion_fallback_takeoff_anchor_tail_window",
    "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
    "tal_candidate_motion_fallback_low_precision",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "tal_candidate_motion_fallback_tail_window",
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_takeoff_apex_gap_unreliable",
    "tal_candidate_takeoff_apex_gap_compressed",
    "tal_candidate_apex_landing_gap_unreliable",
    "tal_candidate_apex_landing_gap_compressed",
    "tal_candidate_core_gap_compressed",
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_unreliable_sparse_track_stitch",
    "tal_candidate_motion_window_occlusion_contaminated",
    "tal_candidate_motion_window_unreliable_tracker_state",
}
SEMANTIC_REUSE_ACCEPTED_SOURCE_CANDIDATE_CONFLICT_FLAGS = {
    "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_takeoff_anchor_fallback",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_early_takeoff_anchor_fallback",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_early_candidate_approach_window",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_takeoff_anchor_phase_shift",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_early_approach_motion_peak",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_low_visibility_no_pose_support",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_compressed_candidate",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_weak_candidate",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_weak_candidate",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_weak_geometry_candidate",
}
IN_PROGRESS_ANALYSIS_STATUSES = {
    "pending",
    "processing",
    "extracting_frames",
    "analyzing",
    "generating_report",
}


def _target_lock_has_manual_review_flag(target_lock: dict[str, Any] | None) -> bool:
    if not isinstance(target_lock, dict):
        return False
    flags = target_lock.get("quality_flags")
    if not isinstance(flags, list):
        return False
    return any("_manual_review" in str(flag) for flag in flags)


def _is_confirmed_target_lock(target_lock: dict[str, Any] | None) -> bool:
    if not isinstance(target_lock, dict):
        return False
    status = str(target_lock.get("status") or "")
    if status in {"locked", "manual"}:
        return True
    if status == "auto_locked":
        return isinstance(target_lock.get("selected_bbox"), dict) and not _target_lock_has_manual_review_flag(target_lock)
    return False


def _sampling_metadata_from_saved(
    *,
    action_window_start: float,
    action_window_end: float,
    source_fps: float,
    is_slow_motion: bool,
    motion_scores: dict[str, object] | None = None,
):
    from app.services.video import MAX_SAMPLED_FRAMES, NORMAL_PLAYBACK_FPS, VideoSamplingMetadata

    selected = motion_scores.get("selected") if isinstance(motion_scores, dict) else None
    if isinstance(selected, list) and len(selected) >= 2:
        sample_count = len(selected)
    elif isinstance(motion_scores, dict):
        sample_count = int(motion_scores.get("sample_count", 0) or MAX_SAMPLED_FRAMES)
    else:
        sample_count = MAX_SAMPLED_FRAMES
    slow_motion_scale = max(source_fps / NORMAL_PLAYBACK_FPS, 1.0) if is_slow_motion and source_fps > 0 else 1.0
    video_duration = max(action_window_end - action_window_start, 1e-6)
    window_seconds = video_duration / slow_motion_scale
    window_start_sec = action_window_start / slow_motion_scale
    # 设计说明: 旧任务重试没有 effective_fps 持久字段，只能从已保存动作窗口和采样帧数恢复。
    effective_fps = (max(sample_count, 2) - 1) / window_seconds
    return VideoSamplingMetadata(
        action_window_start=round(action_window_start, 3),
        action_window_end=round(action_window_end, 3),
        window_start_sec=round(window_start_sec, 3),
        window_end_sec=round(window_start_sec + window_seconds, 3),
        effective_fps=round(effective_fps, 3),
        source_fps=round(source_fps, 3),
        is_slow_motion=is_slow_motion,
    )


def _input_window_payload_from_motion(motion_scores: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(motion_scores, dict):
        return {}
    payload = motion_scores.get("input_window")
    if isinstance(payload, dict):
        return payload
    return {
        key: motion_scores.get(key)
        for key in (
            "source_duration_sec",
            "input_window_start_sec",
            "input_window_end_sec",
            "input_window_duration_sec",
            "input_window_mode",
            "input_window_truncated",
            "input_window_reason",
        )
        if key in motion_scores
    }


def _input_window_payload_for_saved_analysis(analysis: Analysis) -> dict[str, Any]:
    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
    payload = _input_window_payload_from_motion(motion_scores)
    if payload:
        return payload
    if analysis.action_window_start is None or analysis.action_window_end is None:
        return {}
    start = float(analysis.action_window_start)
    end = float(analysis.action_window_end)
    return {
        "source_duration_sec": None,
        "input_window_start_sec": start,
        "input_window_end_sec": end,
        "input_window_duration_sec": round(max(0.0, end - start), 3),
        "input_window_mode": "legacy_action_window",
        "input_window_truncated": False,
        "input_window_reason": "legacy_saved_analysis",
    }


def _skater_display_name(skater: Skater) -> str:
    return skater.display_name or skater.name


def _elapsed_seconds(start_time: float) -> float:
    return round(time.monotonic() - start_time, 2)


async def _provider_for_slot(slot: str, fallback_slot: str = "vision"):
    try:
        return await get_active_provider(slot)
    except RuntimeError:
        if slot == fallback_slot:
            raise
        logger.info("Provider slot %s is not configured; falling back to %s", slot, fallback_slot)
        fallback_provider = await get_active_provider(fallback_slot)
        try:
            fallback_provider.notes = (
                f"fallback_from={slot}; "
                f"fallback_slot={fallback_slot}; "
                f"{fallback_provider.notes or ''}"
            ).strip()
        except Exception:  # noqa: BLE001
            pass
        return fallback_provider


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


MOJIBAKE_LOG_MESSAGE_MAP = {
    "åˆ†æžæµç¨‹å·²å®Œæˆã€‚": "分析流程已完成。",
    "å‘½ä¸­åŒè§†é¢‘å·²é€šè¿‡çš„è¯­ä¹‰ T/A/Lï¼Œå·²é‡æŠ½å½“å‰åˆ†æžçš„ç²¾ç¡®å…³é”®å¸§ã€‚": "命中同视频已通过的语义 T/A/L，已重抽当前分析的精确关键帧。",
}


def _repair_known_mojibake(value: object) -> object:
    if not isinstance(value, str):
        return value
    return MOJIBAKE_LOG_MESSAGE_MAP.get(value, value)


def _normalize_processing_logs(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        entry["message"] = _repair_known_mojibake(entry.get("message"))
        entry["detail"] = _repair_known_mojibake(entry.get("detail"))
        normalized.append(entry)
    return normalized[-MAX_ANALYSIS_LOG_ENTRIES:]


def _provider_label(provider: Any) -> str:
    provider_name = str(getattr(provider, "provider", "") or "").strip() or "unknown"
    model = str(getattr(provider, "model_id", "") or getattr(provider, "vision_model", "") or "").strip()
    return f"{provider_name}/{model}" if model else provider_name


async def _commit_analysis_session(
    session: AsyncSession,
    *,
    context: str,
    refresh: Analysis | None = None,
) -> None:
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        if is_transient_sqlite_write_error(exc):
            logger.warning("Transient SQLite write error during %s: %s", context, exc)
        raise
    if refresh is not None:
        await session.refresh(refresh)


async def _save_analysis_fields_with_retry(
    analysis_id: str,
    values: dict[str, Any],
    *,
    context: str,
) -> bool:
    async def _write() -> bool:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return False
            for key, value in values.items():
                setattr(analysis, key, value)
            await session.commit()
            return True

    return bool(await run_db_write_with_retry(_write, context=context))


def _provider_fallback_note(provider: Any) -> str | None:
    notes = str(getattr(provider, "notes", "") or "")
    return notes if "fallback_from=" in notes else None


def _count_list(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _summarize_path_frames(frames: object) -> list[dict[str, Any]]:
    if not isinstance(frames, list):
        return []
    out: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        item = {
            "frame_id": frame.get("frame_id"),
            "phase": frame.get("phase"),
            "confidence": frame.get("confidence"),
        }
        issues = frame.get("issues")
        if isinstance(issues, list) and issues:
            item["issues"] = [str(value) for value in issues[:2]]
        positives = frame.get("positives")
        if isinstance(positives, list) and positives:
            item["positives"] = [str(value) for value in positives[:2]]
        bio_observations = frame.get("bio_observations")
        if isinstance(bio_observations, dict) and bio_observations:
            item["bio_observations"] = bio_observations
        out.append(item)
    return out


def _build_dual_path_log_detail(
    *,
    path_a: dict[str, Any] | None,
    path_b: dict[str, Any] | None,
    dual_path_meta: dict[str, Any] | None,
    provider_path_a: Any,
    provider_path_b: Any,
    raw_frame_count: int,
    annotated_frame_count: int,
    annotated_dir: Path | None,
    clip_path: Path | None,
    used_key_frames: set[str] | None,
) -> str:
    meta = dual_path_meta if isinstance(dual_path_meta, dict) else {}
    path_a_data = path_a if isinstance(path_a, dict) else {}
    path_b_data = path_b if isinstance(path_b, dict) else {}
    effective_annotated_count = int(meta.get("annotated_frame_count") or annotated_frame_count or 0)
    detail = {
        "path_a": {
            "provider": _provider_label(provider_path_a),
            "provider_fallback": _provider_fallback_note(provider_path_a),
            "mode": path_a_data.get("vision_mode") or ("video" if clip_path else "frames"),
            "input": str(clip_path) if clip_path else f"{raw_frame_count} raw frames",
            "raw_frame_count": raw_frame_count,
            "frame_analysis_count": _count_list(path_a_data.get("frame_analysis")),
            "phase_segments_count": _count_list(path_a_data.get("phase_segments")),
            "path_desc": path_a_data.get("path_desc"),
            "action_phase_summary": path_a_data.get("action_phase_summary"),
            "overall_raw_text": path_a_data.get("overall_raw_text"),
            "frame_analysis": _summarize_path_frames(path_a_data.get("frame_analysis")),
        },
        "path_b": {
            "provider": _provider_label(provider_path_b),
            "provider_fallback": _provider_fallback_note(provider_path_b),
            "input": f"{effective_annotated_count} annotated frames + biomechanics",
            "raw_frame_count": raw_frame_count,
            "annotated_frame_count": effective_annotated_count,
            "annotated_dir": str(annotated_dir) if annotated_dir else None,
            "n_frames": path_b_data.get("n_frames") or effective_annotated_count,
            "key_frames": sorted(used_key_frames or set()),
            "failed": bool(path_b_data.get("error")),
            "error": path_b_data.get("error"),
            "subscores": path_b_data.get("subscores"),
            "action_phase_summary": path_b_data.get("action_phase_summary"),
            "top_issues": path_b_data.get("top_issues"),
            "top_positives": path_b_data.get("top_positives"),
            "frame_analysis": _summarize_path_frames(path_b_data.get("frame_analysis")),
        },
        "cross_validation": {
            "recommended_path": meta.get("recommended_path"),
            "overall_agreement_rate": meta.get("overall_agreement_rate"),
            "skeleton_reliability_signal": meta.get("skeleton_reliability_signal"),
            "conflict_fields": meta.get("conflict_fields"),
            "conflict_summary": meta.get("conflict_summary"),
            "weight_a": meta.get("weight_a"),
            "weight_b": meta.get("weight_b"),
        },
    }
    rendered = json.dumps(detail, ensure_ascii=False, indent=2)
    logger.info(
        "Dual-path payload | provider_a=%s provider_b=%s\n%s",
        detail["path_a"]["provider"],
        detail["path_b"]["provider"],
        rendered,
    )
    return rendered


def _auto_eval_failure_payload(exc: Exception) -> dict[str, Any]:
    return {
        "auto_eval_version": AUTO_EVAL_VERSION,
        "key_frame_order_valid": None,
        "phase_sequence_valid": None,
        "high_confidence_conflicts": [],
        "high_confidence_conflict_rate": 0.0,
        "data_quality_flags": ["auto_eval_failed"],
        "key_frame_signature": "missing",
        "phase_sequence": [],
        "phase_transition_violations": [],
        "warning": stringify_exception(exc),
    }


def _attach_auto_eval(
    cross_validation: dict[str, Any] | None,
    *,
    bio_data: dict[str, Any],
    vision_structured: dict[str, Any],
    frame_motion_scores: dict[str, Any],
    analysis_profile: str,
) -> dict[str, Any]:
    merged = dict(cross_validation or {})
    try:
        merged["auto_eval"] = build_auto_eval_payload(
            bio_data,
            vision_structured,
            frame_motion_scores,
            analysis_profile,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto-eval payload generation failed", exc_info=True)
        merged["auto_eval"] = _auto_eval_failure_payload(exc)
    return merged


def _merge_frame_motion_payload(
    motion_scores: dict[str, object],
    *,
    video_temporal: dict[str, Any] | None = None,
    resolved_keyframes: dict[str, Any] | None = None,
) -> dict[str, object]:
    return merge_frame_motion_payload(
        motion_scores,
        video_temporal=video_temporal,
        resolved_keyframes=resolved_keyframes,
    )


def _merge_quality_flags(*sources: object) -> list[str]:
    flags: list[str] = []
    for source in sources:
        values = source.get("quality_flags") if isinstance(source, dict) else source
        if not isinstance(values, list):
            continue
        for value in values:
            flag = str(value).strip()
            if flag and flag not in flags:
                flags.append(flag)
    return flags


def _initial_analysis_profile(action_type: str, action_subtype: str | None) -> str | None:
    if is_mixed_action_input(action_type, action_subtype):
        return None
    return infer_profile_from_input(action_type, action_subtype)


def _analysis_profile_hint_for_sampling(action_type: str, action_subtype: str | None, stored_profile: str | None) -> str | None:
    if stored_profile:
        return stored_profile
    if is_mixed_action_input(action_type, action_subtype):
        return MIXED_ACTION_AUTO_LOCK_INPUT_PROFILE
    return infer_profile_hint(action_type, action_subtype)


def _video_ai_action_family(video_temporal: dict[str, Any] | None) -> str | None:
    if not isinstance(video_temporal, dict):
        return None
    action_confirmation = video_temporal.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        return None
    family = str(action_confirmation.get("action_family") or "").strip().lower()
    return family if family in SUPPORTED_VIDEO_AI_PROFILES else None


def _video_ai_action_confidence_from_payload(video_temporal: dict[str, Any] | None) -> float:
    if not isinstance(video_temporal, dict):
        return 0.0
    action_confirmation = video_temporal.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        return 0.0
    value = _float_or_none(action_confirmation.get("confidence"))
    return max(0.0, min(1.0, value or 0.0))


def _video_ai_action_confidence(video_temporal: dict[str, Any] | None) -> float:
    selected, _source = _select_mixed_action_video_ai_profile_payload(video_temporal)
    return _video_ai_action_confidence_from_payload(selected)


def _select_mixed_action_video_ai_profile_payload(
    video_temporal: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(video_temporal, dict):
        return None, None

    candidates: list[tuple[dict[str, Any], str]] = [(video_temporal, "primary")]
    retry_attempt = video_temporal.get("retry_attempt")
    if isinstance(retry_attempt, dict):
        candidates.append((retry_attempt, "retry_attempt"))

    viable: list[tuple[dict[str, Any], str, str, float]] = []
    for payload, source in candidates:
        family = _video_ai_action_family(payload)
        if family is None:
            continue
        viable.append((payload, source, family, _video_ai_action_confidence_from_payload(payload)))
    if not viable:
        return None, None

    # A high-confidence retry often corrects a low-confidence first pass on
    # mixed free-skate clips. Prefer it so basic gliding/step clips are not
    # forced into jump T/A/L just because skeleton motion had a small peak.
    for payload, source, family, confidence in viable:
        if source == "retry_attempt" and family in {"spin", "spiral", "step"} and confidence >= 0.80:
            return payload, source
    best_payload, best_source, _family, _confidence = max(viable, key=lambda item: item[3])
    return best_payload, best_source


def _profile_from_video_ai_for_mixed_action(
    action_type: str,
    action_subtype: str | None,
    video_temporal: dict[str, Any] | None,
    profile_evidence: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    if not is_mixed_action_input(action_type, action_subtype):
        return None, []
    selected_video_temporal, selected_source = _select_mixed_action_video_ai_profile_payload(video_temporal)
    family = _video_ai_action_family(selected_video_temporal)
    if family is None:
        return None, []
    confidence = _video_ai_action_confidence_from_payload(selected_video_temporal)
    if family == "jump":
        video_flags = {
            str(flag)
            for flag in (selected_video_temporal.get("quality_flags") if isinstance(selected_video_temporal, dict) else []) or []
            if isinstance(flag, str)
        }
        rotation_signal = (
            _float_or_none((profile_evidence or {}).get("hip_rotation_signal"))
            if isinstance(profile_evidence, dict)
            else None
        ) or 0.0
        if confidence < MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_MIN_CONFIDENCE:
            return None, ["mixed_action_video_ai_jump_profile_low_confidence"]
        if video_flags & MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_REJECT_FLAGS:
            return None, ["mixed_action_video_ai_jump_profile_rejected_low_quality"]
        if rotation_signal > MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_MAX_ROTATION_SIGNAL:
            return None, ["mixed_action_video_ai_jump_profile_rejected_rotation_conflict"]
    elif _mixed_action_non_jump_video_ai_should_yield_to_strong_skeleton_jump(
        selected_source=selected_source,
        family=family,
        confidence=confidence,
        video_temporal=selected_video_temporal,
        profile_evidence=profile_evidence,
    ):
        return None, ["mixed_action_video_ai_non_jump_profile_rejected_strong_skeleton_jump"]
    floor = 0.50 if family == "step" else 0.60
    if confidence < floor:
        return None, ["mixed_action_video_ai_profile_low_confidence"]
    flags = ["mixed_action_profile_overridden_by_video_ai"]
    if selected_source == "retry_attempt":
        flags.append("mixed_action_profile_overridden_by_video_ai_retry_attempt")
    return family, flags


def _mixed_action_non_jump_video_ai_should_yield_to_strong_skeleton_jump(
    *,
    selected_source: str | None,
    family: str,
    confidence: float,
    video_temporal: dict[str, Any] | None,
    profile_evidence: dict[str, Any] | None,
) -> bool:
    if family not in {"spin", "spiral", "step"} or not isinstance(profile_evidence, dict):
        return False
    if not bool(profile_evidence.get("mixed_jump_gate_passed")):
        return False
    airborne_frames = int(_float_or_none(profile_evidence.get("airborne_frames_detected")) or 0)
    relative_vertical = _float_or_none(profile_evidence.get("relative_vertical_range")) or 0.0
    rotation_signal = _float_or_none(profile_evidence.get("hip_rotation_signal")) or 0.0
    strong_skeleton_jump = (
        airborne_frames >= MIXED_ACTION_VIDEO_AI_NON_JUMP_OVERRIDE_STRONG_SKELETON_MIN_AIRBORNE_FRAMES
        and relative_vertical >= MIXED_ACTION_VIDEO_AI_NON_JUMP_OVERRIDE_STRONG_SKELETON_MIN_RELATIVE_VERTICAL
        and rotation_signal <= MIXED_ACTION_VIDEO_AI_NON_JUMP_OVERRIDE_STRONG_SKELETON_MAX_ROTATION_SIGNAL
    )
    if not strong_skeleton_jump:
        return False
    if selected_source == "retry_attempt":
        if confidence >= 0.80 and _mixed_action_retry_non_jump_profile_is_coherent(video_temporal, family):
            return False
        return True
    return True


def _profile_from_resolved_video_ai_for_mixed_action(
    action_type: str,
    action_subtype: str | None,
    *,
    current_profile: str | None,
    video_temporal: dict[str, Any] | None,
    resolved_keyframes: dict[str, Any] | None,
    bio_data: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    if not is_mixed_action_input(action_type, action_subtype):
        return None, []
    selected_video_temporal, selected_source = _select_mixed_action_video_ai_profile_payload(video_temporal)
    family = _video_ai_action_family(selected_video_temporal)
    if family not in {"spin", "spiral", "step"}:
        return None, []
    normalized_current = str(current_profile or "").strip().lower()
    if family == normalized_current:
        return None, []
    resolved_flags = set(_merge_quality_flags(resolved_keyframes))
    resolver_confirmed = (
        "video_temporal_resolver_profile_overridden_by_video_ai" in resolved_flags
        and "video_temporal_resolver_coherent_profile_phases_used" in resolved_flags
    )
    retry_confirmed = (
        selected_source == "retry_attempt"
        and _video_ai_action_confidence_from_payload(selected_video_temporal) >= 0.80
        and _mixed_action_retry_non_jump_profile_is_coherent(selected_video_temporal, family)
        and _mixed_action_current_jump_profile_is_weak(normalized_current, bio_data)
    )
    if not resolver_confirmed and not retry_confirmed:
        return None, []
    flags = ["mixed_action_profile_overridden_by_video_ai_after_resolver"]
    if selected_source == "retry_attempt":
        flags.append("mixed_action_profile_overridden_by_video_ai_retry_attempt")
    return family, flags


def _mixed_action_retry_non_jump_profile_is_coherent(
    video_temporal: dict[str, Any] | None,
    family: str,
) -> bool:
    if not isinstance(video_temporal, dict):
        return False
    expected_codes = {
        "spin": {"spin_entry", "spin_main", "spin_exit"},
        "spiral": {"spiral_hold"},
        "step": {"step_sequence"},
    }.get(family)
    if not expected_codes:
        return False
    segments = video_temporal.get("phase_segments")
    if not isinstance(segments, list):
        return False
    present_codes = {
        str(segment.get("phase_code") or "").strip().lower()
        for segment in segments
        if isinstance(segment, dict)
        and bool(segment.get("valid", True))
        and _candidate_confidence(segment) >= 0.70
    }
    return expected_codes.issubset(present_codes)


def _mixed_action_current_jump_profile_is_weak(
    current_profile: str,
    bio_data: dict[str, Any] | None,
) -> bool:
    if current_profile != "jump":
        return True
    if not isinstance(bio_data, dict):
        return False
    candidates = bio_data.get("key_frame_candidates")
    if not isinstance(candidates, dict):
        return True
    candidate_items = [
        candidates.get(key) if isinstance(candidates.get(key), dict) else None
        for key in ("T", "A", "L")
    ]
    if not all(candidate and candidate.get("frame_id") for candidate in candidate_items):
        return True
    average_confidence = sum(_candidate_confidence(candidate) for candidate in candidate_items) / 3.0
    flags = {str(flag) for flag in candidates.get("quality_flags", []) if isinstance(flag, str)}
    weak_flags = {
        "tal_candidate_confidence_low",
        "tal_candidate_incomplete",
        "tal_candidate_temporal_geometry_unreliable",
        "tal_candidate_weak_geometry",
        "tal_order_unresolved",
    }
    return average_confidence < 0.45 or bool(flags & weak_flags)


def _mixed_action_jump_candidates_are_weak_for_non_jump_stability(
    bio_data: dict[str, Any] | None,
) -> bool:
    if not isinstance(bio_data, dict):
        return True
    candidates = bio_data.get("key_frame_candidates")
    if not isinstance(candidates, dict):
        return True
    candidate_items = [
        candidates.get(key) if isinstance(candidates.get(key), dict) else None
        for key in ("T", "A", "L")
    ]
    if not all(candidate and candidate.get("frame_id") for candidate in candidate_items):
        return True
    average_confidence = sum(_candidate_confidence(candidate) for candidate in candidate_items) / 3.0
    candidate_flags = {
        str(flag)
        for flag in candidates.get("quality_flags", [])
        if isinstance(flag, str)
    }
    return (
        average_confidence < MIXED_ACTION_SKELETON_JUMP_KEEP_MIN_AVG_CANDIDATE_CONFIDENCE
        or bool(candidate_flags & MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_WEAK_JUMP_CANDIDATE_FLAGS)
    )


def _mixed_action_weak_jump_can_yield_to_stable_non_jump_history(
    *,
    current_profile: str,
    video_ai_profile: str | None,
    video_ai_profile_flags: list[str],
    video_temporal: dict[str, Any] | None,
    bio_data: dict[str, Any] | None,
) -> bool:
    if str(current_profile or "").strip().lower() != "jump" or video_ai_profile is not None:
        return False
    selected_video_temporal, _selected_source = _select_mixed_action_video_ai_profile_payload(video_temporal)
    family = _video_ai_action_family(selected_video_temporal)
    confidence = _video_ai_action_confidence_from_payload(selected_video_temporal)
    if confidence < MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_MIN_CURRENT_CONFIDENCE:
        return False
    selected_quality_flags = {
        str(flag)
        for flag in (selected_video_temporal.get("quality_flags") if isinstance(selected_video_temporal, dict) else []) or []
        if isinstance(flag, str)
    }
    weak_ai_flags = set(video_ai_profile_flags or []) & (
        MIXED_ACTION_WEAK_VIDEO_AI_JUMP_FLAGS
        | {"mixed_action_video_ai_non_jump_profile_rejected_strong_skeleton_jump"}
    )
    weak_ai_evidence = bool(weak_ai_flags)
    weak_ai_evidence = weak_ai_evidence or (
        family == "jump" and confidence < MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_MIN_CONFIDENCE
    )
    weak_ai_evidence = weak_ai_evidence or bool(selected_quality_flags & MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_REJECT_FLAGS)
    if not weak_ai_evidence:
        return False
    return _mixed_action_jump_candidates_are_weak_for_non_jump_stability(bio_data)


def _mixed_action_jump_subtype_supports_skeleton_jump(
    profile_evidence: dict[str, Any] | None,
) -> bool:
    if not isinstance(profile_evidence, dict):
        return False
    subtype_evidence = profile_evidence.get("jump_subtype_evidence")
    if not isinstance(subtype_evidence, dict):
        return False
    support_scores = [
        _float_or_none(subtype_evidence.get("toe_pick_confidence")) or 0.0,
        _float_or_none(subtype_evidence.get("free_leg_swing_confidence")) or 0.0,
        _float_or_none(subtype_evidence.get("takeoff_foot_confidence")) or 0.0,
    ]
    return max(support_scores, default=0.0) >= MIXED_ACTION_SKELETON_JUMP_SUBTYPE_SUPPORT_MIN_CONFIDENCE


def _mixed_action_matching_jump_history_blocks_downgrade(
    *,
    current_profile: str,
    video_ai_profile: str | None,
    video_ai_profile_flags: list[str],
    video_temporal: dict[str, Any] | None,
    profile_evidence: dict[str, Any] | None,
    matching_profile_reuse: dict[str, Any] | None,
) -> bool:
    if str(current_profile or "").strip().lower() != "jump" or video_ai_profile is not None:
        return False
    flags = set(video_ai_profile_flags or [])
    if not bool(flags & MIXED_ACTION_WEAK_VIDEO_AI_JUMP_FLAGS):
        return False
    if "mixed_action_video_ai_jump_profile_rejected_rotation_conflict" in flags:
        return False

    selected_video_temporal, _selected_source = _select_mixed_action_video_ai_profile_payload(video_temporal)
    if _video_ai_action_family(selected_video_temporal) != "jump":
        return False
    if (
        _video_ai_action_confidence_from_payload(selected_video_temporal)
        < MIXED_ACTION_MATCHING_JUMP_HISTORY_MIN_CURRENT_VIDEO_AI_CONFIDENCE
    ):
        return False

    if not isinstance(profile_evidence, dict) or not bool(profile_evidence.get("mixed_jump_gate_passed")):
        return False
    rotation_signal = _float_or_none(profile_evidence.get("hip_rotation_signal")) or 0.0
    if rotation_signal > MIXED_ACTION_SKELETON_JUMP_MAX_ROTATION_SIGNAL_WHEN_VIDEO_WEAK:
        return False

    if not isinstance(matching_profile_reuse, dict):
        return False
    if str(matching_profile_reuse.get("analysis_profile") or "").strip().lower() != "jump":
        return False
    match_count = int(_float_or_none(matching_profile_reuse.get("match_count")) or 0)
    profile_ratio = _float_or_none(matching_profile_reuse.get("profile_ratio")) or 0.0
    video_ai_backed_count = int(_float_or_none(matching_profile_reuse.get("video_ai_backed_count")) or 0)
    return (
        match_count >= MIXED_ACTION_PROFILE_REUSE_MIN_MATCHES
        and profile_ratio >= MIXED_ACTION_PROFILE_REUSE_MIN_RATIO
        and video_ai_backed_count >= MIXED_ACTION_PROFILE_REUSE_MIN_VIDEO_AI_BACKED
    )


def _mixed_action_skeleton_jump_should_downgrade_to_step(
    *,
    current_profile: str,
    video_ai_profile: str | None,
    video_ai_profile_flags: list[str],
    bio_data: dict[str, Any] | None,
    profile_evidence: dict[str, Any] | None,
    video_temporal: dict[str, Any] | None = None,
    matching_profile_reuse: dict[str, Any] | None = None,
) -> bool:
    if str(current_profile or "").strip().lower() != "jump" or video_ai_profile is not None:
        return False
    if not (set(video_ai_profile_flags) & MIXED_ACTION_WEAK_VIDEO_AI_JUMP_FLAGS):
        return False
    if _mixed_action_matching_jump_history_blocks_downgrade(
        current_profile=current_profile,
        video_ai_profile=video_ai_profile,
        video_ai_profile_flags=video_ai_profile_flags,
        video_temporal=video_temporal,
        profile_evidence=profile_evidence,
        matching_profile_reuse=matching_profile_reuse,
    ):
        return False
    if not isinstance(bio_data, dict):
        return True
    candidates = bio_data.get("key_frame_candidates")
    if not isinstance(candidates, dict):
        return True
    candidate_items = [
        candidates.get(key) if isinstance(candidates.get(key), dict) else None
        for key in ("T", "A", "L")
    ]
    if not all(candidate and candidate.get("frame_id") for candidate in candidate_items):
        return True

    average_confidence = sum(_candidate_confidence(candidate) for candidate in candidate_items) / 3.0
    candidate_flags = {
        str(flag)
        for flag in candidates.get("quality_flags", [])
        if isinstance(flag, str)
    }
    if candidate_flags & MIXED_ACTION_SKELETON_JUMP_WEAK_CANDIDATE_FLAGS:
        return True
    if average_confidence < MIXED_ACTION_SKELETON_JUMP_HARD_MIN_AVG_CANDIDATE_CONFIDENCE:
        return True
    rotation_signal = (
        _float_or_none((profile_evidence or {}).get("hip_rotation_signal"))
        if isinstance(profile_evidence, dict)
        else None
    ) or 0.0
    if rotation_signal > MIXED_ACTION_SKELETON_JUMP_MAX_ROTATION_SIGNAL_WHEN_VIDEO_WEAK:
        return True
    has_subtype_support = _mixed_action_jump_subtype_supports_skeleton_jump(profile_evidence)
    if average_confidence < MIXED_ACTION_SKELETON_JUMP_KEEP_MIN_AVG_CANDIDATE_CONFIDENCE and not has_subtype_support:
        return True
    if "mixed_action_video_ai_jump_profile_rejected_low_quality" in video_ai_profile_flags and not has_subtype_support:
        return True
    return False


def _build_bio_data_for_profile(
    *,
    pose_data: dict[str, Any],
    motion_scores: dict[str, object],
    action_type: str,
    analysis_profile: str,
    sampling_metadata: VideoSamplingMetadata,
    profile_evidence: dict[str, Any],
    target_lock: dict[str, Any],
) -> dict[str, Any]:
    bio_data = analyze_biomechanics(
        pose_data,
        action_type,
        analysis_profile,
        effective_fps=sampling_metadata.effective_fps,
        source_fps=sampling_metadata.source_fps,
        window_seconds=sampling_metadata.window_end_sec - sampling_metadata.window_start_sec,
    )
    bio_data = attach_key_frame_candidates(
        bio_data,
        pose_data,
        motion_scores,
        analysis_profile,
        sampling_metadata.effective_fps,
    )
    if isinstance(bio_data, dict):
        if analysis_profile == "jump":
            profile_evidence["jump_subtype_evidence"] = infer_jump_subtype_evidence(
                pose_data,
                bio_data.get("key_frames") if isinstance(bio_data.get("key_frames"), dict) else {},
                sampling_metadata.effective_fps,
            )
        merged_quality_flags = bio_data.get("quality_flags") if isinstance(bio_data.get("quality_flags"), list) else []
        merged_quality_flags.extend(
            flag for flag in profile_evidence.get("quality_flags", []) if flag not in merged_quality_flags
        )
        target_flags = target_lock.get("quality_flags") if isinstance(target_lock.get("quality_flags"), list) else []
        merged_quality_flags.extend(flag for flag in target_flags if flag not in merged_quality_flags)
        bio_data["quality_flags"] = merged_quality_flags
        bio_data["profile_evidence"] = profile_evidence
    return bio_data


def _apply_resolved_video_ai_profile_override_to_bio_data(
    *,
    action_type: str,
    action_subtype: str | None,
    current_profile: str,
    video_temporal: dict[str, Any] | None,
    resolved_keyframes: dict[str, Any] | None,
    bio_data: dict[str, Any],
    pose_data: dict[str, Any],
    motion_scores: dict[str, object],
    sampling_metadata: VideoSamplingMetadata,
    profile_evidence: dict[str, Any],
    target_lock: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    resolved_profile, resolved_profile_flags = _profile_from_resolved_video_ai_for_mixed_action(
        action_type,
        action_subtype,
        current_profile=current_profile,
        video_temporal=video_temporal,
        resolved_keyframes=resolved_keyframes,
        bio_data=bio_data,
    )
    if resolved_profile is None:
        return current_profile, bio_data, profile_evidence

    next_evidence = dict(profile_evidence) if isinstance(profile_evidence, dict) else {}
    if current_profile:
        next_evidence.setdefault("skeleton_inferred_profile", current_profile)
        next_evidence["resolver_requested_profile"] = current_profile
    next_evidence["video_ai_action_family"] = resolved_profile
    next_evidence["video_ai_action_confidence"] = round(_video_ai_action_confidence(video_temporal), 4)
    next_evidence["quality_flags"] = _merge_quality_flags(next_evidence, resolved_profile_flags)
    rebuilt_bio_data = _build_bio_data_for_profile(
        pose_data=pose_data,
        motion_scores=motion_scores,
        action_type=action_type,
        analysis_profile=resolved_profile,
        sampling_metadata=sampling_metadata,
        profile_evidence=next_evidence,
        target_lock=target_lock,
    )
    return resolved_profile, rebuilt_bio_data, next_evidence


def _mixed_action_profile_reuse_allowed_by_video_ai(
    video_temporal: dict[str, Any] | None,
    video_ai_profile_flags: list[str] | None,
) -> bool:
    selected_video_temporal, _selected_source = _select_mixed_action_video_ai_profile_payload(video_temporal)
    family = _video_ai_action_family(selected_video_temporal)
    if family is None:
        return True
    confidence = _video_ai_action_confidence_from_payload(selected_video_temporal)
    if confidence < MIXED_ACTION_PROFILE_REUSE_LOW_VIDEO_AI_CONFIDENCE:
        return True
    weak_or_rejected_flags = {
        "mixed_action_video_ai_profile_low_confidence",
        "mixed_action_video_ai_jump_profile_low_confidence",
        "mixed_action_video_ai_jump_profile_rejected_low_quality",
        "mixed_action_video_ai_jump_profile_rejected_rotation_conflict",
        "mixed_action_video_ai_non_jump_profile_rejected_strong_skeleton_jump",
    }
    return bool(set(video_ai_profile_flags or []) & weak_or_rejected_flags)


def _mixed_action_profile_reuse_video_ai_min_confidence(profile: str) -> float:
    return (
        MIXED_ACTION_VIDEO_AI_JUMP_OVERRIDE_MIN_CONFIDENCE
        if profile == "jump"
        else MIXED_ACTION_PROFILE_REUSE_LOW_VIDEO_AI_CONFIDENCE
    )


def _mixed_action_profile_reuse_video_ai_backed(
    analysis: Analysis,
    profile: str,
) -> tuple[bool, float | None, str | None]:
    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else {}
    resolved = motion_scores.get("resolved_keyframes") if isinstance(motion_scores.get("resolved_keyframes"), dict) else {}
    payloads = [
        motion_scores.get("video_temporal") if isinstance(motion_scores.get("video_temporal"), dict) else None,
        resolved.get("video_ai") if isinstance(resolved.get("video_ai"), dict) else None,
    ]
    min_confidence = _mixed_action_profile_reuse_video_ai_min_confidence(profile)
    best_confidence: float | None = None
    for payload in payloads:
        selected, source = _select_mixed_action_video_ai_profile_payload(payload)
        family = _video_ai_action_family(selected)
        if family != profile:
            continue
        confidence = _video_ai_action_confidence_from_payload(selected)
        best_confidence = max(best_confidence or 0.0, confidence)
        if confidence >= min_confidence:
            return True, confidence, source or "video_temporal"

    bio_data = analysis.bio_data if isinstance(getattr(analysis, "bio_data", None), dict) else {}
    profile_evidence = bio_data.get("profile_evidence") if isinstance(bio_data.get("profile_evidence"), dict) else {}
    evidence_family = str(profile_evidence.get("video_ai_action_family") or "").strip().lower()
    evidence_confidence = _float_or_none(profile_evidence.get("video_ai_action_confidence"))
    evidence_flags = set(_merge_quality_flags(profile_evidence))
    if (
        evidence_family == profile
        and evidence_confidence is not None
        and evidence_confidence >= min_confidence
        and (
            "mixed_action_profile_overridden_by_video_ai" in evidence_flags
            or "mixed_action_profile_overridden_by_video_ai_after_resolver" in evidence_flags
        )
    ):
        return True, evidence_confidence, "profile_evidence"

    return False, best_confidence, None


def _mixed_action_candidate_video_ai_backed_for_profile(
    candidate: dict[str, Any],
    profile: str,
) -> bool:
    if str(candidate.get("analysis_profile") or "").strip().lower() != profile:
        return False
    return bool(candidate.get("video_ai_backed"))


def _mixed_action_profile_reuse_candidate_from_analysis(
    analysis: Analysis,
    *,
    current_analysis_id: str,
    video_sha256: str,
    action_type: str | None,
    action_subtype: str | None,
    current_motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if analysis.id == current_analysis_id or analysis.status != "completed":
        return None
    if not _pipeline_version_at_least(analysis.pipeline_version, MIXED_ACTION_PROFILE_REUSE_MIN_PIPELINE_VERSION):
        return None
    if action_type and analysis.action_type != action_type:
        return None
    if (analysis.action_subtype or None) != (action_subtype or None):
        return None
    profile = str(analysis.analysis_profile or "").strip().lower()
    if profile not in SUPPORTED_VIDEO_AI_PROFILES:
        return None
    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
    identity = _video_identity_from_motion(motion_scores)
    if not identity or identity.get("sha256") != video_sha256:
        return None
    if not _input_windows_compatible(current_motion_scores, motion_scores):
        return None
    video_ai_backed, video_ai_confidence, video_ai_source = _mixed_action_profile_reuse_video_ai_backed(
        analysis,
        profile,
    )
    created_at = getattr(analysis, "created_at", None)
    return {
        "analysis_id": analysis.id,
        "analysis_profile": profile,
        "pipeline_version": analysis.pipeline_version,
        "created_at": created_at.isoformat() if created_at is not None else "",
        "created_at_timestamp": created_at.timestamp() if created_at is not None else 0.0,
        "video_ai_backed": video_ai_backed,
        "video_ai_confidence": video_ai_confidence,
        "video_ai_source": video_ai_source,
    }


async def _find_matching_mixed_action_profile(
    *,
    session: AsyncSession,
    current_analysis_id: str,
    video_sha256: str | None,
    action_type: str | None,
    action_subtype: str | None,
    current_motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if not video_sha256:
        return None
    result = await session.execute(
        select(Analysis)
        .options(
            load_only(
                Analysis.id,
                Analysis.status,
                Analysis.action_type,
                Analysis.action_subtype,
                Analysis.analysis_profile,
                Analysis.pipeline_version,
                Analysis.frame_motion_scores,
                Analysis.bio_data,
                Analysis.created_at,
            )
        )
        .where(Analysis.status == "completed")
        .where(Analysis.id != current_analysis_id)
        .where(Analysis.action_type == action_type)
        .where(Analysis.frame_motion_scores.contains(video_sha256))
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(100)
    )
    candidates = [
        candidate
        for analysis in result.scalars().all()
        if (
            candidate := _mixed_action_profile_reuse_candidate_from_analysis(
                analysis,
                current_analysis_id=current_analysis_id,
                video_sha256=video_sha256,
                action_type=action_type,
                action_subtype=action_subtype,
                current_motion_scores=current_motion_scores,
            )
        )
        is not None
    ]
    if not candidates:
        return None
    counts = Counter(str(candidate.get("analysis_profile") or "") for candidate in candidates)
    total = len(candidates)
    for profile, count in counts.most_common():
        profile_candidates = [
            candidate for candidate in candidates if candidate.get("analysis_profile") == profile
        ]
        video_ai_backed_count = sum(1 for candidate in profile_candidates if candidate.get("video_ai_backed"))
        ratio = count / total if total else 0.0
        if (
            count < MIXED_ACTION_PROFILE_REUSE_MIN_MATCHES
            or ratio < MIXED_ACTION_PROFILE_REUSE_MIN_RATIO
            or video_ai_backed_count < MIXED_ACTION_PROFILE_REUSE_MIN_VIDEO_AI_BACKED
        ):
            continue
        latest = max(profile_candidates, key=lambda item: float(item.get("created_at_timestamp") or 0.0))
        return {
            "analysis_profile": profile,
            "source_analysis_id": latest.get("analysis_id"),
            "source_pipeline_version": latest.get("pipeline_version"),
            "source_created_at": latest.get("created_at"),
            "match_count": count,
            "candidate_count": total,
            "profile_ratio": round(ratio, 3),
            "video_ai_backed_count": video_ai_backed_count,
            "video_ai_confidence": latest.get("video_ai_confidence"),
            "video_ai_source": latest.get("video_ai_source"),
        }
    return None


async def _find_matching_mixed_action_prior_non_jump_profile(
    *,
    session: AsyncSession,
    current_analysis_id: str,
    video_sha256: str | None,
    action_type: str | None,
    action_subtype: str | None,
    current_motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if not video_sha256:
        return None
    result = await session.execute(
        select(Analysis)
        .options(
            load_only(
                Analysis.id,
                Analysis.status,
                Analysis.action_type,
                Analysis.action_subtype,
                Analysis.analysis_profile,
                Analysis.pipeline_version,
                Analysis.frame_motion_scores,
                Analysis.bio_data,
                Analysis.created_at,
            )
        )
        .where(Analysis.status == "completed")
        .where(Analysis.id != current_analysis_id)
        .where(Analysis.action_type == action_type)
        .where(Analysis.frame_motion_scores.contains(video_sha256))
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(100)
    )
    candidates = [
        candidate
        for analysis in result.scalars().all()
        if (
            candidate := _mixed_action_profile_reuse_candidate_from_analysis(
                analysis,
                current_analysis_id=current_analysis_id,
                video_sha256=video_sha256,
                action_type=action_type,
                action_subtype=action_subtype,
                current_motion_scores=current_motion_scores,
            )
        )
        is not None
    ]
    if not candidates:
        return None

    counts = Counter(str(candidate.get("analysis_profile") or "") for candidate in candidates)
    jump_count = counts.get("jump", 0)
    total = len(candidates)
    non_jump_profiles = [profile for profile in ("step", "spin", "spiral") if counts.get(profile, 0) > 0]
    if not non_jump_profiles:
        return None

    def _profile_rank(profile: str) -> tuple[int, float]:
        latest_timestamp = max(
            float(candidate.get("created_at_timestamp") or 0.0)
            for candidate in candidates
            if candidate.get("analysis_profile") == profile
        )
        return counts.get(profile, 0), latest_timestamp

    profile = max(non_jump_profiles, key=_profile_rank)
    count = counts.get(profile, 0)
    ratio = count / total if total else 0.0
    if count < jump_count or ratio < MIXED_ACTION_PRIOR_NON_JUMP_GUARD_MIN_RATIO:
        return None

    profile_candidates = [
        candidate for candidate in candidates if candidate.get("analysis_profile") == profile
    ]
    latest = max(profile_candidates, key=lambda item: float(item.get("created_at_timestamp") or 0.0))
    video_ai_backed_count = sum(1 for candidate in profile_candidates if candidate.get("video_ai_backed"))
    if video_ai_backed_count < MIXED_ACTION_PROFILE_REUSE_MIN_VIDEO_AI_BACKED:
        return None
    return {
        "analysis_profile": profile,
        "source_analysis_id": latest.get("analysis_id"),
        "source_pipeline_version": latest.get("pipeline_version"),
        "source_created_at": latest.get("created_at"),
        "match_count": count,
        "candidate_count": total,
        "profile_ratio": round(ratio, 3),
        "jump_match_count": jump_count,
        "video_ai_backed_count": video_ai_backed_count,
        "video_ai_confidence": latest.get("video_ai_confidence"),
        "video_ai_source": latest.get("video_ai_source"),
    }


async def _find_matching_mixed_action_non_jump_profile_stability(
    *,
    session: AsyncSession,
    current_analysis_id: str,
    video_sha256: str | None,
    action_type: str | None,
    action_subtype: str | None,
    current_motion_scores: dict[str, object] | None,
    current_profile: str | None,
    current_video_ai_confidence: float,
) -> dict[str, Any] | None:
    normalized_current = str(current_profile or "").strip().lower()
    if normalized_current not in {"jump", "step", "spin", "spiral"} or not video_sha256:
        return None
    if current_video_ai_confidence < MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_MIN_CURRENT_CONFIDENCE:
        return None

    result = await session.execute(
        select(Analysis)
        .options(
            load_only(
                Analysis.id,
                Analysis.status,
                Analysis.action_type,
                Analysis.action_subtype,
                Analysis.analysis_profile,
                Analysis.pipeline_version,
                Analysis.frame_motion_scores,
                Analysis.bio_data,
                Analysis.created_at,
            )
        )
        .where(Analysis.status == "completed")
        .where(Analysis.id != current_analysis_id)
        .where(Analysis.action_type == action_type)
        .where(Analysis.frame_motion_scores.contains(video_sha256))
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(100)
    )
    candidates = [
        candidate
        for analysis in result.scalars().all()
        if (
            candidate := _mixed_action_profile_reuse_candidate_from_analysis(
                analysis,
                current_analysis_id=current_analysis_id,
                video_sha256=video_sha256,
                action_type=action_type,
                action_subtype=action_subtype,
                current_motion_scores=current_motion_scores,
            )
        )
        is not None
    ]
    if not candidates:
        return None

    profiles = {"step", "spin", "spiral"}
    if normalized_current in profiles:
        profiles -= {normalized_current}
    best_candidate: dict[str, Any] | None = None
    for profile in profiles:
        profile_candidates = [
            candidate
            for candidate in candidates
            if _mixed_action_candidate_video_ai_backed_for_profile(candidate, profile)
        ]
        if len(profile_candidates) < MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_MIN_BACKED_COUNT:
            continue
        best_confidence = max(
            (_float_or_none(candidate.get("video_ai_confidence")) or 0.0)
            for candidate in profile_candidates
        )
        if best_confidence < MIXED_ACTION_NON_JUMP_PROFILE_STABILITY_MIN_BEST_CONFIDENCE:
            continue
        if best_confidence < current_video_ai_confidence:
            continue
        latest = max(profile_candidates, key=lambda item: float(item.get("created_at_timestamp") or 0.0))
        candidate_payload = {
            "analysis_profile": profile,
            "source_analysis_id": latest.get("analysis_id"),
            "source_pipeline_version": latest.get("pipeline_version"),
            "source_created_at": latest.get("created_at"),
            "match_count": len(profile_candidates),
            "candidate_count": len(candidates),
            "profile_ratio": round(len(profile_candidates) / len(candidates), 3),
            "video_ai_backed_count": len(profile_candidates),
            "video_ai_confidence": best_confidence,
            "video_ai_source": latest.get("video_ai_source"),
            "current_video_ai_confidence": round(current_video_ai_confidence, 4),
        }
        if best_candidate is None or (
            float(candidate_payload["video_ai_confidence"]),
            int(candidate_payload["video_ai_backed_count"]),
            float(latest.get("created_at_timestamp") or 0.0),
        ) > (
            float(best_candidate.get("video_ai_confidence") or 0.0),
            int(best_candidate.get("video_ai_backed_count") or 0),
            float(best_candidate.get("source_created_at_timestamp") or 0.0),
        ):
            candidate_payload["source_created_at_timestamp"] = latest.get("created_at_timestamp")
            best_candidate = candidate_payload

    if best_candidate is not None:
        best_candidate.pop("source_created_at_timestamp", None)
    return best_candidate


def _mixed_action_matching_profile_reuse_should_override(
    *,
    current_profile: str,
    reused_profile: str,
    bio_data: dict[str, Any] | None,
) -> bool:
    normalized_current = str(current_profile or "").strip().lower()
    normalized_reused = str(reused_profile or "").strip().lower()
    if normalized_reused not in SUPPORTED_VIDEO_AI_PROFILES or normalized_reused == normalized_current:
        return False
    if normalized_reused == "jump":
        return False
    if (
        normalized_current == "jump"
        and normalized_reused != "jump"
        and not _mixed_action_current_jump_profile_is_weak(normalized_current, bio_data)
    ):
        return False
    return True


def _mixed_action_prior_non_jump_profile_should_override_weak_jump(
    *,
    current_profile: str,
    prior_profile_reuse: dict[str, Any] | None,
    video_ai_profile: str | None,
    bio_data: dict[str, Any] | None,
    profile_evidence: dict[str, Any] | None,
) -> bool:
    if str(current_profile or "").strip().lower() != "jump" or video_ai_profile is not None:
        return False
    if not isinstance(prior_profile_reuse, dict):
        return False
    reused_profile = str(prior_profile_reuse.get("analysis_profile") or "").strip().lower()
    if reused_profile not in {"step", "spin", "spiral"}:
        return False
    if not _mixed_action_current_jump_profile_is_weak("jump", bio_data):
        return False
    return True


def _candidate_timestamp(candidate: dict[str, Any] | None) -> float | None:
    if not isinstance(candidate, dict):
        return None
    return _float_or_none(candidate.get("timestamp"))


def _candidate_confidence(candidate: dict[str, Any] | None) -> float:
    if not isinstance(candidate, dict):
        return 0.0
    return max(0.0, min(1.0, _float_or_none(candidate.get("confidence")) or 0.0))


def _mixed_action_jump_candidates_are_recoverable(candidates: dict[str, Any] | None) -> bool:
    if not isinstance(candidates, dict):
        return False
    t_candidate = candidates.get("T") if isinstance(candidates.get("T"), dict) else None
    a_candidate = candidates.get("A") if isinstance(candidates.get("A"), dict) else None
    l_candidate = candidates.get("L") if isinstance(candidates.get("L"), dict) else None
    if not all(candidate and candidate.get("frame_id") for candidate in (t_candidate, a_candidate, l_candidate)):
        return False
    t_ts = _candidate_timestamp(t_candidate)
    a_ts = _candidate_timestamp(a_candidate)
    l_ts = _candidate_timestamp(l_candidate)
    if t_ts is None or a_ts is None or l_ts is None:
        return False
    if not (t_ts + MIXED_ACTION_JUMP_RECOVERY_MIN_CORE_GAP_SECONDS < a_ts < l_ts - MIXED_ACTION_JUMP_RECOVERY_MIN_CORE_GAP_SECONDS):
        return False
    if l_ts - t_ts > MIXED_ACTION_JUMP_RECOVERY_MAX_TAL_SPAN_SECONDS:
        return False
    avg_confidence = (
        _candidate_confidence(t_candidate)
        + _candidate_confidence(a_candidate)
        + _candidate_confidence(l_candidate)
    ) / 3.0
    if avg_confidence < MIXED_ACTION_JUMP_RECOVERY_MIN_AVG_CANDIDATE_CONFIDENCE:
        return False
    flags = {str(flag) for flag in candidates.get("quality_flags", []) if isinstance(flag, str)}
    return not bool(flags & MIXED_ACTION_JUMP_RECOVERY_REJECT_CANDIDATE_FLAGS)


def _mixed_action_should_recover_jump_from_skeleton(
    action_type: str,
    action_subtype: str | None,
    *,
    current_profile: str,
    video_ai_profile: str | None,
    video_temporal: dict[str, Any] | None,
    profile_evidence: dict[str, Any],
    jump_candidates: dict[str, Any] | None,
) -> bool:
    if not is_mixed_action_input(action_type, action_subtype):
        return False
    if current_profile == "jump" or video_ai_profile in {"spin", "spiral", "step"}:
        return False
    family = _video_ai_action_family(video_temporal)
    if family in {"spin", "spiral", "step"}:
        return False
    if _video_ai_action_confidence(video_temporal) >= 0.60 and family != "jump":
        return False
    if bool(profile_evidence.get("mixed_jump_gate_passed")):
        return False
    if not bool(profile_evidence.get("jump_gate_passed")):
        return False
    relative_vertical = _float_or_none(profile_evidence.get("relative_vertical_range")) or 0.0
    rotation_signal = _float_or_none(profile_evidence.get("hip_rotation_signal")) or 0.0
    if relative_vertical < MIXED_ACTION_JUMP_RECOVERY_MIN_RELATIVE_VERTICAL:
        return False
    if rotation_signal > MIXED_ACTION_JUMP_RECOVERY_MAX_ROTATION_SIGNAL:
        return False
    return _mixed_action_jump_candidates_are_recoverable(jump_candidates)


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_quality_flags(payload: dict[str, Any], *flags: str) -> dict[str, Any]:
    payload["quality_flags"] = _merge_quality_flags(payload, [flag for flag in flags if flag])
    return payload


def _parse_pipeline_version_tuple(value: object) -> tuple[int, int, int] | None:
    text = str(value or "").strip()
    if not text.startswith("v"):
        return None
    parts = text[1:].split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _pipeline_version_at_least(value: object, minimum: str) -> bool:
    parsed = _parse_pipeline_version_tuple(value)
    minimum_parsed = _parse_pipeline_version_tuple(minimum)
    if parsed is None or minimum_parsed is None:
        return False
    return parsed >= minimum_parsed


def _video_identity_payload(video_path: Path, sha256: str) -> dict[str, Any]:
    stat = video_path.stat()
    return {
        "schema_version": VIDEO_IDENTITY_VERSION,
        "sha256": sha256,
        "size_bytes": stat.st_size,
        "filename": video_path.name,
    }


def _attach_video_identity(motion_scores: dict[str, object] | None, video_identity: dict[str, Any] | None) -> dict[str, object] | None:
    if not isinstance(video_identity, dict):
        return motion_scores
    merged: dict[str, object] = dict(motion_scores or {})
    merged["video_identity"] = dict(video_identity)
    return merged


def _video_identity_from_motion(motion_scores: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(motion_scores, dict):
        return None
    identity = motion_scores.get("video_identity")
    return identity if isinstance(identity, dict) else None


def _video_sha256_for_analysis(analysis: Analysis) -> str | None:
    identity = _video_identity_from_motion(
        analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
    )
    value = str((identity or {}).get("sha256") or "").strip()
    return value or None


def _input_windows_compatible(current_motion: dict[str, object] | None, candidate_motion: dict[str, Any] | None) -> bool:
    current = _input_window_payload_from_motion(current_motion if isinstance(current_motion, dict) else None)
    candidate = _input_window_payload_from_motion(candidate_motion)
    if not current or not candidate:
        return True
    current_mode = str(current.get("input_window_mode") or "")
    candidate_mode = str(candidate.get("input_window_mode") or "")
    if current_mode and candidate_mode and current_mode != candidate_mode:
        return False
    for key in ("input_window_start_sec", "input_window_end_sec"):
        current_value = current.get(key)
        candidate_value = candidate.get(key)
        if not isinstance(current_value, (int, float)) or not isinstance(candidate_value, (int, float)):
            continue
        if abs(float(current_value) - float(candidate_value)) > 0.05:
            return False
    return True


def _semantic_reuse_profile(analysis_profile: str | None) -> str:
    return str(analysis_profile or "").strip().lower()


def _semantic_reuse_profile_phases(analysis_profile: str | None) -> tuple[str, ...]:
    return SEMANTIC_REUSE_PROFILE_PHASES.get(_semantic_reuse_profile(analysis_profile), ("T", "A", "L"))


def _semantic_reuse_required_phases(analysis_profile: str | None) -> tuple[str, ...]:
    return SEMANTIC_REUSE_PROFILE_REQUIRED_PHASES.get(_semantic_reuse_profile(analysis_profile), ("T", "A", "L"))


def _semantic_reuse_key(record: dict[str, Any], analysis_profile: str | None = None) -> str | None:
    key_moment = str(record.get("key_moment") or "")
    if key_moment.startswith("T_"):
        return "T"
    if key_moment.startswith("A_"):
        return "A"
    if key_moment.startswith("L_"):
        return "L"
    phase_code = str(record.get("phase_code") or "").strip().lower()
    profile_phases = _semantic_reuse_profile_phases(analysis_profile)
    if phase_code in profile_phases and phase_code not in {"T", "A", "L"}:
        return phase_code
    if phase_code == "takeoff":
        return "T"
    if phase_code == "air":
        return "A"
    if phase_code == "landing":
        return "L"
    return None


def _semantic_reuse_non_jump_selected(records: list[object], analysis_profile: str) -> list[dict[str, Any]]:
    allowed = set(_semantic_reuse_profile_phases(analysis_profile))
    required = set(_semantic_reuse_required_phases(analysis_profile))
    if not allowed or not required:
        return []

    phase_order = {phase: index for index, phase in enumerate(_semantic_reuse_profile_phases(analysis_profile))}
    selected: list[dict[str, Any]] = []
    present: set[str] = set()
    first_timestamp_by_phase: dict[str, float] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = _semantic_reuse_key(record, analysis_profile)
        if key not in allowed:
            continue
        try:
            timestamp = float(record.get("timestamp"))
        except (TypeError, ValueError):
            continue
        if timestamp < 0:
            continue
        item = dict(record)
        item["timestamp"] = round(timestamp, 3)
        item["reused_from_matching_video"] = True
        selected.append(item)
        present.add(key)
        first_timestamp_by_phase.setdefault(key, item["timestamp"])

    if not required.issubset(present):
        return []

    ordered_phases = [phase for phase in _semantic_reuse_profile_phases(analysis_profile) if phase in first_timestamp_by_phase]
    previous_timestamp: float | None = None
    for phase in ordered_phases:
        timestamp = first_timestamp_by_phase[phase]
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            return []
        previous_timestamp = timestamp

    if _semantic_reuse_profile(analysis_profile) == "step":
        return sorted(selected, key=lambda item: float(item.get("timestamp") or 0.0))
    return sorted(
        selected,
        key=lambda item: (
            phase_order.get(str(item.get("phase_code") or "").strip().lower(), len(phase_order)),
            float(item.get("timestamp") or 0.0),
        ),
    )


def _semantic_reuse_selected(records: object, analysis_profile: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    profile = _semantic_reuse_profile(analysis_profile)
    if profile in SEMANTIC_REUSE_PROFILE_PHASES:
        return _semantic_reuse_non_jump_selected(records, profile)

    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = _semantic_reuse_key(record, analysis_profile)
        if key not in {"T", "A", "L"}:
            continue
        try:
            timestamp = float(record.get("timestamp"))
        except (TypeError, ValueError):
            continue
        if timestamp < 0:
            continue
        item = dict(record)
        item["timestamp"] = round(timestamp, 3)
        item["reused_from_matching_video"] = True
        by_key[key] = item
    if not {"T", "A", "L"}.issubset(by_key):
        return []
    selected = [by_key[key] for key in ("T", "A", "L")]
    if not (selected[0]["timestamp"] < selected[1]["timestamp"] < selected[2]["timestamp"]):
        return []
    return selected


def _semantic_reuse_source_is_stable(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
    *,
    allowed_unstable_flags: set[str] | None = None,
) -> bool:
    flags = set(_merge_quality_flags(resolved_keyframes, video_temporal))
    unstable_flags = set(SEMANTIC_REUSE_UNSTABLE_SOURCE_FLAGS)
    if allowed_unstable_flags:
        unstable_flags -= allowed_unstable_flags
    return not bool(flags & unstable_flags)


def _semantic_reuse_phase_range_weak_geometry_source(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
) -> bool:
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    flags = set(_merge_quality_flags(resolved_keyframes, video_temporal))
    if not SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_REQUIRED_SOURCE_FLAGS.issubset(flags):
        return False
    if "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates" in flags:
        return False

    confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if confidence is None and isinstance(video_temporal, dict):
        confidence = _float_or_none(video_temporal.get("confidence"))
    if (
        confidence is None
        or confidence < SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_SOURCE_CONFIDENCE
    ):
        return False

    if isinstance(video_temporal, dict):
        action_confirmation = video_temporal.get("action_confirmation")
        if isinstance(action_confirmation, dict):
            action_family = str(action_confirmation.get("action_family") or "").strip().lower().replace(" ", "_")
            if action_family and action_family not in {"jump", "jumps"}:
                return False
            action_confidence = _float_or_none(action_confirmation.get("confidence"))
            if (
                action_confidence is not None
                and action_confidence < SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_ACTION_CONFIDENCE
            ):
                return False

    selected = _semantic_reuse_selected(resolved_keyframes.get("selected"))
    if not selected:
        return False
    timestamps = _semantic_reuse_selected_timestamp_map(selected)
    tal_span = timestamps["L"] - timestamps["T"]
    if not (
        SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC
    ):
        return False
    for record in selected:
        reason = str(record.get("selection_reason") or "")
        if not reason.startswith("video_phase_range_"):
            return False
        phase_confidence = _float_or_none(record.get("confidence"))
        if (
            phase_confidence is None
            or phase_confidence < SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_PHASE_CONFIDENCE
        ):
            return False
    return True


def _semantic_reuse_phase_range_late_reanchor_source(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
) -> bool:
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    flags = set(_merge_quality_flags(resolved_keyframes, video_temporal))
    if not SEMANTIC_REUSE_PHASE_RANGE_LATE_REANCHOR_SOURCE_FLAGS.issubset(flags):
        return False
    if "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates" in flags:
        return False

    confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if confidence is None and isinstance(video_temporal, dict):
        confidence = _float_or_none(video_temporal.get("confidence"))
    if (
        confidence is None
        or confidence < SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_SOURCE_CONFIDENCE
    ):
        return False

    selected = _semantic_reuse_selected(resolved_keyframes.get("selected"))
    if not selected:
        return False
    timestamps = _semantic_reuse_selected_timestamp_map(selected)
    tal_span = timestamps["L"] - timestamps["T"]
    if not (
        SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC
    ):
        return False
    for record in selected:
        reason = str(record.get("selection_reason") or "")
        if not reason.startswith("video_phase_range_"):
            return False
        phase_confidence = _float_or_none(record.get("confidence"))
        if (
            phase_confidence is None
            or phase_confidence < SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_PHASE_CONFIDENCE
        ):
            return False
        if record.get("late_phase_range_reanchor") is not True:
            return False
        if _float_or_none(record.get("pre_late_phase_reanchor_timestamp")) is None:
            return False
    return True


def _semantic_reuse_foreground_occlusion_repaired_source(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
    current_bio_data: dict[str, Any] | None,
) -> bool:
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    flags = set(_merge_quality_flags(resolved_keyframes, video_temporal))
    if "semantic_keyframe_core_foreground_occlusion_repaired" not in flags:
        return False
    if "semantic_keyframe_core_foreground_occlusion" in flags:
        return False
    if "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates" in flags:
        return False

    confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if confidence is None and isinstance(video_temporal, dict):
        confidence = _float_or_none(video_temporal.get("confidence"))
    if (
        confidence is None
        or confidence < SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_SOURCE_CONFIDENCE
    ):
        return False

    selected = _semantic_reuse_selected(resolved_keyframes.get("selected"))
    if not selected:
        return False
    timestamps = _semantic_reuse_selected_timestamp_map(selected)
    tal_span = timestamps["L"] - timestamps["T"]
    if not (
        SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC
    ):
        return False
    for record in selected:
        reason = str(record.get("selection_reason") or "")
        if not reason.startswith("video_phase_range_"):
            return False
        phase_confidence = _float_or_none(record.get("confidence"))
        if (
            phase_confidence is None
            or phase_confidence < SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_PHASE_CONFIDENCE
        ):
            return False

    delta_summary = _semantic_reuse_current_candidate_delta_summary(selected, current_bio_data)
    if int(delta_summary.get("supported_key_count") or 0) < SEMANTIC_REUSE_CURRENT_CANDIDATE_MIN_SUPPORTED_KEYS:
        return False
    supported_mean = _float_or_none(delta_summary.get("supported_mean_abs_delta_sec"))
    supported_max = _float_or_none(delta_summary.get("supported_max_abs_delta_sec"))
    return (
        supported_mean is not None
        and supported_max is not None
        and supported_mean <= SEMANTIC_REUSE_FOREGROUND_OCCLUSION_REPAIRED_MAX_SUPPORTED_MEAN_DELTA_SEC
        and supported_max <= SEMANTIC_REUSE_FOREGROUND_OCCLUSION_REPAIRED_MAX_SUPPORTED_DELTA_SEC
    )


def _semantic_reuse_insufficient_pose_low_visibility_source(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
    current_bio_data: dict[str, Any] | None,
) -> bool:
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    if not resolved_keyframes_accept_insufficient_pose_low_visibility_fallback(resolved_keyframes):
        return False
    if not bool(
        set(_keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data))
        & SEMANTIC_REUSE_RANKING_UNRELIABLE_CANDIDATE_FLAGS
    ):
        return False

    confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if confidence is None and isinstance(video_temporal, dict):
        confidence = _float_or_none(video_temporal.get("confidence"))
    if (
        confidence is None
        or confidence < SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_SOURCE_CONFIDENCE
    ):
        return False

    selected = _semantic_reuse_selected(resolved_keyframes.get("selected"))
    if not selected:
        return False
    timestamps = _semantic_reuse_selected_timestamp_map(selected)
    tal_span = timestamps["L"] - timestamps["T"]
    return (
        SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC
    )


def _semantic_reuse_degraded_semantic_low_visibility_source(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
    source_bio_data: dict[str, Any] | None,
    current_bio_data: dict[str, Any] | None,
) -> bool:
    if not isinstance(source_bio_data, dict):
        return False
    source_flags = {
        str(flag).strip()
        for flag in (source_bio_data.get("quality_flags") or [])
        if str(flag).strip()
    }
    if "bio_key_frames_synced_from_degraded_semantic_keyframes" not in source_flags:
        return False
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    flags = set(_merge_quality_flags(resolved_keyframes, video_temporal))
    if not (flags & SEMANTIC_REUSE_DEGRADED_SEMANTIC_LOW_VISIBILITY_ACCEPTED_FLAGS):
        return False
    if not bool(
        set(_keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data))
        & SEMANTIC_REUSE_RANKING_UNRELIABLE_CANDIDATE_FLAGS
    ):
        return False

    confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if confidence is None and isinstance(video_temporal, dict):
        confidence = _float_or_none(video_temporal.get("confidence"))
    if (
        confidence is None
        or confidence < SEMANTIC_REUSE_DEGRADED_SEMANTIC_LOW_VISIBILITY_MIN_SOURCE_CONFIDENCE
    ):
        return False

    selected = _semantic_reuse_selected(resolved_keyframes.get("selected"))
    timestamps = _semantic_reuse_selected_timestamp_map(selected)
    bio_timestamps = source_bio_data.get("key_frame_timestamps")
    if not isinstance(bio_timestamps, dict) or not {"T", "A", "L"}.issubset(timestamps):
        return False
    tal_span = timestamps["L"] - timestamps["T"]
    if not (
        SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC
    ):
        return False
    for key, semantic_timestamp in timestamps.items():
        bio_timestamp = _float_or_none(bio_timestamps.get(key))
        if bio_timestamp is None or abs(bio_timestamp - semantic_timestamp) > COMPARE_SAME_VIDEO_KEYFRAME_STABILITY_SECONDS:
            return False
    for record in selected:
        reason = str(record.get("selection_reason") or "")
        if not reason.startswith("video_phase_range_"):
            return False
        phase_confidence = _float_or_none(record.get("confidence"))
        if (
            phase_confidence is None
            or phase_confidence < SEMANTIC_REUSE_DEGRADED_SEMANTIC_LOW_VISIBILITY_MIN_PHASE_CONFIDENCE
        ):
            return False
    return True


def _semantic_reuse_clean_video_tal_over_late_weak_candidate_source(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
    current_bio_data: dict[str, Any] | None,
) -> bool:
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    if not isinstance(video_temporal, dict):
        return False
    if video_temporal.get("valid") is not True:
        return False
    if str(video_temporal.get("fallback_recommendation") or "").strip() != "use_video_timestamps":
        return False

    flags = set(_merge_quality_flags(resolved_keyframes, video_temporal))
    if "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates" in flags:
        return False
    if flags & {
        "video_temporal_fallback_recommended",
        "video_temporal_resolver_video_validation_not_clean",
        "semantic_keyframe_core_foreground_occlusion",
        "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
        "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
        "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
    }:
        return False

    confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if confidence is None:
        confidence = _float_or_none(video_temporal.get("confidence"))
    if confidence is None or confidence < SEMANTIC_REUSE_CLEAN_VIDEO_TAL_MIN_SOURCE_CONFIDENCE:
        return False

    action_confirmation = video_temporal.get("action_confirmation")
    if isinstance(action_confirmation, dict):
        action_family = str(action_confirmation.get("action_family") or "").strip().lower().replace(" ", "_")
        if action_family and action_family not in {"jump", "jumps"}:
            return False

    selected = _semantic_reuse_selected(resolved_keyframes.get("selected"))
    if not selected:
        return False
    timestamps = _semantic_reuse_selected_timestamp_map(selected)
    if not {"T", "A", "L"}.issubset(timestamps):
        return False
    tal_span = timestamps["L"] - timestamps["T"]
    if not (
        SEMANTIC_REUSE_CLEAN_VIDEO_TAL_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_REUSE_CLEAN_VIDEO_TAL_MAX_TAL_SPAN_SEC
    ):
        return False
    for record in selected:
        reason = str(record.get("selection_reason") or "")
        if not reason.startswith("video_phase_range_"):
            return False
        phase_confidence = _float_or_none(record.get("confidence"))
        if (
            phase_confidence is None
            or phase_confidence < SEMANTIC_REUSE_CLEAN_VIDEO_TAL_MIN_PHASE_CONFIDENCE
        ):
            return False

    candidate_flags = set(_keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data))
    if "keyframe_candidates_late_pose_core_reselected" not in candidate_flags:
        return False
    if not (candidate_flags & SEMANTIC_REUSE_RANKING_UNRELIABLE_CANDIDATE_FLAGS):
        return False
    candidate_timestamps, candidate_confidences, _pose_supported = _semantic_reuse_current_candidate_timestamp_map(
        current_bio_data
    )
    shifted_keys = []
    for key in ("T", "A", "L"):
        candidate_timestamp = candidate_timestamps.get(key)
        candidate_confidence = candidate_confidences.get(key)
        if candidate_timestamp is None or candidate_confidence is None:
            continue
        if candidate_confidence > SEMANTIC_REUSE_CLEAN_VIDEO_TAL_LATE_CANDIDATE_MAX_CONFIDENCE:
            continue
        if candidate_timestamp - timestamps[key] >= SEMANTIC_REUSE_CLEAN_VIDEO_TAL_LATE_CANDIDATE_MIN_SHIFT_SEC:
            shifted_keys.append(key)
    return len(shifted_keys) >= 2


def _semantic_reuse_current_candidate_is_sparse_track_stitched(
    current_bio_data: dict[str, Any] | None,
) -> bool:
    flags = set(_keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data))
    return bool(flags & SEMANTIC_REUSE_SPARSE_TRACK_STITCHED_REQUIRED_CANDIDATE_FLAGS)


def _semantic_reuse_sparse_track_stitched_candidate_source(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
    current_bio_data: dict[str, Any] | None,
) -> bool:
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    if not semantic_keyframes_are_reliable(resolved_keyframes):
        return False
    if not _semantic_reuse_current_candidate_is_sparse_track_stitched(current_bio_data):
        return False

    selected = _semantic_reuse_selected(resolved_keyframes.get("selected"))
    if not selected:
        return False
    timestamps = _semantic_reuse_selected_timestamp_map(selected)
    tal_span = timestamps["L"] - timestamps["T"]
    if not (
        SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC
    ):
        return False

    delta_summary = _semantic_reuse_current_candidate_delta_summary(selected, current_bio_data)
    return int(delta_summary.get("supported_key_count") or 0) < SEMANTIC_REUSE_CURRENT_CANDIDATE_MIN_SUPPORTED_KEYS


def _semantic_reuse_allowed_unstable_source_flags(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
    *,
    long_unresolved_motion_fallback: bool,
    current_bio_data: dict[str, Any] | None = None,
    source_bio_data: dict[str, Any] | None = None,
) -> set[str]:
    flags = set(_merge_quality_flags(resolved_keyframes, video_temporal))
    allowed: set[str] = set()
    if long_unresolved_motion_fallback:
        allowed |= SEMANTIC_REUSE_LONG_UNRESOLVED_ALLOWED_SOURCE_FLAGS
    if flags & {
        "semantic_keyframes_phase_range_visual_tal_promoted",
        "semantic_keyframes_distant_full_context_visual_tal_promoted",
    }:
        allowed |= SEMANTIC_REUSE_VISUAL_PROMOTION_ALLOWED_SOURCE_FLAGS
    if _semantic_reuse_phase_range_weak_geometry_source(resolved_keyframes, video_temporal):
        allowed |= SEMANTIC_REUSE_PHASE_RANGE_WEAK_GEOMETRY_ALLOWED_SOURCE_FLAGS
    if _semantic_reuse_foreground_occlusion_repaired_source(
        resolved_keyframes,
        video_temporal,
        current_bio_data,
    ):
        allowed |= SEMANTIC_REUSE_FOREGROUND_OCCLUSION_REPAIRED_ALLOWED_SOURCE_FLAGS
    if _semantic_reuse_insufficient_pose_low_visibility_source(
        resolved_keyframes,
        video_temporal,
        current_bio_data,
    ):
        allowed |= SEMANTIC_REUSE_INSUFFICIENT_POSE_LOW_VISIBILITY_ALLOWED_SOURCE_FLAGS
    if _semantic_reuse_sparse_track_stitched_candidate_source(
        resolved_keyframes,
        video_temporal,
        current_bio_data,
    ):
        allowed |= SEMANTIC_REUSE_INSUFFICIENT_POSE_LOW_VISIBILITY_ALLOWED_SOURCE_FLAGS
    if _semantic_reuse_degraded_semantic_low_visibility_source(
        resolved_keyframes,
        video_temporal,
        source_bio_data,
        current_bio_data,
    ):
        allowed |= SEMANTIC_REUSE_DEGRADED_SEMANTIC_LOW_VISIBILITY_ALLOWED_SOURCE_FLAGS
    if _semantic_reuse_clean_video_tal_over_late_weak_candidate_source(
        resolved_keyframes,
        video_temporal,
        current_bio_data,
    ):
        allowed |= {
            "semantic_keyframe_refinement_delta_rejected",
            "semantic_keyframe_refinement_phase_rejected",
            "semantic_keyframes_partial_core_frames_available",
            "semantic_keyframes_post_vision_partial_phase_frames_available",
            "semantic_keyframes_unreliable_after_refinement",
            "semantic_keyframes_unreliable_candidate_tal_conflict",
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            "video_temporal_quality_retry_rejected",
        }
    return allowed


def _semantic_reuse_source_penalty_flags(
    resolved_keyframes: dict[str, Any],
    video_temporal: dict[str, Any] | None,
) -> list[str]:
    flags = set(_merge_quality_flags(resolved_keyframes, video_temporal))
    return sorted(flags & SEMANTIC_REUSE_SOURCE_PENALTY_FLAGS)


def _attach_semantic_reuse_source_candidate_conflict_context(
    resolved_keyframes: dict[str, Any],
    *,
    source_quality_flags: Sequence[str],
    source_semantic_candidate_tal_conflict: object,
) -> dict[str, Any]:
    accepted_flags = [
        flag
        for flag in source_quality_flags
        if flag in SEMANTIC_REUSE_ACCEPTED_SOURCE_CANDIDATE_CONFLICT_FLAGS
    ]
    if not accepted_flags:
        return resolved_keyframes
    _append_quality_flags(resolved_keyframes, *accepted_flags)
    if isinstance(source_semantic_candidate_tal_conflict, dict):
        resolved_keyframes["semantic_candidate_tal_conflict"] = dict(source_semantic_candidate_tal_conflict)
        resolved_keyframes["semantic_candidate_tal_conflict"]["reused_from_source_analysis"] = True
    return resolved_keyframes


def _semantic_reuse_selected_timestamp_map(
    selected: list[dict[str, Any]],
    analysis_profile: str | None = None,
) -> dict[str, float]:
    timestamps: dict[str, float] = {}
    accepted_keys = set(_semantic_reuse_profile_phases(analysis_profile))
    for record in selected:
        key = _semantic_reuse_key(record, analysis_profile)
        timestamp = _float_or_none(record.get("timestamp"))
        if key in accepted_keys and timestamp is not None and key not in timestamps:
            timestamps[key] = timestamp
    return timestamps


def _semantic_reuse_candidate_source_keyframes(current_bio_data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    candidates = current_bio_data.get("key_frame_candidates") if isinstance(current_bio_data, dict) else None
    return candidates if isinstance(candidates, dict) else {}


def _keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data: dict[str, Any] | None) -> list[str]:
    candidates = _semantic_reuse_candidate_source_keyframes(current_bio_data)
    flags: list[str] = []
    for raw in candidates.get("quality_flags", []):
        value = str(raw).strip()
        if value and value not in flags:
            flags.append(value)
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            continue
        warnings = candidate.get("warnings")
        if not isinstance(warnings, list):
            continue
        for raw in warnings:
            value = str(raw).strip()
            if value and value not in flags:
                flags.append(value)
    return flags


def _semantic_reuse_current_candidate_tal_span_sec(current_bio_data: dict[str, Any] | None) -> float | None:
    candidates = _semantic_reuse_candidate_source_keyframes(current_bio_data)
    timestamps: list[float] = []
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            return None
        timestamp = _float_or_none(candidate.get("timestamp"))
        if timestamp is None:
            return None
        timestamps.append(timestamp)
    return round(max(timestamps) - min(timestamps), 3)


def _semantic_reuse_current_candidate_is_long_unresolved_motion_fallback(
    current_bio_data: dict[str, Any] | None,
) -> bool:
    flags = set(_keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data))
    if not (
        "keyframe_candidates_motion_fallback" in flags
        and "tal_candidate_motion_fallback_low_precision" in flags
        and bool(flags & {"tal_candidate_incomplete", "tal_order_unresolved"})
    ):
        return False
    span = _semantic_reuse_current_candidate_tal_span_sec(current_bio_data)
    return (
        span is not None
        and span > SEMANTIC_REUSE_LONG_UNRESOLVED_MOTION_FALLBACK_MIN_TAL_SPAN_SEC
    )


def _semantic_reuse_current_candidate_has_pose_support(candidate: dict[str, Any]) -> bool:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    pose_visibility = _float_or_none(evidence.get("visibility_score"))
    if pose_visibility is None:
        score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
        pose_visibility = _float_or_none(score_components.get("pose_visibility"))
    if pose_visibility is not None and pose_visibility >= SEMANTIC_REUSE_POSE_SUPPORT_MIN_VISIBILITY:
        return True

    score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
    if any(_float_or_none(score_components.get(key_name)) is not None for key_name in SEMANTIC_REUSE_POSE_SIGNAL_COMPONENTS):
        return True

    warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
    warning_set = {str(item).strip() for item in warnings if str(item).strip()}
    motion_fallback = evidence.get("motion_fallback") is True or "keyframe_candidates_motion_fallback" in warning_set
    if motion_fallback and pose_visibility is not None and pose_visibility <= SEMANTIC_REUSE_LOW_VISIBILITY_MAX_POSE_VISIBILITY:
        return False
    return False


def _semantic_reuse_current_candidate_timestamp_map(
    current_bio_data: dict[str, Any] | None,
) -> tuple[dict[str, float], dict[str, float], set[str]]:
    candidates = _semantic_reuse_candidate_source_keyframes(current_bio_data)
    unreliable_ranking_candidates = bool(
        set(_keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data))
        & SEMANTIC_REUSE_RANKING_UNRELIABLE_CANDIDATE_FLAGS
    )
    timestamps: dict[str, float] = {}
    confidences: dict[str, float] = {}
    pose_supported: set[str] = set()
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            continue
        timestamp = _float_or_none(candidate.get("timestamp"))
        if timestamp is None:
            continue
        timestamps[key] = timestamp
        confidence = _float_or_none(candidate.get("confidence"))
        if confidence is not None:
            confidences[key] = confidence
        if not unreliable_ranking_candidates and _semantic_reuse_current_candidate_has_pose_support(candidate):
            pose_supported.add(key)
    return timestamps, confidences, pose_supported


def _semantic_reuse_current_candidate_delta_summary(
    selected: list[dict[str, Any]],
    current_bio_data: dict[str, Any] | None,
) -> dict[str, Any]:
    selected_timestamps = _semantic_reuse_selected_timestamp_map(selected)
    current_timestamps, current_confidences, pose_supported_keys = _semantic_reuse_current_candidate_timestamp_map(
        current_bio_data
    )
    deltas: dict[str, float] = {}
    supported_deltas: dict[str, float] = {}
    for key, semantic_timestamp in selected_timestamps.items():
        candidate_timestamp = current_timestamps.get(key)
        if candidate_timestamp is None:
            continue
        delta = abs(semantic_timestamp - candidate_timestamp)
        deltas[key] = round(delta, 3)
        if key in pose_supported_keys:
            supported_deltas[key] = round(delta, 3)

    values = list(deltas.values())
    supported_values = list(supported_deltas.values())
    return {
        "candidate_timestamps": {key: round(value, 3) for key, value in current_timestamps.items()},
        "candidate_confidences": {key: round(value, 3) for key, value in current_confidences.items()},
        "pose_supported_keys": sorted(pose_supported_keys),
        "deltas_sec": deltas,
        "supported_deltas_sec": supported_deltas,
        "mean_abs_delta_sec": round(mean(values), 3) if values else None,
        "max_abs_delta_sec": round(max(values), 3) if values else None,
        "supported_mean_abs_delta_sec": round(mean(supported_values), 3) if supported_values else None,
        "supported_max_abs_delta_sec": round(max(supported_values), 3) if supported_values else None,
        "supported_key_count": len(supported_values),
    }


def _semantic_reuse_pairwise_stability_summary(
    selected: list[dict[str, Any]],
    peer_candidates: list[dict[str, Any]],
    *,
    analysis_profile: str | None = None,
) -> dict[str, Any]:
    selected_timestamps = _semantic_reuse_selected_timestamp_map(selected, analysis_profile)
    expected_keys = set(_semantic_reuse_required_phases(analysis_profile))
    peer_means: list[float] = []
    peer_maxes: list[float] = []
    peer_count = 0
    for peer in peer_candidates:
        peer_timestamps = _semantic_reuse_selected_timestamp_map(
            peer.get("selected") if isinstance(peer.get("selected"), list) else [],
            analysis_profile,
        )
        shared_keys = sorted(expected_keys & set(selected_timestamps) & set(peer_timestamps))
        deltas = [
            abs(selected_timestamps[key] - peer_timestamps[key])
            for key in shared_keys
        ]
        if not deltas:
            continue
        peer_count += 1
        peer_means.append(mean(deltas))
        peer_maxes.append(max(deltas))
    return {
        "peer_count": peer_count,
        "peer_mean_abs_delta_sec": round(mean(peer_means), 3) if peer_means else None,
        "peer_max_abs_delta_sec": round(max(peer_maxes), 3) if peer_maxes else None,
    }


def _semantic_reuse_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    supported_count = int(candidate.get("candidate_supported_key_count") or 0)
    confidence = _float_or_none(candidate.get("confidence")) or 0.0
    created_at_timestamp = _float_or_none(candidate.get("created_at_timestamp")) or 0.0
    if supported_count >= SEMANTIC_REUSE_CURRENT_CANDIDATE_MIN_SUPPORTED_KEYS:
        mean_delta = _float_or_none(candidate.get("candidate_supported_mean_abs_delta_sec"))
        max_delta = _float_or_none(candidate.get("candidate_supported_max_abs_delta_sec"))
        source_penalty_count = float(candidate.get("source_penalty_count") or 0)
        if mean_delta is None:
            mean_delta = _float_or_none(candidate.get("candidate_mean_abs_delta_sec"))
        if max_delta is None:
            max_delta = _float_or_none(candidate.get("candidate_max_abs_delta_sec"))
        return (
            0.0,
            mean_delta if mean_delta is not None else SEMANTIC_REUSE_MISSING_DELTA_SECONDS,
            max_delta if max_delta is not None else SEMANTIC_REUSE_MISSING_DELTA_SECONDS,
            source_penalty_count,
            -confidence,
            -created_at_timestamp,
        )

    peer_mean = _float_or_none(candidate.get("peer_mean_abs_delta_sec"))
    peer_max = _float_or_none(candidate.get("peer_max_abs_delta_sec"))
    source_penalty_count = float(candidate.get("source_penalty_count") or 0)
    created_at_rank = (
        created_at_timestamp
        if candidate.get("insufficient_pose_low_visibility_source_override")
        or candidate.get("sparse_track_stitched_candidate_override")
        else -created_at_timestamp
    )
    return (
        1.0,
        peer_mean if peer_mean is not None else SEMANTIC_REUSE_MISSING_DELTA_SECONDS,
        peer_max if peer_max is not None else SEMANTIC_REUSE_MISSING_DELTA_SECONDS,
        source_penalty_count,
        -confidence,
        created_at_rank,
    )


def _semantic_reuse_candidate_from_analysis(
    analysis: Analysis,
    *,
    current_analysis_id: str,
    video_sha256: str,
    action_type: str | None,
    action_subtype: str | None,
    analysis_profile: str | None,
    current_motion_scores: dict[str, object] | None,
    current_bio_data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if analysis.id == current_analysis_id or analysis.status != "completed":
        return None
    if not _pipeline_version_at_least(analysis.pipeline_version, SEMANTIC_REUSE_MIN_PIPELINE_VERSION):
        return None
    if action_type and analysis.action_type != action_type:
        return None
    if (analysis.action_subtype or None) != (action_subtype or None):
        return None
    if (analysis.analysis_profile or None) != (analysis_profile or None):
        return None
    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
    identity = _video_identity_from_motion(motion_scores)
    if not identity or identity.get("sha256") != video_sha256:
        return None
    if not _input_windows_compatible(current_motion_scores, motion_scores):
        return None
    resolved = motion_scores.get("resolved_keyframes") if isinstance(motion_scores, dict) else None
    if not isinstance(resolved, dict):
        return None
    video_temporal = resolved.get("video_ai") if isinstance(resolved.get("video_ai"), dict) else motion_scores.get("video_temporal")
    source_bio_data = analysis.bio_data if isinstance(getattr(analysis, "bio_data", None), dict) else None
    reusable_phase_range_weak_geometry_source = _semantic_reuse_phase_range_weak_geometry_source(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
    )
    reusable_phase_range_late_reanchor_source = _semantic_reuse_phase_range_late_reanchor_source(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
    )
    reusable_foreground_occlusion_repaired_source = _semantic_reuse_foreground_occlusion_repaired_source(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
        current_bio_data,
    )
    reusable_insufficient_pose_low_visibility_source = _semantic_reuse_insufficient_pose_low_visibility_source(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
        current_bio_data,
    )
    reusable_degraded_semantic_low_visibility_source = _semantic_reuse_degraded_semantic_low_visibility_source(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
        source_bio_data,
        current_bio_data,
    )
    reusable_clean_video_tal_late_weak_candidate_source = _semantic_reuse_clean_video_tal_over_late_weak_candidate_source(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
        current_bio_data,
    )
    reusable_sparse_track_stitched_candidate_source = _semantic_reuse_sparse_track_stitched_candidate_source(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
        current_bio_data,
    )
    if (
        not semantic_keyframes_are_reliable(resolved)
        and not reusable_phase_range_weak_geometry_source
        and not reusable_foreground_occlusion_repaired_source
        and not reusable_insufficient_pose_low_visibility_source
        and not reusable_degraded_semantic_low_visibility_source
        and not reusable_clean_video_tal_late_weak_candidate_source
        and not reusable_sparse_track_stitched_candidate_source
    ):
        return None
    source = str(resolved.get("source") or "")
    if source not in {"video_ai_refined", "blended"}:
        return None
    long_unresolved_motion_fallback = _semantic_reuse_current_candidate_is_long_unresolved_motion_fallback(
        current_bio_data
    )
    if not _semantic_reuse_source_is_stable(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
        allowed_unstable_flags=_semantic_reuse_allowed_unstable_source_flags(
            resolved,
            video_temporal if isinstance(video_temporal, dict) else None,
            long_unresolved_motion_fallback=long_unresolved_motion_fallback,
            current_bio_data=current_bio_data,
            source_bio_data=source_bio_data,
        ),
    ):
        return None
    selected = _semantic_reuse_selected(resolved.get("selected"), analysis_profile)
    if not selected:
        return None
    current_resolved = {
        "source": resolved.get("source") or "video_ai_refined",
        "confidence": resolved.get("confidence"),
        "selected": selected,
        "video_ai": video_temporal if isinstance(video_temporal, dict) else None,
        "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
    }
    source_quality_flags = _merge_quality_flags(resolved, video_temporal if isinstance(video_temporal, dict) else None)
    _attach_semantic_reuse_source_candidate_conflict_context(
        current_resolved,
        source_quality_flags=source_quality_flags,
        source_semantic_candidate_tal_conflict=resolved.get("semantic_candidate_tal_conflict"),
    )
    if reusable_phase_range_weak_geometry_source:
        _append_quality_flags(
            current_resolved,
            "semantic_keyframes_reused_from_phase_range_weak_geometry_source",
        )
        current_resolved["semantic_reuse_source_context"] = {
            "decision": "reused_phase_range_tal_over_historical_weak_temporal_geometry",
            "source_quality_flags": _merge_quality_flags(
                resolved,
                video_temporal if isinstance(video_temporal, dict) else None,
            ),
        }
    if reusable_phase_range_late_reanchor_source:
        _append_quality_flags(
            current_resolved,
            "semantic_keyframes_reused_from_phase_range_late_reanchor_source",
        )
        current_resolved["semantic_reuse_source_context"] = {
            "decision": "reused_phase_range_late_reanchored_tal_over_current_early_motion_peak",
            "source_quality_flags": _merge_quality_flags(
                resolved,
                video_temporal if isinstance(video_temporal, dict) else None,
            ),
        }
    if reusable_foreground_occlusion_repaired_source:
        _append_quality_flags(
            current_resolved,
            "semantic_keyframes_reused_from_foreground_occlusion_repaired_source",
        )
        current_resolved["semantic_reuse_source_context"] = {
            "decision": "reused_foreground_occlusion_repaired_tal_with_current_pose_support",
            "source_quality_flags": _merge_quality_flags(
                resolved,
                video_temporal if isinstance(video_temporal, dict) else None,
            ),
        }
    if reusable_insufficient_pose_low_visibility_source:
        _append_quality_flags(
            current_resolved,
            "semantic_keyframes_reused_from_insufficient_pose_low_visibility_source",
        )
        current_resolved["semantic_reuse_source_context"] = {
            "decision": "reused_low_visibility_semantic_tal_over_untrusted_motion_fallback",
            "source_quality_flags": _merge_quality_flags(
                resolved,
                video_temporal if isinstance(video_temporal, dict) else None,
            ),
        }
    if reusable_degraded_semantic_low_visibility_source:
        _append_quality_flags(
            current_resolved,
            "semantic_keyframes_reused_from_degraded_semantic_low_visibility_source",
        )
        current_resolved["semantic_reuse_source_context"] = {
            "decision": "reused_degraded_semantic_tal_over_untrusted_motion_fallback",
            "source_quality_flags": _merge_quality_flags(
                resolved,
                video_temporal if isinstance(video_temporal, dict) else None,
            ),
        }
    if reusable_clean_video_tal_late_weak_candidate_source:
        _append_quality_flags(
            current_resolved,
            "semantic_keyframes_reused_from_clean_video_tal_late_weak_candidate_source",
        )
        current_resolved["semantic_reuse_source_context"] = {
            "decision": "reused_clean_video_tal_over_late_weak_candidate",
            "source_quality_flags": source_quality_flags,
            "candidate_quality_flags": _keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data),
        }
    if reusable_sparse_track_stitched_candidate_source:
        _append_quality_flags(
            current_resolved,
            "semantic_keyframes_reused_over_sparse_track_stitched_candidate",
        )
        current_resolved["semantic_reuse_sparse_track_stitched_candidate"] = {
            "decision": "reused_matching_video_over_sparse_track_stitched_candidate",
            "candidate_quality_flags": _keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data),
        }
    if long_unresolved_motion_fallback:
        _append_quality_flags(
            current_resolved,
            "semantic_keyframes_reused_over_long_unresolved_motion_fallback",
        )
        current_resolved["semantic_reuse_long_unresolved_motion_fallback"] = {
            "decision": "reused_matching_video_over_long_unresolved_motion_fallback",
            "candidate_quality_flags": _keyframe_candidate_quality_flags_for_semantic_reuse(current_bio_data),
            "candidate_tal_span_sec": _semantic_reuse_current_candidate_tal_span_sec(current_bio_data),
        }
    current_resolved = validate_semantic_keyframes_against_current_evidence(
        current_resolved,
        bio_data=current_bio_data,
        motion_scores=current_motion_scores,
        analysis_profile=analysis_profile,
    )
    if not semantic_keyframes_are_reliable(current_resolved):
        return None
    created_at = getattr(analysis, "created_at", None)
    source_penalty_flags = _semantic_reuse_source_penalty_flags(
        resolved,
        video_temporal if isinstance(video_temporal, dict) else None,
    )
    return {
        "analysis_id": analysis.id,
        "pipeline_version": analysis.pipeline_version,
        "selected": selected,
        "source": resolved.get("source") or "video_ai_refined",
        "confidence": resolved.get("confidence"),
        "source_quality_flags": source_quality_flags,
        "source_penalty_flags": source_penalty_flags,
        "source_penalty_count": len(source_penalty_flags),
        "source_semantic_candidate_tal_conflict": resolved.get("semantic_candidate_tal_conflict"),
        "created_at": created_at.isoformat() if created_at is not None else "",
        "created_at_timestamp": created_at.timestamp() if created_at is not None else 0.0,
        "phase_range_weak_geometry_source_override": reusable_phase_range_weak_geometry_source,
        "phase_range_late_reanchor_source_override": reusable_phase_range_late_reanchor_source,
        "foreground_occlusion_repaired_source_override": reusable_foreground_occlusion_repaired_source,
        "insufficient_pose_low_visibility_source_override": reusable_insufficient_pose_low_visibility_source,
        "degraded_semantic_low_visibility_source_override": reusable_degraded_semantic_low_visibility_source,
        "clean_video_tal_late_weak_candidate_source_override": reusable_clean_video_tal_late_weak_candidate_source,
        "sparse_track_stitched_candidate_override": reusable_sparse_track_stitched_candidate_source,
        "long_unresolved_motion_fallback_override": long_unresolved_motion_fallback,
        **{
            f"candidate_{key}": value
            for key, value in _semantic_reuse_current_candidate_delta_summary(selected, current_bio_data).items()
        },
    }


async def _find_matching_semantic_keyframes(
    *,
    session: AsyncSession,
    current_analysis_id: str,
    video_sha256: str | None,
    action_type: str | None,
    action_subtype: str | None,
    analysis_profile: str | None,
    current_motion_scores: dict[str, object] | None,
    current_bio_data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not video_sha256:
        return None
    result = await session.execute(
        select(Analysis)
        .where(Analysis.status == "completed")
        .where(Analysis.id != current_analysis_id)
        .where(Analysis.action_type == action_type)
        .where(Analysis.frame_motion_scores.contains(video_sha256))
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(100)
    )
    reuse_candidates: list[dict[str, Any]] = []
    for candidate in result.scalars().all():
        reuse = _semantic_reuse_candidate_from_analysis(
            candidate,
            current_analysis_id=current_analysis_id,
            video_sha256=video_sha256,
            action_type=action_type,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            current_motion_scores=current_motion_scores,
            current_bio_data=current_bio_data,
        )
        if reuse is not None:
            reuse_candidates.append(reuse)
    if not reuse_candidates:
        return None

    for reuse in reuse_candidates:
        peers = [
            peer
            for peer in reuse_candidates
            if peer.get("analysis_id") != reuse.get("analysis_id")
        ]
        reuse.update(
            _semantic_reuse_pairwise_stability_summary(
                reuse.get("selected") if isinstance(reuse.get("selected"), list) else [],
                peers,
                analysis_profile=analysis_profile,
            )
        )
        reuse["ranking_mode"] = (
            "current_pose_supported_candidate_delta"
            if int(reuse.get("candidate_supported_key_count") or 0) >= SEMANTIC_REUSE_CURRENT_CANDIDATE_MIN_SUPPORTED_KEYS
            else "historical_semantic_stability"
        )

    return sorted(reuse_candidates, key=_semantic_reuse_sort_key)[0]


async def _reuse_matching_semantic_keyframes(
    *,
    analysis_id: str,
    video_path: Path,
    processing_frames_dir: Path,
    video_identity: dict[str, Any] | None,
    action_type: str | None,
    action_subtype: str | None,
    analysis_profile: str | None,
    motion_scores: dict[str, object],
    bio_data: dict[str, Any] | None = None,
    video_temporal_result: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[Path], list[dict[str, Any]], dict[str, Any] | None]:
    sha256 = str((video_identity or {}).get("sha256") or "")
    if not sha256:
        return None, [], [], video_temporal_result
    async with AsyncSessionLocal() as session:
        reuse = await _find_matching_semantic_keyframes(
            session=session,
            current_analysis_id=analysis_id,
            video_sha256=sha256,
            action_type=action_type,
            action_subtype=action_subtype,
            analysis_profile=analysis_profile,
            current_motion_scores=motion_scores,
            current_bio_data=bio_data,
        )
    if reuse is None:
        return None, [], [], video_temporal_result

    selected = [dict(item) for item in reuse["selected"]]
    semantic_frames, semantic_records = await extract_precise_frames_at_timestamps(
        video_path,
        processing_frames_dir.parent / "semantic_frames",
        selected,
        prefix="semantic",
    )
    reused_selected: list[dict[str, Any]] = []
    for record in semantic_records:
        item = dict(record)
        original_selection_reason = str(item.get("selection_reason") or "")
        if original_selection_reason:
            item["semantic_reuse_original_selection_reason"] = original_selection_reason
        item["selection_reason"] = "semantic_reused_from_matching_video"
        item["reused_from_analysis_id"] = reuse["analysis_id"]
        item["reused_from_pipeline_version"] = reuse["pipeline_version"]
        item["reused_video_sha256"] = sha256
        if reuse.get("ranking_mode"):
            item["semantic_reuse_ranking_mode"] = reuse.get("ranking_mode")
        reused_selected.append(item)

    source = str(reuse.get("source") or "video_ai_refined")
    confidence = reuse.get("confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.90
    resolved = {
        "source": source if source in {"video_ai_refined", "blended"} else "video_ai_refined",
        "confidence": round(max(0.0, min(confidence_value, 1.0)), 3),
        "selected": reused_selected,
        "video_ai": video_temporal_result,
        "reused_from_analysis_id": reuse["analysis_id"],
        "reused_from_pipeline_version": reuse["pipeline_version"],
        "reused_video_sha256": sha256,
        "semantic_reuse_ranking": {
            "mode": reuse.get("ranking_mode"),
            "candidate_mean_abs_delta_sec": reuse.get("candidate_mean_abs_delta_sec"),
            "candidate_max_abs_delta_sec": reuse.get("candidate_max_abs_delta_sec"),
            "candidate_supported_mean_abs_delta_sec": reuse.get("candidate_supported_mean_abs_delta_sec"),
            "candidate_supported_max_abs_delta_sec": reuse.get("candidate_supported_max_abs_delta_sec"),
            "candidate_supported_key_count": reuse.get("candidate_supported_key_count"),
            "candidate_pose_supported_keys": reuse.get("candidate_pose_supported_keys"),
            "source_penalty_flags": reuse.get("source_penalty_flags"),
            "source_penalty_count": reuse.get("source_penalty_count"),
            "phase_range_weak_geometry_source_override": reuse.get("phase_range_weak_geometry_source_override"),
            "phase_range_late_reanchor_source_override": reuse.get("phase_range_late_reanchor_source_override"),
            "foreground_occlusion_repaired_source_override": reuse.get("foreground_occlusion_repaired_source_override"),
            "insufficient_pose_low_visibility_source_override": reuse.get("insufficient_pose_low_visibility_source_override"),
            "degraded_semantic_low_visibility_source_override": reuse.get("degraded_semantic_low_visibility_source_override"),
            "clean_video_tal_late_weak_candidate_source_override": reuse.get("clean_video_tal_late_weak_candidate_source_override"),
            "sparse_track_stitched_candidate_override": reuse.get("sparse_track_stitched_candidate_override"),
            "long_unresolved_motion_fallback_override": reuse.get("long_unresolved_motion_fallback_override"),
            "peer_count": reuse.get("peer_count"),
            "peer_mean_abs_delta_sec": reuse.get("peer_mean_abs_delta_sec"),
            "peer_max_abs_delta_sec": reuse.get("peer_max_abs_delta_sec"),
        },
        "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
    }
    source_quality_flags = [str(flag) for flag in reuse.get("source_quality_flags") or [] if str(flag).strip()]
    _attach_semantic_reuse_source_candidate_conflict_context(
        resolved,
        source_quality_flags=source_quality_flags,
        source_semantic_candidate_tal_conflict=reuse.get("source_semantic_candidate_tal_conflict"),
    )
    if reuse.get("phase_range_weak_geometry_source_override"):
        _append_quality_flags(
            resolved,
            "semantic_keyframes_reused_from_phase_range_weak_geometry_source",
        )
        resolved["semantic_reuse_source_context"] = {
            "decision": "reused_phase_range_tal_over_historical_weak_temporal_geometry",
            "source_quality_flags": reuse.get("source_quality_flags"),
        }
    if reuse.get("phase_range_late_reanchor_source_override"):
        _append_quality_flags(
            resolved,
            "semantic_keyframes_reused_from_phase_range_late_reanchor_source",
        )
        resolved["semantic_reuse_source_context"] = {
            "decision": "reused_phase_range_late_reanchored_tal_over_current_early_motion_peak",
            "source_quality_flags": reuse.get("source_quality_flags"),
        }
    if reuse.get("foreground_occlusion_repaired_source_override"):
        _append_quality_flags(
            resolved,
            "semantic_keyframes_reused_from_foreground_occlusion_repaired_source",
        )
        resolved["semantic_reuse_source_context"] = {
            "decision": "reused_foreground_occlusion_repaired_tal_with_current_pose_support",
            "source_quality_flags": reuse.get("source_quality_flags"),
        }
    if reuse.get("insufficient_pose_low_visibility_source_override"):
        _append_quality_flags(
            resolved,
            "semantic_keyframes_reused_from_insufficient_pose_low_visibility_source",
        )
        resolved["semantic_reuse_source_context"] = {
            "decision": "reused_low_visibility_semantic_tal_over_untrusted_motion_fallback",
            "source_quality_flags": reuse.get("source_quality_flags"),
        }
    if reuse.get("degraded_semantic_low_visibility_source_override"):
        _append_quality_flags(
            resolved,
            "semantic_keyframes_reused_from_degraded_semantic_low_visibility_source",
        )
        resolved["semantic_reuse_source_context"] = {
            "decision": "reused_degraded_semantic_tal_over_untrusted_motion_fallback",
            "source_quality_flags": reuse.get("source_quality_flags"),
        }
    if reuse.get("clean_video_tal_late_weak_candidate_source_override"):
        _append_quality_flags(
            resolved,
            "semantic_keyframes_reused_from_clean_video_tal_late_weak_candidate_source",
        )
        resolved["semantic_reuse_source_context"] = {
            "decision": "reused_clean_video_tal_over_late_weak_candidate",
            "source_quality_flags": reuse.get("source_quality_flags"),
            "candidate_quality_flags": _keyframe_candidate_quality_flags_for_semantic_reuse(bio_data),
        }
    if reuse.get("sparse_track_stitched_candidate_override"):
        _append_quality_flags(
            resolved,
            "semantic_keyframes_reused_over_sparse_track_stitched_candidate",
        )
        resolved["semantic_reuse_sparse_track_stitched_candidate"] = {
            "decision": "reused_matching_video_over_sparse_track_stitched_candidate",
            "candidate_quality_flags": _keyframe_candidate_quality_flags_for_semantic_reuse(bio_data),
        }
    if reuse.get("long_unresolved_motion_fallback_override"):
        _append_quality_flags(
            resolved,
            "semantic_keyframes_reused_over_long_unresolved_motion_fallback",
        )
        resolved["semantic_reuse_long_unresolved_motion_fallback"] = {
            "decision": "reused_matching_video_over_long_unresolved_motion_fallback",
            "candidate_quality_flags": _keyframe_candidate_quality_flags_for_semantic_reuse(bio_data),
            "candidate_tal_span_sec": _semantic_reuse_current_candidate_tal_span_sec(bio_data),
        }
    if isinstance(video_temporal_result, dict):
        video_temporal_result = dict(video_temporal_result)
        video_temporal_result["reused_semantic_keyframes_from_analysis_id"] = reuse["analysis_id"]
        video_temporal_result["quality_flags"] = _merge_quality_flags(
            video_temporal_result,
            ["semantic_keyframes_reused_from_matching_video"],
        )
    else:
        video_temporal_result = {
            "valid": True,
            "confidence": resolved["confidence"],
            "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
            "fallback_recommendation": "use_reused_matching_video_timestamps",
            "reused_semantic_keyframes_from_analysis_id": reuse["analysis_id"],
        }
    resolved["video_ai"] = video_temporal_result
    resolved = validate_semantic_keyframes_against_current_evidence(
        resolved,
        bio_data=bio_data,
        motion_scores=motion_scores,
        analysis_profile=analysis_profile,
    )
    if not semantic_keyframes_are_reliable(resolved):
        return None, [], [], video_temporal_result
    return resolved, semantic_frames, reused_selected, video_temporal_result


def _merge_video_temporal_cross_validation(
    cross_validation: dict[str, Any] | None,
    *,
    video_temporal: dict[str, Any] | None = None,
    resolved_keyframes: dict[str, Any] | None = None,
    frame_motion_scores: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(cross_validation, dict):
        return cross_validation
    merged = dict(cross_validation)
    motion = frame_motion_scores if isinstance(frame_motion_scores, dict) else {}
    temporal = video_temporal if isinstance(video_temporal, dict) else motion.get("video_temporal")
    keyframes = resolved_keyframes if isinstance(resolved_keyframes, dict) else motion.get("resolved_keyframes")
    if isinstance(temporal, dict):
        merged["video_temporal"] = temporal
    if isinstance(keyframes, dict):
        merged["resolved_keyframes"] = keyframes
    return merged


def _compact_report_path_b_evidence(path_b: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(path_b, dict) or path_b.get("error"):
        return None

    frames: list[dict[str, Any]] = []
    for frame in path_b.get("frame_analysis", []) if isinstance(path_b.get("frame_analysis"), list) else []:
        if not isinstance(frame, dict):
            continue
        frames.append(
            {
                "frame_id": frame.get("frame_id"),
                "phase": frame.get("phase"),
                "bio_observations": frame.get("bio_observations") if isinstance(frame.get("bio_observations"), dict) else {},
                "issues": frame.get("issues") if isinstance(frame.get("issues"), list) else [],
                "confidence": frame.get("confidence"),
            }
        )
        if len(frames) >= 8:
            break

    return {
        "top_issues": path_b.get("top_issues") if isinstance(path_b.get("top_issues"), list) else [],
        "top_positives": path_b.get("top_positives") if isinstance(path_b.get("top_positives"), list) else [],
        "action_phase_summary": path_b.get("action_phase_summary") if isinstance(path_b.get("action_phase_summary"), dict) else {},
        "frame_analysis": frames,
    }


def _attach_path_b_report_evidence(
    dual_path_meta: dict[str, Any] | None,
    path_b: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(dual_path_meta, dict):
        return dual_path_meta
    evidence = _compact_report_path_b_evidence(path_b)
    if not evidence:
        return dual_path_meta
    return {**dual_path_meta, "path_b_evidence": evidence}


PHASE_LABEL_TO_JUMP_PARTIAL_CODE = {
    "起跳": ("takeoff", "T_takeoff_sec"),
    "腾空": ("air", "A_air_sec"),
    "空中": ("air", "A_air_sec"),
    "落冰": ("landing", "L_landing_sec"),
    "落地": ("landing", "L_landing_sec"),
}


def _motion_timestamp_by_frame_id(frame_motion_scores: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(frame_motion_scores, dict):
        return {}
    output: dict[str, float] = {}
    for item in frame_motion_scores.get("selected", []) if isinstance(frame_motion_scores.get("selected"), list) else []:
        if not isinstance(item, dict):
            continue
        frame_id = str(item.get("frame_id") or "").removesuffix(".jpg")
        try:
            timestamp = float(item.get("timestamp"))
        except (TypeError, ValueError):
            continue
        if frame_id:
            output[frame_id] = timestamp
    return output


def _phase_anchor_records_from_vision(
    vision_structured: dict[str, Any] | None,
    frame_motion_scores: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
) -> list[dict[str, Any]]:
    if str(analysis_profile or "").strip().lower() != "jump" or not isinstance(vision_structured, dict):
        return []
    frame_analysis = vision_structured.get("frame_analysis")
    if not isinstance(frame_analysis, list):
        return []
    timestamp_by_frame = _motion_timestamp_by_frame_id(frame_motion_scores)
    by_phase: dict[str, list[dict[str, Any]]] = {}
    for frame in frame_analysis:
        if not isinstance(frame, dict):
            continue
        phase = str(frame.get("phase") or "").strip()
        mapped = next((value for label, value in PHASE_LABEL_TO_JUMP_PARTIAL_CODE.items() if label in phase), None)
        if mapped is None:
            continue
        phase_code, key_moment = mapped
        frame_id = str(frame.get("frame_id") or "").removesuffix(".jpg")
        timestamp = timestamp_by_frame.get(frame_id)
        if timestamp is None:
            continue
        try:
            confidence = float(frame.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        by_phase.setdefault(phase_code, []).append(
            {
                "frame_id": frame_id,
                "timestamp": timestamp,
                "confidence": max(0.05, min(confidence, 0.35)),
                "phase_code": phase_code,
                "phase_label": phase,
                "key_moment": key_moment,
                "selection_reason": "post_vision_low_confidence_phase_anchor",
                "partial_semantic_frame": True,
                "selection_status": "partial_unreliable",
            }
        )

    output: list[dict[str, Any]] = []
    for phase_code in ("takeoff", "air", "landing"):
        candidates = by_phase.get(phase_code) or []
        if not candidates:
            continue
        candidates.sort(key=lambda item: (item["confidence"], item["timestamp"]), reverse=True)
        output.append(candidates[0])
    return output


async def _attach_post_vision_partial_semantic_frames(
    *,
    video_path: Path,
    semantic_frames_dir: Path,
    resolved_keyframes: dict[str, Any] | None,
    vision_structured: dict[str, Any] | None,
    frame_motion_scores: dict[str, Any] | None,
    analysis_profile: str | None,
) -> dict[str, Any] | None:
    if not isinstance(resolved_keyframes, dict) or semantic_keyframes_are_reliable(resolved_keyframes):
        return resolved_keyframes
    existing_partial = resolved_keyframes.get("partial_selected")
    if isinstance(existing_partial, list) and existing_partial:
        return resolved_keyframes
    candidates = _phase_anchor_records_from_vision(
        vision_structured,
        frame_motion_scores,
        analysis_profile=analysis_profile,
    )
    if not candidates:
        return resolved_keyframes
    try:
        _, partial_records = await extract_precise_frames_at_timestamps(
            video_path,
            semantic_frames_dir,
            candidates,
            prefix="partial_semantic",
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Post-vision partial semantic frame extraction failed: %s", exc)
        return resolved_keyframes
    resolved = dict(resolved_keyframes)
    resolved["partial_selected"] = partial_records
    flags = resolved.get("quality_flags") if isinstance(resolved.get("quality_flags"), list) else []
    for flag in (
        "semantic_keyframes_post_vision_partial_phase_frames_available",
        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
    ):
        if flag not in flags:
            flags = [*flags, flag]
    resolved["quality_flags"] = flags
    return resolved


def _video_temporal_diagnostics(frame_motion_scores: dict[str, Any] | None, *, analysis_id: str | None = None) -> dict[str, Any] | None:
    if not isinstance(frame_motion_scores, dict):
        return None
    video_temporal = frame_motion_scores.get("video_temporal")
    resolved_keyframes = frame_motion_scores.get("resolved_keyframes")
    if not isinstance(video_temporal, dict) and not isinstance(resolved_keyframes, dict):
        return None

    selected = resolved_keyframes.get("selected") if isinstance(resolved_keyframes, dict) else None
    partial_selected = resolved_keyframes.get("partial_selected") if isinstance(resolved_keyframes, dict) else None
    quality_flags: list[str] = []
    for source in (video_temporal, resolved_keyframes):
        flags = source.get("quality_flags") if isinstance(source, dict) else None
        if isinstance(flags, list):
            quality_flags.extend(str(flag) for flag in flags if flag)

    fallback_reason = None
    if isinstance(video_temporal, dict):
        fallback_reason = video_temporal.get("fallback_reason") or video_temporal.get("fallback_recommendation")
    used_semantic_frames = semantic_keyframes_are_reliable(resolved_keyframes if isinstance(resolved_keyframes, dict) else None)
    resolver_source = resolved_keyframes.get("source") if isinstance(resolved_keyframes, dict) else None
    timestamp_source = effective_timestamp_source(
        resolved_keyframes if isinstance(resolved_keyframes, dict) else None,
        used_semantic_frames,
    )
    return {
        "video_ai_model": video_temporal.get("model") if isinstance(video_temporal, dict) else None,
        "video_ai_provider": video_temporal.get("provider") if isinstance(video_temporal, dict) else None,
        "video_ai_confidence": video_temporal.get("confidence") if isinstance(video_temporal, dict) else None,
        "video_ai_ran": isinstance(video_temporal, dict),
        "video_ai_video_url": f"/api/analysis/{analysis_id}/video" if analysis_id else None,
        "raw_response_excerpt": video_temporal.get("raw_response_excerpt") if isinstance(video_temporal, dict) else None,
        "raw_response_length": video_temporal.get("raw_response_length") if isinstance(video_temporal, dict) else None,
        "raw_response_truncated": video_temporal.get("raw_response_truncated") if isinstance(video_temporal, dict) else None,
        "parse_error_detail": video_temporal.get("parse_error_detail") if isinstance(video_temporal, dict) else None,
        "timestamp_source": timestamp_source,
        "resolver_source": resolver_source,
        "resolved_confidence": resolved_keyframes.get("confidence") if isinstance(resolved_keyframes, dict) else None,
        "selected_semantic_frames": selected if isinstance(selected, list) else [],
        "partial_semantic_frames": partial_selected if isinstance(partial_selected, list) else [],
        "fallback_reason": fallback_reason,
        "quality_flags": list(dict.fromkeys(quality_flags)),
        "retry_rejection_flags": (
            resolved_keyframes.get("video_temporal_quality_retry_rejection_flags")
            if isinstance(resolved_keyframes, dict)
            and isinstance(resolved_keyframes.get("video_temporal_quality_retry_rejection_flags"), list)
            else []
        ),
        "used_semantic_frames": used_semantic_frames,
        "used_legacy_sampled_frames": not used_semantic_frames,
    }


async def _await_video_temporal_result(
    task: asyncio.Task | None,
    *,
    analysis_id: str,
) -> dict[str, Any] | None:
    if task is None:
        return None
    try:
        return await asyncio.wait_for(task, timeout=VIDEO_TEMPORAL_WAIT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        task.cancel()
        await _append_analysis_log(
            analysis_id,
            stage="vision",
            level="warning",
            message="视频语义时间定位超时，回退使用现有关键帧。",
            detail="video_temporal_timeout",
        )
        return {
            "schema_version": "video_temporal_v1",
            "provider": "qwen",
            "model": "qwen3.6-plus",
            "valid": False,
            "phase_segments": [],
            "confidence": 0.0,
            "fallback_recommendation": "use_existing_skeleton_timestamps",
            "fallback_reason": "video_temporal_timeout",
            "quality_flags": ["video_temporal_timeout"],
        }
    except Exception as exc:  # noqa: BLE001
        await _append_analysis_log(
            analysis_id,
            stage="vision",
            level="warning",
            message="视频语义时间定位失败，回退使用现有关键帧。",
            detail=stringify_exception(exc),
        )
        return {
            "schema_version": "video_temporal_v1",
            "provider": "qwen",
            "model": "qwen3.6-plus",
            "valid": False,
            "phase_segments": [],
            "confidence": 0.0,
            "fallback_recommendation": "use_existing_skeleton_timestamps",
            "fallback_reason": "video_temporal_task_failed",
            "quality_flags": ["video_temporal_task_failed"],
        }


def _coerce_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_log_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _coerce_utc_datetime(parsed)


def _retry_stage_from_status(status_value: str | None) -> str | None:
    if status_value == "extracting_frames":
        return "extract_frames"
    if status_value == "analyzing":
        return "vision"
    if status_value == "generating_report":
        return "report"
    if status_value in {"pending", "processing"}:
        return "extract_frames"
    return None


def _build_stale_analysis_snapshot(analysis: Analysis) -> Analysis | None:
    if analysis.status not in IN_PROGRESS_ANALYSIS_STATUSES:
        return None

    logs = _normalize_processing_logs(analysis.processing_logs)
    latest_log_ts = max(
        (timestamp for timestamp in (_parse_log_timestamp(item.get("timestamp")) for item in logs) if timestamp is not None),
        default=None,
    )
    updated_at = _coerce_utc_datetime(analysis.updated_at)
    reference_time = max((value for value in (latest_log_ts, updated_at) if value is not None), default=None)
    if reference_time is None:
        return None

    stale_for_seconds = (datetime.now(timezone.utc) - reference_time).total_seconds()
    if stale_for_seconds < STALE_ANALYSIS_TIMEOUT_SECONDS:
        return None

    retry_from_stage = analysis.retry_from_stage or _retry_stage_from_status(analysis.status)
    detail = (
        f"Analysis heartbeat stalled for {round(stale_for_seconds, 1)}s while status={analysis.status}. "
        "The worker likely exited before writing a terminal state."
    )
    logger.warning("Analysis %s detected as stale in-progress task: %s", analysis.id, detail)

    logs.append(
        {
            "timestamp": _utc_now_iso(),
            "stage": "pipeline",
            "level": "error",
            "message": "分析任务长时间无进展，已自动标记为失败，可重试。",
            "retry_from_stage": retry_from_stage,
            "error_code": AnalysisErrorCode.UNKNOWN_ERROR.value,
            "detail": detail,
        }
    )
    snapshot = Analysis()
    for key, value in analysis.__dict__.items():
        if key.startswith("_sa_"):
            continue
        setattr(snapshot, key, value)
    snapshot.status = "failed"
    snapshot.retry_from_stage = retry_from_stage
    snapshot.error_code = AnalysisErrorCode.UNKNOWN_ERROR.value
    snapshot.error_message = "分析任务中断，请重试。"
    snapshot.error_detail = detail
    snapshot.processing_logs = logs[-MAX_ANALYSIS_LOG_ENTRIES:]
    return snapshot


async def _recover_stale_analyses(session: AsyncSession, analyses: list[Analysis]) -> list[Analysis]:
    recovered: list[Analysis] = []
    for analysis in analyses:
        recovered.append(_build_stale_analysis_snapshot(analysis) or analysis)
    return recovered


async def _append_analysis_log(
    analysis_id: str,
    *,
    stage: str,
    level: str,
    message: str,
    elapsed_s: float | None = None,
    retry_from_stage: str | None = None,
    error_code: str | None = None,
    detail: str | None = None,
    status_value: str | None = None,
    timings: dict[str, float] | None = None,
    **extra: Any,
) -> None:
    entry: dict[str, Any] = {
        "timestamp": _utc_now_iso(),
        "stage": stage,
        "level": level,
        "message": message,
    }
    if elapsed_s is not None:
        entry["elapsed_s"] = round(float(elapsed_s), 2)
    if retry_from_stage:
        entry["retry_from_stage"] = retry_from_stage
    if error_code:
        entry["error_code"] = error_code
    if detail:
        entry["detail"] = detail
    for key, value in extra.items():
        if value is not None:
            entry[key] = value

    log_method = getattr(logger, level.lower(), logger.info)
    log_method("Analysis %s [%s] %s", analysis_id, stage, message)

    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            logs = _normalize_processing_logs(analysis.processing_logs)
            logs.append(entry)
            analysis.processing_logs = logs[-MAX_ANALYSIS_LOG_ENTRIES:]
            if status_value is not None:
                analysis.status = status_value
            if timings is not None:
                analysis.processing_timings = dict(timings)
            await session.commit()

    try:
        await run_db_write_with_retry(_write, context=f"append_analysis_log:{analysis_id}:{stage}")
    except Exception:  # noqa: BLE001
        logger.exception("Analysis %s failed to append processing log", analysis_id)


def _log_analysis_timings(
    analysis_id: str,
    timings: dict[str, float],
    *,
    context: str = "completed",
) -> None:
    logger.info("Analysis %s timings (%s): %s", analysis_id, context, timings)


async def _persist_processing_timings(analysis_id: str, timings: dict[str, float]) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            analysis.processing_timings = dict(timings)
            await session.commit()

    try:
        await run_db_write_with_retry(_write, context=f"persist_processing_timings:{analysis_id}")
    except Exception:  # noqa: BLE001
        logger.exception("Analysis %s failed to persist processing timings", analysis_id)


async def _regenerate_report_from_saved_analysis(
    analysis_id: str,
    timings: dict[str, float],
    total_start: float,
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            if not isinstance(analysis.vision_structured, dict):
                raise RuntimeError("report-only retry requires saved vision_structured")
            if not isinstance(analysis.bio_data, dict):
                raise RuntimeError("report-only retry requires saved bio_data")
            action_type = analysis.action_type
            action_subtype = analysis.action_subtype
            skill_category = analysis.skill_category
            analysis_profile = analysis.analysis_profile
            skater_id = analysis.skater_id
            vision_structured = analysis.vision_structured
            bio_data = analysis.bio_data
            frame_motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
            dual_path_meta = _merge_video_temporal_cross_validation(
                analysis.cross_validation if isinstance(analysis.cross_validation, dict) else None,
                frame_motion_scores=frame_motion_scores,
            )
            dual_path_meta = _attach_path_b_report_evidence(
                dual_path_meta,
                analysis.vision_path_b if isinstance(analysis.vision_path_b, dict) else None,
            )
            user_note = analysis.note
            profile_evidence = bio_data.get("profile_evidence") if isinstance(bio_data.get("profile_evidence"), dict) else None

        await _append_analysis_log(
            analysis_id,
            stage="report",
            level="info",
            message="开始重新生成训练报告，复用已保存的视觉和生物力学结果。",
            status_value="generating_report",
            retry_from_stage="report",
        )
        await _set_analysis_status(analysis_id, "generating_report")

        report_start = time.monotonic()
        report = await generate_report(
            action_type,
            vision_structured,
            bio_data,
            skater_id,
            dual_path_meta=dual_path_meta,
            prompt_context=await build_analysis_prompt_context(
                action_type=action_type,
                action_subtype=action_subtype,
                skill_category=skill_category,
                analysis_profile=analysis_profile,
                profile_evidence=profile_evidence,
                motion_features=frame_motion_scores,
                bio_data=bio_data,
                skater_id=skater_id,
                user_note=user_note,
            ),
        )
        force_score = apply_child_score_floor(calculate_force_score(report), report, dual_path_meta)
        timings["report_s"] = _elapsed_seconds(report_start)
        timings["total_s"] = _elapsed_seconds(total_start)

        await _append_analysis_log(
            analysis_id,
            stage="report",
            level="info",
            message=f"报告重新生成完成，Force Score={force_score}。",
            elapsed_s=timings["report_s"],
            timings=timings,
        )

        async def _save_regenerated_report() -> None:
            saved_skater_id: str | None = None
            async with AsyncSessionLocal() as session:
                analysis = await session.get(Analysis, analysis_id)
                if analysis is None:
                    return
                should_update_skill_progress = analysis.status != "completed"
                analysis.report = report
                analysis.force_score = force_score
                analysis.processing_timings = dict(timings)
                analysis.pipeline_version = CURRENT_PIPELINE_VERSION
                analysis.status = "completed"
                analysis.error_code = None
                analysis.error_detail = None
                analysis.error_message = None
                analysis.retry_from_stage = None
                if should_update_skill_progress:
                    await auto_update_skill_progress(analysis_id, session)
                if analysis.skater_id:
                    saved_skater_id = analysis.skater_id
                    await sync_skater_progress(session, analysis.skater_id)
                await session.commit()

            if saved_skater_id:
                try:
                    async with AsyncSessionLocal() as memory_session:
                        await suggest_memory_updates(analysis_id, saved_skater_id, memory_session)
                except Exception:  # noqa: BLE001
                    logger.exception("Analysis %s memory suggestion generation failed", analysis_id)

        await run_db_write_with_retry(_save_regenerated_report, context=f"save_regenerated_report:{analysis_id}")

        _log_analysis_timings(analysis_id, timings, context="report_only_retry")
        await _append_analysis_log(
            analysis_id,
            stage="pipeline",
            level="info",
            message="报告重生成流程已完成。",
            elapsed_s=timings["total_s"],
            timings=timings,
        )
    except Exception as exc:  # noqa: BLE001
        failure = classify_ai_failure(exc)
        timings["total_s"] = _elapsed_seconds(total_start)
        await _mark_analysis_failed(analysis_id, failure.code, failure.detail, stage="report", timings=timings)


def _is_retry_stage(value: str | None) -> bool:
    return value in PIPELINE_STAGES


def _default_retry_stage_for_error(error_code: str | None) -> str | None:
    if not error_code:
        return None
    if error_code in {
        AnalysisErrorCode.AI_API_TIMEOUT.value,
        AnalysisErrorCode.AI_API_AUTH_ERROR.value,
        AnalysisErrorCode.AI_API_QUOTA_EXCEEDED.value,
        AnalysisErrorCode.AI_API_CONTENT_FILTER.value,
        AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL.value,
    }:
        return "vision"
    return None


async def _start_video_temporal_task_if_missing(
    *,
    analysis_id: str,
    video_path: Path,
    processing_frames_dir: Path,
    sampling_metadata: VideoSamplingMetadata,
    action_type: str,
    action_subtype: str | None,
    user_note: str | None,
    motion_scores: dict[str, object],
    current_task: asyncio.Task | None,
    input_window: VideoInputWindow | None,
) -> tuple[asyncio.Task | None, float | None, dict[str, Any] | None]:
    if current_task is not None or isinstance(motion_scores.get("video_temporal"), dict):
        return current_task, None, None
    handle = await start_video_temporal_task(
        video_path=video_path,
        work_dir=processing_frames_dir.parent,
        sampling_metadata=sampling_metadata,
        action_type=action_type,
        action_subtype=action_subtype,
        user_note=user_note,
        analyzed_video_kind="action_window_ai",
        input_window=input_window,
        precheck=False,
    )
    await _append_analysis_log(
        analysis_id,
        stage='extract_frames',
        level='info',
        message='已启动视频 AI 语义时间定位。',
        detail='video_temporal_task_started',
        analyzed_video_path=str(handle.ai_clip_path),
        timestamp_offset_sec=handle.timestamp_offset_sec,
        clip_duration_sec=handle.clip_duration_sec,
        input_window=handle.input_window.to_payload(),
    )
    return handle.task, handle.source_duration_sec, handle.ai_clip_payload()


async def process_analysis(analysis_id: str, retry_from: str | None = None) -> None:
    timings: dict[str, float] = {}
    total_start = time.monotonic()
    processing_frames_dir: Path | None = None
    upload_frames_dir: Path | None = None
    action_type: str | None = None
    skater_id: str | None = None
    action_subtype: str | None = None
    analysis_profile_hint: str | None = None
    existing_target_lock: dict[str, object] | None = None
    saved_motion_scores: dict[str, object] | None = None
    saved_action_window_start = 0.0
    saved_action_window_end = 0.0
    saved_source_fps = 30.0
    saved_is_slow_motion = False
    input_window: VideoInputWindow | None = None
    video_temporal_task: asyncio.Task | None = None
    video_temporal_result: dict[str, Any] | None = None
    video_temporal_ai_clip: dict[str, Any] | None = None
    resolved_keyframes: dict[str, Any] | None = None
    video_temporal_duration_sec: float | None = None
    video_identity: dict[str, Any] | None = None
    retry_from_stage: str | None = retry_from if _is_retry_stage(retry_from) else None
    try:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return

            if retry_from_stage is None and _is_retry_stage(analysis.retry_from_stage):
                retry_from_stage = analysis.retry_from_stage
            if retry_from_stage is None:
                retry_from_stage = _default_retry_stage_for_error(analysis.error_code)

            analysis.status = 'processing'
            analysis.error_code = None
            analysis.error_detail = None
            analysis.error_message = None
            analysis.processing_timings = None
            analysis.processing_logs = []
            await session.commit()
            logger.info('Analysis %s entered processing from stage=%s', analysis_id, retry_from_stage or 'extract_frames')

            action_type = analysis.action_type
            action_subtype = normalize_action_subtype(analysis.action_type, analysis.action_subtype)
            analysis_profile_hint = _analysis_profile_hint_for_sampling(action_type, action_subtype, analysis.analysis_profile)
            skater_id = analysis.skater_id
            skill_category = analysis.skill_category
            video_path = _video_path_for_analysis(analysis)
            upload_frames_dir = video_path.parent / 'frames'
            _, processing_frames_dir = build_processing_frames_dir(analysis_id)
            analysis.action_subtype = action_subtype
            analysis.pipeline_version = CURRENT_PIPELINE_VERSION
            await session.commit()
            existing_target_lock = analysis.target_lock if isinstance(analysis.target_lock, dict) else None
            saved_motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
            saved_action_window_start = float(analysis.action_window_start or 0.0)
            saved_action_window_end = float(analysis.action_window_end or 0.0)
            saved_source_fps = float(analysis.source_fps or 30.0)
            saved_is_slow_motion = bool(analysis.is_slow_motion)
            input_window = build_video_input_window(
                video_path,
                manual_start_sec=analysis.manual_action_window_start,
                manual_end_sec=analysis.manual_action_window_end,
            )
            video_identity = _video_identity_from_motion(saved_motion_scores)

        if video_identity is None:
            try:
                video_identity = _video_identity_payload(
                    video_path,
                    await asyncio.to_thread(compute_video_sha256, video_path),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Analysis %s failed to compute video hash: %s", analysis_id, exc)

        if retry_from_stage == "report":
            await _regenerate_report_from_saved_analysis(analysis_id, timings, total_start)
            return

        await _append_analysis_log(
            analysis_id,
            stage='pipeline',
            level='info',
            message=f"开始分析流程，从 {retry_from_stage or 'extract_frames'} 阶段启动。",
            retry_from_stage=retry_from_stage,
        )

        start_idx = PIPELINE_STAGES.index(retry_from_stage) if retry_from_stage else 0
        run_extract_frames = start_idx <= PIPELINE_STAGES.index('extract_frames')
        run_pose = start_idx <= PIPELINE_STAGES.index('pose')
        run_biomechanics = start_idx <= PIPELINE_STAGES.index('biomechanics')
        run_vision = start_idx <= PIPELINE_STAGES.index('vision')

        sampled_frames: list[Path]
        motion_scores: dict[str, object]
        sampling_metadata: VideoSamplingMetadata
        target_lock: dict[str, Any]

        if run_extract_frames:
            await _append_analysis_log(
                analysis_id,
                stage='extract_frames',
                level='info',
                message='开始提取关键帧。',
                status_value='extracting_frames',
            )
            await _set_analysis_status(analysis_id, 'extracting_frames')
            extract_start = time.monotonic()
            existing_target_lock_confirmed = _is_confirmed_target_lock(existing_target_lock)
            if existing_target_lock_confirmed and upload_frames_dir is not None and upload_frames_dir.exists():
                sampled_frames = persist_frames(sorted(upload_frames_dir.glob('frame_*.jpg')), processing_frames_dir)
                motion_scores = saved_motion_scores if isinstance(saved_motion_scores, dict) else _fallback_motion_payload(upload_frames_dir)
                motion_scores = attach_input_window_payload(dict(motion_scores), input_window)
                motion_scores = _attach_video_identity(motion_scores, video_identity) or motion_scores
                sampling_metadata = _sampling_metadata_from_saved(
                    action_window_start=saved_action_window_start,
                    action_window_end=saved_action_window_end,
                    source_fps=saved_source_fps,
                    is_slow_motion=saved_is_slow_motion,
                    motion_scores=motion_scores,
                )
                try:
                    video_temporal_task, started_duration, started_ai_clip = await _start_video_temporal_task_if_missing(
                        analysis_id=analysis_id,
                        video_path=video_path,
                        processing_frames_dir=processing_frames_dir,
                        sampling_metadata=sampling_metadata,
                        action_type=action_type,
                        action_subtype=action_subtype,
                        user_note=analysis.note,
                        motion_scores=motion_scores,
                        current_task=video_temporal_task,
                        input_window=input_window,
                    )
                    if started_duration is not None:
                        video_temporal_duration_sec = started_duration
                    if isinstance(started_ai_clip, dict):
                        video_temporal_ai_clip = started_ai_clip
                        await _append_analysis_log(
                            analysis_id,
                            stage='extract_frames',
                            level='info',
                            message='复用缓存帧但缺少视频语义定位结果，已补跑视频 AI 时间定位。',
                            detail='cache_reuse_missing_video_temporal',
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Analysis %s failed to start video temporal task on cache reuse: %s", analysis_id, exc)
                    await _append_analysis_log(
                        analysis_id,
                        stage='extract_frames',
                        level='warning',
                        message='复用缓存帧时启动视频语义定位失败，将回退使用现有关键帧。',
                        detail=stringify_exception(exc),
                    )
                await _append_analysis_log(
                    analysis_id,
                    stage='extract_frames',
                    level='info',
                    message='复用已锁定目标后的缓存帧，无需重新抽帧。',
                )
            else:
                try:
                    logger.info('Analysis %s extracting frames with profile=%s', analysis_id, analysis_profile_hint)
                    await precheck_video(video_path)
                    sampled_frames, motion_scores, sampling_metadata = await extract_motion_sampled_frames(
                        video_path,
                        processing_frames_dir,
                        action_type,
                        analysis_profile_hint,
                        input_window=input_window,
                    )
                    motion_scores = attach_input_window_payload(dict(motion_scores), input_window)
                    motion_scores = _attach_video_identity(motion_scores, video_identity) or motion_scores
                    video_temporal_task, started_duration, started_ai_clip = await _start_video_temporal_task_if_missing(
                        analysis_id=analysis_id,
                        video_path=video_path,
                        processing_frames_dir=processing_frames_dir,
                        sampling_metadata=sampling_metadata,
                        action_type=action_type,
                        action_subtype=action_subtype,
                        user_note=analysis.note,
                        motion_scores=motion_scores,
                        current_task=video_temporal_task,
                        input_window=input_window,
                    )
                    if started_duration is not None:
                        video_temporal_duration_sec = started_duration
                    if isinstance(started_ai_clip, dict):
                        video_temporal_ai_clip = started_ai_clip
                except Exception as exc:  # noqa: BLE001
                    failure = classify_video_failure(exc)
                    timings['total_s'] = _elapsed_seconds(total_start)
                    await _mark_analysis_failed(analysis_id, failure.code, failure.detail, stage='extract_frames', timings=timings)
                    return
            timings['extract_frames_s'] = _elapsed_seconds(extract_start)
            logger.info('Analysis %s motion-sampled %s frames', analysis_id, len(sampled_frames))
            await _append_analysis_log(
                analysis_id,
                stage='extract_frames',
                level='info',
                message=f'关键帧提取完成，共 {len(sampled_frames)} 帧。',
                elapsed_s=timings['extract_frames_s'],
                timings=timings,
            )
            if upload_frames_dir is not None:
                persist_frames(sampled_frames, upload_frames_dir)

            preview = build_target_preview(
                analysis_id,
                [frame.name for frame in sampled_frames],
                existing_target_lock=existing_target_lock,
                motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                analysis_profile=analysis_profile_hint,
                detected_candidates=(
                    []
                    if existing_target_lock_confirmed
                    else _formal_target_preview_candidates(sampled_frames, motion_scores)
                ),
            )
            target_lock = existing_target_lock if existing_target_lock_confirmed else build_target_lock_payload(preview)

            saved = await _save_analysis_fields_with_retry(
                analysis_id,
                {
                    "frame_motion_scores": motion_scores,
                    "processing_timings": dict(timings),
                    "action_window_start": sampling_metadata.action_window_start,
                    "action_window_end": sampling_metadata.action_window_end,
                    "source_fps": sampling_metadata.source_fps,
                    "is_slow_motion": sampling_metadata.is_slow_motion,
                    "target_lock": target_lock,
                    "target_lock_status": target_lock["status"],
                    "retry_from_stage": "pose",
                },
                context=f"save_extract_frames:{analysis_id}",
            )
            if not saved:
                return

            if not existing_target_lock_confirmed and preview.target_lock_status != "auto_locked":
                if video_temporal_task is not None and not video_temporal_task.done():
                    video_temporal_task.cancel()
                if upload_frames_dir is not None:
                    persist_frames(sampled_frames, upload_frames_dir)
                timings['total_s'] = _elapsed_seconds(total_start)
                await _persist_processing_timings(analysis_id, timings)
                _log_analysis_timings(analysis_id, timings, context='awaiting_target_selection')
                await _append_analysis_log(
                    analysis_id,
                    stage='extract_frames',
                    level='warning',
                    message='自动锁定主滑行者置信度不足，等待手动确认目标。',
                    timings=timings,
                )
                await _set_analysis_status(analysis_id, 'awaiting_target_selection')
                return
        else:
            if upload_frames_dir is None or not upload_frames_dir.exists():
                raise RuntimeError("缺少已保存的抽帧结果，无法从当前阶段继续。")
            sampled_frames = persist_frames(sorted(upload_frames_dir.glob('frame_*.jpg')), processing_frames_dir)
            motion_scores = saved_motion_scores if isinstance(saved_motion_scores, dict) else _fallback_motion_payload(upload_frames_dir)
            motion_scores = attach_input_window_payload(dict(motion_scores), input_window)
            motion_scores = _attach_video_identity(motion_scores, video_identity) or motion_scores
            sampling_metadata = _sampling_metadata_from_saved(
                action_window_start=saved_action_window_start,
                action_window_end=saved_action_window_end,
                source_fps=saved_source_fps,
                is_slow_motion=saved_is_slow_motion,
                motion_scores=motion_scores,
            )
            try:
                video_temporal_task, started_duration, started_ai_clip = await _start_video_temporal_task_if_missing(
                    analysis_id=analysis_id,
                    video_path=video_path,
                    processing_frames_dir=processing_frames_dir,
                    sampling_metadata=sampling_metadata,
                    action_type=action_type,
                    action_subtype=action_subtype,
                    user_note=analysis.note,
                    motion_scores=motion_scores,
                    current_task=video_temporal_task,
                    input_window=input_window,
                )
                if started_duration is not None:
                    video_temporal_duration_sec = started_duration
                if isinstance(started_ai_clip, dict):
                    video_temporal_ai_clip = started_ai_clip
                    await _append_analysis_log(
                        analysis_id,
                        stage='extract_frames',
                        level='info',
                        message='分段重试复用缓存帧但缺少视频语义定位结果，已补跑视频 AI 时间定位。',
                        detail='retry_cache_reuse_missing_video_temporal',
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Analysis %s failed to start video temporal task on retry cache reuse: %s", analysis_id, exc)
                await _append_analysis_log(
                    analysis_id,
                    stage='extract_frames',
                    level='warning',
                    message='分段重试复用缓存帧时启动视频语义定位失败，将回退使用现有关键帧。',
                    detail=stringify_exception(exc),
                )
            preview = build_target_preview(
                analysis_id,
                [frame.name for frame in sampled_frames],
                existing_target_lock=existing_target_lock,
                motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                analysis_profile=analysis_profile_hint,
                detected_candidates=(
                    []
                    if _is_confirmed_target_lock(existing_target_lock)
                    else _formal_target_preview_candidates(sampled_frames, motion_scores)
                ),
            )
            target_lock = existing_target_lock if _is_confirmed_target_lock(existing_target_lock) else build_target_lock_payload(preview)
            await _append_analysis_log(
                analysis_id,
                stage='extract_frames',
                level='info',
                message=f'分段重试复用缓存关键帧，共 {len(sampled_frames)} 帧。',
                retry_from_stage=retry_from_stage,
            )
            if not _is_confirmed_target_lock(existing_target_lock) and preview.target_lock_status != "auto_locked":
                saved = await _save_analysis_fields_with_retry(
                    analysis_id,
                    {
                        "frame_motion_scores": motion_scores,
                        "processing_timings": dict(timings),
                        "action_window_start": sampling_metadata.action_window_start,
                        "action_window_end": sampling_metadata.action_window_end,
                        "source_fps": sampling_metadata.source_fps,
                        "is_slow_motion": sampling_metadata.is_slow_motion,
                        "target_lock": target_lock,
                        "target_lock_status": target_lock["status"],
                        "retry_from_stage": "pose",
                    },
                    context=f"save_retry_extract_frames:{analysis_id}",
                )
                if not saved:
                    return
                timings["total_s"] = _elapsed_seconds(total_start)
                await _persist_processing_timings(analysis_id, timings)
                _log_analysis_timings(analysis_id, timings, context="awaiting_target_selection_retry_cache")
                await _append_analysis_log(
                    analysis_id,
                    stage="extract_frames",
                    level="warning",
                    message="Target lock requires manual review; waiting for target selection.",
                    timings=timings,
                )
                await _set_analysis_status(analysis_id, "awaiting_target_selection")
                return

        pose_data: dict[str, Any]
        if run_pose:
            try:
                await _append_analysis_log(
                    analysis_id,
                    stage='pose',
                    level='info',
                    message='开始提取姿态关键点。',
                )
                pose_start = time.monotonic()
                bbox_per_frame = _build_bbox_per_frame(sampled_frames, target_lock, sampling_metadata.effective_fps)
                tracker_summary = _tracker_debug_summary(target_lock, len(sampled_frames))
                await _append_analysis_log(
                    analysis_id,
                    stage='pose',
                    level='info',
                    message=(
                        f'目标 bbox 追踪完成：{tracker_summary.get("tracker_type")}，'
                        f'{tracker_summary.get("frame_count", 0)} 帧，'
                        f'lost/reused {tracker_summary.get("lost_reused", 0)}，'
                        f'relock {tracker_summary.get("relocked", 0)}，'
                        f'rejected {tracker_summary.get("continuity_rejected", 0) + tracker_summary.get("relock_rejected", 0)}。'
                    ),
                    detail=_compact_json_detail(
                        {
                            "summary": tracker_summary,
                            "frames": target_lock.get("person_tracker_diagnostics", []),
                        }
                    ),
                )
                pose_data = await asyncio.to_thread(
                    extract_pose,
                    str(processing_frames_dir),
                    target_lock,
                    bbox_per_frame,
                    sampling_metadata.effective_fps,
                )
                timings['pose_s'] = _elapsed_seconds(pose_start)
                tiny_target_risk_flags = _tiny_target_pose_tracking_risk_flags(target_lock, pose_data)
                if tiny_target_risk_flags:
                    _append_target_lock_flags(target_lock, tiny_target_risk_flags)
                    if isinstance(pose_data, dict):
                        pose_data["quality_flags"] = _merge_quality_flags(pose_data, tiny_target_risk_flags)
                multiperson_relock_risk_flags = _multiperson_relock_instability_risk_flags(target_lock, pose_data)
                if multiperson_relock_risk_flags:
                    _append_target_lock_flags(target_lock, multiperson_relock_risk_flags)
                    if isinstance(pose_data, dict):
                        pose_data["quality_flags"] = _merge_quality_flags(pose_data, multiperson_relock_risk_flags)
                pose_summary = _pose_debug_summary(pose_data)
                await _append_analysis_log(
                    analysis_id,
                    stage='pose',
                    level='info',
                    message=(
                        f'姿态候选选择完成：tracked {pose_summary.get("tracked", 0)}/'
                        f'{pose_summary.get("total_frames", 0)}，'
                        f'lost {pose_summary.get("lost", 0)}，'
                        f'low confidence {pose_summary.get("low_confidence", 0)}。'
                    ),
                    detail=_compact_json_detail(
                        {
                            "summary": pose_summary,
                            "frames": (pose_data.get("pose_diagnostics", {}) if isinstance(pose_data, dict) else {}).get("frames", []),
                        }
                    ),
                )
                saved = await _save_analysis_fields_with_retry(
                    analysis_id,
                    {
                        "pose_data": pose_data,
                        "target_lock": target_lock,
                        "processing_timings": dict(timings),
                        "retry_from_stage": "biomechanics",
                    },
                    context=f"save_pose:{analysis_id}",
                )
                if not saved:
                    return
                await _append_analysis_log(
                    analysis_id,
                    stage='pose',
                    level='info',
                    message=f'姿态提取完成，共 {len(pose_data.get("frames", [])) if isinstance(pose_data, dict) else 0} 帧。',
                    elapsed_s=timings['pose_s'],
                    detail=_compact_json_detail(
                        {
                            "tracker": tracker_summary,
                            "pose": pose_summary,
                            "quality_flags": pose_data.get("quality_flags", []) if isinstance(pose_data, dict) else [],
                        }
                    ),
                    timings=timings,
                )
            except Exception as exc:  # noqa: BLE001
                timings['total_s'] = _elapsed_seconds(total_start)
                await _mark_analysis_failed(
                    analysis_id,
                    AnalysisErrorCode.UNKNOWN_ERROR,
                    stringify_exception(exc),
                    stage='pose',
                    timings=timings,
                )
                return
        else:
            async with AsyncSessionLocal() as session:
                analysis = await session.get(Analysis, analysis_id)
                if analysis is None or not isinstance(analysis.pose_data, dict):
                    raise RuntimeError("缺少已保存的 pose_data，无法从当前阶段继续。")
                pose_data = analysis.pose_data
            await _append_analysis_log(
                analysis_id,
                stage='pose',
                level='info',
                message='分段重试复用已有姿态结果。',
                retry_from_stage=retry_from_stage,
            )

        analysis_profile: str
        profile_evidence: dict[str, Any]
        bio_data: dict[str, Any]
        if run_biomechanics:
            try:
                await _append_analysis_log(
                    analysis_id,
                    stage='biomechanics',
                    level='info',
                    message='开始计算生物力学指标。',
                )
                biomechanics_start = time.monotonic()
                if is_mixed_action_input(action_type, action_subtype):
                    if video_temporal_task is not None:
                        video_temporal_result = await _await_video_temporal_result(video_temporal_task, analysis_id=analysis_id)
                        video_temporal_task = None
                    elif isinstance(motion_scores, dict) and isinstance(motion_scores.get("video_temporal"), dict):
                        video_temporal_result = motion_scores.get("video_temporal")  # type: ignore[assignment]
                analysis_profile, profile_evidence = infer_analysis_profile(action_type, action_subtype, pose_data, motion_scores)
                video_ai_profile, video_ai_profile_flags = _profile_from_video_ai_for_mixed_action(
                    action_type,
                    action_subtype,
                    video_temporal_result,
                    profile_evidence,
                )
                if video_ai_profile:
                    profile_evidence["skeleton_inferred_profile"] = analysis_profile
                    profile_evidence["video_ai_action_family"] = video_ai_profile
                    profile_evidence["video_ai_action_confidence"] = round(_video_ai_action_confidence(video_temporal_result), 4)
                    profile_evidence["quality_flags"] = _merge_quality_flags(
                        profile_evidence,
                        video_ai_profile_flags,
                    )
                    analysis_profile = video_ai_profile
                elif video_ai_profile_flags:
                    profile_evidence["quality_flags"] = _merge_quality_flags(profile_evidence, video_ai_profile_flags)
                bio_data = analyze_biomechanics(
                    pose_data,
                    action_type,
                    analysis_profile,
                    effective_fps=sampling_metadata.effective_fps,
                    source_fps=sampling_metadata.source_fps,
                    window_seconds=sampling_metadata.window_end_sec - sampling_metadata.window_start_sec,
                )
                bio_data = attach_key_frame_candidates(
                    bio_data,
                    pose_data,
                    motion_scores,
                    analysis_profile,
                    sampling_metadata.effective_fps,
                )
                if analysis_profile == "jump":
                    profile_evidence["jump_subtype_evidence"] = infer_jump_subtype_evidence(
                        pose_data,
                        bio_data.get("key_frames") if isinstance(bio_data.get("key_frames"), dict) else {},
                        sampling_metadata.effective_fps,
                    )
                stable_non_jump_profile_reuse: dict[str, Any] | None = None
                stable_non_jump_profile_allowed = (
                    video_ai_profile in {"step", "spin", "spiral"}
                    and analysis_profile in {"step", "spin", "spiral"}
                ) or _mixed_action_weak_jump_can_yield_to_stable_non_jump_history(
                    current_profile=analysis_profile,
                    video_ai_profile=video_ai_profile,
                    video_ai_profile_flags=video_ai_profile_flags,
                    video_temporal=video_temporal_result,
                    bio_data=bio_data,
                )
                if (
                    is_mixed_action_input(action_type, action_subtype)
                    and stable_non_jump_profile_allowed
                    and video_identity
                ):
                    try:
                        async with AsyncSessionLocal() as session:
                            stable_non_jump_profile_reuse = (
                                await _find_matching_mixed_action_non_jump_profile_stability(
                                    session=session,
                                    current_analysis_id=analysis_id,
                                    video_sha256=str(video_identity.get("sha256") or ""),
                                    action_type=action_type,
                                    action_subtype=action_subtype,
                                    current_motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                                    current_profile=analysis_profile,
                                    current_video_ai_confidence=_video_ai_action_confidence(video_temporal_result),
                                )
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Analysis %s failed to inspect non-jump profile stability: %s", analysis_id, exc)
                        stable_non_jump_profile_reuse = None
                    if isinstance(stable_non_jump_profile_reuse, dict):
                        reused_profile = str(stable_non_jump_profile_reuse.get("analysis_profile") or "").strip().lower()
                        if reused_profile in {"step", "spin", "spiral"} and reused_profile != analysis_profile:
                            next_evidence = dict(profile_evidence) if isinstance(profile_evidence, dict) else {}
                            if analysis_profile == "jump":
                                next_evidence["skeleton_inferred_profile"] = analysis_profile
                            next_evidence["video_ai_requested_profile"] = analysis_profile
                            next_evidence["matching_video_non_jump_profile_stability"] = stable_non_jump_profile_reuse
                            next_evidence["matching_video_reused_profile"] = reused_profile
                            stability_flags = [
                                "mixed_action_profile_reused_from_matching_video",
                                "mixed_action_profile_overridden_by_non_jump_history_stability",
                            ]
                            if analysis_profile == "jump":
                                stability_flags.append(
                                    "mixed_action_profile_overridden_by_stable_non_jump_history_weak_jump"
                                )
                            next_evidence["quality_flags"] = _merge_quality_flags(
                                next_evidence,
                                stability_flags,
                            )
                            analysis_profile = reused_profile
                            profile_evidence = next_evidence
                            bio_data = _build_bio_data_for_profile(
                                pose_data=pose_data,
                                motion_scores=motion_scores if isinstance(motion_scores, dict) else {},
                                action_type=action_type,
                                analysis_profile=analysis_profile,
                                sampling_metadata=sampling_metadata,
                                profile_evidence=profile_evidence,
                                target_lock=target_lock,
                            )
                matching_profile_reuse: dict[str, Any] | None = None
                prior_non_jump_profile_reuse: dict[str, Any] | None = None
                if (
                    is_mixed_action_input(action_type, action_subtype)
                    and video_ai_profile is None
                    and _mixed_action_profile_reuse_allowed_by_video_ai(video_temporal_result, video_ai_profile_flags)
                    and video_identity
                ):
                    try:
                        async with AsyncSessionLocal() as session:
                            matching_profile_reuse = await _find_matching_mixed_action_profile(
                                session=session,
                                current_analysis_id=analysis_id,
                                video_sha256=str(video_identity.get("sha256") or ""),
                                action_type=action_type,
                                action_subtype=action_subtype,
                                current_motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                            )
                            if analysis_profile == "jump":
                                prior_non_jump_profile_reuse = await _find_matching_mixed_action_prior_non_jump_profile(
                                    session=session,
                                    current_analysis_id=analysis_id,
                                    video_sha256=str(video_identity.get("sha256") or ""),
                                    action_type=action_type,
                                    action_subtype=action_subtype,
                                    current_motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                                )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Analysis %s failed to inspect matching profile reuse: %s", analysis_id, exc)
                        matching_profile_reuse = None
                        prior_non_jump_profile_reuse = None
                    if isinstance(matching_profile_reuse, dict):
                        reused_profile = str(matching_profile_reuse.get("analysis_profile") or "").strip().lower()
                        profile_evidence["matching_video_profile_reuse"] = matching_profile_reuse
                        if _mixed_action_matching_profile_reuse_should_override(
                            current_profile=analysis_profile,
                            reused_profile=reused_profile,
                            bio_data=bio_data,
                        ):
                            next_evidence = dict(profile_evidence) if isinstance(profile_evidence, dict) else {}
                            next_evidence["skeleton_inferred_profile"] = analysis_profile
                            next_evidence["matching_video_reused_profile"] = reused_profile
                            next_evidence["quality_flags"] = _merge_quality_flags(
                                next_evidence,
                                [
                                    "mixed_action_profile_reused_from_matching_video",
                                    "mixed_action_profile_overridden_by_matching_video_history",
                                ],
                            )
                            analysis_profile = reused_profile
                            profile_evidence = next_evidence
                            bio_data = _build_bio_data_for_profile(
                                pose_data=pose_data,
                                motion_scores=motion_scores if isinstance(motion_scores, dict) else {},
                                action_type=action_type,
                                analysis_profile=analysis_profile,
                                sampling_metadata=sampling_metadata,
                                profile_evidence=profile_evidence,
                                target_lock=target_lock,
                            )
                    if _mixed_action_prior_non_jump_profile_should_override_weak_jump(
                        current_profile=analysis_profile,
                        prior_profile_reuse=prior_non_jump_profile_reuse,
                        video_ai_profile=video_ai_profile,
                        bio_data=bio_data,
                        profile_evidence=profile_evidence,
                    ):
                        reused_profile = str(prior_non_jump_profile_reuse.get("analysis_profile") or "").strip().lower()
                        next_evidence = dict(profile_evidence) if isinstance(profile_evidence, dict) else {}
                        next_evidence["skeleton_inferred_profile"] = analysis_profile
                        next_evidence["matching_video_prior_non_jump_profile_reuse"] = prior_non_jump_profile_reuse
                        next_evidence["matching_video_reused_profile"] = reused_profile
                        next_evidence["quality_flags"] = _merge_quality_flags(
                            next_evidence,
                            [
                                "mixed_action_profile_reused_from_matching_video",
                                "mixed_action_profile_overridden_by_prior_same_video_non_jump_history",
                            ],
                        )
                        analysis_profile = reused_profile
                        profile_evidence = next_evidence
                        bio_data = _build_bio_data_for_profile(
                            pose_data=pose_data,
                            motion_scores=motion_scores if isinstance(motion_scores, dict) else {},
                            action_type=action_type,
                            analysis_profile=analysis_profile,
                            sampling_metadata=sampling_metadata,
                            profile_evidence=profile_evidence,
                            target_lock=target_lock,
                        )
                jump_downgraded_by_weak_video_ai = False
                if (
                    is_mixed_action_input(action_type, action_subtype)
                    and _mixed_action_skeleton_jump_should_downgrade_to_step(
                        current_profile=analysis_profile,
                        video_ai_profile=video_ai_profile,
                        video_ai_profile_flags=video_ai_profile_flags,
                        bio_data=bio_data,
                        profile_evidence=profile_evidence,
                        video_temporal=video_temporal_result,
                        matching_profile_reuse=matching_profile_reuse,
                    )
                ):
                    next_evidence = dict(profile_evidence) if isinstance(profile_evidence, dict) else {}
                    next_evidence["skeleton_inferred_profile"] = "jump"
                    next_evidence["quality_flags"] = _merge_quality_flags(
                        next_evidence,
                        [
                            "mixed_action_profile_downgraded_to_step_weak_jump_evidence",
                            *video_ai_profile_flags,
                        ],
                    )
                    analysis_profile = "step"
                    profile_evidence = next_evidence
                    bio_data = _build_bio_data_for_profile(
                        pose_data=pose_data,
                        motion_scores=motion_scores if isinstance(motion_scores, dict) else {},
                        action_type=action_type,
                        analysis_profile=analysis_profile,
                        sampling_metadata=sampling_metadata,
                        profile_evidence=profile_evidence,
                        target_lock=target_lock,
                    )
                    jump_downgraded_by_weak_video_ai = True
                elif _mixed_action_matching_jump_history_blocks_downgrade(
                    current_profile=analysis_profile,
                    video_ai_profile=video_ai_profile,
                    video_ai_profile_flags=video_ai_profile_flags,
                    video_temporal=video_temporal_result,
                    profile_evidence=profile_evidence,
                    matching_profile_reuse=matching_profile_reuse,
                ):
                    profile_evidence["quality_flags"] = _merge_quality_flags(
                        profile_evidence,
                        ["mixed_action_profile_downgrade_blocked_by_matching_jump_history"],
                    )
                if (
                    is_mixed_action_input(action_type, action_subtype)
                    and analysis_profile != "jump"
                    and video_ai_profile is None
                    and not jump_downgraded_by_weak_video_ai
                ):
                    jump_bio_data = analyze_biomechanics(
                        pose_data,
                        action_type,
                        "jump",
                        effective_fps=sampling_metadata.effective_fps,
                        source_fps=sampling_metadata.source_fps,
                        window_seconds=sampling_metadata.window_end_sec - sampling_metadata.window_start_sec,
                    )
                    jump_bio_data = attach_key_frame_candidates(
                        jump_bio_data,
                        pose_data,
                        motion_scores,
                        "jump",
                        sampling_metadata.effective_fps,
                    )
                    jump_candidates = (
                        jump_bio_data.get("key_frame_candidates")
                        if isinstance(jump_bio_data.get("key_frame_candidates"), dict)
                        else None
                    )
                    if _mixed_action_should_recover_jump_from_skeleton(
                        action_type,
                        action_subtype,
                        current_profile=analysis_profile,
                        video_ai_profile=video_ai_profile,
                        video_temporal=video_temporal_result,
                        profile_evidence=profile_evidence,
                        jump_candidates=jump_candidates,
                    ):
                        profile_evidence["skeleton_inferred_profile"] = analysis_profile
                        profile_evidence["quality_flags"] = _merge_quality_flags(
                            profile_evidence,
                            ["mixed_action_profile_recovered_jump_from_skeleton_candidates"],
                        )
                        analysis_profile = "jump"
                        bio_data = jump_bio_data
                if isinstance(bio_data, dict):
                    if analysis_profile == 'jump':
                        profile_evidence['jump_subtype_evidence'] = infer_jump_subtype_evidence(
                            pose_data,
                            bio_data.get('key_frames') if isinstance(bio_data.get('key_frames'), dict) else {},
                            sampling_metadata.effective_fps,
                        )
                    merged_quality_flags = bio_data.get('quality_flags') if isinstance(bio_data.get('quality_flags'), list) else []
                    merged_quality_flags.extend(
                        flag for flag in profile_evidence.get('quality_flags', []) if flag not in merged_quality_flags
                    )
                    target_flags = target_lock.get("quality_flags") if isinstance(target_lock.get("quality_flags"), list) else []
                    merged_quality_flags.extend(flag for flag in target_flags if flag not in merged_quality_flags)
                    bio_data['quality_flags'] = merged_quality_flags
                    bio_data['profile_evidence'] = profile_evidence
                    if 'jump_gate_not_passed' in merged_quality_flags:
                        quality_hint = next(
                            (
                                message
                                for message in profile_evidence.get('negative_constraints', [])
                                if isinstance(message, str) and '几何证据不足' in message
                            ),
                            '几何证据不足（CoM 垂直范围低、无腾空帧检测），但用户填写了跳跃，保留 jump profile',
                        )
                        bio_data['jump_metrics_warning'] = quality_hint
                    if 'spin_rotation_signal_weak' in merged_quality_flags:
                        profile_warning = next(
                            (
                                message
                                for message in profile_evidence.get('negative_constraints', [])
                                if isinstance(message, str) and '旋转信号弱' in message
                            ),
                            '髋部旋转信号弱，可能不是旋转或存在视角遮挡',
                        )
                        bio_data['profile_warning'] = profile_warning
                timings['biomechanics_s'] = _elapsed_seconds(biomechanics_start)
                saved = await _save_analysis_fields_with_retry(
                    analysis_id,
                    {
                        "bio_data": bio_data,
                        "analysis_profile": analysis_profile,
                        "processing_timings": dict(timings),
                        "retry_from_stage": "vision",
                    },
                    context=f"save_biomechanics:{analysis_id}",
                )
                if not saved:
                    return
                await _append_analysis_log(
                    analysis_id,
                    stage='biomechanics',
                    level='info',
                    message=f'生物力学计算完成，profile={analysis_profile}。',
                    elapsed_s=timings['biomechanics_s'],
                    timings=timings,
                )
            except Exception as exc:  # noqa: BLE001
                timings['total_s'] = _elapsed_seconds(total_start)
                await _mark_analysis_failed(
                    analysis_id,
                    AnalysisErrorCode.UNKNOWN_ERROR,
                    stringify_exception(exc),
                    stage='biomechanics',
                    timings=timings,
                )
                return
        else:
            async with AsyncSessionLocal() as session:
                analysis = await session.get(Analysis, analysis_id)
                if analysis is None or not isinstance(analysis.bio_data, dict):
                    raise RuntimeError("缺少已保存的 bio_data，无法从当前阶段继续。")
                bio_data = analysis.bio_data
                analysis_profile = analysis.analysis_profile or analysis_profile_hint or 'jump'
                profile_evidence = bio_data.get('profile_evidence', {}) if isinstance(bio_data.get('profile_evidence'), dict) else {}
            await _append_analysis_log(
                analysis_id,
                stage='biomechanics',
                level='info',
                message='分段重试复用已有生物力学结果。',
                retry_from_stage=retry_from_stage,
            )

        if run_vision:
            reused_resolved, reused_frames, reused_records, reused_video_temporal = await _reuse_matching_semantic_keyframes(
                analysis_id=analysis_id,
                video_path=video_path,
                processing_frames_dir=processing_frames_dir,
                video_identity=video_identity,
                action_type=action_type,
                action_subtype=action_subtype,
                analysis_profile=analysis_profile,
                motion_scores=motion_scores,
                bio_data=bio_data,
                video_temporal_result=video_temporal_result,
            )
            if reused_resolved is not None:
                if video_temporal_task is not None and not video_temporal_task.done():
                    video_temporal_task.cancel()
                    try:
                        await video_temporal_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:  # noqa: BLE001
                        logger.debug("Analysis %s video temporal task ended after semantic reuse", analysis_id, exc_info=True)
                video_temporal_task = None
                semantic_pipeline = SemanticKeyframePipelineResult(
                    ai_clip=video_temporal_ai_clip,
                    video_temporal=reused_video_temporal,
                    resolved_keyframes=reused_resolved,
                    effective_source=effective_timestamp_source(reused_resolved, True),
                    semantic_frames=reused_frames,
                    semantic_records=reused_records,
                    quality_flags=_merge_quality_flags(reused_video_temporal, reused_resolved),
                    used_semantic_frames=True,
                    has_semantic_moments=True,
                )
                await _append_analysis_log(
                    analysis_id,
                    stage="vision",
                    level="info",
                    message="命中同视频已通过的语义 T/A/L，已重抽当前分析的精确关键帧。",
                    detail=_compact_json_detail(
                        {
                            "reused_from_analysis_id": reused_resolved.get("reused_from_analysis_id"),
                            "selected": reused_resolved.get("selected"),
                            "video_sha256": (video_identity or {}).get("sha256"),
                        }
                    ),
                )
            else:
                if video_temporal_task is not None:
                    video_temporal_result = await _await_video_temporal_result(video_temporal_task, analysis_id=analysis_id)
                elif isinstance(motion_scores, dict) and isinstance(motion_scores.get("video_temporal"), dict):
                    video_temporal_result = motion_scores.get("video_temporal")  # type: ignore[assignment]

                semantic_pipeline = await resolve_semantic_keyframe_pipeline(
                    video_path=video_path,
                    work_dir=processing_frames_dir.parent,
                    semantic_frames_dir=processing_frames_dir.parent / "semantic_frames",
                    video_temporal=video_temporal_result,
                    motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                    sampling_metadata=sampling_metadata,
                    analysis_profile=analysis_profile,
                    bio_data=bio_data,
                    video_duration_sec=video_temporal_duration_sec,
                )
                semantic_pipeline = await retry_video_temporal_if_needed(
                    result=semantic_pipeline,
                    video_path=video_path,
                    work_dir=processing_frames_dir.parent,
                    semantic_frames_dir=processing_frames_dir.parent / "semantic_frames",
                    sampling_metadata=sampling_metadata,
                    action_type=action_type,
                    action_subtype=action_subtype,
                    motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                    analysis_profile=analysis_profile,
                    bio_data=bio_data,
                    user_note=analysis.note,
                    analyzed_video_kind="action_window_ai",
                    input_window=input_window,
                )
            video_temporal_result = semantic_pipeline.video_temporal
            resolved_keyframes = semantic_pipeline.resolved_keyframes
            motion_scores = _merge_frame_motion_payload(
                motion_scores,
                video_temporal=video_temporal_result,
                resolved_keyframes=resolved_keyframes,
            )
            analysis_profile, bio_data, profile_evidence = _apply_resolved_video_ai_profile_override_to_bio_data(
                action_type=action_type,
                action_subtype=action_subtype,
                current_profile=analysis_profile,
                video_temporal=video_temporal_result,
                resolved_keyframes=resolved_keyframes if isinstance(resolved_keyframes, dict) else None,
                bio_data=bio_data,
                pose_data=pose_data,
                motion_scores=motion_scores if isinstance(motion_scores, dict) else {},
                sampling_metadata=sampling_metadata,
                profile_evidence=profile_evidence,
                target_lock=target_lock,
            )
            bio_data = sync_key_frames_from_resolved_keyframes(
                bio_data,
                resolved_keyframes if isinstance(resolved_keyframes, dict) else None,
                analysis_profile=analysis_profile,
            )
            saved = await _save_analysis_fields_with_retry(
                analysis_id,
                {
                    "frame_motion_scores": motion_scores,
                    "bio_data": bio_data,
                    "analysis_profile": analysis_profile,
                },
                context=f"save_pre_vision_keyframes:{analysis_id}",
            )
            if not saved:
                return

            await _append_analysis_log(
                analysis_id,
                stage='vision',
                level='info',
                message='开始调用视觉模型分析关键帧。',
                status_value='analyzing',
            )
            await _set_analysis_status(analysis_id, 'analyzing')
            try:
                vision_start = time.monotonic()
                use_semantic_frames = semantic_pipeline.used_semantic_frames
                vision_frame_paths = semantic_pipeline.semantic_frames if use_semantic_frames else sampled_frames
                if semantic_pipeline.has_semantic_moments and not use_semantic_frames:
                    await _append_analysis_log(
                        analysis_id,
                        stage='vision',
                        level='warning',
                        message='语义关键帧未通过质量门槛，视觉分析改用常规 sampled frames。',
                        detail='semantic_keyframes_unreliable_fallback_to_sampled_frames',
                    )
                if "semantic_keyframes_unreliable_after_refinement" in semantic_pipeline.quality_flags:
                    await _append_analysis_log(
                        analysis_id,
                        stage='vision',
                        level='warning',
                        message='Semantic keyframes failed reliability gate after refinement; using sampled frames.',
                        detail='semantic_keyframes_unreliable_after_refinement',
                    )
                timestamps = build_timestamp_map({"selected": resolved_keyframes.get("selected")}) if use_semantic_frames and isinstance(resolved_keyframes, dict) else build_timestamp_map(motion_scores)
                raw_payloads = await encode_frames(vision_frame_paths, timestamps=timestamps)
                provider_path_a = await _provider_for_slot("vision_path_a")
                provider_path_b = await _provider_for_slot("vision_path_b")
                path_a_clip_path = None
                semantic_ai_clip = semantic_pipeline.ai_clip if isinstance(semantic_pipeline.ai_clip, dict) else None
                semantic_ai_clip_path = semantic_ai_clip.get("path") if isinstance(semantic_ai_clip, dict) else None
                video_temporal_ai_clip_path = video_temporal_ai_clip.get("path") if isinstance(video_temporal_ai_clip, dict) else None
                if isinstance(semantic_ai_clip_path, str) and semantic_ai_clip_path:
                    path_a_clip_path = Path(semantic_ai_clip_path)
                elif isinstance(video_temporal_ai_clip_path, str) and video_temporal_ai_clip_path:
                    path_a_clip_path = Path(video_temporal_ai_clip_path)
                else:
                    try:
                        path_a_clip_path = await cut_action_window_ai_clip(
                            video_path,
                            input_window.input_window_start_sec if input_window else sampling_metadata.action_window_start,
                            input_window.input_window_end_sec if input_window else sampling_metadata.action_window_end,
                            processing_frames_dir.parent / 'path_a_input_window_ai.mp4',
                            max_duration_sec=None,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning('Analysis %s AI input-window clip failed; Path A will use frames: %s', analysis_id, exc)
                prompt_context = await build_analysis_prompt_context(
                    action_type=action_type,
                    action_subtype=action_subtype,
                    skill_category=skill_category,
                    analysis_profile=analysis_profile,
                    profile_evidence=profile_evidence,
                    motion_features=motion_scores if isinstance(motion_scores, dict) else None,
                    bio_data=bio_data,
                    skater_id=skater_id,
                    user_note=analysis.note,
                )

                dual = await analyze_frames_dual(
                    action_type=action_type,
                    frame_paths=vision_frame_paths,
                    raw_frame_payloads=raw_payloads,
                    pose_data=pose_data,
                    bio_data=bio_data,
                    provider_path_a=provider_path_a,
                    provider_path_b=provider_path_b,
                    frame_motion_scores=motion_scores,
                    action_subtype=action_subtype,
                    analysis_profile=analysis_profile,
                    profile_evidence=profile_evidence,
                    memory_context="",
                    timestamps=timestamps,
                    clip_path=path_a_clip_path,
                    window_start_sec=sampling_metadata.action_window_start,
                    skill_category=skill_category,
                    prompt_context=prompt_context,
                    video_temporal=video_temporal_result,
                    resolved_keyframes=resolved_keyframes,
                    target_lock=target_lock,
                )
                vision_structured = dual.path_a
                vision_path_a = dual.path_a
                vision_path_b = dual.path_b
                dual_path_meta = dual.dual_path_meta
                cross_validation = {**dual.validation.to_dict(), **dual_path_meta}
                ui_summary = dual_path_summary(dual)
                dual_path_log_detail = _build_dual_path_log_detail(
                    path_a=vision_path_a,
                    path_b=vision_path_b,
                    dual_path_meta=dual_path_meta,
                    provider_path_a=provider_path_a,
                    provider_path_b=provider_path_b,
                    raw_frame_count=len(raw_payloads),
                    annotated_frame_count=ui_summary.get("n_frames_b") if isinstance(ui_summary.get("n_frames_b"), int) else 0,
                    annotated_dir=getattr(dual, "annotated_dir", None),
                    clip_path=path_a_clip_path,
                    used_key_frames=getattr(dual, "used_key_frames", set()),
                )
                frame_analysis = vision_structured.get('frame_analysis')
                if isinstance(frame_analysis, list):
                    vision_structured['frame_analysis'] = smooth_phases(frame_analysis, analysis_profile, bio_data=bio_data)
                    vision_path_a = vision_structured
                resolved_keyframes = await _attach_post_vision_partial_semantic_frames(
                    video_path=video_path,
                    semantic_frames_dir=processing_frames_dir.parent / "semantic_frames",
                    resolved_keyframes=resolved_keyframes,
                    vision_structured=vision_structured,
                    frame_motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                    analysis_profile=analysis_profile,
                )
                motion_scores = _merge_frame_motion_payload(
                    motion_scores,
                    video_temporal=video_temporal_result,
                    resolved_keyframes=resolved_keyframes,
                )
                bio_data = sync_key_frames_from_resolved_keyframes(
                    bio_data,
                    resolved_keyframes if isinstance(resolved_keyframes, dict) else None,
                    analysis_profile=analysis_profile,
                )
                cross_validation = _attach_auto_eval(
                    cross_validation,
                    bio_data=bio_data,
                    vision_structured=vision_structured,
                    frame_motion_scores=motion_scores,
                    analysis_profile=analysis_profile,
                )
                cross_validation = _merge_video_temporal_cross_validation(
                    cross_validation,
                    video_temporal=video_temporal_result,
                    resolved_keyframes=resolved_keyframes,
                    frame_motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                )
                cross_validation = _attach_path_b_report_evidence(cross_validation, vision_path_b)
                dual_path_meta = cross_validation
                vision_raw = json.dumps(vision_structured, ensure_ascii=False)
                timings['vision_s'] = _elapsed_seconds(vision_start)
                saved = await _save_analysis_fields_with_retry(
                    analysis_id,
                    {
                        "vision_raw": vision_raw,
                        "vision_structured": vision_structured,
                        "vision_path_a": vision_path_a,
                        "vision_path_b": vision_path_b,
                        "cross_validation": cross_validation,
                        "processing_timings": dict(timings),
                        "retry_from_stage": "report",
                    },
                    context=f"save_vision:{analysis_id}",
                )
                if not saved:
                    return
            except Exception as exc:  # noqa: BLE001
                failure = classify_ai_failure(exc)
                timings['total_s'] = _elapsed_seconds(total_start)
                await _mark_analysis_failed(analysis_id, failure.code, failure.detail, stage='vision', timings=timings)
                return
            logger.info('Analysis %s received vision result', analysis_id)
            path_a_mode = vision_path_a.get("vision_mode", "frames") if isinstance(vision_path_a, dict) else "unknown"
            path_b_failed = isinstance(vision_path_b, dict) and bool(vision_path_b.get("error"))
            recommended_path = dual_path_meta.get("recommended_path", "unknown") if isinstance(dual_path_meta, dict) else "unknown"
            await _append_analysis_log(
                analysis_id,
                stage='vision',
                level='info',
                message=f'Dual-path details: Path A mode={path_a_mode}, Path B={"failed" if path_b_failed else "completed"}, recommended={recommended_path}.',
                detail=dual_path_log_detail,
            )
            await _append_analysis_log(
                analysis_id,
                stage='vision',
                level='info',
                message='视觉分析完成，已生成结构化帧观察。',
                elapsed_s=timings['vision_s'],
                timings=timings,
            )
        else:
            async with AsyncSessionLocal() as session:
                analysis = await session.get(Analysis, analysis_id)
                if analysis is None or not isinstance(analysis.vision_structured, dict):
                    raise RuntimeError("缺少已保存的 vision_structured，无法从当前阶段继续。")
                vision_structured = analysis.vision_structured
                vision_raw = analysis.vision_raw or json.dumps(vision_structured, ensure_ascii=False)
                vision_path_a = analysis.vision_path_a if isinstance(analysis.vision_path_a, dict) else vision_structured
                vision_path_b = analysis.vision_path_b if isinstance(analysis.vision_path_b, dict) else None
                cross_validation = analysis.cross_validation if isinstance(analysis.cross_validation, dict) else None
                if not isinstance(cross_validation, dict) or not isinstance(cross_validation.get("auto_eval"), dict):
                    cross_validation = _attach_auto_eval(
                        cross_validation,
                        bio_data=bio_data,
                        vision_structured=vision_structured,
                        frame_motion_scores=motion_scores,
                        analysis_profile=analysis_profile,
                    )
                cross_validation = _merge_video_temporal_cross_validation(
                    cross_validation,
                    frame_motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
                )
                resolved_keyframes = (
                    motion_scores.get("resolved_keyframes")
                    if isinstance(motion_scores, dict) and isinstance(motion_scores.get("resolved_keyframes"), dict)
                    else None
                )
                video_temporal_result = (
                    motion_scores.get("video_temporal")
                    if isinstance(motion_scores, dict) and isinstance(motion_scores.get("video_temporal"), dict)
                    else None
                )
                analysis_profile, bio_data, profile_evidence = _apply_resolved_video_ai_profile_override_to_bio_data(
                    action_type=action_type,
                    action_subtype=action_subtype,
                    current_profile=analysis_profile,
                    video_temporal=video_temporal_result,
                    resolved_keyframes=resolved_keyframes,
                    bio_data=bio_data,
                    pose_data=pose_data,
                    motion_scores=motion_scores if isinstance(motion_scores, dict) else {},
                    sampling_metadata=sampling_metadata,
                    profile_evidence=profile_evidence,
                    target_lock=target_lock,
                )
                bio_data = sync_key_frames_from_resolved_keyframes(
                    bio_data,
                    resolved_keyframes,
                    analysis_profile=analysis_profile,
                )
                cross_validation = _attach_path_b_report_evidence(cross_validation, vision_path_b)
                dual_path_meta = cross_validation
            await _append_analysis_log(
                analysis_id,
                stage='vision',
                level='info',
                message='分段重试复用已有视觉分析结果。',
                retry_from_stage=retry_from_stage,
            )

        await _append_analysis_log(
            analysis_id,
            stage='report',
            level='info',
            message='开始生成训练报告。',
            status_value='generating_report',
        )
        await _set_analysis_status(analysis_id, 'generating_report')

        try:
            report_start = time.monotonic()
            report = await generate_report(
                action_type,
                vision_structured,
                bio_data,
                skater_id,
                dual_path_meta=dual_path_meta,
                prompt_context=(
                    await build_analysis_prompt_context(
                        action_type=action_type,
                        action_subtype=action_subtype,
                        skill_category=skill_category,
                        analysis_profile=analysis_profile,
                        profile_evidence=profile_evidence,
                        motion_features=motion_scores if isinstance(motion_scores, dict) else None,
                        bio_data=bio_data,
                        skater_id=skater_id,
                        user_note=analysis.note,
                    )
                ),
            )
            force_score = apply_child_score_floor(calculate_force_score(report), report, dual_path_meta)
            timings['report_s'] = _elapsed_seconds(report_start)
            timings['total_s'] = _elapsed_seconds(total_start)
        except Exception as exc:  # noqa: BLE001
            failure = classify_ai_failure(exc)
            timings['total_s'] = _elapsed_seconds(total_start)
            await _mark_analysis_failed(analysis_id, failure.code, failure.detail, stage='report', timings=timings)
            return
        logger.info('Analysis %s generated report with score %s', analysis_id, force_score)
        await _append_analysis_log(
            analysis_id,
            stage='report',
            level='info',
            message=f'报告生成完成，Force Score={force_score}。',
            elapsed_s=timings['report_s'],
            timings=timings,
        )
        if upload_frames_dir is not None:
            persist_frames(sampled_frames, upload_frames_dir)
            semantic_dir = processing_frames_dir.parent / "semantic_frames"
            if semantic_dir.exists():
                semantic_artifacts = [
                    *sorted(semantic_dir.glob("semantic_*.jpg")),
                    *sorted(semantic_dir.glob("partial_semantic_*.jpg")),
                ]
                persist_frames(semantic_artifacts, video_path.parent / "semantic_frames")

        try:
            async def _save_completed_analysis() -> None:
                saved_skater_id: str | None = None
                should_update_skill_progress = True
                async with AsyncSessionLocal() as session:
                    analysis = await session.get(Analysis, analysis_id)
                    if analysis is None:
                        return

                    should_update_skill_progress = analysis.status != 'completed'
                    analysis.vision_raw = vision_raw
                    analysis.vision_structured = vision_structured
                    analysis.vision_path_a = vision_path_a
                    analysis.vision_path_b = vision_path_b
                    analysis.cross_validation = cross_validation
                    analysis.report = report
                    analysis.pose_data = pose_data
                    analysis.bio_data = bio_data
                    analysis.frame_motion_scores = motion_scores
                    analysis.processing_timings = dict(timings)
                    analysis.analysis_profile = analysis_profile
                    analysis.pipeline_version = CURRENT_PIPELINE_VERSION
                    analysis.target_lock = target_lock
                    analysis.target_lock_status = str(target_lock.get('status') or 'auto_locked')
                    analysis.action_window_start = sampling_metadata.action_window_start
                    analysis.action_window_end = sampling_metadata.action_window_end
                    analysis.source_fps = sampling_metadata.source_fps
                    analysis.is_slow_motion = sampling_metadata.is_slow_motion
                    analysis.force_score = force_score
                    analysis.status = 'completed'
                    analysis.error_code = None
                    analysis.error_detail = None
                    analysis.error_message = None
                    analysis.retry_from_stage = None
                    if should_update_skill_progress:
                        await auto_update_skill_progress(analysis_id, session)
                    if analysis.skater_id:
                        saved_skater_id = analysis.skater_id
                        await sync_skater_progress(session, analysis.skater_id)
                    await session.commit()

                if saved_skater_id:
                    try:
                        async with AsyncSessionLocal() as memory_session:
                            await suggest_memory_updates(analysis_id, saved_skater_id, memory_session)
                    except Exception:  # noqa: BLE001
                        logger.exception('Analysis %s memory suggestion generation failed', analysis_id)

            await run_db_write_with_retry(_save_completed_analysis, context=f"save_completed_analysis:{analysis_id}")
            _log_analysis_timings(analysis_id, timings)
            logger.info('Analysis %s completed', analysis_id)
            await _append_analysis_log(
                analysis_id,
                stage='pipeline',
                level='info',
                message='分析流程已完成。',
                elapsed_s=timings['total_s'],
                timings=timings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception('Analysis %s failed while saving report', analysis_id)
            timings['total_s'] = _elapsed_seconds(total_start)
            await _mark_analysis_failed(
                analysis_id,
                AnalysisErrorCode.REPORT_SAVE_FAILED,
                stringify_exception(exc),
                stage='report',
                timings=timings,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception('Analysis %s failed', analysis_id)
        timings['total_s'] = _elapsed_seconds(total_start)
        await _mark_analysis_failed(
            analysis_id,
            AnalysisErrorCode.UNKNOWN_ERROR,
            stringify_exception(exc),
            stage='pipeline',
            timings=timings,
        )
    finally:
        if video_temporal_task is not None and not video_temporal_task.done():
            video_temporal_task.cancel()
            try:
                await video_temporal_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                logger.debug("Analysis %s video temporal task ended during cleanup", analysis_id, exc_info=True)
        cleanup_processing_dir(analysis_id)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def _mark_analysis_failed(
    analysis_id: str,
    code: AnalysisErrorCode,
    detail: str,
    *,
    stage: str = "pipeline",
    timings: dict[str, float] | None = None,
) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            if code == AnalysisErrorCode.REPORT_SAVE_FAILED and analysis.status == "completed" and isinstance(analysis.report, dict):
                logs = _normalize_processing_logs(analysis.processing_logs)
                logs.append(
                    {
                        "timestamp": _utc_now_iso(),
                        "stage": stage,
                        "level": "warning",
                        "message": friendly_error_title(code),
                        "error_code": code.value,
                        "detail": detail,
                        "preserved_completed_state": True,
                    }
                )
                analysis.processing_logs = logs[-MAX_ANALYSIS_LOG_ENTRIES:]
                if timings is not None:
                    analysis.processing_timings = dict(timings)
                await session.commit()
                return
            logs = _normalize_processing_logs(analysis.processing_logs)
            logs.append(
                {
                    "timestamp": _utc_now_iso(),
                    "stage": stage,
                    "level": "error",
                    "message": friendly_error_title(code),
                    "error_code": code.value,
                    "detail": detail,
                }
            )
            analysis.status = "failed"
            analysis.error_code = code.value
            analysis.error_detail = detail
            analysis.error_message = friendly_error_title(code)
            analysis.processing_logs = logs[-MAX_ANALYSIS_LOG_ENTRIES:]
            if timings is not None:
                analysis.processing_timings = dict(timings)
            await session.commit()

    try:
        await run_db_write_with_retry(_write, context=f"mark_analysis_failed:{analysis_id}:{code.value}")
    except Exception:  # noqa: BLE001
        logger.exception("Analysis %s failed to persist error state", analysis_id)


async def _set_analysis_status(analysis_id: str, status_value: str) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            analysis.status = status_value
            await session.commit()

    try:
        await run_db_write_with_retry(_write, context=f"set_analysis_status:{analysis_id}:{status_value}")
    except Exception:  # noqa: BLE001
        logger.exception("Analysis %s failed to persist status %s", analysis_id, status_value)


async def _get_default_skater(session: AsyncSession) -> Skater | None:
    result = await run_db_read_with_retry(
        lambda: session.execute(select(Skater).order_by(Skater.is_default.desc(), Skater.created_at.asc()).limit(1)),
        context="get_default_skater",
    )
    return result.scalar_one_or_none()


async def _resolve_skater(session: AsyncSession, skater_id: str | None) -> Skater | None:
    if skater_id:
        skater = await session.get(Skater, skater_id)
        if skater is None:
            raise HTTPException(status_code=404, detail="未找到对应的练习档案。")
        return skater

    return await _get_default_skater(session)


async def _get_skater_map(session: AsyncSession, skater_ids: set[str]) -> dict[str, Skater]:
    if not skater_ids:
        return {}
    result = await run_db_read_with_retry(
        lambda: session.execute(select(Skater).where(Skater.id.in_(skater_ids))),
        context="get_skater_map",
    )
    return {skater.id: skater for skater in result.scalars().all()}


def _report_summary(analysis: Analysis) -> str:
    if isinstance(analysis.report, dict):
        summary = str(analysis.report.get("summary", "")).strip()
        if summary:
            return summary
    if analysis.error_message:
        return analysis.error_message
    if analysis.note:
        return analysis.note
    return "暂无报告摘要。"


def _score_to_stars(score: object) -> str:
    try:
        normalized = int(round(float(score)))
    except (TypeError, ValueError):
        normalized = 0

    if normalized >= 85:
        filled = 5
    elif normalized >= 70:
        filled = 4
    elif normalized >= 56:
        filled = 3
    elif normalized >= 40:
        filled = 2
    else:
        filled = 1
    return ("★" * filled) + ("☆" * (5 - filled))


def _first_nonempty_sentence(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = [part.strip("，。；; ") for part in text.replace("！", "。").replace("？", "。").split("。")]
    for part in parts:
        if part:
            return part
    return text


def _join_export_items(items: list[str], fallback: str) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return fallback
    return "，".join(cleaned[:2])


def _build_export_text(analysis: Analysis, skater_name: str | None, session_date: str | None = None) -> str:
    report = analysis.report if isinstance(analysis.report, dict) else {}
    vision_structured = analysis.vision_structured if isinstance(analysis.vision_structured, dict) else {}
    phase_summary = (
        vision_structured.get("action_phase_summary")
        if isinstance(vision_structured.get("action_phase_summary"), dict)
        else {}
    )
    frame_analysis = vision_structured.get("frame_analysis", []) if isinstance(vision_structured.get("frame_analysis"), list) else []

    positives: list[str] = []
    for frame in frame_analysis:
        if not isinstance(frame, dict):
            continue
        for item in frame.get("positives", []):
            text = _first_nonempty_sentence(item)
            if text and text not in positives:
                positives.append(text)

    strongest_phase = str(phase_summary.get("strongest_phase", "")).strip()
    weakest_phase = str(phase_summary.get("weakest_phase", "")).strip()

    highlight = _join_export_items(
        positives[:2]
        or ([f"{strongest_phase}阶段表现相对稳定"] if strongest_phase and strongest_phase != "不可分析" else []),
        "整体动作节奏基本稳定",
    )

    issue_texts: list[str] = []
    issues = report.get("issues", []) if isinstance(report.get("issues"), list) else []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        text = _first_nonempty_sentence(issue.get("description"))
        if text and text not in issue_texts:
            issue_texts.append(text)

    improvements = report.get("improvements", []) if isinstance(report.get("improvements"), list) else []
    improvement_actions: list[str] = []
    for item in improvements:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target", "")).strip()
        action = _first_nonempty_sentence(item.get("action"))
        if target and action:
            improvement_actions.append(f"{target}：{action}")
        elif action:
            improvement_actions.append(action)

    improvement = _join_export_items(
        issue_texts[:1]
        + improvement_actions[:1]
        + ([f"{weakest_phase}阶段还可以继续加强"] if weakest_phase and weakest_phase != "不可分析" else []),
        "建议继续加强稳定性和基础控制练习",
    )

    subscores = report.get("subscores") if isinstance(report.get("subscores"), dict) else {}
    detail_labels = {
        "takeoff_power": "起跳发力",
        "rotation_axis": "旋转轴心",
        "arm_coordination": "手臂配合",
        "landing_absorption": "落冰缓冲",
        "core_stability": "核心稳定",
    }
    detail_parts = [
        f"[{label} {_score_to_stars(subscores.get(key))}]"
        for key, label in detail_labels.items()
        if key in subscores
    ]
    if not detail_parts:
        detail_parts = [f"[综合表现 {_score_to_stars(analysis.force_score)}]"]

    export_date = session_date or analysis.created_at.date().isoformat()
    skater_label = skater_name or "小运动员"
    score_label = analysis.force_score if analysis.force_score is not None else "--"

    return (
        f"[冰宝诊断] {skater_label} · {analysis.action_type} · {export_date}\n"
        f"综合评分：{score_label}分\n\n"
        f"亮点：{highlight}\n"
        f"待改善：{improvement}\n\n"
        f"技术细节：{' '.join(detail_parts)}\n\n"
        "由冰宝（IceBuddy）生成 · 仅供参考"
    )


def _detail_from_analysis(
    analysis: Analysis,
    skater_name: str | None = None,
    *,
    include_error_detail: bool = False,
) -> AnalysisDetail:
    input_window = _input_window_payload_for_saved_analysis(analysis)
    return AnalysisDetail(
        id=analysis.id,
        skater_id=analysis.skater_id,
        session_id=analysis.session_id,
        skater_name=skater_name,
        skill_category=analysis.skill_category,
        skill_node_id=analysis.skill_node_id,
        action_type=analysis.action_type,
        action_subtype=analysis.action_subtype,
        analysis_profile=analysis.analysis_profile,
        retry_from_stage=analysis.retry_from_stage,
        pipeline_version=analysis.pipeline_version,
        video_path=analysis.video_path,
        status=analysis.status,
        vision_raw=analysis.vision_raw,
        vision_structured=analysis.vision_structured,
        vision_path_a=analysis.vision_path_a,
        vision_path_b=analysis.vision_path_b,
        cross_validation=analysis.cross_validation,
        report=analysis.report,
        pose_data=analysis.pose_data,
        bio_data=analysis.bio_data,
        frame_motion_scores=analysis.frame_motion_scores,
        video_temporal_diagnostics=_video_temporal_diagnostics(
            analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None,
            analysis_id=analysis.id,
        ),
        processing_timings=analysis.processing_timings,
        processing_logs=_normalize_processing_logs(analysis.processing_logs),
        target_lock=analysis.target_lock,
        target_lock_status=analysis.target_lock_status,
        action_window_start=analysis.action_window_start,
        action_window_end=analysis.action_window_end,
        manual_action_window_start=analysis.manual_action_window_start,
        manual_action_window_end=analysis.manual_action_window_end,
        source_duration_sec=input_window.get("source_duration_sec"),
        input_window_start_sec=input_window.get("input_window_start_sec"),
        input_window_end_sec=input_window.get("input_window_end_sec"),
        input_window_duration_sec=input_window.get("input_window_duration_sec"),
        input_window_mode=input_window.get("input_window_mode"),
        input_window_truncated=bool(input_window.get("input_window_truncated", False)),
        input_window_reason=input_window.get("input_window_reason"),
        source_fps=analysis.source_fps,
        is_slow_motion=analysis.is_slow_motion,
        force_score=analysis.force_score,
        auto_unlocked_skill=analysis.auto_unlocked_skill,
        error_code=analysis.error_code,
        error_detail=analysis.error_detail if include_error_detail else None,
        error_message=analysis.error_message,
        note=analysis.note,
        created_at=_coerce_utc_datetime(analysis.created_at) or analysis.created_at,
        updated_at=_coerce_utc_datetime(analysis.updated_at) or analysis.updated_at,
    )


def _fusion_diagnostics_summary(cross_validation: dict[str, Any] | None) -> list[str]:
    if not isinstance(cross_validation, dict):
        return []
    diagnostics = cross_validation.get("fusion_diagnostics")
    if not isinstance(diagnostics, dict):
        return []

    summary: list[str] = []
    for key in ("conflict_level", "downgraded_reasons", "needs_human_review", "key_frame_order_invalid"):
        value = diagnostics.get(key)
        if value in (None, [], {}, False):
            continue
        if isinstance(value, list):
            summary.extend(str(item) for item in value if item)
        else:
            summary.append(f"{key}={value}")
    return summary


def _auto_eval_snapshot_from_analysis(analysis: Analysis) -> AnalysisAutoEvalSnapshot:
    bio_data = analysis.bio_data if isinstance(analysis.bio_data, dict) else None
    cross_validation = analysis.cross_validation if isinstance(analysis.cross_validation, dict) else None
    return AnalysisAutoEvalSnapshot(
        analysis_id=analysis.id,
        created_at=_coerce_utc_datetime(analysis.created_at) or analysis.created_at,
        pipeline_version=analysis.pipeline_version,
        analysis_profile=analysis.analysis_profile,
        action_type=analysis.action_type,
        auto_eval=cross_validation.get("auto_eval") if cross_validation else None,
        key_frame_candidates=bio_data.get("key_frame_candidates") if bio_data else None,
        fusion_diagnostics=_fusion_diagnostics_summary(cross_validation),
    )


def _build_pose_response(analysis_id: str, pose_data: dict[str, object] | None) -> PoseResponse:
    safe_pose_data = pose_data if isinstance(pose_data, dict) else {"connections": [], "frames": []}
    frame_urls = {
        frame.get("frame", ""): f"/api/frames/{analysis_id}/{frame.get('frame', '')}"
        for frame in safe_pose_data.get("frames", [])
        if isinstance(frame, dict) and frame.get("frame")
    }
    return PoseResponse(
        connections=safe_pose_data.get("connections", []),
        frames=safe_pose_data.get("frames", []),
        frame_urls=frame_urls,
        pose_diagnostics=safe_pose_data.get("pose_diagnostics") if isinstance(safe_pose_data.get("pose_diagnostics"), dict) else None,
    )


def _fallback_motion_payload(frames_dir: Path) -> dict[str, object]:
    frame_paths = sorted(frames_dir.glob("frame_*.jpg"))
    selected = []
    for index, frame_path in enumerate(frame_paths):
        selected.append(
            {
                "frame_id": frame_path.stem,
                "source_thumb_index": index,
                "timestamp": round(index / 5, 3),
                "motion_score": None,
            }
        )

    return {
        "frame_rate": 5,
        "thumb_size": None,
        "full_size": None,
        "total_thumb_frames": len(frame_paths),
        "sample_count": len(frame_paths),
        "selected": selected,
        "scores": [],
        "source": "legacy_frames",
    }


def _formal_target_preview_candidates(
    sampled_frames: list[Path],
    motion_scores: dict[str, Any] | object,
) -> list[dict[str, Any]]:
    frame_names = [frame.name for frame in sampled_frames]
    anchor_candidates: list[dict[str, Any]] = []
    for anchor_index in target_preview_anchor_frame_indices(
        frame_names,
        motion_scores if isinstance(motion_scores, dict) else None,
    ):
        if anchor_index < 0 or anchor_index >= len(sampled_frames):
            continue
        frame_path = sampled_frames[anchor_index]
        try:
            detected = detect_person_candidates(frame_path, include_zoomed_small_targets=True)
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not detect target preview candidates on %s: %s", frame_path, exc)
            continue
        for candidate in detected:
            item = dict(candidate)
            item["id"] = f"anchor_{anchor_index}_{candidate.get('id') or len(anchor_candidates) + 1}"
            item["anchor_frame"] = frame_path.name
            item["anchor_index"] = anchor_index
            anchor_candidates.append(item)

    selected = select_stable_target_candidate(anchor_candidates)
    if selected is None:
        return anchor_candidates

    selected = dict(selected)
    selected["id"] = "candidate_auto_stable"
    selected["source"] = str(selected.get("source") or "yolo_preview_multi_anchor")
    return [selected, *anchor_candidates]


def _target_preview_detected_candidates_from_frames(
    frames_dir: Path,
    frame_names: list[str],
    motion_scores: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sampled_frames = [frames_dir / frame_name for frame_name in frame_names]
    sampled_frames = [frame for frame in sampled_frames if frame.exists()]
    if not sampled_frames:
        return []
    return _formal_target_preview_candidates(sampled_frames, motion_scores or {})


async def _resume_auto_target_lock_if_available(analysis: Analysis, session: AsyncSession) -> bool:
    if analysis.status != "awaiting_target_selection":
        return False

    frames_dir = _frames_dir_for_analysis(analysis)
    frame_names = frame_names_from_dir(frames_dir)
    if not frame_names:
        return False

    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
    preview = build_target_preview(
        analysis.id,
        frame_names,
        existing_target_lock=analysis.target_lock,
        motion_scores=motion_scores,
        analysis_profile=analysis.analysis_profile,
        detected_candidates=_target_preview_detected_candidates_from_frames(frames_dir, frame_names, motion_scores),
    )
    if preview.target_lock_status != "auto_locked":
        target_lock = build_target_lock_payload(preview)
        if isinstance(target_lock, dict):
            analysis.target_lock = target_lock
            analysis.target_lock_status = str(target_lock.get("status") or preview.target_lock_status)
            await _commit_analysis_session(session, context=f"resume_auto_target_lock_preview_refresh:{analysis.id}", refresh=analysis)
        return False

    target_lock = build_target_lock_payload(preview)
    target_lock = _append_target_lock_flags(target_lock, ["target_lock_auto_resume_from_preview"])
    analysis.target_lock = target_lock
    analysis.target_lock_status = str(target_lock.get("status") or "auto_locked")
    analysis.retry_from_stage = "pose"
    analysis.status = "failed"
    analysis.error_code = None
    analysis.error_detail = None
    analysis.error_message = None
    await _commit_analysis_session(session, context=f"resume_auto_target_lock:{analysis.id}", refresh=analysis)
    return True


def _append_target_lock_flags(target_lock: dict[str, Any], flags: list[str]) -> dict[str, Any]:
    existing = target_lock.get("quality_flags") if isinstance(target_lock.get("quality_flags"), list) else []
    merged = list(existing)
    for flag in flags:
        if flag not in merged:
            merged.append(flag)
    target_lock["quality_flags"] = merged
    return target_lock


def _clear_person_tracker_flags(target_lock: dict[str, Any]) -> dict[str, Any]:
    existing = target_lock.get("quality_flags") if isinstance(target_lock.get("quality_flags"), list) else []
    target_lock["quality_flags"] = [flag for flag in existing if not str(flag).startswith("person_tracker_")]
    return target_lock


def _count_diagnostic_states(diagnostics: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(diagnostics, list):
        return counts
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    return counts


def _diagnostic_final_state(diagnostics: Any) -> str | None:
    if not isinstance(diagnostics, list) or not diagnostics:
        return None
    for item in reversed(diagnostics):
        if isinstance(item, dict):
            return str(item.get("state") or "unknown")
    return None


def _tracker_debug_summary(target_lock: dict[str, Any], frame_count: int) -> dict[str, Any]:
    flags = target_lock.get("quality_flags") if isinstance(target_lock.get("quality_flags"), list) else []
    diagnostics = target_lock.get("person_tracker_diagnostics") if isinstance(target_lock.get("person_tracker_diagnostics"), list) else []
    state_counts = _count_diagnostic_states(diagnostics)
    tracker_type = target_lock.get("tracker_type") or ("yolo_bytetrack" if diagnostics else "fallback")
    return {
        "tracker_type": tracker_type,
        "frame_count": frame_count,
        "diagnostic_frames": len(diagnostics),
        "tracked": (
            state_counts.get("tracked", 0)
            + state_counts.get("relocked", 0)
            + state_counts.get("detector_relocked", 0)
            + state_counts.get("support_anchor_recovered", 0)
            + state_counts.get("support_anchor_handoff_reused", 0)
        ),
        "lost_reused": state_counts.get("lost_reused", 0),
        "support_anchor_handoff_reused": state_counts.get("support_anchor_handoff_reused", 0),
        "relock_pending": state_counts.get("relock_pending", 0),
        "relocked": state_counts.get("relocked", 0),
        "continuity_rejected": state_counts.get("continuity_rejected", 0),
        "relock_rejected": state_counts.get("relock_rejected", 0),
        "states": state_counts,
        "quality_flags": flags,
    }


def _pose_debug_summary(pose_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(pose_data, dict):
        return {"total_frames": 0, "tracked": 0, "lost": 0, "low_confidence": 0}
    diagnostics = pose_data.get("pose_diagnostics") if isinstance(pose_data.get("pose_diagnostics"), dict) else None
    if diagnostics:
        return {
            "mode": diagnostics.get("mode"),
            "total_frames": diagnostics.get("total_frames", 0),
            "tracked": diagnostics.get("tracked_frames", 0),
            "lost": diagnostics.get("lost_frames", 0),
            "interpolated": diagnostics.get("interpolated_frames", 0),
            "low_confidence": diagnostics.get("low_confidence_frames", 0),
            "multi_pose_frames": diagnostics.get("multi_pose_frames", 0),
            "single_pose_crop_frames": diagnostics.get("single_pose_crop_frames", 0),
            "candidate_count_histogram": diagnostics.get("candidate_count_histogram", {}),
        }

    frames = pose_data.get("frames") if isinstance(pose_data.get("frames"), list) else []
    tracked = 0
    lost = 0
    low_confidence = 0
    candidate_counts: dict[str, int] = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        state = str(frame.get("tracking_state") or "unknown")
        if state == "tracked":
            tracked += 1
        else:
            lost += 1
        confidence = frame.get("tracking_confidence")
        if isinstance(confidence, (int, float)) and float(confidence) < 0.2:
            low_confidence += 1
        candidates = frame.get("pose_candidates") if isinstance(frame.get("pose_candidates"), list) else []
        key = str(len(candidates))
        candidate_counts[key] = candidate_counts.get(key, 0) + 1
    return {
        "mode": "legacy",
        "total_frames": len(frames),
        "tracked": tracked,
        "lost": lost,
        "low_confidence": low_confidence,
        "candidate_count_histogram": candidate_counts,
    }


def _selected_target_bbox(target_lock: dict[str, Any]) -> dict[str, Any] | None:
    selected_bbox = target_lock.get("selected_bbox")
    if isinstance(selected_bbox, dict):
        return selected_bbox

    selected_id = str(target_lock.get("selected_candidate_id") or "").strip()
    candidates = target_lock.get("candidates") if isinstance(target_lock.get("candidates"), list) else []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if selected_id and str(candidate.get("id") or "").strip() != selected_id:
            continue
        bbox = candidate.get("bbox")
        if isinstance(bbox, dict):
            return bbox
    return None


def _selected_target_candidate(target_lock: dict[str, Any]) -> dict[str, Any] | None:
    selected_id = str(target_lock.get("selected_candidate_id") or "").strip()
    candidates = target_lock.get("candidates") if isinstance(target_lock.get("candidates"), list) else []
    if selected_id:
        for candidate in candidates:
            if isinstance(candidate, dict) and str(candidate.get("id") or "").strip() == selected_id:
                return candidate
    return None


def _target_support_anchor_bboxes_by_frame(
    sampled_frames: list[Path],
    target_lock: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    selected = _selected_target_candidate(target_lock)
    if not isinstance(selected, dict) or not isinstance(selected.get("bbox"), dict):
        return {}
    candidates = target_lock.get("candidates") if isinstance(target_lock.get("candidates"), list) else []
    frame_name_to_index = {frame.name: index for index, frame in enumerate(sampled_frames)}
    selected_anchor_index = selected.get("anchor_index")
    try:
        selected_frame_index = int(selected_anchor_index) if selected_anchor_index is not None else None
    except (TypeError, ValueError):
        selected_frame_index = None
    support_frames = {
        str(frame)
        for frame in selected.get("support_anchor_frames", [])
        if isinstance(frame, str) and frame
    }
    by_frame: dict[int, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("bbox"), dict):
            continue
        anchor_frame = str(candidate.get("anchor_frame") or "").strip()
        try:
            anchor_index = int(candidate.get("anchor_index"))
        except (TypeError, ValueError):
            anchor_index = frame_name_to_index.get(anchor_frame, -1)
        if anchor_frame not in support_frames and anchor_index != selected_frame_index:
            continue
        if not candidate_matches_target_anchor(candidate, selected):
            continue
        frame_index = frame_name_to_index.get(anchor_frame, anchor_index)
        if frame_index < 0 or frame_index >= len(sampled_frames):
            continue
        existing = by_frame.get(frame_index)
        if existing is None:
            by_frame[frame_index] = candidate
            continue
        try:
            existing_confidence = float(existing.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            existing_confidence = 0.0
        try:
            candidate_confidence = float(candidate.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            candidate_confidence = 0.0
        if candidate_confidence > existing_confidence:
            by_frame[frame_index] = candidate
    return by_frame


def _manual_lock_static_lost_bbox_per_frame(
    sampled_frames: list[Path],
    selected_bbox: dict[str, Any],
    target_lock: dict[str, Any],
    *,
    fallback_reason: str,
) -> list[dict[str, float]]:
    bbox = {
        "x": float(selected_bbox.get("x", 0.0) or 0.0),
        "y": float(selected_bbox.get("y", 0.0) or 0.0),
        "width": float(selected_bbox.get("width", 0.0) or 0.0),
        "height": float(selected_bbox.get("height", 0.0) or 0.0),
    }
    bbox_per_frame = [dict(bbox) for _ in sampled_frames]
    diagnostics = [
        {
            "frame": frame.name,
            "frame_index": frame_index,
            "state": "lost_reused",
            "bbox": dict(bbox),
            "tracker_id": None,
            "lost_frames": frame_index + 1,
            "rejected_reasons": [
                "manual_lock_fallback_blocked",
                fallback_reason,
            ],
            "relock_source": "manual_lock",
        }
        for frame_index, frame in enumerate(sampled_frames)
    ]
    if diagnostics:
        diagnostics[-1]["sequence_summary"] = {
            "state_counts": {"lost_reused": len(diagnostics)},
            "loss_frames": len(diagnostics),
            "recovered_frames": 0,
            "tracked_frames": 0,
            "total_frames": len(diagnostics),
            "final_state": "lost_reused",
            "terminal_loss_frames": len(diagnostics),
            "terminal_loss_graced": False,
            "final_unrecovered": True,
            "transient_loss_recovered": False,
        }
    _append_target_lock_flags(
        target_lock,
        [
            PERSON_TRACKER_MANUAL_LOCK_FALLBACK_BLOCKED_FLAG,
            PERSON_TRACKER_TARGET_LOST_FLAG,
            PERSON_TRACKER_FINAL_UNRECOVERED_FLAG,
        ],
    )
    target_lock["bbox_per_frame"] = bbox_per_frame
    target_lock["person_tracker_diagnostics"] = diagnostics
    target_lock["tracker_type"] = "manual_lock_static_lost"
    return bbox_per_frame


def _bbox_metric(bbox: dict[str, Any] | None, field: str) -> float | None:
    if not isinstance(bbox, dict):
        return None
    try:
        value = float(bbox.get(field))
    except (TypeError, ValueError):
        return None
    return value if value == value else None


def _pose_tracked_ratio(pose_data: dict[str, Any] | None) -> float | None:
    if not isinstance(pose_data, dict):
        return None
    diagnostics = pose_data.get("pose_diagnostics")
    if isinstance(diagnostics, dict):
        try:
            total = float(diagnostics.get("total_frames") or 0.0)
            tracked = float(diagnostics.get("tracked_frames") or 0.0)
        except (TypeError, ValueError):
            return None
        return tracked / total if total > 0 else None

    frames = pose_data.get("frames") if isinstance(pose_data.get("frames"), list) else []
    if not frames:
        return None
    tracked = sum(1 for frame in frames if isinstance(frame, dict) and str(frame.get("tracking_state") or "") == "tracked")
    return tracked / max(len(frames), 1)


def _tracker_loss_ratio(target_lock: dict[str, Any]) -> float | None:
    diagnostics = target_lock.get("person_tracker_diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        return None
    state_counts = _count_diagnostic_states(diagnostics)
    loss_states = {
        "lost_reused",
        "relock_rejected",
        "continuity_rejected",
        "relock_pending",
        "full_frame_yolo_relock_pending",
        "local_zoom_yolo_relock_pending",
    }
    loss_frames = sum(count for state, count in state_counts.items() if state in loss_states or state.endswith("_relock_pending"))
    return loss_frames / max(len(diagnostics), 1)


def _tracker_instability_state_counts(target_lock: dict[str, Any]) -> dict[str, int]:
    diagnostics = target_lock.get("person_tracker_diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        return {}
    return _count_diagnostic_states(diagnostics)


def _tracker_final_state(target_lock: dict[str, Any]) -> str | None:
    return _diagnostic_final_state(target_lock.get("person_tracker_diagnostics"))


def _target_lock_multiperson_risk_context(target_lock: dict[str, Any]) -> bool:
    flags = {
        str(flag)
        for flag in target_lock.get("quality_flags", [])
        if str(flag).strip()
    } if isinstance(target_lock.get("quality_flags"), list) else set()
    if flags & {
        "target_lock_zoomed_multiperson_manual_review",
        "target_lock_zoomed_multiperson_scale_competitor_manual_review",
    }:
        return True
    if any(str(flag).startswith("target_lock_zoomed_multiperson_review_") for flag in flags):
        return True

    candidates = target_lock.get("candidates") if isinstance(target_lock.get("candidates"), list) else []
    selected_id = str(target_lock.get("selected_candidate_id") or "")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if selected_id and str(candidate.get("id") or "") != selected_id:
            continue
        try:
            ambiguous_frames = int(candidate.get("multiperson_ambiguous_frame_count") or 0)
            competitor_count = int(candidate.get("multiperson_competitor_count") or 0)
            other_ambiguous = int(candidate.get("multiperson_other_frame_ambiguous_count") or 0)
        except (TypeError, ValueError):
            return False
        if ambiguous_frames >= 3 and competitor_count >= 6:
            return True
        if other_ambiguous >= 2 and competitor_count >= 4:
            return True
        return False
    return False


def _multiperson_relock_instability_risk_flags(
    target_lock: dict[str, Any],
    pose_data: dict[str, Any] | None,
) -> list[str]:
    if not _target_lock_multiperson_risk_context(target_lock):
        return []

    diagnostics = target_lock.get("person_tracker_diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        return []

    state_counts = _count_diagnostic_states(diagnostics)
    relock_events = sum(
        state_counts.get(state, 0)
        for state in (
            "relocked",
            "detector_relocked",
            "relock_pending",
            "full_frame_yolo_relock_pending",
            "local_zoom_yolo_relock_pending",
        )
    )
    rejected_events = state_counts.get("relock_rejected", 0) + state_counts.get("lost_reused", 0)
    loss_ratio = _tracker_loss_ratio(target_lock)
    pose_ratio = _pose_tracked_ratio(pose_data)
    high_loss = loss_ratio is not None and loss_ratio >= 0.25
    low_pose_tracking = pose_ratio is not None and pose_ratio < 0.70
    repeated_relock = relock_events >= 3 and (state_counts.get("detector_relocked", 0) + state_counts.get("relocked", 0)) >= 1
    unstable_rejections = rejected_events >= 2 and relock_events >= 2
    if (high_loss or low_pose_tracking) and (repeated_relock or unstable_rejections):
        return [PERSON_TRACKER_MULTIPERSON_RELOCK_INSTABILITY_RISK_FLAG]
    return []


def _tiny_target_pose_tracking_risk_flags(
    target_lock: dict[str, Any],
    pose_data: dict[str, Any] | None,
) -> list[str]:
    bbox = _selected_target_bbox(target_lock)
    width = _bbox_metric(bbox, "width")
    height = _bbox_metric(bbox, "height")
    if width is None or height is None:
        return []
    bbox_area = max(0.0, width) * max(0.0, height)
    tiny_target = bbox_area <= 0.0035 or height <= 0.10
    if not tiny_target:
        return []

    pose_ratio = _pose_tracked_ratio(pose_data)
    loss_ratio = _tracker_loss_ratio(target_lock)
    state_counts = _tracker_instability_state_counts(target_lock)
    confirmed_relocks = int(state_counts.get("relocked", 0) or 0) + int(state_counts.get("detector_relocked", 0) or 0)
    hard_rejections = int(state_counts.get("relock_rejected", 0) or 0) + int(state_counts.get("continuity_rejected", 0) or 0)
    terminal_lost = _tracker_final_state(target_lock) in {"lost_reused", "relock_rejected", "continuity_rejected"}
    tracker_unstable = (
        confirmed_relocks > 0
        or hard_rejections > 0
        or terminal_lost
    )
    low_pose_tracking = pose_ratio is not None and pose_ratio < 0.65
    high_tracker_loss = loss_ratio is not None and loss_ratio >= 0.35
    if low_pose_tracking or high_tracker_loss or tracker_unstable:
        return [PERSON_TRACKER_TINY_TARGET_LOW_POSE_TRACKING_RISK_FLAG]
    return []


def _compact_json_detail(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _sync_report_user_note(report: dict[str, Any] | None, note: str | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return report
    updated = dict(report)
    normalized_note = _normalize_optional_text(note)
    if normalized_note:
        updated["user_note"] = normalized_note
    else:
        updated.pop("user_note", None)
    return updated


def _build_bbox_per_frame(
    sampled_frames: list[Path],
    target_lock: dict[str, Any],
    effective_fps: float | None = None,
) -> list[dict[str, float]] | None:
    selected_bbox = target_lock.get("selected_bbox")
    if not isinstance(selected_bbox, dict):
        return None
    preview_frame_index = target_lock.get("preview_frame_index")
    try:
        anchor_index = int(preview_frame_index) if preview_frame_index is not None else 0
    except (TypeError, ValueError):
        anchor_index = 0
    manual_lock_mode = bool(target_lock.get("manual_override"))
    _clear_person_tracker_flags(target_lock)
    try:
        support_anchor_bboxes_by_frame = _target_support_anchor_bboxes_by_frame(sampled_frames, target_lock)
        if manual_lock_mode and support_anchor_bboxes_by_frame:
            _append_target_lock_flags(target_lock, [PERSON_TRACKER_MANUAL_LOCK_SUPPORT_ANCHOR_BLOCKED_FLAG])
            support_anchor_bboxes_by_frame = {}
        bbox_per_frame, flags, diagnostics = track_person_bbox_detailed(
            sampled_frames,
            selected_bbox,
            initial_frame_index=anchor_index,
            effective_fps=effective_fps,
            support_anchor_bboxes_by_frame=support_anchor_bboxes_by_frame,
            manual_lock_mode=manual_lock_mode,
        )
        _append_target_lock_flags(target_lock, flags)
        target_lock["bbox_per_frame"] = bbox_per_frame
        target_lock["person_tracker_diagnostics"] = diagnostics
        target_lock["tracker_type"] = "yolo_bytetrack"
        return bbox_per_frame
    except PersonTrackerUnavailable:
        logger.info("person tracker unavailable during bbox tracking", exc_info=True)
        _append_target_lock_flags(target_lock, [PERSON_TRACKER_UNAVAILABLE_FLAG])
        if manual_lock_mode:
            return _manual_lock_static_lost_bbox_per_frame(
                sampled_frames,
                selected_bbox,
                target_lock,
                fallback_reason=PERSON_TRACKER_UNAVAILABLE_FLAG,
            )
    except Exception:  # noqa: BLE001
        logger.warning("person tracker failed during bbox tracking", exc_info=True)
        _append_target_lock_flags(target_lock, [PERSON_TRACKER_FAILED_FLAG])
        if manual_lock_mode:
            return _manual_lock_static_lost_bbox_per_frame(
                sampled_frames,
                selected_bbox,
                target_lock,
                fallback_reason=PERSON_TRACKER_FAILED_FLAG,
            )

    try:
        bbox_per_frame, flags = track_bbox(sampled_frames, selected_bbox, initial_frame_index=anchor_index)
        _append_target_lock_flags(target_lock, flags)
        target_lock["bbox_per_frame"] = bbox_per_frame
        target_lock["tracker_type"] = "csrt_fallback"
        return bbox_per_frame
    except Exception:  # noqa: BLE001
        logger.warning("bbox tracker failed; falling back to static target bbox", exc_info=True)
        _append_target_lock_flags(target_lock, ["bbox_tracker_failed_fallback"])
        bbox_per_frame = [selected_bbox for _ in sampled_frames]
        target_lock["bbox_per_frame"] = bbox_per_frame
        target_lock["tracker_type"] = "static_fallback"
        return bbox_per_frame


def _video_path_for_analysis(analysis: Analysis) -> Path:
    raw_video_path = Path(analysis.video_path)
    if raw_video_path.exists():
        return raw_video_path

    filename = raw_video_path.name or "source.mp4"
    upload_dir = UPLOADS_DIR / analysis.id
    fallback_video_path = upload_dir / filename
    if fallback_video_path.exists():
        return fallback_video_path

    for candidate in upload_dir.glob("source.*"):
        if candidate.is_file():
            return candidate

    return fallback_video_path


def _archived_video_path_for_analysis(analysis: Analysis) -> Path | None:
    raw_video_path = Path(analysis.video_path)
    archive_dir = UPLOADS_DIR.parent / "archive" / analysis.id
    candidates = []
    if raw_video_path.name:
        candidates.append(archive_dir / raw_video_path.name)
    candidates.extend(sorted(archive_dir.glob("source.*")) if archive_dir.exists() else [])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _frames_dir_for_analysis(analysis: Analysis) -> Path:
    frames_dir = _video_path_for_analysis(analysis).parent / "frames"
    if frames_dir.exists():
        return frames_dir
    return UPLOADS_DIR / analysis.id / "frames"


def _safe_video_response_path(analysis: Analysis) -> Path | None:
    candidate = _video_path_if_available(analysis)
    if candidate is None:
        return None
    resolved = candidate.resolve()
    allowed_roots = [UPLOADS_DIR.resolve(), (UPLOADS_DIR.parent / "archive").resolve()]
    if not any(root == resolved or root in resolved.parents for root in allowed_roots):
        logger.warning("Blocked unsafe video path for analysis %s: %s", analysis.id, resolved)
        return None
    if resolved.suffix.lower() not in COMPARE_VIDEO_SUFFIXES:
        return None
    return resolved


def _video_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".mov":
        return "video/quicktime"
    if suffix == ".avi":
        return "video/x-msvideo"
    if suffix == ".mkv":
        return "video/x-matroska"
    return "video/mp4"


def _can_backfill_artifacts(status_value: str | None) -> bool:
    return status_value in {"completed", "failed"}


def _has_complete_saved_analysis_outputs(analysis: Analysis) -> bool:
    bio_data = analysis.bio_data if isinstance(analysis.bio_data, dict) else {}
    key_frames = bio_data.get("key_frames") if isinstance(bio_data.get("key_frames"), dict) else {}
    return (
        isinstance(analysis.report, dict)
        and analysis.force_score is not None
        and isinstance(analysis.vision_structured, dict)
        and isinstance(analysis.pose_data, dict)
        and isinstance(analysis.frame_motion_scores, dict)
        and all(key_frames.get(label) for label in ("T", "A", "L"))
    )


def _bio_key_frames_intentionally_unsynced(bio_data: dict[str, Any] | None) -> bool:
    if not isinstance(bio_data, dict):
        return False
    flags = bio_data.get("quality_flags")
    if not isinstance(flags, list):
        return False
    return any(
        isinstance(flag, str)
        and (
            flag.startswith("bio_key_frames_not_synced_")
            or flag == "bio_key_frames_not_restored_unreliable_candidates"
        )
        for flag in flags
    )


async def _restore_completed_report_save_failure(session: AsyncSession, analysis: Analysis) -> Analysis:
    if (
        analysis.status != "failed"
        or analysis.error_code != AnalysisErrorCode.REPORT_SAVE_FAILED.value
        or not _has_complete_saved_analysis_outputs(analysis)
    ):
        return analysis

    logs = _normalize_processing_logs(analysis.processing_logs)
    logs.append(
        {
            "timestamp": _utc_now_iso(),
            "stage": "report",
            "level": "warning",
            "message": friendly_error_title(AnalysisErrorCode.REPORT_SAVE_FAILED),
            "error_code": AnalysisErrorCode.REPORT_SAVE_FAILED.value,
            "detail": "Recovered completed analysis from persisted report outputs after transient save failure.",
            "restored_completed_state": True,
        }
    )
    analysis.status = "completed"
    analysis.error_code = None
    analysis.error_detail = None
    analysis.error_message = None
    analysis.retry_from_stage = None
    analysis.processing_logs = logs[-MAX_ANALYSIS_LOG_ENTRIES:]
    await _commit_analysis_session(session, context=f"restore_completed_report_save_failure:{analysis.id}", refresh=analysis)
    return analysis


async def _restore_missing_analysis_frames(session: AsyncSession, analysis: Analysis) -> tuple[Analysis, Path]:
    frames_dir = _frames_dir_for_analysis(analysis)
    existing_frame_paths = sorted(frames_dir.glob("frame_*.jpg")) if frames_dir.exists() else []
    if existing_frame_paths:
        return analysis, frames_dir

    video_path = _video_path_for_analysis(analysis)
    if not video_path.exists():
        return analysis, frames_dir

    logger.info("Analysis %s is missing persisted frame images, attempting backfill", analysis.id)
    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
    selected_frames = motion_scores.get("selected") if isinstance(motion_scores, dict) else None

    restored_paths: list[Path] = []
    if isinstance(selected_frames, list):
        try:
            restored_paths = await restore_sampled_frames(video_path, frames_dir, selected_frames)
        except Exception:  # noqa: BLE001
            logger.warning("Analysis %s failed to restore frames from saved timestamps", analysis.id, exc_info=True)

    if not restored_paths:
        processing_dir, processing_frames_dir = build_processing_frames_dir(analysis.id)
        try:
            restored_paths, motion_scores, sampling_metadata = await extract_motion_sampled_frames(
                video_path,
                processing_frames_dir,
                analysis.action_type,
                analysis.analysis_profile or infer_profile_hint(analysis.action_type, analysis.action_subtype),
                input_window=build_video_input_window(
                    video_path,
                    manual_start_sec=analysis.manual_action_window_start,
                    manual_end_sec=analysis.manual_action_window_end,
                ),
            )
            persist_frames(restored_paths, frames_dir)
            analysis.frame_motion_scores = motion_scores
            analysis.action_window_start = sampling_metadata.action_window_start
            analysis.action_window_end = sampling_metadata.action_window_end
            analysis.source_fps = sampling_metadata.source_fps
            analysis.is_slow_motion = sampling_metadata.is_slow_motion
            await _commit_analysis_session(session, context=f"restore_missing_analysis_frames:{analysis.id}", refresh=analysis)
        finally:
            cleanup_processing_dir(analysis.id)
    else:
        logger.info("Analysis %s restored %s frame images from saved timestamps", analysis.id, len(restored_paths))

    return analysis, frames_dir


async def _ensure_phase3_artifacts(session: AsyncSession, analysis: Analysis) -> Analysis:
    if not _can_backfill_artifacts(analysis.status):
        return analysis

    analysis = await _restore_completed_report_save_failure(session, analysis)
    analysis, frames_dir = await _restore_missing_analysis_frames(session, analysis)
    if analysis.status != "completed" or not frames_dir.exists():
        return analysis

    changed = False
    pose_data = analysis.pose_data if isinstance(analysis.pose_data, dict) else None
    pose_frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    pose_has_keypoints = any(
        isinstance(frame, dict) and bool(frame.get("keypoints"))
        for frame in pose_frames
    )

    if not pose_frames or not pose_has_keypoints:
        logger.info("Analysis %s is missing pose data, backfilling from existing frames", analysis.id)
        sampling_metadata = _sampling_metadata_from_saved(
            action_window_start=float(analysis.action_window_start or 0.0),
            action_window_end=float(analysis.action_window_end or 0.0),
            source_fps=float(analysis.source_fps or 30.0),
            is_slow_motion=bool(analysis.is_slow_motion),
            motion_scores=analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None,
        )
        computed_pose = await asyncio.to_thread(
            extract_pose,
            str(frames_dir),
            analysis.target_lock if isinstance(analysis.target_lock, dict) else None,
            (
                analysis.target_lock.get("bbox_per_frame")
                if isinstance(analysis.target_lock, dict) and isinstance(analysis.target_lock.get("bbox_per_frame"), list)
                else None
            ),
            sampling_metadata.effective_fps,
        )
        analysis.pose_data = computed_pose
        pose_data = computed_pose
        changed = True

    if analysis.frame_motion_scores is None:
        logger.info("Analysis %s is missing motion sampling metadata, generating legacy fallback payload", analysis.id)
        analysis.frame_motion_scores = _fallback_motion_payload(frames_dir)
        changed = True

    bio_data = analysis.bio_data if isinstance(analysis.bio_data, dict) else None
    should_backfill_bio = bio_data is None or (
        not bio_data.get("key_frames")
        and not _bio_key_frames_intentionally_unsynced(bio_data)
    )
    if should_backfill_bio:
        logger.info("Analysis %s is missing biomechanics data, backfilling from pose payload", analysis.id)
        sampling_metadata = _sampling_metadata_from_saved(
            action_window_start=float(analysis.action_window_start or 0.0),
            action_window_end=float(analysis.action_window_end or 0.0),
            source_fps=float(analysis.source_fps or 30.0),
            is_slow_motion=bool(analysis.is_slow_motion),
            motion_scores=analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None,
        )
        computed_bio_data = analyze_biomechanics(
            pose_data or {"connections": [], "frames": []},
            analysis.action_type,
            analysis.analysis_profile or infer_profile_hint(analysis.action_type, analysis.action_subtype),
            effective_fps=sampling_metadata.effective_fps,
            source_fps=sampling_metadata.source_fps,
            window_seconds=sampling_metadata.window_end_sec - sampling_metadata.window_start_sec,
        )
        analysis_profile = analysis.analysis_profile or infer_profile_hint(analysis.action_type, analysis.action_subtype)
        analysis.bio_data = attach_key_frame_candidates(
            computed_bio_data,
            pose_data or {"connections": [], "frames": []},
            analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None,
            analysis_profile,
            sampling_metadata.effective_fps,
        )
        changed = True
    else:
        sanitized_bio_data = sanitize_biomechanics_data(bio_data)
        if sanitized_bio_data != bio_data:
            logger.info("Analysis %s has implausible biomechanics metrics, sanitizing saved payload", analysis.id)
            analysis.bio_data = sanitized_bio_data
            bio_data = sanitized_bio_data
            changed = True
        if "key_frame_candidates" not in bio_data:
            logger.info("Analysis %s is missing key-frame candidates, backfilling from saved pose and motion", analysis.id)
            sampling_metadata = _sampling_metadata_from_saved(
                action_window_start=float(analysis.action_window_start or 0.0),
                action_window_end=float(analysis.action_window_end or 0.0),
                source_fps=float(analysis.source_fps or 30.0),
                is_slow_motion=bool(analysis.is_slow_motion),
                motion_scores=analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None,
            )
            analysis.bio_data = attach_key_frame_candidates(
                bio_data,
                pose_data,
                analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None,
                analysis.analysis_profile or infer_profile_hint(analysis.action_type, analysis.action_subtype),
                sampling_metadata.effective_fps,
            )
            changed = True

    if changed:
        await _commit_analysis_session(session, context=f"ensure_phase3_artifacts:{analysis.id}", refresh=analysis)

    return analysis


def _list_item_from_analysis(analysis: Analysis, skater_name: str | None = None) -> AnalysisListItem:
    return AnalysisListItem(
        id=analysis.id,
        skater_id=analysis.skater_id,
        session_id=analysis.session_id,
        skater_name=skater_name,
        skill_category=analysis.skill_category,
        action_type=analysis.action_type,
        action_subtype=analysis.action_subtype,
        analysis_profile=analysis.analysis_profile,
        pipeline_version=analysis.pipeline_version,
        status=analysis.status,
        force_score=analysis.force_score,
        note=analysis.note,
        created_at=_coerce_utc_datetime(analysis.created_at) or analysis.created_at,
        updated_at=_coerce_utc_datetime(analysis.updated_at) or analysis.updated_at,
    )


def _build_issue_map(report: dict[str, object] | None) -> dict[str, dict[str, str]]:
    issues = report.get("issues", []) if isinstance(report, dict) else []
    issue_map: dict[str, dict[str, str]] = {}
    for raw_issue in issues:
        if not isinstance(raw_issue, dict):
            continue
        category = str(raw_issue.get("category", "")).strip() or "未分类问题"
        issue_map[category] = {
            "category": category,
            "description": str(raw_issue.get("description", "")).strip(),
            "severity": str(raw_issue.get("severity", "low")).strip().lower(),
        }
    return issue_map


def _compare_reports(report_a: dict[str, object] | None, report_b: dict[str, object] | None) -> CompareSummary:
    issues_a = _build_issue_map(report_a)
    issues_b = _build_issue_map(report_b)
    categories = list(dict.fromkeys([*issues_a.keys(), *issues_b.keys()]))

    improved: list[ComparisonChange] = []
    added: list[ComparisonChange] = []
    unchanged: list[ComparisonChange] = []

    for category in categories:
        before = issues_a.get(category)
        after = issues_b.get(category)

        before_severity = before["severity"] if before else None
        after_severity = after["severity"] if after else None

        if before and not after:
            improved.append(
                ComparisonChange(
                    category=category,
                    before_severity=before_severity,
                    after_severity=None,
                    description=f"{before['description']} 当前复盘中未再出现。",
                )
            )
            continue

        if not before and after:
            added.append(
                ComparisonChange(
                    category=category,
                    before_severity=None,
                    after_severity=after_severity,
                    description=after["description"],
                )
            )
            continue

        if before is None or after is None:
            continue

        before_rank = SEVERITY_RANK.get(before["severity"], 1)
        after_rank = SEVERITY_RANK.get(after["severity"], 1)
        description = after["description"] or before["description"]

        if after_rank < before_rank:
            improved.append(
                ComparisonChange(
                    category=category,
                    before_severity=before_severity,
                    after_severity=after_severity,
                    description=description,
                )
            )
        elif after_rank > before_rank:
            added.append(
                ComparisonChange(
                    category=category,
                    before_severity=before_severity,
                    after_severity=after_severity,
                    description=description,
                )
            )
        else:
            unchanged.append(
                ComparisonChange(
                    category=category,
                    before_severity=before_severity,
                    after_severity=after_severity,
                    description=description,
                )
            )

    return CompareSummary(improved=improved, added=added, unchanged=unchanged)


def _to_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _round_delta_value(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    rounded = round(value, digits)
    return int(rounded) if float(rounded).is_integer() else rounded


def _delta_trend(delta: float | None) -> str:
    if delta is None:
        return "unavailable"
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _build_delta(key: str, label: str, before: object, after: object, unit: str | None = None) -> CompareDelta:
    before_value = _to_number(before)
    after_value = _to_number(after)
    delta = after_value - before_value if before_value is not None and after_value is not None else None
    return CompareDelta(
        key=key,
        label=label,
        before=_round_delta_value(before_value),
        after=_round_delta_value(after_value),
        delta=_round_delta_value(delta),
        unit=unit,
        trend=_delta_trend(delta),
        available=before_value is not None and after_value is not None,
    )


def _report_subscores(analysis: Analysis) -> dict[str, Any]:
    report = analysis.report if isinstance(analysis.report, dict) else {}
    subscores = report.get("subscores")
    return subscores if isinstance(subscores, dict) else {}


def _bio_dict(analysis: Analysis) -> dict[str, Any]:
    return analysis.bio_data if isinstance(analysis.bio_data, dict) else {}


def _build_subscore_deltas(analysis_a: Analysis, analysis_b: Analysis) -> list[CompareDelta]:
    before = _report_subscores(analysis_a)
    after = _report_subscores(analysis_b)
    return [
        _build_delta(key, label, before.get(key), after.get(key), "分")
        for key, label in SUBSCORE_COMPARE_LABELS.items()
    ]


def _build_metric_deltas(analysis_a: Analysis, analysis_b: Analysis) -> list[CompareDelta]:
    before_bio = _bio_dict(analysis_a)
    after_bio = _bio_dict(analysis_b)
    before_jump = before_bio.get("jump_metrics") if isinstance(before_bio.get("jump_metrics"), dict) else {}
    after_jump = after_bio.get("jump_metrics") if isinstance(after_bio.get("jump_metrics"), dict) else {}
    if before_jump or after_jump or analysis_a.analysis_profile == "jump" or analysis_b.analysis_profile == "jump":
        return [
            _build_delta(key, label, before_jump.get(key), after_jump.get(key), unit)
            for key, (label, unit) in JUMP_METRIC_COMPARE_LABELS.items()
        ]

    before_metrics = before_bio.get("discipline_metrics") if isinstance(before_bio.get("discipline_metrics"), dict) else {}
    after_metrics = after_bio.get("discipline_metrics") if isinstance(after_bio.get("discipline_metrics"), dict) else {}
    before_subscores = before_bio.get("bio_subscores") if isinstance(before_bio.get("bio_subscores"), dict) else {}
    after_subscores = after_bio.get("bio_subscores") if isinstance(after_bio.get("bio_subscores"), dict) else {}
    metric_deltas = [
        _build_delta(key, label, before_metrics.get(key), after_metrics.get(key), unit)
        for key, (label, unit) in NON_JUMP_METRIC_LABELS.items()
    ]
    metric_deltas.extend(
        _build_delta(key, label, before_subscores.get(key), after_subscores.get(key), "分")
        for key, label in SUBSCORE_COMPARE_LABELS.items()
    )
    return [item for item in metric_deltas if item.available]


def _deltas_within_threshold(deltas: list[CompareDelta], threshold: float) -> bool:
    for delta in deltas:
        if not delta.available or delta.delta is None:
            continue
        value = _to_number(delta.delta)
        if value is not None and abs(value) > threshold:
            return False
    return True


def _frame_timestamp_map(analysis: Analysis) -> dict[str, float]:
    return build_timestamp_map(analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None)


def _normalize_frame_stem(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:-4] if text.lower().endswith(".jpg") else text


def _keyframe_candidate_map(analysis: Analysis) -> dict[str, dict[str, Any]]:
    bio_data = _bio_dict(analysis)
    candidates = bio_data.get("key_frame_candidates")
    return candidates if isinstance(candidates, dict) else {}


def _legacy_keyframes(analysis: Analysis) -> dict[str, Any]:
    bio_data = _bio_dict(analysis)
    keyframes = bio_data.get("key_frames")
    return keyframes if isinstance(keyframes, dict) else {}


def _legacy_keyframe_timestamps(analysis: Analysis) -> dict[str, Any]:
    bio_data = _bio_dict(analysis)
    timestamps = bio_data.get("key_frame_timestamps")
    return timestamps if isinstance(timestamps, dict) else {}


def _frame_exists_for_analysis(analysis: Analysis, frame_id: str) -> bool:
    frames_dir = _frames_dir_for_analysis(analysis)
    return (frames_dir / f"{frame_id}.jpg").exists()


def _semantic_keyframe_records(analysis: Analysis) -> list[dict[str, Any]]:
    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else {}
    resolved = motion_scores.get("resolved_keyframes") if isinstance(motion_scores.get("resolved_keyframes"), dict) else {}
    selected = resolved.get("selected") if isinstance(resolved.get("selected"), list) else []
    return [item for item in selected if isinstance(item, dict)]


def _semantic_key_for_record(record: dict[str, Any]) -> str | None:
    key_moment = str(record.get("key_moment") or "").strip()
    if key_moment.startswith("T_"):
        return "T"
    if key_moment.startswith("A_"):
        return "A"
    if key_moment.startswith("L_"):
        return "L"
    phase_code = str(record.get("phase_code") or "").strip()
    profile_phase_labels = {
        "spin_entry": "旋转入",
        "spin_main": "旋转中",
        "spin_exit": "旋转出",
        "spiral_hold": "峰值",
        "step_sequence": "步法序列",
    }
    for code in (phase_code, key_moment):
        if code in profile_phase_labels:
            return profile_phase_labels[code]
    if phase_code == "takeoff":
        return "T"
    if phase_code == "air":
        return "A"
    if phase_code == "landing":
        return "L"
    return None


def _semantic_keyframe_record(analysis: Analysis, key: str) -> dict[str, Any] | None:
    for record in _semantic_keyframe_records(analysis):
        if _semantic_key_for_record(record) == key:
            return record
    return None


def _semantic_keyframe_record_for_frame(analysis: Analysis, key: str, frame_id: str | None) -> dict[str, Any] | None:
    if frame_id is None:
        return None
    semantic = _semantic_keyframe_record(analysis, key)
    if semantic is None:
        return None
    semantic_frame_id = _normalize_frame_stem(semantic.get("frame_id"))
    return semantic if semantic_frame_id == frame_id else None


def _frame_exists_and_url(analysis: Analysis, frame_id: str) -> tuple[bool, str | None]:
    frames_dir = _frames_dir_for_analysis(analysis)
    if (frames_dir / f"{frame_id}.jpg").exists():
        return True, f"/api/frames/{analysis.id}/{frame_id}.jpg"
    if frame_id.startswith("semantic_"):
        semantic_dir = UPLOADS_DIR / analysis.id / "semantic_frames"
        if (semantic_dir / f"{frame_id}.jpg").exists():
            return True, f"/api/frames/{analysis.id}/{frame_id}.jpg"
    return False, None


def _build_keyframe_side(analysis: Analysis, key: str) -> CompareKeyframeSide:
    candidates = _keyframe_candidate_map(analysis)
    candidate = candidates.get(key) if isinstance(candidates.get(key), dict) else None
    legacy = _legacy_keyframes(analysis)
    legacy_frame_id = _normalize_frame_stem(legacy.get(key))
    if legacy_frame_id is not None:
        semantic = _semantic_keyframe_record_for_frame(analysis, key, legacy_frame_id)
        timestamp = _to_number(_legacy_keyframe_timestamps(analysis).get(key))
        if timestamp is None and semantic is not None:
            timestamp = _to_number(semantic.get("timestamp"))
        if timestamp is None and candidate:
            timestamp = _to_number(candidate.get("timestamp"))
        if timestamp is None:
            timestamp = _frame_timestamp_map(analysis).get(legacy_frame_id)
        confidence = _to_number(semantic.get("confidence")) if semantic is not None else None
        if confidence is None and candidate:
            confidence = _to_number(candidate.get("confidence"))
        if semantic is not None:
            raw_flags = semantic.get("quality_flags")
            quality_flags = [str(value) for value in raw_flags if value] if isinstance(raw_flags, list) else []
        else:
            candidate_flags = candidate.get("warnings") if candidate else None
            quality_flags = [str(value) for value in candidate_flags if value] if isinstance(candidate_flags, list) else []
        frame_exists, frame_url = _frame_exists_and_url(analysis, legacy_frame_id)
        return CompareKeyframeSide(
            frame_id=legacy_frame_id,
            frame_url=frame_url,
            timestamp=_round_delta_value(timestamp, 3),
            confidence=_round_delta_value(confidence, 3),
            source="bio_key_frames",
            phase_label=str(semantic.get("phase_label") or "") if semantic is not None else None,
            selection_reason=(
                str(semantic.get("selection_reason") or "")
                if semantic is not None
                else str(candidate.get("detection_method") or "") if candidate else None
            ),
            pre_refine_timestamp=(
                _round_delta_value(_to_number(semantic.get("pre_refine_timestamp")), 3)
                if semantic is not None
                else None
            ),
            refinement_method=(str(semantic.get("refinement_method") or "") or None) if semantic is not None else None,
            refinement_delta_sec=(
                _round_delta_value(_to_number(semantic.get("refinement_delta_sec")), 3)
                if semantic is not None
                else None
            ),
            quality_flags=quality_flags,
            available=frame_exists,
            missing_reason=None if frame_exists else "keyframe image unavailable",
        )

    semantic = _semantic_keyframe_record(analysis, key)
    if semantic is not None:
        frame_id = _normalize_frame_stem(semantic.get("frame_id"))
        timestamp = _to_number(semantic.get("timestamp"))
        confidence = _to_number(semantic.get("confidence"))
        semantic_flags = semantic.get("quality_flags")
        quality_flags = [str(value) for value in semantic_flags if value] if isinstance(semantic_flags, list) else []
        if frame_id:
            frame_exists, frame_url = _frame_exists_and_url(analysis, frame_id)
            return CompareKeyframeSide(
                frame_id=frame_id,
                frame_url=frame_url,
                timestamp=_round_delta_value(timestamp, 3),
                confidence=_round_delta_value(confidence, 3),
                source="resolved_keyframes",
                phase_label=str(semantic.get("phase_label") or ""),
                selection_reason=str(semantic.get("selection_reason") or ""),
                pre_refine_timestamp=_round_delta_value(_to_number(semantic.get("pre_refine_timestamp")), 3),
                refinement_method=str(semantic.get("refinement_method") or "") or None,
                refinement_delta_sec=_round_delta_value(_to_number(semantic.get("refinement_delta_sec")), 3),
                quality_flags=quality_flags,
                available=frame_exists,
                missing_reason=None if frame_exists else "语义关键帧图片不可用",
            )

    candidate = candidates.get(key) if isinstance(candidates.get(key), dict) else None
    frame_id = _normalize_frame_stem(candidate.get("frame_id")) if candidate else None
    if frame_id is None:
        frame_id = _normalize_frame_stem(legacy.get(key))
    if frame_id is None:
        return CompareKeyframeSide(available=False, missing_reason="未识别到该阶段关键帧")

    timestamps = _frame_timestamp_map(analysis)
    timestamp = _to_number(candidate.get("timestamp")) if candidate else None
    if timestamp is None:
        timestamp = timestamps.get(frame_id)
    confidence = _to_number(candidate.get("confidence")) if candidate else None
    frame_exists = _frame_exists_for_analysis(analysis, frame_id)
    return CompareKeyframeSide(
        frame_id=frame_id,
        frame_url=f"/api/frames/{analysis.id}/{frame_id}.jpg" if frame_exists else None,
        timestamp=_round_delta_value(timestamp, 3),
        confidence=_round_delta_value(confidence, 3),
        source="skeleton_candidate" if candidate else "legacy_keyframe",
        phase_label=None,
        selection_reason=None,
        quality_flags=[],
        available=frame_exists,
        missing_reason=None if frame_exists else "关键帧图片不可用",
    )


def _keyframe_labels_for_profile(profile: str | None) -> list[tuple[str, str]]:
    normalized_profile = str(profile or "").strip().lower()
    if normalized_profile == "spin":
        return [("旋转入", "旋转入"), ("旋转中", "旋转中"), ("旋转出", "旋转出")]
    if normalized_profile == "spiral":
        return [("峰值", "姿态峰值")]
    if normalized_profile in {"step", "step_sequence"}:
        return [("步法序列", "步法序列")]
    return [("T", "起跳"), ("A", "腾空"), ("L", "落冰")]


def _keyframe_keys_for_profile(profile: str | None) -> list[str]:
    return [key for key, _ in _keyframe_labels_for_profile(profile)]


def _build_keyframe_compare(analysis_a: Analysis, analysis_b: Analysis) -> list[CompareKeyframePair]:
    profile = analysis_b.analysis_profile or analysis_a.analysis_profile
    pairs: list[CompareKeyframePair] = []
    before_anchor: float | None = None
    after_anchor: float | None = None
    anchor_key = next(iter(_keyframe_keys_for_profile(profile)), "T")
    for key, label in _keyframe_labels_for_profile(profile):
        before = _build_keyframe_side(analysis_a, key)
        after = _build_keyframe_side(analysis_b, key)
        if key == anchor_key:
            before_anchor = before.timestamp
            after_anchor = after.timestamp
        delta_seconds = (
            _round_delta_value(after.timestamp - before.timestamp, 3)
            if before.timestamp is not None and after.timestamp is not None
            else None
        )
        before_offset_seconds = (
            _round_delta_value(before.timestamp - before_anchor, 3)
            if before.timestamp is not None and before_anchor is not None
            else None
        )
        after_offset_seconds = (
            _round_delta_value(after.timestamp - after_anchor, 3)
            if after.timestamp is not None and after_anchor is not None
            else None
        )
        relative_delta_seconds = (
            _round_delta_value(after_offset_seconds - before_offset_seconds, 3)
            if before_offset_seconds is not None and after_offset_seconds is not None
            else None
        )
        pairs.append(
            CompareKeyframePair(
                key=key,
                label=label,
                before=before,
                after=after,
                delta_seconds=delta_seconds,
                before_offset_seconds=before_offset_seconds,
                after_offset_seconds=after_offset_seconds,
                relative_delta_seconds=relative_delta_seconds,
            )
        )
    return pairs


def _keyframe_compare_within_threshold(keyframes: list[CompareKeyframePair], threshold: float) -> bool:
    compared = False
    for pair in keyframes:
        before = pair.before.timestamp
        after = pair.after.timestamp
        if before is None or after is None:
            continue
        compared = True
        if abs(after - before) > threshold:
            return False
    return compared


def _same_video_core_compare_stable(
    analysis_a: Analysis,
    analysis_b: Analysis,
    *,
    score_delta: int,
    subscore_deltas: list[CompareDelta],
    metric_deltas: list[CompareDelta],
    keyframe_compare: list[CompareKeyframePair],
) -> bool:
    sha_a = _video_sha256_for_analysis(analysis_a)
    sha_b = _video_sha256_for_analysis(analysis_b)
    if not sha_a or sha_a != sha_b:
        return False
    if abs(score_delta) > COMPARE_SAME_VIDEO_SCORE_STABILITY_DELTA:
        return False
    if not _deltas_within_threshold(subscore_deltas, COMPARE_SAME_VIDEO_SUBSCORE_STABILITY_DELTA):
        return False
    if not _deltas_within_threshold(metric_deltas, COMPARE_SAME_VIDEO_METRIC_STABILITY_DELTA):
        return False
    return _keyframe_compare_within_threshold(keyframe_compare, COMPARE_SAME_VIDEO_KEYFRAME_STABILITY_SECONDS)


def _stabilize_same_video_compare_summary(summary: CompareSummary) -> CompareSummary:
    unchanged = [*summary.unchanged, *summary.improved, *summary.added]
    return CompareSummary(improved=[], added=[], unchanged=unchanged)


def _video_path_if_available(analysis: Analysis) -> Path | None:
    try:
        path = _video_path_for_analysis(analysis)
    except Exception:  # noqa: BLE001
        return None
    if path.exists() and path.is_file() and path.suffix.lower() in COMPARE_VIDEO_SUFFIXES:
        return path
    archived = _archived_video_path_for_analysis(analysis)
    if archived is not None and archived.suffix.lower() in COMPARE_VIDEO_SUFFIXES:
        return archived
    return None


def _build_video_side(analysis: Analysis) -> CompareVideoSide:
    path = _video_path_if_available(analysis)
    start = _to_number(analysis.action_window_start)
    end = _to_number(analysis.action_window_end)
    duration = round(end - start, 3) if start is not None and end is not None and end > start else None
    return CompareVideoSide(
        analysis_id=analysis.id,
        video_url=f"/api/analysis/{analysis.id}/video" if path is not None else None,
        available=path is not None,
        missing_reason=None if path is not None else "原视频已清理或不可用",
        action_window_start=_round_delta_value(start, 3),
        action_window_end=_round_delta_value(end, 3),
        action_window_duration=_round_delta_value(duration, 3),
        sync_start=_round_delta_value(start or 0.0, 3),
        sync_duration=_round_delta_value(duration, 3),
        is_slow_motion=bool(analysis.is_slow_motion),
        source_fps=_round_delta_value(_to_number(analysis.source_fps), 3),
    )


def _semantic_timestamp_for_key(analysis: Analysis, key: str) -> float | None:
    record = _semantic_keyframe_record(analysis, key)
    return _to_number(record.get("timestamp")) if isinstance(record, dict) else None


def _bio_timestamp_for_key(analysis: Analysis, key: str) -> float | None:
    timestamp = _to_number(_legacy_keyframe_timestamps(analysis).get(key))
    if timestamp is not None:
        return timestamp
    legacy_frame_id = _normalize_frame_stem(_legacy_keyframes(analysis).get(key))
    if legacy_frame_id is None:
        return None
    candidate = _keyframe_candidate_map(analysis).get(key)
    if isinstance(candidate, dict) and _normalize_frame_stem(candidate.get("frame_id")) == legacy_frame_id:
        timestamp = _to_number(candidate.get("timestamp"))
        if timestamp is not None:
            return timestamp
    return _frame_timestamp_map(analysis).get(legacy_frame_id)


def _keyframe_timestamp_for_key(analysis: Analysis, key: str) -> float | None:
    timestamp = _bio_timestamp_for_key(analysis, key)
    if timestamp is not None:
        return timestamp
    return _semantic_timestamp_for_key(analysis, key)


def _keyframe_sync_duration(analysis: Analysis) -> float | None:
    timestamps = [
        timestamp
        for key in _keyframe_keys_for_profile(analysis.analysis_profile)
        if (timestamp := _keyframe_timestamp_for_key(analysis, key)) is not None
    ]
    if len(timestamps) >= 2:
        start = min(timestamps)
        end = max(timestamps)
        if end > start:
            return max(end - start + 0.70, 0.70)
    start = _to_number(analysis.action_window_start)
    end = _to_number(analysis.action_window_end)
    if start is not None and end is not None and end > start:
        return end - start
    return None


def _build_video_compare(analysis_a: Analysis, analysis_b: Analysis) -> CompareVideoPayload:
    before = _build_video_side(analysis_a)
    after = _build_video_side(analysis_b)
    profile = analysis_b.analysis_profile or analysis_a.analysis_profile
    anchor_key = next(iter(_keyframe_keys_for_profile(profile)), "T")
    before_anchor = _keyframe_timestamp_for_key(analysis_a, anchor_key)
    after_anchor = _keyframe_timestamp_for_key(analysis_b, anchor_key)
    if before_anchor is not None and after_anchor is not None:
        before.sync_start = _round_delta_value(max(0.0, before_anchor - 0.35), 3)
        after.sync_start = _round_delta_value(max(0.0, after_anchor - 0.35), 3)
        before.sync_duration = _round_delta_value(_keyframe_sync_duration(analysis_a), 3)
        after.sync_duration = _round_delta_value(_keyframe_sync_duration(analysis_b), 3)
        return CompareVideoPayload(before=before, after=after, sync_mode="bio_keyframe", sync_anchor_key=anchor_key)
    return CompareVideoPayload(before=before, after=after, sync_mode="action_window_start")


def _quality_flags(analysis: Analysis) -> list[str]:
    flags: list[str] = []
    bio_data = _bio_dict(analysis)
    for value in bio_data.get("quality_flags", []) if isinstance(bio_data.get("quality_flags"), list) else []:
        if value:
            flags.append(str(value))
    target_lock = analysis.target_lock if isinstance(analysis.target_lock, dict) else {}
    for value in target_lock.get("quality_flags", []) if isinstance(target_lock.get("quality_flags"), list) else []:
        if value and str(value) not in flags:
            flags.append(str(value))
    cross_validation = analysis.cross_validation if isinstance(analysis.cross_validation, dict) else {}
    auto_eval = cross_validation.get("auto_eval") if isinstance(cross_validation.get("auto_eval"), dict) else {}
    for value in auto_eval.get("data_quality_flags", []) if isinstance(auto_eval.get("data_quality_flags"), list) else []:
        if value and str(value) not in flags:
            flags.append(str(value))
    return flags


def _report_data_quality(analysis: Analysis) -> str | None:
    report = analysis.report if isinstance(analysis.report, dict) else {}
    value = report.get("data_quality")
    return str(value) if value is not None else None


def _build_compare_quality(analysis_a: Analysis, analysis_b: Analysis) -> CompareQualityPayload:
    before_flags = _quality_flags(analysis_a)
    after_flags = _quality_flags(analysis_b)
    warnings: list[str] = []
    if _report_data_quality(analysis_a) == "poor" or _report_data_quality(analysis_b) == "poor":
        warnings.append("存在数据质量较弱的记录，变化结论需要保守解读。")
    if before_flags or after_flags:
        warnings.append("部分姿态或目标追踪信号存在不确定性，建议结合原视频复核。")
    return CompareQualityPayload(
        before_data_quality=_report_data_quality(analysis_a),
        after_data_quality=_report_data_quality(analysis_b),
        before_flags=before_flags,
        after_flags=after_flags,
        warnings=warnings,
    )


def _fallback_compare_narrative(
    *,
    analysis_a: Analysis,
    analysis_b: Analysis,
    score_delta: int,
    subscore_deltas: list[CompareDelta],
    metric_deltas: list[CompareDelta],
    summary: CompareSummary,
) -> str:
    improving = [item for item in subscore_deltas if isinstance(item.delta, (int, float)) and item.delta > 0]
    best = max(improving, key=lambda item: float(item.delta or 0), default=None)
    metric = max(
        (item for item in metric_deltas if isinstance(item.delta, (int, float)) and item.delta > 0),
        key=lambda item: float(item.delta or 0),
        default=None,
    )
    direction = "提高" if score_delta > 0 else "基本持平" if score_delta == 0 else "下降"
    parts = [
        f"这两次{analysis_b.action_subtype or analysis_b.action_type}对比中，综合评分{direction}{abs(score_delta)}分。",
    ]
    if best:
        parts.append(f"最明显的变化在{best.label}，从{best.before}到{best.after}，说明这一环节有进步信号。")
    if metric:
        parts.append(f"量化指标里，{metric.label}提升了{metric.delta}{metric.unit or ''}，可以作为本次动作改变的客观参考。")
    if summary.improved:
        parts.append(f"之前的“{summary.improved[0].category}”问题这次有所改善。")
    if summary.added:
        parts.append(f"同时也出现或加重了“{summary.added[0].category}”，下次训练仍要重点观察。")
    parts.append("建议把这次对比作为趋势参考，继续结合教练现场观察和稳定拍摄角度复盘。")
    return "".join(parts)


async def _build_ai_compare_narrative(
    *,
    analysis_a: Analysis,
    analysis_b: Analysis,
    score_delta: int,
    subscore_deltas: list[CompareDelta],
    metric_deltas: list[CompareDelta],
    summary: CompareSummary,
    quality: CompareQualityPayload,
    local_only: bool = False,
) -> str:
    fallback = _fallback_compare_narrative(
        analysis_a=analysis_a,
        analysis_b=analysis_b,
        score_delta=score_delta,
        subscore_deltas=subscore_deltas,
        metric_deltas=metric_deltas,
        summary=summary,
    )
    if local_only:
        return fallback
    try:
        provider = await get_active_provider("report")
        payload = {
            "action_type": analysis_b.action_type,
            "action_subtype": analysis_b.action_subtype,
            "score_delta": score_delta,
            "subscores": [item.model_dump() for item in subscore_deltas],
            "metrics": [item.model_dump() for item in metric_deltas],
            "summary": summary.model_dump(),
            "quality": quality.model_dump(),
        }
        raw = await request_text_completion(
            provider,
            temperature=0.2,
            max_tokens=420,
            timeout=45,
            messages=[
                {"role": "system", "content": COMPARE_NARRATIVE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "请基于以下结构化差异，写3-5句家长可读的进步解读。"
                        "不要夸大低质量数据；不要声称重新看过视频；包含一个下一次训练重点。"
                        "如果 score_delta 很小或 quality.needs_human_review=true，请把结论写成谨慎观察。\n"
                        f"{json.dumps(payload, ensure_ascii=False)}"
                    ),
                },
            ],
        )
        cleaned = raw.strip()
        return cleaned[:600] if cleaned else fallback
    except Exception:  # noqa: BLE001
        logger.info("Compare AI narrative unavailable, using fallback.", exc_info=True)
        return fallback


def _can_compare_same_subtype(analysis_a: Analysis, analysis_b: Analysis) -> bool:
    subtype_a = _normalize_optional_text(analysis_a.action_subtype)
    subtype_b = _normalize_optional_text(analysis_b.action_subtype)
    if subtype_a or subtype_b:
        return subtype_a == subtype_b
    skill_a = _normalize_optional_text(analysis_a.skill_node_id)
    skill_b = _normalize_optional_text(analysis_b.skill_node_id)
    return bool(skill_a and skill_a == skill_b)


def _ordered_compare_pair(analysis_a: Analysis, analysis_b: Analysis) -> tuple[Analysis, Analysis]:
    if analysis_a.created_at <= analysis_b.created_at:
        return analysis_a, analysis_b
    return analysis_b, analysis_a


def _plan_detail_from_model(plan: TrainingPlan) -> TrainingPlanDetail:
    return TrainingPlanDetail(
        id=plan.id,
        analysis_id=plan.analysis_id,
        skater_id=plan.skater_id,
        plan_json=plan.plan_json,
        created_at=plan.created_at,
    )


def _skater_context(skater: Skater) -> str:
    parts = [f"姓名：{_skater_display_name(skater)}"]
    if skater.birth_year:
        current_year = datetime.now(timezone.utc).year
        age = max(current_year - int(skater.birth_year), 0)
        parts.append(f"年龄：约{age}岁")
    if skater.current_level:
        parts.append(f"当前阶段：{skater.current_level}")
    if skater.level:
        parts.append(f"水平：{skater.level}")
    if skater.notes:
        parts.append(f"备注：{skater.notes}")
    return "；".join(parts)


async def _get_plan_by_analysis(session: AsyncSession, analysis_id: str) -> TrainingPlan | None:
    result = await session.execute(select(TrainingPlan).where(TrainingPlan.analysis_id == analysis_id).limit(1))
    return result.scalar_one_or_none()


async def _get_latest_plan_for_skater(session: AsyncSession, skater_id: str) -> TrainingPlan | None:
    result = await session.execute(
        select(TrainingPlan)
        .where(TrainingPlan.skater_id == skater_id)
        .order_by(TrainingPlan.created_at.desc(), TrainingPlan.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _verify_parent_pin_or_403(session: AsyncSession, pin: str) -> None:
    try:
        normalized_pin = validate_pin(pin)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    auth = await get_parent_auth(session)
    if auth is None or not verify_pin_hash(normalized_pin, auth.pin_hash):
        raise HTTPException(status_code=403, detail="家长 PIN 验证失败。")


@router.post("/upload", response_model=AnalysisUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_analysis(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    action_type: str = Form(...),
    action_subtype: str | None = Form(default=None),
    skater_id: str | None = Form(default=None),
    skill_node_id: str | None = Form(default=None),
    skill_category: str | None = Form(default=None),
    note: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    manual_action_window_start_sec: float | None = Form(default=None),
    manual_action_window_end_sec: float | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> AnalysisUploadResponse:
    if action_type not in VALID_ACTION_TYPES:
        raise HTTPException(status_code=400, detail="action_type 必须是 跳跃 / 旋转 / 步法 / 自由滑 之一。")

    skater = await _resolve_skater(session, skater_id)
    normalized_session_id = _normalize_optional_text(session_id)
    training_session = None
    if normalized_session_id:
        training_session = await session.get(TrainingSession, normalized_session_id)
        if training_session is None:
            raise HTTPException(status_code=404, detail="未找到对应的训练课次。")
        if skater and training_session.skater_id != skater.id:
            raise HTTPException(status_code=400, detail="训练视频只能关联到当前档案的训练课次。")

    analysis_id = str(uuid4())
    suffix = Path(file.filename or "").suffix.lower()
    video_path, _ = build_upload_paths(analysis_id, suffix)

    try:
        await save_upload_file(file, video_path)
        await precheck_video(video_path)
        video_identity = _video_identity_payload(video_path, await asyncio.to_thread(compute_video_sha256, video_path))
        manual_window = build_video_input_window(
            video_path,
            manual_start_sec=manual_action_window_start_sec,
            manual_end_sec=manual_action_window_end_sec,
        )
    except AnalysisPipelineError as exc:
        video_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail={"code": exc.code.value, "message": exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_action_subtype = normalize_action_subtype(action_type, action_subtype)
    inferred_input_profile = _initial_analysis_profile(action_type, normalized_action_subtype)

    analysis = Analysis(
        id=analysis_id,
        skater_id=skater.id if skater else None,
        session_id=training_session.id if training_session else None,
        skill_node_id=_normalize_optional_text(skill_node_id),
        skill_category=_normalize_optional_text(skill_category),
        action_type=action_type,
        action_subtype=normalized_action_subtype,
        analysis_profile=inferred_input_profile,
        pipeline_version=CURRENT_PIPELINE_VERSION,
        video_path=str(video_path),
        frame_motion_scores={"video_identity": video_identity},
        manual_action_window_start=manual_window.input_window_start_sec if manual_window.input_window_mode == "manual_window" else None,
        manual_action_window_end=manual_window.input_window_end_sec if manual_window.input_window_mode == "manual_window" else None,
        note=_normalize_optional_text(note),
        status="pending",
        processing_timings=None,
        retry_from_stage=None,
        target_lock_status="pending",
    )
    session.add(analysis)
    await session.commit()

    background_tasks.add_task(process_analysis, analysis_id)
    return AnalysisUploadResponse(id=analysis_id, status="pending")


@router.patch("/{analysis_id}/session", response_model=AnalysisDetail)
async def update_analysis_session(
    analysis_id: str,
    payload: AnalysisSessionUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> AnalysisDetail:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    next_session_id = payload.session_id
    if next_session_id is None:
        analysis.session_id = None
    else:
        training_session = await session.get(TrainingSession, next_session_id)
        if training_session is None:
            raise HTTPException(status_code=404, detail="未找到对应的训练课次。")
        if analysis.skater_id and training_session.skater_id != analysis.skater_id:
            raise HTTPException(status_code=400, detail="只能关联到同一档案下的训练课次。")
        analysis.session_id = training_session.id

    await session.commit()
    await session.refresh(analysis)

    skater_name = None
    if analysis.skater_id:
        skater = await session.get(Skater, analysis.skater_id)
        skater_name = _skater_display_name(skater) if skater else None
    return _detail_from_analysis(analysis, skater_name)


@router.get("/", response_model=list[AnalysisListItem])
async def list_analyses(
    action_type: str | None = Query(default=None),
    skater_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[AnalysisListItem]:
    query = (
        select(Analysis)
        .options(
            load_only(
                Analysis.id,
                Analysis.skater_id,
                Analysis.session_id,
                Analysis.skill_category,
                Analysis.action_type,
                Analysis.action_subtype,
                Analysis.analysis_profile,
                Analysis.pipeline_version,
                Analysis.status,
                Analysis.force_score,
                Analysis.note,
                Analysis.created_at,
                Analysis.updated_at,
                Analysis.retry_from_stage,
                Analysis.processing_logs,
            )
        )
        .order_by(Analysis.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if action_type:
        query = query.where(Analysis.action_type == action_type)
    if skater_id:
        query = query.where(Analysis.skater_id == skater_id)

    result = await run_db_read_with_retry(
        lambda: session.execute(query),
        context="list_analyses",
    )
    analyses = await _recover_stale_analyses(session, list(result.scalars().all()))
    skater_map = await _get_skater_map(session, {analysis.skater_id for analysis in analyses if analysis.skater_id})
    return [
        _list_item_from_analysis(
            analysis,
            _skater_display_name(skater_map[analysis.skater_id]) if analysis.skater_id in skater_map else None,
        )
        for analysis in analyses
    ]


@router.get("/compare", response_model=AnalysisCompareResponse)
async def compare_analyses(
    id_a: str = Query(...),
    id_b: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> AnalysisCompareResponse:
    analysis_a = await session.get(Analysis, id_a)
    analysis_b = await session.get(Analysis, id_b)

    if analysis_a is None or analysis_b is None:
        raise HTTPException(status_code=404, detail="至少有一条对比记录不存在。")
    if analysis_a.status != "completed" or analysis_b.status != "completed":
        raise HTTPException(status_code=400, detail="只有 completed 状态的记录可以进行对比。")
    if analysis_a.skater_id != analysis_b.skater_id:
        raise HTTPException(status_code=400, detail="只能比较同一位小朋友的训练记录。")
    if analysis_a.action_type != analysis_b.action_type:
        raise HTTPException(status_code=400, detail="仅支持同动作类型的复盘记录对比。")
    if not _can_compare_same_subtype(analysis_a, analysis_b):
        raise HTTPException(status_code=400, detail="请只选择同一动作小项或同一技能节点的记录进行对比。")

    analysis_a, analysis_b = _ordered_compare_pair(analysis_a, analysis_b)

    skater_map = await _get_skater_map(
        session,
        {analysis.skater_id for analysis in (analysis_a, analysis_b) if analysis.skater_id},
    )
    score_delta = (analysis_b.force_score or 0) - (analysis_a.force_score or 0)
    subscore_deltas = _build_subscore_deltas(analysis_a, analysis_b)
    metric_deltas = _build_metric_deltas(analysis_a, analysis_b)
    keyframe_compare = _build_keyframe_compare(analysis_a, analysis_b)
    video_compare = _build_video_compare(analysis_a, analysis_b)
    quality = _build_compare_quality(analysis_a, analysis_b)
    summary = _compare_reports(
        analysis_a.report if isinstance(analysis_a.report, dict) else None,
        analysis_b.report if isinstance(analysis_b.report, dict) else None,
    )
    same_video_core_stable = _same_video_core_compare_stable(
        analysis_a,
        analysis_b,
        score_delta=score_delta,
        subscore_deltas=subscore_deltas,
        metric_deltas=metric_deltas,
        keyframe_compare=keyframe_compare,
    )
    if same_video_core_stable:
        summary = _stabilize_same_video_compare_summary(summary)
        quality.warnings.append("同一原视频重复分析的关键帧和评分稳定；报告问题分类差异已按重复分析噪声处理。")
    ai_narrative = await _build_ai_compare_narrative(
        analysis_a=analysis_a,
        analysis_b=analysis_b,
        score_delta=score_delta,
        subscore_deltas=subscore_deltas,
        metric_deltas=metric_deltas,
        summary=summary,
        quality=quality,
        local_only=same_video_core_stable,
    )

    return AnalysisCompareResponse(
        analysis_a=_detail_from_analysis(
            analysis_a,
            _skater_display_name(skater_map[analysis_a.skater_id]) if analysis_a.skater_id in skater_map else None,
        ),
        analysis_b=_detail_from_analysis(
            analysis_b,
            _skater_display_name(skater_map[analysis_b.skater_id]) if analysis_b.skater_id in skater_map else None,
        ),
        score_delta=score_delta,
        summary=summary,
        subscore_deltas=subscore_deltas,
        metric_deltas=metric_deltas,
        keyframe_compare=keyframe_compare,
        video_compare=video_compare,
        quality=quality,
        ai_narrative=ai_narrative,
    )


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(
    action_type: str | None = Query(default=None),
    skater_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> ProgressResponse:
    query = (
        select(Analysis)
        .where(Analysis.status == "completed", Analysis.force_score.is_not(None))
        .order_by(Analysis.created_at.asc())
    )
    if action_type:
        query = query.where(Analysis.action_type == action_type)
    if skater_id:
        query = query.where(Analysis.skater_id == skater_id)

    result = await session.execute(query)
    analyses = list(result.scalars().all())

    points = [
        ProgressPoint(
            id=analysis.id,
            created_at=_coerce_utc_datetime(analysis.created_at) or analysis.created_at,
            action_type=analysis.action_type,
            force_score=analysis.force_score or 0,
            summary=_report_summary(analysis),
        )
        for analysis in analyses
    ]
    recent_scores = [analysis.force_score or 0 for analysis in analyses[-5:]]
    stats = ProgressStats(
        total_count=len(analyses),
        latest_score=analyses[-1].force_score if analyses else None,
        best_score=max((analysis.force_score or 0 for analysis in analyses), default=None),
        recent_five_average=round(mean(recent_scores), 1) if recent_scores else None,
    )
    return ProgressResponse(points=points, stats=stats)


@router.get("/auto-eval/snapshots", response_model=list[AnalysisAutoEvalSnapshot])
async def list_auto_eval_snapshots(
    limit: int = Query(default=50, ge=1, le=500),
    analysis_profile: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[AnalysisAutoEvalSnapshot]:
    limit_value = limit if isinstance(limit, int) else 50
    analysis_profile_value = analysis_profile if isinstance(analysis_profile, str) and analysis_profile.strip() else None
    action_type_value = action_type if isinstance(action_type, str) and action_type.strip() else None

    query = select(Analysis).where(Analysis.status == "completed")
    if analysis_profile_value:
        query = query.where(Analysis.analysis_profile == analysis_profile_value)
    if action_type_value:
        query = query.where(Analysis.action_type == action_type_value)
    query = query.order_by(Analysis.created_at.desc()).limit(limit_value)

    result = await session.execute(query)
    analyses = list(result.scalars().all())
    return [_auto_eval_snapshot_from_analysis(analysis) for analysis in analyses]


@router.post("/{analysis_id}/plan", response_model=TrainingPlanDetail)
async def create_training_plan(
    analysis_id: str,
    force: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> TrainingPlanDetail:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")
    if analysis.status != "completed":
        raise HTTPException(status_code=400, detail="只有 completed 状态的分析才能生成训练计划。")
    if not isinstance(analysis.report, dict):
        raise HTTPException(status_code=400, detail="当前分析缺少结构化报告，无法生成训练计划。")

    existing_plan = await _get_plan_by_analysis(session, analysis_id)
    if existing_plan is not None and not force:
        return _plan_detail_from_model(existing_plan)

    skater = await _resolve_skater(session, analysis.skater_id)
    if skater is None:
        raise HTTPException(status_code=400, detail="当前系统尚未配置练习档案。")

    if analysis.skater_id != skater.id:
        analysis.skater_id = skater.id

    try:
        plan_json = await generate_training_plan(
            analysis.action_type,
            analysis.report,
            _skater_context(skater),
            skater.id,
            variation_key=f"{analysis.id}:{datetime.now(timezone.utc).isoformat()}",
        )
    except PlanGenerationError as exc:
        logger.warning("Analysis %s training plan AI failed, using fallback plan: %s", analysis_id, exc)
        plan_json = build_fallback_plan(analysis.action_type, analysis.report, _skater_context(skater))
        plan_json["generation_source"] = "fallback"
        plan_json["generation_note"] = f"AI 训练计划暂不可用，已生成安全兜底计划：{exc}"

    if existing_plan is not None:
        existing_plan.plan_json = plan_json
        await session.commit()
        await session.refresh(existing_plan)
        return _plan_detail_from_model(existing_plan)

    plan = TrainingPlan(
        analysis_id=analysis.id,
        skater_id=skater.id,
        plan_json=plan_json,
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return _plan_detail_from_model(plan)


@router.get("/{analysis_id}/plan", response_model=TrainingPlanDetail)
async def get_analysis_plan(analysis_id: str, session: AsyncSession = Depends(get_session)) -> TrainingPlanDetail:
    plan = await _get_plan_by_analysis(session, analysis_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="该分析记录尚未生成训练计划。")
    return _plan_detail_from_model(plan)


@router.get("/{analysis_id}/pose", response_model=PoseResponse)
async def get_analysis_pose(analysis_id: str, session: AsyncSession = Depends(get_session)) -> PoseResponse:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    analysis = _build_stale_analysis_snapshot(analysis) or analysis
    if analysis.status != "awaiting_target_selection":
        analysis = await _ensure_phase3_artifacts(session, analysis)
    return _build_pose_response(analysis_id, analysis.pose_data)


@router.get("/{analysis_id}/video")
async def get_analysis_video(analysis_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")
    video_path = _safe_video_response_path(analysis)
    if video_path is None:
        raise HTTPException(status_code=404, detail="原视频已清理或不可用。")
    return FileResponse(
        video_path,
        media_type=_video_media_type(video_path),
        filename=video_path.name,
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/{analysis_id}", response_model=AnalysisDetail)
async def get_analysis(
    analysis_id: str,
    is_parent_request: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> AnalysisDetail:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    analysis = _build_stale_analysis_snapshot(analysis) or analysis
    if analysis.status != "awaiting_target_selection":
        analysis = await _ensure_phase3_artifacts(session, analysis)
    skater_name = None
    if analysis.skater_id:
        skater = await session.get(Skater, analysis.skater_id)
        skater_name = _skater_display_name(skater) if skater else None
    return _detail_from_analysis(analysis, skater_name, include_error_detail=is_parent_request)


@router.post("/{analysis_id}/export", response_class=PlainTextResponse)
async def export_analysis_text(analysis_id: str, session: AsyncSession = Depends(get_session)) -> PlainTextResponse:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")
    if analysis.status != "completed":
        raise HTTPException(status_code=400, detail="只有 completed 状态的分析才能导出报告。")

    skater_name = None
    if analysis.skater_id:
        skater = await session.get(Skater, analysis.skater_id)
        skater_name = _skater_display_name(skater) if skater else None

    training_session = await session.get(TrainingSession, analysis.session_id) if analysis.session_id else None
    session_date = training_session.session_date.isoformat() if training_session else None
    return PlainTextResponse(_build_export_text(analysis, skater_name, session_date))


@router.post("/{analysis_id}/retry", response_model=AnalysisRetryResponse)
async def retry_analysis(
    analysis_id: str,
    background_tasks: BackgroundTasks,
    retry_from: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> AnalysisRetryResponse:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    stale_snapshot = _build_stale_analysis_snapshot(analysis)
    if stale_snapshot is not None:
        analysis.status = "failed"
        analysis.retry_from_stage = stale_snapshot.retry_from_stage
        analysis.error_code = stale_snapshot.error_code
        analysis.error_message = stale_snapshot.error_message
        analysis.error_detail = stale_snapshot.error_detail
        analysis.processing_logs = stale_snapshot.processing_logs
        await session.commit()
        await session.refresh(analysis)

    if analysis.status == "awaiting_target_selection":
        await _resume_auto_target_lock_if_available(analysis, session)

    if analysis.status in {"pending", "processing", "extracting_frames", "awaiting_target_selection", "analyzing", "generating_report"}:
        raise HTTPException(status_code=400, detail="当前分析仍在进行中，请完成或失败后再重试。")

    if retry_from is not None and not _is_retry_stage(retry_from):
        raise HTTPException(status_code=400, detail="retry_from 必须是 extract_frames / pose / biomechanics / vision / report 之一。")

    retry_from_stage = retry_from or analysis.retry_from_stage or _default_retry_stage_for_error(analysis.error_code)
    if retry_from_stage == 'pose' and not isinstance(analysis.frame_motion_scores, dict):
        retry_from_stage = None
    if retry_from_stage == 'biomechanics' and not isinstance(analysis.pose_data, dict):
        retry_from_stage = None
    if retry_from_stage == 'vision' and (not isinstance(analysis.pose_data, dict) or not isinstance(analysis.bio_data, dict)):
        retry_from_stage = None
    if retry_from_stage == 'report' and not isinstance(analysis.vision_structured, dict):
        retry_from_stage = 'vision' if isinstance(analysis.pose_data, dict) and isinstance(analysis.bio_data, dict) else None
    if retry_from_stage == 'report' and not isinstance(analysis.bio_data, dict):
        retry_from_stage = 'vision' if isinstance(analysis.pose_data, dict) else None

    upload_dir = UPLOADS_DIR / analysis_id
    source_video_path = (
        next(
            (path for path in upload_dir.iterdir() if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}),
            None,
        )
        if upload_dir.exists()
        else None
    )
    if source_video_path is None and retry_from_stage != 'report':
        raise HTTPException(status_code=404, detail="原始视频已清理或不可用，无法重新分析。")

    analysis.status = "pending"
    analysis.error_code = None
    analysis.error_detail = None
    analysis.error_message = None
    analysis.processing_timings = None
    analysis.pipeline_version = CURRENT_PIPELINE_VERSION
    analysis.retry_from_stage = retry_from_stage
    if retry_from_stage in {None, 'extract_frames', 'pose'} and not _is_confirmed_target_lock(analysis.target_lock):
        analysis.target_lock_status = 'pending'
    analysis.updated_at = datetime.now(timezone.utc)
    await session.commit()

    background_tasks.add_task(process_analysis, analysis_id, retry_from_stage)
    if retry_from_stage:
        return AnalysisRetryResponse(message=f"已从 {retry_from_stage} 阶段重新提交分析。")
    return AnalysisRetryResponse(message="已重新提交分析。")


@router.get("/{analysis_id}/target-preview", response_model=TargetPreviewResponse)
@router.get("/{analysis_id}/target_preview", response_model=TargetPreviewResponse)
async def get_target_preview(analysis_id: str, session: AsyncSession = Depends(get_session)) -> TargetPreviewResponse:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    frames_dir = _frames_dir_for_analysis(analysis)
    frame_names = frame_names_from_dir(frames_dir)
    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
    preview = build_target_preview(
        analysis_id,
        frame_names,
        existing_target_lock=analysis.target_lock,
        motion_scores=motion_scores,
        analysis_profile=analysis.analysis_profile,
        detected_candidates=_target_preview_detected_candidates_from_frames(frames_dir, frame_names, motion_scores),
    )
    return TargetPreviewResponse(
        analysis_id=analysis.id,
        status=analysis.status,
        auto_candidate_id=preview.auto_candidate_id,
        lock_confidence=preview.lock_confidence,
        preview_frame=preview.preview_frame,
        preview_frame_url=preview.preview_frame_url,
        preview_frame_index=preview.preview_frame_index,
        candidates=preview.candidates,
        target_lock_status=preview.target_lock_status,
    )


@router.post("/{analysis_id}/target-lock", response_model=AnalysisDetail)
@router.post("/{analysis_id}/target_lock", response_model=AnalysisDetail)
async def confirm_target_lock(
    analysis_id: str,
    payload: TargetLockRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> AnalysisDetail:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    frames_dir = _frames_dir_for_analysis(analysis)
    frame_names = frame_names_from_dir(frames_dir)
    motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
    preview = build_target_preview(
        analysis_id,
        frame_names,
        existing_target_lock=analysis.target_lock,
        motion_scores=motion_scores,
        analysis_profile=analysis.analysis_profile,
        detected_candidates=_target_preview_detected_candidates_from_frames(frames_dir, frame_names, motion_scores),
    )
    try:
        selected = None if payload.manual_bbox is not None else resolve_manual_candidate(preview.candidates, payload.candidate_id, payload.x, payload.y)
        if selected is None and payload.manual_bbox is None:
            raise HTTPException(status_code=400, detail="Unable to resolve target skater; please select again.")

        analysis.target_lock = (
            build_target_lock_payload(preview, manual_bbox=payload.manual_bbox.model_dump())
            if payload.manual_bbox is not None
            else build_target_lock_payload(preview, selected_candidate=selected, manual=True)
        )
    except AnalysisPipelineError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    analysis.target_lock_status = str(analysis.target_lock.get("status") or "locked")
    analysis.retry_from_stage = None
    analysis.status = "pending"
    analysis.updated_at = datetime.now(timezone.utc)
    await session.commit()

    background_tasks.add_task(process_analysis, analysis_id)

    skater_name = None
    if analysis.skater_id:
        skater = await session.get(Skater, analysis.skater_id)
        skater_name = _skater_display_name(skater) if skater else None
    return _detail_from_analysis(analysis, skater_name)


@router.patch("/{analysis_id}/note", response_model=AnalysisDetail)
async def update_note(
    analysis_id: str,
    payload: NoteUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> AnalysisDetail:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    analysis.note = _normalize_optional_text(payload.note)
    analysis.report = _sync_report_user_note(
        analysis.report if isinstance(analysis.report, dict) else None,
        analysis.note,
    )
    await session.commit()
    await session.refresh(analysis)

    skater_name = None
    if analysis.skater_id:
        skater = await session.get(Skater, analysis.skater_id)
        skater_name = _skater_display_name(skater) if skater else None
    return _detail_from_analysis(analysis, skater_name)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(
    analysis_id: str,
    x_parent_pin: str = Header(..., alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _verify_parent_pin_or_403(session, x_parent_pin)

    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")
    if analysis.status == "processing":
        raise HTTPException(status_code=400, detail="分析进行中，无法删除。")

    skater_id = analysis.skater_id
    plan = await _get_plan_by_analysis(session, analysis_id)
    if plan is not None:
        await session.delete(plan)

    upload_dir = UPLOADS_DIR / analysis_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)

    await session.delete(analysis)
    await session.flush()

    if skater_id:
        await sync_skater_progress(session, skater_id)

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@plan_router.get("/skater/{skater_id}/latest", response_model=TrainingPlanDetail)
async def get_latest_skater_plan(skater_id: str, session: AsyncSession = Depends(get_session)) -> TrainingPlanDetail:
    plan = await _get_latest_plan_for_skater(session, skater_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="No training plan found for this skater.")
    return _plan_detail_from_model(plan)


@plan_router.get("/{plan_id}", response_model=TrainingPlanDetail)
async def get_plan(plan_id: str, session: AsyncSession = Depends(get_session)) -> TrainingPlanDetail:
    plan = await session.get(TrainingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="未找到该训练计划。")
    return _plan_detail_from_model(plan)


@plan_router.patch("/{plan_id}/session/{session_id}", response_model=TrainingPlanDetail)
async def update_plan_session(
    plan_id: str,
    session_id: str,
    payload: UpdatePlanSessionRequest,
    session: AsyncSession = Depends(get_session),
) -> TrainingPlanDetail:
    plan = await session.get(TrainingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="未找到该训练计划。")

    raw_plan = plan.plan_json if isinstance(plan.plan_json, dict) else {}
    days = raw_plan.get("days", [])
    found = False
    next_days: list[dict[str, object]] = []

    for raw_day in days:
        if not isinstance(raw_day, dict):
            continue
        sessions: list[dict[str, object]] = []
        for raw_session in raw_day.get("sessions", []):
            if not isinstance(raw_session, dict):
                continue
            session_payload = dict(raw_session)
            if str(session_payload.get("id")) == session_id:
                session_payload["completed"] = payload.completed
                found = True
            sessions.append(session_payload)

        next_day = dict(raw_day)
        next_day["sessions"] = sessions
        next_days.append(next_day)

    if not found:
        raise HTTPException(status_code=404, detail="未找到对应的训练项目。")

    plan.plan_json = {**raw_plan, "days": next_days}
    await session.commit()
    await session.refresh(plan)
    return _plan_detail_from_model(plan)


@plan_router.post("/{plan_id}/extend", response_model=TrainingPlanDetail)
async def extend_plan(
    plan_id: str,
    payload: ExtendPlanBody,
    session: AsyncSession = Depends(get_session),
) -> TrainingPlanDetail:
    plan = await session.get(TrainingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="未找到该训练计划。")

    analysis = await session.get(Analysis, plan.analysis_id)
    if analysis is None or not isinstance(analysis.report, dict):
        raise HTTPException(status_code=400, detail="当前计划缺少原始分析背景，无法续期。")

    skater = await session.get(Skater, plan.skater_id)
    completed_days = sorted({day for day in payload.completed_days if 1 <= day <= 7})
    if len(completed_days) < 3:
        raise HTTPException(status_code=400, detail="至少完成 3 天后才能续期计划。")

    try:
        plan.plan_json = await extend_training_plan(
            original_plan=plan.plan_json if isinstance(plan.plan_json, dict) else {},
            completed_days=completed_days,
            action_type=analysis.action_type,
            report=analysis.report,
            skater_context=_skater_context(skater) if skater else None,
            skater_id=skater.id if skater else None,
        )
    except PlanGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(plan)
    return _plan_detail_from_model(plan)


@frames_router.get("/{analysis_id}/{filename}")
async def get_frame(analysis_id: str, filename: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    if not (
        filename.startswith("frame_")
        or filename.startswith("semantic_")
        or filename.startswith("partial_semantic_")
    ) or not filename.endswith(".jpg"):
        raise HTTPException(status_code=400, detail="无效的帧文件名。")

    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    analysis, restored_frames_dir = await _restore_missing_analysis_frames(session, analysis)
    frames_dir = restored_frames_dir.resolve() if restored_frames_dir.exists() else (UPLOADS_DIR / analysis_id / "frames").resolve()
    semantic_dir = (UPLOADS_DIR / analysis_id / "semantic_frames").resolve()
    frames_root = (
        semantic_dir
        if (filename.startswith("semantic_") or filename.startswith("partial_semantic_")) and semantic_dir.exists()
        else frames_dir
    )
    frame_path = (frames_root / filename).resolve()
    if frames_root not in frame_path.parents or not frame_path.exists():
        raise HTTPException(status_code=404, detail="未找到该视频帧。")

    return FileResponse(frame_path, media_type="image/jpeg")
