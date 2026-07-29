from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.analysis_v2.config import load_runtime_config
from app.routers import capabilities


def test_public_capability_route_uses_configured_runtime(tmp_path: Path) -> None:
    config = load_runtime_config({}, project_root=tmp_path)

    payload = asyncio.run(capabilities.public_capabilities(config))

    assert payload.public_authority == "legacy"
    assert payload.analysis_experience_v2_enabled is False


def test_advanced_capability_route_requires_parent_pin(tmp_path: Path) -> None:
    config = load_runtime_config({}, project_root=tmp_path)
    session = AsyncMock()

    async def reject_parent(*_args: object) -> None:
        raise HTTPException(status_code=403, detail="parent required")

    with patch.object(capabilities, "require_parent_pin", new=reject_parent):
        with pytest.raises(HTTPException) as error:
            asyncio.run(capabilities.advanced_capabilities(None, session, config))

    assert error.value.status_code == 403


def test_advanced_capability_route_returns_no_private_paths(tmp_path: Path) -> None:
    config = load_runtime_config(
        {"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(tmp_path / "runtime")},
        project_root=tmp_path,
    )
    session = AsyncMock()

    with patch.object(capabilities, "require_parent_pin", new=AsyncMock(return_value=None)):
        payload = asyncio.run(capabilities.advanced_capabilities("1234", session, config))

    assert str(tmp_path) not in payload.model_dump_json()
