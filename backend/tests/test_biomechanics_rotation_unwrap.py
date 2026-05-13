from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.biomechanics import analyze_biomechanics


def _jump_keypoints(shoulder_angle: float, com_shift: float) -> list[dict[str, float]]:
    keypoints: list[dict[str, float]] = [
        {"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
        for index in range(33)
    ]

    shoulder_center_x = 0.5
    shoulder_center_y = 0.24 + com_shift
    shoulder_radius = 0.08
    hip_center_x = 0.5
    hip_center_y = 0.54 + com_shift

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
        23: (hip_center_x - 0.06, hip_center_y),
        24: (hip_center_x + 0.06, hip_center_y),
        25: (hip_center_x - 0.05, hip_center_y + 0.18),
        26: (hip_center_x + 0.05, hip_center_y + 0.18),
        27: (hip_center_x - 0.05, hip_center_y + 0.34),
        28: (hip_center_x + 0.05, hip_center_y + 0.34),
    }
    for index, (x_value, y_value) in visible_points.items():
        keypoints[index] = {"id": index, "x": x_value, "y": y_value, "z": 0.0, "visibility": 0.99}
    return keypoints


class BiomechanicsRotationUnwrapTests(unittest.TestCase):
    def test_rotation_rps_unwraps_shoulder_angle_boundary_crossings(self) -> None:
        frame_count = 13
        effective_fps = 12.0
        true_turns = 2.0
        pose_data = {
            "frames": [
                {
                    "frame": f"frame_{index + 1:04d}.jpg",
                    "keypoints": _jump_keypoints(
                        (2 * math.pi * true_turns) * index / (frame_count - 1),
                        -0.12 * math.sin(math.pi * index / (frame_count - 1)),
                    ),
                }
                for index in range(frame_count)
            ]
        }

        result = analyze_biomechanics(
            pose_data,
            action_type="axel",
            analysis_profile="jump",
            effective_fps=effective_fps,
        )

        expected_rps = true_turns / ((frame_count - 1) / effective_fps)
        self.assertEqual(result["jump_metrics_status"], "ok")
        self.assertAlmostEqual(result["jump_metrics"]["rotation_rps"], expected_rps, delta=expected_rps * 0.05)


if __name__ == "__main__":
    unittest.main()
