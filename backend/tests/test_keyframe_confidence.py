from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.keyframe_candidates import CONFIDENCE_WEIGHTS, calculate_key_frame_confidence


class KeyframeConfidenceTests(unittest.TestCase):
    def test_weighted_formula_matches_expected_value(self) -> None:
        confidence = calculate_key_frame_confidence(
            motion_peak_score=1.0,
            com_velocity_score=0.8,
            pose_visibility_score=0.5,
            knee_angle_change_score=0.4,
            phase_order_score=0.2,
        )

        expected = (
            CONFIDENCE_WEIGHTS["motion_peak_score"] * 1.0
            + CONFIDENCE_WEIGHTS["com_velocity_score"] * 0.8
            + CONFIDENCE_WEIGHTS["pose_visibility_score"] * 0.5
            + CONFIDENCE_WEIGHTS["knee_angle_change_score"] * 0.4
            + CONFIDENCE_WEIGHTS["phase_order_score"] * 0.2
        )
        self.assertAlmostEqual(confidence, expected, places=3)

    def test_inputs_are_clamped_to_zero_one(self) -> None:
        high = calculate_key_frame_confidence(
            motion_peak_score=2.0,
            com_velocity_score=3.0,
            pose_visibility_score=1.5,
            knee_angle_change_score=9.0,
            phase_order_score=4.0,
        )
        low = calculate_key_frame_confidence(
            motion_peak_score=-2.0,
            com_velocity_score=-3.0,
            pose_visibility_score=-1.5,
            knee_angle_change_score=-9.0,
            phase_order_score=-4.0,
        )

        self.assertEqual(high, 1.0)
        self.assertEqual(low, 0.0)

    def test_missing_signals_add_warnings_and_downweight(self) -> None:
        warnings: list[str] = []

        confidence = calculate_key_frame_confidence(
            motion_peak_score=None,
            com_velocity_score=1.0,
            pose_visibility_score=1.0,
            knee_angle_change_score=None,
            phase_order_score=1.0,
            warnings=warnings,
        )

        expected = (
            CONFIDENCE_WEIGHTS["com_velocity_score"]
            + CONFIDENCE_WEIGHTS["pose_visibility_score"]
            + CONFIDENCE_WEIGHTS["phase_order_score"]
        )
        self.assertAlmostEqual(confidence, expected, places=3)
        self.assertIn("confidence_missing_motion_peak", warnings)
        self.assertIn("confidence_missing_knee_angle_change", warnings)

    def test_missing_pose_caps_confidence_at_055(self) -> None:
        warnings: list[str] = []

        confidence = calculate_key_frame_confidence(
            motion_peak_score=1.0,
            com_velocity_score=1.0,
            pose_visibility_score=None,
            knee_angle_change_score=1.0,
            phase_order_score=1.0,
            warnings=warnings,
        )

        self.assertLessEqual(confidence, 0.55)
        self.assertEqual(confidence, 0.55)
        self.assertIn("confidence_missing_pose_visibility", warnings)


if __name__ == "__main__":
    unittest.main()
