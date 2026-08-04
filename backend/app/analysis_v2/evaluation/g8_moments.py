from __future__ import annotations

"""Leakage-safe G8 metric aggregation.

The evaluator consumes predictions already produced without Golden/resolved
semantic labels. It never calls the localizer with label payloads.
"""

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.analysis_v2.contracts import EventMomentSet
from app.analysis_v2.profile_moments import reject_evaluation_leakage


def _wilson(numerator: int, denominator: int) -> list[float] | None:
    if denominator == 0:
        return None
    z = 1.959963984540054
    p = numerator / denominator
    center = (p + z * z / (2 * denominator)) / (1 + z * z / denominator)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * denominator)) / denominator) / (1 + z * z / denominator)
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bootstrap_ci(values: Sequence[float], *, statistic: str, rounds: int = 800) -> list[float] | None:
    if not values:
        return None
    # Deterministic LCG avoids external randomness while preserving a useful
    # small-N diagnostic interval.
    state = 0x12A5B8C3
    samples: list[float] = []
    for _ in range(rounds):
        draw: list[float] = []
        for _ in values:
            state = (1664525 * state + 1013904223) % (2**32)
            draw.append(values[state % len(values)])
        value = _percentile(draw, .5 if statistic == "median" else .95)
        if value is not None:
            samples.append(value)
    return [round(_percentile(samples, .025) or 0, 6), round(_percentile(samples, .975) or 0, 6)]


def evaluate_g8_moments(
    *, labels: Sequence[Mapping[str, Any]], predictions: Mapping[str, EventMomentSet | Mapping[str, Any]],
    candidate_fingerprint: str, dataset_frozen: bool, validation_calibrated: bool,
) -> dict[str, Any]:
    if not candidate_fingerprint:
        raise ValueError("G8 evaluation requires a candidate fingerprint")
    normalized_predictions: dict[str, EventMomentSet] = {}
    for event_id, prediction in predictions.items():
        if isinstance(prediction, Mapping):
            reject_evaluation_leakage(prediction)
        normalized_predictions[event_id] = prediction if isinstance(prediction, EventMomentSet) else EventMomentSet.model_validate(prediction)
    errors: dict[str, list[float]] = defaultdict(list)
    strata: dict[str, list[bool]] = defaultdict(list)
    expected = predicted = refused = 0
    tracking_coverage: list[float] = []
    rows: list[dict[str, Any]] = []
    non_jump: dict[str, dict[str, Any]] = {}
    for label in labels:
        event_id = str(label.get("event_id") or "")
        profile = str(label.get("profile") or "unknown")
        observability = str(label.get("observability") or "unobservable")
        prediction = normalized_predictions.get(event_id)
        tracking = label.get("event_core_tracking_coverage")
        if isinstance(tracking, (int, float)):
            tracking_coverage.append(float(tracking))
        if profile != "jump":
            profile_rows = non_jump.setdefault(profile, {"raw_n": 0, "definition_version": prediction.definition_version if prediction else None, "complete": 0, "incomplete": 0, "status": "reported_separately_no_jump_threshold"})
            profile_rows["raw_n"] += 1
            if prediction and prediction.completeness == "complete": profile_rows["complete"] += 1
            else: profile_rows["incomplete"] += 1
            continue
        truth = label.get("moments") if isinstance(label.get("moments"), Mapping) else {}
        result_row: dict[str, Any] = {"event_id": event_id, "observable": observability == "observable", "errors_sec": {}, "completeness": prediction.completeness if prediction else "missing_prediction"}
        for key in ("takeoff", "apex", "landing"):
            truth_value = truth.get(key)
            truth_pts = truth_value.get("pts") if isinstance(truth_value, Mapping) else truth_value
            if observability != "observable" or not isinstance(truth_pts, (int, float)):
                continue
            expected += 1
            predicted_moment = next((item for item in prediction.moments if item.semantic_key == key), None) if prediction else None
            if predicted_moment is None or predicted_moment.status == "unavailable" or predicted_moment.pts_sec is None:
                refused += 1
                result_row["errors_sec"][key] = None
            else:
                error = abs(predicted_moment.pts_sec - float(truth_pts))
                predicted += 1
                errors[key].append(error)
                result_row["errors_sec"][key] = round(error, 6)
        correct_complete = prediction is not None and prediction.completeness == "complete"
        for key in {profile, *(str(value) for value in label.get("strata", []))}:
            strata[key].append(correct_complete)
        rows.append(result_row)
    all_errors = [value for values in errors.values() for value in values]
    median = _percentile(all_errors, .5)
    p95 = _percentile(all_errors, .95)
    jump_thresholds_met = median is not None and p95 is not None and median <= .10 and p95 <= .25
    formal_protocol_met = dataset_frozen and validation_calibrated
    result = {
        "schema_version": "g8-profile-moments-evidence.v1",
        "gate": "G8",
        "status": "passed" if jump_thresholds_met and formal_protocol_met else "blocked_waiting_for_frozen_candidate" if jump_thresholds_met else "diagnostic_failed_or_insufficient",
        "gate_passed": bool(jump_thresholds_met and formal_protocol_met),
        "release_claim": bool(jump_thresholds_met and formal_protocol_met),
        "diagnostic_only": not formal_protocol_met,
        "candidate_fingerprint": candidate_fingerprint,
        "dataset_frozen": dataset_frozen,
        "validation_calibrated": validation_calibrated,
        "frozen_candidate_runs": 1 if formal_protocol_met else 0,
        "jump_thresholds": {"median_absolute_error_max_sec": .10, "p95_absolute_error_max_sec": .25},
        "jump": {
            "raw_n": len(rows),
            "observable_moment_n": expected,
            "predicted_moment_n": predicted,
            "refused_moment_n": refused,
            "completeness": {"numerator": predicted, "denominator": expected, "rate": round(predicted / expected, 6) if expected else None, "wilson_95_ci": _wilson(predicted, expected)},
            "refusal": {"numerator": refused, "denominator": expected, "rate": round(refused / expected, 6) if expected else None, "wilson_95_ci": _wilson(refused, expected)},
            "median_absolute_error_sec": round(median, 6) if median is not None else None,
            "median_bootstrap_95_ci": _bootstrap_ci(all_errors, statistic="median"),
            "p95_absolute_error_sec": round(p95, 6) if p95 is not None else None,
            "p95_bootstrap_95_ci": _bootstrap_ci(all_errors, statistic="p95"),
            "each_moment": {key: {"raw_n": len(values), "median_absolute_error_sec": round(_percentile(values, .5), 6) if values else None, "p95_absolute_error_sec": round(_percentile(values, .95), 6) if values else None} for key, values in sorted(errors.items())},
            "event_core_tracking_coverage": {"raw_n": len(tracking_coverage), "mean": round(sum(tracking_coverage) / len(tracking_coverage), 6) if tracking_coverage else None, "min": round(min(tracking_coverage), 6) if tracking_coverage else None},
            "thresholds_met": jump_thresholds_met,
        },
        "other_profiles": non_jump,
        "strata": {key: {"numerator": sum(values), "denominator": len(values), "rate": round(sum(values) / len(values), 6), "wilson_95_ci": _wilson(sum(values), len(values))} for key, values in sorted(strata.items())},
        "events": rows,
        "known_limitations": [
            "Jump thresholds do not authorize spin, step, or spiral claims.",
            "Semantic resolved labels and Golden moments are rejected from prediction inputs.",
            "A non-frozen or non-calibrated run is diagnostic only even if point errors meet thresholds.",
        ],
    }
    result["result_fingerprint"] = "sha256:" + hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return result
