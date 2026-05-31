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


def _auto_locked_preview(lock_confidence: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(lock_confidence=lock_confidence, target_lock_status="auto_locked")


class AnalysisVideoTemporalPipelineTests(unittest.IsolatedAsyncioTestCase):
    def test_formal_target_preview_candidates_selects_stable_detected_target(self) -> None:
        import app.routers.analysis as analysis_router

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sampled = []
            for index in range(1, 6):
                path = root / f"frame_{index:04d}.jpg"
                path.write_bytes(b"frame")
                sampled.append(path)
            motion_scores = {"selected": [{"frame_id": "frame_0003", "timestamp": 0.6, "motion_score": 0.9}]}

            stable = {"bbox": {"x": 0.42, "y": 0.26, "width": 0.12, "height": 0.32}, "confidence": 0.83, "source": "yolo_preview"}
            other = {"bbox": {"x": 0.06, "y": 0.15, "width": 0.25, "height": 0.55}, "confidence": 0.91, "source": "yolo_preview"}

            def fake_detect(frame_path: Path, **_: object) -> list[dict[str, object]]:
                if frame_path.name in {"frame_0002.jpg", "frame_0003.jpg", "frame_0004.jpg"}:
                    return [stable]
                return [other]

            with patch("app.routers.analysis.detect_person_candidates", side_effect=fake_detect):
                candidates = analysis_router._formal_target_preview_candidates(sampled, motion_scores)

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "candidate_auto_stable")
        self.assertEqual(candidates[0]["bbox"], stable["bbox"])
        self.assertGreaterEqual(candidates[0]["support_count"], 3)

    async def test_video_temporal_diagnostics_include_partial_semantic_frames(self) -> None:
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
            semantic_dir = upload_dir / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            partial_frame = semantic_dir / "partial_semantic_0001.jpg"
            partial_frame.write_bytes(b"partial")
            partial_records = [
                {
                    "frame_id": "partial_semantic_0001",
                    "timestamp": 1.2,
                    "phase_code": "air",
                    "selection_status": "partial_unreliable",
                }
            ]
            motion_scores = {
                "video_temporal": {"schema_version": "video_temporal_v1", "confidence": 0.75, "quality_flags": []},
                "resolved_keyframes": {
                    "source": "skeleton_fallback",
                    "confidence": 0.75,
                    "quality_flags": ["semantic_keyframes_partial_core_frames_available"],
                    "selected": [],
                    "partial_selected": partial_records,
                },
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="completed",
                        frame_motion_scores=motion_scores,
                    )
                )
                await session.commit()
                analysis = await session.get(models.Analysis, analysis_id)
                assert analysis is not None
                diagnostics = analysis_router._video_temporal_diagnostics(analysis.frame_motion_scores, analysis_id=analysis_id)

                self.assertIsNotNone(diagnostics)
                assert diagnostics is not None
                self.assertFalse(diagnostics["used_semantic_frames"])
                self.assertTrue(diagnostics["used_legacy_sampled_frames"])
                self.assertEqual(diagnostics["partial_semantic_frames"], partial_records)
                response = await analysis_router.get_frame(analysis_id, "partial_semantic_0001.jpg", session)
                self.assertEqual(Path(response.path), partial_frame)

    async def test_video_temporal_diagnostics_preserve_complete_partial_tal(self) -> None:
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
            semantic_dir = upload_dir / "semantic_frames"
            semantic_dir.mkdir(parents=True, exist_ok=True)
            partial_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                frame_id = f"partial_semantic_{index:04d}"
                (semantic_dir / f"{frame_id}.jpg").write_bytes(b"partial")
                partial_records.append(
                    {
                        "frame_id": frame_id,
                        "timestamp": 5.0 + index * 0.2,
                        "phase_code": phase_code,
                        "key_moment": ["T_takeoff_sec", "A_air_sec", "L_landing_sec"][index - 1],
                        "selection_status": "partial_unreliable",
                    }
                )
            motion_scores = {
                "video_temporal": {
                    "schema_version": "video_temporal_v1",
                    "confidence": 0.5,
                    "fallback_recommendation": "manual_review",
                    "quality_flags": ["video_temporal_low_confidence"],
                },
                "resolved_keyframes": {
                    "source": "skeleton_fallback",
                    "confidence": 0.5,
                    "quality_flags": [
                        "video_temporal_resolver_low_video_confidence",
                        "semantic_keyframes_partial_core_frames_available",
                    ],
                    "selected": [],
                    "partial_selected": partial_records,
                },
            }

            async with database.AsyncSessionLocal() as session:
                session.add(
                    models.Analysis(
                        id=analysis_id,
                        action_type="jump",
                        video_path=str(upload_dir / "source.mp4"),
                        status="completed",
                        frame_motion_scores=motion_scores,
                    )
                )
                await session.commit()
                analysis = await session.get(models.Analysis, analysis_id)
                assert analysis is not None
                diagnostics = analysis_router._video_temporal_diagnostics(analysis.frame_motion_scores, analysis_id=analysis_id)

                self.assertIsNotNone(diagnostics)
                assert diagnostics is not None
                self.assertEqual(diagnostics["timestamp_source"], "sampled_frames")
                self.assertFalse(diagnostics["used_semantic_frames"])
                self.assertTrue(diagnostics["used_legacy_sampled_frames"])
                self.assertEqual([item["phase_code"] for item in diagnostics["partial_semantic_frames"]], ["takeoff", "air", "landing"])
                response = await analysis_router.get_frame(analysis_id, "partial_semantic_0003.jpg", session)
                self.assertEqual(Path(response.path), semantic_dir / "partial_semantic_0003.jpg")

    async def test_post_vision_partial_semantic_frames_from_low_confidence_phase_anchors(self) -> None:
        import app.routers.analysis as analysis_router

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.2,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
            }
            vision_structured = {
                "frame_analysis": [
                    {"frame_id": "frame_0019", "phase": "起跳", "confidence": 0.2},
                    {"frame_id": "frame_0025", "phase": "腾空", "confidence": 0.1},
                    {"frame_id": "frame_0030", "phase": "滑出", "confidence": 0.3},
                ]
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0019", "timestamp": 2.712},
                    {"frame_id": "frame_0025", "timestamp": 3.712},
                    {"frame_id": "frame_0030", "timestamp": 4.775},
                ]
            }
            partial_paths = [semantic_dir / "partial_semantic_0001.jpg", semantic_dir / "partial_semantic_0002.jpg"]
            partial_records = [
                {
                    "frame_id": "partial_semantic_0001",
                    "timestamp": 2.712,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_status": "partial_unreliable",
                },
                {
                    "frame_id": "partial_semantic_0002",
                    "timestamp": 3.712,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_status": "partial_unreliable",
                },
            ]

            with patch(
                "app.routers.analysis.extract_precise_frames_at_timestamps",
                AsyncMock(return_value=(partial_paths, partial_records)),
            ) as extract_mock:
                updated = await analysis_router._attach_post_vision_partial_semantic_frames(
                    video_path=video_path,
                    semantic_frames_dir=semantic_dir,
                    resolved_keyframes=resolved,
                    vision_structured=vision_structured,
                    frame_motion_scores=motion_scores,
                    analysis_profile="jump",
                )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertFalse(analysis_router.semantic_keyframes_are_reliable(updated))
        self.assertEqual(updated["partial_selected"], partial_records)
        self.assertIn("semantic_keyframes_post_vision_partial_phase_frames_available", updated["quality_flags"])
        extract_mock.assert_awaited_once()
        args = extract_mock.await_args.args
        self.assertEqual(args[0], video_path)
        self.assertEqual(args[1], semantic_dir)
        self.assertEqual(extract_mock.await_args.kwargs["prefix"], "partial_semantic")

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
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=_auto_locked_preview()))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value=pose_data))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value=bio_data))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                temporal_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", AsyncMock(return_value=video_temporal)))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved))
                refine_mock = stack.enter_context(
                    patch(
                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
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
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(return_value=(semantic_paths, semantic_records))))
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.2)]),
                    )
                )
                ai_clip_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=processing_dir / "action_window_ai.mp4")))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[6.0, 2.0]))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0))
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
            ai_clip_mock.assert_awaited_once()
            self.assertEqual(ai_clip_mock.await_args.args[3].name, "action_window_ai.mp4")
            temporal_kwargs = temporal_mock.await_args.kwargs
            self.assertEqual(temporal_mock.await_args.args[0].name, "action_window_ai.mp4")
            self.assertEqual(temporal_kwargs["video_duration_sec"], 2.0)
            self.assertEqual(temporal_kwargs["source_video_duration_sec"], 6.0)
            self.assertEqual(temporal_kwargs["timestamp_offset_sec"], 0.0)
            self.assertEqual(temporal_kwargs["analyzed_video_kind"], "action_window_ai")
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
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=_auto_locked_preview()))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value={"frames": [], "connections": []}))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", AsyncMock(return_value=fallback_video_temporal)))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved))
                precise_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock()))
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=0.5)]),
                    )
                )
                ai_clip_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=Path(tmpdir) / "action_window_ai.mp4")))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[4.0, 1.0]))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0))
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
            self.assertEqual(ai_clip_mock.await_args_list[-1].args[3].name, "action_window_ai.mp4")
            precise_mock.assert_not_awaited()
            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                self.assertEqual(saved.frame_motion_scores["video_temporal"], fallback_video_temporal)
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["source"], "skeleton_fallback")

    async def test_video_temporal_quality_retry_persists_retry_result_and_uses_semantic_frames(self) -> None:
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
                        action_type="è·³è·ƒ",
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
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append(
                    {
                        "frame_id": f"semantic_{index:04d}",
                        "timestamp": 6.2 + index * 0.25,
                        "phase_code": phase_code,
                        "key_moment": {"takeoff": "T_takeoff_sec", "air": "A_air_sec", "landing": "L_landing_sec"}[phase_code],
                    }
                )

            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 6.2, "motion_score": 0.18},
                    {"frame_id": "frame_0002", "timestamp": 7.8, "motion_score": 0.30},
                ],
                "scores": [0.18, 0.30],
            }
            sampling_metadata = VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False)
            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "phase_segments": [],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_missing_phase_segments"],
                "validation": {"valid": False, "errors": ["video_temporal_missing_phase_segments"], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 6.25, "time_end": 6.65, "confidence": 0.8},
                    {"phase_code": "air", "time_start": 6.65, "time_end": 7.05, "confidence": 0.8},
                    {"phase_code": "landing", "time_start": 7.05, "time_end": 7.35, "confidence": 0.8},
                ],
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_missing_phase_segments", "video_temporal_resolver_no_semantic_selection"],
                "selected": [],
                "video_ai": first_video,
            }
            accepted = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.85, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }
            pose_data = {"frames": [{"frame": "frame_0001.jpg", "keypoints": []}], "connections": []}
            bio_data = {"quality_flags": [], "key_frame_candidates": {}}
            vision_structured = {
                "frame_analysis": [{"frame_id": "semantic_0001", "phase": "èµ·è·³", "confidence": 0.9}],
                "action_phase_summary": {"detected_phases": ["èµ·è·³"], "weakest_phase": "èµ·è·³", "strongest_phase": "èµ·è·³"},
                "overall_raw_text": "ok",
            }

            with ExitStack() as stack:
                stack.enter_context(patch("app.routers.analysis.build_processing_frames_dir", return_value=(processing_dir, frames_dir)))
                stack.enter_context(patch("app.routers.analysis.precheck_video", AsyncMock(return_value=None)))
                stack.enter_context(patch("app.routers.analysis.extract_motion_sampled_frames", AsyncMock(return_value=(sampled, motion_scores, sampling_metadata))))
                stack.enter_context(patch("app.routers.analysis.build_target_preview", return_value=_auto_locked_preview(0.7113)))
                stack.enter_context(patch("app.routers.analysis.build_target_lock_payload", return_value={"status": "auto_locked", "selected_candidate_id": "candidate_center"}))
                stack.enter_context(patch("app.routers.analysis.extract_pose", return_value=pose_data))
                stack.enter_context(patch("app.routers.analysis.infer_analysis_profile", return_value=("jump", {"quality_flags": [], "negative_constraints": []})))
                stack.enter_context(patch("app.routers.analysis.analyze_biomechanics", return_value={"quality_flags": []}))
                stack.enter_context(patch("app.routers.analysis.attach_key_frame_candidates", return_value=bio_data))
                stack.enter_context(patch("app.routers.analysis.infer_jump_subtype_evidence", return_value={}))
                analyze_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", AsyncMock(side_effect=[first_video, retry_video])))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[rejected, accepted]))
                stack.enter_context(
                    patch(
                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                        AsyncMock(return_value=(accepted["selected"], [])),
                    )
                )
                stack.enter_context(
                    patch(
                        "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                        AsyncMock(return_value=(semantic_paths, semantic_records)),
                    )
                )
                stack.enter_context(
                    patch(
                        "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                        return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                    )
                )
                encode_mock = stack.enter_context(
                    patch(
                        "app.routers.analysis.encode_frames",
                        AsyncMock(return_value=[SimpleNamespace(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=6.45)]),
                    )
                )
                ai_clip_mock = stack.enter_context(patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=processing_dir / "action_window_ai.mp4")))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]))
                stack.enter_context(patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0))
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

            self.assertEqual(analyze_mock.await_count, 2)
            self.assertEqual(analyze_mock.await_args_list[1].kwargs["analyzed_video_kind"], "action_window_ai_retry")
            self.assertIn("retry_context", analyze_mock.await_args_list[1].kwargs)
            self.assertIn("video_temporal_missing_phase_segments", analyze_mock.await_args_list[1].kwargs["retry_context"]["retry_reason_flags"])
            self.assertEqual(ai_clip_mock.await_count, 2)
            self.assertEqual(encode_mock.await_args.args[0], semantic_paths)
            self.assertEqual(dual_mock.await_args.kwargs["frame_paths"], semantic_paths)
            self.assertIsNone(dual_mock.await_args.kwargs["clip_path"])

            async with database.AsyncSessionLocal() as session:
                saved = await session.get(models.Analysis, analysis_id)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved.status, "completed")
                assert isinstance(saved.frame_motion_scores, dict)
                self.assertEqual(saved.frame_motion_scores["video_temporal"], retry_video)
                self.assertIn("video_temporal_quality_retry", saved.frame_motion_scores["video_temporal"]["quality_flags"])
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["source"], "blended")
                self.assertEqual(saved.frame_motion_scores["resolved_keyframes"]["selected"], semantic_records)
                self.assertIn("video_temporal_quality_retry_used", saved.frame_motion_scores["resolved_keyframes"]["quality_flags"])


if __name__ == "__main__":
    unittest.main()
