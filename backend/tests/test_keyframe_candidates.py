from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.keyframe_candidates import detect_key_frame_candidates


def _keypoints(
    *,
    com_y: float,
    knee_angle: str = "bent",
    ankle_y: float | None = None,
    visibility: float = 0.95,
) -> list[dict[str, float | int]]:
    keypoints: list[dict[str, float | int]] = [
        {"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
        for index in range(33)
    ]
    shoulder_y = com_y - 0.16
    hip_y = com_y + 0.16
    left_hip = (0.44, hip_y)
    right_hip = (0.56, hip_y)

    if knee_angle == "straight":
        knee_offset_x = 0.0
        lower_dx = 0.0
        lower_dy = 0.18
    elif knee_angle == "soft":
        knee_offset_x = 0.02
        lower_dx = 0.06
        lower_dy = 0.16
    else:
        knee_offset_x = 0.03
        lower_dx = 0.13
        lower_dy = 0.10

    left_knee = (left_hip[0] + knee_offset_x, hip_y + 0.18)
    right_knee = (right_hip[0] - knee_offset_x, hip_y + 0.18)
    left_ankle = (left_knee[0] + lower_dx, left_knee[1] + lower_dy)
    right_ankle = (right_knee[0] - lower_dx, right_knee[1] + lower_dy)

    if ankle_y is not None:
        left_ankle = (left_ankle[0], ankle_y)
        right_ankle = (right_ankle[0], ankle_y)

    visible = {
        11: (0.42, shoulder_y),
        12: (0.58, shoulder_y),
        23: left_hip,
        24: right_hip,
        25: left_knee,
        26: right_knee,
        27: left_ankle,
        28: right_ankle,
    }
    for index, (x_value, y_value) in visible.items():
        keypoints[index] = {
            "id": index,
            "x": x_value,
            "y": y_value,
            "z": 0.0,
            "visibility": visibility,
        }
    return keypoints


def _pose(
    com_values: list[float],
    knee_states: list[str],
    ankle_values: list[float | None],
    *,
    visibility: float = 0.95,
) -> dict[str, object]:
    return {
        "frames": [
            {
                "frame": f"frame_{index + 1:04d}.jpg",
                "keypoints": _keypoints(
                    com_y=com_values[index],
                    knee_angle=knee_states[index],
                    ankle_y=ankle_values[index],
                    visibility=visibility,
                ),
            }
            for index in range(len(com_values))
        ]
    }


def _motion(scores: list[float]) -> dict[str, object]:
    return {
        "scores": scores,
        "selected": [
            {
                "frame_id": f"frame_{index + 1:04d}",
                "timestamp": round(index / 10.0, 3),
                "motion_score": score,
            }
            for index, score in enumerate(scores)
        ],
    }


class KeyframeCandidateTests(unittest.TestCase):
    def test_detects_ordered_jump_candidates_with_evidence(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.60, 0.56, 0.49, 0.43, 0.38, 0.42, 0.50, 0.58],
            knee_states=["bent", "bent", "soft", "straight", "straight", "straight", "straight", "soft", "bent"],
            ankle_values=[None, None, None, None, None, None, None, None, None],
        )
        motion_scores = _motion([0.05, 0.12, 0.35, 0.95, 0.45, 0.25, 0.35, 0.9, 0.25])

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertEqual(result["quality_flags"], [])
        self.assertEqual(result["T"]["frame_id"], "frame_0004")
        self.assertEqual(result["A"]["frame_id"], "frame_0006")
        self.assertEqual(result["L"]["frame_id"], "frame_0008")
        self.assertLess(result["T"]["timestamp"], result["A"]["timestamp"])
        self.assertLess(result["A"]["timestamp"], result["L"]["timestamp"])
        self.assertGreaterEqual(result["T"]["confidence"], 0.6)
        self.assertGreaterEqual(result["A"]["confidence"], 0.6)
        self.assertGreaterEqual(result["L"]["confidence"], 0.6)
        self.assertIn("knee_extension_deg", result["T"]["evidence"])
        self.assertIn("local_minimum", result["A"]["evidence"])
        self.assertIn("ankle_return_delta", result["L"]["evidence"])

    def test_missing_pose_returns_warnings_without_exception(self) -> None:
        result = detect_key_frame_candidates(None, {"scores": [0.1, 0.2]}, "jump", 10.0)

        self.assertIn("keyframe_candidates_missing_pose", result["quality_flags"])
        self.assertIsNone(result["T"]["frame_id"])
        self.assertEqual(result["T"]["confidence"], 0.0)
        self.assertIn("keyframe_candidates_missing_pose", result["A"]["warnings"])

    def test_low_visibility_returns_quality_flag_and_low_confidence_candidates(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.58, 0.54, 0.50],
            knee_states=["bent", "soft", "straight", "soft"],
            ankle_values=[None, None, None, None],
            visibility=0.1,
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.1, 0.4, 0.8, 0.3]), "jump", 10.0)

        self.assertIn("keyframe_candidates_low_visibility", result["quality_flags"])
        self.assertIn("keyframe_candidates_insufficient_pose", result["quality_flags"])
        self.assertIsNone(result["A"]["frame_id"])
        self.assertEqual(result["L"]["confidence"], 0.0)

    def test_order_anomaly_returns_warning_instead_of_raising(self) -> None:
        pose_data = _pose(
            com_values=[0.40, 0.46, 0.55, 0.61, 0.64, 0.63],
            knee_states=["straight", "straight", "soft", "bent", "soft", "straight"],
            ankle_values=[None, None, None, None, None, None],
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.8, 0.4, 0.2, 0.1, 0.4, 0.9]), "jump", 10.0)

        self.assertIn("tal_order_unresolved", result["quality_flags"])
        self.assertIn("takeoff_window_missing", result["T"]["warnings"])
        self.assertEqual(result["T"]["confidence"], 0.0)


if __name__ == "__main__":
    unittest.main()
