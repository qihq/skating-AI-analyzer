from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.analysis_v2.evaluation.golden_schema import (
    GOLDEN_DATASET_SCHEMA_VERSION,
    GOLDEN_SUPPORTED_SCHEMA_VERSIONS,
    GoldenContractError,
    GoldenDatasetV2,
)


class GoldenRevisionConflict(GoldenContractError):
    """Raised when a caller attempts to overwrite a newer catalog revision."""


class GoldenCatalogStore:
    """A private filesystem store; no source reference leaves this boundary."""

    def __init__(self, golden_root: Path) -> None:
        self.root = golden_root / "v2"
        self.manifest_path = self.root / "manifest.json"
        self.videos_dir = self.root / "videos"
        self.labels_dir = self.root / "labels"

    def ensure_initialized(self) -> GoldenDatasetV2:
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.labels_dir.mkdir(parents=True, exist_ok=True)
        if self.manifest_path.exists():
            return self.read()
        dataset = GoldenDatasetV2(
            dataset_id="golden-v2-private-catalog",
            revision={"revision": 1, "annotator_alias": "system", "provenance": "created"},
        )
        self._atomic_write_json(self.manifest_path, self._manifest_payload(dataset))
        return dataset

    def read(self) -> GoldenDatasetV2:
        if not self.manifest_path.exists():
            return self.ensure_initialized()
        raw = self._read_json(self.manifest_path)
        version = raw.get("schema_version")
        if version not in GOLDEN_SUPPORTED_SCHEMA_VERSIONS:
            raise GoldenContractError(f"Unsupported Golden V2 schema version: {version!r}")
        event_ids = raw.pop("event_ids", [])
        if not isinstance(event_ids, list) or not all(isinstance(item, str) for item in event_ids):
            raise GoldenContractError("Golden manifest has an invalid event index")
        events: list[dict[str, Any]] = []
        tracks: list[dict[str, Any]] = []
        poses: list[dict[str, Any]] = []
        for event_id in event_ids:
            label = self._read_json(self.labels_dir / f"{event_id}.json")
            events.append(label["event"])
            tracks.extend(label.get("tracks", []))
            poses.extend(label.get("poses", []))
        raw["events"] = events
        raw["tracks"] = tracks
        raw["poses"] = poses
        try:
            return GoldenDatasetV2.model_validate(raw)
        except ValidationError as exc:
            raise GoldenContractError(f"Invalid Golden V2 catalog: {exc}") from exc

    def save(self, dataset: GoldenDatasetV2, *, expected_revision: int) -> GoldenDatasetV2:
        current = self.ensure_initialized()
        if current.revision.revision != expected_revision:
            raise GoldenRevisionConflict(
                f"Golden catalog changed; expected revision {expected_revision}, current revision is {current.revision.revision}."
            )
        if dataset.schema_version != GOLDEN_DATASET_SCHEMA_VERSION:
            raise GoldenContractError("Only the current Golden V2 schema can be persisted")
        if dataset.revision.revision != expected_revision + 1:
            raise GoldenContractError("Saved catalog revision must advance exactly once")
        if dataset.revision.parent_revision != expected_revision:
            raise GoldenContractError("Saved catalog revision must identify its parent")
        self.root.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(exist_ok=True)
        self.labels_dir.mkdir(exist_ok=True)
        for event in dataset.events:
            payload = {
                "schema_version": dataset.schema_version,
                "event": event.model_dump(mode="json"),
                "tracks": [item.model_dump(mode="json") for item in dataset.tracks if item.event_id == event.event_id],
                "poses": [item.model_dump(mode="json") for item in dataset.poses if item.event_id == event.event_id],
            }
            self._atomic_write_json(self.labels_dir / f"{event.event_id}.json", payload)
        self._atomic_write_json(self.manifest_path, self._manifest_payload(dataset))
        return dataset

    def catalog_summary(self) -> dict[str, Any]:
        try:
            dataset = self.ensure_initialized()
        except GoldenContractError as exc:
            status = "schema-incompatible" if "Unsupported Golden V2 schema" in str(exc) else "invalid-source"
            return {
                "dataset_id": "golden-v2-private-catalog",
                "schema_version": GOLDEN_DATASET_SCHEMA_VERSION,
                "revision": 0,
                "status": status,
                "source_count": 0,
                "event_count": 0,
                "profile_counts": {},
                "observability_counts": {},
                "strata_counts": {},
                "duplicate_sources": [],
            }
        source_counts = Counter(event.profile for event in dataset.events)
        observability = Counter(event.observability for event in dataset.events)
        strata = Counter(stratum for event in dataset.events for stratum in event.strata)
        duplicates = self._duplicate_flags(dataset)
        return {
            "dataset_id": dataset.dataset_id,
            "schema_version": dataset.schema_version,
            "revision": dataset.revision.revision,
            "status": "empty" if not dataset.events else "ready",
            "source_count": len(dataset.sources),
            "event_count": len(dataset.events),
            "profile_counts": dict(sorted(source_counts.items())),
            "observability_counts": dict(sorted(observability.items())),
            "strata_counts": dict(sorted(strata.items())),
            "duplicate_sources": duplicates,
        }

    def sanitized_export(self) -> dict[str, Any]:
        summary = self.catalog_summary()
        # This intentionally returns no source references, filenames, frame data, identities, or labels.
        return {
            "schema_version": "golden-sanitized-summary.v1",
            "dataset_id": summary["dataset_id"],
            "golden_schema_version": summary["schema_version"],
            "revision": summary["revision"],
            "aggregate": {
                "source_count": summary["source_count"],
                "event_count": summary["event_count"],
                "profile_counts": summary["profile_counts"],
                "observability_counts": summary["observability_counts"],
                "strata_counts": summary["strata_counts"],
            },
            "redacted_aliases": ["source-001" for _ in range(summary["source_count"])],
            "gate_template": {"gate": "G1", "status": "not-run", "required_new_events": 36},
        }

    @staticmethod
    def _manifest_payload(dataset: GoldenDatasetV2) -> dict[str, Any]:
        return {
            "dataset_id": dataset.dataset_id,
            "schema_version": dataset.schema_version,
            "revision": dataset.revision.model_dump(mode="json"),
            "sources": [source.model_dump(mode="json") for source in dataset.sources],
            "event_ids": [event.event_id for event in dataset.events],
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GoldenContractError(f"Golden catalog data is unreadable: {path.name}") from exc
        if not isinstance(loaded, dict):
            raise GoldenContractError(f"Golden catalog data is invalid: {path.name}")
        return loaded

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _duplicate_flags(dataset: GoldenDatasetV2) -> list[str]:
        flags: list[str] = []
        sessions: dict[str, list[str]] = {}
        fingerprints: dict[str, list[str]] = {}
        for source in dataset.sources:
            sessions.setdefault(source.recording_session_id, []).append(source.redacted_alias)
            if source.perceptual_fingerprint:
                fingerprints.setdefault(source.perceptual_fingerprint, []).append(source.redacted_alias)
        for aliases in sessions.values():
            if len(aliases) > 1:
                flags.extend(f"same-session:{alias}" for alias in sorted(aliases))
        for aliases in fingerprints.values():
            if len(aliases) > 1:
                flags.extend(f"near-duplicate:{alias}" for alias in sorted(aliases))
        return flags
