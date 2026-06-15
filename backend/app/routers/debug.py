from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, UPLOADS_DIR, get_session
from app.models import Analysis, DebugRun
from app.routers.analysis import (
    CONFIRMED_TARGET_LOCK_STATUSES,
    VALID_ACTION_TYPES,
    _build_bbox_per_frame,
    _pose_debug_summary,
    _safe_video_response_path,
    _tracker_debug_summary,
)
from app.schemas import DebugRunCreateResponse, DebugRunDetail, DebugRunSummary
from app.services.action_profiles import (
    infer_analysis_profile,
    infer_profile_from_input,
    infer_profile_hint,
    is_mixed_action_input,
    normalize_action_subtype,
)
from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError, stringify_exception
from app.services.biomechanics import analyze_biomechanics, attach_key_frame_candidates
from app.services.person_tracker import detect_person_candidates
from app.services.pose import extract_pose
from app.services.target_lock import (
    TARGET_LOCK_AUTO_THRESHOLD,
    TargetPreview,
    build_target_lock_payload,
    build_target_preview,
    resolve_manual_candidate,
    select_stable_target_candidate,
    target_preview_anchor_frame_indices,
)
from app.services.video import (
    VideoSamplingMetadata,
    VideoInputWindow,
    attach_input_window_payload,
    build_video_input_window,
    extract_motion_sampled_frames,
    precheck_video,
    restore_sampled_frames,
    save_upload_file,
)
from app.services.semantic_keyframe_pipeline import effective_timestamp_source, run_semantic_keyframe_pipeline


router = APIRouter(prefix="/api/debug", tags=["debug"])
logger = logging.getLogger(__name__)

DEBUG_MODES = {"local_pose_keyframes", "video_ai_keyframes"}
DEBUG_SOURCE_TYPES = {"analysis", "upload"}
DEBUG_STATUSES = {"pending", "processing", "awaiting_target_selection", "completed", "failed"}
DEBUG_FRAME_PREFIXES = ("frame_", "semantic_", "partial_semantic_")
DEBUG_FRAME_SUFFIX = ".jpg"
CONFIRMED_DEBUG_TARGET_LOCK_STATUSES = {*CONFIRMED_TARGET_LOCK_STATUSES, "auto_locked"}
DEBUG_SAMPLING_ANALYSIS_REPLAY = "analysis_replay"
DEBUG_SAMPLING_FORMAL_RESAMPLE = "formal_pipeline_resample"
DEBUG_SAMPLING_UPLOAD_FORMAL = "upload_formal_pipeline"
DEBUG_DB_WRITE_ATTEMPTS = 5
DEBUG_DB_WRITE_RETRY_DELAY_SECONDS = 0.15
DEBUG_VIDEO_AI_STAGE_LABELS = {
    "ai_clip_ready": "Action-window AI clip is ready; waiting for Video AI.",
    "video_temporal_received": "Video AI returned temporal JSON; resolving keyframes.",
    "video_temporal_retry": "Video AI result failed quality gates; retrying with resolver diagnostics.",
    "video_temporal_retry_used": "Video AI retry produced reliable semantic keyframes.",
    "semantic_frames_resolved": "Semantic keyframe timestamps resolved; finalizing debug result.",
}
DEBUG_VIDEO_AI_STAGE_PROGRESS = {
    "ai_clip_ready": 0.4,
    "video_temporal_received": 0.78,
    "video_temporal_retry": 0.84,
    "video_temporal_retry_used": 0.9,
    "semantic_frames_resolved": 0.92,
}


class DebugAwaitingTargetSelection(Exception):
    def __init__(self, result_json: dict[str, Any], summary: dict[str, Any]) -> None:
        super().__init__("Debug run is awaiting target selection.")
        self.result_json = result_json
        self.summary = summary


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _elapsed(start_time: float) -> float:
    return round(time.monotonic() - start_time, 2)


def _as_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _is_sqlite_locked_error(exc: BaseException) -> bool:
    if "database is locked" in str(exc).lower():
        return True
    orig = getattr(exc, "orig", None)
    return orig is not None and "database is locked" in str(orig).lower()


async def _with_debug_db_write_retry(operation: Any, *, context: str) -> Any:
    last_error: BaseException | None = None
    for attempt in range(DEBUG_DB_WRITE_ATTEMPTS):
        try:
            return await operation()
        except OperationalError as exc:
            if not _is_sqlite_locked_error(exc):
                raise
            last_error = exc
            if attempt == DEBUG_DB_WRITE_ATTEMPTS - 1:
                break
            await asyncio.sleep(DEBUG_DB_WRITE_RETRY_DELAY_SECONDS * (2**attempt))
    assert last_error is not None
    logger.warning("Debug DB write failed after retries during %s: %s", context, last_error)
    raise last_error


def _debug_root(run_id: str) -> Path:
    root = UPLOADS_DIR / "_debug" / run_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _debug_frames_dir(run_id: str) -> Path:
    frames_dir = _debug_root(run_id) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    return frames_dir


def _debug_semantic_frames_dir(run_id: str) -> Path:
    frames_dir = _debug_root(run_id) / "semantic_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    return frames_dir


def _sampling_metadata_payload(metadata: VideoSamplingMetadata) -> dict[str, Any]:
    return {
        "action_window_start": metadata.action_window_start,
        "action_window_end": metadata.action_window_end,
        "window_start_sec": metadata.window_start_sec,
        "window_end_sec": metadata.window_end_sec,
        "effective_fps": metadata.effective_fps,
        "source_fps": metadata.source_fps,
        "is_slow_motion": metadata.is_slow_motion,
    }


def _input_window_payload_from_motion(motion_scores: dict[str, Any] | object) -> dict[str, Any]:
    if not isinstance(motion_scores, dict):
        return {}
    payload = motion_scores.get("input_window")
    if isinstance(payload, dict):
        return _as_jsonable(payload)
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


def _with_input_window_fields(payload: dict[str, Any], input_window: dict[str, Any] | None = None) -> dict[str, Any]:
    window = input_window if isinstance(input_window, dict) else payload.get("input_window")
    if not isinstance(window, dict):
        return payload
    return {**payload, "input_window": window, **_as_jsonable(window)}


