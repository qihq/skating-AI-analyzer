from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore


PROFILE_RANGES = {
    "jump": (24, 32),
    "spin": (16, 20),
    "step": (12, 16),
    "spiral": (8, 12),
}


class G2FreezeError(ValueError):
    """Raised when a dataset cannot safely enter or remain in the G2 frozen state."""


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _split_issues(dataset: GoldenDatasetV2) -> list[str]:
    source_by_hash = {source.source_sha256: source for source in dataset.sources}
    assignments: dict[tuple[str, str], set[str | None]] = defaultdict(set)
    for event in dataset.events:
        source = source_by_hash[event.source_sha256]
        assignments[("session", source.recording_session_id)].add(event.split)
        assignments[("group", source.grouping_id)].add(event.split)
    return [
        f"{kind}:split-inconsistent"
        for (kind, _), splits in sorted(assignments.items())
        if None in splits or len(splits) != 1
    ]


def _distribution(dataset: GoldenDatasetV2) -> dict[str, Any]:
    profiles = Counter(event.profile for event in dataset.events)
    splits = Counter(event.split or "unassigned" for event in dataset.events)
    strata = Counter(stratum for event in dataset.events for stratum in event.strata)
    sessions = {
        source.recording_session_id
        for source in dataset.sources
        if any(event.source_sha256 == source.source_sha256 for event in dataset.events)
    }
    return {
        "profiles": dict(sorted(profiles.items())),
        "splits": dict(sorted(splits.items())),
        "strata": dict(sorted(strata.items())),
        "recording_session_count": len(sessions),
    }


def g2_collection_progress(dataset: GoldenDatasetV2) -> dict[str, Any]:
    distribution = _distribution(dataset)
    event_count = len(dataset.events)
    profile_checks = {
        profile: {
            "count": distribution["profiles"].get(profile, 0),
            "minimum": minimum,
            "maximum": maximum,
            "passed": minimum <= distribution["profiles"].get(profile, 0) <= maximum,
        }
        for profile, (minimum, maximum) in PROFILE_RANGES.items()
    }
    split_issues = _split_issues(dataset)
    split_counts = distribution["splits"]
    required_splits_present = all(split_counts.get(name, 0) > 0 for name in ("development", "validation", "frozen_test"))
    ready = (
        60 <= event_count <= 80
        and all(item["passed"] for item in profile_checks.values())
        and distribution["recording_session_count"] >= 5
        and not split_issues
        and required_splits_present
    )
    return {
        "gate": "G2",
        "status": "ready_to_freeze" if ready else "collecting",
        "event_count": event_count,
        "required_event_range": [60, 80],
        "distribution": distribution,
        "profiles": profile_checks,
        "split_issues": split_issues,
        "required_splits_present": required_splits_present,
        "ready_to_freeze": ready,
        "release_claim": False,
    }


def _dataset_fingerprint(dataset: GoldenDatasetV2) -> str:
    return _canonical_hash(dataset.model_dump(mode="json"))


def _frozen_membership(dataset: GoldenDatasetV2) -> list[dict[str, str]]:
    return sorted(
        (
            {"event_id": event.event_id, "source_sha256": event.source_sha256}
            for event in dataset.events
            if event.split == "frozen_test"
        ),
        key=lambda item: (item["source_sha256"], item["event_id"]),
    )


class G2BaselineStore:
    def __init__(self, golden_store: GoldenCatalogStore) -> None:
        self.golden_store = golden_store
        self.root = golden_store.root / "g2"
        self.freeze_path = self.root / "freeze.json"
        self.baseline_path = self.root / "legacy-baseline.json"

    def freeze(self, dataset: GoldenDatasetV2, *, legacy_pipeline_fingerprint: str) -> dict[str, Any]:
        progress = g2_collection_progress(dataset)
        if not progress["ready_to_freeze"]:
            raise G2FreezeError("G2 freeze requires 60-80 valid, grouped, split-assigned events with profile coverage")
        if not legacy_pipeline_fingerprint.strip():
            raise G2FreezeError("legacy pipeline fingerprint is required")
        payload = {
            "schema_version": "golden-g2-freeze.v1",
            "status": "frozen_waiting_for_baseline",
            "dataset_id": dataset.dataset_id,
            "dataset_revision": dataset.revision.revision,
            "dataset_fingerprint": _dataset_fingerprint(dataset),
            "legacy_pipeline_fingerprint": legacy_pipeline_fingerprint,
            "distribution": progress["distribution"],
            "membership": _frozen_membership(dataset),
            "membership_fingerprint": _canonical_hash(_frozen_membership(dataset)),
            "release_claim": False,
        }
        if self.freeze_path.exists():
            existing = self._read(self.freeze_path)
            if existing.get("dataset_fingerprint") != payload["dataset_fingerprint"]:
                raise G2FreezeError("a different dataset version is already frozen")
            return existing
        GoldenCatalogStore._atomic_write_json(self.freeze_path, payload)
        return payload

    def assert_compatible(self, dataset: GoldenDatasetV2) -> None:
        if not self.freeze_path.exists():
            return
        frozen = self._read(self.freeze_path)
        membership_fingerprint = _canonical_hash(_frozen_membership(dataset))
        if membership_fingerprint != frozen.get("membership_fingerprint"):
            raise G2FreezeError("frozen-test membership changed; create an explicitly authorized dataset revision")

    def record_baseline(
        self,
        dataset: GoldenDatasetV2,
        *,
        dataset_fingerprint: str,
        result_fingerprint: str,
        aggregate: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.freeze_path.exists():
            raise G2FreezeError("freeze the dataset before recording a legacy baseline")
        self.assert_compatible(dataset)
        frozen = self._read(self.freeze_path)
        if dataset_fingerprint != frozen.get("dataset_fingerprint"):
            raise G2FreezeError("baseline dataset fingerprint does not match the frozen dataset")
        if not result_fingerprint.strip():
            raise G2FreezeError("baseline result fingerprint is required")
        payload = {
            "schema_version": "golden-g2-legacy-baseline.v1",
            "status": "baseline_recorded",
            "dataset_id": dataset.dataset_id,
            "dataset_fingerprint": dataset_fingerprint,
            "legacy_pipeline_fingerprint": frozen["legacy_pipeline_fingerprint"],
            "result_fingerprint": result_fingerprint,
            "aggregate": aggregate,
            "release_claim": False,
        }
        GoldenCatalogStore._atomic_write_json(self.baseline_path, payload)
        return payload

    def public_status(self, dataset: GoldenDatasetV2) -> dict[str, Any]:
        progress = g2_collection_progress(dataset)
        if not self.freeze_path.exists():
            return {
                "schema_version": "golden-g2-status.v1",
                "status": "collecting",
                **progress,
            }
        self.assert_compatible(dataset)
        frozen = self._read(self.freeze_path)
        baseline = self._read(self.baseline_path) if self.baseline_path.exists() else None
        return {
            "schema_version": "golden-g2-status.v1",
            "gate": "G2",
            "status": "baseline_recorded" if baseline else "frozen_waiting_for_baseline",
            "event_count": progress["event_count"],
            "required_event_range": progress["required_event_range"],
            "distribution": frozen["distribution"],
            "dataset_revision": frozen["dataset_revision"],
            "dataset_fingerprint": frozen["dataset_fingerprint"],
            "legacy_pipeline_fingerprint": frozen["legacy_pipeline_fingerprint"],
            "baseline_result_fingerprint": baseline.get("result_fingerprint") if baseline else None,
            "release_claim": False,
        }

    @staticmethod
    def _read(path: Any) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise G2FreezeError("G2 artifact is invalid")
        return payload
