from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.config import RuntimeConfig
from app.analysis_v2.evaluation.golden_store import GoldenCatalogStore
from app.database import get_session
from app.routers.capabilities import get_runtime_config
from app.services.parent_access import require_parent_pin


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenCatalogSummary(_StrictResponse):
    dataset_id: str
    schema_version: Literal["golden-dataset.v2"]
    revision: int
    status: Literal["empty", "ready", "invalid-source", "schema-incompatible"]
    source_count: int
    event_count: int
    profile_counts: list["GoldenCount"]
    observability_counts: list["GoldenCount"]
    strata_counts: list["GoldenCount"]
    duplicate_sources: list[str]


class GoldenSchemaResponse(_StrictResponse):
    schema_version: Literal["golden-dataset.v2"]
    supported_schema_versions: list[str]
    migration_policy: Literal["future-v2-only"]
    historical_debug_pool: Literal["not-imported"]


class GoldenAggregateCounts(_StrictResponse):
    source_count: int
    event_count: int
    profile_counts: list["GoldenCount"]
    observability_counts: list["GoldenCount"]
    strata_counts: list["GoldenCount"]


class GoldenCount(_StrictResponse):
    key: str
    count: int


class GoldenGateTemplate(_StrictResponse):
    gate: Literal["G1"]
    status: Literal["not-run"]
    required_new_events: int


class GoldenSanitizedExport(_StrictResponse):
    schema_version: Literal["golden-sanitized-summary.v1"]
    dataset_id: str
    golden_schema_version: Literal["golden-dataset.v2"]
    revision: int
    aggregate: GoldenAggregateCounts
    redacted_aliases: list[str]
    gate_template: GoldenGateTemplate


router = APIRouter(prefix="/api/golden/v2", tags=["golden-v2"])


def get_golden_store(config: RuntimeConfig = Depends(get_runtime_config)) -> GoldenCatalogStore:
    return GoldenCatalogStore(config.runtime_paths["golden"])


async def require_golden_parent(
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> None:
    await require_parent_pin(session, x_parent_pin)


@router.get("/catalog", response_model=GoldenCatalogSummary)
async def get_golden_catalog(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenCatalogSummary:
    return _catalog_response(store.catalog_summary())


@router.get("/schema", response_model=GoldenSchemaResponse)
async def get_golden_schema(_: None = Depends(require_golden_parent)) -> GoldenSchemaResponse:
    return GoldenSchemaResponse(
        schema_version="golden-dataset.v2",
        supported_schema_versions=["golden-dataset.v2"],
        migration_policy="future-v2-only",
        historical_debug_pool="not-imported",
    )


@router.get("/revisions/current", response_model=GoldenCatalogSummary)
async def get_golden_revision(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenCatalogSummary:
    return _catalog_response(store.catalog_summary())


@router.get("/sanitized-export", response_model=GoldenSanitizedExport)
async def get_golden_sanitized_export(
    _: None = Depends(require_golden_parent), store: GoldenCatalogStore = Depends(get_golden_store)
) -> GoldenSanitizedExport:
    payload = store.sanitized_export()
    aggregate = payload["aggregate"]
    return GoldenSanitizedExport(
        schema_version="golden-sanitized-summary.v1",
        dataset_id=str(payload["dataset_id"]),
        golden_schema_version="golden-dataset.v2",
        revision=int(payload["revision"]),
        aggregate=GoldenAggregateCounts(
            source_count=int(aggregate["source_count"]),
            event_count=int(aggregate["event_count"]),
            profile_counts=[GoldenCount(key=key, count=count) for key, count in aggregate["profile_counts"].items()],
            observability_counts=[GoldenCount(key=key, count=count) for key, count in aggregate["observability_counts"].items()],
            strata_counts=[GoldenCount(key=key, count=count) for key, count in aggregate["strata_counts"].items()],
        ),
        redacted_aliases=list(payload["redacted_aliases"]),
        gate_template=GoldenGateTemplate.model_validate(payload["gate_template"]),
    )


def _catalog_response(payload: dict[str, object]) -> GoldenCatalogSummary:
    return GoldenCatalogSummary(
        dataset_id=str(payload["dataset_id"]),
        schema_version="golden-dataset.v2",
        revision=int(payload["revision"]),
        status=str(payload["status"]),
        source_count=int(payload["source_count"]),
        event_count=int(payload["event_count"]),
        profile_counts=_counts(payload["profile_counts"]),
        observability_counts=_counts(payload["observability_counts"]),
        strata_counts=_counts(payload["strata_counts"]),
        duplicate_sources=list(payload["duplicate_sources"]),
    )


def _counts(value: object) -> list[GoldenCount]:
    if not isinstance(value, dict):
        return []
    return [GoldenCount(key=str(key), count=int(count)) for key, count in value.items()]
