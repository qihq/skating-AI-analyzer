from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import statistics
from pathlib import Path
from typing import Any


CORE_KEY_ALIASES = {
    "T": "T",
    "takeoff": "T",
    "T_takeoff_sec": "T",
    "A": "A",
    "air": "A",
    "apex": "A",
    "A_air_sec": "A",
    "L": "L",
    "landing": "L",
    "L_landing_sec": "L",
    "spin_entry": "spin_entry",
    "entry": "spin_entry",
    "spin_main": "spin_main",
    "spin_center": "spin_main",
    "main": "spin_main",
    "center": "spin_main",
    "spin_exit": "spin_exit",
    "exit": "spin_exit",
}

DEFAULT_KEYFRAME_TOLERANCE_SEC = 0.25
DEFAULT_IDENTITY_ACCURACY_FLOOR = 0.80
DEFAULT_IDENTITY_SWITCH_LIMIT = 0
DEFAULT_FAILURE_KEYFRAME_MAX_ERROR_SEC = 0.35
FIXED_FAILURE_TAGS = {
    "identity_switch",
    "target_lost",
    "takeoff_early",
    "takeoff_late",
    "apex_drift",
    "landing_glideout",
    "multi_person_motion_pollution",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _bbox_iou(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 0.0
    ax1 = _number(a.get("x"))
    ay1 = _number(a.get("y"))
    aw = _number(a.get("width", a.get("w")))
    ah = _number(a.get("height", a.get("h")))
    bx1 = _number(b.get("x"))
    by1 = _number(b.get("y"))
    bw = _number(b.get("width", b.get("w")))
    bh = _number(b.get("height", b.get("h")))
    if None in {ax1, ay1, aw, ah, bx1, by1, bw, bh}:
        return 0.0
    ax2 = ax1 + aw  # type: ignore[operator]
    ay2 = ay1 + ah  # type: ignore[operator]
    bx2 = bx1 + bw  # type: ignore[operator]
    by2 = by1 + bh  # type: ignore[operator]
    ix1 = max(ax1, bx1)  # type: ignore[arg-type]
    iy1 = max(ay1, by1)  # type: ignore[arg-type]
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(0.0, aw) * max(0.0, ah)  # type: ignore[arg-type]
    area_b = max(0.0, bw) * max(0.0, bh)  # type: ignore[arg-type]
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _normalize_keyframes(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, float] = {}
    selected = value.get("selected")
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            raw_key = item.get("key") or item.get("phase_code") or item.get("key_moment")
            key = CORE_KEY_ALIASES.get(str(raw_key))
            timestamp = _number(item.get("timestamp", item.get("timestamp_sec")))
            if key and timestamp is not None:
                output[key] = timestamp
    for raw_key, item in value.items():
        key = CORE_KEY_ALIASES.get(str(raw_key))
        if key is None:
            continue
        timestamp = _number(item)
        if timestamp is None and isinstance(item, dict):
            timestamp = _number(item.get("timestamp", item.get("timestamp_sec")))
        if timestamp is not None:
            output[key] = timestamp
    key_moments = value.get("key_moments")
    if isinstance(key_moments, dict):
        for raw_key, item in key_moments.items():
            key = CORE_KEY_ALIASES.get(str(raw_key))
            timestamp = _number(item)
            if key and timestamp is not None:
                output[key] = timestamp
    return output


def _normalize_bboxes(value: Any) -> dict[int, dict[str, Any]]:
    if isinstance(value, dict):
        output: dict[int, dict[str, Any]] = {}
        for raw_index, bbox in value.items():
            try:
                frame_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if isinstance(bbox, dict):
                output[frame_index] = bbox
        return output
    if isinstance(value, list):
        output = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            frame_index = item.get("frame_index")
            if frame_index is None:
                frame_index = item.get("index")
            try:
                index = int(frame_index)
            except (TypeError, ValueError):
                continue
            bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else item
            output[index] = bbox
        return output
    return {}


def _keyframe_metrics(gt: dict[str, float], pred: dict[str, float], tolerance_sec: float) -> dict[str, Any]:
    errors: dict[str, float] = {}
    deltas: dict[str, float] = {}
    missing: list[str] = []
    false_positive: list[str] = []
    for key, gt_ts in gt.items():
        pred_ts = pred.get(key)
        if pred_ts is None:
            missing.append(key)
            continue
        delta = pred_ts - gt_ts
        errors[key] = abs(delta)
        deltas[key] = delta
    for key in pred:
        if key not in gt:
            false_positive.append(key)
    values = list(errors.values())
    return {
        "errors_sec": {key: round(value, 4) for key, value in errors.items()},
        "delta_sec": {key: round(value, 4) for key, value in deltas.items()},
        "mean_error_sec": round(statistics.fmean(values), 4) if values else None,
        "median_error_sec": round(statistics.median(values), 4) if values else None,
        "max_error_sec": round(max(values), 4) if values else None,
        "hits": sum(1 for value in values if value <= tolerance_sec),
        "misses": len(missing),
        "false_positives": len(false_positive),
        "missing_keys": missing,
        "false_positive_keys": false_positive,
    }


def _identity_metrics(
    gt: dict[int, dict[str, Any]],
    pred: dict[int, dict[str, Any]],
    *,
    iou_threshold: float,
    switch_frames: int,
) -> dict[str, Any]:
    shared = sorted(set(gt) & set(pred))
    if not shared:
        return {
            "evaluated_frames": 0,
            "identity_accuracy": None,
            "identity_switches": 0,
            "lost_ratio": None,
            "mean_iou": None,
        }
    ious = [_bbox_iou(gt[index], pred[index]) for index in shared]
    correct = [iou >= iou_threshold for iou in ious]
    switches = 0
    run = 0
    for ok in correct:
        if ok:
            if run >= switch_frames:
                switches += 1
            run = 0
        else:
            run += 1
    if run >= switch_frames:
        switches += 1
    return {
        "evaluated_frames": len(shared),
        "identity_accuracy": round(sum(1 for ok in correct if ok) / len(correct), 4),
        "identity_switches": switches,
        "lost_ratio": round(sum(1 for ok in correct if not ok) / len(correct), 4),
        "mean_iou": round(statistics.fmean(ious), 4),
    }


def _sample_failure_reasons(
    *,
    keyframes: dict[str, Any],
    identity: dict[str, Any],
    expected_review_flags: Any,
    prediction_quality_flags: Any,
    keyframe_max_error_sec: float,
    identity_accuracy_floor: float,
    identity_switch_limit: int,
) -> list[str]:
    reasons: list[str] = []
    max_error = _number(keyframes.get("max_error_sec"))
    if keyframes.get("misses", 0) > 0:
        reasons.append("missing_keyframes")
    if keyframes.get("false_positives", 0) > 0:
        reasons.append("unexpected_keyframes")
    if max_error is not None and max_error > keyframe_max_error_sec:
        reasons.append("keyframe_error_high")
    identity_accuracy = _number(identity.get("identity_accuracy"))
    if identity.get("identity_switches", 0) > identity_switch_limit:
        reasons.append("identity_switch")
    if identity_accuracy is not None and identity_accuracy < identity_accuracy_floor:
        reasons.append("identity_accuracy_low")
    expected_flags = {str(flag) for flag in expected_review_flags if isinstance(flag, str)} if isinstance(expected_review_flags, list) else set()
    quality_flags = {str(flag) for flag in prediction_quality_flags if isinstance(flag, str)} if isinstance(prediction_quality_flags, list) else set()
    missing_expected_flags = sorted(expected_flags - quality_flags)
    if missing_expected_flags:
        reasons.append("missing_expected_review_flags")
    return reasons


def _sample_failure_tags(
    *,
    keyframes: dict[str, Any],
    identity: dict[str, Any],
    prediction_quality_flags: Any,
    stratum: str,
    gt_bbox_count: int,
    keyframe_max_error_sec: float,
    identity_accuracy_floor: float,
    identity_switch_limit: int,
) -> list[str]:
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag in FIXED_FAILURE_TAGS and tag not in tags:
            tags.append(tag)

    if identity.get("identity_switches", 0) > identity_switch_limit:
        add("identity_switch")
    identity_accuracy = _number(identity.get("identity_accuracy"))
    lost_ratio = _number(identity.get("lost_ratio"))
    if gt_bbox_count > 0 and identity.get("evaluated_frames", 0) == 0:
        add("target_lost")
    elif identity_accuracy is not None and identity_accuracy < identity_accuracy_floor and (lost_ratio or 0.0) >= 0.5:
        add("target_lost")

    deltas = keyframes.get("delta_sec")
    if isinstance(deltas, dict):
        for key, raw_delta in deltas.items():
            delta = _number(raw_delta)
            if delta is None or abs(delta) <= keyframe_max_error_sec:
                continue
            normalized = CORE_KEY_ALIASES.get(str(key), str(key))
            if normalized == "T":
                add("takeoff_late" if delta > 0 else "takeoff_early")
            elif normalized == "A":
                add("apex_drift")
            elif normalized == "L":
                add("landing_glideout")

    quality_flags = {str(flag) for flag in prediction_quality_flags if isinstance(flag, str)} if isinstance(prediction_quality_flags, list) else set()
    if stratum == "multi_skater" and any(tag in tags for tag in ("identity_switch", "target_lost")):
        add("multi_person_motion_pollution")
    if any("multi_person_motion_pollution" in flag or "motion_pollution" in flag for flag in quality_flags):
        add("multi_person_motion_pollution")
    return tags


def _aggregate_keyframe_errors(samples: list[dict[str, Any]]) -> list[float]:
    return [
        value
        for sample in samples
        for value in sample["keyframes"]["errors_sec"].values()
    ]


def _summary_for_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    keyframe_errors = _aggregate_keyframe_errors(samples)
    identity_accuracies = [
        sample["identity"]["identity_accuracy"]
        for sample in samples
        if sample["identity"]["identity_accuracy"] is not None
    ]
    return {
        "sample_count": len(samples),
        "keyframe_mean_error_sec": round(statistics.fmean(keyframe_errors), 4) if keyframe_errors else None,
        "keyframe_median_error_sec": round(statistics.median(keyframe_errors), 4) if keyframe_errors else None,
        "keyframe_max_error_sec": round(max(keyframe_errors), 4) if keyframe_errors else None,
        "identity_accuracy": round(statistics.fmean(identity_accuracies), 4) if identity_accuracies else None,
        "identity_switches": sum(sample["identity"]["identity_switches"] for sample in samples),
        "failure_count": sum(1 for sample in samples if sample.get("failure_reasons")),
    }


def _stratum_summary(sample_reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in sample_reports:
        grouped[str(sample.get("stratum") or "unspecified")].append(sample)
    return {key: _summary_for_samples(values) for key, values in sorted(grouped.items())}


def _top_quality_flags(sample_reports: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for sample in sample_reports:
        flags = sample.get("prediction_quality_flags")
        if not isinstance(flags, list):
            continue
        counter.update(str(flag) for flag in flags if str(flag).strip())
    return [{"flag": flag, "count": count} for flag, count in counter.most_common(limit)]


def _sample_prediction(sample: dict[str, Any], manifest_dir: Path) -> dict[str, Any]:
    prediction_path = sample.get("prediction_path") or sample.get("analysis_output_path")
    if not prediction_path:
        return {}
    path = Path(str(prediction_path))
    if not path.is_absolute():
        path = manifest_dir / path
    return _load_json(path) if path.exists() else {}


def evaluate_manifest(
    manifest_path: Path,
    *,
    iou_threshold: float,
    switch_frames: int,
    keyframe_max_error_sec: float = DEFAULT_FAILURE_KEYFRAME_MAX_ERROR_SEC,
    identity_accuracy_floor: float = DEFAULT_IDENTITY_ACCURACY_FLOOR,
    identity_switch_limit: int = DEFAULT_IDENTITY_SWITCH_LIMIT,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    samples = manifest.get("samples") if isinstance(manifest, dict) else manifest
    if not isinstance(samples, list):
        raise ValueError("manifest must be a list or an object with a samples list")

    sample_reports: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        prediction = _sample_prediction(sample, manifest_path.parent)
        gt_keyframes = _normalize_keyframes(sample.get("keyframes"))
        pred_keyframes = _normalize_keyframes(prediction.get("keyframes") or prediction.get("resolved_keyframes") or prediction)
        gt_bboxes = _normalize_bboxes(sample.get("target_bboxes"))
        pred_bboxes = _normalize_bboxes(prediction.get("target_bboxes") or prediction.get("bbox_per_frame"))
        tolerance = (
            _number(sample.get("tolerance_sec"))
            or _number(sample.get("keyframe_tolerance_sec"))
            or min(DEFAULT_KEYFRAME_TOLERANCE_SEC, 2.0 / max(_number(sample.get("fps")) or 15.0, 1.0))
        )
        keyframe_report = _keyframe_metrics(gt_keyframes, pred_keyframes, tolerance)
        identity_report = _identity_metrics(gt_bboxes, pred_bboxes, iou_threshold=iou_threshold, switch_frames=switch_frames)
        expected_review_flags = sample.get("expected_review_flags", [])
        prediction_quality_flags = prediction.get("quality_flags", [])
        stratum = str(sample.get("stratum") or sample.get("scenario") or "unspecified")
        failure_reasons = _sample_failure_reasons(
            keyframes=keyframe_report,
            identity=identity_report,
            expected_review_flags=expected_review_flags,
            prediction_quality_flags=prediction_quality_flags,
            keyframe_max_error_sec=keyframe_max_error_sec,
            identity_accuracy_floor=identity_accuracy_floor,
            identity_switch_limit=identity_switch_limit,
        )
        failure_tags = _sample_failure_tags(
            keyframes=keyframe_report,
            identity=identity_report,
            prediction_quality_flags=prediction_quality_flags,
            stratum=stratum,
            gt_bbox_count=len(gt_bboxes),
            keyframe_max_error_sec=keyframe_max_error_sec,
            identity_accuracy_floor=identity_accuracy_floor,
            identity_switch_limit=identity_switch_limit,
        )
        sample_reports.append(
            {
                "sample_id": str(sample.get("id") or sample.get("video_path") or len(sample_reports) + 1),
                "video_path": sample.get("video_path"),
                "skater_id": sample.get("skater_id"),
                "action_type": sample.get("action_type"),
                "analysis_profile": sample.get("analysis_profile"),
                "stratum": stratum,
                "keyframes": keyframe_report,
                "identity": identity_report,
                "expected_review_flags": expected_review_flags,
                "prediction_quality_flags": prediction_quality_flags,
                "failure_reasons": failure_reasons,
                "failure_tags": failure_tags,
                "passes": not failure_reasons,
            }
        )

    failures = [
        {
            "sample_id": sample["sample_id"],
            "video_path": sample.get("video_path"),
            "stratum": sample.get("stratum"),
            "failure_reasons": sample.get("failure_reasons", []),
            "failure_tags": sample.get("failure_tags", []),
            "keyframe_max_error_sec": sample["keyframes"].get("max_error_sec"),
            "identity_accuracy": sample["identity"].get("identity_accuracy"),
            "identity_switches": sample["identity"].get("identity_switches"),
            "prediction_quality_flags": sample.get("prediction_quality_flags", []),
        }
        for sample in sample_reports
        if sample.get("failure_reasons")
    ]
    return {
        "summary": _summary_for_samples(sample_reports),
        "stratum_summary": _stratum_summary(sample_reports),
        "failures": failures,
        "top_quality_flags": _top_quality_flags(sample_reports),
        "samples": sample_reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate skating keyframes and target identity against golden labels.")
    parser.add_argument("manifest", type=Path, help="Golden manifest JSON.")
    parser.add_argument("--output", type=Path, default=Path("baseline.json"), help="Output JSON path.")
    parser.add_argument("--iou-threshold", type=float, default=0.3)
    parser.add_argument("--switch-frames", type=int, default=3)
    parser.add_argument("--keyframe-max-error-sec", type=float, default=DEFAULT_FAILURE_KEYFRAME_MAX_ERROR_SEC)
    parser.add_argument("--identity-accuracy-floor", type=float, default=DEFAULT_IDENTITY_ACCURACY_FLOOR)
    parser.add_argument("--identity-switch-limit", type=int, default=DEFAULT_IDENTITY_SWITCH_LIMIT)
    args = parser.parse_args()

    report = evaluate_manifest(
        args.manifest,
        iou_threshold=args.iou_threshold,
        switch_frames=args.switch_frames,
        keyframe_max_error_sec=args.keyframe_max_error_sec,
        identity_accuracy_floor=args.identity_accuracy_floor,
        identity_switch_limit=args.identity_switch_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
