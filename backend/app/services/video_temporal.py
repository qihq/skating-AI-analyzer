from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analysis_errors import AnalysisErrorCode, classify_ai_failure
from app.services.providers import (
    ActiveProviderConfig,
    DEFAULT_MIMO_VISION_MODEL,
    get_active_provider,
    request_dashscope_video_completion,
    request_mimo_video_completion,
)


SCHEMA_VERSION = "video_temporal_v1"
DEFAULT_MODEL = "qwen3.6-plus"
VIDEO_TEMPORAL_TEMPERATURE = 0.0
VIDEO_TEMPORAL_MAX_TOKENS = 3200
VIDEO_TEMPORAL_TIMEOUT_SECONDS = 180.0
RAW_RESPONSE_EXCERPT_LIMIT = 2000
RETRY_CONTEXT_JSON_LIMIT = 1800
VALID_FALLBACK_RECOMMENDATIONS = {
    "use_video_timestamps",
    "use_skeleton_fallback",
    "use_sampled_frames",
    "use_existing_skeleton_timestamps",
    "manual_review",
}
VALID_DATA_QUALITY_HINTS = {"good", "partial", "poor"}

JUMP_PHASE_CODES = {"approach", "preparation", "takeoff", "air", "landing", "glide_out"}
SPIN_PHASE_CODES = {"spin_entry", "spin_main", "spin_exit"}
STEP_PHASE_CODES = {"step_sequence"}
SPIRAL_PHASE_CODES = {"spiral_entry", "spiral_hold", "spiral_exit"}
ALL_PHASE_CODES = JUMP_PHASE_CODES | SPIN_PHASE_CODES | STEP_PHASE_CODES | SPIRAL_PHASE_CODES

PHASE_LABELS = {
    "approach": "助滑",
    "preparation": "准备",
    "takeoff": "起跳",
    "air": "腾空",
    "landing": "落冰",
    "glide_out": "滑出",
    "spin_entry": "入转",
    "spin_main": "旋转中",
    "spin_exit": "出转",
    "step_sequence": "步法",
    "spiral_entry": "螺旋线进入",
    "spiral_hold": "螺旋线保持",
    "spiral_exit": "螺旋线退出",
}

PHASE_ALIASES = {
    "approach": "approach",
    "entry": "approach",
    "助滑": "approach",
    "进入": "approach",
    "preparation": "preparation",
    "prep": "preparation",
    "准备": "preparation",
    "takeoff": "takeoff",
    "take_off": "takeoff",
    "t": "takeoff",
    "起跳": "takeoff",
    "离冰": "takeoff",
    "air": "air",
    "flight": "air",
    "apex": "air",
    "a": "air",
    "腾空": "air",
    "空中": "air",
    "landing": "landing",
    "l": "landing",
    "落冰": "landing",
    "触冰": "landing",
    "glide_out": "glide_out",
    "exit": "glide_out",
    "滑出": "glide_out",
    "spin_entry": "spin_entry",
    "旋转入": "spin_entry",
    "入转": "spin_entry",
    "spin_main": "spin_main",
    "spin": "spin_main",
    "旋转中": "spin_main",
    "旋转": "spin_main",
    "spin_exit": "spin_exit",
    "旋转出": "spin_exit",
    "出转": "spin_exit",
    "step_sequence": "step_sequence",
    "step": "step_sequence",
    "steps": "step_sequence",
    "步法": "step_sequence",
    "步法序列": "step_sequence",
    "spiral_entry": "spiral_entry",
    "螺旋线进入": "spiral_entry",
    "spiral_hold": "spiral_hold",
    "spiral": "spiral_hold",
    "螺旋线": "spiral_hold",
    "燕式": "spiral_hold",
    "spiral_exit": "spiral_exit",
    "螺旋线退出": "spiral_exit",
}

ACTION_FAMILIES = {"jump", "spin", "step", "spiral", "unknown"}
CAMERA_VIEWS = {"front", "side", "diagonal_front", "diagonal_back", "rear", "unknown"}
KEY_MOMENT_KEYS = ("T_takeoff_sec", "A_air_sec", "L_landing_sec")
PHASE_KEY_MOMENTS = {
    "takeoff": "T_takeoff_sec",
    "air": "A_air_sec",
    "landing": "L_landing_sec",
}
SPIN_RESOLVER_PHASES = ("spin_entry", "spin_main", "spin_exit")
SPIRAL_RESOLVER_PHASES = ("spiral_entry", "spiral_hold", "spiral_exit")
STEP_SEQUENCE_MIN_MULTI_FRAME_SECONDS = 1.2
STEP_SEQUENCE_COVERAGE_POINTS = (
    ("step_entry", 0.18),
    ("step_mid", 0.50),
    ("step_exit", 0.82),
)
INFERRED_TAIL_PHASE_DURATION_GUARD_SECONDS = 0.08
MAX_RESOLVED_KEYFRAMES = 12
SKELETON_ANCHOR_CONFIDENCE = 0.65
SKELETON_FALLBACK_CONFIDENCE = 0.65
SKELETON_OCCLUSION_ANCHOR_CONFIDENCE = 0.75
SKELETON_OCCLUSION_PHASE_EDGE_TOLERANCE_SECONDS = 0.45
MOTION_SNAP_TOLERANCE_SECONDS = 0.18
FALLBACK_MOTION_WINDOW_SECONDS = 0.30
MOTION_PEAK_PHASES = {"takeoff", "landing"}
SEMANTIC_ORDER_MIN_GAP_SECONDS = 0.02
JUMP_COHERENT_TAL_CONFIDENCE = 0.60
JUMP_COHERENT_TAL_RETRY_CONFIDENCE_FLOOR = 0.50
JUMP_COHERENT_TAL_PHASE_CONFIDENCE = 0.50
JUMP_COHERENT_TAL_RETRY_PHASE_CONFIDENCE = 0.60
JUMP_COHERENT_TAL_RETRY_WEAK_GEOMETRY_PHASE_CONFIDENCE = 0.30
JUMP_COHERENT_TAL_RETRY_WEAK_PHASE_MIN_SPAN_SECONDS = 0.45
JUMP_COHERENT_TAL_RETRY_WEAK_PHASE_MAX_SPAN_SECONDS = 1.50
JUMP_CORE_PHASE_CODES = ("takeoff", "air", "landing")
JUMP_COHERENT_TAL_COMPRESSED_SECONDS = 0.85
JUMP_COHERENT_TAL_EARLY_COMPRESSED_SECONDS = 0.55
JUMP_COHERENT_TAL_EARLY_STRONG_MOTION_LEAD_SECONDS = 0.70
JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING = 0.80
JUMP_COHERENT_TAL_LATE_MOTION_CONFLICT_CONFIDENCE_CEILING = 0.90
JUMP_COHERENT_TAL_MOTION_CONFLICT_LAG_SECONDS = 0.35
JUMP_COHERENT_TAL_MOTION_CONFLICT_LOOKAHEAD_SECONDS = 1.45
JUMP_COHERENT_TAL_MOTION_CONFLICT_SCORE_RATIO = 3.0
JUMP_COHERENT_TAL_MOTION_CONFLICT_MIN_SCORE = 0.12
JUMP_COHERENT_TAL_PHASE_MOTION_SUPPORT_MIN_SCORE = 0.09
JUMP_COHERENT_TAL_LANDING_MOTION_SUPPORT_MIN_SCORE = 0.11
JUMP_COHERENT_TAL_PHASE_MOTION_SUPPORT_RATIO = 0.45
JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS = 0.45
JUMP_COHERENT_TAL_GLIDE_TAIL_MIN_DURATION_SECONDS = 4.0
JUMP_COHERENT_TAL_LANDING_TAIL_TOLERANCE_SECONDS = 0.12
JUMP_COHERENT_TAL_TAKEOFF_BEFORE_MOTION_TOLERANCE_SECONDS = 0.35
JUMP_COHERENT_TAL_GLIDE_OUT_BOUNDARY_TOLERANCE_SECONDS = 0.15
JUMP_COHERENT_TAL_RETRY_CONFIDENCE = 0.80
JUMP_COHERENT_TAL_FALLBACK_GLIDE_OUT_CONFIDENCE = 0.85
JUMP_COHERENT_TAL_TIMESTAMP_GLIDE_OUT_CONFIDENCE = 0.60
JUMP_COHERENT_TAL_SMALL_TARGET_GLIDE_OUT_CONFIDENCE = 0.60
JUMP_COHERENT_TAL_OCCLUSION_GLIDE_OUT_CONFIDENCE = 0.80
JUMP_COHERENT_TAL_RETRY_TAIL_CONFIDENCE_CEILING = 0.75
JUMP_COHERENT_TAL_RETRY_WEAK_PHASE_CONFIDENCE = 0.60
JUMP_COHERENT_TAL_RETRY_TAIL_TAKEOFF_LEAD_SECONDS = 0.25
JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_TAKEOFF_LEAD_SECONDS = 0.55
JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS = 0.30
JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_LANDING_TOLERANCE_SECONDS = 0.18
JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_PEAK_LAG_SECONDS = 0.20
JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_SPAN_SECONDS = 0.25
JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_STRONG_RECORDS = 3
JUMP_COHERENT_TAL_SKELETON_CONFLICT_CONFIDENCE = 0.60
JUMP_COHERENT_TAL_FALLBACK_SKELETON_CONFLICT_CONFIDENCE = 0.50
JUMP_COHERENT_TAL_SKELETON_CONFLICT_MIN_SHIFT_SECONDS = 1.0
JUMP_COHERENT_TAL_NEAR_SKELETON_CANDIDATE_MAX_DELTA_SECONDS = 0.12
JUMP_COHERENT_TAL_NEAR_SKELETON_CANDIDATE_AVG_CONFIDENCE = 0.50
JUMP_COHERENT_TAL_NEAR_SKELETON_CANDIDATE_STRONG_CONFIDENCE = 0.62
JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_TAKEOFF_TOLERANCE_SECONDS = 0.08
JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_APEX_LEAD_SECONDS = 0.20
JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_LANDING_DRIFT_SECONDS = 0.18
JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_LOOKAHEAD_SECONDS = 0.55
JUMP_COHERENT_TAL_MIXED_CLUSTER_TAKEOFF_LEAD_SECONDS = 0.70
JUMP_COHERENT_TAL_MIXED_CLUSTER_LANDING_DRIFT_SECONDS = 0.45
JUMP_COHERENT_TAL_MIXED_CLUSTER_LOOKAHEAD_SECONDS = 0.80
JUMP_COHERENT_TAL_LANDING_BOUNDARY_TOLERANCE_SECONDS = 0.08
JUMP_COHERENT_TAL_PREP_MOTION_BOUNDARY_TOLERANCE_SECONDS = 0.18
JUMP_COHERENT_TAL_GLIDE_OUT_TAIL_TOLERANCE_SECONDS = 0.05
JUMP_INFERRED_PREPARATION_MAX_SECONDS = 0.70
JUMP_INFERRED_PREPARATION_MIN_APPROACH_SECONDS = 0.80
JUMP_INFERRED_PREPARATION_BOUNDARY_TOLERANCE_SECONDS = 0.12
JUMP_TAKEOFF_REFINEMENT_MAX_DELTA_SECONDS = 0.20
JUMP_LANDING_REFINEMENT_TOLERANCE_SECONDS = 0.22
JUMP_MOTION_CLUSTER_FALLBACK_CONFIDENCE = 0.66
JUMP_MOTION_CLUSTER_FALLBACK_MIN_SCORE = 0.16
JUMP_MOTION_CLUSTER_FALLBACK_SCORE_RATIO = 0.65
JUMP_MOTION_CLUSTER_FALLBACK_MIN_RECORDS = 4
JUMP_MOTION_CLUSTER_FALLBACK_MIN_SPAN_SECONDS = 0.25
JUMP_MOTION_CLUSTER_FALLBACK_MAX_GAP_SECONDS = 0.22
JUMP_MOTION_CLUSTER_FALLBACK_TAKEOFF_LEAD_SECONDS = 0.25
JUMP_MOTION_CLUSTER_FALLBACK_APEX_MIN_CONFIDENCE = 0.50
JUMP_MOTION_CLUSTER_FALLBACK_LANDING_MIN_GAP_SECONDS = 0.05
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_MIN_SCORE = 0.09
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_MAX_GAP_SECONDS = 0.28
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_TAIL_MIN_SCORE = 0.045
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_TAIL_SCORE_RATIO = 0.35
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_SEMANTIC_SHIFT_SECONDS = 0.45
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_CORE_PEAK_RATIO = 0.50
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_LOOKAHEAD_SECONDS = 2.00
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_APEX_TARGET_SECONDS = 0.25
JUMP_WEAK_MOTION_CLUSTER_FALLBACK_LANDING_TARGET_SECONDS = 0.80
JUMP_WEAK_MOTION_CLUSTER_HIGH_CONFIDENCE_MIN_SEMANTIC_SHIFT_SECONDS = 0.45
VIDEO_TEMPORAL_PHASE_END_TAIL_TOLERANCE_SECONDS = 0.05
VIDEO_TEMPORAL_HARD_FAILURE_FLAGS = {
    "video_temporal_invalid_json",
    "video_temporal_parse_failed",
    "video_temporal_payload_not_object",
    "video_temporal_missing_phase_segments",
}
VIDEO_TEMPORAL_UNRESOLVED_TAL_CONFLICT_FLAGS = {
    "video_temporal_quality_retry_skeleton_tal_conflict",
    "video_temporal_quality_retry_motion_cluster_conflict",
}
VIDEO_TEMPORAL_WEAK_TAL_CANDIDATE_GEOMETRY_FLAGS = {
    "tal_candidate_temporal_geometry_unreliable",
    "tal_candidate_takeoff_apex_gap_unreliable",
    "tal_candidate_takeoff_apex_gap_compressed",
    "tal_candidate_apex_landing_gap_unreliable",
    "tal_candidate_apex_landing_gap_compressed",
    "tal_candidate_core_gap_compressed",
}
VIDEO_TEMPORAL_ACCEPTED_TAL_REPAIR_FLAGS = {
    "video_temporal_quality_retry_used",
    "video_temporal_quality_retry_motion_cluster_fallback_used",
    "video_temporal_quality_retry_takeoff_partial_merge_used",
    "video_temporal_resolver_motion_cluster_fallback_used",
    "video_temporal_resolver_weak_motion_cluster_fallback_used",
    "semantic_keyframes_phase_range_visual_tal_promoted",
    "semantic_keyframes_distant_full_context_visual_tal_promoted",
    "semantic_keyframes_tracker_final_loss_visual_tal_promoted",
    "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_candidate_tal_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_candidate_tal_conflict_ignored_main_motion_supported_weak_geometry",
    "semantic_keyframes_reuse_candidate_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_reuse_candidate_conflict_ignored_sparse_track_stitched_candidate",
    "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate",
    "video_temporal_quality_retry_motion_cluster_conflict_ignored_occlusion_contaminated_candidate",
    "video_temporal_quality_retry_motion_cluster_conflict_ignored_weak_temporal_geometry",
    "video_temporal_quality_retry_motion_cluster_conflict_ignored_early_approach_motion_peak",
    "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor",
    "semantic_keyframes_reuse_motion_cluster_conflict_ignored_phase_range_late_reanchor",
    "semantic_keyframes_reuse_motion_cluster_conflict_ignored_sparse_track_stitched_candidate",
}
VIDEO_TEMPORAL_INSUFFICIENT_POSE_LOW_VISIBILITY_ACCEPTED_FLAGS = {
    "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_candidate_tal_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_reuse_candidate_conflict_ignored_insufficient_pose_low_visibility_fallback",
    "semantic_keyframes_reuse_candidate_conflict_ignored_sparse_track_stitched_candidate",
}
VIDEO_TEMPORAL_WEAK_GEOMETRY_MAIN_MOTION_ACCEPTED_FLAGS = {
    "semantic_keyframes_candidate_tal_conflict_ignored_main_motion_supported_weak_geometry",
}
VIDEO_TEMPORAL_OCCLUSION_TERMS = (
    "遮挡",
    "挡住",
    "干扰",
    "旁人",
    "其他人",
    "前景",
    "occlusion",
    "occluded",
    "obstruct",
    "foreground",
    "other skater",
)
VIDEO_TEMPORAL_SEVERE_OCCLUSION_TERMS = (
    "severe_occlusion",
    "target_indistinct",
    "motion_incomplete",
    "critical phase missing",
    "key frames missing",
    "严重遮挡",
    "关键动作被严重遮挡",
    "关键阶段细节丢失",
    "关键帧缺失",
)
VIDEO_TEMPORAL_SMALL_TARGET_TERMS = (
    "low_resolution",
    "low_res",
    "low_fps",
    "distant",
    "distant_view",
    "distant_subject",
    "small_target",
    "small subject",
    "\u5206\u8fa8\u7387",
    "\u52a8\u4f5c\u5e45\u5ea6\u5c0f",
    "\u8ddd\u79bb\u8f83\u8fdc",
    "\u753b\u9762\u8ddd\u79bb\u8f83\u8fdc",
)
VIDEO_TEMPORAL_REVISIBLE_TERMS = (
    "re-visible",
    "revisible",
    "visible again",
    "again visible",
    "\u91cd\u65b0\u53ef\u89c1",
    "\u91cd\u73b0\u53ef\u89c1",
)
VIDEO_TEMPORAL_GLIDE_OUT_TERMS = (
    "glide_out",
    "glide out",
    "\u6ed1\u51fa",
)
VIDEO_TEMPORAL_WEAK_JUMP_TERMS = (
    "action_incomplete",
    "low_height",
    "incomplete action",
    "low height",
    "weak jump",
    "very short air",
    "limited takeoff height",
    "limited height",
    "limited takeoff power",
    "\u52a8\u4f5c\u4e0d\u5b8c\u6574",
    "\u9ad8\u5ea6\u6709\u9650",
    "\u8d77\u8df3\u9ad8\u5ea6\u4f4e",
    "\u8d77\u8df3\u9ad8\u5ea6\u5f88\u4f4e",
    "\u8d77\u8df3\u9ad8\u5ea6\u504f\u4f4e",
    "\u8d77\u8df3\u9ad8\u5ea6\u4e0d\u8db3",
    "\u8d77\u8df3\u529b\u91cf\u6709\u9650",
    "\u8d77\u8df3\u529b\u91cf\u548c\u9ad8\u5ea6\u6709\u9650",
    "\u4f4e\u9ad8\u5ea6",
    "\u817e\u7a7a\u65f6\u95f4\u6781\u77ed",
    "\u817e\u7a7a\u65f6\u95f4\u5f88\u77ed",
)
VIDEO_TEMPORAL_FAILED_LANDING_FOLLOWTHROUGH_TERMS = (
    "failed landing",
    "landing failed",
    "lost balance",
    "loss of balance",
    "no stable glide",
    "unstable landing",
    "action interrupted",
    "\u843d\u51b0\u5931\u8d25",
    "\u843d\u51b0\u540e\u7acb\u5373\u5931\u53bb\u5e73\u8861",
    "\u5931\u53bb\u5e73\u8861",
    "\u6454\u5012",
    "\u672a\u80fd\u7a33\u5b9a\u6ed1\u51fa",
    "\u672a\u80fd\u4fdd\u6301\u7a33\u5b9a",
    "\u672a\u80fd\u4fdd\u6301\u6d41\u7545\u6ed1\u51fa",
    "\u672a\u80fd\u6709\u6548\u7f13\u51b2",
    "\u91cd\u5fc3\u4e0d\u7a33",
    "\u843d\u51b0\u4e0d\u7a33",
    "\u8e09\u8dc4",
    "\u6ed1\u51fa\u4e0d\u8212\u5c55",
    "\u52a8\u4f5c\u4e2d\u65ad",
)


def _configured_max_resolved_keyframes() -> int:
    raw = os.getenv("VIDEO_TEMPORAL_MAX_FRAMES", str(MAX_RESOLVED_KEYFRAMES)).strip()
    try:
        value = int(raw)
    except ValueError:
        return MAX_RESOLVED_KEYFRAMES
    return max(1, min(value, MAX_RESOLVED_KEYFRAMES))


def _semantic_key_from_record(record: dict[str, Any]) -> str | None:
    key_moment = str(record.get("key_moment") or "")
    if key_moment.startswith("T_"):
        return "T"
    if key_moment.startswith("A_"):
        return "A"
    if key_moment.startswith("L_"):
        return "L"
    phase_code = str(record.get("phase_code") or "")
    if phase_code == "takeoff":
        return "T"
    if phase_code == "air":
        return "A"
    if phase_code == "landing":
        return "L"
    return None


def _has_original_unresolved_tal_conflict_diagnostic(resolved_keyframes: dict[str, Any]) -> bool:
    skeleton_conflicts = resolved_keyframes.get("semantic_skeleton_tal_conflicts")
    if isinstance(skeleton_conflicts, list) and any(isinstance(item, dict) for item in skeleton_conflicts):
        return True

    motion_conflict = resolved_keyframes.get("semantic_motion_cluster_conflict")
    if isinstance(motion_conflict, dict):
        decision = str(motion_conflict.get("decision") or "").strip()
        accepted_decisions = {
            "ignored_near_skeleton_candidate_tal",
            "ignored_unreliable_pose_motion_fallback_cluster",
            "ignored_occlusion_contaminated_candidate_motion_window",
            "ignored_reused_phase_range_late_reanchor_motion_cluster",
        }
        if decision not in accepted_decisions:
            return True

    return False


def resolved_keyframes_accept_insufficient_pose_low_visibility_fallback(
    resolved_keyframes: dict[str, Any] | None,
) -> bool:
    if not isinstance(resolved_keyframes, dict):
        return False
    flags = {
        flag for flag in (resolved_keyframes.get("quality_flags") or []) if isinstance(flag, str)
    }
    if not (flags & VIDEO_TEMPORAL_INSUFFICIENT_POSE_LOW_VISIBILITY_ACCEPTED_FLAGS):
        return False

    accepted_decision = "ignored_insufficient_pose_low_visibility_motion_fallback_candidate"
    for key in ("semantic_candidate_tal_conflict", "semantic_reuse_current_candidate_conflict"):
        diagnostic = resolved_keyframes.get(key)
        if not isinstance(diagnostic, dict):
            continue
        if str(diagnostic.get("decision") or "") != accepted_decision:
            continue
        low_visibility_keys = diagnostic.get("low_visibility_motion_fallback_keys")
        if not (
            isinstance(low_visibility_keys, list)
            and any(str(item).strip().upper() in {"T", "A", "L"} for item in low_visibility_keys)
        ):
            continue
        candidate_flags = {
            str(flag)
            for flag in (diagnostic.get("candidate_quality_flags") or [])
            if isinstance(flag, str)
        }
        if "keyframe_candidates_motion_fallback" not in candidate_flags:
            continue
        if not (
            candidate_flags
            & {
                "tal_candidate_motion_fallback_low_precision",
                "tal_candidate_incomplete",
                "tal_order_unresolved",
                "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
                "tal_candidate_motion_fallback_foreground_motion_risk",
            }
        ):
            continue
        return True
    return False


