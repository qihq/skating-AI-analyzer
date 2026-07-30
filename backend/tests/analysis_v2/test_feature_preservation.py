from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LEDGER_PATH = ROOT / "docs" / "feature-preservation" / "ledger.json"
sys.path.insert(0, str(ROOT / "scripts"))
from generate_feature_preservation_ledger import generate_ledger  # noqa: E402
REQUIRED_FIELDS = {
    "id",
    "kind",
    "name",
    "source",
    "owning_iteration",
    "current_reads",
    "current_writes",
    "permissions",
    "data_and_artifacts",
    "legacy_fixture",
    "v2_fixture",
    "shadow_behavior",
    "restart_behavior",
    "backup_restore_behavior",
    "rollback_behavior",
    "migration_status",
}


def test_feature_preservation_ledger_has_complete_unique_entries() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    entries = ledger["entries"]

    assert entries
    assert len({entry["id"] for entry in entries}) == len(entries)
    assert all(REQUIRED_FIELDS <= entry.keys() for entry in entries)
    assert all(0 <= entry["owning_iteration"] <= 19 for entry in entries)
    allowed_statuses = set(ledger["allowed_statuses"])
    assert all(entry["migration_status"] in allowed_statuses for entry in entries)
    assert not any(entry["migration_status"] == "retirement-approved" for entry in entries)


def test_ledger_covers_every_required_surface_kind() -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    kinds = {entry["kind"] for entry in ledger["entries"]}

    assert {
        "frontend_route",
        "frontend_api_operation",
        "backend_route",
        "database_model",
        "startup_or_scheduled_job",
        "environment_setting",
        "generated_artifact",
        "package_entrypoint",
        "focused_test",
        "durable_data",
    } <= kinds


def test_checked_ledger_matches_current_source_inventory() -> None:
    checked = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    current = generate_ledger()

    assert checked["inventory_fingerprint"] == current["inventory_fingerprint"]
    assert checked["entry_count"] == current["entry_count"]
