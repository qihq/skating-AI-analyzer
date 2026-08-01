from __future__ import annotations

import hashlib
import json
import subprocess
import os
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.analysis_v2.timebase import SourceFrameIndex, Timebase, build_source_frame_index


class SourceMediaError(ValueError):
    """Raised when an uploaded private video cannot provide source-time evidence."""


@dataclass(frozen=True)
class SourceFrame:
    index: int
    pts: float
    duration: float | None
    status: str = "available"


def source_frame_reference_at(path: Path, index: int):
    """Return the canonical decode-order frame reference for V2 callers."""
    timeline = source_frame_index(path)
    try:
        return timeline.frame_at_index(index)
    except Exception as exc:  # noqa: BLE001
        raise SourceMediaError("Requested source frame is unavailable") from exc


def source_frame_reference_at_pts(path: Path, pts: float):
    """Resolve a requested PTS to one canonical source frame."""
    timeline = source_frame_index(path)
    try:
        return timeline.frame_at_pts(pts)
    except Exception as exc:  # noqa: BLE001
        raise SourceMediaError("Requested source PTS is unavailable") from exc


def extract_source_frame_bytes(path: Path, index: int) -> bytes:
    """Extract one original decode-order frame for local refinement."""
    if index < 0:
        raise SourceMediaError("Source frame index must be non-negative")
    # Decode the original source and select by decode order; no rendition or
    # sampled-frame count participates in this identity lookup.
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{index})", "-vsync", "0", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
        capture_output=True,
        check=False,
    )
    payload = getattr(result, "stdout", b"")
    if result.returncode != 0 or not payload:
        raise SourceMediaError("Unable to extract requested source frame")
    return bytes(payload)


@dataclass(frozen=True)
class SourceMetadata:
    source_sha256: str
    duration_pts: float
    width: int
    height: int
    timebase_numerator: int
    timebase_denominator: int
    is_vfr: bool
    source_frame_count: int | None
    average_fps: float | None
    nominal_fps: float | None
    display_rotation_degrees: int
    timestamp_status: str = "exact"
    pts_discontinuities: tuple[int, ...] = ()
    decode_gap_count: int = 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_source(path: Path) -> SourceMetadata:
    payload = _ffprobe(path, "-show_streams", "-show_format")
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), None)
    if not isinstance(stream, dict):
        raise SourceMediaError("Video stream is missing")
    format_payload = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    timebase = _timebase(str(stream.get("time_base") or ""))
    if timebase is None:
        raise SourceMediaError("Video timebase is missing")
    duration = _number(stream.get("duration")) or _number(format_payload.get("duration"))
    if duration is None or duration <= 0:
        raise SourceMediaError("Video duration is unavailable")
    average = _frame_rate(str(stream.get("avg_frame_rate") or ""))
    nominal = _frame_rate(str(stream.get("r_frame_rate") or ""))
    rotation = _rotation(stream)
    index = source_frame_index(path, metadata=None, _payload=payload)
    return SourceMetadata(
        source_sha256=sha256_file(path),
        duration_pts=duration,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        timebase_numerator=timebase[0],
        timebase_denominator=timebase[1],
        is_vfr=bool(average and nominal and abs(average - nominal) > 0.01),
        source_frame_count=_integer(stream.get("nb_frames")),
        average_fps=average,
        nominal_fps=nominal,
        display_rotation_degrees=rotation,
        timestamp_status="exact" if index.exact else "unavailable",
        pts_discontinuities=index.pts_discontinuities,
        decode_gap_count=len(index.decode_gaps),
    )


def source_frame_at(path: Path, index: int) -> SourceFrame:
    if index < 0:
        raise SourceMediaError("Source frame index must be non-negative")
    frames = _source_packet_index(str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size)
    if index >= len(frames):
        raise SourceMediaError("Requested source frame is unavailable")
    pts, duration, status = frames[index]
    if pts is None:
        raise SourceMediaError("Requested source frame has no timestamp")
    return SourceFrame(index=index, pts=pts, duration=duration, status=status)


