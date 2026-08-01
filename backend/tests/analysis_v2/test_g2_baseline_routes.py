from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.routers import golden_v2


class Store:
    def ensure_initialized(self):
        return object()


class G2Store:
    def public_status(self, dataset):
        assert dataset is not None
        return {
            "schema_version": "golden-g2-status.v1",
            "gate": "G2",
            "status": "collecting",
            "event_count": 12,
            "required_event_range": [60, 80],
            "distribution": {"profiles": {"jump": 6}, "splits": {"unassigned": 12}, "strata": {}, "recording_session_count": 4},
            "release_claim": False,
        }

    def freeze(self, dataset, *, legacy_pipeline_fingerprint):
        assert dataset is not None
        return {
            "status": "frozen_waiting_for_baseline",
            "dataset_revision": 51,
            "dataset_fingerprint": "dataset:123",
            "legacy_pipeline_fingerprint": legacy_pipeline_fingerprint,
            "distribution": {"profiles": {}, "splits": {}, "strata": {}, "recording_session_count": 5},
        }


def test_g2_status_is_parent_authorized_and_sanitized() -> None:
    result = asyncio.run(golden_v2.get_g2_status(None, Store(), G2Store()))

    assert result.status == "collecting"
    assert result.event_count == 12
    assert result.release_claim is False
    assert "membership" not in result.model_dump_json()


def test_g2_freeze_requires_explicit_confirmation() -> None:
    payload = golden_v2.G2FreezeRequest(
        confirmation="review_only",
        legacy_pipeline_fingerprint="legacy:v5.2.307",
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(golden_v2.freeze_g2_dataset(payload, None, Store(), G2Store()))

    assert error.value.status_code == 422


def test_g2_routes_still_use_parent_dependency() -> None:
    session = AsyncMock()

    async def reject(*_args: object) -> None:
        raise HTTPException(status_code=403, detail="parent required")

    original = golden_v2.require_parent_pin
    golden_v2.require_parent_pin = reject
    try:
        with pytest.raises(HTTPException) as error:
            asyncio.run(golden_v2.require_golden_parent(None, session))
    finally:
        golden_v2.require_parent_pin = original

    assert error.value.status_code == 403
