from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.action_recognition.phase_smoother import smooth_phases


class PhaseSmootherTests(unittest.TestCase):
    def test_smooth_phases_corrects_illegal_jump_transition(self):
        frame_analysis = [
            {"frame_id": "frame_0001", "phase": "腾空"},
            {"frame_id": "frame_0002", "phase": "起跳"},
            {"frame_id": "frame_0003", "phase": "腾空"},
        ]
        smoothed = smooth_phases(frame_analysis, "jump")
        self.assertEqual([f["phase"] for f in smoothed], ["腾空", "腾空", "腾空"])
        self.assertFalse(smoothed[0]["phase_corrected"])
        self.assertTrue(smoothed[1]["phase_corrected"])
        self.assertFalse(smoothed[2]["phase_corrected"])


if __name__ == "__main__":
    unittest.main()
