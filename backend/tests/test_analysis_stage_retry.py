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
    def test_normalize_processing_logs_repairs_known_mojibake(self) -> None:
        sys.modules.pop("app.routers.analysis", None)
        import app.routers.analysis as analysis_router

        logs = analysis_router._normalize_processing_logs(
            [
                {
                    "timestamp": "2026-06-15T12:44:23+00:00",
                    "stage": "pipeline",
                    "level": "info",
                    "message": "åˆ†æžæµç¨‹å·²å®Œæˆã€‚",
                }
            ]
        )

        self.assertEqual(logs[0]["message"], "分析流程已完成。")

    async def test_report_save_failed_does_not_downgrade_completed_analysis(self) -> None:
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
            from app.services.analysis_errors import AnalysisErrorCode

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        video_path=str(Path(tmpdir) / "source.mp4"),
                        status="completed",
                        report={"summary": "saved"},
                        force_score=76,
                        processing_logs=[],
                    )
                )
                await session.commit()

            await analysis_router._mark_analysis_failed(
                analysis_id,
                AnalysisErrorCode.REPORT_SAVE_FAILED,
                "sqlite3.OperationalError: disk I/O error",
                stage="report",
                timings={"total_s": 12.3},
            )

            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertIsNone(saved.error_code)
                self.assertEqual(saved.report, {"summary": "saved"})
                self.assertEqual(saved.force_score, 76)
                self.assertEqual(saved.processing_timings, {"total_s": 12.3})
                self.assertEqual(saved.processing_logs[-1]["error_code"], "REPORT_SAVE_FAILED")
                self.assertTrue(saved.processing_logs[-1]["preserved_completed_state"])

    async def test_get_analysis_recovers_failed_report_save_with_complete_outputs(self) -> None:
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
                        video_path=str(upload_dir / "source.mp4"),
                        status="failed",
                        error_code="REPORT_SAVE_FAILED",
                        error_message="save failed",
                        report={"summary": "saved", "issues": [], "improvements": []},
                        force_score=76,
                        vision_structured={"frame_analysis": []},
                        pose_data={"frames": [{"frame": "frame_0001.jpg", "keypoints": [{"x": 0.5, "y": 0.5}]}]},
                        bio_data={"key_frames": {"T": "frame_0001", "A": "frame_0002", "L": "frame_0003"}},
                        frame_motion_scores={"selected": []},
                        processing_logs=[],
                    )
                )
                await session.commit()

            async with database.AsyncSessionLocal() as session:
                detail = await analysis_router.get_analysis(analysis_id, session=session)
                self.assertEqual(detail.status, "completed")
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertIsNone(saved.error_code)
                self.assertTrue(saved.processing_logs[-1]["restored_completed_state"])

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

    async def test_full_retry_with_reset_target_lock_clears_existing_target_lock(self) -> None:
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
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "source.mp4").write_bytes(b"fake-video")

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        action_subtype="single",
                        analysis_profile="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="completed",
                        retry_from_stage="vision",
                        target_lock={
                            "status": "locked",
                            "selected_candidate_id": "old_target",
                            "selected_bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                            "lock_confidence": 0.91,
                        },
                        target_lock_status="locked",
                    )
                )
                await session.commit()

            queued: list[tuple[object, tuple[object, ...]]] = []

            class _Tasks:
                def add_task(self, func: object, *args: object, **kwargs: object) -> None:
                    queued.append((func, args))

            async with database.AsyncSessionLocal() as session:
                response = await analysis_router.retry_analysis(
                    analysis_id,
                    _Tasks(),
                    retry_from=None,
                    reset_target_lock=True,
                    session=session,
                )

            self.assertEqual(response.message, "已重新提交分析。")
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0][1], (analysis_id, None))
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "pending")
                self.assertIsNone(saved.retry_from_stage)
                self.assertIsNone(saved.target_lock)
                self.assertEqual(saved.target_lock_status, "pending")

    async def test_video_ai_keyframe_rerun_creates_proposed_correction_without_mutating_analysis(self) -> None:
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
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "source.mp4").write_bytes(b"fake-video")
            semantic_sources = []
            for index in range(1, 4):
                source = Path(tmpdir) / f"semantic_{index:04d}.jpg"
                source.write_bytes(b"fake-frame")
                semantic_sources.append(source)

            target_lock = {"status": "locked", "selected_candidate_id": "target-1"}
            pose_data = {"frames": [{"frame": "frame_0001.jpg", "keypoints": [{"x": 0.5, "y": 0.5}]}]}
            bio_data = {
                "key_frames": {"T": "frame_0001", "A": "frame_0002", "L": "frame_0003"},
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0001", "timestamp": 1.0, "confidence": 0.8},
                    "A": {"frame_id": "frame_0002", "timestamp": 1.4, "confidence": 0.8},
                    "L": {"frame_id": "frame_0003", "timestamp": 1.9, "confidence": 0.8},
                },
            }
            motion_scores = {
                "selected": [{"frame_id": "frame_0001", "timestamp": 1.0}],
                "resolved_keyframes": {"source": "existing_skeleton", "selected": []},
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        action_subtype="Toe Loop",
                        analysis_profile="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="completed",
                        report={"summary": "saved"},
                        vision_structured={"frame_analysis": []},
                        pose_data=pose_data,
                        bio_data=bio_data,
                        frame_motion_scores=motion_scores,
                        target_lock=target_lock,
                        target_lock_status="locked",
                        manual_action_window_start=1.2,
                        manual_action_window_end=2.4,
                    )
                )
                await session.commit()

            semantic_records = [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 0.9,
                    "phase_code": "takeoff",
                    "phase_label": "Takeoff",
                    "key_moment": "T_takeoff",
                    "confidence": 0.88,
                    "selection_reason": "video_temporal_core",
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 1.35,
                    "phase_code": "air",
                    "phase_label": "Apex",
                    "key_moment": "A_apex",
                    "confidence": 0.86,
                    "selection_reason": "video_temporal_core",
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 2.25,
                    "phase_code": "landing",
                    "phase_label": "Landing",
                    "key_moment": "L_landing",
                    "confidence": 0.84,
                    "selection_reason": "video_temporal_core",
                },
            ]
            pipeline_result = analysis_router.SemanticKeyframePipelineResult(
                ai_clip={"path": "clip.mp4"},
                video_temporal={"confidence": 0.87, "quality_flags": ["video_full_context"]},
                resolved_keyframes={
                    "confidence": 0.85,
                    "quality_flags": ["semantic_ok"],
                    "source": "video_temporal",
                    "selected": semantic_records,
                },
                effective_source="semantic_frames",
                semantic_frames=semantic_sources,
                semantic_records=semantic_records,
                quality_flags=["semantic_ok"],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            rerun = AsyncMock(return_value=pipeline_result)
            full_window = analysis_router.VideoInputWindow(
                source_duration_sec=3.0,
                input_window_start_sec=0.0,
                input_window_end_sec=3.0,
                input_window_duration_sec=3.0,
                input_window_mode="full_context",
                input_window_truncated=False,
                input_window_reason="full_context",
            )

            with (
                patch("app.routers.analysis.build_video_input_window", return_value=full_window) as input_window_mock,
                patch("app.routers.analysis.run_semantic_keyframe_pipeline", rerun),
            ):
                async with database.AsyncSessionLocal() as session:
                    response = await analysis_router.rerun_video_ai_keyframes(analysis_id, session=session)

            input_window_mock.assert_called_once_with(upload_dir / "source.mp4")
            rerun.assert_awaited_once()
            call_kwargs = rerun.await_args.kwargs
            self.assertEqual(call_kwargs["analyzed_video_kind"], "full_video_keyframe_rerun")
            self.assertEqual(call_kwargs["input_window"].input_window_mode, "full_context")
            self.assertEqual(call_kwargs["input_window"].input_window_start_sec, 0.0)
            self.assertEqual(response.correction.kind, "keyframes")
            self.assertEqual(response.correction.source, "video_ai_keyframe_rerun")
            self.assertEqual(response.correction.status, "proposed")
            payload = response.correction.payload
            self.assertEqual(payload["source"], "video_ai_full_video_keyframe_rerun")
            self.assertEqual(set(payload["key_frames"].keys()), {"T", "A", "L"})
            self.assertEqual(payload["key_frames"]["T"]["phase_code"], "takeoff")
            self.assertIn("diagnostics", payload)
            self.assertEqual(payload["diagnostics"]["video_ai_confidence"], 0.87)
            self.assertTrue(payload["diagnostics"]["conflicts"])
            persisted_frame = upload_dir / "semantic_frames" / f"{payload['key_frames']['T']['frame_id']}.jpg"
            self.assertTrue(persisted_frame.exists())

            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.target_lock, target_lock)
                self.assertEqual(saved.pose_data, pose_data)
                self.assertEqual(saved.bio_data, bio_data)
                self.assertEqual(saved.frame_motion_scores, motion_scores)

    async def test_video_ai_keyframe_rerun_requires_completed_analysis_and_source_video(self) -> None:
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
            from fastapi import HTTPException

            database.ensure_storage_dirs()
            await database.init_db()

            missing_video_id = str(uuid4())
            processing_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / processing_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "source.mp4").write_bytes(b"fake-video")
            async with database.AsyncSessionLocal() as session:
                session.add_all(
                    [
                        models.Analysis(
                            id=missing_video_id,
                            action_type="jump",
                            video_path=str(Path(tmpdir) / "missing.mp4"),
                            status="completed",
                            report={"summary": "saved"},
                            vision_structured={"frame_analysis": []},
                        ),
                        models.Analysis(
                            id=processing_id,
                            action_type="jump",
                            video_path=str(upload_dir / "source.mp4"),
                            status="processing",
                        ),
                    ]
                )
                await session.commit()

            async with database.AsyncSessionLocal() as session:
                with self.assertRaises(HTTPException) as missing_ctx:
                    await analysis_router.rerun_video_ai_keyframes(missing_video_id, session=session)
                self.assertEqual(missing_ctx.exception.status_code, 404)

            async with database.AsyncSessionLocal() as session:
                with self.assertRaises(HTTPException) as status_ctx:
                    await analysis_router.rerun_video_ai_keyframes(processing_id, session=session)
                self.assertEqual(status_ctx.exception.status_code, 400)

    async def test_report_retry_does_not_reset_target_lock_even_when_requested(self) -> None:
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
            upload_dir.mkdir(parents=True, exist_ok=True)
            target_lock = {
                "status": "locked",
                "selected_candidate_id": "old_target",
                "selected_bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                "lock_confidence": 0.91,
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        action_subtype="single",
                        analysis_profile="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="completed",
                        report={"summary": "saved"},
                        vision_structured={"frame_analysis": []},
                        bio_data={"key_frames": {}},
                        target_lock=target_lock,
                        target_lock_status="locked",
                    )
                )
                await session.commit()

            queued: list[tuple[object, tuple[object, ...]]] = []

            class _Tasks:
                def add_task(self, func: object, *args: object, **kwargs: object) -> None:
                    queued.append((func, args))

            async with database.AsyncSessionLocal() as session:
                response = await analysis_router.retry_analysis(
                    analysis_id,
                    _Tasks(),
                    retry_from="report",
                    reset_target_lock=True,
                    session=session,
                )

            self.assertIn("report", response.message)
            self.assertEqual(queued[0][1], (analysis_id, "report"))
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.target_lock, target_lock)
                self.assertEqual(saved.target_lock_status, "locked")
                self.assertEqual(saved.retry_from_stage, "report")

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

    async def test_locked_manual_review_candidate_counts_as_confirmed_for_resume(self) -> None:
        for module_name in [
            "app.routers.analysis",
            "app.services.target_lock",
        ]:
            sys.modules.pop(module_name, None)

        import app.routers.analysis as analysis_router
        from app.services.target_lock import build_target_preview

        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4402, "y": 0.2001, "width": 0.0484, "height": 0.234},
                    "confidence": 0.909,
                    "source": "yolo_zoomed_content",
                    "support_count": 32,
                    "support_frame_count": 7,
                    "support_confidence": 0.8571,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "other_anchor_person_1",
                    "bbox": {"x": 0.3828, "y": 0.2, "width": 0.0502, "height": 0.1524},
                    "confidence": 0.8741,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
            ],
        )
        selected = next(item for item in preview.candidates if item["id"] == "candidate_auto_stable")
        target_lock = {
            "status": "locked",
            "selected_candidate_id": selected["id"],
            "selected_bbox": selected["bbox"],
            "lock_confidence": selected["confidence"],
            "quality_flags": ["target_lock_zoomed_multiperson_manual_review"],
        }

        self.assertIn("target_lock_zoomed_multiperson_manual_review", target_lock["quality_flags"])
        self.assertTrue(analysis_router._is_confirmed_target_lock(target_lock))

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
            motion_scores = {
                "selected": [],
                "source": "test",
                "resolved_keyframes": {
                    "source": "skeleton_fallback",
                    "confidence": 0.9,
                    "quality_flags": [],
                    "selected": [
                        {"frame_id": "frame_0001", "timestamp": 0.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                        {"frame_id": "frame_0002", "timestamp": 0.2, "phase_code": "air", "key_moment": "A_air_sec"},
                        {"frame_id": "frame_0003", "timestamp": 0.3, "phase_code": "landing", "key_moment": "L_landing_sec"},
                    ],
                },
            }
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
                patch("app.routers.analysis.cut_action_window_ai_clip", AsyncMock(return_value=upload_dir / "path_a_input_window_ai.mp4")),
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
                self.assertEqual(saved.bio_data["key_frames"], {})
                self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", saved.bio_data["quality_flags"])
                self.assertIn("bio_key_frames_not_restored_unreliable_candidates", saved.bio_data["quality_flags"])
                self.assertIsInstance(saved.vision_structured, dict)
                self.assertEqual(saved.vision_path_a, vision_structured)
                self.assertEqual(saved.vision_path_b, {"path": "B", "error": "mocked"})
                self.assertEqual(saved.cross_validation["recommended_path"], "A")
                self.assertTrue(saved.cross_validation["path_b_failed"])
                self.assertIn("auto_eval", saved.cross_validation)
                self.assertIsInstance(saved.report, dict)


if __name__ == "__main__":
    unittest.main()
