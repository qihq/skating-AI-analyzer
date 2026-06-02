from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import shutil
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Sequence

import aiofiles
import cv2
import numpy as np
from fastapi import UploadFile

from app.database import UPLOADS_DIR
from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError


logger = logging.getLogger(__name__)

FRAME_RATE = 5
MAX_SECONDS = 60
NORMAL_PLAYBACK_FPS = 30.0
MAX_SAMPLED_FRAMES = int(os.getenv("FRAME_SAMPLE_COUNT", "20"))
FRAME_THUMB_SIZE = os.getenv("FRAME_THUMB_SIZE", "160x90")
FRAME_FULL_SIZE = os.getenv("FRAME_FULL_SIZE", "854x480")
ACTION_CLIP_SIZE = os.getenv("ACTION_CLIP_SIZE", "854x480")
ACTION_CLIP_MAX_SECONDS = float(os.getenv("ACTION_CLIP_MAX_SECONDS", "10"))
ACTION_CLIP_MAX_MB = int(os.getenv("ACTION_CLIP_MAX_MB", "100"))
ACTION_AI_CLIP_SIZE = os.getenv("ACTION_AI_CLIP_SIZE", "640x360")
ACTION_AI_CLIP_FPS = float(os.getenv("ACTION_AI_CLIP_FPS", "15"))
ACTION_AI_CLIP_CRF = int(os.getenv("ACTION_AI_CLIP_CRF", "30"))
ACTION_AI_CLIP_MAX_SECONDS = float(os.getenv("ACTION_AI_CLIP_MAX_SECONDS", str(max(ACTION_CLIP_MAX_SECONDS, 15.0))))
ACTION_AI_CLIP_MAX_MB = int(os.getenv("ACTION_AI_CLIP_MAX_MB", "40"))
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500"))
ALLOWED_SUFFIXES = {".mp4", ".mov", ".avi"}
SLOW_MOTION_THRESHOLD_FPS = 60.0
ACTION_WINDOW_DETECTION_FPS = 2
JUMP_SHORT_VIDEO_FULL_CONTEXT_MAX_SECONDS = float(os.getenv("JUMP_SHORT_VIDEO_FULL_CONTEXT_MAX_SECONDS", "15"))
BLUR_THRESHOLD = float(os.getenv("FRAME_BLUR_THRESHOLD", "80.0"))
MIN_VIDEO_DURATION_SECONDS = 0.5
MIN_VIDEO_WIDTH = 320
MIN_VIDEO_HEIGHT = 180
BLANK_FRAME_VARIANCE_THRESHOLD = 5.0
MIN_FILTERED_FRAMES = 3
PROCESSING_ROOT = Path("/tmp/skating-analyzer") if Path("/tmp").exists() else UPLOADS_DIR / "_processing"

ACTION_WINDOW_SIZES: dict[str, float | None] = {
    "跳跃": 3.0,
    "旋转": 5.0,
    "步法": 8.0,
    "自由滑": None,
}
ACTION_PROFILE_CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "action_profiles.json"
DEFAULT_PROFILE_WINDOW_SIZES: dict[str, float | None] = {
    "jump": 3.0,
    "spin": 5.0,
    "step": 8.0,
    "spiral": 6.0,
}
DEFAULT_PROFILE_FRAME_RATES: dict[str, int] = {
    "jump": 16,
    "spin": 10,
    "spiral": 8,
    "step": 6,
}
DEFAULT_PROFILE_MAX_FRAMES: dict[str, int] = {
    "jump": 32,
    "spin": 24,
    "spiral": 16,
    "step": 20,
}
FFMPEG_RETRYABLE_ERRORS = (
    "partial file",
    "cannot allocate memory",
    "error during demuxing",
    "could not open encoder before eof",
    "error while opening encoder",
)
_LAST_ACTION_WINDOW_DIAGNOSTICS: ContextVar[dict[str, object] | None] = ContextVar(
    "last_action_window_diagnostics",
    default=None,
)


@dataclass(slots=True)
class FramePayload:
    frame_id: str
    data_url: str
    timestamp_sec: float = 0.0


@dataclass(slots=True)
class VideoSamplingMetadata:
    action_window_start: float
    action_window_end: float
    window_start_sec: float
    window_end_sec: float
    effective_fps: float
    source_fps: float
    is_slow_motion: bool


@dataclass(slots=True)
class VideoInputWindow:
    source_duration_sec: float | None
    input_window_start_sec: float
    input_window_end_sec: float
    input_window_duration_sec: float
    input_window_mode: str
    input_window_truncated: bool
    input_window_reason: str

    def to_payload(self) -> dict[str, object]:
        return {
            "source_duration_sec": round(self.source_duration_sec, 3) if isinstance(self.source_duration_sec, (int, float)) else None,
            "input_window_start_sec": round(self.input_window_start_sec, 3),
            "input_window_end_sec": round(self.input_window_end_sec, 3),
            "input_window_duration_sec": round(self.input_window_duration_sec, 3),
            "input_window_mode": self.input_window_mode,
            "input_window_truncated": self.input_window_truncated,
            "input_window_reason": self.input_window_reason,
        }


@dataclass(slots=True)
class ActionWindowSelection:
    start_frame: int
    end_frame: int
    diagnostics: dict[str, object]


def get_frame_rate_for_profile(profile: str | None) -> int:
    config = _profile_sampling_config(profile)
    return int(config.get("frame_rate") or DEFAULT_PROFILE_FRAME_RATES.get(profile or "", FRAME_RATE))


def get_max_frames_for_profile(profile: str | None) -> int:
    config = _profile_sampling_config(profile)
    return int(config.get("frame_sample_count") or DEFAULT_PROFILE_MAX_FRAMES.get(profile or "", MAX_SAMPLED_FRAMES))


def get_window_seconds_for_profile(profile: str | None, action_type: str) -> float | None:
    """Return configured action-window duration on the normal-speed timeline."""
    config = _profile_sampling_config(profile)
    value = config.get("window_seconds")
    if isinstance(value, (int, float)):
        return float(value)
    return DEFAULT_PROFILE_WINDOW_SIZES.get(profile or "", ACTION_WINDOW_SIZES.get(action_type))


@lru_cache(maxsize=1)
def _load_action_profile_config() -> dict[str, dict[str, Any]]:
    try:
        with ACTION_PROFILE_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            payload = json.load(config_file)
    except OSError as exc:
        logger.warning("Action profile config missing, using built-in sampling defaults: %s", exc)
        return {}
    except json.JSONDecodeError as exc:
        logger.warning("Action profile config invalid, using built-in sampling defaults: %s", exc)
        return {}

    profiles = payload.get("profiles")
    if isinstance(profiles, dict):
        return {str(key): value for key, value in profiles.items() if isinstance(value, dict)}

    legacy_profiles = payload.get("motion_sampling")
    if isinstance(legacy_profiles, dict):
        return {str(key): value for key, value in legacy_profiles.items() if isinstance(value, dict)}
    return {}


def _profile_sampling_config(profile: str | None) -> dict[str, Any]:
    if not profile:
        return {}
    return _load_action_profile_config().get(profile.strip().lower(), {})


def get_slow_motion_scale(source_fps: float) -> float:
    """Return the slow-motion multiplier relative to normal playback speed."""
    if source_fps <= 0:
        return 1.0
    return max(source_fps / NORMAL_PLAYBACK_FPS, 1.0)


def get_source_window_duration(action_window_duration: float, source_fps: float) -> float:
    """Map a normal-speed action window onto the source video's playback timeline."""
    scale = get_slow_motion_scale(source_fps) if source_fps >= SLOW_MOTION_THRESHOLD_FPS else 1.0
    return action_window_duration * scale


def _effective_sampling_context(
    start_sec: float,
    end_sec: float,
    sample_count: int,
    slow_motion_scale: float,
) -> tuple[float, float, float]:
    effective_duration = max((end_sec - start_sec) / max(slow_motion_scale, 1e-6), 1e-6)
    window_start_sec = round(start_sec / max(slow_motion_scale, 1e-6), 3)
    window_end_sec = round(window_start_sec + effective_duration, 3)
    # 设计说明: N 个采样帧只有 N-1 个时间间隔；慢动作源视频先折算回动作真实时间轴。
    effective_fps = (max(sample_count, 2) - 1) / effective_duration
    return window_start_sec, window_end_sec, round(effective_fps, 3)


