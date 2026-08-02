import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.analysis_v2.config import load_runtime_config
from app.routers import analysis_v2


def test_observation_api_requires_parent_pin() -> None:
    session = AsyncMock()
    async def reject(*_args: object) -> None:
        raise HTTPException(status_code=403, detail="parent required")
    with patch.object(analysis_v2, "require_parent_pin", new=reject):
        try:
            asyncio.run(analysis_v2.get_pilot12_detection_diagnostics(None, session, load_runtime_config({}, project_root=Path.cwd())))
        except HTTPException as error:
            assert error.status_code == 403
        else:
            raise AssertionError("parent authorization was not enforced")


def test_pilot12_observation_api_is_diagnostic_only(tmp_path: Path) -> None:
    config = load_runtime_config({"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(tmp_path)}, project_root=tmp_path)
    session = AsyncMock()
    with patch.object(analysis_v2, "require_parent_pin", new=AsyncMock(return_value=None)):
        payload = asyncio.run(analysis_v2.get_pilot12_detection_diagnostics("1234", session, config))
    assert payload["diagnostic_only"] is True
    assert payload["identity_decisions"] is False
