from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from app.analysis_v2.evaluation.g2_baseline import (
    G2BaselineStore,
    G2FreezeError,
    g2_collection_progress,
)
from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore


REVISION = {
    "revision": 1,
    "annotator_alias": "owner",
    "provenance": "created",
}


def _dataset(profiles: list[str] | None = None) -> GoldenDatasetV2:
    profiles = profiles or (["jump"] * 10 + ["spin"] * 6 + ["step"] * 4 + ["spiral"] * 4)
    sources = []
    events = []
    splits = ["development", "development", "development", "validation", "frozen_test"]
    strata = ["normal", "multi-skater", "crossing", "small", "pan", "blur"]
    for source_index in range(5):
        source_hash = f"{source_index + 1:064x}"
        sources.append(
            {
                "source_sha256": source_hash,
                "duration_pts": 300,
                "width": 1280,
                "height": 720,
                "timebase": {"numerator": 1, "denominator": 90_000, "source_fps": 30, "is_vfr": False},
                "private_source_reference": f"videos/source-{source_index}.mp4",
                "recording_session_id": f"session-{source_index}",
                "grouping_id": f"group-{source_index}",
                "redacted_alias": f"source-{source_index + 1:03d}",
            }
        )
    for index, profile in enumerate(profiles):
        source_index = index % 5
        start = float(index * 3)
        events.append(
            {
                "event_id": f"event-{index + 1:03d}",
                "source_sha256": sources[source_index]["source_sha256"],
                "start_pts": start,
                "end_pts": start + 2,
                "profile": profile,
                "observability": "observable",
                "strata": [strata[index % len(strata)]],
                "ambiguity_tags": [],
                "failure_tags": [],
                "annotator_confidence": 0.9,
                "main_skater_confirmed": True,
                "split": splits[source_index],
                "challenge_intervals": [],
                "revision": REVISION,
            }
        )
    return GoldenDatasetV2.model_validate(
        {
            "dataset_id": "golden-v2-private-catalog",
            "revision": REVISION,
            "sources": sources,
            "events": events,
        }
    )


def test_g2_progress_requires_full_profile_counts_and_locked_splits() -> None:
    progress = g2_collection_progress(_dataset(["jump"] * 6))

    assert progress["status"] == "collecting"
    assert progress["event_count"] == 6
    assert progress["required_event_range"] == [24, 30]
    assert progress["ready_to_freeze"] is False


def test_ready_dataset_can_be_frozen_and_sanitized_without_private_membership(tmp_path: Path) -> None:
    store = G2BaselineStore(GoldenCatalogStore(tmp_path / "golden"))
    dataset = _dataset()

    frozen = store.freeze(dataset, legacy_pipeline_fingerprint="legacy:v5.2.307")
    public = store.public_status(dataset)

    assert frozen["status"] == "frozen_waiting_for_baseline"
    assert frozen["dataset_revision"] == 1
    assert Counter(frozen["distribution"]["profiles"]) == Counter({"jump": 10, "spin": 6, "step": 4, "spiral": 4})
    assert public["status"] == "frozen_waiting_for_baseline"
    assert "membership" not in str(public).lower()
    assert "source_sha256" not in str(public).lower()
    assert str(tmp_path) not in str(public)


def test_freeze_rejects_insufficient_dataset(tmp_path: Path) -> None:
    store = G2BaselineStore(GoldenCatalogStore(tmp_path / "golden"))

    with pytest.raises(G2FreezeError, match="24-30"):
        store.freeze(_dataset(["jump"] * 6), legacy_pipeline_fingerprint="legacy:v5.2.307")


def test_g2_progress_uses_policy_v2_ranges() -> None:
    progress = g2_collection_progress(_dataset())
    assert progress["gate_policy_version"] == "golden-gate-policy.v2"
    assert progress["evidence_scope"] == "limited_sample"
    assert progress["required_event_range"] == [24, 30]
    assert progress["profile_ranges"] == {"jump": [10, 14], "spin": [6, 8], "step": [4, 5], "spiral": [4, 5]}
    assert progress["ready_to_freeze"] is True


