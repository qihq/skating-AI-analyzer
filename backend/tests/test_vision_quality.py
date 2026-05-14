from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.vision_quality import evaluate_vision_payload_quality


def _valid_payload() -> dict[str, object]:
    return {
        "data_quality_hint": "good",
        "frame_analysis": [
            {
                "frame_id": "frame_0001",
                "phase": "起跳",
                "confidence": 0.82,
                "observations": {"blade_edge": "不可判断"},
                "issues": [],
                "positives": [],
            }
        ],
        "action_phase_summary": {"detected_phases": ["起跳"]},
        "overall_raw_text": "动作证据基本清楚。",
    }


class VisionQualityTests(unittest.TestCase):
    def test_complete_payload_scores_high_without_warnings(self) -> None:
        quality = evaluate_vision_payload_quality(_valid_payload())

        self.assertGreaterEqual(quality["json_validity_factor"], 0.9)
        self.assertGreaterEqual(quality["schema_completeness"], 0.9)
        self.assertEqual(quality["warnings"], [])

    def test_missing_frame_analysis_caps_json_validity(self) -> None:
        payload = {
            "data_quality_hint": "good",
            "action_phase_summary": {"detected_phases": []},
            "overall_raw_text": "缺少逐帧分析。",
        }

        quality = evaluate_vision_payload_quality(payload)

        self.assertLessEqual(quality["json_validity_factor"], 0.3)
        self.assertIn("vision_quality_missing_frame_analysis", quality["warnings"])

    def test_poor_quality_high_confidence_blade_edge_warns_and_downweights(self) -> None:
        payload = _valid_payload()
        payload["data_quality_hint"] = "poor"
        assert isinstance(payload["frame_analysis"], list)
        frame = payload["frame_analysis"][0]
        assert isinstance(frame, dict)
        frame["confidence"] = 0.92
        frame["observations"] = {"blade_edge": "外刃"}

        quality = evaluate_vision_payload_quality(payload)

        self.assertIn("vision_quality_poor_quality_high_confidence_blade_edge", quality["warnings"])
        self.assertLessEqual(quality["json_validity_factor"], 0.65)

    def test_poor_quality_uncertain_blade_edge_does_not_warn(self) -> None:
        payload = _valid_payload()
        payload["data_quality_hint"] = "poor"
        assert isinstance(payload["frame_analysis"], list)
        frame = payload["frame_analysis"][0]
        assert isinstance(frame, dict)
        frame["confidence"] = 0.95
        frame["observations"] = {"blade_edge": "不可判断"}

        quality = evaluate_vision_payload_quality(payload)

        self.assertNotIn("vision_quality_poor_quality_high_confidence_blade_edge", quality["warnings"])
        self.assertGreaterEqual(quality["json_validity_factor"], 0.9)

    def test_missing_required_frame_fields_reduce_completeness(self) -> None:
        payload = {
            "data_quality_hint": "partial",
            "frame_analysis": [{"frame_id": "frame_0001", "observations": {}}],
            "action_phase_summary": {},
            "overall_raw_text": "",
        }

        quality = evaluate_vision_payload_quality(payload)

        self.assertLess(quality["schema_completeness"], 0.8)
        self.assertLessEqual(quality["json_validity_factor"], 0.8)
        self.assertIn("vision_quality_missing_phase_frame_0001", quality["warnings"])
        self.assertIn("vision_quality_missing_confidence_frame_0001", quality["warnings"])

    def test_non_object_payload_returns_zero_quality(self) -> None:
        quality = evaluate_vision_payload_quality(None)  # type: ignore[arg-type]

        self.assertEqual(quality["json_validity_factor"], 0.0)
        self.assertEqual(quality["schema_completeness"], 0.0)
        self.assertEqual(quality["warnings"], ["vision_payload_not_object"])


if __name__ == "__main__":
    unittest.main()
