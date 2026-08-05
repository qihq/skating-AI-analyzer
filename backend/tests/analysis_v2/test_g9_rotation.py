from __future__ import annotations

import pytest

from app.analysis_v2.contracts import RotationEstimate
from app.analysis_v2.evaluation.g9_rotation import evaluate_g9_rotation


def prediction(event_id: str, value: float, *, confidence: float = .9, convention: str = "airborne_body_rotation") -> RotationEstimate:
    return RotationEstimate(
        event_id=event_id,
        profile="jump",
        status="exact",
        value_turns=value,
        class_turns=round(value * 2) / 2,
        class_kind="integer" if float(round(value * 2) / 2).is_integer() else "half_integer",
        confidence=confidence,
        observability="observed",
        value_convention=convention,
        competition_convention="non_axel",
        competition_naming_turns=round(value * 2) / 2,
        competition_naming_class="double",
        subtype_support=.9,
        estimator_fingerprint="estimator",
        source_timeline_fingerprint="timeline",
    )


def test_g9_reports_mae_class_accuracy_wrong_rate_refusal_coverage_ci_and_strata() -> None:
    labels = [
        {"event_id": "single", "convention": "non_axel_airborne", "observability": "observable", "reported_turns": 1, "strata": ["clear"]},
        {"event_id": "double", "convention": "non_axel_airborne", "observability": "observable", "reported_turns": 2, "strata": ["clear"]},
        {"event_id": "triple", "convention": "non_axel_airborne", "observability": "observable", "reported_turns": 3, "strata": ["occlusion"]},
        {"event_id": "hidden", "convention": "non_axel_airborne", "observability": "unobservable"},
    ]
    result = evaluate_g9_rotation(labels=labels, predictions={"single": prediction("single", 1), "double": prediction("double", 2), "triple": prediction("triple", 3)}, candidate_fingerprint="candidate", dataset_frozen=False, validation_calibrated=True)
    assert result["status"] == "blocked_waiting_for_frozen_candidate"
    assert result["gate_passed"] is False
    assert result["raw_n"] == 4
    assert result["observable_n"] == 3
    assert result["mae_turns"] == 0
    assert result["class_accuracy"]["rate"] == 1
    assert result["confidently_wrong"]["rate"] == 0
    assert result["coverage"]["rate"] == 1
    assert result["strata"]["single"]["raw_n"] == 1
    assert result["strata"]["triple_or_more"]["raw_n"] == 1


def test_g9_does_not_hide_refusals_or_round_ranges_into_classes() -> None:
    refused = prediction("range", 2).model_copy(update={"status": "range", "value_turns": None, "range_turns": (1.5, 2.5), "class_turns": None, "class_kind": None, "confidence": .4, "observability": "partial", "refusal_reason": "signal_aliasing", "review_required": True})
    result = evaluate_g9_rotation(labels=[{"event_id": "range", "convention": "non_axel_airborne", "observability": "observable", "reported_turns": 2}], predictions={"range": refused}, candidate_fingerprint="candidate", dataset_frozen=False, validation_calibrated=False)
    assert result["refusal"]["numerator"] == 1
    assert result["coverage"]["numerator"] == 0
    assert result["class_accuracy"]["denominator"] == 0
    assert result["events"][0]["prediction_range_turns"] == (1.5, 2.5)


def test_g9_never_mixes_airborne_and_competition_conventions() -> None:
    axel = prediction("axel", 1.5).model_copy(update={"competition_convention": "axel", "competition_naming_turns": 1.5, "competition_naming_class": "single_axel"})
    result = evaluate_g9_rotation(labels=[{"event_id": "axel", "convention": "axel_includes_forward_takeoff", "observability": "observable", "reported_turns": 1.5, "is_axel": True}], predictions={"axel": axel}, candidate_fingerprint="candidate", dataset_frozen=True, validation_calibrated=True)
    assert result["gate_passed"] is True
    assert result["strata"]["axel"]["mae_turns"] == 0
    with pytest.raises(ValueError, match="convention"):
        evaluate_g9_rotation(labels=[{"event_id": "x", "observability": "observable", "reported_turns": 1}], predictions={}, candidate_fingerprint="candidate", dataset_frozen=False, validation_calibrated=False)


def test_empty_diagnostic_is_blocked_and_cannot_satisfy_coverage_protocol() -> None:
    result = evaluate_g9_rotation(
        labels=[],
        predictions={},
        candidate_fingerprint="candidate",
        dataset_frozen=False,
        validation_calibrated=False,
    )
    assert result["status"] == "blocked_waiting_for_frozen_candidate"
    assert result["coverage_protocol_met"] is False
    assert result["thresholds_met"] is False
    assert result["gate_passed"] is False
