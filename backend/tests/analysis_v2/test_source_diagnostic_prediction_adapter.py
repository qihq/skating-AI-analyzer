from __future__ import annotations

from copy import deepcopy

import pytest

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.source_diagnostic_prediction_adapter import (
    build_source_diagnostic_prediction_bundle,
    build_source_diagnostic_prediction_result,
)


HASH = "a" * 64
REVISION = {
    "revision": 1,
    "annotator_alias": "owner",
    "provenance": "created",
    "created_at": "2026-07-01T00:00:00Z",
}


def _dataset(*, profile: str = "jump", event_id: str = "event-a") -> GoldenDatasetV2:
    event = {
        "event_id": event_id,
        "source_sha256": HASH,
        "start_pts": 1.0,
        "end_pts": 9.0,
        "profile": profile,
        "observability": "observable",
        "strata": ["normal"],
        "ambiguity_tags": [],
        "failure_tags": [],
        "annotator_confidence": 0.9,
        "main_skater_confirmed": True,
        "split": "development",
        "challenge_intervals": [],
        "revision": REVISION,
    }
    return GoldenDatasetV2.model_validate({
        "dataset_id": "pilot-fixture",
        "revision": REVISION,
        "sources": [{
            "source_sha256": HASH,
            "duration_pts": 10,
            "width": 1280,
            "height": 720,
            "timebase": {"numerator": 1, "denominator": 90000, "source_fps": 30, "is_vfr": False},
            "private_source_reference": "videos/private.mp4",
            "recording_session_id": "session-1",
            "grouping_id": "group-1",
            "redacted_alias": "source-001",
        }],
        "events": [event],
        "tracks": [],
        "poses": [],
    })


def _diagnostic() -> dict:
    return {
        "videos": [{
            "status": "ok",
            "raw_diagnostics": {
                "source_evidence": {
                    "schema_version": "diagnostic-source-only-evidence.v2",
                    "source_video_hash": HASH,
                    "source_timeline_fingerprint": "sha256:source-timeline",
                    "proposal_collection": {
                        "classifier_labels_consumed": False,
                        "pipeline_fingerprint": "diagnostic-source-only-evidence.v2",
                    },
                    "events": [{
                        "proposal": {"event_id": "source-event", "start_pts": 4.0, "end_pts": 5.0},
                        "classification": {
                            "profile": "spiral",
                            "state": "confirmed",
                            "confidence": 0.91,
                        },
                        "moments": {
                            "semantic_labels_consumed": False,
                            "moments": [{
                                "semantic_key": "spiral_hold",
                                "status": "confirmed",
                                "source_frame_index": 135,
                                "pts_sec": 4.5,
                            }],
                        },
                        "rotation": {
                            "status": "unobservable",
                            "observability": "unobservable",
                            "confidence": 0.8,
                            "refusal_reason": "insufficient_independent_signals",
                        },
                    }],
                },
            },
        }],
    }


def test_adapter_uses_golden_only_for_source_and_event_identity() -> None:
    first = build_source_diagnostic_prediction_bundle(
        _dataset(profile="jump", event_id="event-a"),
        _diagnostic(),
        pipeline_fingerprint="diagnostic-source-only-evidence.v2",
        evaluation_masks=["action", "key_moments", "rotation"],
    )
    second = build_source_diagnostic_prediction_bundle(
        _dataset(profile="spin", event_id="event-b"),
        _diagnostic(),
        pipeline_fingerprint="diagnostic-source-only-evidence.v2",
        evaluation_masks=["action", "key_moments", "rotation"],
    )

    assert first.predictions[0].event_id == "event-a"
    assert second.predictions[0].event_id == "event-b"
    assert first.predictions[0].predicted_profile == second.predictions[0].predicted_profile == "spiral"
    assert first.predictions[0].proposal_start_pts == second.predictions[0].proposal_start_pts == 4.0
    assert first.predictions[0].moments == second.predictions[0].moments
    assert first.predictions[0].rotation == second.predictions[0].rotation
    assert not any("golden" in field or "label" in field for field in first.predictions[0].input_fields)


def test_adapter_rejects_diagnostic_label_consumption_flags() -> None:
    diagnostic = _diagnostic()
    diagnostic["videos"][0]["raw_diagnostics"]["source_evidence"]["proposal_collection"]["classifier_labels_consumed"] = True
    with pytest.raises(ValueError, match="classifier labels"):
        build_source_diagnostic_prediction_bundle(
            _dataset(),
            diagnostic,
            pipeline_fingerprint="diagnostic-source-only-evidence.v2",
            evaluation_masks=["action"],
        )


def test_adapter_skips_whole_source_when_multiple_golden_events_cannot_be_aligned_without_labels() -> None:
    payload = _dataset().model_dump(mode="json")
    second = deepcopy(payload["events"][0])
    second["event_id"] = "event-b"
    payload["events"].append(second)
    result = build_source_diagnostic_prediction_result(
        GoldenDatasetV2.model_validate(payload),
        _diagnostic(),
        pipeline_fingerprint="diagnostic-source-only-evidence.v2",
        evaluation_masks=["action"],
    )

    assert result.bundle.predictions == []
    assert result.diagnostics["golden_target_fields_used_for_selection"] is False
    assert result.diagnostics["multi_event_source_count"] == 1
    assert result.diagnostics["multi_event_event_count"] == 2
    assert result.diagnostics["skipped_multi_event_sources"] == 1


def test_adapter_does_not_invent_exact_tracking_or_pose_predictions() -> None:
    bundle = build_source_diagnostic_prediction_bundle(
        _dataset(),
        _diagnostic(),
        pipeline_fingerprint="diagnostic-source-only-evidence.v2",
        evaluation_masks=["tracking", "pose"],
    )

    assert bundle.predictions[0].tracks == []
    assert bundle.predictions[0].poses == []
