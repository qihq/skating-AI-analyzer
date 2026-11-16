from __future__ import annotations

from copy import deepcopy

import pytest

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.pilot_evaluator import (
    EvaluationLeakageError,
    PilotPredictionBundle,
    evaluate_pilot,
    canonical_fingerprint,
)
from app.analysis_v2.evaluation.gate_policy import GOLDEN_GATE_POLICY
from app.analysis_v2.evaluation.legacy_prediction_adapter import build_pilot_prediction_bundle


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
    tracks = [
        {"label_id": f"track-{event['event_id']}-{index}", "event_id": event["event_id"], "source_sha256": HASH, "source_frame_index": frame, "pts": pts, "bbox": BBOX, "state": "confirmed", "revision": REVISION}
        for event in events
        for index, (frame, pts) in enumerate(((round(event["start_pts"] * 30), event["start_pts"]), (round(event["start_pts"] * 30) + 1, event["start_pts"] + .033)), 1)
    ]
    event_ids = {item["event_id"] for item in events}
    poses = [{"label_id": "pose-event-a-1", "event_id": "event-a", "source_sha256": HASH, "source_frame_index": 42, "pts": 1.4, "joints": [{"joint": "nose", "x": .2, "y": .2, "visibility": 1}], "observability": "observable", "revision": REVISION}] if "event-a" in event_ids else []
    return GoldenDatasetV2.model_validate({
        "dataset_id": "pilot-fixture", "revision": REVISION,
        "sources": [{"source_sha256": HASH, "duration_pts": 10, "width": 1280, "height": 720, "timebase": {"numerator": 1, "denominator": 90000, "source_fps": 30, "is_vfr": False}, "private_source_reference": "videos/private.mp4", "recording_session_id": "session-1", "grouping_id": "group-1", "redacted_alias": "source-001"}],
        "events": events, "tracks": tracks, "poses": poses,
    })


def _bundle(predictions: list[dict], masks: list[str]) -> PilotPredictionBundle:
    return PilotPredictionBundle.model_validate({"pipeline_fingerprint": "pipeline-12345678", "evaluation_masks": masks, "predictions": predictions})


def _bundle_with_proposals(predictions: list[dict], proposals: list[dict], masks: list[str]) -> PilotPredictionBundle:
    return PilotPredictionBundle.model_validate({
        "pipeline_fingerprint": "pipeline-12345678",
        "evaluation_masks": masks,
        "proposals": proposals,
        "predictions": predictions,
    })


def _identity() -> dict:
    return {"source_sha256": HASH, "event_id": "event-a"}


def test_legacy_prediction_adapter_maps_safe_action_fields_without_private_paths() -> None:
    dataset = _dataset()
    bundle = build_pilot_prediction_bundle(
        dataset,
        {
            HASH: {
                "analysis_profile": "spin",
                "status": "failed",
                "video_temporal_diagnostics": {
                    "video_ai_provider": "mimo",
                    "video_ai_model": "mimo-v2.5",
                    "fallback_reason": "video_temporal_auth_error",
                    "used_semantic_frames": False,
                    "used_legacy_sampled_frames": True,
                },
                "video_path": "C:/private/video.mp4",
            }
        },
        pipeline_fingerprint="legacy-api-pilot-20260801",
        evaluation_masks=["action"],
    )

    prediction = bundle.predictions[0]
    assert prediction.predicted_profile == "spin"
    assert prediction.input_payload["provider"] == "mimo"
    assert "video_path" not in prediction.input_payload


def test_legacy_prediction_adapter_omits_missing_analysis_rows() -> None:
    dataset = _dataset()
    bundle = build_pilot_prediction_bundle(
        dataset,
        {},
        pipeline_fingerprint="legacy-api-pilot-20260801",
        evaluation_masks=["action"],
    )

    assert bundle.predictions == []


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


def test_parent_identity_anchor_is_upstream_for_action_but_leakage_for_tracking() -> None:
    prediction = {
        **_identity(),
        "input_fields": ["upstream.parent_confirmed_identity_anchor"],
        "proposal_start_pts": 1,
        "proposal_end_pts": 2,
        "predicted_profile": "jump",
    }

    _, action = evaluate_pilot(_dataset(), _bundle([prediction], ["action"]))
    assert action["aggregate"]["action"]["class_accuracy"]["rate"] == 1
    with pytest.raises(EvaluationLeakageError):
        evaluate_pilot(_dataset(), _bundle([prediction], ["tracking"]))


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


def test_ambiguous_top_profile_is_scored_but_remains_rejected() -> None:
    prediction = {
        **_identity(),
        "proposal_start_pts": 1,
        "proposal_end_pts": 2,
        "predicted_profile": "jump",
        "predicted_profile_state": "ambiguous",
    }

    private, result = evaluate_pilot(_dataset(), _bundle([prediction], ["action"]))

    assert result["aggregate"]["action"]["class_accuracy"]["rate"] == 1
    assert result["aggregate"]["action"]["rejection"]["rate"] == 1
    assert private["events"][0]["metrics"]["action"]["predicted_profile_state"] == "ambiguous"
    assert "action_class_uncertain" in private["events"][0]["failure_codes"]


