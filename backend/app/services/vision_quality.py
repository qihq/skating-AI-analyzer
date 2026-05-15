from __future__ import annotations

from typing import Any


VALID_DATA_QUALITY_HINTS = {"good", "partial", "poor"}
UNCERTAIN_BLADE_EDGES = {"", "不可判断", "不适用", "unknown", "unavailable", "none", "n/a"}
SPECIFIC_BLADE_EDGES = {"外刃", "内刃", "平刃", "outside", "inside", "flat", "outside_edge", "inside_edge", "flat_edge"}
HIGH_CONFIDENCE_THRESHOLD = 0.75
LOW_QUALITY_NOTICE = "视频质量有限，建议保守解读。"


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return None
    return numeric


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _frame_confidence(frame: dict[str, Any]) -> float:
    confidence = _to_float(frame.get("confidence"))
    if confidence is not None:
        return _clamp(confidence)
    phase_confidence = _to_float(frame.get("phase_confidence"))
    return _clamp(phase_confidence) if phase_confidence is not None else 0.0


def _blade_edge(frame: dict[str, Any]) -> str:
    observations = frame.get("observations")
    if not isinstance(observations, dict):
        return ""
    return str(observations.get("blade_edge", "")).strip()


def _frame_completeness(frame: Any) -> float:
    if not isinstance(frame, dict):
        return 0.0
    checks = [
        bool(str(frame.get("frame_id", "")).strip()),
        bool(str(frame.get("phase", "")).strip()),
        _to_float(frame.get("confidence")) is not None,
        isinstance(frame.get("observations"), dict),
    ]
    return sum(1 for item in checks if item) / len(checks)


def apply_low_quality_policy(
    vision_payload: dict[str, Any] | None,
    *,
    data_quality_hint: str | None = None,
    camera_view: str | None = None,
    pose_visibility: float | None = None,
) -> dict[str, Any]:
    """
    Attach conservative diagnostics for poor or partial video inputs.

    The function never mutates the input payload and intentionally does not
    rewrite frame observations or confidence values. Downstream consumers can
    use the flags for weighting and display without losing usable evidence.
    """
    payload = dict(vision_payload or {})
    quality_hint = str(data_quality_hint or payload.get("data_quality_hint", "")).strip().lower()
    camera_view_value = str(camera_view or payload.get("camera_view", "")).strip().lower()
    pose_visibility_value = _to_float(pose_visibility if pose_visibility is not None else payload.get("pose_visibility"))

    is_low_quality = quality_hint in {"poor", "partial"} or (
        pose_visibility_value is not None and pose_visibility_value < 0.65
    )
    if not is_low_quality:
        return payload

    payload["quality_flags"] = _merge_quality_flags(
        payload.get("quality_flags"),
        [
            "vision_low_quality_conservative_policy",
            "vision_low_quality_diagnostic_only",
        ],
    )
    payload["conservative_policy"] = {
        "applied": True,
        "data_quality_hint": quality_hint or None,
        "camera_view": camera_view_value or None,
        "pose_visibility": round(pose_visibility_value, 3) if pose_visibility_value is not None else None,
        "notice": LOW_QUALITY_NOTICE,
        "mode": "diagnostic_only",
    }
    if quality_hint == "poor":
        payload["quality_flags"] = _merge_quality_flags(
            payload.get("quality_flags"),
            ["vision_low_quality_poor"],
        )
    elif quality_hint == "partial":
        payload["quality_flags"] = _merge_quality_flags(
            payload.get("quality_flags"),
            ["vision_low_quality_partial"],
        )
    return payload


def _merge_quality_flags(existing: Any, additions: list[str]) -> list[str]:
    flags = [str(flag) for flag in existing if isinstance(existing, list) and flag] if isinstance(existing, list) else []
    for flag in additions:
        if flag not in flags:
            flags.append(flag)
    return flags


def evaluate_vision_payload_quality(vision_payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate structural quality and risky visual judgments in a vision JSON payload."""
    warnings: list[str] = []
    if not isinstance(vision_payload, dict):
        return {
            "json_validity_factor": 0.0,
            "warnings": ["vision_payload_not_object"],
            "schema_completeness": 0.0,
        }

    frames = vision_payload.get("frame_analysis")
    frame_list = frames if isinstance(frames, list) else []
    data_quality = str(vision_payload.get("data_quality_hint", "")).strip().lower()

    top_level_checks = [
        isinstance(frames, list) and bool(frames),
        data_quality in VALID_DATA_QUALITY_HINTS,
        isinstance(vision_payload.get("action_phase_summary"), dict),
        bool(str(vision_payload.get("overall_raw_text", "")).strip()),
    ]
    frame_score = (
        sum(_frame_completeness(frame) for frame in frame_list) / len(frame_list)
        if frame_list
        else 0.0
    )
    schema_completeness = round((sum(1 for item in top_level_checks if item) + frame_score) / (len(top_level_checks) + 1), 3)

    if not isinstance(frames, list) or not frames:
        warnings.append("vision_quality_missing_frame_analysis")
    if data_quality not in VALID_DATA_QUALITY_HINTS:
        warnings.append("vision_quality_invalid_or_missing_data_quality_hint")
    for index, frame in enumerate(frame_list):
        if not isinstance(frame, dict):
            warnings.append(f"vision_quality_invalid_frame_{index}")
            continue
        if not str(frame.get("phase", "")).strip():
            warnings.append(f"vision_quality_missing_phase_{frame.get('frame_id') or index}")
        if _to_float(frame.get("confidence")) is None:
            warnings.append(f"vision_quality_missing_confidence_{frame.get('frame_id') or index}")
        blade_edge = _blade_edge(frame)
        if data_quality == "poor" and blade_edge not in UNCERTAIN_BLADE_EDGES and _frame_confidence(frame) >= HIGH_CONFIDENCE_THRESHOLD:
            warnings.append("vision_quality_poor_quality_high_confidence_blade_edge")
        elif blade_edge and blade_edge not in UNCERTAIN_BLADE_EDGES and blade_edge not in SPECIFIC_BLADE_EDGES:
            warnings.append(f"vision_quality_unrecognized_blade_edge_{frame.get('frame_id') or index}")

    json_validity_factor = schema_completeness
    if not isinstance(frames, list) or not frames:
        json_validity_factor = min(json_validity_factor, 0.3)
    if data_quality == "poor" and "vision_quality_poor_quality_high_confidence_blade_edge" in warnings:
        json_validity_factor = min(json_validity_factor, 0.65)
    if any(warning.startswith("vision_quality_missing_") for warning in warnings):
        json_validity_factor = min(json_validity_factor, 0.8)

    return {
        "json_validity_factor": round(_clamp(json_validity_factor), 3),
        "warnings": _dedupe(warnings),
        "schema_completeness": schema_completeness,
    }


def build_low_quality_policy_summary(vision_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = vision_payload if isinstance(vision_payload, dict) else {}
    hint = str(payload.get("data_quality_hint", "")).strip().lower()
    return {
        "applied": hint in {"poor", "partial"},
        "data_quality_hint": hint or None,
        "camera_view": str(payload.get("camera_view", "")).strip().lower() or None,
        "pose_visibility": _to_float(payload.get("pose_visibility")),
        "notice": LOW_QUALITY_NOTICE if hint in {"poor", "partial"} else "",
    }
