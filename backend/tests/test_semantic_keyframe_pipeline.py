from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.semantic_keyframe_pipeline import (
    SemanticKeyframePipelineResult,
    _candidate_repair_timestamps,
    _repair_candidate_quality_score,
    _semantic_result_quality_score,
    resolve_semantic_keyframe_pipeline,
    run_semantic_keyframe_pipeline,
    retry_video_temporal_if_needed,
)
from app.services.video import VideoSamplingMetadata
from app.services.video_temporal import normalize_video_temporal_payload, validate_video_temporal_payload


def _validated_coherent_fallback_jump_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "jump_type": "Toe Loop", "confidence": 0.85},
        "phase_segments": [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.25, "key_frame_hint": 5.45, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.25, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 6.95, "key_frame_hint": 6.8, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.25, "key_frame_hint": 7.1, "confidence": 0.8},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.45, "key_frame_hint": 7.35, "confidence": 0.85},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.45, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.9},
        ],
        "key_moments": {"T_takeoff_sec": 6.8, "A_air_sec": 7.1, "L_landing_sec": 7.35},
        "macro_assessment": {},
        "overall_impression": "",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.85,
        "fallback_recommendation": "use_sampled_frames",
        "quality_flags": ["video_temporal_fallback_recommended"],
    }
    return validate_video_temporal_payload(normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"), duration_sec=9.568)


def _validated_late_motion_conflict_jump_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "jump_type": "Toe Loop", "confidence": 0.85},
        "phase_segments": [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.15, "key_frame_hint": 6.25, "confidence": 0.85},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.15, "time_end": 7.75, "key_frame_hint": 7.45, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.75, "time_end": 8.05, "key_frame_hint": 7.95, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 8.05, "time_end": 8.35, "key_frame_hint": 8.25, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.35, "time_end": 8.55, "key_frame_hint": 8.4, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.55, "time_end": 9.25, "key_frame_hint": 8.75, "confidence": 0.8},
        ],
        "key_moments": {"T_takeoff_sec": 7.95, "A_air_sec": 8.25, "L_landing_sec": 8.4},
        "macro_assessment": {},
        "overall_impression": "",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.85,
        "fallback_recommendation": "use_sampled_frames",
        "quality_flags": ["brief_occlusion", "video_temporal_fallback_recommended"],
    }
    return validate_video_temporal_payload(normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"), duration_sec=9.568)


def _validated_latest_retry_early_main_motion_cluster_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "jump_type": "Toe Loop", "confidence": 0.8},
        "phase_segments": [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.15, "key_frame_hint": 5.45, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.15, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.9},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 6.95, "key_frame_hint": 6.75, "confidence": 0.85},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.45, "key_frame_hint": 7.15, "confidence": 0.85},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.45, "time_end": 7.85, "key_frame_hint": 7.65, "confidence": 0.85},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.85, "time_end": 8.65, "key_frame_hint": 8.15, "confidence": 0.9},
        ],
        "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.65},
        "macro_assessment": {},
        "overall_impression": "",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.8,
        "fallback_recommendation": "use_video_timestamps",
        "quality_flags": ["video_temporal_quality_retry"],
    }
    return validate_video_temporal_payload(normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"), duration_sec=9.568)


def _glide_out_motion_scores() -> dict[str, object]:
    return {
        "frame_rate": 16,
        "window_start": 4.65,
        "selected": [
            {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
            {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
            {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
            {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
            {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
            {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
        ],
        "scores": [],
    }


def _visible_person_candidates() -> list[dict[str, object]]:
    return [{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}]


def _fake_extract_precise_frames(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    copied_records = []
    for index, record in enumerate(records, start=1):
        path = output_dir / f"{prefix}_{index:04d}.jpg"
        path.write_bytes(b"frame")
        paths.append(path)
        copied_records.append(dict(record))
    return paths, copied_records


class SemanticKeyframePipelineTests(unittest.IsolatedAsyncioTestCase):
    def test_repair_timestamps_use_temporal_neighbors_not_record_order(self) -> None:
        records = [
            {"timestamp": 7.35, "phase_code": "takeoff", "phase_time_start": 7.15, "phase_time_end": 7.45},
            {"timestamp": 7.65, "phase_code": "air", "phase_time_start": 7.45, "phase_time_end": 7.85},
            {"timestamp": 7.95, "phase_code": "landing", "phase_time_start": 7.85, "phase_time_end": 8.15},
            {"timestamp": 6.65, "phase_code": "preparation", "phase_time_start": 6.15, "phase_time_end": 7.15},
            {"timestamp": 8.65, "phase_code": "glide_out", "phase_time_start": 8.15, "phase_time_end": 9.25},
        ]

        candidates = _candidate_repair_timestamps(
            records[2],
            records,
            source_fps=30.0,
            duration_sec=9.568,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0], 7.917)
        self.assertIn(8.017, candidates)

    def test_repair_timestamps_include_pre_refine_search_center(self) -> None:
        records = [
            {"timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 7.35, "phase_time_end": 7.55},
            {"timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.55, "phase_time_end": 7.75},
            {
                "timestamp": 7.803,
                "pre_refine_timestamp": 7.85,
                "phase_code": "landing",
                "key_moment": "L_landing_sec",
                "phase_time_start": 7.75,
                "phase_time_end": 7.95,
            },
        ]

        candidates = _candidate_repair_timestamps(
            records[2],
            records,
            source_fps=30.0,
            duration_sec=9.568,
        )

        self.assertTrue(candidates)
        self.assertIn(7.85, candidates)
        self.assertLess(candidates.index(7.85), candidates.index(7.917))

    def test_repair_timestamps_keep_core_tal_spacing(self) -> None:
        records = [
            {"timestamp": 7.55, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 7.45, "phase_time_end": 7.65},
            {"timestamp": 7.85, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.65, "phase_time_end": 8.05},
            {"timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec", "phase_time_start": 8.05, "phase_time_end": 8.25},
        ]

        candidates = _candidate_repair_timestamps(
            records[1],
            records,
            source_fps=30.0,
            duration_sec=9.568,
        )

        self.assertTrue(candidates)
        self.assertIn(7.75, candidates)
        self.assertNotIn(8.017, candidates)
        self.assertNotIn(8.05, candidates)

    def test_quality_score_penalizes_core_visibility_repair(self) -> None:
        selected = [
            {"timestamp": 7.55, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            {"timestamp": 7.85, "phase_code": "air", "key_moment": "A_air_sec"},
            {"timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
        ]
        clean = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal={"confidence": 0.85, "quality_flags": []},
            resolved_keyframes={"source": "video_ai_refined", "confidence": 0.85, "quality_flags": [], "selected": selected},
            used_semantic_frames=True,
        )
        repaired = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal={"confidence": 0.85, "quality_flags": []},
            resolved_keyframes={
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "selected": [
                    selected[0],
                    {**selected[1], "pre_visibility_repair_timestamp": 7.85, "visibility_repair_timestamp": 7.75},
                    selected[2],
                ],
            },
            used_semantic_frames=True,
        )

        self.assertGreater(_semantic_result_quality_score(clean), _semantic_result_quality_score(repaired))

    async def test_core_foreground_occlusion_repairs_to_nearby_visible_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": []}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.15, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.45, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    repaired_timestamp_ms: int | None = None

                    async def fake_extract(_: Path, output_dir: Path, extract_records: list[dict[str, object]], *, prefix: str = "semantic"):
                        output_dir.mkdir(parents=True, exist_ok=True)
                        if prefix == "semantic":
                            return semantic_paths, [dict(item) for item in extract_records]
                        timestamp = float(extract_records[0]["timestamp"])
                        path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                        path.write_bytes(b"visible")
                        return [path], [{**extract_records[0], "frame_id": "repair_0001"}]

                    def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                        nonlocal repaired_timestamp_ms
                        if frame_path.parent.name.startswith("repair_"):
                            timestamp_ms = int(frame_path.parent.name.rsplit("_", 1)[1])
                            if timestamp_ms == 7717:
                                repaired_timestamp_ms = timestamp_ms
                                return visible
                            return occluded
                        if frame_path.name == "semantic_0003.jpg":
                            return visible if repaired_timestamp_ms == 7717 else occluded
                        return visible

                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["timestamp"], 7.717)
        self.assertEqual(landing["frame_id"], "semantic_0003")
        self.assertEqual(landing["visibility_repair_method"], "nearby_unoccluded_person_frame")
        self.assertNotIn("semantic_visibility", landing)

    async def test_core_foreground_occlusion_repairs_from_pre_refine_timestamp_when_refined_center_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": []}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 7.85,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "phase_time_start": 7.75,
                        "phase_time_end": 7.95,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined_records = [
                {**resolved["selected"][0], "pre_refine_timestamp": 7.45, "refinement_method": "local_motion_peak_phase_rejected"},
                {**resolved["selected"][1], "pre_refine_timestamp": 7.65, "refinement_method": "apex_preserved"},
                {
                    **resolved["selected"][2],
                    "timestamp": 7.803,
                    "pre_refine_timestamp": 7.85,
                    "refinement_method": "local_motion_peak",
                    "refinement_delta_sec": -0.047,
                },
            ]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]
            extracted_paths: list[Path] = []
            repaired_semantic_0003 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0003
                parent_name = frame_path.parent.name
                if parent_name.startswith("repair_"):
                    timestamp_ms = int(parent_name.rsplit("_", 1)[1])
                    if timestamp_ms == 7850:
                        repaired_semantic_0003 = True
                        return visible
                    return occluded
                if frame_path.name == "semantic_0003.jpg":
                    if repaired_semantic_0003:
                        return visible
                    return occluded
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(refined_records, ["semantic_keyframe_refinement_phase_rejected"])),
                ):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["timestamp"], 7.85)
        self.assertEqual(landing["pre_visibility_repair_timestamp"], 7.803)
        self.assertEqual(landing["visibility_repair_search_origin"], "pre_refine_timestamp")
        self.assertEqual(landing["visibility_repair_search_center_timestamp"], 7.85)
        self.assertTrue(any("repair_semantic_0003_00007850" in str(path) for path in extracted_paths))

    async def test_refined_landing_visibility_repair_stays_near_motion_peak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.75, "quality_flags": ["video_temporal_fallback_recommended"]}
            resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_landing_refinement_phase_tolerance"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.95, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 7.45,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "phase_time_start": 7.35,
                        "phase_time_end": 7.55,
                        "phase_time_end_refinement_tolerance_sec": 0.22,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined_records = [
                {**resolved["selected"][0], "timestamp": 6.903, "pre_refine_timestamp": 6.95, "refinement_method": "local_motion_peak"},
                {**resolved["selected"][1], "pre_refine_timestamp": 7.15, "refinement_method": "apex_preserved"},
                {
                    **resolved["selected"][2],
                    "timestamp": 7.717,
                    "pre_refine_timestamp": 7.45,
                    "refinement_method": "local_motion_peak",
                    "refinement_delta_sec": 0.267,
                    "refinement_phase_end_tolerance_used": True,
                },
            ]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]
            extracted_paths: list[Path] = []
            repaired_semantic_0003 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0003
                parent_name = frame_path.parent.name
                if parent_name.startswith("repair_"):
                    timestamp_ms = int(parent_name.rsplit("_", 1)[1])
                    if timestamp_ms == 7750:
                        repaired_semantic_0003 = True
                        return visible
                    if timestamp_ms == 7450:
                        return visible
                    return occluded
                if frame_path.name == "semantic_0003.jpg":
                    return visible if repaired_semantic_0003 else occluded
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(refined_records, ["semantic_keyframe_refinement_phase_end_tolerance_used"])),
                ):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["timestamp"], 7.75)
        self.assertEqual(landing["pre_visibility_repair_timestamp"], 7.717)
        self.assertEqual(landing["visibility_repair_search_origin"], "timestamp")
        self.assertFalse(any("repair_semantic_0003_00007450" in str(path) for path in extracted_paths))

    def test_landing_repair_score_prefers_nearby_candidate_when_quality_is_close(self) -> None:
        context_area = 0.00833728
        nearer = [
            {
                "bbox": {"x": 0.3944, "y": 0.2766, "width": 0.0521, "height": 0.1866},
                "confidence": 0.747,
            }
        ]
        later = [
            {
                "bbox": {"x": 0.3947, "y": 0.2667, "width": 0.0448, "height": 0.1861},
                "confidence": 0.806,
            }
        ]

        nearer_score = _repair_candidate_quality_score(
            nearer,
            candidate_timestamp=8.05,
            original_timestamp=7.95,
            target_context_area=context_area,
            semantic_key="L",
        )
        later_score = _repair_candidate_quality_score(
            later,
            candidate_timestamp=8.117,
            original_timestamp=7.95,
            target_context_area=context_area,
            semantic_key="L",
        )

        self.assertIsNotNone(nearer_score)
        self.assertIsNotNone(later_score)
        self.assertGreater(nearer_score, later_score)

    async def test_motion_cluster_landing_visibility_repair_respects_explicit_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.75, "quality_flags": ["foreground_occlusion"]}
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_motion_cluster_fallback_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.4, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.66},
                    {"frame_id": "semantic_0002", "timestamp": 7.775, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.66},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 7.963,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.66,
                        "phase_time_start": 7.795,
                        "phase_time_end": 8.145,
                        "visibility_repair_max_delta_sec": 0.12,
                        "visibility_repair_preserve_timestamp": True,
                    },
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]
            attempted_repair_ms: list[int] = []
            repaired_semantic_0003 = False

            async def fake_extract(_: Path, output_dir: Path, extract_records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in extract_records]
                timestamp = float(extract_records[0]["timestamp"])
                timestamp_ms = int(round(timestamp * 1000))
                attempted_repair_ms.append(timestamp_ms)
                path = output_dir / f"{prefix}_{timestamp_ms:08d}.jpg"
                path.write_bytes(b"repair")
                return [path], [{**extract_records[0], "frame_id": "repair_0001"}]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0003
                parent_name = frame_path.parent.name
                if parent_name.startswith("repair_"):
                    timestamp_ms = int(parent_name.rsplit("_", 1)[1])
                    if 7995 <= timestamp_ms <= 7997:
                        repaired_semantic_0003 = True
                        return visible
                    if timestamp_ms == 8063:
                        return [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.08, "height": 0.18}, "confidence": 0.95, "area": 0.0144}]
                    return occluded
                if frame_path.name == "semantic_0003.jpg":
                    return visible if repaired_semantic_0003 else occluded
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["timestamp"], 7.963)
        self.assertEqual(landing["pre_visibility_repair_timestamp"], 7.963)
        self.assertTrue(landing["visibility_repair_timestamp_preserved"])
        self.assertEqual(landing["visibility_repair_frame_timestamp"], 7.996)
        self.assertIn(7996, attempted_repair_ms)

    async def test_single_large_foreground_person_repairs_when_target_context_is_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.70, "quality_flags": ["foreground occlusion"]}
            resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 7.85,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "phase_time_start": 7.65,
                        "phase_time_end": 8.05,
                    },
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            single_large_foreground = [{"bbox": {"x": 0.34, "y": 0.20, "width": 0.24, "height": 0.63}, "confidence": 0.81, "area": 0.1512}]
            extracted_paths: list[Path] = []
            repaired_semantic_0002 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0002
                if frame_path.parent.name.startswith("repair_"):
                    timestamp_ms = int(frame_path.parent.name.rsplit("_", 1)[1])
                    if timestamp_ms == 7817:
                        repaired_semantic_0002 = True
                        return visible
                    return single_large_foreground
                if frame_path.name == "semantic_0002.jpg":
                    if repaired_semantic_0002:
                        return visible
                    return single_large_foreground
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        apex = result.resolved_keyframes["selected"][1]
        self.assertEqual(apex["timestamp"], 7.817)
        self.assertEqual(apex["pre_visibility_repair_timestamp"], 7.85)
        self.assertEqual(apex["visibility_repair_method"], "nearby_unoccluded_person_frame")
        self.assertTrue(any("repair_semantic_0002_00007817" in str(path) for path in extracted_paths))

    async def test_foreground_occlusion_repair_keeps_apex_away_from_landing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": ["foreground occlusion"]}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 7.55,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "phase_time_start": 7.45,
                        "phase_time_end": 7.65,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 7.85,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "phase_time_start": 7.65,
                        "phase_time_end": 8.05,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 8.15,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "phase_time_start": 8.05,
                        "phase_time_end": 8.25,
                    },
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible_context = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            original_occluded = [{"bbox": {"x": 0.34, "y": 0.20, "width": 0.24, "height": 0.63}, "confidence": 0.81, "area": 0.1512}]
            earlier_visible = [
                {"bbox": {"x": 0.42, "y": 0.29, "width": 0.07, "height": 0.17}, "confidence": 0.73, "area": 0.0119},
                {"bbox": {"x": 0.55, "y": 0.06, "width": 0.11, "height": 0.91}, "confidence": 0.47, "area": 0.1001},
            ]
            clearer_but_too_close_to_landing = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.08, "height": 0.18}, "confidence": 0.91, "area": 0.0144}]
            extracted_paths: list[Path] = []
            repaired_semantic_0002 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0002
                if frame_path.parent.name.startswith("repair_"):
                    timestamp_ms = int(frame_path.parent.name.rsplit("_", 1)[1])
                    if timestamp_ms == 7750:
                        repaired_semantic_0002 = True
                        return earlier_visible
                    if timestamp_ms in {8017, 8050}:
                        return clearer_but_too_close_to_landing
                    return original_occluded
                if frame_path.name == "semantic_0002.jpg":
                    if repaired_semantic_0002:
                        return earlier_visible
                    return original_occluded
                return visible_context

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        apex = result.resolved_keyframes["selected"][1]
        self.assertEqual(apex["timestamp"], 7.75)
        self.assertEqual(apex["pre_visibility_repair_timestamp"], 7.85)
        self.assertEqual(apex["visibility_repair_method"], "nearby_unoccluded_person_frame")
        self.assertTrue(any("repair_semantic_0002_00007750" in str(path) for path in extracted_paths))
        self.assertFalse(any("repair_semantic_0002_00008017" in str(path) for path in extracted_paths))

    async def test_foreground_occlusion_repair_prefers_clearer_target_over_first_visible_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.70, "quality_flags": ["foreground occlusion"]}
            resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.37, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 7.85,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "phase_time_start": 7.50,
                        "phase_time_end": 8.05,
                    },
                    {"frame_id": "semantic_0003", "timestamp": 8.35, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible_context = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            original_occluded = [{"bbox": {"x": 0.34, "y": 0.20, "width": 0.24, "height": 0.63}, "confidence": 0.81, "area": 0.1512}]
            first_visible_but_foreground_heavy = [
                {"bbox": {"x": 0.42, "y": 0.29, "width": 0.07, "height": 0.17}, "confidence": 0.73, "area": 0.0119},
                {"bbox": {"x": 0.55, "y": 0.06, "width": 0.11, "height": 0.91}, "confidence": 0.47, "area": 0.1001},
            ]
            clearer_target = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.08, "height": 0.18}, "confidence": 0.84, "area": 0.0144}]
            extracted_paths: list[Path] = []
            repaired_semantic_0002 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0002
                if frame_path.parent.name.startswith("repair_"):
                    timestamp_ms = int(frame_path.parent.name.rsplit("_", 1)[1])
                    if timestamp_ms == 7517:
                        repaired_semantic_0002 = True
                        return clearer_target
                    if timestamp_ms == 7817:
                        return first_visible_but_foreground_heavy
                    return original_occluded
                if frame_path.name == "semantic_0002.jpg":
                    if repaired_semantic_0002:
                        return clearer_target
                    return original_occluded
                return visible_context

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        apex = result.resolved_keyframes["selected"][1]
        self.assertEqual(apex["timestamp"], 7.517)
        self.assertEqual(apex["pre_visibility_repair_timestamp"], 7.85)
        self.assertEqual(apex["visibility_repair_method"], "nearby_unoccluded_person_frame")
        self.assertGreater(apex["visibility_repair_quality_score"], 0)
        self.assertTrue(any("repair_semantic_0002_00007517" in str(path) for path in extracted_paths))

    async def test_quality_retry_replaces_repaired_visible_result_when_retry_scores_better(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 6.7 + index * 0.25, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 7.45, "A_air_sec": 7.85, "L_landing_sec": 8.15},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.90,
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.55},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": [
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "semantic_keyframe_core_foreground_occlusion_repaired",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.75, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.75)
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", retry_context["retry_reason_flags"])

    async def test_quality_retry_keeps_repaired_visible_result_when_retry_scores_worse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 7.1 + index * 0.2, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 7.45, "A_air_sec": 7.85, "L_landing_sec": 8.15},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.60,
                "key_moments": {"T_takeoff_sec": 7.45, "A_air_sec": 7.85, "L_landing_sec": 8.15},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.75, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "blended",
                "confidence": 0.60,
                "quality_flags": [
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "semantic_keyframe_core_foreground_occlusion_repaired",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.75, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 7.45)
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertLessEqual(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_early_compressed_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 6.95, "A_air_sec": 7.35, "L_landing_sec": 7.65},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.90,
                "key_moments": {"T_takeoff_sec": 6.35, "A_air_sec": 6.55, "L_landing_sec": 6.75},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": [
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "semantic_keyframe_core_foreground_occlusion_repaired",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.95, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.35, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.65, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.35, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.55, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 6.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.95)
        self.assertIn("video_temporal_quality_retry_early_compressed_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_early_main_motion_cluster_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "key_moments": {"T_takeoff_sec": 7.25, "A_air_sec": 7.65, "L_landing_sec": 7.95},
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.80,
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.65},
                "quality_flags": ["video_temporal_quality_retry"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.95, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.80,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.65, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={
                                                        "selected": [
                                                            {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                                                            {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                                                            {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                                                            {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                                                            {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                                                            {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                                                        ],
                                                    },
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 7.25)
        self.assertIn("video_temporal_quality_retry_early_main_motion_cluster_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_preserves_unreliable_retry_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 6.35, "A_air_sec": 6.55, "L_landing_sec": 6.75},
                "quality_flags": ["video_temporal_quality_retry"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.70,
                "quality_flags": [
                    "video_temporal_resolver_no_semantic_selection",
                    "video_temporal_resolver_partial_skeleton_fallback",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_compressed",
                    "video_temporal_resolver_coherent_tal_early_motion_conflict",
                    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.35, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.55, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 6.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    result = await run_semantic_keyframe_pipeline(
                                        video_path=video_path,
                                        work_dir=root,
                                        semantic_frames_dir=semantic_dir,
                                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                        action_type="jump",
                                        action_subtype=None,
                                        motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                        analysis_profile="jump",
                                        precheck=False,
                                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_early_motion_conflict", result.resolved_keyframes["quality_flags"])
        self.assertIn(
            "video_temporal_resolver_coherent_tal_early_motion_conflict",
            result.resolved_keyframes["video_temporal_quality_retry_rejection_flags"],
        )
        self.assertIn("retry_attempt", result.video_temporal)

    async def test_rejected_retry_diagnostics_do_not_invalidate_original_semantic_frames(self) -> None:
        first_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.80,
            "key_moments": {"T_takeoff_sec": 7.05, "A_air_sec": 7.35, "L_landing_sec": 7.75},
            "quality_flags": ["video_temporal_fallback_recommended"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.20,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_quality_retry", "video_temporal_low_confidence"],
            "validation": {"valid": False, "errors": [], "warnings": ["manual_review"]},
        }
        first_resolved = {
            "source": "blended",
            "confidence": 0.80,
            "quality_flags": [
                "video_temporal_resolver_advisory_fallback_overridden",
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_core_foreground_occlusion_repaired",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 7.05, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 7.35, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 7.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
            "video_ai": first_video,
        }
        retry_resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.20,
            "quality_flags": [
                "video_temporal_resolver_low_video_confidence",
                "video_temporal_resolver_partial_skeleton_fallback",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "selected": [{"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"}],
            "video_ai": retry_video,
        }

        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=first_video,
            resolved_keyframes=first_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=first_resolved["selected"],
            quality_flags=[*first_video["quality_flags"], *first_resolved["quality_flags"]],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[*retry_video["quality_flags"], *retry_resolved["quality_flags"]],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("app.services.semantic_keyframe_pipeline.start_video_temporal_task") as start_mock:
                retry_future = asyncio.get_running_loop().create_future()
                retry_future.set_result(retry_video)
                start_mock.return_value = SimpleNamespace(
                    task=retry_future,
                    source_duration_sec=9.568,
                    ai_clip_payload=lambda: {"duration_sec": 4.6},
                )
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": [{"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302}]},
                        analysis_profile="jump",
                    )

        self.assertIs(updated, result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_partial_skeleton_fallback", updated.resolved_keyframes["quality_flags"])
        self.assertIn(
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            updated.resolved_keyframes["video_temporal_quality_retry_rejection_flags"],
        )

    async def test_quality_retry_can_partially_merge_clearer_takeoff_when_retry_landing_is_occluded(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.75,
            "key_moments": {"T_takeoff_sec": 6.95, "A_air_sec": 7.65, "L_landing_sec": 8.05},
            "quality_flags": ["video_temporal_not_high_confidence"],
            "validation": {"valid": True, "errors": [], "warnings": ["video_temporal_not_high_confidence"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.85,
            "key_moments": {"T_takeoff_sec": 7.40, "A_air_sec": 7.65, "L_landing_sec": 7.90},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        original_selected = [
            {"frame_id": "semantic_0001", "timestamp": 6.903, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
            {"frame_id": "semantic_0003", "timestamp": 8.037, "phase_code": "landing", "key_moment": "L_landing_sec"},
        ]
        retry_selected = [
            {
                "frame_id": "semantic_0001",
                "timestamp": 7.40,
                "phase_code": "takeoff",
                "key_moment": "T_takeoff_sec",
                "phase_time_start": 7.25,
                "phase_time_end": 7.50,
            },
            {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
            {
                "frame_id": "semantic_0003",
                "timestamp": 7.80,
                "phase_code": "landing",
                "key_moment": "L_landing_sec",
                "semantic_visibility": {"status": "foreground_person_occluded"},
            },
        ]
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes={
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_used",
                    "semantic_keyframe_core_foreground_occlusion_repaired",
                ],
                "selected": original_selected,
                "video_ai": original_video,
            },
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=original_selected,
            quality_flags=[
                "video_temporal_not_high_confidence",
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_core_foreground_occlusion_repaired",
            ],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes={
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion", "semantic_keyframes_unreliable_after_visibility_check"],
                "selected": retry_selected,
                "video_ai": retry_video,
            },
            semantic_frames=[],
            semantic_records=[],
            quality_flags=["video_temporal_quality_retry", "semantic_keyframe_core_foreground_occlusion", "semantic_keyframes_unreliable_after_visibility_check"],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            extracted_records: list[dict[str, object]] = []

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                extracted_records[:] = [dict(record) for record in records]
                paths = []
                copied = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"frame")
                    paths.append(path)
                    copied.append(dict(record))
                return paths, copied

            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=9.568, ai_clip_payload=lambda: {"duration_sec": 4.6})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", fake_extract):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            updated = await retry_video_temporal_if_needed(
                                result=result,
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic",
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                action_type="jump",
                                action_subtype=None,
                                motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                analysis_profile="jump",
                            )

        self.assertIsNot(updated, result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_takeoff_partial_merge_used", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertEqual([record["timestamp"] for record in extracted_records[:3]], [7.40, 7.65, 8.037])
        self.assertEqual(updated.resolved_keyframes["selected"][0]["selection_reason"], "video_temporal_quality_retry_takeoff_partial_merge")
        self.assertEqual(updated.resolved_keyframes["selected"][0]["retry_partial_merge_from_timestamp"], 6.903)
        self.assertEqual(updated.effective_source, "blended")

    async def test_quality_retry_rejects_late_drift_when_original_semantic_frames_are_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 6.7 + index * 0.25, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.55},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.90,
                "key_moments": {"T_takeoff_sec": 7.35, "A_air_sec": 7.85, "L_landing_sec": 8.35},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.35, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.85, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.35, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.75)
        self.assertIn("video_temporal_quality_retry_late_drift_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_late_drift_from_unreliable_but_ordered_original_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            original_paths = []
            retry_paths = []
            original_records = []
            retry_records = []
            original_timestamps = [6.85, 7.25, 7.55]
            retry_timestamps = [7.25, 7.65, 8.15]
            for index, (phase_code, original_timestamp, retry_timestamp) in enumerate(
                zip(("takeoff", "air", "landing"), original_timestamps, retry_timestamps),
                start=1,
            ):
                original_path = semantic_dir / f"original_{index:04d}.jpg"
                retry_path = semantic_dir / f"retry_{index:04d}.jpg"
                original_path.parent.mkdir(parents=True, exist_ok=True)
                original_path.write_bytes(b"semantic")
                retry_path.write_bytes(b"semantic")
                original_paths.append(original_path)
                retry_paths.append(retry_path)
                original_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": original_timestamp, "phase_code": phase_code})
                retry_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": retry_timestamp, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "key_moments": {"T_takeoff_sec": 6.85, "A_air_sec": 7.25, "L_landing_sec": 7.55},
                "quality_flags": ["video_temporal_not_high_confidence"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 7.25, "A_air_sec": 7.65, "L_landing_sec": 8.15},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["semantic_keyframes_unreliable_after_visibility_check"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.85, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.25, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                if records and records[0].get("timestamp") == 6.85:
                    return original_paths, original_records
                return retry_paths, retry_records

            async def fake_refine(_: Path, output_dir: Path, records: list[dict[str, object]], **kwargs: object):
                return records, []

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=fake_refine),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.85)
        self.assertIn("video_temporal_quality_retry_late_drift_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_early_drift_when_original_semantic_frames_are_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 6.7 + index * 0.25, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.55},
                "quality_flags": ["video_temporal_resolver_advisory_fallback_overridden"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.90,
                "key_moments": {"T_takeoff_sec": 6.50, "A_air_sec": 6.90, "L_landing_sec": 7.30},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_advisory_fallback_overridden"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.50, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.90, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.30, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.75)
        self.assertIn("video_temporal_quality_retry_early_drift_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_early_tal_before_later_strong_motion(self) -> None:
        first_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.40,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_low_confidence"],
            "validation": {"valid": False, "errors": [], "warnings": ["manual_review"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.75,
            "key_moments": {"T_takeoff_sec": 6.25, "A_air_sec": 6.85, "L_landing_sec": 7.25},
            "quality_flags": [
                "video_temporal_quality_retry",
                "video_temporal_low_confidence",
                "video_temporal_not_high_confidence",
                "video_temporal_fallback_recommended",
            ],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
        }
        first_resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.40,
            "quality_flags": [
                "video_temporal_resolver_low_video_confidence",
                "video_temporal_resolver_partial_skeleton_fallback",
            ],
            "selected": [{"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"}],
            "video_ai": first_video,
        }
        retry_resolved = {
            "source": "blended",
            "confidence": 0.75,
            "quality_flags": [
                "video_temporal_resolver_advisory_fallback_overridden",
                "video_temporal_resolver_coherent_tal_used",
                "video_temporal_resolver_moderate_confidence_tal_used",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 6.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 6.85, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 7.37, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
            "video_ai": retry_video,
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=first_video,
            resolved_keyframes=first_resolved,
            quality_flags=[*first_video["quality_flags"], *first_resolved["quality_flags"]],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=retry_resolved["selected"],
            quality_flags=[*retry_video["quality_flags"], *retry_resolved["quality_flags"]],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "scores": [0.04] * 47 + [0.103, 0.193, 0.226, 0.217, 0.21, 0.122, 0.25, 0.23, 0.129] + [0.05] * 18,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=9.568, ai_clip_payload=lambda: {"duration_sec": 4.6})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores=motion_scores,
                        analysis_profile="jump",
                    )

        self.assertIs(updated, result)
        self.assertFalse(updated.used_semantic_frames)
        self.assertEqual(updated.resolved_keyframes["selected"][0]["timestamp"], 8.025)
        self.assertIn("video_temporal_quality_retry_later_motion_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_quality_retry_used", updated.resolved_keyframes["quality_flags"])

    async def test_core_foreground_occlusion_rejects_semantic_frames_when_repair_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": []}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.15, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.45, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch(
                        "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                        AsyncMock(return_value=(semantic_paths, records)),
                    ):
                        with patch(
                            "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                            side_effect=[visible, visible, occluded, *([occluded] * 30)],
                        ):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_after_visibility_check", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["semantic_visibility"]["status"], "foreground_person_occluded")

    async def test_pipeline_uses_coherent_fallback_tal_after_resolver_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")

            with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=_validated_coherent_fallback_jump_video(),
                        motion_scores=_glide_out_motion_scores(),
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 6.739, 30.0, False),
                        analysis_profile="jump",
                        video_duration_sec=9.568,
                    )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "blended")
        self.assertEqual(len(result.semantic_frames), 6)
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", result.resolved_keyframes["quality_flags"])
        core = [item for item in result.resolved_keyframes["selected"] if item["phase_code"] in {"takeoff", "air", "landing"}]
        self.assertEqual([item["phase_code"] for item in core], ["takeoff", "air", "landing"])

    async def test_pipeline_keeps_late_motion_conflict_as_sampled_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")

            result = await resolve_semantic_keyframe_pipeline(
                video_path=video_path,
                work_dir=root,
                semantic_frames_dir=root / "semantic_frames",
                video_temporal=_validated_late_motion_conflict_jump_video(),
                motion_scores=_glide_out_motion_scores(),
                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 6.739, 30.0, False),
                analysis_profile="jump",
                video_duration_sec=9.568,
            )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "sampled_frames")
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", result.resolved_keyframes["quality_flags"])

    async def test_pipeline_uses_motion_cluster_fallback_after_ai_motion_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            bio_data = {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(side_effect=lambda _video, _work, records, **_kwargs: (records, []))):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=root / "semantic_frames",
                            video_temporal=_validated_latest_retry_early_main_motion_cluster_video(),
                            motion_scores=_glide_out_motion_scores(),
                            sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 6.739, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=9.568,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "skeleton_fallback")
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["phase_code"] for item in result.resolved_keyframes["selected"][:3]], ["takeoff", "air", "landing"])

    async def test_quality_gate_retry_replaces_rejected_video_temporal_when_second_pass_is_reliable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append(
                    {"frame_id": f"semantic_{index:04d}", "timestamp": 7.2 + index * 0.2, "phase_code": phase_code, "key_moment": f"{phase_code}_moment"}
                )

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.8,
                "key_moments": {"T_takeoff_sec": 6.12, "A_air_sec": 6.45, "L_landing_sec": 6.72},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 7.25, "A_air_sec": 7.6, "L_landing_sec": 7.85},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "video_ai_refined",
                "confidence": 0.8,
                "quality_flags": ["video_temporal_resolver_coherent_tal_motion_conflict_rejected"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.12, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.45, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 6.72, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            accepted = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.6, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.85, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            resolve_mock = patch(
                                "app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes",
                                side_effect=[rejected, accepted],
                            )
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with resolve_mock:
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(accepted["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={
                                                        "selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}],
                                                        "scores": [0.1, 0.2],
                                                    },
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry", result.video_temporal["quality_flags"])
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        retry_kwargs = analyze_mock.await_args_list[1].kwargs
        self.assertIn("retry_context", retry_kwargs)
        retry_context = retry_kwargs["retry_context"]
        self.assertEqual(retry_context["rejected_key_moments"], first_video["key_moments"])
        self.assertIn("retry_instruction_hints", retry_context)
        self.assertIn("resolver_quality_flags", retry_context)
        self.assertEqual(retry_context["top_motion_records"][0]["relation_to_rejected_tal"], "after_rejected_landing")
        self.assertEqual(retry_context["rejected_selected_frames"][0]["phase_code"], "takeoff")

    async def test_quality_gate_retry_runs_for_missing_phase_segments_and_core_tal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 7.1 + index * 0.2, "phase_code": phase_code})

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
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 7.25, "A_air_sec": 7.6, "L_landing_sec": 7.85},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_no_semantic_selection"],
                "selected": [],
                "video_ai": first_video,
            }
            accepted = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.6, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.85, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[rejected, accepted]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(accepted["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_missing_phase_segments", retry_context["retry_reason_flags"])
        self.assertIn("video_temporal_missing_core_tal", retry_context["retry_reason_flags"])
        self.assertIn("video_temporal_resolver_no_semantic_selection", retry_context["retry_reason_flags"])

    async def test_quality_gate_retry_runs_for_non_jump_profile_mismatch_with_no_selected_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, (phase_code, timestamp) in enumerate(
                (("spin_entry", 5.2), ("spin_main", 6.4), ("spin_exit", 7.4)),
                start=1,
            ):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": timestamp, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Axel",
                    "jump_type": "Axel",
                    "confidence": 0.85,
                },
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 4.65, "time_end": 5.5, "key_frame_hint": 5.1, "confidence": 0.85},
                    {"phase_code": "takeoff", "time_start": 5.5, "time_end": 5.8, "key_frame_hint": 5.65, "confidence": 0.85},
                    {"phase_code": "air", "time_start": 5.8, "time_end": 6.1, "key_frame_hint": 5.95, "confidence": 0.85},
                    {"phase_code": "landing", "time_start": 6.1, "time_end": 6.4, "key_frame_hint": 6.25, "confidence": 0.85},
                ],
                "key_moments": {"T_takeoff_sec": 5.65, "A_air_sec": 5.95, "L_landing_sec": 6.25},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.82,
                "action_confirmation": {
                    "action_family": "spin",
                    "confirmed_action": "spin",
                    "jump_type": "",
                    "confidence": 0.86,
                },
                "phase_segments": [
                    {"phase_code": "spin_entry", "time_start": 4.65, "time_end": 5.8, "key_frame_hint": 5.2, "confidence": 0.82},
                    {"phase_code": "spin_main", "time_start": 5.8, "time_end": 7.0, "key_frame_hint": 6.4, "confidence": 0.84},
                    {"phase_code": "spin_exit", "time_start": 7.0, "time_end": 8.2, "key_frame_hint": 7.4, "confidence": 0.80},
                ],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["video_temporal_resolver_no_selected_frames"],
                "selected": [],
                "video_ai": first_video,
            }
            accepted = {
                "source": "video_ai_refined",
                "confidence": 0.82,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.2, "phase_code": "spin_entry", "key_moment": None},
                    {"frame_id": "semantic_0002", "timestamp": 6.4, "phase_code": "spin_main", "key_moment": None},
                    {"frame_id": "semantic_0003", "timestamp": 7.4, "phase_code": "spin_exit", "key_moment": None},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[rejected, accepted]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(accepted["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=_visible_person_candidates(),
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="spin",
                                                    action_subtype=None,
                                                    motion_scores={"selected": []},
                                                    analysis_profile="spin",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry", result.video_temporal["quality_flags"])
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_profile_mismatch_retryable", retry_context["retry_reason_flags"])
        self.assertEqual(retry_context["requested_analysis_profile"], "spin")
        self.assertEqual(retry_context["provider_action_family"], "jump")
        self.assertEqual(retry_context["profile_mismatch"], {"requested": "spin", "provider_action_family": "jump"})
        self.assertTrue(any("spin_entry/spin_main/spin_exit" in hint for hint in retry_context["retry_instruction_hints"]))

    async def test_resolver_uses_detected_source_duration_when_cached_retry_lacks_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.80,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {
                    "action_family": "spin",
                    "confirmed_action": "spin",
                    "confidence": 0.85,
                },
                "phase_segments": [
                    {"phase_code": "spin_entry", "time_start": 5.9, "time_end": 7.1, "key_frame_hint": 6.5, "confidence": 0.8},
                    {"phase_code": "spin_main", "time_start": 7.1, "time_end": 8.5, "key_frame_hint": 7.8, "confidence": 0.65},
                ],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": [],
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", return_value=9.101667):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(side_effect=lambda *args, **kwargs: (args[2], []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(2.0, 10.0, 2.0, 10.0, 16.0, 30.0, False),
                            analysis_profile="spin",
                            video_duration_sec=None,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertNotIn("semantic_frame_extract_failed", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["phase_code"] for item in result.resolved_keyframes["selected"]], ["spin_entry", "spin_main", "spin_exit"])
        self.assertEqual(result.resolved_keyframes["selected"][2]["timestamp"], 8.761)

    async def test_quality_gate_retry_runs_for_retryable_low_confidence_jump_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 6.2 + index * 0.25, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.50,
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 6.25, "time_end": 6.65, "confidence": 0.6},
                    {"phase_code": "air", "time_start": 6.65, "time_end": 7.05, "confidence": 0.5},
                    {"phase_code": "landing", "time_start": 7.05, "time_end": 7.35, "confidence": 0.55},
                ],
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_not_high_confidence"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.50,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": first_video,
            }
            accepted = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.85, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[rejected, accepted]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(accepted["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry", result.video_temporal["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_low_confidence_retryable", retry_context["retry_reason_flags"])
        self.assertEqual(retry_context["rejected_key_moments"], first_video["key_moments"])

    async def test_quality_gate_retry_skips_very_low_confidence_jump_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.20,
                "key_moments": {"T_takeoff_sec": 1.0, "A_air_sec": 1.2, "L_landing_sec": 1.4},
                "quality_flags": ["video_temporal_low_confidence"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.20,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": first_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(return_value=first_video)
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=rejected):
                                    result = await run_semantic_keyframe_pipeline(
                                        video_path=video_path,
                                        work_dir=root,
                                        semantic_frames_dir=root / "semantic_frames",
                                        sampling_metadata=VideoSamplingMetadata(0.15, 4.75, 0.15, 4.75, 16.0, 30.0, False),
                                        action_type="jump",
                                        action_subtype=None,
                                        motion_scores={"selected": []},
                                        analysis_profile="jump",
                                        precheck=False,
                                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 1)
        self.assertNotIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])

    async def test_quality_gate_retry_runs_for_severe_occlusion_low_confidence_above_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.40,
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": ["severe_occlusion", "video_temporal_low_confidence"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.35,
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": ["severe_occlusion", "video_temporal_low_confidence"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.40,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": first_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=rejected):
                                    result = await run_semantic_keyframe_pipeline(
                                        video_path=video_path,
                                        work_dir=root,
                                        semantic_frames_dir=semantic_dir,
                                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                        action_type="jump",
                                        action_subtype=None,
                                        motion_scores={"selected": []},
                                        analysis_profile="jump",
                                        precheck=False,
                                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_low_confidence_retryable", retry_context["retry_reason_flags"])

    async def test_quality_gate_retry_uses_low_confidence_retry_when_tal_is_coherent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, (phase_code, timestamp) in enumerate((("takeoff", 6.75), ("air", 7.05), ("landing", 7.35)), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append(
                    {"frame_id": f"semantic_{index:04d}", "timestamp": timestamp, "phase_code": phase_code, "key_moment": f"{phase_code}_moment"}
                )

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.30,
                "phase_segments": [],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.50,
                "fallback_recommendation": "manual_review",
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 4.65, "time_end": 6.45, "key_frame_hint": 5.65, "confidence": 0.8},
                    {"phase_code": "takeoff", "time_start": 6.45, "time_end": 6.85, "key_frame_hint": 6.65, "confidence": 0.7},
                    {"phase_code": "air", "time_start": 6.85, "time_end": 7.25, "key_frame_hint": 7.05, "confidence": 0.6},
                    {"phase_code": "landing", "time_start": 7.25, "time_end": 7.45, "key_frame_hint": 7.35, "confidence": 0.6},
                    {"phase_code": "glide_out", "time_start": 7.45, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.7},
                ],
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.05, "L_landing_sec": 7.35},
                "quality_flags": [
                    "video_temporal_low_confidence",
                    "video_temporal_not_high_confidence",
                    "video_temporal_fallback_recommended",
                    "video_temporal_quality_retry",
                ],
                "validation": {
                    "valid": False,
                    "errors": [],
                    "warnings": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                },
            }
            first_resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.30,
                "quality_flags": [
                    "video_temporal_resolver_low_video_confidence",
                    "video_temporal_resolver_partial_skeleton_fallback",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "blended",
                "confidence": 0.50,
                "quality_flags": [
                    "video_temporal_resolver_video_fallback_recommended",
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_moderate_confidence_tal_used",
                    "video_temporal_resolver_video_validation_not_clean",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.05, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.35, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(retry_resolved["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "blended")
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_missing_core_tal", retry_context["retry_reason_flags"])
        self.assertIn("video_temporal_resolver_partial_skeleton_fallback", retry_context["retry_reason_flags"])

    async def test_quality_gate_retry_runs_for_partial_skeleton_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

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
                "valid": False,
                "confidence": 0.70,
                "phase_segments": [],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_missing_phase_segments"],
                "validation": {"valid": False, "errors": ["video_temporal_missing_phase_segments"], "warnings": []},
            }
            partial_fallback = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": [
                    "video_temporal_resolver_no_semantic_selection",
                    "video_temporal_resolver_partial_skeleton_fallback",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                ],
                "video_ai": first_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=partial_fallback):
                                    result = await run_semantic_keyframe_pipeline(
                                        video_path=video_path,
                                        work_dir=root,
                                        semantic_frames_dir=semantic_dir,
                                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                        action_type="jump",
                                        action_subtype=None,
                                        motion_scores={"selected": []},
                                        analysis_profile="jump",
                                        precheck=False,
                                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_resolver_partial_skeleton_fallback", retry_context["retry_reason_flags"])

    async def test_partial_core_semantic_candidates_are_extracted_as_diagnostics_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [semantic_dir / "partial_semantic_0001.jpg", semantic_dir / "partial_semantic_0002.jpg"]
            partial_records = [
                {
                    "frame_id": "partial_semantic_0001",
                    "timestamp": 5.9,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.653,
                    "partial_semantic_frame": True,
                    "selection_status": "partial_unreliable",
                },
                {
                    "frame_id": "partial_semantic_0002",
                    "timestamp": 7.525,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.792,
                    "partial_semantic_frame": True,
                    "selection_status": "partial_unreliable",
                },
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "fallback_recommendation": "use_sampled_frames",
                "quality_flags": ["video_temporal_fallback_recommended"],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": [
                    "video_temporal_resolver_partial_skeleton_fallback",
                    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 5.838,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "confidence": 0.42,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 5.9,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "confidence": 0.653,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 7.525,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.792,
                    },
                ],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual([item["key_moment"] for item in records], ["A_air_sec", "L_landing_sec"])
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                        analysis_profile="jump",
                        video_duration_sec=9.568,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(result.semantic_records, [])
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertEqual(result.resolved_keyframes["partial_selected"], partial_records)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_partial_core_diagnostics_merge_missing_video_temporal_tal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [
                semantic_dir / "partial_semantic_0001.jpg",
                semantic_dir / "partial_semantic_0002.jpg",
                semantic_dir / "partial_semantic_0003.jpg",
            ]
            partial_records = [
                {"frame_id": f"partial_semantic_{index:04d}", **record}
                for index, record in enumerate(
                    (
                        {"timestamp": 6.65, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.5},
                        {"timestamp": 5.9, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.653},
                        {"timestamp": 7.525, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.792},
                    ),
                    start=1,
                )
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "use_sampled_frames",
                "quality_flags": ["video_temporal_low_confidence"],
                "key_moments": {"T_takeoff_sec": 6.65, "A_air_sec": 7.05, "L_landing_sec": 7.45},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.45, "time_end": 6.85, "confidence": 0.5},
                    {"phase_code": "air", "phase_label": "air", "time_start": 6.85, "time_end": 7.25, "confidence": 0.4},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.65, "confidence": 0.5},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": [
                    "video_temporal_resolver_low_video_confidence",
                    "video_temporal_resolver_partial_skeleton_fallback",
                ],
                "selected": [
                    {"timestamp": 5.9, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.653},
                    {"timestamp": 7.525, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.792},
                ],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual([item["key_moment"] for item in records], ["T_takeoff_sec", "A_air_sec", "L_landing_sec"])
                self.assertEqual([item["timestamp"] for item in records], [6.65, 5.9, 7.525])
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                        analysis_profile="jump",
                        video_duration_sec=9.568,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_low_confidence_video_temporal_tal_extracts_partial_diagnostic_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [
                semantic_dir / "partial_semantic_0001.jpg",
                semantic_dir / "partial_semantic_0002.jpg",
                semantic_dir / "partial_semantic_0003.jpg",
            ]
            partial_records = [
                {"frame_id": f"partial_semantic_{index:04d}", **record}
                for index, record in enumerate(
                    (
                        {"timestamp": 4.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.2},
                        {"timestamp": 5.15, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.2},
                        {"timestamp": 5.65, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.2},
                    ),
                    start=1,
                )
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.2,
                "fallback_recommendation": "manual_review",
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 4.45, "A_air_sec": 5.15, "L_landing_sec": 5.65},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 4.15, "time_end": 4.85, "confidence": 0.2},
                    {"phase_code": "air", "phase_label": "air", "time_start": 4.85, "time_end": 5.45, "confidence": 0.2},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 5.45, "time_end": 5.95, "confidence": 0.2},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.2,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual([item["key_moment"] for item in records], ["T_takeoff_sec", "A_air_sec", "L_landing_sec"])
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(2.65, 7.25, 2.65, 7.25, 6.739, 30.0, False),
                        analysis_profile="jump",
                        video_duration_sec=8.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertEqual(result.resolved_keyframes["partial_selected"], partial_records)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_low_confidence_jump_partial_tal_promotes_when_visual_check_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "blended")
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertEqual(result.partial_semantic_frames, [])
        self.assertNotIn("partial_selected", result.resolved_keyframes)
        self.assertIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_advisory_low_confidence_overridden", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_low_confidence_zoomed_visual_check", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_low_confidence_visual_tal_promoted"] * 3,
        )
        self.assertEqual(
            [item["semantic_visibility"]["status"] for item in result.resolved_keyframes["selected"]],
            ["target_visible"] * 3,
        )

    async def test_low_confidence_jump_partial_tal_promotes_when_zoomed_visual_check_finds_small_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }

            def fake_candidates(_: Path, *, min_confidence: float = 0.25, include_zoomed_small_targets: bool = False):
                self.assertEqual(min_confidence, 0.25)
                if not include_zoomed_small_targets:
                    return []
                return [
                    {
                        "bbox": {"x": 0.45, "y": 0.49, "width": 0.034, "height": 0.10},
                        "confidence": 0.52,
                        "source": "yolo_zoomed_content",
                        "area": 0.0034,
                    }
                ]

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertEqual(
            [item["semantic_visibility"]["visibility_check_method"] for item in result.resolved_keyframes["selected"]],
            ["zoomed_yolo"] * 3,
        )
        self.assertIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_low_confidence_jump_partial_tal_repairs_nearby_zoomed_visible_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }
            inspected_names: list[str] = []
            repair_detected = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied = []
                for index, record in enumerate(records, start=1):
                    frame_id = f"{prefix}_{index:04d}"
                    if prefix == "repair":
                        frame_id = f"{prefix}_{index:04d}_{int(float(record['timestamp']) * 1000):08d}"
                    path = output_dir / f"{frame_id}.jpg"
                    path.write_bytes(b"frame")
                    paths.append(path)
                    copied.append({**record, "frame_id": frame_id})
                return paths, copied

            def fake_candidates(frame_path: Path, *, min_confidence: float = 0.25, include_zoomed_small_targets: bool = False):
                nonlocal repair_detected
                inspected_names.append(frame_path.name)
                if not include_zoomed_small_targets:
                    return []
                if frame_path.name.startswith("repair_"):
                    repair_detected = True
                    return _visible_person_candidates()
                if frame_path.name in {"semantic_0001.jpg", "semantic_0002.jpg"} or (
                    frame_path.name == "semantic_0003.jpg" and repair_detected
                ):
                    return _visible_person_candidates()
                return []

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("video_temporal_resolver_low_confidence_visual_repair_used", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["frame_id"], "semantic_0003")
        self.assertEqual(landing["semantic_visibility"]["status"], "target_visible")
        self.assertEqual(landing["visual_repair_method"], "nearby_zoomed_yolo_visible_frame")
        self.assertIn("semantic_0003.jpg", inspected_names)
        self.assertTrue(any(name.startswith("repair_") for name in inspected_names))

    async def test_low_confidence_jump_partial_tal_stays_partial_when_no_visual_target_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=[]):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(len(result.partial_semantic_frames), 3)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_low_confidence_jump_partial_tal_stays_partial_when_visual_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=occluded):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(len(result.partial_semantic_frames), 3)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_non_jump_profile_mismatch_extracts_partial_phase_diagnostics_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [semantic_dir / "partial_semantic_0001.jpg"]
            partial_records = [
                {
                    "frame_id": "partial_semantic_0001",
                    "timestamp": 3.5,
                    "phase_code": "step_sequence",
                    "confidence": 0.9,
                    "partial_semantic_frame": True,
                    "selection_status": "partial_unreliable",
                    "selection_reason": "video_temporal_profile_mismatch_partial_phase",
                }
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {
                    "action_family": "step",
                    "confirmed_action": "step_sequence",
                    "confidence": 0.9,
                },
                "phase_segments": [
                    {
                        "phase_code": "step_sequence",
                        "phase_label": "step sequence",
                        "time_start": 0.5,
                        "time_end": 7.7,
                        "key_frame_hint": 3.5,
                        "confidence": 0.9,
                    }
                ],
                "quality_flags": [],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.85,
                "quality_flags": [
                    "video_temporal_profile_mismatch_retryable",
                    "video_temporal_resolver_no_selected_frames",
                ],
                "selected": [],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["phase_code"], "step_sequence")
                self.assertEqual(records[0]["selection_reason"], "video_temporal_profile_mismatch_partial_phase")
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                        analysis_profile="spiral",
                        video_duration_sec=8.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertEqual(result.resolved_keyframes["partial_selected"], partial_records)
        self.assertIn("semantic_keyframes_partial_profile_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_non_jump_provider_jump_mismatch_extracts_partial_action_frames_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [
                semantic_dir / "partial_semantic_0001.jpg",
                semantic_dir / "partial_semantic_0002.jpg",
                semantic_dir / "partial_semantic_0003.jpg",
            ]
            partial_records = [
                {
                    "frame_id": f"partial_semantic_{index:04d}",
                    "timestamp": timestamp,
                    "phase_code": phase_code,
                    "confidence": 0.9,
                    "partial_semantic_frame": True,
                    "selection_status": "partial_unreliable",
                    "selection_reason": "video_temporal_profile_mismatch_partial_action_phase",
                    "requested_profile": "spin",
                    "provider_action_family": "jump",
                }
                for index, (timestamp, phase_code) in enumerate(
                    [(1.2, "takeoff"), (1.5, "air"), (1.9, "landing")],
                    start=1,
                )
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Axel",
                    "confidence": 0.9,
                },
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 1.0, "time_end": 1.3, "key_frame_hint": 1.2, "confidence": 0.9},
                    {"phase_code": "air", "time_start": 1.3, "time_end": 1.7, "key_frame_hint": 1.5, "confidence": 0.9},
                    {"phase_code": "landing", "time_start": 1.7, "time_end": 2.0, "key_frame_hint": 1.9, "confidence": 0.9},
                ],
                "quality_flags": [],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.85,
                "quality_flags": [
                    "video_temporal_profile_mismatch_retryable",
                    "video_temporal_resolver_no_selected_frames",
                ],
                "selected": [],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual([record["phase_code"] for record in records], ["takeoff", "air", "landing"])
                self.assertEqual(
                    [record["selection_reason"] for record in records],
                    ["video_temporal_profile_mismatch_partial_action_phase"] * 3,
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 3.0, 0.0, 3.0, 16.0, 30.0, False),
                        analysis_profile="spin",
                        video_duration_sec=3.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertEqual(result.resolved_keyframes["partial_selected"], partial_records)
        self.assertNotIn("semantic_keyframes_partial_profile_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_partial_mismatch_action_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
