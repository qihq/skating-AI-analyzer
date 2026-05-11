from __future__ import annotations

import unittest

from app.services.phase_smoother import smooth_phases


class PhaseSmootherTests(unittest.TestCase):
    def test_smooth_phases_corrects_illegal_jump_transition(self) -> None:
        frame_analysis = [
            {"frame_id": "frame_0001", "phase": "腾空"},
            {"frame_id": "frame_0002", "phase": "起跳"},
            {"frame_id": "frame_0003", "phase": "腾空"},
        ]

        smoothed = smooth_phases(frame_analysis, "jump")

        self.assertEqual([frame["phase"] for frame in smoothed], ["腾空", "腾空", "腾空"])
        self.assertFalse(smoothed[0]["phase_corrected"])
        self.assertTrue(smoothed[1]["phase_corrected"])
        self.assertFalse(smoothed[2]["phase_corrected"])


if __name__ == "__main__":
    unittest.main()
