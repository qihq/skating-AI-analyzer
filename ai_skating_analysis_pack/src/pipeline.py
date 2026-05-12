"""
AI 花样滑冰视频分析 — 端到端流水线入口

本模块是整个 AI 分析模块的主入口。
一次完整的分析调用链如下：

    1. 视频预处理 + 运动密度抽帧   → video.extract_motion_sampled_frames()
    2. 目标锁定（选人）            → target_lock.build_target_preview()
    3. 骨骼姿态提取                → pose.extract_pose()
    4. 分析 profile 推断           → action_profiles.infer_analysis_profile()
    5. 生物力学计算                → biomechanics.analyze_biomechanics()
    6. LLM 视觉逐帧分析           → vision.analyze_frames()
    7. LLM 结构化报告生成          → report.generate_report()
    8. 综合评分计算                → report.calculate_force_score()
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.preprocessing.video import (
    build_processing_frames_dir,
    encode_frames,
    extract_motion_sampled_frames,
    persist_frames,
    cleanup_processing_dir,
    FramePayload,
    VideoSamplingMetadata,
)
from src.preprocessing.target_lock import (
    TARGET_LOCK_AUTO_THRESHOLD,
    build_target_lock_payload,
    build_target_preview,
    frame_names_from_dir,
)
from src.pose_estimation.pose import extract_pose
from src.action_recognition.action_profiles import (
    infer_analysis_profile,
    infer_profile_hint,
    normalize_action_subtype,
)
from src.action_recognition.phase_smoother import smooth_phases
from src.quality_assessment.biomechanics import analyze_biomechanics, sanitize_biomechanics_data
from src.quality_assessment.vision import analyze_frames
from src.quality_assessment.report import generate_report, calculate_force_score
from src.utils.analysis_errors import (
    AnalysisErrorCode,
    classify_ai_failure,
    classify_video_failure,
    stringify_exception,
)


logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """一次完整分析的全部输出。"""
    analysis_profile: str
    vision_structured: dict[str, Any]
    bio_data: dict[str, Any]
    report: dict[str, Any]
    force_score: int
    pose_data: dict[str, Any]
    frame_motion_scores: dict[str, Any]
    target_lock: dict[str, Any]
    sampling_metadata: dict[str, Any]
    smoothed_phases: list[dict[str, Any]] | None = None


async def run_analysis_pipeline(
    video_path: Path | str,
    action_type: str,
    action_subtype: str | None = None,
    skater_id: str | None = None,
    output_dir: Path | str | None = None,
    *,
    ai_provider_config: dict[str, Any] | None = None,
) -> AnalysisResult:
    """
    执行一次完整的花滑视频 AI 分析流水线。

    参数：
        video_path: 视频文件路径（mp4/mov/avi）
        action_type: 动作类型 — "跳跃" / "旋转" / "步法" / "自由滑"
        action_subtype: 动作子类型（可选，如 "单跳"、"蹲转" 等）
        skater_id: 选手 ID（用于注入长期记忆 context）
        output_dir: 临时文件输出目录（默认使用系统临时目录）
        ai_provider_config: AI 供应商配置（可选，覆盖环境变量）

    返回：
        AnalysisResult 包含全部中间结果和最终报告
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    action_subtype = normalize_action_subtype(action_type, action_subtype)
    analysis_profile_hint = infer_profile_hint(action_type, action_subtype)

    # ── Step 1: 视频预处理 + 运动密度抽帧 ──
    logger.info("[Pipeline] Step 1/8: 视频预处理 + 运动密度抽帧")
    if output_dir is None:
        import tempfile
        output_dir = Path(tempfile.mkdtemp(prefix="skating_analysis_"))
    output_dir = Path(output_dir)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    sampled_frames, motion_scores, sampling_metadata = await extract_motion_sampled_frames(
        video_path, frames_dir, action_type, analysis_profile_hint,
    )

    # ── Step 2: 目标锁定 ──
    logger.info("[Pipeline] Step 2/8: 目标锁定（选人）")
    preview = build_target_preview(
        "pipeline",
        [frame.name for frame in sampled_frames],
    )
    target_lock = build_target_lock_payload(preview)
    if preview.lock_confidence < TARGET_LOCK_AUTO_THRESHOLD:
        logger.warning("[Pipeline] 目标锁定置信度低 (%.2f)，自动使用首选候选者", preview.lock_confidence)

    # ── Step 3: 骨骼姿态提取 ──
    logger.info("[Pipeline] Step 3/8: MediaPipe 骨骼姿态提取")
    pose_data = await asyncio.to_thread(extract_pose, str(frames_dir), target_lock)

    # ── Step 4: 分析 profile 推断 ──
    logger.info("[Pipeline] Step 4/8: 分析 profile 推断")
    analysis_profile, profile_evidence = infer_analysis_profile(
        action_type, action_subtype, pose_data, motion_scores,
    )
    logger.info("[Pipeline] 推断结果: profile=%s, evidence_keys=%s", analysis_profile, list(profile_evidence.keys()))

    # ── Step 5: 生物力学计算 ──
    logger.info("[Pipeline] Step 5/8: 生物力学计算")
    bio_data = analyze_biomechanics(pose_data, action_type, analysis_profile)

    # ── Step 6: LLM 视觉逐帧分析 ──
    logger.info("[Pipeline] Step 6/8: LLM 视觉逐帧分析")
    payloads = await encode_frames(sampled_frames)
    vision_structured = await analyze_frames(
        action_type,
        payloads,
        skater_id,
        action_subtype=action_subtype,
        analysis_profile=analysis_profile,
        profile_evidence=profile_evidence,
    )

    # ── Step 7: LLM 结构化报告生成 ──
    logger.info("[Pipeline] Step 7/8: LLM 结构化报告生成")
    report = await generate_report(action_type, vision_structured, bio_data, skater_id)

    # ── Step 8: 综合评分计算 ──
    logger.info("[Pipeline] Step 8/8: 综合评分计算")
    force_score = calculate_force_score(report)

    # ── 可选：阶段平滑 ──
    smoothed_phases = None
    frame_analysis = vision_structured.get("frame_analysis", [])
    if frame_analysis:
        smoothed_phases = smooth_phases(frame_analysis, analysis_profile)

    # ── 清理临时文件 ──
    try:
        cleanup_processing_dir("pipeline")
    except Exception:
        pass

    logger.info("[Pipeline] 分析完成，force_score=%d", force_score)

    return AnalysisResult(
        analysis_profile=analysis_profile,
        vision_structured=vision_structured,
        bio_data=bio_data,
        report=report,
        force_score=force_score,
        pose_data=pose_data,
        frame_motion_scores=motion_scores,
        target_lock=target_lock,
        sampling_metadata={
            "action_window_start": sampling_metadata.action_window_start,
            "action_window_end": sampling_metadata.action_window_end,
            "source_fps": sampling_metadata.source_fps,
            "is_slow_motion": sampling_metadata.is_slow_motion,
        },
        smoothed_phases=smoothed_phases,
    )
