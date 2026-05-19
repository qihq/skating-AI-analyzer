from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.auto_eval import build_auto_eval_payload


def _bio_candidates(
    *,
    t_frame: str = "frame_0004",
    a_frame: str = "frame_0006",
    l_frame: str = "frame_0008",
    confidence: float = 0.9,
) -> dict[str, object]:
    return {
        "quality_flags": [],
        "key_frame_candidates": {
            "T": {"frame_id": t_frame, "timestamp": 0.3, "confidence": confidence, "evidence": {}, "warnings": []},
            "A": {"frame_id": a_frame, "timestamp": 0.5, "confidence": confidence, "evidence": {}, "warnings": []},
            "L": {"frame_id": l_frame, "timestamp": 0.7, "confidence": confidence, "evidence": {}, "warnings": []},
            "quality_flags": [],
        },
    }


def _vision(phases: list[tuple[str, str, float]]) -> dict[str, object]:
    return {
        "frame_analysis": [
            {
                "frame_id": frame_id,
                "phase": phase,
                "confidence": confidence,
                "issues": [],
                "positives": [],
            }
            for frame_id, phase, confidence in phases
        ],
        "action_phase_summary": {"detected_phases": [phase for _, phase, _ in phases]},
        "quality_flags": [],
    }


class AutoEvalTests(unittest.TestCase):
    def test_valid_jump_payload_has_order_and_phase_sequence_valid(self) -> None:
        payload = build_auto_eval_payload(
            _bio_candidates(),
            _vision(
                [
                    ("frame_0003", "准备", 0.8),
                    ("frame_0004", "起跳", 0.9),
                    ("frame_0006", "腾空", 0.9),
                    ("frame_0008", "落冰", 0.9),
                    ("frame_0009", "滑出", 0.8),
                ]
            ),
            {"quality_flags": []},
            "jump",
        )

        self.assertEqual(payload["auto_eval_version"], "v1")
        self.assertTrue(payload["key_frame_order_valid"])
        self.assertTrue(payload["phase_sequence_valid"])
        self.assertEqual(payload["high_confidence_conflicts"], [])
        self.assertEqual(payload["key_frame_signature"], "T:frame_0004@0.90|A:frame_0006@0.90|L:frame_0008@0.90")
        json.dumps(payload, ensure_ascii=False)

    def test_invalid_key_frame_order_is_flagged(self) -> None:
        payload = build_auto_eval_payload(
            _bio_candidates(t_frame="frame_0008", a_frame="frame_0006", l_frame="frame_0004"),
            _vision([("frame_0004", "起跳", 0.9), ("frame_0006", "腾空", 0.9), ("frame_0008", "落冰", 0.9)]),
            None,
            "jump",
        )

        self.assertFalse(payload["key_frame_order_valid"])
        self.assertIn("auto_eval_key_frame_order_invalid", payload["data_quality_flags"])
        self.assertTrue(payload["key_frame_signature"].startswith("T:frame_0008"))

    def test_missing_candidates_returns_stable_missing_signature(self) -> None:
        payload = build_auto_eval_payload(
            {"quality_flags": ["bio_low_signal"]},
            _vision([("frame_0001", "起跳", 0.8)]),
            {"quality_flags": ["motion_missing"]},
            "jump",
        )

        self.assertIsNone(payload["key_frame_order_valid"])
        self.assertEqual(payload["key_frame_signature"], "missing")
        self.assertIn("auto_eval_missing_key_frame_candidates", payload["data_quality_flags"])
        self.assertIn("bio_low_signal", payload["data_quality_flags"])
        self.assertIn("motion_missing", payload["data_quality_flags"])
        json.dumps(payload)

    def test_high_confidence_visual_phase_conflict_is_reported(self) -> None:
        payload = build_auto_eval_payload(
            _bio_candidates(confidence=0.92),
            _vision(
                [
                    ("frame_0004", "落冰", 0.96),
                    ("frame_0006", "腾空", 0.9),
                    ("frame_0008", "落冰", 0.9),
                ]
            ),
            None,
            "jump",
        )

        self.assertFalse(payload["phase_sequence_valid"])
        self.assertEqual(len(payload["high_confidence_conflicts"]), 1)
        conflict = payload["high_confidence_conflicts"][0]
        self.assertEqual(conflict["label"], "T")
        self.assertEqual(conflict["expected_phase"], "takeoff")
        self.assertEqual(conflict["vision_phase"], "landing")
        self.assertIn("auto_eval_high_confidence_conflict", payload["data_quality_flags"])
        self.assertIn("auto_eval_phase_sequence_invalid", payload["data_quality_flags"])


if __name__ == "__main__":
    unittest.main()
