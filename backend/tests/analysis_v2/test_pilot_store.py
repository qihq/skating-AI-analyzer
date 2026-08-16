from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore
from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.gate_policy import artifact_gate_policy_version
from app.analysis_v2.evaluation.pilot_evaluator import PilotPredictionBundle
from app.analysis_v2.evaluation.pilot_store import PilotEvaluationStore, collection_progress
from app.routers import golden_v2


def _policy_dataset(*, assigned_splits: bool = True, profiles: list[str] | None = None) -> GoldenDatasetV2:
    selected_profiles = profiles or (["jump"] * 10 + ["spin"] * 4 + ["step"] * 2 + ["spiral"] * 2)
    created_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    revision = {"revision": 2, "parent_revision": 1, "annotator_alias": "owner", "provenance": "human_annotation", "created_at": created_at}
    scene_values = ["normal", "multi-skater", "crossing", "small", "pan", "blur"]
    sources: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    for index, profile in enumerate(selected_profiles):
        source_hash = f"{index + 1:064x}"
        sources.append({"source_sha256": source_hash, "duration_pts": 5.0, "width": 1280, "height": 720, "timebase": {"numerator": 1, "denominator": 90_000, "source_fps": 30, "is_vfr": False}, "private_source_reference": f"videos/source-{index + 1}.mp4", "recording_session_id": f"session-{index + 1}", "grouping_id": f"group-{index + 1}", "redacted_alias": f"source-{index + 1:03d}"})
        event: dict[str, object] = {"event_id": f"event-{index + 1:03d}", "source_sha256": source_hash, "start_pts": 1.0, "end_pts": 3.0, "profile": profile, "observability": "observable", "strata": [scene_values[index % len(scene_values)]], "ambiguity_tags": [], "failure_tags": [], "annotator_confidence": 0.9, "main_skater_confirmed": True, "split": ("development", "validation", "frozen_test")[index % 3] if assigned_splits else None, "challenge_intervals": [], "revision": revision}
        if profile == "jump":
            event["jump"] = {"takeoff": {"pts": 1.4, "source_frame_index": 42}, "apex": {"pts": 2.0, "source_frame_index": 60}, "landing": {"pts": 2.6, "source_frame_index": 78}}
        elif profile == "spin":
            event["spin"] = {"entry": {"start_pts": 1.0, "end_pts": 1.5}, "main": {"start_pts": 1.5, "end_pts": 2.5}, "exit": {"start_pts": 2.5, "end_pts": 3.0}}
        else:
            event[profile] = {"phase": {"start_pts": 1.0, "end_pts": 3.0}, "representative_moment": {"pts": 2.0, "source_frame_index": 60}}
        events.append(event)
    return GoldenDatasetV2.model_validate({"dataset_id": "golden-v2-private-catalog", "revision": revision, "sources": sources, "events": events, "tracks": [], "poses": []})


def _save_policy_dataset(store: GoldenCatalogStore, dataset: GoldenDatasetV2) -> None:
    store.ensure_initialized()
    store.save(dataset, expected_revision=1)


