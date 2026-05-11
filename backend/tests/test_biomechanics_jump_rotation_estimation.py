from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.biomechanics import analyze_biomechanics


def _jump_keypoints(shoulder_angle: float, com_shift: float) -> list[dict[str, float]]:
    keypoints: list[dict[str, float]] = [{"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0} for index in range(33)]

    shoulder_center_x = 0.5
    shoulder_center_y = 0.24 + com_shift
    shoulder_radius = 0.08
    hip_center_x = 0.5
    hip_center_y = 0.54 + com_shift
    hip_half_width = 0.06

    left_shoulder = (
        shoulder_center_x - math.cos(shoulder_angle) * shoulder_radius,
        shoulder_center_y - math.sin(shoulder_angle) * shoulder_radius,
    )
    right_shoulder = (
        shoulder_center_x + math.cos(shoulder_angle) * shoulder_radius,
        shoulder_center_y + math.sin(shoulder_angle) * shoulder_radius,
    )

    visible_points = {
        11: left_shoulder,
        12: right_shoulder,
        15: (left_shoulder[0] - 0.05, left_shoulder[1] + 0.03),
        16: (right_shoulder[0] + 0.05, right_shoulder[1] + 0.03),
        23: (hip_center_x - hip_half_width, hip_center_y),
        24: (hip_center_x + hip_half_width, hip_center_y),
        25: (hip_center_x - 0.05, hip_center_y + 0.18),
        26: (hip_center_x + 0.05, hip_center_y + 0.18),
        27: (hip_center_x - 0.05, hip_center_y + 0.34),
        28: (hip_center_x + 0.05, hip_center_y + 0.34),
    }

    for index, (x_value, y_value) in visible_points.items():
        keypoints[index] = {"id": index, "x": x_value, "y": y_value, "z": 0.0, "visibility": 0.99}

    return keypoints


class BiomechanicsJumpRotationEstimationTests(unittest.TestCase):
    def test_jump_metrics_include_estimated_rotations_and_probable_type(self) -> None:
        pose_data = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": _jump_keypoints(0.0, 0.00)},
                {"frame": "frame_0002.jpg", "keypoints": _jump_keypoints(math.pi, -0.08)},
                {"frame": "frame_0003.jpg", "keypoints": _jump_keypoints(0.0, -0.14)},
                {"frame": "frame_0004.jpg", "keypoints": _jump_keypoints(math.pi, -0.10)},
                {"frame": "frame_0005.jpg", "keypoints": _jump_keypoints(0.0, -0.02)},
            ]
        }

        result = analyze_biomechanics(pose_data, action_type="axel", analysis_profile="jump")

        self.assertEqual(result["jump_metrics_status"], "ok")
        self.assertAlmostEqual(result["jump_metrics"]["air_time_seconds"], 0.8, places=2)
        self.assertAlmostEqual(result["jump_metrics"]["rotation_rps"], 2.5, places=2)
        self.assertAlmostEqual(result["jump_metrics"]["estimated_rotations"], 2.0, places=2)
        self.assertIn("双圈跳", result["jump_metrics"]["probable_jump_type"])


if __name__ == "__main__":
    unittest.main()
