from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.biomechanics import analyze_biomechanics, calc_arm_symmetry, calc_center_of_mass_trajectory


def _build_keypoints(
    *,
    shoulder_left: tuple[float, float],
    shoulder_right: tuple[float, float],
    hip_left: tuple[float, float],
    hip_right: tuple[float, float],
    wrist_left: tuple[float, float],
    wrist_right: tuple[float, float],
) -> list[dict[str, float]]:
    keypoints: list[dict[str, float]] = [{"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0} for index in range(33)]
    for index, (x_value, y_value) in {
        11: shoulder_left,
        12: shoulder_right,
        15: wrist_left,
        16: wrist_right,
        23: hip_left,
        24: hip_right,
    }.items():
        keypoints[index] = {"id": index, "x": x_value, "y": y_value, "z": 0.0, "visibility": 0.99}
    return keypoints


def _scale_point(x_value: float, y_value: float, scale: float) -> tuple[float, float]:
    return x_value * scale, y_value * scale


def _scaled_keypoints(scale: float, com_shift: float = 0.0) -> list[dict[str, float]]:
    return _build_keypoints(
        shoulder_left=_scale_point(0.40, 0.20 + com_shift, scale),
        shoulder_right=_scale_point(0.60, 0.20 + com_shift, scale),
        hip_left=_scale_point(0.43, 0.50 + com_shift, scale),
        hip_right=_scale_point(0.57, 0.50 + com_shift, scale),
        wrist_left=_scale_point(0.25, 0.24 + com_shift, scale),
        wrist_right=_scale_point(0.75, 0.24 + com_shift, scale),
    )


def _spin_keypoints(left_hip_x: float, right_hip_x: float, ankle_y: float = 0.88) -> list[dict[str, float]]:
    keypoints: list[dict[str, float]] = [{"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0} for index in range(33)]
    visible_points = {
        11: (0.42, 0.20),
        12: (0.58, 0.20),
        15: (0.35, 0.30),
        16: (0.65, 0.30),
        23: (left_hip_x, 0.50),
        24: (right_hip_x, 0.50),
        25: (0.45, 0.70),
        26: (0.55, 0.70),
        27: (0.46, ankle_y),
        28: (0.54, ankle_y),
    }
    for index, (x_value, y_value) in visible_points.items():
        keypoints[index] = {"id": index, "x": x_value, "y": y_value, "z": 0.0, "visibility": 0.99}
    return keypoints


class BiomechanicsNormalizationTests(unittest.TestCase):
    def test_arm_symmetry_is_stable_across_capture_scales(self) -> None:
        full_body = calc_arm_symmetry(_scaled_keypoints(1.0), 1)
        half_body = calc_arm_symmetry(_scaled_keypoints(0.5), 1)

        self.assertIsNotNone(full_body["symmetry"])
        self.assertIsNotNone(half_body["symmetry"])
        difference = abs(float(full_body["symmetry"]) - float(half_body["symmetry"]))
        baseline = max(float(full_body["symmetry"]), 1e-6)
        self.assertLess(difference / baseline, 0.05)

    def test_com_vertical_range_is_stable_across_capture_scales(self) -> None:
        full_body = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": _scaled_keypoints(1.0, 0.00)},
                {"frame": "frame_0002.jpg", "keypoints": _scaled_keypoints(1.0, -0.08)},
            ]
        }
        half_body = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": _scaled_keypoints(0.5, 0.00)},
                {"frame": "frame_0002.jpg", "keypoints": _scaled_keypoints(0.5, -0.08)},
            ]
        }

        full_range = calc_center_of_mass_trajectory(full_body)["vertical_range"]
        half_range = calc_center_of_mass_trajectory(half_body)["vertical_range"]

        self.assertGreater(full_range, 0.0)
        difference = abs(float(full_range) - float(half_range))
        baseline = max(float(full_range), 1e-6)
        self.assertLess(difference / baseline, 0.05)

    def test_spin_profile_uses_spin_key_frame_labels(self) -> None:
        pose_data = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": _spin_keypoints(0.45, 0.55)},
                {"frame": "frame_0002.jpg", "keypoints": _spin_keypoints(0.46, 0.56)},
                {"frame": "frame_0003.jpg", "keypoints": _spin_keypoints(0.62, 0.72)},
                {"frame": "frame_0004.jpg", "keypoints": _spin_keypoints(0.63, 0.73)},
            ]
        }

        result = analyze_biomechanics(pose_data, action_type="spin", analysis_profile="spin")

        self.assertEqual(
            result["key_frames"],
            {"旋转入": "frame_0002", "旋转中": "frame_0003", "旋转出": "frame_0004"},
        )
        self.assertNotIn("T", result["key_frames"])
        self.assertNotIn("A", result["key_frames"])
        self.assertNotIn("L", result["key_frames"])


if __name__ == "__main__":
    unittest.main()
