from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.video import build_timestamp_map, encode_frames, filter_frames


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
        self.assertEqual([payload.timestamp_sec for payload in payloads], [0.0, 0.0, 0.0])

    async def test_encode_frames_applies_timestamp_map_by_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            frame_path = root / "frame_0001.jpg"
            frame_path.write_bytes(b"frame-1")

            with patch("app.services.video.is_blurry", return_value=False):
                payloads = await encode_frames([frame_path], timestamps={"frame_0001": 1.4})

        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0].frame_id, "frame_0001")
        self.assertEqual(payloads[0].timestamp_sec, 1.4)

    def test_build_timestamp_map_extracts_selected_frame_timestamps(self) -> None:
        payload = {
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 1.4},
                {"frame_id": "frame_0002", "timestamp": 2},
                {"frame_id": "frame_0003", "timestamp": "bad"},
                {"timestamp": 3.0},
                "bad",
            ]
        }

        self.assertEqual(build_timestamp_map(payload), {"frame_0001": 1.4, "frame_0002": 2.0})

    def test_build_timestamp_map_returns_empty_for_invalid_payloads(self) -> None:
        self.assertEqual(build_timestamp_map(None), {})
        self.assertEqual(build_timestamp_map({}), {})
        self.assertEqual(build_timestamp_map({"selected": "not a list"}), {})


if __name__ == "__main__":
    unittest.main()
