from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2


HASH = "a" * 64


def revision(number: int = 1) -> dict[str, object]:
    return {"revision": number, "annotator_alias": "parent", "provenance": "human_annotation"}


def source() -> dict[str, object]:
    return {
        "source_sha256": HASH,
        "duration_pts": 10.0,
        "width": 1920,
        "height": 1080,
        "timebase": {"numerator": 1, "denominator": 90_000, "source_fps": 30, "is_vfr": False},
        "private_source_reference": "private-ref-001",
        "recording_session_id": "session-001",
        "grouping_id": "group-001",
        "redacted_alias": "source-001",
    }


def event(event_id: str = "event-001") -> dict[str, object]:
    return {
        "event_id": event_id,
        "source_sha256": HASH,
        "start_pts": 1.0,
        "end_pts": 4.0,
        "profile": "jump",
        "observability": "observable",
        "annotator_confidence": 0.9,
        "main_skater_confirmed": True,
        "jump": {
            "takeoff": {"pts": 1.5}, "apex": {"pts": 2.0}, "landing": {"pts": 3.0},
            "rotation": {"observed_turns_min": 1.0, "observed_turns_max": 1.5, "reported_turns": 1.0, "convention": "non_axel_airborne", "observability": "observable"},
        },
        "revision": revision(),
    }


def dataset(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "dataset_id": "golden-v2-private-catalog", "revision": {"revision": 1, "annotator_alias": "system", "provenance": "created"},
        "sources": [source()], "events": [event()], "tracks": [], "poses": [],
    }
    value.update(changes)
    return value


def test_invalid_time_order_is_rejected() -> None:
    invalid = event()
    invalid["end_pts"] = 1.0
    with pytest.raises(ValidationError, match="end_pts"):
        GoldenDatasetV2.model_validate(dataset(events=[invalid]))


def test_out_of_window_moment_is_rejected() -> None:
    invalid = event()
    invalid["jump"] = {"takeoff": {"pts": 0.5}}
    with pytest.raises(ValidationError, match="inside the event interval"):
        GoldenDatasetV2.model_validate(dataset(events=[invalid]))


def test_duplicate_event_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="event IDs must be unique"):
        GoldenDatasetV2.model_validate(dataset(events=[event(), event()]))


def test_invalid_bbox_is_rejected() -> None:
    track = {"label_id": "track-001", "event_id": "event-001", "source_sha256": HASH, "pts": 2.0, "bbox": {"left": 0.8, "top": 0.2, "right": 0.2, "bottom": 0.9}, "state": "confirmed", "revision": revision()}
    with pytest.raises(ValidationError, match="positive normalized area"):
        GoldenDatasetV2.model_validate(dataset(tracks=[track]))


def test_rotation_consistency_is_rejected() -> None:
    invalid = event()
    jump = invalid["jump"]
    assert isinstance(jump, dict)
    jump["rotation"] = {"observed_turns_min": 2, "observed_turns_max": 1, "convention": "non_axel_airborne", "observability": "observable"}
    with pytest.raises(ValidationError, match="rotation maximum"):
        GoldenDatasetV2.model_validate(dataset(events=[invalid]))


def test_out_of_window_challenge_interval_is_rejected() -> None:
    invalid = event()
    invalid["challenge_intervals"] = [{"start_pts": 0.5, "end_pts": 1.5, "category": "occlusion", "observability": "uncertain"}]
    with pytest.raises(ValidationError, match="challenge interval"):
        GoldenDatasetV2.model_validate(dataset(events=[invalid]))
