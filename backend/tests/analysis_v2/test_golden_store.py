from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore, GoldenContractError, GoldenRevisionConflict


HASH = "b" * 64


def _source(alias: str = "source-001") -> dict[str, object]:
    return {"source_sha256": HASH, "duration_pts": 8.0, "width": 1280, "height": 720, "timebase": {"numerator": 1, "denominator": 90_000, "is_vfr": True}, "private_source_reference": "private-reference-never-exported", "recording_session_id": "session-a", "grouping_id": "group-a", "redacted_alias": alias, "perceptual_fingerprint": "1234567890abcdef"}


def _dataset(revision: int = 1, parent: int | None = None) -> GoldenDatasetV2:
    metadata: dict[str, object] = {"revision": revision, "annotator_alias": "system", "provenance": "created"}
    if parent is not None:
        metadata["parent_revision"] = parent
    return GoldenDatasetV2.model_validate({"dataset_id": "golden-v2-private-catalog", "revision": metadata, "sources": [_source()], "events": [], "tracks": [], "poses": []})


def test_private_layout_round_trip_and_runtime_isolation(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    store = GoldenCatalogStore(runtime / "golden")
    initial = store.ensure_initialized()
    assert initial.events == []
    assert store.manifest_path == runtime / "golden" / "v2" / "manifest.json"
    saved = store.save(_dataset(2, 1), expected_revision=1)
    assert store.read() == saved
    assert (runtime / "golden" / "v2" / "videos").is_dir()
    assert (runtime / "golden" / "v2" / "labels").is_dir()


def test_rename_does_not_change_source_identity_or_grouping() -> None:
    first = GoldenDatasetV2.model_validate({"dataset_id": "x", "revision": {"revision": 1, "annotator_alias": "system", "provenance": "created"}, "sources": [_source("alias-before")], "events": [], "tracks": [], "poses": []})
    second = GoldenDatasetV2.model_validate({"dataset_id": "x", "revision": {"revision": 1, "annotator_alias": "system", "provenance": "created"}, "sources": [_source("alias-after")], "events": [], "tracks": [], "poses": []})
    assert first.sources[0].source_sha256 == second.sources[0].source_sha256
    assert first.sources[0].grouping_id == second.sources[0].grouping_id


def test_duplicate_flags_are_available_before_split(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    store.ensure_initialized()
    dataset = _dataset(2, 1).model_copy(update={"sources": [_dataset(2, 1).sources[0], _dataset(2, 1).sources[0].model_copy(update={"source_sha256": "c" * 64, "redacted_alias": "source-002"})]})
    store.save(dataset, expected_revision=1)
    assert "near-duplicate:source-001" in store.catalog_summary()["duplicate_sources"]
    assert "same-session:source-002" in store.catalog_summary()["duplicate_sources"]


def test_incompatible_schema_fails_explicitly(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    store.ensure_initialized()
    payload = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "golden-dataset.v1"
    store.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GoldenContractError, match="Unsupported"):
        store.read()
    assert store.catalog_summary()["status"] == "schema-incompatible"


def test_atomic_save_rejects_stale_revision(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    store.ensure_initialized()
    with pytest.raises(GoldenRevisionConflict):
        store.save(_dataset(2, 1), expected_revision=2)


def test_sanitized_export_has_no_private_source_reference_or_path(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    store.ensure_initialized()
    store.save(_dataset(2, 1), expected_revision=1)
    encoded = json.dumps(store.sanitized_export())
    assert "private-reference-never-exported" not in encoded
    assert str(tmp_path) not in encoded


def test_sanitized_export_carries_policy_v2_without_private_data(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    payload = store.sanitized_export()
    template = payload["gate_template"]
    assert template["gate_policy_version"] == "golden-gate-policy.v2"
    assert template["required_source_videos"] == 18
    assert template["required_valid_events"] == 18
    assert template["profile_minimums"] == {"jump": 10, "spin": 4, "step": 2, "spiral": 2}
    assert template["required_new_events"] == 18
    assert template["pose_frame_range"] == [24, 40]
    assert template["g2_event_range"] == [24, 30]
    assert template["g2_profile_ranges"] == {"jump": [10, 14], "spin": [6, 8], "step": [4, 5], "spiral": [4, 5]}
