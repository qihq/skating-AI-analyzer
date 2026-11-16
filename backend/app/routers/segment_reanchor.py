"""R-line auxiliary reanchor routes. All writes require the existing parent gate."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis_v2.contracts import SegmentAnchorSelection, SegmentAnchorConfirmation
from app.database import get_session
from app.models import Analysis, SegmentReanchorRevision
from app.services.parent_access import require_parent_pin
from app.services import segment_reanchor as service
from app.services import segment_reanchor_runtime as lifecycle

class EvidenceRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def validated(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Never echo NaN/Infinity or raw stored evidence into JSON errors.
                raise HTTPException(422, "invalid_segment_evidence_contract")
        return validated


router = APIRouter(tags=["segment-reanchor"], route_class=EvidenceRoute)


async def parent(analysis_id, session, pin):
    from app.trial import trial_profile, trial_capabilities
    if trial_profile() != "off":
        raise HTTPException(403, trial_capabilities()["limitation"])
    await require_parent_pin(session, pin)
    row = await session.get(Analysis, analysis_id)
    if row is None:
        raise HTTPException(404, "analysis_not_found")
    return row


async def revisions(session, analysis_id):
    return list((await session.scalars(select(SegmentReanchorRevision).where(
        SegmentReanchorRevision.analysis_id == analysis_id).order_by(SegmentReanchorRevision.revision))).all())


def view(row, latest):
    return dict(revision=row.revision, parent_revision=row.parent_revision, status=row.status,
        selection=row.selection, error=row.error, identity_source="manual_segment_selection",
        automatic_cross_gap_identity=False,
        superseded=any(r.revision > row.revision and r.selection["segment"] == row.selection["segment"] for r in latest),
        result_available=row.result is not None)


def checked_source(row):
    try:
        return service.load_source(row)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise HTTPException(422, "saved_evidence_unavailable: " + str(exc)) from exc


def checked_selection(row, selection, source):
    try:
        return service.validate_selection(row, selection, source)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{analysis_id}/identity/segments")
async def segment_candidates(analysis_id: str, session: AsyncSession = Depends(get_session), x_parent_pin: str | None = Header(None)):
    row = await parent(analysis_id, session, x_parent_pin)
    stored = await revisions(session, analysis_id)
    current = stored[-1].revision if stored else 0
    try:
        source = service.load_source(row)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return dict(current_revision=current, observations=[], unavailable=[dict(reason=str(exc))],
                    revisions=[view(r, stored) for r in stored])
    observations = []
    for i, item in source["available"].items():
        if not item["lost"]:
            continue
        observations.append(dict(observation_index=i, segment=item["segment"],
            timestamp=item["row"]["timestamp"], canvas=source["manifest"]["canvas"],
            image_url=f"/api/analysis/{analysis_id}/identity/segments/images/{i}?saved_only=true",
            candidates=[dict(index=j, bbox=b[:4], confidence=b[4],
                selection=service.selection_for(row, source, i, j, current))
                for j, b in enumerate(item["receipt"]["candidates"]) ]))
    return dict(current_revision=current, observations=observations, unavailable=source["unavailable"],
        revisions=[view(r, stored) for r in stored], video_overlay_allowed=False)


@router.get("/{analysis_id}/identity/segments/images/{observation_index}")
async def segment_image(analysis_id: str, observation_index: int, saved_only: bool = Query(True),
        session: AsyncSession = Depends(get_session), x_parent_pin: str | None = Header(None)):
    row = await parent(analysis_id, session, x_parent_pin)
    source = checked_source(row)
    if observation_index not in source["available"] or not saved_only:
        raise HTTPException(404, "saved_bound_image_unavailable")
    return FileResponse(source["files"][observation_index], media_type="image/jpeg")


@router.post("/{analysis_id}/identity/segments/preview")
async def preview_segment(analysis_id: str, request: SegmentAnchorSelection,
        session: AsyncSession = Depends(get_session), x_parent_pin: str | None = Header(None)):
    row = await parent(analysis_id, session, x_parent_pin)
    stored = await revisions(session, analysis_id)
    current = stored[-1].revision if stored else 0
    if request.expected_revision != current:
        raise HTTPException(409, "stale_or_jumped_revision")
    indexes, token = checked_selection(row, request.model_dump(), checked_source(row))
    return dict(preview_digest=token, parent_revision=current, revision=current+1,
        local_range=indexes, invalidates_segment=request.segment, identity_source="manual_segment_selection",
        original_automatic_unchanged=True, confirmation_required=True, video_overlay_allowed=False,
        note="人工选定身份来源；仍需连续三帧及逐帧身份/姿态检查，不回填确认前帧。")


async def process_revision(sessions, analysis_id, revision):
    async with sessions() as session:
        record = await session.scalar(select(SegmentReanchorRevision).where(
            SegmentReanchorRevision.analysis_id == analysis_id, SegmentReanchorRevision.revision == revision))
        if record is None or record.status != "submitted":
            return
        record_id = record.id
        selection, preview_digest = record.selection, record.preview_digest
        analysis = await session.get(Analysis, analysis_id)
    owner = asyncio.current_task()
    claim = asyncio.create_task(lifecycle.finish(sessions, record_id, "submitted", status="processing"))
    claimed = False
    try:
        claimed = await asyncio.shield(claim)
        if not claimed:
            return
        lifecycle.remember_submission(record_id)
        # Cancelling this await may leave CPU work running. It only writes this
        # revision's private image directory; publication always uses the CAS.
        result = await asyncio.to_thread(service.execute_local, analysis, selection, revision, preview_digest)
        status = "success" if any(f.get("keypoints") for f in result["pose"]["frames"]) else "insufficient"
        await lifecycle.finish(sessions, record_id, "processing", result=result, status=status)
    except asyncio.CancelledError:
        # Resolve an in-flight claim before deciding which worker may terminate.
        claimed = await asyncio.shield(claim)
        if not claimed:
            raise
        await asyncio.shield(lifecycle.finish(sessions, record_id, "processing", status="failed",
            error="segment_task_cancelled: 局部任务被中断；旧线程结果不会发布，请重新预览并明确确认新修订。"))
        raise
    except Exception as exc:
        await lifecycle.finish(sessions, record_id, "processing", status="failed",
            error=type(exc).__name__ + ": " + str(exc))
    finally:
        lifecycle.forget(record_id, owner)


@router.post("/{analysis_id}/identity/segments/confirm", status_code=202)
async def confirm_segment(analysis_id: str, request: SegmentAnchorConfirmation, background: BackgroundTasks,
        session: AsyncSession = Depends(get_session), x_parent_pin: str | None = Header(None)):
    row = await parent(analysis_id, session, x_parent_pin)
    payload = request.model_dump(mode="json")
    payload_hash = service.digest(payload)
    stored = await revisions(session, analysis_id)
    duplicate = next((r for r in stored if r.idempotency_key == request.idempotency_key), None)
    if duplicate:
        if duplicate.payload_digest != payload_hash:
            raise HTTPException(409, "idempotency_payload_conflict")
        return view(duplicate, stored)
    current = stored[-1].revision if stored else 0
    if request.selection.expected_revision != current or any(r.status in ("submitted", "processing") for r in stored):
        raise HTTPException(409, "stale_or_busy_revision")
    _, token = checked_selection(row, request.selection.model_dump(), checked_source(row))
    if token != request.preview_digest:
        raise HTTPException(409, "preview_evidence_changed")
    record = SegmentReanchorRevision(analysis_id=analysis_id, revision=current+1, parent_revision=current,
        idempotency_key=request.idempotency_key, payload_digest=payload_hash,
        selection=request.selection.model_dump(mode="json"), preview_digest=token, status="submitted")
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # Unique revision is the database compare-and-swap across workers.
        stored = await revisions(session, analysis_id)
        duplicate = next((r for r in stored if r.idempotency_key == request.idempotency_key), None)
        if duplicate and duplicate.payload_digest == payload_hash:
            return view(duplicate, stored)
        raise HTTPException(409, "concurrent_revision_conflict")
    sessions = async_sessionmaker(session.bind, expire_on_commit=False)
    lifecycle.remember_submission(record.id)
    background.add_task(process_revision, sessions, analysis_id, current+1)
    return view(record, stored + [record])


async def saved_revision(analysis_id, revision, session, pin):
    await parent(analysis_id, session, pin)
    stored = await revisions(session, analysis_id)
    row = next((r for r in stored if r.revision == revision), None)
    if row is None:
        raise HTTPException(404, "auxiliary_revision_missing")
    return row, stored


@router.get("/{analysis_id}/identity/segments/revisions/{revision}")
async def revision_detail(analysis_id: str, revision: int, session: AsyncSession = Depends(get_session), x_parent_pin: str | None = Header(None)):
    row, stored = await saved_revision(analysis_id, revision, session, x_parent_pin)
    result = row.result or {}
    return dict(**view(row, stored), bio_data=result.get("bio_data"), report=result.get("report"),
        analysis_profile=result.get("analysis_profile"), profile_evidence=result.get("profile_evidence"),
        local_range=result.get("local_range"), video_overlay_allowed=False)


@router.get("/{analysis_id}/identity/segments/revisions/{revision}/pose")
async def revision_pose(analysis_id: str, revision: int, session: AsyncSession = Depends(get_session), x_parent_pin: str | None = Header(None)):
    from app.routers.analysis import _build_pose_response
    row, stored = await saved_revision(analysis_id, revision, session, x_parent_pin)
    result = row.result or {}
    pose = _build_pose_response(analysis_id, result.get("pose"), result.get("motion")).model_dump(mode="json")
    pose["frame_urls"] = {f["frame"]: f"/api/analysis/{analysis_id}/identity/segments/revisions/{revision}/images/{f['frame']}?saved_only=true"
        for f in pose["frames"]}
    return pose


@router.get("/{analysis_id}/identity/segments/revisions/{revision}/images/{filename}")
async def revision_image(analysis_id: str, revision: int, filename: str, saved_only: bool = Query(True),
        session: AsyncSession = Depends(get_session), x_parent_pin: str | None = Header(None)):
    row, _ = await saved_revision(analysis_id, revision, session, x_parent_pin)
    result = row.result or {}
    binding = next((b for b in result.get("target_lock", {}).get("pose_frame_bindings", []) if b["frame"] == filename), None)
    if binding is None or not saved_only:
        raise HTTPException(404, "saved_auxiliary_image_missing")
    path = service.child(Path(result["image_directory"]), filename)
    if not path.is_file() or service.ct.file_sha256(path) != binding["sha256"]:
        raise HTTPException(404, "saved_auxiliary_image_missing_or_changed")
    return FileResponse(path, media_type="image/jpeg")
