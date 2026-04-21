from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import aiofiles
from fastapi import UploadFile

from app.database import UPLOADS_DIR


logger = logging.getLogger(__name__)

FRAME_RATE = 5
MAX_SECONDS = 60
MAX_SAMPLED_FRAMES = int(os.getenv("FRAME_SAMPLE_COUNT", "20"))
FRAME_THUMB_SIZE = os.getenv("FRAME_THUMB_SIZE", "160x90")
FRAME_FULL_SIZE = os.getenv("FRAME_FULL_SIZE", "854x480")
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500"))
ALLOWED_SUFFIXES = {".mp4", ".mov", ".avi"}
SLOW_MOTION_THRESHOLD_FPS = 60.0
ACTION_WINDOW_DETECTION_FPS = 2
PROCESSING_ROOT = Path("/tmp/skating-analyzer") if Path("/tmp").exists() else UPLOADS_DIR / "_processing"

ACTION_WINDOW_SIZES: dict[str, float | None] = {
    "跳跃": 3.0,
    "旋转": 5.0,
    "步法": 8.0,
    "自由滑": None,
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


@dataclass(slots=True)
class VideoSamplingMetadata:
    action_window_start: float
    action_window_end: float
    source_fps: float
    is_slow_motion: bool


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


async def extract_frames(video_path: Path, frames_dir: Path) -> list[Path]:
    width, height = _frame_dimensions()
    output_pattern = str(frames_dir / "frame_%04d.jpg")
    scale_filter = (
        f"fps={FRAME_RATE},"
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


def _fallback_action_window(action_type: str) -> tuple[float, float]:
    window_size = ACTION_WINDOW_SIZES.get(action_type)
    if window_size is None:
        return 0.0, float(MAX_SECONDS)
    return 0.0, min(float(MAX_SECONDS), float(window_size) + 2.0)


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


async def detect_action_window(video_path: Path, action_type: str, source_fps: float) -> tuple[float, float]:
    """
    用运动密度曲线找到峰值区间，返回 (start_sec, end_sec)。
    无法定位时退化为分析前 N 秒；自由滑维持前 60 秒。
    """
    del source_fps

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
        return _fallback_action_window(action_type)
    finally:
        if thumbs_dir.exists():
            shutil.rmtree(thumbs_dir, ignore_errors=True)

    if len(motion_scores) <= 1:
        return _fallback_action_window(action_type)

    window_frames = max(1, int(window_size * ACTION_WINDOW_DETECTION_FPS))
    best_start_frame = 0
    best_score = -1.0
    max_start = max(1, len(motion_scores) - window_frames + 1)
    for index in range(max_start):
        current_score = sum(motion_scores[index : index + window_frames])
        if current_score > best_score:
            best_score = current_score
            best_start_frame = index

    start_sec = max(0.0, best_start_frame / ACTION_WINDOW_DETECTION_FPS - 1.0)
    end_sec = start_sec + float(window_size) + 2.0
    if end_sec <= start_sec:
        return _fallback_action_window(action_type)
    return start_sec, end_sec


def sample_frame_paths(frame_paths: Sequence[Path], max_frames: int = MAX_SAMPLED_FRAMES) -> list[Path]:
    if len(frame_paths) <= max_frames:
        return list(frame_paths)

    last_index = len(frame_paths) - 1
    sampled_indices = [round((index / (max_frames - 1)) * last_index) for index in range(max_frames)]
    return [frame_paths[index] for index in sampled_indices]


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


async def _extract_thumbnails(video_path: Path, thumbs_dir: Path) -> list[Path]:
    width, height = _size_tuple(FRAME_THUMB_SIZE)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(thumbs_dir / "thumb_%05d.jpg")
    scale_filter = f"fps={FRAME_RATE},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    await _run_ffmpeg(["-y", "-i", str(video_path), "-vf", scale_filter, "-pix_fmt", "yuvj420p", output_pattern])
    return sorted(thumbs_dir.glob("thumb_*.jpg"))


async def _extract_thumbnails_in_window(video_path: Path, thumbs_dir: Path, start_sec: float, end_sec: float) -> list[Path]:
    width, height = _size_tuple(FRAME_THUMB_SIZE)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(thumbs_dir / "thumb_%05d.jpg")
    scale_filter = (
        f"fps={FRAME_RATE},"
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


def _select_motion_weighted_indices(scores: Sequence[float], sample_count: int) -> list[int]:
    total_frames = len(scores)
    if total_frames <= sample_count:
        return list(range(total_frames))

    segment_count = min(10, total_frames)
    base_quota = [1 for _ in range(segment_count)]
    remaining = max(sample_count - segment_count, 0)
    segment_ranges: list[tuple[int, int]] = []
    segment_weights: list[float] = []

    for segment in range(segment_count):
        start = round(segment * total_frames / segment_count)
        end = round((segment + 1) * total_frames / segment_count)
        if end <= start:
            end = min(start + 1, total_frames)
        segment_ranges.append((start, end))
        segment_weights.append(sum(scores[start:end]) + 0.001)

    total_weight = sum(segment_weights)
    extra = [0 for _ in range(segment_count)]
    if remaining > 0 and total_weight > 0:
        raw_extra = [(weight / total_weight) * remaining for weight in segment_weights]
        extra = [int(value) for value in raw_extra]
        leftovers = remaining - sum(extra)
        order = sorted(range(segment_count), key=lambda index: raw_extra[index] - extra[index], reverse=True)
        for index in order[:leftovers]:
            extra[index] += 1

    selected: set[int] = set()
    for segment_index, (start, end) in enumerate(segment_ranges):
        quota = min(base_quota[segment_index] + extra[segment_index], end - start)
        segment_indices = list(range(start, end))
        segment_indices.sort(key=lambda index: scores[index], reverse=True)
        selected.update(segment_indices[:quota])

    if len(selected) < sample_count:
        fallback = [round((index / (sample_count - 1)) * (total_frames - 1)) for index in range(sample_count)]
        selected.update(fallback)

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


async def extract_motion_sampled_frames(
    video_path: Path,
    frames_dir: Path,
    action_type: str,
) -> tuple[list[Path], dict[str, object], VideoSamplingMetadata]:
    for existing_frame in frames_dir.glob("frame_*.jpg"):
        existing_frame.unlink(missing_ok=True)
    thumbs_dir = frames_dir.parent / "thumbs"
    if thumbs_dir.exists():
        shutil.rmtree(thumbs_dir)

    source_fps = detect_video_fps(video_path)
    is_slow_motion = source_fps >= SLOW_MOTION_THRESHOLD_FPS
    start_sec, end_sec = await detect_action_window(video_path, action_type, source_fps)
    sampling_metadata = VideoSamplingMetadata(
        action_window_start=round(start_sec, 3),
        action_window_end=round(end_sec, 3),
        source_fps=round(source_fps, 3),
        is_slow_motion=is_slow_motion,
    )

    try:
        thumbs = await _extract_thumbnails_in_window(video_path, thumbs_dir, start_sec, end_sec)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Thumbnail extraction inside action window failed for %s, falling back to full-video sampling",
            video_path,
            exc_info=True,
        )
        if thumbs_dir.exists():
            shutil.rmtree(thumbs_dir, ignore_errors=True)
        start_sec, end_sec = 0.0, float(MAX_SECONDS)
        sampling_metadata = VideoSamplingMetadata(
            action_window_start=round(start_sec, 3),
            action_window_end=round(end_sec, 3),
            source_fps=round(source_fps, 3),
            is_slow_motion=is_slow_motion,
        )
        thumbs = await _extract_thumbnails(video_path, thumbs_dir)
    if not thumbs:
        raise RuntimeError("视频缩略图抽取结果为空，请检查上传文件是否损坏。")

    scores = _motion_scores_from_thumbs(thumbs)
    selected_indices = _select_motion_weighted_indices(scores, MAX_SAMPLED_FRAMES)

    output_paths: list[Path] = []
    selected_records: list[dict[str, object]] = []
    try:
        for output_index, thumb_index in enumerate(selected_indices, start=1):
            timestamp = start_sec + (thumb_index / FRAME_RATE)
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
        output_paths = sample_frame_paths(await extract_frames(video_path, frames_dir), MAX_SAMPLED_FRAMES)
        selected_records = [
            {
                "frame_id": frame_path.stem,
                "source_thumb_index": index,
                "timestamp": round(index / FRAME_RATE, 3),
                "motion_score": None,
            }
            for index, frame_path in enumerate(output_paths)
        ]

    motion_payload = {
        "frame_rate": FRAME_RATE,
        "thumb_size": FRAME_THUMB_SIZE,
        "full_size": FRAME_FULL_SIZE,
        "window_start": round(start_sec, 3),
        "window_end": round(end_sec, 3),
        "source_fps": round(source_fps, 3),
        "is_slow_motion": is_slow_motion,
        "total_thumb_frames": len(thumbs),
        "sample_count": len(output_paths),
        "selected": selected_records,
        "scores": [round(score, 4) for score in scores],
    }

    return output_paths, motion_payload, sampling_metadata


async def encode_frames(frame_paths: Sequence[Path]) -> list[FramePayload]:
    payloads: list[FramePayload] = []
    for frame_path in frame_paths:
        async with aiofiles.open(frame_path, "rb") as frame_file:
            binary = await frame_file.read()
        payloads.append(
            FramePayload(
                frame_id=frame_path.stem,
                data_url=f"data:image/jpeg;base64,{base64.b64encode(binary).decode('utf-8')}",
            )
        )
    return payloads
