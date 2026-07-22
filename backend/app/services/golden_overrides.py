from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


class GoldenOverrideValidationError(ValueError):
    pass


_KEYFRAME_PHASES = {
    "T": "takeoff",
    "A": "apex",
    "L": "landing",
    "spin_entry": "spin_entry",
    "spin_main": "spin_main",
    "spin_exit": "spin_exit",
}
_ORDERED_KEYFRAME_GROUPS = (
    ("T", "A", "L"),
    ("spin_entry", "spin_main", "spin_exit"),
)
_REQUIRED_KEYFRAMES = {
    "jump": {"T", "A", "L"},
    "spin": {"spin_entry", "spin_main", "spin_exit"},
    "spiral": {"spiral_hold"},
    "step": {"step_sequence"},
}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _normalized_bbox(value: Any) -> dict[str, float] | None:
    raw = _mapping(value)
    fields = {
        "x": _number(raw.get("x")),
        "y": _number(raw.get("y")),
        "width": _number(raw.get("width", raw.get("w"))),
        "height": _number(raw.get("height", raw.get("h"))),
    }
    if any(item is None for item in fields.values()):
        return None
    return {key: round(float(item), 4) for key, item in fields.items() if item is not None}


def _frame_lookup(run: Any) -> dict[str, tuple[str, dict[str, Any]]]:
    result = _mapping(_value(run, "result_json"))
    output: dict[str, tuple[str, dict[str, Any]]] = {}
    for key, source in (
        ("sampled_frames", "sampled"),
        ("semantic_frames", "semantic"),
        ("partial_semantic_frames", "partial"),
    ):
        frames = result.get(key)
        if not isinstance(frames, list):
            continue
        for index, frame in enumerate(frames):
            item = _mapping(frame)
            frame_id = str(item.get("frame_id") or item.get("id") or index)
            output[f"{source}:{frame_id}"] = (source, item)
            if source == "sampled":
                output[str(index)] = (source, item)
    return output


def normalize_golden_label(label: Mapping[str, Any], run: Any) -> dict[str, Any]:
    raw = dict(label)
    normalized_keyframes: dict[str, dict[str, Any]] = {}
    for key, value in _mapping(raw.get("keyframes")).items():
        item = _mapping(value)
        timestamp = _number(item.get("timestamp_sec", item.get("timestamp"))) if item else _number(value)
        if timestamp is None:
            continue
        normalized_keyframes[str(key)] = {
            "timestamp_sec": round(timestamp, 3),
            **({"source_frame_id": str(item["source_frame_id"])} if item.get("source_frame_id") else {}),
        }

    anchors: list[dict[str, Any]] = []
    raw_anchors = raw.get("tracking_anchors")
    if isinstance(raw_anchors, list) and raw_anchors:
        for index, value in enumerate(raw_anchors):
            item = _mapping(value)
            bbox = _normalized_bbox(item.get("bbox"))
            timestamp = _number(item.get("timestamp_sec", item.get("timestamp")))
            if bbox is None or timestamp is None:
                continue
            anchors.append(
                {
                    "anchor_id": str(item.get("anchor_id") or f"anchor-{index + 1}"),
                    "timestamp_sec": round(timestamp, 3),
                    "source_frame_id": str(item.get("source_frame_id") or f"timestamp:{timestamp:.3f}"),
                    "bbox": bbox,
                }
            )
    else:
        frame_lookup = _frame_lookup(run)
        for index, (key, value) in enumerate(_mapping(raw.get("target_bboxes")).items()):
            bbox = _normalized_bbox(value)
            source, frame = frame_lookup.get(str(key), ("sampled", {}))
            timestamp = _number(frame.get("timestamp", frame.get("timestamp_sec")))
            if bbox is None or timestamp is None:
                continue
            frame_id = str(frame.get("frame_id") or frame.get("id") or key)
            anchors.append(
                {
                    "anchor_id": f"legacy-{index + 1}",
                    "timestamp_sec": round(timestamp, 3),
                    "source_frame_id": f"{source}:{frame_id}",
                    "bbox": bbox,
                }
            )

    action_window = _mapping(raw.get("action_window"))
    if not action_window:
        start = _number(raw.get("action_window_start_sec"))
        end = _number(raw.get("action_window_end_sec"))
        if start is not None and end is not None:
            action_window = {"start_sec": round(start, 3), "end_sec": round(end, 3)}
    if not action_window:
        result_json = _mapping(_value(run, "result_json"))
        input_window = _mapping(result_json.get("input_window"))
        if input_window.get("input_window_mode") == "manual_window":
            start = _number(input_window.get("input_window_start_sec"))
            end = _number(input_window.get("input_window_end_sec"))
            if start is not None and end is not None:
                action_window = {"start_sec": round(start, 3), "end_sec": round(end, 3)}

    return {
        "schema_version": 1,
        "source_debug_run_id": str(_value(run, "id") or raw.get("id") or ""),
        "source_analysis_id": str(_value(run, "analysis_id") or raw.get("source_analysis_id") or ""),
        "source_label_revision": int(raw.get("revision") or 1),
        "analysis_profile": str(raw.get("analysis_profile") or _value(run, "analysis_profile") or "").strip().lower(),
        "action_window": action_window or None,
        "keyframes": normalized_keyframes,
        "tracking_anchors": sorted(anchors, key=lambda item: item["timestamp_sec"]),
    }


