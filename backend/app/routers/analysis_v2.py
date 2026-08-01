from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.presentation import AnalysisExperienceV2, present_analysis_experience as build_analysis_experience
from app.database import get_session
from app.models import Analysis
from app.services.parent_access import require_parent_pin

router = APIRouter(prefix="/api/analysis", tags=["analysis-v2"])


def present_analysis_experience(analysis: Any, *, diagnostic: bool = False) -> dict[str, Any]:
    rendered = build_analysis_experience(analysis, pipeline_mode="shadow" if diagnostic else "legacy")
    return rendered.model_dump(mode="json")


async def _load_analysis(analysis_id: str, session: AsyncSession) -> Analysis:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="未找到该分析记录。")
    return analysis


@router.get("/{analysis_id}/experience-v2", response_model=AnalysisExperienceV2)
async def get_analysis_experience_v2(
    analysis_id: str,
    session: AsyncSession = Depends(get_session),
) -> AnalysisExperienceV2:
    analysis = await _load_analysis(analysis_id, session)
    return AnalysisExperienceV2.model_validate(present_analysis_experience(analysis, diagnostic=False))


@router.get("/{analysis_id}/experience-v2/diagnostic", response_model=AnalysisExperienceV2)
async def get_analysis_experience_v2_diagnostic(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> AnalysisExperienceV2:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    return AnalysisExperienceV2.model_validate(present_analysis_experience(analysis, diagnostic=True))
