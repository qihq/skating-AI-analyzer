"""视频处理：FFmpeg 抽帧、运动检测、动作窗口定位。已解耦，可独立使用。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import shutil
from pathlib import Path
from typing import Any, Sequence

import aiofiles

from skating_vision.types import FramePayload, VideoSamplingMetadata

logger = logging.getLogger(__name__)

FRAME_RATE = 5
MAX_SECONDS = 60
SLOW_MOTION_THRESHOLD_FPS = 60.0
ACTION_WINDOW_DETECTION_FPS = 2
ALLOWED_SUFFIXES = {".mp4", ".mov", ".avi"}

ACTION_WINDOW_SIZES: dict[str, float | None] = {"跳跃": 3.0, "旋转": 5.0, "步法": 8.0, "自由滑": None}
PROFILE_WINDOW_SIZES: dict[str, float | None] = {"jump": 3.0, "spin": 5.0, "step": 8.0, "spiral": 6.0}
FFMPEG_RETRYABLE_ERRORS = ("partial file", "cannot allocate memory", "error during demuxing", "could not open encoder before eof", "error while opening encoder")

# ── Configurable paths (call configure() or set env vars) ──────────────
_config: dict[str, Any] = {}


def configure(
    uploads_dir: Path | None = None,
    processing_root: Path | None = None,
    frame_sample_count: int | None = None,
    frame_thumb_size: str | None = None,
    frame_full_size: str | None = None,
    max_upload_size_mb: int | None = None,
) -> None:
    if uploads_dir is not None:
        _config["uploads_dir"] = uploads_dir
    if processing_root is not None:
        _config["processing_root"] = processing_root
    if frame_sample_count is not None:
        _config["frame_sample_count"] = frame_sample_count
    if frame_thumb_size is not None:
        _config["frame_thumb_size"] = frame_thumb_size
    if frame_full_size is not None:
        _config["frame_full_size"] = frame_full_size
    if max_upload_size_mb is not None:
        _config["max_upload_size_mb"] = max_upload_size_mb


def _cfg(key: str, env: str, default: Any) -> Any:
    return _config.get(key, os.getenv(env, str(default)) if isinstance(default, str) else int(os.getenv(env, str(default))))


def _frame_sample_count() -> int:
    return int(_cfg("frame_sample_count", "FRAME_SAMPLE_COUNT", 20))


def _frame_thumb_size() -> str:
    return str(_cfg("frame_thumb_size", "FRAME_THUMB_SIZE", "160x90"))


def _frame_full_size() -> str:
    return str(_cfg("frame_full_size", "FRAME_FULL_SIZE", "854x480"))


def _max_upload_mb() -> int:
    return int(_cfg("max_upload_size_mb", "MAX_UPLOAD_SIZE_MB", 500))


def _uploads_dir() -> Path:
    return Path(_config.get("uploads_dir", os.getenv("UPLOADS_DIR", "/tmp/skating-analyzer/uploads")))


def _processing_root() -> Path:
    return Path(_config.get("processing_root", os.getenv("PROCESSING_ROOT", "/tmp/skating-analyzer")))


def _frame_dims() -> tuple[str, str]:
    w, h = _frame_full_size().lower().split("x", 1)
    return w, h


def _size_tuple(v: str) -> tuple[str, str]:
    w, h = v.lower().split("x", 1)
    return w, h


# ── Path helpers ───────────────────────────────────────────────────────

def build_upload_paths(analysis_id: str, suffix: str) -> tuple[Path, Path]:
    upload_dir = _uploads_dir() / analysis_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = upload_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / f"source{suffix}", frames_dir


def build_processing_frames_dir(analysis_id: str) -> tuple[Path, Path]:
    d = _processing_root() / analysis_id
    fd = d / "frames"
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    fd.mkdir(parents=True, exist_ok=True)
    return d, fd


def get_processing_frames_dir(analysis_id: str) -> Path:
    return _processing_root() / analysis_id / "frames"


def cleanup_processing_dir(analysis_id: str) -> None:
    shutil.rmtree(_processing_root() / analysis_id, ignore_errors=True)


def persist_frames(frame_paths: Sequence[Path], target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for p in frame_paths:
        t = target_dir / p.name
        shutil.copy2(p, t)
        out.append(t)
    return out


# ── Upload ─────────────────────────────────────────────────────────────

async def save_upload_file(upload_file: Any, target_path: Path) -> Path:
    suffix = Path(getattr(upload_file, "filename", "") or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("仅支持 mp4、mov、avi 格式的视频。")
    max_bytes = _max_upload_mb() * 1024 * 1024
    declared = getattr(upload_file, "size", None)
    if isinstance(declared, int) and declared > max_bytes:
        raise ValueError(f"文件超过 {_max_upload_mb()}MB 限制。")
    written = 0
    try:
        async with aiofiles.open(target_path, "wb") as out:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                if written + len(chunk) > max_bytes:
                    raise ValueError(f"文件超过 {_max_upload_mb()}MB 限制。")
                await out.write(chunk)
                written += len(chunk)
    except OSError as exc:
        raise ValueError(f"文件写入失败：{exc.strerror or '存储空间不足。'}") from exc
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await upload_file.close()
    return target_path


# ── FFmpeg helpers ─────────────────────────────────────────────────────

async def _run_ffmpeg(args: list[str]) -> None:
    last = "未知错误"
    for attempt in range(1, 3):
        proc = await asyncio.create_subprocess_exec("ffmpeg", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        msg = stderr.decode("utf-8", errors="ignore").strip()
        if proc.returncode == 0:
            return
        last = msg or last
        if attempt < 2 and any(f in last.lower() for f in FFMPEG_RETRYABLE_ERRORS):
            await asyncio.sleep(0.3)
            continue
        break
    raise RuntimeError(f"FFmpeg 处理失败：{last}")


async def extract_frames(video_path: Path, frames_dir: Path) -> list[Path]:
    w, h = _frame_dims()
    pat = str(frames_dir / "frame_%04d.jpg")
    vf = f"fps={FRAME_RATE},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    await _run_ffmpeg(["-y", "-i", str(video_path), "-t", str(MAX_SECONDS), "-vf", vf, "-pix_fmt", "yuvj420p", pat])
    frames = sorted(frames_dir.glob("frame_*.jpg"))
    if not frames:
        raise RuntimeError("视频抽帧结果为空，请检查上传文件是否损坏。")
    return frames


def detect_video_fps(video_path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video_path)], capture_output=True, text=True, check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return 30.0
        data = json.loads(r.stdout)
        for s in data.get("streams", []):
            if s.get("codec_type") != "video":
                continue
            rate = str(s.get("r_frame_rate") or "30/1")
            if "/" in rate:
                n, d = rate.split("/", 1)
                dv = float(d)
                return float(n) / dv if dv else 30.0
            return float(rate)
    except Exception:
        pass
    return 30.0


# ── Motion scoring ─────────────────────────────────────────────────────

def _motion_scores_from_thumbs(thumbs: Sequence[Path]) -> list[float]:
    if not thumbs:
        return []
    try:
        import cv2
    except Exception:
        return [0.0 for _ in thumbs]
    scores = [0.0]
    prev = cv2.imread(str(thumbs[0]), cv2.IMREAD_GRAYSCALE)
    if prev is None:
        return [0.0 for _ in thumbs]
    for t in thumbs[1:]:
        cur = cv2.imread(str(t), cv2.IMREAD_GRAYSCALE)
        if cur is None:
            scores.append(0.0)
            continue
        diff = cv2.absdiff(prev, cur)
        scores.append(min(float(diff.mean()) / 64.0, 1.0))
        prev = cur
    return scores


def _select_motion_weighted_indices(scores: Sequence[float], count: int) -> list[int]:
    total = len(scores)
    if total <= count:
        return list(range(total))
    seg_n = min(10, total)
    base = [1] * seg_n
    rem = max(count - seg_n, 0)
    ranges: list[tuple[int, int]] = []
    weights: list[float] = []
    for s in range(seg_n):
        st = round(s * total / seg_n)
        en = round((s + 1) * total / seg_n)
        if en <= st:
            en = min(st + 1, total)
        ranges.append((st, en))
        weights.append(sum(scores[st:en]) + 0.001)
    tw = sum(weights)
    extra = [0] * seg_n
    if rem > 0 and tw > 0:
        raw = [(w / tw) * rem for w in weights]
        extra = [int(v) for v in raw]
        left = rem - sum(extra)
        for i in sorted(range(seg_n), key=lambda j: raw[j] - extra[j], reverse=True)[:left]:
            extra[i] += 1
    sel: set[int] = set()
    for si, (st, en) in enumerate(ranges):
        q = min(base[si] + extra[si], en - st)
        idx = list(range(st, en))
        idx.sort(key=lambda j: scores[j], reverse=True)
        sel.update(idx[:q])
    if len(sel) < count:
        fb = [round((i / (count - 1)) * (total - 1)) for i in range(count)]
        sel.update(fb)
    return sorted(sel)[:count]


# ── Action window detection ────────────────────────────────────────────

def _fallback_profile_window(action_type: str, profile: str | None) -> tuple[float, float]:
    ws = PROFILE_WINDOW_SIZES.get(profile or "", ACTION_WINDOW_SIZES.get(action_type))
    if ws is None:
        return 0.0, float(MAX_SECONDS)
    return 0.0, min(float(MAX_SECONDS), ws + 2.0)


def _pick_window(scores: Sequence[float], action_type: str, profile: str | None) -> tuple[int, int]:
    ws = PROFILE_WINDOW_SIZES.get(profile or "", ACTION_WINDOW_SIZES.get(action_type))
    if ws is None:
        return 0, len(scores)
    wf = max(1, int(ws * ACTION_WINDOW_DETECTION_FPS))
    mx = max(1, len(scores) - wf + 1)
    if profile == "spiral":
        bi, bs = 0, float("-inf")
        for i in range(mx):
            w = scores[i:i + wf]
            if not w:
                continue
            sc = -(max(w) - min(w)) - sum(w) / len(w)
            if sc > bs:
                bs, bi = sc, i
        return bi, bi + wf
    bi, bs = 0, float("-inf")
    for i in range(mx):
        w = scores[i:i + wf]
        if not w:
            continue
        sc = (sum(w) - abs(w[0] - w[-1])) if profile == "spin" else sum(w)
        if sc > bs:
            bs, bi = sc, i
    return bi, bi + wf


async def detect_action_window(video_path: Path, action_type: str, source_fps: float, analysis_profile: str | None = None) -> tuple[float, float]:
    del source_fps
    ws = ACTION_WINDOW_SIZES.get(action_type)
    if ws is None:
        return 0.0, float(MAX_SECONDS)
    td = video_path.parent / f"{video_path.stem}_action_thumbs"
    try:
        if td.exists():
            shutil.rmtree(td)
        td.mkdir(parents=True, exist_ok=True)
        pat = str(td / "thumb_%05d.jpg")
        await _run_ffmpeg(["-y", "-i", str(video_path), "-vf", f"fps={ACTION_WINDOW_DETECTION_FPS},scale=160:90", pat])
        thumbs = sorted(td.glob("thumb_*.jpg"))
        scores = _motion_scores_from_thumbs(thumbs)
    except Exception:
        return _fallback_profile_window(action_type, analysis_profile)
    finally:
        if td.exists():
            shutil.rmtree(td, ignore_errors=True)
    if len(scores) <= 1:
        return _fallback_profile_window(action_type, analysis_profile)
    sf, ef = _pick_window(scores, action_type, analysis_profile)
    sel_ws = PROFILE_WINDOW_SIZES.get(analysis_profile or "", ws)
    if sel_ws is None:
        return 0.0, float(MAX_SECONDS)
    start = max(0.0, sf / ACTION_WINDOW_DETECTION_FPS - 1.0)
    end = max(start + 1.0, ef / ACTION_WINDOW_DETECTION_FPS + 1.0)
    end = min(end, start + sel_ws + 2.0)
    return (start, end) if end > start else _fallback_profile_window(action_type, analysis_profile)


# ── Frame sampling ─────────────────────────────────────────────────────

def sample_frame_paths(frame_paths: Sequence[Path], max_frames: int | None = None) -> list[Path]:
    mf = max_frames or _frame_sample_count()
    if len(frame_paths) <= mf:
        return list(frame_paths)
    last = len(frame_paths) - 1
    idx = [round((i / (mf - 1)) * last) for i in range(mf)]
    return [frame_paths[i] for i in idx]


async def _extract_thumbs_in_window(vp: Path, td: Path, s: float, e: float) -> list[Path]:
    w, h = _size_tuple(_frame_thumb_size())
    td.mkdir(parents=True, exist_ok=True)
    pat = str(td / "thumb_%05d.jpg")
    vf = f"fps={FRAME_RATE},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    await _run_ffmpeg(["-y", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", str(vp), "-vf", vf, "-pix_fmt", "yuvj420p", pat])
    return sorted(td.glob("thumb_*.jpg"))


async def _extract_thumbs(vp: Path, td: Path) -> list[Path]:
    w, h = _size_tuple(_frame_thumb_size())
    td.mkdir(parents=True, exist_ok=True)
    pat = str(td / "thumb_%05d.jpg")
    vf = f"fps={FRAME_RATE},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    await _run_ffmpeg(["-y", "-i", str(vp), "-vf", vf, "-pix_fmt", "yuvj420p", pat])
    return sorted(td.glob("thumb_*.jpg"))


async def _extract_full_frame(vp: Path, ts: float, tp: Path) -> None:
    w, h = _frame_dims()
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    await _run_ffmpeg(["-y", "-ss", f"{ts:.3f}", "-i", str(vp), "-frames:v", "1", "-vf", vf, "-pix_fmt", "yuvj420p", str(tp)])


async def extract_motion_sampled_frames(
    video_path: Path, frames_dir: Path, action_type: str, analysis_profile: str | None = None,
) -> tuple[list[Path], dict[str, object], VideoSamplingMetadata]:
    mf = _frame_sample_count()
    for f in frames_dir.glob("frame_*.jpg"):
        f.unlink(missing_ok=True)
    td = frames_dir.parent / "thumbs"
    if td.exists():
        shutil.rmtree(td)

    fps = detect_video_fps(video_path)
    slow = fps >= SLOW_MOTION_THRESHOLD_FPS
    ss, es = await detect_action_window(video_path, action_type, fps, analysis_profile)
    meta = VideoSamplingMetadata(action_window_start=round(ss, 3), action_window_end=round(es, 3), source_fps=round(fps, 3), is_slow_motion=slow)

    try:
        thumbs = await _extract_thumbs_in_window(video_path, td, ss, es)
    except Exception:
        if td.exists():
            shutil.rmtree(td, ignore_errors=True)
        ss, es = _fallback_profile_window(action_type, analysis_profile)
        meta = VideoSamplingMetadata(action_window_start=round(ss, 3), action_window_end=round(es, 3), source_fps=round(fps, 3), is_slow_motion=slow)
        thumbs = await _extract_thumbs(video_path, td)
    if not thumbs:
        raise RuntimeError("视频缩略图抽取结果为空。")

    scores = _motion_scores_from_thumbs(thumbs)
    sel = _select_motion_weighted_indices(scores, mf)
    paths: list[Path] = []
    records: list[dict[str, object]] = []
    try:
        for oi, ti in enumerate(sel, 1):
            ts = ss + ti / FRAME_RATE
            tp = frames_dir / f"frame_{oi:04d}.jpg"
            await _extract_full_frame(video_path, ts, tp)
            paths.append(tp)
            records.append({"frame_id": tp.stem, "source_thumb_index": ti, "timestamp": round(ts, 3), "motion_score": round(scores[ti] if ti < len(scores) else 0.0, 4)})
    except Exception:
        for f in frames_dir.glob("frame_*.jpg"):
            f.unlink(missing_ok=True)
        paths = sample_frame_paths(await extract_frames(video_path, frames_dir), mf)
        records = [{"frame_id": p.stem, "source_thumb_index": i, "timestamp": round(i / FRAME_RATE, 3), "motion_score": None} for i, p in enumerate(paths)]

    payload = {
        "frame_rate": FRAME_RATE, "thumb_size": _frame_thumb_size(), "full_size": _frame_full_size(),
        "window_start": round(ss, 3), "window_end": round(es, 3), "analysis_profile_hint": analysis_profile,
        "source_fps": round(fps, 3), "is_slow_motion": slow, "total_thumb_frames": len(thumbs),
        "sample_count": len(paths), "selected": records, "scores": [round(s, 4) for s in scores],
    }
    return paths, payload, meta


async def encode_frames(frame_paths: Sequence[Path]) -> list[FramePayload]:
    payloads: list[FramePayload] = []
    for p in frame_paths:
        async with aiofiles.open(p, "rb") as f:
            binary = await f.read()
        payloads.append(FramePayload(frame_id=p.stem, data_url=f"data:image/jpeg;base64,{base64.b64encode(binary).decode()}"))
    return payloads
