from __future__ import annotations

import logging
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, UPLOADS_DIR, get_session
from app.models import Analysis, Skater, TrainingPlan, TrainingSession
from app.schemas import (
    AnalysisCompareResponse,
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
from app.services.action_profiles import infer_analysis_profile, infer_profile_hint, normalize_action_subtype
from app.services.analysis_errors import (
    AnalysisErrorCode,
    classify_ai_failure,
    classify_video_failure,
    friendly_error_title,
    stringify_exception,
)
from app.services.auth import get_parent_auth, validate_pin, verify_pin_hash
from app.services.biomechanics import analyze_biomechanics, sanitize_biomechanics_data
from app.services.plan import extend_training_plan, generate_training_plan
from app.services.memory_suggest import suggest_memory_updates
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
    build_processing_frames_dir,
    build_upload_paths,
    cleanup_processing_dir,
    encode_frames,
    extract_motion_sampled_frames,
    persist_frames,
    save_upload_file,
)
from app.services.vision import analyze_frames


router = APIRouter(prefix="/api/analysis", tags=["analysis"])
plan_router = APIRouter(prefix="/api/plan", tags=["plan"])
frames_router = APIRouter(prefix="/api/frames", tags=["frames"])

VALID_ACTION_TYPES = {"跳跃", "旋转", "步法", "自由滑"}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
logger = logging.getLogger(__name__)


def _skater_display_name(skater: Skater) -> str:
    return skater.display_name or skater.name


