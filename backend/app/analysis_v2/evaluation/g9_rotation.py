from __future__ import annotations

"""Convention-safe, refusal-aware G9 rotation evaluation."""

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.analysis_v2.contracts import RotationEstimate


LABEL_CONVENTIONS = {
    "airborne_body_rotation": "airborne_body_rotation",
    "non_axel_airborne": "airborne_body_rotation",
    "observed_spin_rotation": "observed_spin_rotation",
    "axel_includes_forward_takeoff": "competition_naming",
    "competition_naming": "competition_naming",
}


def _wilson(numerator: int, denominator: int) -> list[float] | None:
    if denominator == 0:
        return None
    z = 1.959963984540054
    proportion = numerator / denominator
    center = (proportion + z * z / (2 * denominator)) / (1 + z * z / denominator)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * denominator)) / denominator) / (1 + z * z / denominator)
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def _bootstrap_mean_ci(values: Sequence[float], rounds: int = 800) -> list[float] | None:
    if not values:
        return None
    state = 0x13A5B9C7
    means: list[float] = []
    for _ in range(rounds):
        draw: list[float] = []
        for _ in values:
            state = (1664525 * state + 1013904223) % (2**32)
            draw.append(values[state % len(values)])
        means.append(sum(draw) / len(draw))
    ordered = sorted(means)
    return [round(ordered[int((len(ordered) - 1) * .025)], 6), round(ordered[int((len(ordered) - 1) * .975)], 6)]


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
        "wilson_95_ci": _wilson(numerator, denominator),
    }


def _label_value(label: Mapping[str, Any], convention: str) -> tuple[float | None, tuple[float, float] | None, str]:
    observability = str(label.get("observability") or "unobservable")
    if observability == "unobservable":
        return None, None, observability
    exact = label.get("value_turns", label.get("reported_turns"))
    low = label.get("range_min_turns", label.get("observed_turns_min"))
    high = label.get("range_max_turns", label.get("observed_turns_max"))
    if isinstance(exact, (int, float)):
        return float(exact), None, observability
    if isinstance(low, (int, float)) and isinstance(high, (int, float)):
        if float(high) < float(low):
            raise ValueError("G9 label rotation interval is reversed")
        if float(low) == float(high):
            return float(low), None, observability
        return None, (float(low), float(high)), observability
    return None, None, "unobservable"


def _prediction_value(prediction: RotationEstimate, convention: str) -> tuple[float | None, tuple[float, float] | None]:
    if convention == prediction.value_convention:
        return prediction.value_turns, prediction.range_turns
    if convention == "competition_naming" and prediction.competition_convention in {"axel", "non_axel"}:
        return prediction.competition_naming_turns, None
    return None, None


def _class(value: float) -> float:
    return round(value * 2) / 2


