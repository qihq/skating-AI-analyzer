from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


class SkillMutationTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_lock_survives_skill_tree_refresh_for_default_skater(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"

            for module_name in [
                "app.database",
                "app.models",
                "app.services.skills",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            from app.services.skills import PARENT_LOCKED_STATUS, get_skater_skill_payloads, lock_skill

            database.ensure_storage_dirs()
            await database.init_db()

            async with database.AsyncSessionLocal() as session:
                skater = models.Skater(id="skater-1", name="tantan", display_name="Tantan", is_default=True)
                node = models.SkillNode(
                    id="ss_all",
                    chapter="snowplow",
                    chapter_order=0,
                    stage=1,
                    stage_name="冰场启蒙",
                    group_name="冰上启蒙",
                    sort_order=1,
                    name="犁式刹车全套",
                    emoji="P",
                    xp=120,
                    requires=[],
                    unlock_config=None,
                    action_type=None,
                    is_parent_only=False,
                    metadata_json={},
                )
                row = models.SkaterSkill(
                    skater_id=skater.id,
                    skill_id=node.id,
                    status="unlocked",
                    unlocked_by="parent",
                )
                session.add_all([skater, node, row])
                await session.commit()

                response = await lock_skill(session, skater.id, node.id)
                self.assertEqual(response["status"], "locked")
                await session.commit()

                payloads = await get_skater_skill_payloads(session, skater.id)
                self.assertEqual(payloads[0]["status"], "locked")

                stored = await session.get(models.SkaterSkill, row.id)
                self.assertIsNotNone(stored)
                self.assertEqual(stored.status, PARENT_LOCKED_STATUS)


if __name__ == "__main__":
    unittest.main()
