from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ProviderMetricsApiTests(unittest.TestCase):
    def test_metrics_api_returns_empty_array_without_completed_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"

            for module_name in [
                "app.database",
                "app.models",
                "app.routers.analysis",
                "app.routers.providers",
                "app.services.pipeline_version",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.providers as providers_router
            from app.services.pipeline_version import CURRENT_PIPELINE_VERSION

            database.ensure_storage_dirs()

            async def _prepare() -> list[dict[str, object]]:
                await database.init_db()
                async with database.AsyncSessionLocal() as session:
                    analysis = models.Analysis(
                        id=str(uuid4()),
                        action_type="跳跃",
                        analysis_profile="jump",
                        pipeline_version=CURRENT_PIPELINE_VERSION,
                        video_path=str(Path(tmpdir) / "uploads" / "source.mp4"),
                        status="processing",
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    session.add(analysis)
                    await session.commit()

                async with database.AsyncSessionLocal() as session:
                    return await providers_router.get_provider_metrics(session=session)

            payload = asyncio.run(_prepare())
            self.assertEqual(payload, [])

    def test_metrics_api_aggregates_recent_completed_analyses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"

            for module_name in [
                "app.database",
                "app.models",
                "app.routers.analysis",
                "app.routers.providers",
                "app.services.pipeline_version",
            ]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.providers as providers_router
            from app.services.pipeline_version import CURRENT_PIPELINE_VERSION

            database.ensure_storage_dirs()

            async def _prepare() -> list[dict[str, object]]:
                await database.init_db()
                now = datetime.now(timezone.utc)
                async with database.AsyncSessionLocal() as session:
                    records = [
                        models.Analysis(
                            id=str(uuid4()),
                            action_type="跳跃",
                            analysis_profile="jump",
                            pipeline_version=CURRENT_PIPELINE_VERSION,
                            video_path=str(Path(tmpdir) / "uploads" / "a.mp4"),
                            status="completed",
                            created_at=now - timedelta(days=1),
                            updated_at=now - timedelta(days=1),
                            vision_structured={
                                "provider": "qwen",
                                "json_validity_factor": 0.95,
                                "effective_weight": 0.8,
                                "quality_flags": [],
                            },
                            cross_validation={"conflict_level": "none"},
                        ),
                        models.Analysis(
                            id=str(uuid4()),
                            action_type="跳跃",
                            analysis_profile="jump",
                            pipeline_version=CURRENT_PIPELINE_VERSION,
                            video_path=str(Path(tmpdir) / "uploads" / "b.mp4"),
                            status="completed",
                            created_at=now - timedelta(hours=1),
                            updated_at=now - timedelta(hours=1),
                            vision_structured={
                                "fusion_decisions": [
                                    {
                                        "candidates": [
                                            {
                                                "provider": "doubao",
                                                "factors": {"json_validity_factor": 0.45},
                                                "effective_weight": 0.3,
                                                "rule_flags": ["rule_high_confidence_key_frame_conflict"],
                                            }
                                        ]
                                    }
                                ]
                            },
                            cross_validation={
                                "conflict_level": "high",
                                "fusion_diagnostics": {"needs_human_review": True},
                            },
                        ),
                        models.Analysis(
                            id=str(uuid4()),
                            action_type="旋转",
                            analysis_profile="spin",
                            pipeline_version=CURRENT_PIPELINE_VERSION,
                            video_path=str(Path(tmpdir) / "uploads" / "c.mp4"),
                            status="completed",
                            created_at=now - timedelta(hours=2),
                            updated_at=now - timedelta(hours=2),
                            vision_structured={
                                "provider": "qwen",
                                "quality_flags": ["vision_weighted_fusion_fallback_to_vote"],
                                "json_validity_factor": 0.85,
                                "effective_weight": 0.6,
                            },
                            cross_validation={"conflict_level": "none"},
                        ),
                        models.Analysis(
                            id=str(uuid4()),
                            action_type="跳跃",
                            analysis_profile="jump",
                            pipeline_version=CURRENT_PIPELINE_VERSION,
                            video_path=str(Path(tmpdir) / "uploads" / "d.mp4"),
                            status="completed",
                            created_at=now - timedelta(hours=3),
                            updated_at=now - timedelta(hours=3),
                            vision_structured=None,
                            cross_validation={
                                "conflict_level": "high",
                                "fusion_diagnostics": {
                                    "path_a": {"provider": "qwen", "available": True, "conflict_level": "high", "json_validity_factor": 0.7, "effective_weight": 0.5},
                                    "path_b": {"provider": "doubao", "available": False, "conflict_level": "high", "json_validity_factor": 0.4, "effective_weight": 0.2},
                                },
                            },
                        ),
                    ]
                    session.add_all(records)
                    await session.commit()

                async with database.AsyncSessionLocal() as session:
                    return await providers_router.get_provider_metrics(days=7, analysis_profile="jump", session=session)

            payload = asyncio.run(_prepare())

            self.assertEqual({item.provider for item in payload}, {"doubao", "qwen"})
            self.assertTrue(any(item.failure_rate > 0 for item in payload))
            self.assertTrue(any(item.conflict_rate > 0 for item in payload))


if __name__ == "__main__":
    unittest.main()