def test_empty_catalog_reports_exact_owner_label_gaps(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    progress = collection_progress(store.ensure_initialized(), store)
    assert progress["status"] == "waiting_for_owner_labels"
    assert {item["key"]: item["missing"] for item in progress["profiles"]} == {"jump": 10, "spin": 4, "step": 2, "spiral": 2}
    assert all(item["missing"] == 1 for item in progress["scenes"])
    assert progress["diagnostic_only"] is True


def test_run_with_insufficient_labels_persists_waiting_state_without_fake_result(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    evaluator = PilotEvaluationStore(store)
    bundle = PilotPredictionBundle.model_validate({"pipeline_fingerprint": "pipeline-12345678", "evaluation_masks": ["tracking"], "predictions": []})
    status = evaluator.run(bundle)
    assert status["status"] == "waiting_for_owner_labels"
    assert not evaluator.sanitized_report_path.exists()
    assert json.loads(evaluator.status_path.read_text(encoding="utf-8"))["status"] == "waiting_for_owner_labels"


def test_snapshot_diagnostic_runs_with_insufficient_labels_without_releasing_g1(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    evaluator = PilotEvaluationStore(store)
    bundle = PilotPredictionBundle.model_validate({"pipeline_fingerprint": "pipeline-12345678", "evaluation_masks": ["tracking"], "predictions": []})

    status = evaluator.run(bundle, diagnostic_snapshot=True)

    assert status["status"] == "passed_for_pilot_only"
    result = evaluator.sanitized_result()
    assert result is not None
    assert result["diagnostic_only"] is True
    assert result["release_claim"] is False
    assert result["run_scope"] == "snapshot_diagnostic"


def test_snapshot_diagnostic_route_is_explicit_and_does_not_change_formal_default() -> None:
    calls: list[bool] = []

    class Evaluator:
        def run(self, bundle: PilotPredictionBundle, *, diagnostic_snapshot: bool = False) -> dict[str, object]:
            del bundle
            calls.append(diagnostic_snapshot)
            return {"status": "passed_for_pilot_only", "evaluator_version": "v1", "diagnostic_only": True, "message": "ok"}

    evaluator = Evaluator()
    bundle = PilotPredictionBundle.model_validate({"pipeline_fingerprint": "pipeline-12345678", "evaluation_masks": ["action"], "predictions": []})

    diagnostic = asyncio.run(golden_v2.run_pilot_evaluator(bundle, True, None, evaluator))
    formal = asyncio.run(golden_v2.run_pilot_evaluator(bundle, False, None, evaluator))

    assert diagnostic.status == "passed_for_pilot_only"
    assert formal.status == "passed_for_pilot_only"
    assert calls == [True, False]


def test_evaluator_routes_still_require_parent_authorization() -> None:
    session = AsyncMock()

    async def reject(*_args: object) -> None:
        raise HTTPException(status_code=403, detail="parent required")

    with patch.object(golden_v2, "require_parent_pin", new=reject):
        with pytest.raises(HTTPException) as error:
            asyncio.run(golden_v2.require_golden_parent(None, session))
    assert error.value.status_code == 403


def test_status_and_result_contain_no_runtime_path_on_empty_catalog(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "private-runtime" / "golden")
    evaluator = PilotEvaluationStore(store)
    status = asyncio.run(golden_v2.get_pilot_evaluator_status(None, evaluator))
    progress = asyncio.run(golden_v2.get_pilot_progress(None, store))
    encoded = status.model_dump_json() + json.dumps(progress)
    assert str(tmp_path) not in encoded
    assert "private_source_reference" not in encoded


def test_verified_18_event_shape_meets_count_profile_scene_and_session_requirements(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    _save_policy_dataset(store, _policy_dataset(assigned_splits=False))
    progress = collection_progress(store.read(), store)
    assert progress["gate_policy_version"] == "golden-gate-policy.v2"
    assert progress["evidence_scope"] == "limited_sample"
    assert progress["requirements"]["source_video_count"] == {"count": 18, "target": 18, "passed": True}
    assert progress["requirements"]["event_count"]["passed"] is True
    assert progress["requirements"]["schema_valid"]["passed"] is True
    assert {item["key"]: item["missing"] for item in progress["profiles"]} == {"jump": 0, "spin": 0, "step": 0, "spiral": 0}
    assert progress["requirements"]["split_grouping"]["passed"] is False
    assert "assign_consistent_splits" in progress["next_actions"]


def test_g1_becomes_ready_after_two_delayed_reviews_and_complete_splits(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    _save_policy_dataset(store, _policy_dataset())
    reviewed_at = datetime.now(timezone.utc).isoformat()
    for event_id in ("event-001", "event-002"):
        store.add_review_attestation(event_id, {"review_type": "delayed_relabel", "reviewer_alias": "owner", "reviewed_at": reviewed_at, "event_revision": 2})
    progress = collection_progress(store.read(), store)
    assert progress["requirements"]["delayed_review"] == {"count": 2, "target": 2, "passed": True}
    assert progress["status"] == "ready_for_evaluator"


def test_g1_rejects_17_sources_or_a_missing_profile_minimum(tmp_path: Path) -> None:
    short_store = GoldenCatalogStore(tmp_path / "short")
    _save_policy_dataset(short_store, _policy_dataset(profiles=["jump"] * 10 + ["spin"] * 4 + ["step"] * 2 + ["spiral"]))
    assert collection_progress(short_store.read(), short_store)["requirements"]["source_video_count"]["passed"] is False

    missing_store = GoldenCatalogStore(tmp_path / "missing-profile")
    _save_policy_dataset(missing_store, _policy_dataset(profiles=["jump"] * 11 + ["spin"] * 4 + ["step"] * 2 + ["spiral"]))
    spiral = next(item for item in collection_progress(missing_store.read(), missing_store)["profiles"] if item["key"] == "spiral")
    assert spiral == {"key": "spiral", "count": 1, "target": 2, "missing": 1}


def test_next_actions_surface_all_governance_remediation_categories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    payload = _policy_dataset().model_dump(mode="json")
    payload["events"][0]["challenge_intervals"] = [{"start_pts": 1.2, "end_pts": 1.8, "category": "crossing", "observability": "uncertain"}]
    payload["events"][0]["split"] = "frozen_test"
    _save_policy_dataset(store, GoldenDatasetV2.model_validate(payload))
    import app.analysis_v2.evaluation.pilot_store as pilot_store

    monkeypatch.setattr(pilot_store, "_rotation_ambiguous", lambda _event: True)
    monkeypatch.setattr(pilot_store, "_review_counts", lambda _dataset, _store: (0, {"ambiguous": 0, "frozen_crossing": 0}))
    monkeypatch.setattr(pilot_store.GoldenCatalogStore, "_duplicate_flags", staticmethod(lambda _dataset: ["near-duplicate:event-001"]))
    monkeypatch.setattr(pilot_store, "_frame_identity_issues", lambda _dataset: ["event-001:moment-frame-missing"])
    progress = collection_progress(store.read(), store)
    assert {"complete_ambiguous_rotation_reviews", "complete_frozen_crossing_reviews", "resolve_duplicates", "repair_source_frame_labels"}.issubset(set(progress["next_actions"]))


def test_new_diagnostic_artifacts_are_stamped_with_policy_v2(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    evaluator = PilotEvaluationStore(store)
    bundle = PilotPredictionBundle.model_validate({"pipeline_fingerprint": "pipeline-12345678", "evaluation_masks": ["tracking"], "predictions": []})
    evaluator.run(bundle, diagnostic_snapshot=True)
    for path in (evaluator.private_report_path, evaluator.sanitized_report_path, evaluator.gate_path, evaluator.status_path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["gate_policy_version"] == "golden-gate-policy.v2"
        assert payload["evidence_scope"] == "limited_sample"


def test_unversioned_evaluator_report_is_read_as_legacy_without_rewrite(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    report_path = store.root / "evaluation" / "sanitized-report.json"
    status_path = store.root / "evaluation" / "status.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"schema_version": "golden-pilot-sanitized-report.v1"}), encoding="utf-8")
    status_path.write_text(json.dumps({"status": "passed_for_pilot_only", "evaluator_version": "golden-pilot-evaluator.v1", "diagnostic_only": True, "message": "legacy run"}), encoding="utf-8")
    report_before, status_before = report_path.read_bytes(), status_path.read_bytes()
    evaluator = PilotEvaluationStore(store)
    payload, status = evaluator.sanitized_result(), evaluator.status()
    assert payload is not None
    assert artifact_gate_policy_version(payload) == "golden-gate-policy.v1"
    assert status["status"] == "not_run"
    assert status["gate_policy_version"] == "golden-gate-policy.v2"
    assert "Legacy evaluator evidence remains readable" in status["message"]
    assert report_path.read_bytes() == report_before
    assert status_path.read_bytes() == status_before


def test_delayed_review_attestation_is_separate_and_enforces_24_hours(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    initial = store.ensure_initialized()
    revision = {"revision": 2, "parent_revision": 1, "annotator_alias": "owner", "provenance": "human_annotation", "created_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()}
    source = {"source_sha256": "b" * 64, "duration_pts": 5, "width": 1280, "height": 720, "timebase": {"numerator": 1, "denominator": 90000, "source_fps": 30, "is_vfr": False}, "private_source_reference": "videos/private.mp4", "recording_session_id": "session-1", "grouping_id": "group-1", "redacted_alias": "source-001"}
    event = {"event_id": "event-1", "source_sha256": "b" * 64, "start_pts": 1, "end_pts": 2, "profile": "step", "observability": "observable", "strata": ["normal"], "ambiguity_tags": [], "failure_tags": [], "annotator_confidence": .9, "main_skater_confirmed": True, "split": "development", "challenge_intervals": [], "step": {"phase": {"start_pts": 1, "end_pts": 2}, "representative_moment": {"pts": 1.5, "source_frame_index": 45}}, "revision": revision}
    seeded = type(initial).model_validate({"dataset_id": initial.dataset_id, "revision": {"revision": 2, "parent_revision": 1, "annotator_alias": "owner", "provenance": "human_annotation", "created_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()}, "sources": [source], "events": [event], "tracks": [], "poses": []})
    store.save(seeded, expected_revision=1)
    response = asyncio.run(golden_v2.add_golden_review_attestation("event-1", golden_v2.GoldenReviewAttestationRequest(reviewer_alias="owner", review_type="delayed_relabel"), None, store))
    assert response["recorded"] is True
    assert store.review_attestations("event-1")[0]["review_type"] == "delayed_relabel"
