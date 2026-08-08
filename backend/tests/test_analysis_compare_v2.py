from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4


def _reset_modules() -> None:
    for name in ("app.database", "app.models", "app.routers.analysis"):
        sys.modules.pop(name, None)


class AnalysisCompareV2Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'test.db'}"
        _reset_modules()
        import app.database as database
        import app.models as models
        import app.routers.analysis as router

        self.database, self.models, self.router = database, models, router
        database.ensure_storage_dirs()
        await database.init_db()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    def _fact(self, *, analysis_id: str, event_id: str, claim_type: str, value, definition: str = "v2-score.v1", group: str = "score/jump/v2", unit: str | None = "points"):
        from app.analysis_v2.facts import AnalysisFactV2, FactPermission

        return AnalysisFactV2(
            analysis_id=analysis_id,
            event_id=event_id,
            claim_type=claim_type,
            value=value,
            authority="v2",
            source_pipeline_fingerprint="pipeline-v2-test",
            definition_version=definition,
            compatibility_group=group,
            unit=unit,
            status="confirmed",
            observability="observable",
            permissions=FactPermission(comparison=True, coaching=True, aggregation=True),
        )

    async def _insert_pair(self, *, incompatible: bool = False):
        from app.analysis_v2.fact_consumers import persist_analysis_facts
        from app.analysis_v2.facts import AnalysisFactsV2

        skater_id = str(uuid4())
        left_id, right_id = str(uuid4()), str(uuid4())
        now = datetime.now(timezone.utc)
        async with self.database.AsyncSessionLocal() as session:
            for analysis_id, created_at in ((left_id, now), (right_id, now + timedelta(days=1))):
                session.add(self.models.Analysis(
                    id=analysis_id,
                    skater_id=skater_id,
                    action_type="跳跃",
                    action_subtype="一周跳",
                    analysis_profile="jump",
                    pipeline_version="test",
                    video_path="missing-source.mp4",
                    status="completed",
                    # Deliberately disagree with the V2 facts: ordinary V2
                    # comparison must not read this compatibility scalar.
                    force_score=999 if analysis_id == left_id else 1,
                    report={"summary": "raw must not be read", "issues": [{"category": "raw", "description": "raw issue", "severity": "high"}]},
                    bio_data={"jump_metrics_status": "ok", "jump_metrics": {"air_time_seconds": 999}},
                    created_at=created_at,
                    updated_at=created_at,
                ))
            await session.commit()
            left = await session.get(self.models.Analysis, left_id)
            right = await session.get(self.models.Analysis, right_id)
            assert left is not None and right is not None
            left_facts = AnalysisFactsV2(analysis_id=left_id, authority="v2", facts=(
                self._fact(analysis_id=left_id, event_id="left-event", claim_type="action_profile", value="jump", definition="profile.v2", group="action-profile/jump/v2", unit=None),
                self._fact(analysis_id=left_id, event_id="left-event", claim_type="force_score", value=70),
                self._fact(analysis_id=left_id, event_id="left-event", claim_type="metric_air_time_seconds", value=0.70, definition="metric-air.v2", group="jump-metric/air_time_seconds/s"),
            ))
            right_metric_definition = "metric-air.v3" if incompatible else "metric-air.v2"
            right_metric_group = "jump-metric/air_time_seconds/v3" if incompatible else "jump-metric/air_time_seconds/s"
            right_facts = AnalysisFactsV2(analysis_id=right_id, authority="v2", facts=(
                self._fact(analysis_id=right_id, event_id="right-event", claim_type="action_profile", value="jump", definition="profile.v2", group="action-profile/jump/v2", unit=None),
                self._fact(analysis_id=right_id, event_id="right-event", claim_type="force_score", value=82),
                self._fact(analysis_id=right_id, event_id="right-event", claim_type="metric_air_time_seconds", value=0.82, definition=right_metric_definition, group=right_metric_group),
            ))
            persist_analysis_facts(left, left_facts)
            persist_analysis_facts(right, right_facts)
            await session.commit()
        return left_id, right_id

    async def test_immediate_compare_uses_v2_facts_and_never_legacy_raw(self) -> None:
        left_id, right_id = await self._insert_pair()
        with patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=None)), patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="")):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.router.compare_analyses(left_id, right_id, session=session)
        self.assertEqual(result.score_delta, 12)
        self.assertIsNotNone(result.fact_comparison)
        assert result.fact_comparison is not None
        self.assertEqual(result.fact_comparison.left_authority, "v2")
        self.assertTrue(any(item.key == "metric_air_time_seconds" and abs(float(item.delta or 0) - 0.12) < 1e-6 for item in result.metric_deltas))
        self.assertEqual(result.summary.improved, [])
        self.assertEqual(result.summary.added, [])
        self.assertIsNotNone(result.video_compare)
        assert result.video_compare is not None
        self.assertFalse(result.video_compare.before.available)
        self.assertFalse(result.video_compare.after.available)
        # Deterministic fact deltas remain usable even when source media has
        # already been cleaned up.
        self.assertEqual(result.video_compare.before.missing_reason, "原视频已清理或不可用")

    async def test_v2_compare_refuses_cross_definition_and_persists_provenance(self) -> None:
        left_id, right_id = await self._insert_pair(incompatible=True)
        with patch("app.routers.analysis._run_full_video_ai_for_compare", AsyncMock(return_value=None)) as video_ai_mock:
            async with self.database.AsyncSessionLocal() as session:
                created = await self.router.create_analysis_comparison(self.router.AnalysisComparisonCreateRequest(id_a=left_id, id_b=right_id), self.router.BackgroundTasks(), session=session)
                await self.router.process_analysis_comparison(created.id)
                stored = await session.get(self.models.AnalysisComparison, created.id)
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored.facts_authority, "v2")
                self.assertTrue(stored.source_fact_hash)
                self.assertTrue(stored.generation_fingerprint)
                comparison = (stored.result_json or {}).get("fact_comparison")
                self.assertIsInstance(comparison, dict)
                assert isinstance(comparison, dict)
                self.assertTrue(any(item.get("reason") == "cross_definition_delta_refused" for item in comparison.get("excluded", [])))
                self.assertFalse(any(item.get("claim_type") == "metric_air_time_seconds" for item in comparison.get("deltas", [])))
                video_ai_mock.assert_not_awaited()

    async def test_persisted_compare_retry_keeps_fact_hash(self) -> None:
        left_id, right_id = await self._insert_pair()
        with patch("app.routers.analysis._run_full_video_ai_for_compare", AsyncMock(return_value=None)) as video_ai_mock:
            async with self.database.AsyncSessionLocal() as session:
                created = await self.router.create_analysis_comparison(self.router.AnalysisComparisonCreateRequest(id_a=left_id, id_b=right_id), self.router.BackgroundTasks(), session=session)
                await self.router.process_analysis_comparison(created.id)
                stored = await session.get(self.models.AnalysisComparison, created.id)
                self.assertIsNotNone(stored)
                assert stored is not None
                original_hash = stored.source_fact_hash
                retried = await self.router.retry_analysis_comparison(created.id, self.router.BackgroundTasks(), session=session)
                self.assertEqual(retried.status, "pending")
                await self.router.process_analysis_comparison(created.id)
                await session.refresh(stored)
                self.assertEqual(stored.source_fact_hash, original_hash)
                video_ai_mock.assert_not_awaited()

    async def test_v2_compare_marks_profile_mismatch_without_delta(self) -> None:
        left_id, right_id = await self._insert_pair()
        async with self.database.AsyncSessionLocal() as session:
            right = await session.get(self.models.Analysis, right_id)
            assert right is not None and isinstance(right.analysis_facts, dict)
            facts = dict(right.analysis_facts)
            raw_facts = list(facts.get("facts") or [])
            for item in raw_facts:
                if isinstance(item, dict) and item.get("claim_type") == "action_profile":
                    item["value"] = "spin"
            facts["facts"] = raw_facts
            # Re-validate through the persistence helper so the collection hash
            # and analysis metadata remain internally consistent.
            from app.analysis_v2.fact_consumers import persist_analysis_facts
            from app.analysis_v2.facts import AnalysisFactsV2
            validated = AnalysisFactsV2.model_validate({key: value for key, value in facts.items() if key not in {"schema_version", "source_fact_hash"}})
            persist_analysis_facts(right, validated)
            await session.commit()
            left = await session.get(self.models.Analysis, left_id)
            assert left is not None
            result = await self.router._build_analysis_compare_response(session, left, right)

        self.assertIsNotNone(result.fact_comparison)
        assert result.fact_comparison is not None
        self.assertTrue(result.fact_comparison.profile_mismatch)
        self.assertTrue(any(item.get("reason") == "profile_mismatch" for item in result.fact_comparison.excluded))
        self.assertEqual(result.metric_deltas, [])
        self.assertIsNone(result.score_delta)
