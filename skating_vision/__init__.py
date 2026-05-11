"""
skating_vision — 花样滑冰视觉分析独立模块

可独立于主应用使用，提供：
- 视频抽帧与运动检测
- MediaPipe 姿态检测
- 生物力学分析
- LLM 视觉帧分析
- 结构化报告生成
"""

from skating_vision.types import FramePayload, VideoSamplingMetadata
from skating_vision.providers import ActiveProviderConfig, request_text_completion, extract_message_text
from skating_vision.vision import analyze_frames, normalize_vision_payload
from skating_vision.report import generate_report, calculate_force_score, normalize_report, fuse_subscores
from skating_vision.biomechanics import analyze_biomechanics, sanitize_biomechanics_data
from skating_vision.pose import extract_pose, get_pose_runtime_status, log_pose_runtime_mode
from skating_vision.video import (
    extract_motion_sampled_frames,
    encode_frames,
    extract_frames,
    detect_video_fps,
    detect_action_window,
    save_upload_file,
    build_upload_paths,
    build_processing_frames_dir,
    cleanup_processing_dir,
    persist_frames,
    configure as configure_video,
)
from skating_vision.action_profiles import infer_analysis_profile, infer_profile_hint, normalize_action_subtype
from skating_vision.target_lock import (
    build_target_preview,
    build_target_lock_payload,
    resolve_manual_candidate,
    extract_pose_target_bbox,
    frame_names_from_dir,
    TargetPreview,
    TARGET_LOCK_AUTO_THRESHOLD,
)
from skating_vision.analysis_errors import (
    AnalysisErrorCode,
    AnalysisFailure,
    AnalysisPipelineError,
    classify_video_failure,
    classify_ai_failure,
    friendly_error_title,
    stringify_exception,
)

__all__ = [
    # Types
    "FramePayload",
    "VideoSamplingMetadata",
    # Providers
    "ActiveProviderConfig",
    "request_text_completion",
    "extract_message_text",
    # Vision
    "analyze_frames",
    "normalize_vision_payload",
    # Report
    "generate_report",
    "calculate_force_score",
    "normalize_report",
    "fuse_subscores",
    # Biomechanics
    "analyze_biomechanics",
    "sanitize_biomechanics_data",
    # Pose
    "extract_pose",
    "get_pose_runtime_status",
    "log_pose_runtime_mode",
    # Video
    "extract_motion_sampled_frames",
    "encode_frames",
    "extract_frames",
    "detect_video_fps",
    "detect_action_window",
    "save_upload_file",
    "build_upload_paths",
    "build_processing_frames_dir",
    "cleanup_processing_dir",
    "persist_frames",
    "configure_video",
    # Action profiles
    "infer_analysis_profile",
    "infer_profile_hint",
    "normalize_action_subtype",
    # Target lock
    "build_target_preview",
    "build_target_lock_payload",
    "resolve_manual_candidate",
    "extract_pose_target_bbox",
    "frame_names_from_dir",
    "TargetPreview",
    "TARGET_LOCK_AUTO_THRESHOLD",
    # Errors
    "AnalysisErrorCode",
    "AnalysisFailure",
    "AnalysisPipelineError",
    "classify_video_failure",
    "classify_ai_failure",
    "friendly_error_title",
    "stringify_exception",
]