def _normalize_manual_input_window(
    manual_start_sec: float | None,
    manual_end_sec: float | None,
    *,
    source_duration_sec: float | None,
) -> tuple[float, float] | None:
    if manual_start_sec is None and manual_end_sec is None:
        return None
    if manual_start_sec is None or manual_end_sec is None:
        raise AnalysisPipelineError(
            AnalysisErrorCode.VIDEO_FORMAT_INVALID,
            "Manual action window requires both start and end seconds.",
        )
    try:
        start = float(manual_start_sec)
        end = float(manual_end_sec)
    except (TypeError, ValueError) as exc:
        raise AnalysisPipelineError(
            AnalysisErrorCode.VIDEO_FORMAT_INVALID,
            "Manual action window start/end must be valid numbers.",
        ) from exc
    if start < 0:
        raise AnalysisPipelineError(AnalysisErrorCode.VIDEO_FORMAT_INVALID, "Manual action window start must be >= 0.")
    if end <= start:
        raise AnalysisPipelineError(AnalysisErrorCode.VIDEO_FORMAT_INVALID, "Manual action window end must be greater than start.")
    if source_duration_sec is not None and source_duration_sec > 0:
        if start >= source_duration_sec:
            raise AnalysisPipelineError(
                AnalysisErrorCode.VIDEO_FORMAT_INVALID,
                "Manual action window start is outside the source video duration.",
            )
        if end > source_duration_sec + 0.01:
            raise AnalysisPipelineError(
                AnalysisErrorCode.VIDEO_FORMAT_INVALID,
                "Manual action window end is outside the source video duration.",
            )
        end = min(end, source_duration_sec)
    if end - start < MIN_VIDEO_DURATION_SECONDS:
        raise AnalysisPipelineError(
            AnalysisErrorCode.VIDEO_FORMAT_INVALID,
            "Manual action window is too short for analysis.",
        )
    return round(start, 3), round(end, 3)


def build_video_input_window(
    video_path: Path,
    *,
    manual_start_sec: float | None = None,
    manual_end_sec: float | None = None,
) -> VideoInputWindow:
    duration = detect_video_duration(video_path)
    source_duration = float(duration) if duration and duration > 0 else None
    manual_window = _normalize_manual_input_window(
        manual_start_sec,
        manual_end_sec,
        source_duration_sec=source_duration,
    )
    if manual_window is not None:
        start, end = manual_window
        return VideoInputWindow(
            source_duration_sec=source_duration,
            input_window_start_sec=start,
            input_window_end_sec=end,
            input_window_duration_sec=round(end - start, 3),
            input_window_mode="manual_window",
            input_window_truncated=True,
            input_window_reason="manual_action_window",
        )

    end = source_duration if source_duration is not None else float(MAX_SECONDS)
    mode = "full_context"
    truncated = False
    reason = "full_context"
    if source_duration is None:
        end = float(MAX_SECONDS)
        mode = "system_truncated"
        truncated = True
        reason = "source_duration_unknown_fallback"
    return VideoInputWindow(
        source_duration_sec=source_duration,
        input_window_start_sec=0.0,
        input_window_end_sec=round(end, 3),
        input_window_duration_sec=round(end, 3),
        input_window_mode=mode,
        input_window_truncated=truncated,
        input_window_reason=reason,
    )


def attach_input_window_payload(
    motion_payload: dict[str, object],
    input_window: VideoInputWindow | None,
) -> dict[str, object]:
    if input_window is None:
        return motion_payload
    payload = input_window.to_payload()
    motion_payload["input_window"] = payload
    motion_payload.update(payload)
    return motion_payload


def _frame_dimensions() -> tuple[str, str]:
    width, height = FRAME_FULL_SIZE.lower().split("x", maxsplit=1)
    return width, height


def _size_tuple(value: str) -> tuple[str, str]:
    width, height = value.lower().split("x", maxsplit=1)
    return width, height


def build_upload_paths(analysis_id: str, suffix: str) -> tuple[Path, Path]:
    upload_dir = UPLOADS_DIR / analysis_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = upload_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / f"source{suffix}", frames_dir