def test_narrow_proposal_with_temporal_iou_point_two_counts_as_recalled() -> None:
    prediction = {
        **_identity(),
        "proposal_start_pts": 1.0,
        "proposal_end_pts": 1.2,
        "predicted_profile": "jump",
    }
    _, result = evaluate_pilot(_dataset(), _bundle([prediction], ["action"]))

    assert result["aggregate"]["action"]["proposal_recall"]["rate"] == 1


def test_narrow_proposal_covering_labelled_action_core_counts_as_recalled() -> None:
    event = _event()
    event["start_pts"] = 0.0
    event["end_pts"] = 10.0
    event["jump"] = {
        "takeoff": {"pts": 8.0, "source_frame_index": 240},
        "apex": {"pts": 8.2, "source_frame_index": 246},
        "landing": {"pts": 8.4, "source_frame_index": 252},
        "rotation": event["jump"]["rotation"],
    }
    prediction = {
        **_identity(),
        "proposal_start_pts": 7.9,
        "proposal_end_pts": 8.5,
        "predicted_profile": "jump",
    }
    _, result = evaluate_pilot(_dataset([event]), _bundle([prediction], ["action"]))

    assert result["aggregate"]["action"]["proposal_recall"]["rate"] == 1


def test_source_level_proposals_are_evaluated_independently_from_event_classification() -> None:
    prediction = {
        **_identity(),
        "predicted_profile": "jump",
        "predicted_profile_state": "confirmed",
    }
    proposal = {
        "source_sha256": HASH,
        "proposal_id": "proposal-a",
        "start_pts": 1.0,
        "end_pts": 2.0,
    }

    _, result = evaluate_pilot(
        _dataset(),
        _bundle_with_proposals([prediction], [proposal], ["action"]),
    )

    assert result["aggregate"]["action"]["proposal_recall"]["rate"] == 1
    assert result["aggregate"]["action"]["localized_proposal_recall"]["rate"] == 1
    assert result["aggregate"]["action"]["unlocalized_fallback"]["rate"] == 0
    assert result["aggregate"]["action"]["class_accuracy"]["rate"] == 1


def test_unlocalized_source_fallback_recovers_recall_but_remains_a_failure() -> None:
    proposal = {
        "source_sha256": HASH,
        "proposal_id": "proposal-fallback",
        "start_pts": 0.0,
        "end_pts": 10.0,
        "localization": "unlocalized",
    }

    private, result = evaluate_pilot(
        _dataset(),
        _bundle_with_proposals([], [proposal], ["action"]),
    )

    action = result["aggregate"]["action"]
    assert action["proposal_recall"]["rate"] == 1
    assert action["localized_proposal_recall"]["rate"] == 0
    assert action["unlocalized_fallback"]["rate"] == 1
    assert "action_proposal_unlocalized" in private["events"][0]["failure_codes"]


def test_multiple_events_on_one_source_can_each_match_a_distinct_source_proposal() -> None:
    first = _event("event-a")
    second = _event("event-b")
    second["start_pts"] = 4.0
    second["end_pts"] = 5.0
    second["jump"]["takeoff"] = {"pts": 4.1, "source_frame_index": 123}
    second["jump"]["apex"] = {"pts": 4.4, "source_frame_index": 132}
    second["jump"]["landing"] = {"pts": 4.8, "source_frame_index": 144}
    proposals = [
        {"source_sha256": HASH, "proposal_id": "proposal-a", "start_pts": 1.0, "end_pts": 2.0},
        {"source_sha256": HASH, "proposal_id": "proposal-b", "start_pts": 4.0, "end_pts": 5.0},
    ]

    _, result = evaluate_pilot(
        _dataset([first, second]),
        _bundle_with_proposals([], proposals, ["action"]),
    )

    assert result["aggregate"]["action"]["proposal_recall"]["numerator"] == 2
    assert result["aggregate"]["action"]["proposal_recall"]["denominator"] == 2


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


def test_policy_v2_is_stamped_and_part_of_the_result_fingerprint() -> None:
    private, sanitized = evaluate_pilot(_dataset(), _bundle([_identity()], ["tracking"]))
    assert private["gate_policy_version"] == "golden-gate-policy.v2"
    assert private["evidence_scope"] == "limited_sample"
    assert sanitized["gate_policy_version"] == "golden-gate-policy.v2"
    expected = canonical_fingerprint({"gate_policy_version": GOLDEN_GATE_POLICY.schema_version, "evaluator_version": private["evaluator_version"], "dataset_fingerprint": private["dataset_fingerprint"], "pipeline_fingerprint": private["pipeline_fingerprint"], "evaluation_masks": private["evaluation_masks"], "aggregate": private["aggregate"], "diagnostics": private["events"]})
    assert private["deterministic_fingerprint"] == expected
    assert sanitized["deterministic_fingerprint"] == expected