def validate_golden_override(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(payload))
    keyframes = _mapping(result.get("keyframes"))
    profile = str(result.get("analysis_profile") or "").strip().lower()
    required = _REQUIRED_KEYFRAMES.get(profile, set())
    missing = sorted(required - set(keyframes))
    if missing:
        raise GoldenOverrideValidationError(f"Golden label is missing required {profile} keyframes: {', '.join(missing)}.")
    for group in _ORDERED_KEYFRAME_GROUPS:
        values = [
            _number(_mapping(keyframes.get(key)).get("timestamp_sec"))
            for key in group
            if key in keyframes
        ]
        if len(values) > 1 and any(current <= previous for previous, current in zip(values, values[1:])):
            raise GoldenOverrideValidationError(f"Golden keyframes must follow {' < '.join(group)}.")

    anchors = result.get("tracking_anchors")
    if not isinstance(anchors, list):
        raise GoldenOverrideValidationError("Golden tracking_anchors must be a list.")
    seen_times: set[float] = set()
    for anchor in anchors:
        item = _mapping(anchor)
        timestamp = _number(item.get("timestamp_sec"))
        bbox = _normalized_bbox(item.get("bbox"))
        if timestamp is None or timestamp < 0 or bbox is None:
            raise GoldenOverrideValidationError("Each Golden anchor needs a valid timestamp and bbox.")
        if round(timestamp, 3) in seen_times:
            raise GoldenOverrideValidationError("Golden anchors cannot share the same timestamp.")
        seen_times.add(round(timestamp, 3))
        if (
            bbox["width"] < 0.02
            or bbox["height"] < 0.02
            or bbox["x"] < 0
            or bbox["y"] < 0
            or bbox["x"] + bbox["width"] > 1
            or bbox["y"] + bbox["height"] > 1
        ):
            raise GoldenOverrideValidationError("Golden anchor bbox must fit inside the source frame.")

    action_window = result.get("action_window")
    if action_window is not None:
        window = _mapping(action_window)
        start = _number(window.get("start_sec"))
        end = _number(window.get("end_sec"))
        if start is None or end is None or start < 0 or end <= start:
            raise GoldenOverrideValidationError("Golden action window requires start < end.")
        for key, value in keyframes.items():
            timestamp = _number(_mapping(value).get("timestamp_sec"))
            if timestamp is not None and (timestamp < start or timestamp > end):
                raise GoldenOverrideValidationError(f"Golden keyframe {key} falls outside the action window.")
        for anchor in anchors:
            timestamp = float(_mapping(anchor)["timestamp_sec"])
            if timestamp < start or timestamp > end:
                raise GoldenOverrideValidationError("Golden anchor falls outside the action window.")
    return result


def golden_override_hash(payload: Mapping[str, Any]) -> str:
    content = {
        key: value
        for key, value in payload.items()
        if key not in {"source_label_revision", "applied_at", "applied_by", "label_hash"}
    }
    encoded = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def golden_retry_stage(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> str:
    old = dict(previous or {})
    if current.get("action_window") != old.get("action_window") and current.get("action_window") is not None:
        return "extract_frames"
    if current.get("tracking_anchors") != old.get("tracking_anchors") and current.get("tracking_anchors"):
        return "pose"
    return "biomechanics"


def apply_golden_keyframes(
    bio_data: Mapping[str, Any] | None,
    resolved_keyframes: Mapping[str, Any] | None,
    override: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bio = deepcopy(dict(bio_data or {}))
    resolved = deepcopy(dict(resolved_keyframes or {}))
    keyframes = _mapping(_mapping(override).get("keyframes"))
    if not keyframes:
        return bio, resolved

    automatic = deepcopy(resolved)
    selected: list[dict[str, Any]] = []
    timestamps: dict[str, float] = {}
    for key, value in keyframes.items():
        timestamp = _number(_mapping(value).get("timestamp_sec"))
        if timestamp is None:
            continue
        timestamps[key] = round(timestamp, 3)
        selected.append(
            {
                "key": key,
                "phase_code": _KEYFRAME_PHASES.get(key, key),
                "timestamp": round(timestamp, 3),
                "timestamp_sec": round(timestamp, 3),
                "selection_reason": "golden_override",
                "source": "golden_override",
                "confidence": 1.0,
                "source_frame_id": _mapping(value).get("source_frame_id"),
                "frame_id": f"golden_{key}",
            }
        )
    bio["key_frame_timestamps"] = {**_mapping(bio.get("key_frame_timestamps")), **timestamps}
    bio["key_frames"] = {
        **_mapping(bio.get("key_frames")),
        **{key: f"golden_{key}" for key in timestamps},
    }
    bio["golden_keyframe_revision"] = _mapping(override).get("source_label_revision")
    resolved = {
        **resolved,
        "source": "golden_override",
        "confidence": 1.0,
        "selected": selected,
        "automatic_prediction": automatic,
        "golden_label_revision": _mapping(override).get("source_label_revision"),
    }
    return bio, resolved
