from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.video import precheck_video


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True, check=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe are required")
class VideoPrecheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_precheck_rejects_damaged_mp4_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "damaged.mp4"
            video_path.write_bytes(b"not-a-real-mp4")

            with self.assertRaises(AnalysisPipelineError) as raised:
                await precheck_video(video_path)

        self.assertEqual(raised.exception.code, AnalysisErrorCode.VIDEO_FORMAT_INVALID)

    async def test_precheck_rejects_empty_mp4_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "empty.mp4"
            video_path.write_bytes(b"")

            with self.assertRaises(AnalysisPipelineError) as raised:
                await precheck_video(video_path)

        self.assertEqual(raised.exception.code, AnalysisErrorCode.VIDEO_FORMAT_INVALID)

    async def test_precheck_rejects_video_without_video_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "audio_only.mp4"
            _run_ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:duration=1",
                    "-c:a",
                    "aac",
                    str(video_path),
                ]
            )

            with self.assertRaises(AnalysisPipelineError) as raised:
                await precheck_video(video_path)

        self.assertEqual(raised.exception.code, AnalysisErrorCode.VIDEO_NO_VIDEO_STREAM)

    async def test_precheck_rejects_black_video_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "black.mp4"
            _run_ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=320x180:d=1",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ]
            )

            with self.assertRaises(AnalysisPipelineError) as raised:
                await precheck_video(video_path)

        self.assertEqual(raised.exception.code, AnalysisErrorCode.VIDEO_BLANK_FRAMES)


if __name__ == "__main__":
    unittest.main()
