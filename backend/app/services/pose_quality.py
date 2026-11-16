"""Point-level analysis validity, shared by routing and geometry consumers.

Absence of quality means a legacy observation, not an explicit rejection.
Coordinates and quality on the stored/display point are never changed here.
"""
from __future__ import annotations

import math
from typing import Any


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def point_rejection_reason(point: Any, min_visibility: float | None = None) -> str | None:
    if not isinstance(point, dict):
        return "missing_point"
    quality = point.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    limb = quality.get("limb_consistency")
    if isinstance(limb, dict) and limb.get("status") == "uncertain":
        return "limb_uncertain"
    if quality.get("analysis_usable") is False:
        return "analysis_unusable"
    if point.get("interpolated") or quality.get("source") == "display_interpolation":
        return "display_interpolation"
    if any(finite_number(point.get(axis)) is None for axis in ("x", "y")) or finite_number(point.get("z", 0.)) is None:
        return "invalid_coordinates"
    if min_visibility is not None:
        visibility = finite_number(point.get("visibility"))
        if visibility is None or visibility < min_visibility:
            return "insufficient_visibility"
    return None


def analysis_point(keypoints: Any, index: int, min_visibility: float | None = None) -> dict[str, Any] | None:
    if not isinstance(keypoints, list):
        return None
    matches = [p for p in keypoints if isinstance(p, dict) and p.get("id") == index]
    if len(matches) > 1:
        return None
    raw = matches[0] if matches else None
    # Only truly positional legacy records may use the array slot.
    if raw is None and 0 <= index < len(keypoints):
        candidate = keypoints[index]
        if isinstance(candidate, dict) and "id" not in candidate:
            raw = candidate
    return raw if point_rejection_reason(raw, min_visibility) is None else None
