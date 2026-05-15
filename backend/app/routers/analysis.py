from __future__ import annotations

import logging
import asyncio
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.database import AsyncSessionLocal, UPLOADS_DIR, get_session
from app.models import Analysis, Skater, TrainingPlan, TrainingSession
from app.schemas import (
    AnalysisCompareResponse,
    AnalysisAutoEvalSnapshot,
    AnalysisDetail,
    AnalysisListItem,
    AnalysisRetryResponse,
    AnalysisSessionUpdateRequest,
    AnalysisUploadResponse,
    CompareSummary,
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
from app.services.biomechanics import analyze_biomechanics, attach_key_frame_candidates, sanitize_biomechanics_data
from app.services.bbox_tracker import track_bbox
from app.services.plan import PlanGenerationError, extend_training_plan, generate_training_plan
from app.services.memory_suggest import suggest_memory_updates
from app.services.phase_smoother import smooth_phases
from app.services.pipeline_version import CURRENT_PIPELINE_VERSION
from app.services.pose import extract_pose
from app.services.report import calculate_force_score, generate_report
from app.services.skill_progress import auto_update_skill_progress
from app.services.skills import sync_skater_progress
from app.services.target_lock import (
    TARGET_LOCK_AUTO_THRESHOLD,
    build_target_lock_payload,
    build_target_preview,
    frame_names_from_dir,
    resolve_manual_candidate,
)
from app.services.video import (
    build_timestamp_map,
    build_processing_frames_dir,
    build_upload_paths,
    cleanup_processing_dir,
    cut_action_window_clip,
    encode_frames,
    extract_motion_sampled_frames,
    precheck_video,
    persist_frames,
    restore_sampled_frames,
    save_upload_file,
)
from app.services.vision_dual import analyze_frames_dual, dual_path_summary
from app.services.providers import get_active_provider


router = APIRouter(prefix="/api/analysis", tags=["analysis"])
plan_router = APIRouter(prefix="/api/plan", tags=["plan"])
frames_router = APIRouter(prefix="/api/frames", tags=["frames"])

VALID_ACTION_TYPES = {"跳跃", "旋转", "步法", "自由滑"}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
logger = logging.getLogger(__name__)
PIPELINE_STAGES = ["extract_frames", "pose", "biomechanics", "vision", "report"]
MAX_ANALYSIS_LOG_ENTRIES = 200
CONFIRMED_TARGET_LOCK_STATUSES = {"locked", "manual"}
STALE_ANALYSIS_TIMEOUT_SECONDS = 600
IN_PROGRESS_ANALYSIS_STATUSES = {
    "pending",
    "processing",
    "extracting_frames",
    "analyzing",
    "generating_report",
}


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


def _normalize_processing_logs(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)][-MAX_ANALYSIS_LOG_ENTRIES:]


def _provider_label(provider: Any) -> str:
    provider_name = str(getattr(provider, "provider", "") or "").strip() or "unknown"
    model = str(getattr(provider, "model_id", "") or getattr(provider, "vision_model", "") or "").strip()
    return f"{provider_name}/{model}" if model else provider_name


def _provider_fallback_note(provider: Any) -> str | None:
    notes = str(getattr(provider, "notes", "") or "")
    return notes if "fallback_from=" in notes else None


