from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_v2.config import PipelineMode, RuntimeConfig
from app.analysis_v2.shadow_contracts import (
    SHADOW_SCHEMA_VERSION,
    ShadowArtifactResponse,
    ShadowDiffResponse,
    ShadowCleanupResponse,
    ShadowDecisionResponse,
    ShadowFingerprintUpdateRequest,
    ShadowNoteRequest,
    ShadowNoteResponse,
    ShadowReviewDecision,
    ShadowReviewDecisionRequest,
    ShadowRunListResponse,
    ShadowRunRecord,
    ShadowRunRequest,
    ShadowRunResponse,
    ShadowStatusResponse,
    ShadowRetryRequest,
    ShadowRecoveryResponse,
    utc_now,
)
from app.analysis_v2.shadow_store import ShadowArtifactStore, ShadowRunNotFound, ShadowStoreError
from app.analysis_v2.shadow_execution import get_shadow_execution_coordinator
from app.analysis_v2.orchestration import legacy_stage_fingerprints_from_snapshot
from app.database import get_session
from app.models import Analysis
from app.routers.capabilities import get_runtime_config
from app.services.parent_access import require_parent_pin


router = APIRouter(prefix="/api/shadow", tags=["shadow-orchestration"])
logger = logging.getLogger(__name__)


class ShadowCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SHADOW_SCHEMA_VERSION
    enabled: bool
    runtime_mode: PipelineMode
    public_authority: str = "legacy"
    diagnostic_only: bool = True
    writes_user_data: bool = False
    isolated_runtime: bool
    stages: list[str]


def get_shadow_store(config: RuntimeConfig = Depends(get_runtime_config)) -> ShadowArtifactStore:
    try:
        return ShadowArtifactStore(config)
    except ShadowStoreError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


