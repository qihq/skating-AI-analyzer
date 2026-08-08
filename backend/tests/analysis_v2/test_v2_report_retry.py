from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4


class V2ReportRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_retry_uses_persisted_claims_without_legacy_or_source_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            for module_name in [
                "app.database",
                "app.models",
                "app.routers.analysis",
                "app.services.pipeline_version",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.analysis as analysis_router
            from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2
            from app.services.pipeline_version import CURRENT_PIPELINE_VERSION

            database.ensure_storage_dirs()
            await database.init_db()
            analysis_id = str(uuid4())
            missing_video = Path(tmpdir) / "uploads" / analysis_id / "missing.mp4"
            fact = AnalysisFactV2(
                analysis_id=analysis_id,
                event_id=f"{analysis_id}:event:0",
                claim_type="action_profile",
                value="jump",
                authority="v2",
                source_pipeline_fingerprint="sha256:v2-pipeline",
                definition_version="deterministic-action-profile.v2",
                compatibility_group="action-profile/family/v2",
                confidence=0.9,
                sources=("deterministic",),
                source_fingerprints={"deterministic": "sha256:deterministic"},
            )
            facts = AnalysisFactsV2(analysis_id=analysis_id, authority="v2", facts=(fact,))
            report = {
                "summary": "V2 report regenerated",
                "issues": [],
                "improvements": [],
                "training_focus": "review",
                "subscores": {},
                "data_quality": "good",
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        analysis_profile="jump",
                        video_path=str(missing_video),
                        status="completed",
                        retry_from_stage="report",
                        pipeline_version=CURRENT_PIPELINE_VERSION,
                        # Compatibility slots are deliberately absent.
                        vision_structured=None,
                        bio_data=None,
                        analysis_facts={"schema_version": "analysis-facts.v2", **facts.model_dump(mode="json")},
                        facts_authority="v2",
                        facts_schema_version="analysis-facts.v2",
                        source_fact_hash=facts.source_fact_hash,
                        source_fact_revision=1,
                        source_pipeline_fingerprint="sha256:v2-pipeline",
                    )
                )
                await session.commit()

            with (
                patch.object(analysis_router, "_video_path_for_analysis", side_effect=AssertionError("report retry must not resolve source video")),
                patch.object(analysis_router, "generate_report", AsyncMock(return_value=report)) as report_mock,
                patch.object(analysis_router, "build_analysis_prompt_context", AsyncMock(return_value=SimpleNamespace(marker="v2"))),
                patch.object(analysis_router, "calculate_force_score", return_value=80),
                patch.object(analysis_router, "auto_update_skill_progress", AsyncMock(return_value=None)),
                patch.object(analysis_router, "sync_skater_progress", AsyncMock(return_value=None)),
                patch.object(analysis_router, "suggest_memory_updates", AsyncMock(return_value=None)),
            ):
                await analysis_router.process_analysis(analysis_id, retry_from="report")

            report_mock.assert_awaited_once()
            self.assertEqual(report_mock.await_args.kwargs["fused_claims"][0].value, "jump")
            self.assertEqual(report_mock.await_args.args[1], {})
            self.assertEqual(report_mock.await_args.args[2], {})
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertEqual(saved.retry_from_stage, None)
                self.assertEqual(saved.report["summary"], "V2 report regenerated")
                self.assertIsNone(saved.vision_structured)
                self.assertIsNone(saved.bio_data)
                self.assertEqual(saved.facts_authority, "v2")

    async def test_invalid_declared_v2_facts_fail_closed_without_legacy_fallback(self) -> None:
        """A V2 record with a broken envelope must not regenerate from legacy slots."""

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            for module_name in [
                "app.database",
                "app.models",
                "app.routers.analysis",
                "app.services.pipeline_version",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.analysis as analysis_router
            from app.services.pipeline_version import CURRENT_PIPELINE_VERSION

            database.ensure_storage_dirs()
            await database.init_db()
            analysis_id = str(uuid4())
            legacy_vision = {"frame_analysis": [{"phase": "legacy"}]}
            legacy_bio = {"profile_evidence": {"source": "legacy"}}
            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        analysis_profile="jump",
                        video_path=str(Path(tmpdir) / "missing.mp4"),
                        status="completed",
                        retry_from_stage="report",
                        pipeline_version=CURRENT_PIPELINE_VERSION,
                        vision_structured=legacy_vision,
                        bio_data=legacy_bio,
                        # Declared V2, but deliberately malformed / empty.
                        analysis_facts={"schema_version": "analysis-facts.v2", "authority": "v2", "facts": []},
                        facts_authority="v2",
                        facts_schema_version="analysis-facts.v2",
                    )
                )
                await session.commit()

            with patch.object(analysis_router, "generate_report", AsyncMock()) as report_mock:
                await analysis_router.process_analysis(analysis_id, retry_from="report")

            report_mock.assert_not_awaited()
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "failed")
                self.assertEqual(saved.error_code, "UNKNOWN_ERROR")
                self.assertEqual(saved.vision_structured, legacy_vision)
                self.assertEqual(saved.bio_data, legacy_bio)
                self.assertEqual(saved.facts_authority, "v2")
