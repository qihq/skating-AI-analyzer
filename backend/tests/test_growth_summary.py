from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


class GrowthSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmpdir.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'test.db'}"
        for module_name in [
            "app.database",
            "app.models",
            "app.schemas",
            "app.services.growth_summary",
            "app.routers.skaters",
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

    async def test_summary_counts_completed_analyses_and_sessions(self) -> None:
        from app.services.growth_summary import build_growth_summary

        models = self.models
        async with self.database.AsyncSessionLocal() as session:
            session.add(models.Skater(id="skater-1", name="tantan"))
            session.add_all(
                [
                    models.TrainingSession(id="session-1", skater_id="skater-1", session_date=date(2026, 7, 3)),
                    models.TrainingSession(id="session-2", skater_id="skater-1", session_date=date(2026, 6, 28)),
                    models.Analysis(
                        id="analysis-latest",
                        skater_id="skater-1",
                        session_id="session-1",
                        action_type="jump",
                        action_subtype="Loop",
                        video_path="latest.mp4",
                        status="completed",
                        report={"training_focus": "Landing position", "data_quality": "good"},
                        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    ),
                    models.Analysis(
                        id="analysis-old",
                        skater_id="skater-1",
                        session_id="session-1",
                        action_type="jump",
                        video_path="old.mp4",
                        status="completed",
                        created_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
                    ),
                    models.Analysis(
                        id="analysis-failed",
                        skater_id="skater-1",
                        action_type="jump",
                        video_path="failed.mp4",
                        status="failed",
                        created_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    ),
                ]
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            result = await build_growth_summary(
                session,
                "skater-1",
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )

        self.assertEqual(result.lesson_count, 2)
        self.assertEqual(result.completed_analysis_count, 2)
        self.assertEqual(result.current_month_analysis_count, 1)
        self.assertEqual(result.latest_analysis_id, "analysis-latest")
        self.assertEqual(result.current_focus.label, "Landing position")
        self.assertEqual(result.current_focus.quality, "good")
        self.assertNotIn("landing_rate", result.model_dump())

    async def test_milestones_keep_source_and_newest_first(self) -> None:
        from app.services.growth_summary import build_growth_summary

        models = self.models
        async with self.database.AsyncSessionLocal() as session:
            session.add(models.Skater(id="skater-1", name="tantan"))
            session.add_all(
                [
                    models.SkillNode(
                        id="skill-auto", chapter="fs1", chapter_order=1, stage=1,
                        stage_name="Basics", group_name="Jumps", sort_order=1,
                        name="Waltz jump", xp=100,
                    ),
                    models.SkillNode(
                        id="skill-parent", chapter="fs1", chapter_order=1, stage=1,
                        stage_name="Basics", group_name="Skating", sort_order=2,
                        name="Back crossovers", xp=100,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    models.SkaterSkill(
                        id="progress-auto", skater_id="skater-1", skill_id="skill-auto",
                        status="unlocked", unlocked_by="auto",
                        unlocked_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                    ),
                    models.Analysis(
                        id="analysis-auto-unlock", skater_id="skater-1", action_type="jump",
                        video_path="auto.mp4", status="completed", auto_unlocked_skill="skill-auto",
                        created_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                    ),
                    models.SkaterSkill(
                        id="progress-parent", skater_id="skater-1", skill_id="skill-parent",
                        status="unlocked", unlocked_by="parent", unlock_note="Three in a row",
                        unlocked_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
                    ),
                ]
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            result = await build_growth_summary(session, "skater-1", milestone_limit=8)

        self.assertEqual(result.milestone_count, 2)
        self.assertEqual([item.source_skill_id for item in result.recent_milestones], ["skill-parent", "skill-auto"])
        self.assertEqual(result.recent_milestones[0].verification, "parent_confirmed")
        self.assertEqual(result.recent_milestones[1].verification, "system_detected")
        self.assertEqual(result.recent_milestones[0].note, "Three in a row")
        self.assertEqual(result.recent_milestones[1].source_analysis_ids, ["analysis-auto-unlock"])

    async def test_v2_growth_focus_excludes_legacy_report_when_no_coaching_fact(self) -> None:
        from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2
        from app.services.growth_summary import build_growth_summary

        models = self.models
        fact_set = AnalysisFactsV2(
            analysis_id="analysis-v2",
            authority="v2",
            facts=(
                AnalysisFactV2(
                    analysis_id="analysis-v2",
                    claim_type="action_profile",
                    value="jump",
                    authority="v2",
                    source_pipeline_fingerprint="v2:test",
                    definition_version="action-profile.v2",
                ),
            ),
        )
        async with self.database.AsyncSessionLocal() as session:
            session.add(models.Skater(id="skater-1", name="tantan"))
            session.add(
                models.Analysis(
                    id="analysis-v2",
                    skater_id="skater-1",
                    action_type="jump",
                    video_path="v2.mp4",
                    status="completed",
                    report={"training_focus": "legacy-only focus"},
                    analysis_facts={"schema_version": "analysis-facts.v2", **fact_set.model_dump(mode="json")},
                    facts_authority="v2",
                    facts_schema_version="analysis-facts.v2",
                    source_fact_hash=fact_set.source_fact_hash,
                    source_fact_revision=1,
                    source_pipeline_fingerprint="v2:test",
                )
            )
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            result = await build_growth_summary(session, "skater-1")

        assert result.current_focus is not None
        self.assertEqual(result.current_focus.label, "当前没有可确认的训练重点")
        self.assertIn("不使用旧报告回填", result.current_focus.excluded_reason or "")

    async def test_route_rejects_unknown_skater(self) -> None:
        import app.routers.skaters as skaters_router
        from fastapi import HTTPException

        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(HTTPException) as raised:
                await skaters_router.get_growth_summary("missing", session=session)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
