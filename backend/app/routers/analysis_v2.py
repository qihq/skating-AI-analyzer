from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.presentation import AnalysisExperienceV2, present_analysis_experience as build_analysis_experience
from app.database import get_session
from app.models import Analysis
from app.services.parent_access import require_parent_pin
from app.analysis_v2.evaluation.source_media import SourceMediaError, probe_source, source_frame_index
from app.analysis_v2.contracts import DetectionProposalDiagnostics
from app.analysis_v2.detection import build_proposal_diagnostics, resolve_provider_config
from app.analysis_v2.evaluation.pilot12_detection import evaluate_pilot12_detection
from app.routers.capabilities import get_runtime_config
from app.analysis_v2.config import RuntimeConfig
from pathlib import Path

router = APIRouter(prefix="/api/analysis", tags=["analysis-v2"])


def present_analysis_experience(analysis: Any, *, diagnostic: bool = False) -> dict[str, Any]:
    timeline = None
    video_path = getattr(analysis, "video_path", None)
    if video_path:
        try:
            path = Path(str(video_path))
            if path.exists():
                timeline = source_frame_index(path, metadata=probe_source(path)).to_timeline()
        except (OSError, SourceMediaError, RuntimeError, ValueError):
            timeline = {"schema_version": "source-timeline.v1", "source_video_hash": "", "duration_sec": None, "width": 1, "height": 1, "rotation_degrees": 0, "timebase": {"numerator": 1, "denominator": 1, "is_vfr": False}, "timestamp_status": "unavailable", "frames": [], "decode_gaps": [], "pts_discontinuities": [], "fingerprint": "unavailable"}
    rendered = build_analysis_experience(analysis, pipeline_mode="shadow" if diagnostic else "legacy", source_timeline=timeline)
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


@router.get("/{analysis_id}/observations", response_model=DetectionProposalDiagnostics)
async def get_detection_observations(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> DetectionProposalDiagnostics:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    # Shadow diagnostics are intentionally detached from legacy/family fields.
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("detection_proposals"), dict):
                return DetectionProposalDiagnostics.model_validate(item["detection_proposals"])
    return build_proposal_diagnostics(config=resolve_provider_config(), status="not_run")


@router.get("/pilot12-detection", response_model=dict[str, Any])
async def get_pilot12_detection_diagnostics(
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> dict[str, Any]:
    await require_parent_pin(session, x_parent_pin)
    fixture = config.runtime_paths["test_data"] / "pilot-12-run-20260801" / "api-analysis-index-live.json"
    if not fixture.exists():
        return {"schema_version": "iteration7-pilot12-detection-evidence.v1", "status": "unavailable", "analysis_count": 0, "candidate_count": 0, "proposal_count": 0, "diagnostic_only": True, "identity_decisions": False}
    return evaluate_pilot12_detection(fixture)
