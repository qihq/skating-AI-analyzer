from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import AsyncExitStack
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_skater_and_completed_analysis(session, models, skater_id="skater-1", analysis_id="a-1"):
    session.add(models.Skater(id=skater_id, name="tantan"))
    session.add(
        models.Analysis(
            id=analysis_id,
            skater_id=skater_id,
            action_type="跳跃",
            action_subtype="Waltz",
            video_path="x.mp4",
            status="completed",
            report={"data_quality": "good", "summary": "ok", "training_focus": "落冰"},
            created_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )
    )


PROVIDER = type(
    "ActiveProviderConfig",
    (),
    {"id": "prov-1", "slot": "report", "name": "test-report", "provider": "openai",
     "base_url": "https://example.com/v1", "model_id": "gpt-4", "vision_model": None,
     "api_key": "key", "notes": None},
)()


class GrowthChapterRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'test.db'}"
        for module_name in [
            "app",
            "app.database",
            "app.models",
            "app.routers.growth",
            "app.services.pipeline_version",
            "app.services.monthly_facts",
            "app.services.monthly_chapters",
        ]:
            sys.modules.pop(module_name, None)
        app_pkg = sys.modules.get("app")
        if app_pkg is not None:
            for attr in ("database", "models"):
                if hasattr(app_pkg, attr):
                    delattr(app_pkg, attr)

        import app.database as database
        import app.models as models

        self.database = database
        self.models = models
        database.ensure_storage_dirs()
        await database.init_db()

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()
        self.tmp.cleanup()

    async def test_unknown_skater_returns_404_on_facts(self) -> None:
        import app.routers.growth as growth_router
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(HTTPException) as ctx:
                await growth_router.create_chapter_facts("missing", "2026-07", session=session)
            self.assertEqual(ctx.exception.status_code, 404)

    async def test_invalid_year_month_returns_400_on_facts(self) -> None:
        import app.routers.growth as growth_router
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            await session.commit()
            with self.assertRaises(HTTPException) as ctx:
                await growth_router.create_chapter_facts("skater-1", "2026-7", session=session)
            self.assertEqual(ctx.exception.status_code, 400)

    async def test_facts_creates_facts_ready_chapter(self) -> None:
        import app.routers.growth as growth_router

        async with self.database.AsyncSessionLocal() as session:
            _make_skater_and_completed_analysis(session, self.models)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)
        self.assertEqual(chapter.status, "facts_ready")
        self.assertEqual(chapter.revision, 1)
        self.assertEqual(chapter.year_month, "2026-07")
        self.assertEqual(chapter.fact_snapshot["year_month"], "2026-07")
        self.assertTrue(chapter.source_hash)

    async def test_generate_preserves_facts_on_provider_failure(self) -> None:
        import app.routers.growth as growth_router
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            _make_skater_and_completed_analysis(session, self.models)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)
            chapter_id = chapter.id

        with patch("app.services.monthly_chapters.get_active_provider", AsyncMock(return_value=PROVIDER)), patch("app.services.monthly_chapters.request_text_completion", AsyncMock(side_effect=RuntimeError("boom"))):
            async with self.database.AsyncSessionLocal() as session:
                with self.assertRaises(HTTPException) as ctx:
                    await growth_router.generate_chapter(chapter_id, session=session)
                self.assertIn(ctx.exception.status_code, {502, 503})

        async with self.database.AsyncSessionLocal() as session:
            preserved = await session.get(self.models.MonthlyChapter, chapter_id)
            assert preserved is not None
            self.assertEqual(preserved.status, "facts_ready")
            self.assertIsNone(preserved.draft_text)
            self.assertTrue(preserved.fact_snapshot)

    async def test_generate_creates_draft_with_valid_payload(self) -> None:
        import app.routers.growth as growth_router
        from app.services import monthly_chapters

        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="tantan"))
            session.add(
                self.models.Analysis(
                    id="a-q1", skater_id="skater-1", action_type="跳跃", action_subtype="Waltz",
                    video_path="x.mp4", status="completed", highlight_quote="我今天敢往后滑了",
                    quote_speaker="skater", report={"data_quality": "good", "summary": "ok", "training_focus": "落冰"},
                    created_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                )
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)
            chapter_id = chapter.id

        payload = {
            "title": "七月：开始敢往后滑",
            "narrative": "本月记录了一次训练，孩子开始敢往后滑了。",
            "highlights": [
                {"text": "我今天敢往后滑了", "fact_ids": [f["id"] for f in chapter.fact_snapshot["facts"] if f["kind"] == "quote"]},
            ],
            "quote_fact_id": next(f["id"] for f in chapter.fact_snapshot["facts"] if f["kind"] == "quote"),
            "quality_note": "本月可比较指标较少，未生成趋势结论",
        }
        with patch("app.services.monthly_chapters.get_active_provider", AsyncMock(return_value=PROVIDER)), patch("app.services.monthly_chapters.request_text_completion", AsyncMock(return_value=__import__("json").dumps(payload, ensure_ascii=False))):
            async with self.database.AsyncSessionLocal() as session:
                updated = await growth_router.generate_chapter(chapter_id, session=session)
        self.assertEqual(updated.status, "generated")
        self.assertEqual(updated.draft_text[:2], "七月")
        self.assertEqual(updated.generated_payload["title"], payload["title"])

    async def test_generate_rejects_unknown_fact_reference(self) -> None:
        import app.routers.growth as growth_router
        from app.services.monthly_chapters import validate_generated_chapter, GeneratedChapterError
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            _make_skater_and_completed_analysis(session, self.models)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)

        bad_payload = {
            "title": "七月",
            "narrative": "x" * 50,
            "highlights": [{"text": "不存在", "fact_ids": ["milestone:nope"]}],
            "quote_fact_id": None,
            "quality_note": "ok",
        }
        with self.assertRaises(GeneratedChapterError):
            validate_generated_chapter(bad_payload, chapter.fact_snapshot)

        with patch("app.services.monthly_chapters.get_active_provider", AsyncMock(return_value=PROVIDER)), patch("app.services.monthly_chapters.request_text_completion", AsyncMock(return_value=__import__("json").dumps(bad_payload, ensure_ascii=False))):
            async with self.database.AsyncSessionLocal() as session:
                with self.assertRaises(HTTPException):
                    await growth_router.generate_chapter(chapter.id, session=session)

    async def test_patch_final_text_for_nonpublished_chapter(self) -> None:
        import app.routers.growth as growth_router
        from app.schemas import MonthlyChapterPatchRequest

        async with self.database.AsyncSessionLocal() as session:
            _make_skater_and_completed_analysis(session, self.models)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)

        async with self.database.AsyncSessionLocal() as session:
            updated = await growth_router.patch_chapter(
                chapter.id,
                MonthlyChapterPatchRequest(final_text="家长修改后的文字内容，保留本次成长记录。"),
                session=session,
            )
        self.assertEqual(updated.final_text, "家长修改后的文字内容，保留本次成长记录。")

    async def test_publish_requires_text_and_locks_chapter(self) -> None:
        import app.routers.growth as growth_router
        from app.schemas import MonthlyChapterPatchRequest
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            _make_skater_and_completed_analysis(session, self.models)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)

        # publish without any text -> error
        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(HTTPException) as ctx:
                await growth_router.publish_chapter(chapter.id, session=session)
            self.assertEqual(ctx.exception.status_code, 400)

        # set draft_text, then publish copies draft -> final
        async with self.database.AsyncSessionLocal() as session:
            row = await session.get(self.models.MonthlyChapter, chapter.id)
            assert row is not None
            row.draft_text = "AI 生成的初稿文字内容。"
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            published = await growth_router.publish_chapter(chapter.id, session=session)
        self.assertEqual(published.status, "published")
        self.assertIsNotNone(published.published_at)
        self.assertEqual(published.final_text, "AI 生成的初稿文字内容。")

        # immutable: patching a published chapter fails
        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(HTTPException) as ctx:
                await growth_router.patch_chapter(
                    chapter.id,
                    MonthlyChapterPatchRequest(final_text="尝试修改"),
                    session=session,
                )
            self.assertEqual(ctx.exception.status_code, 409)

    async def test_list_chapters_and_regeneration_creates_next_revision(self) -> None:
        import app.routers.growth as growth_router

        async with self.database.AsyncSessionLocal() as session:
            _make_skater_and_completed_analysis(session, self.models)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            first = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)

        async with self.database.AsyncSessionLocal() as session:
            listed = await growth_router.list_chapters("skater-1", "2026-07", session=session)
        self.assertEqual([c.id for c in listed if c.year_month == "2026-07"], [first.id])

        async with self.database.AsyncSessionLocal() as session:
            second = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)
        self.assertEqual(second.revision, 2)
        self.assertEqual(first.revision, 1)
        self.assertNotEqual(first.id, second.id)

    async def test_published_regeneration_creates_next_revision(self) -> None:
        import app.routers.growth as growth_router

        async with self.database.AsyncSessionLocal() as session:
            _make_skater_and_completed_analysis(session, self.models)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)

        async with self.database.AsyncSessionLocal() as session:
            row = await session.get(self.models.MonthlyChapter, chapter.id)
            assert row is not None
            row.draft_text = "初稿"
            row.status = "published"
            row.final_text = "初稿"
            row.published_at = datetime(2026, 7, 31, tzinfo=timezone.utc)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            new_chapter = await growth_router.create_chapter_facts("skater-1", "2026-07", session=session)
        self.assertEqual(new_chapter.revision, 2)
        self.assertEqual(new_chapter.status, "facts_ready")