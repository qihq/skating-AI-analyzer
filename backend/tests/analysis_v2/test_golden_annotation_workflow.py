from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore
from app.analysis_v2.evaluation import source_media
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


def test_ambiguous_rotation_requires_exact_time_matching_definition_double_review(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    event = _event("event-a", start=1, end=2, split="frozen_test")
    event["jump"]["rotation"] = {
        "observed_turns_min": 1,
        "observed_turns_max": 1.5,
        "reported_turns": None,
        "convention": "non_axel_airborne",
        "definition": "airborne_body_rotation",
        "observability": "uncertain",
        "review_start_pts": 1.1,
        "review_end_pts": 1.9,
    }
    seeded = golden_v2._next_dataset(initial, 1, "owner", "seed", sources=[_source()], events=[event], tracks=[], poses=[])
    store.save(seeded, expected_revision=1)
    assert any(item.status == "double-review-required" for item in asyncio.run(golden_v2.get_golden_review_queue(None, store)))
    with pytest.raises(HTTPException, match="different reviewer"):
        asyncio.run(golden_v2.add_golden_review_attestation("event-a", golden_v2.GoldenReviewAttestationRequest(reviewer_alias="owner", review_type="ambiguous_rotation", rotation_definition="airborne_body_rotation", review_start_pts=1.1, review_end_pts=1.9), None, store))
    with pytest.raises(HTTPException, match="definition"):
        asyncio.run(golden_v2.add_golden_review_attestation("event-a", golden_v2.GoldenReviewAttestationRequest(reviewer_alias="reviewer-2", review_type="ambiguous_rotation", rotation_definition="competition_naming", review_start_pts=1.1, review_end_pts=1.9), None, store))
    asyncio.run(golden_v2.add_golden_review_attestation("event-a", golden_v2.GoldenReviewAttestationRequest(reviewer_alias="reviewer-2", review_type="ambiguous_rotation", rotation_definition="airborne_body_rotation", review_start_pts=1.1, review_end_pts=1.9), None, store))
    assert not any(item.status == "double-review-required" for item in asyncio.run(golden_v2.get_golden_review_queue(None, store)))


def test_private_media_and_frame_identity_require_parent_and_never_return_paths(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    store.ensure_initialized()
    with patch.object(golden_v2, "source_frame_at", return_value=type("Frame", (), {"index": 4, "pts": 0.133, "duration": 0.033})()):
        with patch.object(store, "source_media_path", return_value=tmp_path / "private.mp4"):
            response = asyncio.run(golden_v2.get_golden_frame_identity(HASH, 4, None, store))
    assert response.source_frame_index == 4
    assert str(tmp_path) not in response.model_dump_json()


def test_frame_by_pts_uses_the_static_route_instead_of_the_numeric_frame_route(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(golden_v2.router)
    store = GoldenCatalogStore(tmp_path / "golden")
    app.dependency_overrides[golden_v2.require_golden_parent] = lambda: None
    app.dependency_overrides[golden_v2.get_golden_store] = lambda: store

    reference = SimpleNamespace(source_frame_index=126, pts_sec=4.2, duration_sec=1 / 30)
    with patch.object(store, "source_media_path", return_value=tmp_path / "private.mp4"):
        with patch.object(golden_v2, "source_frame_reference_at_pts", return_value=reference):
            with TestClient(app) as client:
                response = client.get(f"/api/golden/v2/sources/{HASH}/frames/by-pts", params={"pts": 4.2})

    assert response.status_code == 200
    assert response.json() == {"source_frame_index": 126, "pts": 4.2, "duration": pytest.approx(1 / 30)}


def test_workspace_lists_catalog_metadata_without_scanning_private_media(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    persisted_timeline = {
        "schema_version": "source-timeline.v1",
        "source_video_hash": HASH,
        "timestamp_status": "exact",
        "frames": [{"source_frame_index": 0, "pts_sec": 0.0, "duration_sec": 1 / 30, "status": "exact", "gap_before_sec": 0.0}],
    }
    source = {**_source(), "source_frame_count": 360, "source_timeline": persisted_timeline}
    seeded = golden_v2._next_dataset(initial, 1, "owner", "seed", sources=[source], events=[], tracks=[], poses=[])
    store.save(seeded, expected_revision=1)
    scanned_timeline = {**persisted_timeline, "fingerprint": "unexpected-media-scan"}

    with patch.object(store, "source_media_path", return_value=tmp_path / "private.mp4") as media_path:
        with patch.object(source_media, "source_frame_index", return_value=SimpleNamespace(to_timeline=lambda: scanned_timeline)) as frame_index:
            workspace = golden_v2._workspace_response(store.read(), store)

    media_path.assert_not_called()
    frame_index.assert_not_called()
    assert workspace.sources[0].source_frame_count == 360
    assert workspace.sources[0].source_timeline == persisted_timeline


def test_private_media_prefers_a_browser_playback_copy_without_changing_evidence_path(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    seeded = golden_v2._next_dataset(initial, 1, "owner", "seed", sources=[_source()], events=[], tracks=[], poses=[])
    store.save(seeded, expected_revision=1)
    original = store.videos_dir / "private.mp4"
    original.write_bytes(b"original")
    playback = store.videos_dir / f"{HASH}.playback.mp4"
    playback.write_bytes(b"h264")

    assert store.source_media_path(HASH) == original
    assert store.source_playback_path(HASH) == playback


def test_source_frame_uses_cached_packet_pts_without_decoding_frames(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    payload = {"packets": [
        {"pts_time": "0.066667", "duration_time": "0.033333"},
        {"pts_time": "0.000000", "duration_time": "0.033333"},
        {"pts_time": "0.033333", "duration_time": "0.033333"},
    ]}
    source_media._source_packet_index.cache_clear()
    with patch.object(source_media, "_ffprobe", return_value=payload) as probe:
        assert source_media.source_frame_at(video, 1).pts == pytest.approx(0.033333)
        assert source_media.source_frame_at(video, 2).pts == pytest.approx(0.066667)
    probe.assert_called_once()
    assert "-show_packets" in probe.call_args.args


def test_import_rejects_invalid_session_identifier_before_reading_media(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(golden_v2.router)
    app.dependency_overrides[golden_v2.require_golden_parent] = lambda: None
    app.dependency_overrides[golden_v2.get_golden_store] = lambda: GoldenCatalogStore(tmp_path / "golden")

    with TestClient(app) as client:
        response = client.post(
            "/api/golden/v2/sources/import",
            files={"file": ("private.mp4", b"not-a-video", "video/mp4")},
            data={
                "recording_session_id": "invalid session path",
                "grouping_id": "group-1",
                "redacted_alias": "source-001",
                "expected_revision": "1",
                "annotator_alias": "owner",
            },
        )

    assert response.status_code == 422
    assert "recording_session_id" in response.text


def test_deleting_source_cascades_current_labels_and_invalidates_evaluator(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    seeded = golden_v2._next_dataset(
        initial,
        1,
        "owner",
        "seed",
        sources=[_source()],
        events=[_event("event-a", start=1, end=2)],
        tracks=[],
        poses=[],
    )
    store.save(seeded, expected_revision=1)
    media = store.videos_dir / "private.mp4"
    media.write_bytes(b"private")
    evaluator = golden_v2.get_pilot_store(store)
    evaluator._write(evaluator.sanitized_report_path, {"stale": True})

    request = golden_v2.GoldenSourceDeleteRequest(
        expected_revision=2,
        annotator_alias="owner",
        confirmation="delete_source_and_labels",
    )
    workspace = asyncio.run(golden_v2.delete_golden_source(HASH, request, None, store))

    assert workspace.sources == []
    assert workspace.events == []
    assert not media.exists()
    assert not evaluator.sanitized_report_path.exists()
    assert evaluator.status()["status"] == "not_run"
    assert store.event_history("event-a")


def test_updating_source_grouping_preserves_existing_label_revision(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    seeded = golden_v2._next_dataset(initial, 1, "owner", "seed", sources=[_source()], events=[_event("event-a", start=1, end=2)], tracks=[], poses=[])
    store.save(seeded, expected_revision=1)
    previous_event_revision = store.read().events[0].revision.revision
    request = golden_v2.GoldenSourceUpdateRequest(
        expected_revision=2,
        annotator_alias="owner",
        recording_session_id="session-2",
        grouping_id="group-2",
        redacted_alias="source-renamed",
    )

    workspace = asyncio.run(golden_v2.update_golden_source(HASH, request, None, store))

    assert workspace.sources[0].redacted_alias == "source-renamed"
    assert store.read().events[0].revision.revision == previous_event_revision
