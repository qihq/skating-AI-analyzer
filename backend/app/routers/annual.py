from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, DATA_DIR, UPLOADS_DIR, get_session
from app.models import AnnualCollection, AnnualExport, Skater, SkaterSkill, SkillNode
from app.schemas import (
    AnnualCollectionCreateRequest,
    AnnualCollectionPreview,
    AnnualCollectionPublic,
    AnnualCollectionRevisionRequest,
    AnnualExportPublic,
    AnnualMilestonePublic,
)
from app.services.annual_collections import AnnualCollectionValidationError, annual_source_hash, build_annual_snapshot
from app.services.annual_pdf import AnnualPdfError, RENDERER_VERSION, configured_font_paths, render_annual_pdf
from app.services.parent_access import require_parent_pin


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/annual", tags=["annual"])
ANNUAL_ASSET_ROOT = DATA_DIR / "analysis_assets"


async def _require_skater(session: AsyncSession, skater_id: str) -> Skater:
    skater = await session.get(Skater, skater_id)
    if skater is None:
        raise HTTPException(status_code=404, detail="未找到该练习档案对应的选手。")
    return skater


async def _snapshot_or_error(
    session: AsyncSession,
    skater_id: str,
    year: int,
    payload: AnnualCollectionCreateRequest,
) -> dict:
    await _require_skater(session, skater_id)
    try:
        return await build_annual_snapshot(session, skater_id, year, payload.chapter_ids, payload.milestone_ids)
    except AnnualCollectionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skaters/{skater_id}/{year}/preview", response_model=AnnualCollectionPreview)
