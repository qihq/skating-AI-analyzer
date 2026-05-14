from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AnalysisStageRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_from_vision_reuses_pose_and_biomechanics_outputs(self) -> None:
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
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            frames_dir = upload_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "source.mp4").write_bytes(b"fake-video")
            for index in range(1, 4):
                (frames_dir / f"frame_{index:04d}.jpg").write_bytes(b"fake-frame")

            pose_data = {"frames": [{"frame": "frame_0001.jpg", "keypoints": []}], "connections": []}
            bio_data = {
                "key_frames": {"T": "frame_0001", "A": "frame_0002", "L": "frame_0003"},
                "bio_subscores": {},
                "quality_flags": [],
                "profile_evidence": {"quality_flags": [], "negative_constraints": []},
            }
            motion_scores = {"selected": [], "source": "test"}
            target_lock = {"status": "locked", "selected_candidate_id": "candidate_center"}
            vision_structured = {
                "frame_analysis": [
                    {"frame_id": "frame_0001", "phase": "起跳", "issues": [], "positives": [], "confidence": 0.9}
                ],
                "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
                "overall_raw_text": "ok",
            }
            report = {
                "summary": "ok",
                "issues": [],
                "improvements": [],
                "training_focus": "ok",
                "subscores": {
                    "takeoff_power": 80,
                    "rotation_axis": 80,
                    "arm_coordination": 80,
                    "landing_absorption": 80,
                    "core_stability": 80,
                },
                "data_quality": "good",
            }
            dual = SimpleNamespace(
                path_a=vision_structured,
                path_b={"path": "B", "error": "mocked"},
                validation=SimpleNamespace(to_dict=lambda: {"recommended_path": "A"}),
                dual_path_meta={"recommended_path": "A", "path_b_failed": True},
                blend_weights=(1.0, 0.0),
            )

            async with database.AsyncSessionLocal() as session:
                analysis = models.Analysis(
                    id=analysis_id,
                    action_type="跳跃",
                    action_subtype="2A",
                    analysis_profile="jump",
                    retry_from_stage="vision",
                    pipeline_version=CURRENT_PIPELINE_VERSION,
                    video_path=str(upload_dir / "source.mp4"),
                    frame_motion_scores=motion_scores,
                    pose_data=pose_data,
                    bio_data=bio_data,
                    target_lock=target_lock,
                    target_lock_status="locked",
                    action_window_start=0.0,
                    action_window_end=1.0,
                    source_fps=30.0,
                    is_slow_motion=False,
                    status="failed",
                    error_code="AI_API_TIMEOUT",
                )
                session.add(analysis)
                await session.commit()

            with (
                patch("app.routers.analysis.extract_pose", side_effect=AssertionError("pose should not rerun")),
                patch("app.routers.analysis.analyze_biomechanics", side_effect=AssertionError("biomechanics should not rerun")),
                patch(
                    "app.routers.analysis.encode_frames",
                    AsyncMock(return_value=[SimpleNamespace(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA")]),
                ),
                patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=dual)),
                patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A"}),
                patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())),
                patch("app.routers.analysis.generate_report", AsyncMock(return_value=report)),
                patch("app.routers.analysis.calculate_force_score", return_value=80),
                patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)),
            ):
                await analysis_router.process_analysis(analysis_id, retry_from="vision")

            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                self.assertEqual(saved.status, "completed")
                self.assertEqual(saved.retry_from_stage, None)
                self.assertEqual(saved.pose_data, pose_data)
                self.assertEqual(saved.bio_data["key_frames"], bio_data["key_frames"])
                self.assertIsInstance(saved.vision_structured, dict)
                self.assertEqual(saved.vision_path_a, vision_structured)
                self.assertEqual(saved.vision_path_b, {"path": "B", "error": "mocked"})
                self.assertEqual(saved.cross_validation["recommended_path"], "A")
                self.assertTrue(saved.cross_validation["path_b_failed"])
                self.assertIn("auto_eval", saved.cross_validation)
                self.assertIsInstance(saved.report, dict)


if __name__ == "__main__":
    unittest.main()
