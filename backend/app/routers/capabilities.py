from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.capabilities import (
    AdvancedRuntimeCapabilities,
    RuntimeCapabilities,
    build_advanced_capabilities,
    build_public_capabilities,
)
from app.analysis_v2.config import RuntimeConfig
from app.database import get_session
from app.services.parent_access import require_parent_pin


router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])
_runtime_config: RuntimeConfig | None = None


def configure_runtime_capabilities(config: RuntimeConfig) -> None:
    global _runtime_config
    _runtime_config = config


def get_runtime_config() -> RuntimeConfig:
    if _runtime_config is None:
        raise RuntimeError("Runtime capabilities were not configured during application startup.")
    return _runtime_config


@router.get("", response_model=RuntimeCapabilities)
async def public_capabilities(config: RuntimeConfig = Depends(get_runtime_config)) -> RuntimeCapabilities:
    return build_public_capabilities(config)


@router.get("/advanced", response_model=AdvancedRuntimeCapabilities)
async def advanced_capabilities(
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> AdvancedRuntimeCapabilities:
    await require_parent_pin(session, x_parent_pin)
    return build_advanced_capabilities(config)
