from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.action_profiles import infer_jump_subtype_evidence
from app.services.jump_features import compute_jump_evidence


def _keypoints(
    *,
    com_x: float,
    com_y: float = 0.5,
    shoulder_angle: float = 0.0,
    left_ankle: tuple[float, float] = (0.43, 0.82),
    right_ankle: tuple[float, float] = (0.57, 0.82),
    left_z: float = 0.0,
    right_z: float = 0.0,
    left_visibility: float = 0.9,
    right_visibility: float = 0.9,
) -> list[dict[str, float | int]]:
    keypoints: list[dict[str, float | int]] = [
        {"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
        for index in range(33)
    ]
    shoulder_radius = 0.08
    shoulder_y = com_y - 0.18
    hip_y = com_y + 0.08
    left_shoulder = (
        com_x - math.cos(shoulder_angle) * shoulder_radius,
        shoulder_y - math.sin(shoulder_angle) * shoulder_radius,
    )
    right_shoulder = (
        com_x + math.cos(shoulder_angle) * shoulder_radius,
        shoulder_y + math.sin(shoulder_angle) * shoulder_radius,
    )
    visible = {
        11: (*left_shoulder, 0.0, 0.95),
        12: (*right_shoulder, 0.0, 0.95),
        23: (com_x - 0.05, hip_y, 0.0, 0.95),
        24: (com_x + 0.05, hip_y, 0.0, 0.95),
        27: (left_ankle[0], left_ankle[1], left_z, left_visibility),
        28: (right_ankle[0], right_ankle[1], right_z, right_visibility),
    }
    for index, (x_value, y_value, z_value, visibility) in visible.items():
        keypoints[index] = {
            "id": index,
            "x": x_value,
            "y": y_value,
            "z": z_value,
            "visibility": visibility,
        }
    return keypoints


def _pose(frames: list[list[dict[str, float | int]]]) -> dict[str, object]:
    return {
        "frames": [
            {"frame": f"frame_{index + 1:04d}.jpg", "keypoints": keypoints}
            for index, keypoints in enumerate(frames)
        ]
    }


class JumpFeatureEvidenceTests(unittest.TestCase):
    def test_toe_loop_like_sequence_detects_toe_pick_pulse(self) -> None:
        frames = [
            _keypoints(com_x=0.40, right_ankle=(0.60, 0.80)),
            _keypoints(com_x=0.42, right_ankle=(0.60, 0.88)),
            _keypoints(com_x=0.44, right_ankle=(0.60, 0.79)),
            _keypoints(com_x=0.46, right_ankle=(0.59, 0.78)),
        ]

        evidence = compute_jump_evidence(_pose(frames), {"T": "frame_0003"}, effective_fps=10.0)

        self.assertTrue(evidence["toe_pick_pulse"])
        self.assertGreaterEqual(evidence["toe_pick_strength"], 0.07)

    def test_loop_like_sequence_detects_feet_together_at_takeoff(self) -> None:
        frames = [
            _keypoints(com_x=0.40, left_ankle=(0.49, 0.82), right_ankle=(0.52, 0.82)),
            _keypoints(com_x=0.42, left_ankle=(0.50, 0.82), right_ankle=(0.53, 0.82)),
        ]

        evidence = compute_jump_evidence(_pose(frames), {"T": "frame_0002"}, effective_fps=10.0)

        self.assertTrue(evidence["feet_together_at_takeoff"])
        self.assertLess(evidence["feet_distance_shoulder_ratio"], 0.3)

    def test_salchow_like_sequence_detects_free_leg_swing(self) -> None:
        frames = [
            _keypoints(com_x=0.40, right_ankle=(0.35, 0.84)),
            _keypoints(com_x=0.42, right_ankle=(0.48, 0.80)),
            _keypoints(com_x=0.44, right_ankle=(0.64, 0.76)),
            _keypoints(com_x=0.46, right_ankle=(0.70, 0.74)),
        ]

        evidence = compute_jump_evidence(_pose(frames), {"T": "frame_0004"}, effective_fps=8.0)

        self.assertGreater(evidence["free_leg_swing_amplitude"], 0.35)
        self.assertGreaterEqual(evidence["free_leg_swing_confidence"], 0.5)

    def test_axel_like_sequence_detects_forward_approach(self) -> None:
        frames = [
            _keypoints(com_x=0.40, shoulder_angle=-math.pi / 2),
            _keypoints(com_x=0.43, shoulder_angle=-math.pi / 2),
            _keypoints(com_x=0.46, shoulder_angle=-math.pi / 2),
        ]

        evidence = compute_jump_evidence(_pose(frames), {"T": "frame_0003"}, effective_fps=6.0)

        self.assertEqual(evidence["approach_direction"], "forward")
        self.assertGreaterEqual(evidence["approach_direction_confidence"], 0.5)

    def test_edge_score_reports_inside_or_outside_when_curvature_signal_is_clear(self) -> None:
        outside_frames = [
            _keypoints(com_x=0.40, com_y=0.50),
            _keypoints(com_x=0.44, com_y=0.47),
            _keypoints(com_x=0.48, com_y=0.50),
        ]
        inside_frames = [
            _keypoints(com_x=0.40, com_y=0.50),
            _keypoints(com_x=0.44, com_y=0.53),
            _keypoints(com_x=0.48, com_y=0.50),
        ]

        outside = compute_jump_evidence(_pose(outside_frames), {"T": "frame_0003"}, effective_fps=6.0)
        inside = compute_jump_evidence(_pose(inside_frames), {"T": "frame_0003"}, effective_fps=6.0)

        self.assertEqual(outside["pre_takeoff_edge_label"], "likely_outside_edge")
        self.assertLess(outside["pre_takeoff_edge_score"], 0.5)
        self.assertEqual(inside["pre_takeoff_edge_label"], "likely_inside_edge")
        self.assertGreater(inside["pre_takeoff_edge_score"], 0.5)

    def test_action_profile_wrapper_returns_quality_flag_for_missing_inputs(self) -> None:
        evidence = infer_jump_subtype_evidence(None, None, None)

        self.assertIn("jump_evidence_missing_inputs", evidence["quality_flags"])


if __name__ == "__main__":
    unittest.main()
