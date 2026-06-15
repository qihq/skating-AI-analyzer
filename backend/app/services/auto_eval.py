"""Automatic proxy evaluation metrics for analysis outputs.

The service does not require human labels. It checks internal consistency:
key-frame candidate order, profile phase transitions, high-confidence conflicts,
and a deterministic key-frame signature for repeat-run comparison.
"""

from __future__ import annotations

import json
from typing import Any


AUTO_EVAL_VERSION = "v1"
HIGH_CONFIDENCE_THRESHOLD = 0.75

PHASE_ALIASES = {
    "prepare": "prepare",
    "preparation": "prepare",
    "准备": "prepare",
    "起跳准备": "prepare",
    "takeoff": "takeoff",
    "t": "takeoff",
    "起跳": "takeoff",
    "air": "air",
    "apex": "air",
    "flight": "air",
    "airborne": "air",
    "腾空": "air",
    "空中": "air",
    "landing": "landing",
    "l": "landing",
    "落冰": "landing",
    "落地": "landing",
    "exit": "exit",
    "glideout": "exit",
    "滑出": "exit",
    "不可分析": "unknown",
    "unknown": "unknown",
}

VALID_PHASE_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "jump": {
        "prepare": {"prepare", "takeoff", "unknown"},
        "takeoff": {"takeoff", "air", "unknown"},
        "air": {"air", "landing", "unknown"},
        "landing": {"landing", "exit", "unknown"},
        "exit": {"exit", "unknown"},
        "unknown": {"prepare", "takeoff", "air", "landing", "exit", "unknown"},
    },
    "spin": {
        "spin_entry": {"spin_entry", "spin", "unknown"},
        "spin": {"spin", "spin_exit", "unknown"},
        "spin_exit": {"spin_exit", "unknown"},
        "unknown": {"spin_entry", "spin", "spin_exit", "unknown"},
    },
    "spiral": {
        "prepare": {"prepare", "step", "unknown"},
        "step": {"step", "unknown"},
        "unknown": {"prepare", "step", "unknown"},
    },
    "step": {
        "step": {"step", "unknown"},
        "unknown": {"step", "unknown"},
    },
}


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


def _frame_number(frame_id: Any) -> int | None:
    digits = "".join(char for char in str(frame_id or "") if char.isdigit())
    return int(digits) if digits else None


def _normalize_phase(phase: Any, analysis_profile: str) -> str:
    raw = str(phase or "").strip()
    if not raw:
        return "unknown"
    compact = raw.lower().replace(" ", "").replace("_", "").replace("-", "")
    if compact in PHASE_ALIASES:
        return PHASE_ALIASES[compact]
    if analysis_profile == "spin":
        if raw in {"旋转入"} or compact in {"spinentry", "entry"}:
            return "spin_entry"
        if raw in {"旋转中"} or compact in {"spin", "spinning"}:
            return "spin"
        if raw in {"旋转出"} or compact in {"spinexit", "exit"}:
            return "spin_exit"
    if analysis_profile in {"step", "spiral"} and (raw in {"步法"} or compact in {"step", "steps"}):
        return "step"
    return compact


def _candidate_frame_number(candidates: dict[str, Any], label: str) -> int | None:
    candidate = candidates.get(label)
    if not isinstance(candidate, dict):
        return None
    return _frame_number(candidate.get("frame_id"))


def _candidate_confidence(candidates: dict[str, Any], label: str) -> float | None:
    candidate = candidates.get(label)
    if not isinstance(candidate, dict):
        return None
    confidence = _to_float(candidate.get("confidence"))
    return _clamp(confidence) if confidence is not None else None


