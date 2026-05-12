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


class BiomechanicsFpsCorrectionTests(unittest.TestCase):
    def test_slow_motion_effective_fps_keeps_jump_metrics_valid(self) -> None:
        pose_data = {
            "frames": [
                {"frame": f"frame_{index:04d}.jpg", "keypoints": _jump_keypoints(index * math.pi / 2, shift)}
                for index, shift in enumerate(
                    [0.08, 0.06, 0.04, 0.02, 0.00, -0.02, -0.05, -0.08, -0.11, -0.14, -0.16, -0.14, -0.10, -0.06, -0.02, 0.02],
                    start=1,
                )
            ]
        }

        corrected = analyze_biomechanics(
            pose_data,
            action_type="axel",
            analysis_profile="jump",
            effective_fps=20.0,
            source_fps=240.0,
            window_seconds=0.75,
        )

        self.assertEqual(corrected["jump_metrics_status"], "ok")
        self.assertGreaterEqual(corrected["jump_metrics"]["air_time_seconds"], 0.4)
        self.assertLessEqual(corrected["jump_metrics"]["air_time_seconds"], 0.7)
        self.assertGreaterEqual(corrected["jump_metrics"]["estimated_height_cm"], 20)
        self.assertLessEqual(corrected["jump_metrics"]["estimated_height_cm"], 60)
        self.assertEqual(corrected["sampling_context"]["effective_fps"], 20.0)
        self.assertEqual(corrected["sampling_context"]["source_fps"], 240.0)

        legacy = analyze_biomechanics(pose_data, action_type="axel", analysis_profile="jump")
        self.assertEqual(legacy["jump_metrics_status"], "invalid")
        self.assertEqual(legacy["jump_metrics_warning"], "滞空时间检测异常")


if __name__ == "__main__":
    unittest.main()
