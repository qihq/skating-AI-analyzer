from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services.action_profiles import infer_profile_from_input
from app.services.video import (
    detect_action_window,
    extract_motion_sampled_frames,
    get_frame_rate_for_profile,
    get_max_frames_for_profile,
    get_slow_motion_scale,
)


class AnalysisProfileInputTests(unittest.IsolatedAsyncioTestCase):
    def test_infer_profile_from_axel_input_returns_jump(self) -> None:
        self.assertEqual(infer_profile_from_input("Ã¨Â·Â³Ã¨Â·Æ’", "Axel Ã¨Â·Â³Ã¨Â·Æ’"), "jump")

    def test_profile_sampling_configuration_prefers_jump_over_defaults(self) -> None:
        self.assertEqual(get_frame_rate_for_profile("jump"), 10)
        self.assertEqual(get_max_frames_for_profile("jump"), 15)
        self.assertEqual(get_frame_rate_for_profile("unknown"), 5)

    def test_get_slow_motion_scale_maps_240fps_to_8x(self) -> None:
        self.assertEqual(get_slow_motion_scale(240.0), 8.0)
        self.assertEqual(get_slow_motion_scale(30.0), 1.0)

    async def test_detect_action_window_expands_jump_window_for_slow_motion_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake")

            thumb_paths = [root / f"thumb_{index:05d}.jpg" for index in range(1, 121)]
            motion_scores = [0.0] * 120
            for index in range(16, 64):
                motion_scores[index] = 1.0

            with (
                patch("app.services.video._extract_action_thumbnails", AsyncMock(return_value=thumb_paths)),
                patch("app.services.video._motion_scores_from_thumbs", return_value=motion_scores),
            ):
                start_sec, end_sec = await detect_action_window(
                    video_path=video_path,
                    action_type="ÃƒÂ¨Ã‚Â·Ã‚Â³ÃƒÂ¨Ã‚Â·Ã†â€™",
                    source_fps=240.0,
                    analysis_profile="jump",
                )

        self.assertLessEqual(start_sec, 8.0)
        self.assertGreaterEqual(end_sec, 30.0)
        self.assertGreater(end_sec - start_sec, 20.0)

    async def test_jump_profile_uses_jump_frame_rate_during_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake")
            frames_dir = root / "frames"
            frames_dir.mkdir()
            thumbs_dir = root / "thumbs"
            thumb_paths = [thumbs_dir / f"thumb_{index:05d}.jpg" for index in range(1, 19)]
            extracted_timestamps: list[float] = []

            async def fake_extract_thumbnails_in_window(
                _video_path: Path,
                _thumbs_dir: Path,
                _start_sec: float,
                _end_sec: float,
                frame_rate: int = 5,
            ) -> list[Path]:
                self.assertEqual(frame_rate, 10)
                _thumbs_dir.mkdir(parents=True, exist_ok=True)
                for thumb_path in thumb_paths:
                    thumb_path.write_bytes(b"thumb")
                return thumb_paths

            async def fake_extract_full_frame_at(_video_path: Path, _timestamp: float, target_path: Path) -> None:
                extracted_timestamps.append(round(_timestamp, 3))
                target_path.write_bytes(b"frame")

            with (
                patch("app.services.video.detect_video_fps", return_value=30.0),
                patch("app.services.video.detect_action_window", AsyncMock(return_value=(0.0, 2.0))),
                patch("app.services.video._extract_thumbnails_in_window", side_effect=fake_extract_thumbnails_in_window),
                patch("app.services.video._motion_scores_from_thumbs", return_value=[float(index) for index in range(len(thumb_paths))]),
                patch("app.services.video._extract_full_frame_at", side_effect=fake_extract_full_frame_at),
            ):
                sampled_frames, motion_payload, sampling_metadata = await extract_motion_sampled_frames(
                    video_path=video_path,
                    frames_dir=frames_dir,
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                    analysis_profile="jump",
                )

        self.assertEqual(motion_payload["analysis_profile_hint"], "jump")
        self.assertEqual(motion_payload["frame_rate"], 10)
        self.assertEqual(motion_payload["max_frames_for_profile"], 15)
        self.assertEqual(len(sampled_frames), 15)
        self.assertIn(0.1, extracted_timestamps)
        self.assertIn(1.7, extracted_timestamps)
        self.assertTrue(all(abs(timestamp * 10 - round(timestamp * 10)) < 1e-9 for timestamp in extracted_timestamps))
        self.assertEqual(sampling_metadata.action_window_start, 0.0)
        self.assertEqual(sampling_metadata.action_window_end, 2.0)

    async def test_slow_motion_sampling_spreads_timestamps_across_full_action_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake")
            frames_dir = root / "frames"
            frames_dir.mkdir()
            thumbs_dir = root / "thumbs"
            thumb_paths = [thumbs_dir / f"thumb_{index:05d}.jpg" for index in range(1, 241)]
            extracted_timestamps: list[float] = []

            async def fake_extract_thumbnails_in_window(
                _video_path: Path,
                _thumbs_dir: Path,
                _start_sec: float,
                _end_sec: float,
                frame_rate: int = 5,
            ) -> list[Path]:
                self.assertEqual((_start_sec, _end_sec), (0.0, 24.0))
                self.assertEqual(frame_rate, 10)
                _thumbs_dir.mkdir(parents=True, exist_ok=True)
                for thumb_path in thumb_paths:
                    thumb_path.write_bytes(b"thumb")
                return thumb_paths

            async def fake_extract_full_frame_at(_video_path: Path, _timestamp: float, target_path: Path) -> None:
                extracted_timestamps.append(round(_timestamp, 3))
                target_path.write_bytes(b"frame")

            motion_scores = [0.1 + (index / 1000.0) for index in range(len(thumb_paths))]

            with (
                patch("app.services.video.detect_video_fps", return_value=240.0),
                patch("app.services.video.detect_action_window", AsyncMock(return_value=(0.0, 24.0))),
                patch("app.services.video._extract_thumbnails_in_window", side_effect=fake_extract_thumbnails_in_window),
                patch("app.services.video._motion_scores_from_thumbs", return_value=motion_scores),
                patch("app.services.video._extract_full_frame_at", side_effect=fake_extract_full_frame_at),
            ):
                sampled_frames, motion_payload, sampling_metadata = await extract_motion_sampled_frames(
                    video_path=video_path,
                    frames_dir=frames_dir,
                    action_type="ÃƒÂ¨Ã‚Â·Ã‚Â³ÃƒÂ¨Ã‚Â·Ã†â€™",
                    analysis_profile="jump",
                )

        self.assertEqual(len(sampled_frames), 15)
        self.assertEqual(motion_payload["slow_motion_scale"], 8.0)
        self.assertEqual(motion_payload["effective_window_duration"], 3.0)
        self.assertTrue(sampling_metadata.is_slow_motion)
        self.assertLess(min(extracted_timestamps), 4.0)
        self.assertTrue(any(8.0 <= timestamp <= 16.0 for timestamp in extracted_timestamps))
        self.assertGreater(max(extracted_timestamps), 20.0)
        self.assertGreater(max(extracted_timestamps) - min(extracted_timestamps), 20.0)


if __name__ == "__main__":
    unittest.main()