def _final_key_frame_records(bio_data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(bio_data, dict):
        return None
    key_frames = bio_data.get("key_frames") if isinstance(bio_data.get("key_frames"), dict) else {}
    timestamps = (
        bio_data.get("key_frame_timestamps")
        if isinstance(bio_data.get("key_frame_timestamps"), dict)
        else {}
    )
    confidence = _to_float(bio_data.get("key_frame_confidence"))
    records: dict[str, Any] = {}
    for label in ("T", "A", "L"):
        frame_id = key_frames.get(label)
        timestamp = _to_float(timestamps.get(label)) if isinstance(timestamps, dict) else None
        if not frame_id and timestamp is None:
            continue
        record: dict[str, Any] = {}
        if frame_id:
            record["frame_id"] = str(frame_id)
        if timestamp is not None:
            record["timestamp"] = timestamp
        if confidence is not None:
            record["confidence"] = confidence
        records[label] = record
    return records or None


def _ordered_key_frame_values(
    records: dict[str, Any] | None,
    *,
    prefer_timestamps: bool,
) -> tuple[float | int, float | int, float | int] | None:
    if not isinstance(records, dict):
        return None
    timestamps: list[float | None] = [
        _to_float(record.get("timestamp")) if isinstance((record := records.get(label)), dict) else None
        for label in ("T", "A", "L")
    ]
    frame_numbers = [_candidate_frame_number(records, label) for label in ("T", "A", "L")]
    if prefer_timestamps and all(value is not None for value in timestamps):
        return timestamps[0], timestamps[1], timestamps[2]  # type: ignore[return-value]
    if all(value is not None for value in frame_numbers):
        return frame_numbers[0], frame_numbers[1], frame_numbers[2]  # type: ignore[return-value]
    if all(value is not None for value in timestamps):
        return timestamps[0], timestamps[1], timestamps[2]  # type: ignore[return-value]
    return None


def _key_frame_order_valid(
    final_key_frames: dict[str, Any] | None,
    candidates: dict[str, Any] | None,
    flags: list[str],
) -> bool | None:
    values = _ordered_key_frame_values(final_key_frames, prefer_timestamps=True)
    if values is None:
        values = _ordered_key_frame_values(candidates, prefer_timestamps=False)
    if values is None:
        if isinstance(final_key_frames, dict) or isinstance(candidates, dict):
            flags.append("auto_eval_incomplete_key_frame_candidates")
            return None
        flags.append("auto_eval_missing_key_frame_candidates")
        return None
    return bool(values[0] < values[1] < values[2])


def _key_frame_signature_records(
    final_key_frames: dict[str, Any] | None,
    candidates: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    if _ordered_key_frame_values(final_key_frames, prefer_timestamps=True) is not None:
        return final_key_frames, "bio_key_frames"
    if isinstance(candidates, dict):
        return candidates, "key_frame_candidates"
    if isinstance(final_key_frames, dict):
        return final_key_frames, "bio_key_frames"
    return None, "missing"


def _key_frame_signature(records: dict[str, Any] | None) -> str:
    if not isinstance(records, dict):
        return "missing"
    parts: list[str] = []
    for label in ("T", "A", "L"):
        candidate = records.get(label)
        if not isinstance(candidate, dict) or not candidate.get("frame_id"):
            parts.append(f"{label}:missing")
            continue
        confidence = _candidate_confidence(records, label)
        confidence_text = "na" if confidence is None else f"{confidence:.2f}"
        parts.append(f"{label}:{candidate.get('frame_id')}@{confidence_text}")
    return "|".join(parts)


def _phase_sequence(vision_structured: dict[str, Any] | None, analysis_profile: str) -> list[dict[str, Any]]:
    frames = vision_structured.get("frame_analysis", []) if isinstance(vision_structured, dict) else []
    if not isinstance(frames, list):
        return []
    sequence: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            continue
        confidence = _to_float(frame.get("confidence"))
        sequence.append(
            {
                "index": index,
                "frame_id": str(frame.get("frame_id") or ""),
                "phase": _normalize_phase(frame.get("phase"), analysis_profile),
                "raw_phase": str(frame.get("phase") or ""),
                "confidence": round(_clamp(confidence if confidence is not None else 0.0), 3),
            }
        )
    return sequence


def _phase_sequence_valid(sequence: list[dict[str, Any]], analysis_profile: str, flags: list[str]) -> tuple[bool | None, list[dict[str, Any]]]:
    if not sequence:
        flags.append("auto_eval_missing_phase_sequence")
        return None, []

    transitions = VALID_PHASE_TRANSITIONS.get(analysis_profile, {})
    if not transitions:
        flags.append("auto_eval_unknown_profile")
        return None, []

    violations: list[dict[str, Any]] = []
    previous = "unknown"
    for item in sequence:
        current = str(item.get("phase") or "unknown")
        allowed = transitions.get(previous)
        if allowed and current not in allowed:
            violations.append(
                {
                    "from_phase": previous,
                    "to_phase": current,
                    "frame_id": item.get("frame_id"),
                    "index": item.get("index"),
                    "confidence": item.get("confidence"),
                }
            )
        previous = current
    return len(violations) == 0, violations


def _expected_phase_for_label(label: str) -> str:
    return {"T": "takeoff", "A": "air", "L": "landing"}[label]


def _nearby_frames(sequence: list[dict[str, Any]], frame_number: int, radius: int = 1) -> list[dict[str, Any]]:
    exact = []
    nearby = []
    for item in sequence:
        number = _frame_number(item.get("frame_id"))
        if number == frame_number:
            exact.append(item)
        elif number is not None and abs(number - frame_number) <= radius:
            nearby.append(item)
    return exact or nearby


def _high_confidence_conflicts(
    candidates: dict[str, Any] | None,
    phase_sequence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(candidates, dict) or not phase_sequence:
        return []

    conflicts: list[dict[str, Any]] = []
    for label in ("T", "A", "L"):
        frame_number = _candidate_frame_number(candidates, label)
        candidate_confidence = _candidate_confidence(candidates, label)
        if frame_number is None or candidate_confidence is None or candidate_confidence < HIGH_CONFIDENCE_THRESHOLD:
            continue
        expected = _expected_phase_for_label(label)
        nearby = _nearby_frames(phase_sequence, frame_number)
        if not any(_frame_number(item.get("frame_id")) == frame_number for item in nearby):
            expected_nearby = [
                item
                for item in nearby
                if str(item.get("phase") or "unknown") == expected
                and (_to_float(item.get("confidence")) or 0.0) >= HIGH_CONFIDENCE_THRESHOLD
            ]
            if expected_nearby:
                continue
        for item in nearby:
            vision_confidence = _to_float(item.get("confidence")) or 0.0
            phase = str(item.get("phase") or "unknown")
            if vision_confidence >= HIGH_CONFIDENCE_THRESHOLD and phase not in {expected, "unknown"}:
                conflicts.append(
                    {
                        "label": label,
                        "frame_id": item.get("frame_id"),
                        "candidate_confidence": round(candidate_confidence, 3),
                        "vision_phase": phase,
                        "expected_phase": expected,
                        "vision_confidence": round(_clamp(vision_confidence), 3),
                    }
                )
    return conflicts


def _collect_quality_flags(
    bio_data: dict[str, Any] | None,
    vision_structured: dict[str, Any] | None,
    frame_motion_scores: dict[str, Any] | None,
    auto_flags: list[str],
) -> list[str]:
    flags: list[str] = []
    for source in (bio_data, vision_structured, frame_motion_scores):
        if isinstance(source, dict) and isinstance(source.get("quality_flags"), list):
            flags.extend(str(flag) for flag in source.get("quality_flags", []) if flag)

    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if isinstance(candidates, dict) and isinstance(candidates.get("quality_flags"), list):
        flags.extend(str(flag) for flag in candidates.get("quality_flags", []) if flag)
    flags.extend(auto_flags)
    return list(dict.fromkeys(flags))


def _json_safe(payload: dict[str, Any]) -> dict[str, Any]:
    json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return payload


def build_auto_eval_payload(
    bio_data: dict[str, Any] | None,
    vision_structured: dict[str, Any] | None,
    frame_motion_scores: dict[str, Any] | None,
    analysis_profile: str,
) -> dict[str, Any]:
    """Build automatic proxy metrics for an analysis result.

    Args:
        bio_data: Biomechanics payload, ideally containing key_frame_candidates.
        vision_structured: Vision output with frame_analysis phases.
        frame_motion_scores: Sampling/motion payload. Quality flags are folded in.
        analysis_profile: Normalized profile such as jump, spin, step, or spiral.

    Returns:
        JSON-serializable auto-eval payload with stable keys.
    """
    profile = str(analysis_profile or "jump").strip().lower() or "jump"
    auto_flags: list[str] = []
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    final_key_frames = _final_key_frame_records(bio_data)
    signature_records, signature_source = _key_frame_signature_records(final_key_frames, candidates)

    key_frame_order_valid = _key_frame_order_valid(final_key_frames, candidates, auto_flags)
    phase_sequence = _phase_sequence(vision_structured, profile)
    phase_sequence_valid, phase_violations = _phase_sequence_valid(phase_sequence, profile, auto_flags)
    conflicts = _high_confidence_conflicts(signature_records, phase_sequence)
    if conflicts:
        auto_flags.append("auto_eval_high_confidence_conflict")
    if key_frame_order_valid is False:
        auto_flags.append("auto_eval_key_frame_order_invalid")
    if phase_sequence_valid is False:
        auto_flags.append("auto_eval_phase_sequence_invalid")

    payload = {
        "auto_eval_version": AUTO_EVAL_VERSION,
        "analysis_profile": profile,
        "key_frame_order_valid": key_frame_order_valid,
        "phase_sequence_valid": phase_sequence_valid,
        "high_confidence_conflicts": conflicts,
        "high_confidence_conflict_rate": round(len(conflicts) / max(1, len(phase_sequence)), 3),
        "data_quality_flags": _collect_quality_flags(bio_data, vision_structured, frame_motion_scores, auto_flags),
        "key_frame_signature": _key_frame_signature(signature_records),
        "key_frame_signature_source": signature_source,
        "candidate_key_frame_signature": _key_frame_signature(candidates),
        "phase_sequence": [
            {
                "frame_id": item["frame_id"],
                "phase": item["phase"],
                "confidence": item["confidence"],
            }
            for item in phase_sequence
        ],
        "phase_transition_violations": phase_violations,
    }
    return _json_safe(payload)