async def require_shadow_parent(
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> None:
    await require_parent_pin(session, x_parent_pin)


def _not_found(exc: ShadowRunNotFound) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _safe_ephemeral_source_path(raw: Any, config: RuntimeConfig | Any, *, runtime_root: Path | None = None) -> str | None:
    """Return a source path only while executing; never put it in a manifest.

    Parent Shadow work is restricted to the isolated V2 runtime.  A legacy
    database row may still point at a production/upload path, so those paths
    are deliberately omitted and the deterministic legacy adapter uses the
    detached frame evidence instead.
    """
    if not raw:
        return None
    try:
        candidate = Path(str(raw)).expanduser().resolve()
        root = runtime_root or getattr(config, "runtime_root", None)
        if root is None or not candidate.is_file() or not candidate.is_relative_to(Path(root).resolve()):
            return None
        return str(candidate)
    except (OSError, ValueError, TypeError):
        return None


async def _legacy_execution_inputs(
    analysis_id: str,
    *,
    session: AsyncSession | Any = None,
    config: RuntimeConfig | Any = None,
    source_video_hash: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build a detached legacy snapshot and ephemeral source identity.

    The API remains useful for a run created from a hash-only fixture: if the
    analysis row is absent (or this optional read fails), a minimal payload is
    returned.  This read is never part of the legacy completion transaction
    and no row is mutated.
    """
    analysis: Analysis | None = None
    getter = getattr(session, "get", None)
    if callable(getter):
        try:
            analysis = await getter(Analysis, str(analysis_id))
        except Exception:  # noqa: BLE001
            # Parent diagnostics must fail soft when the isolated DB is not
            # initialized in a standalone/API fixture.
            logger.debug("Could not load legacy analysis %s for Shadow", analysis_id, exc_info=True)

    if analysis is None:
        digest = str(source_video_hash or "").strip()
        identity = {"analysis_id": str(analysis_id)}
        if digest:
            identity["video_hash"] = digest
        return (
            {
                "schema_version": "legacy-analysis-snapshot.v1",
                "analysis_id": str(analysis_id),
                "authority": "legacy",
                "status": "completed",
                "pipeline_version": "legacy-shadow-api.v1",
                "analysis_profile": "unknown",
                "source_fps": 30.0,
                "action_window_start": 0.0,
                "action_window_end": 1.0,
                "frame_motion_scores": {},
                "target_lock": {},
                "pose_data": {},
                "vision_path_a": {},
                "vision_path_b": {},
                "cross_validation": {},
                "bio_data": {},
                "report": {},
            },
            identity,
        )

    # Keep the shape aligned with the post-commit legacy dispatch snapshot,
    # while explicitly excluding the raw source path from the detached payload.
    field_names = (
        "action_type",
        "action_subtype",
        "analysis_profile",
        "pipeline_version",
        "report",
        "vision_structured",
        "vision_path_a",
        "vision_path_b",
        "cross_validation",
        "pose_data",
        "bio_data",
        "frame_motion_scores",
        "processing_timings",
        "target_lock",
        "action_window_start",
        "action_window_end",
        "source_fps",
        "is_slow_motion",
        "force_score",
        "note",
    )
    snapshot: dict[str, Any] = {
        "schema_version": "legacy-analysis-snapshot.v1",
        "analysis_id": str(analysis.id),
        "authority": "legacy",
        "status": "completed" if str(getattr(analysis, "status", "")) == "completed" else str(getattr(analysis, "status", "unknown")),
    }
    for name in field_names:
        value = getattr(analysis, name, None)
        snapshot[name] = copy.deepcopy(value)

    identity: dict[str, str] = {"analysis_id": str(analysis.id)}
    digest = str(source_video_hash or "").strip()
    motion = getattr(analysis, "frame_motion_scores", None)
    if not digest and isinstance(motion, Mapping):
        video_identity = motion.get("video_identity")
        if isinstance(video_identity, Mapping):
            digest = str(video_identity.get("sha256") or "").strip()
    if digest:
        identity["video_hash"] = digest
    path = _safe_ephemeral_source_path(getattr(analysis, "video_path", None), config)
    if path:
        identity["source_path"] = path
    return snapshot, identity


@router.get("/capabilities", response_model=ShadowCapabilitiesResponse)
async def shadow_capabilities(
    _: None = Depends(require_shadow_parent), config: RuntimeConfig = Depends(get_runtime_config)
) -> ShadowCapabilitiesResponse:
    from app.analysis_v2.shadow_contracts import SHADOW_STAGES

    return ShadowCapabilitiesResponse(
        enabled=config.pipeline_mode is PipelineMode.SHADOW and config.is_isolated,
        runtime_mode=config.pipeline_mode,
        isolated_runtime=config.is_isolated,
        stages=list(SHADOW_STAGES),
    )


@router.post("/runs", response_model=ShadowRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_shadow_run(
    payload: ShadowRunRequest,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
    session: AsyncSession = Depends(get_session),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> ShadowRunResponse:
    try:
        run = store.create(payload)
    except ShadowStoreError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    # Persist first, then enqueue detached execution.  A duplicate request
    # joins the same coordinator task and never launches another stage graph.
    legacy_result, source_identity = await _legacy_execution_inputs(
        payload.analysis_id,
        session=session,
        config=config,
        source_video_hash=payload.source_video_hash or payload.source_fingerprint,
    )
    if not run.legacy_stage_fingerprints:
        run = store.attach_legacy_stage_fingerprints(
            run.run_id,
            legacy_stage_fingerprints_from_snapshot(legacy_result),
        )
    try:
        coordinator = get_shadow_execution_coordinator(config, store=store)
        receipt = await coordinator.submit(run.run_id, legacy_result, source_identity=source_identity)
        if not receipt.accepted:
            logger.warning("Shadow run %s was not accepted by local queue: %s", run.run_id, receipt.reason)
    except Exception:  # noqa: BLE001
        # The run remains inspectable/recoverable in its isolated manifest;
        # parent API creation must not turn into a legacy-side failure.
        logger.exception("Shadow run %s execution scheduling failed", run.run_id)
    return ShadowRunResponse(run=run)


@router.get("/analyses/{analysis_id}/runs", response_model=ShadowRunListResponse)
async def list_shadow_runs(
    analysis_id: str,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> ShadowRunListResponse:
    return ShadowRunListResponse(analysis_id=analysis_id, runs=store.list_for_analysis(analysis_id))


@router.get("/runs/{run_id}", response_model=ShadowRunResponse)
async def get_shadow_run(
    run_id: str,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> ShadowRunResponse:
    try:
        return ShadowRunResponse(run=store.read(run_id))
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/runs/{run_id}/status", response_model=ShadowStatusResponse)
async def get_shadow_status(
    run_id: str,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> ShadowStatusResponse:
    try:
        run = store.read(run_id)
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    return ShadowStatusResponse(status=run.status, runtime_mode=config.pipeline_mode, run=run)


@router.get("/runs/{run_id}/diff", response_model=ShadowDiffResponse)
async def get_shadow_diff(
    run_id: str,
    compare_to: str | None = Query(default=None),
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> ShadowDiffResponse:
    try:
        run = store.read(run_id)
        first_divergent_stage, stages = store.stage_diffs(run_id, compare_to)
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    return ShadowDiffResponse(
        run_id=run.run_id,
        analysis_id=run.analysis_id,
        first_divergent_stage=first_divergent_stage,
        stages=stages,
        downstream=run.downstream,
    )


@router.get("/runs/{run_id}/artifacts", response_model=list[Any])
async def list_shadow_artifacts(
    run_id: str,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> list[Any]:
    try:
        run = store.read(run_id)
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    return run.artifacts


@router.get("/runs/{run_id}/artifacts/{artifact_id}", response_model=ShadowArtifactResponse)
async def get_shadow_artifact(
    run_id: str,
    artifact_id: str,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> ShadowArtifactResponse:
    try:
        run = store.read(run_id)
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    reference = next((item for item in run.artifacts if item.artifact_id == artifact_id), None)
    if reference is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shadow artifact reference was not found")
    return ShadowArtifactResponse(run_id=run.run_id, analysis_id=run.analysis_id, artifact=reference, content=store.artifact_content(reference))


@router.post("/runs/{run_id}/retry", response_model=ShadowRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_shadow_run(
    run_id: str,
    payload: ShadowRetryRequest,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
    session: AsyncSession = Depends(get_session),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> ShadowRunResponse:
    try:
        run = store.retry(run_id, payload.stage)
        run = store.add_note(run_id, {"author": payload.requested_by, "note": f"retry: {payload.reason or 'resume from invalid stage'}", "created_at": utc_now()})
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    legacy_result, source_identity = await _legacy_execution_inputs(
        run.analysis_id,
        session=session,
        config=config,
        source_video_hash=run.source_video_hash,
    )
    try:
        coordinator = get_shadow_execution_coordinator(config, store=store)
        receipt = await coordinator.submit(run.run_id, legacy_result, source_identity=source_identity, resubmit_if_inflight=True)
        if not receipt.accepted:
            logger.warning("Shadow retry %s was not accepted by local queue: %s", run.run_id, receipt.reason)
    except Exception:  # noqa: BLE001
        logger.exception("Shadow retry %s execution scheduling failed", run.run_id)
    return ShadowRunResponse(run=run)


@router.post("/runs/{run_id}/recover", response_model=ShadowRecoveryResponse, status_code=status.HTTP_202_ACCEPTED)
async def recover_shadow_run(
    run_id: str,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
    session: AsyncSession = Depends(get_session),
    config: RuntimeConfig = Depends(get_runtime_config),
) -> ShadowRecoveryResponse:
    """Recover stale ``running`` checkpoints after an application restart."""
    try:
        run = store.recover_incomplete(run_id)
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    legacy_result, source_identity = await _legacy_execution_inputs(
        run.analysis_id,
        session=session,
        config=config,
        source_video_hash=run.source_video_hash,
    )
    try:
        coordinator = get_shadow_execution_coordinator(config, store=store)
        receipt = await coordinator.submit(run.run_id, legacy_result, source_identity=source_identity, resubmit_if_inflight=True)
        if not receipt.accepted:
            logger.warning("Shadow recovery %s was not accepted by local queue: %s", run.run_id, receipt.reason)
    except Exception:  # noqa: BLE001
        logger.exception("Shadow recovery %s execution scheduling failed", run.run_id)
    return ShadowRecoveryResponse(run=run)


@router.post("/runs/{run_id}/fingerprints", response_model=ShadowRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def update_shadow_fingerprints(
    run_id: str,
    payload: ShadowFingerprintUpdateRequest,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> ShadowRunResponse:
    try:
        run = store.update_fingerprints(run_id, payload.model_dump(exclude={"requested_by", "confirmation"}, exclude_none=True))
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    return ShadowRunResponse(run=run)


@router.post("/runs/{run_id}/cleanup", response_model=ShadowCleanupResponse, status_code=status.HTTP_200_OK)
async def cleanup_shadow_run(
    run_id: str,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> ShadowCleanupResponse:
    """Delete rebuildable Shadow stage artifacts only; retain manifest/audit."""
    try:
        removed = store.cleanup(run_id)
        # ``cleanup`` validates the run before deleting generated files.
        store.read(run_id)
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    return ShadowCleanupResponse(
        run_id=run_id,
        removed=list(removed),
        retained=["run.json", "audit.jsonl", "source", "golden", "reviews", "corrections"],
    )


@router.post("/runs/{run_id}/review-decisions", response_model=ShadowDecisionResponse, status_code=status.HTTP_201_CREATED)
async def add_shadow_review_decision(
    run_id: str,
    payload: ShadowReviewDecisionRequest,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> ShadowDecisionResponse:
    try:
        run = store.read(run_id)
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    if payload.decision == "promote_candidate" and payload.promotion_scope != "shadow_only":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Shadow candidate promotion must explicitly remain shadow_only")
    decision = ShadowReviewDecision(
        decision_id=f"decision-{uuid4().hex}",
        run_id=run_id,
        stage=payload.stage,
        decision=payload.decision,
        reviewer=payload.reviewer,
        note=payload.note,
        promotion_scope=payload.promotion_scope,
    )
    updated = store.add_decision(run_id, decision)
    return ShadowDecisionResponse(run_id=run_id, decision=decision, run=updated)


@router.get("/runs/{run_id}/review-decisions", response_model=list[ShadowReviewDecision])
async def list_shadow_review_decisions(
    run_id: str,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> list[ShadowReviewDecision]:
    try:
        return store.review_decisions(run_id)
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/runs/{run_id}/notes", response_model=ShadowNoteResponse, status_code=status.HTTP_201_CREATED)
async def add_shadow_note(
    run_id: str,
    payload: ShadowNoteRequest,
    _: None = Depends(require_shadow_parent),
    store: ShadowArtifactStore = Depends(get_shadow_store),
) -> ShadowNoteResponse:
    try:
        run = store.add_note(run_id, {"author": payload.author, "note": payload.note, "created_at": utc_now()})
    except ShadowRunNotFound as exc:
        raise _not_found(exc) from exc
    return ShadowNoteResponse(run_id=run_id, notes=run.notes)
