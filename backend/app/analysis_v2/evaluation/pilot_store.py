from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2
from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore
from app.analysis_v2.evaluation.pilot_evaluator import (
    EVALUATOR_VERSION,
    EvaluationLeakageError,
    PilotPredictionBundle,
    canonical_fingerprint,
    evaluate_pilot,
)


PROFILE_TARGETS = {"jump": 14, "spin": 10, "step": 6, "spiral": 6}
SCENE_TARGETS = {
    "normal": 1,
    "multi-skater": 1,
    "crossing/occlusion": 1,
    "small/distant target": 1,
    "pan/zoom": 1,
    "blur/compression": 1,
}
SCENE_ALIASES = {
    "normal": {"normal", "single", "single-skater", "clear"},
    "multi-skater": {"multi-skater", "multi_skater", "crowd"},
    "crossing/occlusion": {"crossing", "occlusion", "crossing/occlusion"},
    "small/distant target": {"small", "distant", "small/distant", "small/distant target"},
    "pan/zoom": {"pan", "zoom", "pan/zoom"},
    "blur/compression": {"blur", "compression", "blur/compression"},
}


def collection_progress(dataset: GoldenDatasetV2, store: GoldenCatalogStore | None = None) -> dict[str, Any]:
    profiles = Counter(event.profile for event in dataset.events)
    profile_progress = [
        {"key": key, "count": profiles[key], "target": target, "missing": max(0, target - profiles[key])}
        for key, target in PROFILE_TARGETS.items()
    ]
    scene_progress = []
    for key, target in SCENE_TARGETS.items():
        count = sum(
            any(
                str(value).strip().lower().replace("_", "-") in SCENE_ALIASES[key]
                for value in [*event.strata, *(challenge.category for challenge in event.challenge_intervals)]
            )
            for event in dataset.events
        )
        scene_progress.append({"key": key, "count": count, "target": target, "missing": max(0, target - count)})

    split_issues = _split_issues(dataset)
    duplicate_issues = _event_duplicate_issues(dataset)
    duplicate_issues.extend(
        flag for flag in GoldenCatalogStore._duplicate_flags(dataset) if flag.startswith("near-duplicate:")
    )
    session_count = len({source.recording_session_id for source in dataset.sources if any(event.source_sha256 == source.source_sha256 for event in dataset.events)})
    delayed, double_reviewed = _review_counts(dataset, store)
    required_delayed = max(4, (len(dataset.events) + 9) // 10) if dataset.events else 4
    ambiguous_required = sum(bool(_rotation_ambiguous(event)) for event in dataset.events)
    crossing_required = sum(
        event.split == "frozen_test" and any(item.category == "crossing" for item in event.challenge_intervals)
        for event in dataset.events
    )
    frame_identity_issues = _frame_identity_issues(dataset)
    valid_events = len(dataset.events) - len({item.split(":", 1)[0] for item in frame_identity_issues})
    requirements = {
        "event_count": {"count": len(dataset.events), "target": 36, "passed": len(dataset.events) == 36},
        "recording_sessions": {"count": session_count, "target": 5, "passed": session_count >= 5},
        "schema_valid": {"count": valid_events, "target": 36, "passed": valid_events == 36},
        "split_grouping": {"issues": split_issues, "passed": not split_issues},
        "duplicates": {"issues": duplicate_issues, "passed": not duplicate_issues},
        "delayed_review": {"count": delayed, "target": required_delayed, "passed": delayed >= required_delayed},
        "ambiguous_rotation_double_review": {"count": double_reviewed["ambiguous"], "target": ambiguous_required, "passed": double_reviewed["ambiguous"] >= ambiguous_required},
        "frozen_crossing_double_review": {"count": double_reviewed["frozen_crossing"], "target": crossing_required, "passed": double_reviewed["frozen_crossing"] >= crossing_required},
        "source_frame_identity": {"issues": frame_identity_issues, "passed": not frame_identity_issues},
    }
    ready = all(item.get("passed", False) for item in requirements.values()) and all(item["missing"] == 0 for item in profile_progress + scene_progress)
    return {
        "gate": "G1",
        "status": "ready_for_evaluator" if ready else "waiting_for_owner_labels",
        "diagnostic_only": True,
        "release_claim": False,
        "profiles": profile_progress,
        "scenes": scene_progress,
        "requirements": requirements,
        "next_best_videos": [
            item["key"] for item in scene_progress if item["missing"]
        ] + [item["key"] for item in profile_progress if item["missing"]],
    }


class PilotEvaluationStore:
    def __init__(self, golden_store: GoldenCatalogStore) -> None:
        self.golden_store = golden_store
        self.root = golden_store.root / "evaluation"
        self.status_path = self.root / "status.json"
        self.private_report_path = self.root / "private-report.json"
        self.sanitized_report_path = self.root / "sanitized-report.json"
        self.diff_path = self.root / "sanitized-diff.json"
        self.gate_path = self.root / "sanitized-gate.json"

    def status(self) -> dict[str, Any]:
        if not self.status_path.exists():
            return {"status": "not_run", "evaluator_version": EVALUATOR_VERSION, "diagnostic_only": True, "message": None}
        return self._read(self.status_path)

    def run(self, bundle: PilotPredictionBundle) -> dict[str, Any]:
        try:
            dataset = self.golden_store.ensure_initialized()
            progress = collection_progress(dataset, self.golden_store)
        except Exception:
            status = {"status": "invalid_labels", "evaluator_version": EVALUATOR_VERSION, "diagnostic_only": True, "message": "Golden labels could not be validated."}
            self._write(self.status_path, status)
            return status
        if progress["status"] != "ready_for_evaluator":
            status = {"status": "waiting_for_owner_labels", "evaluator_version": EVALUATOR_VERSION, "diagnostic_only": True, "message": "G1 needs owner-confirmed real labels before evaluation.", "progress": progress}
            self._write(self.status_path, status)
            return status
        self._write(self.status_path, {"status": "running", "evaluator_version": EVALUATOR_VERSION, "diagnostic_only": True, "message": None})
        try:
            private, sanitized = evaluate_pilot(dataset, bundle)
        except EvaluationLeakageError as exc:
            status = {"status": "failed", "evaluator_version": EVALUATOR_VERSION, "diagnostic_only": True, "message": "Evaluation leakage detected.", "leakage_fields": exc.fields}
            self._write(self.status_path, status)
            return status
        except Exception:
            status = {"status": "invalid_labels", "evaluator_version": EVALUATOR_VERSION, "diagnostic_only": True, "message": "Golden labels or predictions could not be evaluated."}
            self._write(self.status_path, status)
            return status

        previous = self._read(self.sanitized_report_path) if self.sanitized_report_path.exists() else None
        diff = _sanitized_diff(previous, sanitized)
        has_failures = bool(sanitized["failed_events"])
        status_value = "failed" if has_failures else "passed_for_pilot_only"
        gate = {
            "schema_version": "golden-pilot-gate.v1",
            "gate": "G1",
            "status": status_value,
            "diagnostic_only": True,
            "release_claim": False,
            "dataset_fingerprint": sanitized["dataset_fingerprint"],
            "pipeline_fingerprint": sanitized["pipeline_fingerprint"],
            "result_fingerprint": sanitized["deterministic_fingerprint"],
            "failed_event_count": len(sanitized["failed_events"]),
        }
        self._write(self.private_report_path, private)
        self._write(self.sanitized_report_path, sanitized)
        self._write(self.diff_path, diff)
        self._write(self.gate_path, gate)
        status = {"status": status_value, "evaluator_version": EVALUATOR_VERSION, "diagnostic_only": True, "message": "Pilot diagnostic complete.", "result_fingerprint": sanitized["deterministic_fingerprint"]}
        self._write(self.status_path, status)
        return status

    def sanitized_result(self) -> dict[str, Any] | None:
        return self._read(self.sanitized_report_path) if self.sanitized_report_path.exists() else None

    def private_event(self, alias: str) -> dict[str, Any] | None:
        if not self.private_report_path.exists():
            return None
        report = self._read(self.private_report_path)
        for index, item in enumerate(report.get("events", []), 1):
            if alias == f"event-{index:03d}":
                return item
        return None

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        GoldenCatalogStore._atomic_write_json(path, payload)


def _split_issues(dataset: GoldenDatasetV2) -> list[str]:
    issues: list[str] = []
    source_by_hash = {source.source_sha256: source for source in dataset.sources}
    groups: dict[tuple[str, str], set[str | None]] = defaultdict(set)
    for event in dataset.events:
        source = source_by_hash[event.source_sha256]
        groups[("session", source.recording_session_id)].add(event.split)
        groups[("group", source.grouping_id)].add(event.split)
    for (kind, _), splits in sorted(groups.items()):
        if None in splits or len(splits) != 1:
            issues.append(f"{kind}:split-inconsistent")
    return issues


def _event_duplicate_issues(dataset: GoldenDatasetV2) -> list[str]:
    issues: list[str] = []
    grouped: dict[str, list[Any]] = defaultdict(list)
    for event in dataset.events:
        grouped[event.source_sha256].append(event)
    for events in grouped.values():
        for index, left in enumerate(events):
            for right in events[index + 1:]:
                overlap = max(0.0, min(left.end_pts, right.end_pts) - max(left.start_pts, right.start_pts))
                shorter = min(left.end_pts - left.start_pts, right.end_pts - right.start_pts)
                if shorter and overlap / shorter >= 0.8:
                    issues.append(f"{left.event_id}:overlaps-{right.event_id}")
    return sorted(issues)


def _frame_identity_issues(dataset: GoldenDatasetV2) -> list[str]:
    issues: list[str] = []
    for event in dataset.events:
        moments = []
        if event.jump:
            moments.extend(item for item in (event.jump.takeoff, event.jump.apex, event.jump.landing) if item)
        detail = event.step or event.spiral
        if detail and detail.representative_moment:
            moments.append(detail.representative_moment)
        if any(item.source_frame_index is None for item in moments):
            issues.append(f"{event.event_id}:moment-frame-missing")
    for item in [*dataset.tracks, *dataset.poses]:
        if item.source_frame_index is None:
            issues.append(f"{item.event_id}:label-frame-missing")
    return sorted(set(issues))


def _rotation_ambiguous(event: Any) -> bool:
    rotation = event.jump.rotation if event.jump else event.spin.rotation if event.spin else None
    return bool(rotation and (rotation.observability != "observable" or rotation.observed_turns_min != rotation.observed_turns_max))


def _review_counts(dataset: GoldenDatasetV2, store: GoldenCatalogStore | None) -> tuple[int, dict[str, int]]:
    if store is None:
        return 0, {"ambiguous": 0, "frozen_crossing": 0}
    delayed = 0
    double = {"ambiguous": 0, "frozen_crossing": 0}
    for event in dataset.events:
        reviews = store.review_attestations(event.event_id)
        delayed_reviews = [item for item in reviews if item.get("review_type") == "delayed_relabel"]
        first_label_at = _first_label_at(store, event)
        if any(
            datetime.fromisoformat(str(item["reviewed_at"]).replace("Z", "+00:00")) - first_label_at >= timedelta(hours=24)
            for item in delayed_reviews
            if item.get("reviewed_at")
        ):
            delayed += 1
        if _rotation_ambiguous(event) and any(item.get("review_type") == "ambiguous_rotation" for item in reviews):
            double["ambiguous"] += 1
        if event.split == "frozen_test" and any(item.category == "crossing" for item in event.challenge_intervals) and any(item.get("review_type") == "frozen_identity_crossing" for item in reviews):
            double["frozen_crossing"] += 1
    return delayed, double


def _first_label_at(store: GoldenCatalogStore, event: Any) -> datetime:
    timestamps = [event.revision.created_at]
    for snapshot in store.event_history(event.event_id):
        revision = snapshot.get("event", {}).get("revision", {})
        if revision.get("created_at"):
            timestamps.append(datetime.fromisoformat(str(revision["created_at"]).replace("Z", "+00:00")))
    return min(timestamps)


def _sanitized_diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "golden-pilot-sanitized-diff.v1",
        "diagnostic_only": True,
        "previous_fingerprint": previous.get("deterministic_fingerprint") if previous else None,
        "current_fingerprint": current["deterministic_fingerprint"],
        "changed": not previous or previous.get("deterministic_fingerprint") != current["deterministic_fingerprint"],
        "previous_failed_event_count": len(previous.get("failed_events", [])) if previous else None,
        "current_failed_event_count": len(current["failed_events"]),
    }
