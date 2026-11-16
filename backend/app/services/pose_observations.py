"""Preserve saved observation holes and time/person/binding discontinuities."""
from __future__ import annotations

from fractions import Fraction
import math
from typing import Any

from app.services.pose_quality import finite_number
from app.services.smoothing import MAX_CONTINUOUS_GAP_SECONDS
from app.services.tracking_states import EXCLUDED_TRACKING_STATES, EXCLUDED_TRACKER_STATES


def verified_source_clock(temporal: dict) -> dict[str, float] | None:
    """Validate the binding without confusing source PTS and playback axes.

    Negative source coordinates are valid when subtracting the stream origin
    produces nonnegative playback. Historical bindings without an origin keep
    their zero-origin interpretation; unbound sampling never establishes PTS.
    """
    if temporal.get("time_source") != "bound_source_pts":
        return None
    binding = temporal.get("binding") or {}
    if not isinstance(binding, dict):
        return None
    pts = binding.get("source_pts")
    if type(pts) is not int:
        return None
    try:
        base = Fraction(str(binding.get("source_time_base")))
        if base <= 0 or not math.isfinite(float(base)) or float(base) <= 0:
            return None
        source = float(pts * base)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    playback = finite_number(temporal.get("playback_timestamp"))
    origin = finite_number(binding.get("source_origin_sec", 0.))
    if (not math.isfinite(source) or origin is None or playback is None
            or playback < 0 or abs(source - origin - playback) > .002):
        return None
    return {"source_timestamp": source, "playback_timestamp": playback,
            "source_origin_sec": origin}


def verified_source_time(temporal: dict) -> float | None:
    """Return PTS × time_base in the source coordinate system."""
    clock = verified_source_clock(temporal)
    return clock["source_timestamp"] if clock is not None else None


def verified_playback_time(temporal: dict) -> float | None:
    """Return validated playback time, the input to slow-motion scaling."""
    clock = verified_source_clock(temporal)
    return clock["playback_timestamp"] if clock is not None else None


def observation_time_error(frame: dict) -> str | None:
    """Validate explicit time without upgrading historical sampling to PTS."""
    temporal = frame.get("temporal") or {}
    if temporal.get("time_valid") is False:
        return "explicit_time_invalid"
    if temporal.get("time_source") == "bound_source_pts":
        playback = verified_playback_time(temporal)
        scale = finite_number(temporal.get("slow_motion_scale"))
        stamp = finite_number(temporal.get("analysis_timestamp"))
        if playback is None:
            return "bound_source_time_invalid"
        if scale is None or scale <= 0 or stamp is None or stamp < 0 or abs(playback / scale - stamp) > .002:
            return "bound_analysis_time_or_scale_invalid"
    return None


def _frame_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    name = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, _ = name.rpartition(".")
    return stem if dot and stem else name


def frame_usable(frame: Any) -> bool:
    if not isinstance(frame, dict):
        return False
    state = str(frame.get("tracking_state") or "").strip().lower()
    tracker_state = str(frame.get("tracker_state") or "").strip().lower()
    if state in EXCLUDED_TRACKING_STATES or tracker_state in EXCLUDED_TRACKER_STATES:
        return False
    if (frame.get("input_binding_valid") is False or
            frame.get("image_binding_valid") is False or
            frame.get("identity_status") == "identity_unconfirmed"):
        return False
    temporal = frame.get("temporal")
    return not (isinstance(temporal, dict) and temporal.get("segment_id") is None)


def _selected_timeline(selected: Any) -> tuple[dict[str, float], set[str]]:
    timeline: dict[str, float] = {}
    duplicates: set[str] = set()
    seen: set[str] = set()
    if not isinstance(selected, list):
        return timeline, duplicates
    for record in selected:
        if not isinstance(record, dict):
            continue
        frame_key = _frame_key(record.get("frame_id"))
        if frame_key is None:
            continue
        if frame_key in seen:
            duplicates.add(frame_key)
            continue
        seen.add(frame_key)
        timestamp = finite_number(record.get("timestamp"))
        if timestamp is not None and timestamp >= 0:
            timeline[frame_key] = timestamp
    return timeline, duplicates


def observation_slots(
    pose_data: dict[str, Any] | None,
    motion_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any] | None]:
    """Keep holes and explicit same-person/time/binding boundaries.

    Legacy records without any time contract retain their original adjacency;
    explicit timestamps are never replaced by array-index time.
    """
    frames = pose_data.get("frames", []) if isinstance(pose_data, dict) else []
    if not isinstance(frames, list):
        return []
    metadata = motion_metadata if isinstance(motion_metadata, dict) else {}
    selected = "selected" in metadata
    timeline, duplicates = _selected_timeline(metadata.get("selected"))
    fps = finite_number(metadata.get("frame_rate"))
    max_gap = (2. / fps if fps is not None and fps > 0 else None) if selected else MAX_CONTINUOUS_GAP_SECONDS
    explicit_time = selected or any(isinstance(f, dict) and any(k in f for k in ("timestamp", "analysis_timestamp", "temporal")) for f in frames)
    observations: list[dict[str, Any] | None] = []
    previous = None
    for frame in frames:
        if not frame_usable(frame) or observation_time_error(frame):
            observations.append(None)
            previous = None
            continue
        temporal = frame.get("temporal") or {}
        has_frame_time = any(k in frame for k in ("timestamp", "analysis_timestamp")) or "analysis_timestamp" in temporal
        timestamp = finite_number(temporal.get("analysis_timestamp", frame.get("analysis_timestamp", frame.get("timestamp"))))
        selected_time = None
        if selected:
            key = _frame_key(frame.get("frame") or frame.get("frame_id"))
            selected_time = timeline.get(key) if key not in duplicates else None
            # Selected times use the playback timeline. Prefer the persisted
            # analysis time for elapsed-time checks (e.g. slow-motion scaling).
            if selected_time is None:
                observations.append(None)
                previous = None
                continue
            timestamp = timestamp if has_frame_time else selected_time
        if explicit_time and (timestamp is None or timestamp < 0):
            observations.append(None)
            previous = None
            continue
        identity = (frame.get("identity_id"), frame.get("tracker_id"), temporal.get("slow_motion_scale"))
        segment = temporal.get("segment_id")
        if previous is not None:
            prev_time, prev_identity, prev_segment, prev_selected = previous
            if (identity != prev_identity or segment != prev_segment
                    or temporal.get("continuous") is False
                    or (timestamp is not None and prev_time is not None and
                        (timestamp <= prev_time or (max_gap is not None and timestamp - prev_time > max_gap + .002)))
                    or (selected_time is not None and prev_selected is not None and
                        (selected_time <= prev_selected or (max_gap is not None and selected_time - prev_selected > max_gap + .002)))):
                observations.append(None)
        observations.append(frame)
        previous = (timestamp, identity, segment, selected_time)
    return observations

