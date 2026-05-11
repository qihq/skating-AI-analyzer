from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.video import encode_frames, filter_frames


class VideoBlurFilterTests(unittest.IsolatedAsyncioTestCase):
    def test_filter_frames_falls_back_to_first_three_when_too_many_are_blurry(self) -> None:
        frame_paths = [Path(f"frame_{index:04d}.jpg") for index in range(1, 6)]
        blurry_frames = {frame_paths[0], frame_paths[2], frame_paths[3], frame_paths[4]}

        with patch("app.services.video.is_blurry", side_effect=lambda path: path in blurry_frames):
            filtered = filter_frames(frame_paths)

        self.assertEqual(filtered, frame_paths[:3])

    async def test_encode_frames_skips_blurry_frames_before_payload_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            frame_paths = []
            for index in range(1, 6):
                frame_path = root / f"frame_{index:04d}.jpg"
                frame_path.write_bytes(f"frame-{index}".encode("utf-8"))
                frame_paths.append(frame_path)

            blurry_frames = {frame_paths[1], frame_paths[3]}
            with patch("app.services.video.is_blurry", side_effect=lambda path: path in blurry_frames):
                payloads = await encode_frames(frame_paths)

        self.assertEqual([payload.frame_id for payload in payloads], ["frame_0001", "frame_0003", "frame_0005"])


if __name__ == "__main__":
    unittest.main()
