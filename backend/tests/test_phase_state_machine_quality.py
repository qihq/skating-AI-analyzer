from __future__ import annotations

import json
import unittest

from app.services.phase_smoother import evaluate_phase_consistency, smooth_phases


PREPARE = "\u51c6\u5907"
TAKEOFF = "\u8d77\u8df3"
AIR = "\u817e\u7a7a"
LANDING = "\u843d\u51b0"
SPIN_ENTRY = "\u65cb\u8f6c\u5165"
SPIN = "\u65cb\u8f6c\u4e2d"
SPIN_EXIT = "\u65cb\u8f6c\u51fa"


class PhaseStateMachineQualityTests(unittest.TestCase):
    def test_jump_landing_before_takeoff_is_corrected_with_reason(self) -> None:
        payload = evaluate_phase_consistency(
            [
                {"frame_id": "frame_0001", "phase": LANDING},
                {"frame_id": "frame_0002", "phase": TAKEOFF},
                {"frame_id": "frame_0003", "phase": AIR},
            ],
            "jump",
        )

        frames = payload["frame_analysis"]
        flags = payload["phase_consistency_flags"]

        self.assertEqual(frames[0]["phase"], PREPARE)
        self.assertTrue(frames[0]["phase_corrected"])
        self.assertEqual(frames[0]["phase_correction_source"], "phase_state_machine")
        self.assertIn("phase_skip", frames[0]["phase_correction_reason"])
        self.assertTrue(any(flag["flag"] == "phase_skip_corrected" for flag in flags))
        self.assertFalse(payload["phase_consistency_valid"])
        json.dumps(payload, ensure_ascii=False)

    def test_jump_missing_airborne_phase_is_flagged(self) -> None:
        payload = evaluate_phase_consistency(
            [
                {"frame_id": "frame_0001", "phase": PREPARE},
                {"frame_id": "frame_0002", "phase": TAKEOFF},
                {"frame_id": "frame_0003", "phase": LANDING},
            ],
            "jump",
        )

        frames = payload["frame_analysis"]
        flags = payload["phase_consistency_flags"]

        self.assertEqual(frames[2]["phase"], AIR)
        self.assertTrue(frames[2]["phase_corrected"])
        self.assertIn("phase_skip", frames[2]["phase_correction_reason"])
        skip_flags = [flag for flag in flags if flag["flag"] == "phase_skip_corrected"]
        self.assertEqual(skip_flags[0]["missing_phases"], [AIR])
        self.assertFalse(payload["phase_consistency_valid"])

    def test_spin_backward_phase_is_corrected_with_reason(self) -> None:
        payload = evaluate_phase_consistency(
            [
                {"frame_id": "frame_0001", "phase": SPIN_ENTRY},
                {"frame_id": "frame_0002", "phase": SPIN},
                {"frame_id": "frame_0003", "phase": SPIN_EXIT},
                {"frame_id": "frame_0004", "phase": SPIN},
            ],
            "spin",
        )

        frames = payload["frame_analysis"]
        flags = payload["phase_consistency_flags"]

        self.assertEqual(frames[3]["phase"], SPIN_EXIT)
        self.assertTrue(frames[3]["phase_corrected"])
        self.assertEqual(frames[3]["phase_correction_source"], "phase_state_machine")
        self.assertIn("phase_backward", frames[3]["phase_correction_reason"])
        self.assertTrue(any(flag["flag"] == "phase_backward_corrected" for flag in flags))

    def test_smooth_phases_still_returns_frame_list_and_adds_reason(self) -> None:
        smoothed = smooth_phases(
            [
                {"frame_id": "frame_0001", "phase": AIR},
                {"frame_id": "frame_0002", "phase": TAKEOFF},
            ],
            "jump",
        )

        self.assertIsInstance(smoothed, list)
        self.assertTrue(smoothed[1]["phase_corrected"])
        self.assertEqual(smoothed[1]["phase_correction_source"], "phase_transition_state_machine")
        self.assertIn("illegal_transition", smoothed[1]["phase_correction_reason"])


if __name__ == "__main__":
    unittest.main()
