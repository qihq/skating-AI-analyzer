"""Offline reliability boundaries: synthetic images/pose, real SQLite and routes."""
import asyncio
import copy
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.analysis_v2.contracts import SegmentAnchorConfirmation
from app.routers import segment_reanchor as routes
from app.services import segment_reanchor_runtime as runtime
from app.services.local_runtime import recover_interrupted_local_analyses
from test_segment_reanchor_contract import case, choose, submit, read, cleanup_clients, save


async def ignored(*args):
    pass


def abandoned(c, monkeypatch):
    original = routes.process_revision
    monkeypatch.setattr(routes, "process_revision", ignored)
    _, body, _ = submit(c, key="reliability-original")
    monkeypatch.setattr(routes, "process_revision", original)
    return body


async def snapshot(c):
    async with c.sessions() as session:
        parent = await session.get(models.Analysis, "synthetic-segment")
        rows = (await session.scalars(select(models.SegmentReanchorRevision).order_by(models.SegmentReanchorRevision.revision))).all()
        return copy.deepcopy(dict(parent={k: getattr(parent, k) for k in c.original},
            rows=[{k: getattr(r, k) for k in ("id", "revision", "parent_revision", "idempotency_key", "payload_digest", "preview_digest", "selection", "result", "status", "error")} for r in rows]))


@pytest.mark.parametrize("phase", ["submitted", "processing"])
def test_actual_app_lifespan_recovers_only_orphans(tmp_path, monkeypatch, phase):
    c = case(tmp_path, monkeypatch)
    body = abandoned(c, monkeypatch)
    async def prepare():
        async with c.sessions() as session:
            row = await session.scalar(select(models.SegmentReanchorRevision))
            row.status = phase
            row.result = {"saved_before_interruption": True}
            await session.commit()
        return await snapshot(c)
    before = asyncio.run(prepare())
    # Execute the actual application's lifespan. Unrelated startup IO/seeding is
    # replaced; its recovery import/call and the isolated SQLite writes are real.
    from app import main, database
    monkeypatch.setattr(database, "AsyncSessionLocal", c.sessions)
    for name in ("ensure_storage_dirs", "validate_font_paths", "log_pose_runtime_mode"):
        monkeypatch.setattr(main, name, lambda: None)
    for name in ("init_db", "_backfill_applied_corrections_startup", "_recover_annual_exports_startup",
                 "seed_preset_skaters", "seed_default_memories", "seed_skill_catalog"):
        monkeypatch.setattr(main, name, AsyncMock())
    monkeypatch.setenv("SYNC_SKATER_PROGRESS_ON_STARTUP", "0")
    monkeypatch.setattr(main, "scheduler", SimpleNamespace(add_job=lambda *a, **k: None, start=lambda: None, running=False))
    async def restart():
        await c.engine.dispose()  # Reopens the actual file on the next connection.
        async with main.lifespan(main.app):
            return await snapshot(c)
    with patch.object(routes.service, "execute_local", side_effect=AssertionError("recovery must not execute")):
        after = asyncio.run(restart())
        old = c.client.post(c.base + "/confirm", json=body)
        assert old.status_code == 202 and old.json()["status"] == "failed"
        with patch.object(AsyncSession, "commit", new=AsyncMock(side_effect=AssertionError("GET write"))), patch.object(AsyncSession, "flush", new=AsyncMock(side_effect=AssertionError("GET flush"))):
            assert c.client.get(c.base).status_code == 200
            assert c.client.get(c.base + "/revisions/1").json()["result_available"]
            assert c.client.get(c.base + "/revisions/1/pose").status_code == 200
    assert before["parent"] == after["parent"] == c.original
    expected = dict(before["rows"][0], status="failed", error=after["rows"][0]["error"])
    assert after["rows"] == [expected]
    assert "segment_process_interrupted" in expected["error"]
    replacement, _, _ = submit(c, key="explicit-after-startup")
    assert replacement["revision"] == 2 and read(c, 2)[0]["status"] == "success"
    save("lifespan-" + phase, dict(before=before, after=after, explicit_new_revision=replacement))


@pytest.mark.parametrize("status", ["success", "insufficient", "failed"])
def test_startup_preserves_terminal_records_exactly(tmp_path, monkeypatch, status):
    c = case(tmp_path, monkeypatch)
    abandoned(c, monkeypatch)
    async def check():
        async with c.sessions() as session:
            row = await session.scalar(select(models.SegmentReanchorRevision))
            row.status, row.result, row.error = status, {"preserved": status}, "original reason"
            await session.commit()
        before = await snapshot(c)
        assert await recover_interrupted_local_analyses(c.sessions) == 0
        assert await snapshot(c) == before
    asyncio.run(check())


def confirmation(c, key):
    selection = choose(c)[0]
    preview = c.client.post(c.base + "/preview", json=selection).json()
    return SegmentAnchorConfirmation(selection=selection, preview_digest=preview["preview_digest"],
        idempotency_key=key, confirmation="confirm_manual_segment_target")


