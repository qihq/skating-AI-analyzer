from __future__ import annotations

import json
from pathlib import Path

from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore


ROOT = Path(__file__).resolve().parents[3]


def test_committed_sanitized_template_contains_no_private_source_material() -> None:
    template = ROOT / "docs" / "evaluation" / "v2" / "golden-v2-sanitized-summary-template.json"
    payload = json.loads(template.read_text(encoding="utf-8"))
    encoded = json.dumps(payload)
    for forbidden in ("path", "reference", "filename", "source_frame", "face", "embedding", "secret"):
        assert forbidden not in encoded.lower()


def test_committed_g1_waiting_evidence_contains_only_aggregate_state() -> None:
    evidence = ROOT / "docs" / "evaluation" / "v2" / "g1-waiting-for-owner-labels.json"
    encoded = evidence.read_text(encoding="utf-8").lower()
    for forbidden in ("c:\\users", "source_sha256", "event_id", "annotator_alias", "reviewer_alias", "filename", "embedding"):
        assert forbidden not in encoded


def test_committed_pilot_snapshot_evidence_is_sanitized_and_non_releasing() -> None:
    evidence = ROOT / "docs" / "evaluation" / "v2" / "pilot-12-diagnostic-2026-08-01.json"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    encoded = json.dumps(payload).lower()

    assert payload["event_count"] == 12
    assert payload["status"] == "failed"
    assert payload["diagnostic_only"] is True
    assert payload["release_claim"] is False
    for forbidden in ("c:\\users", "source_sha256", "event_id", "annotator_alias", "filename", "embedding"):
        assert forbidden not in encoded


def test_committed_iteration_3_g1_evidence_is_aggregate_only() -> None:
    evidence = ROOT / "docs" / "evaluation" / "v2" / "iteration-03-g1-pilot-evidence.json"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    encoded = json.dumps(payload).lower()

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {str(key).lower() for key in value} | {
                nested_key for nested in value.values() for nested_key in keys(nested)
            }
        if isinstance(value, list):
            return {nested_key for nested in value for nested_key in keys(nested)}
        return set()

    assert payload["gate_policy_version"] == "golden-gate-policy.v2"
    assert payload["evidence_scope"] == "limited_sample"
    assert payload["release_claim"] is False
    assert payload["formal_evaluator_status"] == "failed"
    assert "c:\\users" not in encoded
    for forbidden_key in (
        "source_sha256",
        "event_id",
        "annotator_alias",
        "reviewer_alias",
        "filename",
        "embedding",
        "artifact_sha256",
    ):
        assert forbidden_key not in keys(payload)


def test_committed_g2_waiting_evidence_is_sanitized_and_non_releasing() -> None:
    evidence = ROOT / "docs" / "evaluation" / "v2" / "g2-waiting-for-owner-labels.json"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    encoded = json.dumps(payload).lower()

    assert payload["status"] == "collecting"
    assert payload["release_claim"] is False
    assert payload["current_snapshot"]["frozen"] is False
    for forbidden in ("c:\\users", "source_sha256", "event_id", "annotator_alias", "filename", "embedding"):
        assert forbidden not in encoded


def test_private_golden_layout_is_ignored_and_never_committed() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "golden/" in ignore
    tracked = [path for path in (ROOT / "golden").rglob("*")] if (ROOT / "golden").exists() else []
    assert tracked == []


def test_sanitized_store_export_has_no_source_reference_or_runtime_path(tmp_path: Path) -> None:
    store = GoldenCatalogStore(tmp_path / "runtime" / "golden")
    encoded = json.dumps(store.sanitized_export())
    assert "runtime" not in encoded
    assert "reference" not in encoded.lower()


def test_policy_v2_transition_artifact_is_aggregate_only() -> None:
    evidence = ROOT / "docs" / "evaluation" / "v2" / "golden-gate-policy-v2-transition.json"
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    encoded = json.dumps(payload).lower()
    assert payload["gate_policy_version"] == "golden-gate-policy.v2"
    assert payload["verified_catalog"]["source_video_count"] == 18
    assert payload["release_claim"] is False
    for forbidden in ("c:\\users", "source_sha256", "event_id", "annotator_alias", "reviewer_alias", "filename", "embedding"):
        assert forbidden not in encoded


def test_sanitized_template_uses_policy_v2_counts() -> None:
    template = ROOT / "docs" / "evaluation" / "v2" / "golden-v2-sanitized-summary-template.json"
    payload = json.loads(template.read_text(encoding="utf-8"))
    gate = payload["gate_template"]
    assert gate["gate_policy_version"] == "golden-gate-policy.v2"
    assert gate["required_source_videos"] == 18
    assert gate["required_valid_events"] == 18
    assert gate["pose_frame_range"] == [24, 40]
    assert gate["g2_event_range"] == [24, 30]
    assert gate["g2_profile_ranges"] == {"jump": [10, 14], "spin": [6, 8], "step": [4, 5], "spiral": [4, 5]}
