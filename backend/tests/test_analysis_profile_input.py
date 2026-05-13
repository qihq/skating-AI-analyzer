from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.action_profiles import infer_profile_from_input
from app.services.video import (
    _select_motion_weighted_indices,
    detect_action_window,
    extract_motion_sampled_frames,
    get_frame_rate_for_profile,
    get_max_frames_for_profile,
    get_slow_motion_scale,
    get_window_seconds_for_profile,
)


class AnalysisProfileInputTests(unittest.IsolatedAsyncioTestCase):
    def test_infer_profile_from_axel_input_returns_jump(self) -> None:
        self.assertEqual(infer_profile_from_input("è·³è·ƒ", "Axel è·³è·ƒ"), "jump")

    def test_profile_sampling_configuration_prefers_jump_over_defaults(self) -> None:
        self.assertEqual(get_frame_rate_for_profile("jump"), 12)
        self.assertEqual(get_max_frames_for_profile("jump"), 32)
        self.assertEqual(get_window_seconds_for_profile("jump", "跳跃"), 3.0)
        self.assertEqual(get_max_frames_for_profile("spin"), 24)
        self.assertEqual(get_max_frames_for_profile("spiral"), 16)
        self.assertEqual(get_frame_rate_for_profile("unknown"), 5)

    def test_motion_sampling_protects_top_two_peak_neighborhoods(self) -> None:
        scores = [0.05] * 40
        scores[10] = 1.0
        scores[28] = 0.9

        selected = _select_motion_weighted_indices(scores, sample_count=12)

        self.assertTrue({9, 10, 11}.issubset(selected))
        self.assertTrue({27, 28, 29}.issubset(selected))
        self.assertEqual(len(selected), 12)
        self.assertEqual(selected, sorted(selected))

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
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
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
            thumb_paths = [thumbs_dir / f"thumb_{index:05d}.jpg" for index in range(1, 49)]
            extracted_timestamps: list[float] = []

            async def fake_extract_thumbnails_in_window(
                _video_path: Path,
                _thumbs_dir: Path,
                _start_sec: float,
                _end_sec: float,
                frame_rate: int = 5,
            ) -> list[Path]:
                self.assertEqual(frame_rate, 12)
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
                    action_type="è·³è·ƒ",
                    analysis_profile="jump",
                )

        self.assertEqual(motion_payload["analysis_profile_hint"], "jump")
        self.assertEqual(motion_payload["frame_rate"], 12)
        self.assertEqual(motion_payload["max_frames_for_profile"], 32)
        self.assertEqual(len(sampled_frames), 32)
        self.assertIn(0.0, extracted_timestamps)
        self.assertIn(round(47 / 12, 3), extracted_timestamps)
        self.assertTrue(all(abs(timestamp * 12 - round(timestamp * 12)) < 0.01 for timestamp in extracted_timestamps))
        self.assertEqual(sampling_metadata.action_window_start, 0.0)
        self.assertEqual(sampling_metadata.action_window_end, 2.0)
        self.assertEqual(sampling_metadata.window_start_sec, 0.0)
        self.assertEqual(sampling_metadata.window_end_sec, 2.0)
        self.assertAlmostEqual(sampling_metadata.effective_fps, 15.5, places=2)

    async def test_slow_motion_sampling_spreads_timestamps_across_full_action_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake")
            frames_dir = root / "frames"
            frames_dir.mkdir()
            thumbs_dir = root / "thumbs"
            thumb_paths = [thumbs_dir / f"thumb_{index:05d}.jpg" for index in range(1, 289)]
            extracted_timestamps: list[float] = []

            async def fake_extract_thumbnails_in_window(
                _video_path: Path,
                _thumbs_dir: Path,
                _start_sec: float,
                _end_sec: float,
                frame_rate: int = 5,
            ) -> list[Path]:
                self.assertEqual((_start_sec, _end_sec), (0.0, 24.0))
                self.assertEqual(frame_rate, 12)
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
                    action_type="Ã¨Â·Â³Ã¨Â·Æ’",
                    analysis_profile="jump",
                )

        self.assertEqual(len(sampled_frames), 32)
        self.assertEqual(motion_payload["slow_motion_scale"], 8.0)
        self.assertEqual(motion_payload["effective_window_duration"], 3.0)
        self.assertEqual(motion_payload["window_start_sec"], 0.0)
        self.assertEqual(motion_payload["window_end_sec"], 3.0)
        self.assertAlmostEqual(float(motion_payload["effective_fps"]), 31 / 3, places=2)
        self.assertTrue(sampling_metadata.is_slow_motion)
        self.assertEqual(sampling_metadata.window_start_sec, 0.0)
        self.assertEqual(sampling_metadata.window_end_sec, 3.0)
        self.assertAlmostEqual(sampling_metadata.effective_fps, 31 / 3, places=2)
        self.assertLess(min(extracted_timestamps), 4.0)
        self.assertTrue(any(8.0 <= timestamp <= 16.0 for timestamp in extracted_timestamps))
        self.assertGreater(max(extracted_timestamps), 20.0)
        self.assertGreater(max(extracted_timestamps) - min(extracted_timestamps), 20.0)


if __name__ == "__main__":
    unittest.main()
