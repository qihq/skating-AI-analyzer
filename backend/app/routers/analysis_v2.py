from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.presentation import AnalysisExperienceV2, build_pose_detail_resource, present_analysis_experience as build_analysis_experience
from app.database import get_session
from app.models import Analysis
from app.services.parent_access import require_parent_pin
from app.analysis_v2.evaluation.source_media import SourceMediaError, probe_source, source_frame_index
from app.analysis_v2.contracts import DetectionProposalDiagnostics, IdentityAnchor, IdentityAnchorRevision, IdentityTimeline, PoseAvailabilitySummary, PoseDetailResource, PoseObservation
from app.analysis_v2.identity import create_anchor_revision, immutable_template_fingerprint, replace_causal_interval
from app.analysis_v2.detection import build_proposal_diagnostics, resolve_provider_config
from app.analysis_v2.contracts import IdentityTimeline
from app.analysis_v2.evaluation.pilot12_detection import evaluate_pilot12_detection
from app.routers.capabilities import get_runtime_config
from app.analysis_v2.config import RuntimeConfig
from pathlib import Path

router = APIRouter(prefix="/api/analysis", tags=["analysis-v2"])


class IdentityAnchorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_frame_index: int = Field(ge=0)
    pts_sec: float = Field(ge=0)
    bbox: tuple[float, float, float, float]
    annotator: str = Field(min_length=1, max_length=160)
    quality_score: float = Field(ge=0, le=1)
    expected_revision: int = Field(default=1, ge=1)
    invalidated_interval: tuple[float, float] | None = None


class IdentityRevisionPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["identity-revision-preview.v1"] = "identity-revision-preview.v1"
    analysis_id: str
    current_revision: int
    next_revision: int
    invalidated_intervals: tuple[tuple[float, float], ...] = ()
    anchor: IdentityAnchor
    identity: IdentityTimeline | None = None
    diagnostic_only: Literal[True] = True


class IdentityAnchorConfirmRequest(IdentityAnchorRequest):
    preview_revision: int = Field(ge=2)
    confirmation: Literal["confirm_identity_anchor_revision"]


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
    identity = None
    pose_summary = None
    stored = getattr(analysis, "processing_logs", None)
    if diagnostic and isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("identity_timeline"), dict):
                identity = IdentityTimeline.model_validate(item["identity_timeline"])
            if isinstance(item, dict) and isinstance(item.get("pose_summary"), dict):
                pose_summary = PoseAvailabilitySummary.model_validate(item["pose_summary"])
            if identity is not None and pose_summary is not None:
                break
    rendered = build_analysis_experience(analysis, pipeline_mode="shadow" if diagnostic else "legacy", source_timeline=timeline, identity=identity, pose=pose_summary)
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


@router.get("/{analysis_id}/identity", response_model=IdentityTimeline | None)
async def get_identity_timeline(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> IdentityTimeline | None:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("identity_timeline"), dict):
                return IdentityTimeline.model_validate(item["identity_timeline"])
    return None


