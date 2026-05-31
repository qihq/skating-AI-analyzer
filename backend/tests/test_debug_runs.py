from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DebugRunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'test.db'}"

        for module_name in [
            "app.database",
            "app.models",
            "app.routers.analysis",
            "app.routers.debug",
            "app.services.pipeline_version",
        ]:
            sys.modules.pop(module_name, None)
        app_pkg = sys.modules.get("app")
        if app_pkg is not None:
            for attr in ("database", "models"):
                if hasattr(app_pkg, attr):
                    delattr(app_pkg, attr)

        import app.database as database

        database.ensure_storage_dirs()
        await database.init_db()
        self.database = database

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_local_debug_run_from_analysis_does_not_modify_formal_analysis(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.video import VideoSamplingMetadata

        analysis_id = str(uuid4())
        upload_dir = Path(self.tmp.name) / "uploads" / analysis_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        source_video = upload_dir / "source.mp4"
        source_video.write_bytes(b"fake-video")

        original_report = {"summary": "formal report", "issues": [], "improvements": [], "training_focus": "formal"}
        original_vision = {"frame_analysis": [{"frame_id": "frame_0001"}]}
        original_cross_validation = {"recommended_path": "A"}
        original_motion_scores = {
            "window_start": 4.0,
            "window_end": 5.0,
            "window_start_sec": 4.0,
            "window_end_sec": 5.0,
            "effective_fps": 2.0,
            "source_fps": 30.0,
            "is_slow_motion": False,
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 4.0, "motion_score": 0.2},
                {"frame_id": "frame_0002", "timestamp": 4.5, "motion_score": 0.7},
                {"frame_id": "frame_0003", "timestamp": 5.0, "motion_score": 0.3},
            ],
            "scores": [0.2, 0.7, 0.3],
        }
        original_target_lock = {
            "preview_frame": "frame_0002.jpg",
            "preview_frame_index": 1,
            "candidates": [
                {
                    "id": "formal_candidate",
                    "confidence": 0.9,
                    "bbox": {"x": 0.11, "y": 0.22, "width": 0.33, "height": 0.44},
                }
            ],
            "selected_candidate_id": "formal_candidate",
            "selected_bbox": {"x": 0.11, "y": 0.22, "width": 0.33, "height": 0.44},
            "lock_confidence": 0.9,
            "status": "locked",
            "quality_flags": [],
        }

        async with self.database.AsyncSessionLocal() as session:
            analysis = models.Analysis(
                id=analysis_id,
                action_type="è·³è·ƒ",
                action_subtype="Axel",
                analysis_profile="jump",
                video_path=str(source_video),
                status="completed",
                report=original_report,
                force_score=88,
                vision_structured=original_vision,
                frame_motion_scores=original_motion_scores,
                action_window_start=4.0,
                action_window_end=5.0,
                source_fps=30.0,
                vision_path_a={"path": "A"},
                vision_path_b={"path": "B"},
                cross_validation=original_cross_validation,
                target_lock=original_target_lock,
                target_lock_status="locked",
            )
            session.add(analysis)
            run = models.DebugRun(
                id=str(uuid4()),
                mode="local_pose_keyframes",
                source_type="analysis",
                analysis_id=analysis_id,
                video_path=str(source_video),
                action_type="è·³è·ƒ",
                action_subtype="Axel",
                analysis_profile="jump",
                status="pending",
            )
            session.add(run)
            await session.commit()
            run_id = run.id

        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        sampled = []
        for index in range(1, 4):
            frame = frames_dir / f"frame_{index:04d}.jpg"
            frame.write_bytes(b"frame")
            sampled.append(frame)

        pose_data = {
            "connections": [],
            "frames": [{"frame": "frame_0001.jpg", "keypoints": [], "tracking_state": "tracked", "tracking_confidence": 0.8}],
            "pose_diagnostics": {"total_frames": 1, "tracked_frames": 1, "lost_frames": 0, "low_confidence_frames": 0, "frames": []},
        }
        bio_data = {"quality_flags": [], "key_frame_candidates": {"T": {"frame_id": "frame_0001", "confidence": 0.8}}}

        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            restore_mock = stack.enter_context(patch("app.routers.debug.restore_sampled_frames", AsyncMock(return_value=sampled)))
            extract_mock = stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(side_effect=AssertionError("analysis replay should use saved timestamps"))))
            preview_mock = stack.enter_context(
                patch(
                    "app.routers.debug.build_target_preview",
                    return_value=SimpleNamespace(
                        preview_frame="frame_0001.jpg",
                        preview_frame_index=0,
                        preview_frame_url=None,
                        auto_candidate_id="candidate_1",
                        lock_confidence=0.95,
                        candidates=[{"id": "candidate_1", "confidence": 0.95, "bbox": {"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.5}}],
                        target_lock_status="auto_locked",
                    ),
                )
            )
            lock_payload_mock = stack.enter_context(
                patch("app.routers.debug.build_target_lock_payload", side_effect=AssertionError("confirmed target lock should be reused"))
            )
            bbox_mock = stack.enter_context(
                patch("app.routers.debug._build_bbox_per_frame", return_value=[{"x": 0.11, "y": 0.22, "width": 0.33, "height": 0.44}])
            )
            stack.enter_context(patch("app.routers.debug.extract_pose", return_value=pose_data))
            stack.enter_context(patch("app.routers.debug.infer_analysis_profile", return_value=("jump", {"quality_flags": []})))
            stack.enter_context(patch("app.routers.debug.analyze_biomechanics", return_value={"quality_flags": []}))
            stack.enter_context(patch("app.routers.debug.attach_key_frame_candidates", return_value=bio_data))
            await debug_router.process_debug_run(run_id)

        restore_mock.assert_awaited_once()
        self.assertEqual(restore_mock.call_args.args[2], original_motion_scores["selected"])
        extract_mock.assert_not_called()
        lock_payload_mock.assert_not_called()
        preview_mock.assert_called_once()
        self.assertEqual(preview_mock.call_args.kwargs["existing_target_lock"]["selected_bbox"], original_target_lock["selected_bbox"])
        bbox_mock.assert_called_once()
        self.assertEqual(bbox_mock.call_args.args[1]["selected_bbox"], original_target_lock["selected_bbox"])

        async with self.database.AsyncSessionLocal() as session:
            saved_analysis = await session.get(models.Analysis, analysis_id)
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_analysis)
            self.assertIsNotNone(saved_run)
            assert saved_analysis is not None and saved_run is not None
            self.assertEqual(saved_analysis.status, "completed")
            self.assertEqual(saved_analysis.report, original_report)
            self.assertEqual(saved_analysis.force_score, 88)
            self.assertEqual(saved_analysis.vision_structured, original_vision)
            self.assertEqual(saved_analysis.cross_validation, original_cross_validation)
            self.assertEqual(saved_analysis.target_lock, original_target_lock)
            self.assertEqual(saved_run.status, "completed")
            self.assertEqual(saved_run.result_json["mode"], "local_pose_keyframes")
            self.assertEqual(saved_run.result_json["sampling_source"], "analysis_replay")
            self.assertEqual(saved_run.result_json["sampling_metadata"]["action_window_start"], 4.0)
            self.assertEqual(saved_run.result_json["sampling_metadata"]["action_window_end"], 5.0)
            self.assertTrue(saved_run.result_json["target_preview"]["source_target_lock_reused"])
            self.assertEqual(saved_run.result_json["target_lock"]["selected_bbox"], original_target_lock["selected_bbox"])
            self.assertEqual(saved_run.result_json["target_lock"]["debug_source"], "analysis_target_lock")
            self.assertIn("key_frame_candidates", saved_run.result_json)

    async def test_analysis_debug_fallback_resamples_and_does_not_reuse_target_lock(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.video import VideoSamplingMetadata

        analysis_id = str(uuid4())
        upload_dir = Path(self.tmp.name) / "uploads" / analysis_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        source_video = upload_dir / "source.mp4"
        source_video.write_bytes(b"fake-video")
        original_target_lock = {
            "selected_bbox": {"x": 0.11, "y": 0.22, "width": 0.33, "height": 0.44},
            "status": "locked",
            "quality_flags": [],
        }
        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.Analysis(
                    id=analysis_id,
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                    action_subtype="Axel",
                    analysis_profile="jump",
                    video_path=str(source_video),
                    status="completed",
                    target_lock=original_target_lock,
                    target_lock_status="locked",
                )
            )
            run = models.DebugRun(
                id=str(uuid4()),
                mode="local_pose_keyframes",
                source_type="analysis",
                analysis_id=analysis_id,
                video_path=str(source_video),
                action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                action_subtype="Axel",
                analysis_profile="jump",
                status="pending",
            )
            session.add(run)
            await session.commit()
            run_id = run.id

        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        sampled = [frames_dir / "frame_0001.jpg"]
        sampled[0].write_bytes(b"frame")
        motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 4.0, "motion_score": 0.4}], "scores": [0.4]}
        sampling = VideoSamplingMetadata(4.0, 5.0, 4.0, 5.0, 10.0, 30.0, False)

        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            extract_mock = stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling))))
            preview_mock = stack.enter_context(
                patch(
                    "app.routers.debug.build_target_preview",
                    return_value=SimpleNamespace(
                        preview_frame="frame_0001.jpg",
                        preview_frame_index=0,
                        preview_frame_url=None,
                        auto_candidate_id=None,
                        lock_confidence=0.0,
                        candidates=[],
                        target_lock_status="awaiting_manual",
                    ),
                )
            )
            stack.enter_context(patch("app.routers.debug.extract_pose", side_effect=AssertionError("pose should wait for new target lock")))
            await debug_router.process_debug_run(run_id)

        extract_mock.assert_awaited_once()
        self.assertNotIn("full_video_window", extract_mock.call_args.kwargs)
        preview_mock.assert_called_once()
        self.assertIsNone(preview_mock.call_args.kwargs["existing_target_lock"])
        async with self.database.AsyncSessionLocal() as session:
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_run)
            assert saved_run is not None
            self.assertEqual(saved_run.status, "awaiting_target_selection")
            self.assertEqual(saved_run.result_json["sampling_source"], "formal_pipeline_resample")
            self.assertNotEqual(saved_run.result_json["target_lock"].get("selected_bbox"), original_target_lock["selected_bbox"])

    async def test_video_ai_debug_run_does_not_call_pose_or_report_pipeline(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.semantic_keyframe_pipeline import SemanticKeyframePipelineResult
        from app.services.video import VideoSamplingMetadata

        run_id = str(uuid4())
        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        semantic_dir = debug_root / "semantic_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        semantic_dir.mkdir(parents=True, exist_ok=True)
        source_video = debug_root / "source.mp4"
        source_video.write_bytes(b"fake-video")
        sampled = [frames_dir / "frame_0001.jpg"]
        sampled[0].write_bytes(b"frame")
        semantic_frame = semantic_dir / "semantic_0001.jpg"
        semantic_frame.write_bytes(b"semantic")

        async with self.database.AsyncSessionLocal() as session:
            run = models.DebugRun(
                id=run_id,
                mode="video_ai_keyframes",
                source_type="upload",
                video_path=str(source_video),
                action_type="è·³è·ƒ",
                action_subtype="Axel",
                analysis_profile="jump",
                status="pending",
            )
            session.add(run)
            await session.commit()

        motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 0.4, "motion_score": 0.9}], "scores": [0.9]}
        sampling = VideoSamplingMetadata(0.0, 1.0, 0.0, 1.0, 10.0, 30.0, False)
        video_temporal = {"schema_version": "video_temporal_v1", "valid": True, "confidence": 0.9, "quality_flags": []}
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.9,
            "quality_flags": [],
            "selected": [{"frame_id": "semantic_0001", "timestamp": 0.45, "phase_code": "takeoff", "phase_label": "èµ·è·³"}],
            "video_ai": video_temporal,
        }
        semantic_records = [{"frame_id": "semantic_0001", "timestamp": 0.45, "phase_code": "takeoff", "phase_label": "èµ·è·³"}]
        semantic_result = SemanticKeyframePipelineResult(
            ai_clip={
                "path": str(debug_root / "action_window_ai.mp4"),
                "duration_sec": 1.0,
                "source_duration_sec": 5.0,
                "fps": 15.0,
                "timestamp_offset_sec": 0.0,
            },
            video_temporal=video_temporal,
            resolved_keyframes=resolved,
            semantic_frames=[semantic_frame],
            semantic_records=semantic_records,
            quality_flags=[],
            used_semantic_frames=True,
        )
        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling))))
            pipeline_mock = stack.enter_context(patch("app.routers.debug.run_semantic_keyframe_pipeline", AsyncMock(return_value=semantic_result)))
            stack.enter_context(patch("app.routers.debug.extract_pose", side_effect=AssertionError("pose should not run")))
            stack.enter_context(patch("app.routers.analysis.analyze_frames_dual", side_effect=AssertionError("image AI should not run")))
            stack.enter_context(patch("app.routers.analysis.generate_report", side_effect=AssertionError("report AI should not run")))
            await debug_router.process_debug_run(run_id)

        pipeline_mock.assert_awaited_once()
        self.assertEqual(pipeline_mock.await_args.kwargs["analyzed_video_kind"], "debug_action_window_ai")
        self.assertFalse(pipeline_mock.await_args.kwargs["precheck"])
        self.assertEqual(
            pipeline_mock.await_args.kwargs["bio_data"],
            {"quality_flags": ["debug_video_ai_no_bio_candidates_upload_source"]},
        )
        async with self.database.AsyncSessionLocal() as session:
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_run)
            assert saved_run is not None
            self.assertEqual(saved_run.status, "completed")
            self.assertIn("debug_video_ai_no_bio_candidates_upload_source", saved_run.result_json["bio_data"]["quality_flags"])
            self.assertEqual(saved_run.result_json["video_temporal"], video_temporal)
            self.assertEqual(saved_run.result_json["semantic_frames"][0]["frame_id"], "semantic_0001")
            response = await debug_router.get_debug_run_frame(run_id, "semantic_0001.jpg", session)
            self.assertEqual(Path(response.path), semantic_frame)

    async def test_video_ai_debug_from_analysis_passes_bio_candidates_to_semantic_pipeline(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.semantic_keyframe_pipeline import SemanticKeyframePipelineResult
        from app.services.video import VideoSamplingMetadata

        analysis_id = str(uuid4())
        run_id = str(uuid4())
        upload_dir = Path(self.tmp.name) / "uploads" / analysis_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        source_video = upload_dir / "source.mp4"
        source_video.write_bytes(b"fake-video")
        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        semantic_dir = debug_root / "semantic_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        semantic_dir.mkdir(parents=True, exist_ok=True)
        sampled = [frames_dir / "frame_0001.jpg"]
        sampled[0].write_bytes(b"frame")
        semantic_frame = semantic_dir / "semantic_0001.jpg"
        semantic_frame.write_bytes(b"semantic")
        target_lock = {
            "preview_frame": "frame_0001.jpg",
            "preview_frame_index": 0,
            "selected_candidate_id": "candidate_center",
            "selected_bbox": {"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.5},
            "lock_confidence": 0.9,
            "status": "locked",
            "quality_flags": [],
        }
        motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 0.4, "motion_score": 0.9}], "scores": [0.9]}
        sampling = VideoSamplingMetadata(0.0, 1.0, 0.0, 1.0, 10.0, 30.0, False)
        pose_data = {"connections": [], "frames": [{"frame": "frame_0001.jpg", "keypoints": [], "tracking_state": "tracked"}]}
        bio_data = {"quality_flags": [], "key_frame_candidates": {"T": {"frame_id": "frame_0001", "timestamp": 0.4, "confidence": 0.82}}}
        video_temporal = {"schema_version": "video_temporal_v1", "valid": True, "confidence": 0.9, "quality_flags": []}
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.9,
            "quality_flags": [],
            "selected": [{"frame_id": "semantic_0001", "timestamp": 0.45, "phase_code": "takeoff", "phase_label": "takeoff"}],
            "video_ai": video_temporal,
        }
        semantic_result = SemanticKeyframePipelineResult(
            ai_clip={"path": str(debug_root / "action_window_ai.mp4"), "duration_sec": 1.0, "source_duration_sec": 5.0, "fps": 15.0, "timestamp_offset_sec": 0.0},
            video_temporal=video_temporal,
            resolved_keyframes=resolved,
            semantic_frames=[semantic_frame],
            semantic_records=[{"frame_id": "semantic_0001", "timestamp": 0.45, "phase_code": "takeoff", "phase_label": "takeoff"}],
            quality_flags=[],
            used_semantic_frames=True,
        )

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.Analysis(
                    id=analysis_id,
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                    action_subtype="Axel",
                    analysis_profile="jump",
                    video_path=str(source_video),
                    status="completed",
                    target_lock=target_lock,
                    target_lock_status="locked",
                )
            )
            session.add(
                models.DebugRun(
                    id=run_id,
                    mode="video_ai_keyframes",
                    source_type="analysis",
                    analysis_id=analysis_id,
                    video_path=str(source_video),
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                    action_subtype="Axel",
                    analysis_profile="jump",
                    status="pending",
                )
            )
            await session.commit()

        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling))))
            stack.enter_context(patch("app.routers.debug._build_bbox_per_frame", return_value=[target_lock["selected_bbox"]]))
            stack.enter_context(patch("app.routers.debug.extract_pose", return_value=pose_data))
            stack.enter_context(patch("app.routers.debug.infer_analysis_profile", return_value=("jump", {"quality_flags": []})))
            stack.enter_context(patch("app.routers.debug.analyze_biomechanics", return_value={"quality_flags": []}))
            stack.enter_context(patch("app.routers.debug.attach_key_frame_candidates", return_value=bio_data))
            pipeline_mock = stack.enter_context(patch("app.routers.debug.run_semantic_keyframe_pipeline", AsyncMock(return_value=semantic_result)))
            await debug_router.process_debug_run(run_id)

        pipeline_mock.assert_awaited_once()
        self.assertEqual(pipeline_mock.await_args.kwargs["bio_data"], bio_data)
        async with self.database.AsyncSessionLocal() as session:
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_run)
            assert saved_run is not None
            self.assertEqual(saved_run.status, "completed")
            self.assertEqual(saved_run.result_json["key_frame_candidates"], bio_data["key_frame_candidates"])

    async def test_video_ai_debug_upload_auto_lock_passes_bio_candidates_to_semantic_pipeline(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.semantic_keyframe_pipeline import SemanticKeyframePipelineResult
        from app.services.video import VideoSamplingMetadata

        run_id = str(uuid4())
        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        semantic_dir = debug_root / "semantic_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        semantic_dir.mkdir(parents=True, exist_ok=True)
        source_video = debug_root / "source.mp4"
        source_video.write_bytes(b"fake-video")
        sampled = [frames_dir / "frame_0001.jpg"]
        sampled[0].write_bytes(b"frame")
        semantic_frame = semantic_dir / "semantic_0001.jpg"
        semantic_frame.write_bytes(b"semantic")

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.DebugRun(
                    id=run_id,
                    mode="video_ai_keyframes",
                    source_type="upload",
                    video_path=str(source_video),
                    action_type="ÃƒÂ¨Ã‚Â·Ã‚Â³ÃƒÂ¨Ã‚Â·Ã†â€™",
                    action_subtype="Axel",
                    analysis_profile="jump",
                    status="pending",
                )
            )
            await session.commit()

        target_lock = {
            "preview_frame": "frame_0001.jpg",
            "preview_frame_index": 0,
            "selected_candidate_id": "candidate_center",
            "selected_bbox": {"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.5},
            "lock_confidence": 0.9,
            "status": "auto_locked",
            "quality_flags": [],
        }
        motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 0.4, "motion_score": 0.9}], "scores": [0.9]}
        sampling = VideoSamplingMetadata(0.0, 1.0, 0.0, 1.0, 10.0, 30.0, False)
        pose_data = {"connections": [], "frames": [{"frame": "frame_0001.jpg", "keypoints": [], "tracking_state": "tracked"}]}
        bio_data = {
            "quality_flags": [],
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0001", "timestamp": 0.4, "confidence": 0.82},
                "A": {"frame_id": "frame_0001", "timestamp": 0.5, "confidence": 0.8},
                "L": {"frame_id": "frame_0001", "timestamp": 0.6, "confidence": 0.81},
            },
        }
        video_temporal = {"schema_version": "video_temporal_v1", "valid": True, "confidence": 0.9, "quality_flags": []}
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.9,
            "quality_flags": [],
            "selected": [{"frame_id": "semantic_0001", "timestamp": 0.45, "phase_code": "takeoff", "phase_label": "takeoff"}],
            "video_ai": video_temporal,
        }
        semantic_result = SemanticKeyframePipelineResult(
            ai_clip={"path": str(debug_root / "action_window_ai.mp4"), "duration_sec": 1.0, "source_duration_sec": 5.0, "fps": 15.0, "timestamp_offset_sec": 0.0},
            video_temporal=video_temporal,
            resolved_keyframes=resolved,
            semantic_frames=[semantic_frame],
            semantic_records=[{"frame_id": "semantic_0001", "timestamp": 0.45, "phase_code": "takeoff", "phase_label": "takeoff"}],
            quality_flags=[],
            used_semantic_frames=True,
        )

        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling))))
            stack.enter_context(
                patch(
                    "app.routers.debug.build_target_preview",
                    return_value=SimpleNamespace(
                        preview_frame="frame_0001.jpg",
                        preview_frame_index=0,
                        lock_confidence=0.9,
                        candidates=[],
                        auto_candidate_id="candidate_center",
                        target_lock_status="auto_locked",
                    ),
                )
            )
            stack.enter_context(patch("app.routers.debug.build_target_lock_payload", return_value=dict(target_lock)))
            stack.enter_context(
                patch(
                    "app.routers.debug.detect_person_candidates",
                    return_value=[
                        {
                            "id": "candidate_center",
                            "bbox": target_lock["selected_bbox"],
                            "confidence": 0.9,
                            "source": "yolo_preview",
                        }
                    ],
                )
            )
            stack.enter_context(patch("app.routers.debug._build_bbox_per_frame", return_value=[target_lock["selected_bbox"]]))
            stack.enter_context(patch("app.routers.debug.extract_pose", return_value=pose_data))
            stack.enter_context(patch("app.routers.debug.infer_analysis_profile", return_value=("jump", {"quality_flags": []})))
            stack.enter_context(patch("app.routers.debug.analyze_biomechanics", return_value={"quality_flags": []}))
            stack.enter_context(patch("app.routers.debug.attach_key_frame_candidates", return_value=dict(bio_data)))
            pipeline_mock = stack.enter_context(patch("app.routers.debug.run_semantic_keyframe_pipeline", AsyncMock(return_value=semantic_result)))
            stack.enter_context(patch("app.routers.analysis.analyze_frames_dual", side_effect=AssertionError("image AI should not run")))
            stack.enter_context(patch("app.routers.analysis.generate_report", side_effect=AssertionError("report AI should not run")))
            await debug_router.process_debug_run(run_id)

        pipeline_mock.assert_awaited_once()
        passed_bio_data = pipeline_mock.await_args.kwargs["bio_data"]
        self.assertEqual(passed_bio_data["key_frame_candidates"], bio_data["key_frame_candidates"])
        self.assertIn("debug_video_ai_upload_auto_bio_candidates_used", passed_bio_data["quality_flags"])
        async with self.database.AsyncSessionLocal() as session:
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_run)
            assert saved_run is not None
            self.assertEqual(saved_run.status, "completed")
            self.assertEqual(saved_run.result_json["target_lock"]["debug_source"], "debug_upload_auto_target_lock")
            self.assertEqual(saved_run.result_json["key_frame_candidates"], bio_data["key_frame_candidates"])
            self.assertIn("debug_video_ai_upload_auto_bio_candidates_used", saved_run.result_json["bio_data"]["quality_flags"])

    async def test_video_ai_upload_auto_lock_prefers_stable_middle_anchor_over_late_motion_peak(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.video import VideoSamplingMetadata

        run_id = str(uuid4())
        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        sampled = [frames_dir / f"frame_{index:04d}.jpg" for index in range(1, 6)]
        for frame in sampled:
            frame.write_bytes(b"frame")
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 0.0, "motion_score": 0.02},
                {"frame_id": "frame_0002", "timestamp": 0.2, "motion_score": 0.03},
                {"frame_id": "frame_0003", "timestamp": 0.4, "motion_score": 0.04},
                {"frame_id": "frame_0004", "timestamp": 0.6, "motion_score": 0.05},
                {"frame_id": "frame_0005", "timestamp": 0.8, "motion_score": 0.90},
            ]
        }
        run = models.DebugRun(
            id=run_id,
            mode="video_ai_keyframes",
            source_type="upload",
            video_path=str(debug_root / "source.mp4"),
            action_type="jump",
            analysis_profile="jump",
            status="processing",
        )
        stable = {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.20}
        late_peak = {"x": 0.20, "y": 0.05, "width": 0.30, "height": 0.90}

        def fake_detect(frame_path: Path, **_: object) -> list[dict[str, object]]:
            if frame_path.name in {"frame_0002.jpg", "frame_0003.jpg", "frame_0004.jpg"}:
                return [{"id": "stable", "bbox": stable, "confidence": 0.78, "source": "test"}]
            if frame_path.name == "frame_0005.jpg":
                return [{"id": "late", "bbox": late_peak, "confidence": 0.94, "source": "test"}]
            return []

        with patch("app.routers.debug.detect_person_candidates", side_effect=fake_detect):
            target_lock = debug_router._video_ai_upload_target_lock(
                run,
                sampled_frames=sampled,
                motion_scores=motion_scores,
            )

        self.assertIsNotNone(target_lock)
        assert target_lock is not None
        self.assertEqual(target_lock["preview_frame"], "frame_0003.jpg")
        self.assertEqual(target_lock["selected_bbox"], stable)
        self.assertEqual(target_lock["selected_candidate_id"], "candidate_auto_stable")

    async def test_video_ai_upload_auto_lock_prefers_zoomed_small_target_over_foreground_person(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router

        run_id = str(uuid4())
        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        sampled = [frames_dir / f"frame_{index:04d}.jpg" for index in range(1, 6)]
        for frame in sampled:
            frame.write_bytes(b"frame")
        motion_scores = {"selected": [{"frame_id": "frame_0005", "timestamp": 0.8, "motion_score": 0.90}]}
        run = models.DebugRun(
            id=run_id,
            mode="video_ai_keyframes",
            source_type="upload",
            video_path=str(debug_root / "source.mp4"),
            action_type="jump",
            analysis_profile="jump",
            status="processing",
        )
        foreground = {"x": 0.34, "y": 0.06, "width": 0.31, "height": 0.91}
        small_target = {"x": 0.42, "y": 0.31, "width": 0.07, "height": 0.19}

        def fake_detect(frame_path: Path, **kwargs: object) -> list[dict[str, object]]:
            self.assertTrue(kwargs.get("include_zoomed_small_targets"))
            if frame_path.name in {"frame_0002.jpg", "frame_0003.jpg", "frame_0004.jpg"}:
                return [
                    {"id": "foreground", "bbox": foreground, "confidence": 0.91, "source": "yolo_preview"},
                    {"id": "small", "bbox": small_target, "confidence": 0.86, "source": "yolo_zoomed_content"},
                ]
            return [{"id": "foreground", "bbox": foreground, "confidence": 0.93, "source": "yolo_preview"}]

        with patch("app.routers.debug.detect_person_candidates", side_effect=fake_detect):
            target_lock = debug_router._video_ai_upload_target_lock(
                run,
                sampled_frames=sampled,
                motion_scores=motion_scores,
            )

        self.assertIsNotNone(target_lock)
        assert target_lock is not None
        self.assertEqual(target_lock["selected_candidate_id"], "candidate_auto_stable")
        self.assertEqual(target_lock["selected_bbox"], small_target)

    async def test_video_ai_debug_summary_counts_moderate_blended_semantic_frames(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.semantic_keyframe_pipeline import SemanticKeyframePipelineResult
        from app.services.video import VideoSamplingMetadata

        run_id = str(uuid4())
        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        semantic_dir = debug_root / "semantic_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        semantic_dir.mkdir(parents=True, exist_ok=True)
        source_video = debug_root / "source.mp4"
        source_video.write_bytes(b"fake-video")
        sampled = [frames_dir / "frame_0001.jpg"]
        sampled[0].write_bytes(b"frame")
        semantic_frames = []
        semantic_records = []
        for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
            frame = semantic_dir / f"semantic_{index:04d}.jpg"
            frame.write_bytes(b"semantic")
            semantic_frames.append(frame)
            semantic_records.append(
                {
                    "frame_id": f"semantic_{index:04d}",
                    "timestamp": 1.0 + index * 0.2,
                    "phase_code": phase_code,
                    "phase_label": phase_code,
                }
            )

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.DebugRun(
                    id=run_id,
                    mode="video_ai_keyframes",
                    source_type="upload",
                    video_path=str(source_video),
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                    action_subtype="Axel",
                    analysis_profile="jump",
                    status="pending",
                )
            )
            await session.commit()

        motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 0.4, "motion_score": 0.9}], "scores": [0.9]}
        sampling = VideoSamplingMetadata(0.0, 2.0, 0.0, 2.0, 10.0, 30.0, False)
        video_temporal = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.6,
            "fallback_recommendation": "use_sampled_frames",
            "quality_flags": ["video_temporal_fallback_recommended"],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.6,
            "quality_flags": [
                "video_temporal_resolver_advisory_fallback_overridden",
                "video_temporal_resolver_moderate_confidence_tal_used",
            ],
            "selected": semantic_records,
            "video_ai": video_temporal,
        }
        semantic_result = SemanticKeyframePipelineResult(
            ai_clip={
                "path": str(debug_root / "action_window_ai.mp4"),
                "duration_sec": 2.0,
                "source_duration_sec": 5.0,
                "fps": 15.0,
                "timestamp_offset_sec": 0.0,
            },
            video_temporal=video_temporal,
            resolved_keyframes=resolved,
            semantic_frames=semantic_frames,
            semantic_records=semantic_records,
            quality_flags=[*video_temporal["quality_flags"], *resolved["quality_flags"]],
            used_semantic_frames=True,
        )

        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling))))
            stack.enter_context(patch("app.routers.debug.run_semantic_keyframe_pipeline", AsyncMock(return_value=semantic_result)))
            await debug_router.process_debug_run(run_id)

        async with self.database.AsyncSessionLocal() as session:
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_run)
            assert saved_run is not None
            self.assertEqual(saved_run.status, "completed")
            self.assertTrue(saved_run.summary["used_semantic_frames"])
            self.assertEqual(saved_run.summary["semantic_frame_count"], 3)
            self.assertEqual(saved_run.summary["resolved_source"], "blended")
            self.assertEqual(saved_run.summary["timestamp_source"], "blended")
            self.assertEqual(saved_run.summary["action_window"], {"start_sec": 0.0, "end_sec": 2.0, "duration_sec": 2.0})
            self.assertEqual(len(saved_run.result_json["semantic_frames"]), 3)

    async def test_video_ai_debug_summary_marks_sampled_frames_when_semantic_rejected(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.semantic_keyframe_pipeline import SemanticKeyframePipelineResult
        from app.services.video import VideoSamplingMetadata

        run_id = str(uuid4())
        debug_root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = debug_root / "frames"
        semantic_dir = debug_root / "semantic_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        semantic_dir.mkdir(parents=True, exist_ok=True)
        source_video = debug_root / "source.mp4"
        source_video.write_bytes(b"fake-video")
        sampled = [frames_dir / "frame_0001.jpg"]
        sampled[0].write_bytes(b"frame")
        partial_frame = semantic_dir / "partial_semantic_0001.jpg"
        partial_frame.write_bytes(b"partial")
        partial_records = [
            {
                "frame_id": "partial_semantic_0001",
                "timestamp": 1.2,
                "phase_code": "air",
                "phase_label": "air",
                "selection_status": "partial_unreliable",
            }
        ]

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.DebugRun(
                    id=run_id,
                    mode="video_ai_keyframes",
                    source_type="upload",
                    video_path=str(source_video),
                    action_type="jump",
                    action_subtype="Axel",
                    analysis_profile="jump",
                    status="pending",
                )
            )
            await session.commit()

        motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 0.4, "motion_score": 0.9}], "scores": [0.9]}
        sampling = VideoSamplingMetadata(0.0, 2.0, 0.0, 2.0, 10.0, 30.0, False)
        video_temporal = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.8,
            "fallback_recommendation": "use_video_timestamps",
            "quality_flags": [],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.0, "phase_code": "takeoff", "phase_label": "takeoff"},
                {"frame_id": "semantic_0002", "timestamp": 1.2, "phase_code": "air", "phase_label": "air"},
                {"frame_id": "semantic_0003", "timestamp": 1.4, "phase_code": "landing", "phase_label": "landing"},
            ],
            "video_ai": video_temporal,
        }
        semantic_result = SemanticKeyframePipelineResult(
            ai_clip={
                "path": str(debug_root / "action_window_ai.mp4"),
                "duration_sec": 2.0,
                "source_duration_sec": 5.0,
                "fps": 15.0,
                "timestamp_offset_sec": 0.0,
            },
            video_temporal=video_temporal,
            resolved_keyframes=resolved,
            semantic_frames=[],
            semantic_records=[],
            partial_semantic_frames=[partial_frame],
            partial_semantic_records=partial_records,
            quality_flags=[*resolved["quality_flags"]],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )

        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling))))
            stack.enter_context(patch("app.routers.debug.run_semantic_keyframe_pipeline", AsyncMock(return_value=semantic_result)))
            await debug_router.process_debug_run(run_id)

        async with self.database.AsyncSessionLocal() as session:
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_run)
            assert saved_run is not None
            self.assertEqual(saved_run.status, "completed")
            self.assertFalse(saved_run.summary["used_semantic_frames"])
            self.assertEqual(saved_run.summary["semantic_frame_count"], 0)
            self.assertEqual(saved_run.summary["partial_semantic_frame_count"], 1)
            self.assertEqual(saved_run.summary["resolved_source"], "sampled_frames")
            self.assertEqual(saved_run.summary["timestamp_source"], "sampled_frames")
            self.assertEqual(saved_run.summary["action_window"], {"start_sec": 0.0, "end_sec": 2.0, "duration_sec": 2.0})
            self.assertEqual(saved_run.summary["resolver_source"], "video_ai_refined")
            self.assertEqual(saved_run.result_json["effective_timestamp_source"], "sampled_frames")
            self.assertEqual(saved_run.result_json["resolved_keyframes"]["source"], "video_ai_refined")
            self.assertEqual(saved_run.result_json["partial_semantic_frames"][0]["frame_id"], "partial_semantic_0001")
            response = await debug_router.get_debug_run_frame(run_id, "partial_semantic_0001.jpg", session)
            self.assertEqual(Path(response.path), partial_frame)

    async def test_debug_frame_endpoint_blocks_invalid_filenames(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router

        run_id = str(uuid4())
        root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"frame")

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.DebugRun(
                    id=run_id,
                    mode="local_pose_keyframes",
                    source_type="upload",
                    video_path=str(root / "source.mp4"),
                    action_type="è·³è·ƒ",
                    status="completed",
                )
            )
            await session.commit()

            response = await debug_router.get_debug_run_frame(run_id, "frame_0001.jpg", session)
            self.assertEqual(Path(response.path), frames_dir / "frame_0001.jpg")
            with self.assertRaises(Exception):
                await debug_router.get_debug_run_frame(run_id, "../source.mp4", session)

    async def test_progress_update_ignores_sqlite_locked_after_retries(self) -> None:
        import app.routers.debug as debug_router
        from sqlalchemy.exc import OperationalError

        locked = OperationalError(
            "UPDATE debug_runs SET summary=?",
            {},
            sqlite3.OperationalError("database is locked"),
        )

        async def raise_locked(*args, **kwargs):
            raise locked

        with patch("app.routers.debug._with_debug_db_write_retry", raise_locked):
            await debug_router._update_run_progress(
                "debug-run",
                stage="video_ai",
                label="Calling Video AI",
                progress=0.5,
            )

    async def test_progress_update_reraises_non_locked_operational_error(self) -> None:
        import app.routers.debug as debug_router
        from sqlalchemy.exc import OperationalError

        failure = OperationalError(
            "UPDATE debug_runs SET summary=?",
            {},
            sqlite3.OperationalError("disk I/O error"),
        )

        async def raise_failure(*args, **kwargs):
            raise failure

        with patch("app.routers.debug._with_debug_db_write_retry", raise_failure):
            with self.assertRaises(OperationalError):
                await debug_router._update_run_progress(
                    "debug-run",
                    stage="video_ai",
                    label="Calling Video AI",
                    progress=0.5,
                )

    async def test_delete_debug_run_removes_record_and_artifacts(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router

        run_id = str(uuid4())
        root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        root.mkdir(parents=True, exist_ok=True)
        (root / "source.mp4").write_bytes(b"video")

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.DebugRun(
                    id=run_id,
                    mode="local_pose_keyframes",
                    source_type="upload",
                    video_path=str(root / "source.mp4"),
                    action_type="jump",
                    status="completed",
                )
            )
            await session.commit()

            response = await debug_router.delete_debug_run(run_id, session)
            self.assertEqual(response.status_code, 204)
            self.assertIsNone(await session.get(models.DebugRun, run_id))
            self.assertFalse(root.exists())

    async def test_delete_debug_run_blocks_processing_record(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router

        run_id = str(uuid4())
        root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        root.mkdir(parents=True, exist_ok=True)
        (root / "source.mp4").write_bytes(b"video")

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.DebugRun(
                    id=run_id,
                    mode="local_pose_keyframes",
                    source_type="upload",
                    video_path=str(root / "source.mp4"),
                    action_type="jump",
                    status="processing",
                )
            )
            await session.commit()

            with self.assertRaises(Exception):
                await debug_router.delete_debug_run(run_id, session)
            self.assertIsNotNone(await session.get(models.DebugRun, run_id))
            self.assertTrue(root.exists())

    async def test_video_ai_retry_progress_labels_are_user_facing_and_monotonic(self) -> None:
        import app.routers.debug as debug_router

        self.assertEqual(
            debug_router.DEBUG_VIDEO_AI_STAGE_LABELS["video_temporal_retry"],
            "Video AI result failed quality gates; retrying with resolver diagnostics.",
        )
        self.assertEqual(
            debug_router.DEBUG_VIDEO_AI_STAGE_LABELS["video_temporal_retry_used"],
            "Video AI retry produced reliable semantic keyframes.",
        )
        self.assertGreater(
            debug_router.DEBUG_VIDEO_AI_STAGE_PROGRESS["video_temporal_retry"],
            debug_router.DEBUG_VIDEO_AI_STAGE_PROGRESS["video_temporal_received"],
        )
        self.assertGreater(
            debug_router.DEBUG_VIDEO_AI_STAGE_PROGRESS["semantic_frames_resolved"],
            debug_router.DEBUG_VIDEO_AI_STAGE_PROGRESS["video_temporal_retry"],
        )

    async def test_local_upload_debug_run_waits_for_manual_target_then_continues(self) -> None:
        import app.models as models
        import app.routers.debug as debug_router
        from app.services.video import VideoSamplingMetadata

        run_id = str(uuid4())
        root = Path(self.tmp.name) / "uploads" / "_debug" / run_id
        frames_dir = root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        source_video = root / "source.mp4"
        source_video.write_bytes(b"fake-video")
        sampled = [frames_dir / f"frame_{index:04d}.jpg" for index in range(1, 3)]
        for frame in sampled:
            frame.write_bytes(b"frame")

        async with self.database.AsyncSessionLocal() as session:
            session.add(
                models.DebugRun(
                    id=run_id,
                    mode="local_pose_keyframes",
                    source_type="upload",
                    video_path=str(source_video),
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                    action_subtype="Axel",
                    analysis_profile="jump",
                    status="pending",
                )
            )
            await session.commit()

        motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 0.1, "motion_score": 0.4}], "scores": [0.4]}
        sampling = VideoSamplingMetadata(0.0, 1.0, 0.0, 1.0, 10.0, 30.0, False)
        pose_data = {
            "connections": [],
            "frames": [{"frame": "frame_0001.jpg", "keypoints": [], "tracking_state": "tracked", "tracking_confidence": 0.8}],
            "pose_diagnostics": {"total_frames": 1, "tracked_frames": 1, "lost_frames": 0, "low_confidence_frames": 0, "frames": []},
        }
        bio_data = {"quality_flags": [], "key_frame_candidates": {"T": {"frame_id": "frame_0001", "confidence": 0.8}}}

        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            extract_mock = stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling))))
            stack.enter_context(patch("app.routers.debug.extract_pose", side_effect=AssertionError("pose should wait for manual target lock")))
            await debug_router.process_debug_run(run_id)

        extract_mock.assert_awaited_once()
        self.assertNotIn("full_video_window", extract_mock.call_args.kwargs)
        async with self.database.AsyncSessionLocal() as session:
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_run)
            assert saved_run is not None
            self.assertEqual(saved_run.status, "awaiting_target_selection")
            self.assertIn("target_preview", saved_run.result_json)
            self.assertEqual(saved_run.result_json["sampling_source"], "upload_formal_pipeline")

            response = await debug_router.confirm_debug_target_lock(
                run_id,
                {"manual_bbox": {"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.5}},
                SimpleNamespace(add_task=lambda *args, **kwargs: None),
                session,
            )
            self.assertEqual(response.status, "pending")

        with ExitStack() as stack:
            stack.enter_context(patch("app.routers.debug.precheck_video", AsyncMock(return_value=None)))
            extract_mock = stack.enter_context(patch("app.routers.debug.extract_motion_sampled_frames", AsyncMock(side_effect=AssertionError("frames should be reused"))))
            stack.enter_context(patch("app.routers.debug._build_bbox_per_frame", return_value=[{"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.5}]))
            stack.enter_context(patch("app.routers.debug.extract_pose", return_value=pose_data))
            stack.enter_context(patch("app.routers.debug.infer_analysis_profile", return_value=("jump", {"quality_flags": []})))
            stack.enter_context(patch("app.routers.debug.analyze_biomechanics", return_value={"quality_flags": []}))
            stack.enter_context(patch("app.routers.debug.attach_key_frame_candidates", return_value=bio_data))
            await debug_router.process_debug_run(run_id)

        extract_mock.assert_not_called()
        async with self.database.AsyncSessionLocal() as session:
            saved_run = await session.get(models.DebugRun, run_id)
            self.assertIsNotNone(saved_run)
            assert saved_run is not None
            self.assertEqual(saved_run.status, "completed")
            self.assertEqual(saved_run.result_json["target_lock"]["status"], "manual")
            self.assertIn("key_frame_candidates", saved_run.result_json)


if __name__ == "__main__":
    unittest.main()
