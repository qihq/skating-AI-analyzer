from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import AsyncExitStack
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _upload_file(filename: str = "source.mp4", size: int = 16):
    from starlette.datastructures import UploadFile

    return UploadFile(filename=filename, file=BytesIO(b"x" * size), size=size)


async def _passthrough_retry(operation, *, context, **_kwargs):  # type: ignore[no-untyped-def]
    return await operation()


class HighlightQuoteUploadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'test.db'}"

        for module_name in [
            "app.database",
            "app.models",
            "app.routers.analysis",
            "app.services.pipeline_version",
        ]:
            sys.modules.pop(module_name, None)
        app_pkg = sys.modules.get("app")
        if app_pkg is not None:
            for attr in ("database", "models"):
                if hasattr(app_pkg, attr):
                    delattr(app_pkg, attr)

        import app.database as database

        database.ensure_storage_dirs()
        await database.init_db()
        self.database = database

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def _submit(self, **extra_form) -> tuple[object, "object | None"]:
        import app.models as models
        import app.routers.analysis as analysis_router
        from fastapi import BackgroundTasks
        from sqlalchemy import select

        background = BackgroundTasks()
        stack = AsyncExitStack()
        stack.enter_context(patch("app.routers.analysis.save_upload_file", AsyncMock(return_value=None)))
        stack.enter_context(patch("app.routers.analysis.precheck_video", AsyncMock(return_value=None)))
        stack.enter_context(patch("app.routers.analysis.compute_video_sha256", AsyncMock(return_value="sha256")))
        stack.enter_context(
            patch.object(analysis_router, "_video_identity_payload", return_value={"schema_version": "video_identity_v1"})
        )
        stack.enter_context(patch("app.routers.analysis.process_analysis", AsyncMock(return_value=None)))
        stack.enter_context(patch("app.routers.analysis.run_db_write_with_retry", _passthrough_retry))

        kwargs: dict[str, object] = {
            "background_tasks": background,
            "file": _upload_file(),
            "action_type": "跳跃",
            "action_subtype": None,
            "skater_id": None,
            "skill_node_id": None,
            "skill_category": None,
            "note": None,
            "session_id": None,
            "manual_action_window_start_sec": None,
            "manual_action_window_end_sec": None,
        }
        kwargs.update(extra_form)

        async with self.database.AsyncSessionLocal() as session:
            kwargs["session"] = session
            async with stack:
                response = await analysis_router.upload_analysis(**kwargs)

        analysis_row = None
        async with self.database.AsyncSessionLocal() as session:
            analysis_row = (
                await session.execute(select(models.Analysis).where(models.Analysis.id == response.id))
            ).scalar_one_or_none()
        return response, analysis_row

    async def test_persists_highlight_quote_and_speaker(self) -> None:
        response, analysis = await self._submit(highlight_quote="我今天敢往后滑了", quote_speaker="skater")
        self.assertEqual(response.status, "pending")
        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertEqual(analysis.highlight_quote, "我今天敢往后滑了")
        self.assertEqual(analysis.quote_speaker, "skater")

    async def test_rejects_unknown_speaker(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self._submit(highlight_quote="hello", quote_speaker="unknown")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_rejects_quote_over_280_chars(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self._submit(highlight_quote="x" * 281, quote_speaker="skater")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_rejects_speaker_without_quote(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self._submit(highlight_quote=None, quote_speaker="skater")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_empty_quote_with_speaker_is_rejected(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self._submit(highlight_quote="   ", quote_speaker="skater")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_empty_quote_without_speaker_is_allowed(self) -> None:
        response, analysis = await self._submit(highlight_quote="   ", quote_speaker=None)
        self.assertEqual(response.status, "pending")
        assert analysis is not None
        self.assertIsNone(analysis.highlight_quote)
        self.assertIsNone(analysis.quote_speaker)