@router.get("/{analysis_id}/pose-v2/detail", response_model=PoseDetailResource)
async def get_pose_v2_detail(
    analysis_id: str,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> PoseDetailResource:
    """Return raw V2 joints only from the parent-authorized diagnostic resource."""
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    stored = getattr(analysis, "processing_logs", None)
    if isinstance(stored, list):
        for item in reversed(stored):
            if not isinstance(item, dict) or not isinstance(item.get("pose_v2_detail"), dict):
                continue
            detail = item["pose_v2_detail"]
            observations = tuple(PoseObservation.model_validate(value) for value in detail.get("observations", ()))
            summary = PoseAvailabilitySummary.model_validate(detail.get("summary", {}))
            return build_pose_detail_resource(
                analysis_id=analysis_id,
                source_pipeline_fingerprint=str(detail.get("source_pipeline_fingerprint", "v2:unfingerprinted")),
                observations=observations,
                summary=summary,
                authority="v2",
            )
    raise HTTPException(status_code=404, detail="V2 pose detail is unavailable")


@router.post("/{analysis_id}/identity/anchors/preview", response_model=IdentityRevisionPreview, status_code=status.HTTP_200_OK)
async def preview_identity_anchor_revision(
    analysis_id: str,
    payload: IdentityAnchorRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> IdentityRevisionPreview:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    stored = getattr(analysis, "processing_logs", None)
    timeline: IdentityTimeline | None = None
    if isinstance(stored, list):
        for item in reversed(stored):
            if isinstance(item, dict) and isinstance(item.get("identity_timeline"), dict):
                timeline = IdentityTimeline.model_validate(item["identity_timeline"])
                break
    anchor = IdentityAnchor(anchor_id=f"{analysis_id}:anchor:{payload.source_frame_index}:{payload.expected_revision + 1}", source_frame_index=payload.source_frame_index, pts_sec=payload.pts_sec, bbox=payload.bbox, annotator=payload.annotator, quality_score=payload.quality_score, revision=payload.expected_revision + 1, provenance="manual_revision", template_fingerprint="pending")
    anchor = anchor.model_copy(update={"template_fingerprint": immutable_template_fingerprint(anchor)})
    invalidated = (payload.invalidated_interval,) if payload.invalidated_interval else ()
    revision = create_anchor_revision(revision=payload.expected_revision + 1, parent_revision=payload.expected_revision, anchor_ids=(anchor.anchor_id,), invalidated_intervals=invalidated, created_by=payload.annotator)
    return IdentityRevisionPreview(analysis_id=analysis_id, current_revision=payload.expected_revision, next_revision=revision.revision, invalidated_intervals=revision.invalidated_intervals, anchor=anchor, identity=timeline)


@router.post("/{analysis_id}/identity/anchors/confirm", response_model=IdentityRevisionPreview, status_code=status.HTTP_201_CREATED)
async def confirm_identity_anchor_revision(
    analysis_id: str,
    payload: IdentityAnchorConfirmRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> IdentityRevisionPreview:
    await require_parent_pin(session, x_parent_pin)
    analysis = await _load_analysis(analysis_id, session)
    stored = getattr(analysis, "processing_logs", None)
    current_revision = payload.expected_revision
    if isinstance(stored, list):
        revisions = [item.get("identity_anchor_revision", {}).get("revision") for item in stored if isinstance(item, dict) and isinstance(item.get("identity_anchor_revision"), dict)]
        if revisions:
            current_revision = max(current_revision, max(int(value) for value in revisions if value is not None))
    if payload.preview_revision != current_revision + 1:
        raise HTTPException(status_code=409, detail={"code": "identity_revision_conflict", "current_revision": current_revision})
    anchor = IdentityAnchor(anchor_id=f"{analysis_id}:anchor:{payload.source_frame_index}:{payload.preview_revision}", source_frame_index=payload.source_frame_index, pts_sec=payload.pts_sec, bbox=payload.bbox, annotator=payload.annotator, quality_score=payload.quality_score, revision=payload.preview_revision, provenance="manual_revision", template_fingerprint="pending")
    anchor = anchor.model_copy(update={"template_fingerprint": immutable_template_fingerprint(anchor)})
    invalidated = (payload.invalidated_interval,) if payload.invalidated_interval else ()
    revision = create_anchor_revision(revision=payload.preview_revision, parent_revision=current_revision, anchor_ids=(anchor.anchor_id,), invalidated_intervals=invalidated, created_by=payload.annotator, provenance="manual_confirmation")
    logs = list(stored) if isinstance(stored, list) else []
    logs.append({"identity_anchor": anchor.model_dump(mode="json"), "identity_anchor_revision": revision.model_dump(mode="json"), "identity_audit": {"action": "confirm", "legacy_mutation": False, "invalidation_scope": list(invalidated)}})
    analysis.processing_logs = logs
    session.add(analysis)
    await session.commit()
    return IdentityRevisionPreview(analysis_id=analysis_id, current_revision=current_revision, next_revision=revision.revision, invalidated_intervals=revision.invalidated_intervals, anchor=anchor, identity=None)


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
