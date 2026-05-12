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

    def test_smooth_phases_uses_biomechanics_key_frame_when_votes_split(self) -> None:
        frame_analysis = [
            {"frame_id": "frame_0001", "phase": "准备", "phase_votes": {"准备": 2}},
            {"frame_id": "frame_0002", "phase": "准备", "phase_votes": {"准备": 1, "起跳": 1}},
            {"frame_id": "frame_0003", "phase": "腾空", "phase_votes": {"腾空": 2}},
        ]
        bio_data = {"key_frames": {"takeoff": "frame_0002", "peak": "frame_0003", "landing": "frame_0004"}}

        smoothed = smooth_phases(frame_analysis, "jump", bio_data=bio_data)

        self.assertEqual(smoothed[1]["phase"], "起跳")
        self.assertTrue(smoothed[1]["phase_corrected"])
        self.assertEqual(smoothed[1]["phase_correction_source"], "biomechanics_key_frame")


if __name__ == "__main__":
    unittest.main()
