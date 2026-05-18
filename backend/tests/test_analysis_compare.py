from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4


def _reset_app_modules() -> None:
    for module_name in [
        "app.database",
        "app.models",
        "app.routers.analysis",
        "app.services.pipeline_version",
    ]:
        sys.modules.pop(module_name, None)


def _report(score: int, severity: str = "medium") -> dict[str, object]:
    return {
        "summary": "ok",
        "issues": [{"category": "落冰", "description": "落冰不稳", "severity": severity}],
        "improvements": [],
        "training_focus": "稳定落冰",
        "subscores": {
            "takeoff_power": score,
            "rotation_axis": score - 1,
            "arm_coordination": score - 2,
            "landing_absorption": score - 3,
            "core_stability": score - 4,
        },
        "data_quality": "good",
    }


def _bio(score: int) -> dict[str, object]:
    return {
        "key_frames": {"T": "frame_0001", "A": "frame_0002", "L": "frame_0003"},
        "key_frame_candidates": {
            "T": {"frame_id": "frame_0001", "timestamp": 0.1, "confidence": 0.8},
            "A": {"frame_id": "frame_0002", "timestamp": 0.2, "confidence": 0.82},
            "L": {"frame_id": "frame_0003", "timestamp": 0.3, "confidence": 0.84},
        },
        "jump_metrics_status": "ok",
        "jump_metrics": {
            "air_time_seconds": round(score / 100, 2),
            "estimated_height_cm": float(score),
            "takeoff_speed_mps": round(score / 50, 2),
            "rotation_rps": round(score / 40, 2),
            "estimated_rotations": round(score / 80, 2),
        },
        "bio_subscores": {"takeoff_power": score},
        "quality_flags": [],
    }


class AnalysisCompareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'test.db'}"
        _reset_app_modules()

        import app.database as database
        import app.models as models
        import app.routers.analysis as analysis_router

        self.database = database
        self.models = models
        self.analysis_router = analysis_router
        database.ensure_storage_dirs()
        await database.init_db()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    def _make_upload(self, analysis_id: str) -> Path:
        upload_dir = Path(self.tmp.name) / "uploads" / analysis_id
        frames_dir = upload_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        semantic_dir = upload_dir / "semantic_frames"
        semantic_dir.mkdir(parents=True, exist_ok=True)
        video_path = upload_dir / "source.mp4"
        video_path.write_bytes(b"fake-video")
        for index in range(1, 4):
            (frames_dir / f"frame_{index:04d}.jpg").write_bytes(b"fake-frame")
            (semantic_dir / f"semantic_{index:04d}.jpg").write_bytes(b"fake-semantic-frame")
        return video_path

    async def _insert_analysis(
        self,
        *,
        analysis_id: str,
        skater_id: str,
        score: int,
        created_at: datetime,
        action_subtype: str = "一周跳",
        status: str = "completed",
    ) -> None:
        video_path = self._make_upload(analysis_id)
        async with self.database.AsyncSessionLocal() as session:
            session.add(
                self.models.Analysis(
                    id=analysis_id,
                    skater_id=skater_id,
                    action_type="跳跃",
                    action_subtype=action_subtype,
                    analysis_profile="jump",
                    pipeline_version="test",
                    video_path=str(video_path),
                    status=status,
                    force_score=score,
                    report=_report(score),
                    bio_data=_bio(score),
                    frame_motion_scores={
                        "selected": [
                            {"frame_id": "frame_0001", "timestamp": 0.1},
                            {"frame_id": "frame_0002", "timestamp": 0.2},
                            {"frame_id": "frame_0003", "timestamp": 0.3},
                        ],
                        "resolved_keyframes": {
                            "source": "video_ai_refined",
                            "confidence": 0.88,
                            "selected": [
                                {
                                    "frame_id": "semantic_0001",
                                    "timestamp": 0.12,
                                    "phase_code": "takeoff",
                                    "phase_label": "起跳",
                                    "key_moment": "T_takeoff_sec",
                                    "selection_reason": "video_phase_range_motion_peak",
                                    "pre_refine_timestamp": 0.1,
                                    "refinement_method": "local_motion_peak",
                                    "refinement_delta_sec": 0.02,
                                    "confidence": 0.86,
                                },
                                {
                                    "frame_id": "semantic_0002",
                                    "timestamp": 0.24,
                                    "phase_code": "air",
                                    "phase_label": "腾空",
                                    "key_moment": "A_air_sec",
                                    "selection_reason": "video_phase_range_key_moment_motion_nearby",
                                    "pre_refine_timestamp": 0.24,
                                    "refinement_method": "apex_preserved",
                                    "refinement_delta_sec": 0.0,
                                    "confidence": 0.87,
                                },
                                {
                                    "frame_id": "semantic_0003",
                                    "timestamp": 0.36,
                                    "phase_code": "landing",
                                    "phase_label": "落冰",
                                    "key_moment": "L_landing_sec",
                                    "selection_reason": "video_phase_range_skeleton_candidate",
                                    "confidence": 0.88,
                                },
                            ],
                        },
                    },
                    action_window_start=0.1,
                    action_window_end=0.9,
                    source_fps=30.0,
                    is_slow_motion=False,
                    target_lock={"status": "locked"},
                    target_lock_status="locked",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await session.commit()

    async def test_compare_returns_ordered_deltas_keyframes_and_video_payload(self) -> None:
        older_id = str(uuid4())
        newer_id = str(uuid4())
        skater_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=newer_id,
            skater_id=skater_id,
            score=82,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=older_id,
            skater_id=skater_id,
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        with (
            patch("app.routers.analysis.get_active_provider", AsyncMock(return_value=object())),
            patch("app.routers.analysis.request_text_completion", AsyncMock(return_value="孩子这次动作更稳定。")),
        ):
            async with self.database.AsyncSessionLocal() as session:
                result = await self.analysis_router.compare_analyses(newer_id, older_id, session=session)

        self.assertEqual(result.analysis_a.id, older_id)
        self.assertEqual(result.analysis_b.id, newer_id)
        self.assertEqual(result.score_delta, 12)
        self.assertEqual(result.subscore_deltas[0].delta, 12)
        self.assertTrue(result.metric_deltas[0].available)
        self.assertEqual(result.keyframe_compare[0].before.frame_id, "semantic_0001")
        self.assertEqual(result.keyframe_compare[0].before.source, "resolved_keyframes")
        self.assertEqual(result.keyframe_compare[0].before.phase_label, "起跳")
        self.assertEqual(result.keyframe_compare[0].before.selection_reason, "video_phase_range_motion_peak")
        self.assertEqual(result.keyframe_compare[0].before.pre_refine_timestamp, 0.1)
        self.assertEqual(result.keyframe_compare[0].before.refinement_method, "local_motion_peak")
        self.assertEqual(result.keyframe_compare[0].before.refinement_delta_sec, 0.02)
        self.assertTrue(result.keyframe_compare[0].before.available)
        self.assertIsNotNone(result.video_compare)
        assert result.video_compare is not None
        self.assertTrue(result.video_compare.before.available)
        self.assertEqual(result.video_compare.sync_mode, "semantic_keyframe")
        self.assertEqual(result.video_compare.sync_anchor_key, "T")
        self.assertEqual(result.ai_narrative, "孩子这次动作更稳定。")

    async def test_compare_rejects_different_skater_or_subtype(self) -> None:
        first_id = str(uuid4())
        second_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=first_id,
            skater_id="kid-a",
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        await self._insert_analysis(
            analysis_id=second_id,
            skater_id="kid-b",
            score=80,
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(Exception) as ctx:
                await self.analysis_router.compare_analyses(first_id, second_id, session=session)
        self.assertIn("同一位小朋友", str(ctx.exception))

        async with self.database.AsyncSessionLocal() as session:
            second = await session.get(self.models.Analysis, second_id)
            assert second is not None
            second.skater_id = "kid-a"
            second.action_subtype = "后外点冰跳"
            await session.commit()

        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(Exception) as ctx:
                await self.analysis_router.compare_analyses(first_id, second_id, session=session)
        self.assertIn("同一动作小项", str(ctx.exception))

    async def test_video_endpoint_rejects_missing_video(self) -> None:
        analysis_id = str(uuid4())
        await self._insert_analysis(
            analysis_id=analysis_id,
            skater_id="kid-a",
            score=70,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        video_path = Path(self.tmp.name) / "uploads" / analysis_id / "source.mp4"
        video_path.unlink()
        async with self.database.AsyncSessionLocal() as session:
            with self.assertRaises(Exception) as ctx:
                await self.analysis_router.get_analysis_video(analysis_id, session=session)
        self.assertIn("原视频", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