def semantic_keyframes_are_reliable(resolved_keyframes: dict[str, Any] | None) -> bool:
    if not isinstance(resolved_keyframes, dict):
        return False
    selected = resolved_keyframes.get("selected")
    if not isinstance(selected, list) or not selected:
        return False
    top_level_quality_flags = [
        flag for flag in (resolved_keyframes.get("quality_flags") or []) if isinstance(flag, str)
    ]
    accepted_unreliable_pose_motion_fallback = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_unreliable_pose_fallback" in top_level_quality_flags
    )
    accepted_near_candidate_motion_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate" in top_level_quality_flags
    )
    accepted_occlusion_contaminated_motion_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_occlusion_contaminated_candidate"
        in top_level_quality_flags
    )
    accepted_weak_temporal_geometry_motion_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_weak_temporal_geometry"
        in top_level_quality_flags
    )
    accepted_early_approach_motion_peak_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_early_approach_motion_peak"
        in top_level_quality_flags
    )
    accepted_phase_range_late_reanchor_motion_conflict = (
        "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor"
        in top_level_quality_flags
    )
    accepted_reused_phase_range_late_reanchor_motion_conflict = (
        "semantic_keyframes_reuse_motion_cluster_conflict_ignored_phase_range_late_reanchor"
        in top_level_quality_flags
    )
    accepted_sparse_track_stitched_motion_conflict = (
        "semantic_keyframes_reuse_motion_cluster_conflict_ignored_sparse_track_stitched_candidate"
        in top_level_quality_flags
    )
    accepted_tracker_final_loss_visual_promotion = (
        "semantic_keyframes_tracker_final_loss_visual_tal_promoted" in top_level_quality_flags
    )
    accepted_phase_range_visual_promotion = (
        "semantic_keyframes_phase_range_visual_tal_promoted" in top_level_quality_flags
    )
    accepted_weak_skeleton_cluster_visual_promotion = (
        "semantic_keyframes_weak_skeleton_cluster_visual_tal_promoted" in top_level_quality_flags
    )
    accepted_distant_full_context_visual_promotion = (
        "semantic_keyframes_distant_full_context_visual_tal_promoted" in top_level_quality_flags
    )
    accepted_long_unresolved_partial_promotion = (
        "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted" in top_level_quality_flags
    )
    accepted_full_context_takeoff_anchor_fallback = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_takeoff_anchor_fallback"
        in top_level_quality_flags
    )
    accepted_early_takeoff_anchor_fallback = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_early_takeoff_anchor_fallback"
        in top_level_quality_flags
    )
    accepted_early_candidate_approach_window = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_early_candidate_approach_window"
        in top_level_quality_flags
    )
    accepted_takeoff_anchor_phase_shift = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_takeoff_anchor_phase_shift"
        in top_level_quality_flags
    )
    accepted_full_context_weak_candidate_motion_conflict = (
        "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_weak_candidate"
        in top_level_quality_flags
    )
    accepted_near_candidate_refinement_rejection = (
        "semantic_keyframe_refinement_rejection_ignored_near_skeleton_candidate" in top_level_quality_flags
    )
    accepted_weak_temporal_geometry_refinement_rejection = (
        "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry" in top_level_quality_flags
    )
    accepted_weak_temporal_geometry_conflict = (
        "video_temporal_quality_retry_skeleton_tal_conflict_ignored_weak_temporal_geometry" in top_level_quality_flags
        or "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry" in top_level_quality_flags
    )
    accepted_main_motion_supported_weak_geometry_conflict = bool(
        set(top_level_quality_flags) & VIDEO_TEMPORAL_WEAK_GEOMETRY_MAIN_MOTION_ACCEPTED_FLAGS
    )
    accepted_insufficient_pose_low_visibility_fallback = (
        resolved_keyframes_accept_insufficient_pose_low_visibility_fallback(resolved_keyframes)
    )
    accepted_degraded_semantic_low_visibility_reuse = (
        accepted_insufficient_pose_low_visibility_fallback
        and "semantic_keyframes_reused_from_matching_video" in top_level_quality_flags
        and "semantic_keyframes_reused_from_degraded_semantic_low_visibility_source" in top_level_quality_flags
    )
    accepted_clean_video_tal_late_weak_candidate_reuse = (
        "semantic_keyframes_reused_from_matching_video" in top_level_quality_flags
        and "semantic_keyframes_reused_from_clean_video_tal_late_weak_candidate_source" in top_level_quality_flags
    )
    accepted_sparse_track_stitched_reuse_conflict = (
        "semantic_keyframes_reuse_candidate_conflict_ignored_sparse_track_stitched_candidate"
        in top_level_quality_flags
    )
    hard_unreliable_flags = {
        "semantic_frame_extract_failed",
        "semantic_keyframe_refinement_order_rejected",
        "semantic_keyframe_core_foreground_occlusion",
        "semantic_keyframes_unreliable_candidate_tal_conflict",
        "semantic_keyframes_unreliable_candidate_motion_window_conflict",
        "semantic_keyframes_unreliable_candidate_takeoff_single_conflict",
        "semantic_keyframes_unreliable_candidate_early_takeoff_conflict",
        "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
        "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
        "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
        "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
        "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
        "semantic_keyframes_unreliable_reused_current_candidate_conflict",
        "semantic_keyframes_unreliable_reused_motion_cluster_conflict",
        "semantic_keyframes_unreliable_after_visibility_check",
        "semantic_keyframes_unreliable_after_retry_rejection",
    }
    if (
        accepted_full_context_takeoff_anchor_fallback
        or accepted_early_takeoff_anchor_fallback
        or accepted_early_candidate_approach_window
        or accepted_takeoff_anchor_phase_shift
        or accepted_full_context_weak_candidate_motion_conflict
    ):
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframe_refinement_phase_rejected",
            "semantic_keyframe_refinement_delta_rejected",
            "semantic_keyframes_unreliable_candidate_tal_conflict",
            "semantic_keyframes_unreliable_candidate_motion_window_conflict",
            "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
            "semantic_keyframes_unreliable_after_refinement",
        }
    if accepted_early_approach_motion_peak_conflict:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframe_refinement_phase_rejected",
            "semantic_keyframes_unreliable_candidate_motion_window_conflict",
            "semantic_keyframes_unreliable_after_refinement",
        }
    if accepted_phase_range_late_reanchor_motion_conflict:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_after_refinement",
            "semantic_keyframes_unreliable_after_retry_rejection",
        }
    if accepted_reused_phase_range_late_reanchor_motion_conflict:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_reused_motion_cluster_conflict",
        }
    if accepted_sparse_track_stitched_motion_conflict:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_reused_motion_cluster_conflict",
        }
    if accepted_sparse_track_stitched_reuse_conflict:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_reused_current_candidate_conflict",
        }
    if accepted_near_candidate_refinement_rejection or accepted_weak_temporal_geometry_refinement_rejection:
        hard_unreliable_flags = hard_unreliable_flags - {"semantic_keyframe_refinement_order_rejected"}
    if accepted_tracker_final_loss_visual_promotion:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
            "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
        }
    if accepted_phase_range_visual_promotion or accepted_weak_skeleton_cluster_visual_promotion:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_candidate_tal_conflict",
            "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
            "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
            "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
            "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            "semantic_keyframes_unreliable_after_retry_rejection",
        }
    if accepted_distant_full_context_visual_promotion:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_candidate_tal_conflict",
            "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
            "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
            "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
            "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
        }
    if accepted_main_motion_supported_weak_geometry_conflict:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_candidate_tal_conflict",
            "semantic_keyframes_unreliable_after_refinement",
        }
    if accepted_degraded_semantic_low_visibility_reuse:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
        }
    if accepted_clean_video_tal_late_weak_candidate_reuse:
        hard_unreliable_flags = hard_unreliable_flags - {
            "semantic_keyframe_refinement_delta_rejected",
            "semantic_keyframe_refinement_phase_rejected",
            "semantic_keyframes_unreliable_candidate_tal_conflict",
            "semantic_keyframes_unreliable_after_refinement",
        }
    if any(flag in hard_unreliable_flags for flag in top_level_quality_flags):
        return False
    if (
        "semantic_keyframes_unreliable_fallback_to_sampled_frames" in top_level_quality_flags
        and not accepted_unreliable_pose_motion_fallback
        and not accepted_near_candidate_motion_conflict
        and not accepted_occlusion_contaminated_motion_conflict
        and not accepted_weak_temporal_geometry_motion_conflict
        and not accepted_early_approach_motion_peak_conflict
        and not accepted_phase_range_late_reanchor_motion_conflict
        and not accepted_reused_phase_range_late_reanchor_motion_conflict
        and not accepted_sparse_track_stitched_motion_conflict
        and not accepted_tracker_final_loss_visual_promotion
        and not accepted_phase_range_visual_promotion
        and not accepted_weak_skeleton_cluster_visual_promotion
        and not accepted_distant_full_context_visual_promotion
        and not accepted_long_unresolved_partial_promotion
        and not accepted_full_context_takeoff_anchor_fallback
        and not accepted_early_takeoff_anchor_fallback
        and not accepted_early_candidate_approach_window
        and not accepted_takeoff_anchor_phase_shift
        and not accepted_full_context_weak_candidate_motion_conflict
        and not accepted_main_motion_supported_weak_geometry_conflict
        and not accepted_insufficient_pose_low_visibility_fallback
        and not accepted_clean_video_tal_late_weak_candidate_reuse
        and not accepted_sparse_track_stitched_reuse_conflict
    ):
        return False
    retry_rejection_flags = set()
    if (
        "video_temporal_quality_retry_rejected" in top_level_quality_flags
        and isinstance(resolved_keyframes.get("video_temporal_quality_retry_rejection_flags"), list)
    ):
        retry_rejection_flags = {
            flag for flag in resolved_keyframes.get("video_temporal_quality_retry_rejection_flags", []) if isinstance(flag, str)
        }
    if (
        any(flag in VIDEO_TEMPORAL_UNRESOLVED_TAL_CONFLICT_FLAGS for flag in top_level_quality_flags)
        and _has_original_unresolved_tal_conflict_diagnostic(resolved_keyframes)
        and not any(flag in VIDEO_TEMPORAL_ACCEPTED_TAL_REPAIR_FLAGS for flag in top_level_quality_flags)
        and not accepted_weak_temporal_geometry_conflict
        and not accepted_main_motion_supported_weak_geometry_conflict
        and not accepted_insufficient_pose_low_visibility_fallback
        and not accepted_clean_video_tal_late_weak_candidate_reuse
        and not accepted_sparse_track_stitched_reuse_conflict
        and not accepted_sparse_track_stitched_motion_conflict
    ):
        return False
    quality_flags = [
        flag
        for flag in top_level_quality_flags
        if flag not in retry_rejection_flags
    ]
    if accepted_unreliable_pose_motion_fallback:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag != "semantic_keyframes_unreliable_fallback_to_sampled_frames"
        ]
    if "video_temporal_resolver_motion_cluster_fallback_used" in quality_flags:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag != "video_temporal_resolver_coherent_tal_motion_conflict_rejected"
        ]
    if "video_temporal_resolver_coherent_tal_motion_supported_despite_late_motion" in quality_flags:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag != "video_temporal_resolver_coherent_tal_motion_conflict_rejected"
        ]
    if "video_temporal_quality_retry_motion_cluster_conflict_ignored_unreliable_pose_fallback" in quality_flags:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag != "video_temporal_resolver_coherent_tal_motion_conflict_rejected"
        ]
    if accepted_near_candidate_motion_conflict:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_occlusion_contaminated_motion_conflict:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_weak_temporal_geometry_motion_conflict:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_early_approach_motion_peak_conflict:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframe_refinement_phase_rejected",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_candidate_motion_window_conflict",
                "semantic_keyframes_unreliable_after_refinement",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_phase_range_late_reanchor_motion_conflict or accepted_reused_phase_range_late_reanchor_motion_conflict:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_reused_motion_cluster_conflict",
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_after_retry_rejection",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_sparse_track_stitched_motion_conflict:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_reused_motion_cluster_conflict",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_tracker_final_loss_visual_promotion:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
            }
        ]
    if accepted_phase_range_visual_promotion or accepted_weak_skeleton_cluster_visual_promotion:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                "semantic_keyframes_unreliable_after_retry_rejection",
                "video_temporal_quality_retry_skeleton_tal_conflict",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_distant_full_context_visual_promotion:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            }
        ]
    if accepted_long_unresolved_partial_promotion:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_near_candidate_refinement_rejection or accepted_weak_temporal_geometry_refinement_rejection:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag != "semantic_keyframe_refinement_order_rejected"
        ]
    if accepted_weak_temporal_geometry_conflict:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag not in {
                "video_temporal_quality_retry_skeleton_tal_conflict",
                "semantic_keyframes_unreliable_candidate_tal_conflict",
            }
        ]
    if accepted_main_motion_supported_weak_geometry_conflict:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag not in {
                "video_temporal_quality_retry_skeleton_tal_conflict",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_unreliable_after_refinement",
            }
        ]
    if (
        accepted_full_context_takeoff_anchor_fallback
        or accepted_early_takeoff_anchor_fallback
        or accepted_early_candidate_approach_window
        or accepted_takeoff_anchor_phase_shift
        or accepted_full_context_weak_candidate_motion_conflict
    ):
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframe_refinement_phase_rejected",
                "semantic_keyframe_refinement_delta_rejected",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_unreliable_candidate_motion_window_conflict",
                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                "semantic_keyframes_unreliable_after_refinement",
                "video_temporal_quality_retry_motion_cluster_conflict",
            }
        ]
    if accepted_insufficient_pose_low_visibility_fallback:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_quality_retry_motion_cluster_conflict",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
            }
        ]
    if accepted_degraded_semantic_low_visibility_reuse:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag != "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion"
        ]
    if accepted_clean_video_tal_late_weak_candidate_reuse:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframe_refinement_delta_rejected",
                "semantic_keyframe_refinement_phase_rejected",
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            }
        ]
    if "semantic_keyframes_phase_range_visual_tal_promoted" in quality_flags:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            }
        ]
    if "semantic_keyframes_distant_full_context_visual_tal_promoted" in quality_flags:
        quality_flags = [
            flag
            for flag in quality_flags
            if flag
            not in {
                "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            }
        ]
    if any(
        flag
        in {
            "semantic_frame_extract_failed",
            "semantic_keyframe_refinement_order_rejected",
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            "semantic_keyframe_core_foreground_occlusion",
            "semantic_keyframes_unreliable_candidate_tal_conflict",
            "semantic_keyframes_unreliable_candidate_motion_window_conflict",
            "semantic_keyframes_unreliable_candidate_takeoff_single_conflict",
            "semantic_keyframes_unreliable_candidate_early_takeoff_conflict",
            "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
            "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
            "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
            "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
            "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            "semantic_keyframes_unreliable_after_visibility_check",
            "semantic_keyframes_unreliable_after_retry_rejection",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        }
        for flag in quality_flags
    ):
        return False
    if (
        any(flag in VIDEO_TEMPORAL_UNRESOLVED_TAL_CONFLICT_FLAGS for flag in quality_flags)
        and not any(flag in VIDEO_TEMPORAL_ACCEPTED_TAL_REPAIR_FLAGS for flag in quality_flags)
    ):
        return False
    source = resolved_keyframes.get("source")
    anchors: dict[str, float] = {}
    selected_phase_codes: set[str] = set()
    for item in selected:
        if not isinstance(item, dict):
            continue
        phase_code = str(item.get("phase_code") or "")
        if phase_code:
            selected_phase_codes.add(phase_code)
        key = _semantic_key_from_record(item)
        timestamp = _to_float(item.get("timestamp"))
        if key in {"T", "A", "L"} and timestamp is not None:
            anchors[key] = timestamp
    if anchors and not {"T", "A", "L"}.issubset(anchors):
        return False
    if {"T", "A", "L"}.issubset(anchors) and not (
        anchors["T"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["A"]
        and anchors["A"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["L"]
    ):
        return False
    if source in {"video_ai_refined", "blended"}:
        if selected_phase_codes & JUMP_PHASE_CODES:
            return {"T", "A", "L"}.issubset(anchors)
        return True
    if source != "skeleton_fallback":
        return False
    if "video_temporal_resolver_motion_cluster_fallback_used" in quality_flags:
        return _selected_has_complete_ordered_core_tal(selected, min_confidence=JUMP_MOTION_CLUSTER_FALLBACK_CONFIDENCE)

    anchors = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _semantic_key_from_record(item)
        timestamp = _to_float(item.get("timestamp"))
        confidence = _candidate_confidence(item)
        if key in {"T", "A", "L"} and timestamp is not None and confidence >= SKELETON_FALLBACK_CONFIDENCE:
            anchors[key] = timestamp
    return (
        {"T", "A", "L"}.issubset(anchors)
        and anchors["T"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["A"]
        and anchors["A"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["L"]
    )


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    numeric = _to_float(value)
    if numeric is None:
        numeric = default
    return round(max(0.0, min(1.0, numeric)), 3)


def _optional_time(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return round(numeric, 3)


def _string(value: Any, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_flags(*sources: Any) -> list[str]:
    flags: list[str] = []
    for source in sources:
        if not isinstance(source, list):
            continue
        for flag in source:
            text = str(flag).strip()
            if text and text not in flags:
                flags.append(text)
    return flags


def _raw_response_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False, default=str)
    return str(raw)


def _raw_response_diagnostics(raw: Any, detail: str = "") -> dict[str, Any]:
    text = _raw_response_text(raw)
    excerpt = text[:RAW_RESPONSE_EXCERPT_LIMIT]
    return {
        "raw_response_excerpt": excerpt,
        "raw_response_length": len(text),
        "raw_response_truncated": len(text) > RAW_RESPONSE_EXCERPT_LIMIT,
        "parse_error_detail": detail or None,
    }


def _object_from_nested_content(raw: dict[str, Any]) -> Any:
    for key in ("content", "text"):
        value = raw.get(key)
        if value is not None:
            if isinstance(value, list):
                text_parts = [
                    str(item.get("text", "")).strip()
                    for item in value
                    if isinstance(item, dict) and str(item.get("text", "")).strip()
                ]
                if text_parts:
                    return "\n".join(text_parts)
            return value
    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                for key in ("content", "text"):
                    value = message.get(key)
                    if value is not None:
                        return value
            for key in ("content", "text"):
                value = first.get(key)
                if value is not None:
                    return value
    output = raw.get("output")
    if isinstance(output, dict):
        return _object_from_nested_content(output)
    return None


def _parse_json_object_from_text(raw_text: str) -> tuple[dict[str, Any] | None, str]:
    text = raw_text.strip()
    if not text:
        return None, "empty response"

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, ""
        return None, "parsed JSON is not an object"
    except json.JSONDecodeError as exc:
        first_error = str(exc)

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text, re.IGNORECASE):
        candidate = match.group(1).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed, ""
        except json.JSONDecodeError as exc:
            first_error = str(exc)

    partial = _parse_partial_video_temporal_object(raw_text, first_error)
    if partial is not None:
        return partial, ""

    best_candidate: dict[str, Any] | None = None
    best_score = 0
    for start, char in enumerate(raw_text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(raw_text)):
            current = raw_text[end]
            if escaped:
                escaped = False
                continue
            if current == "\\" and in_string:
                escaped = True
                continue
            if current == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw_text[start : end + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            score = _video_temporal_object_score(parsed)
                            if score > best_score:
                                best_candidate = parsed
                                best_score = score
                    except json.JSONDecodeError as exc:
                        first_error = str(exc)
                    break
    if best_candidate is not None and best_score >= 2:
        return best_candidate, ""
    return None, first_error


def _video_temporal_object_score(value: dict[str, Any]) -> int:
    score = 0
    if value.get("schema_version") == SCHEMA_VERSION:
        score += 3
    if isinstance(value.get("phase_segments"), list):
        score += 4
    if isinstance(value.get("key_moments"), dict):
        score += 2
    if isinstance(value.get("action_confirmation"), dict):
        score += 2
    if any(key in value for key in ("confidence", "fallback_recommendation", "data_quality_hint")):
        score += 1
    return score


def _decode_json_value_after_key(raw_text: str, key: str) -> Any:
    match = re.search(rf'"{re.escape(key)}"\s*:', raw_text)
    if not match:
        return None
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(raw_text[match.end() :].lstrip())
    except json.JSONDecodeError:
        return None
    return value


def _parse_partial_video_temporal_object(raw_text: str, parse_error: str) -> dict[str, Any] | None:
    phase_segments = _decode_json_value_after_key(raw_text, "phase_segments")
    if not isinstance(phase_segments, list):
        return None

    parsed: dict[str, Any] = {"phase_segments": phase_segments}
    for key in (
        "schema_version",
        "action_confirmation",
        "key_moments",
        "macro_assessment",
        "overall_impression",
        "camera_view",
        "data_quality_hint",
        "confidence",
        "fallback_recommendation",
        "quality_flags",
    ):
        value = _decode_json_value_after_key(raw_text, key)
        if value is not None:
            parsed[key] = value

    flags = _merge_flags(parsed.get("quality_flags"), ["video_temporal_partial_json_salvaged"])
    parsed["quality_flags"] = flags
    parsed.update(_raw_response_diagnostics(raw_text, f"partial JSON salvaged after parse error: {parse_error}"))
    return parsed


def _parse_raw_payload(raw: Any) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    if isinstance(raw, dict):
        nested = _object_from_nested_content(raw)
        if nested is not None:
            return _parse_raw_payload(nested)
        return raw, [], {}
    if isinstance(raw, str):
        parsed, detail = _parse_json_object_from_text(raw)
        if isinstance(parsed, dict):
            return parsed, [], {}
        return None, ["video_temporal_invalid_json"], _raw_response_diagnostics(raw, detail)
    return None, ["video_temporal_payload_not_object"], _raw_response_diagnostics(raw, "payload is not a JSON object or text")


def _fallback_video_temporal_payload(
    *,
    provider: str,
    model: str,
    reason: str,
    quality_flags: list[str],
    detail: str = "",
) -> dict[str, Any]:
    flags = _merge_flags(quality_flags)
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": _string(provider, "unknown"),
        "model": _string(model, DEFAULT_MODEL),
        "valid": False,
        "action_confirmation": {
            "action_family": "unknown",
            "confirmed_action": "不可分析",
            "jump_type": "",
            "confidence": 0.0,
            "notes": detail,
        },
        "phase_segments": [],
        "key_moments": {key: None for key in KEY_MOMENT_KEYS},
        "macro_assessment": _normalize_macro_assessment({}),
        "overall_impression": "",
        "camera_view": "unknown",
        "data_quality_hint": "poor",
        "confidence": 0.0,
        "fallback_recommendation": "use_existing_skeleton_timestamps",
        "fallback_reason": reason,
        "quality_flags": flags,
        "validation": {
            "valid": False,
            "errors": flags,
            "warnings": [],
        },
    }


def _normalize_action_family(value: Any) -> str:
    text = _string(value).lower()
    aliases = {
        "jump": "jump",
        "jumps": "jump",
        "跳跃": "jump",
        "spin": "spin",
        "spins": "spin",
        "旋转": "spin",
        "step": "step",
        "steps": "step",
        "step_sequence": "step",
        "步法": "step",
        "spiral": "spiral",
        "spirals": "spiral",
        "spiral_line": "spiral",
        "螺旋线": "spiral",
        "燕式": "spiral",
    }
    return aliases.get(text, "unknown")


def _normalize_phase_code(value: Any) -> str:
    text = _string(value)
    if not text:
        return "unknown"
    compact = text.strip().lower().replace(" ", "_").replace("-", "_")
    return PHASE_ALIASES.get(text, PHASE_ALIASES.get(compact, compact if compact in ALL_PHASE_CODES else "unknown"))


def _phase_codes_for_family(action_family: str) -> set[str]:
    if action_family == "jump":
        return JUMP_PHASE_CODES
    if action_family == "spin":
        return SPIN_PHASE_CODES
    if action_family == "step":
        return STEP_PHASE_CODES
    if action_family == "spiral":
        return SPIRAL_PHASE_CODES
    return ALL_PHASE_CODES


def _infer_action_family(action_confirmation: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    family = _normalize_action_family(action_confirmation.get("action_family"))
    confirmed = _string(action_confirmation.get("confirmed_action") or action_confirmation.get("jump_type")).lower()
    codes = {segment.get("phase_code") for segment in segments if isinstance(segment, dict)}
    if family == "step" and (confirmed in {"spiral", "spiral_line"} or codes & SPIRAL_PHASE_CODES):
        return "spiral"
    if family != "unknown":
        return family
    if confirmed in {"axel", "lutz", "flip", "loop", "salchow", "toe loop", "toe_loop"}:
        return "jump"
    if codes & JUMP_PHASE_CODES:
        return "jump"
    if codes & SPIN_PHASE_CODES:
        return "spin"
    if codes & SPIRAL_PHASE_CODES:
        return "spiral"
    if codes & STEP_PHASE_CODES:
        return "step"
    return "unknown"


def _normalize_action_confirmation(raw: dict[str, Any]) -> dict[str, Any]:
    action = raw.get("action_confirmation")
    if not isinstance(action, dict):
        action = {}
    return {
        "action_family": _normalize_action_family(action.get("action_family") or raw.get("action_family")),
        "confirmed_action": _string(action.get("confirmed_action") or raw.get("confirmed_action") or "不可分析"),
        "jump_type": _string(action.get("jump_type") or raw.get("jump_type") or ""),
        "confidence": _clamp_confidence(action.get("confidence", raw.get("confidence", 0.0))),
        "notes": _string(action.get("notes")),
    }


def _normalize_phase_segments(raw: dict[str, Any], flags: list[str]) -> list[dict[str, Any]]:
    segments = raw.get("phase_segments")
    if not isinstance(segments, list):
        for alias in ("phases", "segments", "timeline", "phase_timeline", "action_phases"):
            value = raw.get(alias)
            if isinstance(value, list):
                segments = value
                flags.append(f"video_temporal_phase_segments_alias_{alias}")
                break
        else:
            return []

    normalized: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            flags.append(f"video_temporal_phase_{index}_not_object")
            continue
        phase_code = _normalize_phase_code(segment.get("phase_code") or segment.get("phase") or segment.get("phase_label"))
        if phase_code == "unknown":
            flags.append(f"video_temporal_phase_{index}_unknown_code")
        start_value = segment.get("time_start", segment.get("start_sec", segment.get("start", segment.get("start_time"))))
        end_value = segment.get("time_end", segment.get("end_sec", segment.get("end", segment.get("end_time"))))
        hint_value = segment.get(
            "key_frame_hint",
            segment.get("keyframe_hint", segment.get("representative_sec", segment.get("keyframe_sec", segment.get("timestamp", segment.get("time"))))),
        )
        normalized.append(
            {
                "phase_code": phase_code,
                "phase_label": _string(segment.get("phase_label"), PHASE_LABELS.get(phase_code, "不可分析")),
                "time_start": _optional_time(start_value),
                "time_end": _optional_time(end_value),
                "key_frame_hint": _optional_time(hint_value),
                "confidence": _clamp_confidence(segment.get("confidence", raw.get("confidence", 0.0))),
                "observations": _list_of_strings(
                    segment.get("observations", segment.get("notes", segment.get("description", segment.get("details"))))
                ),
                "issues": _list_of_strings(segment.get("issues", segment.get("problems", segment.get("warnings")))),
            }
        )
    return normalized


def _normalize_key_moments(raw: dict[str, Any]) -> dict[str, float | None]:
    source = raw.get("key_moments")
    if not isinstance(source, dict):
        for alias in ("keyframes", "key_frames", "key_points", "moments"):
            value = raw.get(alias)
            if isinstance(value, dict):
                source = value
                break
        else:
            source = {}
    aliases = {
        "T_takeoff_sec": ("T_takeoff_sec", "T", "takeoff_sec", "takeoff", "takeoff_time", "takeoff_time_sec", "t_takeoff_sec"),
        "A_air_sec": ("A_air_sec", "A", "air_sec", "air", "apex", "apex_sec", "apex_time", "apex_time_sec", "a_air_sec"),
        "L_landing_sec": ("L_landing_sec", "L", "landing_sec", "landing", "landing_time", "landing_time_sec", "l_landing_sec"),
    }
    normalized: dict[str, float | None] = {}
    for output_key, input_keys in aliases.items():
        value = None
        for input_key in input_keys:
            if input_key in source:
                raw_value = source.get(input_key)
                value = raw_value.get("timestamp") if isinstance(raw_value, dict) else raw_value
                break
            if input_key in raw:
                raw_value = raw.get(input_key)
                value = raw_value.get("timestamp") if isinstance(raw_value, dict) else raw_value
                break
        normalized[output_key] = _optional_time(value)
    return normalized


def _normalize_macro_assessment(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw.get("macro_assessment")
    if not isinstance(source, dict):
        source = {}
    return {
        "timing_rhythm": _string(source.get("timing_rhythm")),
        "speed_flow": _string(source.get("speed_flow")),
        "axis_overall": _string(source.get("axis_overall")),
        "entry_quality": _string(source.get("entry_quality")),
        "exit_or_landing_quality": _string(source.get("exit_or_landing_quality")),
        "top_strengths": _list_of_strings(source.get("top_strengths")),
        "top_issues": _list_of_strings(source.get("top_issues")),
    }


def build_video_temporal_prompts(
    *,
    action_type: str,
    action_subtype: str | None = None,
    user_note: str | None = None,
    video_duration_sec: float | None = None,
    source_fps: float | None = None,
    skater_level: str = "儿童初级 / Free Skate 1",
    model: str = DEFAULT_MODEL,
    retry_context: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """
    Build video-temporal prompts for semantic phase localization.
    """
    duration_text = "unknown" if video_duration_sec is None else f"{max(0.0, float(video_duration_sec)):.2f}"
    fps_text = "unknown" if source_fps is None else f"{max(0.0, float(source_fps)):.2f}"
    model_text = _string(model, DEFAULT_MODEL)
    action_type_text = _string(action_type, "unknown")
    action_subtype_text = _string(action_subtype, "unknown")
    user_note_text = _string(user_note)
    user_note_section = f"- 上传备注/额外 comments: {user_note_text}\n" if user_note_text else ""
    uncertainty_section = (
        "\n动作不确定性规则：\n"
        "- action_type_hint/action_subtype_hint 是用户输入的线索，不是最终标签；用户可能只知道动作大类。\n"
        "- action_subtype_hint=unknown/未指定 时，只能在画面证据清楚时输出 confirmed_action 或 jump_type 的具体名称。\n"
        "- 如果只能确认大类，请保留 confirmed_action 为通用名称或“不可分析”，jump_type 留空，并降低 action_confirmation.confidence。\n"
        "- 上传备注/comments 只能作为观察线索，不能替代可见视频证据。\n"
    )
    mixed_action_mode = action_type_text == "自由滑" and action_subtype_text in {"unknown", "节目片段"}
    mixed_action_section = (
        "\n混合动作自动识别要求：\n"
        "- action_type_hint=自由滑 且 action_subtype_hint=节目片段 表示视频可能是跳跃、旋转、步法或螺旋线中的任意一种，不代表一定是跳跃。\n"
        "- 必须先判断实际动作类型；不要为了填 T/A/L 把旋转、步法、螺旋线或普通滑行解释成小跳。\n"
        "- 只有清楚看到主滑行者完成离冰/腾空/首次落冰三段证据时，action_family 才能填 jump，并输出 takeoff/air/landing 与 T/A/L。\n"
        "- 如果没有清楚腾空：旋转使用 spin_entry/spin_main/spin_exit；步法使用 step_sequence；螺旋线/燕式使用 spiral_entry/spiral_hold/spiral_exit；key_moments 的 T/A/L 保持 null。\n"
        if mixed_action_mode
        else ""
    )

    system_prompt = (
        "你是一名专业花样滑冰技术分析师，熟悉儿童初级训练、ISU 技术要素、基础运动生物力学和视频时间定位。\n\n"
        "你的任务是直接分析完整动作视频，输出动作阶段的时间区间、动作类型确认、宏观技术评价和整体印象。\n\n"
        "要求：\n"
        "1. 只输出一个合法 JSON 对象，不要输出 Markdown、解释或代码块。\n"
        "2. 所有时间戳单位为秒，基于源视频从 0.000 秒开始的播放时间轴。\n"
        "3. 如果无法判断，使用 null 或 “不可分析”，不要编造。\n"
        "4. 目标学员为 5-8 岁儿童，评价要使用儿童训练标准，不使用成人竞技标准。\n"
        "5. 你只负责视频宏观时序和整体质量判断，不输出骨架测量数值。\n"
        "6. 对高速跳跃动作，给出阶段区间，不要假装能锁定单个绝对精确帧。\n"
        "7. 时间保留两位小数，尽量精确到 0.1 秒以内；T/A/L 关键时刻误差应尽量控制在 0.2 秒以内。\n"
        "8. T = 最后一只脚离冰的瞬间，A = 身体重心达到最高点的瞬间，L = 冰刀首次接触冰面的瞬间。\n"
        "9. 始终跟踪主滑行者；忽略旁人、前景遮挡、镜头前经过的人和背景滑行者。遮挡后主滑行者重新可见时，不要把重新可见、滑出或后续摆臂误判为 T/A/L。\n"
        "10. 动作细项不确定时要保持不确定，不要为了输出完整字段而编造具体跳种、刃型或周数。"
    )

    schema_hint = {
        "schema_version": SCHEMA_VERSION,
        "action_confirmation": {
            "action_family": "jump|spin|step|spiral|unknown",
            "confirmed_action": "Axel|Lutz|Flip|Loop|Salchow|Toe Loop|spin|step_sequence|spiral|不可分析",
            "jump_type": "Axel|Lutz|Flip|Loop|Salchow|Toe Loop|",
            "confidence": 0.0,
            "notes": "",
        },
        "phase_segments": [
            {
                "phase_code": "approach|preparation|takeoff|air|landing|glide_out|spin_entry|spin_main|spin_exit|step_sequence|spiral_entry|spiral_hold|spiral_exit",
                "phase_label": "起跳",
                "time_start": 0.0,
                "time_end": 0.0,
                "key_frame_hint": 0.0,
                "confidence": 0.0,
                "observations": [],
                "issues": [],
            }
        ],
        "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
        "macro_assessment": {
            "timing_rhythm": "",
            "speed_flow": "",
            "axis_overall": "",
            "entry_quality": "",
            "exit_or_landing_quality": "",
            "top_strengths": [],
            "top_issues": [],
        },
        "overall_impression": "",
        "camera_view": "front|side|diagonal_front|diagonal_back|rear|unknown",
        "data_quality_hint": "good|partial|poor",
        "confidence": 0.0,
        "fallback_recommendation": "use_video_timestamps|use_sampled_frames|manual_review",
        "quality_flags": [],
    }

    retry_section = ""
    if isinstance(retry_context, dict) and retry_context:
        retry_json = _compact_retry_context_json(retry_context, RETRY_CONTEXT_JSON_LIMIT)
        profile_mismatch = retry_context.get("profile_mismatch")
        if isinstance(profile_mismatch, dict) and profile_mismatch.get("requested") in {"spin", "spiral", "step"}:
            retry_section = (
                "\n\nQUALITY_GATE_RETRY_CONTEXT:\n"
                "A previous JSON response was parsed but rejected because it classified a different action family than the requested non-jump profile and produced no usable semantic frames. "
                "Re-evaluate the same clip for the requested target action only. "
                "Do not return jump phases or T/A/L timestamps unless the requested profile is jump. "
                "For spin use spin_entry/spin_main/spin_exit; for spiral use spiral_entry/spiral_hold/spiral_exit; for step use step_sequence. "
                "Keep hard uncertainty as fallback/manual_review only if the requested action is genuinely not visible.\n"
                f"{retry_json}\n"
            )
        else:
            retry_section = (
                "\n\nQUALITY_GATE_RETRY_CONTEXT:\n"
                "A previous JSON response was parsed but rejected by downstream quality gates. "
                "Re-evaluate the same clip using the structured diagnostics below. "
                "Top motion records are full-frame signals and may come from foreground occlusion, another skater, camera motion, or glide_out; do not move T/A/L solely because a later motion peak is larger. "
                "If skeleton_candidate_tal is present, treat those timestamps as noisy but useful target-skater instance anchors: when they are close to the previous T/A/L, refine within the same local action instance instead of jumping to an earlier or later skating segment. "
                "If you disagree with those anchors, keep the same target skater and explain the visible takeoff, apex, or first-contact landing evidence through phase timing rather than selecting a different motion cluster. "
                "Keep previous T/A/L when the main skater's takeoff-air-landing sequence supports them, and change them only when first-contact landing, takeoff, or apex evidence is clearer elsewhere. "
                "Keep hard uncertainty as fallback, but if the target skater's takeoff-air-landing sequence is visible, return the most coherent T/A/L sequence for the main skater only.\n"
                f"{retry_json}\n"
            )

    user_prompt = (
        "请分析这段花样滑冰训练视频。\n\n"
        "已知信息：\n"
        f"- action_type_hint: {_string(action_type, 'unknown')}\n"
        f"- action_subtype_hint: {_string(action_subtype, 'unknown')}\n"
        f"{user_note_section}"
        f"- skater_level: {skater_level}\n"
        f"- video_duration_sec: {duration_text}\n"
        f"- source_fps: {fps_text}\n"
        f"- model: {model_text}\n\n"
        "需要覆盖的动作类型：\n"
        "- 跳跃：Lutz, Flip, Loop, Salchow, Toe Loop, Axel\n"
        "- 非跳跃：旋转、步法、螺旋线\n\n"
        f"{uncertainty_section}\n"
        "请完成：\n"
        "1. 确认实际动作类型和子类型。\n"
        "2. 输出每个动作阶段的 time_start/time_end。\n"
        "3. 对每个关键阶段输出 key_frame_hint，表示该阶段最有代表性的时间点。\n"
        "4. 仅当实际动作是跳跃时，给出 T/A/L 建议时间：T = 最后一只脚离冰的瞬间，A = 身体重心达到最高点的瞬间，L = 冰刀首次接触冰面的瞬间。\n"
        "   - 只看主滑行者；如果有旁人或近景遮挡经过，忽略遮挡物造成的大运动量。\n"
        "   - L 必须是第一次触冰，不是落冰后滑出、重新露出画面或手臂打开的时间。\n"
        "   - 如果实际动作不是跳跃，T/A/L 必须保持 null，不要编造 takeoff/air/landing。\n"
        "5. 输出宏观技术评价：节奏、速度、轴心、入跳/入转、落冰/出转/滑出、整体流畅度。\n"
        "6. 输出整体印象和置信度。\n"
        "7. 如果主滑行者不清楚、多人遮挡、画面太远或动作不完整，请降低 confidence 并说明原因。\n\n"
        f"{mixed_action_section}"
        "只输出 JSON，schema_version 必须为 \"video_temporal_v1\"。\n"
        f"简洁 JSON schema 示例：{json.dumps(schema_hint, ensure_ascii=False, separators=(',', ':'))}"
        f"{retry_section}"
    )
    return system_prompt, user_prompt


def _compact_retry_context_json(retry_context: dict[str, Any], limit: int = RETRY_CONTEXT_JSON_LIMIT) -> str:
    def encoded(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))

    compact = _compact_retry_context_payload(retry_context)
    retry_json = encoded(compact)
    if len(retry_json) <= limit:
        return retry_json

    for motion_count in (6, 4, 3, 2):
        for selected_count in (4, 3, 2, 0):
            compact = _compact_retry_context_payload(
                retry_context,
                motion_count=motion_count,
                selected_count=selected_count,
                quality_flag_count=8,
                hint_count=3,
            )
            retry_json = encoded(compact)
            if len(retry_json) <= limit:
                return retry_json

    minimal = _compact_retry_context_payload(
        retry_context,
        motion_count=2,
        selected_count=0,
        quality_flag_count=4,
        hint_count=2,
    )
    minimal["context_truncated"] = True
    retry_json = encoded(minimal)
    if len(retry_json) <= limit:
        return retry_json
    return encoded(
        {
            "retry_reason_flags": minimal.get("retry_reason_flags", []),
            "retry_instruction_hints": minimal.get("retry_instruction_hints", []),
            "requested_analysis_profile": minimal.get("requested_analysis_profile"),
            "provider_action_family": minimal.get("provider_action_family"),
            "profile_mismatch": minimal.get("profile_mismatch"),
            "rejected_key_moments": minimal.get("rejected_key_moments"),
            "action_window": minimal.get("action_window"),
            "top_motion_records": minimal.get("top_motion_records", []),
            "context_truncated": True,
        }
    )


def _compact_retry_context_payload(
    retry_context: dict[str, Any],
    *,
    motion_count: int = 8,
    selected_count: int = 6,
    quality_flag_count: int = 10,
    hint_count: int = 4,
) -> dict[str, Any]:
    return {
        "retry_reason_flags": _compact_string_list(retry_context.get("retry_reason_flags"), quality_flag_count),
        "retry_instruction_hints": _compact_string_list(retry_context.get("retry_instruction_hints"), hint_count),
        "requested_analysis_profile": retry_context.get("requested_analysis_profile"),
        "provider_action_family": retry_context.get("provider_action_family"),
        "profile_mismatch": retry_context.get("profile_mismatch"),
        "rejected_key_moments": retry_context.get("rejected_key_moments"),
        "rejected_selected_frames": _compact_selected_frames(retry_context.get("rejected_selected_frames"), selected_count),
        "video_quality_flags": _compact_string_list(retry_context.get("video_quality_flags"), quality_flag_count),
        "resolver_quality_flags": _compact_string_list(retry_context.get("resolver_quality_flags"), quality_flag_count),
        "skeleton_candidate_tal": _compact_skeleton_candidate_tal(retry_context.get("skeleton_candidate_tal")),
        "keyframe_candidate_quality_flags": _compact_string_list(retry_context.get("keyframe_candidate_quality_flags"), quality_flag_count),
        "rejected_source": retry_context.get("rejected_source"),
        "action_window": retry_context.get("action_window"),
        "top_motion_records": _compact_motion_records(retry_context.get("top_motion_records"), motion_count),
    }


def _compact_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list) or limit <= 0:
        return []
    return [str(item) for item in value[:limit] if item is not None]


def _compact_selected_frames(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or limit <= 0:
        return []
    selected: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        selected.append(
            {
                "phase": item.get("phase_code"),
                "t": item.get("timestamp"),
                "km": item.get("key_moment"),
                "reason": item.get("selection_reason"),
                "start": item.get("phase_time_start"),
                "end": item.get("phase_time_end"),
            }
        )
    return selected


def _compact_skeleton_candidate_tal(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    records: list[dict[str, Any]] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "key": item.get("key"),
                "t": item.get("timestamp"),
                "conf": item.get("confidence"),
                "raw_conf": item.get("raw_confidence"),
                "delta": item.get("delta_from_rejected_tal_sec"),
            }
        )
    return records


def _compact_motion_records(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or limit <= 0:
        return []
    records: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "t": item.get("timestamp"),
                "score": item.get("motion_score"),
                "frame": item.get("frame_id"),
                "relation": item.get("relation_to_rejected_tal"),
            }
        )
    return records


def normalize_video_temporal_payload(raw: Any, provider: str, model: str) -> dict[str, Any]:
    """
    Normalize model output into the video_temporal_v1 contract.

    The function is intentionally forgiving: malformed inputs return a diagnostic
    payload with valid=False instead of raising, so callers can fall back to the
    existing sampled-frame pipeline.
    """
    parsed, parse_flags, parse_diagnostics = _parse_raw_payload(raw)
    if parsed is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "provider": _string(provider, "unknown"),
            "model": _string(model, DEFAULT_MODEL),
            "valid": False,
            "action_confirmation": {
                "action_family": "unknown",
                "confirmed_action": "不可分析",
                "jump_type": "",
                "confidence": 0.0,
                "notes": "",
            },
            "phase_segments": [],
            "key_moments": {key: None for key in KEY_MOMENT_KEYS},
            "macro_assessment": _normalize_macro_assessment({}),
            "overall_impression": "",
            "camera_view": "unknown",
            "data_quality_hint": "poor",
            "confidence": 0.0,
            "fallback_recommendation": "use_sampled_frames",
            "quality_flags": parse_flags,
            "validation": {
                "valid": False,
                "errors": parse_flags,
                "warnings": [],
            },
            **parse_diagnostics,
        }

    flags = _merge_flags(parsed.get("quality_flags"), parse_flags)
    action_confirmation = _normalize_action_confirmation(parsed)
    phase_segments = _normalize_phase_segments(parsed, flags)
    action_confirmation["action_family"] = _infer_action_family(action_confirmation, phase_segments)

    data_quality_hint = _string(parsed.get("data_quality_hint"), "partial").lower()
    if data_quality_hint not in VALID_DATA_QUALITY_HINTS:
        data_quality_hint = "partial"
        flags.append("video_temporal_invalid_data_quality_hint")

    camera_view = _string(parsed.get("camera_view"), "unknown")
    if camera_view not in CAMERA_VIEWS:
        camera_view = "unknown"
        flags.append("video_temporal_invalid_camera_view")

    fallback_recommendation = _string(parsed.get("fallback_recommendation"), "use_video_timestamps")
    if fallback_recommendation not in VALID_FALLBACK_RECOMMENDATIONS:
        fallback_recommendation = "use_sampled_frames"
        flags.append("video_temporal_invalid_fallback_recommendation")

    if parsed.get("schema_version") != SCHEMA_VERSION:
        flags.append("video_temporal_schema_version_normalized")

    diagnostics = (
        _raw_response_diagnostics(raw, "normalized payload missing phase_segments")
        if not phase_segments and "raw_response_excerpt" not in parsed
        else {}
    )
    parsed_diagnostics = {
        key: parsed.get(key)
        for key in ("raw_response_excerpt", "raw_response_length", "raw_response_truncated", "parse_error_detail")
        if key in parsed
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "provider": _string(provider, "unknown"),
        "model": _string(model, DEFAULT_MODEL),
        "valid": True,
        "action_confirmation": action_confirmation,
        "phase_segments": phase_segments,
        "key_moments": _normalize_key_moments(parsed),
        "macro_assessment": _normalize_macro_assessment(parsed),
        "overall_impression": _string(parsed.get("overall_impression") or parsed.get("overall_raw_text")),
        "camera_view": camera_view,
        "data_quality_hint": data_quality_hint,
        "confidence": _clamp_confidence(parsed.get("confidence", action_confirmation.get("confidence", 0.0))),
        "fallback_recommendation": fallback_recommendation,
        "quality_flags": _merge_flags(flags),
        **parsed_diagnostics,
        **diagnostics,
    }


def _video_temporal_failure_flag(exc: Exception) -> str:
    failure = classify_ai_failure(exc)
    if failure.code == AnalysisErrorCode.AI_API_TIMEOUT:
        return "video_temporal_timeout"
    if failure.code == AnalysisErrorCode.AI_API_QUOTA_EXCEEDED:
        return "video_temporal_budget_exceeded"
    if failure.code == AnalysisErrorCode.AI_API_AUTH_ERROR:
        return "video_temporal_auth_error"
    return "video_temporal_provider_error"


def _qwen_temporal_provider(provider: ActiveProviderConfig) -> ActiveProviderConfig:
    model_id = _string(provider.vision_model) or _string(provider.model_id) or DEFAULT_MODEL
    return ActiveProviderConfig(
        id=provider.id,
        slot=provider.slot,
        name=provider.name,
        provider=provider.provider,
        base_url=provider.base_url,
        model_id=model_id,
        vision_model=provider.vision_model,
        api_key=provider.api_key,
        notes=provider.notes,
    )


def _shift_video_temporal_timestamps(payload: dict[str, Any], offset_sec: float) -> dict[str, Any]:
    offset = _to_float(offset_sec)
    if offset is None or abs(offset) < 1e-6:
        return payload

    shifted = dict(payload)
    shifted["timestamp_offset_sec"] = round(offset, 3)

    segments: list[dict[str, Any]] = []
    for segment in payload.get("phase_segments") or []:
        if not isinstance(segment, dict):
            continue
        item = dict(segment)
        for key in ("time_start", "time_end", "key_frame_hint"):
            value = _to_float(item.get(key))
            if value is not None:
                item[key] = round(value + offset, 3)
        segments.append(item)
    shifted["phase_segments"] = segments

    key_moments = payload.get("key_moments")
    if isinstance(key_moments, dict):
        shifted_moments: dict[str, Any] = {}
        for key, value in key_moments.items():
            timestamp = _to_float(value)
            shifted_moments[key] = round(timestamp + offset, 3) if timestamp is not None else None
        shifted["key_moments"] = shifted_moments
    return shifted


async def analyze_video_temporal(
    video_path: Path,
    *,
    action_type: str,
    action_subtype: str | None = None,
    user_note: str | None = None,
    video_duration_sec: float | None = None,
    source_video_duration_sec: float | None = None,
    source_fps: float | None = None,
    timestamp_offset_sec: float = 0.0,
    analyzed_video_kind: str = "source",
    retry_context: dict[str, Any] | None = None,
    session: AsyncSession | None = None,
    provider: ActiveProviderConfig | None = None,
    timeout: float = VIDEO_TEMPORAL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Run Qwen 3.6 Plus video semantic phase localization.

    This is a soft-fail API: every provider, timeout, budget, and parse failure
    returns a diagnostic payload so the existing skeleton/sample-frame path can
    continue.
    """
    try:
        active_provider = provider or await get_active_provider("vision", session)
    except Exception as exc:  # noqa: BLE001
        flag = _video_temporal_failure_flag(exc)
        return _fallback_video_temporal_payload(
            provider="unknown",
            model=DEFAULT_MODEL,
            reason=flag,
            quality_flags=[flag],
            detail=str(exc),
        )

    provider_name = _string(getattr(active_provider, "provider", ""), "unknown").lower()
    if provider_name not in {"qwen", "mimo"}:
        return _fallback_video_temporal_payload(
            provider=provider_name,
            model=DEFAULT_MODEL,
            reason="video_temporal_provider_not_qwen",
            quality_flags=["video_temporal_provider_not_qwen"],
            detail="Video temporal localization v1 only uses qwen or mimo.",
        )

    request_provider = _qwen_temporal_provider(active_provider) if provider_name == "qwen" else active_provider
    request_model = _string(request_provider.model_id) or (DEFAULT_MODEL if provider_name == "qwen" else DEFAULT_MIMO_VISION_MODEL)
    system_prompt, user_prompt = build_video_temporal_prompts(
        action_type=action_type,
        action_subtype=action_subtype,
        user_note=user_note,
        video_duration_sec=video_duration_sec,
        source_fps=source_fps,
        model=request_model,
        retry_context=retry_context,
    )

    try:
        if provider_name == "qwen":
            raw = await request_dashscope_video_completion(
                request_provider,
                video_path=video_path,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=VIDEO_TEMPORAL_TEMPERATURE,
                max_tokens=VIDEO_TEMPORAL_MAX_TOKENS,
                timeout=timeout,
            )
        else:
            raw = await request_mimo_video_completion(
                request_provider,
                video_path=video_path,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=VIDEO_TEMPORAL_TEMPERATURE,
                max_tokens=VIDEO_TEMPORAL_MAX_TOKENS,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
    except Exception as exc:  # noqa: BLE001
        flag = _video_temporal_failure_flag(exc)
        return _fallback_video_temporal_payload(
            provider=provider_name,
            model=request_model,
            reason=flag,
            quality_flags=[flag],
            detail=str(exc),
        )

    normalized = normalize_video_temporal_payload(raw, provider=provider_name, model=request_model)
    if not normalized.get("valid"):
        flags = _merge_flags(normalized.get("quality_flags"), ["video_temporal_parse_failed"])
        normalized["quality_flags"] = flags
        normalized["fallback_recommendation"] = "use_existing_skeleton_timestamps"
        normalized["fallback_reason"] = "video_temporal_parse_failed"
        normalized["valid"] = False
        normalized["validation"] = {
            "valid": False,
            "errors": flags,
            "warnings": [],
        }
        return normalized

    normalized["analyzed_video_kind"] = _string(analyzed_video_kind, "source")
    normalized["analyzed_video_path"] = str(video_path)
    normalized["timestamp_offset_sec"] = round(float(timestamp_offset_sec or 0.0), 3)
    shifted = _shift_video_temporal_timestamps(normalized, float(timestamp_offset_sec or 0.0))

    validation_duration = source_video_duration_sec
    if validation_duration is None and video_duration_sec is not None:
        validation_duration = float(video_duration_sec) + max(0.0, float(timestamp_offset_sec or 0.0))

    if validation_duration is not None:
        return validate_video_temporal_payload(shifted, duration_sec=validation_duration)
    return shifted


def _candidate_timestamp(candidate: Any) -> float | None:
    if not isinstance(candidate, dict):
        return None
    for key in ("timestamp", "timestamp_sec", "time_sec"):
        value = _to_float(candidate.get(key))
        if value is not None:
            return value
    return None


def _candidate_confidence(candidate: Any) -> float:
    if not isinstance(candidate, dict):
        return 0.0
    return _clamp_confidence(candidate.get("confidence"), default=0.0)


def _skeleton_candidates(skeleton_timestamps: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(skeleton_timestamps, dict):
        return {}
    source = skeleton_timestamps.get("key_frame_candidates")
    if isinstance(source, dict):
        return {str(key): value for key, value in source.items() if isinstance(value, dict)}
    return {str(key): value for key, value in skeleton_timestamps.items() if key in {"T", "A", "L"} and isinstance(value, dict)}


def _motion_selected_records(motion_scores: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(motion_scores, dict):
        return []
    selected = motion_scores.get("selected")
    if isinstance(selected, list):
        return [item for item in selected if isinstance(item, dict)]
    return []


def _motion_records_from_scores(motion_scores: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(motion_scores, dict):
        return []

    scores = [
        float(score)
        for score in motion_scores.get("scores", [])
        if isinstance(score, (int, float)) and not math.isnan(float(score)) and not math.isinf(float(score))
    ]
    frame_rate = _to_float(motion_scores.get("frame_rate"))
    window_start = _to_float(motion_scores.get("window_start"))
    if scores and frame_rate is not None and frame_rate > 0 and window_start is not None:
        return [
            {
                "timestamp": round(window_start + (index / frame_rate), 3),
                "motion_score": round(score, 4),
                "source": "motion_score_series",
            }
            for index, score in enumerate(scores)
        ]

    return _motion_selected_records(motion_scores)


def _motion_score_value(record: dict[str, Any]) -> float:
    value = _to_float(record.get("motion_score"))
    return value if value is not None else 0.0


def _records_in_range(records: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        timestamp = _to_float(record.get("timestamp"))
        if timestamp is not None and start <= timestamp <= end:
            out.append(record)
    return out


def _motion_peak_in_range(records: list[dict[str, Any]], start: float, end: float) -> float | None:
    candidates = _records_in_range(records, start, end)
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (_motion_score_value(item), -abs((_to_float(item.get("timestamp")) or start) - ((start + end) / 2))))
    return _to_float(best.get("timestamp"))


def _motion_peak_score_in_range(records: list[dict[str, Any]], start: float, end: float) -> float:
    return max((_motion_score_value(record) for record in _records_in_range(records, start, end)), default=0.0)


def _motion_peak_near(records: list[dict[str, Any]], target: float, start: float, end: float, tolerance: float = MOTION_SNAP_TOLERANCE_SECONDS) -> float | None:
    candidates = _records_in_range(records, max(start, target - tolerance), min(end, target + tolerance))
    if not candidates:
        return None
    best = max(candidates, key=lambda item: (_motion_score_value(item), -abs((_to_float(item.get("timestamp")) or target) - target)))
    phase_peak = max((_motion_score_value(item) for item in _records_in_range(records, start, end)), default=0.0)
    best_score = _motion_score_value(best)
    if phase_peak > 0 and best_score < max(0.35, phase_peak * 0.50):
        return None
    timestamp = _to_float(best.get("timestamp"))
    return timestamp if timestamp is not None and abs(timestamp - target) <= tolerance else None


def _phase_code_for_skeleton_label(label: str) -> str:
    return {"T": "takeoff", "A": "air", "L": "landing"}[label]


def _resolve_skeleton_candidate_timestamp(
    *,
    label: str,
    candidate: dict[str, Any],
    motion_records: list[dict[str, Any]],
    start: float,
    end: float,
    fallback: bool = False,
) -> tuple[float | None, str, list[str]]:
    flags: list[str] = []
    timestamp = _candidate_timestamp(candidate)
    if timestamp is None or timestamp < start or timestamp > end:
        return None, "skeleton_candidate_invalid", flags

    phase_code = _phase_code_for_skeleton_label(label)
    confidence = _candidate_confidence(candidate)
    required_confidence = SKELETON_FALLBACK_CONFIDENCE if fallback else SKELETON_ANCHOR_CONFIDENCE
    if confidence < required_confidence:
        flags.append(f"video_temporal_resolver_skeleton_{label.lower()}_below_anchor_confidence")
        return None, "skeleton_candidate_below_anchor_confidence", flags

    if phase_code in MOTION_PEAK_PHASES:
        snapped = _motion_peak_near(motion_records, timestamp, start, end)
        if snapped is not None:
            reason = "skeleton_fallback_motion_peak" if fallback else f"video_phase_range_skeleton_{phase_code}_motion_peak"
            return snapped, reason, flags
        reason = "skeleton_fallback_candidate" if fallback else f"video_phase_range_skeleton_{phase_code}_anchor"
        return timestamp, reason, flags

    if confidence >= required_confidence:
        reason = "skeleton_fallback_apex_preserved" if fallback else "video_phase_range_skeleton_apex"
        return timestamp, reason, flags

    flags.append(f"video_temporal_resolver_skeleton_{label.lower()}_below_anchor_confidence")
    return None, "skeleton_candidate_below_anchor_confidence", flags


def _fallback_skeleton_selected(
    candidates: dict[str, dict[str, Any]],
    *,
    video_duration_sec: float,
    max_frames: int,
    motion_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    selected: list[dict[str, Any]] = []
    flags: list[str] = []
    for index, (label, key_moment) in enumerate(
        (("T", "T_takeoff_sec"), ("A", "A_air_sec"), ("L", "L_landing_sec")),
        start=1,
    ):
        candidate = candidates.get(label)
        if not isinstance(candidate, dict):
            continue
        raw_timestamp = _candidate_timestamp(candidate)
        if raw_timestamp is None or raw_timestamp < 0 or raw_timestamp > video_duration_sec:
            continue
        start = max(0.0, raw_timestamp - FALLBACK_MOTION_WINDOW_SECONDS)
        end = min(video_duration_sec, raw_timestamp + FALLBACK_MOTION_WINDOW_SECONDS)
        timestamp, reason, candidate_flags = _resolve_skeleton_candidate_timestamp(
            label=label,
            candidate=candidate,
            motion_records=motion_records,
            start=start,
            end=end,
            fallback=True,
        )
        flags.extend(candidate_flags)
        if timestamp is None:
            continue
        phase_code = _phase_code_for_skeleton_label(label)
        selected.append(
            {
                "frame_id": f"semantic_{index:04d}",
                "timestamp": round(timestamp, 3),
                "phase_code": phase_code,
                "phase_label": PHASE_LABELS[phase_code],
                "key_moment": key_moment,
                "selection_reason": reason,
                "confidence": _candidate_confidence(candidate),
            }
        )
        if len(selected) >= max_frames:
            break
    return selected, flags


def _motion_cluster_from_records(
    records: list[dict[str, Any]],
    *,
    min_score: float,
    score_ratio: float,
    min_records: int,
    min_span_seconds: float,
    max_gap_seconds: float,
    mode: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    if not records:
        return None
    valid_records = [
        record
        for record in records
        if _to_float(record.get("timestamp")) is not None and _motion_score_value(record) > 0
    ]
    if not valid_records:
        return None
    global_peak = max((_motion_score_value(record) for record in valid_records), default=0.0)
    threshold = max(min_score, global_peak * score_ratio)
    strong_records = [record for record in valid_records if _motion_score_value(record) >= threshold]
    if len(strong_records) < min_records:
        return None

    strong_records.sort(key=lambda record: _to_float(record.get("timestamp")) or 0.0)
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    last_ts: float | None = None
    for record in strong_records:
        timestamp = _to_float(record.get("timestamp"))
        if timestamp is None:
            continue
        if current and last_ts is not None and timestamp - last_ts > max_gap_seconds:
            clusters.append(current)
            current = []
        current.append(record)
        last_ts = timestamp
    if current:
        clusters.append(current)
    if not clusters:
        return None

    def cluster_key(cluster: list[dict[str, Any]]) -> tuple[float, float, float]:
        peak = max((_motion_score_value(record) for record in cluster), default=0.0)
        span_start = _to_float(cluster[0].get("timestamp")) or 0.0
        span_end = _to_float(cluster[-1].get("timestamp")) or span_start
        return (peak, span_end - span_start, span_start)

    cluster = max(clusters, key=cluster_key)
    start_ts = _to_float(cluster[0].get("timestamp"))
    end_ts = _to_float(cluster[-1].get("timestamp"))
    if start_ts is None or end_ts is None:
        return None
    if end_ts - start_ts < min_span_seconds:
        return None
    peak_record = max(cluster, key=_motion_score_value)
    peak_ts = _to_float(peak_record.get("timestamp"))
    if peak_ts is None:
        return None
    return cluster, {
        "start_sec": round(start_ts, 3),
        "end_sec": round(end_ts, 3),
        "peak_sec": round(peak_ts, 3),
        "peak_score": round(_motion_score_value(peak_record), 4),
        "threshold": round(threshold, 4),
        "record_count": len(cluster),
        "mode": mode,
    }


def _strong_motion_cluster(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    return _motion_cluster_from_records(
        records,
        min_score=JUMP_MOTION_CLUSTER_FALLBACK_MIN_SCORE,
        score_ratio=JUMP_MOTION_CLUSTER_FALLBACK_SCORE_RATIO,
        min_records=JUMP_MOTION_CLUSTER_FALLBACK_MIN_RECORDS,
        min_span_seconds=JUMP_MOTION_CLUSTER_FALLBACK_MIN_SPAN_SECONDS,
        max_gap_seconds=JUMP_MOTION_CLUSTER_FALLBACK_MAX_GAP_SECONDS,
        mode="strong",
    )


def _weak_motion_cluster(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    return _motion_cluster_from_records(
        records,
        min_score=JUMP_WEAK_MOTION_CLUSTER_FALLBACK_MIN_SCORE,
        score_ratio=JUMP_MOTION_CLUSTER_FALLBACK_SCORE_RATIO,
        min_records=JUMP_MOTION_CLUSTER_FALLBACK_MIN_RECORDS,
        min_span_seconds=JUMP_MOTION_CLUSTER_FALLBACK_MIN_SPAN_SECONDS,
        max_gap_seconds=JUMP_WEAK_MOTION_CLUSTER_FALLBACK_MAX_GAP_SECONDS,
        mode="weak",
    )


def _nearest_record_timestamp(records: list[dict[str, Any]], target: float) -> float | None:
    if not records:
        return None
    best = min(records, key=lambda record: abs((_to_float(record.get("timestamp")) or target) - target))
    return _to_float(best.get("timestamp"))


def _best_record_timestamp_in_range(records: list[dict[str, Any]], start: float, end: float) -> float | None:
    candidates = _records_in_range(records, start, end)
    if not candidates:
        return None
    best = max(candidates, key=lambda record: (_motion_score_value(record), -abs((_to_float(record.get("timestamp")) or start) - ((start + end) / 2.0))))
    return _to_float(best.get("timestamp"))


def _nearest_record_timestamp_in_range(records: list[dict[str, Any]], target: float, start: float, end: float) -> float | None:
    candidates = _records_in_range(records, start, end)
    if not candidates:
        return None
    best = min(candidates, key=lambda record: abs((_to_float(record.get("timestamp")) or target) - target))
    return _to_float(best.get("timestamp"))


def _jump_motion_cluster_fallback_selected(
    *,
    analysis_profile: str | None,
    video_ai_result: dict[str, Any] | None,
    motion_records: list[dict[str, Any]],
    skeleton_candidates: dict[str, dict[str, Any]],
    fallback_selected: list[dict[str, Any]],
    video_duration_sec: float,
    max_frames: int,
    existing_flags: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    if str(analysis_profile or "").strip().lower() != "jump" or max_frames < 3 or video_duration_sec <= 0:
        return [], []
    if _selected_has_complete_ordered_core_tal(fallback_selected, min_confidence=SKELETON_FALLBACK_CONFIDENCE):
        return [], []
    flag_set = set(existing_flags)
    if not (
        "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in flag_set
        or "video_temporal_resolver_partial_skeleton_fallback" in flag_set
        or "video_temporal_resolver_video_fallback_recommended" in flag_set
        or "video_temporal_resolver_low_video_confidence" in flag_set
        or "video_temporal_resolver_missing_video_ai" in flag_set
    ):
        return [], []

    cluster_mode = "strong"
    cluster_result = _strong_motion_cluster(motion_records)
    if cluster_result is None and "video_temporal_resolver_coherent_tal_weak_jump_late_main_motion_cluster_conflict" in flag_set:
        cluster_result = _weak_motion_cluster(motion_records)
        cluster_mode = "weak"
    if cluster_result is None:
        return [], []
    cluster, diagnostics = cluster_result
    cluster_start = _to_float(cluster[0].get("timestamp"))
    cluster_end = _to_float(cluster[-1].get("timestamp"))
    cluster_peak = _to_float(diagnostics.get("peak_sec"))
    if cluster_start is None or cluster_end is None or cluster_peak is None:
        return [], []

    takeoff_candidate = skeleton_candidates.get("T")
    apex_candidate = skeleton_candidates.get("A")
    landing_candidate = skeleton_candidates.get("L")
    skeleton_takeoff_ts = _candidate_timestamp(takeoff_candidate) if isinstance(takeoff_candidate, dict) else None
    skeleton_takeoff_conf = _candidate_confidence(takeoff_candidate) if isinstance(takeoff_candidate, dict) else 0.0
    skeleton_apex_ts = _candidate_timestamp(apex_candidate) if isinstance(apex_candidate, dict) else None
    skeleton_apex_conf = _candidate_confidence(apex_candidate) if isinstance(apex_candidate, dict) else 0.0
    skeleton_landing_ts = _candidate_timestamp(landing_candidate) if isinstance(landing_candidate, dict) else None
    skeleton_landing_conf = _candidate_confidence(landing_candidate) if isinstance(landing_candidate, dict) else 0.0
    takeoff_anchor_supports_cluster = (
        skeleton_takeoff_ts is not None
        and skeleton_takeoff_conf >= SKELETON_ANCHOR_CONFIDENCE
        and (
            cluster_start - 0.15 <= skeleton_takeoff_ts <= cluster_peak + 0.10
            or (
                cluster_mode == "weak"
                and cluster_start - 0.15 <= skeleton_takeoff_ts <= cluster_end + 0.20
            )
        )
    )
    apex_landing_anchors_support_cluster = (
        skeleton_apex_ts is not None
        and skeleton_landing_ts is not None
        and skeleton_apex_conf >= JUMP_MOTION_CLUSTER_FALLBACK_APEX_MIN_CONFIDENCE
        and skeleton_landing_conf >= SKELETON_FALLBACK_CONFIDENCE
        and cluster_start - 0.20 <= skeleton_apex_ts <= cluster_end
        and cluster_start <= skeleton_landing_ts <= cluster_end + 0.15
        and skeleton_apex_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS < skeleton_landing_ts
    )
    if not (takeoff_anchor_supports_cluster or apex_landing_anchors_support_cluster):
        return [], []
    if not isinstance(video_ai_result, dict) or _video_temporal_has_severe_occlusion_risk(video_ai_result):
        return [], []
    key_moments = video_ai_result.get("key_moments") if isinstance(video_ai_result.get("key_moments"), dict) else {}
    rejected_t = _to_float(key_moments.get("T_takeoff_sec"))
    rejected_a = _to_float(key_moments.get("A_air_sec"))
    rejected_l = _to_float(key_moments.get("L_landing_sec"))
    if not (
        rejected_t is not None
        and rejected_a is not None
        and rejected_l is not None
        and rejected_t + SEMANTIC_ORDER_MIN_GAP_SECONDS < rejected_a
        and rejected_a + SEMANTIC_ORDER_MIN_GAP_SECONDS < rejected_l
        and (
            (
                rejected_t <= cluster_start - JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_TAKEOFF_LEAD_SECONDS
                and rejected_a <= cluster_start - JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
                and rejected_l <= cluster_start + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_LANDING_TOLERANCE_SECONDS
                and cluster_peak >= rejected_l + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_PEAK_LAG_SECONDS
            )
            or (
                "video_temporal_resolver_coherent_tal_weak_jump_late_main_motion_cluster_conflict" in flag_set
                and (
                    rejected_t >= cluster_start + MOTION_SNAP_TOLERANCE_SECONDS
                    or (
                        cluster_mode == "weak"
                        and takeoff_anchor_supports_cluster
                        and skeleton_takeoff_ts is not None
                        and rejected_t - skeleton_takeoff_ts >= JUMP_WEAK_MOTION_CLUSTER_FALLBACK_SEMANTIC_SHIFT_SECONDS
                    )
                )
                and rejected_a >= cluster_start + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
                and rejected_l >= cluster_end + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
                and rejected_l <= cluster_end + JUMP_WEAK_MOTION_CLUSTER_FALLBACK_LOOKAHEAD_SECONDS
            )
            or (
                "video_temporal_quality_retry_extreme_late_motion_cluster_conflict" in flag_set
                and cluster_mode == "weak"
                and takeoff_anchor_supports_cluster
                and skeleton_takeoff_ts is not None
                and rejected_t - skeleton_takeoff_ts >= JUMP_WEAK_MOTION_CLUSTER_FALLBACK_SEMANTIC_SHIFT_SECONDS
                and rejected_a >= cluster_start + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
                and rejected_l >= cluster_end + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
            )
            or (
                "video_temporal_resolver_coherent_tal_late_main_motion_cluster_conflict" in flag_set
                and rejected_t >= cluster_start - JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_TAKEOFF_TOLERANCE_SECONDS
                and rejected_a >= cluster_start + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_APEX_LEAD_SECONDS
                and rejected_l >= cluster_end + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_LANDING_DRIFT_SECONDS
                and rejected_l <= cluster_end + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_LOOKAHEAD_SECONDS
            )
            or (
                "video_temporal_resolver_coherent_tal_late_motion_conflict" in flag_set
                and rejected_t >= cluster_start - JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_TAKEOFF_TOLERANCE_SECONDS
                and rejected_a >= cluster_start + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_APEX_LEAD_SECONDS
                and rejected_l >= cluster_end + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_LANDING_DRIFT_SECONDS
                and rejected_l <= cluster_end + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_LOOKAHEAD_SECONDS
            )
            or (
                "video_temporal_resolver_coherent_tal_late_motion_conflict" in flag_set
                and rejected_t >= cluster_start - JUMP_COHERENT_TAL_MIXED_CLUSTER_TAKEOFF_LEAD_SECONDS
                and rejected_t <= cluster_start + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_TAKEOFF_TOLERANCE_SECONDS
                and rejected_a >= cluster_start - MOTION_SNAP_TOLERANCE_SECONDS
                and rejected_a <= cluster_end + MOTION_SNAP_TOLERANCE_SECONDS
                and rejected_l >= cluster_end + JUMP_COHERENT_TAL_MIXED_CLUSTER_LANDING_DRIFT_SECONDS
                and rejected_l <= cluster_end + JUMP_COHERENT_TAL_MIXED_CLUSTER_LOOKAHEAD_SECONDS
            )
        )
    ):
        return [], []

    takeoff_ts = cluster_start - JUMP_MOTION_CLUSTER_FALLBACK_TAKEOFF_LEAD_SECONDS
    if takeoff_anchor_supports_cluster and skeleton_takeoff_ts is not None:
        if cluster_mode == "weak":
            takeoff_ts = skeleton_takeoff_ts
        else:
            takeoff_ts = min(takeoff_ts, skeleton_takeoff_ts - max(SEMANTIC_ORDER_MIN_GAP_SECONDS * 2, 0.05))
    takeoff_ts = max(0.0, min(video_duration_sec, takeoff_ts))

    apex_ts: float | None = None
    if (
        cluster_mode != "weak"
        and
        skeleton_apex_ts is not None
        and 0 <= skeleton_apex_ts <= video_duration_sec
        and skeleton_apex_conf >= JUMP_MOTION_CLUSTER_FALLBACK_APEX_MIN_CONFIDENCE
        and cluster_start - 0.20 <= skeleton_apex_ts <= cluster_end
    ):
        apex_ts = skeleton_apex_ts
    elif cluster_mode == "weak":
        apex_floor = max(
            JUMP_WEAK_MOTION_CLUSTER_FALLBACK_TAIL_MIN_SCORE,
            _motion_score_value(max(cluster, key=_motion_score_value)) * JUMP_WEAK_MOTION_CLUSTER_FALLBACK_TAIL_SCORE_RATIO,
        )
        apex_ts = _nearest_record_timestamp_in_range(
            [
                record
                for record in motion_records
                if _motion_score_value(record) >= apex_floor
            ],
            min(video_duration_sec, takeoff_ts + JUMP_WEAK_MOTION_CLUSTER_FALLBACK_APEX_TARGET_SECONDS),
            max(takeoff_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS, cluster_start),
            min(video_duration_sec, cluster_end + JUMP_WEAK_MOTION_CLUSTER_FALLBACK_APEX_TARGET_SECONDS),
        )
        if apex_ts is None:
            apex_ts = _best_record_timestamp_in_range(
                motion_records,
                max(takeoff_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS, cluster_peak),
                min(video_duration_sec, cluster_end + JUMP_WEAK_MOTION_CLUSTER_FALLBACK_APEX_TARGET_SECONDS),
            )
        if apex_ts is None or apex_ts <= takeoff_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS:
            apex_ts = _nearest_record_timestamp(cluster, max(takeoff_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS, cluster_end))
    else:
        apex_ts = _nearest_record_timestamp(cluster, (cluster_start + cluster_peak) / 2.0)
    if apex_ts is None:
        return [], []

    landing_ts = cluster_peak
    if cluster_mode == "weak":
        tail_floor = max(
            JUMP_WEAK_MOTION_CLUSTER_FALLBACK_TAIL_MIN_SCORE,
            _motion_score_value(max(cluster, key=_motion_score_value)) * JUMP_WEAK_MOTION_CLUSTER_FALLBACK_TAIL_SCORE_RATIO,
        )
        landing_ts = _nearest_record_timestamp_in_range(
            [
                record
                for record in motion_records
                if _motion_score_value(record) >= tail_floor
            ],
            min(video_duration_sec, takeoff_ts + JUMP_WEAK_MOTION_CLUSTER_FALLBACK_LANDING_TARGET_SECONDS),
            apex_ts + max(JUMP_MOTION_CLUSTER_FALLBACK_LANDING_MIN_GAP_SECONDS, SEMANTIC_ORDER_MIN_GAP_SECONDS),
            min(video_duration_sec, cluster_end + JUMP_WEAK_MOTION_CLUSTER_FALLBACK_LANDING_TARGET_SECONDS),
        ) or cluster_end
    if landing_ts <= apex_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS:
        later_records = [
            record
            for record in cluster
            if (timestamp := _to_float(record.get("timestamp"))) is not None
            and timestamp >= apex_ts + max(JUMP_MOTION_CLUSTER_FALLBACK_LANDING_MIN_GAP_SECONDS, SEMANTIC_ORDER_MIN_GAP_SECONDS)
        ]
        if later_records:
            landing_ts = _to_float(max(later_records, key=_motion_score_value).get("timestamp")) or landing_ts
        else:
            landing_ts = cluster_end

    if not (
        takeoff_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS < apex_ts
        and apex_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS < landing_ts
        and 0 <= landing_ts <= video_duration_sec
    ):
        return [], []

    confidence = JUMP_MOTION_CLUSTER_FALLBACK_CONFIDENCE
    if cluster_mode == "weak":
        takeoff_phase_start = round(max(0.0, takeoff_ts - 0.20), 3)
        takeoff_phase_end = round(
            min(video_duration_sec, max(takeoff_ts + 0.12, min(apex_ts - SEMANTIC_ORDER_MIN_GAP_SECONDS, takeoff_ts + 0.25))),
            3,
        )
        landing_phase_start = round(max(0.0, apex_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS, landing_ts - 0.20), 3)
        landing_phase_end = round(min(video_duration_sec, landing_ts + 0.18), 3)
    else:
        takeoff_phase_start = round(max(0.0, takeoff_ts - 0.20), 3)
        takeoff_phase_end = round(min(video_duration_sec, cluster_start + 0.10), 3)
        landing_phase_start = round(max(0.0, apex_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS), 3)
        landing_phase_end = round(min(video_duration_sec, cluster_end + 0.12), 3)
    selected = [
        {
            "frame_id": "semantic_0001",
            "timestamp": round(takeoff_ts, 3),
            "phase_code": "takeoff",
            "phase_label": PHASE_LABELS["takeoff"],
            "key_moment": "T_takeoff_sec",
            "selection_reason": "motion_cluster_fallback_takeoff_lead",
            "confidence": confidence,
            "phase_time_start": takeoff_phase_start,
            "phase_time_end": takeoff_phase_end,
            "max_refinement_delta_sec": 0.12,
        },
        {
            "frame_id": "semantic_0002",
            "timestamp": round(apex_ts, 3),
            "phase_code": "air",
            "phase_label": PHASE_LABELS["air"],
            "key_moment": "A_air_sec",
            "selection_reason": (
                "motion_cluster_fallback_skeleton_apex"
                if skeleton_apex_ts is not None and abs(apex_ts - skeleton_apex_ts) < 0.001
                else "motion_cluster_fallback_mid_cluster"
            ),
            "confidence": confidence,
            "phase_time_start": round(max(0.0, takeoff_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS), 3),
            "phase_time_end": round(min(video_duration_sec, landing_ts - SEMANTIC_ORDER_MIN_GAP_SECONDS), 3),
        },
        {
            "frame_id": "semantic_0003",
            "timestamp": round(landing_ts, 3),
            "phase_code": "landing",
            "phase_label": PHASE_LABELS["landing"],
            "key_moment": "L_landing_sec",
            "selection_reason": "motion_cluster_fallback_landing_peak",
            "confidence": confidence,
            "phase_time_start": landing_phase_start,
            "phase_time_end": landing_phase_end,
            "max_refinement_delta_sec": 0.12,
            "visibility_repair_max_delta_sec": 0.12,
            "visibility_repair_preserve_timestamp": True,
        },
    ]
    flags = [
        "video_temporal_resolver_motion_cluster_fallback_used",
        "video_temporal_resolver_motion_cluster_fallback_low_confidence",
    ]
    if cluster_mode == "weak":
        flags.append("video_temporal_resolver_weak_motion_cluster_fallback_used")
        if takeoff_anchor_supports_cluster:
            flags.append("video_temporal_resolver_weak_motion_cluster_takeoff_anchor_used")
        if skeleton_apex_conf < SKELETON_FALLBACK_CONFIDENCE or skeleton_landing_conf < SKELETON_FALLBACK_CONFIDENCE:
            flags.append("video_temporal_resolver_weak_motion_cluster_replaced_low_confidence_apex_landing")
    selected[0]["motion_cluster_diagnostics"] = diagnostics
    return selected[:max_frames], flags


def _valid_video_temporal_for_resolver(video_ai_result: dict[str, Any] | None, duration_sec: float) -> dict[str, Any] | None:
    if not isinstance(video_ai_result, dict):
        return None
    recovered = _recover_video_temporal_from_raw_excerpt(video_ai_result, duration_sec)
    if recovered is not None:
        return recovered
    if video_ai_result.get("schema_version") == SCHEMA_VERSION:
        return validate_video_temporal_payload(video_ai_result, duration_sec)
    normalized = normalize_video_temporal_payload(video_ai_result, provider=str(video_ai_result.get("provider") or "unknown"), model=str(video_ai_result.get("model") or DEFAULT_MODEL))
    return validate_video_temporal_payload(normalized, duration_sec)


def _recover_video_temporal_from_raw_excerpt(video_ai_result: dict[str, Any], duration_sec: float) -> dict[str, Any] | None:
    if video_ai_result.get("phase_segments"):
        return None
    raw_excerpt = video_ai_result.get("raw_response_excerpt")
    if not isinstance(raw_excerpt, str) or not raw_excerpt.strip():
        return None
    provider = str(video_ai_result.get("provider") or "unknown")
    model = str(video_ai_result.get("model") or DEFAULT_MODEL)
    normalized = normalize_video_temporal_payload(raw_excerpt, provider=provider, model=model)
    if not normalized.get("phase_segments"):
        return None
    offset = _to_float(video_ai_result.get("timestamp_offset_sec")) or 0.0
    shifted = _shift_video_temporal_timestamps(normalized, offset)
    if offset:
        shifted["timestamp_offset_sec"] = round(offset, 3)
    _fill_key_moments_from_phase_hints(shifted)
    recovered = validate_video_temporal_payload(shifted, duration_sec)
    flags = _merge_flags(
        video_ai_result.get("quality_flags"),
        recovered.get("quality_flags"),
        ["video_temporal_recovered_from_raw_response_excerpt"],
    )
    recovered["quality_flags"] = flags
    if isinstance(recovered.get("validation"), dict):
        recovered["validation"]["warnings"] = _merge_flags(
            recovered["validation"].get("warnings"),
            ["video_temporal_recovered_from_raw_response_excerpt"],
        )
    return recovered


def _fill_key_moments_from_phase_hints(payload: dict[str, Any]) -> None:
    key_moments = payload.get("key_moments") if isinstance(payload.get("key_moments"), dict) else {}
    if all(_to_float(key_moments.get(key)) is not None for key in KEY_MOMENT_KEYS):
        return
    updated = dict(key_moments)
    changed = False
    by_phase = {
        str(segment.get("phase_code") or ""): segment
        for segment in payload.get("phase_segments") or []
        if isinstance(segment, dict)
    }
    for phase_code, key in PHASE_KEY_MOMENTS.items():
        if _to_float(updated.get(key)) is not None:
            continue
        segment = by_phase.get(phase_code)
        if not isinstance(segment, dict):
            continue
        hint = _to_float(segment.get("key_frame_hint"))
        start = _to_float(segment.get("time_start"))
        end = _to_float(segment.get("time_end"))
        if hint is None or start is None or end is None or not (start <= hint <= end):
            continue
        updated[key] = round(hint, 3)
        changed = True
    if changed:
        payload["key_moments"] = updated
        payload["quality_flags"] = _merge_flags(
            payload.get("quality_flags"),
            ["video_temporal_recovered_key_moments_from_phase_hints"],
        )


def _phase_segment_for_key_moment(
    segments: list[dict[str, Any]],
    phase_code: str,
    key_moment_value: float | None,
    duration_sec: float,
    *,
    require_contains: bool = False,
) -> dict[str, Any] | None:
    matching_segments = [
        segment
        for segment in segments
        if isinstance(segment, dict) and str(segment.get("phase_code") or "") == phase_code
    ]
    if not matching_segments:
        return None
    if key_moment_value is not None:
        for segment in matching_segments:
            phase_range = _valid_phase_time_range(segment, duration_sec)
            if phase_range is None:
                continue
            start, end = phase_range
            if start <= key_moment_value <= end:
                return segment
        if require_contains:
            return None
    return matching_segments[0]


def _segment_matches_core_key_moment(
    segment: dict[str, Any],
    key_moments: dict[str, Any],
    duration_sec: float,
    segment_counts: dict[str, int] | None = None,
) -> bool:
    phase_code = str(segment.get("phase_code") or "")
    key = PHASE_KEY_MOMENTS.get(phase_code)
    if key is None:
        return True
    if segment_counts is not None and segment_counts.get(phase_code, 0) <= 1:
        return True
    value = _to_float(key_moments.get(key))
    if value is None:
        return True
    phase_range = _valid_phase_time_range(segment, duration_sec)
    if phase_range is None:
        return False
    start, end = phase_range
    return start <= value <= end


def _valid_phase_time_range(segment: dict[str, Any], duration_sec: float) -> tuple[float, float] | None:
    start = _to_float(segment.get("time_start"))
    end = _to_float(segment.get("time_end"))
    if start is None or end is None or start < 0 or end <= start:
        return None
    if end > duration_sec:
        if end <= duration_sec + VIDEO_TEMPORAL_PHASE_END_TAIL_TOLERANCE_SECONDS:
            end = duration_sec
        else:
            return None
    return start, end


def _video_temporal_has_occlusion_risk(video_ai_result: dict[str, Any] | None) -> bool:
    if not isinstance(video_ai_result, dict):
        return False
    text = _video_temporal_quality_text(video_ai_result)
    return any(term.lower() in text for term in VIDEO_TEMPORAL_OCCLUSION_TERMS)


def _video_temporal_quality_text(video_ai_result: dict[str, Any]) -> str:
    chunks: list[str] = []
    for flag in video_ai_result.get("quality_flags") or []:
        if isinstance(flag, str):
            chunks.append(flag)
    for segment in video_ai_result.get("phase_segments") or []:
        if not isinstance(segment, dict):
            continue
        for key in ("observations", "issues"):
            values = segment.get(key)
            if isinstance(values, list):
                chunks.extend(str(value) for value in values if value is not None)
            elif isinstance(values, str):
                chunks.append(values)
    return " ".join(chunks).lower()


def _video_temporal_has_severe_occlusion_risk(video_ai_result: dict[str, Any] | None) -> bool:
    if not isinstance(video_ai_result, dict):
        return False
    text = _video_temporal_quality_text(video_ai_result)
    return any(term.lower() in text for term in VIDEO_TEMPORAL_SEVERE_OCCLUSION_TERMS)


def _video_temporal_has_small_target_risk(video_ai_result: dict[str, Any] | None) -> bool:
    if not isinstance(video_ai_result, dict):
        return False
    chunks: list[str] = []
    for flag in video_ai_result.get("quality_flags") or []:
        if isinstance(flag, str):
            chunks.append(flag)
    for segment in video_ai_result.get("phase_segments") or []:
        if not isinstance(segment, dict):
            continue
        for key in ("observations", "issues"):
            values = segment.get(key)
            if isinstance(values, list):
                chunks.extend(str(value) for value in values if value is not None)
            elif isinstance(values, str):
                chunks.append(values)
    text = " ".join(chunks).lower()
    return any(term.lower() in text for term in VIDEO_TEMPORAL_SMALL_TARGET_TERMS)


def _video_temporal_mentions_revisible_glide_out(video_ai_result: dict[str, Any] | None) -> bool:
    if not isinstance(video_ai_result, dict):
        return False
    text = _video_temporal_quality_text(video_ai_result)
    return any(term.lower() in text for term in VIDEO_TEMPORAL_REVISIBLE_TERMS) and any(
        term.lower() in text for term in VIDEO_TEMPORAL_GLIDE_OUT_TERMS
    )


def _video_temporal_has_weak_jump_risk(video_ai_result: dict[str, Any] | None) -> bool:
    if not isinstance(video_ai_result, dict):
        return False
    text = _video_temporal_quality_text(video_ai_result)
    return any(term.lower() in text for term in VIDEO_TEMPORAL_WEAK_JUMP_TERMS)


def _video_temporal_has_failed_landing_followthrough(video_ai_result: dict[str, Any] | None) -> bool:
    if not isinstance(video_ai_result, dict):
        return False
    text = _video_temporal_quality_text(video_ai_result)
    return any(term.lower() in text for term in VIDEO_TEMPORAL_FAILED_LANDING_FOLLOWTHROUGH_TERMS)


def _jump_core_phase_motion_is_supported(
    *,
    motion_records: list[dict[str, Any]],
    takeoff_range: tuple[float, float] | None,
    landing_range: tuple[float, float] | None,
    global_peak: float,
    severe_occlusion_risk: bool,
    confidence: float,
) -> bool:
    if severe_occlusion_risk or confidence < JUMP_COHERENT_TAL_CONFIDENCE:
        return False
    if takeoff_range is None or landing_range is None or global_peak <= 0:
        return False

    takeoff_peak = _motion_peak_score_in_range(
        motion_records,
        max(0.0, takeoff_range[0] - MOTION_SNAP_TOLERANCE_SECONDS),
        takeoff_range[1] + MOTION_SNAP_TOLERANCE_SECONDS,
    )
    landing_peak = _motion_peak_score_in_range(
        motion_records,
        max(0.0, landing_range[0] - MOTION_SNAP_TOLERANCE_SECONDS),
        landing_range[1] + MOTION_SNAP_TOLERANCE_SECONDS,
    )
    relative_floor = global_peak * JUMP_COHERENT_TAL_PHASE_MOTION_SUPPORT_RATIO
    return (
        takeoff_peak >= max(JUMP_COHERENT_TAL_PHASE_MOTION_SUPPORT_MIN_SCORE, relative_floor)
        and landing_peak >= max(JUMP_COHERENT_TAL_LANDING_MOTION_SUPPORT_MIN_SCORE, relative_floor)
    )


def _jump_landing_refinement_needs_phase_tolerance(
    *,
    normalized_video: dict[str, Any],
    analysis_profile: str | None,
    phase_code: str,
    explicit_video_fallback: bool,
    coherent_tal_override: bool,
) -> bool:
    if str(analysis_profile or "").strip().lower() != "jump" or phase_code != "landing":
        return False
    quality_flags = [flag for flag in (normalized_video.get("quality_flags") or []) if isinstance(flag, str)]
    if coherent_tal_override and "video_temporal_quality_retry" in quality_flags:
        return True
    if explicit_video_fallback and coherent_tal_override:
        return True
    if _video_temporal_has_small_target_risk(normalized_video):
        return True
    return bool(_video_temporal_mentions_revisible_glide_out(normalized_video))


def _jump_takeoff_refinement_needs_delta_expansion(
    *,
    normalized_video: dict[str, Any],
    analysis_profile: str | None,
    phase_code: str,
    coherent_tal_override: bool,
) -> bool:
    if str(analysis_profile or "").strip().lower() != "jump" or phase_code != "takeoff":
        return False
    if not coherent_tal_override:
        return bool(_video_temporal_has_small_target_risk(normalized_video))
    quality_flags = [flag for flag in (normalized_video.get("quality_flags") or []) if isinstance(flag, str)]
    fallback_recommendation = str(normalized_video.get("fallback_recommendation") or "").strip()
    return (
        "video_temporal_quality_retry" in quality_flags
        or fallback_recommendation != "use_video_timestamps"
        or _video_temporal_has_small_target_risk(normalized_video)
    )


def _coherent_skeleton_tal_anchors(
    skeleton_candidates: dict[str, dict[str, Any]],
    *,
    duration_sec: float,
) -> dict[str, float]:
    anchors: dict[str, float] = {}
    for label in ("T", "A", "L"):
        candidate = skeleton_candidates.get(label)
        if not isinstance(candidate, dict):
            return {}
        timestamp = _candidate_timestamp(candidate)
        if timestamp is None or timestamp < 0 or timestamp > duration_sec:
            return {}
        if _candidate_confidence(candidate) < SKELETON_OCCLUSION_ANCHOR_CONFIDENCE:
            return {}
        anchors[label] = timestamp
    if not (
        anchors["T"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["A"]
        and anchors["A"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["L"]
    ):
        return {}
    return anchors


def _selected_has_complete_ordered_core_tal(
    selected: list[dict[str, Any]],
    *,
    min_confidence: float | None = None,
) -> bool:
    anchors: dict[str, float] = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        key = _semantic_key_from_record(item)
        timestamp = _to_float(item.get("timestamp"))
        if key not in {"T", "A", "L"} or timestamp is None:
            continue
        if min_confidence is not None and _candidate_confidence(item) < min_confidence:
            continue
        anchors[key] = timestamp
    return (
        {"T", "A", "L"}.issubset(anchors)
        and anchors["T"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["A"]
        and anchors["A"] + SEMANTIC_ORDER_MIN_GAP_SECONDS < anchors["L"]
    )


def _weak_retry_motion_conflict_should_preserve_video_tal(
    video_ai_result: dict[str, Any] | None,
    skeleton_candidates: dict[str, dict[str, Any]],
    *,
    confidence: float,
    analysis_profile: str | None,
) -> bool:
    if (
        str(analysis_profile or "").strip().lower() != "jump"
        or not isinstance(video_ai_result, dict)
        or confidence < JUMP_COHERENT_TAL_FALLBACK_GLIDE_OUT_CONFIDENCE
    ):
        return False
    quality_flags = [flag for flag in (video_ai_result.get("quality_flags") or []) if isinstance(flag, str)]
    if "video_temporal_quality_retry" not in quality_flags or not _video_temporal_has_weak_jump_risk(video_ai_result):
        return False
    takeoff = skeleton_candidates.get("T")
    apex = skeleton_candidates.get("A")
    landing = skeleton_candidates.get("L")
    if not isinstance(takeoff, dict) or _candidate_confidence(takeoff) < SKELETON_ANCHOR_CONFIDENCE:
        return False
    if isinstance(apex, dict) and _candidate_confidence(apex) >= SKELETON_FALLBACK_CONFIDENCE:
        return False
    if isinstance(landing, dict) and _candidate_confidence(landing) >= SKELETON_FALLBACK_CONFIDENCE:
        return False
    return True


def _candidate_quality_flags(skeleton_candidates: dict[str, dict[str, Any]]) -> set[str]:
    flags: set[str] = set()
    for candidate in skeleton_candidates.values():
        if not isinstance(candidate, dict):
            continue
        values = candidate.get("quality_flags")
        if isinstance(values, list):
            flags.update(str(flag) for flag in values if isinstance(flag, str))
        values = candidate.get("warnings")
        if isinstance(values, list):
            flags.update(str(flag) for flag in values if isinstance(flag, str))
    return flags


def _retry_tal_can_use_weak_phase_ranges(
    video_ai_result: dict[str, Any],
    skeleton_candidates: dict[str, dict[str, Any]],
    *,
    confidence: float,
    duration_sec: float,
    analysis_profile: str | None,
    tal_anchors: tuple[float, float, float],
) -> bool:
    if str(analysis_profile or "").strip().lower() != "jump":
        return False
    quality_flags = [flag for flag in (video_ai_result.get("quality_flags") or []) if isinstance(flag, str)]
    if "video_temporal_quality_retry" not in quality_flags:
        return False
    if confidence < JUMP_COHERENT_TAL_RETRY_CONFIDENCE_FLOOR:
        return False
    candidate_flags = _candidate_quality_flags(skeleton_candidates)
    if not (candidate_flags & VIDEO_TEMPORAL_WEAK_TAL_CANDIDATE_GEOMETRY_FLAGS):
        return False

    t_value, _, l_value = tal_anchors
    tal_span = l_value - t_value
    if not (
        JUMP_COHERENT_TAL_RETRY_WEAK_PHASE_MIN_SPAN_SECONDS
        <= tal_span
        <= JUMP_COHERENT_TAL_RETRY_WEAK_PHASE_MAX_SPAN_SECONDS
    ):
        return False

    segments = [segment for segment in video_ai_result.get("phase_segments") or [] if isinstance(segment, dict)]
    for phase_code, timestamp in zip(JUMP_CORE_PHASE_CODES, tal_anchors, strict=True):
        segment = _phase_segment_for_key_moment(segments, phase_code, timestamp, duration_sec)
        if not isinstance(segment, dict):
            return False
        phase_range = _valid_phase_time_range(segment, duration_sec)
        if phase_range is None:
            return False
        start, end = phase_range
        if not (start <= timestamp <= end):
            return False
        if _clamp_confidence(segment.get("confidence")) < JUMP_COHERENT_TAL_RETRY_WEAK_GEOMETRY_PHASE_CONFIDENCE:
            return False
    return True


def _jump_coherent_tal_is_usable(
    video_ai_result: dict[str, Any],
    *,
    confidence: float,
    duration_sec: float,
    analysis_profile: str | None,
    skeleton_candidates: dict[str, dict[str, Any]] | None = None,
) -> bool:
    profile = str(analysis_profile or "").strip().lower()
    quality_flags = [flag for flag in (video_ai_result.get("quality_flags") or []) if isinstance(flag, str)]
    is_quality_retry = "video_temporal_quality_retry" in quality_flags
    confidence_floor = JUMP_COHERENT_TAL_RETRY_CONFIDENCE_FLOOR if is_quality_retry else JUMP_COHERENT_TAL_CONFIDENCE
    phase_confidence_floor = JUMP_COHERENT_TAL_RETRY_PHASE_CONFIDENCE if is_quality_retry else JUMP_COHERENT_TAL_PHASE_CONFIDENCE
    if profile != "jump" or confidence < confidence_floor or duration_sec <= 0:
        return False

    validation = video_ai_result.get("validation") if isinstance(video_ai_result.get("validation"), dict) else {}
    if validation.get("errors"):
        return False

    if any(flag in VIDEO_TEMPORAL_HARD_FAILURE_FLAGS for flag in quality_flags):
        return False

    key_moments = video_ai_result.get("key_moments")
    if not isinstance(key_moments, dict):
        return False
    t_value = _to_float(key_moments.get("T_takeoff_sec"))
    a_value = _to_float(key_moments.get("A_air_sec"))
    l_value = _to_float(key_moments.get("L_landing_sec"))
    if t_value is None or a_value is None or l_value is None:
        return False
    if min(t_value, a_value, l_value) < 0 or max(t_value, a_value, l_value) > duration_sec:
        return False
    if not (
        t_value + SEMANTIC_ORDER_MIN_GAP_SECONDS < a_value
        and a_value + SEMANTIC_ORDER_MIN_GAP_SECONDS < l_value
    ):
        return False

    raw_segments = video_ai_result.get("phase_segments")
    if not isinstance(raw_segments, list):
        return False
    segments = [segment for segment in raw_segments if isinstance(segment, dict)]
    expected = {
        "takeoff": t_value,
        "air": a_value,
        "landing": l_value,
    }
    for phase_code, timestamp in expected.items():
        segment = _phase_segment_for_key_moment(segments, phase_code, timestamp, duration_sec)
        if not isinstance(segment, dict):
            return False
        phase_range = _valid_phase_time_range(segment, duration_sec)
        if phase_range is None:
            return False
        start, end = phase_range
        if not (start <= timestamp <= end):
            return False
        if _clamp_confidence(segment.get("confidence")) < phase_confidence_floor:
            if not _retry_tal_can_use_weak_phase_ranges(
                video_ai_result,
                skeleton_candidates or {},
                confidence=confidence,
                duration_sec=duration_sec,
                analysis_profile=analysis_profile,
                tal_anchors=(t_value, a_value, l_value),
            ):
                return False
    return True


def _coherent_profile_phases_are_usable(
    video_ai_result: dict[str, Any],
    *,
    confidence: float,
    duration_sec: float,
    analysis_profile: str | None,
) -> bool:
    profile = str(analysis_profile or "").strip().lower()
    expected_by_profile = {
        "spin": SPIN_RESOLVER_PHASES,
        "spiral": SPIRAL_RESOLVER_PHASES,
        "step": ("step_sequence",),
    }
    expected = expected_by_profile.get(profile)
    confidence_floor = 0.50 if profile == "step" else 0.70
    phase_confidence_floor = 0.65 if profile == "step" and confidence < 0.70 else 0.60
    if expected is None or confidence < confidence_floor or duration_sec <= 0:
        return False

    quality_flags = [flag for flag in (video_ai_result.get("quality_flags") or []) if isinstance(flag, str)]
    if any(flag in VIDEO_TEMPORAL_HARD_FAILURE_FLAGS for flag in quality_flags):
        return False

    validation = video_ai_result.get("validation") if isinstance(video_ai_result.get("validation"), dict) else {}
    segments = [segment for segment in video_ai_result.get("phase_segments", []) if isinstance(segment, dict)]
    hard_errors = [
        flag
        for flag in validation.get("errors", [])
        if isinstance(flag, str) and not re.fullmatch(r"video_temporal_phase_\d+_invalid_code", flag)
    ]
    if hard_errors:
        return False

    by_code = {str(segment.get("phase_code") or ""): segment for segment in segments}
    previous_end: float | None = None
    for phase_code in expected:
        segment = by_code.get(phase_code)
        if not isinstance(segment, dict):
            return False
        phase_range = _valid_phase_time_range(segment, duration_sec)
        if phase_range is None:
            return False
        start, end = phase_range
        hint = _to_float(segment.get("key_frame_hint"))
        if hint is not None and not (start <= hint <= end):
            return False
        if previous_end is not None and start + 0.25 < previous_end:
            return False
        previous_end = end
        if _clamp_confidence(segment.get("confidence")) < phase_confidence_floor:
            return False
    return True


def _effective_non_jump_analysis_profile(
    analysis_profile: str | None,
    video_ai_result: dict[str, Any] | None,
    *,
    confidence: float,
    duration_sec: float,
) -> tuple[str | None, list[str]]:
    requested = str(analysis_profile or "").strip().lower() or None
    if requested not in {"spin", "step", "spiral"} or not isinstance(video_ai_result, dict):
        return requested, []

    action_confirmation = video_ai_result.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        return requested, []
    provider_profile = _normalize_action_family(action_confirmation.get("action_family"))
    if provider_profile not in {"spin", "step", "spiral"} or provider_profile == requested:
        return requested, []

    action_confidence = _clamp_confidence(action_confirmation.get("confidence"), default=confidence)
    low_confidence_step_override = provider_profile == "step" and confidence >= 0.50 and action_confidence >= 0.90
    if not low_confidence_step_override and (confidence < 0.75 or action_confidence < 0.80):
        return requested, []
    if not _coherent_profile_phases_are_usable(
        video_ai_result,
        confidence=confidence,
        duration_sec=duration_sec,
        analysis_profile=provider_profile,
    ):
        return requested, []
    flags = ["video_temporal_resolver_profile_overridden_by_video_ai"]
    if low_confidence_step_override:
        flags.append("video_temporal_resolver_profile_overridden_by_video_ai_low_confidence_step_sequence")
    return provider_profile, flags


def _jump_coherent_tal_motion_conflict_flags(
    video_ai_result: dict[str, Any],
    motion_records: list[dict[str, Any]],
    *,
    confidence: float,
    duration_sec: float,
    explicit_video_fallback: bool,
    occlusion_risk: bool,
    skeleton_candidates: dict[str, dict[str, Any]] | None,
    analysis_profile: str | None,
) -> list[str]:
    profile = str(analysis_profile or "").strip().lower()
    quality_flags = [flag for flag in (video_ai_result.get("quality_flags") or []) if isinstance(flag, str)]
    is_quality_retry = "video_temporal_quality_retry" in quality_flags
    fallback_recommendation = str(video_ai_result.get("fallback_recommendation") or "").strip()
    uses_video_timestamps = fallback_recommendation == "use_video_timestamps"
    is_sampled_frames_fallback = fallback_recommendation == "use_sampled_frames"
    uncertain_timestamp_recommendation = (
        uses_video_timestamps
        and confidence <= JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING
        and "video_temporal_not_high_confidence" in quality_flags
    )
    skeleton_takeoff = skeleton_candidates.get("T") if isinstance(skeleton_candidates, dict) else None
    skeleton_apex = skeleton_candidates.get("A") if isinstance(skeleton_candidates, dict) else None
    skeleton_timeline_check_possible = (
        isinstance(skeleton_takeoff, dict)
        and isinstance(skeleton_apex, dict)
        and _candidate_confidence(skeleton_takeoff) >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_CONFIDENCE
        and _candidate_confidence(skeleton_apex) >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_CONFIDENCE
    )
    small_target_risk = _video_temporal_has_small_target_risk(video_ai_result)
    weak_jump_risk = _video_temporal_has_weak_jump_risk(video_ai_result)
    severe_occlusion_risk = _video_temporal_has_severe_occlusion_risk(video_ai_result)
    revisible_glide_out_risk = _video_temporal_mentions_revisible_glide_out(video_ai_result)
    failed_landing_followthrough = _video_temporal_has_failed_landing_followthrough(video_ai_result)

    key_moments = video_ai_result.get("key_moments")
    if not isinstance(key_moments, dict):
        return []
    t_value = _to_float(key_moments.get("T_takeoff_sec"))
    a_value = _to_float(key_moments.get("A_air_sec"))
    l_value = _to_float(key_moments.get("L_landing_sec"))
    if t_value is None or a_value is None or l_value is None:
        return []
    if not (
        t_value + SEMANTIC_ORDER_MIN_GAP_SECONDS < a_value
        and a_value + SEMANTIC_ORDER_MIN_GAP_SECONDS < l_value
    ):
        return []

    skeleton_takeoff_ts = _candidate_timestamp(skeleton_takeoff) if isinstance(skeleton_takeoff, dict) else None
    skeleton_apex_ts = _candidate_timestamp(skeleton_apex) if isinstance(skeleton_apex, dict) else None
    skeleton_landing = skeleton_candidates.get("L") if isinstance(skeleton_candidates, dict) else None
    skeleton_landing_ts = _candidate_timestamp(skeleton_landing) if isinstance(skeleton_landing, dict) else None
    skeleton_core_candidates = {
        "T": skeleton_takeoff,
        "A": skeleton_apex,
        "L": skeleton_landing,
    }
    skeleton_core_timestamps = {
        key: _candidate_timestamp(candidate) if isinstance(candidate, dict) else None
        for key, candidate in skeleton_core_candidates.items()
    }
    skeleton_core_confidences = [
        _candidate_confidence(candidate)
        for candidate in skeleton_core_candidates.values()
        if isinstance(candidate, dict)
    ]
    near_skeleton_candidate_tal_support = (
        len(skeleton_core_confidences) == 3
        and all(timestamp is not None for timestamp in skeleton_core_timestamps.values())
        and all(
            abs(video_timestamp - float(skeleton_core_timestamps[key])) <= JUMP_COHERENT_TAL_NEAR_SKELETON_CANDIDATE_MAX_DELTA_SECONDS
            for key, video_timestamp in {"T": t_value, "A": a_value, "L": l_value}.items()
        )
        and (
            (sum(skeleton_core_confidences) / len(skeleton_core_confidences)) >= JUMP_COHERENT_TAL_NEAR_SKELETON_CANDIDATE_AVG_CONFIDENCE
            or max(skeleton_core_confidences) >= JUMP_COHERENT_TAL_NEAR_SKELETON_CANDIDATE_STRONG_CONFIDENCE
        )
    )
    skeleton_fallback_timeline_conflict = (
        profile == "jump"
        and explicit_video_fallback
        and skeleton_takeoff_ts is not None
        and skeleton_apex_ts is not None
        and skeleton_landing_ts is not None
        and _candidate_confidence(skeleton_takeoff) >= JUMP_COHERENT_TAL_FALLBACK_SKELETON_CONFLICT_CONFIDENCE
        and _candidate_confidence(skeleton_apex) >= JUMP_COHERENT_TAL_FALLBACK_SKELETON_CONFLICT_CONFIDENCE
        and _candidate_confidence(skeleton_landing) >= JUMP_COHERENT_TAL_FALLBACK_SKELETON_CONFLICT_CONFIDENCE
        and skeleton_takeoff_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS < skeleton_apex_ts
        and skeleton_apex_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS < skeleton_landing_ts
        and t_value - skeleton_takeoff_ts >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_MIN_SHIFT_SECONDS
        and a_value - skeleton_apex_ts >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_MIN_SHIFT_SECONDS
        and l_value - skeleton_landing_ts >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_MIN_SHIFT_SECONDS
    )
    if skeleton_fallback_timeline_conflict and confidence < JUMP_COHERENT_TAL_FALLBACK_GLIDE_OUT_CONFIDENCE:
        return [
            "video_temporal_resolver_coherent_tal_skeleton_timeline_conflict",
            "video_temporal_resolver_coherent_tal_advisory_fallback_skeleton_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]

    if (
        profile != "jump"
        or not (
            explicit_video_fallback
            or occlusion_risk
            or weak_jump_risk
            or is_quality_retry
            or uncertain_timestamp_recommendation
            or skeleton_timeline_check_possible
        )
        or not motion_records
        or duration_sec <= 0
    ):
        return []

    global_peak = max((_motion_score_value(record) for record in motion_records), default=0.0)
    global_peak_record = max(motion_records, key=_motion_score_value, default=None)
    global_peak_ts = _to_float(global_peak_record.get("timestamp")) if isinstance(global_peak_record, dict) else None
    strong_threshold = max(JUMP_COHERENT_TAL_MOTION_CONFLICT_MIN_SCORE, global_peak * 0.65)
    strong_records = [
        record
        for record in motion_records
        if _motion_score_value(record) >= strong_threshold and _to_float(record.get("timestamp")) is not None
    ]
    first_strong_ts = min((_to_float(record.get("timestamp")) for record in strong_records), default=None)
    last_strong_ts = max((_to_float(record.get("timestamp")) for record in strong_records), default=None)
    segment_by_code = {
        str(segment.get("phase_code") or ""): segment
        for segment in (video_ai_result.get("phase_segments") or [])
        if isinstance(segment, dict)
    }
    takeoff = segment_by_code.get("takeoff")
    takeoff_range = _valid_phase_time_range(takeoff, duration_sec) if isinstance(takeoff, dict) else None
    landing = segment_by_code.get("landing")
    landing_range = _valid_phase_time_range(landing, duration_sec) if isinstance(landing, dict) else None
    glide_out = segment_by_code.get("glide_out")
    glide_out_range = _valid_phase_time_range(glide_out, duration_sec) if isinstance(glide_out, dict) else None
    core_phase_motion_supported = _jump_core_phase_motion_is_supported(
        motion_records=motion_records,
        takeoff_range=takeoff_range,
        landing_range=landing_range,
        global_peak=global_peak,
        severe_occlusion_risk=severe_occlusion_risk,
        confidence=confidence,
    )
    landing_near_phase_tail = (
        landing_range is not None
        and l_value >= landing_range[1] - JUMP_COHERENT_TAL_LANDING_TAIL_TOLERANCE_SECONDS
    )
    landing_near_glide_boundary = (
        glide_out_range is not None
        and glide_out_range[0] - JUMP_COHERENT_TAL_GLIDE_OUT_BOUNDARY_TOLERANCE_SECONDS
        <= l_value
        <= glide_out_range[0] + JUMP_COHERENT_TAL_GLIDE_OUT_BOUNDARY_TOLERANCE_SECONDS
    )
    core_phase_not_clean = any(
        isinstance(segment_by_code.get(phase_code), dict)
        and (
            segment_by_code[phase_code].get("valid") is False
            or _clamp_confidence(segment_by_code[phase_code].get("confidence")) <= JUMP_COHERENT_TAL_PHASE_CONFIDENCE
        )
        for phase_code in JUMP_CORE_PHASE_CODES
    )
    failed_landing_motion_supported = (
        failed_landing_followthrough
        and not severe_occlusion_risk
        and confidence >= JUMP_COHERENT_TAL_CONFIDENCE
        and first_strong_ts is not None
        and takeoff_range is not None
        and landing_range is not None
        and glide_out_range is not None
        and isinstance(takeoff, dict)
        and isinstance(landing, dict)
        and _clamp_confidence(takeoff.get("confidence")) >= JUMP_COHERENT_TAL_RETRY_PHASE_CONFIDENCE
        and _clamp_confidence(landing.get("confidence")) >= JUMP_COHERENT_TAL_RETRY_PHASE_CONFIDENCE
        and landing_range[0] <= l_value <= landing_range[1] + JUMP_COHERENT_TAL_GLIDE_OUT_BOUNDARY_TOLERANCE_SECONDS
        and max(landing_range[0], glide_out_range[0] - JUMP_COHERENT_TAL_GLIDE_OUT_BOUNDARY_TOLERANCE_SECONDS)
        <= first_strong_ts
        <= glide_out_range[1] + JUMP_COHERENT_TAL_GLIDE_OUT_BOUNDARY_TOLERANCE_SECONDS
    )
    failed_landing_motion_support_flags = [
        "video_temporal_resolver_coherent_tal_failed_landing_motion_supported",
        "video_temporal_resolver_coherent_tal_motion_supported_despite_late_motion",
    ]
    near_skeleton_candidate_motion_support_flags = [
        "video_temporal_resolver_coherent_tal_near_skeleton_candidate_supported",
        "video_temporal_resolver_coherent_tal_motion_supported_despite_late_motion",
    ]
    phase_ranges = [
        phase_range
        for segment in segment_by_code.values()
        if (phase_range := _valid_phase_time_range(segment, duration_sec)) is not None
    ]
    motion_start = min((_to_float(record.get("timestamp")) for record in motion_records), default=None)
    motion_end = max((_to_float(record.get("timestamp")) for record in motion_records), default=None)
    phase_start = min((phase_range[0] for phase_range in phase_ranges), default=None)
    phase_end = max((phase_range[1] for phase_range in phase_ranges), default=None)
    action_window_start = min(value for value in (motion_start, phase_start) if value is not None) if motion_start is not None or phase_start is not None else 0.0
    action_window_end = max(value for value in (motion_end, phase_end) if value is not None) if motion_end is not None or phase_end is not None else duration_sec
    action_window_duration = max(0.0, action_window_end - action_window_start)
    core_tail_position = (
        action_window_duration > 0
        and t_value >= action_window_start + action_window_duration * 0.68
        and l_value >= action_window_start + action_window_duration * 0.78
    )
    if (
        revisible_glide_out_risk
        and explicit_video_fallback
        and core_tail_position
        and landing_range is not None
        and glide_out_range is not None
        and l_value >= glide_out_range[0] - JUMP_COHERENT_TAL_GLIDE_OUT_BOUNDARY_TOLERANCE_SECONDS
    ):
        return [
            "video_temporal_resolver_coherent_tal_compressed",
            "video_temporal_resolver_coherent_tal_revisible_glide_out_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        is_quality_retry
        and global_peak_ts is not None
        and confidence <= JUMP_COHERENT_TAL_RETRY_TAIL_CONFIDENCE_CEILING
        and t_value >= global_peak_ts + MOTION_SNAP_TOLERANCE_SECONDS
        and l_value >= global_peak_ts + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
        and l_value <= global_peak_ts + JUMP_COHERENT_TAL_MOTION_CONFLICT_LOOKAHEAD_SECONDS
        and (core_phase_not_clean or occlusion_risk or landing_near_phase_tail or landing_near_glide_boundary)
    ):
        return [
            "video_temporal_resolver_coherent_tal_compressed",
            "video_temporal_resolver_coherent_tal_late_motion_conflict",
            "video_temporal_resolver_coherent_tal_retry_tail_motion_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        is_quality_retry
        and confidence <= JUMP_COHERENT_TAL_RETRY_TAIL_CONFIDENCE_CEILING
        and last_strong_ts is not None
        and landing_range is not None
        and l_value >= last_strong_ts + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
        and l_value >= landing_range[0] + max((landing_range[1] - landing_range[0]) * 0.35, 0.18)
    ):
        return [
            "video_temporal_resolver_coherent_tal_late_motion_conflict",
            "video_temporal_resolver_coherent_tal_retry_tail_motion_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        is_quality_retry
        and confidence <= JUMP_COHERENT_TAL_RETRY_TAIL_CONFIDENCE_CEILING
        and first_strong_ts is not None
        and last_strong_ts is not None
        and core_tail_position
        and takeoff is not None
        and landing is not None
        and _clamp_confidence(takeoff.get("confidence")) <= JUMP_COHERENT_TAL_RETRY_WEAK_PHASE_CONFIDENCE
        and _clamp_confidence(landing.get("confidence")) <= JUMP_COHERENT_TAL_RETRY_WEAK_PHASE_CONFIDENCE
        and takeoff_range is not None
        and first_strong_ts >= takeoff_range[0] - JUMP_COHERENT_TAL_RETRY_TAIL_TAKEOFF_LEAD_SECONDS
        and first_strong_ts <= takeoff_range[0] + MOTION_SNAP_TOLERANCE_SECONDS
        and l_value >= last_strong_ts + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
    ):
        return [
            "video_temporal_resolver_coherent_tal_compressed",
            "video_temporal_resolver_coherent_tal_late_motion_conflict",
            "video_temporal_resolver_coherent_tal_retry_tail_motion_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    skeleton_early_timeline_conflict = (
        skeleton_takeoff_ts is not None
        and skeleton_apex_ts is not None
        and _candidate_confidence(skeleton_takeoff) >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_CONFIDENCE
        and _candidate_confidence(skeleton_apex) >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_CONFIDENCE
        and skeleton_takeoff_ts + SEMANTIC_ORDER_MIN_GAP_SECONDS < skeleton_apex_ts
        and t_value - skeleton_takeoff_ts >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_MIN_SHIFT_SECONDS
        and a_value - skeleton_apex_ts >= JUMP_COHERENT_TAL_SKELETON_CONFLICT_MIN_SHIFT_SECONDS
    )
    if (
        skeleton_early_timeline_conflict
        and core_tail_position
        and first_strong_ts is not None
        and takeoff_range is not None
        and first_strong_ts >= takeoff_range[0] - JUMP_COHERENT_TAL_RETRY_TAIL_TAKEOFF_LEAD_SECONDS
        and first_strong_ts <= takeoff_range[1] + MOTION_SNAP_TOLERANCE_SECONDS
        and l_value >= first_strong_ts + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
    ):
        return [
            "video_temporal_resolver_coherent_tal_compressed",
            "video_temporal_resolver_coherent_tal_skeleton_timeline_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        first_strong_ts is not None
        and not is_quality_retry
        and duration_sec >= JUMP_COHERENT_TAL_GLIDE_TAIL_MIN_DURATION_SECONDS
        and confidence <= JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING
        and landing_range is not None
        and glide_out_range is not None
        and not (failed_landing_followthrough and core_phase_motion_supported)
        and t_value >= first_strong_ts - JUMP_COHERENT_TAL_TAKEOFF_BEFORE_MOTION_TOLERANCE_SECONDS
        and l_value >= first_strong_ts + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
        and l_value <= first_strong_ts + JUMP_COHERENT_TAL_MOTION_CONFLICT_LOOKAHEAD_SECONDS
        and (
            landing_near_phase_tail
            or landing_near_glide_boundary
            or (
                last_strong_ts is not None
                and l_value >= last_strong_ts + MOTION_SNAP_TOLERANCE_SECONDS
            )
        )
    ):
        if near_skeleton_candidate_tal_support:
            return near_skeleton_candidate_motion_support_flags
        return _merge_flags(
            [
                "video_temporal_resolver_coherent_tal_compressed",
                "video_temporal_resolver_coherent_tal_late_motion_conflict",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
            ],
            ["video_temporal_resolver_coherent_tal_weak_jump_late_main_motion_cluster_conflict"] if weak_jump_risk else [],
        )
    if (
        weak_jump_risk
        and uses_video_timestamps
        and first_strong_ts is not None
        and last_strong_ts is not None
        and global_peak_ts is not None
        and len(strong_records) >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_STRONG_RECORDS
        and last_strong_ts - first_strong_ts >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_SPAN_SECONDS
        and skeleton_takeoff_ts is not None
        and _candidate_confidence(skeleton_takeoff) >= SKELETON_ANCHOR_CONFIDENCE
        and first_strong_ts - 0.15 <= skeleton_takeoff_ts <= last_strong_ts + 0.20
        and (
            confidence < JUMP_COHERENT_TAL_FALLBACK_GLIDE_OUT_CONFIDENCE
            or t_value - skeleton_takeoff_ts >= JUMP_WEAK_MOTION_CLUSTER_HIGH_CONFIDENCE_MIN_SEMANTIC_SHIFT_SECONDS
            or (
                skeleton_apex_ts is not None
                and skeleton_landing_ts is not None
                and _candidate_confidence(skeleton_apex) >= JUMP_MOTION_CLUSTER_FALLBACK_APEX_MIN_CONFIDENCE
                and _candidate_confidence(skeleton_landing) >= SKELETON_FALLBACK_CONFIDENCE
            )
        )
        and t_value >= first_strong_ts + MOTION_SNAP_TOLERANCE_SECONDS
        and a_value >= first_strong_ts + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
        and l_value >= last_strong_ts + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
        and l_value <= last_strong_ts + JUMP_WEAK_MOTION_CLUSTER_FALLBACK_LOOKAHEAD_SECONDS
    ):
        return [
            "video_temporal_resolver_coherent_tal_weak_jump_late_main_motion_cluster_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        weak_jump_risk
        and uses_video_timestamps
        and first_strong_ts is not None
        and last_strong_ts is not None
        and len(strong_records) >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_STRONG_RECORDS
        and last_strong_ts - first_strong_ts >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_SPAN_SECONDS
        and skeleton_takeoff_ts is not None
        and _candidate_confidence(skeleton_takeoff) >= SKELETON_ANCHOR_CONFIDENCE
        and first_strong_ts - 0.15 <= skeleton_takeoff_ts <= last_strong_ts + 0.20
        and t_value - skeleton_takeoff_ts >= JUMP_WEAK_MOTION_CLUSTER_FALLBACK_SEMANTIC_SHIFT_SECONDS
        and a_value >= first_strong_ts + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
        and l_value >= last_strong_ts + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
        and _motion_peak_score_in_range(
            motion_records,
            max(0.0, t_value - MOTION_SNAP_TOLERANCE_SECONDS),
            min(duration_sec, l_value + MOTION_SNAP_TOLERANCE_SECONDS),
        )
        < global_peak * JUMP_WEAK_MOTION_CLUSTER_FALLBACK_CORE_PEAK_RATIO
    ):
        return [
            "video_temporal_resolver_coherent_tal_weak_jump_late_main_motion_cluster_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    main_cluster_result = _strong_motion_cluster(motion_records)
    if main_cluster_result is not None:
        main_cluster, main_cluster_diagnostics = main_cluster_result
        main_cluster_start = _to_float(main_cluster[0].get("timestamp"))
        main_cluster_end = _to_float(main_cluster[-1].get("timestamp"))
        main_cluster_peak = _to_float(main_cluster_diagnostics.get("peak_sec"))
    else:
        main_cluster_start = None
        main_cluster_end = None
        main_cluster_peak = None
    if (
        weak_jump_risk
        and uses_video_timestamps
        and confidence >= JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING
        and main_cluster_start is not None
        and main_cluster_end is not None
        and main_cluster_peak is not None
        and skeleton_takeoff_ts is not None
        and skeleton_apex_ts is not None
        and _candidate_confidence(skeleton_takeoff) >= SKELETON_ANCHOR_CONFIDENCE
        and _candidate_confidence(skeleton_apex) >= JUMP_MOTION_CLUSTER_FALLBACK_APEX_MIN_CONFIDENCE
        and main_cluster_start - 0.15 <= skeleton_takeoff_ts <= main_cluster_peak + 0.10
        and main_cluster_start - 0.20 <= skeleton_apex_ts <= main_cluster_end
        and l_value - t_value <= JUMP_COHERENT_TAL_COMPRESSED_SECONDS
        and t_value >= main_cluster_start - JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_TAKEOFF_TOLERANCE_SECONDS
        and a_value >= main_cluster_start + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_APEX_LEAD_SECONDS
        and l_value >= main_cluster_end + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_LANDING_DRIFT_SECONDS
        and l_value <= main_cluster_end + JUMP_COHERENT_TAL_LATE_MAIN_CLUSTER_LOOKAHEAD_SECONDS
    ):
        return [
            "video_temporal_resolver_coherent_tal_late_main_motion_cluster_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        first_strong_ts is not None
        and l_value - t_value <= JUMP_COHERENT_TAL_EARLY_COMPRESSED_SECONDS
        and l_value <= first_strong_ts - JUMP_COHERENT_TAL_EARLY_STRONG_MOTION_LEAD_SECONDS
        and confidence < 0.95
        and uses_video_timestamps
        and occlusion_risk
    ):
        return [
            "video_temporal_resolver_coherent_tal_compressed",
            "video_temporal_resolver_coherent_tal_early_motion_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        not is_quality_retry
        and uses_video_timestamps
        and (occlusion_risk or small_target_risk)
        and first_strong_ts is not None
        and last_strong_ts is not None
        and global_peak_ts is not None
        and len(strong_records) >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_STRONG_RECORDS
        and last_strong_ts - first_strong_ts >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_SPAN_SECONDS
        and skeleton_takeoff_ts is not None
        and _candidate_confidence(skeleton_takeoff) >= SKELETON_ANCHOR_CONFIDENCE
        and first_strong_ts - 0.15 <= skeleton_takeoff_ts <= global_peak_ts + 0.10
        and l_value <= first_strong_ts + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_LANDING_TOLERANCE_SECONDS
        and a_value <= first_strong_ts - JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
        and global_peak_ts >= l_value + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_PEAK_LAG_SECONDS
    ):
        if failed_landing_motion_supported:
            return failed_landing_motion_support_flags
        return [
            "video_temporal_resolver_coherent_tal_early_main_motion_cluster_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        is_quality_retry
        and "video_temporal_recovered_from_raw_response_excerpt" not in quality_flags
        and first_strong_ts is not None
        and last_strong_ts is not None
        and global_peak_ts is not None
        and len(strong_records) >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_STRONG_RECORDS
        and last_strong_ts - first_strong_ts >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_SPAN_SECONDS
        and landing_range is not None
        and first_strong_ts <= landing_range[1] + JUMP_COHERENT_TAL_LANDING_BOUNDARY_TOLERANCE_SECONDS
        and t_value <= first_strong_ts - JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_TAKEOFF_LEAD_SECONDS
        and a_value <= first_strong_ts - JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
        and l_value <= first_strong_ts + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_LANDING_TOLERANCE_SECONDS
        and global_peak_ts >= l_value + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_PEAK_LAG_SECONDS
    ):
        if failed_landing_motion_supported:
            return failed_landing_motion_support_flags
        return [
            "video_temporal_resolver_coherent_tal_early_main_motion_cluster_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if (
        not is_quality_retry
        and uses_video_timestamps
        and (occlusion_risk or small_target_risk)
        and first_strong_ts is not None
        and last_strong_ts is not None
        and global_peak_ts is not None
        and len(strong_records) >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_STRONG_RECORDS
        and last_strong_ts - first_strong_ts >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_SPAN_SECONDS
        and skeleton_takeoff_ts is not None
        and _candidate_confidence(skeleton_takeoff) >= SKELETON_ANCHOR_CONFIDENCE
        and first_strong_ts - 0.15 <= skeleton_takeoff_ts <= global_peak_ts + 0.10
        and l_value <= first_strong_ts + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_LANDING_TOLERANCE_SECONDS
        and a_value <= first_strong_ts - JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
        and global_peak_ts >= l_value + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_PEAK_LAG_SECONDS
        and failed_landing_motion_supported
    ):
        return failed_landing_motion_support_flags
    if (
        uncertain_timestamp_recommendation
        and "video_temporal_recovered_from_raw_response_excerpt" not in quality_flags
        and first_strong_ts is not None
        and last_strong_ts is not None
        and global_peak_ts is not None
        and len(strong_records) >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_STRONG_RECORDS
        and last_strong_ts - first_strong_ts >= JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_MIN_SPAN_SECONDS
        and landing_range is not None
        and first_strong_ts <= landing_range[1] + JUMP_COHERENT_TAL_LANDING_BOUNDARY_TOLERANCE_SECONDS
        and t_value <= first_strong_ts - JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_TAKEOFF_LEAD_SECONDS
        and a_value <= first_strong_ts - JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_APEX_LEAD_SECONDS
        and l_value <= first_strong_ts + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_LANDING_TOLERANCE_SECONDS
        and global_peak_ts >= l_value + JUMP_COHERENT_TAL_RETRY_MAIN_MOTION_PEAK_LAG_SECONDS
    ):
        if failed_landing_motion_supported:
            return failed_landing_motion_support_flags
        return [
            "video_temporal_resolver_coherent_tal_early_main_motion_cluster_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    if l_value - t_value >= JUMP_COHERENT_TAL_COMPRESSED_SECONDS:
        return []
    if (
        first_strong_ts is not None
        and t_value >= first_strong_ts + MOTION_SNAP_TOLERANCE_SECONDS
        and not core_phase_motion_supported
        and (
            confidence < JUMP_COHERENT_TAL_LATE_MOTION_CONFLICT_CONFIDENCE_CEILING
            or (occlusion_risk and not explicit_video_fallback)
        )
    ):
        preparation = segment_by_code.get("preparation")
        preparation_range = _valid_phase_time_range(preparation, duration_sec) if isinstance(preparation, dict) else None
        skeleton_takeoff_supports_video_phase = (
            explicit_video_fallback
            and confidence >= JUMP_COHERENT_TAL_FALLBACK_GLIDE_OUT_CONFIDENCE
            and takeoff_range is not None
            and skeleton_takeoff_ts is not None
            and takeoff_range[0] - MOTION_SNAP_TOLERANCE_SECONDS <= skeleton_takeoff_ts <= takeoff_range[1] + MOTION_SNAP_TOLERANCE_SECONDS
            and _candidate_confidence(skeleton_takeoff) >= SKELETON_ANCHOR_CONFIDENCE
        )
        takeoff_boundary_motion = (
            takeoff_range is not None
            and takeoff_range[0] - MOTION_SNAP_TOLERANCE_SECONDS <= first_strong_ts <= takeoff_range[1]
        )
        preparation_boundary_motion = (
            preparation_range is not None
            and takeoff_range is not None
            and max(
                preparation_range[0],
                takeoff_range[0] - JUMP_COHERENT_TAL_PREP_MOTION_BOUNDARY_TOLERANCE_SECONDS,
            )
            <= first_strong_ts
            <= preparation_range[1]
        )
        if skeleton_takeoff_supports_video_phase:
            return []
        if (
            not is_quality_retry
            and
            confidence < JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING
            and l_value <= first_strong_ts + JUMP_COHERENT_TAL_MOTION_CONFLICT_LOOKAHEAD_SECONDS
        ):
            if near_skeleton_candidate_tal_support:
                return near_skeleton_candidate_motion_support_flags
            if failed_landing_followthrough and core_phase_motion_supported:
                return failed_landing_motion_support_flags
            return [
                "video_temporal_resolver_coherent_tal_compressed",
                "video_temporal_resolver_coherent_tal_late_motion_conflict",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
            ]
        if (
            not is_quality_retry
            and confidence <= JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING
            and l_value >= first_strong_ts + JUMP_COHERENT_TAL_LANDING_AFTER_MOTION_PEAK_SECONDS
            and l_value <= first_strong_ts + JUMP_COHERENT_TAL_MOTION_CONFLICT_LOOKAHEAD_SECONDS
        ):
            if near_skeleton_candidate_tal_support:
                return near_skeleton_candidate_motion_support_flags
            if failed_landing_followthrough and core_phase_motion_supported:
                return failed_landing_motion_support_flags
            return [
                "video_temporal_resolver_coherent_tal_compressed",
                "video_temporal_resolver_coherent_tal_late_motion_conflict",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
            ]
        if preparation_range is None or takeoff_boundary_motion or preparation_boundary_motion:
            if near_skeleton_candidate_tal_support:
                return near_skeleton_candidate_motion_support_flags
            if failed_landing_followthrough and core_phase_motion_supported:
                return failed_landing_motion_support_flags
            return [
                "video_temporal_resolver_coherent_tal_compressed",
                "video_temporal_resolver_coherent_tal_late_motion_conflict",
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
            ]

    core_records = _records_in_range(
        motion_records,
        max(0.0, t_value - MOTION_SNAP_TOLERANCE_SECONDS),
        min(duration_sec, l_value + MOTION_SNAP_TOLERANCE_SECONDS),
    )
    later_start = min(duration_sec, l_value + JUMP_COHERENT_TAL_MOTION_CONFLICT_LAG_SECONDS)
    later_records = _records_in_range(
        motion_records,
        later_start,
        min(duration_sec, l_value + JUMP_COHERENT_TAL_MOTION_CONFLICT_LOOKAHEAD_SECONDS),
    )
    first_strong_after_l = min(
        (
            timestamp
            for record in strong_records
            if (timestamp := _to_float(record.get("timestamp"))) is not None and timestamp >= later_start
        ),
        default=None,
    )
    if not later_records or first_strong_after_l is None:
        return []
    if (
        landing_range is not None
        and first_strong_after_l <= landing_range[1] + JUMP_COHERENT_TAL_LANDING_BOUNDARY_TOLERANCE_SECONDS
    ):
        return []
    if (
        (
            (is_quality_retry and confidence >= JUMP_COHERENT_TAL_RETRY_CONFIDENCE)
            or (
                is_quality_retry
                and uses_video_timestamps
                and not severe_occlusion_risk
                and confidence >= JUMP_COHERENT_TAL_TIMESTAMP_GLIDE_OUT_CONFIDENCE
            )
            or (explicit_video_fallback and confidence >= JUMP_COHERENT_TAL_FALLBACK_GLIDE_OUT_CONFIDENCE)
            or (
                is_quality_retry
                and explicit_video_fallback
                and confidence >= JUMP_COHERENT_TAL_RETRY_CONFIDENCE_FLOOR
                and not severe_occlusion_risk
                and not core_tail_position
                and glide_out_range is not None
                and l_value <= glide_out_range[0] + JUMP_COHERENT_TAL_LANDING_BOUNDARY_TOLERANCE_SECONDS
            )
            or (
                explicit_video_fallback
                and is_sampled_frames_fallback
                and confidence >= JUMP_COHERENT_TAL_SMALL_TARGET_GLIDE_OUT_CONFIDENCE
                and not occlusion_risk
                and small_target_risk
            )
            or (
                not explicit_video_fallback
                and not is_quality_retry
                and confidence >= JUMP_COHERENT_TAL_FALLBACK_GLIDE_OUT_CONFIDENCE
            )
            or (
                not explicit_video_fallback
                and not is_quality_retry
                and uses_video_timestamps
                and confidence >= JUMP_COHERENT_TAL_TIMESTAMP_GLIDE_OUT_CONFIDENCE
                and glide_out_range is not None
                and first_strong_after_l >= glide_out_range[1] - JUMP_COHERENT_TAL_GLIDE_OUT_TAIL_TOLERANCE_SECONDS
            )
            or (
                occlusion_risk
                and not severe_occlusion_risk
                and confidence >= JUMP_COHERENT_TAL_OCCLUSION_GLIDE_OUT_CONFIDENCE
            )
        )
        and glide_out_range is not None
        and glide_out_range[0] <= first_strong_after_l <= glide_out_range[1]
    ):
        return []
    if confidence >= JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING and not explicit_video_fallback and not occlusion_risk:
        return []
    core_peak = max((_motion_score_value(record) for record in core_records), default=0.0)
    later_peak = max((_motion_score_value(record) for record in later_records), default=0.0)
    if core_phase_motion_supported:
        return ["video_temporal_resolver_coherent_tal_motion_supported_despite_late_motion"]
    if (
        first_strong_after_l <= l_value + JUMP_COHERENT_TAL_MOTION_CONFLICT_LOOKAHEAD_SECONDS
        and later_peak >= strong_threshold
        and core_peak < strong_threshold
    ):
        if failed_landing_motion_supported:
            return failed_landing_motion_support_flags
        return [
            "video_temporal_resolver_coherent_tal_compressed",
            "video_temporal_resolver_coherent_tal_later_motion_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
        ]
    threshold = max(JUMP_COHERENT_TAL_MOTION_CONFLICT_MIN_SCORE, core_peak * JUMP_COHERENT_TAL_MOTION_CONFLICT_SCORE_RATIO)
    if later_peak < threshold:
        return []
    if failed_landing_motion_supported:
        return failed_landing_motion_support_flags
    return [
        "video_temporal_resolver_coherent_tal_compressed",
        "video_temporal_resolver_coherent_tal_later_motion_conflict",
        "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
    ]


def _resolver_profile_phase_codes(analysis_profile: str | None) -> set[str] | None:
    profile = str(analysis_profile or "").strip().lower()
    if profile == "jump":
        return set(JUMP_PHASE_CODES)
    if profile == "spin":
        return set(SPIN_PHASE_CODES)
    if profile == "spiral":
        return set(SPIRAL_PHASE_CODES)
    if profile == "step":
        return set(STEP_PHASE_CODES)
    return None


def _resolver_phase_is_usable(
    segment: dict[str, Any],
    *,
    coherent_tal_override: bool,
    coherent_profile_override: bool = False,
    analysis_profile: str | None = None,
    duration_sec: float,
    weak_retry_phase_override: bool = False,
) -> bool:
    confidence = _clamp_confidence(segment.get("confidence"))
    if confidence >= 0.60 and segment.get("valid") is not False:
        return True
    if not coherent_tal_override and not coherent_profile_override:
        return False
    phase_code = str(segment.get("phase_code") or "")
    if coherent_profile_override:
        profile_codes = _resolver_profile_phase_codes(analysis_profile) or set()
        return phase_code in profile_codes and confidence >= 0.60 and _valid_phase_time_range(segment, duration_sec) is not None
    return (
        phase_code in JUMP_CORE_PHASE_CODES
        and confidence
        >= (
            JUMP_COHERENT_TAL_RETRY_WEAK_GEOMETRY_PHASE_CONFIDENCE
            if weak_retry_phase_override
            else JUMP_COHERENT_TAL_PHASE_CONFIDENCE
        )
        and _valid_phase_time_range(segment, duration_sec) is not None
    )


def _resolver_phase_order(analysis_profile: str | None, video_ai_result: dict[str, Any]) -> list[dict[str, Any]]:
    allowed_codes = _resolver_profile_phase_codes(analysis_profile)
    segments = [
        segment
        for segment in video_ai_result.get("phase_segments", [])
        if isinstance(segment, dict) and (allowed_codes is None or str(segment.get("phase_code") or "") in allowed_codes)
    ]
    profile = str(analysis_profile or "").strip().lower()
    if profile == "jump":
        priority = {"takeoff": 0, "air": 1, "landing": 2, "preparation": 3, "glide_out": 4, "approach": 5}
    elif profile == "spin":
        priority = {code: index for index, code in enumerate(SPIN_RESOLVER_PHASES)}
    elif profile == "spiral":
        priority = {code: index for index, code in enumerate(SPIRAL_RESOLVER_PHASES)}
    elif profile == "step":
        priority = {"step_sequence": 0}
    else:
        priority = {}
    return sorted(segments, key=lambda segment: priority.get(str(segment.get("phase_code")), 99))


def _maybe_inferred_jump_preparation(
    *,
    normalized_video: dict[str, Any],
    selected: list[dict[str, Any]],
    duration_sec: float,
    confidence: float,
    analysis_profile: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    profile = str(analysis_profile or "").strip().lower()
    if profile != "jump" or not _selected_has_complete_ordered_core_tal(selected):
        return None, []

    segments = [segment for segment in normalized_video.get("phase_segments") or [] if isinstance(segment, dict)]
    by_phase = {str(segment.get("phase_code") or ""): segment for segment in segments}
    if "preparation" in by_phase:
        return None, []
    approach = by_phase.get("approach")
    takeoff = by_phase.get("takeoff")
    if not isinstance(approach, dict) or not isinstance(takeoff, dict):
        return None, []

    approach_range = _valid_phase_time_range(approach, duration_sec)
    takeoff_range = _valid_phase_time_range(takeoff, duration_sec)
    if approach_range is None or takeoff_range is None:
        return None, []
    approach_start, approach_end = approach_range
    takeoff_start, _ = takeoff_range
    if abs(approach_end - takeoff_start) > JUMP_INFERRED_PREPARATION_BOUNDARY_TOLERANCE_SECONDS:
        return None, []
    if approach_end - approach_start < JUMP_INFERRED_PREPARATION_MIN_APPROACH_SECONDS:
        return None, []

    inferred_start = max(approach_start, takeoff_start - JUMP_INFERRED_PREPARATION_MAX_SECONDS)
    if takeoff_start - inferred_start < 0.10:
        return None, []
    timestamp = round((inferred_start + takeoff_start) / 2.0, 3)
    if not (0 <= timestamp <= duration_sec):
        return None, []

    phase_confidence = min(_clamp_confidence(approach.get("confidence"), default=confidence), _clamp_confidence(takeoff.get("confidence"), default=confidence))
    return (
        {
            "frame_id": "",
            "timestamp": timestamp,
            "phase_code": "preparation",
            "phase_label": PHASE_LABELS["preparation"],
            "key_moment": None,
            "selection_reason": "inferred_preparation_before_takeoff",
            "confidence": phase_confidence,
            "phase_time_start": round(inferred_start, 3),
            "phase_time_end": round(takeoff_start, 3),
        },
        ["video_temporal_resolver_inferred_preparation_phase"],
    )


def _insert_inferred_preparation(selected: list[dict[str, Any]], inferred: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    inserted = False
    for item in selected:
        phase_code = str(item.get("phase_code") or "")
        if not inserted and phase_code in {"glide_out", "approach"}:
            output.append(dict(inferred))
            inserted = True
        output.append(item)
    if not inserted:
        output.append(dict(inferred))
    for index, item in enumerate(output, start=1):
        item["frame_id"] = f"semantic_{index:04d}"
    return output


def _maybe_inferred_spin_exit(
    *,
    normalized_video: dict[str, Any],
    selected: list[dict[str, Any]],
    duration_sec: float,
    confidence: float,
    analysis_profile: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    profile = str(analysis_profile or "").strip().lower()
    if profile != "spin" or confidence < 0.70:
        return None, []

    selected_codes = {str(item.get("phase_code") or "") for item in selected if isinstance(item, dict)}
    if "spin_exit" in selected_codes or "spin_main" not in selected_codes:
        return None, []

    segments = [segment for segment in normalized_video.get("phase_segments") or [] if isinstance(segment, dict)]
    by_phase = {str(segment.get("phase_code") or ""): segment for segment in segments}
    if "spin_exit" in by_phase:
        return None, []
    main = by_phase.get("spin_main")
    if not isinstance(main, dict):
        return None, []
    main_range = _valid_phase_time_range(main, duration_sec)
    if main_range is None:
        return None, []
    _, main_end = main_range
    remaining = duration_sec - main_end
    if remaining < 0.25:
        return None, []

    safe_duration_end = max(main_end, duration_sec - INFERRED_TAIL_PHASE_DURATION_GUARD_SECONDS)
    inferred_end = min(safe_duration_end, main_end + min(max(remaining, 0.60), 1.20))
    if inferred_end - main_end < 0.20:
        return None, []
    timestamp = round((main_end + inferred_end) / 2.0, 3)
    phase_confidence = min(confidence, _clamp_confidence(main.get("confidence"), default=confidence))
    return (
        {
            "frame_id": "",
            "timestamp": timestamp,
            "phase_code": "spin_exit",
            "phase_label": PHASE_LABELS["spin_exit"],
            "key_moment": None,
            "selection_reason": "inferred_spin_exit_after_main",
            "confidence": phase_confidence,
            "phase_time_start": round(main_end, 3),
            "phase_time_end": round(inferred_end, 3),
        },
        ["video_temporal_resolver_inferred_spin_exit_phase"],
    )


def _append_inferred_phase(selected: list[dict[str, Any]], inferred: dict[str, Any]) -> list[dict[str, Any]]:
    output = [dict(item) for item in selected]
    output.append(dict(inferred))
    output.sort(key=lambda item: _to_float(item.get("timestamp")) if _to_float(item.get("timestamp")) is not None else float("inf"))
    for index, item in enumerate(output, start=1):
        item["frame_id"] = f"semantic_{index:04d}"
    return output


def _resolve_segment_timestamp(
    segment: dict[str, Any],
    *,
    source: str,
    video_ai_result: dict[str, Any],
    skeleton_candidates: dict[str, dict[str, Any]],
    motion_records: list[dict[str, Any]],
    prefer_key_moments: bool = False,
    preserve_key_moments: bool = False,
    prefer_key_moments_before_skeleton: bool = False,
    skeleton_phase_edge_anchors: dict[str, float] | None = None,
) -> tuple[float | None, str, str | None, list[str]]:
    flags: list[str] = []
    phase_code = str(segment.get("phase_code") or "")
    start = _to_float(segment.get("time_start"))
    end = _to_float(segment.get("time_end"))
    hint = _to_float(segment.get("key_frame_hint"))
    if start is None or end is None or end <= start:
        return None, "invalid_phase_range", PHASE_KEY_MOMENTS.get(phase_code), ["video_temporal_resolver_invalid_phase_range"]

    key_moment = PHASE_KEY_MOMENTS.get(phase_code)
    skeleton_label = {"T_takeoff_sec": "T", "A_air_sec": "A", "L_landing_sec": "L"}.get(key_moment or "")
    skeleton_candidate = skeleton_candidates.get(skeleton_label or "")
    if prefer_key_moments_before_skeleton:
        key_value = _to_float(video_ai_result.get("key_moments", {}).get(key_moment)) if key_moment else None
        if key_value is not None and start <= key_value <= end:
            return key_value, "video_phase_range_key_moment", key_moment, flags
    if skeleton_label and skeleton_phase_edge_anchors:
        skeleton_edge_ts = skeleton_phase_edge_anchors.get(skeleton_label)
        if (
            skeleton_edge_ts is not None
            and start - SKELETON_OCCLUSION_PHASE_EDGE_TOLERANCE_SECONDS <= skeleton_edge_ts <= end + SKELETON_OCCLUSION_PHASE_EDGE_TOLERANCE_SECONDS
        ):
            flags.append("video_temporal_resolver_skeleton_occlusion_anchor_used")
            return skeleton_edge_ts, f"video_phase_range_skeleton_{phase_code}_occlusion_anchor", key_moment, flags
    if isinstance(skeleton_candidate, dict):
        skeleton_ts = _candidate_timestamp(skeleton_candidate)
        skeleton_conf = _candidate_confidence(skeleton_candidate)
        if skeleton_ts is not None and start <= skeleton_ts <= end:
            timestamp, reason, skeleton_flags = _resolve_skeleton_candidate_timestamp(
                label=skeleton_label or "",
                candidate=skeleton_candidate,
                motion_records=motion_records,
                start=start,
                end=end,
            )
            flags.extend(skeleton_flags)
            if timestamp is not None:
                return timestamp, reason, key_moment, flags
            if skeleton_conf < SKELETON_ANCHOR_CONFIDENCE:
                flags.append("video_temporal_resolver_skeleton_candidate_not_used")

    if source == "video_ai_refined" or prefer_key_moments or preserve_key_moments:
        key_value = _to_float(video_ai_result.get("key_moments", {}).get(key_moment)) if key_moment else None
        if key_value is not None and start <= key_value <= end:
            if preserve_key_moments:
                return key_value, "video_phase_range_key_moment", key_moment, flags
            if phase_code in MOTION_PEAK_PHASES:
                nearest = _motion_peak_near(motion_records, key_value, start, end)
                if nearest is not None:
                    return nearest, "video_phase_range_key_moment_motion_peak", key_moment, flags
                return key_value, "video_phase_range_key_moment", key_moment, flags
            else:
                return key_value, "video_phase_range_key_moment_apex", key_moment, flags

    if phase_code in MOTION_PEAK_PHASES:
        peak = _motion_peak_in_range(motion_records, start, end)
        if peak is not None:
            return peak, "video_phase_range_motion_peak", key_moment, flags

    if hint is not None and start <= hint <= end:
        return hint, "video_phase_range_key_hint", key_moment, flags

    center = round((start + end) / 2, 3)
    flags.append("video_temporal_resolver_used_phase_center")
    return center, "video_phase_range_center_fallback", key_moment, flags


def _step_sequence_coverage_records(
    segment: dict[str, Any],
    *,
    current_count: int,
    max_frames: int,
    duration_sec: float,
    confidence: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    start = _to_float(segment.get("time_start"))
    end = _to_float(segment.get("time_end"))
    if start is None or end is None or end <= start:
        return [], ["video_temporal_resolver_invalid_phase_range"]
    start = max(0.0, start)
    end = min(duration_sec, end)
    if end <= start:
        return [], ["video_temporal_resolver_invalid_phase_range"]
    span = end - start
    if span < STEP_SEQUENCE_MIN_MULTI_FRAME_SECONDS or current_count + 2 >= max_frames:
        return [], []

    records: list[dict[str, Any]] = []
    flags = ["video_temporal_resolver_step_sequence_multi_frame_coverage"]
    phase_confidence = _clamp_confidence(segment.get("confidence"), default=confidence)
    label = str(segment.get("phase_label") or PHASE_LABELS.get("step_sequence", "步法"))
    seen_timestamps: set[float] = set()
    for coverage_label, ratio in STEP_SEQUENCE_COVERAGE_POINTS:
        if current_count + len(records) >= max_frames:
            flags.append("video_temporal_resolver_frame_budget_trimmed")
            break
        timestamp = round(start + span * ratio, 3)
        if timestamp in seen_timestamps:
            continue
        seen_timestamps.add(timestamp)
        records.append(
            {
                "frame_id": f"semantic_{current_count + len(records) + 1:04d}",
                "timestamp": timestamp,
                "phase_code": "step_sequence",
                "phase_label": label,
                "key_moment": coverage_label,
                "selection_reason": "video_phase_range_step_sequence_coverage",
                "confidence": phase_confidence,
                "phase_time_start": start,
                "phase_time_end": end,
            }
        )
    return records, flags if records else []


def resolve_semantic_keyframes(
    video_ai_result: dict[str, Any] | None,
    skeleton_timestamps: dict[str, Any] | None,
    motion_scores: dict[str, Any] | None,
    *,
    video_duration_sec: float,
    analysis_profile: str | None,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """
    Convert semantic video intervals into exact frame timestamps for FFmpeg.
    """
    flags: list[str] = []
    resolved_budget = _configured_max_resolved_keyframes() if max_frames is None else max_frames
    max_frames = max(1, min(int(resolved_budget), MAX_RESOLVED_KEYFRAMES))
    duration = _to_float(video_duration_sec)
    if duration is None or duration <= 0:
        duration = 0.0
        flags.append("video_temporal_resolver_invalid_duration")

    normalized_video = _valid_video_temporal_for_resolver(video_ai_result, duration) if duration > 0 else None
    skeleton_candidates = _skeleton_candidates(skeleton_timestamps)
    motion_records = _motion_records_from_scores(motion_scores)
    if isinstance(normalized_video, dict):
        flags.extend(
            flag
            for flag in normalized_video.get("quality_flags", [])
            if isinstance(flag, str)
            and flag.startswith(
                (
                    "video_temporal_recovered_",
                    "video_temporal_partial_json_salvaged",
                )
            )
        )

    confidence = _clamp_confidence(normalized_video.get("confidence") if isinstance(normalized_video, dict) else 0.0)
    occlusion_risk = _video_temporal_has_occlusion_risk(normalized_video)
    skeleton_phase_edge_anchors = (
        _coherent_skeleton_tal_anchors(skeleton_candidates, duration_sec=duration)
        if occlusion_risk and str(analysis_profile or "").strip().lower() == "jump"
        else {}
    )
    fallback_selected, fallback_flags = _fallback_skeleton_selected(
        skeleton_candidates,
        video_duration_sec=duration,
        max_frames=max_frames,
        motion_records=motion_records,
    )
    flags.extend(fallback_flags)
    validation = normalized_video.get("validation") if isinstance(normalized_video, dict) and isinstance(normalized_video.get("validation"), dict) else {}
    effective_analysis_profile, profile_override_flags = _effective_non_jump_analysis_profile(
        analysis_profile,
        normalized_video,
        confidence=confidence,
        duration_sec=duration,
    )
    flags.extend(profile_override_flags)
    requested_profile = str(analysis_profile or "").strip().lower()
    provider_family = (
        str(normalized_video.get("action_confirmation", {}).get("action_family") or "").strip().lower()
        if isinstance(normalized_video, dict) and isinstance(normalized_video.get("action_confirmation"), dict)
        else ""
    )
    if (
        requested_profile in {"spin", "spiral", "step"}
        and provider_family in {"jump", "spin", "spiral", "step"}
        and provider_family != requested_profile
        and "video_temporal_resolver_profile_overridden_by_video_ai" not in flags
    ):
        flags.append("video_temporal_resolver_profile_mismatch")
    explicit_video_fallback = (
        isinstance(normalized_video, dict)
        and normalized_video.get("fallback_recommendation") != "use_video_timestamps"
        and not validation.get("errors")
    )
    coherent_tal_override = (
        _jump_coherent_tal_is_usable(
            normalized_video,
            confidence=confidence,
            duration_sec=duration,
            analysis_profile=effective_analysis_profile,
            skeleton_candidates=skeleton_candidates,
        )
        if isinstance(normalized_video, dict)
        else False
    )
    coherent_profile_override = (
        _coherent_profile_phases_are_usable(
            normalized_video,
            confidence=confidence,
            duration_sec=duration,
            analysis_profile=effective_analysis_profile,
        )
        if isinstance(normalized_video, dict)
        else False
    )
    should_check_motion_conflict = False
    if isinstance(normalized_video, dict):
        normalized_flags = [flag for flag in (normalized_video.get("quality_flags") or []) if isinstance(flag, str)]
        fallback_recommendation = str(normalized_video.get("fallback_recommendation") or "").strip()
        should_check_motion_conflict = (
            coherent_tal_override
            or "video_temporal_quality_retry" in normalized_flags
            or (
                fallback_recommendation == "use_video_timestamps"
                and (
                    (confidence <= JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING and "video_temporal_not_high_confidence" in normalized_flags)
                    or _video_temporal_has_occlusion_risk(normalized_video)
                    or _video_temporal_has_small_target_risk(normalized_video)
                    or _video_temporal_has_weak_jump_risk(normalized_video)
                )
            )
        )
    motion_supported_despite_late_motion = False
    if isinstance(normalized_video, dict) and should_check_motion_conflict:
        motion_conflict_flags = _jump_coherent_tal_motion_conflict_flags(
            normalized_video,
            motion_records,
            confidence=confidence,
            duration_sec=duration,
            explicit_video_fallback=explicit_video_fallback,
            occlusion_risk=occlusion_risk,
            skeleton_candidates=skeleton_candidates,
            analysis_profile=effective_analysis_profile,
        )
        if motion_conflict_flags:
            motion_supported_despite_late_motion = (
                "video_temporal_resolver_coherent_tal_motion_supported_despite_late_motion" in motion_conflict_flags
            )
            flags.extend(motion_conflict_flags)
            if not motion_supported_despite_late_motion:
                coherent_tal_override = False
    motion_conflict_rejected = "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in flags
    preserve_video_tal_despite_weak_retry_motion_conflict = (
        motion_conflict_rejected
        and not motion_supported_despite_late_motion
        and _weak_retry_motion_conflict_should_preserve_video_tal(
            normalized_video,
            skeleton_candidates,
            confidence=confidence,
            analysis_profile=effective_analysis_profile,
        )
    )
    if preserve_video_tal_despite_weak_retry_motion_conflict:
        flags = [
            flag
            for flag in flags
            if flag
            not in {
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                "video_temporal_resolver_coherent_tal_compressed",
                "video_temporal_resolver_coherent_tal_late_motion_conflict",
                "video_temporal_resolver_coherent_tal_weak_jump_late_main_motion_cluster_conflict",
            }
        ]
        flags.append("video_temporal_resolver_weak_retry_motion_conflict_preserved_video_tal")
        coherent_tal_override = True
        motion_conflict_rejected = False
    conflicted_small_occluded_target = (
        _video_temporal_has_small_target_risk(normalized_video)
        and _video_temporal_has_occlusion_risk(normalized_video)
    )
    preserve_rejected_semantic_candidates = (
        isinstance(normalized_video, dict)
        and explicit_video_fallback
        and motion_conflict_rejected
        and "video_temporal_resolver_coherent_tal_advisory_fallback_skeleton_conflict" not in flags
        and not _video_temporal_has_severe_occlusion_risk(normalized_video)
        and not conflicted_small_occluded_target
    )
    if not isinstance(normalized_video, dict) or (confidence < 0.55 and not coherent_tal_override and not coherent_profile_override) or (
        explicit_video_fallback and not coherent_tal_override and not coherent_profile_override and not preserve_rejected_semantic_candidates
    ):
        if not isinstance(normalized_video, dict):
            flags.append("video_temporal_resolver_missing_video_ai")
        elif confidence < 0.55:
            flags.append("video_temporal_resolver_low_video_confidence")
        else:
            flags.append("video_temporal_resolver_video_fallback_recommended")
        if fallback_selected and not _selected_has_complete_ordered_core_tal(fallback_selected, min_confidence=SKELETON_FALLBACK_CONFIDENCE):
            flags.append("video_temporal_resolver_partial_skeleton_fallback")
        motion_cluster_selected, motion_cluster_flags = _jump_motion_cluster_fallback_selected(
            analysis_profile=analysis_profile,
            video_ai_result=normalized_video,
            motion_records=motion_records,
            skeleton_candidates=skeleton_candidates,
            fallback_selected=fallback_selected,
            video_duration_sec=duration,
            max_frames=max_frames,
            existing_flags=flags,
        )
        if motion_cluster_selected:
            fallback_selected = motion_cluster_selected
            flags.extend(motion_cluster_flags)
        return {
            "source": "skeleton_fallback",
            "confidence": confidence,
            "quality_flags": _merge_flags(flags),
            "selected": fallback_selected,
            "video_ai": normalized_video or {},
        }

    source = "video_ai_refined" if confidence >= 0.80 else "blended"
    if (
        confidence <= JUMP_COHERENT_TAL_MOTION_CONFLICT_CONFIDENCE_CEILING
        and "video_temporal_resolver_coherent_tal_motion_conflict_rejected" in flags
    ):
        source = "blended"
    if normalized_video.get("fallback_recommendation") != "use_video_timestamps":
        source = "blended"
        flags.append("video_temporal_resolver_video_fallback_recommended")
        if coherent_tal_override:
            flags.append("video_temporal_resolver_advisory_fallback_overridden")
        elif coherent_profile_override:
            flags.append("video_temporal_resolver_advisory_fallback_overridden")
        elif preserve_rejected_semantic_candidates:
            flags.append("video_temporal_resolver_rejected_semantic_candidates_preserved")
    if coherent_tal_override:
        flags.append("video_temporal_resolver_coherent_tal_used")
        if confidence < 0.80:
            flags.append("video_temporal_resolver_moderate_confidence_tal_used")
        if (
            "video_temporal_quality_retry" in normalized_video.get("quality_flags", [])
            and any(
                isinstance(segment, dict)
                and str(segment.get("phase_code") or "") in JUMP_CORE_PHASE_CODES
                and _clamp_confidence(segment.get("confidence")) < JUMP_COHERENT_TAL_RETRY_PHASE_CONFIDENCE
                for segment in normalized_video.get("phase_segments", [])
            )
        ):
            flags.append("video_temporal_resolver_retry_weak_phase_tal_preserved")
    if coherent_profile_override:
        flags.append("video_temporal_resolver_coherent_profile_phases_used")
    if skeleton_phase_edge_anchors:
        flags.append("video_temporal_resolver_occlusion_skeleton_tal_available")
    if "video_temporal_tal_order_invalid" in normalized_video.get("quality_flags", []):
        source = "blended"
        flags.append("video_temporal_resolver_tal_order_blended")
    if validation.get("valid") is False and (confidence < 0.80 or normalized_video.get("fallback_recommendation") != "use_video_timestamps"):
        flags.append("video_temporal_resolver_video_validation_not_clean")
    key_moments = normalized_video.get("key_moments") if isinstance(normalized_video.get("key_moments"), dict) else {}
    weak_retry_phase_override = False
    if coherent_tal_override:
        tal_values = (
            _to_float(key_moments.get("T_takeoff_sec")),
            _to_float(key_moments.get("A_air_sec")),
            _to_float(key_moments.get("L_landing_sec")),
        )
        if all(value is not None for value in tal_values):
            weak_retry_phase_override = _retry_tal_can_use_weak_phase_ranges(
                normalized_video,
                skeleton_candidates,
                confidence=confidence,
                duration_sec=duration,
                analysis_profile=effective_analysis_profile,
                tal_anchors=(tal_values[0], tal_values[1], tal_values[2]),  # type: ignore[arg-type]
            )

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    allow_core_candidate_phase = coherent_tal_override or preserve_rejected_semantic_candidates
    preserve_core_key_moments = allow_core_candidate_phase or preserve_video_tal_despite_weak_retry_motion_conflict
    ordered_segments = _resolver_phase_order(effective_analysis_profile, normalized_video)
    segment_counts: dict[str, int] = {}
    for segment in ordered_segments:
        code = str(segment.get("phase_code") or "") if isinstance(segment, dict) else ""
        if code:
            segment_counts[code] = segment_counts.get(code, 0) + 1
    for segment in ordered_segments:
        if len(selected) >= max_frames:
            flags.append("video_temporal_resolver_frame_budget_trimmed")
            break
        if not _resolver_phase_is_usable(
            segment,
            coherent_tal_override=allow_core_candidate_phase,
            coherent_profile_override=coherent_profile_override,
            analysis_profile=effective_analysis_profile,
            duration_sec=duration,
            weak_retry_phase_override=weak_retry_phase_override,
        ):
            flags.append(f"video_temporal_resolver_phase_{segment.get('phase_code')}_fallback")
            continue
        phase_code = str(segment.get("phase_code") or "")
        if (
            str(effective_analysis_profile or "").strip().lower() == "jump"
            and phase_code in PHASE_KEY_MOMENTS
            and not _segment_matches_core_key_moment(segment, key_moments, duration, segment_counts)
        ):
            flags.append(f"video_temporal_resolver_skipped_duplicate_{phase_code}_outside_key_moment")
            continue
        if str(effective_analysis_profile or "").strip().lower() == "step" and phase_code == "step_sequence":
            coverage_records, coverage_flags = _step_sequence_coverage_records(
                segment,
                current_count=len(selected),
                max_frames=max_frames,
                duration_sec=duration,
                confidence=confidence,
            )
            if coverage_records:
                flags.extend(coverage_flags)
                for item in coverage_records:
                    dedupe_key = (str(item.get("phase_code") or ""), round(float(item.get("timestamp", 0.0) or 0.0), 3))
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    selected.append(item)
                continue
            flags.extend(coverage_flags)
        timestamp, reason, key_moment, segment_flags = _resolve_segment_timestamp(
            segment,
            source=source,
            video_ai_result=normalized_video,
            skeleton_candidates=skeleton_candidates,
            motion_records=motion_records,
            prefer_key_moments=allow_core_candidate_phase and explicit_video_fallback,
            preserve_key_moments=preserve_core_key_moments,
            prefer_key_moments_before_skeleton=preserve_video_tal_despite_weak_retry_motion_conflict,
            skeleton_phase_edge_anchors=skeleton_phase_edge_anchors,
        )
        flags.extend(segment_flags)
        if timestamp is None:
            continue
        if timestamp < 0 or timestamp > duration:
            flags.append("video_temporal_resolver_timestamp_out_of_bounds")
            continue
        dedupe_key = (phase_code, round(timestamp, 3))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        selected.append(
            {
                "frame_id": f"semantic_{len(selected) + 1:04d}",
                "timestamp": round(timestamp, 3),
                "phase_code": phase_code,
                "phase_label": str(segment.get("phase_label") or PHASE_LABELS.get(phase_code, "不可分析")),
                "key_moment": key_moment,
                "selection_reason": reason,
                "confidence": _clamp_confidence(segment.get("confidence"), default=confidence),
                "phase_time_start": _to_float(segment.get("time_start")),
                "phase_time_end": _to_float(segment.get("time_end")),
            }
        )
        if coherent_tal_override and explicit_video_fallback and phase_code == "landing":
            selected[-1]["max_refinement_delta_sec"] = 0.30
            selected[-1]["refinement_window_seconds"] = 0.30
            flags.append("video_temporal_resolver_expanded_core_refinement_delta")
        if _jump_takeoff_refinement_needs_delta_expansion(
            normalized_video=normalized_video,
            analysis_profile=analysis_profile,
            phase_code=phase_code,
            coherent_tal_override=coherent_tal_override,
        ):
            selected[-1]["max_refinement_delta_sec"] = max(
                _to_float(selected[-1].get("max_refinement_delta_sec")) or 0.0,
                JUMP_TAKEOFF_REFINEMENT_MAX_DELTA_SECONDS,
            )
            flags.append("video_temporal_resolver_takeoff_refinement_delta_expanded")
            if explicit_video_fallback:
                selected[-1]["max_refinement_backward_delta_sec"] = max(
                    _to_float(selected[-1].get("max_refinement_backward_delta_sec")) or 0.0,
                    0.08,
                )
                flags.append("video_temporal_resolver_takeoff_backward_refinement_guard")
        if _jump_landing_refinement_needs_phase_tolerance(
            normalized_video=normalized_video,
            analysis_profile=analysis_profile,
            phase_code=phase_code,
            explicit_video_fallback=explicit_video_fallback,
            coherent_tal_override=coherent_tal_override,
        ):
            selected[-1]["max_refinement_delta_sec"] = max(_to_float(selected[-1].get("max_refinement_delta_sec")) or 0.0, 0.30)
            selected[-1]["refinement_window_seconds"] = max(_to_float(selected[-1].get("refinement_window_seconds")) or 0.0, 0.30)
            selected[-1]["phase_time_start_refinement_tolerance_sec"] = JUMP_LANDING_REFINEMENT_TOLERANCE_SECONDS
            selected[-1]["phase_time_end_refinement_tolerance_sec"] = JUMP_LANDING_REFINEMENT_TOLERANCE_SECONDS
            flags.append("video_temporal_resolver_landing_refinement_phase_tolerance")

    if not selected and fallback_selected:
        flags.append("video_temporal_resolver_no_semantic_selection")
        source = "skeleton_fallback"
        if not _selected_has_complete_ordered_core_tal(fallback_selected, min_confidence=SKELETON_FALLBACK_CONFIDENCE):
            flags.append("video_temporal_resolver_partial_skeleton_fallback")
        motion_cluster_selected, motion_cluster_flags = _jump_motion_cluster_fallback_selected(
            analysis_profile=analysis_profile,
            video_ai_result=normalized_video,
            motion_records=motion_records,
            skeleton_candidates=skeleton_candidates,
            fallback_selected=fallback_selected,
            video_duration_sec=duration,
            max_frames=max_frames,
            existing_flags=flags,
        )
        if motion_cluster_selected:
            selected = motion_cluster_selected
            flags.extend(motion_cluster_flags)
        else:
            selected = fallback_selected
    elif motion_conflict_rejected and selected and not semantic_keyframes_are_reliable({"source": source, "quality_flags": flags, "selected": selected}):
        motion_cluster_selected, motion_cluster_flags = _jump_motion_cluster_fallback_selected(
            analysis_profile=analysis_profile,
            video_ai_result=normalized_video,
            motion_records=motion_records,
            skeleton_candidates=skeleton_candidates,
            fallback_selected=fallback_selected or selected,
            video_duration_sec=duration,
            max_frames=max_frames,
            existing_flags=flags,
        )
        if motion_cluster_selected:
            source = "skeleton_fallback"
            selected = motion_cluster_selected
            flags.extend(motion_cluster_flags)
    elif not selected:
        flags.append("video_temporal_resolver_no_selected_frames")

    inferred_preparation, inferred_flags = _maybe_inferred_jump_preparation(
        normalized_video=normalized_video,
        selected=selected,
        duration_sec=duration,
        confidence=confidence,
        analysis_profile=analysis_profile,
    )
    if inferred_preparation is not None and len(selected) < max_frames:
        selected = _insert_inferred_preparation(selected, inferred_preparation)
        flags.extend(inferred_flags)

    inferred_spin_exit, spin_exit_flags = _maybe_inferred_spin_exit(
        normalized_video=normalized_video,
        selected=selected,
        duration_sec=duration,
        confidence=confidence,
        analysis_profile=effective_analysis_profile,
    )
    if inferred_spin_exit is not None and len(selected) < max_frames:
        selected = _append_inferred_phase(selected, inferred_spin_exit)
        flags.extend(spin_exit_flags)

    return {
        "source": source,
        "confidence": confidence,
        "quality_flags": _merge_flags(flags),
        "selected": selected[:max_frames],
        "video_ai": normalized_video,
    }


def _phase_contains_time(segment: dict[str, Any], timestamp: float | None) -> bool:
    if timestamp is None:
        return False
    start = _to_float(segment.get("time_start"))
    end = _to_float(segment.get("time_end"))
    return start is not None and end is not None and start <= timestamp <= end


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _remove_once(items: list[str], value: str) -> None:
    try:
        items.remove(value)
    except ValueError:
        pass


def validate_video_temporal_payload(payload: dict[str, Any], duration_sec: float) -> dict[str, Any]:
    """
    Validate a normalized video temporal payload.

    Returns a copy of the payload plus validation diagnostics. It never raises on
    bad model data; callers should inspect valid and quality_flags.
    """
    out = dict(payload) if isinstance(payload, dict) else {}
    errors: list[str] = []
    warnings: list[str] = []
    flags = _merge_flags(out.get("quality_flags"))

    duration = _to_float(duration_sec)
    if duration is None or duration <= 0:
        duration = 0.0
        errors.append("video_temporal_invalid_duration")

    if not isinstance(payload, dict):
        errors.append("video_temporal_payload_not_object")
        out = {
            "schema_version": SCHEMA_VERSION,
            "provider": "unknown",
            "model": DEFAULT_MODEL,
            "action_confirmation": {
                "action_family": "unknown",
                "confirmed_action": "不可分析",
                "jump_type": "",
                "confidence": 0.0,
                "notes": "",
            },
            "phase_segments": [],
            "key_moments": {key: None for key in KEY_MOMENT_KEYS},
            "macro_assessment": _normalize_macro_assessment({}),
            "overall_impression": "",
            "camera_view": "unknown",
            "data_quality_hint": "poor",
            "confidence": 0.0,
            "fallback_recommendation": "use_sampled_frames",
        }

    if out.get("schema_version") != SCHEMA_VERSION:
        errors.append("video_temporal_invalid_schema_version")

    confidence = _clamp_confidence(out.get("confidence"))
    out["confidence"] = confidence
    if confidence < 0.55:
        warnings.append("video_temporal_low_confidence")
    if confidence < 0.80:
        warnings.append("video_temporal_not_high_confidence")

    fallback_recommendation = _string(out.get("fallback_recommendation"), "use_sampled_frames")
    if fallback_recommendation != "use_video_timestamps":
        warnings.append("video_temporal_fallback_recommended")

    action_confirmation = out.get("action_confirmation")
    if not isinstance(action_confirmation, dict):
        action_confirmation = _normalize_action_confirmation({})
        out["action_confirmation"] = action_confirmation
        errors.append("video_temporal_missing_action_confirmation")
    action_family = _normalize_action_family(action_confirmation.get("action_family"))
    action_confirmation["action_family"] = action_family
    action_confirmation["confidence"] = _clamp_confidence(action_confirmation.get("confidence"))

    segments = out.get("phase_segments")
    if not isinstance(segments, list) or not segments:
        errors.append("video_temporal_missing_phase_segments")
        segments = []
    valid_phase_codes = _phase_codes_for_family(action_family)
    normalized_segments: list[dict[str, Any]] = []
    previous_start: float | None = None
    previous_end: float | None = None
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            errors.append(f"video_temporal_phase_{index}_not_object")
            continue
        item = dict(segment)
        item["confidence"] = _clamp_confidence(item.get("confidence"))
        code = _normalize_phase_code(item.get("phase_code"))
        item["phase_code"] = code
        start = _to_float(item.get("time_start"))
        end = _to_float(item.get("time_end"))
        hint = _to_float(item.get("key_frame_hint"))

        phase_valid = True
        if code not in valid_phase_codes:
            phase_valid = False
            errors.append(f"video_temporal_phase_{index}_invalid_code")
        if start is None or end is None:
            phase_valid = False
            errors.append(f"video_temporal_phase_{index}_missing_time")
        elif start < 0 or end <= start:
            phase_valid = False
            errors.append(f"video_temporal_phase_{index}_invalid_time_range")
        elif end > duration:
            if end <= duration + VIDEO_TEMPORAL_PHASE_END_TAIL_TOLERANCE_SECONDS:
                item["time_end"] = round(duration, 3)
                _remove_once(errors, f"video_temporal_phase_{index}_invalid_time_range")
                _remove_once(flags, f"video_temporal_phase_{index}_invalid_time_range")
                warnings.append(f"video_temporal_phase_{index}_end_clamped_to_duration")
                end = duration
            else:
                phase_valid = False
                errors.append(f"video_temporal_phase_{index}_invalid_time_range")
        if hint is not None and start is not None and end is not None and not (start <= hint <= end):
            warnings.append(f"video_temporal_phase_{index}_hint_outside_range")
        if item["confidence"] < 0.60:
            warnings.append(f"video_temporal_phase_{index}_low_confidence")
        if previous_start is not None and start is not None and previous_end is not None:
            overlap = min(previous_end, end if end is not None else previous_end) - max(previous_start, start)
            if overlap > 0.25:
                warnings.append(f"video_temporal_phase_{index}_overlaps_previous")
        previous_start = start if start is not None else previous_start
        previous_end = end if end is not None else previous_end
        item["valid"] = phase_valid and item["confidence"] >= 0.60
        normalized_segments.append(item)
    out["phase_segments"] = normalized_segments

    key_moments = out.get("key_moments")
    if not isinstance(key_moments, dict):
        key_moments = {key: None for key in KEY_MOMENT_KEYS}
        out["key_moments"] = key_moments
    for key in KEY_MOMENT_KEYS:
        value = _to_float(key_moments.get(key))
        key_moments[key] = round(value, 3) if value is not None else None
        if value is not None and (value < 0 or value > duration):
            warnings.append(f"video_temporal_{key}_out_of_bounds")

    if action_family == "jump":
        t_value = _to_float(key_moments.get("T_takeoff_sec"))
        a_value = _to_float(key_moments.get("A_air_sec"))
        l_value = _to_float(key_moments.get("L_landing_sec"))
        if t_value is not None and a_value is not None and l_value is not None and not (t_value < a_value < l_value):
            warnings.append("video_temporal_tal_order_invalid")
        if (
            t_value is not None
            and _phase_segment_for_key_moment(
                normalized_segments,
                "takeoff",
                t_value,
                duration,
                require_contains=True,
            )
            is None
        ):
            warnings.append("video_temporal_T_takeoff_outside_takeoff_phase")
        if (
            a_value is not None
            and _phase_segment_for_key_moment(
                normalized_segments,
                "air",
                a_value,
                duration,
                require_contains=True,
            )
            is None
        ):
            warnings.append("video_temporal_A_air_outside_air_phase")
        if (
            l_value is not None
            and _phase_segment_for_key_moment(
                normalized_segments,
                "landing",
                l_value,
                duration,
                require_contains=True,
            )
            is None
        ):
            warnings.append("video_temporal_L_landing_outside_landing_phase")

    for item in errors:
        _append_once(flags, item)
    for item in warnings:
        _append_once(flags, item)

    valid = not errors and confidence >= 0.55 and fallback_recommendation == "use_video_timestamps"
    out["valid"] = valid
    out["quality_flags"] = flags
    out["validation"] = {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "duration_sec": duration,
    }
    if not valid and out.get("fallback_recommendation") == "use_video_timestamps":
        out["fallback_recommendation"] = "use_sampled_frames"
    return out
