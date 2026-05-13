from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.action_recognition.action_profiles import (
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


def _frame(com_y, nose_y, left_ankle_y, right_ankle_y, *, visibility=0.99):
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
    def test_jump_profile_detected_for_wide_shot_using_relative_height(self):
        pose_data = {"frames": [
            _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.45, right_ankle_y=0.45),
            _frame(com_y=0.57, nose_y=0.20, left_ankle_y=0.45, right_ankle_y=0.45),
        ]}
        motion_scores = {"scores": [0.02, 0.07]}
        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)
        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])

    def test_jump_profile_detected_from_airborne_ankles_when_com_signal_is_weak(self):
        pose_data = {"frames": [
            _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
            _frame(com_y=0.595, nose_y=0.20, left_ankle_y=0.66, right_ankle_y=0.65),
            _frame(com_y=0.59, nose_y=0.20, left_ankle_y=0.64, right_ankle_y=0.63),
            _frame(com_y=0.598, nose_y=0.20, left_ankle_y=0.79, right_ankle_y=0.80),
        ]}
        motion_scores = {"scores": [0.01, 0.03, 0.04, 0.02]}
        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)
        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])
        self.assertGreaterEqual(evidence["airborne_frames_detected"], 2)

    def test_jump_hint_is_preserved_when_jump_gate_fails(self):
        pose_data = {"frames": [
            _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
            _frame(com_y=0.595, nose_y=0.20, left_ankle_y=0.79, right_ankle_y=0.79),
            _frame(com_y=0.592, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
        ]}
        motion_scores = {"scores": [0.01, 0.02, 0.03]}
        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)
        self.assertEqual(profile, "jump")
        self.assertFalse(evidence["jump_gate_passed"])
        self.assertEqual(evidence["profile_confidence"], "low")


if __name__ == "__main__":
    unittest.main()
