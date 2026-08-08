from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _reload_app_modules() -> None:
    for module_name in ["app.database", "app.models", "app.routers.analysis"]:
        sys.modules.pop(module_name, None)


async def _make_db(tmpdir: str):
    os.environ["DATA_DIR"] = tmpdir
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
    _reload_app_modules()
    import app.database as database

    database.ensure_storage_dirs()
    await database.init_db()
    return database


def test_training_plan_snapshot_preserves_previous_fact_artifact():
    import asyncio

    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = await _make_db(tmpdir)
            import app.models as models
            import app.routers.analysis as analysis_router

            async with database.AsyncSessionLocal() as session:
                session.add(models.Skater(id="skater-1", name="kid"))
                session.add(models.Analysis(id="analysis-1", skater_id="skater-1", action_type="jump", video_path="source.mp4", status="completed"))
                plan = models.TrainingPlan(
                    id="plan-1",
                    analysis_id="analysis-1",
                    skater_id="skater-1",
                    plan_json={"title": "old", "focus_skill": "landing", "days": [], "generation_status": "ai"},
                    facts_authority="v2",
                    facts_schema_version="analysis-facts.v2",
                    source_fact_hash="old-hash",
                    source_fact_revision=1,
                    source_pipeline_fingerprint="old-pipeline",
                    generation_fingerprint="old-generation",
                )
                session.add(plan)
                await session.commit()

                snapshot = await analysis_router._snapshot_training_plan(session, plan)
                plan.plan_json = {"title": "new", "focus_skill": "axis", "days": [], "generation_status": "ai"}
                plan.source_fact_hash = "new-hash"
                await session.commit()

                stored = await session.get(models.TrainingPlanRevision, snapshot.id)
                assert stored is not None
                assert stored.revision == 1
                assert stored.plan_json["title"] == "old"
                assert stored.source_fact_hash == "old-hash"

                revisions = await analysis_router.list_plan_revisions("plan-1", session)
                assert len(revisions) == 1
                assert revisions[0].plan_json.title == "old"

    asyncio.run(scenario())
