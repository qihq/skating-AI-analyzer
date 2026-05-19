from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report import _apply_low_confidence_notice, normalize_report
from app.services.vision_quality import apply_low_quality_policy


class LowQualityConservativePolicyTests(unittest.TestCase):
    def test_poor_payload_keeps_observations_and_confidence_but_adds_diagnostics(self) -> None:
        payload = {
            "data_quality_hint": "poor",
            "camera_view": "side",
            "pose_visibility": 0.42,
            "frame_analysis": [
                {
                    "frame_id": "frame_0001",
                    "phase": "起跳",
                    "confidence": 0.92,
                    "element_confidence": 0.88,
                    "observations": {"blade_edge": "外刃"},
                }
            ],
            "quality_flags": [],
        }

        adjusted = apply_low_quality_policy(payload, data_quality_hint="poor", camera_view="side", pose_visibility=0.42)

        frame = adjusted["frame_analysis"][0]
        self.assertEqual(frame["observations"]["blade_edge"], "外刃")
        self.assertEqual(frame["confidence"], 0.92)
        self.assertEqual(frame["element_confidence"], 0.88)
        self.assertIn("vision_low_quality_conservative_policy", adjusted["quality_flags"])
        self.assertIn("vision_low_quality_diagnostic_only", adjusted["quality_flags"])
        self.assertTrue(adjusted["conservative_policy"]["applied"])
        self.assertEqual(adjusted["conservative_policy"]["mode"], "diagnostic_only")

    def test_partial_payload_is_marked_conservative_without_overcorrecting_frame(self) -> None:
        payload = {
            "data_quality_hint": "partial",
            "camera_view": "unknown",
            "pose_visibility": 0.58,
            "frame_analysis": [
                {
                    "frame_id": "frame_0002",
                    "phase": "落冰",
                    "confidence": 0.6,
                    "element_confidence": 0.7,
                    "observations": {"blade_edge": "不可判断"},
                }
            ],
        }

        adjusted = apply_low_quality_policy(payload)

        frame = adjusted["frame_analysis"][0]
        self.assertEqual(frame["observations"]["blade_edge"], "不可判断")
        self.assertEqual(frame["confidence"], 0.6)
        self.assertEqual(frame["element_confidence"], 0.7)
        self.assertIn("vision_low_quality_partial", adjusted["quality_flags"])

    def test_report_summary_does_not_add_conservative_notice_for_poor_quality_alone(self) -> None:
        report = normalize_report(
            {
                "summary": "ok",
                "issues": [],
                "improvements": [],
                "training_focus": "focus",
                "subscores": {
                    "takeoff_power": 80,
                    "rotation_axis": 80,
                    "arm_coordination": 80,
                    "landing_absorption": 80,
                    "core_stability": 80,
                },
                "data_quality": "good",
            },
            bio_data={"quality_flags": []},
        )

        updated = _apply_low_confidence_notice(
            report,
            {
                "data_quality_hint": "poor",
                "reliability_note": "",
                "conservative_policy": {"applied": True, "notice": "视频质量有限，建议保守解读。"},
            },
        )

        self.assertEqual(updated["summary"], "ok")
        self.assertEqual(updated["data_quality"], "good")


if __name__ == "__main__":
    unittest.main()
