from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SnowballRouteParentPinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmpdir.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'test.db'}"
        for name in [
            "app.database",
            "app.models",
            "app.schemas",
            "app.routers.snowball",
            "app.services.snowball",
        ]:
            sys.modules.pop(name, None)
        app_pkg = sys.modules.get("app")
        if app_pkg is not None:
            for attr in ("database", "models", "schemas"):
                if hasattr(app_pkg, attr):
                    delattr(app_pkg, attr)

        import app.database as database
        import app.models as models
        from app.services.auth import hash_pin

        self.database = database
        self.models = models
        database.ensure_storage_dirs()
        await database.init_db()
        async with database.AsyncSessionLocal() as session:
            session.add(models.ParentAuth(pin_hash=hash_pin("1234"), pin_length=4))
            session.add(models.Skater(id="skater-1", name="Tantan"))
            session.add(models.Analysis(id="analysis-1", action_type="jump", video_path="clip.mp4"))
            await session.commit()

        import app.routers.snowball as snowball

        self.router = snowball

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()
        self.tmpdir.cleanup()

    async def _memory(self, memory_id: str = "memory-1"):
        async with self.database.AsyncSessionLocal() as session:
            memory = self.models.SnowballMemory(
                id=memory_id,
                skater_id="skater-1",
                title="Goal",
                content="Keep the axis steady",
                category="goal",
            )
            session.add(memory)
            await session.commit()
            return memory_id

    async def _suggestion(self, suggestion_id: str = "suggestion-1", *, action: str = "add"):
        async with self.database.AsyncSessionLocal() as session:
            suggestion = self.models.MemorySuggestion(
                id=suggestion_id,
                analysis_id="analysis-1",
                skater_id="skater-1",
                suggestions=[
                    {
                        "action": action,
                        "title": "Suggested focus",
                        "content": "Keep the landing quiet",
                        "category": "focus",
                    }
                ],
            )
            session.add(suggestion)
            await session.commit()
            return suggestion_id

    async def test_memory_mutations_require_parent_pin_and_valid_pin_allows_them(self) -> None:
        from app.schemas import SnowballMemoryCreate, SnowballMemoryPinUpdate, SnowballMemoryUpdate
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            create_payload = SnowballMemoryCreate(title="New", content="Content", category="goal")
            for pin in (None, "9999"):
                with self.assertRaises(HTTPException) as raised:
                    await self.router.create_snowball_memory("skater-1", create_payload, x_parent_pin=pin, session=session)
                self.assertEqual(raised.exception.status_code, 403)

            created = await self.router.create_snowball_memory(
                "skater-1", create_payload, x_parent_pin="1234", session=session
            )
            self.assertEqual(created.title, "New")

            updated = await self.router.update_snowball_memory(
                "skater-1", created.id, SnowballMemoryUpdate(title="Updated"), x_parent_pin="1234", session=session
            )
            self.assertEqual(updated.title, "Updated")

            pinned = await self.router.pin_snowball_memory(
                "skater-1", created.id, SnowballMemoryPinUpdate(is_pinned=True), x_parent_pin="1234", session=session
            )
            self.assertTrue(pinned.is_pinned)

            for route, args in (
                (self.router.update_snowball_memory, ("skater-1", created.id, SnowballMemoryUpdate(title="No"))),
                (self.router.pin_snowball_memory, ("skater-1", created.id, SnowballMemoryPinUpdate(is_pinned=False))),
                (self.router.delete_snowball_memory, ("skater-1", created.id)),
            ):
                with self.assertRaises(HTTPException) as raised:
                    await route(*args, x_parent_pin=None, session=session)
                self.assertEqual(raised.exception.status_code, 403)

            response = await self.router.delete_snowball_memory(
                "skater-1", created.id, x_parent_pin="1234", session=session
            )
            self.assertEqual(response.status_code, 204)

    async def test_suggestion_mutations_require_pin_but_reads_and_chat_do_not(self) -> None:
        from app.schemas import MemorySuggestionApplyRequest
        from fastapi import HTTPException

        await self._suggestion("suggestion-add", action="add")
        await self._suggestion("suggestion-dismiss", action="expire")

        async with self.database.AsyncSessionLocal() as session:
            payload = MemorySuggestionApplyRequest(suggestion_id="suggestion-add", accepted_indices=[0])
            for pin in (None, "9999"):
                with self.assertRaises(HTTPException) as raised:
                    await self.router.apply_memory_suggestions("skater-1", payload, x_parent_pin=pin, session=session)
                self.assertEqual(raised.exception.status_code, 403)

            applied = await self.router.apply_memory_suggestions(
                "skater-1", payload, x_parent_pin="1234", session=session
            )
            self.assertEqual(len(applied), 1)

            for pin in (None, "9999"):
                with self.assertRaises(HTTPException) as raised:
                    await self.router.dismiss_memory_suggestion(
                        "skater-1", "suggestion-dismiss", x_parent_pin=pin, session=session
                    )
                self.assertEqual(raised.exception.status_code, 403)

            dismissed = await self.router.dismiss_memory_suggestion(
                "skater-1", "suggestion-dismiss", x_parent_pin="1234", session=session
            )
            self.assertTrue(dismissed.is_reviewed)

            # Read routes remain available without a PIN.
            memories = await self.router.get_snowball_memories("skater-1", session=session)
            suggestions = await self.router.get_memory_suggestions("skater-1", session=session)
            self.assertGreaterEqual(len(memories), 1)
            self.assertEqual(suggestions, [])

            with patch.object(self.router, "chat_with_snowball", new=AsyncMock(return_value="ok")):
                reply = await self.router.snowball_chat(
                    type("ChatPayload", (), {"skater_id": "skater-1", "history": [], "message": "Hi"})(),
                    session=session,
                )
            self.assertEqual(reply.reply, "ok")


if __name__ == "__main__":
    unittest.main()
