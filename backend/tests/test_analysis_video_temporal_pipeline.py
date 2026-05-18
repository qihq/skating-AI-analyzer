from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _report() -> dict[str, object]:
    return {
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


def _dual(vision_structured: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        path_a=vision_structured,
        path_b={"path": "B", "subscores": {}},
        validation=SimpleNamespace(to_dict=lambda: {"recommended_path": "A"}),
        dual_path_meta={"recommended_path": "A"},
        blend_weights=(1.0, 0.0),
        annotated_dir=None,
        used_key_frames=set(),
    )


class AnalysisVideoTemporalPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_temporal_success_persists_resolved_keyframes_and_uses_semantic_frames(self) -> None:
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
            from app.services.video import VideoSamplingMetadata

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            source_video = upload_dir / "source.mp4"
            source_video.write_bytes(b"fake-video")

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="跳跃",
                        action_subtype="Axel",
                        video_path=str(source_video),
                        status="pending",
                    )
                )
                await session.commit()

            processing_dir, frames_dir = analysis_router.build_processing_frames_dir(analysis_id)
            sampled = []
            for index in range(1, 4):
                path = frames_dir / f"frame_{index:04d}.jpg"
                path.write_bytes(b"sampled")
                sampled.append(path)
            semantic_dir = processing_dir / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            semantic_paths = []
            for index in range(1, 3):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(b"semantic")
                semantic_paths.append(path)

            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 1.0, "motion_score": 0.2},
                    {"frame_id": "frame_0002", "timestamp": 1.2, "motion_score": 0.9},
                ],
                "scores": [0.2, 0.9],
            }
            sampling_metadata = VideoSamplingMetadata(
                action_window_start=0.0,
                action_window_end=2.0,
                window_start_sec=0.0,
                window_end_sec=2.0,
                effective_fps=10.0,
                source_fps=30.0,
                is_slow_motion=False,
            )
            pose_data = {"frames": [{"frame": "frame_0001.jpg", "keypoints": []}], "connections": []}
            bio_data = {
                "key_frame_candidates": {"T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.8}},
                "quality_flags": [],
            }
            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.86, "quality_flags": []}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.86,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 1.2, "phase_code": "takeoff", "phase_label": "起跳"}
                ],
                "video_ai": video_temporal,
            }
            semantic_records = [
                {"frame_id": "semantic_0001", "timestamp": 1.2, "phase_code": "takeoff", "phase_label": "起跳"}
            ]
            vision_structured = {
                "frame_analysis": [{"frame_id": "semantic_0001", "phase": "起跳", "confidence": 0.9}],
                "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
                "overall_raw_text": "ok",
            }

            with ExitStack() as stack:
                stack.enter_context(patch("app.routers.analysis.build_processing_frames_dir", return_value=(processing_dir, frames_dir)))
                stack.enter_context(patch("app.routers.analysis.precheck_video", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling_metadata))))
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=SimpleNamespace(lock_confidence=1.0)))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value=pose_data))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value=bio_data))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                stack.enter_context(patch("app.routers.analysis.analyze_video_temporal", AsyncMock(return_value=video_temporal)))
                stack.enter_context(patch("app.routers.analysis.resolve_semantic_keyframes", return_value=resolved))
                refine_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.refine_semantic_keyframe_timestamps",
                        AsyncMock(
                            return_value=(
                                [
                                    {
                                        "frame_id": "semantic_0001",
                                        "timestamp": 1.24,
                                        "phase_code": "takeoff",
                                        "phase_label": "起跳",
                                        "pre_refine_timestamp": 1.2,
                                        "refinement_method": "local_motion_peak",
                                        "refinement_delta_sec": 0.04,
                                    }
                                ],
                                [],
                            )
                        ),
                    )
                )
                stack.enter_context(patch("app.routers.analysis.extract_precise_frames_at_timestamps", AsyncMock(return_value=(semantic_paths, semantic_records))))
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.2)]),
                    )
                )
                stack.enter_context(patch("app.routers.analysis.cut_action_window_clip", AsyncMock(return_value=processing_dir / "action_window.mp4")))
                stack.enter_context(patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())))
                stack.enter_context(patch("app.routers.analysis.build_analysis_prompt_context", AsyncMock(return_value=None)))
                dual_mock = stack.enter_context(patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=_dual(vision_structured))))
                stack.enter_context(patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}))
                stack.enter_context(patch("app.routers.analysis.generate_report", AsyncMock(return_value=_report())))
                stack.enter_context(patch("app.routers.analysis.calculate_force_score", return_value=80))
                stack.enter_context(patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)))
                await analysis_router.process_analysis(analysis_id)

            self.assertEqual(encode_mock.await_args.args[0], semantic_paths)
            self.assertEqual(refine_mock.await_args.args[2][0]["timestamp"], 1.2)
            self.assertEqual(dual_mock.await_args.kwargs["frame_paths"], semantic_paths)
            self.assertIsNone(dual_mock.await_args.kwargs["clip_path"])
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertIsInstance(saved.frame_motion_scores, dict)
                assert isinstance(saved.frame_motion_scores, dict)
                self.assertEqual(saved.frame_motion_scores["video_temporal"], video_temporal)
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["selected"], semantic_records)

    async def test_video_temporal_failure_keeps_existing_sampled_frame_flow(self) -> None:
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
            from app.services.video import VideoSamplingMetadata

            database.ensure_storage_dirs()
            await database.init_db()

            analysis_id = str(uuid4())
            upload_dir = Path(tmpdir) / "uploads" / analysis_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            source_video = upload_dir / "source.mp4"
            source_video.write_bytes(b"fake-video")

            async with database.AsyncSessionLocal() as session:
                session.add(models.Analysis(id=analysis_id, action_type="跳跃", action_subtype="Axel", video_path=str(source_video), status="pending"))
                await session.commit()

            _, frames_dir = analysis_router.build_processing_frames_dir(analysis_id)
            sampled = []
            for index in range(1, 3):
                path = frames_dir / f"frame_{index:04d}.jpg"
                path.write_bytes(b"sampled")
                sampled.append(path)

            motion_scores = {"selected": [{"frame_id": "frame_0001", "timestamp": 0.5, "motion_score": 0.4}], "scores": [0.4]}
            sampling_metadata = VideoSamplingMetadata(0.0, 1.0, 0.0, 1.0, 10.0, 30.0, False)
            fallback_video_temporal = {"valid": False, "confidence": 0.0, "quality_flags": ["video_temporal_timeout"]}
            resolved = {"source": "skeleton_fallback", "confidence": 0.0, "quality_flags": [], "selected": [], "video_ai": fallback_video_temporal}
            vision_structured = {
                "frame_analysis": [{"frame_id": "frame_0001", "phase": "起跳", "confidence": 0.9}],
                "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
                "overall_raw_text": "ok",
            }

            with ExitStack() as stack:
                stack.enter_context(patch("app.routers.analysis.build_processing_frames_dir", return_value=(frames_dir.parent, frames_dir)))
                stack.enter_context(patch("app.routers.analysis.precheck_video", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling_metadata))))
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=SimpleNamespace(lock_confidence=1.0)))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value={"frames": [], "connections": []}))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                stack.enter_context(patch("app.routers.analysis.analyze_video_temporal", AsyncMock(return_value=fallback_video_temporal)))
                stack.enter_context(patch("app.routers.analysis.resolve_semantic_keyframes", return_value=resolved))
                precise_mock = stack.enter_context(patch("app.routers.analysis.extract_precise_frames_at_timestamps", AsyncMock()))
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=0.5)]),
                    )
                )
                stack.enter_context(patch("app.routers.analysis.cut_action_window_clip", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis._provider_for_slot", AsyncMock(return_value=SimpleNamespace())))
                stack.enter_context(patch("app.routers.analysis.build_analysis_prompt_context", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.analyze_frames_dual", AsyncMock(return_value=_dual(vision_structured))))
                stack.enter_context(patch("app.routers.analysis.dual_path_summary", return_value={"recommended": "A", "n_frames_b": 0}))
                stack.enter_context(patch("app.routers.analysis.generate_report", AsyncMock(return_value=_report())))
                stack.enter_context(patch("app.routers.analysis.calculate_force_score", return_value=80))
                stack.enter_context(patch("app.routers.analysis.auto_update_skill_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.sync_skater_progress", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.suggest_memory_updates", AsyncMock(return_value=None)))
                await analysis_router.process_analysis(analysis_id)

            self.assertEqual(encode_mock.await_args.args[0], sampled)
            precise_mock.assert_not_awaited()
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertEqual(saved.frame_motion_scores["video_temporal"], fallback_video_temporal)
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["source"], "skeleton_fallback")


if __name__ == "__main__":
    unittest.main()
