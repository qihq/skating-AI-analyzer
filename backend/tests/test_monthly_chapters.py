from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class MonthlyChapterPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'test.db'}"

        for module_name in ["app.database", "app.models", "app.services.pipeline_version"]:
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

    async def test_table_created_with_required_columns(self) -> None:
        import sqlite3

        conn = sqlite3.connect(Path(self.tmp.name) / "test.db")
        try:
            rows = {row[1]: row for row in conn.execute("PRAGMA table_info(monthly_chapters)").fetchall()}
        finally:
            conn.close()

        for column in [
            "id", "skater_id", "year_month", "revision", "status", "fact_snapshot",
            "source_hash", "draft_text", "final_text", "quality_flags",
            "representative_frames", "published_at",
        ]:
            self.assertIn(column, rows)

    async def test_unique_constraint_on_skater_month_revision(self) -> None:
        import app.models as models
        from sqlalchemy.exc import IntegrityError

        snapshot = {"schema_version": "monthly_facts.v1", "facts": []}
        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.MonthlyChapter(
                    id=str(uuid4()),
                    skater_id="skater-1",
                    year_month="2026-07",
                    revision=1,
                    status="facts_ready",
                    fact_snapshot=snapshot,
                    source_hash="abc",
                    quality_flags=[],
                    representative_frames=[],
                )
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.MonthlyChapter(
                    id=str(uuid4()),
                    skater_id="skater-1",
                    year_month="2026-07",
                    revision=1,
                    status="facts_ready",
                    fact_snapshot=snapshot,
                    source_hash="abc",
                    quality_flags=[],
                    representative_frames=[],
                )
            )
            with self.assertRaises(IntegrityError):
                await session.commit()

    async def test_status_defaults_to_facts_ready(self) -> None:
        import app.models as models

        chapter_id = str(uuid4())
        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.MonthlyChapter(
                    id=chapter_id,
                    skater_id="skater-1",
                    year_month="2026-07",
                    revision=1,
                    fact_snapshot={"schema_version": "monthly_facts.v1"},
                    source_hash="abc",
                    quality_flags=[],
                    representative_frames=[],
                )
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await session.get(models.MonthlyChapter, chapter_id)
            self.assertIsNotNone(chapter)
            assert chapter is not None
            self.assertEqual(chapter.status, "facts_ready")

    async def test_json_fields_round_trip(self) -> None:
        import app.models as models

        chapter_id = str(uuid4())
        snapshot = {"schema_version": "monthly_facts.v1", "facts": [{"id": "session_count", "kind": "count", "text": "本月记录 4 次", "value": 4}]}
        frames = [{"analysis_id": "a1", "frame_id": "f1", "timestamp": 0.5, "phase": "落冰", "evidence_source": "milestone"}]
        flags = ["insufficient_comparable_evidence"]
        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.MonthlyChapter(
                    id=chapter_id,
                    skater_id="skater-1",
                    year_month="2026-07",
                    revision=1,
                    fact_snapshot=snapshot,
                    source_hash="abc",
                    quality_flags=flags,
                    representative_frames=frames,
                )
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await session.get(models.MonthlyChapter, chapter_id)
            assert chapter is not None
            self.assertEqual(chapter.fact_snapshot, snapshot)
            self.assertEqual(chapter.quality_flags, flags)
            self.assertEqual(chapter.representative_frames, frames)

    async def test_publish_sets_published_at(self) -> None:
        import app.models as models

        chapter_id = str(uuid4())
        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.MonthlyChapter(
                    id=chapter_id,
                    skater_id="skater-1",
                    year_month="2026-07",
                    revision=1,
                    status="published",
                    fact_snapshot={"schema_version": "monthly_facts.v1"},
                    source_hash="abc",
                    draft_text="本月记录了四次训练……",
                    final_text="本月记录了四次训练……",
                    quality_flags=[],
                    representative_frames=[],
                    published_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            chapter = await session.get(models.MonthlyChapter, chapter_id)
            assert chapter is not None
            self.assertEqual(chapter.status, "published")
            self.assertIsNotNone(chapter.published_at)
            self.assertEqual(chapter.final_text, "本月记录了四次训练……")

    async def test_public_schema_round_trips(self) -> None:
        import app.models as models
        from app.schemas import MonthlyChapterPublic

        chapter_id = str(uuid4())
        snapshot = {"schema_version": "monthly_facts.v1", "facts": []}
        now = datetime.now(timezone.utc)
        async with self.database.AsyncSessionLocal() as session:
            chapter = models.MonthlyChapter(
                id=chapter_id,
                skater_id="skater-1",
                year_month="2026-07",
                revision=1,
                status="generated",
                fact_snapshot=snapshot,
                source_hash="abc",
                published_at=None,
            )
            session.add(chapter)
            await session.commit()
            await session.refresh(chapter)
            public = MonthlyChapterPublic.model_validate(chapter)
            self.assertEqual(public.id, chapter_id)
            self.assertEqual(public.year_month, "2026-07")
            self.assertEqual(public.revision, 1)
            self.assertEqual(public.status, "generated")
            self.assertEqual(public.fact_snapshot, snapshot)
            self.assertEqual(public.source_hash, "abc")
            self.assertEqual(public.quality_flags, [])
            self.assertEqual(public.representative_frames, [])
            self.assertIsNone(public.published_at)

    async def test_published_revision_preserves_original_and_recycle_lifecycle(self) -> None:
        import app.models as models
        import app.routers.growth as growth
        from app.schemas import MonthlyChapterRevisionRequest
        from app.services.auth import hash_pin

        original_id = str(uuid4())
        snapshot = {"schema_version": "monthly_facts.v1", "facts": [{"id": "one"}]}
        async with self.database.AsyncSessionLocal() as session:
            session.add(models.Skater(id="skater-1", name="Tantan"))
            session.add(models.ParentAuth(pin_hash=hash_pin("1234"), pin_length=4))
            session.add(models.MonthlyChapter(
                id=original_id,
                skater_id="skater-1",
                year_month="2026-07",
                revision=1,
                title="原始月报",
                status="published",
                fact_snapshot=snapshot,
                source_hash="abc",
                final_text="原始正文",
                published_at=datetime.now(timezone.utc),
            ))
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            revised = await growth.create_chapter_revision(
                original_id,
                MonthlyChapterRevisionRequest(title="修订月报", final_text="修订正文"),
                x_parent_pin="1234",
                session=session,
            )
            original = await session.get(models.MonthlyChapter, original_id)
            assert original is not None
            self.assertEqual((original.title, original.final_text, original.status), ("原始月报", "原始正文", "published"))
            self.assertEqual(revised.parent_revision_id, original_id)
            self.assertEqual(revised.revision, 2)
            self.assertEqual(revised.fact_snapshot, snapshot)

        async with self.database.AsyncSessionLocal() as session:
            await growth.recycle_chapter(revised.id, x_parent_pin="1234", session=session)
        async with self.database.AsyncSessionLocal() as session:
            active = await growth.list_chapters("skater-1", recycled=False, session=session)
            recycled = await growth.list_chapters("skater-1", recycled=True, session=session)
            self.assertEqual([item.id for item in active], [original_id])
            self.assertEqual([item.id for item in recycled], [revised.id])
            await growth.restore_chapter(revised.id, x_parent_pin="1234", session=session)
            await growth.recycle_chapter(revised.id, x_parent_pin="1234", session=session)
            await growth.permanently_delete_chapter(revised.id, x_parent_pin="1234", session=session)
            self.assertIsNone(await session.get(models.MonthlyChapter, revised.id))