def _manual_input_window_from_summary(run: DebugRun) -> tuple[float | None, float | None]:
    summary = run.summary if isinstance(run.summary, dict) else {}
    start = summary.get("manual_action_window_start_sec")
    end = summary.get("manual_action_window_end_sec")
    try:
        return (
            float(start) if start is not None else None,
            float(end) if end is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def _debug_input_window_for_run(run: DebugRun, video_path: Path) -> VideoInputWindow:
    manual_start, manual_end = _manual_input_window_from_summary(run)
    return build_video_input_window(video_path, manual_start_sec=manual_start, manual_end_sec=manual_end)


def _sampling_metadata_from_payload(payload: object) -> VideoSamplingMetadata | None:
    if not isinstance(payload, dict):
        return None
    try:
        return VideoSamplingMetadata(
            float(payload["action_window_start"]),
            float(payload["action_window_end"]),
            float(payload.get("window_start_sec", payload["action_window_start"])),
            float(payload.get("window_end_sec", payload["action_window_end"])),
            float(payload["effective_fps"]),
            float(payload["source_fps"]),
            bool(payload.get("is_slow_motion", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _sampling_metadata_from_analysis(analysis: Analysis, motion_scores: dict[str, Any]) -> VideoSamplingMetadata:
    selected = motion_scores.get("selected") if isinstance(motion_scores.get("selected"), list) else []
    sample_count = len(selected) if len(selected) >= 2 else int(motion_scores.get("sample_count") or 2)
    action_window_start = _float_or_none(motion_scores.get("window_start")) or _float_or_none(analysis.action_window_start) or 0.0
    action_window_end = _float_or_none(motion_scores.get("window_end")) or _float_or_none(analysis.action_window_end)
    if action_window_end is None:
        last_timestamp = None
        if selected and isinstance(selected[-1], dict):
            last_timestamp = _float_or_none(selected[-1].get("timestamp"))
        action_window_end = last_timestamp if last_timestamp is not None else action_window_start + 1.0
    window_start_sec = _float_or_none(motion_scores.get("window_start_sec"))
    window_end_sec = _float_or_none(motion_scores.get("window_end_sec"))
    if window_start_sec is None:
        window_start_sec = action_window_start
    if window_end_sec is None:
        window_end_sec = action_window_end
    effective_fps = _float_or_none(motion_scores.get("effective_fps"))
    if effective_fps is None or effective_fps <= 0:
        effective_fps = (max(sample_count, 2) - 1) / max(window_end_sec - window_start_sec, 1e-6)
    source_fps = _float_or_none(motion_scores.get("source_fps")) or _float_or_none(analysis.source_fps) or 30.0
    is_slow_motion = bool(motion_scores.get("is_slow_motion", analysis.is_slow_motion))
    return VideoSamplingMetadata(
        action_window_start=round(action_window_start, 3),
        action_window_end=round(action_window_end, 3),
        window_start_sec=round(window_start_sec, 3),
        window_end_sec=round(window_end_sec, 3),
        effective_fps=round(effective_fps, 3),
        source_fps=round(source_fps, 3),
        is_slow_motion=is_slow_motion,
    )


async def _source_analysis_for_run(run: DebugRun) -> Analysis | None:
    if run.source_type != "analysis" or not run.analysis_id:
        return None
    async with AsyncSessionLocal() as session:
        return await session.get(Analysis, run.analysis_id)


async def _prepare_formal_debug_sampling(
    run: DebugRun,
    video_path: Path,
    frames_dir: Path,
    timings: dict[str, float],
) -> tuple[list[Path], dict[str, Any], VideoSamplingMetadata, str]:
    precheck_start = time.monotonic()
    await precheck_video(video_path)
    timings["precheck_s"] = _elapsed(precheck_start)
    input_window = _debug_input_window_for_run(run, video_path)

    analysis = await _source_analysis_for_run(run)
    if analysis is not None and isinstance(analysis.frame_motion_scores, dict):
        selected = analysis.frame_motion_scores.get("selected")
        if isinstance(selected, list) and selected:
            extract_start = time.monotonic()
            sampled_frames = await restore_sampled_frames(video_path, frames_dir, selected)
            timings["extract_frames_s"] = _elapsed(extract_start)
            if sampled_frames:
                motion_scores = _as_jsonable(analysis.frame_motion_scores)
                if not _input_window_payload_from_motion(motion_scores):
                    if analysis.action_window_start is not None and analysis.action_window_end is not None:
                        legacy_start = float(analysis.action_window_start)
                        legacy_end = float(analysis.action_window_end)
                        attach_input_window_payload(
                            motion_scores,
                            VideoInputWindow(
                                source_duration_sec=input_window.source_duration_sec,
                                input_window_start_sec=legacy_start,
                                input_window_end_sec=legacy_end,
                                input_window_duration_sec=round(max(0.0, legacy_end - legacy_start), 3),
                                input_window_mode="legacy_action_window",
                                input_window_truncated=False,
                                input_window_reason="legacy_saved_analysis",
                            ),
                        )
                    else:
                        attach_input_window_payload(motion_scores, input_window)
                sampling_metadata = _sampling_metadata_from_analysis(analysis, motion_scores)
                return sampled_frames, motion_scores, sampling_metadata, DEBUG_SAMPLING_ANALYSIS_REPLAY

    extract_start = time.monotonic()
    sampled_frames, motion_scores, sampling_metadata = await extract_motion_sampled_frames(
        video_path,
        frames_dir,
        run.action_type,
        run.analysis_profile,
        input_window=input_window,
    )
    attach_input_window_payload(motion_scores, input_window)
    timings["extract_frames_s"] = _elapsed(extract_start)
    sampling_source = DEBUG_SAMPLING_FORMAL_RESAMPLE if run.source_type == "analysis" else DEBUG_SAMPLING_UPLOAD_FORMAL
    return sampled_frames, _as_jsonable(motion_scores), sampling_metadata, sampling_source


def _frame_url(run_id: str, frame_name: str) -> str:
    return f"/api/debug/runs/{run_id}/frames/{frame_name}"


def _debug_preview_from_payload(run_id: str, payload: object) -> TargetPreview:
    data = payload if isinstance(payload, dict) else {}
    return TargetPreview(
        preview_frame=str(data.get("preview_frame")) if data.get("preview_frame") else None,
        preview_frame_url=_frame_url(run_id, str(data.get("preview_frame"))) if data.get("preview_frame") else None,
        preview_frame_index=int(data["preview_frame_index"]) if data.get("preview_frame_index") is not None else None,
        auto_candidate_id=str(data.get("auto_candidate_id")) if data.get("auto_candidate_id") else None,
        lock_confidence=float(data.get("lock_confidence") or 0.0),
        candidates=[item for item in data.get("candidates", []) if isinstance(item, dict)] if isinstance(data.get("candidates"), list) else [],
        target_lock_status=str(data.get("target_lock_status") or "awaiting_manual"),
    )


def _target_preview_payload(
    *,
    run_id: str,
    preview: TargetPreview,
    source_target_lock_status: str | None = None,
    source_target_lock_reused: bool = False,
) -> dict[str, Any]:
    return {
        "preview_frame": preview.preview_frame,
        "preview_frame_url": _frame_url(run_id, preview.preview_frame) if preview.preview_frame else None,
        "preview_frame_index": preview.preview_frame_index,
        "auto_candidate_id": preview.auto_candidate_id,
        "lock_confidence": preview.lock_confidence,
        "target_lock_status": preview.target_lock_status,
        "candidates": preview.candidates,
        "auto_lock_threshold": TARGET_LOCK_AUTO_THRESHOLD,
        "source_target_lock_status": source_target_lock_status,
        "source_target_lock_reused": source_target_lock_reused,
    }


def _frame_records(run_id: str, frame_paths: list[Path], selected: object | None = None) -> list[dict[str, Any]]:
    selected_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, dict) and isinstance(item.get("frame_id"), str):
                selected_by_id[item["frame_id"]] = item
    records: list[dict[str, Any]] = []
    for path in frame_paths:
        item = dict(selected_by_id.get(path.stem, {}))
        item["frame_id"] = path.stem
        item["filename"] = path.name
        item["url"] = _frame_url(run_id, path.name)
        records.append(item)
    return records


def _semantic_records(run_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in records:
        frame_id = item.get("frame_id")
        frame_name = f"{frame_id}.jpg" if isinstance(frame_id, str) else None
        payload = dict(item)
        if frame_name:
            payload["filename"] = frame_name
            payload["url"] = _frame_url(run_id, frame_name)
        out.append(payload)
    return out


def _quality_flags(*sources: object) -> list[str]:
    flags: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        raw_flags = source.get("quality_flags")
        if not isinstance(raw_flags, list):
            continue
        for flag in raw_flags:
            value = str(flag).strip()
            if value and value not in flags:
                flags.append(value)
    return flags


def _merge_quality_flag(data: dict[str, Any], flag: str) -> dict[str, Any]:
    flags: list[str] = []
    if isinstance(data.get("quality_flags"), list):
        for item in data["quality_flags"]:
            value = str(item).strip()
            if value and value not in flags:
                flags.append(value)
    if flag not in flags:
        flags.append(flag)
    return {**data, "quality_flags": flags}


def _upload_target_anchor_frame_indices(
    sampled_frames: list[Path],
    motion_scores: dict[str, Any] | object,
) -> list[int]:
    return target_preview_anchor_frame_indices(
        [frame.name for frame in sampled_frames],
        motion_scores if isinstance(motion_scores, dict) else None,
    )


def _select_upload_target_candidate(anchor_candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    selected = select_stable_target_candidate(anchor_candidates)
    if selected is None:
        return None
    selected = dict(selected)
    selected["id"] = "candidate_auto_stable"
    selected["source"] = str(selected.get("source") or "yolo_preview_multi_anchor")
    return selected


def _video_ai_upload_target_lock(
    run: DebugRun,
    *,
    sampled_frames: list[Path],
    motion_scores: dict[str, Any] | object,
) -> dict[str, Any] | None:
    saved_result = run.result_json if isinstance(run.result_json, dict) else {}
    saved_target_lock = saved_result.get("target_lock")
    if isinstance(saved_target_lock, dict) and isinstance(saved_target_lock.get("selected_bbox"), dict):
        target_lock = _as_jsonable(saved_target_lock)
        target_lock["debug_source"] = str(target_lock.get("debug_source") or "debug_saved_target_lock")
        return target_lock

    frame_names = [frame.name for frame in sampled_frames]
    anchor_candidates: list[dict[str, Any]] = []
    for anchor_index in _upload_target_anchor_frame_indices(sampled_frames, motion_scores):
        if anchor_index < 0 or anchor_index >= len(sampled_frames):
            continue
        frame_path = sampled_frames[anchor_index]
        try:
            detected = detect_person_candidates(frame_path, include_zoomed_small_targets=True)
        except Exception as exc:  # noqa: BLE001
            logger.info("Debug run %s could not auto-detect upload target candidates: %s", run.id, exc)
            continue
        for candidate in detected:
            item = dict(candidate)
            item["id"] = f"anchor_{anchor_index}_{candidate.get('id') or len(anchor_candidates) + 1}"
            item["anchor_frame"] = frame_path.name
            item["anchor_index"] = anchor_index
            anchor_candidates.append(item)

    selected_candidate = _select_upload_target_candidate(anchor_candidates)
    if selected_candidate is None:
        return None
    existing_target_lock = (
        {
            "preview_frame": selected_candidate.get("anchor_frame"),
            "preview_frame_index": selected_candidate.get("anchor_index"),
            "candidates": [selected_candidate],
        }
    )
    preview = build_target_preview(
        run.id,
        frame_names,
        existing_target_lock=existing_target_lock,
        motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
        detected_candidates=[selected_candidate, *anchor_candidates],
        analysis_profile=run.analysis_profile,
    )
    if preview.lock_confidence < TARGET_LOCK_AUTO_THRESHOLD:
        return None
    target_lock = build_target_lock_payload(preview)
    if not isinstance(target_lock.get("selected_bbox"), dict):
        return None
    target_lock["debug_source"] = "debug_upload_auto_target_lock"
    return target_lock


async def _video_ai_debug_bio_data(
    run: DebugRun,
    *,
    sampled_frames: list[Path],
    motion_scores: dict[str, Any] | object,
    sampling_metadata: VideoSamplingMetadata,
    timings: dict[str, float],
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    upload_auto_bio = False
    if run.source_type == "analysis":
        source_target_lock = await _source_target_lock_for_run(run)
        source_target_lock_status = str(source_target_lock.get("status")) if isinstance(source_target_lock, dict) else None
        if not source_target_lock or source_target_lock_status not in CONFIRMED_DEBUG_TARGET_LOCK_STATUSES:
            return {"quality_flags": ["debug_video_ai_no_confirmed_target_lock"]}, None, None, None

        target_lock = _as_jsonable(source_target_lock)
        target_lock["debug_source"] = "analysis_target_lock"
    else:
        target_lock = _video_ai_upload_target_lock(
            run,
            sampled_frames=sampled_frames,
            motion_scores=motion_scores,
        )
        if not target_lock:
            return {"quality_flags": ["debug_video_ai_no_bio_candidates_upload_source"]}, None, None, None
        upload_auto_bio = target_lock.get("debug_source") == "debug_upload_auto_target_lock"
    try:
        pose_start = time.monotonic()
        bbox_per_frame = _build_bbox_per_frame(sampled_frames, target_lock, sampling_metadata.effective_fps)
        tracker_summary = _tracker_debug_summary(target_lock, len(sampled_frames))
        pose_data = await asyncio.to_thread(
            extract_pose,
            str(_debug_frames_dir(run.id)),
            target_lock,
            bbox_per_frame,
            sampling_metadata.effective_fps,
        )
        timings["pose_s"] = _elapsed(pose_start)

        bio_start = time.monotonic()
        analysis_profile, profile_evidence = infer_analysis_profile(run.action_type, run.action_subtype, pose_data, motion_scores)
        bio_data = analyze_biomechanics(
            pose_data,
            run.action_type,
            analysis_profile,
            effective_fps=sampling_metadata.effective_fps,
            source_fps=sampling_metadata.source_fps,
            window_seconds=sampling_metadata.window_end_sec - sampling_metadata.window_start_sec,
        )
        bio_data = attach_key_frame_candidates(
            bio_data,
            pose_data,
            motion_scores if isinstance(motion_scores, dict) else None,
            analysis_profile,
            sampling_metadata.effective_fps,
        )
        if upload_auto_bio:
            bio_data = _merge_quality_flag(bio_data, "debug_video_ai_upload_auto_bio_candidates_used")
        bio_data["profile_evidence"] = profile_evidence
        timings["biomechanics_s"] = _elapsed(bio_start)
        return bio_data, pose_data, target_lock, tracker_summary
    except Exception as exc:  # noqa: BLE001
        logger.warning("Debug run %s failed to prepare video AI bio candidates: %s", run.id, exc, exc_info=True)
        return {
            "quality_flags": ["debug_video_ai_bio_candidates_failed"],
            "debug_bio_error": stringify_exception(exc),
        }, None, target_lock, None


def _debug_summary_from_model(run: DebugRun) -> DebugRunSummary:
    return DebugRunSummary(
        id=run.id,
        mode=run.mode,
        source_type=run.source_type,
        analysis_id=run.analysis_id,
        action_type=run.action_type,
        action_subtype=run.action_subtype,
        analysis_profile=run.analysis_profile,
        note=run.note,
        status=run.status,
        summary=run.summary,
        error_code=run.error_code,
        created_at=_as_utc_datetime(run.created_at),
        updated_at=_as_utc_datetime(run.updated_at),
    )


def _debug_detail_from_model(run: DebugRun) -> DebugRunDetail:
    return DebugRunDetail(
        **_debug_summary_from_model(run).model_dump(),
        video_path=run.video_path,
        result_json=run.result_json,
        error_detail=run.error_detail,
    )


async def _mark_run_processing(run_id: str) -> DebugRun | None:
    async def _write() -> DebugRun | None:
        async with AsyncSessionLocal() as session:
            run = await session.get(DebugRun, run_id)
            if run is None:
                return None
            run.status = "processing"
            run.error_code = None
            run.error_detail = None
            run.updated_at = _utc_now()
            await session.commit()
            await session.refresh(run)
            return run

    return await _with_debug_db_write_retry(_write, context="mark_run_processing")


async def _update_run_progress(run_id: str, *, stage: str, label: str, progress: float, **extra: Any) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            run = await session.get(DebugRun, run_id)
            if run is None or run.status not in {"pending", "processing"}:
                return
            summary = dict(run.summary) if isinstance(run.summary, dict) else {}
            timings = summary.get("timings") if isinstance(summary.get("timings"), dict) else {}
            update_extra = dict(extra)
            if "timings" in update_extra and isinstance(update_extra["timings"], dict):
                timings = {**timings, **update_extra.pop("timings")}
            if isinstance(update_extra.get("input_window"), dict):
                update_extra = _with_input_window_fields(update_extra)
            summary.update(
                {
                    "status": run.status,
                    "stage": stage,
                    "stage_label": label,
                    "progress": max(0.0, min(1.0, progress)),
                    **update_extra,
                }
            )
            if timings:
                summary["timings"] = timings
            run.summary = _as_jsonable(summary)
            run.updated_at = _utc_now()
            await session.commit()

    try:
        await _with_debug_db_write_retry(_write, context=f"update_run_progress:{stage}")
    except OperationalError as exc:
        if not _is_sqlite_locked_error(exc):
            raise
        logger.warning("Skipping debug progress update for %s at %s because the database is busy.", run_id, stage)


async def _mark_run_completed(run_id: str, *, result_json: dict[str, Any], summary: dict[str, Any]) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            run = await session.get(DebugRun, run_id)
            if run is None:
                return
            run.status = "completed"
            run.result_json = _as_jsonable(_with_input_window_fields(dict(result_json)))
            run.summary = _as_jsonable(_with_input_window_fields(dict(summary)))
            run.error_code = None
            run.error_detail = None
            run.updated_at = _utc_now()
            await session.commit()

    await _with_debug_db_write_retry(_write, context="mark_run_completed")


async def _mark_run_failed(run_id: str, *, code: str, detail: str, result_json: dict[str, Any] | None = None) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            run = await session.get(DebugRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.error_code = code
            run.error_detail = detail
            existing_summary = run.summary if isinstance(run.summary, dict) else {}
            existing_input_window = existing_summary.get("input_window") if isinstance(existing_summary.get("input_window"), dict) else None
            run.result_json = _as_jsonable(_with_input_window_fields(result_json or {"error": detail}, existing_input_window))
            run.summary = _as_jsonable(_with_input_window_fields({"status": "failed", "error_code": code}, existing_input_window))
            run.updated_at = _utc_now()
            await session.commit()

    await _with_debug_db_write_retry(_write, context="mark_run_failed")


async def _mark_run_awaiting_target_selection(run_id: str, *, result_json: dict[str, Any], summary: dict[str, Any]) -> None:
    async def _write() -> None:
        async with AsyncSessionLocal() as session:
            run = await session.get(DebugRun, run_id)
            if run is None:
                return
            run.status = "awaiting_target_selection"
            run.result_json = _as_jsonable(_with_input_window_fields(dict(result_json)))
            run.summary = _as_jsonable(_with_input_window_fields(dict(summary)))
            run.error_code = None
            run.error_detail = None
            run.updated_at = _utc_now()
            await session.commit()

    await _with_debug_db_write_retry(_write, context="mark_run_awaiting_target_selection")


def _require_debug_video_path(run: DebugRun) -> Path:
    if not run.video_path:
        raise RuntimeError("Debug run has no source video path.")
    path = Path(run.video_path)
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Debug source video is not available: {path}")
    return path


async def _source_video_for_analysis(session: AsyncSession, analysis_id: str) -> tuple[Analysis, Path]:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    video_path = _safe_video_response_path(analysis)
    if video_path is None:
        raise HTTPException(status_code=404, detail="Analysis source video is not available.")
    return analysis, video_path


async def _source_target_lock_for_run(run: DebugRun) -> dict[str, Any] | None:
    if run.source_type != "analysis" or not run.analysis_id:
        return None
    async with AsyncSessionLocal() as session:
        analysis = await session.get(Analysis, run.analysis_id)
        if analysis is None or not isinstance(analysis.target_lock, dict):
            return None
        return _as_jsonable(analysis.target_lock)


async def _create_debug_run(
    *,
    mode: str,
    background_tasks: BackgroundTasks,
    analysis_id: str | None,
    file: UploadFile | None,
    action_type: str | None,
    action_subtype: str | None,
    analysis_profile: str | None,
    note: str | None,
    manual_action_window_start_sec: float | None,
    manual_action_window_end_sec: float | None,
    session: AsyncSession,
) -> DebugRunCreateResponse:
    if mode not in DEBUG_MODES:
        raise HTTPException(status_code=400, detail="Invalid debug mode.")
    if analysis_id and file is not None:
        raise HTTPException(status_code=400, detail="Provide either analysis_id or file, not both.")
    if not analysis_id and file is None:
        raise HTTPException(status_code=400, detail="Provide analysis_id or file.")

    run_id = str(uuid4())
    source_type = "analysis" if analysis_id else "upload"
    video_path: Path
    resolved_action_type = action_type
    resolved_action_subtype = action_subtype
    resolved_profile = analysis_profile

    if analysis_id:
        analysis, video_path = await _source_video_for_analysis(session, analysis_id)
        resolved_action_type = resolved_action_type or analysis.action_type
        resolved_action_subtype = resolved_action_subtype if resolved_action_subtype is not None else analysis.action_subtype
        resolved_profile = resolved_profile or analysis.analysis_profile or infer_profile_hint(resolved_action_type, resolved_action_subtype)
    else:
        if not resolved_action_type:
            raise HTTPException(status_code=400, detail="action_type is required for debug upload.")
        suffix = Path(file.filename or "").suffix.lower() if file is not None else ""
        video_path = _debug_root(run_id) / f"source{suffix}"
        try:
            await save_upload_file(file, video_path)  # type: ignore[arg-type]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        resolved_profile = resolved_profile or infer_profile_from_input(resolved_action_type, resolved_action_subtype)

    if resolved_action_type not in VALID_ACTION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid action_type.")
    resolved_action_subtype = normalize_action_subtype(resolved_action_type, resolved_action_subtype)
    if resolved_profile is None and not is_mixed_action_input(resolved_action_type, resolved_action_subtype):
        resolved_profile = infer_profile_hint(resolved_action_type, resolved_action_subtype)
    input_window = build_video_input_window(
        video_path,
        manual_start_sec=manual_action_window_start_sec,
        manual_end_sec=manual_action_window_end_sec,
    )
    manual_payload = (
        {
            "manual_action_window_start_sec": input_window.input_window_start_sec,
            "manual_action_window_end_sec": input_window.input_window_end_sec,
        }
        if input_window.input_window_mode == "manual_window"
        else {}
    )

    run = DebugRun(
        id=run_id,
        mode=mode,
        source_type=source_type,
        analysis_id=analysis_id,
        video_path=str(video_path),
        action_type=resolved_action_type,
        action_subtype=resolved_action_subtype,
        analysis_profile=resolved_profile,
        note=note,
        status="pending",
        summary=_with_input_window_fields({"status": "pending", **manual_payload, "input_window": input_window.to_payload()}),
        result_json=None,
    )
    session.add(run)
    await session.commit()

    background_tasks.add_task(process_debug_run, run_id)
    return DebugRunCreateResponse(id=run_id, status="pending")


async def _run_local_pose_keyframes(run: DebugRun) -> tuple[dict[str, Any], dict[str, Any]]:
    start = time.monotonic()
    saved_result = run.result_json if isinstance(run.result_json, dict) else {}
    timings: dict[str, float] = dict(saved_result.get("timings") if isinstance(saved_result.get("timings"), dict) else {})
    video_path = _require_debug_video_path(run)
    frames_dir = _debug_frames_dir(run.id)
    motion_scores: dict[str, Any] | object
    sampling_metadata: VideoSamplingMetadata | None = _sampling_metadata_from_payload(saved_result.get("sampling_metadata"))
    sampling_source = str(saved_result.get("sampling_source") or "")
    sampled_frames = sorted(frames_dir.glob("frame_*.jpg"))

    if sampled_frames and isinstance(saved_result.get("motion_scores"), dict) and sampling_metadata is not None:
        motion_scores = saved_result["motion_scores"]
        default_sampling_source = DEBUG_SAMPLING_ANALYSIS_REPLAY if run.source_type == "analysis" else DEBUG_SAMPLING_UPLOAD_FORMAL
        sampling_source = sampling_source or str(saved_result.get("sampling_source") or default_sampling_source)
    else:
        sampled_frames, motion_scores, sampling_metadata, sampling_source = await _prepare_formal_debug_sampling(
            run,
            video_path,
            frames_dir,
            timings,
        )
    if sampling_metadata is None:
        raise RuntimeError("Debug sampling metadata is not available.")
    input_window_payload = _input_window_payload_from_motion(motion_scores)

    source_target_lock = await _source_target_lock_for_run(run) if sampling_source == DEBUG_SAMPLING_ANALYSIS_REPLAY else None
    source_target_lock_status = str(source_target_lock.get("status")) if isinstance(source_target_lock, dict) else None
    saved_preview = saved_result.get("target_preview")
    preview = (
        _debug_preview_from_payload(run.id, saved_preview)
        if isinstance(saved_preview, dict)
        else build_target_preview(
            run.id,
            [frame.name for frame in sampled_frames],
            existing_target_lock=source_target_lock,
            motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
            analysis_profile=run.analysis_profile,
        )
    )
    if source_target_lock and source_target_lock_status in CONFIRMED_DEBUG_TARGET_LOCK_STATUSES:
        target_lock = source_target_lock
        target_lock["debug_source"] = "analysis_target_lock"
    elif isinstance(saved_result.get("target_lock"), dict) and isinstance(saved_result["target_lock"].get("selected_bbox"), dict):
        target_lock = _as_jsonable(saved_result["target_lock"])
    else:
        target_lock = build_target_lock_payload(preview)
    if not isinstance(target_lock.get("selected_bbox"), dict):
        preview_payload = _target_preview_payload(
            run_id=run.id,
            preview=preview,
            source_target_lock_status=source_target_lock_status,
            source_target_lock_reused=False,
        )
        result_json = {
            **saved_result,
            "mode": run.mode,
            "source_type": run.source_type,
            "analysis_id": run.analysis_id,
            "action_type": run.action_type,
            "action_subtype": run.action_subtype,
            "analysis_profile": run.analysis_profile,
            "note": run.note,
            "sampling_source": sampling_source,
            "sampling_metadata": _sampling_metadata_payload(sampling_metadata),
            "input_window": input_window_payload,
            "motion_scores": motion_scores,
            "sampled_frames": _frame_records(run.id, sampled_frames, motion_scores.get("selected") if isinstance(motion_scores, dict) else None),
            "target_preview": preview_payload,
            "target_lock": target_lock,
            "timings": timings,
            "quality_flags": _quality_flags(target_lock),
        }
        summary = {
            "status": "awaiting_target_selection",
            "timings": timings,
            "frame_count": len(sampled_frames),
            "sampling_source": sampling_source,
            "input_window": input_window_payload,
            "target_preview": preview_payload,
            "quality_flags": ["debug_awaiting_manual_target_lock"],
        }
        raise DebugAwaitingTargetSelection(result_json, summary)

    pose_start = time.monotonic()
    bbox_per_frame = _build_bbox_per_frame(sampled_frames, target_lock, sampling_metadata.effective_fps)
    tracker_summary = _tracker_debug_summary(target_lock, len(sampled_frames))
    pose_data = await asyncio.to_thread(
        extract_pose,
        str(frames_dir),
        target_lock,
        bbox_per_frame,
        sampling_metadata.effective_fps,
    )
    pose_summary = _pose_debug_summary(pose_data)
    timings["pose_s"] = _elapsed(pose_start)

    bio_start = time.monotonic()
    analysis_profile, profile_evidence = infer_analysis_profile(run.action_type, run.action_subtype, pose_data, motion_scores)
    bio_data = analyze_biomechanics(
        pose_data,
        run.action_type,
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
    bio_data["profile_evidence"] = profile_evidence
    timings["biomechanics_s"] = _elapsed(bio_start)
    timings["total_s"] = _elapsed(start)

    selected_records = motion_scores.get("selected") if isinstance(motion_scores, dict) else None
    result = {
        "mode": run.mode,
        "source_type": run.source_type,
        "analysis_id": run.analysis_id,
        "action_type": run.action_type,
        "action_subtype": run.action_subtype,
        "analysis_profile": analysis_profile,
        "note": run.note,
        "sampling_source": sampling_source,
        "sampling_metadata": _sampling_metadata_payload(sampling_metadata),
        "input_window": input_window_payload,
        "motion_scores": motion_scores,
        "sampled_frames": _frame_records(run.id, sampled_frames, selected_records),
        "target_preview": {
            **_target_preview_payload(
                run_id=run.id,
                preview=preview,
                source_target_lock_status=source_target_lock_status,
                source_target_lock_reused=target_lock.get("debug_source") == "analysis_target_lock",
            ),
        },
        "target_lock": target_lock,
        "tracker_summary": tracker_summary,
        "pose_data": pose_data,
        "pose_summary": pose_summary,
        "bio_data": bio_data,
        "key_frame_candidates": bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None,
        "timings": timings,
        "quality_flags": _quality_flags(target_lock, pose_data, bio_data),
    }
    summary = {
        "timings": timings,
        "frame_count": len(sampled_frames),
        "sampling_source": sampling_source,
        "input_window": input_window_payload,
        "analysis_profile": analysis_profile,
        "tracker": tracker_summary,
        "pose": pose_summary,
        "key_frame_candidates": bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None,
        "quality_flags": result["quality_flags"],
    }
    return result, summary


async def _run_video_ai_keyframes(run: DebugRun) -> tuple[dict[str, Any], dict[str, Any]]:
    start = time.monotonic()
    timings: dict[str, float] = {}
    video_path = _require_debug_video_path(run)
    frames_dir = _debug_frames_dir(run.id)
    initial_input_window = _debug_input_window_for_run(run, video_path)

    await _update_run_progress(
        run.id,
        stage="sampling",
        label="Preparing sampled frames from the formal pipeline.",
        progress=0.08,
        input_window=initial_input_window.to_payload(),
    )
    sampled_frames, motion_scores, sampling_metadata, sampling_source = await _prepare_formal_debug_sampling(
        run,
        video_path,
        frames_dir,
        timings,
    )
    input_window_payload = _input_window_payload_from_motion(motion_scores)
    input_window = _debug_input_window_for_run(run, video_path)
    await _update_run_progress(
        run.id,
        stage="video_ai",
        label="Calling Video AI for semantic keyframe timing.",
        progress=0.32,
        timings=timings,
        frame_count=len(sampled_frames),
        sampling_source=sampling_source,
        input_window=input_window_payload,
    )
    bio_data, pose_data, target_lock, tracker_summary = await _video_ai_debug_bio_data(
        run,
        sampled_frames=sampled_frames,
        motion_scores=motion_scores,
        sampling_metadata=sampling_metadata,
        timings=timings,
    )

    async def _semantic_progress(stage: str, payload: dict[str, Any]) -> None:
        await _update_run_progress(
            run.id,
            stage=stage,
            label=DEBUG_VIDEO_AI_STAGE_LABELS.get(stage, stage),
            progress=DEBUG_VIDEO_AI_STAGE_PROGRESS.get(stage, 0.5),
            timings=timings,
            **payload,
        )

    video_ai_start = time.monotonic()
    semantic_result = await run_semantic_keyframe_pipeline(
        video_path=video_path,
        work_dir=_debug_root(run.id),
        semantic_frames_dir=_debug_semantic_frames_dir(run.id),
        sampling_metadata=sampling_metadata,
        action_type=run.action_type,
        action_subtype=run.action_subtype,
        motion_scores=motion_scores if isinstance(motion_scores, dict) else None,
        analysis_profile=run.analysis_profile,
        bio_data=bio_data,
        analyzed_video_kind="debug_action_window_ai",
        input_window=input_window,
        precheck=False,
        progress_callback=_semantic_progress,
    )
    timings["video_ai_keyframes_s"] = _elapsed(video_ai_start)
    timings["total_s"] = _elapsed(start)
    effective_source = effective_timestamp_source(
        semantic_result.resolved_keyframes,
        semantic_result.used_semantic_frames,
    )

    result = {
        "mode": run.mode,
        "source_type": run.source_type,
        "analysis_id": run.analysis_id,
        "action_type": run.action_type,
        "action_subtype": run.action_subtype,
        "analysis_profile": run.analysis_profile,
        "note": run.note,
        "sampling_source": sampling_source,
        "sampling_metadata": _sampling_metadata_payload(sampling_metadata),
        "input_window": input_window_payload,
        "motion_scores": motion_scores,
        "sampled_frames": _frame_records(run.id, sampled_frames, motion_scores.get("selected") if isinstance(motion_scores, dict) else None),
        "target_lock": target_lock,
        "tracker_summary": tracker_summary,
        "pose_data": pose_data,
        "bio_data": bio_data,
        "key_frame_candidates": bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None,
        "ai_clip": semantic_result.ai_clip,
        "video_temporal": semantic_result.video_temporal,
        "resolved_keyframes": semantic_result.resolved_keyframes,
        "effective_timestamp_source": effective_source,
        "refinement_flags": semantic_result.refinement_flags,
        "semantic_frames": _semantic_records(run.id, semantic_result.semantic_records),
        "partial_semantic_frames": _semantic_records(run.id, semantic_result.partial_semantic_records),
        "used_semantic_frames": semantic_result.used_semantic_frames,
        "timings": timings,
        "quality_flags": semantic_result.quality_flags,
    }
    action_window_summary = {
        "start_sec": sampling_metadata.action_window_start,
        "end_sec": sampling_metadata.action_window_end,
        "duration_sec": round(sampling_metadata.action_window_end - sampling_metadata.action_window_start, 3),
    }
    summary = {
        "timings": timings,
        "sampling_source": sampling_source,
        "action_window": action_window_summary,
        "input_window": input_window_payload,
        "timestamp_source": effective_source,
        "video_ai_confidence": semantic_result.video_temporal.get("confidence") if isinstance(semantic_result.video_temporal, dict) else None,
        "resolved_source": effective_source,
        "resolver_source": semantic_result.resolved_keyframes.get("source") if isinstance(semantic_result.resolved_keyframes, dict) else None,
        "resolved_confidence": semantic_result.resolved_keyframes.get("confidence") if isinstance(semantic_result.resolved_keyframes, dict) else None,
        "semantic_frame_count": len(semantic_result.semantic_frames),
        "partial_semantic_frame_count": len(semantic_result.partial_semantic_frames),
        "used_semantic_frames": semantic_result.used_semantic_frames,
        "key_frame_candidates": bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None,
        "quality_flags": result["quality_flags"],
    }
    return result, summary


async def process_debug_run(run_id: str) -> None:
    run = await _mark_run_processing(run_id)
    if run is None:
        return

    try:
        if run.mode == "local_pose_keyframes":
            result, summary = await _run_local_pose_keyframes(run)
        elif run.mode == "video_ai_keyframes":
            result, summary = await _run_video_ai_keyframes(run)
        else:
            raise RuntimeError(f"Unsupported debug mode: {run.mode}")
        await _mark_run_completed(run_id, result_json=result, summary=summary)
    except DebugAwaitingTargetSelection as exc:
        await _mark_run_awaiting_target_selection(run_id, result_json=exc.result_json, summary=exc.summary)
    except AnalysisPipelineError as exc:
        logger.warning("Debug run %s failed with pipeline error", run_id, exc_info=True)
        await _mark_run_failed(run_id, code=exc.code.value, detail=exc.detail)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Debug run %s failed", run_id, exc_info=True)
        await _mark_run_failed(run_id, code=AnalysisErrorCode.UNKNOWN_ERROR.value, detail=stringify_exception(exc))


@router.get("/runs", response_model=list[DebugRunSummary])
async def list_debug_runs(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[DebugRunSummary]:
    result = await session.execute(select(DebugRun).order_by(DebugRun.created_at.desc()).limit(limit))
    return [_debug_summary_from_model(run) for run in result.scalars().all()]


@router.get("/runs/{run_id}", response_model=DebugRunDetail)
async def get_debug_run(run_id: str, session: AsyncSession = Depends(get_session)) -> DebugRunDetail:
    run = await session.get(DebugRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Debug run not found.")
    return _debug_detail_from_model(run)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_debug_run(run_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    run = await session.get(DebugRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Debug run not found.")
    if run.status == "processing":
        raise HTTPException(status_code=400, detail="Debug run is processing and cannot be deleted.")

    await session.delete(run)
    await session.commit()
    delete_debug_artifacts(run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/runs/local-pose-keyframes", response_model=DebugRunCreateResponse)
async def create_local_pose_debug_run(
    background_tasks: BackgroundTasks,
    analysis_id: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    action_type: str | None = Form(default=None),
    action_subtype: str | None = Form(default=None),
    analysis_profile: str | None = Form(default=None),
    note: str | None = Form(default=None),
    manual_action_window_start_sec: float | None = Form(default=None),
    manual_action_window_end_sec: float | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> DebugRunCreateResponse:
    return await _create_debug_run(
        mode="local_pose_keyframes",
        background_tasks=background_tasks,
        analysis_id=analysis_id,
        file=file,
        action_type=action_type,
        action_subtype=action_subtype,
        analysis_profile=analysis_profile,
        note=note,
        manual_action_window_start_sec=manual_action_window_start_sec,
        manual_action_window_end_sec=manual_action_window_end_sec,
        session=session,
    )


@router.post("/runs/video-ai-keyframes", response_model=DebugRunCreateResponse)
async def create_video_ai_debug_run(
    background_tasks: BackgroundTasks,
    analysis_id: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    action_type: str | None = Form(default=None),
    action_subtype: str | None = Form(default=None),
    analysis_profile: str | None = Form(default=None),
    note: str | None = Form(default=None),
    manual_action_window_start_sec: float | None = Form(default=None),
    manual_action_window_end_sec: float | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> DebugRunCreateResponse:
    return await _create_debug_run(
        mode="video_ai_keyframes",
        background_tasks=background_tasks,
        analysis_id=analysis_id,
        file=file,
        action_type=action_type,
        action_subtype=action_subtype,
        analysis_profile=analysis_profile,
        note=note,
        manual_action_window_start_sec=manual_action_window_start_sec,
        manual_action_window_end_sec=manual_action_window_end_sec,
        session=session,
    )


@router.post("/runs/{run_id}/target-lock", response_model=DebugRunCreateResponse)
async def confirm_debug_target_lock(
    run_id: str,
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> DebugRunCreateResponse:
    run = await session.get(DebugRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Debug run not found.")
    if run.mode != "local_pose_keyframes":
        raise HTTPException(status_code=400, detail="Target lock is only available for local pose debug runs.")
    if run.status != "awaiting_target_selection":
        raise HTTPException(status_code=400, detail="Debug run is not awaiting target selection.")

    result_json = run.result_json if isinstance(run.result_json, dict) else {}
    preview = _debug_preview_from_payload(run.id, result_json.get("target_preview"))
    manual_bbox = payload.get("manual_bbox")
    candidate_id = str(payload.get("candidate_id")) if payload.get("candidate_id") else None
    try:
        selected = None if manual_bbox is not None else resolve_manual_candidate(preview.candidates, candidate_id, payload.get("x"), payload.get("y"))
        if selected is None and manual_bbox is None:
            raise HTTPException(status_code=400, detail="Unable to resolve target skater; please select again.")
        target_lock = (
            build_target_lock_payload(preview, manual_bbox=manual_bbox)
            if manual_bbox is not None
            else build_target_lock_payload(preview, selected_candidate=selected, manual=True)
        )
    except AnalysisPipelineError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc

    run.result_json = _as_jsonable({**result_json, "target_lock": target_lock})
    run.summary = _as_jsonable({**(run.summary if isinstance(run.summary, dict) else {}), "status": "pending", "target_lock_status": target_lock.get("status")})
    run.status = "pending"
    run.error_code = None
    run.error_detail = None
    run.updated_at = _utc_now()
    await session.commit()

    background_tasks.add_task(process_debug_run, run_id)
    return DebugRunCreateResponse(id=run_id, status="pending")


@router.get("/runs/{run_id}/frames/{filename}")
async def get_debug_run_frame(run_id: str, filename: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    if not filename.endswith(DEBUG_FRAME_SUFFIX) or not filename.startswith(DEBUG_FRAME_PREFIXES):
        raise HTTPException(status_code=400, detail="Invalid debug frame filename.")
    run = await session.get(DebugRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Debug run not found.")

    root = _debug_root(run_id).resolve()
    candidate_dirs = [_debug_frames_dir(run_id).resolve(), _debug_semantic_frames_dir(run_id).resolve()]
    for frames_dir in candidate_dirs:
        frame_path = (frames_dir / filename).resolve()
        if root not in frame_path.parents:
            continue
        if frame_path.exists() and frame_path.is_file():
            return FileResponse(frame_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Debug frame not found.")


def delete_debug_artifacts(run_id: str) -> None:
    shutil.rmtree(UPLOADS_DIR / "_debug" / run_id, ignore_errors=True)
