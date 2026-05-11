from __future__ import annotations

import unittest

from app.services.action_profiles import (
    ACTION_SUBTYPE_OPTIONS,
    JUMP_SUBTYPES,
    infer_analysis_profile,
    infer_profile_hint,
)


JUMP_ACTION_TYPE = next(
    action_type for action_type in ACTION_SUBTYPE_OPTIONS if infer_profile_hint(action_type, None) == "jump"
)
JUMP_ACTION_SUBTYPE = next(
    subtype for subtype in ACTION_SUBTYPE_OPTIONS[JUMP_ACTION_TYPE] if subtype in JUMP_SUBTYPES
)


def _frame(
    com_y: float,
    nose_y: float,
    left_ankle_y: float,
    right_ankle_y: float,
    *,
    visibility: float = 0.99,
) -> dict[str, object]:
    hip_y = com_y - 0.01
    shoulder_y = com_y + 0.01
    keypoints = [
        {"id": 0, "y": nose_y, "visibility": visibility},
        {"id": 11, "y": shoulder_y, "visibility": visibility},
        {"id": 12, "y": shoulder_y, "visibility": visibility},
        {"id": 23, "y": hip_y, "visibility": visibility},
        {"id": 24, "y": hip_y, "visibility": visibility},
        {"id": 27, "y": left_ankle_y, "visibility": visibility},
        {"id": 28, "y": right_ankle_y, "visibility": visibility},
    ]
    return {"keypoints": keypoints}


class ActionProfileInferenceTests(unittest.TestCase):
    def test_jump_profile_detected_for_wide_shot_using_relative_height(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.45, right_ankle_y=0.45),
                _frame(com_y=0.57, nose_y=0.20, left_ankle_y=0.45, right_ankle_y=0.45),
            ]
        }
        motion_scores = {"scores": [0.02, 0.07]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])
        self.assertAlmostEqual(evidence["com_vertical_range"], 0.03, places=4)
        self.assertAlmostEqual(evidence["person_height_reference"], 0.25, places=4)
        self.assertAlmostEqual(evidence["relative_vertical_range"], 0.12, places=4)

    def test_jump_profile_detected_for_close_shot_using_relative_height(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.72, nose_y=0.10, left_ankle_y=0.90, right_ankle_y=0.90),
                _frame(com_y=0.62, nose_y=0.10, left_ankle_y=0.90, right_ankle_y=0.90),
            ]
        }
        motion_scores = {"scores": [0.03, 0.08]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])
        self.assertAlmostEqual(evidence["com_vertical_range"], 0.1, places=4)
        self.assertAlmostEqual(evidence["person_height_reference"], 0.8, places=4)
        self.assertAlmostEqual(evidence["relative_vertical_range"], 0.125, places=4)

    def test_jump_profile_detected_from_airborne_ankles_when_com_signal_is_weak(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
                _frame(com_y=0.595, nose_y=0.20, left_ankle_y=0.66, right_ankle_y=0.65),
                _frame(com_y=0.59, nose_y=0.20, left_ankle_y=0.64, right_ankle_y=0.63),
                _frame(com_y=0.598, nose_y=0.20, left_ankle_y=0.79, right_ankle_y=0.80),
            ]
        }
        motion_scores = {"scores": [0.01, 0.03, 0.04, 0.02]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])
        self.assertGreaterEqual(evidence["airborne_frames_detected"], 2)
        self.assertAlmostEqual(evidence["com_vertical_range"], 0.01, places=4)
        self.assertAlmostEqual(evidence["relative_vertical_range"], 0.0192, places=4)

    def test_jump_hint_is_preserved_when_jump_gate_fails(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
                _frame(com_y=0.595, nose_y=0.20, left_ankle_y=0.79, right_ankle_y=0.79),
                _frame(com_y=0.592, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
            ]
        }
        motion_scores = {"scores": [0.01, 0.02, 0.03]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertFalse(evidence["jump_gate_passed"])
        self.assertEqual(evidence["profile_confidence"], "low")
        self.assertIn("jump_gate_not_passed", evidence["quality_flags"])
        self.assertTrue(any("几何证据不足" in message for message in evidence["negative_constraints"]))


if __name__ == "__main__":
    unittest.main()