def test_live_submitted_and_processing_remain_busy(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    request = confirmation(c, "live-submitted-key")
    original = routes.service.execute_local
    async def check():
        background = BackgroundTasks()
        async with c.sessions() as session:
            first = await routes.confirm_segment("synthetic-segment", request, background, session, None)
        assert first["status"] == "submitted"
        assert await recover_interrupted_local_analyses(c.sessions) == 0
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        def blocked(*args):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(10), "test release missing"
            return original(*args)
        monkeypatch.setattr(routes.service, "execute_local", blocked)
        task = asyncio.create_task(background())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert (await snapshot(c))["rows"][0]["status"] == "processing"
            assert await recover_interrupted_local_analyses(c.sessions) == 0
            new_request = request.model_copy(update={"idempotency_key": "live-other-key",
                "selection": request.selection.model_copy(update={"expected_revision": 1})})
            async with c.sessions() as session:
                with pytest.raises(HTTPException) as exc:
                    await routes.confirm_segment("synthetic-segment", new_request, BackgroundTasks(), session, None)
            assert exc.value.status_code == 409
        finally:
            release.set()
            await task
        assert (await snapshot(c))["rows"][0]["status"] == "success"
    asyncio.run(check())


@pytest.mark.parametrize("cancel", [True, False])
def test_late_cpu_result_cannot_overwrite_terminal_or_replacement(tmp_path, monkeypatch, cancel):
    c = case(tmp_path, monkeypatch)
    body = abandoned(c, monkeypatch)
    original = routes.service.execute_local
    async def check():
        loop = asyncio.get_running_loop()
        entered, finished = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        executions = []
        def slow(*args):
            executions.append(args[2])
            if args[2] == 1:
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(10), "test release missing"
            try:
                return original(*args)
            finally:
                if args[2] == 1: loop.call_soon_threadsafe(finished.set)
        monkeypatch.setattr(routes.service, "execute_local", slow)
        task = asyncio.create_task(routes.process_revision(c.sessions, "synthetic-segment", 1))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
            else:
                # Adversarial terminal transition exercises the publication CAS
                # even if a surviving worker still returns normally.
                row = (await snapshot(c))["rows"][0]
                assert await runtime.finish(c.sessions, row["id"], "processing", status="failed", error="terminated-boundary-test")
            old_terminal = (await snapshot(c))["rows"][0]
            assert old_terminal["status"] == "failed"
            duplicate = c.client.post(c.base + "/confirm", json=body)
            assert duplicate.json()["status"] == "failed" and executions == [1]
            replacement, _, _ = submit(c, key="explicit-replacement-2")
            assert replacement["revision"] == 2 and read(c, 2)[0]["status"] == "success"
            before_late = await snapshot(c)
        finally:
            release.set()
            await asyncio.wait_for(finished.wait(), 5)
            if not task.cancelled(): await task
        assert await snapshot(c) == before_late
        assert before_late["rows"][0] == old_terminal
        assert before_late["parent"] == c.original
        assert executions == [1, 2]
        save("late-thread-" + str(cancel), dict(cancelled=cancel, executions=executions, before_late=before_late, after_late=await snapshot(c)))
    asyncio.run(check())


def test_concurrent_confirmations_execute_once(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    first = confirmation(c, "concurrent-first-key")
    second = first.model_copy(update={"idempotency_key": "concurrent-second-key"})
    calls = []
    original = routes.service.execute_local
    def counted(*args):
        calls.append(args[2])
        return original(*args)
    monkeypatch.setattr(routes.service, "execute_local", counted)
    async def check():
        async def confirm(request):
            background = BackgroundTasks()
            async with c.sessions() as session:
                try:
                    return await routes.confirm_segment("synthetic-segment", request, background, session, None), background
                except HTTPException as exc:
                    return exc.status_code, background
        responses = await asyncio.gather(confirm(first), confirm(second))
        accepted = [r for r in responses if isinstance(r[0], dict)]
        assert len(accepted) == 1 and [r[0] for r in responses if isinstance(r[0], int)] == [409]
        await accepted[0][1]()
        assert calls == [1]
        before = await snapshot(c)
        successful = first if accepted[0][0]["selection"] == first.selection.model_dump() and before["rows"][0]["idempotency_key"] == first.idempotency_key else second
        async with c.sessions() as session:
            repeat = BackgroundTasks()
            old = await routes.confirm_segment("synthetic-segment", successful, repeat, session, None)
        assert old["status"] == "success" and not repeat.tasks
        assert await snapshot(c) == before
    asyncio.run(check())


def test_two_dispatchers_claim_same_revision_only_once(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    abandoned(c, monkeypatch)
    original = routes.service.execute_local
    calls = []
    def counted(*args):
        calls.append(args[2]); return original(*args)
    monkeypatch.setattr(routes.service, "execute_local", counted)
    async def check():
        await asyncio.gather(*(routes.process_revision(c.sessions, "synthetic-segment", 1) for _ in range(2)))
        assert calls == [1]
        assert (await snapshot(c))["rows"][0]["status"] == "success"
    asyncio.run(check())


@pytest.mark.parametrize("profile", ["web-preview", "legacy-analysis-preview"])
def test_trial_startup_keeps_auxiliary_records_untouched(tmp_path, monkeypatch, profile):
    c = case(tmp_path, monkeypatch)
    abandoned(c, monkeypatch)
    before = asyncio.run(snapshot(c))
    monkeypatch.setenv("SKATING_TRIAL_PROFILE", profile)
    assert asyncio.run(recover_interrupted_local_analyses(c.sessions)) == 0
    assert asyncio.run(snapshot(c)) == before
