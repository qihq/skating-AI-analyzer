from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services.video import build_timestamp_map, extract_precise_frames_at_timestamps, refine_semantic_keyframe_timestamps


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@unittest.skipUnless(_ffmpeg_available(), "ffmpeg/ffprobe is required for synthetic precise extraction test")
class VideoPreciseExtractTests(unittest.IsolatedAsyncioTestCase):
    async def test_extract_precise_frames_outputs_stable_names_and_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            frames_dir = root / "frames"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=2:size=320x240:rate=10",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            frame_paths, records = await extract_precise_frames_at_timestamps(
                video_path,
                frames_dir,
                [
                    {
                        "timestamp": 0.25,
                        "phase_code": "takeoff",
                        "phase_label": "起跳",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_motion_peak",
                    },
                    {
                        "timestamp": 1.2,
                        "phase_code": "landing",
                        "phase_label": "落冰",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_hint",
                    },
                ],
            )

            self.assertEqual([path.name for path in frame_paths], ["semantic_0001.jpg", "semantic_0002.jpg"])
            self.assertTrue(all(path.exists() and path.stat().st_size > 0 for path in frame_paths))
            self.assertEqual([record["frame_id"] for record in records], ["semantic_0001", "semantic_0002"])
            self.assertEqual([record["timestamp"] for record in records], [0.25, 1.2])
            self.assertEqual(
                build_timestamp_map({"selected": records}),
                {"semantic_0001": 0.25, "semantic_0002": 1.2},
            )

    async def test_refine_semantic_keyframe_timestamps_preserves_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {"timestamp": 1.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"timestamp": 1.4, "phase_code": "air", "key_moment": "A_air_sec"},
                {"timestamp": 1.8, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(1.08, 60.0, 0.9), (1.72, 60.0, 0.8)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=120.0,
                    video_duration_sec=2.0,
                )

        self.assertEqual(flags, [])
        self.assertEqual([item["timestamp"] for item in refined], [1.08, 1.4, 1.72])
        self.assertEqual(refined[0]["pre_refine_timestamp"], 1.0)
        self.assertEqual(refined[0]["refinement_method"], "local_motion_peak")
        self.assertEqual(refined[0]["refinement_delta_sec"], 0.08)
        self.assertEqual(refined[1]["refinement_method"], "apex_preserved")
        self.assertEqual(refined[1]["refinement_delta_sec"], 0.0)

    async def test_refinement_failure_preserves_original_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [{"timestamp": 1.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"}]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=RuntimeError("ffmpeg failed"))):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=2.0,
                )

        self.assertEqual(refined[0]["timestamp"], 1.0)
        self.assertEqual(refined[0]["refinement_method"], "refinement_failed_preserved")
        self.assertIn("semantic_keyframe_refinement_failed", flags)

    async def test_refinement_rejects_motion_peak_that_breaks_tal_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {"timestamp": 3.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"timestamp": 4.1, "phase_code": "air", "key_moment": "A_air_sec"},
                {"timestamp": 4.2, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(3.08, 30.0, 0.7), (4.04, 30.0, 0.9)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=5.0,
                )

        self.assertEqual([item["timestamp"] for item in refined], [3.08, 4.1, 4.2])
        self.assertEqual(refined[2]["refinement_method"], "local_motion_peak_order_rejected")
        self.assertIn("semantic_keyframe_refinement_order_rejected", flags)

    async def test_refinement_rejects_motion_peak_outside_phase_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {"timestamp": 7.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 6.85, "phase_time_end": 7.15},
                {"timestamp": 7.3, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.15, "phase_time_end": 7.45},
                {"timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec", "phase_time_start": 7.35, "phase_time_end": 7.65},
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(6.95, 30.0, 0.6), (7.8, 30.0, 0.9)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=9.0,
                )

        self.assertEqual([item["timestamp"] for item in refined], [6.95, 7.3, 7.55])
        self.assertEqual(refined[2]["refinement_method"], "local_motion_peak_phase_rejected")
        self.assertIn("semantic_keyframe_refinement_phase_rejected", flags)

    async def test_landing_refinement_allows_configured_phase_end_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {"timestamp": 7.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 6.85, "phase_time_end": 7.15},
                {"timestamp": 7.3, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.15, "phase_time_end": 7.45},
                {
                    "timestamp": 7.55,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "phase_time_start": 7.35,
                    "phase_time_end": 7.65,
                    "max_refinement_delta_sec": 0.30,
                    "phase_time_end_refinement_tolerance_sec": 0.22,
                    "refinement_window_seconds": 0.30,
                },
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(6.95, 30.0, 0.6), (7.703, 30.0, 0.9)])) as refine_mock:
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=9.0,
                    window_seconds=0.18,
                )

        self.assertEqual([item["timestamp"] for item in refined], [6.95, 7.3, 7.703])
        self.assertEqual(refined[2]["refinement_method"], "local_motion_peak")
        self.assertTrue(refined[2]["refinement_phase_end_tolerance_used"])
        self.assertIn("semantic_keyframe_refinement_phase_end_tolerance_used", flags)
        self.assertEqual(refine_mock.await_args_list[0].kwargs["window_seconds"], 0.18)
        self.assertEqual(refine_mock.await_args_list[1].kwargs["window_seconds"], 0.30)

    async def test_landing_refinement_allows_configured_phase_start_tolerance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {"timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 7.15, "phase_time_end": 7.65},
                {"timestamp": 7.85, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.65, "phase_time_end": 8.15},
                {
                    "timestamp": 8.25,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "phase_time_start": 8.15,
                    "phase_time_end": 8.45,
                    "max_refinement_delta_sec": 0.30,
                    "phase_time_start_refinement_tolerance_sec": 0.22,
                    "refinement_window_seconds": 0.30,
                },
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(7.45, 30.0, 0.6), (8.017, 30.0, 0.9)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=9.0,
                )

        self.assertEqual([item["timestamp"] for item in refined], [7.45, 7.85, 8.017])
        self.assertEqual(refined[2]["refinement_method"], "local_motion_peak")
        self.assertTrue(refined[2]["refinement_phase_start_tolerance_used"])
        self.assertIn("semantic_keyframe_refinement_phase_start_tolerance_used", flags)

    async def test_refinement_rejects_large_motion_peak_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {"timestamp": 7.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 6.8, "phase_time_end": 7.2},
                {"timestamp": 7.3, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.2, "phase_time_end": 7.4},
                {"timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec", "phase_time_start": 7.4, "phase_time_end": 7.8},
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(6.91, 30.0, 0.6), (7.703, 30.0, 0.9)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=9.0,
                )

        self.assertEqual([item["timestamp"] for item in refined], [6.91, 7.3, 7.55])
        self.assertEqual(refined[2]["refinement_method"], "local_motion_peak_delta_rejected")
        self.assertEqual(refined[2]["refinement_candidate_timestamp"], 7.703)
        self.assertEqual(refined[2]["refinement_candidate_delta_sec"], 0.153)
        self.assertEqual(refined[2]["refinement_reject_reason"], "delta")
        self.assertIn("semantic_keyframe_refinement_delta_rejected", flags)

    async def test_jump_takeoff_refinement_can_use_configured_delta_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {
                    "timestamp": 7.2,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "phase_time_start": 7.1,
                    "phase_time_end": 7.4,
                    "max_refinement_delta_sec": 0.20,
                },
                {"timestamp": 7.55, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.4, "phase_time_end": 7.7},
                {"timestamp": 7.8, "phase_code": "landing", "key_moment": "L_landing_sec", "phase_time_start": 7.7, "phase_time_end": 8.0},
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(7.353, 30.0, 0.0274), (7.787, 30.0, 0.1557)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=9.568,
                )

        self.assertEqual(refined[0]["timestamp"], 7.353)
        self.assertEqual(refined[0]["refinement_method"], "local_motion_peak")
        self.assertEqual(refined[0]["refinement_delta_sec"], 0.153)
        self.assertNotIn("semantic_keyframe_refinement_delta_rejected", flags)

    async def test_jump_takeoff_refinement_delta_expansion_still_has_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {
                    "timestamp": 7.2,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "phase_time_start": 7.1,
                    "phase_time_end": 7.4,
                    "max_refinement_delta_sec": 0.20,
                },
                {"timestamp": 7.55, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.4, "phase_time_end": 7.7},
                {"timestamp": 7.8, "phase_code": "landing", "key_moment": "L_landing_sec", "phase_time_start": 7.7, "phase_time_end": 8.0},
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(7.41, 30.0, 0.04), (7.787, 30.0, 0.1557)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=9.568,
                )

        self.assertEqual(refined[0]["timestamp"], 7.2)
        self.assertEqual(refined[0]["refinement_method"], "local_motion_peak_phase_rejected")
        self.assertEqual(refined[0]["refinement_candidate_timestamp"], 7.41)
        self.assertIn("semantic_keyframe_refinement_phase_rejected", flags)

    async def test_jump_takeoff_refinement_can_reject_large_backward_shift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {
                    "timestamp": 7.15,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "phase_time_start": 6.95,
                    "phase_time_end": 7.35,
                    "max_refinement_delta_sec": 0.20,
                    "max_refinement_backward_delta_sec": 0.08,
                },
                {"timestamp": 7.55, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.35, "phase_time_end": 7.75},
                {"timestamp": 7.8, "phase_code": "landing", "key_moment": "L_landing_sec", "phase_time_start": 7.7, "phase_time_end": 8.0},
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(7.003, 30.0, 0.05), (7.787, 30.0, 0.1557)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=9.568,
                )

        self.assertEqual(refined[0]["timestamp"], 7.15)
        self.assertEqual(refined[0]["refinement_method"], "local_motion_peak_backward_delta_rejected")
        self.assertEqual(refined[0]["refinement_candidate_timestamp"], 7.003)
        self.assertIn("semantic_keyframe_refinement_backward_delta_rejected", flags)

    async def test_landing_refinement_tolerance_keeps_delta_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "synthetic.mp4"
            video_path.write_bytes(b"fake")
            records = [
                {"timestamp": 7.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 6.85, "phase_time_end": 7.15},
                {"timestamp": 7.3, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.15, "phase_time_end": 7.45},
                {
                    "timestamp": 7.45,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "phase_time_start": 7.32,
                    "phase_time_end": 7.58,
                    "max_refinement_delta_sec": 0.20,
                    "phase_time_end_refinement_tolerance_sec": 0.22,
                    "refinement_window_seconds": 0.30,
                },
            ]

            with patch("app.services.video._refine_motion_peak_timestamp", AsyncMock(side_effect=[(6.95, 30.0, 0.6), (7.703, 30.0, 0.9)])):
                refined, flags = await refine_semantic_keyframe_timestamps(
                    video_path,
                    root / "work",
                    records,
                    source_fps=30.0,
                    video_duration_sec=9.0,
                )

        self.assertEqual([item["timestamp"] for item in refined], [6.95, 7.3, 7.45])
        self.assertEqual(refined[2]["refinement_method"], "local_motion_peak_delta_rejected")
        self.assertIn("semantic_keyframe_refinement_delta_rejected", flags)


if __name__ == "__main__":
    unittest.main()
