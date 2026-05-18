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


if __name__ == "__main__":
    unittest.main()
