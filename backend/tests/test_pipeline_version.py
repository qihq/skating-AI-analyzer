from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.services.pipeline_version import CURRENT_PIPELINE_VERSION


class PipelineVersionPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def test_current_pipeline_version_is_v5_2_9(self) -> None:
        self.assertEqual(CURRENT_PIPELINE_VERSION, "v5.2.9")

    async def test_init_db_adds_pipeline_columns_and_new_analysis_uses_current_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"

            for module_name in [
                "app.database",
                "app.models",
                "app.services.pipeline_version",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            from app.services.pipeline_version import CURRENT_PIPELINE_VERSION

            database.ensure_storage_dirs()
            await database.init_db()

            async with database.engine.begin() as conn:
                result = await conn.execute(text("PRAGMA table_info(analyses)"))
                columns = {row[1]: row for row in result.fetchall()}
                self.assertIn("pipeline_version", columns)
                self.assertIn("processing_timings", columns)
                self.assertIn("retry_from_stage", columns)

            async with database.AsyncSessionLocal() as session:
                analysis = models.Analysis(
                    id=str(uuid4()),
                    action_type="跳跃",
                    video_path="/tmp/demo.mp4",
                    pipeline_version=CURRENT_PIPELINE_VERSION,
                    processing_timings={"extract_frames_s": 0.12, "total_s": 0.34},
                )
                session.add(analysis)
                await session.commit()

            async with database.engine.begin() as conn:
                result = await conn.execute(text("SELECT pipeline_version, processing_timings FROM analyses"))
                stored_pipeline_version, stored_timings = result.one()
                self.assertEqual(stored_pipeline_version, CURRENT_PIPELINE_VERSION)
                self.assertIsNotNone(stored_timings)


if __name__ == "__main__":
    unittest.main()
