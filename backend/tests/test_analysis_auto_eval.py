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

from test_analysis_keyframe_candidates import _motion_scores, _pose_data


class AnalysisAutoEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_analysis_persists_auto_eval_in_cross_validation(self) -> None:
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
            for index in range(1, 10):
                (frames_dir / f"frame_{index:04d}.jpg").write_bytes(b"fake-frame")

            vision_structured = {
                "frame_analysis": [
                    {"frame_id": "frame_0004", "phase": "起跳", "issues": [], "positives": [], "confidence": 0.9},
                    {"frame_id": "frame_0006", "phase": "腾空", "issues": [], "positives": [], "confidence": 0.9},
                    {"frame_id": "frame_0008", "phase": "落冰", "issues": [], "positives": [], "confidence": 0.9},
                ],
                "action_phase_summary": {"detected_phases": ["起跳", "腾空", "落冰"]},
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
                path_b={"path": "B", "subscores": {}},
                validation=SimpleNamespace(to_dict=lambda: {"overall_agreement_rate": 0.88, "recommended_path": "blend"}),
                dual_path_meta={"recommended_path": "A", "weight_a": 1.0, "weight_b": 0.0},
                blend_weights=(1.0, 0.0),
                annotated_dir=None,
                used_key_frames=set(),
            )

            async with database.AsyncSessionLocal() as session:
                analysis = models.Analysis(
                    id=analysis_id,
                    action_type="跳跃",
                    action_subtype="单跳",
                    analysis_profile="jump",
                    retry_from_stage="biomechanics",
                    pipeline_version=CURRENT_PIPELINE_VERSION,
                    video_path=str(upload_dir / "source.mp4"),
                    frame_motion_scores=_motion_scores(),
                    pose_data=_pose_data(),
                    target_lock={"status": "locked", "selected_candidate_id": "candidate_center"},
                    target_lock_status="locked",
                    action_window_start=0.0,
                    action_window_end=0.8,
                    source_fps=30.0,
                    is_slow_motion=False,
                    status="failed",
                    error_code="UNKNOWN_ERROR",
                )
                session.add(analysis)
                await session.commit()

            with (
                patch(
                    "app.routers.analysis.encode_frames",
                    AsyncMock(return_value=[SimpleNamespace(frame_id="frame_0004", data_url="data:image/jpeg;base64,AAA")]),
                ),
                patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=dual)),
                patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}),
                patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())),
                patch("app.routers.analysis.generate_report", AsyncMock(return_value=report)),
                patch("app.routers.analysis.calculate_force_score", return_value=80),
                patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)),
            ):
                await analysis_router.process_analysis(analysis_id, retry_from="biomechanics")

            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertIsInstance(saved.cross_validation, dict)
                assert isinstance(saved.cross_validation, dict)
                self.assertEqual(saved.cross_validation["overall_agreement_rate"], 0.88)
                self.assertEqual(saved.cross_validation["recommended_path"], "A")
                self.assertEqual(saved.cross_validation["weight_a"], 1.0)
                self.assertIn("auto_eval", saved.cross_validation)

                auto_eval = saved.cross_validation["auto_eval"]
                self.assertEqual(auto_eval["auto_eval_version"], "v1")
                self.assertTrue(auto_eval["key_frame_order_valid"])
                self.assertTrue(auto_eval["phase_sequence_valid"])
                self.assertEqual(auto_eval["high_confidence_conflicts"], [])

                detail = await analysis_router.get_analysis(analysis_id, session=session)
                self.assertIsInstance(detail.cross_validation, dict)
                assert isinstance(detail.cross_validation, dict)
                self.assertIn("auto_eval", detail.cross_validation)
                self.assertEqual(detail.cross_validation["auto_eval"]["auto_eval_version"], "v1")

    async def test_auto_eval_failure_is_persisted_as_warning_without_blocking_report(self) -> None:
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
            for index in range(1, 10):
                (frames_dir / f"frame_{index:04d}.jpg").write_bytes(b"fake-frame")

            vision_structured = {
                "frame_analysis": [{"frame_id": "frame_0004", "phase": "起跳", "confidence": 0.9}],
                "action_phase_summary": {"detected_phases": ["起跳"]},
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
                path_b={"path": "B", "subscores": {}},
                validation=SimpleNamespace(to_dict=lambda: {"overall_agreement_rate": 0.77, "recommended_path": "blend"}),
                dual_path_meta={"recommended_path": "A"},
                blend_weights=(1.0, 0.0),
                annotated_dir=None,
                used_key_frames=set(),
            )

            async with database.AsyncSessionLocal() as session:
                analysis = models.Analysis(
                    id=analysis_id,
                    action_type="跳跃",
                    action_subtype="单跳",
                    analysis_profile="jump",
                    retry_from_stage="biomechanics",
                    pipeline_version=CURRENT_PIPELINE_VERSION,
                    video_path=str(upload_dir / "source.mp4"),
                    frame_motion_scores=_motion_scores(),
                    pose_data=_pose_data(),
                    target_lock={"status": "locked"},
                    target_lock_status="locked",
                    action_window_start=0.0,
                    action_window_end=0.8,
                    source_fps=30.0,
                    is_slow_motion=False,
                    status="failed",
                    error_code="UNKNOWN_ERROR",
                )
                session.add(analysis)
                await session.commit()

            with (
                patch(
                    "app.routers.analysis.encode_frames",
                    AsyncMock(return_value=[SimpleNamespace(frame_id="frame_0004", data_url="data:image/jpeg;base64,AAA")]),
                ),
                patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=dual)),
                patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}),
                patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())),
                patch("app.routers.analysis.build_auto_eval_payload", side_effect=RuntimeError("auto eval boom")),
                patch("app.routers.analysis.generate_report", AsyncMock(return_value=report)) as report_mock,
                patch("app.routers.analysis.calculate_force_score", return_value=80),
                patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)),
            ):
                await analysis_router.process_analysis(analysis_id, retry_from="biomechanics")

            report_mock.assert_awaited_once()
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                assert isinstance(saved.cross_validation, dict)
                self.assertEqual(saved.cross_validation["overall_agreement_rate"], 0.77)
                auto_eval = saved.cross_validation["auto_eval"]
                self.assertIn("auto_eval_failed", auto_eval["data_quality_flags"])
                self.assertIn("auto eval boom", auto_eval["warning"])


if __name__ == "__main__":
    unittest.main()
