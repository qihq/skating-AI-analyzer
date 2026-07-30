from __future__ import annotations

from copy import deepcopy

import pytest

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.pilot_evaluator import (
    EvaluationLeakageError,
    PilotPredictionBundle,
    evaluate_pilot,
)


HASH = "a" * 64
REVISION = {"revision": 1, "annotator_alias": "owner", "provenance": "created", "created_at": "2026-07-01T00:00:00Z"}
BBOX = {"left": .1, "top": .1, "right": .4, "bottom": .8}


def _event(event_id: str = "event-a", profile: str = "jump", *, unobservable_rotation: bool = False) -> dict:
    details: dict[str, object] = {}
    if profile == "jump":
        details["jump"] = {
            "takeoff": {"pts": 1.1, "source_frame_index": 33},
            "apex": {"pts": 1.4, "source_frame_index": 42},
            "landing": {"pts": 1.8, "source_frame_index": 54},
            "rotation": {
                "observed_turns_min": 1,
                "observed_turns_max": 1,
                "reported_turns": None if unobservable_rotation else 1,
                "convention": "non_axel_airborne",
                "observability": "unobservable" if unobservable_rotation else "observable",
            },
        }
    elif profile == "spin":
        details["spin"] = {
            "entry": {"start_pts": 1.0, "end_pts": 1.2},
            "main": {"start_pts": 1.2, "end_pts": 1.8},
            "exit": {"start_pts": 1.8, "end_pts": 2.0},
            "rotation": {
                "observed_turns_min": 2,
                "observed_turns_max": 2,
                "reported_turns": 2,
                "convention": "non_axel_airborne",
                "observability": "observable",
            },
        }
    return {
        "event_id": event_id,
        "source_sha256": HASH,
        "start_pts": 1,
        "end_pts": 2,
        "profile": profile,
        "observability": "observable",
        "strata": ["multi-skater"],
        "ambiguity_tags": [],
        "failure_tags": [],
        "annotator_confidence": .9,
        "main_skater_confirmed": True,
        "split": "development",
        "challenge_intervals": [],
        "revision": REVISION,
        **details,
    }


def _dataset(events: list[dict] | None = None) -> GoldenDatasetV2:
    events = events or [_event()]
    event_ids = {item["event_id"] for item in events}
    tracks = [
        {"label_id": f"track-{event_id}-{index}", "event_id": event_id, "source_sha256": HASH, "source_frame_index": frame, "pts": pts, "bbox": BBOX, "state": "confirmed", "revision": REVISION}
        for event_id in event_ids
        for index, (frame, pts) in enumerate(((30, 1.0), (31, 1.033)), 1)
    ]
    poses = [{"label_id": "pose-event-a-1", "event_id": "event-a", "source_sha256": HASH, "source_frame_index": 42, "pts": 1.4, "joints": [{"joint": "nose", "x": .2, "y": .2, "visibility": 1}], "observability": "observable", "revision": REVISION}] if "event-a" in event_ids else []
    return GoldenDatasetV2.model_validate({
        "dataset_id": "pilot-fixture", "revision": REVISION,
        "sources": [{"source_sha256": HASH, "duration_pts": 10, "width": 1280, "height": 720, "timebase": {"numerator": 1, "denominator": 90000, "source_fps": 30, "is_vfr": False}, "private_source_reference": "videos/private.mp4", "recording_session_id": "session-1", "grouping_id": "group-1", "redacted_alias": "source-001"}],
        "events": events, "tracks": tracks, "poses": poses,
    })


def _bundle(predictions: list[dict], masks: list[str]) -> PilotPredictionBundle:
    return PilotPredictionBundle.model_validate({"pipeline_fingerprint": "pipeline-12345678", "evaluation_masks": masks, "predictions": predictions})


def _identity() -> dict:
    return {"source_sha256": HASH, "event_id": "event-a"}


def test_missing_track_frame_stays_in_denominator_and_lowers_coverage() -> None:
    prediction = {**_identity(), "tracks": [{"source_frame_index": 30, "pts": 1, "state": "confirmed", "identity": "target", "bbox": BBOX}]}
    _, result = evaluate_pilot(_dataset(), _bundle([prediction], ["tracking"]))
    tracking = result["aggregate"]["tracking"]
    assert tracking["confirmed_coverage"]["numerator"] == 1
    assert tracking["confirmed_coverage"]["denominator"] == 2
    assert tracking["lost_coverage"]["numerator"] == 1


def test_wrong_person_false_relock_is_not_counted_as_lost() -> None:
    prediction = {**_identity(), "tracks": [
        {"source_frame_index": 30, "pts": 1, "state": "confirmed", "identity": "wrong_person", "bbox": BBOX, "false_relock": True},
        {"source_frame_index": 31, "pts": 1.033, "state": "confirmed", "identity": "target", "bbox": BBOX},
    ]}
    _, result = evaluate_pilot(_dataset(), _bundle([prediction], ["tracking"]))
    tracking = result["aggregate"]["tracking"]
    assert tracking["false_relock"]["numerator"] == 1
    assert tracking["wrong_person"]["numerator"] == 1
    assert tracking["lost_coverage"]["numerator"] == 0


