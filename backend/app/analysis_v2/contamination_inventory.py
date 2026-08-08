"""Family-state inventory used by the Shadow contamination sentinel.

Iteration 15 permits Shadow orchestration to write only isolated Shadow run,
artifact, review, and audit state.  This module describes the complementary
boundary: every family-facing table, logical job/state surface, generated
artifact tree, setting, provider record, and backup inventory that must remain
unchanged while a Shadow run executes.

The inventory is deliberately provider-driven.  Importing this module does not
open the application database or inspect any runtime path.  Tests and operator
evidence must inject the exact copied database session, logical snapshots, and
filesystem roots that are safe to read.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol


FAMILY_CONTAMINATION_DOMAINS: tuple[str, ...] = (
    "chat_corrections",
    "plans_sessions",
    "growth_compare",
    "skills_xp",
    "memories",
    "chapters_annual",
    "shares_exports_notifications",
    "settings_providers",
    "published_completed_artifacts",
    "backup_inventory",
)

# These names/paths are the complete allowlist for writes intentionally owned
# by Shadow orchestration.  Callers cannot add an arbitrary family table or
# directory to the exclusion set.
ISOLATED_SHADOW_TABLES: frozenset[str] = frozenset(
    {
        "shadow_artifact_records",
        "shadow_audit_events",
        "shadow_review_decisions",
        "shadow_run_records",
        "shadow_stage_checkpoints",
    }
)
ISOLATED_SHADOW_RELATIVE_DIRS: tuple[str, ...] = (
    "shadow/v2/audits",
    "shadow/v2/runs",
)


def _unique_sorted(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


@dataclass(frozen=True)
class FamilyDomainSpec:
    """Sources whose content contributes to one family-domain hash."""

    tables: tuple[str, ...] = ()
    logical: tuple[str, ...] = ()
    files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tables", _unique_sorted(self.tables))
        object.__setattr__(self, "logical", _unique_sorted(self.logical))
        object.__setattr__(self, "files", _unique_sorted(self.files))
        illegal = set(self.tables) & ISOLATED_SHADOW_TABLES
        if illegal:
            raise ValueError(f"family inventory cannot include isolated Shadow tables: {sorted(illegal)}")
        if not (self.tables or self.logical or self.files):
            raise ValueError("a family contamination domain must have at least one source")


# Tables are intentionally allowed to appear in more than one domain.  For
# example, a completed Analysis row is both growth input and a published family
# artifact.  A per-capture cache keeps this overlap from causing repeated SQL.
FAMILY_DOMAIN_SPECS: Mapping[str, FamilyDomainSpec] = {
    "chat_corrections": FamilyDomainSpec(
        tables=("analysis_chat_messages", "analysis_corrections"),
        logical=("chat_delivery_state", "correction_regeneration_history"),
        files=("chat_share_artifacts",),
    ),
    "plans_sessions": FamilyDomainSpec(
        tables=("training_plan_revisions", "training_plans", "training_sessions"),
        logical=("plan_generation_jobs", "session_analysis_links"),
        files=("plan_share_artifacts",),
    ),
    "growth_compare": FamilyDomainSpec(
        tables=("analyses", "analysis_comparisons", "skater_skills", "skaters"),
        logical=("compare_generation_jobs", "growth_aggregate_state"),
        files=("comparison_artifacts",),
    ),
    "skills_xp": FamilyDomainSpec(
        tables=("skater_skills", "skaters", "skill_nodes"),
        logical=("skill_automation_state", "xp_ledger"),
        files=("milestone_share_artifacts",),
    ),
    "memories": FamilyDomainSpec(
        tables=("memory_suggestions", "snowball_memories"),
        logical=("memory_generation_jobs", "memory_review_state"),
        files=("memory_artifacts",),
    ),
    "chapters_annual": FamilyDomainSpec(
        tables=("annual_collections", "annual_exports", "monthly_chapters"),
        logical=("annual_generation_jobs", "chapter_generation_jobs"),
        files=("annual_and_chapter_artifacts",),
    ),
    "shares_exports_notifications": FamilyDomainSpec(
        tables=("annual_exports",),
        logical=("notification_delivery_state", "share_records"),
        files=("share_export_notification_artifacts",),
    ),
    "settings_providers": FamilyDomainSpec(
        tables=("ai_providers", "parent_auth", "skaters"),
        logical=("model_runtime_settings", "provider_activation_state", "ui_preferences"),
        files=("settings_files",),
    ),
    "published_completed_artifacts": FamilyDomainSpec(
        tables=("analyses", "annual_collections", "annual_exports", "monthly_chapters"),
        logical=("published_artifact_index",),
        files=("published_completed_artifacts",),
    ),
    "backup_inventory": FamilyDomainSpec(
        logical=("backup_policy_state",),
        files=("backup_inventory",),
    ),
}


class SnapshotProvider(Protocol):
    """Read-only sources injected into :func:`capture_family_inventory`."""

    def snapshot_table(self, table_name: str) -> Any | Awaitable[Any]: ...

    def snapshot_logical(self, logical_name: str) -> Any | Awaitable[Any]: ...

    def snapshot_files(self, file_name: str) -> Any | Awaitable[Any]: ...


@dataclass(frozen=True)
class FileSnapshotTarget:
    """One file/tree snapshot with optional exact Shadow-only exclusions."""

    path: Path
    excluded_relative_dirs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        normalized = tuple(_normalize_relative_dir(item) for item in self.excluded_relative_dirs)
        validate_shadow_path_exclusions(normalized)
        object.__setattr__(self, "excluded_relative_dirs", tuple(sorted(set(normalized))))


@dataclass
class MappingSnapshotProvider:
    """Small injectable provider for copied fixtures and focused tests.

    Values under ``files`` may be :class:`FileSnapshotTarget`, a ``Path`` (with
    no exclusions), or an already-sanitized logical file inventory.
    """

    tables: Mapping[str, Any] = field(default_factory=dict)
    logical: Mapping[str, Any] = field(default_factory=dict)
    files: Mapping[str, Any] = field(default_factory=dict)

    def snapshot_table(self, table_name: str) -> Any:
        return self.tables.get(table_name, {"state": "not_present", "table": table_name})

    def snapshot_logical(self, logical_name: str) -> Any:
        return self.logical.get(logical_name, {"state": "not_present", "logical": logical_name})

    def snapshot_files(self, file_name: str) -> Any:
        value = self.files.get(file_name, {"state": "not_present", "files": file_name})
        if isinstance(value, FileSnapshotTarget):
            return snapshot_file_target(value)
        if isinstance(value, Path):
            return snapshot_file_target(FileSnapshotTarget(value))
        return value


class SQLAlchemySnapshotProvider(MappingSnapshotProvider):
    """Snapshot provider for an explicitly injected SQLAlchemy async session.

    SQL is limited to identifier-validated ``SELECT *`` statements.  Rows are
    sorted canonically before hashing, so physical row order and query plans do
    not affect the sentinel.  No connection or production path is discovered
    implicitly.
    """

    def __init__(
        self,
        session: Any,
        *,
        logical: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(tables={}, logical=logical or {}, files=files or {})
        self.session = session

    async def snapshot_table(self, table_name: str) -> Any:
        if not _SQL_IDENTIFIER.fullmatch(table_name):
            raise ValueError(f"unsafe SQL table identifier: {table_name!r}")
        # Imported lazily to keep the pure inventory helpers usable without a
        # SQLAlchemy import side effect.
        from sqlalchemy import text

        result = await self.session.execute(text(f'SELECT * FROM "{table_name}"'))
        rows = [dict(row) for row in result.mappings().all()]
        return sorted(rows, key=_canonical_sort_key)


@dataclass(frozen=True)
class FamilyContaminationInventory:
    schema_version: str
    family_hashes: Mapping[str, str]
    component_hashes: Mapping[str, Mapping[str, str]]
    overall_hash: str

    def __post_init__(self) -> None:
        family_hashes = dict(self.family_hashes)
        component_hashes = {name: dict(values) for name, values in self.component_hashes.items()}
        if tuple(family_hashes) != FAMILY_CONTAMINATION_DOMAINS:
            raise ValueError("family inventory must contain every domain in canonical order")
        if tuple(component_hashes) != FAMILY_CONTAMINATION_DOMAINS:
            raise ValueError("component inventory must contain every domain in canonical order")
        object.__setattr__(self, "family_hashes", family_hashes)
        object.__setattr__(self, "component_hashes", component_hashes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "family_hashes": dict(self.family_hashes),
            "component_hashes": {name: dict(values) for name, values in self.component_hashes.items()},
            "overall_hash": self.overall_hash,
        }


@dataclass(frozen=True)
class FamilyContaminationComparison:
    schema_version: str
    unchanged: bool
    changed_domains: tuple[str, ...]
    changed_components: Mapping[str, tuple[str, ...]]
    before_hash: str
    after_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "changed_components", dict(self.changed_components))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "unchanged": self.unchanged,
            "changed_domains": list(self.changed_domains),
            "changed_components": {name: list(values) for name, values in self.changed_components.items()},
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
        }


class FamilyContaminationError(RuntimeError):
    """Raised when a Shadow run changed one or more protected family domains."""


async def capture_family_inventory(provider: SnapshotProvider) -> FamilyContaminationInventory:
    """Capture secret-free hashes for every protected family-state domain."""

    if tuple(FAMILY_DOMAIN_SPECS) != FAMILY_CONTAMINATION_DOMAINS:
        raise RuntimeError("family contamination coverage is incomplete or out of order")

    table_cache: dict[str, str] = {}
    logical_cache: dict[str, str] = {}
    file_cache: dict[str, str] = {}
    family_hashes: dict[str, str] = {}
    component_hashes: dict[str, dict[str, str]] = {}

    for domain in FAMILY_CONTAMINATION_DOMAINS:
        spec = FAMILY_DOMAIN_SPECS[domain]
        components: dict[str, str] = {}
        for table_name in spec.tables:
            if table_name not in table_cache:
                value = await _resolve(provider.snapshot_table(table_name))
                table_cache[table_name] = stable_content_hash(value)
            components[f"table:{table_name}"] = table_cache[table_name]
        for logical_name in spec.logical:
            if logical_name not in logical_cache:
                value = await _resolve(provider.snapshot_logical(logical_name))
                logical_cache[logical_name] = stable_content_hash(value)
            components[f"logical:{logical_name}"] = logical_cache[logical_name]
        for file_name in spec.files:
            if file_name not in file_cache:
                value = await _resolve(provider.snapshot_files(file_name))
                file_cache[file_name] = stable_content_hash(value)
            components[f"file:{file_name}"] = file_cache[file_name]
        component_hashes[domain] = components
        family_hashes[domain] = stable_content_hash(components)

    overall_hash = stable_content_hash(
        {"schema_version": "shadow-family-contamination.v1", "family_hashes": family_hashes}
    )
    return FamilyContaminationInventory(
        schema_version="shadow-family-contamination.v1",
        family_hashes=family_hashes,
        component_hashes=component_hashes,
        overall_hash=overall_hash,
    )


def compare_family_inventories(
    before: FamilyContaminationInventory,
    after: FamilyContaminationInventory,
) -> FamilyContaminationComparison:
    """Locate every family domain/component changed between two captures."""

    if before.schema_version != after.schema_version:
        raise ValueError("cannot compare contamination inventories with different schemas")
    changed_domains = tuple(
        domain
        for domain in FAMILY_CONTAMINATION_DOMAINS
        if before.family_hashes[domain] != after.family_hashes[domain]
    )
    changed_components: dict[str, tuple[str, ...]] = {}
    for domain in changed_domains:
        previous = before.component_hashes[domain]
        current = after.component_hashes[domain]
        names = sorted(set(previous) | set(current))
        changed_components[domain] = tuple(name for name in names if previous.get(name) != current.get(name))
    return FamilyContaminationComparison(
        schema_version="shadow-family-contamination-comparison.v1",
        unchanged=not changed_domains,
        changed_domains=changed_domains,
        changed_components=changed_components,
        before_hash=before.overall_hash,
        after_hash=after.overall_hash,
    )


def assert_family_inventory_unchanged(
    before: FamilyContaminationInventory,
    after: FamilyContaminationInventory,
) -> FamilyContaminationComparison:
    comparison = compare_family_inventories(before, after)
    if not comparison.unchanged:
        detail = ", ".join(
            f"{domain} ({', '.join(comparison.changed_components[domain])})"
            for domain in comparison.changed_domains
        )
        raise FamilyContaminationError(f"Shadow family contamination detected: {detail}")
    return comparison


def validate_shadow_table_exclusions(table_names: Sequence[str]) -> tuple[str, ...]:
    """Reject attempts to hide a non-Shadow table from contamination checks."""

    normalized = tuple(sorted({str(name) for name in table_names}))
    invalid = set(normalized) - ISOLATED_SHADOW_TABLES
    if invalid:
        raise ValueError(f"only isolated Shadow tables may be excluded: {sorted(invalid)}")
    return normalized


def validate_shadow_path_exclusions(relative_dirs: Sequence[str]) -> tuple[str, ...]:
    """Reject path exclusions broader than the versioned Shadow directories."""

    normalized = tuple(sorted({_normalize_relative_dir(item) for item in relative_dirs}))
    invalid = set(normalized) - set(ISOLATED_SHADOW_RELATIVE_DIRS)
    if invalid:
        raise ValueError(f"only isolated Shadow directories may be excluded: {sorted(invalid)}")
    return normalized


def snapshot_file_target(target: FileSnapshotTarget) -> dict[str, Any]:
    """Return a byte-level, relocation-stable inventory for one file/tree."""

    path = target.path
    if not path.exists():
        return {"state": "missing"}
    if path.is_symlink():
        return {"state": "symlink", "target_hash": stable_content_hash(os.readlink(path))}
    if path.is_file():
        return {"state": "file", "size": path.stat().st_size, "sha256": _hash_file(path)}

    excluded = tuple(PurePosixPath(item) for item in target.excluded_relative_dirs)
    entries: list[dict[str, Any]] = []
    root = path.resolve()
    for current_root, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_root)
        relative_root = current.relative_to(root)
        kept_dirs: list[str] = []
        for name in sorted(dir_names):
            relative = (relative_root / name).as_posix()
            if _is_excluded_relative(relative, excluded):
                continue
            child = current / name
            if child.is_symlink():
                entries.append(
                    {
                        "path": relative,
                        "type": "symlink",
                        "target_hash": stable_content_hash(os.readlink(child)),
                    }
                )
                continue
            kept_dirs.append(name)
        dir_names[:] = kept_dirs
        for name in sorted(file_names):
            child = current / name
            relative = (relative_root / name).as_posix()
            if _is_excluded_relative(relative, excluded):
                continue
            if child.is_symlink():
                entries.append(
                    {
                        "path": relative,
                        "type": "symlink",
                        "target_hash": stable_content_hash(os.readlink(child)),
                    }
                )
                continue
            entries.append(
                {"path": relative, "type": "file", "size": child.stat().st_size, "sha256": _hash_file(child)}
            )
    return {"state": "directory", "entries": entries}


def stable_content_hash(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


async def _resolve(value: Any | Awaitable[Any]) -> Any:
    return await value if inspect.isawaitable(value) else value


def _canonical(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset)):
        items = [_canonical(item) for item in value]
        return sorted(items, key=_canonical_sort_key)
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _normalize_relative_dir(value: str) -> str:
    raw = str(value).strip().replace("\\", "/").strip("/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"invalid relative directory exclusion: {value!r}")
    return path.as_posix()


def _is_excluded_relative(relative: str, excluded: Sequence[PurePosixPath]) -> bool:
    candidate = PurePosixPath(relative)
    return any(candidate == root or root in candidate.parents for root in excluded)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


_SQL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
