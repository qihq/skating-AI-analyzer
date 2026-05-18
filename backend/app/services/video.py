from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import shutil
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
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500"))
ALLOWED_SUFFIXES = {".mp4", ".mov", ".avi"}
SLOW_MOTION_THRESHOLD_FPS = 60.0
ACTION_WINDOW_DETECTION_FPS = 2
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
    window_size = ACTION_WINDOW_SIZES.get(action_type)
    if window_size is None:
        return 0.0, float(MAX_SECONDS)
    return 0.0, min(float(MAX_SECONDS), float(window_size) + 2.0)


def _fallback_profile_window(action_type: str, analysis_profile: str | None, source_fps: float = NORMAL_PLAYBACK_FPS) -> tuple[float, float]:
    window_size = get_window_seconds_for_profile(analysis_profile, action_type)
    if window_size is None:
        return 0.0, float(MAX_SECONDS)
    source_window_size = get_source_window_duration(float(window_size), source_fps)
    return 0.0, min(float(MAX_SECONDS), source_window_size + 2.0)


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
    window_size = get_window_seconds_for_profile(analysis_profile, action_type)
    if window_size is None:
        return 0, len(motion_scores)

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
        return best_start, best_start + window_frames

    best_start = 0
    best_score = float("-inf")
    for index in range(max_start):
        window = motion_scores[index : index + window_frames]
        if not window:
            continue
        if analysis_profile == "spin":
            current_score = sum(window) - abs(window[0] - window[-1])
        else:
            current_score = sum(window)
        if current_score > best_score:
            best_score = current_score
            best_start = index
    return best_start, best_start + window_frames


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
    window_size = ACTION_WINDOW_SIZES.get(action_type)
    if window_size is None:
        return 0.0, float(MAX_SECONDS)

    thumbs_dir = video_path.parent / f"{video_path.stem}_action_thumbs"
    try:
        if thumbs_dir.exists():
            shutil.rmtree(thumbs_dir)
        thumbs = await _extract_action_thumbnails(video_path, thumbs_dir)
        motion_scores = _motion_scores_from_thumbs(thumbs)
    except Exception:  # noqa: BLE001
        logger.warning("Action window detection failed for %s, using fallback window", video_path, exc_info=True)
        return _fallback_profile_window(action_type, analysis_profile, source_fps)
    finally:
        if thumbs_dir.exists():
            shutil.rmtree(thumbs_dir, ignore_errors=True)

    if len(motion_scores) <= 1:
        return _fallback_profile_window(action_type, analysis_profile, source_fps)

    best_start_frame, best_end_frame = _pick_window_by_profile(motion_scores, action_type, analysis_profile, source_fps)
    selected_window_size = get_window_seconds_for_profile(analysis_profile, action_type)
    if selected_window_size is None:
        return 0.0, float(MAX_SECONDS)
    source_window_size = get_source_window_duration(float(selected_window_size), source_fps)

    start_sec = max(0.0, best_start_frame / ACTION_WINDOW_DETECTION_FPS - 1.0)
    end_sec = max(start_sec + 1.0, (best_end_frame / ACTION_WINDOW_DETECTION_FPS) + 1.0)
    end_sec = min(end_sec, start_sec + source_window_size + 2.0)
    if end_sec <= start_sec:
        return _fallback_profile_window(action_type, analysis_profile, source_fps)
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
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        message = stderr.decode("utf-8", errors="ignore").strip()
        if process.returncode == 0:
            return

        last_message = message or "未知错误"
        retryable = any(fragment in last_message.lower() for fragment in FFMPEG_RETRYABLE_ERRORS)
        if attempt < attempts and retryable:
            logger.warning("FFmpeg failed on attempt %s/%s, retrying once: %s", attempt, attempts, last_message)
            await asyncio.sleep(0.3)
            continue
        break

    raise RuntimeError(f"FFmpeg 处理失败：{last_message}")


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


def _select_motion_weighted_indices(scores: Sequence[float], sample_count: int) -> list[int]:
    total_frames = len(scores)
    if total_frames <= sample_count:
        return list(range(total_frames))

    smoothed = _smooth_motion_scores(scores, window=3)
    # 设计说明: top-3 局部运动峰值通常覆盖准备/起跳/落冰瞬间；
    # 先锁定 ±2 帧的邻域保护区，剩余配额再按运动密度分配。
    selected: set[int] = _peak_neighborhood_indices(smoothed, radius=2, limit=3)
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
    start_sec, end_sec = await detect_action_window(video_path, action_type, source_fps, analysis_profile)
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
    selected_indices = _select_motion_weighted_indices(scores, sample_count)

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
        "selected": selected_records,
        "scores": [round(score, 4) for score in scores],
    }

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
