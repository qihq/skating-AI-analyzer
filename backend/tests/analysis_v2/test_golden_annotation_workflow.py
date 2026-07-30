from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore
from app.routers import golden_v2


HASH = "d" * 64


def _source() -> dict[str, object]:
    return {"source_sha256": HASH, "duration_pts": 12.0, "width": 1280, "height": 720, "timebase": {"numerator": 1, "denominator": 90000, "source_fps": 30, "is_vfr": False}, "private_source_reference": "videos/private.mp4", "recording_session_id": "session-1", "grouping_id": "session-1", "redacted_alias": "source-001"}


def _event(event_id: str, *, start: float, end: float, split: str | None = None) -> dict[str, object]:
    return {"event_id": event_id, "source_sha256": HASH, "start_pts": start, "end_pts": end, "profile": "jump", "observability": "observable", "strata": [], "ambiguity_tags": [], "failure_tags": [], "annotator_confidence": 0.9, "main_skater_confirmed": True, "split": split, "challenge_intervals": [], "jump": {"takeoff": {"pts": start + .1, "source_frame_index": 3}, "apex": {"pts": start + .4, "source_frame_index": 12}, "landing": {"pts": end - .1, "source_frame_index": 22}, "rotation": {"observed_turns_min": 1, "observed_turns_max": 1, "reported_turns": 1, "convention": "non_axel_airborne", "observability": "observable"}}}


def _request(revision: int, events: list[dict[str, object]]) -> golden_v2.GoldenAnnotationSaveRequest:
    return golden_v2.GoldenAnnotationSaveRequest(expected_revision=revision, annotator_alias="owner", events=events, tracks=[], poses=[])


def test_saving_one_event_does_not_change_another_and_records_field_revisions(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    seeded = golden_v2._next_dataset(initial, 1, "owner", "seed", sources=[_source()], events=[_event("event-a", start=1, end=2), _event("event-b", start=4, end=5)], tracks=[], poses=[])
    store.save(seeded, expected_revision=1)
    changed = [dict(_event("event-a", start=1.2, end=2.2)), _event("event-b", start=4, end=5)]
    workspace = asyncio.run(golden_v2.save_golden_annotations(_request(2, changed), None, store))
    assert next(event for event in workspace.events if event["event_id"] == "event-b")["start_pts"] == 4
    saved = store.read()
    assert saved.events[0].field_revisions["interval"].annotator_alias == "owner"
    assert store.event_history("event-a")


def test_stale_save_is_a_conflict_and_never_reports_success(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    seeded = golden_v2._next_dataset(initial, 1, "owner", "seed", sources=[_source()], events=[_event("event-a", start=1, end=2)], tracks=[], poses=[])
    store.save(seeded, expected_revision=1)
    with pytest.raises(HTTPException) as error:
        asyncio.run(golden_v2.save_golden_annotations(_request(1, [_event("event-a", start=1, end=2)]), None, store))
    assert error.value.status_code == 409
    assert store.read().revision.revision == 2


def test_frozen_first_pass_cannot_access_suggestions(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    seeded = golden_v2._next_dataset(initial, 1, "owner", "seed", sources=[_source()], events=[_event("event-a", start=1, end=2, split="frozen_test")], tracks=[], poses=[])
    store.save(seeded, expected_revision=1)
    with pytest.raises(HTTPException) as error:
        asyncio.run(golden_v2.get_golden_event_suggestions("event-a", None, store))
    assert error.value.status_code == 403


def test_review_queue_reports_ambiguous_and_incomplete_labels(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    event = _event("event-a", start=1, end=2)
    event.update({"main_skater_confirmed": False, "annotator_confidence": .5, "ambiguity_tags": ["blur"]})
    seeded = golden_v2._next_dataset(initial, 1, "owner", "seed", sources=[_source()], events=[event], tracks=[], poses=[])
    store.save(seeded, expected_revision=1)
    queue = asyncio.run(golden_v2.get_golden_review_queue(None, store))
    assert {item.status for item in queue} >= {"incomplete", "low-confidence", "ambiguous"}


def test_private_media_and_frame_identity_require_parent_and_never_return_paths(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    store.ensure_initialized()
    with patch.object(golden_v2, "source_frame_at", return_value=type("Frame", (), {"index": 4, "pts": 0.133, "duration": 0.033})()):
        with patch.object(store, "source_media_path", return_value=tmp_path / "private.mp4"):
            response = asyncio.run(golden_v2.get_golden_frame_identity(HASH, 4, None, store))
    assert response.source_frame_index == 4
    assert str(tmp_path) not in response.model_dump_json()
