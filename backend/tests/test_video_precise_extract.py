from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.services.video import build_timestamp_map, extract_precise_frames_at_timestamps


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


if __name__ == "__main__":
    unittest.main()
