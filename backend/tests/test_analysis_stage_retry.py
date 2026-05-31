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
    async def test_retry_awaiting_target_selection_resumes_when_preview_auto_locks(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            frames_dir = upload_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "source.mp4").write_bytes(b"fake-video")
            for index in range(1, 4):
                (frames_dir / f"frame_{index:04d}.jpg").write_bytes(b"fake-frame")

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        action_subtype="single",
                        analysis_profile="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="awaiting_target_selection",
                        retry_from_stage="pose",
                        frame_motion_scores={"selected": [{"frame_id": "frame_0002", "motion_score": 0.9}]},
                        target_lock={
                            "status": "awaiting_manual",
                            "selected_candidate_id": "fallback_center",
                            "selected_bbox": None,
                            "lock_confidence": 0.22,
                        },
                        target_lock_status="awaiting_manual",
                    )
                )
                await session.commit()

            detected = [
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.3854, "y": 0.2043, "width": 0.0727, "height": 0.2868},
                    "confidence": 0.7113,
                    "source": "yolo_zoomed_content",
                    "support_count": 8,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ]
            queued: list[tuple[object, tuple[object, ...]]] = []

            class _Tasks:
                def add_task(self, func: object, *args: object, **kwargs: object) -> None:
                    queued.append((func, args))

            with patch("app.routers.analysis._target_preview_detected_candidates_from_frames", return_value=detected):
                async with database.AsyncSessionLocal() as session:
                    response = await analysis_router.retry_analysis(
                        analysis_id,
                        _Tasks(),
                        retry_from="pose",
                        session=session,
                    )

            self.assertIn("pose", response.message)
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0][1], (analysis_id, "pose"))
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "pending")
                self.assertEqual(saved.retry_from_stage, "pose")
                self.assertEqual(saved.target_lock_status, "auto_locked")
                self.assertEqual(saved.target_lock["selected_candidate_id"], "candidate_auto_stable")
                self.assertEqual(saved.target_lock["selected_bbox"], detected[0]["bbox"])
                self.assertIn("target_lock_auto_resume_from_preview", saved.target_lock["quality_flags"])

    async def test_retry_awaiting_target_selection_refreshes_manual_review_diagnostics(self) -> None:
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

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            frames_dir = upload_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "source.mp4").write_bytes(b"fake-video")
            for index in range(1, 4):
                (frames_dir / f"frame_{index:04d}.jpg").write_bytes(b"fake-frame")

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        action_subtype="single",
                        analysis_profile="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="awaiting_target_selection",
                        retry_from_stage="pose",
                        frame_motion_scores={"selected": [{"frame_id": "frame_0002", "motion_score": 0.9}]},
                        target_lock={
                            "status": "awaiting_manual",
                            "selected_candidate_id": "candidate_auto_stable",
                            "selected_bbox": None,
                            "lock_confidence": 0.22,
                            "quality_flags": [],
                        },
                        target_lock_status="awaiting_manual",
                    )
                )
                await session.commit()

            detected = [
                {
                    "id": "candidate_weak_stable",
                    "bbox": {"x": 0.4459, "y": 0.5088, "width": 0.0347, "height": 0.0947},
                    "confidence": 0.4089,
                    "source": "yolo_zoomed_content",
                    "support_count": 2,
                    "support_frame_count": 2,
                    "support_confidence": 0.485,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ]

            with patch("app.routers.analysis._target_preview_detected_candidates_from_frames", return_value=detected):
                async with database.AsyncSessionLocal() as session:
                    refreshed = await analysis_router._resume_auto_target_lock_if_available(
                        await session.get(models.Analysis, analysis_id),
                        session,
                    )

            self.assertFalse(refreshed)
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "awaiting_target_selection")
                self.assertEqual(saved.target_lock_status, "awaiting_manual")
                self.assertIsNone(saved.target_lock["selected_bbox"])
                self.assertIn("target_lock_manual_review_low_confidence", saved.target_lock["quality_flags"])
                self.assertIn("target_lock_tiny_zoomed_low_support_manual_review", saved.target_lock["quality_flags"])

    async def test_retry_from_report_reuses_saved_outputs_without_source_video(self) -> None:
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
            upload_dir.mkdir(parents=True, exist_ok=True)

            old_report = {
                "summary": "旧报告",
                "issues": [],
                "improvements": [],
                "training_focus": "旧重点",
                "subscores": {
                    "takeoff_power": 60,
                    "rotation_axis": 60,
                    "arm_coordination": 60,
                    "landing_absorption": 60,
                    "core_stability": 60,
                },
                "data_quality": "partial",
            }
            new_report = {
                "summary": "新报告包含起跳问题",
                "issues": [],
                "improvements": [{"target": "起跳", "action": "练压膝"}],
                "training_focus": "起跳节奏",
                "subscores": {
                    "takeoff_power": 80,
                    "rotation_axis": 80,
                    "arm_coordination": 80,
                    "landing_absorption": 80,
                    "core_stability": 80,
                },
                "data_quality": "partial",
            }
            vision_structured = {
                "frame_analysis": [
                    {"frame_id": "frame_0001", "phase": "起跳", "issues": ["起跳准备不足"], "positives": [], "confidence": 0.8}
                ],
                "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
                "overall_raw_text": "ok",
            }
            bio_data = {"bio_subscores": {}, "quality_flags": [], "key_frames": {"T": "frame_0001"}}

            async with database.AsyncSessionLocal() as session:
                analysis = models.Analysis(
                    id=analysis_id,
                    action_type="跳跃",
                    action_subtype="单跳",
                    skill_category="Axel 入门",
                    analysis_profile="jump",
                    retry_from_stage="report",
                    pipeline_version=CURRENT_PIPELINE_VERSION,
                    video_path=str(upload_dir / "source.mp4"),
                    vision_structured=vision_structured,
                    bio_data=bio_data,
                    frame_motion_scores={"sample_count": 32},
                    cross_validation={"recommended_path": "A"},
                    report=old_report,
                    status="completed",
                    force_score=60,
                    note="今天手动上传时备注：落冰有点紧张。",
                )
                session.add(analysis)
                await session.commit()

            with (
                patch("app.routers.analysis.extract_pose", side_effect=AssertionError("pose should not rerun")),
                patch("app.routers.analysis.analyze_frames_dual", side_effect=AssertionError("vision should not rerun")),
                patch("app.routers.analysis.generate_report", AsyncMock(return_value=new_report)) as report_mock,
                patch(
                    "app.routers.analysis.build_analysis_prompt_context",
                    AsyncMock(return_value=SimpleNamespace(marker="prompt-context")),
                ) as context_mock,
                patch("app.routers.analysis.calculate_force_score", return_value=80),
                patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)),
                patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)),
            ):
                await analysis_router.process_analysis(analysis_id, retry_from="report")

            report_mock.assert_awaited_once()
            context_mock.assert_awaited_once()
            self.assertEqual(context_mock.await_args.kwargs["action_type"], "跳跃")
            self.assertEqual(context_mock.await_args.kwargs["action_subtype"], "单跳")
            self.assertEqual(context_mock.await_args.kwargs["skill_category"], "Axel 入门")
            self.assertEqual(context_mock.await_args.kwargs["analysis_profile"], "jump")
            self.assertEqual(context_mock.await_args.kwargs["motion_features"], {"sample_count": 32})
            self.assertEqual(context_mock.await_args.kwargs["user_note"], "今天手动上传时备注：落冰有点紧张。")
            self.assertEqual(report_mock.await_args.kwargs["prompt_context"].marker, "prompt-context")
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                self.assertEqual(saved.status, "completed")
                self.assertEqual(saved.retry_from_stage, None)
                self.assertEqual(saved.report["summary"], "新报告包含起跳问题")
                self.assertEqual(saved.force_score, 80)
                self.assertEqual(saved.vision_structured, vision_structured)
                self.assertEqual(saved.bio_data, bio_data)

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
