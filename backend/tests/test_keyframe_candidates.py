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
    tracking_states: list[str] | None = None,
) -> dict[str, object]:
    return {
        "frames": [
            {
                "frame": f"frame_{index + 1:04d}.jpg",
                "tracking_state": tracking_states[index] if tracking_states else "tracked",
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
        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertEqual(result["A"]["frame_id"], "frame_0003")
        self.assertGreaterEqual(result["L"]["confidence"], 0.35)
        self.assertIn("keyframe_candidates_motion_fallback", result["A"]["warnings"])

    def test_order_anomaly_returns_warning_instead_of_raising(self) -> None:
        pose_data = _pose(
            com_values=[0.40, 0.46, 0.55, 0.61, 0.64, 0.63],
            knee_states=["straight", "straight", "soft", "bent", "soft", "straight"],
            ankle_values=[None, None, None, None, None, None],
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.8, 0.4, 0.2, 0.1, 0.4, 0.9]), "jump", 10.0)

        self.assertIn("tal_order_unresolved", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback", result["T"]["warnings"])
        self.assertIsNotNone(result["T"]["frame_id"])
        self.assertGreaterEqual(result["T"]["confidence"], 0.35)

    def test_partial_geometry_uses_low_motion_fallback_to_complete_tal(self) -> None:
        pose_data = _pose(
            com_values=[0.38, 0.43, 0.49, 0.55, 0.61, 0.65],
            knee_states=["straight", "straight", "soft", "bent", "soft", "straight"],
            ankle_values=[None, None, None, None, None, None],
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.012, 0.018, 0.027, 0.02, 0.019, 0.016]), "jump", 10.0)

        self.assertIn("tal_order_unresolved", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_low_motion", result["quality_flags"])
        self.assertIsNotNone(result["T"]["frame_id"])
        self.assertIsNotNone(result["A"]["frame_id"])
        self.assertIsNotNone(result["L"]["frame_id"])

    def test_excludes_unreliable_pose_states_from_candidates(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.60, 0.56, 0.49, 0.43, 0.38, 0.42, 0.50, 0.58],
            knee_states=["bent", "bent", "soft", "straight", "straight", "straight", "straight", "soft", "bent"],
            ankle_values=[None, None, None, None, None, None, None, None, None],
            tracking_states=[
                "tracked",
                "tracked",
                "tracked",
                "low_confidence",
                "tracked",
                "tracked",
                "interpolated",
                "tracked",
                "lost",
            ],
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.05, 0.12, 0.35, 0.95, 0.45, 0.25, 0.35, 0.9, 0.25]), "jump", 10.0)

        self.assertIn("keyframe_candidates_excluded_unreliable_pose_frames", result["quality_flags"])
        self.assertEqual(result["excluded_pose_frames"], {"low_confidence": 1, "interpolated": 1, "lost": 1})
        self.assertNotEqual(result["T"]["frame_id"], "frame_0004")
        self.assertNotEqual(result["L"]["frame_id"], "frame_0009")

    def test_filtered_pose_indices_do_not_overflow_detector_windows(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.61, 0.59, 0.56, 0.50, 0.43, 0.39, 0.44, 0.52, 0.59, 0.63],
            knee_states=["bent", "bent", "soft", "soft", "straight", "straight", "straight", "soft", "bent", "bent", "soft"],
            ankle_values=[None, None, None, None, None, None, None, None, None, None, None],
            tracking_states=[
                "tracked",
                "low_confidence",
                "tracked",
                "interpolated",
                "tracked",
                "tracked",
                "tracked",
                "lost",
                "tracked",
                "tracked",
                "tracked",
            ],
        )

        result = detect_key_frame_candidates(
            pose_data,
            _motion([0.03, 0.04, 0.06, 0.08, 0.14, 0.30, 0.42, 0.20, 0.36, 0.18, 0.10]),
            "jump",
            10.0,
        )

        self.assertIn("keyframe_candidates_excluded_unreliable_pose_frames", result["quality_flags"])
        self.assertNotIn("keyframe_candidates_detection_failed", result["quality_flags"])
        self.assertIsNotNone(result["A"]["frame_id"])
        self.assertIsInstance(result["A"]["evidence"].get("pose_index"), int)
        self.assertIsInstance(result["A"]["evidence"].get("signal_index"), int)

    def test_ordered_visible_landing_candidate_keeps_complete_tal_with_low_confidence_warning(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.60, 0.56, 0.50, 0.44, 0.39, 0.40, 0.401],
            knee_states=["bent", "bent", "soft", "straight", "straight", "straight", "straight", "straight"],
            ankle_values=[0.72, 0.70, 0.68, 0.66, 0.64, 0.62, 0.62, 0.62],
            visibility=0.42,
        )
        motion_scores = _motion([0.02, 0.05, 0.10, 0.70, 0.20, 0.30, 0.04, 0.05])

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertEqual(result["quality_flags"], [])
        self.assertEqual(result["L"]["confidence"], 0.35)
        self.assertIn("landing_confidence_low", result["L"]["warnings"])
        self.assertIn("confidence_floor_from_ordered_tal", result["L"]["warnings"])


if __name__ == "__main__":
    unittest.main()
