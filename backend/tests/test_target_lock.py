from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.target_lock import build_target_lock_payload, build_target_preview, validate_manual_bbox


class TargetLockTests(unittest.TestCase):
    def test_build_target_lock_payload_accepts_manual_bbox(self) -> None:
        preview = build_target_preview("analysis-1", ["frame_0001.jpg"])

        payload = build_target_lock_payload(preview, manual_bbox={"x": 0.2, "y": 0.1, "w": 0.3, "h": 0.5})

        self.assertEqual(payload["status"], "manual")
        self.assertTrue(payload["manual_override"])
        self.assertEqual(payload["lock_confidence"], 1.0)
        self.assertEqual(payload["selected_bbox"], {"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.5})
        self.assertEqual(payload["candidates"], preview.candidates)

    def test_build_target_preview_returns_no_person_without_confident_candidates(self) -> None:
        preview = build_target_preview("analysis-1", ["frame_0001.jpg"])

        self.assertEqual(preview.target_lock_status, "no_person_detected")
        self.assertIsNone(preview.auto_candidate_id)
        self.assertEqual(preview.lock_confidence, 0.0)
        self.assertEqual(preview.candidates, [])

    def test_build_target_preview_rejects_all_low_confidence_candidates(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg"],
            existing_target_lock={
                "candidates": [
                    {
                        "id": "candidate_low",
                        "bbox": {"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.5},
                        "confidence": 0.14,
                        "source": "detector",
                    }
                ]
            },
        )

        self.assertEqual(preview.target_lock_status, "no_person_detected")
        self.assertIsNone(preview.auto_candidate_id)
        self.assertEqual(preview.lock_confidence, 0.0)

    def test_validate_manual_bbox_rejects_tiny_bbox(self) -> None:
        with self.assertRaises(AnalysisPipelineError) as raised:
            validate_manual_bbox({"x": 0.2, "y": 0.1, "w": 0.01, "h": 0.5})

        self.assertEqual(raised.exception.code, AnalysisErrorCode.TARGET_BBOX_INVALID)


if __name__ == "__main__":
    unittest.main()