def test_unobservable_rotation_refusal_is_quality_not_confident_error() -> None:
    prediction = {**_identity(), "rotation": {"turns": None, "rotation_class": None, "observability": "unobservable", "confidence": .95, "refusal_reason": "occluded"}}
    _, result = evaluate_pilot(_dataset([_event(unobservable_rotation=True)]), _bundle([prediction], ["rotation"]))
    rotation = result["aggregate"]["rotation"]
    assert rotation["refusal_quality"]["numerator"] == 1
    assert rotation["confidently_wrong"]["denominator"] == 0


@pytest.mark.parametrize("field", ["golden.takeoff", "golden.apex", "golden.landing", "golden.T"])
def test_golden_tal_in_prediction_inputs_triggers_leakage(field: str) -> None:
    prediction = {**_identity(), "input_fields": [field]}
    with pytest.raises(EvaluationLeakageError):
        evaluate_pilot(_dataset(), _bundle([prediction], ["key_moments"]))


def test_manifest_and_prediction_reordering_does_not_change_result() -> None:
    events = [_event("event-b"), _event("event-a")]
    predictions = [
        {"source_sha256": HASH, "event_id": event_id, "proposal_start_pts": 1, "proposal_end_pts": 2, "predicted_profile": "jump"}
        for event_id in ("event-b", "event-a")
    ]
    _, first = evaluate_pilot(_dataset(events), _bundle(predictions, ["action"]))
    _, second = evaluate_pilot(_dataset(list(reversed(events))), _bundle(list(reversed(predictions)), ["action"]))
    assert first["deterministic_fingerprint"] == second["deterministic_fingerprint"]
    assert first["aggregate"] == second["aggregate"]


def test_perfect_action_fixture_only_emits_requested_metric() -> None:
    prediction = {**_identity(), "proposal_start_pts": 1, "proposal_end_pts": 2, "predicted_profile": "jump"}
    _, result = evaluate_pilot(_dataset(), _bundle([prediction], ["action"]))
    assert result["aggregate"]["action"]["proposal_recall"]["rate"] == 1
    assert set(result["aggregate"]) == {"event_count", "action", "strata"}
    assert "tracking" not in result["aggregate"]
    assert "rotation" not in result["aggregate"]
    assert HASH not in str(result)
    assert "event-a" not in str(result)


def test_pose_reports_availability_pck_oks_provenance_and_wrong_person() -> None:
    prediction = {**_identity(), "poses": [{"source_frame_index": 42, "pts": 1.4, "identity": "wrong_person", "joints": [{"joint": "nose", "x": .2, "y": .2, "source": "measured"}]}]}
    _, result = evaluate_pilot(_dataset(), _bundle([prediction], ["pose"]))
    pose = result["aggregate"]["pose"]
    assert pose["joint_availability"]["rate"] == 0
    assert pose["pck_at_0_2"]["rate"] == 0
    assert pose["oks"] is None
    assert pose["provenance"] == {"measured": 1}
    assert pose["wrong_person_skeleton"]["numerator"] == 1


def test_source_frame_accuracy_excludes_phase_labels_without_frame_identity() -> None:
    prediction = {
        **_identity(),
        "moments": [
            {"key": "entry_start", "source_frame_index": 30, "pts": 1.0},
            {"key": "main_start", "source_frame_index": 36, "pts": 1.2},
            {"key": "exit_end", "source_frame_index": 60, "pts": 2.0},
        ],
    }
    _, result = evaluate_pilot(_dataset([_event(profile="spin")]), _bundle([prediction], ["key_moments"]))
    moments = result["aggregate"]["key_moments"]
    assert moments["timing_coverage"]["denominator"] == 3
    assert moments["timing_coverage"]["numerator"] == 3
    assert moments["source_frame_accuracy"]["denominator"] == 0


def test_source_hash_and_event_id_both_participate_in_alignment() -> None:
    prediction = {**_identity(), "event_id": "another-event", "tracks": [{"source_frame_index": 30, "pts": 1, "state": "confirmed", "identity": "target", "bbox": BBOX}]}
    _, result = evaluate_pilot(_dataset(), _bundle([prediction], ["tracking"]))
    assert result["aggregate"]["tracking"]["lost_coverage"]["numerator"] == 2


def test_sanitized_result_maps_free_text_strata_and_rejects_path_fingerprints() -> None:
    dataset = _dataset()
    payload = dataset.model_dump(mode="json")
    payload["events"][0]["strata"] = ["family-name-or-path"]
    _, result = evaluate_pilot(GoldenDatasetV2.model_validate(payload), _bundle([{**_identity(), "proposal_start_pts": 1, "proposal_end_pts": 2, "predicted_profile": "jump"}], ["action"]))
    assert "family-name-or-path" not in str(result)
    assert "other" in result["aggregate"]["strata"]
    with pytest.raises(ValueError):
        PilotPredictionBundle.model_validate({"pipeline_fingerprint": "C:/private/path", "evaluation_masks": ["action"], "predictions": []})
