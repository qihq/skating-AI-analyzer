from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.biomechanics import _point
from app.services.pose import (
    _apply_short_gap_interpolation,
    _candidate_rejection_reasons,
    _crop_bounds,
    _empty_payload,
)
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


def _visible_pose_keypoints(x: float = 0.45, y: float = 0.45) -> list[dict[str, float | int | str]]:
    keypoints = _empty_keypoints()
    for offset, keypoint_id in enumerate((11, 12, 23, 24)):
        keypoints[keypoint_id] = {
            "id": keypoint_id,
            "name": f"landmark_{keypoint_id}",
            "x": x + offset * 0.005,
            "y": y + offset * 0.01,
            "z": 0.0,
            "visibility": 0.9,
        }
    return keypoints


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

    def test_empty_pose_payload_includes_diagnostics(self) -> None:
        payload = _empty_payload()

        self.assertEqual(payload["pose_diagnostics"]["total_frames"], 0)
        self.assertEqual(payload["pose_diagnostics"]["candidate_count_histogram"], {})

    def test_tracker_gate_rejects_pose_candidate_that_is_much_wider_than_tracker_bbox(self) -> None:
        tracker_bbox = {"x": 0.44, "y": 0.43, "width": 0.025, "height": 0.11}
        wide_pose_candidate = {
            "bbox": {"x": 0.40, "y": 0.37, "width": 0.19, "height": 0.10},
            "keypoints": _visible_pose_keypoints(0.45, 0.45),
            "source": "tasks_multi_pose",
        }

        reasons = _candidate_rejection_reasons(
            wide_pose_candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertIn("tracker_width_ratio", reasons)
        self.assertIn("oversized_multi_pose_candidate", reasons)

    def test_tracker_gate_allows_reasonable_pose_candidate_near_tracker_bbox(self) -> None:
        tracker_bbox = {"x": 0.44, "y": 0.43, "width": 0.04, "height": 0.12}
        pose_candidate = {
            "bbox": {"x": 0.435, "y": 0.42, "width": 0.06, "height": 0.15},
            "keypoints": _visible_pose_keypoints(0.455, 0.45),
            "source": "single_pose_crop",
        }

        reasons = _candidate_rejection_reasons(
            pose_candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertEqual(reasons, [])

    def test_keypoint_gate_rejects_candidate_when_core_points_are_outside_tracker_roi(self) -> None:
        tracker_bbox = {"x": 0.44, "y": 0.43, "width": 0.04, "height": 0.12}
        candidate = {
            "bbox": {"x": 0.435, "y": 0.42, "width": 0.06, "height": 0.15},
            "keypoints": _visible_pose_keypoints(0.15, 0.15),
            "source": "single_pose_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertIn("keypoint_roi_coverage", reasons)
        self.assertIn("core_center_outside_roi", reasons)

    def test_small_tracker_crop_rejects_partial_foreground_body(self) -> None:
        tracker_bbox = {"x": 0.4376, "y": 0.4391, "width": 0.0385, "height": 0.1163}
        keypoints = _empty_keypoints()
        for keypoint_id, x, y in (
            (11, 0.455, 0.484),
            (12, 0.381, 0.486),
        ):
            keypoints[keypoint_id] = {
                "id": keypoint_id,
                "name": f"landmark_{keypoint_id}",
                "x": x,
                "y": y,
                "z": 0.0,
                "visibility": 0.99,
            }
        candidate = {
            "bbox": tracker_bbox,
            "keypoints": keypoints,
            "source": "single_pose_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertIn("core_keypoints_insufficient", reasons)
        self.assertIn("visible_keypoint_bbox", candidate["candidate_validation"])

    def test_short_lost_gap_is_interpolated_for_display_only(self) -> None:
        frames = [
            {"frame": "frame_0001.jpg", "tracking_state": "tracked", "keypoints": _visible_pose_keypoints(0.4, 0.4), "target_bbox": {"x": 0.4, "y": 0.4, "width": 0.05, "height": 0.1}},
            {"frame": "frame_0002.jpg", "tracking_state": "lost", "keypoints": [], "target_bbox": {"x": 0.41, "y": 0.4, "width": 0.05, "height": 0.1}},
            {"frame": "frame_0003.jpg", "tracking_state": "tracked", "keypoints": _visible_pose_keypoints(0.5, 0.5), "target_bbox": {"x": 0.5, "y": 0.5, "width": 0.05, "height": 0.1}},
        ]
        diagnostics = [{"tracking_state": frame["tracking_state"]} for frame in frames]

        interpolated, remaining_lost = _apply_short_gap_interpolation(frames, diagnostics)

        self.assertEqual(interpolated, 1)
        self.assertEqual(remaining_lost, 0)
        self.assertEqual(frames[1]["tracking_state"], "interpolated")
        self.assertEqual(frames[1]["tracking_confidence"], 0.05)
        self.assertTrue(all(point["interpolated"] for point in frames[1]["keypoints"]))
        self.assertEqual(diagnostics[1]["reason"], "pose_interpolated")

    def test_tracker_crop_expands_bbox_for_single_pose_fallback(self) -> None:
        bbox = {"x": 0.40, "y": 0.40, "width": 0.10, "height": 0.20}

        left, top, right, bottom = _crop_bounds(1000, 500, bbox, padding_ratio=0.75)

        self.assertEqual((left, top, right, bottom), (325, 125, 575, 375))


if __name__ == "__main__":
    unittest.main()