async def preview_collection(
    skater_id: str,
    year: int,
    payload: AnnualCollectionCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> AnnualCollectionPreview:
    snapshot = await _snapshot_or_error(session, skater_id, year, payload)
    return AnnualCollectionPreview(
        snapshot=snapshot,
        source_hash=annual_source_hash(snapshot),
        coverage={key: int(value) for key, value in snapshot["coverage"].items()},
    )


@router.post("/skaters/{skater_id}/{year}/collections", response_model=AnnualCollectionPublic, status_code=201)
async def create_collection(
    skater_id: str,
    year: int,
    payload: AnnualCollectionCreateRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> AnnualCollectionPublic:
    await require_parent_pin(session, x_parent_pin)
    snapshot = await _snapshot_or_error(session, skater_id, year, payload)
    source_hash = annual_source_hash(snapshot)
    existing = (
        await session.execute(
            select(AnnualCollection)
            .where(AnnualCollection.skater_id == skater_id, AnnualCollection.year == year, AnnualCollection.source_hash == source_hash)
            .order_by(desc(AnnualCollection.revision))
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return AnnualCollectionPublic.model_validate(existing)
    revision = int(
        (
            await session.scalar(
                select(AnnualCollection.revision)
                .where(AnnualCollection.skater_id == skater_id, AnnualCollection.year == year)
                .order_by(desc(AnnualCollection.revision))
                .limit(1)
            )
        )
        or 0
    ) + 1
    collection = AnnualCollection(
        skater_id=skater_id,
        year=year,
        revision=revision,
        status="ready",
        title=(payload.title or f"{year} 年度成长合集").strip(),
        selected_chapter_ids=list(payload.chapter_ids),
        selected_milestone_ids=list(payload.milestone_ids),
        snapshot=snapshot,
        source_hash=source_hash,
    )
    session.add(collection)
    await session.commit()
    await session.refresh(collection)
    return AnnualCollectionPublic.model_validate(collection)


@router.get("/skaters/{skater_id}/{year}/collections", response_model=list[AnnualCollectionPublic])
async def list_collections(
    skater_id: str,
    year: int,
    recycled: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> list[AnnualCollectionPublic]:
    await _require_skater(session, skater_id)
    rows = (
        await session.execute(
            select(AnnualCollection)
            .where(
                AnnualCollection.skater_id == skater_id,
                AnnualCollection.year == year,
                AnnualCollection.deleted_at.is_not(None) if recycled is True else AnnualCollection.deleted_at.is_(None),
            )
            .order_by(desc(AnnualCollection.revision))
        )
    ).scalars().all()
    return [AnnualCollectionPublic.model_validate(row) for row in rows]


@router.post("/collections/{collection_id}/revisions", response_model=AnnualCollectionPublic, status_code=201)
async def revise_collection(
    collection_id: str,
    payload: AnnualCollectionRevisionRequest,
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> AnnualCollectionPublic:
    await require_parent_pin(session, x_parent_pin)
    current = await session.get(AnnualCollection, collection_id)
    if current is None:
        raise HTTPException(status_code=404, detail="未找到年度合集。")
    if current.deleted_at is not None:
        raise HTTPException(status_code=409, detail="请先从回收站恢复该年度合集。")
    snapshot = await _snapshot_or_error(session, current.skater_id, current.year, payload)
    revision = int((await session.scalar(
        select(AnnualCollection.revision)
        .where(AnnualCollection.skater_id == current.skater_id, AnnualCollection.year == current.year)
        .order_by(desc(AnnualCollection.revision)).limit(1)
    )) or 0) + 1
    collection = AnnualCollection(
        skater_id=current.skater_id,
        year=current.year,
        revision=revision,
        parent_revision_id=current.id,
        status="ready",
        title=(payload.title or current.title).strip(),
        selected_chapter_ids=list(payload.chapter_ids),
        selected_milestone_ids=list(payload.milestone_ids),
        snapshot=snapshot,
        source_hash=annual_source_hash(snapshot),
    )
    session.add(collection)
    await session.commit()
    await session.refresh(collection)
    return AnnualCollectionPublic.model_validate(collection)


@router.delete("/collections/{collection_id}", status_code=204, response_class=Response)
async def recycle_collection(collection_id: str, x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"), session: AsyncSession = Depends(get_session)) -> Response:
    await require_parent_pin(session, x_parent_pin)
    collection = await session.get(AnnualCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="未找到年度合集。")
    collection.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=204)


@router.post("/collections/{collection_id}/restore", response_model=AnnualCollectionPublic)
async def restore_collection(collection_id: str, x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"), session: AsyncSession = Depends(get_session)) -> AnnualCollectionPublic:
    await require_parent_pin(session, x_parent_pin)
    collection = await session.get(AnnualCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="未找到年度合集。")
    collection.deleted_at = None
    await session.commit()
    await session.refresh(collection)
    return AnnualCollectionPublic.model_validate(collection)


@router.delete("/collections/{collection_id}/permanent", status_code=204, response_class=Response)
async def permanently_delete_collection(collection_id: str, x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"), session: AsyncSession = Depends(get_session)) -> Response:
    await require_parent_pin(session, x_parent_pin)
    collection = await session.get(AnnualCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="未找到年度合集。")
    if collection.deleted_at is None:
        raise HTTPException(status_code=409, detail="只有回收站中的年度合集可以永久删除。")
    exports = (await session.execute(select(AnnualExport).where(AnnualExport.collection_id == collection.id))).scalars().all()
    asset_paths = [_resolve_export_path(item.asset_relative_path) for item in exports if item.asset_relative_path]
    for path in asset_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            await session.rollback()
            raise HTTPException(status_code=500, detail=f"无法删除年度 PDF 文件，请检查存储权限后重试：{path.name}") from exc
    await session.execute(delete(AnnualExport).where(AnnualExport.collection_id == collection.id))
    await session.execute(delete(AnnualCollection).where(AnnualCollection.id == collection.id))
    await session.commit()
    return Response(status_code=204)


@router.get("/skaters/{skater_id}/{year}/milestones", response_model=list[AnnualMilestonePublic])
async def list_milestones(
    skater_id: str,
    year: int,
    session: AsyncSession = Depends(get_session),
) -> list[AnnualMilestonePublic]:
    await _require_skater(session, skater_id)
    rows = (
        await session.execute(
            select(SkaterSkill, SkillNode)
            .join(SkillNode, SkillNode.id == SkaterSkill.skill_id)
            .where(SkaterSkill.skater_id == skater_id, SkaterSkill.unlocked_at.is_not(None))
            .order_by(SkaterSkill.unlocked_at.asc(), SkaterSkill.id.asc())
        )
    ).all()
    result: list[AnnualMilestonePublic] = []
    for progress, node in rows:
        occurred_at = progress.unlocked_at
        if occurred_at is None or occurred_at.year != year:
            continue
        result.append(
            AnnualMilestonePublic(
                id=progress.id,
                title=node.name,
                occurred_at=occurred_at,
                note=progress.unlock_note,
                verification={"parent": "parent_confirmed", "coach": "coach_confirmed"}.get(
                    progress.unlocked_by or "", "system_detected"
                ),
            )
        )
    return result


async def run_export(export_id: str) -> None:
    """Render after the response using a fresh session so request teardown is safe."""
    async with AsyncSessionLocal() as session:
        export = await session.get(AnnualExport, export_id)
        if export is None:
            return
        collection = await session.get(AnnualCollection, export.collection_id)
        if collection is None:
            export.status = "failed"
            export.error_message = "年度合集不存在。"
            await session.commit()
            return
        export.status = "processing"
        export.error_message = None
        await session.commit()
        relative_path = Path("annual") / collection.id / f"{export.id}.pdf"
        output_path = ANNUAL_ASSET_ROOT / relative_path
        try:
            result = await asyncio.to_thread(
                render_annual_pdf,
                collection.snapshot,
                output_path,
                configured_font_paths(),
                frames_root=UPLOADS_DIR,
            )
            export.status = "completed"
            export.asset_relative_path = relative_path.as_posix()
            export.file_sha256 = result.file_sha256
            export.page_count = result.page_count
            export.completed_at = datetime.now(timezone.utc)
            collection.status = "exported"
        except AnnualPdfError as exc:
            logger.warning("Annual export %s failed: %s", export_id, exc)
            export.status = "failed"
            export.error_message = str(exc)
        except Exception:  # noqa: BLE001 - retain a safe user-facing error
            logger.exception("Annual export %s failed unexpectedly", export_id)
            export.status = "failed"
            export.error_message = "年度 PDF 生成失败，请检查字体配置后重试。"
        await session.commit()


async def recover_incomplete_exports(*, enqueue=run_export) -> list[str]:
    """Return interrupted exports to the queue after a process restart."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AnnualExport)
                .where(AnnualExport.status.in_(("pending", "processing")))
                .order_by(AnnualExport.created_at.asc())
            )
        ).scalars().all()
        export_ids = [row.id for row in rows]
        for row in rows:
            row.status = "pending"
            row.error_message = None
        if export_ids:
            await session.commit()
    for export_id in export_ids:
        await enqueue(export_id)
    return export_ids


@router.post("/collections/{collection_id}/exports", response_model=AnnualExportPublic, status_code=202)
async def create_export(
    collection_id: str,
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False),
    x_parent_pin: str | None = Header(default=None, alias="X-Parent-Pin"),
    session: AsyncSession = Depends(get_session),
) -> AnnualExportPublic:
    await require_parent_pin(session, x_parent_pin)
    collection = await session.get(AnnualCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="未找到年度合集。")
    if collection.deleted_at is not None:
        raise HTTPException(status_code=409, detail="请先从回收站恢复该年度合集。")
    active = (
        await session.execute(
            select(AnnualExport)
            .where(AnnualExport.collection_id == collection.id, AnnualExport.status.in_(("pending", "processing")))
            .order_by(desc(AnnualExport.created_at)).limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        return AnnualExportPublic.model_validate(active)
    existing = (
        await session.execute(
            select(AnnualExport)
            .where(AnnualExport.collection_id == collection.id, AnnualExport.status == "completed")
            .order_by(desc(AnnualExport.completed_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None and force is not True:
        if existing.asset_relative_path and _resolve_export_path(existing.asset_relative_path).is_file():
            return AnnualExportPublic.model_validate(existing)
        existing.status = "failed"
        existing.error_message = "年度导出文件已不存在，可重新生成。"
        existing.asset_relative_path = None
        await session.commit()
    export = AnnualExport(collection_id=collection.id, status="pending", renderer_version=RENDERER_VERSION)
    session.add(export)
    await session.commit()
    await session.refresh(export)
    background_tasks.add_task(run_export, export.id)
    return AnnualExportPublic.model_validate(export)


@router.get("/exports/{export_id}", response_model=AnnualExportPublic)
async def get_export(export_id: str, session: AsyncSession = Depends(get_session)) -> AnnualExportPublic:
    export = await session.get(AnnualExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="未找到年度导出任务。")
    return AnnualExportPublic.model_validate(export)


def _resolve_export_path(relative_path: str) -> Path:
    root = ANNUAL_ASSET_ROOT.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="年度导出文件不存在。") from exc
    return candidate


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    export = await session.get(AnnualExport, export_id)
    if export is None or export.status != "completed" or not export.asset_relative_path:
        raise HTTPException(status_code=404, detail="年度导出文件尚不可下载。")
    path = _resolve_export_path(export.asset_relative_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="年度导出文件不存在。")
    collection = await session.get(AnnualCollection, export.collection_id)
    year = collection.year if collection else "annual"
    return FileResponse(path, media_type="application/pdf", filename=f"icebuddy-{year}-skater.pdf")