def _count_list(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


DUAL_PATH_RAW_PREVIEW_CHARS = 2400
DUAL_PATH_FRAME_PREVIEW_LIMIT = 12


def _truncate_text(value: object, limit: int = DUAL_PATH_RAW_PREVIEW_CHARS) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"...<truncated {len(text) - limit} chars>"


def _summarize_path_frames(frames: object, limit: int = DUAL_PATH_FRAME_PREVIEW_LIMIT) -> list[dict[str, Any]]:
    if not isinstance(frames, list):
        return []
    out: list[dict[str, Any]] = []
    for frame in frames[:limit]:
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
    detail = {
        "path_a": {
            "provider": _provider_label(provider_path_a),
            "provider_fallback": _provider_fallback_note(provider_path_a),
            "mode": path_a_data.get("vision_mode") or ("video" if clip_path else "frames"),
            "input": str(clip_path) if clip_path else f"{raw_frame_count} raw frames",
            "frame_analysis_count": _count_list(path_a_data.get("frame_analysis")),
            "phase_segments_count": _count_list(path_a_data.get("phase_segments")),
            "path_desc": path_a_data.get("path_desc"),
            "action_phase_summary": path_a_data.get("action_phase_summary"),
            "overall_raw_text": _truncate_text(path_a_data.get("overall_raw_text")),
            "frame_preview": _summarize_path_frames(path_a_data.get("frame_analysis")),
        },
        "path_b": {
            "provider": _provider_label(provider_path_b),
            "provider_fallback": _provider_fallback_note(provider_path_b),
            "input": f"{annotated_frame_count} annotated frames + biomechanics",
            "annotated_dir": str(annotated_dir) if annotated_dir else None,
            "n_frames": path_b_data.get("n_frames") or annotated_frame_count,
            "key_frames": sorted(used_key_frames or set()),
            "failed": bool(path_b_data.get("error")),
            "error": path_b_data.get("error"),
            "subscores": path_b_data.get("subscores"),
            "action_phase_summary": path_b_data.get("action_phase_summary"),
            "top_issues": path_b_data.get("top_issues"),
            "top_positives": path_b_data.get("top_positives"),
            "frame_preview": _summarize_path_frames(path_b_data.get("frame_analysis")),
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

    log_method = getattr(logger, level.lower(), logger.info)
    log_method("Analysis %s [%s] %s", analysis_id, stage, message)

    try:
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
    try:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            analysis.processing_timings = dict(timings)
            await session.commit()
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
            skater_id = analysis.skater_id
            vision_structured = analysis.vision_structured
            bio_data = analysis.bio_data
            dual_path_meta = analysis.cross_validation if isinstance(analysis.cross_validation, dict) else None

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
        )
        force_score = calculate_force_score(report)
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

        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            analysis.report = report
            analysis.force_score = force_score
            analysis.processing_timings = dict(timings)
            analysis.pipeline_version = CURRENT_PIPELINE_VERSION
            analysis.status = "completed"
            analysis.error_code = None
            analysis.error_detail = None
            analysis.error_message = None
            analysis.retry_from_stage = None
            await auto_update_skill_progress(analysis_id, session)
            if analysis.skater_id:
                await sync_skater_progress(session, analysis.skater_id)
            await session.commit()
            if analysis.skater_id:
                try:
                    await suggest_memory_updates(analysis_id, analysis.skater_id, session)
                except Exception:  # noqa: BLE001
                    logger.exception("Analysis %s memory suggestion generation failed", analysis_id)

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
            analysis_profile_hint = analysis.analysis_profile or infer_profile_hint(action_type, action_subtype)
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
            if existing_target_lock and str(existing_target_lock.get('status')) in CONFIRMED_TARGET_LOCK_STATUSES and upload_frames_dir is not None and upload_frames_dir.exists():
                sampled_frames = persist_frames(sorted(upload_frames_dir.glob('frame_*.jpg')), processing_frames_dir)
                motion_scores = saved_motion_scores if isinstance(saved_motion_scores, dict) else _fallback_motion_payload(upload_frames_dir)
                sampling_metadata = _sampling_metadata_from_saved(
                    action_window_start=saved_action_window_start,
                    action_window_end=saved_action_window_end,
                    source_fps=saved_source_fps,
                    is_slow_motion=saved_is_slow_motion,
                    motion_scores=motion_scores,
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
                    )
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

            preview = build_target_preview(analysis_id, [frame.name for frame in sampled_frames], existing_target_lock=existing_target_lock)
            target_lock = existing_target_lock if existing_target_lock and str(existing_target_lock.get('status')) in CONFIRMED_TARGET_LOCK_STATUSES else build_target_lock_payload(preview)

            async with AsyncSessionLocal() as session:
                analysis = await session.get(Analysis, analysis_id)
                if analysis is None:
                    return
                analysis.frame_motion_scores = motion_scores
                analysis.processing_timings = dict(timings)
                analysis.action_window_start = sampling_metadata.action_window_start
                analysis.action_window_end = sampling_metadata.action_window_end
                analysis.source_fps = sampling_metadata.source_fps
                analysis.is_slow_motion = sampling_metadata.is_slow_motion
                analysis.target_lock = target_lock
                analysis.target_lock_status = target_lock['status']
                analysis.retry_from_stage = 'pose'
                await session.commit()

            if (not existing_target_lock or str(existing_target_lock.get('status')) not in CONFIRMED_TARGET_LOCK_STATUSES) and preview.lock_confidence < TARGET_LOCK_AUTO_THRESHOLD:
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
                raise RuntimeError('?????????????????')
            sampled_frames = persist_frames(sorted(upload_frames_dir.glob('frame_*.jpg')), processing_frames_dir)
            motion_scores = saved_motion_scores if isinstance(saved_motion_scores, dict) else _fallback_motion_payload(upload_frames_dir)
            sampling_metadata = _sampling_metadata_from_saved(
                action_window_start=saved_action_window_start,
                action_window_end=saved_action_window_end,
                source_fps=saved_source_fps,
                is_slow_motion=saved_is_slow_motion,
                motion_scores=motion_scores,
            )
            preview = build_target_preview(analysis_id, [frame.name for frame in sampled_frames], existing_target_lock=existing_target_lock)
            target_lock = existing_target_lock if existing_target_lock else build_target_lock_payload(preview)
            await _append_analysis_log(
                analysis_id,
                stage='extract_frames',
                level='info',
                message=f'分段重试复用缓存关键帧，共 {len(sampled_frames)} 帧。',
                retry_from_stage=retry_from_stage,
            )

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
                bbox_per_frame = _build_bbox_per_frame(sampled_frames, target_lock)
                pose_data = await asyncio.to_thread(
                    extract_pose,
                    str(processing_frames_dir),
                    target_lock,
                    bbox_per_frame,
                    sampling_metadata.effective_fps,
                )
                timings['pose_s'] = _elapsed_seconds(pose_start)
                async with AsyncSessionLocal() as session:
                    analysis = await session.get(Analysis, analysis_id)
                    if analysis is None:
                        return
                    analysis.pose_data = pose_data
                    analysis.target_lock = target_lock
                    analysis.processing_timings = dict(timings)
                    analysis.retry_from_stage = 'biomechanics'
                    await session.commit()
                await _append_analysis_log(
                    analysis_id,
                    stage='pose',
                    level='info',
                    message=f'姿态提取完成，共 {len(pose_data.get("frames", [])) if isinstance(pose_data, dict) else 0} 帧。',
                    elapsed_s=timings['pose_s'],
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
                    raise RuntimeError('???????????? pose_data?')
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
                analysis_profile, profile_evidence = infer_analysis_profile(action_type, action_subtype, pose_data, motion_scores)
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
                    bio_data['quality_flags'] = merged_quality_flags
                    bio_data['profile_evidence'] = profile_evidence
                    if 'jump_gate_not_passed' in merged_quality_flags:
                        quality_hint = next(
                            (
                                message
                                for message in profile_evidence.get('negative_constraints', [])
                                if isinstance(message, str) and '??????' in message
                            ),
                            '???????CoM ????????????????????? jump ???',
                        )
                        bio_data['jump_metrics_warning'] = quality_hint
                    if 'spin_rotation_signal_weak' in merged_quality_flags:
                        profile_warning = next(
                            (
                                message
                                for message in profile_evidence.get('negative_constraints', [])
                                if isinstance(message, str) and '???????' in message
                            ),
                            '???????????????? spin ?????????????????',
                        )
                        bio_data['profile_warning'] = profile_warning
                timings['biomechanics_s'] = _elapsed_seconds(biomechanics_start)
                async with AsyncSessionLocal() as session:
                    analysis = await session.get(Analysis, analysis_id)
                    if analysis is None:
                        return
                    analysis.bio_data = bio_data
                    analysis.analysis_profile = analysis_profile
                    analysis.processing_timings = dict(timings)
                    analysis.retry_from_stage = 'vision'
                    await session.commit()
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
                    raise RuntimeError('???????????? bio_data?')
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
                timestamps = build_timestamp_map(motion_scores)
                raw_payloads = await encode_frames(sampled_frames, timestamps=timestamps)
                clip_path = None
                provider_path_a = await _provider_for_slot("vision_path_a")
                provider_path_b = await _provider_for_slot("vision_path_b")
                try:
                    clip_path = await cut_action_window_clip(
                        video_path,
                        sampling_metadata.action_window_start,
                        sampling_metadata.action_window_end,
                        processing_frames_dir.parent / 'action_window.mp4',
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning('Analysis %s action-window clip failed; Path A will use frames: %s', analysis_id, exc)
                dual = await analyze_frames_dual(
                    action_type=action_type,
                    frame_paths=sampled_frames,
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
                    clip_path=clip_path,
                    window_start_sec=sampling_metadata.action_window_start,
                    skill_category=skill_category,
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
                    clip_path=clip_path,
                    used_key_frames=getattr(dual, "used_key_frames", set()),
                )
                frame_analysis = vision_structured.get('frame_analysis')
                if isinstance(frame_analysis, list):
                    vision_structured['frame_analysis'] = smooth_phases(frame_analysis, analysis_profile, bio_data=bio_data)
                    vision_path_a = vision_structured
                cross_validation = _attach_auto_eval(
                    cross_validation,
                    bio_data=bio_data,
                    vision_structured=vision_structured,
                    frame_motion_scores=motion_scores,
                    analysis_profile=analysis_profile,
                )
                dual_path_meta = cross_validation
                vision_raw = json.dumps(vision_structured, ensure_ascii=False)
                timings['vision_s'] = _elapsed_seconds(vision_start)
                async with AsyncSessionLocal() as session:
                    analysis = await session.get(Analysis, analysis_id)
                    if analysis is None:
                        return
                    analysis.vision_raw = vision_raw
                    analysis.vision_structured = vision_structured
                    analysis.vision_path_a = vision_path_a
                    analysis.vision_path_b = vision_path_b
                    analysis.cross_validation = cross_validation
                    analysis.processing_timings = dict(timings)
                    analysis.retry_from_stage = 'report'
                    await session.commit()
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
                    raise RuntimeError('???????????? vision_structured?')
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
            )
            force_score = calculate_force_score(report)
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

        try:
            async with AsyncSessionLocal() as session:
                analysis = await session.get(Analysis, analysis_id)
                if analysis is None:
                    return

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
                await auto_update_skill_progress(analysis_id, session)
                if analysis.skater_id:
                    await sync_skater_progress(session, analysis.skater_id)
                await session.commit()
                if analysis.skater_id:
                    try:
                        await suggest_memory_updates(analysis_id, analysis.skater_id, session)
                    except Exception:  # noqa: BLE001
                        logger.exception('Analysis %s memory suggestion generation failed', analysis_id)
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
    try:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
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
    except Exception:  # noqa: BLE001
        logger.exception("Analysis %s failed to persist error state", analysis_id)


async def _set_analysis_status(analysis_id: str, status_value: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            analysis.status = status_value
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Analysis %s failed to persist status %s", analysis_id, status_value)


async def _get_default_skater(session: AsyncSession) -> Skater | None:
    result = await session.execute(select(Skater).order_by(Skater.is_default.desc(), Skater.created_at.asc()).limit(1))
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
    result = await session.execute(select(Skater).where(Skater.id.in_(skater_ids)))
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
        or ([f"{strongest_phase}阶段表现相对稳定"] if strongest_phase and strongest_phase != "ä¸å¯åˆ†æž" else []),
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
        + ([f"{weakest_phase}阶段还可以继续加强"] if weakest_phase and weakest_phase != "ä¸å¯åˆ†æž" else []),
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
        processing_timings=analysis.processing_timings,
        processing_logs=_normalize_processing_logs(analysis.processing_logs),
        target_lock=analysis.target_lock,
        target_lock_status=analysis.target_lock_status,
        action_window_start=analysis.action_window_start,
        action_window_end=analysis.action_window_end,
        source_fps=analysis.source_fps,
        is_slow_motion=analysis.is_slow_motion,
        force_score=analysis.force_score,
        auto_unlocked_skill=analysis.auto_unlocked_skill,
        error_code=analysis.error_code,
        error_detail=analysis.error_detail if include_error_detail else None,
        error_message=analysis.error_message,
        note=analysis.note,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
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
        created_at=analysis.created_at,
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


def _append_target_lock_flags(target_lock: dict[str, Any], flags: list[str]) -> dict[str, Any]:
    existing = target_lock.get("quality_flags") if isinstance(target_lock.get("quality_flags"), list) else []
    merged = list(existing)
    for flag in flags:
        if flag not in merged:
            merged.append(flag)
    target_lock["quality_flags"] = merged
    return target_lock


def _build_bbox_per_frame(sampled_frames: list[Path], target_lock: dict[str, Any]) -> list[dict[str, float]] | None:
    selected_bbox = target_lock.get("selected_bbox")
    if not isinstance(selected_bbox, dict):
        return None
    try:
        bbox_per_frame, flags = track_bbox(sampled_frames, selected_bbox)
        _append_target_lock_flags(target_lock, flags)
        target_lock["bbox_per_frame"] = bbox_per_frame
        return bbox_per_frame
    except Exception:  # noqa: BLE001
        logger.warning("bbox tracker failed; falling back to static target bbox", exc_info=True)
        _append_target_lock_flags(target_lock, ["bbox_tracker_failed_fallback"])
        bbox_per_frame = [selected_bbox for _ in sampled_frames]
        target_lock["bbox_per_frame"] = bbox_per_frame
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


def _frames_dir_for_analysis(analysis: Analysis) -> Path:
    frames_dir = _video_path_for_analysis(analysis).parent / "frames"
    if frames_dir.exists():
        return frames_dir
    return UPLOADS_DIR / analysis.id / "frames"


def _can_backfill_artifacts(status_value: str | None) -> bool:
    return status_value in {"completed", "failed"}


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
            )
            persist_frames(restored_paths, frames_dir)
            analysis.frame_motion_scores = motion_scores
            analysis.action_window_start = sampling_metadata.action_window_start
            analysis.action_window_end = sampling_metadata.action_window_end
            analysis.source_fps = sampling_metadata.source_fps
            analysis.is_slow_motion = sampling_metadata.is_slow_motion
            await session.commit()
            await session.refresh(analysis)
        finally:
            cleanup_processing_dir(analysis.id)
    else:
        logger.info("Analysis %s restored %s frame images from saved timestamps", analysis.id, len(restored_paths))

    return analysis, frames_dir


async def _ensure_phase3_artifacts(session: AsyncSession, analysis: Analysis) -> Analysis:
    if not _can_backfill_artifacts(analysis.status):
        return analysis

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
            None,
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
    if bio_data is None or not bio_data.get("key_frames"):
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
        await session.commit()
        await session.refresh(analysis)

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
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
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
    except AnalysisPipelineError as exc:
        video_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail={"code": exc.code.value, "message": exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_action_subtype = normalize_action_subtype(action_type, action_subtype)
    inferred_input_profile = infer_profile_from_input(action_type, action_subtype)

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
    )
    if action_type:
        query = query.where(Analysis.action_type == action_type)
    if skater_id:
        query = query.where(Analysis.skater_id == skater_id)

    result = await session.execute(query)
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
    if analysis_a.action_type != analysis_b.action_type:
        raise HTTPException(status_code=400, detail="仅支持同动作类型的复盘记录对比。")

    skater_map = await _get_skater_map(
        session,
        {analysis.skater_id for analysis in (analysis_a, analysis_b) if analysis.skater_id},
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
        score_delta=(analysis_b.force_score or 0) - (analysis_a.force_score or 0),
        summary=_compare_reports(
            analysis_a.report if isinstance(analysis_a.report, dict) else None,
            analysis_b.report if isinstance(analysis_b.report, dict) else None,
        ),
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
            created_at=analysis.created_at,
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
async def create_training_plan(analysis_id: str, session: AsyncSession = Depends(get_session)) -> TrainingPlanDetail:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")
    if analysis.status != "completed":
        raise HTTPException(status_code=400, detail="只有 completed 状态的分析才能生成训练计划。")
    if not isinstance(analysis.report, dict):
        raise HTTPException(status_code=400, detail="当前分析缺少结构化报告，无法生成训练计划。")

    existing_plan = await _get_plan_by_analysis(session, analysis_id)
    if existing_plan is not None:
        return _plan_detail_from_model(existing_plan)

    skater = await _resolve_skater(session, analysis.skater_id)
    if skater is None:
        raise HTTPException(status_code=400, detail="当前系统尚未配置练习档案。")

    if analysis.skater_id != skater.id:
        analysis.skater_id = skater.id

    try:
        plan_json = await generate_training_plan(analysis.action_type, analysis.report, _skater_context(skater), skater.id)
    except PlanGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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
        raise HTTPException(status_code=404, detail="æœªæ‰¾åˆ°è¯¥åˆ†æžè®°å½•ã€‚")
    if analysis.status != "completed":
        raise HTTPException(status_code=400, detail="åªæœ‰ completed çŠ¶æ€çš„åˆ†æžæ‰èƒ½å¯¼å‡ºæŠ¥å‘Šã€‚")

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
        raise HTTPException(status_code=404, detail="?????????")

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

    if analysis.status in {"pending", "processing", "extracting_frames", "awaiting_target_selection", "analyzing", "generating_report"}:
        raise HTTPException(status_code=400, detail="????????????????")

    if retry_from is not None and not _is_retry_stage(retry_from):
        raise HTTPException(status_code=400, detail="retry_from ??? extract_frames / pose / biomechanics / vision / report ???")

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
        raise HTTPException(status_code=404, detail="????????????????")

    analysis.status = "pending"
    analysis.error_code = None
    analysis.error_detail = None
    analysis.error_message = None
    analysis.processing_timings = None
    analysis.pipeline_version = CURRENT_PIPELINE_VERSION
    analysis.retry_from_stage = retry_from_stage
    if retry_from_stage in {None, 'extract_frames', 'pose'}:
        analysis.target_lock_status = 'pending'
    analysis.updated_at = datetime.now(timezone.utc)
    await session.commit()

    background_tasks.add_task(process_analysis, analysis_id, retry_from_stage)
    if retry_from_stage:
        return AnalysisRetryResponse(message=f"?? {retry_from_stage} ??????????")
    return AnalysisRetryResponse(message="?????????")


@router.get("/{analysis_id}/target-preview", response_model=TargetPreviewResponse)
@router.get("/{analysis_id}/target_preview", response_model=TargetPreviewResponse)
async def get_target_preview(analysis_id: str, session: AsyncSession = Depends(get_session)) -> TargetPreviewResponse:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    frames_dir = _frames_dir_for_analysis(analysis)
    preview = build_target_preview(analysis_id, frame_names_from_dir(frames_dir), existing_target_lock=analysis.target_lock)
    return TargetPreviewResponse(
        analysis_id=analysis.id,
        status=analysis.status,
        auto_candidate_id=preview.auto_candidate_id,
        lock_confidence=preview.lock_confidence,
        preview_frame=preview.preview_frame,
        preview_frame_url=preview.preview_frame_url,
        candidates=preview.candidates,
        target_lock_status=analysis.target_lock_status,
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
    preview = build_target_preview(analysis_id, frame_names_from_dir(frames_dir), existing_target_lock=analysis.target_lock)
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
    if not filename.startswith("frame_") or not filename.endswith(".jpg"):
        raise HTTPException(status_code=400, detail="无效的帧文件名。")

    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")

    analysis, restored_frames_dir = await _restore_missing_analysis_frames(session, analysis)
    frames_root = restored_frames_dir.resolve() if restored_frames_dir.exists() else (UPLOADS_DIR / analysis_id / "frames").resolve()
    frame_path = (frames_root / filename).resolve()
    if frames_root not in frame_path.parents or not frame_path.exists():
        raise HTTPException(status_code=404, detail="未找到该视频帧。")

    return FileResponse(frame_path, media_type="image/jpeg")
