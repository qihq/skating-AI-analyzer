from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.analysis_v2.evaluation.source_media import SourceMediaError, probe_source, source_frame_index


MEDIA_SCHEMA_VERSION = "analysis_media.v1"
MEDIA_QUALITIES = ("original", "1080p", "720p", "480p")
RENDITION_KEYFRAME_SECONDS = int(os.getenv("MEDIA_RENDITION_KEYFRAME_SECONDS", "2"))


def manifest_path_for_video(video_path: Path) -> Path:
    return video_path.parent / "media-manifest.json"


def _probe(video_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(video_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    payload = json.loads(result.stdout)
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), None)
    if not isinstance(stream, dict):
        raise RuntimeError("video stream is missing")
    format_payload = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec": str(stream.get("codec_name") or "unknown"),
        "duration_sec": float(stream.get("duration") or format_payload.get("duration") or 0),
        "bitrate": int(format_payload.get("bit_rate") or 0) or None,
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _source(quality: str, status: str, *, metadata: dict[str, Any], url: str | None, filename: str | None = None, error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "quality": quality,
        "status": status,
        "width": metadata["width"],
        "height": metadata["height"],
        "url": url,
        "filename": filename,
    }
    if error:
        payload["error"] = error
    return payload


def create_manifest(video_path: Path, analysis_id: str) -> dict[str, Any]:
    metadata = _probe(video_path)
    sources = [_source("original", "ready", metadata=metadata, url=f"/api/analysis/{analysis_id}/video?quality=original", filename=video_path.name)]
    for quality, height in (("1080p", 1080), ("720p", 720), ("480p", 480)):
        if metadata["height"] > height:
            sources.append(_source(quality, "pending", metadata={**metadata, "height": height}, url=None, filename=f"renditions/{quality}.mp4"))
    source_timeline: dict[str, Any] | None = None
    try:
        source_timeline = source_frame_index(video_path, metadata=probe_source(video_path)).to_timeline()
    except (AttributeError, OSError, SourceMediaError, RuntimeError, ValueError):
        source_timeline = {
            "schema_version": "source-timeline.v1",
            "source_video_hash": "",
            "duration_sec": metadata["duration_sec"],
            "width": metadata["width"],
            "height": metadata["height"],
            "rotation_degrees": 0,
            "timebase": {"numerator": 0, "denominator": 0, "is_vfr": False},
            "timestamp_status": "unavailable",
            "frames": [],
            "decode_gaps": [],
            "pts_discontinuities": [],
            "fingerprint": "unavailable",
        }
    return {"schema_version": MEDIA_SCHEMA_VERSION, "status": "ready", "sources": sources, "source_timeline": source_timeline}


def read_or_create_manifest(video_path: Path, analysis_id: str) -> dict[str, Any]:
    path = manifest_path_for_video(video_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("schema_version") == MEDIA_SCHEMA_VERSION:
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    payload = create_manifest(video_path, analysis_id)
    _atomic_write(path, payload)
    return payload


def resolve_media_source(video_path: Path, analysis_id: str, quality: str) -> Path | None:
    if quality not in MEDIA_QUALITIES:
        return None
    manifest = read_or_create_manifest(video_path, analysis_id)
    source = next((item for item in manifest["sources"] if item.get("quality") == quality and item.get("status") == "ready"), None)
    if not isinstance(source, dict):
        return None
    if quality == "original":
        return video_path
    filename = str(source.get("filename") or "")
    candidate = (video_path.parent / filename).resolve()
    return candidate if video_path.parent.resolve() in candidate.parents and candidate.exists() else None


async def generate_media_renditions(video_path: Path, analysis_id: str) -> dict[str, Any]:
    """Create independent seek-friendly renditions while retaining playable Original."""
    manifest = read_or_create_manifest(video_path, analysis_id)
    for source in manifest["sources"]:
        if source.get("quality") == "original" or source.get("status") == "ready":
            continue
        quality = str(source["quality"])
        height = int(str(quality).removesuffix("p"))
        target = video_path.parent / "renditions" / f"{quality}.mp4"
        source["status"] = "processing"
        manifest["status"] = "processing"
        _atomic_write(manifest_path_for_video(video_path), manifest)
        command = [
            "ffmpeg", "-y", "-i", str(video_path), "-vf", f"scale=-2:{height}:force_original_aspect_ratio=decrease",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-g", str(max(1, RENDITION_KEYFRAME_SECONDS * 30)),
            "-c:a", "aac", "-movflags", "+faststart", str(target),
        ]
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            result = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, check=False)
            if result.returncode != 0 or not target.exists():
                raise RuntimeError(result.stderr[-400:] or "ffmpeg failed")
            probe = await asyncio.to_thread(_probe, target)
            source.update(_source(quality, "ready", metadata=probe, url=f"/api/analysis/{analysis_id}/video?quality={quality}", filename=f"renditions/{quality}.mp4"))
        except Exception as exc:  # noqa: BLE001
            source["status"] = "failed"
            source["error"] = str(exc)[:400]
    manifest["status"] = "ready" if all(item.get("status") in {"ready", "failed"} for item in manifest["sources"]) else "processing"
    _atomic_write(manifest_path_for_video(video_path), manifest)
    return manifest