def source_frame_index(path: Path, *, metadata: SourceMetadata | None = None, _payload: dict[str, Any] | None = None) -> SourceFrameIndex:
    """Build the canonical source-order PTS index; the index is rebuildable from the source video."""
    payload = _payload or _ffprobe(
        path,
        "-show_streams", "-show_format",
    )
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), None)
    if not isinstance(stream, dict):
        raise SourceMediaError("Video stream is missing")
    format_payload = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    timebase_value = _timebase(str(stream.get("time_base") or ""))
    if timebase_value is None:
        raise SourceMediaError("Video timebase is missing")
    stream_payload = _ffprobe(
        path,
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time,pkt_duration_time,width,height",
    )
    records = [
        {
            "pts_time": item.get("best_effort_timestamp_time"),
            "duration_time": item.get("pkt_duration_time"),
            "width": item.get("width") or stream.get("width"),
            "height": item.get("height") or stream.get("height"),
        }
        for item in stream_payload.get("frames", [])
        if isinstance(item, dict)
    ]
    duration = _number(stream.get("duration")) or _number(format_payload.get("duration"))
    return build_source_frame_index(
        records,
        source_video_hash=(metadata.source_sha256 if metadata else sha256_file(path)),
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        duration_sec=duration,
        timebase=Timebase(
            numerator=timebase_value[0],
            denominator=timebase_value[1],
            average_fps=_frame_rate(str(stream.get("avg_frame_rate") or "")),
            nominal_fps=_frame_rate(str(stream.get("r_frame_rate") or "")),
            is_vfr=bool(
                _frame_rate(str(stream.get("avg_frame_rate") or ""))
                and _frame_rate(str(stream.get("r_frame_rate") or ""))
                and abs(_frame_rate(str(stream.get("avg_frame_rate") or "")) - _frame_rate(str(stream.get("r_frame_rate") or ""))) > 0.01
            ),
        ),
        rotation_degrees=_rotation(stream),
        timestamp_status="exact",
    )


@lru_cache(maxsize=64)
def _source_packet_index(path: str, _mtime_ns: int, _size: int) -> tuple[tuple[float | None, float | None, str], ...]:
    payload = _ffprobe(
        Path(path),
        "-select_streams", "v:0",
        "-show_packets",
        "-show_entries", "packet=pts_time,duration_time",
    )
    packets: list[tuple[float | None, float | None, str]] = []
    for packet in payload.get("packets", []):
        if not isinstance(packet, dict):
            continue
        pts = _number(packet.get("pts_time", packet.get("best_effort_timestamp_time")))
        duration = _number(packet.get("duration_time", packet.get("pkt_duration_time")))
        packets.append((pts, duration, "available" if pts is not None else "timestamp_unavailable"))
    if not packets:
        for frame in payload.get("frames", []):
            if not isinstance(frame, dict):
                continue
            pts = _number(frame.get("best_effort_timestamp_time", frame.get("pts_time")))
            duration = _number(frame.get("pkt_duration_time", frame.get("duration_time")))
            packets.append((pts, duration, "available" if pts is not None else "timestamp_unavailable"))
    if not packets:
        raise SourceMediaError("Video frame PTS index is unavailable")
    # Historical frame lookup is timestamp-ordered for compatibility. The V2
    # source-frame index uses ffprobe frame order and retains discontinuities.
    return tuple(sorted(packets, key=lambda item: (float("inf") if item[0] is None else item[0])))


def create_browser_playback(source: Path, target: Path) -> None:
    """Create a seek-friendly H.264 copy while retaining the original evidence file."""
    temporary = target.with_suffix(".tmp.mp4")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", str(temporary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SourceMediaError(result.stderr.strip() or "ffmpeg browser playback conversion failed")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _ffprobe(path: Path, *arguments: str) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", *arguments, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SourceMediaError(result.stderr.strip() or "ffprobe failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SourceMediaError("ffprobe returned invalid metadata") from exc
    return payload if isinstance(payload, dict) else {}


def _timebase(value: str) -> tuple[int, int] | None:
    try:
        numerator, denominator = value.split("/", 1)
        top, bottom = int(numerator), int(denominator)
        if top <= 0 or bottom <= 0:
            return None
        return top, bottom
    except (ValueError, ZeroDivisionError):
        return None


def _frame_rate(value: str) -> float | None:
    ratio = _timebase(value)
    return ratio[0] / ratio[1] if ratio else None


def _number(value: object) -> float | None:
    try:
        number = float(str(value))
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    try:
        number = int(str(value))
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _rotation(stream: dict[str, Any]) -> int:
    candidates = [stream.get("tags", {}).get("rotate") if isinstance(stream.get("tags"), dict) else None]
    candidates.extend(item.get("rotation") for item in stream.get("side_data_list", []) if isinstance(item, dict))
    for candidate in candidates:
        try:
            rotation = int(round(float(str(candidate)))) % 360
            if rotation in {0, 90, 180, 270}:
                return rotation
        except (TypeError, ValueError):
            continue
    return 0
