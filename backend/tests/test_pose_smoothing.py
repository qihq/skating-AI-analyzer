from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.biomechanics import _point
from app.services.smoothing import smooth_keypoint_sequence


def _empty_keypoints() -> list[dict[str, float | int | str]]:
    return [
        {
            "id": index,
            "name": f"landmark_{index}",
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
            "visibility": 0.0,
        }
        for index in range(33)
    ]


def _frames_from_signal(values: list[float], *, missing: set[int] | None = None) -> list[dict[str, object]]:
    missing = missing or set()
    frames: list[dict[str, object]] = []
    for frame_index, value in enumerate(values):
        keypoints = _empty_keypoints()
        visibility = 0.0 if frame_index in missing else 0.99
        for keypoint_id in (11, 12, 23, 24):
            keypoints[keypoint_id] = {
                "id": keypoint_id,
                "name": f"landmark_{keypoint_id}",
                "x": value,
                "y": 0.2 + keypoint_id * 0.01,
                "z": 0.0,
                "visibility": visibility,
            }
        frames.append({"frame": f"frame_{frame_index + 1:04d}.jpg", "keypoints": keypoints})
    return frames


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def _second_difference(values: list[float]) -> list[float]:
    return [values[index + 1] - 2 * values[index] + values[index - 1] for index in range(1, len(values) - 1)]


class PoseSmoothingTests(unittest.TestCase):
    def test_one_euro_filter_reduces_high_frequency_jitter_and_keeps_trend(self) -> None:
        sample_count = 90
        effective_fps = 30.0
        trend = [0.1 + 0.08 * math.sin(index / 12.0) for index in range(sample_count)]
        noisy = [
            value + (0.02 if index % 2 == 0 else -0.02)
            for index, value in enumerate(trend)
        ]

        smoothed = smooth_keypoint_sequence(_frames_from_signal(noisy), effective_fps)
        smoothed_x = [float(frame["keypoints"][11]["x"]) for frame in smoothed]
        raw_jitter = [(noisy[index] - trend[index]) for index in range(sample_count)]
        raw_high_frequency = _second_difference(noisy)
        smoothed_high_frequency = _second_difference(smoothed_x)
        trend_mae = sum(abs(smoothed_x[index] - trend[index]) for index in range(sample_count)) / sample_count

        self.assertGreater(_rms(raw_jitter), 0.015)
        self.assertLess(_rms(smoothed_high_frequency), _rms(raw_high_frequency) * 0.12)
        self.assertLess(trend_mae, 0.02)

    def test_low_visibility_gap_is_linearly_interpolated_before_smoothing(self) -> None:
        values = [0.1 + index * 0.01 for index in range(10)]
        smoothed = smooth_keypoint_sequence(_frames_from_signal(values, missing={3, 4, 5}), effective_fps=10.0)

        for frame_index in (3, 4, 5):
            keypoint = smoothed[frame_index]["keypoints"][11]
            self.assertTrue(keypoint["interpolated"])
            self.assertEqual(keypoint["visibility"], 0.0)
            self.assertGreater(float(keypoint["x"]), float(smoothed[frame_index - 1]["keypoints"][11]["x"]))

    def test_biomechanics_point_accepts_smoothed_low_visibility_coordinates(self) -> None:
        keypoints = _empty_keypoints()
        keypoints[11] = {"id": 11, "x": 0.42, "y": 0.24, "z": 0.0, "visibility": 0.4}
        keypoints[12] = {"id": 12, "x": 0.58, "y": 0.24, "z": 0.0, "visibility": 0.1, "interpolated": True}

        self.assertEqual(_point(keypoints, 11), {"x": 0.42, "y": 0.24, "z": 0.0})
        self.assertIsNone(_point(keypoints, 12))

    def test_fully_invisible_keypoint_remains_unusable(self) -> None:
        smoothed = smooth_keypoint_sequence(_frames_from_signal([0.1, 0.2, 0.3]), effective_fps=10.0)

        self.assertIsNone(smoothed[0]["keypoints"][0]["x"])
        self.assertIsNone(_point(smoothed[0]["keypoints"], 0))


if __name__ == "__main__":
    unittest.main()
