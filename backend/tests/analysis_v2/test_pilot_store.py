from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore
from app.analysis_v2.evaluation.pilot_evaluator import PilotPredictionBundle
from app.analysis_v2.evaluation.pilot_store import PilotEvaluationStore, collection_progress
from app.routers import golden_v2


def test_empty_catalog_reports_exact_owner_label_gaps(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "golden")
    progress = collection_progress(store.ensure_initialized(), store)
    assert progress["status"] == "waiting_for_owner_labels"
    assert {item["key"]: item["missing"] for item in progress["profiles"]} == {"jump": 14, "spin": 10, "step": 6, "spiral": 6}
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
