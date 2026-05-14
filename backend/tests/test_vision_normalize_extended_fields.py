from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video import FramePayload
from app.services.vision import normalize_vision_payload


class VisionNormalizeExtendedFieldsTests(unittest.TestCase):
    def test_preserves_camera_and_key_frame_agreement_fields(self) -> None:
        frame_payloads = [
            FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA"),
            FramePayload(frame_id="frame_0002", data_url="data:image/jpeg;base64,BBB"),
        ]
        payload = {
            "data_quality_hint": "partial",
            "camera_view": "diagonal_front",
            "camera_view_confidence": 0.82,
            "frame_analysis": [
                {
                    "frame_id": "frame_0001",
                    "phase": "起跳",
                    "phase_confidence": 0.91,
                    "key_frame_agreement": "T",
                    "confidence": 0.88,
                },
                {
                    "frame_id": "frame_0002",
                    "phase": "落冰",
                    "phase_confidence": 0.77,
                    "key_frame_agreement": "shifted",
                    "confidence": 0.7,
                },
            ],
            "action_phase_summary": {
                "detected_phases": ["起跳", "落冰"],
                "weakest_phase": "落冰",
                "strongest_phase": "起跳",
                "key_frame_agreement": {"T": "agree", "A": "shifted", "L": "disagree"},
            },
            "overall_raw_text": "ok",
        }

        normalized = normalize_vision_payload(payload, frame_payloads)

        self.assertEqual(normalized["data_quality_hint"], "partial")
        self.assertEqual(normalized["camera_view"], "diagonal_front")
        self.assertEqual(normalized["camera_view_confidence"], 0.82)
        self.assertEqual(normalized["frame_analysis"][0]["phase_confidence"], 0.91)
        self.assertEqual(normalized["frame_analysis"][0]["key_frame_agreement"], "T")
        self.assertEqual(normalized["frame_analysis"][1]["phase_confidence"], 0.77)
        self.assertEqual(normalized["frame_analysis"][1]["key_frame_agreement"], "shifted")
        self.assertEqual(
            normalized["action_phase_summary"]["key_frame_agreement"],
            {"T": "agree", "A": "shifted", "L": "disagree"},
        )

    def test_invalid_enums_degrade_to_unknown_or_unavailable(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA")]
        payload = {
            "data_quality_hint": "bad",
            "camera_view": "overhead",
            "camera_view_confidence": 2.5,
            "frame_analysis": [
                {
                    "frame_id": "frame_0001",
                    "phase": "起跳",
                    "phase_confidence": "not-a-number",
                    "key_frame_agreement": "maybe",
                    "confidence": 0.8,
                }
            ],
            "action_phase_summary": {
                "key_frame_agreement": {"T": "yes", "A": "agree", "L": None},
            },
            "overall_raw_text": "ok",
        }

        normalized = normalize_vision_payload(payload, frame_payloads)

        self.assertNotIn("data_quality_hint", normalized)
        self.assertEqual(normalized["camera_view"], "unknown")
        self.assertEqual(normalized["camera_view_confidence"], 1.0)
        self.assertEqual(normalized["frame_analysis"][0]["phase_confidence"], 0.0)
        self.assertEqual(normalized["frame_analysis"][0]["key_frame_agreement"], "unavailable")
        self.assertEqual(
            normalized["action_phase_summary"]["key_frame_agreement"],
            {"T": "unavailable", "A": "agree", "L": "unavailable"},
        )


if __name__ == "__main__":
    unittest.main()
