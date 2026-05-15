from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_analysis_keyframe_candidates import _motion_scores, _pose_data


class AutoEvalExportApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_eval_snapshot_export_filters_and_sorts_completed_records(self) -> None:
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

            base_time = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
            records = [
                {
                    "id": str(uuid4()),
                    "action_type": "跳跃",
                    "analysis_profile": "jump",
                    "status": "completed",
                    "created_at": base_time + timedelta(hours=1),
                    "cross_validation": {
                        "auto_eval": {"auto_eval_version": "v1", "key_frame_order_valid": True},
                        "fusion_diagnostics": {"conflict_level": "medium", "downgraded_reasons": ["weighted_fusion_medium_conflict"], "needs_human_review": False},
                    },
                    "bio_data": {"key_frame_candidates": {"T": {"frame_id": "frame_0004"}}},
                },
                {
                    "id": str(uuid4()),
                    "action_type": "旋转",
                    "analysis_profile": "spin",
                    "status": "completed",
                    "created_at": base_time + timedelta(hours=2),
                    "cross_validation": {
                        "auto_eval": {"auto_eval_version": "v1", "key_frame_order_valid": False},
                        "fusion_diagnostics": {"conflict_level": "high", "downgraded_reasons": ["weighted_fusion_high_conflict"], "needs_human_review": True},
                    },
                    "bio_data": {"key_frame_candidates": {"T": {"frame_id": "frame_0007"}}},
                },
                {
                    "id": str(uuid4()),
                    "action_type": "跳跃",
                    "analysis_profile": "jump",
                    "status": "processing",
                    "created_at": base_time + timedelta(hours=3),
                    "cross_validation": {"auto_eval": {"auto_eval_version": "v1"}},
                    "bio_data": {"key_frame_candidates": {"T": {"frame_id": "frame_0008"}}},
                },
            ]

            async with database.AsyncSessionLocal() as session:
                for payload in records:
                    analysis = models.Analysis(
                        id=payload["id"],
                        action_type=payload["action_type"],
                        analysis_profile=payload["analysis_profile"],
                        pipeline_version=CURRENT_PIPELINE_VERSION,
                        video_path=str(Path(tmpdir) / "uploads" / payload["id"] / "source.mp4"),
                        frame_motion_scores=_motion_scores(),
                        pose_data=_pose_data(),
                        bio_data=payload["bio_data"],
                        target_lock={"status": "locked"},
                        target_lock_status="locked",
                        action_window_start=0.0,
                        action_window_end=0.8,
                        source_fps=30.0,
                        is_slow_motion=False,
                        status=payload["status"],
                        created_at=payload["created_at"],
                        updated_at=payload["created_at"],
                        cross_validation=payload["cross_validation"],
                    )
                    session.add(analysis)
                await session.commit()

            with (
                patch("app.routers.analysis.encode_frames", AsyncMock()),
                patch("app.routers.analysis.analyze_frames_dual", AsyncMock()),
                patch("app.routers.analysis.dual_path_summary", return_value={}),
                patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())),
            ):
                async with database.AsyncSessionLocal() as session:
                    snapshots = await analysis_router.list_auto_eval_snapshots(session=session)
                    self.assertEqual([item.analysis_id for item in snapshots], [records[1]["id"], records[0]["id"]])
                    self.assertEqual(snapshots[0].analysis_profile, "spin")
                    self.assertEqual(snapshots[0].action_type, "旋转")
                    self.assertIn("conflict_level=high", snapshots[0].fusion_diagnostics)
                    self.assertEqual(snapshots[1].key_frame_candidates["T"]["frame_id"], "frame_0004")

                    filtered = await analysis_router.list_auto_eval_snapshots(
                        analysis_profile="jump",
                        action_type="跳跃",
                        session=session,
                    )
                    self.assertEqual([item.analysis_id for item in filtered], [records[0]["id"]])

                    empty = await analysis_router.list_auto_eval_snapshots(
                        analysis_profile="spiral",
                        session=session,
                    )
                    self.assertEqual(empty, [])

    async def test_auto_eval_snapshot_export_returns_empty_list_when_no_completed_rows(self) -> None:
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
                snapshots = await analysis_router.list_auto_eval_snapshots(session=session)
                self.assertEqual(snapshots, [])


if __name__ == "__main__":
    unittest.main()