def _has_supported_video_magic(video_path: Path) -> bool:
    header = video_path.read_bytes()[:16]
    suffix = video_path.suffix.lower()
    if suffix in {".mp4", ".mov"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if suffix == ".avi":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI "
    return False


def _probe_video(video_path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise AnalysisPipelineError(
            AnalysisErrorCode.VIDEO_FORMAT_INVALID,
            "ffprobe cannot read the uploaded video container.",
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AnalysisPipelineError(
            AnalysisErrorCode.VIDEO_FORMAT_INVALID,
            "ffprobe returned invalid metadata for the uploaded video.",
        ) from exc


async def _extract_precheck_frames(video_path: Path, frames_dir: Path) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(frames_dir / "precheck_%02d.jpg")
    await _run_ffmpeg(
        [
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "select='eq(n,0)+eq(n,10)+eq(n,20)',scale=160:90",
            "-vsync",
            "0",
            "-frames:v",
            "3",
            output_pattern,
        ]
    )
    return sorted(frames_dir.glob("precheck_*.jpg"))


async def precheck_video(video_path: Path) -> None:
    """Validate a video before the expensive analysis pipeline starts.

    Args:
        video_path: Uploaded mp4/mov/avi file path.

    Returns:
        None when the container, stream metadata, and sampled frame content are usable.

    Raises:
        AnalysisPipelineError: VIDEO_FORMAT_INVALID, VIDEO_NO_VIDEO_STREAM,
            or VIDEO_BLANK_FRAMES when the input cannot be analyzed.
    """
    if not video_path.exists() or not _has_supported_video_magic(video_path):
        raise AnalysisPipelineError(
            AnalysisErrorCode.VIDEO_FORMAT_INVALID,
            "Uploaded file header does not match mp4/mov/avi video magic bytes.",
        )

    metadata = _probe_video(video_path)
    streams = metadata.get("streams") if isinstance(metadata, dict) else None
    video_stream = next(
        (stream for stream in streams or [] if isinstance(stream, dict) and stream.get("codec_type") == "video"),
        None,
    )
    if not isinstance(video_stream, dict):
        raise AnalysisPipelineError(AnalysisErrorCode.VIDEO_NO_VIDEO_STREAM, "Uploaded file has no video stream.")

    try:
        duration = float(video_stream.get("duration") or (metadata.get("format") or {}).get("duration") or 0.0)
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
    except (TypeError, ValueError) as exc:
        raise AnalysisPipelineError(
            AnalysisErrorCode.VIDEO_NO_VIDEO_STREAM,
            "Uploaded video stream metadata is incomplete.",
        ) from exc

    if duration <= MIN_VIDEO_DURATION_SECONDS or width < MIN_VIDEO_WIDTH or height < MIN_VIDEO_HEIGHT:
        raise AnalysisPipelineError(
            AnalysisErrorCode.VIDEO_NO_VIDEO_STREAM,
            "Uploaded video is too short or below the minimum 320x180 resolution.",
        )

    precheck_dir = video_path.parent / "_precheck_frames"
    try:
        if precheck_dir.exists():
            shutil.rmtree(precheck_dir)
        frames = await _extract_precheck_frames(video_path, precheck_dir)
        if not frames:
            raise AnalysisPipelineError(
                AnalysisErrorCode.VIDEO_NO_VIDEO_STREAM,
                "No frames could be decoded from the uploaded video.",
            )

        variances: list[float] = []
        for frame_path in frames:
            image = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                variances.append(float(np.var(image)))

        # 设计说明: low luminance variance across several decoded frames catches black-screen videos before pose/LLM work.
        if not variances or max(variances) <= BLANK_FRAME_VARIANCE_THRESHOLD:
            raise AnalysisPipelineError(
                AnalysisErrorCode.VIDEO_BLANK_FRAMES,
                "Decoded sample frames are blank or nearly static black frames.",
            )
    finally:
        if precheck_dir.exists():
            shutil.rmtree(precheck_dir, ignore_errors=True)


def build_processing_frames_dir(analysis_id: str) -> tuple[Path, Path]:
    processing_dir = PROCESSING_ROOT / analysis_id
    frames_dir = processing_dir / "frames"
    if processing_dir.exists():
        shutil.rmtree(processing_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    return processing_dir, frames_dir


def get_processing_frames_dir(analysis_id: str) -> Path:
    return PROCESSING_ROOT / analysis_id / "frames"


def cleanup_processing_dir(analysis_id: str) -> None:
    shutil.rmtree(PROCESSING_ROOT / analysis_id, ignore_errors=True)


def persist_frames(frame_paths: Sequence[Path], target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    persisted_paths: list[Path] = []
    for frame_path in frame_paths:
        target_path = target_dir / frame_path.name
        shutil.copy2(frame_path, target_path)
        persisted_paths.append(target_path)
    return persisted_paths


async def save_upload_file(upload_file: UploadFile, target_path: Path) -> Path:
    suffix = Path(upload_file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("仅支持 mp4、mov、avi 格式的视频。")

    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    declared_size = getattr(upload_file, "size", None)
    if isinstance(declared_size, int) and declared_size > max_bytes:
        raise ValueError(f"文件超过 {MAX_UPLOAD_SIZE_MB}MB 限制。")

    written = 0

    try:
        logger.info("Saving upload to %s", target_path)
        async with aiofiles.open(target_path, "wb") as output:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                next_size = written + len(chunk)
                if next_size > max_bytes:
                    raise ValueError(f"文件超过 {MAX_UPLOAD_SIZE_MB}MB 限制。")
                await output.write(chunk)
                written = next_size
    except OSError as exc:
        raise ValueError(f"文件写入失败：{exc.strerror or '存储空间不足或磁盘写入异常。'}") from exc
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await upload_file.close()

    return target_path


async def extract_frames(video_path: Path, frames_dir: Path, frame_rate: int = FRAME_RATE) -> list[Path]:
    width, height = _frame_dimensions()
    output_pattern = str(frames_dir / "frame_%04d.jpg")
    scale_filter = (
        f"fps={frame_rate},"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )

    logger.info("Extracting frames from %s into %s at %s", video_path, frames_dir, FRAME_FULL_SIZE)
    await _run_ffmpeg(
        [
            "-y",
            "-i",
            str(video_path),
            "-t",
            str(MAX_SECONDS),
            "-vf",
            scale_filter,
            "-pix_fmt",
            "yuvj420p",
            output_pattern,
        ]
    )

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    if not frames:
        raise RuntimeError("视频抽帧结果为空，请检查上传文件是否损坏。")

    logger.info("Extracted %s frames for %s", len(frames), video_path)
    return frames


def detect_video_fps(video_path: Path) -> float:
    """
    用 FFprobe 读取视频实际帧率。
    解析 r_frame_rate（如 "240/1" -> 240.0，"30000/1001" -> 29.97）。
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return 30.0

        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") != "video":
                continue
            rate = str(stream.get("r_frame_rate") or "30/1")
            if "/" in rate:
                numerator, denominator = rate.split("/", maxsplit=1)
                denominator_value = float(denominator)
                if denominator_value == 0:
                    return 30.0
                return float(numerator) / denominator_value
            return float(rate)
    except Exception:  # noqa: BLE001
        logger.warning("Unable to detect fps for %s, using 30fps fallback", video_path, exc_info=True)
    return 30.0


def detect_video_duration(video_path: Path) -> float | None:
    try:
        metadata = _probe_video(video_path)
        streams = metadata.get("streams") if isinstance(metadata, dict) else None
        video_stream = next(
            (stream for stream in streams or [] if isinstance(stream, dict) and stream.get("codec_type") == "video"),
            None,
        )
        if isinstance(video_stream, dict):
            value = video_stream.get("duration")
            if value is not None:
                return max(0.0, float(value))
        format_payload = metadata.get("format") if isinstance(metadata, dict) else None
        if isinstance(format_payload, dict) and format_payload.get("duration") is not None:
            return max(0.0, float(format_payload.get("duration")))
    except Exception:  # noqa: BLE001
        logger.warning("Unable to detect duration for %s", video_path, exc_info=True)
    return None


def _fallback_action_window(action_type: str) -> tuple[float, float]:
    window_size = get_window_seconds_for_profile(analysis_profile, action_type)
    if window_size is None:
        return 0.0, float(MAX_SECONDS)
    return 0.0, min(float(MAX_SECONDS), float(window_size) + 2.0)


def _fallback_profile_window(action_type: str, analysis_profile: str | None, source_fps: float = NORMAL_PLAYBACK_FPS) -> tuple[float, float]:
    window_size = get_window_seconds_for_profile(analysis_profile, action_type)
    if window_size is None:
        return 0.0, float(MAX_SECONDS)
    source_window_size = get_source_window_duration(float(window_size), source_fps)
    return 0.0, min(float(MAX_SECONDS), source_window_size + 2.0)


def _short_jump_full_context_duration(video_path: Path, analysis_profile: str | None, source_fps: float) -> float | None:
    profile = (analysis_profile or "").strip().lower()
    if profile != "jump" or source_fps >= SLOW_MOTION_THRESHOLD_FPS:
        return None
    max_duration = min(float(MAX_SECONDS), max(0.0, JUMP_SHORT_VIDEO_FULL_CONTEXT_MAX_SECONDS))
    if max_duration <= 0.0:
        return None
    duration = detect_video_duration(video_path)
    if duration is None or duration <= 0.0 or duration > max_duration:
        return None
    return min(float(duration), float(MAX_SECONDS))


def _action_window_padding(analysis_profile: str | None) -> tuple[float, float]:
    profile = (analysis_profile or "").strip().lower()
    if profile == "jump":
        return 0.35, 0.75
    return 1.0, 1.0


async def _extract_action_thumbnails(video_path: Path, thumbs_dir: Path) -> list[Path]:
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(thumbs_dir / "thumb_%05d.jpg")
    await _run_ffmpeg(
        [
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps={ACTION_WINDOW_DETECTION_FPS},scale=160:90",
            output_pattern,
        ]
    )
    return sorted(thumbs_dir.glob("thumb_*.jpg"))


def _pick_window_by_profile(
    motion_scores: Sequence[float],
    action_type: str,
    analysis_profile: str | None,
    source_fps: float,
) -> tuple[int, int]:
    selection = _select_action_window_by_profile(motion_scores, action_type, analysis_profile, source_fps)
    return selection.start_frame, selection.end_frame


def _select_action_window_by_profile(
    motion_scores: Sequence[float],
    action_type: str,
    analysis_profile: str | None,
    source_fps: float,
) -> ActionWindowSelection:
    window_size = get_window_seconds_for_profile(analysis_profile, action_type)
    if window_size is None:
        return ActionWindowSelection(
            start_frame=0,
            end_frame=len(motion_scores),
            diagnostics={
                "selection_reason": "full_video_profile",
                "candidate_windows": [],
                "late_window_override": False,
            },
        )

    source_window_size = get_source_window_duration(float(window_size), source_fps)
    window_frames = max(1, round(source_window_size * ACTION_WINDOW_DETECTION_FPS))
    max_start = max(1, len(motion_scores) - window_frames + 1)

    if analysis_profile == "spiral":
        best_start = 0
        best_score = float("-inf")
        for index in range(max_start):
            window = motion_scores[index : index + window_frames]
            if not window:
                continue
            avg_motion = sum(window) / len(window)
            stability_bonus = -max(window) + min(window)
            current_score = stability_bonus - avg_motion
            if current_score > best_score:
                best_score = current_score
                best_start = index
        return ActionWindowSelection(
            start_frame=best_start,
            end_frame=best_start + window_frames,
            diagnostics={
                "selection_reason": "spiral_low_motion_stability",
                "window_frames": window_frames,
                "candidate_windows": [
                    {
                        "start_frame": best_start,
                        "end_frame": best_start + window_frames,
                        "start_sec": round(best_start / ACTION_WINDOW_DETECTION_FPS, 3),
                        "end_sec": round((best_start + window_frames) / ACTION_WINDOW_DETECTION_FPS, 3),
                        "score": round(best_score, 4),
                    }
                ],
                "late_window_override": False,
            },
        )

    candidates: list[dict[str, object]] = []
    for index in range(max_start):
        window = motion_scores[index : index + window_frames]
        if not window:
            continue
        raw_score = sum(window)
        if analysis_profile == "spin":
            current_score = raw_score - abs(window[0] - window[-1])
            late_bonus = 0.0
        else:
            progress = index / max(max_start - 1, 1)
            late_bonus = 0.0
            if analysis_profile == "jump":
                # Bias away from very early full-frame motion spikes caused by blockers or unrelated skaters.
                late_bonus = raw_score * 0.30 * progress
            current_score = raw_score + late_bonus
        candidates.append(
            {
                "start_frame": index,
                "end_frame": index + window_frames,
                "start_sec": round(index / ACTION_WINDOW_DETECTION_FPS, 3),
                "end_sec": round((index + window_frames) / ACTION_WINDOW_DETECTION_FPS, 3),
                "raw_score": round(raw_score, 4),
                "score": round(current_score, 4),
                "late_bonus": round(late_bonus, 4),
            }
        )

    if not candidates:
        return ActionWindowSelection(
            start_frame=0,
            end_frame=window_frames,
            diagnostics={
                "selection_reason": "no_motion_candidates",
                "window_frames": window_frames,
                "candidate_windows": [],
                "late_window_override": False,
            },
        )

    raw_best = max(candidates, key=lambda item: float(item["raw_score"]))
    scored_best = max(candidates, key=lambda item: float(item["score"]))
    chosen = scored_best if analysis_profile != "jump" else raw_best
    late_override = False
    selection_reason = "max_motion_score"
    if analysis_profile == "jump":
        early_threshold = max_start * 0.25
        late_threshold = max_start * 0.35
        raw_best_score = float(raw_best["raw_score"])
        eligible_late = [
            item
            for item in candidates
            if int(raw_best["start_frame"]) <= early_threshold
            and int(item["start_frame"]) >= late_threshold
            and float(item["raw_score"]) >= raw_best_score * 0.80
        ]
        if eligible_late:
            late_best = max(eligible_late, key=lambda item: float(item["score"]))
            if float(late_best["score"]) >= float(raw_best["score"]) * 0.985:
                chosen = late_best
                late_override = True
                selection_reason = "jump_late_window_guard"

    top_candidates = sorted(candidates, key=lambda item: float(item["score"]), reverse=True)[:6]
    return ActionWindowSelection(
        start_frame=int(chosen["start_frame"]),
        end_frame=int(chosen["end_frame"]),
        diagnostics={
            "selection_reason": selection_reason,
            "window_frames": window_frames,
            "raw_best_start_frame": raw_best["start_frame"],
            "raw_best_score": raw_best["raw_score"],
            "selected_start_frame": chosen["start_frame"],
            "selected_score": chosen["score"],
            "late_window_override": late_override,
            "candidate_windows": top_candidates,
        },
    )


def _action_window_seconds_from_selection(
    selection: ActionWindowSelection,
    *,
    action_type: str,
    analysis_profile: str | None,
    source_fps: float,
) -> tuple[float, float]:
    selected_window_size = get_window_seconds_for_profile(analysis_profile, action_type)
    if selected_window_size is None:
        return 0.0, float(MAX_SECONDS)
    source_window_size = get_source_window_duration(float(selected_window_size), source_fps)
    pre_padding_sec, post_padding_sec = _action_window_padding(analysis_profile)
    start_sec = max(0.0, selection.start_frame / ACTION_WINDOW_DETECTION_FPS - pre_padding_sec)
    end_sec = max(start_sec + 1.0, (selection.end_frame / ACTION_WINDOW_DETECTION_FPS) + post_padding_sec)
    end_sec = min(end_sec, start_sec + source_window_size + pre_padding_sec + post_padding_sec)
    return start_sec, end_sec


def _action_window_diagnostics_for_seconds(
    selection: ActionWindowSelection,
    *,
    start_sec: float,
    end_sec: float,
) -> dict[str, object]:
    diagnostics = dict(selection.diagnostics)
    diagnostics["selected_start_sec"] = round(start_sec, 3)
    diagnostics["selected_end_sec"] = round(end_sec, 3)
    return diagnostics


async def detect_action_window(
    video_path: Path,
    action_type: str,
    source_fps: float,
    analysis_profile: str | None = None,
) -> tuple[float, float]:
    """
    用运动密度曲线找到峰值区间，返回 (start_sec, end_sec)。
    无法定位时退化为分析前 N 秒；自由滑维持前 60 秒。
    """
    _LAST_ACTION_WINDOW_DIAGNOSTICS.set(None)
    window_size = get_window_seconds_for_profile(analysis_profile, action_type)
    if window_size is None:
        _LAST_ACTION_WINDOW_DIAGNOSTICS.set({
            "selection_reason": "full_video_profile",
            "candidate_windows": [],
            "late_window_override": False,
            "selected_start_sec": 0.0,
            "selected_end_sec": float(MAX_SECONDS),
        })
        return 0.0, float(MAX_SECONDS)

    short_jump_duration = _short_jump_full_context_duration(video_path, analysis_profile, source_fps)
    if short_jump_duration is not None:
        _LAST_ACTION_WINDOW_DIAGNOSTICS.set({
            "selection_reason": "jump_short_video_full_context",
            "candidate_windows": [],
            "late_window_override": False,
            "source_duration_sec": round(short_jump_duration, 3),
            "selected_start_sec": 0.0,
            "selected_end_sec": round(short_jump_duration, 3),
        })
        return 0.0, short_jump_duration

    thumbs_dir = PROCESSING_ROOT / "_action_windows" / f"{video_path.stem}_{uuid.uuid4().hex}"
    try:
        if thumbs_dir.exists():
            shutil.rmtree(thumbs_dir)
        thumbs = await _extract_action_thumbnails(video_path, thumbs_dir)
        motion_scores = _motion_scores_from_thumbs(thumbs)
    except Exception:  # noqa: BLE001
        logger.warning("Action window detection failed for %s, using fallback window", video_path, exc_info=True)
        start_sec, end_sec = _fallback_profile_window(action_type, analysis_profile, source_fps)
        _LAST_ACTION_WINDOW_DIAGNOSTICS.set({
            "selection_reason": "fallback_detection_failed",
            "candidate_windows": [],
            "late_window_override": False,
            "selected_start_sec": round(start_sec, 3),
            "selected_end_sec": round(end_sec, 3),
        })
        return start_sec, end_sec
    finally:
        if thumbs_dir.exists():
            shutil.rmtree(thumbs_dir, ignore_errors=True)

    if len(motion_scores) <= 1:
        start_sec, end_sec = _fallback_profile_window(action_type, analysis_profile, source_fps)
        _LAST_ACTION_WINDOW_DIAGNOSTICS.set({
            "selection_reason": "fallback_insufficient_motion_scores",
            "candidate_windows": [],
            "late_window_override": False,
            "selected_start_sec": round(start_sec, 3),
            "selected_end_sec": round(end_sec, 3),
        })
        return start_sec, end_sec

    selection = _select_action_window_by_profile(motion_scores, action_type, analysis_profile, source_fps)
    start_sec, end_sec = _action_window_seconds_from_selection(
        selection,
        action_type=action_type,
        analysis_profile=analysis_profile,
        source_fps=source_fps,
    )
    if end_sec <= start_sec:
        start_sec, end_sec = _fallback_profile_window(action_type, analysis_profile, source_fps)
        _LAST_ACTION_WINDOW_DIAGNOSTICS.set({
            "selection_reason": "fallback_invalid_selected_window",
            "candidate_windows": [],
            "late_window_override": False,
            "selected_start_sec": round(start_sec, 3),
            "selected_end_sec": round(end_sec, 3),
        })
        return start_sec, end_sec
    _LAST_ACTION_WINDOW_DIAGNOSTICS.set(
        _action_window_diagnostics_for_seconds(
            selection,
            start_sec=start_sec,
            end_sec=end_sec,
        )
    )
    return start_sec, end_sec


def sample_frame_paths(frame_paths: Sequence[Path], max_frames: int = MAX_SAMPLED_FRAMES) -> list[Path]:
    if len(frame_paths) <= max_frames:
        return list(frame_paths)

    last_index = len(frame_paths) - 1
    sampled_indices = [round((index / (max_frames - 1)) * last_index) for index in range(max_frames)]
    return [frame_paths[index] for index in sampled_indices]


def is_blurry(image_path: Path, threshold: float = BLUR_THRESHOLD) -> bool:
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return True
    variance = float(np.var(cv2.Laplacian(image, cv2.CV_64F)))
    return variance < threshold


def filter_frames(frame_paths: Sequence[Path]) -> list[Path]:
    frame_list = list(frame_paths)
    good_frames = [frame_path for frame_path in frame_list if not is_blurry(frame_path)]
    if len(good_frames) >= MIN_FILTERED_FRAMES:
        return good_frames
    return frame_list[:MIN_FILTERED_FRAMES]


async def _run_ffmpeg(args: list[str]) -> None:
    attempts = 2
    last_message = "未知错误"
    for attempt in range(1, attempts + 1):
        cmd = ["ffmpeg", *args]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            returncode = process.returncode
        except NotImplementedError:
            returncode, stderr = await asyncio.to_thread(_run_ffmpeg_sync, cmd)
        message = stderr.decode("utf-8", errors="ignore").strip()
        if returncode == 0:
            return

        last_message = message or "未知错误"
        retryable = any(fragment in last_message.lower() for fragment in FFMPEG_RETRYABLE_ERRORS)
        if attempt < attempts and retryable:
            logger.warning("FFmpeg failed on attempt %s/%s, retrying once: %s", attempt, attempts, last_message)
            await asyncio.sleep(0.3)
            continue
        break

    raise RuntimeError(f"FFmpeg 处理失败：{last_message}")


def _run_ffmpeg_sync(cmd: list[str]) -> tuple[int, bytes]:
    import subprocess

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode, result.stderr


async def cut_action_window_clip(
    video_path: Path,
    window_start_sec: float,
    window_end_sec: float,
    out_path: Path,
) -> Path:
    """
    Cut a short action-window clip for native video vision models.

    Args:
        video_path: Source mp4/mov/avi path.
        window_start_sec: Source-video window start in seconds.
        window_end_sec: Source-video window end in seconds.
        out_path: Output mp4 path.

    Returns:
        The created clip path.

    Raises:
        RuntimeError: When ffmpeg cannot create a valid bounded clip.
    """
    start = max(0.0, float(window_start_sec))
    end = max(start + 0.5, float(window_end_sec))
    if end - start > ACTION_CLIP_MAX_SECONDS:
        end = start + ACTION_CLIP_MAX_SECONDS

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)

    try:
        await _run_ffmpeg(
            [
                "-y",
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-i",
                str(video_path),
                "-c",
                "copy",
                str(out_path),
            ]
        )
    except Exception:  # noqa: BLE001
        logger.warning("Stream-copy action clip failed for %s, transcoding fallback.", video_path, exc_info=True)
        width, height = _size_tuple(ACTION_CLIP_SIZE)
        # Design note: transcode fallback bounds upload size and normalizes to <=480p for DashScope video mode.
        scale_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        )
        await _run_ffmpeg(
            [
                "-y",
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-i",
                str(video_path),
                "-vf",
                scale_filter,
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                "-an",
                str(out_path),
            ]
        )

    max_bytes = ACTION_CLIP_MAX_MB * 1024 * 1024
    if not out_path.exists() or out_path.stat().st_size <= 0:
        raise RuntimeError("Action-window clip was not created.")
    if out_path.stat().st_size > max_bytes:
        raise RuntimeError(f"Action-window clip exceeds {ACTION_CLIP_MAX_MB}MB.")
    return out_path


async def cut_action_window_ai_clip(
    video_path: Path,
    window_start_sec: float,
    window_end_sec: float,
    out_path: Path,
    *,
    max_duration_sec: float | None = None,
) -> Path:
    """
    Create the compact action-window clip used only for AI video inputs.

    The source upload remains untouched; timestamps emitted by models for this
    clip are expected to be shifted back to the source-video timeline by callers.
    """
    start = max(0.0, float(window_start_sec))
    end = max(start + 0.5, float(window_end_sec))
    if max_duration_sec is not None and end - start > max_duration_sec:
        end = start + max_duration_sec

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)

    width, height = _size_tuple(ACTION_AI_CLIP_SIZE)
    fps = max(1.0, min(float(ACTION_AI_CLIP_FPS), 30.0))
    crf = max(18, min(int(ACTION_AI_CLIP_CRF), 40))
    scale_filter = (
        f"fps={fps:.3f},"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )
    await _run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(video_path),
            "-vf",
            scale_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(out_path),
        ]
    )

    max_bytes = ACTION_AI_CLIP_MAX_MB * 1024 * 1024
    if not out_path.exists() or out_path.stat().st_size <= 0:
        raise RuntimeError("AI action-window clip was not created.")
    if out_path.stat().st_size > max_bytes:
        raise RuntimeError(f"AI action-window clip exceeds {ACTION_AI_CLIP_MAX_MB}MB.")
    return out_path


async def _extract_thumbnails(video_path: Path, thumbs_dir: Path, frame_rate: int = FRAME_RATE) -> list[Path]:
    width, height = _size_tuple(FRAME_THUMB_SIZE)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(thumbs_dir / "thumb_%05d.jpg")
    scale_filter = f"fps={frame_rate},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    await _run_ffmpeg(["-y", "-i", str(video_path), "-vf", scale_filter, "-pix_fmt", "yuvj420p", output_pattern])
    return sorted(thumbs_dir.glob("thumb_*.jpg"))


async def _extract_thumbnails_in_window(
    video_path: Path,
    thumbs_dir: Path,
    start_sec: float,
    end_sec: float,
    frame_rate: int = FRAME_RATE,
) -> list[Path]:
    width, height = _size_tuple(FRAME_THUMB_SIZE)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(thumbs_dir / "thumb_%05d.jpg")
    scale_filter = (
        f"fps={frame_rate},"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )
    await _run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{start_sec:.3f}",
            "-to",
            f"{end_sec:.3f}",
            "-i",
            str(video_path),
            "-vf",
            scale_filter,
            "-pix_fmt",
            "yuvj420p",
            output_pattern,
        ]
    )
    return sorted(thumbs_dir.glob("thumb_*.jpg"))


def _motion_scores_from_thumbs(thumbs: Sequence[Path]) -> list[float]:
    if not thumbs:
        return []

    try:
        import cv2  # type: ignore
    except Exception:  # noqa: BLE001
        logger.warning("OpenCV is unavailable; falling back to uniform frame sampling.")
        return [0.0 for _ in thumbs]

    scores = [0.0]
    previous = cv2.imread(str(thumbs[0]), cv2.IMREAD_GRAYSCALE)
    if previous is None:
        return [0.0 for _ in thumbs]

    for thumb_path in thumbs[1:]:
        current = cv2.imread(str(thumb_path), cv2.IMREAD_GRAYSCALE)
        if current is None:
            scores.append(0.0)
            continue
        diff = cv2.absdiff(previous, current)
        scores.append(min(float(diff.mean()) / 64.0, 1.0))
        previous = current
    return scores


def _smooth_motion_scores(scores: Sequence[float], window: int = 3) -> list[float]:
    """Apply a small moving-average to motion scores to suppress noise spikes.

    Why: 单帧抖动/噪声会让 peak 选错；3 帧均值能稳定起跳/落冰瞬间的位置，
    使切帧密度更贴合真实动作节奏。
    """
    if window <= 1 or not scores:
        return [float(value) for value in scores]
    half = window // 2
    out: list[float] = []
    for index in range(len(scores)):
        left = max(0, index - half)
        right = min(len(scores), index + half + 1)
        window_slice = scores[left:right]
        out.append(sum(float(value) for value in window_slice) / max(len(window_slice), 1))
    return out


def _top_local_peak_indices(scores: Sequence[float], limit: int = 2) -> list[int]:
    """
    Return the strongest local motion peaks.

    Args:
        scores: Motion density scores ordered by thumbnail time.
        limit: Maximum number of peak centers.

    Returns:
        Peak indices sorted by descending score.
    """
    if not scores or limit <= 0:
        return []

    peaks: list[int] = []
    for index, score in enumerate(scores):
        left = scores[index - 1] if index > 0 else float("-inf")
        right = scores[index + 1] if index < len(scores) - 1 else float("-inf")
        if score >= left and score >= right and (score > left or score > right):
            peaks.append(index)

    if not peaks:
        peaks = list(range(len(scores)))
    peaks.sort(key=lambda item: (scores[item], -item), reverse=True)
    return peaks[:limit]


def _peak_neighborhood_indices(scores: Sequence[float], radius: int = 1, limit: int = 2) -> set[int]:
    selected: set[int] = set()
    for peak in _top_local_peak_indices(scores, limit=limit):
        for index in range(max(0, peak - radius), min(len(scores), peak + radius + 1)):
            selected.add(index)
    return selected


def _motion_peak_records(scores: Sequence[float], frame_rate: float, limit: int = 6) -> list[dict[str, object]]:
    smoothed = _smooth_motion_scores(scores, window=3)
    return [
        {
            "thumb_index": index,
            "timestamp_offset": round(index / max(frame_rate, 1e-6), 3),
            "score": round(float(scores[index]) if index < len(scores) else 0.0, 4),
            "smoothed_score": round(float(smoothed[index]) if index < len(smoothed) else 0.0, 4),
        }
        for index in _top_local_peak_indices(smoothed, limit=limit)
    ]


def _coverage_gap_records(selected_indices: Sequence[int], frame_rate: float) -> list[dict[str, object]]:
    ordered = sorted(set(selected_indices))
    gaps: list[dict[str, object]] = []
    for left, right in zip(ordered, ordered[1:]):
        gap_frames = right - left
        if gap_frames <= 1:
            continue
        gaps.append(
            {
                "from_thumb_index": left,
                "to_thumb_index": right,
                "gap_frames": gap_frames,
                "gap_seconds": round(gap_frames / max(frame_rate, 1e-6), 3),
            }
        )
    gaps.sort(key=lambda item: float(item["gap_seconds"]), reverse=True)
    return gaps[:8]


def _dense_peak_burst_indices(scores: Sequence[float], sample_count: int, *, radius: int = 8, peak_limit: int = 2) -> set[int]:
    if not scores or sample_count <= 0:
        return set()
    smoothed = _smooth_motion_scores(scores, window=3)
    selected: set[int] = set()
    budget = min(max(sample_count // 2, 12), sample_count)
    peaks = _top_local_peak_indices(smoothed, limit=peak_limit)
    for peak in peaks:
        ordered = list(range(max(0, peak - radius), min(len(scores), peak + radius + 1)))
        ordered.sort(key=lambda index: (abs(index - peak), -smoothed[index]))
        for index in ordered:
            selected.add(index)
            if len(selected) >= budget:
                return selected
    return selected


def _select_motion_weighted_indices(scores: Sequence[float], sample_count: int, *, dense_peak_bursts: bool = False) -> list[int]:
    total_frames = len(scores)
    if total_frames <= sample_count:
        return list(range(total_frames))

    smoothed = _smooth_motion_scores(scores, window=3)
    # 设计说明: top-3 局部运动峰值通常覆盖准备/起跳/落冰瞬间；
    # 先锁定 ±2 帧的邻域保护区，剩余配额再按运动密度分配。
    selected: set[int] = (
        _dense_peak_burst_indices(scores, sample_count, radius=8, peak_limit=2)
        if dense_peak_bursts
        else _peak_neighborhood_indices(smoothed, radius=2, limit=3)
    )
    if len(selected) >= sample_count:
        return sorted(selected)[:sample_count]

    segment_count = min(10, total_frames)
    base_quota = [1 for _ in range(segment_count)]
    remaining_after_peaks = max(sample_count - len(selected), 0)
    base_quota = [0 if remaining_after_peaks < segment_count else 1 for _ in range(segment_count)]
    remaining = max(remaining_after_peaks - sum(base_quota), 0)
    segment_ranges: list[tuple[int, int]] = []
    segment_weights: list[float] = []

    for segment in range(segment_count):
        start = round(segment * total_frames / segment_count)
        end = round((segment + 1) * total_frames / segment_count)
        if end <= start:
            end = min(start + 1, total_frames)
        segment_ranges.append((start, end))
        segment_weights.append(sum(smoothed[start:end]) + 0.001)

    total_weight = sum(segment_weights)
    extra = [0 for _ in range(segment_count)]
    if remaining > 0 and total_weight > 0:
        raw_extra = [(weight / total_weight) * remaining for weight in segment_weights]
        extra = [int(value) for value in raw_extra]
        leftovers = remaining - sum(extra)
        order = sorted(range(segment_count), key=lambda index: raw_extra[index] - extra[index], reverse=True)
        for index in order[:leftovers]:
            extra[index] += 1

    for segment_index, (start, end) in enumerate(segment_ranges):
        quota = max(0, min(base_quota[segment_index] + extra[segment_index], end - start))
        if quota == 0:
            continue
        segment_indices = list(range(start, end))
        segment_indices.sort(key=lambda index: smoothed[index], reverse=True)
        for index in segment_indices:
            if len([item for item in selected if start <= item < end]) >= quota:
                break
            selected.add(index)

    if len(selected) < sample_count:
        fallback = [round((index / (sample_count - 1)) * (total_frames - 1)) for index in range(sample_count)]
        for index in fallback:
            selected.add(index)
            if len(selected) >= sample_count:
                break

    if len(selected) > sample_count:
        selected_list = sorted(selected)
        protected = _peak_neighborhood_indices(smoothed, radius=2, limit=3)
        overflow = len(selected_list) - sample_count
        removable = [index for index in selected_list if index not in protected]
        for index in sorted(removable, key=lambda item: smoothed[item])[:overflow]:
            selected.remove(index)

    return sorted(selected)[:sample_count]


async def _extract_full_frame_at(video_path: Path, timestamp: float, target_path: Path) -> None:
    width, height = _frame_dimensions()
    scale_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    await _run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            scale_filter,
            "-pix_fmt",
            "yuvj420p",
            str(target_path),
        ]
    )


async def _extract_precise_full_frame_at(video_path: Path, timestamp: float, target_path: Path) -> None:
    width, height = _frame_dimensions()
    scale_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    await _run_ffmpeg(
        [
            "-y",
            "-i",
            str(video_path),
            "-ss",
            f"{timestamp:.3f}",
            "-frames:v",
            "1",
            "-vf",
            scale_filter,
            "-pix_fmt",
            "yuvj420p",
            str(target_path),
        ]
    )


async def _extract_local_motion_thumbnails(
    video_path: Path,
    thumbs_dir: Path,
    start_sec: float,
    end_sec: float,
    frame_rate: float,
) -> list[Path]:
    width, height = _size_tuple(FRAME_THUMB_SIZE)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(thumbs_dir / "refine_%05d.jpg")
    scale_filter = (
        f"fps={frame_rate:.3f},"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )
    await _run_ffmpeg(
        [
            "-y",
            "-i",
            str(video_path),
            "-ss",
            f"{max(0.0, start_sec):.3f}",
            "-t",
            f"{max(end_sec - start_sec, 0.001):.3f}",
            "-vf",
            scale_filter,
            "-pix_fmt",
            "yuvj420p",
            output_pattern,
        ]
    )
    return sorted(thumbs_dir.glob("refine_*.jpg"))


def _semantic_key_moment(record: dict[str, object]) -> str | None:
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


def _refinement_fps(source_fps: float | None) -> float:
    if source_fps is None or source_fps <= 0:
        return 60.0
    return max(1.0, min(float(source_fps), 60.0))


def _semantic_record_timestamp(record: dict[str, object]) -> float | None:
    try:
        return float(record.get("timestamp"))
    except (TypeError, ValueError):
        return None


def _semantic_order_anchors(records: Sequence[dict[str, object]]) -> dict[str, float]:
    anchors: dict[str, float] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = _semantic_key_moment(record)
        timestamp = _semantic_record_timestamp(record)
        if key in {"T", "A", "L"} and timestamp is not None:
            anchors[key] = timestamp
    return anchors


def _semantic_phase_bounds(record: dict[str, object]) -> tuple[float | None, float | None]:
    start = record.get("phase_time_start")
    end = record.get("phase_time_end")
    if start is None:
        start = record.get("time_start")
    if end is None:
        end = record.get("time_end")
    try:
        start_value = None if start is None else float(start)
    except (TypeError, ValueError):
        start_value = None
    try:
        end_value = None if end is None else float(end)
    except (TypeError, ValueError):
        end_value = None
    if start_value is not None and end_value is not None and end_value <= start_value:
        return None, None
    return start_value, end_value


def _semantic_refinement_max_delta(record: dict[str, object], default: float = 0.12) -> float:
    value = record.get("max_refinement_delta_sec")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(parsed, 0.30))


def _semantic_refinement_max_backward_delta(record: dict[str, object], default: float | None = None) -> float | None:
    value = record.get("max_refinement_backward_delta_sec")
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(parsed, 0.30))


def _semantic_refinement_window_seconds(record: dict[str, object], default: float) -> float:
    value = record.get("refinement_window_seconds")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(parsed, 0.30))


def _semantic_phase_end_refinement_tolerance(record: dict[str, object], key: str | None) -> float:
    if key != "L":
        return 0.0
    value = record.get("phase_time_end_refinement_tolerance_sec")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(parsed, 0.25))


def _semantic_phase_start_refinement_tolerance(record: dict[str, object], key: str | None) -> float:
    if key != "L":
        return 0.0
    value = record.get("phase_time_start_refinement_tolerance_sec")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(parsed, 0.25))


def _record_rejected_refinement_candidate(
    output: dict[str, object],
    *,
    refined_ts: float,
    original_ts: float,
    fps: float,
    motion_score: float,
    reason: str,
) -> None:
    output["timestamp"] = round(original_ts, 3)
    output["refinement_method"] = f"local_motion_peak_{reason}_rejected"
    output["refinement_delta_sec"] = 0.0
    output["refinement_fps"] = round(fps, 3)
    output["refinement_motion_score"] = motion_score
    output["refinement_candidate_timestamp"] = round(refined_ts, 3)
    output["refinement_candidate_delta_sec"] = round(refined_ts - original_ts, 3)
    output["refinement_reject_reason"] = reason


def _violates_semantic_order(key: str | None, timestamp: float, anchors: dict[str, float], min_gap_sec: float = 0.02) -> bool:
    if key == "T":
        apex = anchors.get("A")
        landing = anchors.get("L")
        return (apex is not None and timestamp >= apex - min_gap_sec) or (landing is not None and timestamp >= landing - min_gap_sec)
    if key == "A":
        takeoff = anchors.get("T")
        landing = anchors.get("L")
        return (takeoff is not None and timestamp <= takeoff + min_gap_sec) or (landing is not None and timestamp >= landing - min_gap_sec)
    if key == "L":
        takeoff = anchors.get("T")
        apex = anchors.get("A")
        return (takeoff is not None and timestamp <= takeoff + min_gap_sec) or (apex is not None and timestamp <= apex + min_gap_sec)
    return False


async def _refine_motion_peak_timestamp(
    video_path: Path,
    work_dir: Path,
    timestamp: float,
    *,
    source_fps: float | None,
    video_duration_sec: float | None,
    window_seconds: float,
) -> tuple[float, float, float]:
    fps = _refinement_fps(source_fps)
    duration = video_duration_sec if video_duration_sec is not None and video_duration_sec > 0 else None
    start = max(0.0, timestamp - window_seconds)
    end = timestamp + window_seconds
    if duration is not None:
        end = min(duration, end)
    if end <= start:
        return round(timestamp, 3), fps, 0.0

    thumbs_dir = work_dir / f"refine_{int(timestamp * 1000):08d}"
    if thumbs_dir.exists():
        shutil.rmtree(thumbs_dir, ignore_errors=True)
    try:
        thumbs = await _extract_local_motion_thumbnails(video_path, thumbs_dir, start, end, fps)
        scores = _motion_scores_from_thumbs(thumbs)
    finally:
        shutil.rmtree(thumbs_dir, ignore_errors=True)

    if not scores:
        return round(timestamp, 3), fps, 0.0

    best_index = max(range(len(scores)), key=lambda index: (scores[index], -abs((start + index / fps) - timestamp)))
    refined = start + (best_index / fps)
    if duration is not None:
        refined = min(duration, refined)
    return round(max(0.0, refined), 3), fps, round(float(scores[best_index]), 4)


async def refine_semantic_keyframe_timestamps(
    video_path: Path,
    work_dir: Path,
    selected_records: Sequence[dict[str, object]],
    *,
    source_fps: float | None = None,
    video_duration_sec: float | None = None,
    window_seconds: float = 0.18,
) -> tuple[list[dict[str, object]], list[str]]:
    """
    Refine semantic T/L timestamps with a short high-fps local motion scan.

    Apex frames are intentionally preserved because the highest COM point does
    not usually coincide with the strongest motion impulse.
    """
    refined_records: list[dict[str, object]] = []
    quality_flags: list[str] = []
    order_anchors = _semantic_order_anchors(selected_records)
    work_dir.mkdir(parents=True, exist_ok=True)

    for record in selected_records:
        if not isinstance(record, dict):
            continue
        output: dict[str, object] = dict(record)
        try:
            timestamp = float(record.get("timestamp"))
        except (TypeError, ValueError):
            output["refinement_method"] = "invalid_timestamp_preserved"
            quality_flags.append("semantic_keyframe_refinement_invalid_timestamp")
            refined_records.append(output)
            continue

        key = _semantic_key_moment(record)
        output["pre_refine_timestamp"] = round(timestamp, 3)
        if key == "A":
            output["refinement_method"] = "apex_preserved"
            output["refinement_delta_sec"] = 0.0
            output["refinement_fps"] = _refinement_fps(source_fps)
            output["refinement_motion_score"] = None
            refined_records.append(output)
            continue
        if key not in {"T", "L"}:
            output["refinement_method"] = "not_applicable"
            output["refinement_delta_sec"] = 0.0
            output["refinement_fps"] = _refinement_fps(source_fps)
            output["refinement_motion_score"] = None
            refined_records.append(output)
            continue

        try:
            record_window_seconds = _semantic_refinement_window_seconds(record, window_seconds)
            refined_ts, fps, motion_score = await _refine_motion_peak_timestamp(
                video_path,
                work_dir,
                timestamp,
                source_fps=source_fps,
                video_duration_sec=video_duration_sec,
                window_seconds=record_window_seconds,
            )
            phase_start, phase_end = _semantic_phase_bounds(record)
            phase_start_tolerance = _semantic_phase_start_refinement_tolerance(record, key)
            phase_end_tolerance = _semantic_phase_end_refinement_tolerance(record, key)
            if phase_start_tolerance > 0:
                output["phase_time_start_refinement_tolerance_sec"] = round(phase_start_tolerance, 3)
            if phase_end_tolerance > 0:
                output["phase_time_end_refinement_tolerance_sec"] = round(phase_end_tolerance, 3)
            if (
                (phase_start is not None and refined_ts < phase_start - phase_start_tolerance)
                or (phase_end is not None and refined_ts > phase_end + phase_end_tolerance)
            ):
                _record_rejected_refinement_candidate(
                    output,
                    refined_ts=refined_ts,
                    original_ts=timestamp,
                    fps=fps,
                    motion_score=motion_score,
                    reason="phase",
                )
                quality_flags.append("semantic_keyframe_refinement_phase_rejected")
                refined_records.append(output)
                continue
            if _violates_semantic_order(key, refined_ts, order_anchors):
                _record_rejected_refinement_candidate(
                    output,
                    refined_ts=refined_ts,
                    original_ts=timestamp,
                    fps=fps,
                    motion_score=motion_score,
                    reason="order",
                )
                quality_flags.append("semantic_keyframe_refinement_order_rejected")
                refined_records.append(output)
                continue
            max_delta = _semantic_refinement_max_delta(record)
            if abs(refined_ts - timestamp) > max_delta:
                _record_rejected_refinement_candidate(
                    output,
                    refined_ts=refined_ts,
                    original_ts=timestamp,
                    fps=fps,
                    motion_score=motion_score,
                    reason="delta",
                )
                quality_flags.append("semantic_keyframe_refinement_delta_rejected")
                refined_records.append(output)
                continue
            max_backward_delta = _semantic_refinement_max_backward_delta(record)
            if max_backward_delta is not None and refined_ts < timestamp - max_backward_delta:
                _record_rejected_refinement_candidate(
                    output,
                    refined_ts=refined_ts,
                    original_ts=timestamp,
                    fps=fps,
                    motion_score=motion_score,
                    reason="backward_delta",
                )
                quality_flags.append("semantic_keyframe_refinement_backward_delta_rejected")
                refined_records.append(output)
                continue
            output["timestamp"] = refined_ts
            output["refinement_method"] = "local_motion_peak"
            output["refinement_delta_sec"] = round(refined_ts - timestamp, 3)
            output["refinement_fps"] = round(fps, 3)
            output["refinement_motion_score"] = motion_score
            if phase_start is not None and refined_ts < phase_start and phase_start_tolerance > 0:
                output["refinement_phase_start_tolerance_used"] = True
                quality_flags.append("semantic_keyframe_refinement_phase_start_tolerance_used")
            if phase_end is not None and refined_ts > phase_end and phase_end_tolerance > 0:
                output["refinement_phase_end_tolerance_used"] = True
                quality_flags.append("semantic_keyframe_refinement_phase_end_tolerance_used")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Semantic keyframe local refinement failed at %.3fs: %s", timestamp, exc)
            output["timestamp"] = round(timestamp, 3)
            output["refinement_method"] = "refinement_failed_preserved"
            output["refinement_delta_sec"] = 0.0
            output["refinement_fps"] = _refinement_fps(source_fps)
            output["refinement_motion_score"] = None
            quality_flags.append("semantic_keyframe_refinement_failed")
        refined_records.append(output)

    return refined_records, sorted(set(quality_flags))


async def extract_precise_frames_at_timestamps(
    video_path: Path,
    frames_dir: Path,
    selected_records: Sequence[dict[str, object]],
    prefix: str = "semantic",
) -> tuple[list[Path], list[dict[str, object]]]:
    """
    Extract semantic keyframes at resolved timestamps with accurate FFmpeg seek.

    Uses output-side -ss after -i to avoid depending only on fast GOP seek. The
    returned records are compatible with build_timestamp_map({"selected": ...}).
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    if not video_path.exists():
        raise AnalysisPipelineError(AnalysisErrorCode.FRAME_EXTRACT_FAILED, f"Video not found: {video_path}")

    valid_records: list[dict[str, object]] = []
    for record in selected_records:
        if not isinstance(record, dict):
            continue
        try:
            timestamp = float(record.get("timestamp"))
        except (TypeError, ValueError):
            continue
        if timestamp < 0:
            continue
        valid_records.append({**record, "timestamp": round(timestamp, 3)})

    if not valid_records:
        raise AnalysisPipelineError(
            AnalysisErrorCode.FRAME_EXTRACT_FAILED,
            "No valid semantic timestamps were provided for precise extraction.",
        )

    for existing_frame in frames_dir.glob(f"{prefix}_*.jpg"):
        existing_frame.unlink(missing_ok=True)

    output_paths: list[Path] = []
    output_records: list[dict[str, object]] = []
    try:
        for output_index, record in enumerate(valid_records, start=1):
            timestamp = float(record["timestamp"])
            frame_id = f"{prefix}_{output_index:04d}"
            target_path = frames_dir / f"{frame_id}.jpg"
            await _extract_precise_full_frame_at(video_path, timestamp, target_path)
            if not target_path.exists() or target_path.stat().st_size <= 0:
                raise RuntimeError(f"Semantic frame was not created: {target_path}")
            output_paths.append(target_path)
            output_record = {**record, "frame_id": frame_id, "timestamp": round(timestamp, 3)}
            output_records.append(output_record)
    except Exception as exc:  # noqa: BLE001
        for path in output_paths:
            path.unlink(missing_ok=True)
        if isinstance(exc, AnalysisPipelineError):
            raise
        raise AnalysisPipelineError(
            AnalysisErrorCode.FRAME_EXTRACT_FAILED,
            f"Precise semantic frame extraction failed: {exc}",
        ) from exc

    return output_paths, output_records


async def restore_sampled_frames(
    video_path: Path,
    frames_dir: Path,
    selected_frames: Sequence[dict[str, object]] | None,
) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    restored_paths: list[Path] = []

    selected_items = [item for item in (selected_frames or []) if isinstance(item, dict)]
    if selected_items:
        for existing_frame in frames_dir.glob("frame_*.jpg"):
            existing_frame.unlink(missing_ok=True)

        for output_index, item in enumerate(selected_items, start=1):
            try:
                timestamp = float(item.get("timestamp"))
            except (TypeError, ValueError):
                continue

            frame_id = str(item.get("frame_id") or f"frame_{output_index:04d}")
            filename = f"{frame_id}.jpg" if not frame_id.endswith(".jpg") else frame_id
            target_path = frames_dir / filename
            await _extract_full_frame_at(video_path, timestamp, target_path)
            restored_paths.append(target_path)

    return sorted(restored_paths)


async def extract_motion_sampled_frames(
    video_path: Path,
    frames_dir: Path,
    action_type: str,
    analysis_profile: str | None = None,
    *,
    dense_peak_bursts: bool = False,
    full_video_window: bool = False,
    input_window: VideoInputWindow | None = None,
) -> tuple[list[Path], dict[str, object], VideoSamplingMetadata]:
    for existing_frame in frames_dir.glob("frame_*.jpg"):
        existing_frame.unlink(missing_ok=True)
    thumbs_dir = frames_dir.parent / "thumbs"
    if thumbs_dir.exists():
        shutil.rmtree(thumbs_dir)

    source_fps = detect_video_fps(video_path)
    is_slow_motion = source_fps >= SLOW_MOTION_THRESHOLD_FPS
    slow_motion_scale = get_slow_motion_scale(source_fps) if is_slow_motion else 1.0
    frame_rate = get_frame_rate_for_profile(analysis_profile)
    sample_count = get_max_frames_for_profile(analysis_profile)
    if input_window is not None:
        start_sec = input_window.input_window_start_sec
        end_sec = input_window.input_window_end_sec
        window_diagnostics: dict[str, object] = {
            "selection_reason": input_window.input_window_reason,
            "candidate_windows": [],
            "late_window_override": False,
            "selected_start_sec": round(start_sec, 3),
            "selected_end_sec": round(end_sec, 3),
            "input_window_mode": input_window.input_window_mode,
            "input_window_truncated": input_window.input_window_truncated,
        }
    elif full_video_window:
        duration = detect_video_duration(video_path)
        start_sec = 0.0
        end_sec = min(float(MAX_SECONDS), float(duration)) if duration and duration > 0 else float(MAX_SECONDS)
        window_diagnostics: dict[str, object] = {
            "selection_reason": "full_video_debug",
            "candidate_windows": [],
            "late_window_override": False,
            "selected_start_sec": round(start_sec, 3),
            "selected_end_sec": round(end_sec, 3),
        }
    else:
        start_sec, end_sec = await detect_action_window(video_path, action_type, source_fps, analysis_profile)
        window_diagnostics = dict(_LAST_ACTION_WINDOW_DIAGNOSTICS.get() or {})
        if not window_diagnostics:
            window_diagnostics = {
                "selection_reason": "detected_action_window",
                "candidate_windows": [],
                "late_window_override": False,
                "selected_start_sec": round(start_sec, 3),
                "selected_end_sec": round(end_sec, 3),
            }
    window_start_sec, window_end_sec, effective_fps = _effective_sampling_context(
        start_sec,
        end_sec,
        sample_count,
        slow_motion_scale,
    )
    sampling_metadata = VideoSamplingMetadata(
        action_window_start=round(start_sec, 3),
        action_window_end=round(end_sec, 3),
        window_start_sec=window_start_sec,
        window_end_sec=window_end_sec,
        effective_fps=effective_fps,
        source_fps=round(source_fps, 3),
        is_slow_motion=is_slow_motion,
    )

    try:
        thumbs = await _extract_thumbnails_in_window(video_path, thumbs_dir, start_sec, end_sec, frame_rate=frame_rate)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Thumbnail extraction inside action window failed for %s, falling back to full-video sampling",
            video_path,
            exc_info=True,
        )
        if thumbs_dir.exists():
            shutil.rmtree(thumbs_dir, ignore_errors=True)
        start_sec, end_sec = _fallback_profile_window(action_type, analysis_profile, source_fps)
        window_start_sec, window_end_sec, effective_fps = _effective_sampling_context(
            start_sec,
            end_sec,
            sample_count,
            slow_motion_scale,
        )
        sampling_metadata = VideoSamplingMetadata(
            action_window_start=round(start_sec, 3),
            action_window_end=round(end_sec, 3),
            window_start_sec=window_start_sec,
            window_end_sec=window_end_sec,
            effective_fps=effective_fps,
            source_fps=round(source_fps, 3),
            is_slow_motion=is_slow_motion,
        )
        thumbs = await _extract_thumbnails(video_path, thumbs_dir, frame_rate=frame_rate)
    if not thumbs:
        raise RuntimeError("视频缩略图抽取结果为空，请检查上传文件是否损坏。")

    scores = _motion_scores_from_thumbs(thumbs)
    selected_indices = _select_motion_weighted_indices(scores, sample_count, dense_peak_bursts=dense_peak_bursts)

    output_paths: list[Path] = []
    selected_records: list[dict[str, object]] = []
    try:
        for output_index, thumb_index in enumerate(selected_indices, start=1):
            timestamp = start_sec + (thumb_index / frame_rate)
            target_path = frames_dir / f"frame_{output_index:04d}.jpg"
            await _extract_full_frame_at(video_path, timestamp, target_path)
            output_paths.append(target_path)
            selected_records.append(
                {
                    "frame_id": target_path.stem,
                    "source_thumb_index": thumb_index,
                    "timestamp": round(timestamp, 3),
                    "motion_score": round(scores[thumb_index] if thumb_index < len(scores) else 0.0, 4),
                }
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Full-frame extraction failed for %s, falling back to uniform frame extraction",
            video_path,
            exc_info=True,
        )
        for existing_frame in frames_dir.glob("frame_*.jpg"):
            existing_frame.unlink(missing_ok=True)
        output_paths = sample_frame_paths(await extract_frames(video_path, frames_dir, frame_rate=frame_rate), sample_count)
        selected_records = [
            {
                "frame_id": frame_path.stem,
                "source_thumb_index": index,
                "timestamp": round(start_sec + index / frame_rate, 3),
                "motion_score": None,
            }
            for index, frame_path in enumerate(output_paths)
        ]

    motion_payload = {
        "frame_rate": frame_rate,
        "thumb_size": FRAME_THUMB_SIZE,
        "full_size": FRAME_FULL_SIZE,
        "window_start": round(start_sec, 3),
        "window_end": round(end_sec, 3),
        "window_start_sec": window_start_sec,
        "window_end_sec": window_end_sec,
        "effective_fps": effective_fps,
        "analysis_profile_hint": analysis_profile,
        "source_fps": round(source_fps, 3),
        "is_slow_motion": is_slow_motion,
        "slow_motion_scale": round(slow_motion_scale, 3),
        "effective_window_duration": round((end_sec - start_sec) / slow_motion_scale, 3),
        "total_thumb_frames": len(thumbs),
        "sample_count": len(output_paths),
        "max_frames_for_profile": sample_count,
        "selection_strategy": "dense_peak_bursts" if dense_peak_bursts else "motion_weighted",
        "window_strategy": "full_video_debug" if full_video_window else "detected_action_window",
        "window_diagnostics": window_diagnostics,
        "top_motion_peaks": [
            {**record, "timestamp": round(start_sec + float(record["timestamp_offset"]), 3)}
            for record in _motion_peak_records(scores, frame_rate=frame_rate)
        ],
        "coverage_gaps": _coverage_gap_records(selected_indices, frame_rate=frame_rate),
        "selected": selected_records,
        "scores": [round(score, 4) for score in scores],
    }
    attach_input_window_payload(motion_payload, input_window)

    return output_paths, motion_payload, sampling_metadata


async def encode_frames(
    frame_paths: Sequence[Path],
    timestamps: dict[str, float] | None = None,
) -> list[FramePayload]:
    """
    Encode frame paths as vision payloads.

    timestamps maps frame_path.stem to seconds. When omitted, timestamp_sec
    remains 0.0 for every payload to preserve existing callers.
    """
    filtered_frame_paths = filter_frames(frame_paths)
    if len(filtered_frame_paths) != len(frame_paths):
        logger.info(
            "Filtered blurry frames before vision encoding: kept %s/%s frames",
            len(filtered_frame_paths),
            len(frame_paths),
        )

    payloads: list[FramePayload] = []
    ts_map = timestamps or {}
    for frame_path in filtered_frame_paths:
        async with aiofiles.open(frame_path, "rb") as frame_file:
            binary = await frame_file.read()
        payloads.append(
            FramePayload(
                frame_id=frame_path.stem,
                data_url=f"data:image/jpeg;base64,{base64.b64encode(binary).decode('utf-8')}",
                timestamp_sec=ts_map.get(frame_path.stem, 0.0),
            )
        )
    return payloads


def build_timestamp_map(sampling_payload: dict[str, object] | None) -> dict[str, float]:
    """
    Build frame_id(stem) -> seconds from extract_motion_sampled_frames metadata.

    Fallback timestamps may not include action-window offset, so callers should
    treat them as ordering/relative-position hints rather than physical time.
    """
    if not isinstance(sampling_payload, dict):
        return {}
    selected = sampling_payload.get("selected")
    if not isinstance(selected, list):
        return {}

    out: dict[str, float] = {}
    for rec in selected:
        if not isinstance(rec, dict):
            continue
        frame_id = rec.get("frame_id")
        timestamp = rec.get("timestamp")
        if isinstance(frame_id, str) and isinstance(timestamp, (int, float)):
            out[frame_id] = float(timestamp)
    return out
