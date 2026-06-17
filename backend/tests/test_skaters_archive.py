from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SkaterArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_archive_does_not_load_processing_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"

            for module_name in [
                "app.database",
                "app.models",
                "app.routers.skaters",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.skaters as skaters_router

            database.ensure_storage_dirs()
            await database.init_db()

            async with database.AsyncSessionLocal() as session:
                skater = models.Skater(id="skater-1", name="tantan", display_name="Tantan", is_default=True)
                analysis = models.Analysis(
                    id="analysis-1",
                    skater_id=skater.id,
                    action_type="jump",
                    skill_category="jump",
                    video_path="video.mp4",
                    status="completed",
                    report={"summary": "stable jump"},
                    processing_logs=[{"message": "x" * 100_000}],
                )
                session.add_all([skater, analysis])
                await session.commit()

            original_build_report_snippet = skaters_router.build_report_snippet

            def assert_lightweight_snippet(analysis: models.Analysis) -> str:
                self.assertNotIn("processing_logs", analysis.__dict__)
                return original_build_report_snippet(analysis)

            async with database.AsyncSessionLocal() as session:
                with patch.object(skaters_router, "build_report_snippet", side_effect=assert_lightweight_snippet):
                    payload = await skaters_router.get_skater_archive("skater-1", session=session)

            self.assertEqual(payload.stats.total_records, 1)
            self.assertEqual(payload.timeline[0].report_snippet, "stable jump")

    async def test_archive_supports_limit_offset_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"

            for module_name in [
                "app.database",
                "app.models",
                "app.routers.skaters",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.skaters as skaters_router

            database.ensure_storage_dirs()
            await database.init_db()

            async with database.AsyncSessionLocal() as session:
                skater = models.Skater(id="skater-1", name="tantan", display_name="Tantan", is_default=True)
                session.add(skater)
                for index in range(3):
                    session.add(
                        models.Analysis(
                            id=f"analysis-{index}",
                            skater_id=skater.id,
                            action_type="jump",
                            video_path=f"video-{index}.mp4",
                            status="completed",
                            report={"summary": f"summary {index}"},
                        )
                    )
                await session.commit()

            async with database.AsyncSessionLocal() as session:
                first_page = await skaters_router.get_skater_archive("skater-1", limit=2, offset=0, session=session)
                second_page = await skaters_router.get_skater_archive("skater-1", limit=2, offset=2, session=session)

            self.assertEqual(first_page.stats.total_records, 3)
            self.assertEqual(len(first_page.timeline), 2)
            self.assertTrue(first_page.has_more)
            self.assertEqual(first_page.limit, 2)
            self.assertEqual(first_page.offset, 0)
            self.assertEqual(len(second_page.timeline), 1)
            self.assertFalse(second_page.has_more)
            self.assertEqual(second_page.offset, 2)


if __name__ == "__main__":
    unittest.main()
