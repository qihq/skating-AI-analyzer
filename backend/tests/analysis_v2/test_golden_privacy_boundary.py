from __future__ import annotations

import json
from pathlib import Path

from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore


ROOT = Path(__file__).resolve().parents[3]


def test_committed_sanitized_template_contains_no_private_source_material() -> None:
    template = ROOT / "docs" / "evaluation" / "v2" / "golden-v2-sanitized-summary-template.json"
    payload = json.loads(template.read_text(encoding="utf-8"))
    encoded = json.dumps(payload)
    for forbidden in ("path", "reference", "filename", "frame", "face", "embedding", "secret"):
        assert forbidden not in encoded.lower()


def test_committed_g1_waiting_evidence_contains_only_aggregate_state() -> None:
    evidence = ROOT / "docs" / "evaluation" / "v2" / "g1-waiting-for-owner-labels.json"
    encoded = evidence.read_text(encoding="utf-8").lower()
    for forbidden in ("c:\\users", "source_sha256", "event_id", "annotator_alias", "reviewer_alias", "filename", "embedding"):
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