@pytest.mark.parametrize("profiles", [
    ["jump"] * 9 + ["spin"] * 6 + ["step"] * 4 + ["spiral"] * 4,
    ["jump"] * 10 + ["spin"] * 5 + ["step"] * 4 + ["spiral"] * 5,
    ["jump"] * 10 + ["spin"] * 6 + ["step"] * 3 + ["spiral"] * 5,
    ["jump"] * 15 + ["spin"] * 6 + ["step"] * 4 + ["spiral"] * 4,
    ["jump"] * 14 + ["spin"] * 8 + ["step"] * 5 + ["spiral"] * 5,
])
def test_g2_rejects_total_or_profile_values_outside_policy(profiles: list[str]) -> None:
    assert g2_collection_progress(_dataset(profiles))["ready_to_freeze"] is False


def test_freeze_and_baseline_persist_policy_version(tmp_path: Path) -> None:
    store = G2BaselineStore(GoldenCatalogStore(tmp_path / "golden"))
    dataset = _dataset()
    frozen = store.freeze(dataset, legacy_pipeline_fingerprint="legacy:v5.2.307")
    baseline = store.record_baseline(dataset, dataset_fingerprint=frozen["dataset_fingerprint"], result_fingerprint="result:123", aggregate={"event_count": 24})
    assert frozen["gate_policy_version"] == "golden-gate-policy.v2"
    assert baseline["gate_policy_version"] == "golden-gate-policy.v2"
    assert store.public_status(dataset)["gate_policy_version"] == "golden-gate-policy.v2"


def test_unversioned_freeze_keeps_legacy_ranges_without_rewrite(tmp_path: Path) -> None:
    store = G2BaselineStore(GoldenCatalogStore(tmp_path / "golden"))
    dataset = _dataset()
    store.freeze(dataset, legacy_pipeline_fingerprint="legacy:v5.2.307")
    frozen = json.loads(store.freeze_path.read_text(encoding="utf-8"))
    frozen.pop("gate_policy_version")
    store.freeze_path.write_text(json.dumps(frozen, sort_keys=True), encoding="utf-8")
    before = store.freeze_path.read_bytes()
    status = store.public_status(dataset)
    assert status["gate_policy_version"] == "golden-gate-policy.v1"
    assert status["required_event_range"] == [60, 80]
    assert status["profile_ranges"] == {"jump": [24, 32], "spin": [16, 20], "step": [12, 16], "spiral": [8, 12]}
    baseline = store.record_baseline(dataset, dataset_fingerprint=frozen["dataset_fingerprint"], result_fingerprint="result:legacy-policy", aggregate={"event_count": len(dataset.events)})
    assert baseline["gate_policy_version"] == "golden-gate-policy.v1"
    assert store.public_status(dataset)["gate_policy_version"] == "golden-gate-policy.v1"
    assert store.freeze_path.read_bytes() == before


def test_frozen_test_membership_cannot_change_silently(tmp_path: Path) -> None:
    store = G2BaselineStore(GoldenCatalogStore(tmp_path / "golden"))
    dataset = _dataset()
    store.freeze(dataset, legacy_pipeline_fingerprint="legacy:v5.2.307")
    changed = dataset.model_copy(deep=True)
    changed.events[next(i for i, event in enumerate(changed.events) if event.split == "frozen_test")].split = "validation"

    with pytest.raises(G2FreezeError, match="frozen-test membership"):
        store.assert_compatible(changed)


def test_legacy_baseline_is_bound_to_the_frozen_dataset_fingerprint(tmp_path: Path) -> None:
    store = G2BaselineStore(GoldenCatalogStore(tmp_path / "golden"))
    dataset = _dataset()
    frozen = store.freeze(dataset, legacy_pipeline_fingerprint="legacy:v5.2.307")

    baseline = store.record_baseline(
        dataset,
        dataset_fingerprint=frozen["dataset_fingerprint"],
        result_fingerprint="result:123",
        aggregate={"event_count": 60, "tracking": {"coverage": 0.4}},
    )

    assert baseline["status"] == "baseline_recorded"
    assert store.public_status(dataset)["status"] == "baseline_recorded"
    with pytest.raises(G2FreezeError, match="dataset fingerprint"):
        store.record_baseline(
            dataset,
            dataset_fingerprint="wrong",
            result_fingerprint="result:456",
            aggregate={"event_count": 60},
        )
