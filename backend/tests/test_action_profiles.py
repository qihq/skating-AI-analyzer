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
    center_x: float = 0.5,
    body_facing: float = 1.0,
    visibility: float = 0.99,
) -> dict[str, object]:
    hip_y = com_y - 0.01
    shoulder_y = com_y + 0.01
    shoulder_half_width = 0.04 * body_facing
    hip_half_width = 0.025 * body_facing
    keypoints = [
        {"id": 0, "x": center_x, "y": nose_y, "visibility": visibility},
        {"id": 11, "x": center_x + shoulder_half_width, "y": shoulder_y, "visibility": visibility},
        {"id": 12, "x": center_x - shoulder_half_width, "y": shoulder_y, "visibility": visibility},
        {"id": 23, "x": center_x + hip_half_width, "y": hip_y, "visibility": visibility},
        {"id": 24, "x": center_x - hip_half_width, "y": hip_y, "visibility": visibility},
        {"id": 27, "x": center_x + 0.02, "y": left_ankle_y, "visibility": visibility},
        {"id": 28, "x": center_x - 0.02, "y": right_ankle_y, "visibility": visibility},
    ]
    return {"keypoints": keypoints}


class ActionProfileInferenceTests(unittest.TestCase):
    def test_english_action_type_preserves_jump_profile(self) -> None:
        profile, evidence = infer_analysis_profile("jump", None, {"frames": []}, {"scores": []})

        self.assertEqual(profile, "jump")
        self.assertEqual(evidence["profile_hint"], "jump")
        self.assertIn("jump_gate_not_passed", evidence["quality_flags"])

    def test_vertical_range_without_airborne_transition_does_not_confirm_wide_shot_jump(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.45, right_ankle_y=0.45),
                _frame(com_y=0.57, nose_y=0.20, left_ankle_y=0.45, right_ankle_y=0.45),
            ]
        }
        motion_scores = {"scores": [0.02, 0.07]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertFalse(evidence["jump_gate_passed"])
        self.assertEqual(evidence["airborne_frames_detected"], 0)
        self.assertAlmostEqual(evidence["com_vertical_range"], 0.03, places=4)
        self.assertAlmostEqual(evidence["person_height_reference"], 0.25, places=4)
        self.assertAlmostEqual(evidence["relative_vertical_range"], 0.12, places=4)

    def test_scale_change_without_airborne_transition_does_not_confirm_close_shot_jump(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.72, nose_y=0.10, left_ankle_y=0.90, right_ankle_y=0.90),
                _frame(com_y=0.62, nose_y=0.10, left_ankle_y=0.90, right_ankle_y=0.90),
            ]
        }
        motion_scores = {"scores": [0.03, 0.08]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertFalse(evidence["jump_gate_passed"])
        self.assertEqual(evidence["airborne_frames_detected"], 0)
        self.assertAlmostEqual(evidence["com_vertical_range"], 0.1, places=4)
        self.assertAlmostEqual(evidence["person_height_reference"], 0.8, places=4)
        self.assertAlmostEqual(evidence["relative_vertical_range"], 0.125, places=4)

    def test_mixed_profile_does_not_treat_horizontal_translation_as_rotation(self) -> None:
        pose_data = {
            "frames": [
                _frame(0.60, 0.20, 0.80, 0.80, center_x=0.20),
                _frame(0.60, 0.20, 0.80, 0.80, center_x=0.42),
                _frame(0.60, 0.20, 0.80, 0.80, center_x=0.68),
                _frame(0.60, 0.20, 0.80, 0.80, center_x=0.82),
            ]
        }

        profile, evidence = infer_analysis_profile(
            "自由滑",
            "节目片段",
            pose_data,
            {"scores": [0.02, 0.08, 0.09, 0.07]},
        )

        self.assertEqual(profile, "step")
        self.assertEqual(evidence["hip_rotation_signal"], 0.0)
        self.assertIn("mixed_action_profile_defaulted_step", evidence["quality_flags"])

    def test_mixed_profile_accepts_repeated_internal_body_orientation_changes_as_rotation(self) -> None:
        pose_data = {
            "frames": [
                _frame(0.60, 0.20, 0.80, 0.80, body_facing=facing)
                for facing in (1.0, 0.2, -1.0, -0.2, 1.0, 0.2, -1.0)
            ]
        }

        profile, evidence = infer_analysis_profile(
            "自由滑",
            "节目片段",
            pose_data,
            {"scores": [0.02, 0.08, 0.09, 0.07, 0.08, 0.09, 0.07]},
        )

        self.assertEqual(profile, "spin")
        self.assertGreaterEqual(evidence["hip_rotation_signal"], 0.15)

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
