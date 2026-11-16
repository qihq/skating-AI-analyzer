"""Single-process auxiliary task ownership; no GET, timeout or inference recovery."""
from __future__ import annotations

import asyncio
from sqlalchemy import select, update
from app.models import SegmentReanchorRevision

# Submission and BackgroundTasks share the request task. A finished/cancelled task
# cannot own work. On a fresh single-worker startup this registry is empty.
_owners: dict[str, asyncio.Task] = {}
BUSY = ("submitted", "processing")


def remember_submission(record_id: str) -> None:
    _owners[record_id] = asyncio.current_task()


def forget(record_id: str, owner) -> None:
    if _owners.get(record_id) is owner:
        _owners.pop(record_id, None)


async def finish(sessions, record_id: str, expected: str, **values) -> bool:
    """CAS prevents cancelled/recovered workers publishing a late result."""
    async with sessions() as session:
        changed = await session.execute(update(SegmentReanchorRevision).where(
            SegmentReanchorRevision.id == record_id,
            SegmentReanchorRevision.status == expected).values(**values))
        await session.commit()
        return changed.rowcount == 1


async def recover_interrupted_reanchors(sessions) -> int:
    """Called only at the app's startup boundary, before accepting requests.

    The deployment uses one process. Never infer interruption from record age.
    Skip this process's live request/background owners if startup is re-entered.
    Old payloads, results and keys remain attached to their original records.
    """
    count = 0
    async with sessions() as session:
        rows = (await session.scalars(select(SegmentReanchorRevision).where(
            SegmentReanchorRevision.status.in_(BUSY)))).all()
        for row in rows:
            owner = _owners.get(row.id)
            if owner is not None and not owner.done():
                continue
            changed = await session.execute(update(SegmentReanchorRevision).where(
                SegmentReanchorRevision.id == row.id,
                SegmentReanchorRevision.status == row.status).values(status="failed",
                error="segment_process_interrupted: 服务启动时原执行者已失效；保留旧选择和数据，请重新预览并明确确认新修订。"))
            count += changed.rowcount
            forget(row.id, owner)
        await session.commit()
    return count
