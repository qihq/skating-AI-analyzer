"""Service layer for the analysis pipeline."""

from app.services.bio_context import (
    build_frame_bio_context,
    extract_key_frame_stems,
    summarize_jump_metrics,
)
from app.services.cross_validator import (
    OBJECTIVE_FIELDS,
    SUBSCORE_KEYS as DUAL_SUBSCORE_KEYS,
    CrossValidationReport,
    FieldValidation,
    compute_blend_weights,
    cross_validate,
)
from app.services.frame_annotator import (
    annotate_frame,
    annotate_frames_batch,
    build_pose_by_stem,
)
from app.services.report import SUBSCORE_KEYS, generate_report
from app.services.video import FramePayload, build_timestamp_map
from app.services.vision import analyze_frames
from app.services.vision_dual import (
    DUAL_PATH_TOTAL_TIMEOUT,
    DualPathResult,
    analyze_frames_dual,
    dual_path_summary,
)
from app.services.vision_path_a import analyze_path_a
from app.services.vision_path_b import analyze_path_b, sample_frames_path_b

__all__ = [
    "analyze_frames",
    "generate_report",
    "FramePayload",
    "SUBSCORE_KEYS",
    "annotate_frame",
    "annotate_frames_batch",
    "build_pose_by_stem",
    "build_frame_bio_context",
    "extract_key_frame_stems",
    "summarize_jump_metrics",
    "analyze_path_a",
    "analyze_path_b",
    "sample_frames_path_b",
    "cross_validate",
    "compute_blend_weights",
    "CrossValidationReport",
    "FieldValidation",
    "DUAL_SUBSCORE_KEYS",
    "OBJECTIVE_FIELDS",
    "analyze_frames_dual",
    "dual_path_summary",
    "DualPathResult",
    "DUAL_PATH_TOTAL_TIMEOUT",
    "build_timestamp_map",
]
