"""生物力学上下文构建。

职责: 将 bio_data 重排为逐帧测量字典，用于 Path B prompt 注入。
输入: bio_data、frame_stems。
输出: 逐帧测量字典。
"""
from __future__ import annotations

import math
from typing import Any


def _safe(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def build_frame_bio_context(
    bio_data: dict[str, Any] | None,
    frame_stems: list[str],
) -> dict[str, dict[str, float]]:
    """
    Rearrange biomechanics output into per-frame measurement dicts keyed by stem.
    frame_stems must be passed in sampling order, where frame_idx is 1-based.

    Example output:
      {"frame_0001": {"left_knee_angle": 145.2, "trunk_tilt_deg": 8.4}}
    """
    if not isinstance(bio_data, dict):
        return {}

    by_idx_knee = {
        int(item.get("frame_idx", 0)): item
        for item in bio_data.get("knee_angles", [])
        if isinstance(item, dict)
    }
    by_idx_trunk = {
        int(item.get("frame_idx", 0)): item
        for item in bio_data.get("trunk_tilts", [])
        if isinstance(item, dict)
    }
    by_idx_arm = {
        int(item.get("frame_idx", 0)): item
        for item in bio_data.get("arm_symmetry", [])
        if isinstance(item, dict)
    }

    out: dict[str, dict[str, float]] = {}
    for i, stem in enumerate(frame_stems, start=1):
        knee = by_idx_knee.get(i, {})
        trunk = by_idx_trunk.get(i, {})
        arm = by_idx_arm.get(i, {})

        entry: dict[str, float] = {}
        l = _safe(knee.get("left"))
        r = _safe(knee.get("right"))
        if l is not None:
            entry["left_knee_angle"] = l
        if r is not None:
            entry["right_knee_angle"] = r
        t = _safe(trunk.get("tilt_degrees"))
        if t is not None:
            entry["trunk_tilt_deg"] = t
        s = _safe(arm.get("symmetry"))
        if s is not None:
            entry["arm_symmetry"] = s
        if entry:
            out[stem] = entry
    return out


def extract_key_frame_stems(bio_data: dict[str, Any] | None) -> set[str]:
    """Extract stems from bio_data['key_frames']; only meaningful for jump profiles."""
    if not isinstance(bio_data, dict):
        return set()
    kf = bio_data.get("key_frames")
    if not isinstance(kf, dict):
        return set()
    return {str(v) for v in kf.values() if isinstance(v, str) and v}


def summarize_jump_metrics(bio_data: dict[str, Any] | None) -> str:
    """
    Summarize jump_metrics as a single ASCII grounding line.
    Returns an empty string for non-jump data or when jump_metrics_status != 'ok'.
    """
    if not isinstance(bio_data, dict):
        return ""
    if bio_data.get("jump_metrics_status") != "ok":
        return ""
    jm = bio_data.get("jump_metrics")
    if not isinstance(jm, dict):
        return ""

    parts = []
    if (v := _safe(jm.get("air_time_seconds"))) is not None:
        parts.append(f"AirTime={v:.2f}s")
    if (v := _safe(jm.get("estimated_height_cm"))) is not None:
        parts.append(f"Height={v:.1f}cm")
    if (v := _safe(jm.get("takeoff_speed_mps"))) is not None:
        parts.append(f"VTakeoff={v:.2f}m/s")
    if (v := _safe(jm.get("rotation_rps"))) is not None:
        parts.append(f"Rot={v:.2f}rps")
    return " | ".join(parts)
