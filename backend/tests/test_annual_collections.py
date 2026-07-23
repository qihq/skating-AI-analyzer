from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


class AnnualCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmpdir.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'test.db'}"
        for module_name in [
            "app.database",
            "app.models",
            "app.schemas",
            "app.services.annual_collections",
        ]:
            sys.modules.pop(module_name, None)

        import app.database as database
        import app.models as models

        self.database = database
        self.models = models
        database.ensure_storage_dirs()
        await database.init_db()

    async def asyncTearDown(self) -> None:
        await self.database.engine.dispose()
        self.tmpdir.cleanup()

    async def test_snapshot_uses_only_selected_published_chapters_in_year(self) -> None:
        from app.services.annual_collections import build_annual_snapshot, annual_source_hash

        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="Tantan"))
            session.add_all([
                self._chapter("chapter-january", "2026-01", "published", "January final"),
                self._chapter("chapter-draft", "2026-02", "generated", "Draft must not appear"),
                self._chapter("chapter-prior-year", "2025-12", "published", "Old year"),
            ])
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            snapshot = await build_annual_snapshot(
                session,
                "skater-1",
                2026,
                ["chapter-january"],
                [],
            )

        self.assertEqual([item["id"] for item in snapshot["chapters"]], ["chapter-january"])
        self.assertEqual(snapshot["chapters"][0]["final_text"], "January final")
        self.assertEqual(snapshot["coverage"]["published_chapter_count"], 1)
        self.assertEqual(annual_source_hash(snapshot), annual_source_hash(snapshot))

    async def test_snapshot_rejects_duplicate_unpublished_and_wrong_year_chapters(self) -> None:
        from app.services.annual_collections import AnnualCollectionValidationError, build_annual_snapshot

        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="Tantan"))
            session.add_all([
                self._chapter("chapter-published", "2026-01", "published", "Final"),
                self._chapter("chapter-draft", "2026-02", "generated", "Draft"),
                self._chapter("chapter-old", "2025-12", "published", "Old"),
            ])
            await session.commit()

        cases = [
            ["chapter-published", "chapter-published"],
            ["chapter-draft"],
            ["chapter-old"],
        ]
        for chapter_ids in cases:
            async with self.database.AsyncSessionLocal() as session:
                with self.assertRaises(AnnualCollectionValidationError):
                    await build_annual_snapshot(session, "skater-1", 2026, chapter_ids, [])

    async def test_snapshot_rejects_chapter_with_mismatched_fact_hash(self) -> None:
        from app.services.annual_collections import AnnualCollectionValidationError, build_annual_snapshot

        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="Tantan"))
            chapter = self._chapter("chapter-tampered", "2026-01", "published", "Final")
            chapter.source_hash = "b" * 64
            session.add(chapter)
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaisesRegex(AnnualCollectionValidationError, "source hash"):
                await build_annual_snapshot(session, "skater-1", 2026, ["chapter-tampered"], [])

    async def test_snapshot_rejects_milestone_from_another_year(self) -> None:
        from app.services.annual_collections import AnnualCollectionValidationError, build_annual_snapshot

        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="Tantan"))
            session.add(self._chapter("chapter-published", "2026-01", "published", "Final"))
            session.add(self.models.SkillNode(
                id="skill-old", chapter="c", chapter_order=1, stage=1, stage_name="Basics",
                group_name="Jumps", sort_order=1, name="Old milestone", xp=1,
            ))
            session.add(self.models.SkaterSkill(
                id="milestone-old", skater_id="skater-1", skill_id="skill-old", status="unlocked",
                unlocked_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
            ))
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(AnnualCollectionValidationError):
                await build_annual_snapshot(session, "skater-1", 2026, ["chapter-published"], ["milestone-old"])

    async def test_collection_revision_is_unique_per_skater_and_year(self) -> None:
        async with self.database.AsyncSessionLocal() as session:
            session.add(self.models.Skater(id="skater-1", name="Tantan"))
            session.add_all([
                self.models.AnnualCollection(
                    id="annual-1", skater_id="skater-1", year=2026, revision=1,
                    status="ready", title="2026 annual", selected_chapter_ids=[], selected_milestone_ids=[],
                    snapshot={}, source_hash="a" * 64,
                ),
                self.models.AnnualCollection(
                    id="annual-2", skater_id="skater-1", year=2026, revision=1,
                    status="ready", title="2026 annual", selected_chapter_ids=[], selected_milestone_ids=[],
                    snapshot={}, source_hash="b" * 64,
                ),
            ])
            with self.assertRaises(Exception):
                await session.commit()

    def _chapter(self, chapter_id: str, year_month: str, status: str, final_text: str):
        from app.services.monthly_facts import monthly_source_hash

        facts = {
            "schema_version": "monthly_facts.v1",
            "coverage": {"sessions": 2, "completed_analyses": 3, "comparable_metrics": 0},
            "facts": [{"id": "quote:1", "kind": "quote", "text": "I kept trying", "speaker": "skater"}],
            "representative_frames": [],
        }
        return self.models.MonthlyChapter(
            id=chapter_id,
            skater_id="skater-1",
            year_month=year_month,
            revision=1,
            status=status,
            fact_snapshot=facts,
            source_hash=monthly_source_hash(facts),
            final_text=final_text,
            representative_frames=[],
            published_at=datetime(2026, 1, 31, tzinfo=timezone.utc) if status == "published" else None,
        )


if __name__ == "__main__":
    unittest.main()
