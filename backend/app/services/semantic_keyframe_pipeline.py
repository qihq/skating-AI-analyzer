from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.person_tracker import detect_person_candidates
from app.services.video import (
    VideoInputWindow,
    VideoSamplingMetadata,
    build_video_input_window,
    cut_action_window_ai_clip,
    detect_video_duration,
    detect_video_fps,
    extract_precise_frames_at_timestamps,
    precheck_video,
    refine_semantic_keyframe_timestamps,
)
from app.services.video_temporal import (
    SPIN_PHASE_CODES,
    SPIRAL_PHASE_CODES,
    STEP_PHASE_CODES,
    _fallback_skeleton_selected,
    _jump_motion_cluster_fallback_selected,
    _motion_records_from_scores as _resolver_motion_records_from_scores,
    _skeleton_candidates,
    analyze_video_temporal,
    resolve_semantic_keyframes,
    semantic_keyframes_are_reliable,
)

SemanticPipelineProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
CORE_SEMANTIC_PHASES = {"takeoff", "air", "landing"}
NON_JUMP_PARTIAL_PHASE_CODES = SPIN_PHASE_CODES | SPIRAL_PHASE_CODES | STEP_PHASE_CODES
FOREGROUND_OCCLUDER_MIN_AREA = 0.08
FOREGROUND_OCCLUDER_AREA_RATIO = 5.0
FOREGROUND_OCCLUDER_MIN_OVERLAP = 0.25
SEMANTIC_TARGET_MIN_AREA = 0.006
SEMANTIC_ZOOMED_TARGET_MIN_AREA = 0.002
SEMANTIC_TARGET_MAX_AREA = 0.04
SEMANTIC_TARGET_CONTEXT_AREA_MULTIPLIER = 4.0
SEMANTIC_TARGET_CONTEXT_MIN_FRAMES = 2
SEMANTIC_OCCLUSION_REPAIR_MAX_DELTA_SEC = 0.35
SEMANTIC_OCCLUSION_REPAIR_REFINED_LANDING_MAX_DELTA_SEC = 0.18
SEMANTIC_OCCLUSION_REPAIR_MIN_GAP_SEC = 0.02
SEMANTIC_OCCLUSION_REPAIR_CORE_MIN_GAP_SEC = 0.12
SEMANTIC_OCCLUSION_REPAIR_APEX_LANDING_MIN_GAP_SEC = 0.15
SEMANTIC_OCCLUSION_REPAIR_MAX_CANDIDATES = 18
SEMANTIC_OCCLUSION_REPAIR_LANDING_DISTANCE_PENALTY_MULTIPLIER = 3.2
VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_FLOOR = 0.35
VIDEO_TEMPORAL_RETRY_TRIGGER_FLAGS = {
    "video_temporal_quality_retry_motion_cluster_conflict",
    "video_temporal_quality_retry_skeleton_tal_conflict",
    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
    "semantic_keyframe_core_foreground_occlusion_repaired",
    "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
    "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
    "semantic_keyframes_unreliable_candidate_motion_window_conflict",
    "semantic_keyframes_unreliable_candidate_takeoff_single_conflict",
    "semantic_keyframes_unreliable_candidate_early_takeoff_conflict",
    "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
    "semantic_keyframes_unreliable_after_refinement",
    "semantic_keyframes_unreliable_after_visibility_check",
    "video_temporal_missing_phase_segments",
    "video_temporal_missing_core_tal",
    "video_temporal_resolver_no_semantic_selection",
    "video_temporal_resolver_partial_skeleton_fallback",
    "video_temporal_resolver_advisory_fallback_overridden",
    "video_temporal_low_confidence_retryable",
    "video_temporal_profile_mismatch_retryable",
    "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
}
VIDEO_TEMPORAL_RETRY_HARD_FAILURE_FLAGS = {
    "video_temporal_invalid_json",
    "video_temporal_parse_failed",
    "video_temporal_payload_not_object",
    "video_temporal_timeout",
    "video_temporal_budget_exceeded",
    "video_temporal_auth_error",
    "video_temporal_provider_error",
    "video_temporal_provider_not_qwen",
}
VIDEO_TEMPORAL_RETRY_LATE_DRIFT_MIN_SECONDS = 0.30
VIDEO_TEMPORAL_RETRY_LATE_DRIFT_LANDING_MIN_SECONDS = 0.45
VIDEO_TEMPORAL_RETRY_EARLY_DRIFT_MIN_SECONDS = 0.18
VIDEO_TEMPORAL_RETRY_EARLY_DRIFT_LANDING_MIN_SECONDS = 0.18
VIDEO_TEMPORAL_RETRY_CORE_MIN_GAP_SECONDS = 0.10
VIDEO_TEMPORAL_RETRY_COMPRESSED_CORE_MAX_SECONDS = 0.55
VIDEO_TEMPORAL_RETRY_COMPRESSED_EARLY_SHIFT_SECONDS = 0.25
VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_LAG_SECONDS = 0.25
VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_MIN_SCORE = 0.12
VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_RATIO = 2.4
VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_COUNT = 3
VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_TAKEOFF_LEAD_SECONDS = 0.55
VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_APEX_LEAD_SECONDS = 0.30
VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_LANDING_TOLERANCE_SECONDS = 0.18
VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_PEAK_LAG_SECONDS = 0.20
VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_MIN_SPAN_SECONDS = 0.25
VIDEO_TEMPORAL_RETRY_TAKEOFF_PARTIAL_MIN_SHIFT_SECONDS = 0.25
VIDEO_TEMPORAL_RETRY_TAKEOFF_PARTIAL_MAX_SHIFT_SECONDS = 0.75
VIDEO_TEMPORAL_RETRY_TAKEOFF_PARTIAL_APEX_TOLERANCE_SECONDS = 0.25
VIDEO_TEMPORAL_RETRY_TAKEOFF_PARTIAL_LANDING_TOLERANCE_SECONDS = 0.35
VIDEO_TEMPORAL_RETRY_SKELETON_CONFLICT_MIN_CONFIDENCE = 0.62
VIDEO_TEMPORAL_RETRY_SKELETON_CONFLICT_MIN_DELTA_SEC = 0.25
VIDEO_TEMPORAL_RETRY_SKELETON_CONFLICT_STRONG_DELTA_SEC = 0.45
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_MIN_SCORE = 0.12
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_RATIO = 0.70
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_TOLERANCE_SEC = 0.25
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_PEAK_RATIO = 0.50
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_MAX_DELTA_SEC = 0.12
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_AVG_CONFIDENCE = 0.50
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_STRONG_CONFIDENCE = 0.62
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_BOUNDARY_APEX_MAX_CONFIDENCE = 0.52
VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_BOUNDARY_APEX_TRAIL_TOLERANCE_SEC = 0.20
VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_MIN_SECONDS = 0.75
VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_MAX_CONFIDENCE = 0.72
VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_REFINEMENT_MAX_SCORE = 0.025
VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_CORE_MOTION_MAX_SCORE = 0.035
VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_CORE_MOTION_RATIO = 0.50
SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_SHIFT_SECONDS = 0.75
SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_KEYS = 2
SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_CONFIDENCE = 0.45
SEMANTIC_CANDIDATE_MOTION_WINDOW_MIN_CONFLICT_KEYS = 2
SEMANTIC_CANDIDATE_MOTION_WINDOW_TOLERANCE_SECONDS = 0.25
SEMANTIC_CANDIDATE_MOTION_WINDOW_MIN_GLOBAL_PEAK = 0.035
SEMANTIC_CANDIDATE_MOTION_WINDOW_CANDIDATE_PEAK_RATIO = 0.55
SEMANTIC_CANDIDATE_MOTION_WINDOW_SEMANTIC_PEAK_RATIO = 0.50
SEMANTIC_CANDIDATE_MOTION_WINDOW_MIN_CANDIDATE_TO_SEMANTIC_RATIO = 1.20
SEMANTIC_CANDIDATE_MOTION_WINDOW_MIN_CANDIDATE_TO_SEMANTIC_DELTA = 0.012
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MAX_PEAK = 0.10
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MIN_SEMANTIC_PEAK_RATIO = 0.65
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MAX_BOUNDARY_AVG_CONFIDENCE = 0.52
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MAX_BOUNDARY_CONFIDENCE = 0.61
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_SEMANTIC_CONFIDENCE = 0.85
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_SEMANTIC_CONFIDENCE = 0.70
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_MIN_SEMANTIC_PEAK_RATIO = 0.25
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_MIN_SEMANTIC_SPAN_SEC = 0.55
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_MAX_BOUNDARY_CONFIDENCE = 0.62
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_UNRELIABLE_POSE_MAX_BOUNDARY_CONFIDENCE = 0.66
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_LATE_MAIN_PEAK_MIN_LAG_SEC = 0.75
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_LATE_MAIN_PEAK_MIN_RATIO = 1.60
SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_LATE_MAIN_PEAK_MIN_SHIFT_KEYS = 2
SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MIN_DURATION_SEC = 8.0
SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MIN_SEPARATION_SEC = 1.50
SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MIN_SEMANTIC_PEAK = 0.02
SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MAX_BOUNDARY_CONFIDENCE = 0.64
SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MAX_CONFIDENCE = 0.75
SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_SHIFT_SECONDS = 0.60
SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_SHIFT_KEYS = 2
SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_GLOBAL_PEAK = 0.055
SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_GLOBAL_LAG_SEC = 0.45
SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MAX_SEMANTIC_PEAK_RATIO = 0.50
SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_CANDIDATE_PEAK_RATIO = 0.75
SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_CANDIDATE_TO_SEMANTIC_RATIO = 1.80
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_FULL_CONTEXT_CONFIDENCE = 0.85
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_MODERATE_CONFIDENCE = 0.80
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_ACTION_CONFIDENCE = 0.85
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_CONFIDENCE = 0.80
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_AIR_PHASE_CONFIDENCE = 0.70
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_PHASE_CONFIDENCE = 0.70
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_MAX_VISIBILITY = 0.10
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_MIN_LOW_VISIBILITY_KEYS = 2
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_TAIL_SHIFT_SEC = 2.0
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_EARLY_SHIFT_SEC = 1.50
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_EARLY_START_MAX_SEC = 0.35
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_WINDOW_MIN_SHIFT_SEC = 1.50
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_CANDIDATE_MAX_PRE_TAKEOFF_GAP_SEC = 0.45
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_WINDOW_MIN_PEAK_RATIO = 1.40
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_WINDOW_MAX_SEMANTIC_RATIO = 0.55
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_SHIFT_MIN_EARLY_SEC = 0.35
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_SHIFT_MAX_L_TO_T_SEC = 0.18
SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_SHIFT_MAX_SPAN_SEC = 1.05
SEMANTIC_CANDIDATE_MOTION_WINDOW_COMPRESSED_CORE_MAX_SPAN_SEC = 0.32
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_LEAD_SEC = 0.55
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_SEMANTIC_LEAD_SEC = 1.0
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_T_SHIFT_SEC = 0.25
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MAX_T_SHIFT_SEC = 0.85
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_CONFLICT_KEYS = 2
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_CORE_RATIO = 0.30
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_CORE_SCORE = 0.035
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_REQUIRED_FLAGS = {
    "keyframe_candidates_motion_fallback",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "tal_candidate_motion_fallback_low_precision",
}
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_SUPPORT_FLAGS = {
    "tal_candidate_skeleton_drifted_after_takeoff",
    "a_pose_signal_drifted",
    "l_pose_signal_drifted",
    "tal_candidate_motion_fallback_low_precision",
}
SEMANTIC_EARLY_APPROACH_MOTION_PEAK_BLOCK_FLAGS = {
    "tal_candidate_motion_window_occlusion_contaminated",
    "tal_candidate_motion_fallback_foreground_motion_risk",
}
SEMANTIC_CANDIDATE_MOTION_WINDOW_ONLY_CONTEXT_FLAGS = {
    "keyframe_candidates_excluded_unreliable_pose_frames",
}
SEMANTIC_CANDIDATE_MOTION_WINDOW_ONLY_MIN_BOUNDARY_AVG_CONFIDENCE = 0.52
SEMANTIC_CANDIDATE_MOTION_WINDOW_ONLY_MIN_BOUNDARY_STRONG_CONFIDENCE = 0.60
SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_SHIFT_SECONDS = 0.15
SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MIN_CONFIDENCE = 0.65
SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MIN_MOTION_SCORE = 0.08
SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MOTION_RATIO = 1.45
SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_CORE_ALIGNMENT_SECONDS = 0.12
SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MOTION_WINDOW_SECONDS = 0.09
SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_SHIFT_SECONDS = 0.25
SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_CONFIDENCE = 0.75
SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_CORE_CONFIDENCE = 0.45
SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MAX_APEX_DELTA_SECONDS = 0.18
SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MAX_LANDING_DELTA_SECONDS = 0.20
SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_TAKEOFF_APEX_GAP_SECONDS = 0.12
SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_APEX_LANDING_GAP_SECONDS = 0.12
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_SHIFT_SECONDS = 0.15
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MAX_SHIFT_SECONDS = 0.35
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_CONFIDENCE = 0.70
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_MOTION_SCORE = 0.08
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MOTION_WINDOW_SECONDS = 0.09
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_REFINEMENT_GAP_SECONDS = 0.12
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_APEX_MAX_DELTA_SECONDS = 0.12
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_APEX_GAP_SECONDS = 0.04
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_CANDIDATE_TO_SEMANTIC_PEAK_RATIO = 0.85
SEMANTIC_TAKEOFF_ANCHOR_APEX_CONFLICT_MIN_SHIFT_SECONDS = 0.60
SEMANTIC_TAKEOFF_ANCHOR_CORE_CONFLICT_MIN_SHIFT_SECONDS = {
    "T": 0.35,
    "L": 0.45,
}
SEMANTIC_WEAK_REFINEMENT_MAX_MOTION_SCORE = 0.025
SEMANTIC_LATE_POSE_CORE_CONFLICT_MIN_KEYS = 2
SEMANTIC_LATE_POSE_CORE_CONFLICT_MIN_SHIFT_SECONDS = 0.12
SEMANTIC_LATE_POSE_CORE_CONFLICT_MIN_CONFIDENCE = 0.30
SEMANTIC_LATE_POSE_CORE_CONFLICT_MAX_SPAN_SECONDS = 1.10
SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_CONTEXT_FLAGS = {
    "keyframe_candidates_tail_motion_window_rejected",
    "keyframe_candidates_late_pose_core_reselected",
    "keyframe_candidates_motion_fallback",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "tal_candidate_skeleton_drifted_after_takeoff",
    "tal_candidate_motion_fallback_low_precision",
    "tal_candidate_motion_fallback_low_visibility_weak_boundary",
    "tal_candidate_motion_fallback_low_motion_low_confidence",
    "tal_candidate_motion_fallback_cross_segment_unreliable",
    "tal_candidate_motion_fallback_compressed",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "tal_candidate_motion_fallback_tail_window",
    "tal_candidate_motion_window_occlusion_contaminated",
}
SEMANTIC_CANDIDATE_TAL_CONFLICT_CONTEXT_FLAGS = {
    "keyframe_candidates_tail_motion_window_rejected",
    "keyframe_candidates_late_pose_core_reselected",
    "keyframe_candidates_motion_fallback",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "tal_candidate_skeleton_drifted_after_takeoff",
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_takeoff_apex_gap_unreliable",
    "tal_candidate_takeoff_apex_gap_compressed",
    "tal_candidate_apex_landing_gap_unreliable",
    "tal_candidate_apex_landing_gap_compressed",
    "tal_candidate_core_gap_compressed",
    "tal_candidate_weak_geometry",
    "tal_candidate_landing_geometry_absent",
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_unreliable_sparse_track_stitch",
    "tal_candidate_motion_fallback_cross_segment_unreliable",
    "tal_candidate_motion_fallback_compressed",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "tal_candidate_motion_fallback_low_visibility_weak_boundary",
    "tal_candidate_motion_fallback_low_motion_low_confidence",
    "tal_candidate_motion_fallback_tail_window",
    "tal_candidate_motion_window_occlusion_contaminated",
}
SEMANTIC_CANDIDATE_TAL_CONFLICT_STRONG_FLAGS = {
    "keyframe_candidates_late_pose_core_reselected",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_takeoff_apex_gap_unreliable",
    "tal_candidate_takeoff_apex_gap_compressed",
    "tal_candidate_apex_landing_gap_unreliable",
    "tal_candidate_apex_landing_gap_compressed",
    "tal_candidate_core_gap_compressed",
    "landing_geometry_weak",
    "tal_candidate_landing_geometry_weak",
    "tal_candidate_skeleton_drifted_after_takeoff",
    "tal_candidate_weak_geometry",
    "tal_candidate_landing_geometry_absent",
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_unreliable_sparse_track_stitch",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "tal_candidate_motion_fallback_low_visibility_weak_boundary",
    "tal_candidate_motion_fallback_low_motion_low_confidence",
    "tal_candidate_motion_fallback_tail_window",
    "tal_candidate_motion_window_occlusion_contaminated",
}
SEMANTIC_CANDIDATE_UNRELIABLE_POSE_FALLBACK_FLAGS = {
    "keyframe_candidates_motion_fallback_unreliable_pose_state",
    "keyframe_candidates_motion_fallback_low_visibility_weak_boundary",
    "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
    "keyframe_candidates_motion_fallback_takeoff_anchor_tail_window",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "tal_candidate_motion_fallback_low_visibility_weak_boundary",
    "tal_candidate_motion_fallback_low_motion_low_confidence",
    "tal_candidate_motion_fallback_tail_window",
}
SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS = {
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_takeoff_apex_gap_unreliable",
    "tal_candidate_takeoff_apex_gap_compressed",
    "tal_candidate_apex_landing_gap_unreliable",
    "tal_candidate_apex_landing_gap_compressed",
    "tal_candidate_core_gap_compressed",
}
SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS = {
    "tal_candidate_takeoff_geometry_weak",
    "tal_candidate_landing_geometry_weak",
    "landing_geometry_weak",
    "tal_candidate_weak_geometry",
}
SEMANTIC_REFINEMENT_REJECTION_FLAGS = {
    "semantic_keyframe_refinement_order_rejected",
    "semantic_keyframe_refinement_phase_rejected",
}
SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_CONTEXT_FLAGS = {
    "keyframe_candidates_excluded_unreliable_pose_frames",
    "keyframe_candidates_motion_fallback",
    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
    "tal_candidate_motion_fallback_low_precision",
    "tal_candidate_motion_fallback_low_visibility_weak_boundary",
    "tal_candidate_motion_fallback_low_motion_low_confidence",
    "tal_candidate_motion_fallback_cross_segment_unreliable",
    "tal_candidate_motion_fallback_compressed",
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
}
SEMANTIC_REUSE_SPARSE_TRACK_STITCHED_CANDIDATE_FLAGS = {
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_unreliable_sparse_track_stitch",
}
SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CONTEXT_FLAGS = SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_CONTEXT_FLAGS | {
    "tal_candidate_motion_window_occlusion_contaminated",
    "tal_candidate_motion_window_unreliable_tracker_state",
}
SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS = {
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_unreliable_sparse_track_stitch",
    "tal_candidate_motion_window_occlusion_contaminated",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "tal_candidate_motion_fallback_low_visibility_weak_boundary",
    "tal_candidate_motion_fallback_low_motion_low_confidence",
    "tal_candidate_motion_fallback_tail_window",
}
SEMANTIC_CANDIDATE_FINAL_FALLBACK_BLOCKING_FLAGS = (
    SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS
    | SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
    | {
        "tal_candidate_skeleton_drifted_after_takeoff",
        "tal_candidate_weak_geometry",
        "tal_candidate_landing_geometry_absent",
        "tal_candidate_landing_geometry_weak",
        "landing_geometry_weak",
        "tal_candidate_motion_fallback_cross_segment_unreliable",
        "tal_candidate_motion_fallback_compressed",
    }
)
SEMANTIC_MOTION_ALIGNED_CANDIDATE_BLOCKING_FLAGS = {
    "tal_candidate_motion_fallback_cross_segment_unreliable",
    "tal_candidate_sparse_track_stitched",
    "tal_candidate_unreliable_sparse_track_stitch",
    "tal_candidate_motion_fallback_foreground_motion_risk",
    "keyframe_candidates_motion_fallback_unreliable_pose_state",
    "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
    "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
}
SEMANTIC_MOTION_ALIGNED_CANDIDATE_DROP_FLAGS = {
    "semantic_frame_extract_failed",
    "semantic_keyframe_core_foreground_occlusion",
    "semantic_keyframe_refinement_order_rejected",
    "semantic_keyframes_unreliable_after_refinement",
    "semantic_keyframes_unreliable_after_retry_rejection",
    "semantic_keyframes_unreliable_after_visibility_check",
    "semantic_keyframes_unreliable_candidate_early_takeoff_conflict",
    "semantic_keyframes_unreliable_candidate_motion_window_conflict",
    "semantic_keyframes_unreliable_candidate_takeoff_single_conflict",
    "semantic_keyframes_unreliable_candidate_tal_conflict",
    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
    "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
    "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
    "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
    "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
    "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
    "video_temporal_resolver_no_semantic_selection",
    "video_temporal_resolver_no_selected_frames",
    "video_temporal_resolver_partial_skeleton_fallback",
}
SEMANTIC_MOTION_ALIGNED_CANDIDATE_CONFIDENCE = 0.66
SEMANTIC_MOTION_ALIGNED_CANDIDATE_MAX_KEY_DELTA_SEC = 0.12
SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC = 0.12
SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_GAP_SEC = 0.10
SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_SPAN_SEC = 0.28
SEMANTIC_MOTION_ALIGNED_CANDIDATE_MAX_SPAN_SEC = 1.25
SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_RECORDS = 3
SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_PEAK_SCORE = 0.045
SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_KEY_SCORE = 0.035
SEMANTIC_MOTION_ALIGNED_CANDIDATE_STRONG_RATIO = 0.35
SEMANTIC_MOTION_ALIGNED_CANDIDATE_GLOBAL_PEAK_TOLERANCE_SEC = 0.18
SEMANTIC_MOTION_ALIGNED_CANDIDATE_REMOTE_GLOBAL_RATIO = 0.85
SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_BLOCKING_FLAGS = (
    SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS
    | SEMANTIC_CANDIDATE_UNRELIABLE_POSE_FALLBACK_FLAGS
    | SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
    | {
        "keyframe_candidates_motion_fallback",
        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
        "tal_candidate_motion_fallback_low_precision",
        "tal_candidate_incomplete",
        "tal_order_unresolved",
        "tal_candidate_weak_geometry",
        "tal_candidate_landing_geometry_absent",
        "tal_candidate_landing_geometry_weak",
        "landing_geometry_weak",
    }
)
SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_MIN_SHIFT_SECONDS = 0.75
SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_MIN_CONFIDENCE = 0.45
SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_MIN_KEYS = 2
SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_MIN_SHIFT_SECONDS = 0.75
SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_MIN_SCORE = VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_MIN_SCORE
SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_RATIO = VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_RATIO
SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CORE_TOLERANCE_SEC = VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_TOLERANCE_SEC
SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CORE_PEAK_RATIO = VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_PEAK_RATIO
SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CANDIDATE_PEAK_RATIO = 0.55
SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_MIN_STRONG_RECORDS = 2
SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_SEMANTIC_PEAK_RATIO = 0.35
SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_CANDIDATE_PEAK_RATIO = 0.70
SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_MIN_SEPARATION_SEC = 1.25
SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_NEAR_MIN_SEPARATION_SEC = 0.12
SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_NEAR_MIN_GLOBAL_PEAK = 0.18
SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_NEAR_CANDIDATE_PEAK_RATIO = 0.85
SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MIN_GLOBAL_PEAK = 0.18
SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MIN_CANDIDATE_PEAK_RATIO = 0.85
SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MAX_SEMANTIC_PEAK_RATIO = 0.35
SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MOTION_WINDOW_SECONDS = 0.10
SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MIN_SHIFT_SECONDS = 0.45
SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MAX_TAKEOFF_AFTER_SEMANTIC_L_SEC = 0.60
SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MIN_CONFLICT_KEYS = 2
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_MIN_SHIFT_SEC = 0.12
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_MAX_SHIFT_SEC = 0.45
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_EXTENDED_T_MAX_SHIFT_SEC = 0.85
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_EXTENDED_T_APEX_LEAD_SEC = 0.10
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_EXTENDED_T_LANDING_TOLERANCE_SEC = 0.15
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_MAX_TAKEOFF_AFTER_SEMANTIC_L_SEC = 0.60
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_APEX_COLLAPSED_TO_TAKEOFF_SEC = 0.08
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_LANDING_MAX_SHIFT_SEC = 0.15
SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_LANDING_MIN_PEAK_RATIO = 0.50
SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MIN_AVG_CONFIDENCE = 0.50
SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MIN_BOUNDARY_CONFIDENCE = 0.42
SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MIN_SHIFT_SECONDS = 0.75
SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MAX_CORE_PEAK_RATIO = 0.50
SEMANTIC_WEAK_TAKEOFF_APEX_MAX_GAP_SEC = 0.10
SEMANTIC_LATE_POSE_CORE_FALLBACK_MIN_CONFIDENCE = 0.45
SEMANTIC_LATE_POSE_CORE_FALLBACK_MIN_TAKEOFF_APEX_GAP_SEC = 0.12
SEMANTIC_LATE_POSE_CORE_FALLBACK_MIN_APEX_LANDING_GAP_SEC = 0.18
SEMANTIC_WEAK_TAKEOFF_APEX_WARNINGS = {
    "apex_local_minimum_not_clear",
    "apex_motion_bounded_unclear_fallback",
    "apex_geometry_weak",
    "confidence_missing_knee_angle_change",
}
SEMANTIC_APEX_WEAK_CANDIDATE_FLAGS = {
    "apex_local_minimum_not_clear",
    "confidence_missing_knee_angle_change",
    "a_pose_signal_drifted",
    "tal_candidate_takeoff_apex_gap_unreliable",
    "tal_candidate_takeoff_apex_gap_compressed",
    "tal_candidate_temporal_geometry_unreliable",
}
SEMANTIC_UNRELIABLE_POSE_FALLBACK_EFFECTIVE_CONFIDENCE_CAP = 0.34
SEMANTIC_TRACKER_FINAL_LOSS_FALLBACK_FLAGS = {
    "tal_candidate_motion_fallback_low_precision",
    "tal_candidate_incomplete",
    "tal_order_unresolved",
    "tal_candidate_skeleton_drifted_after_takeoff",
}
SEMANTIC_TRACKER_FINAL_LOSS_MOTION_FALLBACK_FLAGS = {
    "keyframe_candidates_motion_fallback",
    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
}
SEMANTIC_TRACKER_FINAL_LOSS_WEAK_REFINEMENT_MAX_SCORE = 0.04
SEMANTIC_TRACKER_FINAL_LOSS_WEAK_CANDIDATE_MAX_CONFIDENCE = 0.50
SEMANTIC_TRACKER_FINAL_LOSS_WEAK_CANDIDATE_MIN_KEYS = 2
SEMANTIC_TRACKER_FINAL_LOSS_WEAK_GEOMETRY_RETRY_MAX_REFINEMENT_SCORE = 0.04
SEMANTIC_TRACKER_FINAL_LOSS_MOTION_FALLBACK_MAX_TAL_SPAN_SEC = 2.20
SEMANTIC_TRACKER_FINAL_LOSS_RELIABLE_POSE_BOUND_TOLERANCE_SEC = 0.45
SEMANTIC_TRACKER_FINAL_LOSS_BOUNDED_FALLBACK_MIN_CONFLICT_KEYS = 2
SEMANTIC_TRACKER_FINAL_LOSS_BOUNDED_FALLBACK_MIN_CONFIDENCE = 0.50
SEMANTIC_TRACKER_FINAL_LOSS_VISUAL_PROMOTION_CONFIDENCE_FLOOR = 0.75
SEMANTIC_TRACKER_FINAL_LOSS_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR = 0.65
SEMANTIC_TRACKER_FINAL_LOSS_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR = 0.70
SEMANTIC_TRACKER_FINAL_LOSS_LOW_VISIBILITY_CANDIDATE_MAX_CONFIDENCE = 0.58
SEMANTIC_TRACKER_FINAL_LOSS_LOW_VISIBILITY_MAX_POSE_VISIBILITY = 0.08
SEMANTIC_TRACKER_FINAL_LOSS_LOW_VISIBILITY_MAX_TAL_SPAN_SEC = 0.75
SEMANTIC_TRACKER_FINAL_LOSS_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC = 0.25
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_CONFIDENCE_FLOOR = 0.75
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_WEAK_GEOMETRY_CONFIDENCE_FLOOR = 0.70
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR = 0.70
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR = 0.75
SEMANTIC_PHASE_RANGE_LOW_VISIBILITY_CANDIDATE_MAX_VISIBILITY = 0.08
SEMANTIC_PHASE_RANGE_LOW_VISIBILITY_CANDIDATE_MIN_KEYS = 2
SEMANTIC_PHASE_RANGE_LOW_VISIBILITY_REQUIRED_KEYS = {"T"}
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MIN_DURATION_SEC = 8.0
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_CONFIDENCE_FLOOR = 0.50
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR = 0.50
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR = 0.55
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC = 0.25
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC = 1.50
SEMANTIC_DISTANT_FULL_CONTEXT_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC = 3.20
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MIN_SHIFT_SEC = 0.75
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MIN_SHIFT_KEYS = 2
SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_CONTEXT_FLAGS = {
    "distance_too_far",
    "low_resolution",
    "distant_view",
    "tiny_target",
    "zoomed_target",
    "video_temporal_fallback_recommended",
    "video_temporal_not_high_confidence",
}
SEMANTIC_DISTANT_FULL_CONTEXT_WEAK_GEOMETRY_FLAGS = {
    "keyframe_candidates_excluded_unreliable_pose_frames",
    "tal_candidate_weak_geometry",
    "tal_candidate_takeoff_geometry_weak",
    "tal_candidate_landing_geometry_weak",
}
SEMANTIC_INSUFFICIENT_POSE_LOW_VISIBILITY_MOTION_FALLBACK_FLAGS = {
    "keyframe_candidates_insufficient_pose",
    "keyframe_candidates_motion_fallback",
    "tal_candidate_motion_fallback_low_precision",
}
SEMANTIC_BOUNDED_LOW_VISIBILITY_MOTION_FALLBACK_FLAGS = {
    "keyframe_candidates_motion_fallback",
    "tal_candidate_motion_fallback_low_precision",
    "tal_candidate_incomplete",
    "tal_order_unresolved",
    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
}
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_SHIFT_SEC = 0.75
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_SHIFT_KEYS = 2
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC = 0.25
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC = 1.50
SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_CORE_PEAK_RATIO_FLOOR = 0.20
SEMANTIC_PHASE_RANGE_WEAK_GEOMETRY_MOTION_CLUSTER_MIN_SHIFT_KEYS = 2
SEMANTIC_PHASE_RANGE_WEAK_GEOMETRY_MIN_CORE_PEAK_RATIO = 0.35
SEMANTIC_RETRY_WEAK_PHASE_MIN_TAL_SPAN_SEC = 0.45
SEMANTIC_RETRY_WEAK_PHASE_MAX_TAL_SPAN_SEC = 1.50
SEMANTIC_RETRY_WEAK_PHASE_MAX_BOUNDARY_CONFIDENCE = 0.45
SEMANTIC_RETRY_WEAK_PHASE_EARLY_MOTION_MIN_LEAD_SEC = 0.45
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_CONFIDENCE_FLOOR = 0.60
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR = 0.60
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR = 0.50
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC = 0.45
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC = 1.50
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_TAKEOFF_LEAD_SEC = 0.55
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_LANDING_TRAIL_SEC = 0.75
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MAX_CANDIDATE_CONFIDENCE = 0.62
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MIN_SHIFT_SEC = 0.25
SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MIN_SHIFT_KEYS = 2
SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MIN_SHIFT_SEC = 0.75
SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MIN_KEYS = 2
SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_CORE_TOLERANCE_SEC = 0.20
SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MIN_GLOBAL_PEAK = 0.035
SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MIN_SEMANTIC_PEAK_RATIO = 0.80
SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MAX_CANDIDATE_PEAK_RATIO = 0.95
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_SHIFT_SEC = 0.40
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_PREP_PEAK = 0.06
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_PREP_TO_CORE_PEAK_RATIO = 1.10
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MAX_T_OFFSET_SEC = 0.22
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_PREP_TAKEOFF_GAP_SEC = 0.10
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MAX_TAL_SPAN_SEC = 1.50
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_SKELETON_T_PRE_SEC = 0.25
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_SKELETON_T_POST_SEC = 0.45
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_A_MIN_OFFSET_SEC = 0.48
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_A_MAX_OFFSET_SEC = 0.56
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_L_MIN_OFFSET_SEC = 0.72
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_L_MAX_OFFSET_SEC = 0.82
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MIN_SHIFT_SEC = 1.00
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MAX_T_LEAD_SEC = 0.25
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MIN_SUPPORT_RECORDS = 3
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MAX_CORE_PEAK_RATIO = 0.28
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MAX_SUPPORT_PEAK_RATIO = 0.40
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MIN_SUPPORT_SCORE = 0.055
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_T_AFTER_L_SEC = 0.08
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_A_MIN_OFFSET_SEC = 0.28
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_A_MAX_OFFSET_SEC = 0.32
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_L_MIN_OFFSET_SEC = 0.58
SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_L_MAX_OFFSET_SEC = 0.62
SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_CONFIDENCE_FLOOR = 0.50
SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_PHASE_CONFIDENCE_FLOOR = 0.40
SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_ACTION_CONFIDENCE_FLOOR = 0.60
SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_MIN_TAL_SPAN_SEC = 0.18
SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_MAX_TAL_SPAN_SEC = 2.20
SEMANTIC_TRACKER_FINAL_LOSS_BOUNDED_FALLBACK_SHIFT_SECONDS = {
    "T": 0.20,
    "A": 0.20,
    "L": 0.25,
}
SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_SHIFT_SECONDS = {
    "T": 0.45,
    "A": 0.35,
    "L": 0.45,
}
SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_MIN_CONFLICT_KEYS = 2
SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_MIN_CONFIDENCE = 0.50
SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_MAX_VIDEO_CONFIDENCE = 0.75
SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_MIN_POSE_VISIBILITY = 0.25
SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_CONTEXT_FLAGS = {
    "distant_view",
    "low_detail",
    "partial_occlusion",
    "distance",
    "small_target",
    "video_temporal_not_high_confidence",
}
VIDEO_TEMPORAL_RETRY_EARLY_DRIFT_ALLOW_ORIGINAL_FLAGS = {
    "semantic_keyframe_core_foreground_occlusion_repaired",
    "semantic_keyframes_unreliable_after_visibility_check",
    "semantic_keyframes_unreliable_after_refinement",
    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
    "video_temporal_resolver_partial_skeleton_fallback",
}
LOW_CONFIDENCE_JUMP_VISUAL_PROMOTION_CONFIDENCE_FLOOR = 0.50
LOW_CONFIDENCE_JUMP_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR = 0.80
LOW_CONFIDENCE_JUMP_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR = 0.65
LOW_CONFIDENCE_JUMP_VISUAL_REPAIR_MAX_DELTA_SEC = 0.35
LOW_CONFIDENCE_JUMP_VISUAL_REPAIR_MAX_CANDIDATES = 9
WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_CONFIDENCE_FLOOR = 0.55
WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR = 0.65
WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR = 0.40
WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MAX_DELTA_SEC = 0.35
WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MAX_MEAN_DELTA_SEC = 0.22
WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MAX_CANDIDATE_CONFIDENCE = 0.45
WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC = 0.25
WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC = 1.20


@dataclass(slots=True)
class VideoTemporalTaskHandle:
    task: asyncio.Task[dict[str, Any]]
    ai_clip_path: Path
    source_duration_sec: float | None
    clip_duration_sec: float | None
    clip_fps: float
    timestamp_offset_sec: float
    analyzed_video_kind: str
    input_window: VideoInputWindow

    def ai_clip_payload(self) -> dict[str, Any]:
        return {
            "path": str(self.ai_clip_path),
            "duration_sec": self.clip_duration_sec,
            "source_duration_sec": self.source_duration_sec,
            "fps": self.clip_fps,
            "timestamp_offset_sec": self.timestamp_offset_sec,
            **self.input_window.to_payload(),
        }


@dataclass(slots=True)
class SemanticKeyframePipelineResult:
    ai_clip: dict[str, Any] | None
    video_temporal: dict[str, Any] | None
    resolved_keyframes: dict[str, Any]
    effective_source: str = "sampled_frames"
    semantic_frames: list[Path] = field(default_factory=list)
    semantic_records: list[dict[str, Any]] = field(default_factory=list)
    partial_semantic_frames: list[Path] = field(default_factory=list)
    partial_semantic_records: list[dict[str, Any]] = field(default_factory=list)
    refinement_flags: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    used_semantic_frames: bool = False
    has_semantic_moments: bool = False


def merge_frame_motion_payload(
    motion_scores: dict[str, object],
    *,
    video_temporal: dict[str, Any] | None = None,
    resolved_keyframes: dict[str, Any] | None = None,
) -> dict[str, object]:
    merged: dict[str, object] = dict(motion_scores)
    if isinstance(video_temporal, dict):
        merged["video_temporal"] = video_temporal
    if isinstance(resolved_keyframes, dict):
        merged["resolved_keyframes"] = resolved_keyframes
    return merged


def _merge_flags(*sources: object) -> list[str]:
    flags: list[str] = []
    for source in sources:
        raw_flags = source.get("quality_flags") if isinstance(source, dict) else source
        if not isinstance(raw_flags, list):
            continue
        for flag in raw_flags:
            value = str(flag).strip()
            if value and value not in flags:
                flags.append(value)
    return flags


def _append_flag(payload: dict[str, Any], flag: str) -> None:
    flags = payload.get("quality_flags") if isinstance(payload.get("quality_flags"), list) else []
    if flag not in flags:
        payload["quality_flags"] = [*flags, flag]


def _remove_flags(payload: dict[str, Any], *flags_to_remove: str) -> None:
    flags = payload.get("quality_flags") if isinstance(payload.get("quality_flags"), list) else []
    blocked = set(flags_to_remove)
    payload["quality_flags"] = [flag for flag in flags if flag not in blocked]


def _mark_low_visibility_bounded_motion_fallback_drift_ignored_after_visual_promotion(
    payload: dict[str, Any],
) -> None:
    diagnostic = payload.get("semantic_low_visibility_bounded_motion_fallback_drift")
    if not isinstance(diagnostic, dict):
        return
    diagnostic["previous_decision"] = diagnostic.get("decision")
    diagnostic["decision"] = "ignored_after_tracker_final_loss_visual_tal_promotion"
    diagnostic["promotion_reason"] = "visible_video_tal_over_low_visibility_motion_fallback"


def _mark_late_pose_core_conflict_ignored_after_weak_cluster_visual_promotion(
    payload: dict[str, Any],
    support: dict[str, Any] | None,
) -> None:
    conflict = payload.get("semantic_candidate_tal_conflict")
    if not isinstance(conflict, dict):
        return
    if str(conflict.get("decision") or "") != "rejected_late_pose_core_candidate_conflict":
        return
    conflict["previous_decision"] = conflict.get("decision")
    conflict["decision"] = "ignored_after_weak_skeleton_cluster_visual_promotion"
    conflict["promotion_reason"] = "visible_video_tal_over_nearby_weak_skeleton_cluster"
    if support is not None:
        conflict["weak_skeleton_cluster_support"] = support


def _semantic_visual_promotion_overrides_low_visibility_motion_fallback(payload: dict[str, Any]) -> bool:
    flags = set(_quality_flags(payload))
    return bool(
        flags
        & {
            "semantic_keyframes_tracker_final_loss_visual_tal_promoted",
            "semantic_keyframes_phase_range_visual_tal_promoted",
            "semantic_keyframes_distant_full_context_visual_tal_promoted",
        }
    )


def _has_rejected_late_pose_core_candidate_conflict(resolved_keyframes: dict[str, Any]) -> bool:
    conflict = resolved_keyframes.get("semantic_candidate_tal_conflict")
    return (
        isinstance(conflict, dict)
        and str(conflict.get("decision") or "") == "rejected_late_pose_core_candidate_conflict"
    )


def _semantic_reuse_overrides_low_visibility_motion_fallback(payload: dict[str, Any]) -> bool:
    return "semantic_keyframes_reused_from_matching_video" in set(_quality_flags(payload))


def _semantic_reuse_overrides_long_unresolved_motion_fallback(payload: dict[str, Any]) -> bool:
    flags = set(_quality_flags(payload))
    return (
        "semantic_keyframes_reused_from_matching_video" in flags
        and "semantic_keyframes_reused_over_long_unresolved_motion_fallback" in flags
    )


def effective_timestamp_source(resolved_keyframes: dict[str, Any] | None, used_semantic_frames: bool) -> str:
    if not used_semantic_frames:
        return "sampled_frames"
    if isinstance(resolved_keyframes, dict):
        source = str(resolved_keyframes.get("source") or "").strip()
        if source:
            return source
    return "semantic_frames"


def _isolated_semantic_frames_dir(semantic_frames_dir: Path, suffix: str) -> Path:
    return semantic_frames_dir.parent / f"{semantic_frames_dir.name}_{suffix}"


def _promote_semantic_frame_artifacts(
    source_paths: Sequence[Path],
    source_records: Sequence[dict[str, Any]],
    target_dir: Path,
    *,
    prefix: str = "semantic",
) -> tuple[list[Path], list[dict[str, Any]]]:
    records = [dict(record) for record in source_records if isinstance(record, dict)]
    if not records:
        return [], []
    if len(source_paths) < len(records):
        raise FileNotFoundError("Not enough semantic frame artifacts to promote.")

    target_dir.mkdir(parents=True, exist_ok=True)
    target_paths = [target_dir / f"{prefix}_{index:04d}.jpg" for index in range(1, len(records) + 1)]
    source_subset = [Path(path) for path in source_paths[: len(records)]]
    source_is_target = all(source.resolve() == target.resolve() for source, target in zip(source_subset, target_paths))

    promoted_records: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        promoted_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})

    if source_is_target:
        for path in target_paths:
            if not path.exists() or path.stat().st_size <= 0:
                raise FileNotFoundError(f"Semantic frame artifact is missing: {path}")
        return target_paths, promoted_records

    for source_path in source_subset:
        if not source_path.exists() or source_path.stat().st_size <= 0:
            raise FileNotFoundError(f"Semantic frame artifact is missing: {source_path}")
    for existing_frame in target_dir.glob(f"{prefix}_*.jpg"):
        existing_frame.unlink(missing_ok=True)
    for source_path, target_path in zip(source_subset, target_paths):
        shutil.copyfile(source_path, target_path)
    return target_paths, promoted_records


def _promote_semantic_result_artifacts(
    result: SemanticKeyframePipelineResult,
    semantic_frames_dir: Path,
) -> SemanticKeyframePipelineResult:
    records = result.semantic_records
    if not records:
        selected = result.resolved_keyframes.get("selected")
        records = [dict(item) for item in selected if isinstance(item, dict)] if isinstance(selected, list) else []
    promoted_paths, promoted_records = _promote_semantic_frame_artifacts(
        result.semantic_frames,
        records,
        semantic_frames_dir,
        prefix="semantic",
    )
    result.semantic_frames = promoted_paths
    result.semantic_records = promoted_records
    result.resolved_keyframes["selected"] = promoted_records
    result.quality_flags = _merge_flags(result.video_temporal, result.resolved_keyframes)
    return result


def _quality_flags(*sources: object) -> list[str]:
    return _merge_flags(*sources)


def _video_temporal_retry_reason_flags(
    video_temporal: dict[str, Any] | None,
    resolved_keyframes: dict[str, Any],
    *,
    analysis_profile: str | None = None,
    used_semantic_frames: bool | None = None,
    motion_scores: dict[str, object] | None = None,
    bio_data: dict[str, Any] | None = None,
) -> list[str]:
    flags = _quality_flags(video_temporal, resolved_keyframes)
    if isinstance(video_temporal, dict):
        requested_profile = _normalize_action_profile(analysis_profile)
        provider_family = _provider_action_family(video_temporal)
        is_jump_context = requested_profile in {"", "jump"} or (requested_profile not in {"spin", "spiral", "step"} and provider_family == "jump")
        key_moments = video_temporal.get("key_moments") if isinstance(video_temporal.get("key_moments"), dict) else {}
        if is_jump_context and any(key_moments.get(key) is None for key in ("T_takeoff_sec", "A_air_sec", "L_landing_sec")):
            flags = _merge_flags(flags, ["video_temporal_missing_core_tal"])
        confidence = video_temporal.get("confidence")
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        if (
            VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_FLOOR <= confidence_value < 0.55
            and "video_temporal_resolver_low_video_confidence" in flags
        ):
            flags = _merge_flags(flags, ["video_temporal_low_confidence_retryable"])
        if _non_jump_profile_mismatch_is_retryable(
            video_temporal,
            resolved_keyframes,
            analysis_profile=analysis_profile,
            used_semantic_frames=used_semantic_frames,
        ):
            flags = _merge_flags(flags, ["video_temporal_profile_mismatch_retryable"])
    flags = _merge_flags(
        flags,
        _semantic_tracker_final_loss_motion_fallback_flags(
            resolved_keyframes,
            bio_data,
            analysis_profile=analysis_profile,
        ),
        _semantic_tracker_final_loss_outside_reliable_pose_flags(
            resolved_keyframes,
            bio_data,
            analysis_profile=analysis_profile,
        ),
        _semantic_tracker_final_loss_weak_semantic_motion_flags(
            resolved_keyframes,
            bio_data,
            analysis_profile=analysis_profile,
        ),
        _semantic_low_visibility_bounded_motion_fallback_drift_flags(
            resolved_keyframes,
            bio_data,
            analysis_profile=analysis_profile,
        ),
        _semantic_candidate_tal_conflict_flags(
            resolved_keyframes,
            bio_data,
            analysis_profile=analysis_profile,
            motion_scores=motion_scores,
        ),
        _semantic_skeleton_tal_conflict_flags(resolved_keyframes, bio_data, analysis_profile=analysis_profile),
        _semantic_motion_cluster_conflict_flags(
            resolved_keyframes,
            motion_scores,
            analysis_profile=analysis_profile,
            bio_data=bio_data,
        ),
    )
    return [flag for flag in flags if flag in VIDEO_TEMPORAL_RETRY_TRIGGER_FLAGS]


def validate_semantic_keyframes_against_current_evidence(
    resolved_keyframes: dict[str, Any] | None,
    *,
    bio_data: dict[str, Any] | None = None,
    motion_scores: dict[str, object] | None = None,
    analysis_profile: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(resolved_keyframes, dict):
        return None
    validated = dict(resolved_keyframes)
    if isinstance(resolved_keyframes.get("selected"), list):
        validated["selected"] = [
            dict(item) if isinstance(item, dict) else item
            for item in resolved_keyframes.get("selected", [])
        ]
    if isinstance(resolved_keyframes.get("video_ai"), dict):
        validated["video_ai"] = dict(resolved_keyframes["video_ai"])
    _maybe_align_pose_supported_takeoff_candidate(
        validated,
        bio_data,
        motion_scores,
        analysis_profile=analysis_profile,
    )
    _maybe_align_low_visibility_main_motion_candidates(
        validated,
        bio_data,
        motion_scores,
        analysis_profile=analysis_profile,
    )
    _maybe_reanchor_late_phase_range_tal(
        validated,
        bio_data,
        motion_scores,
        analysis_profile=analysis_profile,
    )
    for flag in _semantic_tracker_final_loss_motion_fallback_flags(
        validated,
        bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(validated, flag)
    for flag in _semantic_tracker_final_loss_outside_reliable_pose_flags(
        validated,
        bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(validated, flag)
    for flag in _semantic_tracker_final_loss_weak_semantic_motion_flags(
        validated,
        bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(validated, flag)
    for flag in _semantic_low_visibility_bounded_motion_fallback_drift_flags(
        validated,
        bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(validated, flag)
    for flag in _semantic_candidate_tal_conflict_flags(
        validated,
        bio_data,
        analysis_profile=analysis_profile,
        motion_scores=motion_scores,
    ):
        _append_flag(validated, flag)
    for flag in _semantic_reuse_current_candidate_conflict_flags(
        validated,
        bio_data,
        analysis_profile=analysis_profile,
        motion_scores=motion_scores,
    ):
        _append_flag(validated, flag)
    for flag in _semantic_reuse_early_motion_cluster_conflict_flags(
        validated,
        motion_scores,
        bio_data=bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(validated, flag)
    for flag in _semantic_weak_refinement_late_candidate_conflict_flags(
        validated,
        bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(validated, flag)
    for flag in _semantic_skeleton_tal_conflict_flags(validated, bio_data, analysis_profile=analysis_profile):
        _append_flag(validated, flag)
    for flag in _semantic_motion_cluster_conflict_flags(
        validated,
        motion_scores,
        analysis_profile=analysis_profile,
        bio_data=bio_data,
    ):
        _append_flag(validated, flag)
    return validated


def _video_confidence(video_temporal: dict[str, Any] | None, resolved_keyframes: dict[str, Any] | None = None) -> float:
    for source in (video_temporal, resolved_keyframes):
        if not isinstance(source, dict):
            continue
        try:
            return float(source.get("confidence"))
        except (TypeError, ValueError):
            continue
    return 0.0


def _unreliable_pose_fallback_late_candidate_motion_rejection(
    resolved_keyframes: dict[str, Any],
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None
    video_confidence = _video_confidence(
        resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else None,
        resolved_keyframes,
    )
    core_confidences = _semantic_core_confidence_values(resolved_keyframes)
    effective_confidence = (
        min(video_confidence, sum(core_confidences) / len(core_confidences))
        if core_confidences
        else video_confidence
    )
    if effective_confidence > SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MAX_CONFIDENCE:
        return None

    shifted_keys = [
        key
        for key in ("T", "A", "L")
        if skeleton_anchors[key]["timestamp"] - semantic_anchors[key]
        >= SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_SHIFT_SECONDS
    ]
    if len(shifted_keys) < SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_SHIFT_KEYS:
        return None

    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3:
        return None
    global_peak_record = max(records, key=lambda record: record["motion_score"])
    global_peak = float(global_peak_record["motion_score"])
    if global_peak < SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_GLOBAL_PEAK:
        return None

    semantic_start = min(semantic_anchors["T"], semantic_anchors["L"])
    semantic_end = max(semantic_anchors["T"], semantic_anchors["L"])
    candidate_window_values = [skeleton_anchors["T"]["timestamp"], skeleton_anchors["L"]["timestamp"]]
    for anchor in skeleton_anchors.values():
        start = _float_or_none(anchor.get("motion_window_start"))
        end = _float_or_none(anchor.get("motion_window_end"))
        if start is not None and end is not None:
            candidate_window_values.extend([start, end])
    candidate_start = min(candidate_window_values)
    candidate_end = max(candidate_window_values)
    candidate_start_after_semantic = candidate_start - semantic_end
    global_peak_after_semantic = global_peak_record["timestamp"] - semantic_end
    if (
        candidate_start_after_semantic < 0.0
        and global_peak_after_semantic
        < SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_GLOBAL_LAG_SEC
    ):
        return None

    semantic_peak = _peak_motion_in_window(records, semantic_start, semantic_end, tolerance=0.0)
    semantic_peak_with_tolerance = _peak_motion_in_window(records, semantic_start, semantic_end)
    candidate_peak = _peak_motion_in_window(records, candidate_start, candidate_end)
    semantic_peak_ratio = semantic_peak / max(global_peak, 1e-9)
    candidate_peak_ratio = candidate_peak / max(global_peak, 1e-9)
    candidate_to_semantic_peak_ratio = candidate_peak / max(semantic_peak, 1e-9)
    if semantic_peak_ratio > SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MAX_SEMANTIC_PEAK_RATIO:
        return None
    if candidate_peak_ratio < SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_CANDIDATE_PEAK_RATIO:
        return None
    if (
        candidate_to_semantic_peak_ratio
        < SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_CANDIDATE_TO_SEMANTIC_RATIO
    ):
        return None

    return {
        "global_peak_timestamp": round(global_peak_record["timestamp"], 3),
        "global_peak_motion_score": round(global_peak, 5),
        "semantic_window": {
            "start_sec": round(semantic_start, 3),
            "end_sec": round(semantic_end, 3),
            "peak_motion_score": round(semantic_peak, 5),
            "peak_motion_score_with_tolerance": round(semantic_peak_with_tolerance, 5),
        },
        "candidate_window": {
            "start_sec": round(candidate_start, 3),
            "end_sec": round(candidate_end, 3),
            "peak_motion_score": round(candidate_peak, 5),
        },
        "shifted_keys": shifted_keys,
        "semantic_peak_ratio": round(semantic_peak_ratio, 3),
        "candidate_peak_ratio": round(candidate_peak_ratio, 3),
        "candidate_to_semantic_peak_ratio": round(candidate_to_semantic_peak_ratio, 3),
        "global_peak_lag_after_semantic_sec": round(global_peak_after_semantic, 3),
        "semantic_effective_confidence": round(effective_confidence, 3),
        "semantic_video_confidence": round(video_confidence, 3),
    }


def _normalize_action_profile(value: object) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "jumps": "jump",
        "step_sequence": "step",
        "steps": "step",
        "spiral_line": "spiral",
        "spins": "spin",
    }
    return aliases.get(text, text)


def _provider_action_family(video_temporal: dict[str, Any] | None) -> str | None:
    if not isinstance(video_temporal, dict):
        return None
    action_confirmation = video_temporal.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        return None
    provider_family = _normalize_action_profile(action_confirmation.get("action_family"))
    return provider_family if provider_family in {"jump", "spin", "spiral", "step"} else None


def _non_jump_profile_mismatch_is_retryable(
    video_temporal: dict[str, Any],
    resolved_keyframes: dict[str, Any],
    *,
    analysis_profile: str | None,
    used_semantic_frames: bool | None,
) -> bool:
    requested = _normalize_action_profile(analysis_profile)
    if requested not in {"spin", "spiral", "step"}:
        return False
    provider_family = _provider_action_family(video_temporal)
    if provider_family is None or provider_family == requested:
        return False
    if used_semantic_frames is None:
        used_semantic_frames = semantic_keyframes_are_reliable(resolved_keyframes)
    if used_semantic_frames:
        return False
    flags = set(_quality_flags(video_temporal, resolved_keyframes))
    selected = resolved_keyframes.get("selected")
    has_selected = isinstance(selected, list) and bool(selected)
    return (
        not has_selected
        or "video_temporal_resolver_no_selected_frames" in flags
        or "video_temporal_resolver_no_semantic_selection" in flags
        or "semantic_keyframes_unreliable_fallback_to_sampled_frames" in flags
    )


def _semantic_core_anchors(resolved_keyframes: dict[str, Any]) -> dict[str, float]:
    anchors: dict[str, float] = {}
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return anchors
    for item in selected:
        if not isinstance(item, dict):
            continue
        phase_code = str(item.get("phase_code") or "")
        key_moment = str(item.get("key_moment") or "")
        label = None
        if phase_code == "takeoff" or key_moment.startswith("T_"):
            label = "T"
        elif phase_code == "air" or key_moment.startswith("A_"):
            label = "A"
        elif phase_code == "landing" or key_moment.startswith("L_"):
            label = "L"
        if label is None:
            continue
        try:
            anchors[label] = float(item.get("timestamp"))
        except (TypeError, ValueError):
            continue
    return anchors


def _semantic_core_confidence_values(resolved_keyframes: dict[str, Any]) -> list[float]:
    values: list[float] = []
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return values
    seen: set[str] = set()
    for item in selected:
        if not isinstance(item, dict):
            continue
        phase_code = str(item.get("phase_code") or "")
        key_moment = str(item.get("key_moment") or "")
        label = None
        if phase_code == "takeoff" or key_moment.startswith("T_"):
            label = "T"
        elif phase_code == "air" or key_moment.startswith("A_"):
            label = "A"
        elif phase_code == "landing" or key_moment.startswith("L_"):
            label = "L"
        if label is None or label in seen:
            continue
        confidence = _float_or_none(item.get("confidence"))
        if confidence is None:
            continue
        values.append(confidence)
        seen.add(label)
    return values


def _has_ordered_core_tal(resolved_keyframes: dict[str, Any]) -> bool:
    anchors = _semantic_core_anchors(resolved_keyframes)
    return (
        {"T", "A", "L"}.issubset(anchors)
        and anchors["T"] + 0.02 < anchors["A"]
        and anchors["A"] + 0.02 < anchors["L"]
    )


def _skeleton_candidate_anchors(bio_data: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    source = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(source, dict):
        return {}
    anchors: dict[str, dict[str, float]] = {}
    for key in ("T", "A", "L"):
        candidate = source.get(key)
        if not isinstance(candidate, dict):
            continue
        timestamp = _float_or_none(candidate.get("timestamp"))
        confidence = _float_or_none(candidate.get("confidence"))
        if timestamp is None or confidence is None:
            continue
        raw_confidence = confidence
        warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
        warning_values = {str(item).strip() for item in warnings}
        unreliable_pose_fallback = bool(
            warning_values
            & {
                "keyframe_candidates_motion_fallback_unreliable_pose_state",
                "tal_candidate_motion_fallback_low_visibility_weak_boundary",
            }
        )
        motion_window_occlusion_contaminated = "motion_window_occlusion_contaminated" in warning_values
        if unreliable_pose_fallback or motion_window_occlusion_contaminated:
            confidence = min(confidence, SEMANTIC_UNRELIABLE_POSE_FALLBACK_EFFECTIVE_CONFIDENCE_CAP)
        anchors[key] = {"timestamp": timestamp, "confidence": confidence, "raw_confidence": raw_confidence}
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        cluster = evidence.get("motion_cluster_window") if isinstance(evidence.get("motion_cluster_window"), dict) else {}
        cluster_start = _float_or_none(cluster.get("start_timestamp"))
        cluster_end = _float_or_none(cluster.get("end_timestamp"))
        if cluster_start is not None and cluster_end is not None and cluster_end >= cluster_start:
            anchors[key]["motion_window_start"] = cluster_start
            anchors[key]["motion_window_end"] = cluster_end
        motion_score = _float_or_none(evidence.get("motion_score"))
        if motion_score is not None:
            anchors[key]["motion_score"] = motion_score
        if unreliable_pose_fallback:
            anchors[key]["unreliable_pose_fallback"] = 1.0
        if motion_window_occlusion_contaminated:
            anchors[key]["motion_window_occlusion_contaminated"] = 1.0
    return anchors


def _keyframe_candidate_warnings(bio_data: dict[str, Any] | None, key: str) -> set[str]:
    source = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(source, dict):
        return set()
    candidate = source.get(key)
    if not isinstance(candidate, dict):
        return set()
    warnings = candidate.get("warnings")
    if not isinstance(warnings, list):
        return set()
    return {str(item).strip() for item in warnings if str(item).strip()}


def _keyframe_candidate_quality_flags(bio_data: dict[str, Any] | None) -> list[str]:
    source = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(source, dict):
        return []
    flags: list[str] = []
    for raw in source.get("quality_flags", []):
        value = str(raw).strip()
        if value and value not in flags:
            flags.append(value)
    for key in ("T", "A", "L"):
        candidate = source.get(key)
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


def _tracker_final_unrecovered_from_flags(bio_flags: set[str]) -> bool:
    return (
        "person_tracker_final_unrecovered" in bio_flags
        or "person_tracker_final_loss_unrecovered" in bio_flags
        or (
            "person_tracker_target_lost" in bio_flags
            and "person_tracker_transient_loss_recovered" not in bio_flags
            and bool(
                bio_flags
                & {
                    "person_tracker_relock_rejected",
                    "person_tracker_relock_pending",
                    "person_tracker_continuity_rejected",
                }
            )
        )
    )


def _tracker_final_loss_motion_fallback_has_bounded_tal_span(bio_data: dict[str, Any] | None) -> bool:
    anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(anchors):
        return True
    tal_span = anchors["L"]["timestamp"] - anchors["T"]["timestamp"]
    if tal_span <= 0:
        return False
    return tal_span <= SEMANTIC_TRACKER_FINAL_LOSS_MOTION_FALLBACK_MAX_TAL_SPAN_SEC


def _low_visibility_tracker_final_loss_motion_fallback_candidate(bio_data: dict[str, Any] | None) -> bool:
    bio_flags = set(_quality_flags(bio_data or {}))
    if not _tracker_final_unrecovered_from_flags(bio_flags):
        return False

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    required_flags = {
        "keyframe_candidates_motion_fallback",
        "tal_candidate_motion_fallback_low_precision",
        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
    }
    if not required_flags.issubset(candidate_flags):
        return False

    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return False

    timestamps: dict[str, float] = {}
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            return False
        timestamp = _float_or_none(candidate.get("timestamp"))
        confidence = _float_or_none(candidate.get("confidence"))
        if timestamp is None or confidence is None:
            return False
        if confidence > SEMANTIC_TRACKER_FINAL_LOSS_LOW_VISIBILITY_CANDIDATE_MAX_CONFIDENCE:
            return False

        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        if evidence.get("motion_fallback") is not True:
            return False
        pose_visibility = _float_or_none(evidence.get("visibility_score"))
        if pose_visibility is None:
            pose_visibility = _float_or_none((evidence.get("score_components") or {}).get("pose_visibility"))
        if pose_visibility is None or pose_visibility > SEMANTIC_TRACKER_FINAL_LOSS_LOW_VISIBILITY_MAX_POSE_VISIBILITY:
            return False
        timestamps[key] = timestamp

    tal_span = timestamps["L"] - timestamps["T"]
    return 0.0 < tal_span <= SEMANTIC_TRACKER_FINAL_LOSS_LOW_VISIBILITY_MAX_TAL_SPAN_SEC


def _low_visibility_motion_fallback_candidate_keys(bio_data: dict[str, Any] | None) -> set[str]:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return set()

    keys: set[str] = set()
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            continue
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
        warning_set = {str(warning).strip() for warning in warnings if str(warning).strip()}
        motion_fallback = evidence.get("motion_fallback") is True or "keyframe_candidates_motion_fallback" in warning_set
        if not motion_fallback:
            continue
        pose_visibility = _float_or_none(evidence.get("visibility_score"))
        if pose_visibility is None:
            score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
            pose_visibility = _float_or_none(score_components.get("pose_visibility"))
        if pose_visibility is None or pose_visibility > SEMANTIC_PHASE_RANGE_LOW_VISIBILITY_CANDIDATE_MAX_VISIBILITY:
            continue
        keys.add(key)
    return keys


def _takeoff_anchor_low_visibility_boundary_candidate_context(bio_data: dict[str, Any] | None) -> bool:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return False
    low_visibility_keys = _low_visibility_motion_fallback_candidate_keys(bio_data)
    if not {"A", "L"}.issubset(low_visibility_keys):
        return False

    takeoff = candidates.get("T")
    if not isinstance(takeoff, dict):
        return False
    evidence = takeoff.get("evidence") if isinstance(takeoff.get("evidence"), dict) else {}
    boundary = evidence.get("motion_fallback_low_visibility_weak_boundary")
    if not isinstance(boundary, dict):
        boundary = candidates.get("motion_fallback_low_visibility_weak_boundary")
    if not isinstance(boundary, dict):
        return False
    if str(boundary.get("reason") or "") != "takeoff_anchor_low_visibility_motion_only_boundary":
        return False
    roles = boundary.get("low_visibility_motion_roles")
    if not isinstance(roles, list) or not {"A", "L"}.issubset({str(item) for item in roles}):
        return False

    score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
    takeoff_timing = _float_or_none(score_components.get("takeoff_timing"))
    joint_extension_ascent = _float_or_none(score_components.get("takeoff_joint_extension_ascent"))
    takeoff_event = _float_or_none(score_components.get("takeoff_event"))
    warnings = takeoff.get("warnings") if isinstance(takeoff.get("warnings"), list) else []
    warning_set = {str(warning).strip() for warning in warnings if str(warning).strip()}
    weak_timing = takeoff_timing is not None and takeoff_timing <= 0.12
    weak_joint_ascent = joint_extension_ascent is not None and joint_extension_ascent <= 0.12
    weak_event = takeoff_event is not None and takeoff_event <= 0.35
    weak_warning = bool(warning_set & {"knee_extension_weak", "takeoff_timing_window_weak", "takeoff_geometry_weak"})
    return (weak_timing or "takeoff_timing_window_weak" in warning_set) and (
        weak_joint_ascent or weak_event or weak_warning
    )


def _candidate_pose_visibility(candidate: dict[str, Any]) -> float | None:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    pose_visibility = _float_or_none(evidence.get("visibility_score"))
    if pose_visibility is None:
        score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
        pose_visibility = _float_or_none(score_components.get("pose_visibility"))
    return pose_visibility


def _bounded_motion_fallback_conflict_has_pose_support(
    bio_data: dict[str, Any] | None,
    conflict_keys: set[str],
) -> bool:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return False
    for key in conflict_keys:
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            continue
        pose_visibility = _candidate_pose_visibility(candidate)
        if (
            pose_visibility is not None
            and pose_visibility >= SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_MIN_POSE_VISIBILITY
        ):
            return True
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
        if any(
            _float_or_none(score_components.get(key_name)) is not None
            for key_name in (
                "knee_angle_change",
                "knee_extension",
                "com_ascent",
                "ankle_return",
                "knee_absorption",
                "com_descent",
            )
        ):
            return True
    return False


def _insufficient_pose_low_visibility_motion_fallback_keys(bio_data: dict[str, Any] | None) -> set[str]:
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    has_insufficient_pose_context = SEMANTIC_INSUFFICIENT_POSE_LOW_VISIBILITY_MOTION_FALLBACK_FLAGS.issubset(
        candidate_flags
    )
    has_bounded_low_visibility_context = SEMANTIC_BOUNDED_LOW_VISIBILITY_MOTION_FALLBACK_FLAGS.issubset(
        candidate_flags
    )
    if not has_insufficient_pose_context and not has_bounded_low_visibility_context:
        return set()
    return _low_visibility_motion_fallback_candidate_keys(bio_data)


def _has_insufficient_pose_low_visibility_motion_fallback(
    bio_data: dict[str, Any] | None,
    *,
    required_keys: set[str] | None = None,
) -> bool:
    low_visibility_keys = _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
    if required_keys:
        return required_keys.issubset(low_visibility_keys)
    return len(low_visibility_keys) >= SEMANTIC_PHASE_RANGE_LOW_VISIBILITY_CANDIDATE_MIN_KEYS


def _motion_fallback_time_bounds(bio_data: dict[str, Any] | None) -> tuple[float | None, float | None]:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return None, None
    bounds = candidates.get("motion_fallback_time_bounds")
    if not isinstance(bounds, dict):
        return None, None
    start = _float_or_none(bounds.get("start_timestamp"))
    if start is None:
        start = _float_or_none(bounds.get("start_sec"))
    end = _float_or_none(bounds.get("end_timestamp"))
    if end is None:
        end = _float_or_none(bounds.get("end_sec"))
    return start, end


def _candidate_final_fallback_blocked_by_weak_takeoff_apex(bio_data: dict[str, Any] | None) -> bool:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return False
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    if "tal_candidate_takeoff_geometry_weak" not in candidate_flags and "takeoff_geometry_weak" not in candidate_flags:
        return False

    takeoff = candidates.get("T")
    apex = candidates.get("A")
    if not isinstance(takeoff, dict) or not isinstance(apex, dict):
        return False

    takeoff_ts = _float_or_none(takeoff.get("timestamp"))
    apex_ts = _float_or_none(apex.get("timestamp"))
    compressed_takeoff_apex = (
        takeoff_ts is not None
        and apex_ts is not None
        and 0.0 <= (apex_ts - takeoff_ts) <= SEMANTIC_WEAK_TAKEOFF_APEX_MAX_GAP_SEC
    )
    if not compressed_takeoff_apex:
        return False

    apex_warning_set = _keyframe_candidate_warnings(bio_data, "A")
    weak_apex = bool(apex_warning_set & SEMANTIC_WEAK_TAKEOFF_APEX_WARNINGS)
    if not weak_apex:
        return False

    takeoff_warning_set = _keyframe_candidate_warnings(bio_data, "T")
    return bool(takeoff_warning_set & {"takeoff_geometry_weak", "knee_extension_weak", "com_ascent_weak"})


def _late_pose_core_candidate_final_fallback_allowed(bio_data: dict[str, Any] | None) -> bool:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return False
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    if "keyframe_candidates_late_pose_core_reselected" not in candidate_flags:
        return False

    timestamps: dict[str, float] = {}
    confidences: list[float] = []
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            return False
        timestamp = _float_or_none(candidate.get("timestamp"))
        confidence = _float_or_none(candidate.get("confidence"))
        if timestamp is None or confidence is None:
            return False
        timestamps[key] = timestamp
        confidences.append(confidence)

    if min(confidences) < SEMANTIC_LATE_POSE_CORE_FALLBACK_MIN_CONFIDENCE:
        return False
    takeoff_apex_gap = timestamps["A"] - timestamps["T"]
    apex_landing_gap = timestamps["L"] - timestamps["A"]
    if takeoff_apex_gap < SEMANTIC_LATE_POSE_CORE_FALLBACK_MIN_TAKEOFF_APEX_GAP_SEC:
        return False
    if apex_landing_gap < SEMANTIC_LATE_POSE_CORE_FALLBACK_MIN_APEX_LANDING_GAP_SEC:
        return False
    if candidate_flags & {
        "tal_candidate_apex_landing_gap_compressed",
        "tal_candidate_core_gap_compressed",
        "tal_candidate_confidence_low",
    }:
        return False
    return True


def _fallback_selected_from_keyframe_candidates(bio_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return []
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    allow_occluded_motion_window = "tal_candidate_motion_window_occlusion_contaminated" in candidate_flags
    allow_late_pose_core_candidate = _late_pose_core_candidate_final_fallback_allowed(bio_data)
    blocking_flags = (
        SEMANTIC_CANDIDATE_FINAL_FALLBACK_BLOCKING_FLAGS
        - {
            "tal_candidate_motion_window_occlusion_contaminated",
            "tal_candidate_landing_geometry_weak",
            "landing_geometry_weak",
        }
        if allow_occluded_motion_window
        else SEMANTIC_CANDIDATE_FINAL_FALLBACK_BLOCKING_FLAGS
    )
    if allow_late_pose_core_candidate:
        blocking_flags = blocking_flags - (
            SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
            | SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS
            | {
                "tal_candidate_weak_geometry",
                "tal_candidate_landing_geometry_weak",
                "landing_geometry_weak",
            }
        )
    if candidate_flags & blocking_flags:
        return []
    if _candidate_final_fallback_blocked_by_weak_takeoff_apex(bio_data):
        return []
    if _has_long_unresolved_low_precision_motion_fallback(bio_data):
        return []

    selected: list[dict[str, Any]] = []
    confidences: list[float] = []
    for index, (key, phase_code, key_moment) in enumerate(
        (
            ("T", "takeoff", "T_takeoff_sec"),
            ("A", "air", "A_air_sec"),
            ("L", "landing", "L_landing_sec"),
        ),
        start=1,
    ):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            return []
        timestamp = _float_or_none(candidate.get("timestamp"))
        if timestamp is None:
            return []
        confidence = _float_or_none(candidate.get("confidence"))
        confidence_value = float(confidence if confidence is not None else 0.0)
        confidences.append(confidence_value)
        frame_id = str(candidate.get("frame_id") or f"frame_{index:04d}").strip()
        selected.append(
            {
                "frame_id": frame_id,
                "timestamp": round(timestamp, 3),
                "phase_code": phase_code,
                "phase_label": {"takeoff": "起跳", "air": "腾空", "landing": "落冰"}[phase_code],
                "key_moment": key_moment,
                "selection_reason": "fallback_to_keyframe_candidates",
                "confidence": round(max(0.0, min(confidence_value, 1.0)), 3),
            }
        )
    if not (selected[0]["timestamp"] < selected[1]["timestamp"] < selected[2]["timestamp"]):
        return []
    if allow_occluded_motion_window:
        if (
            sum(confidences) / len(confidences) < SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MIN_AVG_CONFIDENCE
            or min(confidences[0], confidences[2]) < SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MIN_BOUNDARY_CONFIDENCE
        ):
            return []
    return selected


def _numeric_motion_records_from_scores(motion_scores: dict[str, object] | None) -> list[dict[str, float | str]]:
    records: list[dict[str, float | str]] = []
    for raw in _resolver_motion_records_from_scores(motion_scores):
        if not isinstance(raw, dict):
            continue
        timestamp = _float_or_none(raw.get("timestamp"))
        motion_score = _float_or_none(raw.get("motion_score"))
        if timestamp is None or motion_score is None:
            continue
        record: dict[str, float | str] = {
            "timestamp": timestamp,
            "motion_score": motion_score,
        }
        frame_id = str(raw.get("frame_id") or "").strip()
        if frame_id:
            record["frame_id"] = frame_id
        records.append(record)
    records.sort(key=lambda record: float(record["timestamp"]))
    return records


def _nearest_motion_record(
    records: Sequence[dict[str, float | str]],
    timestamp: float,
) -> dict[str, float | str] | None:
    if not records:
        return None
    return min(records, key=lambda record: abs(float(record["timestamp"]) - timestamp))


def _motion_aligned_candidate_fallback_selected(
    *,
    bio_data: dict[str, Any] | None,
    motion_scores: dict[str, object] | None,
    analysis_profile: str | None,
    video_duration_sec: float | None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return [], [], None
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return [], [], None

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    blocking_flags = sorted(candidate_flags & SEMANTIC_MOTION_ALIGNED_CANDIDATE_BLOCKING_FLAGS)
    if blocking_flags:
        return [], [], {"decision": "blocked_candidate_quality_flags", "blocking_flags": blocking_flags}

    candidate_records: dict[str, dict[str, Any]] = {}
    timestamps: dict[str, float] = {}
    frame_ids: dict[str, str] = {}
    confidences: dict[str, float] = {}
    for key in ("T", "A", "L"):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            return [], [], {"decision": "missing_candidate", "missing_key": key}
        timestamp = _float_or_none(candidate.get("timestamp"))
        frame_id = str(candidate.get("frame_id") or "").strip()
        if timestamp is None or not frame_id:
            return [], [], {"decision": "candidate_missing_timestamp_or_frame_id", "key": key}
        candidate_records[key] = candidate
        timestamps[key] = timestamp
        frame_ids[key] = frame_id
        confidences[key] = max(
            SEMANTIC_MOTION_ALIGNED_CANDIDATE_CONFIDENCE,
            min(1.0, _float_or_none(candidate.get("confidence")) or 0.0),
        )

    t_value = timestamps["T"]
    a_value = timestamps["A"]
    l_value = timestamps["L"]
    span = l_value - t_value
    if not (
        t_value + SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_GAP_SEC <= a_value
        and a_value + SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_GAP_SEC <= l_value
        and SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_SPAN_SEC <= span <= SEMANTIC_MOTION_ALIGNED_CANDIDATE_MAX_SPAN_SEC
    ):
        return [], [], {
            "decision": "candidate_temporal_geometry_rejected",
            "timestamps": {key: round(value, 3) for key, value in timestamps.items()},
            "span_sec": round(span, 3),
        }

    duration = _float_or_none(video_duration_sec)
    if duration is not None and (t_value < -0.001 or l_value > duration + SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC):
        return [], [], {"decision": "candidate_outside_video_duration", "duration_sec": round(duration, 3)}
    safe_duration = max(duration or 0.0, l_value + SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC)

    records = _numeric_motion_records_from_scores(motion_scores)
    if not records:
        return [], [], {"decision": "missing_motion_records"}
    global_peak = max(records, key=lambda record: float(record["motion_score"]))
    global_peak_ts = float(global_peak["timestamp"])
    global_peak_score = float(global_peak["motion_score"])

    window_start = t_value - SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC
    window_end = l_value + SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC
    window_records = [
        record
        for record in records
        if window_start <= float(record["timestamp"]) <= window_end
    ]
    if len(window_records) < SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_RECORDS:
        return [], [], {
            "decision": "insufficient_candidate_window_motion_records",
            "candidate_window_record_count": len(window_records),
        }
    candidate_peak = max(window_records, key=lambda record: float(record["motion_score"]))
    candidate_peak_score = float(candidate_peak["motion_score"])
    candidate_peak_ts = float(candidate_peak["timestamp"])
    if candidate_peak_score < SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_PEAK_SCORE:
        return [], [], {
            "decision": "candidate_window_motion_too_weak",
            "candidate_peak_score": round(candidate_peak_score, 4),
        }
    global_peak_inside_candidate_window = (
        t_value - SEMANTIC_MOTION_ALIGNED_CANDIDATE_GLOBAL_PEAK_TOLERANCE_SEC
        <= global_peak_ts
        <= l_value + SEMANTIC_MOTION_ALIGNED_CANDIDATE_GLOBAL_PEAK_TOLERANCE_SEC
    )
    if (
        not global_peak_inside_candidate_window
        and global_peak_score > 0
        and candidate_peak_score < global_peak_score * SEMANTIC_MOTION_ALIGNED_CANDIDATE_REMOTE_GLOBAL_RATIO
    ):
        return [], [], {
            "decision": "candidate_window_not_dominant_motion_cluster",
            "candidate_peak_timestamp": round(candidate_peak_ts, 3),
            "candidate_peak_score": round(candidate_peak_score, 4),
            "global_peak_timestamp": round(global_peak_ts, 3),
            "global_peak_score": round(global_peak_score, 4),
        }

    strong_floor = max(
        SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_KEY_SCORE,
        candidate_peak_score * SEMANTIC_MOTION_ALIGNED_CANDIDATE_STRONG_RATIO,
    )
    strong_records = [
        record
        for record in window_records
        if float(record["motion_score"]) >= strong_floor
    ]
    if len(strong_records) < SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_RECORDS:
        return [], [], {
            "decision": "insufficient_strong_candidate_window_motion_records",
            "strong_record_count": len(strong_records),
            "strong_floor": round(strong_floor, 4),
        }

    key_diagnostics: dict[str, dict[str, Any]] = {}
    for key, timestamp in timestamps.items():
        nearest = _nearest_motion_record(window_records, timestamp)
        if nearest is None:
            return [], [], {"decision": "missing_nearest_key_motion_record", "key": key}
        nearest_ts = float(nearest["timestamp"])
        nearest_score = float(nearest["motion_score"])
        delta = abs(nearest_ts - timestamp)
        key_diagnostics[key] = {
            "candidate_timestamp": round(timestamp, 3),
            "nearest_motion_timestamp": round(nearest_ts, 3),
            "nearest_motion_score": round(nearest_score, 4),
            "delta_sec": round(delta, 3),
        }
        if delta > SEMANTIC_MOTION_ALIGNED_CANDIDATE_MAX_KEY_DELTA_SEC:
            return [], [], {
                "decision": "candidate_key_motion_alignment_rejected",
                "key": key,
                "key_motion_alignment": key_diagnostics,
            }
        if nearest_score < SEMANTIC_MOTION_ALIGNED_CANDIDATE_MIN_KEY_SCORE:
            return [], [], {
                "decision": "candidate_key_motion_score_too_weak",
                "key": key,
                "key_motion_alignment": key_diagnostics,
            }

    phase_specs = (
        ("T", "takeoff", "T_takeoff_sec"),
        ("A", "air", "A_air_sec"),
        ("L", "landing", "L_landing_sec"),
    )
    phase_bounds = {
        "T": (
            max(0.0, t_value - SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC),
            min(safe_duration, t_value + SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC, a_value - 0.02),
        ),
        "A": (
            max(0.0, t_value + 0.02, a_value - SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC),
            min(safe_duration, l_value - 0.02, a_value + SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC),
        ),
        "L": (
            max(0.0, a_value + 0.02, l_value - SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC),
            min(safe_duration, l_value + SEMANTIC_MOTION_ALIGNED_CANDIDATE_WINDOW_PADDING_SEC),
        ),
    }
    selected: list[dict[str, Any]] = []
    for index, (key, phase_code, key_moment) in enumerate(phase_specs, start=1):
        start, end = phase_bounds[key]
        selected.append(
            {
                "frame_id": frame_ids[key] or f"semantic_{index:04d}",
                "timestamp": round(timestamps[key], 3),
                "phase_code": phase_code,
                "phase_label": phase_code,
                "key_moment": key_moment,
                "selection_reason": "motion_aligned_keyframe_candidate",
                "confidence": round(confidences[key], 3),
                "phase_time_start": round(start, 3),
                "phase_time_end": round(max(start, end), 3),
                "max_refinement_delta_sec": SEMANTIC_MOTION_ALIGNED_CANDIDATE_MAX_KEY_DELTA_SEC,
            }
        )
        warnings = _keyframe_candidate_warnings(bio_data, key)
        if warnings:
            selected[-1]["candidate_warnings"] = sorted(warnings)
    selected[-1]["visibility_repair_preserve_timestamp"] = True

    fallback_flags = [
        "video_temporal_resolver_motion_cluster_fallback_used",
        "video_temporal_quality_retry_motion_cluster_fallback_used",
        "semantic_keyframes_motion_aligned_candidate_fallback_used",
    ]
    if candidate_flags & (SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS | {"tal_candidate_confidence_low"}):
        fallback_flags.append("semantic_keyframes_motion_aligned_candidate_fallback_weak_candidate")
    if "tal_candidate_motion_fallback_low_precision" in candidate_flags:
        fallback_flags.append("semantic_keyframes_motion_aligned_candidate_fallback_low_precision")

    diagnostics = {
        "decision": "selected_motion_aligned_candidate_fallback",
        "candidate_timestamps": {key: round(value, 3) for key, value in timestamps.items()},
        "candidate_quality_flags": sorted(candidate_flags),
        "candidate_window": {
            "start_sec": round(window_start, 3),
            "end_sec": round(window_end, 3),
            "record_count": len(window_records),
            "strong_record_count": len(strong_records),
        },
        "candidate_peak_timestamp": round(candidate_peak_ts, 3),
        "candidate_peak_score": round(candidate_peak_score, 4),
        "global_peak_timestamp": round(global_peak_ts, 3),
        "global_peak_score": round(global_peak_score, 4),
        "global_peak_inside_candidate_window": global_peak_inside_candidate_window,
        "key_motion_alignment": key_diagnostics,
    }
    selected[0]["motion_cluster_diagnostics"] = diagnostics
    return selected, fallback_flags, diagnostics


def _motion_aligned_candidate_fallback_quality_flags(
    *sources: object,
) -> list[str]:
    flags = _merge_flags(*sources)
    return [flag for flag in flags if flag not in SEMANTIC_MOTION_ALIGNED_CANDIDATE_DROP_FLAGS]


def _has_long_unresolved_low_precision_motion_fallback(bio_data: dict[str, Any] | None) -> bool:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return False
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    if not (
        "keyframe_candidates_motion_fallback" in candidate_flags
        and "tal_candidate_motion_fallback_low_precision" in candidate_flags
        and bool(candidate_flags & {"tal_candidate_incomplete", "tal_order_unresolved"})
    ):
        return False
    candidate_timestamps = [
        _float_or_none(candidates.get(key, {}).get("timestamp"))
        for key in ("T", "A", "L")
        if isinstance(candidates.get(key), dict)
    ]
    return (
        len(candidate_timestamps) == 3
        and all(timestamp is not None for timestamp in candidate_timestamps)
        and max(candidate_timestamps) - min(candidate_timestamps)
        > SEMANTIC_TRACKER_FINAL_LOSS_MOTION_FALLBACK_MAX_TAL_SPAN_SEC
    )


def _long_unresolved_motion_fallback_reuse_override(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
) -> bool:
    return (
        _semantic_reuse_overrides_long_unresolved_motion_fallback(resolved_keyframes)
        and _has_long_unresolved_low_precision_motion_fallback(bio_data)
    )


def _candidate_tal_span_sec(bio_data: dict[str, Any] | None) -> float | None:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return None
    timestamps = [
        _float_or_none(candidates.get(key, {}).get("timestamp"))
        for key in ("T", "A", "L")
        if isinstance(candidates.get(key), dict)
    ]
    if len(timestamps) != 3 or any(timestamp is None for timestamp in timestamps):
        return None
    return round(max(timestamps) - min(timestamps), 3)


def _apply_unreliable_semantic_selected_fallback(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
) -> dict[str, Any]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return resolved_keyframes
    if _candidate_final_fallback_blocked_by_weak_takeoff_apex(bio_data):
        _append_flag(resolved_keyframes, "semantic_keyframes_candidate_fallback_rejected_weak_takeoff_apex")
        return resolved_keyframes
    fallback_selected = _fallback_selected_from_keyframe_candidates(bio_data)
    if not fallback_selected:
        return resolved_keyframes
    selected = resolved_keyframes.get("selected")
    if isinstance(selected, list) and selected and "rejected_semantic_selected" not in resolved_keyframes:
        resolved_keyframes["rejected_semantic_selected"] = [
            dict(item) if isinstance(item, dict) else item
            for item in selected
        ]
    resolved_keyframes["selected"] = fallback_selected
    resolved_keyframes["source"] = "skeleton_fallback"
    _append_flag(resolved_keyframes, "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates")
    return resolved_keyframes


def _bounded_motion_fallback_semantic_candidate_conflicts(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
) -> list[dict[str, float | str]]:
    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return []

    conflicts: list[dict[str, float | str]] = []
    for key, threshold in SEMANTIC_TRACKER_FINAL_LOSS_BOUNDED_FALLBACK_SHIFT_SECONDS.items():
        candidate = skeleton_anchors.get(key)
        if not isinstance(candidate, dict):
            continue
        confidence = float(candidate["confidence"])
        if confidence < SEMANTIC_TRACKER_FINAL_LOSS_BOUNDED_FALLBACK_MIN_CONFIDENCE:
            continue
        delta = semantic_anchors[key] - candidate["timestamp"]
        if abs(delta) < threshold:
            continue
        conflicts.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(candidate["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(confidence, 3),
                "candidate_raw_confidence": round(float(candidate.get("raw_confidence", confidence)), 3),
            }
        )
    if len(conflicts) < SEMANTIC_TRACKER_FINAL_LOSS_BOUNDED_FALLBACK_MIN_CONFLICT_KEYS:
        return []
    return conflicts


def _semantic_low_visibility_bounded_motion_fallback_drift_flags(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return []

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    required_candidate_flags = {
        "keyframe_candidates_motion_fallback",
        "tal_candidate_motion_fallback_low_precision",
        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
    }
    if not required_candidate_flags.issubset(candidate_flags):
        return []

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    video_flags = {
        str(flag).strip()
        for flag in _quality_flags(video_ai, resolved_keyframes)
        if str(flag).strip()
    }
    if not (video_flags & SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_CONTEXT_FLAGS):
        return []
    video_confidence = _float_or_none(video_ai.get("confidence"))
    if video_confidence is None:
        video_confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if (
        video_confidence is not None
        and video_confidence > SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_MAX_VIDEO_CONFIDENCE
    ):
        return []

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return []

    conflicts: list[dict[str, float | str]] = []
    for key, threshold in SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_SHIFT_SECONDS.items():
        candidate = skeleton_anchors.get(key)
        if not isinstance(candidate, dict):
            continue
        confidence = float(candidate["confidence"])
        if confidence < SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_MIN_CONFIDENCE:
            continue
        delta = semantic_anchors[key] - candidate["timestamp"]
        if delta < threshold:
            continue
        conflicts.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(candidate["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(confidence, 3),
                "candidate_raw_confidence": round(float(candidate.get("raw_confidence", confidence)), 3),
            }
        )
    if len(conflicts) < SEMANTIC_LOW_VISIBILITY_BOUNDED_FALLBACK_MIN_CONFLICT_KEYS:
        return []
    conflict_keys = {str(item.get("key")) for item in conflicts if isinstance(item.get("key"), str)}
    if not _bounded_motion_fallback_conflict_has_pose_support(bio_data, conflict_keys):
        resolved_keyframes["semantic_low_visibility_bounded_motion_fallback_drift"] = {
            "decision": "ignored_low_visibility_bounded_motion_fallback_without_pose_support",
            "conflicts": conflicts,
            "candidate_quality_flags": sorted(candidate_flags),
            "video_quality_flags": sorted(video_flags),
            "video_confidence": round(video_confidence, 3) if video_confidence is not None else None,
            "low_visibility_motion_fallback_keys": sorted(_low_visibility_motion_fallback_candidate_keys(bio_data)),
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_low_visibility_bounded_motion_fallback_ignored_no_pose_support",
        )
        return []

    start_bound, end_bound = _motion_fallback_time_bounds(bio_data)
    resolved_keyframes["semantic_low_visibility_bounded_motion_fallback_drift"] = {
        "decision": "rejected_low_visibility_bounded_motion_fallback_drift",
        "conflicts": conflicts,
        "candidate_quality_flags": sorted(candidate_flags),
        "video_quality_flags": sorted(video_flags),
        "video_confidence": round(video_confidence, 3) if video_confidence is not None else None,
        "bounds": {
            "start_timestamp": round(start_bound, 3) if start_bound is not None else None,
            "end_timestamp": round(end_bound, 3) if end_bound is not None else None,
        },
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift")
    return ["semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift"]


def _semantic_weak_refinement_late_candidate_conflict_flags(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return []

    candidate_flags = _keyframe_candidate_quality_flags(bio_data)
    if not (set(candidate_flags) & SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_CONTEXT_FLAGS):
        return []

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or len(skeleton_anchors) < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_KEYS:
        return []

    refinement_scores: dict[str, float] = {}
    for key in ("T", "L"):
        record = _core_record_by_key(resolved_keyframes, key)
        if record is None:
            continue
        score = _float_or_none(record.get("refinement_motion_score"))
        if score is not None:
            refinement_scores[key] = score
    if len(refinement_scores) < 2 or max(refinement_scores.values()) > SEMANTIC_WEAK_REFINEMENT_MAX_MOTION_SCORE:
        return []

    conflicts: list[dict[str, float | str]] = []
    for key in ("T", "A", "L"):
        candidate = skeleton_anchors.get(key)
        if not isinstance(candidate, dict):
            continue
        if candidate["confidence"] < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_CONFIDENCE:
            continue
        delta = semantic_anchors[key] - candidate["timestamp"]
        if delta >= SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_SHIFT_SECONDS:
            conflicts.append(
                {
                    "key": key,
                    "semantic_timestamp": round(semantic_anchors[key], 3),
                    "candidate_timestamp": round(candidate["timestamp"], 3),
                    "delta_sec": round(delta, 3),
                    "candidate_confidence": round(candidate["confidence"], 3),
                }
            )
    if len(conflicts) < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_KEYS:
        return []
    conflict_keys = {str(item.get("key")) for item in conflicts if isinstance(item.get("key"), str)}
    if _has_insufficient_pose_low_visibility_motion_fallback(bio_data, required_keys=conflict_keys) and not _bounded_motion_fallback_conflict_has_pose_support(
        bio_data,
        conflict_keys,
    ):
        resolved_keyframes["semantic_weak_refinement_late_candidate_conflict"] = {
            "conflicts": conflicts,
            "refinement_motion_scores": {key: round(value, 4) for key, value in refinement_scores.items()},
            "candidate_quality_flags": candidate_flags,
            "low_visibility_motion_fallback_keys": sorted(_insufficient_pose_low_visibility_motion_fallback_keys(bio_data)),
            "decision": "ignored_low_visibility_refinement_conflict_without_pose_support",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_weak_refinement_late_candidate_conflict_ignored_low_visibility_no_pose_support",
        )
        return []

    resolved_keyframes["semantic_weak_refinement_late_candidate_conflict"] = {
        "conflicts": conflicts,
        "refinement_motion_scores": {key: round(value, 4) for key, value in refinement_scores.items()},
        "candidate_quality_flags": candidate_flags,
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict")
    return ["semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict"]


def _peak_motion_in_window(
    records: Sequence[dict[str, float]],
    start: float,
    end: float,
    *,
    tolerance: float = SEMANTIC_CANDIDATE_MOTION_WINDOW_TOLERANCE_SECONDS,
) -> float:
    return max(
        (
            record["motion_score"]
            for record in records
            if start - tolerance <= record["timestamp"] <= end + tolerance
        ),
        default=0.0,
    )


def _semantic_candidate_motion_window_conflict_diagnostic(
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    conflicts: Sequence[dict[str, float | str]],
    motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if len(conflicts) < SEMANTIC_CANDIDATE_MOTION_WINDOW_MIN_CONFLICT_KEYS:
        return None
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None
    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3:
        return None
    global_peak = max((record["motion_score"] for record in records), default=0.0)
    if global_peak < SEMANTIC_CANDIDATE_MOTION_WINDOW_MIN_GLOBAL_PEAK:
        return None

    semantic_start = min(semantic_anchors["T"], semantic_anchors["L"])
    semantic_end = max(semantic_anchors["T"], semantic_anchors["L"])
    candidate_window_values = [
        skeleton_anchors["T"]["timestamp"],
        skeleton_anchors["L"]["timestamp"],
    ]
    for anchor in skeleton_anchors.values():
        start = _float_or_none(anchor.get("motion_window_start"))
        end = _float_or_none(anchor.get("motion_window_end"))
        if start is not None and end is not None:
            candidate_window_values.extend([start, end])
    candidate_start = min(candidate_window_values)
    candidate_end = max(candidate_window_values)
    semantic_peak = _peak_motion_in_window(records, semantic_start, semantic_end)
    candidate_peak = _peak_motion_in_window(records, candidate_start, candidate_end)

    if candidate_peak < global_peak * SEMANTIC_CANDIDATE_MOTION_WINDOW_CANDIDATE_PEAK_RATIO:
        return None
    candidate_beats_semantic = (
        candidate_peak >= semantic_peak * SEMANTIC_CANDIDATE_MOTION_WINDOW_MIN_CANDIDATE_TO_SEMANTIC_RATIO
        and candidate_peak - semantic_peak >= SEMANTIC_CANDIDATE_MOTION_WINDOW_MIN_CANDIDATE_TO_SEMANTIC_DELTA
    )
    if (
        semantic_peak >= global_peak * SEMANTIC_CANDIDATE_MOTION_WINDOW_SEMANTIC_PEAK_RATIO
        and not candidate_beats_semantic
    ):
        return None

    peak_record = max(records, key=lambda record: record["motion_score"])
    return {
        "global_peak_timestamp": round(peak_record["timestamp"], 3),
        "global_peak_motion_score": round(global_peak, 5),
        "semantic_window": {
            "start_sec": round(semantic_start, 3),
            "end_sec": round(semantic_end, 3),
            "peak_motion_score": round(semantic_peak, 5),
        },
        "candidate_window": {
            "start_sec": round(candidate_start, 3),
            "end_sec": round(candidate_end, 3),
            "peak_motion_score": round(candidate_peak, 5),
        },
        "candidate_peak_ratio": round(candidate_peak / max(global_peak, 1e-9), 3),
        "semantic_peak_ratio": round(semantic_peak / max(global_peak, 1e-9), 3),
        "candidate_to_semantic_peak_ratio": round(candidate_peak / max(semantic_peak, 1e-9), 3),
        "candidate_to_semantic_peak_delta": round(candidate_peak - semantic_peak, 5),
    }


def _semantic_candidate_tal_conflict_evidence(
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    conflicts: Sequence[dict[str, float | str]],
    candidate_flags: Sequence[str],
    motion_scores: dict[str, object] | None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "semantic_anchors": {
            key: round(timestamp, 3)
            for key, timestamp in semantic_anchors.items()
            if key in {"T", "A", "L"}
        },
        "candidate_anchors": {},
        "anchor_deltas_sec": {},
        "conflict_keys": sorted(
            {
                str(item.get("key"))
                for item in conflicts
                if isinstance(item, dict) and str(item.get("key") or "") in {"T", "A", "L"}
            }
        ),
    }
    for key in ("T", "A", "L"):
        candidate = skeleton_anchors.get(key)
        if not isinstance(candidate, dict):
            continue
        timestamp = _float_or_none(candidate.get("timestamp"))
        if timestamp is None:
            continue
        anchor: dict[str, Any] = {"timestamp": round(timestamp, 3)}
        confidence = _float_or_none(candidate.get("confidence"))
        raw_confidence = _float_or_none(candidate.get("raw_confidence"))
        motion_score = _float_or_none(candidate.get("motion_score"))
        if confidence is not None:
            anchor["confidence"] = round(confidence, 3)
        if raw_confidence is not None and raw_confidence != confidence:
            anchor["raw_confidence"] = round(raw_confidence, 3)
        if motion_score is not None:
            anchor["motion_score"] = round(motion_score, 5)
        window_start = _float_or_none(candidate.get("motion_window_start"))
        window_end = _float_or_none(candidate.get("motion_window_end"))
        if window_start is not None and window_end is not None:
            anchor["motion_window"] = {
                "start_sec": round(window_start, 3),
                "end_sec": round(window_end, 3),
            }
        evidence["candidate_anchors"][key] = anchor
        semantic_timestamp = semantic_anchors.get(key)
        if semantic_timestamp is not None:
            evidence["anchor_deltas_sec"][key] = round(semantic_timestamp - timestamp, 3)

    candidate_timestamps = [
        float(anchor["timestamp"])
        for anchor in evidence["candidate_anchors"].values()
        if isinstance(anchor, dict) and isinstance(anchor.get("timestamp"), (int, float))
    ]
    semantic_timestamps = [
        float(timestamp)
        for key, timestamp in semantic_anchors.items()
        if key in {"T", "A", "L"}
    ]
    if len(candidate_timestamps) >= 2:
        evidence["candidate_span_sec"] = round(max(candidate_timestamps) - min(candidate_timestamps), 3)
    if len(semantic_timestamps) >= 2:
        evidence["semantic_span_sec"] = round(max(semantic_timestamps) - min(semantic_timestamps), 3)

    flag_set = set(candidate_flags)
    unreliable_reasons = sorted(
        flag_set
        & (
            SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
            | SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS
            | SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS
            | SEMANTIC_CANDIDATE_UNRELIABLE_POSE_FALLBACK_FLAGS
        )
    )
    if unreliable_reasons:
        evidence["untrusted_candidate_reasons"] = unreliable_reasons

    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3 or not {"T", "L"}.issubset(semantic_anchors):
        return evidence

    candidate_window_values = list(candidate_timestamps)
    for anchor in evidence["candidate_anchors"].values():
        if not isinstance(anchor, dict):
            continue
        motion_window = anchor.get("motion_window")
        if not isinstance(motion_window, dict):
            continue
        start = _float_or_none(motion_window.get("start_sec"))
        end = _float_or_none(motion_window.get("end_sec"))
        if start is not None and end is not None:
            candidate_window_values.extend([start, end])
    if len(candidate_window_values) < 2:
        return evidence

    global_peak_record = max(records, key=lambda record: record["motion_score"])
    global_peak = float(global_peak_record["motion_score"])
    semantic_start = min(semantic_anchors["T"], semantic_anchors["L"])
    semantic_end = max(semantic_anchors["T"], semantic_anchors["L"])
    candidate_start = min(candidate_window_values)
    candidate_end = max(candidate_window_values)
    semantic_peak = _peak_motion_in_window(records, semantic_start, semantic_end)
    candidate_peak = _peak_motion_in_window(records, candidate_start, candidate_end)

    def nearest_motion(timestamp: float | None) -> dict[str, float] | None:
        if timestamp is None:
            return None
        record = min(records, key=lambda item: abs(item["timestamp"] - timestamp))
        return {
            "timestamp": round(record["timestamp"], 3),
            "motion_score": round(record["motion_score"], 5),
            "delta_sec": round(timestamp - record["timestamp"], 3),
        }

    labels: list[str] = []
    if flag_set & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS:
        labels.append("candidate_temporal_geometry_unreliable")
    if flag_set & SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS:
        labels.append("candidate_pose_geometry_weak")
    if flag_set & (SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS | SEMANTIC_CANDIDATE_UNRELIABLE_POSE_FALLBACK_FLAGS):
        labels.append("candidate_motion_fallback_or_occlusion_risk")
    if (
        global_peak > 0
        and candidate_peak >= global_peak * SEMANTIC_CANDIDATE_MOTION_WINDOW_CANDIDATE_PEAK_RATIO
        and semantic_peak < global_peak * SEMANTIC_CANDIDATE_MOTION_WINDOW_SEMANTIC_PEAK_RATIO
    ):
        labels.append("candidate_window_dominant_full_frame_motion_over_semantic_window")

    evidence["motion_context"] = {
        "global_peak_timestamp": round(global_peak_record["timestamp"], 3),
        "global_peak_motion_score": round(global_peak, 5),
        "semantic_window": {
            "start_sec": round(semantic_start, 3),
            "end_sec": round(semantic_end, 3),
            "peak_motion_score": round(semantic_peak, 5),
            "peak_ratio": round(semantic_peak / max(global_peak, 1e-9), 3),
        },
        "candidate_window": {
            "start_sec": round(candidate_start, 3),
            "end_sec": round(candidate_end, 3),
            "peak_motion_score": round(candidate_peak, 5),
            "peak_ratio": round(candidate_peak / max(global_peak, 1e-9), 3),
        },
        "nearest_motion_to_semantic": {
            key: nearest_motion(semantic_anchors.get(key))
            for key in ("T", "A", "L")
            if key in semantic_anchors
        },
        "nearest_motion_to_candidate": {
            key: nearest_motion(_float_or_none(anchor.get("timestamp")) if isinstance(anchor, dict) else None)
            for key, anchor in evidence["candidate_anchors"].items()
        },
    }
    if labels:
        evidence["motion_context"]["diagnostic_labels"] = labels
    return evidence


def _semantic_candidate_takeoff_single_conflict_diagnostic(
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    conflicts: Sequence[dict[str, float | str]],
    motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None
    takeoff = skeleton_anchors["T"]
    takeoff_delta = semantic_anchors["T"] - takeoff["timestamp"]
    if abs(takeoff_delta) < SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_SHIFT_SECONDS:
        return None
    if takeoff["confidence"] < SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MIN_CONFIDENCE:
        return None
    takeoff_motion = _float_or_none(takeoff.get("motion_score"))
    if takeoff_motion is None or takeoff_motion < SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MIN_MOTION_SCORE:
        return None
    records = _motion_records_from_scores(motion_scores)
    semantic_takeoff_peak = _peak_motion_in_window(
        records,
        semantic_anchors["T"],
        semantic_anchors["T"],
        tolerance=SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MOTION_WINDOW_SECONDS,
    )
    candidate_takeoff_peak = max(
        takeoff_motion,
        _peak_motion_in_window(
            records,
            takeoff["timestamp"],
            takeoff["timestamp"],
            tolerance=SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MOTION_WINDOW_SECONDS,
        ),
    )
    if semantic_takeoff_peak > 0 and (
        candidate_takeoff_peak
        < semantic_takeoff_peak * SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MOTION_RATIO
    ):
        return None

    aligned_keys: list[str] = []
    for key in ("A", "L"):
        candidate = skeleton_anchors[key]
        delta = semantic_anchors[key] - candidate["timestamp"]
        if abs(delta) <= SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_CORE_ALIGNMENT_SECONDS:
            aligned_keys.append(key)
    if len(aligned_keys) < 2:
        return None

    matching_conflict = next((item for item in conflicts if item.get("key") == "T"), None)
    return {
        "conflict": matching_conflict
        or {
            "key": "T",
            "semantic_timestamp": round(semantic_anchors["T"], 3),
            "candidate_timestamp": round(takeoff["timestamp"], 3),
            "delta_sec": round(takeoff_delta, 3),
            "candidate_confidence": round(takeoff["confidence"], 3),
        },
        "aligned_core_keys": aligned_keys,
        "candidate_takeoff_motion_score": round(candidate_takeoff_peak, 5),
        "semantic_takeoff_motion_score": round(semantic_takeoff_peak, 5),
    }


def _semantic_candidate_early_takeoff_conflict_diagnostic(
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    conflicts: Sequence[dict[str, float | str]],
    motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None
    takeoff = skeleton_anchors["T"]
    apex = skeleton_anchors["A"]
    landing = skeleton_anchors["L"]
    takeoff_delta = takeoff["timestamp"] - semantic_anchors["T"]
    if takeoff_delta < SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_SHIFT_SECONDS:
        return None
    if takeoff["confidence"] < SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_CONFIDENCE:
        return None
    if (
        apex["confidence"] < SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_CORE_CONFIDENCE
        or landing["confidence"] < SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_CORE_CONFIDENCE
    ):
        return None
    if not (
        takeoff["timestamp"] + SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_TAKEOFF_APEX_GAP_SECONDS
        <= apex["timestamp"]
        and apex["timestamp"] + SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MIN_APEX_LANDING_GAP_SECONDS
        <= landing["timestamp"]
    ):
        return None

    apex_delta = abs(semantic_anchors["A"] - apex["timestamp"])
    landing_delta = abs(semantic_anchors["L"] - landing["timestamp"])
    if (
        apex_delta > SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MAX_APEX_DELTA_SECONDS
        or landing_delta > SEMANTIC_CANDIDATE_TAKEOFF_EARLY_SEMANTIC_MAX_LANDING_DELTA_SECONDS
    ):
        return None

    records = _motion_records_from_scores(motion_scores)
    semantic_takeoff_peak = _peak_motion_in_window(
        records,
        semantic_anchors["T"],
        semantic_anchors["T"],
        tolerance=SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MOTION_WINDOW_SECONDS,
    )
    candidate_takeoff_peak = max(
        _float_or_none(takeoff.get("motion_score")) or 0.0,
        _peak_motion_in_window(
            records,
            takeoff["timestamp"],
            takeoff["timestamp"],
            tolerance=SEMANTIC_CANDIDATE_TAKEOFF_SINGLE_CONFLICT_MOTION_WINDOW_SECONDS,
        ),
    )
    matching_conflict = next((item for item in conflicts if item.get("key") == "T"), None)
    return {
        "conflict": matching_conflict
        or {
            "key": "T",
            "semantic_timestamp": round(semantic_anchors["T"], 3),
            "candidate_timestamp": round(takeoff["timestamp"], 3),
            "delta_sec": round(semantic_anchors["T"] - takeoff["timestamp"], 3),
            "candidate_confidence": round(takeoff["confidence"], 3),
        },
        "aligned_core_keys": ["A", "L"],
        "candidate_takeoff_motion_score": round(candidate_takeoff_peak, 5),
        "semantic_takeoff_motion_score": round(semantic_takeoff_peak, 5),
        "candidate_core_confidences": {
            "T": round(takeoff["confidence"], 3),
            "A": round(apex["confidence"], 3),
            "L": round(landing["confidence"], 3),
        },
        "core_delta_sec": {
            "T": round(takeoff_delta, 3),
            "A": round(semantic_anchors["A"] - apex["timestamp"], 3),
            "L": round(semantic_anchors["L"] - landing["timestamp"], 3),
        },
        "support_mode": "early_semantic_takeoff_over_ordered_candidate_core",
    }


def _late_pose_core_candidate_conflict_should_reject(
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if "keyframe_candidates_late_pose_core_reselected" not in set(candidate_flags):
        return None
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None

    candidate_timestamps = [skeleton_anchors[key]["timestamp"] for key in ("T", "A", "L")]
    if max(candidate_timestamps) - min(candidate_timestamps) > SEMANTIC_LATE_POSE_CORE_CONFLICT_MAX_SPAN_SECONDS:
        return None

    shifted: list[dict[str, float | str]] = []
    for key in ("T", "A", "L"):
        candidate = skeleton_anchors[key]
        if candidate["confidence"] < SEMANTIC_LATE_POSE_CORE_CONFLICT_MIN_CONFIDENCE:
            continue
        delta = semantic_anchors[key] - candidate["timestamp"]
        if abs(delta) < SEMANTIC_LATE_POSE_CORE_CONFLICT_MIN_SHIFT_SECONDS:
            continue
        shifted.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(candidate["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(candidate["confidence"], 3),
            }
        )
    if len(shifted) < SEMANTIC_LATE_POSE_CORE_CONFLICT_MIN_KEYS:
        return None

    evidence = _semantic_candidate_tal_conflict_evidence(
        semantic_anchors,
        skeleton_anchors,
        shifted,
        candidate_flags,
        motion_scores,
    )
    return {
        "conflicts": shifted,
        "candidate_conflict_evidence": evidence,
        "decision": "rejected_late_pose_core_candidate_conflict",
    }


def _weak_geometry_candidate_conflict_should_ignore_for_semantic_main_motion(
    resolved_keyframes: dict[str, Any],
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    conflicts: Sequence[dict[str, float | str]],
    candidate_flags: Sequence[str],
    motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if not _has_ordered_core_tal(resolved_keyframes):
        return None
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "L"}.issubset(skeleton_anchors):
        return None
    flag_set = set(candidate_flags)
    if not (
        "keyframe_candidates_excluded_unreliable_pose_frames" in flag_set
        and "tal_candidate_weak_geometry" in flag_set
        and bool(flag_set & SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS)
    ):
        return None
    if flag_set & SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS:
        return None

    shifted_keys = {
        str(item.get("key"))
        for item in conflicts
        if isinstance(item, dict)
        and str(item.get("key") or "") in {"T", "A", "L"}
        and (_float_or_none(item.get("delta_sec")) or 0.0)
        >= SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MIN_SHIFT_SEC
    }
    if len(shifted_keys) < SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MIN_KEYS:
        return None

    candidate_timestamps = [
        float(anchor["timestamp"])
        for key, anchor in skeleton_anchors.items()
        if key in {"T", "A", "L"} and isinstance(anchor, dict)
    ]
    if len(candidate_timestamps) < 2:
        return None
    candidate_start = min(candidate_timestamps)
    candidate_end = max(candidate_timestamps)
    semantic_start = min(semantic_anchors["T"], semantic_anchors["L"])
    semantic_end = max(semantic_anchors["T"], semantic_anchors["L"])
    if candidate_end >= semantic_start - SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_CORE_TOLERANCE_SEC:
        return None

    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3:
        return None
    global_peak_record = max(records, key=lambda record: record["motion_score"])
    global_peak = float(global_peak_record["motion_score"])
    if global_peak < SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MIN_GLOBAL_PEAK:
        return None
    core_start = semantic_start - SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_CORE_TOLERANCE_SEC
    core_end = semantic_end + SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_CORE_TOLERANCE_SEC
    if not (core_start <= global_peak_record["timestamp"] <= core_end):
        return None

    semantic_peak = _peak_motion_in_window(
        records,
        semantic_start,
        semantic_end,
        tolerance=SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_CORE_TOLERANCE_SEC,
    )
    candidate_peak = _peak_motion_in_window(
        records,
        candidate_start,
        candidate_end,
        tolerance=SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_CORE_TOLERANCE_SEC,
    )
    semantic_peak_ratio = semantic_peak / max(global_peak, 1e-9)
    candidate_peak_ratio = candidate_peak / max(global_peak, 1e-9)
    if semantic_peak_ratio < SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MIN_SEMANTIC_PEAK_RATIO:
        return None
    if candidate_peak_ratio > SEMANTIC_WEAK_GEOMETRY_EARLY_CANDIDATE_MAIN_MOTION_MAX_CANDIDATE_PEAK_RATIO:
        return None

    return {
        "decision": "ignored_early_weak_geometry_candidate_main_motion_supports_semantic_tal",
        "shifted_keys": [key for key in ("T", "A", "L") if key in shifted_keys],
        "semantic_window": {
            "start_sec": round(semantic_start, 3),
            "end_sec": round(semantic_end, 3),
            "peak_motion_score": round(semantic_peak, 5),
            "peak_ratio": round(semantic_peak_ratio, 3),
        },
        "candidate_window": {
            "start_sec": round(candidate_start, 3),
            "end_sec": round(candidate_end, 3),
            "peak_motion_score": round(candidate_peak, 5),
            "peak_ratio": round(candidate_peak_ratio, 3),
        },
        "global_peak_timestamp": round(global_peak_record["timestamp"], 3),
        "global_peak_motion_score": round(global_peak, 5),
    }


def _maybe_align_pose_supported_takeoff_candidate(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    motion_scores: dict[str, object] | None,
    *,
    analysis_profile: str | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    if not _has_ordered_core_tal(resolved_keyframes):
        return False

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    if candidate_flags & SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_BLOCKING_FLAGS:
        return False

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return False

    takeoff = skeleton_anchors["T"]
    takeoff_shift = takeoff["timestamp"] - semantic_anchors["T"]
    if (
        takeoff_shift < SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_SHIFT_SECONDS
        or takeoff_shift > SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MAX_SHIFT_SECONDS
    ):
        return False
    if takeoff["confidence"] < SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_CONFIDENCE:
        return False

    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return False
    selected_by_key: dict[str, dict[str, Any]] = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item)
        if key in {"T", "A", "L"} and key not in selected_by_key:
            selected_by_key[key] = item
    if not {"T", "A", "L"}.issubset(selected_by_key):
        return False

    takeoff_record = selected_by_key["T"]
    refinement_reason = str(takeoff_record.get("refinement_reject_reason") or "")
    refinement_method = str(takeoff_record.get("refinement_method") or "")
    if refinement_reason != "delta" and refinement_method != "local_motion_peak_delta_rejected":
        return False
    refinement_candidate = _float_or_none(takeoff_record.get("refinement_candidate_timestamp"))
    if refinement_candidate is None:
        return False
    if refinement_candidate - semantic_anchors["T"] < SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_SHIFT_SECONDS:
        return False
    if (
        abs(refinement_candidate - takeoff["timestamp"])
        > SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_REFINEMENT_GAP_SECONDS
    ):
        return False

    if abs(semantic_anchors["A"] - skeleton_anchors["A"]["timestamp"]) > SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_APEX_MAX_DELTA_SECONDS:
        return False
    if takeoff["timestamp"] + SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_APEX_GAP_SECONDS > semantic_anchors["A"]:
        return False
    if not (takeoff["timestamp"] + 0.02 < semantic_anchors["A"] and semantic_anchors["A"] + 0.02 < semantic_anchors["L"]):
        return False

    takeoff_motion = _float_or_none(takeoff.get("motion_score"))
    if takeoff_motion is None or takeoff_motion < SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_MOTION_SCORE:
        return False
    records = _motion_records_from_scores(motion_scores)
    semantic_takeoff_peak = _peak_motion_in_window(
        records,
        semantic_anchors["T"],
        semantic_anchors["T"],
        tolerance=SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MOTION_WINDOW_SECONDS,
    )
    candidate_takeoff_peak = max(
        takeoff_motion,
        _peak_motion_in_window(
            records,
            takeoff["timestamp"],
            takeoff["timestamp"],
            tolerance=SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MOTION_WINDOW_SECONDS,
        ),
    )
    if candidate_takeoff_peak < SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_MOTION_SCORE:
        return False
    if (
        semantic_takeoff_peak > 0
        and candidate_takeoff_peak / semantic_takeoff_peak
        < SEMANTIC_POSE_SUPPORTED_TAKEOFF_ALIGNMENT_MIN_CANDIDATE_TO_SEMANTIC_PEAK_RATIO
    ):
        return False

    original_timestamp = _float_or_none(takeoff_record.get("timestamp"))
    if original_timestamp is not None and takeoff_record.get("pre_motion_alignment_timestamp") is None:
        takeoff_record["pre_motion_alignment_timestamp"] = round(original_timestamp, 3)
    takeoff_record["timestamp"] = round(takeoff["timestamp"], 3)
    takeoff_record["motion_alignment_source"] = "pose_supported_takeoff_candidate"
    takeoff_record["motion_alignment_delta_sec"] = round(takeoff_shift, 3)
    takeoff_record["motion_alignment_candidate_confidence"] = round(takeoff["confidence"], 3)
    takeoff_record["motion_alignment_candidate_motion_score"] = round(candidate_takeoff_peak, 5)
    takeoff_record["motion_alignment_refinement_candidate_timestamp"] = round(refinement_candidate, 3)

    video_ai = resolved_keyframes.get("video_ai")
    if isinstance(video_ai, dict):
        key_moments = video_ai.get("key_moments")
        if isinstance(key_moments, dict):
            updated_key_moments = dict(key_moments)
            updated_key_moments["T_takeoff_sec"] = round(takeoff["timestamp"], 3)
            video_ai["key_moments"] = updated_key_moments

    resolved_keyframes["semantic_pose_supported_takeoff_alignment"] = {
        "decision": "aligned_delta_rejected_takeoff_to_pose_supported_candidate",
        "semantic_timestamp": round(semantic_anchors["T"], 3),
        "candidate_timestamp": round(takeoff["timestamp"], 3),
        "delta_sec": round(takeoff_shift, 3),
        "refinement_candidate_timestamp": round(refinement_candidate, 3),
        "refinement_candidate_gap_sec": round(takeoff["timestamp"] - refinement_candidate, 3),
        "candidate_confidence": round(takeoff["confidence"], 3),
        "candidate_motion_score": round(candidate_takeoff_peak, 5),
        "semantic_takeoff_motion_score": round(semantic_takeoff_peak, 5),
        "apex_delta_sec": round(semantic_anchors["A"] - skeleton_anchors["A"]["timestamp"], 3),
        "candidate_quality_flags": sorted(candidate_flags),
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_pose_supported_takeoff_candidate_aligned")
    return True


def _semantic_motion_window_conflict_should_ignore_weak_candidate(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    motion_window_conflict: dict[str, Any],
) -> bool:
    if not _has_ordered_core_tal(resolved_keyframes):
        return False
    semantic_confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if semantic_confidence is None or semantic_confidence < SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_SEMANTIC_CONFIDENCE:
        return False
    semantic_window = motion_window_conflict.get("semantic_window")
    candidate_window = motion_window_conflict.get("candidate_window")
    if not isinstance(semantic_window, dict) or not isinstance(candidate_window, dict):
        return False
    candidate_peak = _float_or_none(candidate_window.get("peak_motion_score"))
    semantic_peak = _float_or_none(semantic_window.get("peak_motion_score"))
    if candidate_peak is None or semantic_peak is None:
        return False
    if candidate_peak > SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MAX_PEAK:
        return False
    if candidate_peak > 0 and semantic_peak / candidate_peak < SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MIN_SEMANTIC_PEAK_RATIO:
        return False

    boundary_confidences = [
        skeleton_anchors[key]["confidence"]
        for key in ("T", "L")
        if isinstance(skeleton_anchors.get(key), dict)
    ]
    if len(boundary_confidences) < 2:
        return False
    if (
        sum(boundary_confidences) / len(boundary_confidences)
        > SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MAX_BOUNDARY_AVG_CONFIDENCE
        or max(boundary_confidences) > SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MAX_BOUNDARY_CONFIDENCE
    ):
        return False

    flag_set = set(candidate_flags)
    return bool(
        flag_set
        & {
            "keyframe_candidates_excluded_unreliable_pose_frames",
            "tal_candidate_landing_geometry_weak",
            "landing_geometry_weak",
            "landing_confidence_low",
            "apex_local_minimum_not_clear",
        }
    )


def _motion_scores_full_context_duration(motion_scores: dict[str, object] | None) -> float | None:
    if not isinstance(motion_scores, dict):
        return None
    mode = str(motion_scores.get("input_window_mode") or motion_scores.get("window_strategy") or "").strip()
    reason = str(motion_scores.get("input_window_reason") or "").strip()
    if mode not in {"full_context", "full_video"} and reason != "full_context":
        return None
    for key in (
        "input_window_duration_sec",
        "effective_window_duration",
        "source_duration_sec",
    ):
        value = _float_or_none(motion_scores.get(key))
        if value is not None and value > 0:
            return value
    start = _float_or_none(motion_scores.get("input_window_start_sec"))
    end = _float_or_none(motion_scores.get("input_window_end_sec"))
    if start is None:
        start = _float_or_none(motion_scores.get("window_start_sec") or motion_scores.get("window_start"))
    if end is None:
        end = _float_or_none(motion_scores.get("window_end_sec") or motion_scores.get("window_end"))
    if start is not None and end is not None and end > start:
        return end - start
    return None


def _window_separation_seconds(first: dict[str, Any], second: dict[str, Any]) -> float | None:
    first_start = _float_or_none(first.get("start_sec"))
    first_end = _float_or_none(first.get("end_sec"))
    second_start = _float_or_none(second.get("start_sec"))
    second_end = _float_or_none(second.get("end_sec"))
    if first_start is None or first_end is None or second_start is None or second_end is None:
        return None
    if first_end < second_start:
        return second_start - first_end
    if second_end < first_start:
        return first_start - second_end
    return 0.0


def _semantic_motion_window_conflict_should_ignore_full_context_weak_candidate(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    motion_window_conflict: dict[str, Any],
    motion_scores: dict[str, object] | None,
) -> bool:
    if not _has_ordered_core_tal(resolved_keyframes):
        return False
    semantic_confidence = _float_or_none(resolved_keyframes.get("confidence"))
    if semantic_confidence is None or semantic_confidence < SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_SEMANTIC_CONFIDENCE:
        return False
    duration = _motion_scores_full_context_duration(motion_scores)
    if duration is None or duration < SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MIN_DURATION_SEC:
        return False
    semantic_window = motion_window_conflict.get("semantic_window")
    candidate_window = motion_window_conflict.get("candidate_window")
    if not isinstance(semantic_window, dict) or not isinstance(candidate_window, dict):
        return False
    semantic_peak = _float_or_none(semantic_window.get("peak_motion_score"))
    if semantic_peak is None or semantic_peak < SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MIN_SEMANTIC_PEAK:
        return False
    separation = _window_separation_seconds(semantic_window, candidate_window)
    if separation is None or separation < SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MIN_SEPARATION_SEC:
        return False

    boundary_confidences = [
        skeleton_anchors[key]["confidence"]
        for key in ("T", "L")
        if isinstance(skeleton_anchors.get(key), dict)
    ]
    if len(boundary_confidences) < 2:
        return False
    if (
        sum(boundary_confidences) / len(boundary_confidences)
        > SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MAX_BOUNDARY_AVG_CONFIDENCE
        or max(boundary_confidences) > SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_CANDIDATE_MAX_BOUNDARY_CONFIDENCE
    ):
        return False

    flag_set = set(candidate_flags)
    return bool(
        flag_set
        & {
            "keyframe_candidates_excluded_unreliable_pose_frames",
            "landing_geometry_weak",
            "landing_confidence_low",
            "apex_local_minimum_not_clear",
            "confidence_missing_knee_angle_change",
        }
    )


def _semantic_motion_window_conflict_should_ignore_weak_geometry_candidate(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    motion_window_conflict: dict[str, Any],
) -> bool:
    if not _has_ordered_core_tal(resolved_keyframes):
        return False
    flag_set = set(candidate_flags)
    if not (flag_set & SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS):
        return False
    if "tal_candidate_landing_geometry_absent" in flag_set:
        return False

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "L"}.issubset(skeleton_anchors):
        return False
    semantic_span = semantic_anchors["L"] - semantic_anchors["T"]
    if semantic_span < SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_MIN_SEMANTIC_SPAN_SEC:
        return False

    semantic_confidence = _float_or_none(resolved_keyframes.get("confidence"))
    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    video_confidence = _float_or_none(video_ai.get("confidence")) if isinstance(video_ai, dict) else None
    confidence = max(value for value in (semantic_confidence, video_confidence, 0.0) if value is not None)
    if confidence < SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_SEMANTIC_CONFIDENCE:
        return False

    semantic_window = motion_window_conflict.get("semantic_window")
    if not isinstance(semantic_window, dict):
        return False
    semantic_peak_ratio = _float_or_none(motion_window_conflict.get("semantic_peak_ratio"))
    if semantic_peak_ratio is None:
        semantic_peak = _float_or_none(semantic_window.get("peak_motion_score")) or 0.0
        global_peak = _float_or_none(motion_window_conflict.get("global_peak_motion_score")) or 0.0
        semantic_peak_ratio = semantic_peak / max(global_peak, 1e-9)
    if semantic_peak_ratio < SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_MIN_SEMANTIC_PEAK_RATIO:
        return False

    if _weak_geometry_candidate_conflict_has_late_main_motion_peak(
        resolved_keyframes,
        skeleton_anchors,
        motion_window_conflict,
    ):
        return False

    boundary_confidences = [
        skeleton_anchors[key]["confidence"]
        for key in ("T", "L")
        if isinstance(skeleton_anchors.get(key), dict)
    ]
    if len(boundary_confidences) < 2:
        return False
    max_boundary_confidence = SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_MAX_BOUNDARY_CONFIDENCE
    unreliable_pose_weak_geometry_only = (
        "keyframe_candidates_excluded_unreliable_pose_frames" in flag_set
        and bool(flag_set & SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS)
        and not bool(
            flag_set
            & (
                SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
                | SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS
                | SEMANTIC_CANDIDATE_UNRELIABLE_POSE_FALLBACK_FLAGS
            )
        )
    )
    if unreliable_pose_weak_geometry_only:
        max_boundary_confidence = (
            SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_UNRELIABLE_POSE_MAX_BOUNDARY_CONFIDENCE
        )
    return max(boundary_confidences) <= max_boundary_confidence


def _weak_geometry_candidate_conflict_has_late_main_motion_peak(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    motion_window_conflict: dict[str, Any],
) -> bool:
    flags = set(_quality_flags(resolved_keyframes))
    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if isinstance(video_ai, dict):
        flags.update(_quality_flags(video_ai))
    if not (
        "video_temporal_resolver_video_fallback_recommended" in flags
        or "video_temporal_resolver_video_validation_not_clean" in flags
        or "video_temporal_fallback_recommended" in flags
        or str(video_ai.get("fallback_recommendation") or "").strip() in {"manual_review", "use_sampled_frames"}
    ):
        return False

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return False

    peak_timestamp = _float_or_none(motion_window_conflict.get("global_peak_timestamp"))
    if peak_timestamp is None:
        return False
    if (
        peak_timestamp - semantic_anchors["L"]
        < SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_LATE_MAIN_PEAK_MIN_LAG_SEC
    ):
        return False

    candidate_window = motion_window_conflict.get("candidate_window")
    if not isinstance(candidate_window, dict):
        return False
    candidate_start = _float_or_none(candidate_window.get("start_sec"))
    candidate_end = _float_or_none(candidate_window.get("end_sec"))
    if candidate_start is None or candidate_end is None or not (candidate_start <= peak_timestamp <= candidate_end):
        return False

    candidate_peak = _float_or_none(candidate_window.get("peak_motion_score"))
    semantic_window = motion_window_conflict.get("semantic_window")
    semantic_peak = (
        _float_or_none(semantic_window.get("peak_motion_score"))
        if isinstance(semantic_window, dict)
        else None
    )
    if candidate_peak is None or semantic_peak is None:
        return False
    if (
        candidate_peak / max(semantic_peak, 1e-9)
        < SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_LATE_MAIN_PEAK_MIN_RATIO
    ):
        return False

    late_shifted_keys = 0
    for key in ("T", "A", "L"):
        skeleton = skeleton_anchors.get(key)
        if not isinstance(skeleton, dict):
            continue
        if (
            skeleton["timestamp"] - semantic_anchors[key]
            >= SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_SHIFT_SECONDS
        ):
            late_shifted_keys += 1
    return late_shifted_keys >= SEMANTIC_CANDIDATE_MOTION_WINDOW_WEAK_GEOMETRY_LATE_MAIN_PEAK_MIN_SHIFT_KEYS


def _full_context_takeoff_anchor_fallback_override(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    motion_scores: dict[str, object] | None,
    bio_data: dict[str, Any] | None = None,
) -> bool:
    if not _has_ordered_core_tal(resolved_keyframes):
        return False
    flag_set = set(candidate_flags)
    required = {
        "keyframe_candidates_motion_fallback",
        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
        "tal_candidate_motion_fallback_low_precision",
        "tal_candidate_skeleton_drifted_after_takeoff",
    }
    if not required.issubset(flag_set):
        return False
    semantic_confidence = _float_or_none(resolved_keyframes.get("confidence"))
    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    video_confidence = _float_or_none(video_ai.get("confidence"))
    confidence = max(
        value
        for value in (semantic_confidence, video_confidence, 0.0)
        if value is not None
    )
    if (
        confidence < SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_FULL_CONTEXT_CONFIDENCE
        and not _moderate_confidence_full_context_takeoff_anchor_video_supports_override(
            resolved_keyframes,
            bio_data,
            confidence=confidence,
        )
    ):
        return False
    duration = _motion_scores_full_context_duration(motion_scores)
    if duration is None or duration < SEMANTIC_CANDIDATE_MOTION_WINDOW_FULL_CONTEXT_MIN_DURATION_SEC:
        return False

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return False
    return (
        skeleton_anchors["T"]["timestamp"] - semantic_anchors["L"]
        >= SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_TAIL_SHIFT_SEC
    )


def _moderate_confidence_full_context_takeoff_anchor_video_supports_override(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    confidence: float,
    allow_lower_air_confidence: bool = False,
    require_low_visibility_tail: bool = True,
) -> bool:
    if confidence < SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_MODERATE_CONFIDENCE:
        return False
    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return False
    if str(video_ai.get("fallback_recommendation") or "").strip() != "use_video_timestamps":
        return False

    action_confirmation = video_ai.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        return False
    if _normalize_action_profile(action_confirmation.get("action_family")) != "jump":
        return False
    action_confidence = _float_or_none(action_confirmation.get("confidence"))
    if (
        action_confidence is None
        or action_confidence < SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_ACTION_CONFIDENCE
    ):
        return False

    phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)]
    phase_by_code = {str(item.get("phase_code") or ""): item for item in phase_segments}
    for phase_code in ("takeoff", "air", "landing"):
        phase = phase_by_code.get(phase_code)
        phase_confidence = _float_or_none(phase.get("confidence") if isinstance(phase, dict) else None)
        threshold = (
            SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_AIR_PHASE_CONFIDENCE
            if allow_lower_air_confidence and phase_code == "air"
            else SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_CONFIDENCE
        )
        if (
            phase_confidence is None
            or phase_confidence < threshold
        ):
            return False

    if not require_low_visibility_tail:
        return True

    return _takeoff_anchor_fallback_has_low_visibility_tail_candidates(bio_data)


def _early_approach_motion_peak_video_supports_override(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    confidence: float,
) -> bool:
    if _moderate_confidence_full_context_takeoff_anchor_video_supports_override(
        resolved_keyframes,
        bio_data,
        confidence=confidence,
        allow_lower_air_confidence=True,
        require_low_visibility_tail=False,
    ):
        return True
    if confidence < SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_MODERATE_CONFIDENCE:
        return False

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return False
    if str(video_ai.get("fallback_recommendation") or "").strip() != "use_video_timestamps":
        return False

    action_confirmation = video_ai.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        return False
    if _normalize_action_profile(action_confirmation.get("action_family")) != "jump":
        return False
    action_confidence = _float_or_none(action_confirmation.get("confidence"))
    if (
        action_confidence is None
        or action_confidence < SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_ACTION_CONFIDENCE
    ):
        return False

    phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)]
    phase_by_code = {str(item.get("phase_code") or ""): item for item in phase_segments}
    for phase_code in ("takeoff", "air", "landing"):
        phase = phase_by_code.get(phase_code)
        phase_confidence = _float_or_none(phase.get("confidence") if isinstance(phase, dict) else None)
        if (
            phase_confidence is None
            or phase_confidence < SEMANTIC_EARLY_APPROACH_MOTION_PEAK_PHASE_CONFIDENCE
        ):
            return False
    return True


def _takeoff_anchor_fallback_has_low_visibility_tail_candidates(bio_data: dict[str, Any] | None) -> bool:
    source = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(source, dict):
        return False

    low_visibility_keys = 0
    for key in ("A", "L"):
        candidate = source.get(key)
        if not isinstance(candidate, dict):
            continue
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        warnings = candidate.get("warnings") if isinstance(candidate.get("warnings"), list) else []
        warning_values = {str(item).strip() for item in warnings}
        if "keyframe_candidates_motion_fallback" not in warning_values and not bool(evidence.get("motion_fallback")):
            continue
        visibility = _float_or_none(evidence.get("visibility_score"))
        if visibility is None:
            score_components = evidence.get("score_components") if isinstance(evidence.get("score_components"), dict) else {}
            visibility = _float_or_none(score_components.get("pose_visibility"))
        if (
            visibility is not None
            and visibility <= SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_MAX_VISIBILITY
        ):
            low_visibility_keys += 1

    return low_visibility_keys >= SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_MIN_LOW_VISIBILITY_KEYS


def _early_takeoff_anchor_fallback_override(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    motion_window_conflict: dict[str, Any],
    bio_data: dict[str, Any] | None,
) -> bool:
    if not _has_ordered_core_tal(resolved_keyframes):
        return False
    flag_set = set(candidate_flags)
    required = {
        "keyframe_candidates_motion_fallback",
        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
        "tal_candidate_motion_fallback_low_precision",
        "tal_candidate_skeleton_drifted_after_takeoff",
    }
    if not required.issubset(flag_set):
        return False
    if not {"T", "A", "L"}.issubset(skeleton_anchors):
        return False

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors):
        return False
    if semantic_anchors["T"] - skeleton_anchors["T"]["timestamp"] < SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_EARLY_SHIFT_SEC:
        return False

    candidate_window = motion_window_conflict.get("candidate_window")
    if not isinstance(candidate_window, dict):
        return False
    candidate_start = _float_or_none(candidate_window.get("start_sec"))
    if candidate_start is None or candidate_start > SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_EARLY_START_MAX_SEC:
        return False

    if not _moderate_confidence_full_context_takeoff_anchor_video_supports_override(
        resolved_keyframes,
        bio_data,
        confidence=_video_confidence(
            resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else None,
            resolved_keyframes,
        ),
        allow_lower_air_confidence=True,
    ):
        return False
    if not _takeoff_anchor_fallback_takeoff_is_weak(bio_data):
        return False
    return True


def _early_takeoff_anchor_approach_motion_window_override(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    motion_window_conflict: dict[str, Any],
    bio_data: dict[str, Any] | None,
) -> bool:
    if not _has_ordered_core_tal(resolved_keyframes):
        return False
    flag_set = set(candidate_flags)
    required = {
        "keyframe_candidates_motion_fallback",
        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
        "tal_candidate_motion_fallback_low_precision",
        "tal_candidate_skeleton_drifted_after_takeoff",
    }
    if not required.issubset(flag_set):
        return False
    if not {"T", "A", "L"}.issubset(skeleton_anchors):
        return False

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors):
        return False
    early_shifted_keys = sum(
        1
        for key in ("T", "A", "L")
        if semantic_anchors[key] - skeleton_anchors[key]["timestamp"]
        >= SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_WINDOW_MIN_SHIFT_SEC
    )
    if early_shifted_keys < 2:
        return False

    global_peak = _float_or_none(motion_window_conflict.get("global_peak_motion_score"))
    semantic_window = motion_window_conflict.get("semantic_window")
    candidate_window = motion_window_conflict.get("candidate_window")
    if (
        global_peak is None
        or not isinstance(semantic_window, dict)
        or not isinstance(candidate_window, dict)
    ):
        return False

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)] if isinstance(video_ai, dict) else []
    takeoff_phase = next((item for item in phase_segments if str(item.get("phase_code") or "") == "takeoff"), None)
    takeoff_start = _float_or_none(takeoff_phase.get("time_start") if isinstance(takeoff_phase, dict) else None)
    if takeoff_start is None:
        takeoff_start = semantic_anchors["T"]
    latest_candidate_timestamp = max(skeleton_anchors[key]["timestamp"] for key in ("T", "A", "L"))
    if (
        latest_candidate_timestamp
        > takeoff_start - SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_CANDIDATE_MAX_PRE_TAKEOFF_GAP_SEC
    ):
        return False

    semantic_peak = _float_or_none(semantic_window.get("peak_motion_score"))
    candidate_peak = _float_or_none(candidate_window.get("peak_motion_score"))
    if semantic_peak is None or candidate_peak is None:
        return False
    if candidate_peak / max(semantic_peak, 1e-9) < SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_WINDOW_MIN_PEAK_RATIO:
        return False
    if semantic_peak / max(global_peak, 1e-9) > SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_WINDOW_MAX_SEMANTIC_RATIO:
        return False

    if not _moderate_confidence_full_context_takeoff_anchor_video_supports_override(
        resolved_keyframes,
        bio_data,
        confidence=_video_confidence(
            resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else None,
            resolved_keyframes,
        ),
        allow_lower_air_confidence=True,
        require_low_visibility_tail=False,
    ):
        return False

    return True


def _takeoff_anchor_phase_shifted_candidate_override(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    motion_window_conflict: dict[str, Any],
    bio_data: dict[str, Any] | None,
) -> bool:
    if not _has_ordered_core_tal(resolved_keyframes):
        return False
    flag_set = set(candidate_flags)
    required = {
        "keyframe_candidates_motion_fallback",
        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
        "tal_candidate_motion_fallback_low_precision",
        "tal_candidate_skeleton_drifted_after_takeoff",
    }
    if not required.issubset(flag_set):
        return False
    if not {"T", "A", "L"}.issubset(skeleton_anchors):
        return False

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors):
        return False
    if not (
        semantic_anchors["T"] - skeleton_anchors["T"]["timestamp"]
        >= SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_SHIFT_MIN_EARLY_SEC
        and semantic_anchors["A"] - skeleton_anchors["A"]["timestamp"]
        >= SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_SHIFT_MIN_EARLY_SEC
    ):
        return False
    if abs(skeleton_anchors["L"]["timestamp"] - semantic_anchors["T"]) > SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_SHIFT_MAX_L_TO_T_SEC:
        return False
    candidate_span = skeleton_anchors["L"]["timestamp"] - skeleton_anchors["T"]["timestamp"]
    if candidate_span <= 0 or candidate_span > SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_PHASE_SHIFT_MAX_SPAN_SEC:
        return False

    semantic_window = motion_window_conflict.get("semantic_window")
    candidate_window = motion_window_conflict.get("candidate_window")
    global_peak = _float_or_none(motion_window_conflict.get("global_peak_motion_score"))
    if not isinstance(semantic_window, dict) or not isinstance(candidate_window, dict) or global_peak is None:
        return False
    semantic_peak = _float_or_none(semantic_window.get("peak_motion_score"))
    candidate_peak = _float_or_none(candidate_window.get("peak_motion_score"))
    if semantic_peak is None or candidate_peak is None:
        return False
    if candidate_peak / max(semantic_peak, 1e-9) < SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_WINDOW_MIN_PEAK_RATIO:
        return False
    if semantic_peak / max(global_peak, 1e-9) > SEMANTIC_TAKEOFF_ANCHOR_FALLBACK_APPROACH_WINDOW_MAX_SEMANTIC_RATIO:
        return False

    return _moderate_confidence_full_context_takeoff_anchor_video_supports_override(
        resolved_keyframes,
        bio_data,
        confidence=_video_confidence(
            resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else None,
            resolved_keyframes,
        ),
        allow_lower_air_confidence=True,
        require_low_visibility_tail=False,
    )


def _takeoff_anchor_fallback_takeoff_is_weak(bio_data: dict[str, Any] | None) -> bool:
    source = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(source, dict):
        return False
    takeoff = source.get("T")
    if not isinstance(takeoff, dict):
        return False
    warnings = takeoff.get("warnings") if isinstance(takeoff.get("warnings"), list) else []
    warning_values = {str(item).strip() for item in warnings}
    weak_warnings = {
        "knee_extension_weak",
        "com_ascent_weak",
        "takeoff_timing_window_weak",
    }
    return len(warning_values & weak_warnings) >= 2


def _early_approach_motion_peak_contaminated_candidate_support(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
    conflicts: Sequence[dict[str, float | str]],
    motion_window_conflict: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    peak_timestamp: float,
    global_peak: float,
    core_peak: float,
    strong_records: Sequence[dict[str, float]],
    tolerance: float,
) -> dict[str, Any] | None:
    if not _has_ordered_core_tal(resolved_keyframes):
        return None
    if not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None

    flag_set = set(candidate_flags)
    if not SEMANTIC_EARLY_APPROACH_MOTION_PEAK_REQUIRED_FLAGS.issubset(flag_set):
        return None
    if flag_set & SEMANTIC_EARLY_APPROACH_MOTION_PEAK_BLOCK_FLAGS:
        return None
    if not (flag_set & SEMANTIC_EARLY_APPROACH_MOTION_PEAK_SUPPORT_FLAGS):
        return None

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors):
        return None
    if peak_timestamp >= semantic_anchors["T"] - SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_SEMANTIC_LEAD_SEC:
        return None
    if not all(record["timestamp"] < semantic_anchors["T"] - tolerance for record in strong_records):
        return None

    takeoff_shift = semantic_anchors["T"] - skeleton_anchors["T"]["timestamp"]
    if not (
        SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_T_SHIFT_SEC
        <= takeoff_shift
        <= SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MAX_T_SHIFT_SEC
    ):
        return None
    if skeleton_anchors["T"]["timestamp"] - peak_timestamp < SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_LEAD_SEC:
        return None

    conflict_keys = {str(item.get("key") or "") for item in conflicts if isinstance(item, dict)}
    if len({key for key in conflict_keys if key in {"T", "A", "L"}}) < SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_CONFLICT_KEYS:
        return None

    candidate_window = motion_window_conflict.get("candidate_window")
    semantic_window = motion_window_conflict.get("semantic_window")
    if not isinstance(candidate_window, dict) or not isinstance(semantic_window, dict):
        return None
    candidate_start = _float_or_none(candidate_window.get("start_sec"))
    if candidate_start is None or candidate_start > peak_timestamp + tolerance:
        return None
    semantic_peak = _float_or_none(semantic_window.get("peak_motion_score"))
    if semantic_peak is None or semantic_peak < SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_CORE_SCORE:
        return None
    if global_peak > 0 and max(core_peak, semantic_peak) < global_peak * SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_CORE_RATIO:
        return None

    if not _early_approach_motion_peak_video_supports_override(
        resolved_keyframes,
        bio_data,
        confidence=_video_confidence(
            resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else None,
            resolved_keyframes,
        ),
    ):
        return None

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)]
    early_phase_codes: list[str] = []
    for phase in phase_segments:
        phase_code = str(phase.get("phase_code") or "")
        if phase_code not in {"approach", "preparation"}:
            continue
        start = _float_or_none(phase.get("time_start"))
        end = _float_or_none(phase.get("time_end"))
        if start is not None and end is not None and start - tolerance <= peak_timestamp <= end + tolerance:
            early_phase_codes.append(phase_code)
    if not early_phase_codes:
        return None

    return {
        "peak_phase_codes": early_phase_codes,
        "takeoff_shift_sec": round(takeoff_shift, 3),
        "candidate_quality_flags": sorted(flag_set),
    }


def _early_approach_motion_peak_motion_cluster_support(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    candidate_flags: Sequence[str],
    *,
    peak_timestamp: float,
    global_peak: float,
    core_peak: float,
    strong_records: Sequence[dict[str, float]],
    tolerance: float,
) -> dict[str, Any] | None:
    candidate_conflict = resolved_keyframes.get("semantic_candidate_tal_conflict")
    if not isinstance(candidate_conflict, dict):
        return None
    if (
        str(candidate_conflict.get("decision") or "")
        != "ignored_early_approach_motion_peak_candidate_window"
    ):
        return None
    motion_window_conflict = candidate_conflict.get("motion_window_conflict")
    if not isinstance(motion_window_conflict, dict):
        return None
    conflicts = candidate_conflict.get("conflicts")
    if not isinstance(conflicts, list):
        return None
    support = _early_approach_motion_peak_contaminated_candidate_support(
        resolved_keyframes,
        _skeleton_candidate_anchors(bio_data),
        candidate_flags,
        conflicts,
        motion_window_conflict,
        bio_data,
        peak_timestamp=peak_timestamp,
        global_peak=global_peak,
        core_peak=core_peak,
        strong_records=strong_records,
        tolerance=tolerance,
    )
    if support is None:
        return None
    support = dict(support)
    support["candidate_conflict_decision"] = candidate_conflict.get("decision")
    return support


def _retry_weak_phase_early_motion_cluster_support(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    candidate_flags: Sequence[str],
    *,
    peak_timestamp: float,
    global_peak: float,
    core_peak: float,
    strong_records: Sequence[dict[str, float]],
    tolerance: float,
) -> dict[str, Any] | None:
    flags = set(_quality_flags(resolved_keyframes))
    if "video_temporal_resolver_retry_weak_phase_tal_preserved" not in flags:
        return None
    if not (set(candidate_flags) & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS):
        return None

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors):
        return None
    tal_span = semantic_anchors["L"] - semantic_anchors["T"]
    if not (
        SEMANTIC_RETRY_WEAK_PHASE_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_RETRY_WEAK_PHASE_MAX_TAL_SPAN_SEC
    ):
        return None
    if peak_timestamp >= semantic_anchors["T"] - SEMANTIC_RETRY_WEAK_PHASE_EARLY_MOTION_MIN_LEAD_SEC:
        return None
    if not all(record["timestamp"] < semantic_anchors["T"] - tolerance for record in strong_records):
        return None

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    boundary_confidences = [
        float(skeleton_anchors[key]["confidence"])
        for key in ("T", "L")
        if isinstance(skeleton_anchors.get(key), dict)
    ]
    if boundary_confidences and max(boundary_confidences) > SEMANTIC_RETRY_WEAK_PHASE_MAX_BOUNDARY_CONFIDENCE:
        return None

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return None
    phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)]
    early_phase_codes: list[str] = []
    core_phase_confidences: dict[str, float] = {}
    for phase in phase_segments:
        phase_code = str(phase.get("phase_code") or "")
        start = _float_or_none(phase.get("time_start"))
        end = _float_or_none(phase.get("time_end"))
        if phase_code in {"approach", "preparation"} and start is not None and end is not None:
            if start - tolerance <= peak_timestamp <= end + tolerance:
                early_phase_codes.append(phase_code)
        if phase_code in {"takeoff", "air", "landing"}:
            phase_confidence = _float_or_none(phase.get("confidence"))
            core_phase_confidences[phase_code] = max(0.0, min(float(phase_confidence or 0.0), 1.0))
    if not early_phase_codes:
        return None
    if set(core_phase_confidences) != {"takeoff", "air", "landing"}:
        return None

    return {
        "support_mode": "retry_weak_phase_tal_over_early_approach_motion_peak",
        "peak_phase_codes": early_phase_codes,
        "tal_span_sec": round(tal_span, 3),
        "core_phase_confidences": {
            key: round(value, 3)
            for key, value in sorted(core_phase_confidences.items())
        },
        "candidate_quality_flags": sorted(set(candidate_flags)),
        "candidate_boundary_confidences": [round(value, 3) for value in boundary_confidences],
        "core_peak_ratio": round(core_peak / global_peak, 3) if global_peak > 0 else None,
    }


def _semantic_motion_window_conflict_should_ignore_compressed_candidate(
    resolved_keyframes: dict[str, Any],
    skeleton_anchors: dict[str, dict[str, float]],
    candidate_flags: Sequence[str],
) -> bool:
    if not _has_ordered_core_tal(resolved_keyframes):
        return False
    if not {"T", "A", "L"}.issubset(skeleton_anchors):
        return False
    flag_set = set(candidate_flags)
    if not flag_set & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS:
        return False
    timestamps = [skeleton_anchors[key]["timestamp"] for key in ("T", "A", "L")]
    if not (timestamps[0] + 0.02 < timestamps[1] and timestamps[1] + 0.02 < timestamps[2]):
        return False
    return timestamps[2] - timestamps[0] <= SEMANTIC_CANDIDATE_MOTION_WINDOW_COMPRESSED_CORE_MAX_SPAN_SEC


def _occluded_motion_window_candidate_supports_rejecting_semantic(
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    *,
    core_peak: float,
    global_peak: float,
) -> dict[str, Any] | None:
    if global_peak <= 0 or not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None
    if core_peak >= global_peak * SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MAX_CORE_PEAK_RATIO:
        return None

    candidate_timestamps = {key: skeleton_anchors[key]["timestamp"] for key in ("T", "A", "L")}
    if not (
        candidate_timestamps["T"] + 0.02 < candidate_timestamps["A"]
        and candidate_timestamps["A"] + 0.02 < candidate_timestamps["L"]
    ):
        return None

    conflicts: list[dict[str, float | str]] = []
    confidences: list[float] = []
    for key in ("T", "A", "L"):
        candidate = skeleton_anchors[key]
        confidence = float(candidate["confidence"])
        support_confidence = float(candidate.get("raw_confidence", confidence))
        confidences.append(confidence)
        delta = semantic_anchors[key] - candidate["timestamp"]
        if delta < SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MIN_SHIFT_SECONDS:
            return None
        conflicts.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(candidate["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(confidence, 3),
                "candidate_raw_confidence": round(support_confidence, 3),
            }
        )

    support_confidences = [
        float(skeleton_anchors[key].get("raw_confidence", skeleton_anchors[key]["confidence"]))
        for key in ("T", "A", "L")
    ]
    boundary_confidence = min(
        float(skeleton_anchors["T"].get("raw_confidence", skeleton_anchors["T"]["confidence"])),
        float(skeleton_anchors["L"].get("raw_confidence", skeleton_anchors["L"]["confidence"])),
    )
    average_confidence = sum(support_confidences) / len(support_confidences)
    if (
        average_confidence < SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MIN_AVG_CONFIDENCE
        or boundary_confidence < SEMANTIC_OCCLUDED_MOTION_WINDOW_CANDIDATE_MIN_BOUNDARY_CONFIDENCE
    ):
        return None

    return {
        "conflicts": conflicts,
        "average_candidate_confidence": round(average_confidence, 3),
        "boundary_min_confidence": round(boundary_confidence, 3),
    }


def _semantic_candidate_tal_conflict_flags(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
    motion_scores: dict[str, object] | None = None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return []
    existing_flags = set(_quality_flags(resolved_keyframes))
    existing_candidate_conflict = resolved_keyframes.get("semantic_candidate_tal_conflict")
    reused_accepted_source_conflict = (
        "semantic_keyframes_reused_from_matching_video" in existing_flags
        and isinstance(existing_candidate_conflict, dict)
        and existing_candidate_conflict.get("reused_from_source_analysis") is True
        and bool(
            existing_flags
            & {
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
        )
    )
    if reused_accepted_source_conflict:
        return []

    candidate_flags = _keyframe_candidate_quality_flags(bio_data)
    candidate_flag_set = set(candidate_flags)
    has_standard_context = bool(candidate_flag_set & SEMANTIC_CANDIDATE_TAL_CONFLICT_CONTEXT_FLAGS)
    has_standard_strong_signal = bool(candidate_flag_set & SEMANTIC_CANDIDATE_TAL_CONFLICT_STRONG_FLAGS)
    has_motion_window_only_context = bool(candidate_flag_set & SEMANTIC_CANDIDATE_MOTION_WINDOW_ONLY_CONTEXT_FLAGS)
    if not has_standard_context and not has_motion_window_only_context:
        return []
    if not has_standard_strong_signal and not has_motion_window_only_context:
        return []
    absent_landing_geometry_only = (
        "tal_candidate_landing_geometry_absent" in candidate_flags
        and not (set(candidate_flags) & {
            "keyframe_candidates_motion_fallback",
            "keyframe_candidates_motion_fallback_from_takeoff_anchor",
            "tal_candidate_skeleton_drifted_after_takeoff",
        })
    )
    unreliable_pose_motion_fallback = bool(set(candidate_flags) & SEMANTIC_CANDIDATE_UNRELIABLE_POSE_FALLBACK_FLAGS)
    weak_temporal_geometry = bool(set(candidate_flags) & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS)

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or len(skeleton_anchors) < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_KEYS:
        return []
    if has_motion_window_only_context and not has_standard_strong_signal:
        boundary_confidences = [
            skeleton_anchors[key]["confidence"]
            for key in ("T", "L")
            if isinstance(skeleton_anchors.get(key), dict)
        ]
        if len(boundary_confidences) < 2:
            return []
        if (
            sum(boundary_confidences) / len(boundary_confidences)
            < SEMANTIC_CANDIDATE_MOTION_WINDOW_ONLY_MIN_BOUNDARY_AVG_CONFIDENCE
            and max(boundary_confidences) < SEMANTIC_CANDIDATE_MOTION_WINDOW_ONLY_MIN_BOUNDARY_STRONG_CONFIDENCE
        ):
            return []

    conflicts: list[dict[str, float | str]] = []
    for key in ("T", "A", "L"):
        candidate = skeleton_anchors.get(key)
        if not isinstance(candidate, dict):
            continue
        if candidate["confidence"] < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_CONFIDENCE:
            continue
        delta = semantic_anchors[key] - candidate["timestamp"]
        if abs(delta) < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_SHIFT_SECONDS:
            continue
        conflicts.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(candidate["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(candidate["confidence"], 3),
            }
        )
    if "keyframe_candidates_late_pose_core_reselected" in candidate_flag_set:
        existing_conflict_keys = {str(item.get("key")) for item in conflicts if isinstance(item, dict)}
        for key in ("T", "A", "L"):
            if key in existing_conflict_keys:
                continue
            candidate = skeleton_anchors.get(key)
            if not isinstance(candidate, dict):
                continue
            if candidate["confidence"] < SEMANTIC_LATE_POSE_CORE_CONFLICT_MIN_CONFIDENCE:
                continue
            delta = semantic_anchors[key] - candidate["timestamp"]
            if abs(delta) < SEMANTIC_LATE_POSE_CORE_CONFLICT_MIN_SHIFT_SECONDS:
                continue
            conflicts.append(
                {
                    "key": key,
                    "semantic_timestamp": round(semantic_anchors[key], 3),
                    "candidate_timestamp": round(candidate["timestamp"], 3),
                    "delta_sec": round(delta, 3),
                    "candidate_confidence": round(candidate["confidence"], 3),
                }
            )
    takeoff_anchor_core_conflict = False
    apex_candidate = skeleton_anchors.get("A")
    unreliable_pose_fallback_conflicts: list[dict[str, float | str]] = []
    if (
        "keyframe_candidates_motion_fallback_from_takeoff_anchor" in candidate_flags
        and isinstance(apex_candidate, dict)
        and (
            apex_candidate["confidence"] >= SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_CONFIDENCE
            or bool(apex_candidate.get("unreliable_pose_fallback"))
        )
        and abs(semantic_anchors["A"] - apex_candidate["timestamp"])
        >= SEMANTIC_TAKEOFF_ANCHOR_APEX_CONFLICT_MIN_SHIFT_SECONDS
    ):
        takeoff_anchor_core_conflict = True
        conflict = {
            "key": "A",
            "semantic_timestamp": round(semantic_anchors["A"], 3),
            "candidate_timestamp": round(apex_candidate["timestamp"], 3),
            "delta_sec": round(semantic_anchors["A"] - apex_candidate["timestamp"], 3),
            "candidate_confidence": round(apex_candidate["confidence"], 3),
            "candidate_raw_confidence": round(apex_candidate.get("raw_confidence", apex_candidate["confidence"]), 3),
        }
        if bool(apex_candidate.get("unreliable_pose_fallback")):
            unreliable_pose_fallback_conflicts.append(conflict)
        elif not any(item["key"] == "A" for item in conflicts):
            conflicts.append(conflict)
    if "keyframe_candidates_motion_fallback_from_takeoff_anchor" in candidate_flags:
        for key, threshold in SEMANTIC_TAKEOFF_ANCHOR_CORE_CONFLICT_MIN_SHIFT_SECONDS.items():
            candidate = skeleton_anchors.get(key)
            if not isinstance(candidate, dict):
                continue
            if (
                candidate["confidence"] < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_CONFIDENCE
                and not bool(candidate.get("unreliable_pose_fallback"))
            ):
                continue
            delta = semantic_anchors[key] - candidate["timestamp"]
            if abs(delta) < threshold:
                continue
            takeoff_anchor_core_conflict = True
            conflict = {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(candidate["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(candidate["confidence"], 3),
                "candidate_raw_confidence": round(candidate.get("raw_confidence", candidate["confidence"]), 3),
            }
            if bool(candidate.get("unreliable_pose_fallback")):
                unreliable_pose_fallback_conflicts.append(conflict)
                continue
            if any(item["key"] == key for item in conflicts):
                continue
            conflicts.append(conflict)
    candidate_motion_window_conflict = _semantic_candidate_motion_window_conflict_diagnostic(
        semantic_anchors,
        skeleton_anchors,
        conflicts,
        motion_scores,
    )
    if (
        candidate_motion_window_conflict is None
        and unreliable_pose_motion_fallback
        and takeoff_anchor_core_conflict
        and len(unreliable_pose_fallback_conflicts) >= SEMANTIC_UNRELIABLE_POSE_FALLBACK_LATE_CANDIDATE_MIN_SHIFT_KEYS
    ):
        unreliable_pose_motion_rejection = _unreliable_pose_fallback_late_candidate_motion_rejection(
            resolved_keyframes,
            semantic_anchors,
            skeleton_anchors,
            motion_scores,
        )
        if unreliable_pose_motion_rejection is not None:
            candidate_motion_window_conflict = unreliable_pose_motion_rejection
            candidate_motion_window_conflict["unreliable_pose_fallback_conflicts_used"] = True
            candidate_motion_window_conflict[
                "unreliable_pose_fallback_rejection_reason"
            ] = "late_unreliable_pose_candidate_with_weak_semantic_motion"
            _remove_flags(
                resolved_keyframes,
                "semantic_keyframes_candidate_tal_conflict_ignored_unreliable_pose_fallback",
            )
            conflicts = [*conflicts, *unreliable_pose_fallback_conflicts]
    if candidate_motion_window_conflict is not None:
        candidate_motion_window_conflict["candidate_conflict_evidence"] = _semantic_candidate_tal_conflict_evidence(
            semantic_anchors,
            skeleton_anchors,
            conflicts,
            candidate_flags,
            motion_scores,
        )
        early_approach_motion_peak_support = _early_approach_motion_peak_contaminated_candidate_support(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
            conflicts,
            candidate_motion_window_conflict,
            bio_data,
            peak_timestamp=_float_or_none(candidate_motion_window_conflict.get("global_peak_timestamp")) or 0.0,
            global_peak=_float_or_none(candidate_motion_window_conflict.get("global_peak_motion_score")) or 0.0,
            core_peak=_float_or_none(
                (candidate_motion_window_conflict.get("semantic_window") or {}).get("peak_motion_score")
                if isinstance(candidate_motion_window_conflict.get("semantic_window"), dict)
                else None
            )
            or 0.0,
            strong_records=[
                {
                    "timestamp": _float_or_none(candidate_motion_window_conflict.get("global_peak_timestamp")) or 0.0,
                    "motion_score": _float_or_none(candidate_motion_window_conflict.get("global_peak_motion_score")) or 0.0,
                }
            ],
            tolerance=VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_TOLERANCE_SEC,
        )
        if early_approach_motion_peak_support is not None:
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "candidate_support": early_approach_motion_peak_support,
                "decision": "ignored_early_approach_motion_peak_candidate_window",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_candidate_motion_window_conflict_ignored_early_approach_motion_peak",
            )
            return []
        if _has_insufficient_pose_low_visibility_motion_fallback(
            bio_data,
            required_keys={"T", "A", "L"},
        ):
            low_visibility_current_motion_rejection = _low_visibility_reuse_conflict_should_reject_for_current_motion(
                semantic_anchors,
                skeleton_anchors,
                motion_scores,
            )
            if low_visibility_current_motion_rejection is not None:
                conflict_keys = {str(item.get("key")) for item in conflicts if isinstance(item.get("key"), str)}
                reject_without_pose_support = _low_visibility_no_pose_current_motion_rejection_should_reject(
                    low_visibility_current_motion_rejection,
                    bio_data,
                )
                if (
                    not reject_without_pose_support
                    and not _bounded_motion_fallback_conflict_has_pose_support(bio_data, conflict_keys)
                ):
                    resolved_keyframes["semantic_candidate_tal_conflict"] = {
                        "conflicts": conflicts,
                        "candidate_quality_flags": candidate_flags,
                        "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                        "motion_window_conflict": candidate_motion_window_conflict,
                        "low_visibility_motion_fallback_keys": sorted(
                            _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
                        ),
                        "current_motion_rejection": low_visibility_current_motion_rejection,
                        "decision": "ignored_low_visibility_current_motion_window_without_pose_support",
                    }
                    _append_flag(
                        resolved_keyframes,
                        "semantic_keyframes_candidate_motion_window_conflict_ignored_low_visibility_no_pose_support",
                    )
                    return []
                resolved_keyframes["semantic_candidate_tal_conflict"] = {
                    "conflicts": conflicts,
                    "candidate_quality_flags": candidate_flags,
                    "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                    "motion_window_conflict": candidate_motion_window_conflict,
                    "low_visibility_motion_fallback_keys": sorted(
                        _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
                    ),
                    "current_motion_rejection": low_visibility_current_motion_rejection,
                    "decision": (
                        "rejected_low_visibility_current_motion_window_conflict_without_pose_support"
                        if reject_without_pose_support
                        and not _bounded_motion_fallback_conflict_has_pose_support(bio_data, conflict_keys)
                        else "rejected_low_visibility_current_motion_window_conflict"
                    ),
                }
                _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_candidate_motion_window_conflict")
                return ["semantic_keyframes_unreliable_candidate_motion_window_conflict"]
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "low_visibility_motion_fallback_keys": sorted(
                    _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
                ),
                "decision": "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
            )
            return []
        if _semantic_motion_window_conflict_should_ignore_compressed_candidate(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
        ):
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "decision": "ignored_compressed_candidate_motion_window_conflict",
            }
            _append_flag(resolved_keyframes, "semantic_keyframes_candidate_motion_window_conflict_ignored_compressed_candidate")
            return []
        if _semantic_motion_window_conflict_should_ignore_weak_candidate(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
            candidate_motion_window_conflict,
        ):
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "decision": "ignored_weak_candidate_motion_window_conflict",
            }
            _append_flag(resolved_keyframes, "semantic_keyframes_candidate_motion_window_conflict_ignored_weak_candidate")
            return []
        if _semantic_motion_window_conflict_should_ignore_full_context_weak_candidate(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
            candidate_motion_window_conflict,
            motion_scores,
        ):
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "decision": "ignored_full_context_weak_candidate_motion_window_conflict",
            }
            _append_flag(resolved_keyframes, "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_weak_candidate")
            return []
        if _semantic_motion_window_conflict_should_ignore_weak_geometry_candidate(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
            candidate_motion_window_conflict,
        ):
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "decision": "ignored_weak_geometry_candidate_motion_window_conflict",
            }
            _append_flag(resolved_keyframes, "semantic_keyframes_candidate_motion_window_conflict_ignored_weak_geometry_candidate")
            return []
        if _full_context_takeoff_anchor_fallback_override(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
            motion_scores,
            bio_data,
        ):
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "decision": "ignored_full_context_takeoff_anchor_motion_fallback_tail_window",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_takeoff_anchor_fallback",
            )
            return []
        if _early_takeoff_anchor_fallback_override(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
            candidate_motion_window_conflict,
            bio_data,
        ):
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "decision": "ignored_early_takeoff_anchor_motion_fallback_window",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_candidate_motion_window_conflict_ignored_early_takeoff_anchor_fallback",
            )
            return []
        if _early_takeoff_anchor_approach_motion_window_override(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
            candidate_motion_window_conflict,
            bio_data,
        ):
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "decision": "ignored_early_takeoff_anchor_approach_motion_window",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_candidate_motion_window_conflict_ignored_early_candidate_approach_window",
            )
            return []
        if _takeoff_anchor_phase_shifted_candidate_override(
            resolved_keyframes,
            skeleton_anchors,
            candidate_flags,
            candidate_motion_window_conflict,
            bio_data,
        ):
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "motion_window_conflict": candidate_motion_window_conflict,
                "decision": "ignored_takeoff_anchor_phase_shifted_candidate",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_candidate_motion_window_conflict_ignored_takeoff_anchor_phase_shift",
            )
            return []
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": candidate_flags,
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "motion_window_conflict": candidate_motion_window_conflict,
            "decision": "rejected_candidate_motion_window_conflict",
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_candidate_motion_window_conflict")
        return ["semantic_keyframes_unreliable_candidate_motion_window_conflict"]
    takeoff_single_conflict = _semantic_candidate_takeoff_single_conflict_diagnostic(
        semantic_anchors,
        skeleton_anchors,
        conflicts,
        motion_scores,
    )
    if takeoff_single_conflict is not None:
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": candidate_flags,
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "takeoff_single_conflict": takeoff_single_conflict,
            "decision": "rejected_candidate_takeoff_single_conflict",
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_candidate_takeoff_single_conflict")
        return ["semantic_keyframes_unreliable_candidate_takeoff_single_conflict"]
    early_takeoff_conflict = _semantic_candidate_early_takeoff_conflict_diagnostic(
        semantic_anchors,
        skeleton_anchors,
        conflicts,
        motion_scores,
    )
    if early_takeoff_conflict is not None:
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": candidate_flags,
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "early_takeoff_conflict": early_takeoff_conflict,
            "decision": "rejected_candidate_early_takeoff_conflict",
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_candidate_early_takeoff_conflict")
        return ["semantic_keyframes_unreliable_candidate_early_takeoff_conflict"]
    if absent_landing_geometry_only:
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": candidate_flags,
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "decision": "ignored_absent_landing_geometry_candidate",
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_candidate_tal_conflict_ignored_weak_geometry")
        return []
    if unreliable_pose_motion_fallback and takeoff_anchor_core_conflict:
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "ignored_unreliable_pose_fallback_conflicts": unreliable_pose_fallback_conflicts,
            "candidate_quality_flags": candidate_flags,
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "unreliable_pose_records": (
                (bio_data or {}).get("key_frame_candidates", {}).get("motion_fallback_unreliable_pose_records")
                if isinstance((bio_data or {}).get("key_frame_candidates"), dict)
                else None
            ),
            "decision": "ignored_unreliable_pose_motion_fallback_candidate",
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_candidate_tal_conflict_ignored_unreliable_pose_fallback")
        return []
    if _long_unresolved_motion_fallback_reuse_override(resolved_keyframes, bio_data):
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": candidate_flags,
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
            "decision": "ignored_reused_semantic_over_long_unresolved_motion_fallback",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_reused_ignored_long_unresolved_motion_fallback",
        )
        return []
    late_pose_core_conflict = _late_pose_core_candidate_conflict_should_reject(
        semantic_anchors,
        skeleton_anchors,
        candidate_flags,
        motion_scores,
    )
    if late_pose_core_conflict is not None:
        if "semantic_keyframes_reused_from_clean_video_tal_late_weak_candidate_source" in existing_flags:
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": late_pose_core_conflict["conflicts"],
                "candidate_quality_flags": candidate_flags,
                "candidate_conflict_evidence": late_pose_core_conflict["candidate_conflict_evidence"],
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "decision": "ignored_clean_video_tal_over_late_weak_candidate",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_candidate_tal_conflict_ignored_clean_video_late_weak_candidate",
            )
            return []
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": late_pose_core_conflict["conflicts"],
            "candidate_quality_flags": candidate_flags,
            "candidate_conflict_evidence": late_pose_core_conflict["candidate_conflict_evidence"],
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "decision": late_pose_core_conflict["decision"],
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_candidate_tal_conflict")
        return ["semantic_keyframes_unreliable_candidate_tal_conflict"]
    if _has_insufficient_pose_low_visibility_motion_fallback(
        bio_data,
        required_keys={"T", "A", "L"},
    ):
        low_visibility_current_motion_rejection = _low_visibility_reuse_conflict_should_reject_for_current_motion(
            semantic_anchors,
            skeleton_anchors,
            motion_scores,
        )
        if low_visibility_current_motion_rejection is not None:
            conflict_keys = {str(item.get("key")) for item in conflicts if isinstance(item.get("key"), str)}
            reject_without_pose_support = _low_visibility_no_pose_current_motion_rejection_should_reject(
                low_visibility_current_motion_rejection,
                bio_data,
            )
            if (
                not reject_without_pose_support
                and not _bounded_motion_fallback_conflict_has_pose_support(bio_data, conflict_keys)
            ):
                resolved_keyframes["semantic_candidate_tal_conflict"] = {
                    "conflicts": conflicts,
                    "candidate_quality_flags": candidate_flags,
                    "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                    "low_visibility_motion_fallback_keys": sorted(
                        _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
                    ),
                    "current_motion_rejection": low_visibility_current_motion_rejection,
                    "decision": "ignored_low_visibility_current_motion_window_without_pose_support",
                }
                _append_flag(
                    resolved_keyframes,
                    "semantic_keyframes_candidate_tal_conflict_ignored_low_visibility_no_pose_support",
                )
                return []
            resolved_keyframes["semantic_candidate_tal_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": candidate_flags,
                "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
                "low_visibility_motion_fallback_keys": sorted(
                    _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
                ),
                "current_motion_rejection": low_visibility_current_motion_rejection,
                "decision": (
                    "rejected_low_visibility_current_motion_window_conflict_without_pose_support"
                    if reject_without_pose_support
                    and not _bounded_motion_fallback_conflict_has_pose_support(bio_data, conflict_keys)
                    else "rejected_low_visibility_current_motion_window_conflict"
                ),
            }
            _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_candidate_tal_conflict")
            return ["semantic_keyframes_unreliable_candidate_tal_conflict"]
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": candidate_flags,
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "low_visibility_motion_fallback_keys": sorted(
                _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
            ),
            "decision": "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_candidate_tal_conflict_ignored_insufficient_pose_low_visibility_fallback",
        )
        return []
    if weak_temporal_geometry:
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": candidate_flags,
            "candidate_conflict_evidence": _semantic_candidate_tal_conflict_evidence(
                semantic_anchors,
                skeleton_anchors,
                conflicts,
                candidate_flags,
                motion_scores,
            ),
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "decision": "ignored_weak_temporal_geometry_candidate",
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry")
        return []
    if len(conflicts) < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_KEYS and not takeoff_anchor_core_conflict:
        return []

    weak_geometry_main_motion_support = _weak_geometry_candidate_conflict_should_ignore_for_semantic_main_motion(
        resolved_keyframes,
        semantic_anchors,
        skeleton_anchors,
        conflicts,
        candidate_flags,
        motion_scores,
    )
    if weak_geometry_main_motion_support is not None:
        resolved_keyframes["semantic_candidate_tal_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": candidate_flags,
            "candidate_conflict_evidence": _semantic_candidate_tal_conflict_evidence(
                semantic_anchors,
                skeleton_anchors,
                conflicts,
                candidate_flags,
                motion_scores,
            ),
            "main_motion_support": weak_geometry_main_motion_support,
            "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
            "decision": "ignored_early_weak_geometry_candidate_main_motion_supports_semantic_tal",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_candidate_tal_conflict_ignored_main_motion_supported_weak_geometry",
        )
        return []

    resolved_keyframes["semantic_candidate_tal_conflict"] = {
        "conflicts": conflicts,
        "candidate_quality_flags": candidate_flags,
        "takeoff_anchor_core_conflict": takeoff_anchor_core_conflict,
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_candidate_tal_conflict")
    return ["semantic_keyframes_unreliable_candidate_tal_conflict"]


def _semantic_reuse_current_candidate_conflict_flags(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
    motion_scores: dict[str, object] | None = None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return []
    flags = set(_quality_flags(resolved_keyframes))
    if "semantic_keyframes_reused_from_matching_video" not in flags:
        return []

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    if not (candidate_flags & SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_CONTEXT_FLAGS):
        return []

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or len(skeleton_anchors) < SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_MIN_KEYS:
        return []

    conflicts: list[dict[str, float | str]] = []
    for key in ("T", "A", "L"):
        candidate = skeleton_anchors.get(key)
        if not isinstance(candidate, dict):
            continue
        if candidate["confidence"] < SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_MIN_CONFIDENCE:
            continue
        delta = semantic_anchors[key] - candidate["timestamp"]
        if abs(delta) < SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_MIN_SHIFT_SECONDS:
            continue
        conflicts.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(candidate["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(candidate["confidence"], 3),
            }
        )

    if len(conflicts) < SEMANTIC_REUSE_CURRENT_CANDIDATE_CONFLICT_MIN_KEYS:
        return []

    weak_temporal_geometry = bool(candidate_flags & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS)
    blocking_candidate_context = candidate_flags & (
        SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS
        | SEMANTIC_CANDIDATE_UNRELIABLE_POSE_FALLBACK_FLAGS
        | {
            "keyframe_candidates_motion_fallback",
            "keyframe_candidates_motion_fallback_from_takeoff_anchor",
            "tal_candidate_motion_fallback_low_precision",
            "tal_candidate_skeleton_drifted_after_takeoff",
        }
    )
    if weak_temporal_geometry and not blocking_candidate_context:
        resolved_keyframes["semantic_reuse_current_candidate_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": sorted(candidate_flags),
            "candidate_conflict_evidence": _semantic_candidate_tal_conflict_evidence(
                semantic_anchors,
                skeleton_anchors,
                conflicts,
                sorted(candidate_flags),
                motion_scores,
            ),
            "decision": "ignored_weak_temporal_geometry_candidate",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_reuse_candidate_conflict_ignored_weak_temporal_geometry",
        )
        return []

    if _long_unresolved_motion_fallback_reuse_override(resolved_keyframes, bio_data):
        resolved_keyframes["semantic_reuse_current_candidate_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": sorted(candidate_flags),
            "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
            "decision": "ignored_reused_semantic_over_long_unresolved_motion_fallback",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_reuse_candidate_conflict_ignored_long_unresolved_motion_fallback",
        )
        return []

    if (
        "semantic_keyframes_reused_over_sparse_track_stitched_candidate" in flags
        and candidate_flags & SEMANTIC_REUSE_SPARSE_TRACK_STITCHED_CANDIDATE_FLAGS
    ):
        resolved_keyframes["semantic_reuse_current_candidate_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": sorted(candidate_flags),
            "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
            "decision": "ignored_reused_semantic_over_sparse_track_stitched_candidate",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_reuse_candidate_conflict_ignored_sparse_track_stitched_candidate",
        )
        return []

    accepted_full_context_takeoff_anchor = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_takeoff_anchor_fallback"
        in flags
    )
    accepted_early_takeoff_anchor = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_early_takeoff_anchor_fallback"
        in flags
    )
    accepted_early_candidate_approach_window = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_early_candidate_approach_window"
        in flags
    )
    accepted_takeoff_anchor_phase_shift = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_takeoff_anchor_phase_shift"
        in flags
    )
    if (
        accepted_full_context_takeoff_anchor
        or accepted_early_takeoff_anchor
        or accepted_early_candidate_approach_window
        or accepted_takeoff_anchor_phase_shift
    ):
        existing_candidate_conflict = resolved_keyframes.get("semantic_candidate_tal_conflict")
        motion_window_conflict = (
            existing_candidate_conflict.get("motion_window_conflict")
            if isinstance(existing_candidate_conflict, dict)
            else None
        )
        if accepted_takeoff_anchor_phase_shift:
            decision = "ignored_reused_semantic_over_takeoff_anchor_phase_shift"
            flag = "semantic_keyframes_reuse_candidate_conflict_ignored_takeoff_anchor_phase_shift"
        elif accepted_early_candidate_approach_window:
            decision = "ignored_reused_semantic_over_early_candidate_approach_window"
            flag = "semantic_keyframes_reuse_candidate_conflict_ignored_early_candidate_approach_window"
        elif accepted_early_takeoff_anchor:
            decision = "ignored_reused_semantic_over_early_takeoff_anchor_motion_fallback"
            flag = "semantic_keyframes_reuse_candidate_conflict_ignored_early_takeoff_anchor_fallback"
        else:
            decision = "ignored_reused_semantic_over_full_context_takeoff_anchor_motion_fallback"
            flag = "semantic_keyframes_reuse_candidate_conflict_ignored_full_context_takeoff_anchor_fallback"
        resolved_keyframes["semantic_reuse_current_candidate_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": sorted(candidate_flags),
            "motion_window_conflict": motion_window_conflict,
            "decision": decision,
        }
        _append_flag(resolved_keyframes, flag)
        return []

    if _has_insufficient_pose_low_visibility_motion_fallback(
        bio_data,
        required_keys={str(item.get("key")) for item in conflicts if isinstance(item.get("key"), str)},
    ):
        low_visibility_current_motion_rejection = _low_visibility_reuse_conflict_should_reject_for_current_motion(
            semantic_anchors,
            skeleton_anchors,
            motion_scores,
        )
        if low_visibility_current_motion_rejection is not None:
            conflict_keys = {str(item.get("key")) for item in conflicts if isinstance(item.get("key"), str)}
            reject_without_pose_support = _low_visibility_no_pose_current_motion_rejection_should_reject(
                low_visibility_current_motion_rejection,
                bio_data,
            )
            if (
                not reject_without_pose_support
                and not _bounded_motion_fallback_conflict_has_pose_support(bio_data, conflict_keys)
            ):
                resolved_keyframes["semantic_reuse_current_candidate_conflict"] = {
                    "conflicts": conflicts,
                    "candidate_quality_flags": sorted(candidate_flags),
                    "low_visibility_motion_fallback_keys": sorted(
                        _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
                    ),
                    "current_motion_rejection": low_visibility_current_motion_rejection,
                    "decision": "ignored_reused_semantic_current_motion_window_without_pose_support",
                }
                _append_flag(
                    resolved_keyframes,
                    "semantic_keyframes_reuse_candidate_conflict_ignored_low_visibility_no_pose_support",
                )
                return []
            resolved_keyframes["semantic_reuse_current_candidate_conflict"] = {
                "conflicts": conflicts,
                "candidate_quality_flags": sorted(candidate_flags),
                "low_visibility_motion_fallback_keys": sorted(
                    _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
                ),
                "current_motion_rejection": low_visibility_current_motion_rejection,
                "decision": (
                    "rejected_reused_semantic_current_motion_window_conflict_without_pose_support"
                    if reject_without_pose_support
                    and not _bounded_motion_fallback_conflict_has_pose_support(bio_data, conflict_keys)
                    else "rejected_reused_semantic_current_motion_window_conflict"
                ),
            }
            _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_reused_current_candidate_conflict")
            return ["semantic_keyframes_unreliable_reused_current_candidate_conflict"]
        resolved_keyframes["semantic_reuse_current_candidate_conflict"] = {
            "conflicts": conflicts,
            "candidate_quality_flags": sorted(candidate_flags),
            "low_visibility_motion_fallback_keys": sorted(
                _insufficient_pose_low_visibility_motion_fallback_keys(bio_data)
            ),
            "decision": "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_reuse_candidate_conflict_ignored_insufficient_pose_low_visibility_fallback",
        )
        return []

    resolved_keyframes["semantic_reuse_current_candidate_conflict"] = {
        "conflicts": conflicts,
        "candidate_quality_flags": sorted(candidate_flags),
        "decision": "rejected_reused_semantic_current_candidate_conflict",
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_reused_current_candidate_conflict")
    return ["semantic_keyframes_unreliable_reused_current_candidate_conflict"]


def _low_visibility_reuse_conflict_should_reject_for_current_motion(
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    motion_scores: dict[str, object] | None,
) -> dict[str, Any] | None:
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "L"}.issubset(skeleton_anchors):
        return None
    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3:
        return None
    global_peak = max((record["motion_score"] for record in records), default=0.0)
    if global_peak <= 0.0:
        return None

    semantic_start = min(semantic_anchors["T"], semantic_anchors["L"])
    semantic_end = max(semantic_anchors["T"], semantic_anchors["L"])
    candidate_window_values = [skeleton_anchors["T"]["timestamp"], skeleton_anchors["L"]["timestamp"]]
    for anchor in skeleton_anchors.values():
        start = _float_or_none(anchor.get("motion_window_start"))
        end = _float_or_none(anchor.get("motion_window_end"))
        if start is not None and end is not None:
            candidate_window_values.extend([start, end])
    candidate_start = min(candidate_window_values)
    candidate_end = max(candidate_window_values)
    separation = _window_separation_seconds(
        {"start_sec": semantic_start, "end_sec": semantic_end},
        {"start_sec": candidate_start, "end_sec": candidate_end},
    )
    if separation is None:
        return None
    near_candidate_window = separation < SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_MIN_SEPARATION_SEC
    local_core_rejection = _low_visibility_local_core_motion_rejection(
        semantic_anchors,
        skeleton_anchors,
        records,
        global_peak,
        semantic_window={"start_sec": semantic_start, "end_sec": semantic_end},
        candidate_window={"start_sec": candidate_start, "end_sec": candidate_end},
        window_separation_sec=separation,
    )
    if near_candidate_window and separation < SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_NEAR_MIN_SEPARATION_SEC:
        if local_core_rejection is not None:
            return local_core_rejection
        return None
    semantic_tolerance = 0.0 if near_candidate_window else SEMANTIC_CANDIDATE_MOTION_WINDOW_TOLERANCE_SECONDS
    candidate_tolerance = 0.0 if near_candidate_window else SEMANTIC_CANDIDATE_MOTION_WINDOW_TOLERANCE_SECONDS

    semantic_peak = _peak_motion_in_window(records, semantic_start, semantic_end, tolerance=semantic_tolerance)
    candidate_peak = _peak_motion_in_window(records, candidate_start, candidate_end, tolerance=candidate_tolerance)
    if near_candidate_window:
        if global_peak < SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_NEAR_MIN_GLOBAL_PEAK:
            return None
        if candidate_peak < global_peak * SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_NEAR_CANDIDATE_PEAK_RATIO:
            return None
    if candidate_peak < global_peak * SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_CANDIDATE_PEAK_RATIO:
        return None
    if semantic_peak >= global_peak * SEMANTIC_REUSE_LOW_VISIBILITY_OVERRIDE_SEMANTIC_PEAK_RATIO:
        if local_core_rejection is not None:
            return local_core_rejection
        return None

    peak_record = max(records, key=lambda record: record["motion_score"])
    return {
        "global_peak_timestamp": round(peak_record["timestamp"], 3),
        "global_peak_motion_score": round(global_peak, 5),
        "semantic_window": {
            "start_sec": round(semantic_start, 3),
            "end_sec": round(semantic_end, 3),
            "peak_motion_score": round(semantic_peak, 5),
        },
        "candidate_window": {
            "start_sec": round(candidate_start, 3),
            "end_sec": round(candidate_end, 3),
            "peak_motion_score": round(candidate_peak, 5),
        },
        "semantic_peak_ratio": round(semantic_peak / max(global_peak, 1e-9), 3),
        "candidate_peak_ratio": round(candidate_peak / max(global_peak, 1e-9), 3),
        "window_separation_sec": round(separation, 3),
        "near_candidate_window": near_candidate_window,
    }


def _low_visibility_no_pose_current_motion_rejection_should_reject(
    current_motion_rejection: dict[str, Any],
    bio_data: dict[str, Any] | None,
) -> bool:
    if not _fallback_selected_from_keyframe_candidates(bio_data):
        return False
    global_peak = _float_or_none(current_motion_rejection.get("global_peak_motion_score"))
    candidate_peak_ratio = _float_or_none(current_motion_rejection.get("candidate_peak_ratio"))
    semantic_peak_ratio = _float_or_none(current_motion_rejection.get("semantic_peak_ratio"))
    if global_peak is None or global_peak < SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MIN_GLOBAL_PEAK:
        return False
    if (
        candidate_peak_ratio is None
        or candidate_peak_ratio < SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MIN_CANDIDATE_PEAK_RATIO
    ):
        return False
    if (
        semantic_peak_ratio is None
        or semantic_peak_ratio > SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MAX_SEMANTIC_PEAK_RATIO
    ):
        return False
    return True


def _low_visibility_local_core_motion_rejection(
    semantic_anchors: dict[str, float],
    skeleton_anchors: dict[str, dict[str, float]],
    records: Sequence[dict[str, float]],
    global_peak: float,
    *,
    semantic_window: dict[str, float],
    candidate_window: dict[str, float],
    window_separation_sec: float,
) -> dict[str, Any] | None:
    if global_peak < SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MIN_GLOBAL_PEAK:
        return None
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None
    takeoff_after_semantic_landing = skeleton_anchors["T"]["timestamp"] - semantic_anchors["L"]
    if takeoff_after_semantic_landing > SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MAX_TAKEOFF_AFTER_SEMANTIC_L_SEC:
        return None

    conflicts: list[dict[str, float | str]] = []
    semantic_local_peaks: list[float] = []
    candidate_local_peaks: list[float] = []
    for key in ("T", "A"):
        semantic_timestamp = semantic_anchors[key]
        candidate_timestamp = skeleton_anchors[key]["timestamp"]
        shift = candidate_timestamp - semantic_timestamp
        if shift < SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MIN_SHIFT_SECONDS:
            continue
        semantic_peak = _peak_motion_in_window(
            records,
            semantic_timestamp,
            semantic_timestamp,
            tolerance=SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MOTION_WINDOW_SECONDS,
        )
        candidate_peak = max(
            _float_or_none(skeleton_anchors[key].get("motion_score")) or 0.0,
            _peak_motion_in_window(
                records,
                candidate_timestamp,
                candidate_timestamp,
                tolerance=SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MOTION_WINDOW_SECONDS,
            ),
        )
        semantic_local_peaks.append(semantic_peak)
        candidate_local_peaks.append(candidate_peak)
        conflicts.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_timestamp, 3),
                "candidate_timestamp": round(candidate_timestamp, 3),
                "delta_sec": round(semantic_timestamp - candidate_timestamp, 3),
                "semantic_local_peak_motion_score": round(semantic_peak, 5),
                "candidate_local_peak_motion_score": round(candidate_peak, 5),
            }
        )
    if len(conflicts) < SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MIN_CONFLICT_KEYS:
        return None

    semantic_peak = max(semantic_local_peaks, default=0.0)
    candidate_peak = max(candidate_local_peaks, default=0.0)
    if candidate_peak < global_peak * SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MIN_CANDIDATE_PEAK_RATIO:
        return None
    if semantic_peak > global_peak * SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MAX_SEMANTIC_PEAK_RATIO:
        return None

    peak_record = max(records, key=lambda record: record["motion_score"])
    return {
        "global_peak_timestamp": round(peak_record["timestamp"], 3),
        "global_peak_motion_score": round(global_peak, 5),
        "semantic_window": {
            "start_sec": round(float(semantic_window["start_sec"]), 3),
            "end_sec": round(float(semantic_window["end_sec"]), 3),
            "peak_motion_score": round(semantic_peak, 5),
            "peak_scope": "local_core_ta",
        },
        "candidate_window": {
            "start_sec": round(float(candidate_window["start_sec"]), 3),
            "end_sec": round(float(candidate_window["end_sec"]), 3),
            "peak_motion_score": round(candidate_peak, 5),
            "peak_scope": "local_core_ta",
        },
        "semantic_peak_ratio": round(semantic_peak / max(global_peak, 1e-9), 3),
        "candidate_peak_ratio": round(candidate_peak / max(global_peak, 1e-9), 3),
        "window_separation_sec": round(window_separation_sec, 3),
        "near_candidate_window": True,
        "local_core_motion_conflict": {
            "keys": [str(item["key"]) for item in conflicts],
            "conflicts": conflicts,
            "takeoff_after_semantic_landing_sec": round(takeoff_after_semantic_landing, 3),
            "motion_window_sec": SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MOTION_WINDOW_SECONDS,
        },
    }


def _maybe_align_low_visibility_main_motion_candidates(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    motion_scores: dict[str, object] | None,
    *,
    analysis_profile: str | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    if not _has_insufficient_pose_low_visibility_motion_fallback(
        bio_data,
        required_keys={"T", "A", "L"},
    ):
        return False
    if _video_confidence(
        resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else None,
        resolved_keyframes,
    ) < SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_CONFIDENCE_FLOOR:
        return False

    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return False
    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return False
    takeoff_after_semantic_landing = skeleton_anchors["T"]["timestamp"] - semantic_anchors["L"]
    if takeoff_after_semantic_landing > SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_MAX_TAKEOFF_AFTER_SEMANTIC_L_SEC:
        return False

    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3:
        return False
    global_peak = max((record["motion_score"] for record in records), default=0.0)
    if global_peak < SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MIN_GLOBAL_PEAK:
        return False

    selected_by_key: dict[str, dict[str, Any]] = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item)
        if key in {"T", "A", "L"} and key not in selected_by_key:
            selected_by_key[key] = item
    if not {"T", "A", "L"}.issubset(selected_by_key):
        return False

    def local_peak(timestamp: float) -> float:
        return _peak_motion_in_window(
            records,
            timestamp,
            timestamp,
            tolerance=SEMANTIC_REUSE_LOW_VISIBILITY_LOCAL_CORE_MOTION_WINDOW_SECONDS,
        )

    def candidate_peak(key: str) -> float:
        return max(
            _float_or_none(skeleton_anchors[key].get("motion_score")) or 0.0,
            local_peak(skeleton_anchors[key]["timestamp"]),
        )

    def extended_takeoff_overlap_allowed(shift: float) -> bool:
        if shift > SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_EXTENDED_T_MAX_SHIFT_SEC:
            return False
        candidate_t = skeleton_anchors["T"]["timestamp"]
        candidate_a = skeleton_anchors["A"]["timestamp"]
        candidate_l = skeleton_anchors["L"]["timestamp"]
        return (
            candidate_t >= semantic_anchors["A"] - SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_EXTENDED_T_APEX_LEAD_SEC
            and candidate_t <= semantic_anchors["L"] + SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_EXTENDED_T_LANDING_TOLERANCE_SEC
            and candidate_a <= semantic_anchors["L"] + SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_EXTENDED_T_LANDING_TOLERANCE_SEC
            and candidate_l <= semantic_anchors["L"] + SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_EXTENDED_T_LANDING_TOLERANCE_SEC
        )

    adjustments: dict[str, dict[str, float | str]] = {}
    for key in ("T", "A"):
        semantic_timestamp = semantic_anchors[key]
        candidate_timestamp = skeleton_anchors[key]["timestamp"]
        shift = candidate_timestamp - semantic_timestamp
        if shift < SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_MIN_SHIFT_SEC:
            continue
        standard_shift = shift <= SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_MAX_SHIFT_SEC
        extended_takeoff_shift = key == "T" and extended_takeoff_overlap_allowed(shift)
        if not standard_shift and not extended_takeoff_shift:
            continue
        semantic_peak = local_peak(semantic_timestamp)
        candidate_motion_peak = candidate_peak(key)
        if candidate_motion_peak < global_peak * SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MIN_CANDIDATE_PEAK_RATIO:
            continue
        semantic_peak_is_weak = semantic_peak <= global_peak * SEMANTIC_REUSE_LOW_VISIBILITY_NO_POSE_REJECT_MAX_SEMANTIC_PEAK_RATIO
        apex_collapsed_to_takeoff = (
            key == "A"
            and semantic_timestamp
            <= skeleton_anchors["T"]["timestamp"] + SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_APEX_COLLAPSED_TO_TAKEOFF_SEC
        )
        if not semantic_peak_is_weak and not apex_collapsed_to_takeoff:
            continue
        adjustments[key] = {
            "key": key,
            "semantic_timestamp": round(semantic_timestamp, 3),
            "candidate_timestamp": round(candidate_timestamp, 3),
            "delta_sec": round(candidate_timestamp - semantic_timestamp, 3),
            "semantic_local_peak_motion_score": round(semantic_peak, 5),
            "candidate_local_peak_motion_score": round(candidate_motion_peak, 5),
            "alignment_mode": "extended_overlap_takeoff" if extended_takeoff_shift else "standard",
        }
    if not {"T", "A"}.issubset(adjustments):
        return False

    landing_shift = skeleton_anchors["L"]["timestamp"] - semantic_anchors["L"]
    landing_candidate_peak = candidate_peak("L")
    if (
        abs(landing_shift) <= SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_LANDING_MAX_SHIFT_SEC
        and landing_candidate_peak
        >= global_peak * SEMANTIC_LOW_VISIBILITY_MAIN_MOTION_ALIGNMENT_LANDING_MIN_PEAK_RATIO
    ):
        adjustments["L"] = {
            "key": "L",
            "semantic_timestamp": round(semantic_anchors["L"], 3),
            "candidate_timestamp": round(skeleton_anchors["L"]["timestamp"], 3),
            "delta_sec": round(landing_shift, 3),
            "semantic_local_peak_motion_score": round(local_peak(semantic_anchors["L"]), 5),
            "candidate_local_peak_motion_score": round(landing_candidate_peak, 5),
        }

    proposed = dict(semantic_anchors)
    for key in adjustments:
        proposed[key] = skeleton_anchors[key]["timestamp"]
    if not (proposed["T"] + 0.02 < proposed["A"] and proposed["A"] + 0.02 < proposed["L"]):
        return False

    for key, adjustment in adjustments.items():
        record = selected_by_key[key]
        original_timestamp = _float_or_none(record.get("timestamp"))
        if original_timestamp is not None and record.get("pre_motion_alignment_timestamp") is None:
            record["pre_motion_alignment_timestamp"] = round(original_timestamp, 3)
        record["timestamp"] = round(skeleton_anchors[key]["timestamp"], 3)
        record["motion_alignment_source"] = "low_visibility_main_motion_candidate"
        record["motion_alignment_delta_sec"] = adjustment["delta_sec"]
        record["motion_alignment_candidate_confidence"] = round(skeleton_anchors[key]["confidence"], 3)
        record["motion_alignment_candidate_motion_score"] = adjustment["candidate_local_peak_motion_score"]

    video_ai = resolved_keyframes.get("video_ai")
    if isinstance(video_ai, dict):
        key_moments = video_ai.get("key_moments")
        if isinstance(key_moments, dict):
            updated_key_moments = dict(key_moments)
            moment_names = {"T": "T_takeoff_sec", "A": "A_air_sec", "L": "L_landing_sec"}
            for key in adjustments:
                updated_key_moments[moment_names[key]] = round(skeleton_anchors[key]["timestamp"], 3)
            video_ai["key_moments"] = updated_key_moments

    peak_record = max(records, key=lambda record: record["motion_score"])
    resolved_keyframes["semantic_low_visibility_main_motion_alignment"] = {
        "decision": "aligned_phase_range_tal_to_current_main_motion_candidates",
        "global_peak_timestamp": round(peak_record["timestamp"], 3),
        "global_peak_motion_score": round(global_peak, 5),
        "adjustments": [adjustments[key] for key in ("T", "A", "L") if key in adjustments],
        "candidate_quality_flags": _keyframe_candidate_quality_flags(bio_data),
        "takeoff_after_semantic_landing_sec": round(takeoff_after_semantic_landing, 3),
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_low_visibility_main_motion_candidate_aligned")
    return True


def _post_candidate_window_late_phase_range_reanchor_support(
    *,
    skeleton_anchors: dict[str, dict[str, float]],
    records: Sequence[dict[str, float]],
    current_anchors: dict[str, float],
    current_core_peak: float,
    global_peak: float,
    candidate_flags: set[str],
) -> dict[str, Any] | None:
    if not {"T", "A", "L"}.issubset(skeleton_anchors) or not {"T", "A", "L"}.issubset(current_anchors):
        return None
    if not (
        "tal_candidate_apex_landing_gap_compressed" in candidate_flags
        or "tal_candidate_takeoff_apex_gap_compressed" in candidate_flags
        or "tal_candidate_core_gap_compressed" in candidate_flags
    ):
        return None

    candidate_values = [skeleton_anchors[key]["timestamp"] for key in ("T", "A", "L")]
    candidate_start = min(candidate_values)
    candidate_end = max(candidate_values)
    for anchor in skeleton_anchors.values():
        start = _float_or_none(anchor.get("motion_window_start"))
        end = _float_or_none(anchor.get("motion_window_end"))
        if start is not None and end is not None and end >= start:
            candidate_start = min(candidate_start, start)
            candidate_end = max(candidate_end, end)

    if current_anchors["T"] - candidate_end < SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MIN_SHIFT_SEC:
        return None
    if global_peak <= 0.0:
        return None
    if current_core_peak > global_peak * SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MAX_CORE_PEAK_RATIO:
        return None

    support_start = max(candidate_end + 0.04, skeleton_anchors["L"]["timestamp"] + 0.04)
    support_end = min(current_anchors["T"] - 0.25, support_start + 0.85)
    support_records = [
        record
        for record in records
        if support_start <= record["timestamp"] <= support_end
    ]
    if len(support_records) < SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MIN_SUPPORT_RECORDS:
        return None

    support_peak_record = max(support_records, key=lambda record: (record["motion_score"], -record["timestamp"]))
    support_peak = support_peak_record["motion_score"]
    if support_peak < SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MIN_SUPPORT_SCORE:
        return None
    if support_peak > global_peak * SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MAX_SUPPORT_PEAK_RATIO:
        return None

    reanchor_t = min(
        support_start + SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_MAX_T_LEAD_SEC,
        candidate_end + SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_T_AFTER_L_SEC,
    )
    if reanchor_t <= candidate_end:
        return None

    return {
        "anchor_scope": "post_candidate_motion_window",
        "candidate_window": {
            "start_sec": round(candidate_start, 3),
            "end_sec": round(candidate_end, 3),
        },
        "support_window": {
            "start_sec": round(support_start, 3),
            "end_sec": round(support_end, 3),
            "record_count": len(support_records),
            "peak_timestamp": round(support_peak_record["timestamp"], 3),
            "peak_motion_score": round(support_peak, 5),
        },
        "reanchor_t": round(reanchor_t, 3),
        "semantic_shift_from_candidate_end_sec": round(current_anchors["T"] - candidate_end, 3),
        "core_peak_ratio": round(current_core_peak / global_peak, 3),
        "support_peak_ratio": round(support_peak / global_peak, 3),
    }


def _maybe_reanchor_late_phase_range_tal(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    motion_scores: dict[str, object] | None,
    *,
    analysis_profile: str | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return False
    if not _has_ordered_core_tal(resolved_keyframes):
        return False

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    weak_candidate_context = bool(
        candidate_flags
        & (
            SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
            | SEMANTIC_CANDIDATE_UNRELIABLE_POSE_FALLBACK_FLAGS
            | {
                "tal_candidate_skeleton_drifted_after_takeoff",
                "tal_candidate_weak_geometry",
                "tal_candidate_landing_geometry_weak",
                "landing_geometry_weak",
            }
        )
    )
    if not weak_candidate_context:
        return False

    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return False
    selected_by_key: dict[str, dict[str, Any]] = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item)
        if key in {"T", "A", "L"} and key not in selected_by_key:
            selected_by_key[key] = item
    if not {"T", "A", "L"}.issubset(selected_by_key):
        return False
    if any(
        not str(selected_by_key[key].get("selection_reason") or "").startswith("video_phase_range_")
        for key in ("T", "A", "L")
    ):
        return False

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return False
    if _video_confidence(video_ai, resolved_keyframes) < SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_CONFIDENCE_FLOOR:
        return False

    phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)]
    phase_by_code = {str(item.get("phase_code") or ""): item for item in phase_segments}
    preparation = phase_by_code.get("preparation")
    takeoff_segment = phase_by_code.get("takeoff")
    if not isinstance(preparation, dict) or not isinstance(takeoff_segment, dict):
        return False

    prep_start = _float_or_none(preparation.get("time_start"))
    prep_end = _float_or_none(preparation.get("time_end"))
    takeoff_start = _float_or_none(takeoff_segment.get("time_start"))
    if prep_start is None or prep_end is None or takeoff_start is None:
        return False
    if prep_end <= prep_start or takeoff_start <= prep_start:
        return False

    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3:
        return False

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    skeleton_takeoff = skeleton_anchors.get("T")
    skeleton_t = (
        _float_or_none(skeleton_takeoff.get("timestamp"))
        if isinstance(skeleton_takeoff, dict)
        else None
    )

    def valid_pre_takeoff_peak(
        source_records: Sequence[dict[str, float]],
    ) -> dict[str, float] | None:
        if not source_records:
            return None
        peak = max(source_records, key=lambda record: (record["motion_score"], -record["timestamp"]))
        if peak["motion_score"] < SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_PREP_PEAK:
            return None
        if peak["timestamp"] > takeoff_start - SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_PREP_TAKEOFF_GAP_SEC:
            return None
        return peak

    prep_records = [
        record
        for record in records
        if prep_start <= record["timestamp"] <= min(prep_end, takeoff_start)
    ]
    prep_peak_record = valid_pre_takeoff_peak(prep_records)
    anchor_scope = "preparation_phase"
    if prep_peak_record is None and skeleton_t is not None:
        skeleton_window_start = max(0.0, skeleton_t - SEMANTIC_PHASE_RANGE_LATE_REANCHOR_SKELETON_T_PRE_SEC)
        skeleton_window_end = min(
            takeoff_start - SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_PREP_TAKEOFF_GAP_SEC,
            skeleton_t + SEMANTIC_PHASE_RANGE_LATE_REANCHOR_SKELETON_T_POST_SEC,
        )
        skeleton_records = [
            record
            for record in records
            if skeleton_window_start <= record["timestamp"] <= skeleton_window_end
        ]
        prep_peak_record = valid_pre_takeoff_peak(skeleton_records)
        anchor_scope = "skeleton_takeoff_near_pre_takeoff"
    if prep_peak_record is None:
        return False

    current_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(current_anchors):
        return False

    current_core_records = [
        record
        for record in records
        if current_anchors["T"] - VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_TOLERANCE_SEC
        <= record["timestamp"]
        <= current_anchors["L"] + VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_TOLERANCE_SEC
    ]
    current_core_peak = max((record["motion_score"] for record in current_core_records), default=0.0)

    post_candidate_support: dict[str, Any] | None = None

    def use_post_candidate_support() -> bool:
        nonlocal anchor_scope, post_candidate_support, prep_peak_score, prep_peak_timestamp
        global_peak = max((record["motion_score"] for record in records), default=0.0)
        support = _post_candidate_window_late_phase_range_reanchor_support(
            skeleton_anchors=skeleton_anchors,
            records=records,
            current_anchors=current_anchors,
            current_core_peak=current_core_peak,
            global_peak=global_peak,
            candidate_flags=candidate_flags,
        )
        if support is None:
            return False
        post_candidate_support = support
        prep_peak_timestamp = float(support["reanchor_t"])
        prep_peak_score = float(support["support_window"]["peak_motion_score"])
        anchor_scope = str(support["anchor_scope"])
        return True

    if prep_peak_record is not None:
        prep_peak_timestamp = prep_peak_record["timestamp"]
        prep_peak_score = prep_peak_record["motion_score"]
        if (
            skeleton_t is not None
            and abs(prep_peak_timestamp - skeleton_t) > SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MAX_T_OFFSET_SEC
        ):
            skeleton_window_start = max(0.0, skeleton_t - SEMANTIC_PHASE_RANGE_LATE_REANCHOR_SKELETON_T_PRE_SEC)
            skeleton_window_end = min(
                takeoff_start - SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_PREP_TAKEOFF_GAP_SEC,
                skeleton_t + SEMANTIC_PHASE_RANGE_LATE_REANCHOR_SKELETON_T_POST_SEC,
            )
            skeleton_records = [
                record
                for record in records
                if skeleton_window_start <= record["timestamp"] <= skeleton_window_end
            ]
            skeleton_peak_record = valid_pre_takeoff_peak(skeleton_records)
            if skeleton_peak_record is not None:
                prep_peak_record = skeleton_peak_record
                prep_peak_timestamp = prep_peak_record["timestamp"]
                prep_peak_score = prep_peak_record["motion_score"]
                anchor_scope = "skeleton_takeoff_near_pre_takeoff"
            else:
                prep_peak_record = None

    if prep_peak_record is None:
        if not use_post_candidate_support():
            return False
    else:
        current_t = current_anchors["T"]
        if (
            current_t - prep_peak_timestamp < SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_SHIFT_SEC
            or (
                current_core_peak > 0
                and prep_peak_score < current_core_peak * SEMANTIC_PHASE_RANGE_LATE_REANCHOR_PREP_TO_CORE_PEAK_RATIO
            )
            or (
                skeleton_t is not None
                and abs(prep_peak_timestamp - skeleton_t) > SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MAX_T_OFFSET_SEC
            )
        ) and not use_post_candidate_support():
            return False

    selected_values: dict[str, float] = {}
    pre_refine_values: dict[str, float] = {}
    for key in ("T", "A", "L"):
        record = selected_by_key[key]
        selected_value = _record_timestamp(record)
        pre_refine_value = _float_or_none(record.get("pre_refine_timestamp"))
        if pre_refine_value is None:
            pre_refine_value = selected_value
        if selected_value is None or pre_refine_value is None:
            return False
        selected_values[key] = selected_value
        pre_refine_values[key] = pre_refine_value
    if not (
        selected_values["T"] < selected_values["A"] < selected_values["L"]
        and pre_refine_values["T"] < pre_refine_values["A"] < pre_refine_values["L"]
    ):
        return False

    def bounded_offset(value: float, *, minimum: float, maximum: float) -> float:
        return max(minimum, min(value, maximum))

    offsets = {
        "T": 0.0,
        "A": bounded_offset(
            pre_refine_values["A"] - pre_refine_values["T"],
            minimum=(
                SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_A_MIN_OFFSET_SEC
                if post_candidate_support is not None
                else SEMANTIC_PHASE_RANGE_LATE_REANCHOR_A_MIN_OFFSET_SEC
            ),
            maximum=(
                SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_A_MAX_OFFSET_SEC
                if post_candidate_support is not None
                else SEMANTIC_PHASE_RANGE_LATE_REANCHOR_A_MAX_OFFSET_SEC
            ),
        ),
        "L": bounded_offset(
            pre_refine_values["L"] - pre_refine_values["T"],
            minimum=(
                SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_L_MIN_OFFSET_SEC
                if post_candidate_support is not None
                else SEMANTIC_PHASE_RANGE_LATE_REANCHOR_L_MIN_OFFSET_SEC
            ),
            maximum=(
                SEMANTIC_PHASE_RANGE_LATE_REANCHOR_POST_CANDIDATE_L_MAX_OFFSET_SEC
                if post_candidate_support is not None
                else SEMANTIC_PHASE_RANGE_LATE_REANCHOR_L_MAX_OFFSET_SEC
            ),
        ),
    }
    proposed = {key: prep_peak_timestamp + offsets[key] for key in ("T", "A", "L")}
    if not (
        proposed["T"] + 0.02 < proposed["A"]
        and proposed["A"] + 0.02 < proposed["L"]
        and proposed["L"] - proposed["T"] <= SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MAX_TAL_SPAN_SEC
    ):
        return False
    if sum(1 for key in ("T", "A", "L") if current_anchors[key] - proposed[key] >= SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_SHIFT_SEC) < 2:
        return False

    adjustments: list[dict[str, float | str]] = []
    for key in ("T", "A", "L"):
        record = selected_by_key[key]
        original_timestamp = _record_timestamp(record)
        if original_timestamp is not None and record.get("pre_late_phase_reanchor_timestamp") is None:
            record["pre_late_phase_reanchor_timestamp"] = round(original_timestamp, 3)
        record["timestamp"] = round(proposed[key], 3)
        record["late_phase_range_reanchor"] = True
        record["late_phase_range_reanchor_delta_sec"] = (
            round(proposed[key] - original_timestamp, 3)
            if original_timestamp is not None
            else None
        )
        adjustments.append(
            {
                "key": key,
                "original_timestamp": round(original_timestamp, 3) if original_timestamp is not None else None,
                "reanchored_timestamp": round(proposed[key], 3),
                "delta_sec": round(proposed[key] - original_timestamp, 3)
                if original_timestamp is not None
                else None,
            }
        )

    key_moments = video_ai.get("key_moments")
    if isinstance(key_moments, dict):
        updated_key_moments = dict(key_moments)
        moment_names = {"T": "T_takeoff_sec", "A": "A_air_sec", "L": "L_landing_sec"}
        for key in ("T", "A", "L"):
            updated_key_moments[moment_names[key]] = round(proposed[key], 3)
        video_ai["key_moments"] = updated_key_moments

    resolved_keyframes["semantic_phase_range_late_reanchor"] = {
        "decision": "reanchored_late_phase_range_tal_to_pre_takeoff_motion_peak",
        "anchor_scope": anchor_scope,
        "preparation_window": {
            "start_sec": round(prep_start, 3),
            "end_sec": round(prep_end, 3),
        },
        "takeoff_phase_start_sec": round(takeoff_start, 3),
        "pre_takeoff_peak_timestamp": round(prep_peak_timestamp, 3),
        "pre_takeoff_peak_motion_score": round(prep_peak_score, 5),
        "preparation_peak_timestamp": round(prep_peak_timestamp, 3),
        "preparation_peak_motion_score": round(prep_peak_score, 5),
        "late_core_peak_motion_score": round(current_core_peak, 5),
        "candidate_quality_flags": sorted(candidate_flags),
        "adjustments": adjustments,
    }
    if post_candidate_support is not None:
        resolved_keyframes["semantic_phase_range_late_reanchor"]["post_candidate_support"] = post_candidate_support
    _append_flag(resolved_keyframes, "semantic_keyframes_phase_range_late_reanchored")
    _append_flag(resolved_keyframes, "video_temporal_resolver_phase_range_late_reanchored")
    return True


def _semantic_reuse_early_motion_cluster_conflict_flags(
    resolved_keyframes: dict[str, Any],
    motion_scores: dict[str, object] | None,
    *,
    bio_data: dict[str, Any] | None,
    analysis_profile: str | None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return []
    flags = set(_quality_flags(resolved_keyframes))
    if "semantic_keyframes_reused_from_matching_video" not in flags:
        return []

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors):
        return []

    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3:
        return []
    global_peak = max((record["motion_score"] for record in records), default=0.0)
    if global_peak < SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_MIN_SCORE:
        return []
    strong_threshold = max(
        SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_MIN_SCORE,
        global_peak * SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_RATIO,
    )
    strong_records = [record for record in records if record["motion_score"] >= strong_threshold]
    if len(strong_records) < SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_MIN_STRONG_RECORDS:
        return []

    tolerance = SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CORE_TOLERANCE_SEC
    core_start = semantic_anchors["T"]
    core_end = semantic_anchors["L"]
    core_records = [
        record
        for record in records
        if core_start - tolerance <= record["timestamp"] <= core_end + tolerance
    ]
    core_peak = max((record["motion_score"] for record in core_records), default=0.0)
    peak_record = max(records, key=lambda record: record["motion_score"])
    strong_before = all(record["timestamp"] < core_start - tolerance for record in strong_records)
    if not strong_before:
        return []
    if peak_record["timestamp"] >= core_start - tolerance:
        return []
    if core_peak >= global_peak * SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CORE_PEAK_RATIO:
        return []
    if core_start - peak_record["timestamp"] < SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_MIN_SHIFT_SECONDS:
        return []

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    if not (candidate_flags & SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CONTEXT_FLAGS):
        return []

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    candidate_window_peak = 0.0
    candidate_window: dict[str, float] | None = None
    if {"T", "L"}.issubset(skeleton_anchors):
        candidate_window_values = [
            skeleton_anchors["T"]["timestamp"],
            skeleton_anchors["L"]["timestamp"],
        ]
        for anchor in skeleton_anchors.values():
            start = _float_or_none(anchor.get("motion_window_start"))
            end = _float_or_none(anchor.get("motion_window_end"))
            if start is not None and end is not None:
                candidate_window_values.extend([start, end])
        candidate_start = min(candidate_window_values)
        candidate_end = max(candidate_window_values)
        candidate_window_peak = _peak_motion_in_window(records, candidate_start, candidate_end)
        candidate_window = {
            "start_sec": round(candidate_start, 3),
            "end_sec": round(candidate_end, 3),
            "peak_motion_score": round(candidate_window_peak, 5),
        }

    if candidate_window_peak < global_peak * SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CANDIDATE_PEAK_RATIO:
        return []

    if "semantic_keyframes_reused_from_phase_range_weak_geometry_source" in flags:
        weak_temporal_geometry_support = _phase_range_weak_temporal_geometry_motion_cluster_support(
            resolved_keyframes,
            bio_data,
            candidate_flags,
            require_video_confidence=False,
            core_peak=core_peak,
            global_peak=global_peak,
        )
        if weak_temporal_geometry_support is not None:
            resolved_keyframes["semantic_reuse_motion_cluster_conflict"] = {
                "core_start_sec": round(core_start, 3),
                "core_end_sec": round(core_end, 3),
                "peak_timestamp": round(peak_record["timestamp"], 3),
                "peak_motion_score": round(global_peak, 5),
                "core_peak_motion_score": round(core_peak, 5),
                "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                "candidate_window": candidate_window,
                "candidate_quality_flags": sorted(candidate_flags),
                "candidate_support": weak_temporal_geometry_support,
                "decision": "ignored_reused_phase_range_weak_geometry_motion_cluster",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_reuse_motion_cluster_conflict_ignored_phase_range_weak_geometry_source",
            )
            return []

    late_reanchor_support = _phase_range_late_reanchor_reuse_motion_cluster_support(
        resolved_keyframes,
        bio_data,
        candidate_flags,
        peak_timestamp=peak_record["timestamp"],
        global_peak=global_peak,
        core_peak=core_peak,
    )
    if late_reanchor_support is not None:
        resolved_keyframes["semantic_reuse_motion_cluster_conflict"] = {
            "core_start_sec": round(core_start, 3),
            "core_end_sec": round(core_end, 3),
            "peak_timestamp": round(peak_record["timestamp"], 3),
            "peak_motion_score": round(global_peak, 5),
            "core_peak_motion_score": round(core_peak, 5),
            "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
            "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
            "candidate_window": candidate_window,
            "candidate_quality_flags": sorted(candidate_flags),
            "candidate_support": late_reanchor_support,
            "decision": "ignored_reused_phase_range_late_reanchor_motion_cluster",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_reuse_motion_cluster_conflict_ignored_phase_range_late_reanchor",
        )
        return []

    if _long_unresolved_motion_fallback_reuse_override(resolved_keyframes, bio_data):
        resolved_keyframes["semantic_reuse_motion_cluster_conflict"] = {
            "core_start_sec": round(core_start, 3),
            "core_end_sec": round(core_end, 3),
            "peak_timestamp": round(peak_record["timestamp"], 3),
            "peak_motion_score": round(global_peak, 5),
            "core_peak_motion_score": round(core_peak, 5),
            "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
            "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
            "candidate_window": candidate_window,
            "candidate_quality_flags": sorted(candidate_flags),
            "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
            "decision": "ignored_reused_semantic_over_long_unresolved_motion_fallback",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_reuse_motion_cluster_conflict_ignored_long_unresolved_motion_fallback",
        )
        return []

    if (
        "semantic_keyframes_reused_over_sparse_track_stitched_candidate" in flags
        and candidate_flags & SEMANTIC_REUSE_SPARSE_TRACK_STITCHED_CANDIDATE_FLAGS
        and candidate_window is not None
        and candidate_window_peak >= global_peak * SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CANDIDATE_PEAK_RATIO
    ):
        resolved_keyframes["semantic_reuse_motion_cluster_conflict"] = {
            "core_start_sec": round(core_start, 3),
            "core_end_sec": round(core_end, 3),
            "peak_timestamp": round(peak_record["timestamp"], 3),
            "peak_motion_score": round(global_peak, 5),
            "core_peak_motion_score": round(core_peak, 5),
            "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
            "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
            "candidate_window": candidate_window,
            "candidate_quality_flags": sorted(candidate_flags),
            "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
            "decision": "ignored_reused_semantic_over_sparse_track_stitched_motion_cluster",
        }
        _append_flag(
            resolved_keyframes,
            "semantic_keyframes_reuse_motion_cluster_conflict_ignored_sparse_track_stitched_candidate",
        )
        return []

    resolved_keyframes["semantic_reuse_motion_cluster_conflict"] = {
        "core_start_sec": round(core_start, 3),
        "core_end_sec": round(core_end, 3),
        "peak_timestamp": round(peak_record["timestamp"], 3),
        "peak_motion_score": round(global_peak, 5),
        "core_peak_motion_score": round(core_peak, 5),
        "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
        "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
        "candidate_window": candidate_window,
        "candidate_quality_flags": sorted(candidate_flags),
        "decision": "rejected_reused_semantic_early_motion_cluster_conflict",
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_reused_motion_cluster_conflict")
    return ["semantic_keyframes_unreliable_reused_motion_cluster_conflict"]


def _semantic_tracker_final_loss_motion_fallback_flags(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return []
    if _semantic_visual_promotion_overrides_low_visibility_motion_fallback(resolved_keyframes):
        return []
    semantic_reuse_overrides_low_visibility = _semantic_reuse_overrides_low_visibility_motion_fallback(resolved_keyframes)
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    bio_flags = set(_quality_flags(bio_data or {}))
    if not _tracker_final_unrecovered_from_flags(bio_flags):
        return []
    if not (candidate_flags & SEMANTIC_TRACKER_FINAL_LOSS_FALLBACK_FLAGS):
        return []
    if not (candidate_flags & SEMANTIC_TRACKER_FINAL_LOSS_MOTION_FALLBACK_FLAGS):
        return []
    if "keyframe_candidates_motion_fallback_bounded_to_reliable_pose" in candidate_flags:
        anchors = _skeleton_candidate_anchors(bio_data)
        conflicts = _bounded_motion_fallback_semantic_candidate_conflicts(resolved_keyframes, bio_data)
        if conflicts:
            if semantic_reuse_overrides_low_visibility and _low_visibility_tracker_final_loss_motion_fallback_candidate(bio_data):
                start_bound, end_bound = _motion_fallback_time_bounds(bio_data)
                resolved_keyframes["semantic_tracker_final_loss_motion_fallback"] = {
                    "candidate_quality_flags": sorted(candidate_flags),
                    "tracker_quality_flags": sorted(flag for flag in bio_flags if flag.startswith("person_tracker_")),
                    "candidate_tal_span_sec": (
                        round(anchors["L"]["timestamp"] - anchors["T"]["timestamp"], 3)
                        if {"T", "A", "L"}.issubset(anchors)
                        else None
                    ),
                    "bounds": {
                        "start_timestamp": round(start_bound, 3) if start_bound is not None else None,
                        "end_timestamp": round(end_bound, 3) if end_bound is not None else None,
                    },
                    "conflicts": conflicts,
                    "decision": "ignored_reused_semantic_over_low_visibility_bounded_motion_fallback",
                }
                _append_flag(
                    resolved_keyframes,
                    "semantic_keyframes_reused_ignored_low_visibility_bounded_motion_fallback",
                )
                return []
            start_bound, end_bound = _motion_fallback_time_bounds(bio_data)
            resolved_keyframes["semantic_tracker_final_loss_motion_fallback"] = {
                "candidate_quality_flags": sorted(candidate_flags),
                "tracker_quality_flags": sorted(flag for flag in bio_flags if flag.startswith("person_tracker_")),
                "candidate_tal_span_sec": (
                    round(anchors["L"]["timestamp"] - anchors["T"]["timestamp"], 3)
                    if {"T", "A", "L"}.issubset(anchors)
                    else None
                ),
                "bounds": {
                    "start_timestamp": round(start_bound, 3) if start_bound is not None else None,
                    "end_timestamp": round(end_bound, 3) if end_bound is not None else None,
                },
                "conflicts": conflicts,
                "decision": "rejected_bounded_motion_fallback_candidate_conflict",
            }
            _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback")
            return ["semantic_keyframes_unreliable_tracker_final_loss_motion_fallback"]
        resolved_keyframes["semantic_tracker_final_loss_motion_fallback"] = {
            "candidate_quality_flags": sorted(candidate_flags),
            "tracker_quality_flags": sorted(flag for flag in bio_flags if flag.startswith("person_tracker_")),
            "candidate_tal_span_sec": (
                round(anchors["L"]["timestamp"] - anchors["T"]["timestamp"], 3)
                if {"T", "A", "L"}.issubset(anchors)
                else None
            ),
            "decision": "ignored_reliable_pose_bounded_motion_fallback",
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_tracker_final_loss_motion_fallback_ignored")
        return []
    if not _tracker_final_loss_motion_fallback_has_bounded_tal_span(bio_data):
        anchors = _skeleton_candidate_anchors(bio_data)
        resolved_keyframes["semantic_tracker_final_loss_motion_fallback"] = {
            "candidate_quality_flags": sorted(candidate_flags),
            "tracker_quality_flags": sorted(flag for flag in bio_flags if flag.startswith("person_tracker_")),
            "candidate_tal_span_sec": round(
                anchors["L"]["timestamp"] - anchors["T"]["timestamp"],
                3,
            ),
            "decision": "ignored_unbounded_motion_fallback",
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_tracker_final_loss_motion_fallback_ignored")
        return []
    resolved_keyframes["semantic_tracker_final_loss_motion_fallback"] = {
        "candidate_quality_flags": sorted(candidate_flags),
        "tracker_quality_flags": sorted(flag for flag in bio_flags if flag.startswith("person_tracker_")),
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback")
    return ["semantic_keyframes_unreliable_tracker_final_loss_motion_fallback"]


def _semantic_tracker_final_loss_outside_reliable_pose_flags(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return []
    if _semantic_visual_promotion_overrides_low_visibility_motion_fallback(resolved_keyframes):
        return []
    if (
        _semantic_reuse_overrides_low_visibility_motion_fallback(resolved_keyframes)
        and _low_visibility_tracker_final_loss_motion_fallback_candidate(bio_data)
    ):
        return []
    bio_flags = set(_quality_flags(bio_data or {}))
    if not _tracker_final_unrecovered_from_flags(bio_flags):
        return []
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    if "keyframe_candidates_motion_fallback_bounded_to_reliable_pose" not in candidate_flags:
        return []

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors):
        return []

    start_bound, end_bound = _motion_fallback_time_bounds(bio_data)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if end_bound is None and {"T", "A", "L"}.issubset(skeleton_anchors):
        end_bound = max(anchor["timestamp"] for anchor in skeleton_anchors.values())
    if start_bound is None and {"T", "A", "L"}.issubset(skeleton_anchors):
        start_bound = min(anchor["timestamp"] for anchor in skeleton_anchors.values())
    if start_bound is None and end_bound is None:
        return []

    conflicts: list[dict[str, float | str]] = []
    tolerance = SEMANTIC_TRACKER_FINAL_LOSS_RELIABLE_POSE_BOUND_TOLERANCE_SEC
    for key in ("T", "A", "L"):
        timestamp = semantic_anchors[key]
        if end_bound is not None and timestamp > end_bound + tolerance:
            conflicts.append(
                {
                    "key": key,
                    "semantic_timestamp": round(timestamp, 3),
                    "bound": "end",
                    "bound_timestamp": round(end_bound, 3),
                    "delta_sec": round(timestamp - end_bound, 3),
                }
            )
        elif start_bound is not None and timestamp < start_bound - tolerance:
            conflicts.append(
                {
                    "key": key,
                    "semantic_timestamp": round(timestamp, 3),
                    "bound": "start",
                    "bound_timestamp": round(start_bound, 3),
                    "delta_sec": round(start_bound - timestamp, 3),
                }
            )
    if not conflicts:
        return []

    resolved_keyframes["semantic_tracker_final_loss_reliable_pose_bounds"] = {
        "conflicts": conflicts,
        "bounds": {
            "start_timestamp": round(start_bound, 3) if start_bound is not None else None,
            "end_timestamp": round(end_bound, 3) if end_bound is not None else None,
            "tolerance_sec": tolerance,
        },
        "candidate_timestamps": {
            key: round(value["timestamp"], 3)
            for key, value in skeleton_anchors.items()
            if key in {"T", "A", "L"}
        },
        "candidate_quality_flags": sorted(candidate_flags),
        "tracker_quality_flags": sorted(flag for flag in bio_flags if flag.startswith("person_tracker_")),
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose")
    return ["semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose"]


def _semantic_tracker_final_loss_weak_semantic_motion_flags(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return []
    if _semantic_visual_promotion_overrides_low_visibility_motion_fallback(resolved_keyframes):
        return []
    bio_flags = set(_quality_flags(bio_data or {}))
    if not _tracker_final_unrecovered_from_flags(bio_flags):
        return []
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))

    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(semantic_anchors):
        return []

    refinement_scores: dict[str, float] = {}
    for key in ("T", "L"):
        record = _core_record_by_key(resolved_keyframes, key)
        if record is None:
            continue
        score = _float_or_none(record.get("refinement_motion_score"))
        if score is not None:
            refinement_scores[key] = score
    if (
        len(refinement_scores) < 2
        or max(refinement_scores.values()) > SEMANTIC_TRACKER_FINAL_LOSS_WEAK_REFINEMENT_MAX_SCORE
    ):
        return []

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    conflicts: list[dict[str, float | str]] = []
    for key in ("T", "A", "L"):
        candidate = skeleton_anchors.get(key)
        if not isinstance(candidate, dict):
            continue
        if candidate["confidence"] > SEMANTIC_TRACKER_FINAL_LOSS_WEAK_CANDIDATE_MAX_CONFIDENCE:
            continue
        delta = abs(semantic_anchors[key] - candidate["timestamp"])
        if delta < SEMANTIC_WEAK_REFINEMENT_LATE_CANDIDATE_MIN_SHIFT_SECONDS:
            continue
        conflicts.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(candidate["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(candidate["confidence"], 3),
            }
        )
    weak_candidate_context = "tal_candidate_weak_geometry" in candidate_flags
    retry_flags = set(_quality_flags(resolved_keyframes))
    retry_with_absent_landing_geometry = (
        "video_temporal_quality_retry" in retry_flags
        and "tal_candidate_landing_geometry_absent" in candidate_flags
        and max(refinement_scores.values(), default=0.0)
        <= SEMANTIC_TRACKER_FINAL_LOSS_WEAK_GEOMETRY_RETRY_MAX_REFINEMENT_SCORE
    )
    if retry_with_absent_landing_geometry:
        landing_candidate = skeleton_anchors.get("L")
        landing_shift = (
            abs(semantic_anchors["L"] - landing_candidate["timestamp"])
            if isinstance(landing_candidate, dict)
            else None
        )
        resolved_keyframes["semantic_tracker_final_loss_weak_semantic_motion"] = {
            "weak_candidate_conflicts": conflicts,
            "refinement_motion_scores": {key: round(value, 4) for key, value in refinement_scores.items()},
            "candidate_quality_flags": sorted(candidate_flags),
            "tracker_quality_flags": sorted(flag for flag in bio_flags if flag.startswith(("person_tracker_", "target_lock_"))),
            "decision": "ignored_retry_absent_landing_geometry_candidate",
            "landing_delta_sec": round(landing_shift, 3) if landing_shift is not None else None,
        }
        _append_flag(resolved_keyframes, "semantic_keyframes_tracker_final_loss_weak_semantic_motion_ignored")
        return []
    if not weak_candidate_context and len(conflicts) < SEMANTIC_TRACKER_FINAL_LOSS_WEAK_CANDIDATE_MIN_KEYS:
        return []

    resolved_keyframes["semantic_tracker_final_loss_weak_semantic_motion"] = {
        "weak_candidate_conflicts": conflicts,
        "refinement_motion_scores": {key: round(value, 4) for key, value in refinement_scores.items()},
        "candidate_quality_flags": sorted(candidate_flags),
        "tracker_quality_flags": sorted(flag for flag in bio_flags if flag.startswith(("person_tracker_", "target_lock_"))),
    }
    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion")
    return ["semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion"]


def _semantic_skeleton_tal_conflict_flags(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    *,
    analysis_profile: str | None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or len(skeleton_anchors) < 2:
        return []
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    conflicts: list[dict[str, float | str]] = []
    for key, skeleton in skeleton_anchors.items():
        if skeleton["confidence"] < VIDEO_TEMPORAL_RETRY_SKELETON_CONFLICT_MIN_CONFIDENCE:
            continue
        delta = semantic_anchors.get(key)
        if delta is None:
            continue
        offset = abs(delta - skeleton["timestamp"])
        if offset >= VIDEO_TEMPORAL_RETRY_SKELETON_CONFLICT_MIN_DELTA_SEC:
            conflicts.append(
                {
                    "key": key,
                    "semantic_timestamp": round(delta, 3),
                    "skeleton_timestamp": round(skeleton["timestamp"], 3),
                    "delta_sec": round(offset, 3),
                    "skeleton_confidence": round(skeleton["confidence"], 3),
                }
            )
    strong_conflict = any(float(item["delta_sec"]) >= VIDEO_TEMPORAL_RETRY_SKELETON_CONFLICT_STRONG_DELTA_SEC for item in conflicts)
    if len(conflicts) >= 2 or strong_conflict:
        if "semantic_keyframes_candidate_motion_window_conflict_ignored_early_approach_motion_peak" in set(
            _quality_flags(resolved_keyframes)
        ):
            resolved_keyframes["semantic_skeleton_tal_conflicts"] = conflicts
            resolved_keyframes["semantic_skeleton_tal_conflict_decision"] = "ignored_early_approach_motion_peak_candidate"
            resolved_keyframes["semantic_skeleton_tal_conflict_candidate_quality_flags"] = sorted(candidate_flags)
            _append_flag(
                resolved_keyframes,
                "video_temporal_quality_retry_skeleton_tal_conflict_ignored_early_approach_motion_peak",
            )
            return []
        if candidate_flags & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS:
            resolved_keyframes["semantic_skeleton_tal_conflicts"] = conflicts
            resolved_keyframes["semantic_skeleton_tal_conflict_decision"] = "ignored_weak_temporal_geometry_candidate"
            resolved_keyframes["semantic_skeleton_tal_conflict_candidate_quality_flags"] = sorted(candidate_flags)
            _append_flag(resolved_keyframes, "video_temporal_quality_retry_skeleton_tal_conflict_ignored_weak_temporal_geometry")
            return []
        resolved_keyframes["semantic_skeleton_tal_conflicts"] = conflicts
        _append_flag(resolved_keyframes, "video_temporal_quality_retry_skeleton_tal_conflict")
        return ["video_temporal_quality_retry_skeleton_tal_conflict"]
    return []


def _semantic_motion_cluster_conflict_flags(
    resolved_keyframes: dict[str, Any],
    motion_scores: dict[str, object] | None,
    *,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None = None,
) -> list[str]:
    if _normalize_action_profile(analysis_profile) != "jump":
        return []
    anchors = _semantic_core_anchors(resolved_keyframes)
    if not {"T", "A", "L"}.issubset(anchors):
        return []
    records = _motion_records_from_scores(motion_scores)
    if len(records) < 3:
        return []
    global_peak = max(record["motion_score"] for record in records)
    if global_peak < VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_MIN_SCORE:
        return []
    strong_threshold = max(
        VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_MIN_SCORE,
        global_peak * VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_RATIO,
    )
    strong_records = [record for record in records if record["motion_score"] >= strong_threshold]
    if len(strong_records) < 2:
        return []
    t_value = anchors["T"]
    l_value = anchors["L"]
    tolerance = VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_TOLERANCE_SEC
    core_peak = max(
        (
            record["motion_score"]
            for record in records
            if t_value - tolerance <= record["timestamp"] <= l_value + tolerance
        ),
        default=0.0,
    )
    peak_record = max(records, key=lambda record: record["motion_score"])
    strong_before = all(record["timestamp"] < t_value - tolerance for record in strong_records)
    strong_after = all(record["timestamp"] > l_value + tolerance for record in strong_records)
    peak_outside_core = peak_record["timestamp"] < t_value - tolerance or peak_record["timestamp"] > l_value + tolerance
    if (strong_before or strong_after or peak_outside_core) and core_peak < global_peak * VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_CORE_PEAK_RATIO:
        candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
        near_candidate_support = _semantic_tal_near_skeleton_candidates(resolved_keyframes, bio_data)
        if near_candidate_support is not None:
            support_mode = str(near_candidate_support.get("support_mode") or "complete_tal")
            decision = (
                "ignored_near_skeleton_boundary_candidate_tal"
                if support_mode == "takeoff_landing_boundary_with_weak_apex_candidate"
                else "ignored_near_skeleton_candidate_tal"
            )
            resolved_keyframes["semantic_motion_cluster_conflict"] = {
                "core_start_sec": round(t_value, 3),
                "core_end_sec": round(l_value, 3),
                "peak_timestamp": round(peak_record["timestamp"], 3),
                "peak_motion_score": round(global_peak, 5),
                "core_peak_motion_score": round(core_peak, 5),
                "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                "candidate_support": near_candidate_support,
                "decision": decision,
            }
            _append_flag(resolved_keyframes, "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate")
            return []
        weak_temporal_geometry_support = _phase_range_weak_temporal_geometry_motion_cluster_support(
            resolved_keyframes,
            bio_data,
            candidate_flags,
            require_video_confidence=(
                "semantic_keyframes_reused_from_phase_range_weak_geometry_source"
                not in set(_quality_flags(resolved_keyframes))
            ),
            core_peak=core_peak,
            global_peak=global_peak,
        )
        if weak_temporal_geometry_support is not None:
            resolved_keyframes["semantic_motion_cluster_conflict"] = {
                "core_start_sec": round(t_value, 3),
                "core_end_sec": round(l_value, 3),
                "peak_timestamp": round(peak_record["timestamp"], 3),
                "peak_motion_score": round(global_peak, 5),
                "core_peak_motion_score": round(core_peak, 5),
                "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                "candidate_quality_flags": sorted(candidate_flags),
                "candidate_support": weak_temporal_geometry_support,
                "decision": "ignored_weak_temporal_geometry_candidate_motion_cluster",
            }
            _append_flag(
                resolved_keyframes,
                "video_temporal_quality_retry_motion_cluster_conflict_ignored_weak_temporal_geometry",
            )
            return []
        retry_weak_phase_support = _retry_weak_phase_early_motion_cluster_support(
            resolved_keyframes,
            bio_data,
            candidate_flags,
            peak_timestamp=peak_record["timestamp"],
            global_peak=global_peak,
            core_peak=core_peak,
            strong_records=strong_records,
            tolerance=tolerance,
        )
        if retry_weak_phase_support is not None:
            resolved_keyframes["semantic_motion_cluster_conflict"] = {
                "core_start_sec": round(t_value, 3),
                "core_end_sec": round(l_value, 3),
                "peak_timestamp": round(peak_record["timestamp"], 3),
                "peak_motion_score": round(global_peak, 5),
                "core_peak_motion_score": round(core_peak, 5),
                "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                "candidate_quality_flags": sorted(candidate_flags),
                "candidate_support": retry_weak_phase_support,
                "decision": "ignored_retry_weak_phase_early_approach_motion_cluster",
            }
            _append_flag(
                resolved_keyframes,
                "video_temporal_quality_retry_motion_cluster_conflict_ignored_early_approach_motion_peak",
            )
            return []
        late_reanchor_reuse_support = _phase_range_late_reanchor_reuse_motion_cluster_support(
            resolved_keyframes,
            bio_data,
            candidate_flags,
            peak_timestamp=peak_record["timestamp"],
            global_peak=global_peak,
            core_peak=core_peak,
        )
        if late_reanchor_reuse_support is not None:
            resolved_keyframes["semantic_motion_cluster_conflict"] = {
                "core_start_sec": round(t_value, 3),
                "core_end_sec": round(l_value, 3),
                "peak_timestamp": round(peak_record["timestamp"], 3),
                "peak_motion_score": round(global_peak, 5),
                "core_peak_motion_score": round(core_peak, 5),
                "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                "candidate_quality_flags": sorted(candidate_flags),
                "candidate_support": late_reanchor_reuse_support,
                "decision": "ignored_reused_phase_range_late_reanchor_motion_cluster",
            }
            _append_flag(
                resolved_keyframes,
                "semantic_keyframes_reuse_motion_cluster_conflict_ignored_phase_range_late_reanchor",
            )
            return []
        unreliable_motion_records = (
            (bio_data or {}).get("key_frame_candidates", {}).get("motion_fallback_unreliable_pose_records")
            if isinstance((bio_data or {}).get("key_frame_candidates"), dict)
            else None
        )
        unreliable_timestamps: list[float] = []
        candidates = (bio_data or {}).get("key_frame_candidates") if isinstance(bio_data, dict) else None
        if isinstance(candidates, dict) and isinstance(unreliable_motion_records, dict):
            for key in unreliable_motion_records:
                candidate = candidates.get(key)
                if not isinstance(candidate, dict):
                    continue
                timestamp = _float_or_none(candidate.get("timestamp"))
                if timestamp is not None:
                    unreliable_timestamps.append(timestamp)
        peak_matches_unreliable_pose_fallback = any(abs(peak_record["timestamp"] - value) <= 0.18 for value in unreliable_timestamps)
        if (
            "keyframe_candidates_motion_fallback_unreliable_pose_state" in candidate_flags
            and peak_matches_unreliable_pose_fallback
        ):
            resolved_keyframes["semantic_motion_cluster_conflict"] = {
                "core_start_sec": round(t_value, 3),
                "core_end_sec": round(l_value, 3),
                "peak_timestamp": round(peak_record["timestamp"], 3),
                "peak_motion_score": round(global_peak, 5),
                "core_peak_motion_score": round(core_peak, 5),
                "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                "candidate_quality_flags": sorted(candidate_flags),
                "unreliable_pose_records": unreliable_motion_records,
                "decision": "ignored_unreliable_pose_motion_fallback_cluster",
            }
            _append_flag(resolved_keyframes, "video_temporal_quality_retry_motion_cluster_conflict_ignored_unreliable_pose_fallback")
            return []
        early_approach_motion_peak_support = _early_approach_motion_peak_motion_cluster_support(
            resolved_keyframes,
            bio_data,
            candidate_flags,
            peak_timestamp=peak_record["timestamp"],
            global_peak=global_peak,
            core_peak=core_peak,
            strong_records=strong_records,
            tolerance=tolerance,
        )
        if early_approach_motion_peak_support is not None:
            resolved_keyframes["semantic_motion_cluster_conflict"] = {
                "core_start_sec": round(t_value, 3),
                "core_end_sec": round(l_value, 3),
                "peak_timestamp": round(peak_record["timestamp"], 3),
                "peak_motion_score": round(global_peak, 5),
                "core_peak_motion_score": round(core_peak, 5),
                "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                "candidate_quality_flags": sorted(candidate_flags),
                "candidate_support": early_approach_motion_peak_support,
                "decision": "ignored_early_approach_motion_peak_candidate_window",
            }
            _append_flag(
                resolved_keyframes,
                "video_temporal_quality_retry_motion_cluster_conflict_ignored_early_approach_motion_peak",
            )
            return []
        late_reanchor = resolved_keyframes.get("semantic_phase_range_late_reanchor")
        if (
            "semantic_keyframes_phase_range_late_reanchored" in set(_quality_flags(resolved_keyframes))
            and isinstance(late_reanchor, dict)
            and peak_record["timestamp"] < t_value - tolerance
        ):
            video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
            phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)]
            approach_segment = next(
                (item for item in phase_segments if str(item.get("phase_code") or "") == "approach"),
                None,
            )
            approach_start = _float_or_none(approach_segment.get("time_start")) if isinstance(approach_segment, dict) else None
            approach_end = _float_or_none(approach_segment.get("time_end")) if isinstance(approach_segment, dict) else None
            approach_peak = (
                approach_start is not None
                and approach_end is not None
                and approach_start <= peak_record["timestamp"] <= approach_end
            )
            reanchor_peak = _float_or_none(
                late_reanchor.get("pre_takeoff_peak_timestamp")
                if late_reanchor.get("pre_takeoff_peak_timestamp") is not None
                else late_reanchor.get("preparation_peak_timestamp")
            )
            reanchor_motion = _float_or_none(
                late_reanchor.get("pre_takeoff_peak_motion_score")
                if late_reanchor.get("pre_takeoff_peak_motion_score") is not None
                else late_reanchor.get("preparation_peak_motion_score")
            ) or 0.0
            if (
                approach_peak
                and reanchor_peak is not None
                and abs(reanchor_peak - t_value) <= SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MAX_T_OFFSET_SEC
                and reanchor_motion >= SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_PREP_PEAK
            ):
                resolved_keyframes["semantic_motion_cluster_conflict"] = {
                    "core_start_sec": round(t_value, 3),
                    "core_end_sec": round(l_value, 3),
                    "peak_timestamp": round(peak_record["timestamp"], 3),
                    "peak_motion_score": round(global_peak, 5),
                    "core_peak_motion_score": round(core_peak, 5),
                    "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                    "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                    "candidate_quality_flags": sorted(candidate_flags),
                    "phase_range_late_reanchor": late_reanchor,
                    "decision": "ignored_approach_motion_after_phase_range_late_reanchor",
                }
                _append_flag(
                    resolved_keyframes,
                    "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor",
                )
                return []
        candidates = (bio_data or {}).get("key_frame_candidates") if isinstance(bio_data, dict) else None
        contaminated_motion_window = None
        if (
            "tal_candidate_motion_window_occlusion_contaminated" in candidate_flags
            and isinstance(candidates, dict)
        ):
            for key in ("T", "A", "L"):
                candidate = candidates.get(key)
                evidence = candidate.get("evidence") if isinstance(candidate, dict) else None
                diagnostic = (
                    evidence.get("motion_window_occlusion_contamination")
                    if isinstance(evidence, dict)
                    else None
                )
                if not isinstance(diagnostic, dict):
                    continue
                contaminated_peak = _float_or_none(diagnostic.get("peak_timestamp"))
                if contaminated_peak is not None and abs(peak_record["timestamp"] - contaminated_peak) <= 0.18:
                    contaminated_motion_window = diagnostic
                    break
        if contaminated_motion_window is not None:
            occluded_candidate_support = _occluded_motion_window_candidate_supports_rejecting_semantic(
                anchors,
                _skeleton_candidate_anchors(bio_data),
                core_peak=core_peak,
                global_peak=global_peak,
            )
            if occluded_candidate_support is not None:
                resolved_keyframes["semantic_motion_cluster_conflict"] = {
                    "core_start_sec": round(t_value, 3),
                    "core_end_sec": round(l_value, 3),
                    "peak_timestamp": round(peak_record["timestamp"], 3),
                    "peak_motion_score": round(global_peak, 5),
                    "core_peak_motion_score": round(core_peak, 5),
                    "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                    "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                    "candidate_quality_flags": sorted(candidate_flags),
                    "contaminated_motion_window": contaminated_motion_window,
                    "candidate_support": occluded_candidate_support,
                    "decision": "rejected_occlusion_contaminated_candidate_motion_window",
                }
                _append_flag(resolved_keyframes, "video_temporal_quality_retry_motion_cluster_conflict")
                return ["video_temporal_quality_retry_motion_cluster_conflict"]
            resolved_keyframes["semantic_motion_cluster_conflict"] = {
                "core_start_sec": round(t_value, 3),
                "core_end_sec": round(l_value, 3),
                "peak_timestamp": round(peak_record["timestamp"], 3),
                "peak_motion_score": round(global_peak, 5),
                "core_peak_motion_score": round(core_peak, 5),
                "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                "candidate_quality_flags": sorted(candidate_flags),
                "contaminated_motion_window": contaminated_motion_window,
                "decision": "ignored_occlusion_contaminated_candidate_motion_window",
            }
            _append_flag(
                resolved_keyframes,
                "video_temporal_quality_retry_motion_cluster_conflict_ignored_occlusion_contaminated_candidate",
            )
            return []
        if (
            "semantic_keyframes_reused_over_sparse_track_stitched_candidate" in set(_quality_flags(resolved_keyframes))
            and candidate_flags & SEMANTIC_REUSE_SPARSE_TRACK_STITCHED_CANDIDATE_FLAGS
        ):
            skeleton_anchors = _skeleton_candidate_anchors(bio_data)
            if {"T", "L"}.issubset(skeleton_anchors):
                candidate_window_values = [
                    skeleton_anchors["T"]["timestamp"],
                    skeleton_anchors["L"]["timestamp"],
                ]
                for anchor in skeleton_anchors.values():
                    start = _float_or_none(anchor.get("motion_window_start"))
                    end = _float_or_none(anchor.get("motion_window_end"))
                    if start is not None and end is not None:
                        candidate_window_values.extend([start, end])
                candidate_start = min(candidate_window_values)
                candidate_end = max(candidate_window_values)
                candidate_peak = _peak_motion_in_window(records, candidate_start, candidate_end)
                if (
                    candidate_start - tolerance <= peak_record["timestamp"] <= candidate_end + tolerance
                    and candidate_peak >= global_peak * SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CANDIDATE_PEAK_RATIO
                ):
                    resolved_keyframes["semantic_motion_cluster_conflict"] = {
                        "core_start_sec": round(t_value, 3),
                        "core_end_sec": round(l_value, 3),
                        "peak_timestamp": round(peak_record["timestamp"], 3),
                        "peak_motion_score": round(global_peak, 5),
                        "core_peak_motion_score": round(core_peak, 5),
                        "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
                        "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
                        "candidate_quality_flags": sorted(candidate_flags),
                        "candidate_window": {
                            "start_sec": round(candidate_start, 3),
                            "end_sec": round(candidate_end, 3),
                            "peak_motion_score": round(candidate_peak, 5),
                        },
                        "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
                        "decision": "ignored_sparse_track_stitched_candidate_motion_cluster",
                    }
                    _append_flag(
                        resolved_keyframes,
                        "semantic_keyframes_reuse_motion_cluster_conflict_ignored_sparse_track_stitched_candidate",
                    )
                    return []
        resolved_keyframes["semantic_motion_cluster_conflict"] = {
            "core_start_sec": round(t_value, 3),
            "core_end_sec": round(l_value, 3),
            "peak_timestamp": round(peak_record["timestamp"], 3),
            "peak_motion_score": round(global_peak, 5),
            "core_peak_motion_score": round(core_peak, 5),
            "strong_cluster_first_sec": round(min(record["timestamp"] for record in strong_records), 3),
            "strong_cluster_last_sec": round(max(record["timestamp"] for record in strong_records), 3),
        }
        _append_flag(resolved_keyframes, "video_temporal_quality_retry_motion_cluster_conflict")
        return ["video_temporal_quality_retry_motion_cluster_conflict"]
    return []


def _phase_range_weak_temporal_geometry_motion_cluster_support(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    candidate_flags: set[str],
    *,
    require_video_confidence: bool = True,
    require_core_peak_ratio: bool = True,
    core_peak: float | None = None,
    global_peak: float | None = None,
) -> dict[str, Any] | None:
    weak_geometry_flags = (
        SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
        | SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS
    )
    if not (candidate_flags & weak_geometry_flags):
        return None
    if not _has_ordered_core_tal(resolved_keyframes):
        return None

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return None
    video_confidence = _video_confidence(video_ai, resolved_keyframes)
    weak_geometry_only_context = bool(
        candidate_flags & SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS
    ) and not bool(candidate_flags & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS)
    confidence_floor = (
        SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_WEAK_GEOMETRY_CONFIDENCE_FLOOR
        if weak_geometry_only_context
        else SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_CONFIDENCE_FLOOR
    )
    if require_video_confidence and video_confidence < confidence_floor:
        return None

    action_confirmation = video_ai.get("action_confirmation") if isinstance(video_ai, dict) else None
    if require_video_confidence and isinstance(action_confirmation, dict):
        action_family = _normalize_action_profile(action_confirmation.get("action_family"))
        if action_family and action_family != "jump":
            return None
        action_confidence = _float_or_none(action_confirmation.get("confidence"))
        if (
            action_confidence is not None
            and action_confidence < SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR
        ):
            return None

    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return None

    anchors: dict[str, dict[str, Any]] = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item)
        if key not in {"T", "A", "L"} or key in anchors:
            continue
        reason = str(item.get("selection_reason") or "")
        if (
            reason == "semantic_reused_from_matching_video"
            and set(_quality_flags(resolved_keyframes))
            & {
                "semantic_keyframes_reused_from_phase_range_weak_geometry_source",
                "semantic_keyframes_reused_from_phase_range_late_reanchor_source",
            }
        ):
            reason = str(item.get("semantic_reuse_original_selection_reason") or reason)
        if not reason.startswith("video_phase_range_"):
            continue
        visibility = item.get("semantic_visibility") if isinstance(item.get("semantic_visibility"), dict) else {}
        if str(visibility.get("status") or "") == "foreground_person_occluded":
            return None
        timestamp = _record_timestamp(item)
        confidence = _record_numeric_field(item, "confidence") or _video_confidence(video_ai, resolved_keyframes)
        if timestamp is None or confidence < SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR:
            return None
        anchors[key] = {
            "timestamp": timestamp,
            "confidence": confidence,
            "selection_reason": reason,
        }
    if set(anchors) != {"T", "A", "L"}:
        return None

    tal_span = anchors["L"]["timestamp"] - anchors["T"]["timestamp"]
    if not (
        SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC
    ):
        return None

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    shifted: list[dict[str, float | str]] = []
    for key in ("T", "A", "L"):
        skeleton = skeleton_anchors.get(key)
        if not isinstance(skeleton, dict):
            continue
        delta = anchors[key]["timestamp"] - skeleton["timestamp"]
        if abs(delta) < SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_SHIFT_SEC:
            continue
        shifted.append(
            {
                "key": key,
                "semantic_timestamp": round(anchors[key]["timestamp"], 3),
                "candidate_timestamp": round(skeleton["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(skeleton["confidence"], 3),
            }
        )
    if len(shifted) < SEMANTIC_PHASE_RANGE_WEAK_GEOMETRY_MOTION_CLUSTER_MIN_SHIFT_KEYS:
        return None
    if (
        require_core_peak_ratio
        and core_peak is not None
        and global_peak is not None
        and global_peak > 0
        and core_peak < global_peak * SEMANTIC_PHASE_RANGE_WEAK_GEOMETRY_MIN_CORE_PEAK_RATIO
    ):
        if (
            not weak_geometry_only_context
            or core_peak < global_peak * SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_CORE_PEAK_RATIO_FLOOR
        ):
            return None

    return {
        "support_mode": "phase_range_tal_over_weak_temporal_geometry_candidate",
        "shifted_keys": shifted,
        "tal_span_sec": round(tal_span, 3),
        "video_confidence": round(video_confidence, 3),
        "confidence_floor": round(confidence_floor, 3),
        "weak_geometry_only_context": weak_geometry_only_context,
        "candidate_quality_flags": sorted(candidate_flags),
        "core_peak_ratio": round(core_peak / global_peak, 3)
        if core_peak is not None and global_peak is not None and global_peak > 0
        else None,
    }


def _phase_range_late_reanchor_reuse_motion_cluster_support(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    candidate_flags: set[str],
    *,
    peak_timestamp: float,
    global_peak: float,
    core_peak: float,
) -> dict[str, Any] | None:
    flags = set(_quality_flags(resolved_keyframes))
    if "semantic_keyframes_reused_from_phase_range_late_reanchor_source" not in flags:
        return None
    if not (candidate_flags & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS):
        return None
    if not _has_ordered_core_tal(resolved_keyframes):
        return None
    anchors = _semantic_core_anchors(resolved_keyframes)
    if peak_timestamp >= anchors["T"] - SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_CORE_TOLERANCE_SEC:
        return None
    if anchors["T"] - peak_timestamp < SEMANTIC_REUSE_EARLY_MOTION_CLUSTER_MIN_SHIFT_SECONDS:
        return None
    if core_peak < SEMANTIC_EARLY_APPROACH_MOTION_PEAK_MIN_CORE_SCORE:
        return None

    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return None
    reanchored: list[dict[str, float | str]] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item)
        if key not in {"T", "A", "L"}:
            continue
        if item.get("late_phase_range_reanchor") is not True:
            return None
        timestamp = _record_timestamp(item)
        pre_reanchor = _record_numeric_field(item, "pre_late_phase_reanchor_timestamp")
        confidence = _record_numeric_field(item, "confidence") or _video_confidence(
            resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else None,
            resolved_keyframes,
        )
        if (
            timestamp is None
            or pre_reanchor is None
            or confidence < SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR
        ):
            return None
        if pre_reanchor - timestamp < SEMANTIC_PHASE_RANGE_LATE_REANCHOR_MIN_SHIFT_SEC:
            return None
        reanchored.append(
            {
                "key": key,
                "timestamp": round(timestamp, 3),
                "pre_late_phase_reanchor_timestamp": round(pre_reanchor, 3),
                "delta_sec": round(timestamp - pre_reanchor, 3),
                "confidence": round(confidence, 3),
            }
        )
    if len({str(item["key"]) for item in reanchored}) != 3:
        return None

    tal_span = anchors["L"] - anchors["T"]
    if not (
        SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC
    ):
        return None
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    candidate_timestamps = {
        key: round(anchor["timestamp"], 3)
        for key, anchor in skeleton_anchors.items()
        if key in {"T", "A", "L"}
    }
    if len(candidate_timestamps) < 2:
        return None

    return {
        "support_mode": "phase_range_late_reanchor_reuse_over_early_motion_cluster",
        "phase_range_late_reanchor_records": sorted(reanchored, key=lambda item: str(item["key"])),
        "candidate_timestamps": candidate_timestamps,
        "tal_span_sec": round(tal_span, 3),
        "core_peak_ratio": round(core_peak / global_peak, 3) if global_peak > 0 else None,
    }


def _semantic_tal_near_skeleton_candidates(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    semantic_anchors = _semantic_core_anchors(resolved_keyframes)
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if not {"T", "A", "L"}.issubset(semantic_anchors) or not {"T", "A", "L"}.issubset(skeleton_anchors):
        return None

    matches: list[dict[str, float | str]] = []
    confidences: list[float] = []
    raw_confidences: list[float] = []
    for key in ("T", "A", "L"):
        skeleton = skeleton_anchors[key]
        delta = semantic_anchors[key] - skeleton["timestamp"]
        if abs(delta) > VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_MAX_DELTA_SEC:
            break
        confidence = float(skeleton["confidence"])
        raw_confidence = float(skeleton.get("raw_confidence", confidence))
        confidences.append(confidence)
        raw_confidences.append(raw_confidence)
        matches.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(skeleton["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(confidence, 3),
                "candidate_raw_confidence": round(raw_confidence, 3),
            }
        )
    else:
        average_confidence = sum(confidences) / len(confidences)
        strongest_confidence = max(confidences)
        if (
            average_confidence >= VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_AVG_CONFIDENCE
            or strongest_confidence >= VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_STRONG_CONFIDENCE
        ):
            return {
                "matches": matches,
                "max_delta_sec": round(max(abs(float(item["delta_sec"])) for item in matches), 3),
                "average_candidate_confidence": round(average_confidence, 3),
                "strongest_candidate_confidence": round(strongest_confidence, 3),
                "average_candidate_raw_confidence": round(sum(raw_confidences) / len(raw_confidences), 3),
                "support_mode": "complete_tal",
            }

    boundary_matches: list[dict[str, float | str]] = []
    boundary_confidences: list[float] = []
    boundary_raw_confidences: list[float] = []
    for key in ("T", "L"):
        skeleton = skeleton_anchors[key]
        delta = semantic_anchors[key] - skeleton["timestamp"]
        if abs(delta) > VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_MAX_DELTA_SEC:
            return None
        confidence = float(skeleton["confidence"])
        raw_confidence = float(skeleton.get("raw_confidence", confidence))
        boundary_confidences.append(confidence)
        boundary_raw_confidences.append(raw_confidence)
        boundary_matches.append(
            {
                "key": key,
                "semantic_timestamp": round(semantic_anchors[key], 3),
                "candidate_timestamp": round(skeleton["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(confidence, 3),
                "candidate_raw_confidence": round(raw_confidence, 3),
            }
        )

    boundary_average_confidence = sum(boundary_confidences) / len(boundary_confidences)
    boundary_strongest_confidence = max(boundary_confidences)
    if (
        boundary_average_confidence < VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_AVG_CONFIDENCE
        and boundary_strongest_confidence < VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_CANDIDATE_STRONG_CONFIDENCE
    ):
        return None

    apex_candidate = skeleton_anchors["A"]
    apex_confidence = float(apex_candidate["confidence"])
    apex_warnings = _keyframe_candidate_warnings(bio_data, "A")
    apex_is_weak = (
        apex_confidence <= VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_BOUNDARY_APEX_MAX_CONFIDENCE
        or bool(apex_warnings & SEMANTIC_APEX_WEAK_CANDIDATE_FLAGS)
    )
    if not apex_is_weak:
        return None
    if not (semantic_anchors["T"] < semantic_anchors["A"] < semantic_anchors["L"]):
        return None
    if semantic_anchors["A"] > apex_candidate["timestamp"] + VIDEO_TEMPORAL_RETRY_MOTION_CLUSTER_NEAR_BOUNDARY_APEX_TRAIL_TOLERANCE_SEC:
        return None

    apex_delta = semantic_anchors["A"] - apex_candidate["timestamp"]
    return {
        "matches": boundary_matches,
        "ignored_apex_candidate": {
            "key": "A",
            "semantic_timestamp": round(semantic_anchors["A"], 3),
            "candidate_timestamp": round(apex_candidate["timestamp"], 3),
            "delta_sec": round(apex_delta, 3),
            "candidate_confidence": round(apex_confidence, 3),
            "candidate_raw_confidence": round(float(apex_candidate.get("raw_confidence", apex_confidence)), 3),
            "candidate_warnings": sorted(apex_warnings),
        },
        "max_delta_sec": round(max(abs(float(item["delta_sec"])) for item in boundary_matches), 3),
        "average_candidate_confidence": round(boundary_average_confidence, 3),
        "strongest_candidate_confidence": round(boundary_strongest_confidence, 3),
        "average_candidate_raw_confidence": round(sum(boundary_raw_confidences) / len(boundary_raw_confidences), 3),
        "support_mode": "takeoff_landing_boundary_with_weak_apex_candidate",
    }


def _maybe_ignore_refinement_rejection_near_skeleton_candidate(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    refinement_flags: Sequence[str],
    *,
    analysis_profile: str | None,
) -> None:
    if _normalize_action_profile(analysis_profile) != "jump":
        return
    flag_set = {flag for flag in refinement_flags if isinstance(flag, str)}
    rejected_flags = flag_set & {
        "semantic_keyframe_refinement_order_rejected",
        "semantic_keyframe_refinement_phase_rejected",
    }
    if not rejected_flags:
        return
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return
    if not _has_ordered_core_tal(resolved_keyframes):
        return
    support = _semantic_tal_near_skeleton_candidates(resolved_keyframes, bio_data)
    if support is None:
        return

    rejected_records: list[dict[str, Any]] = []
    selected = resolved_keyframes.get("selected")
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("refinement_reject_reason") or "")
            if reason not in {"order", "phase"}:
                continue
            key = _core_semantic_key(item)
            if key not in {"T", "L"}:
                continue
            timestamp = _float_or_none(item.get("timestamp"))
            rejected_records.append(
                {
                    "key": key,
                    "timestamp": round(timestamp, 3) if timestamp is not None else None,
                    "rejected_candidate_timestamp": item.get("refinement_candidate_timestamp"),
                    "rejected_candidate_delta_sec": item.get("refinement_candidate_delta_sec"),
                    "reason": reason,
                    "motion_score": item.get("refinement_motion_score"),
                }
            )
    if not rejected_records:
        return

    resolved_keyframes["semantic_refinement_rejection"] = {
        "decision": "ignored_near_skeleton_candidate_tal",
        "rejection_flags": sorted(rejected_flags),
        "candidate_support": support,
        "rejected_records": rejected_records,
    }
    _append_flag(resolved_keyframes, "semantic_keyframe_refinement_rejection_ignored_near_skeleton_candidate")


def _maybe_ignore_refinement_rejection_for_weak_temporal_geometry(
    resolved_keyframes: dict[str, Any],
    bio_data: dict[str, Any] | None,
    refinement_flags: Sequence[str],
    *,
    analysis_profile: str | None,
) -> None:
    if _normalize_action_profile(analysis_profile) != "jump":
        return
    rejected_flags = {flag for flag in refinement_flags if isinstance(flag, str)} & SEMANTIC_REFINEMENT_REJECTION_FLAGS
    if not rejected_flags:
        return
    if str(resolved_keyframes.get("source") or "") not in {"video_ai_refined", "blended"}:
        return
    if not _has_ordered_core_tal(resolved_keyframes):
        return
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    if not (candidate_flags & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS):
        return

    rejected_records: list[dict[str, Any]] = []
    selected = resolved_keyframes.get("selected")
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("refinement_reject_reason") or "")
            if reason not in {"order", "phase"}:
                continue
            key = _core_semantic_key(item)
            if key not in {"T", "L"}:
                continue
            timestamp = _float_or_none(item.get("timestamp"))
            rejected_records.append(
                {
                    "key": key,
                    "timestamp": round(timestamp, 3) if timestamp is not None else None,
                    "rejected_candidate_timestamp": item.get("refinement_candidate_timestamp"),
                    "rejected_candidate_delta_sec": item.get("refinement_candidate_delta_sec"),
                    "reason": reason,
                    "motion_score": item.get("refinement_motion_score"),
                }
            )
    if not rejected_records:
        return

    existing = resolved_keyframes.get("semantic_refinement_rejection")
    if isinstance(existing, dict):
        existing["weak_temporal_geometry_candidate_flags"] = sorted(candidate_flags)
        existing["weak_temporal_geometry_rejected_records"] = rejected_records
    else:
        resolved_keyframes["semantic_refinement_rejection"] = {
            "decision": "ignored_weak_temporal_geometry_candidate",
            "rejection_flags": sorted(rejected_flags),
            "candidate_quality_flags": sorted(candidate_flags),
            "rejected_records": rejected_records,
        }
    _append_flag(resolved_keyframes, "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry")


def _core_visibility_repair_count(resolved_keyframes: dict[str, Any]) -> int:
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return 0
    count = 0
    for item in selected:
        if not isinstance(item, dict):
            continue
        if _semantic_core_anchors({"selected": [item]}) and item.get("pre_visibility_repair_timestamp") is not None:
            count += 1
    return count


def _motion_records_from_scores(motion_scores: dict[str, object] | None) -> list[dict[str, float]]:
    if not isinstance(motion_scores, dict):
        return []
    records: list[dict[str, float]] = []
    frame_rate = _float_or_none(motion_scores.get("frame_rate"))
    window_start = _float_or_none(motion_scores.get("window_start"))
    scores = motion_scores.get("scores")
    if isinstance(scores, list) and frame_rate is not None and frame_rate > 0 and window_start is not None:
        for index, score in enumerate(scores):
            score_value = _float_or_none(score)
            if score_value is None:
                continue
            records.append({"timestamp": round(window_start + index / frame_rate, 3), "motion_score": score_value})
        return records

    selected = motion_scores.get("selected")
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            timestamp = _float_or_none(item.get("timestamp"))
            score_value = _float_or_none(item.get("motion_score"))
            if timestamp is None or score_value is None:
                continue
            records.append({"timestamp": timestamp, "motion_score": score_value})
    return records


def _retry_has_later_strong_motion_conflict(
    retry: SemanticKeyframePipelineResult,
    retry_anchors: dict[str, float],
    motion_scores: dict[str, object] | None,
) -> bool:
    records = _motion_records_from_scores(motion_scores)
    if not records:
        return False
    retry_flags = set(_quality_flags(retry.video_temporal, retry.resolved_keyframes))
    if not (
        "video_temporal_quality_retry" in retry_flags
        or "video_temporal_fallback_recommended" in retry_flags
        or "video_temporal_resolver_advisory_fallback_overridden" in retry_flags
        or "video_temporal_not_high_confidence" in retry_flags
    ):
        return False
    landing = retry_anchors["L"]
    core_records = [
        record
        for record in records
        if retry_anchors["T"] - 0.15 <= record["timestamp"] <= landing + 0.15
    ]
    later_records = [
        record
        for record in records
        if record["timestamp"] >= landing + VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_LAG_SECONDS
    ]
    if not core_records or not later_records:
        return False
    core_peak = max(record["motion_score"] for record in core_records)
    later_peak = max(record["motion_score"] for record in later_records)
    strong_threshold = max(VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_MIN_SCORE, core_peak * VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_RATIO)
    strong_later_count = sum(1 for record in later_records if record["motion_score"] >= strong_threshold)
    if strong_later_count < VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_COUNT:
        return False
    first_strong_later = min(record["timestamp"] for record in later_records if record["motion_score"] >= strong_threshold)
    return first_strong_later >= landing + VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_LAG_SECONDS


def _retry_has_early_main_motion_cluster_conflict(
    retry: SemanticKeyframePipelineResult,
    retry_anchors: dict[str, float],
    motion_scores: dict[str, object] | None,
) -> bool:
    records = _motion_records_from_scores(motion_scores)
    if not records:
        return False
    retry_flags = set(_quality_flags(retry.video_temporal, retry.resolved_keyframes))
    if "video_temporal_quality_retry" not in retry_flags:
        return False
    global_peak = max((record["motion_score"] for record in records), default=0.0)
    if global_peak <= 0:
        return False
    strong_threshold = max(VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_MIN_SCORE, global_peak * 0.65)
    strong_records = [record for record in records if record["motion_score"] >= strong_threshold]
    if len(strong_records) < VIDEO_TEMPORAL_RETRY_EARLY_STRONG_MOTION_COUNT:
        return False
    first_strong = min(record["timestamp"] for record in strong_records)
    last_strong = max(record["timestamp"] for record in strong_records)
    if last_strong - first_strong < VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_MIN_SPAN_SECONDS:
        return False
    peak_record = max(records, key=lambda record: record["motion_score"])
    peak_timestamp = peak_record["timestamp"]
    return (
        retry_anchors["T"] <= first_strong - VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_TAKEOFF_LEAD_SECONDS
        and retry_anchors["A"] <= first_strong - VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_APEX_LEAD_SECONDS
        and retry_anchors["L"] <= first_strong + VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_LANDING_TOLERANCE_SECONDS
        and peak_timestamp >= retry_anchors["L"] + VIDEO_TEMPORAL_RETRY_EARLY_MAIN_MOTION_PEAK_LAG_SECONDS
    )


def _retry_has_low_confidence_late_shift_conflict(
    original: SemanticKeyframePipelineResult,
    retry: SemanticKeyframePipelineResult,
    retry_anchors: dict[str, float],
    motion_scores: dict[str, object] | None,
    *,
    analysis_profile: str | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    retry_flags = set(_quality_flags(retry.video_temporal, retry.resolved_keyframes))
    if "video_temporal_quality_retry" not in retry_flags:
        return False
    unstable_retry_flags = {
        "video_temporal_fallback_recommended",
        "video_temporal_not_high_confidence",
        "video_temporal_resolver_video_fallback_recommended",
        "video_temporal_resolver_advisory_fallback_overridden",
        "video_temporal_resolver_video_validation_not_clean",
    }
    if not (retry_flags & unstable_retry_flags):
        return False
    if (
        _video_confidence(retry.video_temporal, retry.resolved_keyframes)
        > VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_MAX_CONFIDENCE
        and "video_temporal_resolver_video_validation_not_clean" not in retry_flags
    ):
        return False

    original_anchors = _semantic_core_anchors(original.resolved_keyframes)
    common_keys = [key for key in ("T", "A", "L") if key in original_anchors and key in retry_anchors]
    if not common_keys:
        return False
    late_shifts = {
        key: retry_anchors[key] - original_anchors[key]
        for key in common_keys
    }
    if max(late_shifts.values()) < VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_MIN_SECONDS:
        return False

    refinement_scores: list[float] = []
    for key in ("T", "L"):
        record = _core_record_by_key(retry.resolved_keyframes, key)
        if record is None:
            continue
        score = _float_or_none(record.get("refinement_motion_score"))
        if score is not None:
            refinement_scores.append(score)
    weak_refinement_support = (
        len(refinement_scores) >= 2
        and max(refinement_scores) <= VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_REFINEMENT_MAX_SCORE
    )

    weak_motion_support = False
    records = _motion_records_from_scores(motion_scores)
    if records:
        global_peak = max((record["motion_score"] for record in records), default=0.0)
        core_records = [
            record
            for record in records
            if retry_anchors["T"] - 0.15 <= record["timestamp"] <= retry_anchors["L"] + 0.15
        ]
        if core_records and global_peak > 0:
            core_peak = max(record["motion_score"] for record in core_records)
            weak_motion_support = (
                core_peak <= VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_CORE_MOTION_MAX_SCORE
                and core_peak <= global_peak * VIDEO_TEMPORAL_RETRY_LOW_CONFIDENCE_LATE_SHIFT_CORE_MOTION_RATIO
            )

    return weak_refinement_support or weak_motion_support


def _retry_replacement_rejection_flags(
    original: SemanticKeyframePipelineResult,
    retry: SemanticKeyframePipelineResult,
    motion_scores: dict[str, object] | None = None,
    *,
    bio_data: dict[str, Any] | None = None,
    analysis_profile: str | None = None,
) -> list[str]:
    if not retry.used_semantic_frames:
        return []
    retry_anchors = _semantic_core_anchors(retry.resolved_keyframes)
    if not {"T", "A", "L"}.issubset(retry_anchors):
        return []

    if (
        _normalize_action_profile(analysis_profile) == "jump"
        and min(retry_anchors["A"] - retry_anchors["T"], retry_anchors["L"] - retry_anchors["A"]) < VIDEO_TEMPORAL_RETRY_CORE_MIN_GAP_SECONDS
    ):
        return ["video_temporal_quality_retry_core_spacing_rejected"]

    if _retry_has_later_strong_motion_conflict(retry, retry_anchors, motion_scores):
        return ["video_temporal_quality_retry_later_motion_rejected"]
    if _retry_has_early_main_motion_cluster_conflict(retry, retry_anchors, motion_scores):
        return ["video_temporal_quality_retry_early_main_motion_cluster_rejected"]
    if _retry_has_low_confidence_late_shift_conflict(
        original,
        retry,
        retry_anchors,
        motion_scores,
        analysis_profile=analysis_profile,
    ):
        return ["video_temporal_quality_retry_low_confidence_late_shift_rejected"]

    retry_source = str(retry.resolved_keyframes.get("source") or "")
    if retry_source in {"video_ai_refined", "blended"}:
        rejection_flags: list[str] = []
        retry_flags = set(_quality_flags(retry.resolved_keyframes))
        if _semantic_skeleton_tal_conflict_flags(retry.resolved_keyframes, bio_data, analysis_profile=analysis_profile):
            rejection_flags.append("video_temporal_quality_retry_skeleton_tal_conflict_rejected")
        if (
            "semantic_keyframes_retry_tail_motion_aligned_visual_tal_promoted" not in retry_flags
            and _semantic_motion_cluster_conflict_flags(
                retry.resolved_keyframes,
                motion_scores,
                analysis_profile=analysis_profile,
                bio_data=bio_data,
            )
        ):
            rejection_flags.append("video_temporal_quality_retry_motion_cluster_conflict_rejected")
        if rejection_flags:
            return rejection_flags

    original_anchors = _semantic_core_anchors(original.resolved_keyframes)
    if not {"T", "A", "L"}.issubset(original_anchors):
        return []

    shifts = {key: retry_anchors[key] - original_anchors[key] for key in ("T", "A", "L")}
    original_flags = set(_quality_flags(original.video_temporal, original.resolved_keyframes))
    original_has_usable_tal_candidate = _has_ordered_core_tal(original.resolved_keyframes) and (
        original.used_semantic_frames
        or (
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected" not in original_flags
            and str(original.resolved_keyframes.get("source") or "") in {"video_ai_refined", "blended"}
        )
    )
    later_core_count = sum(1 for value in shifts.values() if value >= VIDEO_TEMPORAL_RETRY_LATE_DRIFT_MIN_SECONDS)
    if (
        original_has_usable_tal_candidate
        and later_core_count >= 2
        and shifts["L"] >= VIDEO_TEMPORAL_RETRY_LATE_DRIFT_LANDING_MIN_SECONDS
    ):
        return ["video_temporal_quality_retry_late_drift_rejected"]

    retry_core_duration = retry_anchors["L"] - retry_anchors["T"]
    earlier_core_count = sum(1 for value in shifts.values() if value <= -VIDEO_TEMPORAL_RETRY_EARLY_DRIFT_MIN_SECONDS)
    if (
        original_has_usable_tal_candidate
        and retry_core_duration <= VIDEO_TEMPORAL_RETRY_COMPRESSED_CORE_MAX_SECONDS
        and earlier_core_count >= 2
        and shifts["L"] <= -VIDEO_TEMPORAL_RETRY_COMPRESSED_EARLY_SHIFT_SECONDS
    ):
        return ["video_temporal_quality_retry_early_compressed_rejected"]

    if original.used_semantic_frames and not (original_flags & VIDEO_TEMPORAL_RETRY_EARLY_DRIFT_ALLOW_ORIGINAL_FLAGS):
        if earlier_core_count >= 2 and shifts["L"] <= -VIDEO_TEMPORAL_RETRY_EARLY_DRIFT_LANDING_MIN_SECONDS:
            return ["video_temporal_quality_retry_early_drift_rejected"]
    return []


def _core_record_by_key(resolved_keyframes: dict[str, Any], key: str) -> dict[str, Any] | None:
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return None
    for item in selected:
        if not isinstance(item, dict):
            continue
        if _core_semantic_key(item) == key:
            return item
    return None


def _accepted_visual_promotion_survives_retry_rejection(
    result: SemanticKeyframePipelineResult,
) -> bool:
    if not result.used_semantic_frames:
        return False
    flags = set(_quality_flags(result.resolved_keyframes))
    if not (
        "semantic_keyframes_phase_range_visual_tal_promoted" in flags
        or "semantic_keyframes_distant_full_context_visual_tal_promoted" in flags
        or "semantic_keyframes_tracker_final_loss_visual_tal_promoted" in flags
        or "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_weak_candidate" in flags
    ):
        return False
    selected = result.resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return False
    core_records = [
        item
        for item in selected
        if isinstance(item, dict) and _core_semantic_key(item) in {"T", "A", "L"}
    ]
    if len(core_records) < 3:
        return False
    for item in core_records:
        visibility = item.get("semantic_visibility") if isinstance(item.get("semantic_visibility"), dict) else {}
        if str(visibility.get("status") or "") == "foreground_person_occluded":
            return False
    return semantic_keyframes_are_reliable(result.resolved_keyframes)


def _record_has_foreground_occlusion(record: dict[str, Any] | None) -> bool:
    if not isinstance(record, dict):
        return False
    visibility = record.get("semantic_visibility")
    return isinstance(visibility, dict) and visibility.get("status") == "foreground_person_occluded"


def _retry_takeoff_partial_merge_records(
    original: SemanticKeyframePipelineResult,
    retry: SemanticKeyframePipelineResult,
) -> list[dict[str, Any]] | None:
    if not original.used_semantic_frames or retry.used_semantic_frames:
        return None
    retry_flags = set(_quality_flags(retry.video_temporal, retry.resolved_keyframes))
    if not (
        "semantic_keyframe_core_foreground_occlusion" in retry_flags
        or "semantic_keyframes_unreliable_after_visibility_check" in retry_flags
    ):
        return None

    original_anchors = _semantic_core_anchors(original.resolved_keyframes)
    retry_anchors = _semantic_core_anchors(retry.resolved_keyframes)
    if not {"T", "A", "L"}.issubset(original_anchors) or not {"T", "A", "L"}.issubset(retry_anchors):
        return None

    shift = retry_anchors["T"] - original_anchors["T"]
    if not (
        VIDEO_TEMPORAL_RETRY_TAKEOFF_PARTIAL_MIN_SHIFT_SECONDS
        <= shift
        <= VIDEO_TEMPORAL_RETRY_TAKEOFF_PARTIAL_MAX_SHIFT_SECONDS
    ):
        return None
    if retry_anchors["T"] >= original_anchors["A"] - SEMANTIC_OCCLUSION_REPAIR_CORE_MIN_GAP_SEC:
        return None
    if abs(retry_anchors["A"] - original_anchors["A"]) > VIDEO_TEMPORAL_RETRY_TAKEOFF_PARTIAL_APEX_TOLERANCE_SECONDS:
        return None
    if abs(retry_anchors["L"] - original_anchors["L"]) > VIDEO_TEMPORAL_RETRY_TAKEOFF_PARTIAL_LANDING_TOLERANCE_SECONDS:
        return None

    retry_takeoff = _core_record_by_key(retry.resolved_keyframes, "T")
    original_takeoff = _core_record_by_key(original.resolved_keyframes, "T")
    if retry_takeoff is None or original_takeoff is None or _record_has_foreground_occlusion(retry_takeoff):
        return None

    selected = original.resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        return None
    merged: list[dict[str, Any]] = []
    replaced = False
    for item in selected:
        if not isinstance(item, dict):
            continue
        if _core_semantic_key(item) == "T":
            merged_takeoff = dict(retry_takeoff)
            merged_takeoff["frame_id"] = item.get("frame_id") or retry_takeoff.get("frame_id")
            merged_takeoff["retry_partial_merge_from_timestamp"] = round(original_anchors["T"], 3)
            merged_takeoff["retry_partial_merge_delta_sec"] = round(shift, 3)
            merged_takeoff["selection_reason"] = "video_temporal_quality_retry_takeoff_partial_merge"
            merged.append(merged_takeoff)
            replaced = True
        else:
            merged.append(dict(item))
    return merged if replaced else None


async def _maybe_apply_retry_takeoff_partial_merge(
    *,
    original: SemanticKeyframePipelineResult,
    retry: SemanticKeyframePipelineResult,
    video_path: Path,
    work_dir: Path,
    semantic_frames_dir: Path,
    sampling_metadata: VideoSamplingMetadata,
) -> SemanticKeyframePipelineResult:
    merged_records = _retry_takeoff_partial_merge_records(original, retry)
    if merged_records is None:
        return original

    merged_resolved = dict(original.resolved_keyframes)
    merged_resolved["selected"] = merged_records
    _append_flag(merged_resolved, "video_temporal_quality_retry_takeoff_partial_merge_used")
    _append_flag(merged_resolved, "video_temporal_quality_retry_rejected")

    partial_merge_dir = _isolated_semantic_frames_dir(semantic_frames_dir, "partial_merge")
    try:
        shutil.rmtree(partial_merge_dir, ignore_errors=True)
        semantic_frames, semantic_records = await extract_precise_frames_at_timestamps(
            video_path,
            partial_merge_dir,
            merged_records,
            prefix="semantic",
        )
        semantic_records, visibility_flags = _semantic_frame_visibility_flags(semantic_frames, semantic_records)
        if visibility_flags:
            semantic_frames, semantic_records, repair_flags = await _repair_foreground_occluded_semantic_frames(
                video_path=video_path,
                work_dir=work_dir,
                frame_paths=semantic_frames,
                records=semantic_records,
                source_fps=sampling_metadata.source_fps,
                duration_sec=max(float(sampling_metadata.action_window_end or 0.0), 0.001),
            )
            for flag in repair_flags:
                _append_flag(merged_resolved, flag)
            semantic_records, visibility_flags = _semantic_frame_visibility_flags(semantic_frames, semantic_records)
        for flag in visibility_flags:
            _append_flag(merged_resolved, flag)
        merged_resolved["selected"] = semantic_records
        if not semantic_keyframes_are_reliable(merged_resolved):
            return original
        semantic_frames, semantic_records = _promote_semantic_frame_artifacts(
            semantic_frames,
            semantic_records,
            semantic_frames_dir,
            prefix="semantic",
        )
        merged_resolved["selected"] = semantic_records
    except Exception:  # noqa: BLE001
        return original
    finally:
        shutil.rmtree(partial_merge_dir, ignore_errors=True)

    return SemanticKeyframePipelineResult(
        ai_clip=original.ai_clip,
        video_temporal=original.video_temporal,
        resolved_keyframes=merged_resolved,
        effective_source=effective_timestamp_source(merged_resolved, True),
        semantic_frames=semantic_frames,
        semantic_records=semantic_records,
        refinement_flags=original.refinement_flags,
        quality_flags=_merge_flags(original.video_temporal, merged_resolved),
        used_semantic_frames=True,
        has_semantic_moments=True,
    )


async def _maybe_apply_motion_cluster_fallback_after_retry_rejection(
    *,
    original: SemanticKeyframePipelineResult,
    retry_rejection_flags: list[str],
    video_path: Path,
    work_dir: Path,
    semantic_frames_dir: Path,
    motion_scores: dict[str, object] | None,
    sampling_metadata: VideoSamplingMetadata,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None,
    video_duration_sec: float | None,
) -> SemanticKeyframePipelineResult:
    if _normalize_action_profile(analysis_profile) != "jump":
        return original
    if _accepted_visual_promotion_survives_retry_rejection(original):
        return original
    flags = set(_quality_flags(original.video_temporal, original.resolved_keyframes, retry_rejection_flags))
    if not (
        "video_temporal_quality_retry_skeleton_tal_conflict" in flags
        or "video_temporal_quality_retry_motion_cluster_conflict" in flags
        or "video_temporal_quality_retry_skeleton_tal_conflict_rejected" in flags
        or "video_temporal_quality_retry_motion_cluster_conflict_rejected" in flags
    ):
        return original
    if not isinstance(original.video_temporal, dict):
        return original

    duration = max(float(video_duration_sec or sampling_metadata.action_window_end or 0.0), 0.001)
    max_frames = max(3, len(original.resolved_keyframes.get("selected") or []))
    skeleton_candidates = _skeleton_candidates(bio_data or {})
    motion_records = _resolver_motion_records_from_scores(motion_scores)
    fallback_selected, fallback_flags = _fallback_skeleton_selected(
        skeleton_candidates,
        video_duration_sec=duration,
        max_frames=max_frames,
        motion_records=motion_records,
    )
    existing_flags = _merge_flags(
        original.video_temporal,
        original.resolved_keyframes,
        retry_rejection_flags,
        fallback_flags,
        [
            "video_temporal_quality_retry",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
            "video_temporal_resolver_coherent_tal_weak_jump_late_main_motion_cluster_conflict",
            "video_temporal_quality_retry_extreme_late_motion_cluster_conflict",
        ],
    )
    motion_cluster_selected, motion_cluster_flags = _jump_motion_cluster_fallback_selected(
        analysis_profile=analysis_profile,
        video_ai_result=original.video_temporal,
        motion_records=motion_records,
        skeleton_candidates=skeleton_candidates,
        fallback_selected=fallback_selected,
        video_duration_sec=duration,
        max_frames=max_frames,
        existing_flags=existing_flags,
    )
    if not motion_cluster_selected:
        return original
    fallback_resolved = {
        "source": "skeleton_fallback",
        "confidence": _video_confidence(original.video_temporal, original.resolved_keyframes),
        "quality_flags": _merge_flags(existing_flags, motion_cluster_flags),
        "selected": motion_cluster_selected,
        "video_ai": original.video_temporal,
    }
    if not semantic_keyframes_are_reliable(fallback_resolved):
        return original

    fallback_dir = _isolated_semantic_frames_dir(semantic_frames_dir, "fallback")
    try:
        shutil.rmtree(fallback_dir, ignore_errors=True)
        fallback_records = fallback_resolved.get("selected") if isinstance(fallback_resolved.get("selected"), list) else []
        semantic_frames, semantic_records = await extract_precise_frames_at_timestamps(
            video_path,
            fallback_dir,
            fallback_records,
            prefix="semantic",
        )
        semantic_records, visibility_flags = _semantic_frame_visibility_flags(semantic_frames, semantic_records)
        for flag in visibility_flags:
            _append_flag(fallback_resolved, flag)
        fallback_resolved["selected"] = semantic_records
        if not semantic_keyframes_are_reliable(fallback_resolved):
            return original
        semantic_frames, semantic_records = _promote_semantic_frame_artifacts(
            semantic_frames,
            semantic_records,
            semantic_frames_dir,
            prefix="semantic",
        )
        fallback_resolved["selected"] = semantic_records
    except Exception:  # noqa: BLE001
        return original
    finally:
        shutil.rmtree(fallback_dir, ignore_errors=True)

    _append_flag(fallback_resolved, "video_temporal_quality_retry_rejected")
    _append_flag(fallback_resolved, "video_temporal_quality_retry_motion_cluster_fallback_used")
    for flag in retry_rejection_flags:
        _append_flag(fallback_resolved, flag)

    return SemanticKeyframePipelineResult(
        ai_clip=original.ai_clip,
        video_temporal=original.video_temporal,
        resolved_keyframes=fallback_resolved,
        effective_source=effective_timestamp_source(fallback_resolved, True),
        semantic_frames=semantic_frames,
        semantic_records=semantic_records,
        refinement_flags=original.refinement_flags,
        quality_flags=_merge_flags(original.video_temporal, fallback_resolved),
        used_semantic_frames=True,
        has_semantic_moments=True,
    )


async def _maybe_apply_motion_aligned_candidate_fallback_after_retry_rejection(
    *,
    original: SemanticKeyframePipelineResult,
    retry_result: SemanticKeyframePipelineResult,
    retry_rejection_flags: list[str],
    video_path: Path,
    semantic_frames_dir: Path,
    motion_scores: dict[str, object] | None,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None,
    video_duration_sec: float | None,
) -> SemanticKeyframePipelineResult:
    if _normalize_action_profile(analysis_profile) != "jump":
        return original
    if _accepted_visual_promotion_survives_retry_rejection(original):
        return original
    original_anchors = _semantic_core_anchors(original.resolved_keyframes)
    original_unresolved = not {"T", "A", "L"}.issubset(original_anchors) or not semantic_keyframes_are_reliable(
        original.resolved_keyframes
    )
    retry_flags = set(_quality_flags(retry_result.video_temporal, retry_result.resolved_keyframes, retry_rejection_flags))
    retry_rejected_by_conflict = bool(
        retry_flags
        & {
            "video_temporal_quality_retry_skeleton_tal_conflict_rejected",
            "video_temporal_quality_retry_motion_cluster_conflict_rejected",
            "video_temporal_quality_retry_core_spacing_rejected",
            "video_temporal_quality_retry_later_motion_rejected",
            "video_temporal_quality_retry_early_main_motion_cluster_rejected",
            "video_temporal_quality_retry_low_confidence_late_shift_rejected",
            "video_temporal_quality_retry_late_drift_rejected",
            "video_temporal_quality_retry_early_drift_rejected",
            "video_temporal_quality_retry_early_compressed_rejected",
        }
    )
    if not original_unresolved and not retry_rejected_by_conflict:
        return original

    fallback_selected, fallback_flags, diagnostics = _motion_aligned_candidate_fallback_selected(
        bio_data=bio_data,
        motion_scores=motion_scores,
        analysis_profile=analysis_profile,
        video_duration_sec=video_duration_sec,
    )
    if not fallback_selected:
        return original

    retry_quality_flags = _quality_flags(retry_result.video_temporal, retry_result.resolved_keyframes)
    retry_rejection_diagnostic_flags = [
        flag
        for flag in retry_quality_flags
        if flag.startswith(
            (
                "video_temporal_quality_retry_",
                "video_temporal_resolver_",
                "semantic_keyframe_",
                "semantic_keyframes_",
            )
        )
    ]
    retry_rejection_diagnostic_flags = _merge_flags(retry_rejection_diagnostic_flags, retry_rejection_flags)
    fallback_quality_flags = _motion_aligned_candidate_fallback_quality_flags(
        original.video_temporal,
        original.resolved_keyframes,
        retry_rejection_flags,
        fallback_flags,
        ["video_temporal_quality_retry_rejected"],
    )
    fallback_resolved = {
        "source": "skeleton_fallback",
        "confidence": max(
            SEMANTIC_MOTION_ALIGNED_CANDIDATE_CONFIDENCE,
            _video_confidence(original.video_temporal, original.resolved_keyframes),
        ),
        "quality_flags": fallback_quality_flags,
        "selected": fallback_selected,
        "video_ai": original.video_temporal,
        "semantic_motion_aligned_candidate_fallback": diagnostics,
    }
    if retry_rejection_diagnostic_flags:
        fallback_resolved["video_temporal_quality_retry_rejection_flags"] = retry_rejection_diagnostic_flags
    if not semantic_keyframes_are_reliable(fallback_resolved):
        return original

    fallback_dir = _isolated_semantic_frames_dir(semantic_frames_dir, "motion_aligned_candidate")
    try:
        shutil.rmtree(fallback_dir, ignore_errors=True)
        semantic_frames, semantic_records = await extract_precise_frames_at_timestamps(
            video_path,
            fallback_dir,
            fallback_selected,
            prefix="semantic",
        )
        semantic_records, visibility_flags = _semantic_frame_visibility_flags(semantic_frames, semantic_records)
        for flag in visibility_flags:
            _append_flag(fallback_resolved, flag)
        fallback_resolved["selected"] = semantic_records
        if not semantic_keyframes_are_reliable(fallback_resolved):
            return original
        semantic_frames, semantic_records = _promote_semantic_frame_artifacts(
            semantic_frames,
            semantic_records,
            semantic_frames_dir,
            prefix="semantic",
        )
        fallback_resolved["selected"] = semantic_records
    except Exception:  # noqa: BLE001
        return original
    finally:
        shutil.rmtree(fallback_dir, ignore_errors=True)

    return SemanticKeyframePipelineResult(
        ai_clip=original.ai_clip,
        video_temporal=original.video_temporal,
        resolved_keyframes=fallback_resolved,
        effective_source=effective_timestamp_source(fallback_resolved, True),
        semantic_frames=semantic_frames,
        semantic_records=semantic_records,
        refinement_flags=original.refinement_flags,
        quality_flags=_merge_flags(original.video_temporal, fallback_resolved),
        used_semantic_frames=True,
        has_semantic_moments=True,
    )


def _semantic_result_quality_score(result: SemanticKeyframePipelineResult) -> float:
    flags = set(_quality_flags(result.video_temporal, result.resolved_keyframes))
    selected = result.resolved_keyframes.get("selected") if isinstance(result.resolved_keyframes.get("selected"), list) else []
    score = 100.0 if result.used_semantic_frames else -100.0
    if _has_ordered_core_tal(result.resolved_keyframes):
        score += 18.0
    else:
        score -= 25.0
    score += min(len(selected), 6) * 0.5
    source = str(result.resolved_keyframes.get("source") or "")
    if source == "video_ai_refined":
        score += 8.0
    elif source == "blended":
        score += 4.0
    elif source == "skeleton_fallback":
        score -= 8.0
    score += min(max(_video_confidence(result.video_temporal, result.resolved_keyframes), 0.0), 1.0) * 10.0
    score -= min(_core_visibility_repair_count(result.resolved_keyframes), 3) * 8.0

    penalties = {
        "semantic_keyframe_core_foreground_occlusion": 35.0,
        "semantic_keyframes_unreliable_after_visibility_check": 35.0,
        "semantic_keyframes_unreliable_after_refinement": 25.0,
        "video_temporal_resolver_coherent_tal_motion_conflict_rejected": 25.0,
        "semantic_keyframe_core_foreground_occlusion_repaired": 6.0,
        "video_temporal_resolver_advisory_fallback_overridden": 4.0,
        "video_temporal_resolver_video_fallback_recommended": 4.0,
        "video_temporal_fallback_recommended": 3.0,
        "video_temporal_not_high_confidence": 2.0,
        "semantic_keyframe_refinement_phase_rejected": 1.0,
        "semantic_keyframe_refinement_delta_rejected": 1.0,
        "video_temporal_resolver_video_validation_not_clean": 1.0,
    }
    for flag, penalty in penalties.items():
        if flag in flags:
            score -= penalty
    return round(score, 3)


def _retry_resolves_near_candidate_motion_conflict(
    original: SemanticKeyframePipelineResult,
    retry: SemanticKeyframePipelineResult,
) -> bool:
    original_flags = set(_quality_flags(original.video_temporal, original.resolved_keyframes))
    retry_flags = set(_quality_flags(retry.video_temporal, retry.resolved_keyframes))
    return (
        not original.used_semantic_frames
        or "video_temporal_quality_retry_motion_cluster_conflict" in original_flags
        or "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in original_flags
    ) and "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate" in retry_flags


def _video_temporal_retry_context(
    *,
    video_temporal: dict[str, Any] | None,
    resolved_keyframes: dict[str, Any],
    motion_scores: dict[str, object] | None,
    sampling_metadata: VideoSamplingMetadata,
    analysis_profile: str | None = None,
    used_semantic_frames: bool | None = None,
    bio_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key_moments = video_temporal.get("key_moments") if isinstance(video_temporal, dict) and isinstance(video_temporal.get("key_moments"), dict) else {}
    t_value = _float_or_none(key_moments.get("T_takeoff_sec"))
    a_value = _float_or_none(key_moments.get("A_air_sec"))
    l_value = _float_or_none(key_moments.get("L_landing_sec"))
    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    skeleton_candidate_tal: list[dict[str, Any]] = []
    for key in ("T", "A", "L"):
        candidate = skeleton_anchors.get(key)
        if not isinstance(candidate, dict):
            continue
        semantic_value = {"T": t_value, "A": a_value, "L": l_value}.get(key)
        timestamp = _float_or_none(candidate.get("timestamp"))
        skeleton_candidate_tal.append(
            {
                "key": key,
                "timestamp": round(timestamp, 3) if timestamp is not None else None,
                "confidence": round(float(candidate.get("confidence") or 0.0), 3),
                "raw_confidence": round(float(candidate.get("raw_confidence", candidate.get("confidence") or 0.0)), 3),
                "delta_from_rejected_tal_sec": (
                    round(timestamp - semantic_value, 3)
                    if timestamp is not None and semantic_value is not None
                    else None
                ),
            }
        )

    selected_motion = []
    if isinstance(motion_scores, dict) and isinstance(motion_scores.get("selected"), list):
        motion_items = [item for item in motion_scores["selected"] if isinstance(item, dict)]
        motion_items.sort(key=lambda item: float(item.get("motion_score") or 0.0), reverse=True)
        for item in motion_items[:8]:
            timestamp = _float_or_none(item.get("timestamp"))
            selected_motion.append(
                {
                    "timestamp": item.get("timestamp"),
                    "motion_score": item.get("motion_score"),
                    "frame_id": item.get("frame_id"),
                    "relation_to_rejected_tal": _motion_relation_to_tal(timestamp, t_value, a_value, l_value),
                }
            )
    selected_frames = []
    for item in resolved_keyframes.get("selected", []) if isinstance(resolved_keyframes.get("selected"), list) else []:
        if not isinstance(item, dict):
            continue
        selected_frames.append(
            {
                "phase_code": item.get("phase_code"),
                "timestamp": item.get("timestamp"),
                "key_moment": item.get("key_moment"),
                "selection_reason": item.get("selection_reason"),
                "phase_time_start": item.get("phase_time_start"),
                "phase_time_end": item.get("phase_time_end"),
            }
        )
    retry_reasons = _video_temporal_retry_reason_flags(
        video_temporal,
        resolved_keyframes,
        analysis_profile=analysis_profile,
        used_semantic_frames=used_semantic_frames,
        motion_scores=motion_scores,
        bio_data=bio_data,
    )
    requested_profile = _normalize_action_profile(analysis_profile)
    provider_family = _provider_action_family(video_temporal)
    return {
        "retry_reason_flags": retry_reasons,
        "retry_instruction_hints": _retry_instruction_hints(retry_reasons),
        "requested_analysis_profile": requested_profile or None,
        "provider_action_family": provider_family,
        "profile_mismatch": (
            {"requested": requested_profile, "provider_action_family": provider_family}
            if requested_profile in {"spin", "spiral", "step"} and provider_family not in {None, requested_profile}
            else None
        ),
        "rejected_key_moments": key_moments if key_moments else None,
        "rejected_selected_frames": selected_frames,
        "video_quality_flags": video_temporal.get("quality_flags") if isinstance(video_temporal, dict) else None,
        "resolver_quality_flags": resolved_keyframes.get("quality_flags"),
        "semantic_skeleton_tal_conflicts": resolved_keyframes.get("semantic_skeleton_tal_conflicts"),
        "semantic_motion_cluster_conflict": resolved_keyframes.get("semantic_motion_cluster_conflict"),
        "skeleton_candidate_tal": skeleton_candidate_tal or None,
        "keyframe_candidate_quality_flags": _keyframe_candidate_quality_flags(bio_data),
        "rejected_source": resolved_keyframes.get("source"),
        "action_window": {
            "start_sec": sampling_metadata.action_window_start,
            "end_sec": sampling_metadata.action_window_end,
        },
        "top_motion_records": selected_motion,
    }


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _motion_relation_to_tal(timestamp: float | None, t_value: float | None, a_value: float | None, l_value: float | None) -> str | None:
    if timestamp is None:
        return None
    if t_value is not None and timestamp < t_value - 0.20:
        return "before_takeoff"
    if t_value is not None and l_value is not None and t_value - 0.20 <= timestamp <= l_value + 0.20:
        return "within_rejected_core"
    if l_value is not None and timestamp > l_value + 0.20:
        return "after_rejected_landing"
    if a_value is not None and timestamp >= a_value:
        return "after_rejected_apex"
    return "near_rejected_tal"


def _retry_instruction_hints(retry_reasons: list[str]) -> list[str]:
    hints: list[str] = []
    reasons = set(retry_reasons)
    if "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in reasons:
        hints.append(
            "Top motion records are full-frame motion signals; verify whether they show target-skater takeoff/landing, foreground occlusion, or glide_out before moving T/A/L."
        )
        hints.append(
            "Keep the previous T/A/L if the main skater's visible phase sequence supports it; change them only when first-contact landing or takeoff evidence is clearer elsewhere."
        )
    if "video_temporal_quality_retry_skeleton_tal_conflict" in reasons:
        hints.append(
            "Previous T/A/L conflicted with high-confidence pose-derived skeleton anchors; re-check target-skater takeoff, apex, and first-contact landing against those anchors before changing the timeline."
        )
    if "video_temporal_quality_retry_motion_cluster_conflict" in reasons:
        hints.append(
            "Previous T/A/L did not cover the dominant motion cluster; verify whether that cluster is the target skater's jump core or non-target foreground motion."
        )
    if "video_temporal_low_confidence_retryable" in reasons:
        hints.append("Previous confidence was low; return usable T/A/L only if the target skater is visible enough to identify takeoff, apex, and first-contact landing.")
    if "semantic_keyframes_unreliable_after_visibility_check" in reasons:
        hints.append("Previous semantic frames were rejected by foreground visibility checks; prefer nearby timestamps where the target skater is not covered by a larger foreground person.")
    if "semantic_keyframe_core_foreground_occlusion_repaired" in reasons:
        hints.append("Previous core semantic frame required foreground-occlusion repair; return T/A/L on frames where the target skater is directly visible, not behind a larger foreground person.")
    if "semantic_keyframes_unreliable_after_refinement" in reasons:
        hints.append("Previous refined timestamps violated semantic order or phase bounds; keep T/A/L ordered and inside their phase intervals.")
    if "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion" in reasons:
        hints.append(
            "Tracker ended unrecovered and the previous T/L timestamps had weak local motion support; accept semantic T/A/L only when the target skater is visibly clear and the jump core is unambiguous."
        )
    if "semantic_keyframes_unreliable_candidate_motion_window_conflict" in reasons:
        hints.append(
            "Previous semantic T/A/L was far from current candidate T/A/L, and the candidate window carried stronger motion support; re-check the target skater's jump core near the candidate timestamps before preserving the old segment."
        )
    if "video_temporal_missing_core_tal" in reasons or "video_temporal_missing_phase_segments" in reasons:
        hints.append("Return complete takeoff, air/apex, and landing phases when visible; otherwise keep fallback/manual_review.")
    if "video_temporal_resolver_partial_skeleton_fallback" in reasons:
        hints.append("Skeleton fallback found only part of T/A/L; return full ordered T/A/L only if the video evidence is coherent.")
    if "video_temporal_resolver_advisory_fallback_overridden" in reasons:
        hints.append("Previous provider recommended fallback but T/A/L was structurally coherent; retry only if visual evidence supports cleaner target-skater takeoff, apex, and first-contact landing timestamps.")
    if "video_temporal_profile_mismatch_retryable" in reasons:
        hints.append(
            "Previous response classified a different action family than the requested non-jump profile and produced no usable semantic frames; re-evaluate the target skater for the requested spin, spiral, or step action instead of returning jump phases."
        )
        hints.append(
            "For spin use spin_entry/spin_main/spin_exit phases; for spiral use spiral_entry/spiral_hold/spiral_exit; for step use step_sequence. Keep fallback/manual_review only if the requested action is genuinely not visible."
        )
    return hints


def _should_retry_video_temporal(
    video_temporal: dict[str, Any] | None,
    resolved_keyframes: dict[str, Any],
    *,
    used_semantic_frames: bool,
    analysis_profile: str | None,
    motion_scores: dict[str, object] | None = None,
    bio_data: dict[str, Any] | None = None,
) -> bool:
    profile = _normalize_action_profile(analysis_profile)
    if not isinstance(video_temporal, dict):
        return False
    validation = video_temporal.get("validation") if isinstance(video_temporal.get("validation"), dict) else {}
    flags = set(_quality_flags(video_temporal, resolved_keyframes))
    if flags & VIDEO_TEMPORAL_RETRY_HARD_FAILURE_FLAGS:
        return False
    retry_reasons = _video_temporal_retry_reason_flags(
        video_temporal,
        resolved_keyframes,
        analysis_profile=analysis_profile,
        used_semantic_frames=used_semantic_frames,
        motion_scores=motion_scores,
        bio_data=bio_data,
    )
    if validation.get("errors") and not retry_reasons:
        return False
    if not retry_reasons:
        return False
    if profile != "jump":
        return (
            profile in {"spin", "spiral", "step"}
            and not used_semantic_frames
            and "video_temporal_profile_mismatch_retryable" in retry_reasons
        )
    if not used_semantic_frames:
        return True
    if "semantic_keyframe_core_foreground_occlusion_repaired" in retry_reasons:
        return True
    if (
        "video_temporal_quality_retry_skeleton_tal_conflict" in retry_reasons
        or "video_temporal_quality_retry_motion_cluster_conflict" in retry_reasons
    ):
        return True
    if (
        "video_temporal_resolver_advisory_fallback_overridden" in retry_reasons
        and _video_confidence(video_temporal, resolved_keyframes) < 0.80
    ):
        return True
    return False


def _has_semantic_moments(records: Sequence[object]) -> bool:
    for item in records:
        if not isinstance(item, dict):
            continue
        if item.get("timestamp") is None:
            continue
        if str(item.get("key_moment") or "").startswith(("T_", "A_", "L_")):
            return True
        if str(item.get("phase_code") or "") in {"takeoff", "air", "landing"}:
            return True
    return False


def _partial_semantic_candidates(
    resolved_keyframes: dict[str, Any],
    *,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    profile = _normalize_action_profile(analysis_profile)
    if profile != "jump":
        return _non_jump_partial_phase_candidates(resolved_keyframes, analysis_profile=profile)
    flags = set(_quality_flags(resolved_keyframes))
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list):
        selected = []
    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    video_temporal_candidates = _video_temporal_partial_core_candidates(video_ai) if isinstance(video_ai, dict) else []
    if not (
        "video_temporal_resolver_partial_skeleton_fallback" in flags
        or "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in flags
        or "semantic_keyframes_unreliable_fallback_to_sampled_frames" in flags
        or (
            video_temporal_candidates
            and (
                "video_temporal_resolver_low_video_confidence" in flags
                or "video_temporal_resolver_video_fallback_recommended" in flags
            )
        )
    ):
        return []
    selected_phase_range_keys = {
        _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
        for item in selected
        if isinstance(item, dict)
        and str(item.get("selection_reason") or "").startswith("video_phase_range_")
    }
    prefer_video_temporal_core = (
        str(resolved_keyframes.get("source") or "") == "skeleton_fallback"
        and bool(video_temporal_candidates)
        and not {"T", "A", "L"}.issubset(selected_phase_range_keys)
        and bool(
            flags
            & {
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
            }
        )
    )
    prefer_weak_skeleton_cluster_video_core = (
        str(resolved_keyframes.get("source") or "") == "skeleton_fallback"
        and bool(video_temporal_candidates)
        and _weak_skeleton_cluster_video_partial_support(
            resolved_keyframes,
            video_temporal_candidates,
            analysis_profile=analysis_profile,
            bio_data=bio_data,
        )
        is not None
    )
    prefer_selected_phase_range_core = (
        str(resolved_keyframes.get("source") or "") == "skeleton_fallback"
        and {"T", "A", "L"}.issubset(selected_phase_range_keys)
        and bool(
            flags
            & {
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_unreliable_candidate_motion_window_conflict",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                "video_temporal_resolver_video_fallback_recommended",
            }
        )
    )
    selected = (
        _merge_partial_core_candidates(video_temporal_candidates, selected)
        if prefer_video_temporal_core or prefer_weak_skeleton_cluster_video_core
        else (
            _merge_partial_core_candidates(
                [
                    item
                    for item in selected
                    if isinstance(item, dict)
                    and str(item.get("selection_reason") or "").startswith("video_phase_range_")
                ],
                selected,
            )
            if prefer_selected_phase_range_core
            else _merge_partial_core_candidates(selected, video_temporal_candidates)
        )
    )
    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in selected:
        if not isinstance(item, dict):
            continue
        semantic_key = _core_semantic_key(item)
        if semantic_key not in {"T", "A", "L"} or semantic_key in seen_keys:
            continue
        timestamp = _record_timestamp(item)
        if timestamp is None:
            continue
        confidence = _record_numeric_field(item, "confidence") or 0.0
        min_confidence = 0.15 if item.get("selection_reason") == "video_temporal_low_confidence_partial_core" else 0.50
        if confidence < min_confidence:
            continue
        record = dict(item)
        record["partial_semantic_frame"] = True
        record["selection_status"] = "partial_unreliable"
        record["selection_reason"] = str(record.get("selection_reason") or "partial_semantic_candidate")
        candidates.append(record)
        seen_keys.add(semantic_key)
    return candidates if len(candidates) >= 2 else []


def _merge_partial_core_candidates(
    selected: Sequence[dict[str, Any]],
    video_temporal_candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for source in (selected, video_temporal_candidates):
        for item in source:
            if not isinstance(item, dict):
                continue
            semantic_key = _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
            if semantic_key not in {"T", "A", "L"} or semantic_key in by_key:
                continue
            by_key[semantic_key] = dict(item)
    return [by_key[key] for key in ("T", "A", "L") if key in by_key]


def _non_jump_partial_phase_candidates(
    resolved_keyframes: dict[str, Any],
    *,
    analysis_profile: str,
) -> list[dict[str, Any]]:
    if analysis_profile not in {"spin", "spiral", "step"}:
        return []
    flags = set(_quality_flags(resolved_keyframes))
    if not (
        "video_temporal_profile_mismatch_retryable" in flags
        or "video_temporal_resolver_no_selected_frames" in flags
        or "video_temporal_resolver_no_semantic_selection" in flags
        or "video_temporal_resolver_video_fallback_recommended" in flags
        or "semantic_keyframes_unreliable_fallback_to_sampled_frames" in flags
    ):
        return []

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return []
    phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)]
    if not phase_segments:
        return []

    provider_family = _provider_action_family(video_ai)
    requested_codes = {
        "spin": SPIN_PHASE_CODES,
        "spiral": SPIRAL_PHASE_CODES,
        "step": STEP_PHASE_CODES,
    }.get(analysis_profile, set())
    provider_codes_by_family = {
        "spin": SPIN_PHASE_CODES,
        "spiral": SPIRAL_PHASE_CODES,
        "step": STEP_PHASE_CODES,
    }
    provider_codes = provider_codes_by_family.get(provider_family or "", set())
    allowed_codes = (requested_codes | provider_codes) & NON_JUMP_PARTIAL_PHASE_CODES
    if provider_family == "jump" and provider_family != analysis_profile:
        allowed_codes = {"takeoff", "air", "landing"}
    if not allowed_codes:
        return []

    candidates: list[dict[str, Any]] = []
    for segment in phase_segments:
        phase_code = str(segment.get("phase_code") or "")
        if phase_code not in allowed_codes:
            continue
        timestamp = _partial_phase_timestamp(segment)
        if timestamp is None:
            continue
        confidence = _record_numeric_field(segment, "confidence")
        if confidence is not None and confidence < 0.45:
            continue
        record = {
            "timestamp": round(timestamp, 3),
            "phase_code": phase_code,
            "phase_label": str(segment.get("phase_label") or phase_code),
            "confidence": confidence if confidence is not None else _video_confidence(video_ai),
            "partial_semantic_frame": True,
            "selection_status": "partial_unreliable",
            "selection_reason": (
                "video_temporal_profile_mismatch_partial_phase"
                if provider_family and provider_family != analysis_profile
                else "video_temporal_non_jump_partial_phase"
            ),
        }
        if provider_family == "jump" and provider_family != analysis_profile:
            record["selection_reason"] = "video_temporal_profile_mismatch_partial_action_phase"
            record["partial_semantic_key"] = {"takeoff": "T", "air": "A", "landing": "L"}.get(phase_code)
        if segment.get("time_start") is not None:
            record["phase_time_start"] = segment.get("time_start")
        if segment.get("time_end") is not None:
            record["phase_time_end"] = segment.get("time_end")
        if provider_family and provider_family != analysis_profile:
            record["requested_profile"] = analysis_profile
            record["provider_action_family"] = provider_family
        candidates.append(record)
    return candidates[:3]


def _partial_phase_timestamp(segment: dict[str, Any]) -> float | None:
    hint = _float_or_none(segment.get("key_frame_hint"))
    start = _float_or_none(segment.get("time_start"))
    end = _float_or_none(segment.get("time_end"))
    if start is not None and end is not None:
        if end <= start:
            return None
        if hint is not None and start <= hint <= end:
            return hint
        return start + (end - start) / 2
    if hint is not None and hint >= 0:
        return hint
    return None


def _partial_semantic_candidate_kind(candidates: Sequence[dict[str, Any]]) -> str:
    if any(
        str(item.get("selection_reason") or "") == "video_temporal_profile_mismatch_partial_action_phase"
        for item in candidates
        if isinstance(item, dict)
    ):
        return "mismatch_action"
    if any(str(item.get("phase_code") or "") in NON_JUMP_PARTIAL_PHASE_CODES for item in candidates if isinstance(item, dict)):
        return "profile"
    return "core"


def _low_confidence_jump_partial_can_be_promoted(
    resolved_keyframes: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    analysis_profile: str | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    if str(resolved_keyframes.get("source") or "") not in {"skeleton_fallback", "blended"}:
        return False
    flags = set(_quality_flags(resolved_keyframes))
    if "video_temporal_resolver_low_video_confidence" not in flags:
        return False
    if "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in flags:
        return False

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return False
    if _video_confidence(video_ai, resolved_keyframes) < LOW_CONFIDENCE_JUMP_VISUAL_PROMOTION_CONFIDENCE_FLOOR:
        return False
    action_confirmation = video_ai.get("action_confirmation")
    if not isinstance(action_confirmation, dict) or _normalize_action_profile(action_confirmation.get("action_family")) != "jump":
        return False
    action_confidence = _float_or_none(action_confirmation.get("confidence")) or 0.0
    if action_confidence < LOW_CONFIDENCE_JUMP_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR:
        return False

    anchors: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
        if key in {"T", "A", "L"} and key not in anchors:
            anchors[key] = item
    if set(anchors) != {"T", "A", "L"}:
        return False

    timestamps: dict[str, float] = {}
    for key, item in anchors.items():
        timestamp = _record_timestamp(item)
        confidence = _record_numeric_field(item, "confidence") or 0.0
        if timestamp is None or confidence < LOW_CONFIDENCE_JUMP_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR:
            return False
        timestamps[key] = timestamp
    return timestamps["T"] + 0.02 < timestamps["A"] and timestamps["A"] + 0.02 < timestamps["L"]


def _tracker_final_loss_jump_partial_can_be_promoted(
    resolved_keyframes: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    if str(resolved_keyframes.get("source") or "") not in {"skeleton_fallback", "blended"}:
        return False
    if not _low_visibility_tracker_final_loss_motion_fallback_candidate(bio_data):
        return False

    flags = set(_quality_flags(resolved_keyframes))
    if not (
        "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in flags
        or "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback" in flags
        or "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose" in flags
    ):
        return False

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return False
    if _video_confidence(video_ai, resolved_keyframes) < SEMANTIC_TRACKER_FINAL_LOSS_VISUAL_PROMOTION_CONFIDENCE_FLOOR:
        return False

    action_confirmation = video_ai.get("action_confirmation")
    if isinstance(action_confirmation, dict):
        action_family = _normalize_action_profile(action_confirmation.get("action_family"))
        if action_family and action_family != "jump":
            return False
        action_confidence = _float_or_none(action_confirmation.get("confidence"))
        if (
            action_confidence is not None
            and action_confidence < SEMANTIC_TRACKER_FINAL_LOSS_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR
        ):
            return False

    anchors: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
        if key in {"T", "A", "L"} and key not in anchors:
            anchors[key] = item
    if set(anchors) != {"T", "A", "L"}:
        return False

    timestamps: dict[str, float] = {}
    for key, item in anchors.items():
        timestamp = _record_timestamp(item)
        confidence = _record_numeric_field(item, "confidence") or _video_confidence(video_ai, resolved_keyframes)
        if (
            timestamp is None
            or confidence < SEMANTIC_TRACKER_FINAL_LOSS_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR
        ):
            return False
        timestamps[key] = timestamp

    tal_span = timestamps["L"] - timestamps["T"]
    return (
        tal_span >= SEMANTIC_TRACKER_FINAL_LOSS_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC
        and timestamps["T"] + 0.02 < timestamps["A"]
        and timestamps["A"] + 0.02 < timestamps["L"]
    )


def _phase_range_motion_fallback_jump_partial_can_be_promoted(
    resolved_keyframes: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    if _has_rejected_late_pose_core_candidate_conflict(resolved_keyframes):
        return False

    flags = set(_quality_flags(resolved_keyframes))
    if not (
        "semantic_keyframes_unreliable_after_refinement" in flags
        or "semantic_keyframes_unreliable_candidate_tal_conflict" in flags
        or "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict" in flags
        or "semantic_keyframes_unreliable_fallback_to_sampled_frames" in flags
    ):
        return False

    low_visibility_keys = _low_visibility_motion_fallback_candidate_keys(bio_data)
    takeoff_anchor_low_visibility_boundary_context = (
        _takeoff_anchor_low_visibility_boundary_candidate_context(bio_data)
    )
    low_visibility_candidate_context = (
        len(low_visibility_keys) >= SEMANTIC_PHASE_RANGE_LOW_VISIBILITY_CANDIDATE_MIN_KEYS
        and (
            SEMANTIC_PHASE_RANGE_LOW_VISIBILITY_REQUIRED_KEYS.issubset(low_visibility_keys)
            or takeoff_anchor_low_visibility_boundary_context
        )
    )
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    weak_temporal_candidate_context = bool(
        candidate_flags
        & (
            SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
            | SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS
        )
    )
    if not low_visibility_candidate_context and not weak_temporal_candidate_context:
        return False

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return False
    weak_geometry_only_context = bool(
        candidate_flags & SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS
    ) and not bool(candidate_flags & SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS)
    confidence_floor = (
        SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_WEAK_GEOMETRY_CONFIDENCE_FLOOR
        if weak_geometry_only_context
        else SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_CONFIDENCE_FLOOR
    )
    if _video_confidence(video_ai, resolved_keyframes) < confidence_floor:
        return False

    action_confirmation = video_ai.get("action_confirmation")
    if isinstance(action_confirmation, dict):
        action_family = _normalize_action_profile(action_confirmation.get("action_family"))
        if action_family and action_family != "jump":
            return False
        action_confidence = _float_or_none(action_confirmation.get("confidence"))
        if (
            action_confidence is not None
            and action_confidence < SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR
        ):
            return False

    anchors: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
        if key not in {"T", "A", "L"} or key in anchors:
            continue
        reason = str(item.get("selection_reason") or "")
        if not reason.startswith("video_phase_range_"):
            continue
        visibility = item.get("semantic_visibility") if isinstance(item.get("semantic_visibility"), dict) else {}
        if str(visibility.get("status") or "") == "foreground_person_occluded":
            return False
        anchors[key] = item
    if set(anchors) != {"T", "A", "L"}:
        return False

    timestamps: dict[str, float] = {}
    for key, item in anchors.items():
        timestamp = _record_timestamp(item)
        confidence = _record_numeric_field(item, "confidence") or _video_confidence(video_ai, resolved_keyframes)
        if timestamp is None or confidence < SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR:
            return False
        timestamps[key] = timestamp

    tal_span = timestamps["L"] - timestamps["T"]
    if not (
        SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC
        and timestamps["T"] + 0.02 < timestamps["A"]
        and timestamps["A"] + 0.02 < timestamps["L"]
    ):
        return False

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    shifted_keys = 0
    for key, timestamp in timestamps.items():
        skeleton = skeleton_anchors.get(key)
        if not isinstance(skeleton, dict):
            continue
        if abs(timestamp - skeleton["timestamp"]) >= SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_SHIFT_SEC:
            shifted_keys += 1
    return shifted_keys >= SEMANTIC_PHASE_RANGE_VISUAL_PROMOTION_MIN_SHIFT_KEYS


def _weak_skeleton_cluster_video_partial_support(
    resolved_keyframes: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if _normalize_action_profile(analysis_profile) != "jump":
        return None
    if str(resolved_keyframes.get("source") or "") != "skeleton_fallback":
        return None

    flags = set(_quality_flags(resolved_keyframes))
    if not (
        "semantic_keyframes_unreliable_fallback_to_sampled_frames" in flags
        or "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates" in flags
        or "video_temporal_resolver_partial_skeleton_fallback" in flags
    ):
        return None

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    weak_candidate_context = bool(
        candidate_flags
        & (
            SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
            | SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS
        )
    )
    if not weak_candidate_context:
        return None
    if candidate_flags & SEMANTIC_CANDIDATE_FALLBACK_BLOCKING_FLAGS:
        return None

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return None
    video_confidence = _video_confidence(video_ai, resolved_keyframes)
    if video_confidence < WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_CONFIDENCE_FLOOR:
        return None

    action_confirmation = video_ai.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        return None
    action_family = _normalize_action_profile(action_confirmation.get("action_family"))
    if action_family != "jump":
        return None
    action_confidence = _float_or_none(action_confirmation.get("confidence"))
    if (
        action_confidence is None
        or action_confidence < WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR
    ):
        return None

    anchors: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
        if key not in {"T", "A", "L"} or key in anchors:
            continue
        if str(item.get("selection_reason") or "") != "video_temporal_low_confidence_partial_core":
            continue
        timestamp = _record_timestamp(item)
        confidence = _record_numeric_field(item, "confidence") or video_confidence
        if (
            timestamp is None
            or confidence < WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR
        ):
            return None
        anchors[key] = {
            "timestamp": timestamp,
            "confidence": confidence,
        }
    if set(anchors) != {"T", "A", "L"}:
        return None
    if not (
        anchors["T"]["timestamp"] + 0.02 < anchors["A"]["timestamp"]
        and anchors["A"]["timestamp"] + 0.02 < anchors["L"]["timestamp"]
    ):
        return None

    tal_span = anchors["L"]["timestamp"] - anchors["T"]["timestamp"]
    if not (
        WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC
        <= tal_span
        <= WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC
    ):
        return None

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    if set(skeleton_anchors) != {"T", "A", "L"}:
        return None

    matches: list[dict[str, float | str]] = []
    deltas: list[float] = []
    candidate_confidences: list[float] = []
    for key in ("T", "A", "L"):
        skeleton = skeleton_anchors[key]
        candidate_confidence = float(skeleton["confidence"])
        candidate_confidences.append(candidate_confidence)
        if candidate_confidence > WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MAX_CANDIDATE_CONFIDENCE:
            return None
        delta = anchors[key]["timestamp"] - skeleton["timestamp"]
        abs_delta = abs(delta)
        if abs_delta > WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MAX_DELTA_SEC:
            return None
        deltas.append(abs_delta)
        matches.append(
            {
                "key": key,
                "video_timestamp": round(anchors[key]["timestamp"], 3),
                "candidate_timestamp": round(skeleton["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(candidate_confidence, 3),
                "video_phase_confidence": round(float(anchors[key]["confidence"]), 3),
            }
        )

    mean_delta = sum(deltas) / len(deltas)
    if mean_delta > WEAK_SKELETON_CLUSTER_VISUAL_PROMOTION_MAX_MEAN_DELTA_SEC:
        return None

    return {
        "decision": "promoted_video_tal_over_weak_skeleton_cluster",
        "matches": matches,
        "max_delta_sec": round(max(deltas), 3),
        "mean_delta_sec": round(mean_delta, 3),
        "candidate_quality_flags": sorted(candidate_flags),
        "average_candidate_confidence": round(sum(candidate_confidences) / len(candidate_confidences), 3),
        "video_confidence": round(video_confidence, 3),
        "action_confidence": round(action_confidence, 3),
        "tal_span_sec": round(tal_span, 3),
    }


def _retry_tail_motion_aligned_jump_partial_promotion_support(
    resolved_keyframes: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    motion_scores: dict[str, object] | None,
    *,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if _normalize_action_profile(analysis_profile) != "jump":
        return None
    if _has_rejected_late_pose_core_candidate_conflict(resolved_keyframes):
        return None

    resolved_flags = set(_quality_flags(resolved_keyframes))
    if not {
        "video_temporal_resolver_coherent_tal_retry_tail_motion_conflict",
        "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
    }.issubset(resolved_flags):
        return None

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return None
    video_flags = set(_quality_flags(video_ai))
    if "video_temporal_quality_retry" not in video_flags:
        return None

    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    unreliable_candidate_flags = (
        SEMANTIC_CANDIDATE_TEMPORAL_GEOMETRY_UNRELIABLE_FLAGS
        | SEMANTIC_CANDIDATE_WEAK_GEOMETRY_UNRELIABLE_FLAGS
    )
    if not (candidate_flags & unreliable_candidate_flags):
        return None

    video_confidence = _video_confidence(video_ai, resolved_keyframes)
    if video_confidence < SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_CONFIDENCE_FLOOR:
        return None

    action_confidence: float | None = None
    action_confirmation = video_ai.get("action_confirmation")
    if isinstance(action_confirmation, dict):
        action_family = _normalize_action_profile(action_confirmation.get("action_family"))
        if action_family and action_family != "jump":
            return None
        action_confidence = _float_or_none(action_confirmation.get("confidence"))
        if (
            action_confidence is not None
            and action_confidence < SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR
        ):
            return None

    anchors: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        visibility = item.get("semantic_visibility") if isinstance(item.get("semantic_visibility"), dict) else {}
        if str(visibility.get("status") or "") == "foreground_person_occluded":
            return None
        key = _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
        if key not in {"T", "A", "L"} or key in anchors:
            continue
        reason = str(item.get("selection_reason") or "")
        if not (
            reason.startswith("video_phase_range_")
            or reason == "video_temporal_low_confidence_partial_core"
        ):
            continue
        timestamp = _record_timestamp(item)
        confidence = _record_numeric_field(item, "confidence") or video_confidence
        if (
            timestamp is None
            or confidence < SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR
        ):
            return None
        anchors[key] = {
            "timestamp": timestamp,
            "confidence": confidence,
            "selection_reason": reason,
        }
    if set(anchors) != {"T", "A", "L"}:
        return None
    if not (
        anchors["T"]["timestamp"] + 0.02 < anchors["A"]["timestamp"]
        and anchors["A"]["timestamp"] + 0.02 < anchors["L"]["timestamp"]
    ):
        return None

    tal_span = anchors["L"]["timestamp"] - anchors["T"]["timestamp"]
    if not (
        SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC
    ):
        return None

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    candidate_confidences = [
        float(anchor["confidence"])
        for key, anchor in skeleton_anchors.items()
        if key in {"T", "A", "L"} and isinstance(anchor, dict)
    ]
    if not candidate_confidences:
        return None
    if max(candidate_confidences) > SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MAX_CANDIDATE_CONFIDENCE:
        return None

    shifted: list[dict[str, float | str]] = []
    for key in ("T", "A", "L"):
        skeleton = skeleton_anchors.get(key)
        if not isinstance(skeleton, dict):
            continue
        delta = anchors[key]["timestamp"] - skeleton["timestamp"]
        if abs(delta) < SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MIN_SHIFT_SEC:
            continue
        shifted.append(
            {
                "key": key,
                "semantic_timestamp": round(anchors[key]["timestamp"], 3),
                "candidate_timestamp": round(skeleton["timestamp"], 3),
                "delta_sec": round(delta, 3),
                "candidate_confidence": round(float(skeleton["confidence"]), 3),
            }
        )
    if len(shifted) < SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_MIN_SHIFT_KEYS:
        return None

    records = _motion_records_from_scores(motion_scores)
    if not records:
        return None
    peak_record = max(records, key=lambda record: record["motion_score"])
    peak_timestamp = peak_record["timestamp"]
    core_start = anchors["T"]["timestamp"] - SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_TAKEOFF_LEAD_SEC
    core_end = anchors["L"]["timestamp"] + SEMANTIC_RETRY_TAIL_VISUAL_PROMOTION_LANDING_TRAIL_SEC
    if not (core_start <= peak_timestamp <= core_end):
        return None
    core_peak = max(
        (
            record["motion_score"]
            for record in records
            if core_start <= record["timestamp"] <= core_end
        ),
        default=0.0,
    )

    return {
        "support_mode": "retry_tail_motion_aligned_visual_tal_over_weak_temporal_geometry_candidate",
        "peak_timestamp": round(peak_timestamp, 3),
        "peak_motion_score": round(peak_record["motion_score"], 5),
        "core_window_start_sec": round(core_start, 3),
        "core_window_end_sec": round(core_end, 3),
        "core_peak_motion_score": round(core_peak, 5),
        "tal_span_sec": round(tal_span, 3),
        "shifted_keys": shifted,
        "candidate_max_confidence": round(max(candidate_confidences), 3),
        "candidate_quality_flags": sorted(candidate_flags),
        "video_confidence": round(video_confidence, 3),
        "action_confidence": round(action_confidence, 3) if action_confidence is not None else None,
        "phase_confidences": {
            key: round(float(anchor["confidence"]), 3)
            for key, anchor in sorted(anchors.items())
        },
        "selection_reasons": {
            key: str(anchor["selection_reason"])
            for key, anchor in sorted(anchors.items())
        },
    }


def _distant_full_context_visual_jump_partial_can_be_promoted(
    resolved_keyframes: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None,
    video_duration_sec: float | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    if str(resolved_keyframes.get("source") or "") not in {"skeleton_fallback", "blended"}:
        return False
    duration = _float_or_none(video_duration_sec)
    if duration is None or duration < SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MIN_DURATION_SEC:
        return False
    candidate_flags = set(_keyframe_candidate_quality_flags(bio_data))
    weak_geometry_candidate_context = (
        "keyframe_candidates_excluded_unreliable_pose_frames" in candidate_flags
        and "tal_candidate_weak_geometry" in candidate_flags
        and bool(candidate_flags & SEMANTIC_DISTANT_FULL_CONTEXT_WEAK_GEOMETRY_FLAGS)
    )
    low_visibility_candidate_context = _low_visibility_tracker_final_loss_motion_fallback_candidate(bio_data)
    if not low_visibility_candidate_context and not weak_geometry_candidate_context:
        return False

    flags = set(_quality_flags(resolved_keyframes))
    if not (
        "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose" in flags
        or "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback" in flags
        or "semantic_keyframes_tracker_final_loss_motion_fallback_ignored" in flags
        or "semantic_keyframes_unreliable_fallback_to_sampled_frames" in flags
        or "semantic_keyframes_unreliable_candidate_tal_conflict" in flags
        or "semantic_keyframes_unreliable_candidate_motion_window_conflict" in flags
    ):
        return False

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return False
    if _video_confidence(video_ai, resolved_keyframes) < SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_CONFIDENCE_FLOOR:
        return False

    video_flags = set(_quality_flags(video_ai))
    if not (video_flags & SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_CONTEXT_FLAGS):
        return False

    action_confirmation = video_ai.get("action_confirmation")
    if isinstance(action_confirmation, dict):
        action_family = _normalize_action_profile(action_confirmation.get("action_family"))
        if action_family and action_family != "jump":
            return False
        action_confidence = _float_or_none(action_confirmation.get("confidence"))
        if (
            action_confidence is not None
            and action_confidence < SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_ACTION_CONFIDENCE_FLOOR
        ):
            return False

    anchors: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
        if key not in {"T", "A", "L"} or key in anchors:
            continue
        reason = str(item.get("selection_reason") or "")
        if reason != "video_temporal_low_confidence_partial_core" and not reason.startswith("video_phase_range_"):
            continue
        anchors[key] = item
    if set(anchors) != {"T", "A", "L"}:
        return False

    timestamps: dict[str, float] = {}
    for key, item in anchors.items():
        timestamp = _record_timestamp(item)
        confidence = _record_numeric_field(item, "confidence") or _video_confidence(video_ai, resolved_keyframes)
        if (
            timestamp is None
            or confidence < SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_PHASE_CONFIDENCE_FLOOR
        ):
            return False
        timestamps[key] = timestamp

    tal_span = timestamps["L"] - timestamps["T"]
    max_tal_span = (
        SEMANTIC_DISTANT_FULL_CONTEXT_WEAK_GEOMETRY_MAX_TAL_SPAN_SEC
        if weak_geometry_candidate_context
        else SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MAX_TAL_SPAN_SEC
    )
    if not (
        SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MIN_TAL_SPAN_SEC
        <= tal_span
        <= max_tal_span
        and timestamps["T"] + 0.02 < timestamps["A"]
        and timestamps["A"] + 0.02 < timestamps["L"]
    ):
        return False

    skeleton_anchors = _skeleton_candidate_anchors(bio_data)
    shifted_keys = 0
    for key, timestamp in timestamps.items():
        skeleton = skeleton_anchors.get(key)
        if not isinstance(skeleton, dict):
            continue
        if abs(timestamp - skeleton["timestamp"]) >= SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MIN_SHIFT_SEC:
            shifted_keys += 1
    return shifted_keys >= SEMANTIC_DISTANT_FULL_CONTEXT_VISUAL_PROMOTION_MIN_SHIFT_KEYS


def _long_unresolved_motion_fallback_jump_partial_can_be_promoted(
    resolved_keyframes: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None,
) -> bool:
    if _normalize_action_profile(analysis_profile) != "jump":
        return False
    if str(resolved_keyframes.get("source") or "") not in {"skeleton_fallback", "blended"}:
        return False
    if not _has_long_unresolved_low_precision_motion_fallback(bio_data):
        return False

    flags = set(_quality_flags(resolved_keyframes))
    if not (
        "video_temporal_resolver_low_video_confidence" in flags
        or "semantic_keyframes_unreliable_fallback_to_sampled_frames" in flags
        or "video_temporal_resolver_video_fallback_recommended" in flags
        or "semantic_keyframes_unreliable_after_refinement" in flags
        or "video_temporal_quality_retry_motion_cluster_conflict" in flags
    ):
        return False

    video_ai = resolved_keyframes.get("video_ai") if isinstance(resolved_keyframes.get("video_ai"), dict) else {}
    if not isinstance(video_ai, dict):
        return False
    video_confidence = _video_confidence(video_ai, resolved_keyframes)
    if video_confidence < SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_CONFIDENCE_FLOOR:
        return False

    action_confirmation = video_ai.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        return False
    action_family = _normalize_action_profile(action_confirmation.get("action_family"))
    if action_family != "jump":
        return False
    action_confidence = _float_or_none(action_confirmation.get("confidence"))
    if (
        action_confidence is None
        or action_confidence < SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_ACTION_CONFIDENCE_FLOOR
    ):
        return False

    anchors: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = _core_semantic_key(item) or str(item.get("partial_semantic_key") or "")
        if key not in {"T", "A", "L"} or key in anchors:
            continue
        reason = str(item.get("selection_reason") or "")
        if reason != "video_temporal_low_confidence_partial_core" and not reason.startswith("video_phase_range_"):
            continue
        anchors[key] = item
    if set(anchors) != {"T", "A", "L"}:
        return False

    timestamps: dict[str, float] = {}
    for key, item in anchors.items():
        timestamp = _record_timestamp(item)
        confidence = _record_numeric_field(item, "confidence") or video_confidence
        if (
            timestamp is None
            or confidence < SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_PHASE_CONFIDENCE_FLOOR
        ):
            return False
        timestamps[key] = timestamp

    tal_span = timestamps["L"] - timestamps["T"]
    return (
        SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_MIN_TAL_SPAN_SEC
        <= tal_span
        <= SEMANTIC_LONG_UNRESOLVED_PARTIAL_PROMOTION_MAX_TAL_SPAN_SEC
        and timestamps["T"] + 0.02 < timestamps["A"]
        and timestamps["A"] + 0.02 < timestamps["L"]
    )


def _semantic_records_from_promoted_partials(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    core_order = {"T": 0, "A": 1, "L": 2}
    sorted_records = sorted(
        [dict(item) for item in records if isinstance(item, dict)],
        key=lambda item: core_order.get(_core_semantic_key(item) or str(item.get("partial_semantic_key") or ""), 99),
    )
    for index, item in enumerate(sorted_records, start=1):
        item.pop("partial_semantic_frame", None)
        item.pop("selection_status", None)
        item["frame_id"] = f"semantic_{index:04d}"
        item["selection_reason"] = "video_temporal_visual_tal_promoted"
        item["semantic_visual_tal_promotion"] = True
        output.append(item)
    return output


def _promoted_partial_resolved_keyframes(
    resolved_keyframes: dict[str, Any],
    semantic_records: Sequence[dict[str, Any]],
    *,
    promotion_reason: str,
) -> dict[str, Any]:
    promoted = dict(resolved_keyframes)
    promoted["source"] = "blended"
    records = [dict(item) for item in semantic_records]
    for item in records:
        item["selection_reason"] = promotion_reason
        if promotion_reason == "video_temporal_low_confidence_visual_tal_promoted":
            item["low_confidence_visual_promotion"] = True
        elif promotion_reason == "video_temporal_tracker_final_loss_visual_tal_promoted":
            item["tracker_final_loss_visual_promotion"] = True
        elif promotion_reason == "video_temporal_phase_range_visual_tal_promoted":
            item["phase_range_visual_promotion"] = True
        elif promotion_reason == "video_temporal_distant_full_context_visual_tal_promoted":
            item["distant_full_context_visual_promotion"] = True
        elif promotion_reason == "video_temporal_long_unresolved_motion_fallback_partial_tal_promoted":
            item["long_unresolved_motion_fallback_partial_promotion"] = True
    promoted["selected"] = records
    _remove_flags(
        promoted,
        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
        "semantic_keyframes_partial_core_frames_available",
    )
    if promotion_reason == "video_temporal_phase_range_visual_tal_promoted":
        _append_flag(promoted, "video_temporal_resolver_phase_range_visual_tal_promoted")
        _append_flag(promoted, "video_temporal_resolver_phase_range_zoomed_visual_check")
    elif promotion_reason == "video_temporal_distant_full_context_visual_tal_promoted":
        _append_flag(promoted, "video_temporal_resolver_distant_full_context_visual_tal_promoted")
        _append_flag(promoted, "video_temporal_resolver_phase_range_zoomed_visual_check")
    elif promotion_reason == "video_temporal_long_unresolved_motion_fallback_partial_tal_promoted":
        _append_flag(promoted, "video_temporal_resolver_long_unresolved_motion_fallback_partial_tal_promoted")
    else:
        _append_flag(promoted, "video_temporal_resolver_low_confidence_visual_tal_promoted")
        _append_flag(promoted, "video_temporal_resolver_advisory_low_confidence_overridden")
        _append_flag(promoted, "video_temporal_resolver_low_confidence_zoomed_visual_check")
    return promoted


def promote_long_unresolved_motion_fallback_partials(
    resolved_keyframes: dict[str, Any] | None,
    partial_records: Sequence[dict[str, Any]],
    *,
    bio_data: dict[str, Any] | None,
    analysis_profile: str | None,
) -> dict[str, Any] | None:
    if not isinstance(resolved_keyframes, dict):
        return resolved_keyframes
    if not _long_unresolved_motion_fallback_jump_partial_can_be_promoted(
        resolved_keyframes,
        partial_records,
        analysis_profile=analysis_profile,
        bio_data=bio_data,
    ):
        return resolved_keyframes
    promoted_records = _semantic_records_from_promoted_partials(partial_records)
    promoted = _promoted_partial_resolved_keyframes(
        resolved_keyframes,
        promoted_records,
        promotion_reason="video_temporal_long_unresolved_motion_fallback_partial_tal_promoted",
    )
    _append_flag(
        promoted,
        "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted",
    )
    _remove_flags(
        promoted,
        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
        "semantic_keyframes_unreliable_after_refinement",
        "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
        "video_temporal_quality_retry_motion_cluster_conflict",
    )
    promoted["semantic_long_unresolved_motion_fallback_partial_promotion"] = {
        "decision": "promoted_partial_video_tal_over_long_unresolved_motion_fallback",
        "candidate_quality_flags": _keyframe_candidate_quality_flags(bio_data),
        "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
    }
    promoted.pop("partial_selected", None)
    return promoted


def _record_has_visible_target(record: dict[str, Any]) -> bool:
    visibility = record.get("semantic_visibility")
    return isinstance(visibility, dict) and visibility.get("status") == "target_visible"


def _tracker_final_loss_visual_promotion_visibility_passed(records: Sequence[dict[str, Any]]) -> bool:
    visible_keys: set[str] = set()
    core_count = 0
    for record in records:
        if not isinstance(record, dict) or not _is_core_semantic_record(record):
            continue
        core_count += 1
        visibility = record.get("semantic_visibility")
        status = str(visibility.get("status") or "") if isinstance(visibility, dict) else ""
        if status == "foreground_person_occluded":
            return False
        if status == "target_visible":
            key = _core_semantic_key(record)
            if key:
                visible_keys.add(key)
    return core_count >= 3 and bool(visible_keys & {"T", "L"})


def _low_confidence_visual_promotion_repair_timestamps(
    record: dict[str, Any],
    records: Sequence[dict[str, Any]],
    *,
    source_fps: float,
    duration_sec: float,
) -> list[float]:
    original = _record_timestamp(record)
    if original is None:
        return []
    phase_bounds = _record_phase_bounds(record, duration_sec)
    if phase_bounds is None:
        return []
    start, end = phase_bounds
    fps = max(1.0, min(float(source_fps or 30.0), 60.0))
    step = 1.0 / fps
    max_steps = max(1, int(round(LOW_CONFIDENCE_JUMP_VISUAL_REPAIR_MAX_DELTA_SEC * fps)))
    record_core_key = _core_semantic_key(record)
    core_other_timestamps = [
        (value, _core_semantic_key(item))
        for item in records
        if item is not record
        and not _same_semantic_record(record, item)
        and _is_core_semantic_record(item)
        and (value := _record_timestamp(item)) is not None
    ]
    output: list[float] = []
    seen = {round(original, 3)}
    for step_index in range(1, max_steps + 1):
        for direction in (-1, 1):
            candidate = round(original + direction * step_index * step, 3)
            if candidate in seen:
                continue
            seen.add(candidate)
            if not (start <= candidate <= end):
                continue
            if abs(candidate - original) > LOW_CONFIDENCE_JUMP_VISUAL_REPAIR_MAX_DELTA_SEC:
                continue
            if any(
                abs(candidate - other_timestamp) < _repair_core_min_gap(record_core_key, other_key)
                for other_timestamp, other_key in core_other_timestamps
            ):
                continue
            output.append(candidate)
            if len(output) >= LOW_CONFIDENCE_JUMP_VISUAL_REPAIR_MAX_CANDIDATES:
                return output
    return output


async def _repair_low_confidence_promoted_visual_frames(
    *,
    video_path: Path,
    work_dir: Path,
    frame_paths: list[Path],
    records: list[dict[str, Any]],
    source_fps: float,
    duration_sec: float,
) -> tuple[list[Path], list[dict[str, Any]], list[str]]:
    repaired_paths = list(frame_paths)
    repaired_records = [dict(item) for item in records]
    flags: list[str] = []
    repair_root = work_dir / "low_confidence_visual_promotion_repair"

    for index, record in enumerate(list(repaired_records)):
        if _record_has_visible_target(record):
            continue
        best: tuple[Path, dict[str, Any]] | None = None
        for candidate_timestamp in _low_confidence_visual_promotion_repair_timestamps(
            record,
            repaired_records,
            source_fps=source_fps,
            duration_sec=duration_sec,
        ):
            try:
                extracted = await _extract_repair_candidate_frame(video_path, repair_root, record, candidate_timestamp)
            except Exception:  # noqa: BLE001
                continue
            if extracted is None:
                continue
            candidate_path, candidate_record = extracted
            inspected, visibility_flags = _semantic_frame_visibility_flags(
                [candidate_path],
                [candidate_record],
                include_zoomed_small_targets=True,
                require_visible_target=True,
            )
            if visibility_flags or not inspected or not _record_has_visible_target(inspected[0]):
                continue
            best = (candidate_path, inspected[0])
            break
        if best is None:
            continue
        candidate_path, candidate_record = best
        target_path = repaired_paths[index]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate_path, target_path)
        repaired_paths[index] = target_path
        repaired_record = {
            **candidate_record,
            "frame_id": record.get("frame_id"),
            "pre_visual_repair_timestamp": record.get("timestamp"),
            "visual_repair_timestamp": candidate_record.get("timestamp"),
            "visual_repair_method": "nearby_zoomed_yolo_visible_frame",
        }
        repaired_records[index] = repaired_record
        flags.append("video_temporal_resolver_low_confidence_visual_repair_used")

    return repaired_paths, repaired_records, sorted(set(flags))


def _video_temporal_partial_core_candidates(video_ai: dict[str, Any]) -> list[dict[str, Any]]:
    key_moments = video_ai.get("key_moments") if isinstance(video_ai.get("key_moments"), dict) else {}
    phase_segments = [item for item in video_ai.get("phase_segments", []) if isinstance(item, dict)]
    phase_by_code = {str(item.get("phase_code") or ""): item for item in phase_segments}
    core_specs = (
        ("T_takeoff_sec", "takeoff", "T"),
        ("A_air_sec", "air", "A"),
        ("L_landing_sec", "landing", "L"),
    )
    records: list[dict[str, Any]] = []
    for key_moment, phase_code, semantic_key in core_specs:
        timestamp = key_moments.get(key_moment)
        try:
            timestamp_value = float(timestamp)
        except (TypeError, ValueError):
            continue
        if timestamp_value < 0:
            continue
        segment = phase_by_code.get(phase_code, {})
        confidence = _record_numeric_field(segment, "confidence")
        record = {
            "timestamp": round(timestamp_value, 3),
            "phase_code": phase_code,
            "phase_label": str(segment.get("phase_label") or phase_code),
            "key_moment": key_moment,
            "confidence": confidence if confidence is not None else _video_confidence(video_ai),
            "selection_reason": "video_temporal_low_confidence_partial_core",
            "partial_semantic_key": semantic_key,
        }
        if segment.get("time_start") is not None:
            record["phase_time_start"] = segment.get("time_start")
        if segment.get("time_end") is not None:
            record["phase_time_end"] = segment.get("time_end")
        records.append(record)
    return records


def _bbox_area(bbox: dict[str, Any]) -> float:
    return max(0.0, float(bbox.get("width", 0.0) or 0.0)) * max(0.0, float(bbox.get("height", 0.0) or 0.0))


def _bbox_intersection_area(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1 = float(a.get("x", 0.0) or 0.0)
    ay1 = float(a.get("y", 0.0) or 0.0)
    ax2 = ax1 + float(a.get("width", 0.0) or 0.0)
    ay2 = ay1 + float(a.get("height", 0.0) or 0.0)
    bx1 = float(b.get("x", 0.0) or 0.0)
    by1 = float(b.get("y", 0.0) or 0.0)
    bx2 = bx1 + float(b.get("width", 0.0) or 0.0)
    by2 = by1 + float(b.get("height", 0.0) or 0.0)
    width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0.0, min(ay2, by2) - max(ay1, by1))
    return width * height


def _is_core_semantic_record(record: dict[str, Any]) -> bool:
    phase_code = str(record.get("phase_code") or "")
    key_moment = str(record.get("key_moment") or "")
    return phase_code in CORE_SEMANTIC_PHASES or key_moment.startswith(("T_", "A_", "L_"))


def _core_semantic_key(record: dict[str, Any]) -> str | None:
    phase_code = str(record.get("phase_code") or "")
    key_moment = str(record.get("key_moment") or "")
    if phase_code == "takeoff" or key_moment.startswith("T_"):
        return "T"
    if phase_code == "air" or key_moment.startswith("A_"):
        return "A"
    if phase_code == "landing" or key_moment.startswith("L_"):
        return "L"
    return None


def _repair_core_min_gap(left_key: str | None, right_key: str | None) -> float:
    if {left_key, right_key} == {"A", "L"}:
        return SEMANTIC_OCCLUSION_REPAIR_APEX_LANDING_MIN_GAP_SEC
    return SEMANTIC_OCCLUSION_REPAIR_CORE_MIN_GAP_SEC


def _foreground_occlusion_diagnostic(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    person_candidates = [item for item in candidates if isinstance(item.get("bbox"), dict) and _bbox_area(item["bbox"]) > 0.0]
    if len(person_candidates) < 2:
        return None
    largest = max(person_candidates, key=lambda item: _bbox_area(item["bbox"]))
    largest_bbox = largest["bbox"]
    largest_area = _bbox_area(largest_bbox)
    if largest_area < FOREGROUND_OCCLUDER_MIN_AREA:
        return None

    for candidate in person_candidates:
        if candidate is largest:
            continue
        candidate_bbox = candidate["bbox"]
        candidate_area = _bbox_area(candidate_bbox)
        if candidate_area <= 0.0 or largest_area < candidate_area * FOREGROUND_OCCLUDER_AREA_RATIO:
            continue
        overlap_ratio = _bbox_intersection_area(largest_bbox, candidate_bbox) / candidate_area
        if overlap_ratio >= FOREGROUND_OCCLUDER_MIN_OVERLAP:
            return {
                "occluder_bbox": largest_bbox,
                "occluder_area": round(largest_area, 6),
                "occluder_confidence": largest.get("confidence"),
                "target_candidate_bbox": candidate_bbox,
                "target_candidate_area": round(candidate_area, 6),
                "target_candidate_confidence": candidate.get("confidence"),
                "target_overlap_ratio": round(overlap_ratio, 4),
            }
    return None


def _visible_target_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for item in candidates:
        bbox = item.get("bbox")
        if not isinstance(bbox, dict):
            continue
        area = _bbox_area(bbox)
        confidence = float(item.get("confidence", 0.0) or 0.0)
        min_area = (
            SEMANTIC_ZOOMED_TARGET_MIN_AREA
            if str(item.get("source") or "") == "yolo_zoomed_content"
            else SEMANTIC_TARGET_MIN_AREA
        )
        if min_area <= area <= SEMANTIC_TARGET_MAX_AREA and confidence >= 0.25:
            visible.append(item)
    return visible


def _has_visible_target_candidate(candidates: list[dict[str, Any]]) -> bool:
    return bool(_visible_target_candidates(candidates))


def _largest_person_area(candidates: list[dict[str, Any]]) -> float:
    return max(
        (_bbox_area(item["bbox"]) for item in candidates if isinstance(item.get("bbox"), dict)),
        default=0.0,
    )


def _best_visible_target_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    visible = _visible_target_candidates(candidates)
    if not visible:
        return None
    return max(
        visible,
        key=lambda item: (
            float(item.get("confidence", 0.0) or 0.0),
            _bbox_area(item["bbox"]) if isinstance(item.get("bbox"), dict) else 0.0,
        ),
    )


def _repair_candidate_quality_score(
    candidates: list[dict[str, Any]],
    *,
    candidate_timestamp: float,
    original_timestamp: float | None,
    target_context_area: float | None,
    semantic_key: str | None = None,
) -> float | None:
    target = _best_visible_target_candidate(candidates)
    if target is None:
        return None
    if _foreground_occlusion_diagnostic(candidates) is not None:
        return None

    target_bbox = target.get("bbox") if isinstance(target.get("bbox"), dict) else {}
    target_area = _bbox_area(target_bbox)
    target_confidence = float(target.get("confidence", 0.0) or 0.0)
    largest_area = _largest_person_area(candidates)
    foreground_area = max(0.0, largest_area - target_area)
    distance = abs(candidate_timestamp - original_timestamp) if original_timestamp is not None else 0.0

    area_score = 0.0
    if target_context_area is not None and target_context_area > 0.0 and target_area > 0.0:
        area_ratio = target_area / target_context_area
        area_score = max(0.0, 1.0 - min(abs(area_ratio - 1.0), 1.0))
    foreground_penalty = min(3.0, foreground_area * 8.0)
    distance_penalty = min(2.0, distance / max(SEMANTIC_OCCLUSION_REPAIR_MAX_DELTA_SEC, 0.001))
    if semantic_key == "L":
        distance_penalty *= SEMANTIC_OCCLUSION_REPAIR_LANDING_DISTANCE_PENALTY_MULTIPLIER
    return round(target_confidence * 4.0 + area_score * 2.0 - foreground_penalty - distance_penalty, 4)


def _target_context_area(candidates_by_index: dict[int, list[dict[str, Any]]]) -> float | None:
    areas: list[float] = []
    for candidates in candidates_by_index.values():
        visible = _visible_target_candidates(candidates)
        if not visible:
            continue
        areas.append(min(_bbox_area(item["bbox"]) for item in visible if isinstance(item.get("bbox"), dict)))
    if len(areas) < SEMANTIC_TARGET_CONTEXT_MIN_FRAMES:
        return None
    areas.sort()
    return areas[len(areas) // 2]


def _detect_visibility_person_candidates(
    frame_path: Path,
    *,
    include_zoomed_small_targets: bool = False,
) -> list[dict[str, Any]]:
    if include_zoomed_small_targets:
        try:
            return detect_person_candidates(
                frame_path,
                min_confidence=0.25,
                include_zoomed_small_targets=True,
            )
        except TypeError:
            return detect_person_candidates(frame_path, min_confidence=0.25)
    return detect_person_candidates(frame_path, min_confidence=0.25)


def _target_context_area_from_records(
    frame_paths: Sequence[Path],
    records: Sequence[dict[str, Any]],
    *,
    include_zoomed_small_targets: bool = False,
) -> float | None:
    candidates_by_index: dict[int, list[dict[str, Any]]] = {}
    for index, (frame_path, record) in enumerate(zip(frame_paths, records)):
        if not _is_core_semantic_record(record):
            continue
        try:
            candidates_by_index[index] = _detect_visibility_person_candidates(
                frame_path,
                include_zoomed_small_targets=include_zoomed_small_targets,
            )
        except Exception:  # noqa: BLE001
            candidates_by_index[index] = []
    return _target_context_area(candidates_by_index)


def _single_foreground_person_diagnostic(
    candidates: list[dict[str, Any]],
    *,
    target_context_area: float | None,
) -> dict[str, Any] | None:
    if target_context_area is None or target_context_area <= 0.0:
        return None
    person_candidates = [item for item in candidates if isinstance(item.get("bbox"), dict) and _bbox_area(item["bbox"]) > 0.0]
    if len(person_candidates) != 1:
        return None
    candidate = person_candidates[0]
    candidate_bbox = candidate["bbox"]
    candidate_area = _bbox_area(candidate_bbox)
    if candidate_area < FOREGROUND_OCCLUDER_MIN_AREA:
        return None
    if candidate_area < target_context_area * SEMANTIC_TARGET_CONTEXT_AREA_MULTIPLIER:
        return None
    return {
        "occlusion_type": "single_large_foreground_person",
        "occluder_bbox": candidate_bbox,
        "occluder_area": round(candidate_area, 6),
        "occluder_confidence": candidate.get("confidence"),
        "target_context_area": round(target_context_area, 6),
        "occluder_target_area_ratio": round(candidate_area / target_context_area, 3),
    }


def _semantic_frame_visibility_flags(
    frame_paths: Sequence[Path],
    records: Sequence[dict[str, Any]],
    *,
    include_zoomed_small_targets: bool = False,
    require_visible_target: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    flags: list[str] = []
    inspected: list[dict[str, Any]] = []
    candidates_by_index: dict[int, list[dict[str, Any]]] = {}
    for index, (frame_path, record) in enumerate(zip(frame_paths, records)):
        if not _is_core_semantic_record(record):
            continue
        try:
            if include_zoomed_small_targets:
                candidates_by_index[index] = _detect_visibility_person_candidates(
                    frame_path,
                    include_zoomed_small_targets=True,
                )
            else:
                candidates_by_index[index] = _detect_visibility_person_candidates(frame_path)
        except Exception:  # noqa: BLE001
            candidates_by_index[index] = []
    context_area = _target_context_area(candidates_by_index)
    for frame_path, record in zip(frame_paths, records):
        item = dict(record)
        if not _is_core_semantic_record(item):
            inspected.append(item)
            continue
        candidates = candidates_by_index.get(len(inspected), [])
        diagnostic = _foreground_occlusion_diagnostic(candidates)
        if diagnostic is None:
            diagnostic = _single_foreground_person_diagnostic(candidates, target_context_area=context_area)
        if diagnostic is not None:
            item["semantic_visibility"] = {
                "status": "foreground_person_occluded",
                "person_candidate_count": len(candidates),
                **diagnostic,
            }
            flags.append("semantic_keyframe_core_foreground_occlusion")
        elif require_visible_target:
            target = _best_visible_target_candidate(candidates)
            if target is None:
                item["semantic_visibility"] = {
                    "status": "target_not_detected",
                    "person_candidate_count": len(candidates),
                    "visibility_check_method": "zoomed_yolo" if include_zoomed_small_targets else "yolo",
                }
                flags.append("semantic_keyframes_unreliable_after_visibility_check")
            else:
                item["semantic_visibility"] = {
                    "status": "target_visible",
                    "person_candidate_count": len(candidates),
                    "visibility_check_method": "zoomed_yolo"
                    if str(target.get("source") or "") == "yolo_zoomed_content"
                    else "yolo",
                    "target_candidate_bbox": target.get("bbox"),
                    "target_candidate_confidence": target.get("confidence"),
                    "target_candidate_source": target.get("source"),
                }
        inspected.append(item)
    return inspected, sorted(set(flags))


def _record_timestamp(record: dict[str, Any]) -> float | None:
    try:
        return float(record.get("timestamp"))
    except (TypeError, ValueError):
        return None


def _record_numeric_field(record: dict[str, Any], field: str) -> float | None:
    try:
        return float(record.get(field))
    except (TypeError, ValueError):
        return None


def _record_phase_bounds(record: dict[str, Any], duration_sec: float) -> tuple[float, float] | None:
    start = record.get("phase_time_start", record.get("time_start"))
    end = record.get("phase_time_end", record.get("time_end"))
    try:
        start_value = float(start) if start is not None else 0.0
        end_value = float(end) if end is not None else duration_sec
    except (TypeError, ValueError):
        return None
    if _core_semantic_key(record) == "L":
        start_tolerance = _record_numeric_field(record, "phase_time_start_refinement_tolerance_sec") or 0.0
        end_tolerance = _record_numeric_field(record, "phase_time_end_refinement_tolerance_sec") or 0.0
        start_value -= max(0.0, min(start_tolerance, 0.25))
        end_value += max(0.0, min(end_tolerance, 0.25))
    start_value = max(0.0, start_value)
    end_value = min(duration_sec, end_value)
    if end_value <= start_value:
        return None
    return start_value, end_value


def _record_repair_max_delta(record: dict[str, Any]) -> float:
    explicit_value = _record_numeric_field(record, "visibility_repair_max_delta_sec")
    if explicit_value is not None:
        return max(0.0, min(explicit_value, SEMANTIC_OCCLUSION_REPAIR_MAX_DELTA_SEC))
    if _core_semantic_key(record) == "L" and record.get("refinement_method") == "local_motion_peak":
        return SEMANTIC_OCCLUSION_REPAIR_REFINED_LANDING_MAX_DELTA_SEC
    return SEMANTIC_OCCLUSION_REPAIR_MAX_DELTA_SEC


def _repair_search_centers(record: dict[str, Any]) -> list[tuple[float, str, bool]]:
    timestamp = _record_timestamp(record)
    if timestamp is None:
        return []
    centers: list[tuple[float, str, bool]] = [(timestamp, "timestamp", False)]
    pre_refine_timestamp = _record_numeric_field(record, "pre_refine_timestamp")
    if pre_refine_timestamp is not None and abs(pre_refine_timestamp - timestamp) >= 0.001:
        centers.append((pre_refine_timestamp, "pre_refine_timestamp", True))
    return centers


def _same_semantic_record(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left is right:
        return True
    left_frame_id = str(left.get("frame_id") or "")
    right_frame_id = str(right.get("frame_id") or "")
    if left_frame_id and right_frame_id and left_frame_id == right_frame_id:
        return True
    left_key = str(left.get("key_moment") or "")
    right_key = str(right.get("key_moment") or "")
    return bool(left_key and right_key and left_key == right_key)


def _candidate_repair_timestamp_options(
    record: dict[str, Any],
    records: Sequence[dict[str, Any]],
    *,
    source_fps: float,
    duration_sec: float,
) -> list[tuple[float, str, float]]:
    centers = _repair_search_centers(record)
    phase_bounds = _record_phase_bounds(record, duration_sec)
    if not centers or phase_bounds is None:
        return []

    fps = max(1.0, min(float(source_fps or 30.0), 60.0))
    step = 1.0 / fps
    max_steps = max(1, int(round(SEMANTIC_OCCLUSION_REPAIR_MAX_DELTA_SEC * fps)))
    options: list[tuple[float, str, float]] = []
    seen: set[float] = set()
    record_timestamp = centers[0][0]
    repair_max_delta = _record_repair_max_delta(record)

    other_timestamps = [
        value
        for item in records
        if item is not record
        and not _same_semantic_record(record, item)
        and (value := _record_timestamp(item)) is not None
    ]
    record_core_key = _core_semantic_key(record)
    core_other_timestamps = [
        (value, _core_semantic_key(item))
        for item in records
        if item is not record
        and not _same_semantic_record(record, item)
        and _is_core_semantic_record(item)
        and (value := _record_timestamp(item)) is not None
    ]
    enforce_core_gap = _is_core_semantic_record(record)

    for center, source, include_center in centers:
        start, end = phase_bounds
        previous_timestamp = max((value for value in other_timestamps if value < center), default=None)
        next_timestamp = min((value for value in other_timestamps if value > center), default=None)
        if previous_timestamp is not None:
            start = max(start, previous_timestamp + SEMANTIC_OCCLUSION_REPAIR_MIN_GAP_SEC)
        if next_timestamp is not None:
            end = min(end, next_timestamp - SEMANTIC_OCCLUSION_REPAIR_MIN_GAP_SEC)
        if end <= start:
            continue

        candidate_values: list[float] = []
        if include_center and start <= center <= end:
            candidate_values.append(round(center, 3))
        for step_index in range(1, max_steps + 1):
            for direction in (-1, 1):
                candidate_values.append(round(center + direction * step_index * step, 3))

        for candidate in candidate_values:
            if not (start <= candidate <= end):
                continue
            if enforce_core_gap and any(
                abs(candidate - other_timestamp) < _repair_core_min_gap(record_core_key, other_key)
                for other_timestamp, other_key in core_other_timestamps
            ):
                continue
            if abs(candidate - record_timestamp) > repair_max_delta:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            options.append((candidate, source, center))
    return options


def _candidate_repair_timestamps(
    record: dict[str, Any],
    records: Sequence[dict[str, Any]],
    *,
    source_fps: float,
    duration_sec: float,
) -> list[float]:
    return [
        candidate
        for candidate, _, _ in _candidate_repair_timestamp_options(
            record,
            records,
            source_fps=source_fps,
            duration_sec=duration_sec,
        )
    ]


def _late_phase_reanchor_rollback_records(
    records: Sequence[dict[str, Any]],
    *,
    timestamp_field: str,
    duration_sec: float,
) -> list[dict[str, Any]] | None:
    updated = [dict(record) for record in records]
    core_indices: dict[str, int] = {}
    has_occluded_late_reanchor = False
    for index, record in enumerate(updated):
        key = _core_semantic_key(record)
        if key in {"T", "A", "L"} and key not in core_indices:
            core_indices[key] = index
        visibility = record.get("semantic_visibility")
        if (
            isinstance(visibility, dict)
            and visibility.get("status") == "foreground_person_occluded"
            and record.get("late_phase_range_reanchor") is True
        ):
            has_occluded_late_reanchor = True

    if not has_occluded_late_reanchor or not {"T", "A", "L"}.issubset(core_indices):
        return None

    anchors: dict[str, float] = {}
    for key in ("T", "A", "L"):
        index = core_indices[key]
        record = updated[index]
        if record.get("late_phase_range_reanchor") is not True:
            return None
        timestamp = _record_numeric_field(record, timestamp_field)
        if timestamp is None:
            return None
        phase_bounds = _record_phase_bounds(record, duration_sec)
        if phase_bounds is not None:
            start, end = phase_bounds
            if not (start <= timestamp <= end):
                return None
        original_timestamp = _record_timestamp(record)
        anchors[key] = timestamp
        record["timestamp"] = round(timestamp, 3)
        record["pre_visibility_repair_timestamp"] = original_timestamp
        record["visibility_repair_timestamp"] = round(timestamp, 3)
        record["visibility_repair_delta_sec"] = (
            round(timestamp - original_timestamp, 3) if original_timestamp is not None else None
        )
        record["visibility_repair_method"] = "late_phase_range_reanchor_rollback_visible_frame"
        record["visibility_repair_search_origin"] = timestamp_field
        record.pop("semantic_visibility", None)
        updated[index] = record

    if not (
        anchors["T"] + SEMANTIC_OCCLUSION_REPAIR_MIN_GAP_SEC < anchors["A"]
        and anchors["A"] + SEMANTIC_OCCLUSION_REPAIR_MIN_GAP_SEC < anchors["L"]
    ):
        return None
    return updated


async def _repair_late_phase_reanchor_occlusion_group(
    *,
    video_path: Path,
    work_dir: Path,
    frame_paths: list[Path],
    records: list[dict[str, Any]],
    duration_sec: float,
) -> tuple[list[Path], list[dict[str, Any]], list[str]]:
    if not frame_paths or len(frame_paths) != len(records):
        return frame_paths, records, []

    for timestamp_field in ("pre_late_phase_reanchor_timestamp", "pre_refine_timestamp"):
        rollback_records = _late_phase_reanchor_rollback_records(
            records,
            timestamp_field=timestamp_field,
            duration_sec=duration_sec,
        )
        if rollback_records is None:
            continue
        rollback_dir = work_dir / f"late_reanchor_rollback_{timestamp_field}"
        try:
            rollback_paths, extracted_records = await extract_precise_frames_at_timestamps(
                video_path,
                rollback_dir,
                rollback_records,
                prefix="repair",
            )
            inspected_records, visibility_flags = _semantic_frame_visibility_flags(
                rollback_paths,
                extracted_records,
                include_zoomed_small_targets=True,
            )
        except Exception:  # noqa: BLE001
            shutil.rmtree(rollback_dir, ignore_errors=True)
            continue
        if visibility_flags:
            shutil.rmtree(rollback_dir, ignore_errors=True)
            continue

        final_records: list[dict[str, Any]] = []
        for original, inspected in zip(records, inspected_records):
            final_records.append({**inspected, "frame_id": original.get("frame_id", inspected.get("frame_id"))})
        for source_path, target_path in zip(rollback_paths, frame_paths):
            shutil.copyfile(source_path, target_path)
        shutil.rmtree(rollback_dir, ignore_errors=True)
        return (
            frame_paths,
            final_records,
            [
                "semantic_keyframe_core_foreground_occlusion_repaired",
                "semantic_keyframes_late_phase_reanchor_occlusion_rolled_back",
            ],
        )

    return frame_paths, records, []


async def _extract_repair_candidate_frame(
    video_path: Path,
    work_dir: Path,
    record: dict[str, Any],
    timestamp: float,
) -> tuple[Path, dict[str, Any]] | None:
    candidate_dir = work_dir / f"repair_{str(record.get('frame_id') or 'semantic')}_{int(timestamp * 1000):08d}"
    frame_paths, records = await extract_precise_frames_at_timestamps(
        video_path,
        candidate_dir,
        [{**record, "timestamp": timestamp}],
        prefix="repair",
    )
    if not frame_paths or not records:
        return None
    return frame_paths[0], records[0]


async def _repair_foreground_occluded_semantic_frames(
    *,
    video_path: Path,
    work_dir: Path,
    frame_paths: list[Path],
    records: list[dict[str, Any]],
    source_fps: float,
    duration_sec: float,
) -> tuple[list[Path], list[dict[str, Any]], list[str]]:
    updated_records = [dict(record) for record in records]
    flags: list[str] = []
    repaired_any = False
    repair_root = work_dir / "semantic_visibility_repair"
    shutil.rmtree(repair_root, ignore_errors=True)
    repair_root.mkdir(parents=True, exist_ok=True)

    try:
        rollback_paths, rollback_records, rollback_flags = await _repair_late_phase_reanchor_occlusion_group(
            video_path=video_path,
            work_dir=repair_root,
            frame_paths=frame_paths,
            records=updated_records,
            duration_sec=duration_sec,
        )
        if rollback_flags:
            return rollback_paths, rollback_records, sorted(set(rollback_flags))

        for index, record in enumerate(records):
            visibility = record.get("semantic_visibility")
            if not isinstance(visibility, dict) or visibility.get("status") != "foreground_person_occluded":
                continue
            if index >= len(frame_paths):
                continue
            original_timestamp = _record_timestamp(record)
            semantic_key = _core_semantic_key(record)
            target_context_area = _target_context_area_from_records(
                frame_paths,
                updated_records,
                include_zoomed_small_targets=True,
            )
            best_repair: tuple[float, Path, dict[str, Any], str, float, float] | None = None
            checked = 0
            for candidate_timestamp, search_origin, search_center in _candidate_repair_timestamp_options(
                record,
                updated_records,
                source_fps=source_fps,
                duration_sec=duration_sec,
            ):
                if checked >= SEMANTIC_OCCLUSION_REPAIR_MAX_CANDIDATES:
                    break
                checked += 1
                try:
                    extracted = await _extract_repair_candidate_frame(video_path, repair_root, record, candidate_timestamp)
                except Exception:  # noqa: BLE001
                    continue
                if extracted is None:
                    continue
                candidate_path, candidate_record = extracted
                try:
                    candidates = _detect_visibility_person_candidates(
                        candidate_path,
                        include_zoomed_small_targets=True,
                    )
                except Exception:  # noqa: BLE001
                    continue
                quality_score = _repair_candidate_quality_score(
                    candidates,
                    candidate_timestamp=candidate_timestamp,
                    original_timestamp=original_timestamp,
                    target_context_area=target_context_area,
                    semantic_key=semantic_key,
                )
                if quality_score is None:
                    continue
                if best_repair is None or quality_score > best_repair[0]:
                    best_repair = (quality_score, candidate_path, candidate_record, search_origin, search_center, candidate_timestamp)

            if best_repair is not None:
                quality_score, candidate_path, candidate_record, search_origin, search_center, candidate_timestamp = best_repair
                preserve_timestamp = bool(record.get("visibility_repair_preserve_timestamp"))
                repaired_timestamp = original_timestamp if preserve_timestamp and original_timestamp is not None else candidate_timestamp
                repaired_record = {
                    **candidate_record,
                    "frame_id": record.get("frame_id"),
                    "timestamp": round(repaired_timestamp, 3),
                    "pre_visibility_repair_timestamp": original_timestamp,
                    "visibility_repair_timestamp": round(candidate_timestamp, 3),
                    "visibility_repair_delta_sec": (
                        round(candidate_timestamp - original_timestamp, 3) if original_timestamp is not None else None
                    ),
                    "visibility_repair_method": "nearby_unoccluded_person_frame",
                    "visibility_repair_search_origin": search_origin,
                    "visibility_repair_search_center_timestamp": round(search_center, 3),
                    "visibility_repair_quality_score": quality_score,
                }
                if preserve_timestamp:
                    repaired_record["visibility_repair_frame_timestamp"] = round(candidate_timestamp, 3)
                    repaired_record["visibility_repair_timestamp_preserved"] = True
                repaired_record.pop("semantic_visibility", None)
                shutil.copyfile(candidate_path, frame_paths[index])
                updated_records[index] = repaired_record
                flags.append("semantic_keyframe_core_foreground_occlusion_repaired")
                repaired_any = True
    finally:
        shutil.rmtree(repair_root, ignore_errors=True)

    if repaired_any:
        return frame_paths, updated_records, sorted(set(flags))
    return frame_paths, records, []


async def start_video_temporal_task(
    *,
    video_path: Path,
    work_dir: Path,
    sampling_metadata: VideoSamplingMetadata,
    action_type: str,
    action_subtype: str | None,
    analyzed_video_kind: str,
    user_note: str | None = None,
    input_window: VideoInputWindow | None = None,
    retry_context: dict[str, Any] | None = None,
    precheck: bool = True,
) -> VideoTemporalTaskHandle:
    if precheck:
        await precheck_video(video_path)
    effective_input_window = input_window or build_video_input_window(video_path)
    source_duration_sec = effective_input_window.source_duration_sec or detect_video_duration(video_path)
    ai_clip_path = await cut_action_window_ai_clip(
        video_path,
        effective_input_window.input_window_start_sec,
        effective_input_window.input_window_end_sec,
        work_dir / "action_window_ai.mp4",
        max_duration_sec=None,
    )
    clip_duration_sec = detect_video_duration(ai_clip_path)
    clip_fps = detect_video_fps(ai_clip_path)
    task = asyncio.create_task(
        analyze_video_temporal(
            ai_clip_path,
            action_type=action_type,
            action_subtype=action_subtype,
            user_note=user_note,
            video_duration_sec=clip_duration_sec,
            source_video_duration_sec=source_duration_sec,
            source_fps=clip_fps,
            timestamp_offset_sec=effective_input_window.input_window_start_sec,
            analyzed_video_kind=analyzed_video_kind,
            retry_context=retry_context,
        )
    )
    return VideoTemporalTaskHandle(
        task=task,
        ai_clip_path=ai_clip_path,
        source_duration_sec=source_duration_sec,
        clip_duration_sec=clip_duration_sec,
        clip_fps=clip_fps,
        timestamp_offset_sec=effective_input_window.input_window_start_sec,
        analyzed_video_kind=analyzed_video_kind,
        input_window=effective_input_window,
    )


async def resolve_semantic_keyframe_pipeline(
    *,
    video_path: Path,
    work_dir: Path,
    semantic_frames_dir: Path,
    video_temporal: dict[str, Any] | None,
    motion_scores: dict[str, object] | None,
    sampling_metadata: VideoSamplingMetadata,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None = None,
    video_duration_sec: float | None = None,
    ai_clip: dict[str, Any] | None = None,
) -> SemanticKeyframePipelineResult:
    detected_duration_sec = None
    if video_duration_sec is None or video_duration_sec <= 0:
        detected_duration_sec = detect_video_duration(video_path)
    resolver_duration = max(
        float(video_duration_sec or detected_duration_sec or sampling_metadata.action_window_end or 0.0),
        0.001,
    )
    try:
        resolved_keyframes = resolve_semantic_keyframes(
            video_temporal,
            bio_data or {},
            motion_scores,
            video_duration_sec=resolver_duration,
            analysis_profile=analysis_profile,
        )
    except Exception as exc:  # noqa: BLE001
        resolved_keyframes = {
            "source": "skeleton_fallback",
            "confidence": 0.0,
            "quality_flags": ["video_temporal_resolver_failed"],
            "selected": [],
            "video_ai": video_temporal or {},
            "resolver_error": str(exc),
        }

    selected = resolved_keyframes.get("selected") if isinstance(resolved_keyframes.get("selected"), list) else []
    has_semantic_moments = _has_semantic_moments(selected)
    for flag in _semantic_tracker_final_loss_motion_fallback_flags(
        resolved_keyframes,
        bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(resolved_keyframes, flag)
    for flag in _semantic_tracker_final_loss_outside_reliable_pose_flags(
        resolved_keyframes,
        bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(resolved_keyframes, flag)
    for flag in _semantic_low_visibility_bounded_motion_fallback_drift_flags(
        resolved_keyframes,
        bio_data,
        analysis_profile=analysis_profile,
    ):
        _append_flag(resolved_keyframes, flag)
    used_semantic_frames = semantic_keyframes_are_reliable(resolved_keyframes)
    semantic_frames: list[Path] = []
    semantic_records: list[dict[str, Any]] = []
    partial_semantic_frames: list[Path] = []
    partial_semantic_records: list[dict[str, Any]] = []
    refinement_flags: list[str] = []

    if has_semantic_moments and not used_semantic_frames:
        _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_fallback_to_sampled_frames")

    if used_semantic_frames:
        try:
            refined_records, refinement_flags = await refine_semantic_keyframe_timestamps(
                video_path,
                work_dir / "semantic_refinement",
                selected,
                source_fps=sampling_metadata.source_fps,
                video_duration_sec=resolver_duration,
            )
            if refinement_flags:
                for flag in refinement_flags:
                    _append_flag(resolved_keyframes, flag)
            resolved_keyframes["selected"] = refined_records
            _maybe_ignore_refinement_rejection_near_skeleton_candidate(
                resolved_keyframes,
                bio_data,
                refinement_flags,
                analysis_profile=analysis_profile,
            )
            _maybe_ignore_refinement_rejection_for_weak_temporal_geometry(
                resolved_keyframes,
                bio_data,
                refinement_flags,
                analysis_profile=analysis_profile,
            )
            _maybe_align_pose_supported_takeoff_candidate(
                resolved_keyframes,
                bio_data,
                motion_scores,
                analysis_profile=analysis_profile,
            )
            _maybe_align_low_visibility_main_motion_candidates(
                resolved_keyframes,
                bio_data,
                motion_scores,
                analysis_profile=analysis_profile,
            )
            _maybe_reanchor_late_phase_range_tal(
                resolved_keyframes,
                bio_data,
                motion_scores,
                analysis_profile=analysis_profile,
            )
            for flag in _semantic_weak_refinement_late_candidate_conflict_flags(
                resolved_keyframes,
                bio_data,
                analysis_profile=analysis_profile,
            ):
                _append_flag(resolved_keyframes, flag)
            for flag in _semantic_candidate_tal_conflict_flags(
                resolved_keyframes,
                bio_data,
                analysis_profile=analysis_profile,
                motion_scores=motion_scores,
            ):
                _append_flag(resolved_keyframes, flag)
            for flag in _semantic_motion_cluster_conflict_flags(
                resolved_keyframes,
                motion_scores,
                analysis_profile=analysis_profile,
                bio_data=bio_data,
            ):
                _append_flag(resolved_keyframes, flag)
            for flag in _semantic_tracker_final_loss_weak_semantic_motion_flags(
                resolved_keyframes,
                bio_data,
                analysis_profile=analysis_profile,
            ):
                _append_flag(resolved_keyframes, flag)
            for flag in _semantic_tracker_final_loss_outside_reliable_pose_flags(
                resolved_keyframes,
                bio_data,
                analysis_profile=analysis_profile,
            ):
                _append_flag(resolved_keyframes, flag)
            for flag in _semantic_low_visibility_bounded_motion_fallback_drift_flags(
                resolved_keyframes,
                bio_data,
                analysis_profile=analysis_profile,
            ):
                _append_flag(resolved_keyframes, flag)
            if not semantic_keyframes_are_reliable(resolved_keyframes):
                _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_after_refinement")
                used_semantic_frames = False
            else:
                semantic_frames, semantic_records = await extract_precise_frames_at_timestamps(
                    video_path,
                    semantic_frames_dir,
                    refined_records,
                    prefix="semantic",
                )
                semantic_records, visibility_flags = _semantic_frame_visibility_flags(semantic_frames, semantic_records)
                if visibility_flags:
                    semantic_frames, semantic_records, repair_flags = await _repair_foreground_occluded_semantic_frames(
                        video_path=video_path,
                        work_dir=work_dir,
                        frame_paths=semantic_frames,
                        records=semantic_records,
                        source_fps=sampling_metadata.source_fps,
                        duration_sec=resolver_duration,
                    )
                    if repair_flags:
                        for flag in repair_flags:
                            _append_flag(resolved_keyframes, flag)
                        semantic_records, visibility_flags = _semantic_frame_visibility_flags(
                            semantic_frames,
                            semantic_records,
                            include_zoomed_small_targets=True,
                        )
                if visibility_flags:
                    for flag in visibility_flags:
                        _append_flag(resolved_keyframes, flag)
                resolved_keyframes["selected"] = semantic_records
                if not semantic_keyframes_are_reliable(resolved_keyframes):
                    _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_after_visibility_check")
                    used_semantic_frames = False
                    semantic_frames = []
                    semantic_records = []
        except Exception as exc:  # noqa: BLE001
            extra_flag = "semantic_frame_extract_failed"
            if isinstance(exc, AnalysisPipelineError) and exc.code == AnalysisErrorCode.FRAME_EXTRACT_FAILED:
                extra_flag = "semantic_frame_extract_failed"
            elif "semantic_keyframes_unreliable_after_visibility_check" in str(exc):
                extra_flag = "semantic_keyframes_unreliable_after_visibility_check"
            elif "semantic_keyframes_unreliable_after_refinement" in str(exc):
                extra_flag = "semantic_keyframes_unreliable_after_refinement"
            _append_flag(resolved_keyframes, extra_flag)
            used_semantic_frames = False
            semantic_frames = []
            semantic_records = []

    if not used_semantic_frames:
        partial_candidates = _partial_semantic_candidates(
            resolved_keyframes,
            analysis_profile=analysis_profile,
            bio_data=bio_data,
        )
        if partial_candidates:
            _append_flag(resolved_keyframes, "semantic_keyframes_unreliable_fallback_to_sampled_frames")
            partial_candidate_kind = _partial_semantic_candidate_kind(partial_candidates)
            try:
                partial_semantic_frames, partial_semantic_records = await extract_precise_frames_at_timestamps(
                    video_path,
                    semantic_frames_dir,
                    partial_candidates,
                    prefix="partial_semantic",
                )
                resolved_keyframes["partial_selected"] = partial_semantic_records
                if partial_candidate_kind == "profile":
                    _append_flag(resolved_keyframes, "semantic_keyframes_partial_profile_frames_available")
                elif partial_candidate_kind == "mismatch_action":
                    _append_flag(resolved_keyframes, "semantic_keyframes_partial_mismatch_action_frames_available")
                else:
                    _append_flag(resolved_keyframes, "semantic_keyframes_partial_core_frames_available")
                    low_confidence_visual_promotion = _low_confidence_jump_partial_can_be_promoted(
                        resolved_keyframes,
                        partial_candidates,
                        analysis_profile=analysis_profile,
                    )
                    tracker_final_loss_visual_promotion = _tracker_final_loss_jump_partial_can_be_promoted(
                        resolved_keyframes,
                        partial_candidates,
                        analysis_profile=analysis_profile,
                        bio_data=bio_data,
                    )
                    phase_range_visual_promotion = _phase_range_motion_fallback_jump_partial_can_be_promoted(
                        resolved_keyframes,
                        partial_candidates,
                        analysis_profile=analysis_profile,
                        bio_data=bio_data,
                    )
                    weak_skeleton_cluster_visual_promotion_support = (
                        _weak_skeleton_cluster_video_partial_support(
                            resolved_keyframes,
                            partial_candidates,
                            analysis_profile=analysis_profile,
                            bio_data=bio_data,
                        )
                    )
                    weak_skeleton_cluster_visual_promotion = (
                        weak_skeleton_cluster_visual_promotion_support is not None
                    )
                    retry_tail_motion_aligned_visual_promotion_support = (
                        _retry_tail_motion_aligned_jump_partial_promotion_support(
                            resolved_keyframes,
                            partial_candidates,
                            motion_scores,
                            analysis_profile=analysis_profile,
                            bio_data=bio_data,
                        )
                    )
                    retry_tail_motion_aligned_visual_promotion = (
                        retry_tail_motion_aligned_visual_promotion_support is not None
                    )
                    if (
                        _has_rejected_late_pose_core_candidate_conflict(resolved_keyframes)
                        and any(
                            str(item.get("selection_reason") or "").startswith("video_phase_range_")
                            for item in partial_candidates
                            if isinstance(item, dict)
                        )
                        and not weak_skeleton_cluster_visual_promotion
                    ):
                        _append_flag(
                            resolved_keyframes,
                            "semantic_keyframes_phase_range_visual_promotion_blocked_late_pose_core_conflict",
                        )
                    phase_range_like_visual_promotion = (
                        phase_range_visual_promotion
                        or retry_tail_motion_aligned_visual_promotion
                        or weak_skeleton_cluster_visual_promotion
                    )
                    distant_full_context_visual_promotion = (
                        _distant_full_context_visual_jump_partial_can_be_promoted(
                            resolved_keyframes,
                            partial_candidates,
                            analysis_profile=analysis_profile,
                            bio_data=bio_data,
                            video_duration_sec=resolver_duration,
                        )
                    )
                    long_unresolved_motion_fallback_partial_promotion = (
                        _long_unresolved_motion_fallback_jump_partial_can_be_promoted(
                            resolved_keyframes,
                            partial_candidates,
                            analysis_profile=analysis_profile,
                            bio_data=bio_data,
                        )
                    )
                    if (
                        low_confidence_visual_promotion
                        or tracker_final_loss_visual_promotion
                        or phase_range_like_visual_promotion
                        or distant_full_context_visual_promotion
                        or long_unresolved_motion_fallback_partial_promotion
                    ):
                        promoted_records = _semantic_records_from_promoted_partials(partial_semantic_records)
                        promoted_resolved = _promoted_partial_resolved_keyframes(
                            resolved_keyframes,
                            promoted_records,
                            promotion_reason=(
                                "video_temporal_low_confidence_visual_tal_promoted"
                                if low_confidence_visual_promotion
                                else (
                                    "video_temporal_tracker_final_loss_visual_tal_promoted"
                                    if tracker_final_loss_visual_promotion
                                    else (
                                        "video_temporal_phase_range_visual_tal_promoted"
                                        if phase_range_like_visual_promotion
                                        else (
                                            "video_temporal_distant_full_context_visual_tal_promoted"
                                            if distant_full_context_visual_promotion
                                            else "video_temporal_long_unresolved_motion_fallback_partial_tal_promoted"
                                        )
                                    )
                                )
                            ),
                        )
                        if tracker_final_loss_visual_promotion and not low_confidence_visual_promotion:
                            _append_flag(promoted_resolved, "semantic_keyframes_tracker_final_loss_visual_tal_promoted")
                            _remove_flags(
                                promoted_resolved,
                                "video_temporal_resolver_advisory_low_confidence_overridden",
                                "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                                "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                                "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
                                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                            )
                            _mark_low_visibility_bounded_motion_fallback_drift_ignored_after_visual_promotion(promoted_resolved)
                            promoted_resolved["semantic_tracker_final_loss_visual_promotion"] = {
                                "decision": "promoted_visible_video_tal_over_low_visibility_motion_fallback",
                                "candidate_quality_flags": _keyframe_candidate_quality_flags(bio_data),
                            }
                        if phase_range_like_visual_promotion and not low_confidence_visual_promotion and not tracker_final_loss_visual_promotion:
                            _append_flag(promoted_resolved, "semantic_keyframes_phase_range_visual_tal_promoted")
                            if retry_tail_motion_aligned_visual_promotion:
                                _append_flag(
                                    promoted_resolved,
                                    "semantic_keyframes_retry_tail_motion_aligned_visual_tal_promoted",
                                )
                            _remove_flags(
                                promoted_resolved,
                                "semantic_keyframes_unreliable_after_refinement",
                                "semantic_keyframes_unreliable_candidate_tal_conflict",
                                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                                "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                                "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                                "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
                                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                                "semantic_keyframes_phase_range_visual_promotion_blocked_late_pose_core_conflict",
                                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                                "video_temporal_resolver_coherent_tal_retry_tail_motion_conflict",
                                "video_temporal_resolver_coherent_tal_late_motion_conflict",
                                "video_temporal_quality_retry_motion_cluster_conflict",
                                "video_temporal_quality_retry_skeleton_tal_conflict",
                                "semantic_keyframes_unreliable_after_retry_rejection",
                            )
                            promoted_resolved.pop("semantic_motion_cluster_conflict", None)
                            promoted_resolved.pop("semantic_skeleton_tal_conflicts", None)
                            promoted_resolved.pop("semantic_skeleton_tal_conflict_decision", None)
                            promoted_resolved.pop("semantic_skeleton_tal_conflict_candidate_quality_flags", None)
                            _mark_low_visibility_bounded_motion_fallback_drift_ignored_after_visual_promotion(promoted_resolved)
                            low_visibility_keys = sorted(_low_visibility_motion_fallback_candidate_keys(bio_data))
                            takeoff_anchor_low_visibility_boundary_context = (
                                _takeoff_anchor_low_visibility_boundary_candidate_context(bio_data)
                            )
                            promoted_resolved["semantic_phase_range_visual_promotion"] = {
                                "decision": (
                                    "promoted_retry_tail_motion_aligned_video_tal_over_weak_temporal_geometry_candidate"
                                    if retry_tail_motion_aligned_visual_promotion
                                    else (
                                        "promoted_video_tal_over_weak_skeleton_cluster"
                                        if weak_skeleton_cluster_visual_promotion
                                        else (
                                            "promoted_video_phase_range_tal_over_low_visibility_motion_fallback"
                                            if low_visibility_keys
                                            else "promoted_video_phase_range_tal_over_weak_temporal_geometry_candidate"
                                        )
                                    )
                                ),
                                "candidate_quality_flags": _keyframe_candidate_quality_flags(bio_data),
                                "low_visibility_motion_fallback_keys": low_visibility_keys,
                                "promotion_context": (
                                    "retry_tail_motion_aligned_weak_temporal_geometry_candidate"
                                    if retry_tail_motion_aligned_visual_promotion
                                    else (
                                        "weak_skeleton_cluster"
                                        if weak_skeleton_cluster_visual_promotion
                                        else (
                                            "takeoff_anchor_low_visibility_boundary"
                                            if takeoff_anchor_low_visibility_boundary_context
                                            else (
                                                "low_visibility_motion_fallback"
                                                if low_visibility_keys
                                                else "weak_temporal_geometry_candidate"
                                            )
                                        )
                                    )
                                ),
                            }
                            if weak_skeleton_cluster_visual_promotion:
                                _append_flag(
                                    promoted_resolved,
                                    "semantic_keyframes_weak_skeleton_cluster_visual_tal_promoted",
                                )
                                _append_flag(
                                    promoted_resolved,
                                    "video_temporal_resolver_weak_skeleton_cluster_visual_tal_promoted",
                                )
                                promoted_resolved["semantic_phase_range_visual_promotion"][
                                    "weak_skeleton_cluster_support"
                                ] = weak_skeleton_cluster_visual_promotion_support
                                _mark_late_pose_core_conflict_ignored_after_weak_cluster_visual_promotion(
                                    promoted_resolved,
                                    weak_skeleton_cluster_visual_promotion_support,
                                )
                            if retry_tail_motion_aligned_visual_promotion:
                                promoted_resolved["semantic_phase_range_visual_promotion"][
                                    "retry_tail_motion_aligned_support"
                                ] = retry_tail_motion_aligned_visual_promotion_support
                        if (
                            distant_full_context_visual_promotion
                            and not low_confidence_visual_promotion
                            and not tracker_final_loss_visual_promotion
                            and not phase_range_like_visual_promotion
                        ):
                            _append_flag(promoted_resolved, "semantic_keyframes_distant_full_context_visual_tal_promoted")
                            _remove_flags(
                                promoted_resolved,
                                "semantic_keyframes_unreliable_after_refinement",
                                "semantic_keyframes_unreliable_candidate_tal_conflict",
                                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                                "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                                "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                                "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
                                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                            )
                            _mark_low_visibility_bounded_motion_fallback_drift_ignored_after_visual_promotion(promoted_resolved)
                            promoted_resolved["semantic_distant_full_context_visual_promotion"] = {
                                "decision": (
                                    "promoted_distant_full_context_video_tal_over_compressed_low_visibility_motion_fallback"
                                    if _low_visibility_motion_fallback_candidate_keys(bio_data)
                                    else "promoted_distant_full_context_video_tal_over_weak_geometry_candidate"
                                ),
                                "candidate_quality_flags": _keyframe_candidate_quality_flags(bio_data),
                                "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
                                "video_duration_sec": round(resolver_duration, 3),
                                "low_visibility_motion_fallback_keys": sorted(_low_visibility_motion_fallback_candidate_keys(bio_data)),
                                "promotion_context": (
                                    "low_visibility_motion_fallback"
                                    if _low_visibility_motion_fallback_candidate_keys(bio_data)
                                    else "weak_geometry_candidate"
                                ),
                            }
                        if (
                            long_unresolved_motion_fallback_partial_promotion
                            and not low_confidence_visual_promotion
                            and not tracker_final_loss_visual_promotion
                            and not phase_range_like_visual_promotion
                            and not distant_full_context_visual_promotion
                        ):
                            promoted_resolved = promote_long_unresolved_motion_fallback_partials(
                                promoted_resolved,
                                promoted_records,
                                bio_data=bio_data,
                                analysis_profile=analysis_profile,
                            ) or promoted_resolved
                            _append_flag(
                                promoted_resolved,
                                "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted",
                            )
                            _remove_flags(
                                promoted_resolved,
                                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                                "semantic_keyframes_unreliable_after_refinement",
                                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                                "video_temporal_quality_retry_motion_cluster_conflict",
                            )
                            promoted_resolved.setdefault(
                                "semantic_long_unresolved_motion_fallback_partial_promotion",
                                {
                                    "decision": "promoted_partial_video_tal_over_long_unresolved_motion_fallback",
                                    "candidate_quality_flags": _keyframe_candidate_quality_flags(bio_data),
                                    "candidate_tal_span_sec": _candidate_tal_span_sec(bio_data),
                                },
                            )
                        promoted_selected = (
                            promoted_resolved.get("selected")
                            if isinstance(promoted_resolved.get("selected"), list)
                            else promoted_records
                        )
                        promoted_paths = [semantic_frames_dir / f"{record['frame_id']}.jpg" for record in promoted_selected]
                        for source_path, target_path in zip(partial_semantic_frames, promoted_paths):
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source_path, target_path)
                        skip_visibility_gate = (
                            long_unresolved_motion_fallback_partial_promotion
                            and not low_confidence_visual_promotion
                            and not tracker_final_loss_visual_promotion
                            and not phase_range_like_visual_promotion
                            and not distant_full_context_visual_promotion
                        )
                        if skip_visibility_gate:
                            inspected_records = [dict(item) for item in promoted_selected]
                            visibility_flags: list[str] = []
                            promoted_resolved["selected"] = inspected_records
                        else:
                            inspected_records, visibility_flags = _semantic_frame_visibility_flags(
                                promoted_paths,
                                promoted_selected,
                                include_zoomed_small_targets=True,
                                require_visible_target=True,
                            )
                            if visibility_flags:
                                promoted_paths, inspected_records, repair_flags = await _repair_low_confidence_promoted_visual_frames(
                                    video_path=video_path,
                                    work_dir=work_dir,
                                    frame_paths=promoted_paths,
                                    records=inspected_records,
                                    source_fps=sampling_metadata.source_fps,
                                    duration_sec=resolver_duration,
                                )
                                for flag in repair_flags:
                                    _append_flag(promoted_resolved, flag)
                                if repair_flags:
                                    inspected_records, visibility_flags = _semantic_frame_visibility_flags(
                                        promoted_paths,
                                        inspected_records,
                                        include_zoomed_small_targets=True,
                                        require_visible_target=True,
                                    )
                            for flag in visibility_flags:
                                _append_flag(promoted_resolved, flag)
                            promoted_resolved["selected"] = inspected_records
                        if (
                            tracker_final_loss_visual_promotion
                            and not low_confidence_visual_promotion
                            and "semantic_keyframes_unreliable_after_visibility_check" in set(visibility_flags)
                            and _tracker_final_loss_visual_promotion_visibility_passed(inspected_records)
                        ):
                            _remove_flags(promoted_resolved, "semantic_keyframes_unreliable_after_visibility_check")
                            _append_flag(promoted_resolved, "semantic_keyframes_tracker_final_loss_visual_tal_partial_visibility")
                            promoted_resolved["semantic_tracker_final_loss_visual_promotion"]["visibility_decision"] = (
                                "accepted_takeoff_or_landing_visible_with_small_target_core"
                            )
                            promoted_resolved["selected"] = inspected_records
                        if semantic_keyframes_are_reliable(promoted_resolved):
                            resolved_keyframes = promoted_resolved
                            semantic_frames = promoted_paths
                            semantic_records = [
                                dict(item) if isinstance(item, dict) else item
                                for item in promoted_resolved.get("selected", [])
                            ]
                            used_semantic_frames = True
                            partial_semantic_frames = []
                            partial_semantic_records = []
                            resolved_keyframes.pop("partial_selected", None)
            except Exception:  # noqa: BLE001
                if partial_candidate_kind == "profile":
                    _append_flag(resolved_keyframes, "semantic_keyframes_partial_profile_frame_extract_failed")
                elif partial_candidate_kind == "mismatch_action":
                    _append_flag(resolved_keyframes, "semantic_keyframes_partial_mismatch_action_frame_extract_failed")
                else:
                    _append_flag(resolved_keyframes, "semantic_keyframes_partial_core_frame_extract_failed")
                partial_semantic_frames = []
                partial_semantic_records = []

    if not used_semantic_frames:
        _apply_unreliable_semantic_selected_fallback(
            resolved_keyframes,
            bio_data,
            analysis_profile=analysis_profile,
        )

    return SemanticKeyframePipelineResult(
        ai_clip=ai_clip,
        video_temporal=video_temporal,
        resolved_keyframes=resolved_keyframes,
        effective_source=effective_timestamp_source(resolved_keyframes, used_semantic_frames),
        semantic_frames=semantic_frames,
        semantic_records=semantic_records,
        partial_semantic_frames=partial_semantic_frames,
        partial_semantic_records=partial_semantic_records,
        refinement_flags=refinement_flags,
        quality_flags=_merge_flags(video_temporal, resolved_keyframes),
        used_semantic_frames=used_semantic_frames,
        has_semantic_moments=has_semantic_moments,
    )


async def retry_video_temporal_if_needed(
    *,
    result: SemanticKeyframePipelineResult,
    video_path: Path,
    work_dir: Path,
    semantic_frames_dir: Path,
    sampling_metadata: VideoSamplingMetadata,
    action_type: str,
    action_subtype: str | None,
    motion_scores: dict[str, object] | None,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None = None,
    user_note: str | None = None,
    analyzed_video_kind: str = "action_window_ai",
    input_window: VideoInputWindow | None = None,
    progress_callback: SemanticPipelineProgressCallback | None = None,
) -> SemanticKeyframePipelineResult:
    video_temporal = result.video_temporal
    if not _should_retry_video_temporal(
        video_temporal,
        result.resolved_keyframes,
        used_semantic_frames=result.used_semantic_frames,
        analysis_profile=analysis_profile,
        motion_scores=motion_scores,
        bio_data=bio_data,
    ):
        return result

    retry_context = _video_temporal_retry_context(
        video_temporal=video_temporal,
        resolved_keyframes=result.resolved_keyframes,
        motion_scores=motion_scores,
        sampling_metadata=sampling_metadata,
        analysis_profile=analysis_profile,
        used_semantic_frames=result.used_semantic_frames,
        bio_data=bio_data,
    )
    if progress_callback is not None:
        await progress_callback(
            "video_temporal_retry",
            {
                "quality_flags": _merge_flags(result.quality_flags, ["video_temporal_quality_retry_started"]),
                "retry_context": retry_context,
            },
        )
    retry_handle = await start_video_temporal_task(
        video_path=video_path,
        work_dir=work_dir,
        sampling_metadata=sampling_metadata,
        action_type=action_type,
        action_subtype=action_subtype,
        user_note=user_note,
        analyzed_video_kind=f"{analyzed_video_kind}_retry",
        input_window=input_window,
        retry_context=retry_context,
        precheck=False,
    )
    retry_video_temporal = await retry_handle.task
    if isinstance(retry_video_temporal, dict):
        _append_flag(retry_video_temporal, "video_temporal_quality_retry")
    retry_semantic_frames_dir = _isolated_semantic_frames_dir(semantic_frames_dir, "retry")
    shutil.rmtree(retry_semantic_frames_dir, ignore_errors=True)
    retry_result = await resolve_semantic_keyframe_pipeline(
        video_path=video_path,
        work_dir=work_dir,
        semantic_frames_dir=retry_semantic_frames_dir,
        video_temporal=retry_video_temporal,
        motion_scores=motion_scores,
        sampling_metadata=sampling_metadata,
        analysis_profile=analysis_profile,
        bio_data=bio_data,
        video_duration_sec=retry_handle.source_duration_sec,
        ai_clip=retry_handle.ai_clip_payload(),
    )
    original_score = _semantic_result_quality_score(result)
    retry_score = _semantic_result_quality_score(retry_result)
    retry_rejection_flags = _retry_replacement_rejection_flags(
        result,
        retry_result,
        motion_scores,
        bio_data=bio_data,
        analysis_profile=analysis_profile,
    )
    retry_resolves_motion_conflict = _retry_resolves_near_candidate_motion_conflict(result, retry_result)
    should_use_retry = retry_result.used_semantic_frames and not retry_rejection_flags and (
        not result.used_semantic_frames or retry_score > original_score
        or (retry_score >= original_score and retry_resolves_motion_conflict)
    )
    if should_use_retry:
        try:
            retry_result = _promote_semantic_result_artifacts(retry_result, semantic_frames_dir)
        except Exception:  # noqa: BLE001
            retry_rejection_flags = _merge_flags(
                retry_rejection_flags,
                ["video_temporal_quality_retry_artifact_promotion_failed"],
            )
            should_use_retry = False
    if should_use_retry:
        _append_flag(retry_result.resolved_keyframes, "video_temporal_quality_retry_used")
        retry_result.resolved_keyframes["video_temporal_quality_retry_scores"] = {
            "original": original_score,
            "retry": retry_score,
        }
        retry_result.quality_flags = _merge_flags(retry_result.video_temporal, retry_result.resolved_keyframes)
        shutil.rmtree(retry_semantic_frames_dir, ignore_errors=True)
        if progress_callback is not None:
            await progress_callback(
                "video_temporal_retry_used",
                {
                    "video_ai_confidence": retry_video_temporal.get("confidence") if isinstance(retry_video_temporal, dict) else None,
                    "quality_flags": retry_result.quality_flags,
                },
        )
        return retry_result

    partial_merge_result = await _maybe_apply_retry_takeoff_partial_merge(
        original=result,
        retry=retry_result,
        video_path=video_path,
        work_dir=work_dir,
        semantic_frames_dir=semantic_frames_dir,
        sampling_metadata=sampling_metadata,
    )
    if partial_merge_result is not result:
        partial_merge_result.resolved_keyframes["video_temporal_quality_retry_scores"] = {
            "original": original_score,
            "retry": retry_score,
        }
        if isinstance(partial_merge_result.video_temporal, dict):
            partial_merge_result.video_temporal["retry_attempt"] = retry_video_temporal
        shutil.rmtree(retry_semantic_frames_dir, ignore_errors=True)
        return partial_merge_result

    fallback_result = await _maybe_apply_motion_cluster_fallback_after_retry_rejection(
        original=result,
        retry_rejection_flags=retry_rejection_flags,
        video_path=video_path,
        work_dir=work_dir,
        semantic_frames_dir=semantic_frames_dir,
        motion_scores=motion_scores,
        sampling_metadata=sampling_metadata,
        analysis_profile=analysis_profile,
        bio_data=bio_data,
        video_duration_sec=retry_handle.source_duration_sec,
    )
    if fallback_result is not result:
        fallback_result.resolved_keyframes["video_temporal_quality_retry_scores"] = {
            "original": original_score,
            "retry": retry_score,
        }
        if isinstance(fallback_result.video_temporal, dict):
            fallback_result.video_temporal["retry_attempt"] = retry_video_temporal
        fallback_result.quality_flags = _merge_flags(fallback_result.video_temporal, fallback_result.resolved_keyframes)
        shutil.rmtree(retry_semantic_frames_dir, ignore_errors=True)
        return fallback_result

    motion_aligned_candidate_result = await _maybe_apply_motion_aligned_candidate_fallback_after_retry_rejection(
        original=result,
        retry_result=retry_result,
        retry_rejection_flags=retry_rejection_flags,
        video_path=video_path,
        semantic_frames_dir=semantic_frames_dir,
        motion_scores=motion_scores,
        analysis_profile=analysis_profile,
        bio_data=bio_data,
        video_duration_sec=retry_handle.source_duration_sec,
    )
    if motion_aligned_candidate_result is not result:
        motion_aligned_candidate_result.resolved_keyframes["video_temporal_quality_retry_scores"] = {
            "original": original_score,
            "retry": retry_score,
        }
        if isinstance(motion_aligned_candidate_result.video_temporal, dict):
            motion_aligned_candidate_result.video_temporal["retry_attempt"] = retry_video_temporal
        motion_aligned_candidate_result.quality_flags = _merge_flags(
            motion_aligned_candidate_result.video_temporal,
            motion_aligned_candidate_result.resolved_keyframes,
        )
        shutil.rmtree(retry_semantic_frames_dir, ignore_errors=True)
        return motion_aligned_candidate_result

    for flag in retry_rejection_flags:
        _append_flag(result.resolved_keyframes, flag)
    retry_quality_flags = _quality_flags(retry_result.video_temporal, retry_result.resolved_keyframes)
    retry_rejection_diagnostic_flags = [
        flag
        for flag in retry_quality_flags
        if flag.startswith(
            (
                "video_temporal_quality_retry_",
                "video_temporal_resolver_",
                "semantic_keyframe_",
                "semantic_keyframes_",
            )
        )
    ]
    retry_rejection_diagnostic_flags = _merge_flags(retry_rejection_diagnostic_flags, retry_rejection_flags)
    _append_flag(result.resolved_keyframes, "video_temporal_quality_retry_rejected")
    result.resolved_keyframes["video_temporal_quality_retry_scores"] = {
        "original": original_score,
        "retry": retry_score,
    }
    if retry_rejection_diagnostic_flags:
        result.resolved_keyframes["video_temporal_quality_retry_rejection_flags"] = retry_rejection_diagnostic_flags
    if (
        result.used_semantic_frames
        and not semantic_keyframes_are_reliable(result.resolved_keyframes)
        and not _accepted_visual_promotion_survives_retry_rejection(result)
    ):
        _append_flag(result.resolved_keyframes, "semantic_keyframes_unreliable_after_retry_rejection")
        _apply_unreliable_semantic_selected_fallback(
            result.resolved_keyframes,
            bio_data,
            analysis_profile=analysis_profile,
        )
        result.used_semantic_frames = False
        result.semantic_frames = []
        result.semantic_records = []
        result.effective_source = effective_timestamp_source(result.resolved_keyframes, False)
    elif result.used_semantic_frames:
        result.effective_source = effective_timestamp_source(result.resolved_keyframes, True)
    result.quality_flags = _merge_flags(result.video_temporal, result.resolved_keyframes)
    if isinstance(result.video_temporal, dict):
        result.video_temporal["retry_attempt"] = retry_video_temporal
    shutil.rmtree(retry_semantic_frames_dir, ignore_errors=True)
    return result


async def run_semantic_keyframe_pipeline(
    *,
    video_path: Path,
    work_dir: Path,
    semantic_frames_dir: Path,
    sampling_metadata: VideoSamplingMetadata,
    action_type: str,
    action_subtype: str | None,
    motion_scores: dict[str, object] | None,
    analysis_profile: str | None,
    bio_data: dict[str, Any] | None = None,
    user_note: str | None = None,
    analyzed_video_kind: str = "action_window_ai",
    input_window: VideoInputWindow | None = None,
    precheck: bool = True,
    progress_callback: SemanticPipelineProgressCallback | None = None,
) -> SemanticKeyframePipelineResult:
    handle = await start_video_temporal_task(
        video_path=video_path,
        work_dir=work_dir,
        sampling_metadata=sampling_metadata,
        action_type=action_type,
        action_subtype=action_subtype,
        user_note=user_note,
        analyzed_video_kind=analyzed_video_kind,
        input_window=input_window,
        precheck=precheck,
    )
    if progress_callback is not None:
        await progress_callback("ai_clip_ready", {"ai_clip": handle.ai_clip_payload()})
    video_temporal = await handle.task
    if progress_callback is not None:
        await progress_callback(
            "video_temporal_received",
            {
                "video_ai_confidence": video_temporal.get("confidence") if isinstance(video_temporal, dict) else None,
                "quality_flags": video_temporal.get("quality_flags") if isinstance(video_temporal, dict) else None,
            },
        )
    result = await resolve_semantic_keyframe_pipeline(
        video_path=video_path,
        work_dir=work_dir,
        semantic_frames_dir=semantic_frames_dir,
        video_temporal=video_temporal,
        motion_scores=motion_scores,
        sampling_metadata=sampling_metadata,
        analysis_profile=analysis_profile,
        bio_data=bio_data,
        video_duration_sec=handle.source_duration_sec,
        ai_clip=handle.ai_clip_payload(),
    )
    result = await retry_video_temporal_if_needed(
        result=result,
        video_path=video_path,
        work_dir=work_dir,
        semantic_frames_dir=semantic_frames_dir,
        sampling_metadata=sampling_metadata,
        action_type=action_type,
        action_subtype=action_subtype,
        motion_scores=motion_scores,
        analysis_profile=analysis_profile,
        bio_data=bio_data,
        user_note=user_note,
        analyzed_video_kind=analyzed_video_kind,
        input_window=input_window,
        progress_callback=progress_callback,
    )
    if progress_callback is not None:
        await progress_callback(
            "semantic_frames_resolved",
            {
                "resolved_source": result.resolved_keyframes.get("source") if isinstance(result.resolved_keyframes, dict) else None,
                "resolved_confidence": result.resolved_keyframes.get("confidence") if isinstance(result.resolved_keyframes, dict) else None,
                "semantic_frame_count": len(result.semantic_frames),
                "used_semantic_frames": result.used_semantic_frames,
                "quality_flags": result.quality_flags,
            },
        )
    return result