def evaluate_g9_rotation(
    *,
    labels: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, RotationEstimate | Mapping[str, Any]],
    candidate_fingerprint: str,
    dataset_frozen: bool,
    validation_calibrated: bool,
) -> dict[str, Any]:
    if not candidate_fingerprint:
        raise ValueError("G9 evaluation requires a candidate fingerprint")
    normalized = {
        event_id: prediction if isinstance(prediction, RotationEstimate) else RotationEstimate.model_validate(prediction)
        for event_id, prediction in predictions.items()
    }
    errors: list[float] = []
    observable_n = clear_exact_label_n = exact_prediction_n = refused_n = wrong_class_n = confident_wrong_n = convention_mismatch_n = 0
    rows: list[dict[str, Any]] = []
    strata_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for label in labels:
        event_id = str(label.get("event_id") or "")
        raw_convention = str(label.get("convention") or label.get("value_convention") or "")
        convention = LABEL_CONVENTIONS.get(raw_convention)
        if convention is None:
            raise ValueError(f"G9 label convention is unsupported: {raw_convention or 'missing'}")
        truth, truth_range, observability = _label_value(label, convention)
        prediction = normalized.get(event_id)
        predicted, predicted_range = _prediction_value(prediction, convention) if prediction else (None, None)
        observable = observability != "unobservable" and (truth is not None or truth_range is not None)
        if observable:
            observable_n += 1
        if truth is not None and observability == "observable":
            clear_exact_label_n += 1
        refused = observable and predicted is None
        if refused:
            refused_n += 1
        error = None
        class_correct = None
        confidently_wrong = False
        if observable and truth is not None and predicted is not None and prediction is not None and prediction.status == "exact":
            exact_prediction_n += 1
            error = abs(predicted - truth)
            errors.append(error)
            class_correct = _class(predicted) == _class(truth)
            wrong_class_n += int(not class_correct)
            confidently_wrong = prediction.confidence >= .70 and error > .25
            confident_wrong_n += int(confidently_wrong)
        elif prediction is not None and observable and predicted is None and prediction.status == "exact":
            convention_mismatch_n += 1
        row = {
            "event_id": event_id,
            "label_convention": convention,
            "label_observability": observability,
            "label_value_turns": truth,
            "label_range_turns": truth_range,
            "prediction_status": prediction.status if prediction else "missing",
            "prediction_value_turns": predicted,
            "prediction_range_turns": predicted_range,
            "absolute_error_turns": round(error, 6) if error is not None else None,
            "class_correct": class_correct,
            "confidently_wrong": confidently_wrong,
            "refused": refused,
        }
        rows.append(row)
        truth_for_strata = truth if truth is not None else sum(truth_range) / 2 if truth_range is not None else None
        multiplicity = "unobservable"
        if truth_for_strata is not None:
            multiplicity = "single" if truth_for_strata < 1.75 else "double" if truth_for_strata < 2.75 else "triple_or_more"
        axel = "axel" if bool(label.get("is_axel")) or raw_convention == "axel_includes_forward_takeoff" else "non_axel"
        for key in {multiplicity, axel, observability, *(str(value) for value in label.get("strata", []))}:
            strata_rows[key].append(row)
    class_denominator = exact_prediction_n
    class_correct_n = class_denominator - wrong_class_n
    mae = sum(errors) / len(errors) if errors else None
    coverage = _rate(exact_prediction_n, observable_n)
    refusal = _rate(refused_n, observable_n)
    class_accuracy = _rate(class_correct_n, class_denominator)
    confidently_wrong = _rate(confident_wrong_n, class_denominator)
    coverage_protocol_met = clear_exact_label_n > 0 and exact_prediction_n == clear_exact_label_n and convention_mismatch_n == 0
    thresholds_met = (
        mae is not None
        and mae <= .25
        and class_accuracy["rate"] is not None
        and class_accuracy["rate"] >= .90
        and confidently_wrong["rate"] is not None
        and confidently_wrong["rate"] < .02
        and coverage_protocol_met
    )
    formal_protocol_met = dataset_frozen and validation_calibrated

    def summarize_stratum(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        observed = sum(1 for item in items if item["label_observability"] != "unobservable" and (item["label_value_turns"] is not None or item["label_range_turns"] is not None))
        exact = [item for item in items if item["absolute_error_turns"] is not None]
        stratum_errors = [float(item["absolute_error_turns"]) for item in exact]
        correct = sum(1 for item in exact if item["class_correct"] is True)
        wrong_confident = sum(1 for item in exact if item["confidently_wrong"] is True)
        return {
            "raw_n": len(items),
            "observable_n": observed,
            "exact_prediction_n": len(exact),
            "refusal": _rate(sum(1 for item in items if item["refused"] is True), observed),
            "coverage": _rate(len(exact), observed),
            "mae_turns": round(sum(stratum_errors) / len(stratum_errors), 6) if stratum_errors else None,
            "mae_bootstrap_95_ci": _bootstrap_mean_ci(stratum_errors),
            "class_accuracy": _rate(correct, len(exact)),
            "confidently_wrong": _rate(wrong_confident, len(exact)),
        }

    result = {
        "schema_version": "g9-multi-signal-rotation-evidence.v1",
        "gate": "G9",
        "status": "passed" if thresholds_met and formal_protocol_met else "blocked_waiting_for_frozen_candidate" if not formal_protocol_met else "diagnostic_failed_or_insufficient",
        "gate_passed": bool(thresholds_met and formal_protocol_met),
        "release_claim": bool(thresholds_met and formal_protocol_met),
        "diagnostic_only": not formal_protocol_met,
        "candidate_fingerprint": candidate_fingerprint,
        "dataset_frozen": dataset_frozen,
        "validation_calibrated": validation_calibrated,
        "frozen_candidate_runs": 1 if formal_protocol_met else 0,
        "thresholds": {"observable_mae_max_turns": .25, "class_accuracy_min": .90, "confidently_wrong_max": .02},
        "raw_n": len(labels),
        "observable_n": observable_n,
        "clear_exact_label_n": clear_exact_label_n,
        "exact_prediction_n": exact_prediction_n,
        "mae_turns": round(mae, 6) if mae is not None else None,
        "mae_bootstrap_95_ci": _bootstrap_mean_ci(errors),
        "class_accuracy": class_accuracy,
        "confidently_wrong": confidently_wrong,
        "refusal": refusal,
        "coverage": coverage,
        "convention_mismatch_n": convention_mismatch_n,
        "coverage_protocol_met": coverage_protocol_met,
        "thresholds_met": thresholds_met,
        "strata": {key: summarize_stratum(items) for key, items in sorted(strata_rows.items())},
        "events": rows,
        "known_limitations": [
            "Unobservable labels remain in raw N and refusal/coverage denominators are reported explicitly.",
            "Airborne-body and competition-naming conventions are never compared across definitions.",
            "Range predictions remain context and are not rounded into class-accuracy observations.",
            "A non-frozen or non-calibrated run is diagnostic only even if thresholds are met.",
        ],
    }
    result["result_fingerprint"] = "sha256:" + hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return result