async def process_analysis(analysis_id: str) -> None:
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
    try:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return

            analysis.status = "processing"
            analysis.error_code = None
            analysis.error_detail = None
            analysis.error_message = None
            await session.commit()
            logger.info("Analysis %s entered processing", analysis_id)

            action_type = analysis.action_type
            action_subtype = normalize_action_subtype(analysis.action_type, analysis.action_subtype)
            analysis_profile_hint = infer_profile_hint(action_type, action_subtype)
            skater_id = analysis.skater_id
            video_path = _video_path_for_analysis(analysis)
            upload_frames_dir = video_path.parent / "frames"
            _, processing_frames_dir = build_processing_frames_dir(analysis_id)
            analysis.action_subtype = action_subtype
            await session.commit()
            existing_target_lock = analysis.target_lock if isinstance(analysis.target_lock, dict) else None
            saved_motion_scores = analysis.frame_motion_scores if isinstance(analysis.frame_motion_scores, dict) else None
            saved_action_window_start = float(analysis.action_window_start or 0.0)
            saved_action_window_end = float(analysis.action_window_end or 0.0)
            saved_source_fps = float(analysis.source_fps or 30.0)
            saved_is_slow_motion = bool(analysis.is_slow_motion)

        await _set_analysis_status(analysis_id, "extracting_frames")

        if existing_target_lock and str(existing_target_lock.get("status")) == "locked" and upload_frames_dir is not None and upload_frames_dir.exists():
            sampled_frames = persist_frames(sorted(upload_frames_dir.glob("frame_*.jpg")), processing_frames_dir)
            motion_scores = saved_motion_scores if isinstance(saved_motion_scores, dict) else _fallback_motion_payload(upload_frames_dir)
            from app.services.video import VideoSamplingMetadata

            sampling_metadata = VideoSamplingMetadata(
                action_window_start=saved_action_window_start,
                action_window_end=saved_action_window_end,
                source_fps=saved_source_fps,
                is_slow_motion=saved_is_slow_motion,
            )
        else:
            try:
                sampled_frames, motion_scores, sampling_metadata = await extract_motion_sampled_frames(
                    video_path,
                    processing_frames_dir,
                    action_type,
                    analysis_profile_hint,
                )
            except Exception as exc:  # noqa: BLE001
                failure = classify_video_failure(exc)
                await _mark_analysis_failed(analysis_id, failure.code, failure.detail)
                return
        logger.info("Analysis %s motion-sampled %s frames", analysis_id, len(sampled_frames))

        preview = build_target_preview(analysis_id, [frame.name for frame in sampled_frames], existing_target_lock=existing_target_lock)
        target_lock = existing_target_lock if existing_target_lock and str(existing_target_lock.get("status")) == "locked" else build_target_lock_payload(preview)

        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            analysis.frame_motion_scores = motion_scores
            analysis.action_window_start = sampling_metadata.action_window_start
            analysis.action_window_end = sampling_metadata.action_window_end
            analysis.source_fps = sampling_metadata.source_fps
            analysis.is_slow_motion = sampling_metadata.is_slow_motion
            analysis.target_lock = target_lock
            analysis.target_lock_status = target_lock["status"]
            await session.commit()

        if (not existing_target_lock or str(existing_target_lock.get("status")) != "locked") and preview.lock_confidence < TARGET_LOCK_AUTO_THRESHOLD:
            if upload_frames_dir is not None:
                persist_frames(sampled_frames, upload_frames_dir)
            await _set_analysis_status(analysis_id, "awaiting_target_selection")
            return

        try:
            pose_data = await asyncio.to_thread(extract_pose, str(processing_frames_dir), target_lock)
            analysis_profile, profile_evidence = infer_analysis_profile(action_type, action_subtype, pose_data, motion_scores)
            bio_data = analyze_biomechanics(pose_data, action_type, analysis_profile)
        except Exception as exc:  # noqa: BLE001
            await _mark_analysis_failed(analysis_id, AnalysisErrorCode.UNKNOWN_ERROR, stringify_exception(exc))
            return

        await _set_analysis_status(analysis_id, "analyzing")

        try:
            payloads = await encode_frames(sampled_frames)
            vision_structured = await analyze_frames(
                action_type,
                payloads,
                skater_id,
                action_subtype=action_subtype,
                analysis_profile=analysis_profile,
                profile_evidence=profile_evidence,
            )
            vision_raw = json.dumps(vision_structured, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            failure = classify_ai_failure(exc)
            await _mark_analysis_failed(analysis_id, failure.code, failure.detail)
            return
        logger.info("Analysis %s received vision result", analysis_id)

        await _set_analysis_status(analysis_id, "generating_report")

        try:
            report = await generate_report(action_type, vision_structured, bio_data, skater_id)
            force_score = calculate_force_score(report)
        except Exception as exc:  # noqa: BLE001
            failure = classify_ai_failure(exc)
            await _mark_analysis_failed(analysis_id, failure.code, failure.detail)
            return
        logger.info("Analysis %s generated report with score %s", analysis_id, force_score)
        if upload_frames_dir is not None:
            persist_frames(sampled_frames, upload_frames_dir)

        try:
            async with AsyncSessionLocal() as session:
                analysis = await session.get(Analysis, analysis_id)
                if analysis is None:
                    return

                analysis.vision_raw = vision_raw
                analysis.vision_structured = vision_structured
                analysis.report = report
                analysis.pose_data = pose_data
                analysis.bio_data = bio_data
                analysis.frame_motion_scores = motion_scores
                analysis.analysis_profile = analysis_profile
                analysis.target_lock = target_lock
                analysis.target_lock_status = "auto_locked"
                analysis.action_window_start = sampling_metadata.action_window_start
                analysis.action_window_end = sampling_metadata.action_window_end
                analysis.source_fps = sampling_metadata.source_fps
                analysis.is_slow_motion = sampling_metadata.is_slow_motion
                analysis.force_score = force_score
                analysis.status = "completed"
                analysis.error_code = None
                analysis.error_detail = None
                analysis.error_message = None
                await auto_update_skill_progress(analysis_id, session)
                if analysis.skater_id:
                    await sync_skater_progress(session, analysis.skater_id)
                await session.commit()
                if analysis.skater_id:
                    try:
                        await suggest_memory_updates(analysis_id, analysis.skater_id, session)
                    except Exception:  # noqa: BLE001
                        logger.exception("Analysis %s memory suggestion generation failed", analysis_id)
                logger.info("Analysis %s completed", analysis_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Analysis %s failed while saving report", analysis_id)
            await _mark_analysis_failed(analysis_id, AnalysisErrorCode.REPORT_SAVE_FAILED, stringify_exception(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Analysis %s failed", analysis_id)
        await _mark_analysis_failed(analysis_id, AnalysisErrorCode.UNKNOWN_ERROR, stringify_exception(exc))
    finally:
        cleanup_processing_dir(analysis_id)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def _mark_analysis_failed(analysis_id: str, code: AnalysisErrorCode, detail: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return
            analysis.status = "failed"
            analysis.error_code = code.value
            analysis.error_detail = detail
            analysis.error_message = friendly_error_title(code)
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
        video_path=analysis.video_path,
        status=analysis.status,
        vision_raw=analysis.vision_raw,
        vision_structured=analysis.vision_structured,
        report=analysis.report,
        pose_data=analysis.pose_data,
        bio_data=analysis.bio_data,
        frame_motion_scores=analysis.frame_motion_scores,
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


async def _ensure_phase3_artifacts(session: AsyncSession, analysis: Analysis) -> Analysis:
    if analysis.status != "completed":
        return analysis

    frames_dir = _frames_dir_for_analysis(analysis)
    if not frames_dir.exists():
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
        computed_pose = await asyncio.to_thread(extract_pose, str(frames_dir), analysis.target_lock if isinstance(analysis.target_lock, dict) else None)
        analysis.pose_data = computed_pose
        pose_data = computed_pose
        changed = True

    bio_data = analysis.bio_data if isinstance(analysis.bio_data, dict) else None
    if bio_data is None or not bio_data.get("key_frames"):
        logger.info("Analysis %s is missing biomechanics data, backfilling from pose payload", analysis.id)
        analysis.bio_data = analyze_biomechanics(
            pose_data or {"connections": [], "frames": []},
            analysis.action_type,
            analysis.analysis_profile or infer_profile_hint(analysis.action_type, analysis.action_subtype),
        )
        changed = True
    else:
        sanitized_bio_data = sanitize_biomechanics_data(bio_data)
        if sanitized_bio_data != bio_data:
            logger.info("Analysis %s has implausible biomechanics metrics, sanitizing saved payload", analysis.id)
            analysis.bio_data = sanitized_bio_data
            changed = True

    if analysis.frame_motion_scores is None:
        logger.info("Analysis %s is missing motion sampling metadata, generating legacy fallback payload", analysis.id)
        analysis.frame_motion_scores = _fallback_motion_payload(frames_dir)
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    analysis = Analysis(
        id=analysis_id,
        skater_id=skater.id if skater else None,
        session_id=training_session.id if training_session else None,
        skill_node_id=_normalize_optional_text(skill_node_id),
        skill_category=_normalize_optional_text(skill_category),
        action_type=action_type,
        action_subtype=normalize_action_subtype(action_type, action_subtype),
        video_path=str(video_path),
        note=_normalize_optional_text(note),
        status="pending",
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
    query = select(Analysis).order_by(Analysis.created_at.desc())
    if action_type:
        query = query.where(Analysis.action_type == action_type)
    if skater_id:
        query = query.where(Analysis.skater_id == skater_id)

    result = await session.execute(query)
    analyses = list(result.scalars().all())
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

    plan_json = await generate_training_plan(analysis.action_type, analysis.report, _skater_context(skater), skater.id)
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
    session: AsyncSession = Depends(get_session),
) -> AnalysisRetryResponse:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")
    if analysis.status in {"pending", "processing", "extracting_frames", "awaiting_target_selection", "analyzing", "generating_report"}:
        raise HTTPException(status_code=400, detail="当前分析正在进行中，请稍后再试。")

    upload_dir = UPLOADS_DIR / analysis_id
    source_video_path = (
        next(
            (path for path in upload_dir.iterdir() if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}),
            None,
        )
        if upload_dir.exists()
        else None
    )
    if source_video_path is None:
        raise HTTPException(status_code=404, detail="原始视频文件已不存在，请重新上传")

    analysis.status = "pending"
    analysis.error_code = None
    analysis.error_detail = None
    analysis.error_message = None
    analysis.target_lock_status = "pending"
    analysis.updated_at = datetime.now(timezone.utc)
    await session.commit()

    background_tasks.add_task(process_analysis, analysis_id)
    return AnalysisRetryResponse(message="已重新提交分析任务")


@router.get("/{analysis_id}/target-preview", response_model=TargetPreviewResponse)
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
    selected = resolve_manual_candidate(preview.candidates, payload.candidate_id, payload.x, payload.y)
    if selected is None:
        raise HTTPException(status_code=400, detail="未能确定要分析的主滑行者，请重新点选。")

    analysis.target_lock = build_target_lock_payload(preview, selected_candidate=selected, manual=True)
    analysis.target_lock_status = "locked"
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

    plan.plan_json = await extend_training_plan(
        original_plan=plan.plan_json if isinstance(plan.plan_json, dict) else {},
        completed_days=completed_days,
        action_type=analysis.action_type,
        report=analysis.report,
        skater_context=_skater_context(skater) if skater else None,
        skater_id=skater.id if skater else None,
    )
    await session.commit()
    await session.refresh(plan)
    return _plan_detail_from_model(plan)


@frames_router.get("/{analysis_id}/{filename}")
async def get_frame(analysis_id: str, filename: str) -> FileResponse:
    if not filename.startswith("frame_") or not filename.endswith(".jpg"):
        raise HTTPException(status_code=400, detail="无效的帧文件名。")

    frames_root = (UPLOADS_DIR / analysis_id / "frames").resolve()
    frame_path = (frames_root / filename).resolve()
    if frames_root not in frame_path.parents or not frame_path.exists():
        raise HTTPException(status_code=404, detail="未找到该视频帧。")

    return FileResponse(frame_path, media_type="image/jpeg")
