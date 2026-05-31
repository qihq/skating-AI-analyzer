from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.person_tracker import detect_person_candidates
from app.services.video import (
    VideoSamplingMetadata,
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
    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
    "semantic_keyframe_core_foreground_occlusion_repaired",
    "semantic_keyframes_unreliable_after_refinement",
    "semantic_keyframes_unreliable_after_visibility_check",
    "video_temporal_missing_phase_segments",
    "video_temporal_missing_core_tal",
    "video_temporal_resolver_no_semantic_selection",
    "video_temporal_resolver_partial_skeleton_fallback",
    "video_temporal_resolver_advisory_fallback_overridden",
    "video_temporal_low_confidence_retryable",
    "video_temporal_profile_mismatch_retryable",
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


@dataclass(slots=True)
class VideoTemporalTaskHandle:
    task: asyncio.Task[dict[str, Any]]
    ai_clip_path: Path
    source_duration_sec: float | None
    clip_duration_sec: float | None
    clip_fps: float
    timestamp_offset_sec: float
    analyzed_video_kind: str

    def ai_clip_payload(self) -> dict[str, Any]:
        return {
            "path": str(self.ai_clip_path),
            "duration_sec": self.clip_duration_sec,
            "source_duration_sec": self.source_duration_sec,
            "fps": self.clip_fps,
            "timestamp_offset_sec": self.timestamp_offset_sec,
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


def effective_timestamp_source(resolved_keyframes: dict[str, Any] | None, used_semantic_frames: bool) -> str:
    if not used_semantic_frames:
        return "sampled_frames"
    if isinstance(resolved_keyframes, dict):
        source = str(resolved_keyframes.get("source") or "").strip()
        if source:
            return source
    return "semantic_frames"


def _quality_flags(*sources: object) -> list[str]:
    return _merge_flags(*sources)


def _video_temporal_retry_reason_flags(
    video_temporal: dict[str, Any] | None,
    resolved_keyframes: dict[str, Any],
    *,
    analysis_profile: str | None = None,
    used_semantic_frames: bool | None = None,
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
    return [flag for flag in flags if flag in VIDEO_TEMPORAL_RETRY_TRIGGER_FLAGS]


def _video_confidence(video_temporal: dict[str, Any] | None, resolved_keyframes: dict[str, Any] | None = None) -> float:
    for source in (video_temporal, resolved_keyframes):
        if not isinstance(source, dict):
            continue
        try:
            return float(source.get("confidence"))
        except (TypeError, ValueError):
            continue
    return 0.0


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


def _has_ordered_core_tal(resolved_keyframes: dict[str, Any]) -> bool:
    anchors = _semantic_core_anchors(resolved_keyframes)
    return (
        {"T", "A", "L"}.issubset(anchors)
        and anchors["T"] + 0.02 < anchors["A"]
        and anchors["A"] + 0.02 < anchors["L"]
    )


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


def _retry_replacement_rejection_flags(
    original: SemanticKeyframePipelineResult,
    retry: SemanticKeyframePipelineResult,
    motion_scores: dict[str, object] | None = None,
) -> list[str]:
    if not retry.used_semantic_frames:
        return []
    retry_anchors = _semantic_core_anchors(retry.resolved_keyframes)
    if not {"T", "A", "L"}.issubset(retry_anchors):
        return []

    if _retry_has_later_strong_motion_conflict(retry, retry_anchors, motion_scores):
        return ["video_temporal_quality_retry_later_motion_rejected"]
    if _retry_has_early_main_motion_cluster_conflict(retry, retry_anchors, motion_scores):
        return ["video_temporal_quality_retry_early_main_motion_cluster_rejected"]

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

    try:
        semantic_frames, semantic_records = await extract_precise_frames_at_timestamps(
            video_path,
            semantic_frames_dir,
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
    except Exception:  # noqa: BLE001
        return original

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


def _video_temporal_retry_context(
    *,
    video_temporal: dict[str, Any] | None,
    resolved_keyframes: dict[str, Any],
    motion_scores: dict[str, object] | None,
    sampling_metadata: VideoSamplingMetadata,
    analysis_profile: str | None = None,
    used_semantic_frames: bool | None = None,
) -> dict[str, Any]:
    key_moments = video_temporal.get("key_moments") if isinstance(video_temporal, dict) and isinstance(video_temporal.get("key_moments"), dict) else {}
    t_value = _float_or_none(key_moments.get("T_takeoff_sec"))
    a_value = _float_or_none(key_moments.get("A_air_sec"))
    l_value = _float_or_none(key_moments.get("L_landing_sec"))

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
    if "video_temporal_low_confidence_retryable" in reasons:
        hints.append("Previous confidence was low; return usable T/A/L only if the target skater is visible enough to identify takeoff, apex, and first-contact landing.")
    if "semantic_keyframes_unreliable_after_visibility_check" in reasons:
        hints.append("Previous semantic frames were rejected by foreground visibility checks; prefer nearby timestamps where the target skater is not covered by a larger foreground person.")
    if "semantic_keyframe_core_foreground_occlusion_repaired" in reasons:
        hints.append("Previous core semantic frame required foreground-occlusion repair; return T/A/L on frames where the target skater is directly visible, not behind a larger foreground person.")
    if "semantic_keyframes_unreliable_after_refinement" in reasons:
        hints.append("Previous refined timestamps violated semantic order or phase bounds; keep T/A/L ordered and inside their phase intervals.")
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
    selected = _merge_partial_core_candidates(selected, video_temporal_candidates)
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
    if str(resolved_keyframes.get("source") or "") != "skeleton_fallback":
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
        item["selection_reason"] = "video_temporal_low_confidence_visual_tal_promoted"
        item["low_confidence_visual_promotion"] = True
        output.append(item)
    return output


def _promoted_partial_resolved_keyframes(
    resolved_keyframes: dict[str, Any],
    semantic_records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    promoted = dict(resolved_keyframes)
    promoted["source"] = "blended"
    promoted["selected"] = [dict(item) for item in semantic_records]
    _remove_flags(
        promoted,
        "semantic_keyframes_unreliable_fallback_to_sampled_frames",
        "semantic_keyframes_partial_core_frames_available",
    )
    _append_flag(promoted, "video_temporal_resolver_low_confidence_visual_tal_promoted")
    _append_flag(promoted, "video_temporal_resolver_advisory_low_confidence_overridden")
    _append_flag(promoted, "video_temporal_resolver_low_confidence_zoomed_visual_check")
    return promoted


def _record_has_visible_target(record: dict[str, Any]) -> bool:
    visibility = record.get("semantic_visibility")
    return isinstance(visibility, dict) and visibility.get("status") == "target_visible"


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


def _target_context_area_from_records(frame_paths: Sequence[Path], records: Sequence[dict[str, Any]]) -> float | None:
    candidates_by_index: dict[int, list[dict[str, Any]]] = {}
    for index, (frame_path, record) in enumerate(zip(frame_paths, records)):
        if not _is_core_semantic_record(record):
            continue
        try:
            candidates_by_index[index] = detect_person_candidates(frame_path, min_confidence=0.25)
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
                candidates_by_index[index] = detect_person_candidates(
                    frame_path,
                    min_confidence=0.25,
                    include_zoomed_small_targets=True,
                )
            else:
                candidates_by_index[index] = detect_person_candidates(frame_path, min_confidence=0.25)
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
        for index, record in enumerate(records):
            visibility = record.get("semantic_visibility")
            if not isinstance(visibility, dict) or visibility.get("status") != "foreground_person_occluded":
                continue
            if index >= len(frame_paths):
                continue
            original_timestamp = _record_timestamp(record)
            semantic_key = _core_semantic_key(record)
            target_context_area = _target_context_area_from_records(frame_paths, updated_records)
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
                    candidates = detect_person_candidates(candidate_path, min_confidence=0.25)
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
    retry_context: dict[str, Any] | None = None,
    precheck: bool = True,
) -> VideoTemporalTaskHandle:
    if precheck:
        await precheck_video(video_path)
    source_duration_sec = detect_video_duration(video_path)
    ai_clip_path = await cut_action_window_ai_clip(
        video_path,
        sampling_metadata.action_window_start,
        sampling_metadata.action_window_end,
        work_dir / "action_window_ai.mp4",
    )
    clip_duration_sec = detect_video_duration(ai_clip_path)
    clip_fps = detect_video_fps(ai_clip_path)
    task = asyncio.create_task(
        analyze_video_temporal(
            ai_clip_path,
            action_type=action_type,
            action_subtype=action_subtype,
            video_duration_sec=clip_duration_sec,
            source_video_duration_sec=source_duration_sec,
            source_fps=clip_fps,
            timestamp_offset_sec=sampling_metadata.action_window_start,
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
        timestamp_offset_sec=sampling_metadata.action_window_start,
        analyzed_video_kind=analyzed_video_kind,
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
                        semantic_records, visibility_flags = _semantic_frame_visibility_flags(semantic_frames, semantic_records)
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
        partial_candidates = _partial_semantic_candidates(resolved_keyframes, analysis_profile=analysis_profile)
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
                    if _low_confidence_jump_partial_can_be_promoted(
                        resolved_keyframes,
                        partial_candidates,
                        analysis_profile=analysis_profile,
                    ):
                        promoted_records = _semantic_records_from_promoted_partials(partial_semantic_records)
                        promoted_resolved = _promoted_partial_resolved_keyframes(resolved_keyframes, promoted_records)
                        promoted_paths = [semantic_frames_dir / f"{record['frame_id']}.jpg" for record in promoted_records]
                        for source_path, target_path in zip(partial_semantic_frames, promoted_paths):
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source_path, target_path)
                        inspected_records, visibility_flags = _semantic_frame_visibility_flags(
                            promoted_paths,
                            promoted_records,
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
                        if semantic_keyframes_are_reliable(promoted_resolved):
                            resolved_keyframes = promoted_resolved
                            semantic_frames = promoted_paths
                            semantic_records = inspected_records
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
    analyzed_video_kind: str = "action_window_ai",
    progress_callback: SemanticPipelineProgressCallback | None = None,
) -> SemanticKeyframePipelineResult:
    video_temporal = result.video_temporal
    if not _should_retry_video_temporal(
        video_temporal,
        result.resolved_keyframes,
        used_semantic_frames=result.used_semantic_frames,
        analysis_profile=analysis_profile,
    ):
        return result

    retry_context = _video_temporal_retry_context(
        video_temporal=video_temporal,
        resolved_keyframes=result.resolved_keyframes,
        motion_scores=motion_scores,
        sampling_metadata=sampling_metadata,
        analysis_profile=analysis_profile,
        used_semantic_frames=result.used_semantic_frames,
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
        analyzed_video_kind=f"{analyzed_video_kind}_retry",
        retry_context=retry_context,
        precheck=False,
    )
    retry_video_temporal = await retry_handle.task
    if isinstance(retry_video_temporal, dict):
        _append_flag(retry_video_temporal, "video_temporal_quality_retry")
    retry_result = await resolve_semantic_keyframe_pipeline(
        video_path=video_path,
        work_dir=work_dir,
        semantic_frames_dir=semantic_frames_dir,
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
    retry_rejection_flags = _retry_replacement_rejection_flags(result, retry_result, motion_scores)
    should_use_retry = retry_result.used_semantic_frames and not retry_rejection_flags and (
        not result.used_semantic_frames or retry_score > original_score
    )
    if should_use_retry:
        _append_flag(retry_result.resolved_keyframes, "video_temporal_quality_retry_used")
        retry_result.resolved_keyframes["video_temporal_quality_retry_scores"] = {
            "original": original_score,
            "retry": retry_score,
        }
        retry_result.quality_flags = _merge_flags(retry_result.video_temporal, retry_result.resolved_keyframes)
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
        return partial_merge_result

    for flag in retry_rejection_flags:
        _append_flag(result.resolved_keyframes, flag)
    retry_quality_flags = _quality_flags(retry_result.video_temporal, retry_result.resolved_keyframes)
    retry_rejection_diagnostic_flags = [
        flag
        for flag in retry_quality_flags
        if flag.startswith(
            (
                "video_temporal_resolver_",
                "semantic_keyframe_",
                "semantic_keyframes_",
            )
        )
    ]
    _append_flag(result.resolved_keyframes, "video_temporal_quality_retry_rejected")
    result.resolved_keyframes["video_temporal_quality_retry_scores"] = {
        "original": original_score,
        "retry": retry_score,
    }
    if retry_rejection_diagnostic_flags:
        result.resolved_keyframes["video_temporal_quality_retry_rejection_flags"] = retry_rejection_diagnostic_flags
    result.quality_flags = _merge_flags(result.video_temporal, result.resolved_keyframes)
    if isinstance(result.video_temporal, dict):
        result.video_temporal["retry_attempt"] = retry_video_temporal
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
    analyzed_video_kind: str = "action_window_ai",
    precheck: bool = True,
    progress_callback: SemanticPipelineProgressCallback | None = None,
) -> SemanticKeyframePipelineResult:
    handle = await start_video_temporal_task(
        video_path=video_path,
        work_dir=work_dir,
        sampling_metadata=sampling_metadata,
        action_type=action_type,
        action_subtype=action_subtype,
        analyzed_video_kind=analyzed_video_kind,
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
        analyzed_video_kind=analyzed_video_kind,
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
