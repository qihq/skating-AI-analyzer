from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.provider_metrics import summarize_provider_metrics


class ProviderMetricsTests(unittest.TestCase):
    def test_empty_inputs_return_zeroed_summary(self) -> None:
        report = summarize_provider_metrics([], [])

        self.assertEqual(report["summary"]["provider_count"], 0)
        self.assertEqual(report["summary"]["sample_count"], 0)
        self.assertEqual(report["providers"], {})
        self.assertEqual(report["recommendations"], [])
        json.dumps(report, ensure_ascii=False)

    def test_single_provider_metrics_are_aggregated(self) -> None:
        vision_structured_items = [
            {
                "provider": "qwen",
                "json_validity_factor": 0.9,
                "effective_weight": 0.8,
                "quality_flags": [],
            },
            {
                "provider": "qwen",
                "json_validity_factor": 0.7,
                "effective_weight": 0.4,
                "quality_flags": ["vision_fallback_to_frames"],
            },
        ]
        cross_validation_items = [
            {"conflict_level": "none"},
            {"conflict_level": "high", "fusion_diagnostics": {"path_b": {"available": False}}},
        ]

        report = summarize_provider_metrics(vision_structured_items, cross_validation_items)

        qwen = report["providers"]["qwen"]
        self.assertEqual(report["summary"]["provider_count"], 1)
        self.assertEqual(report["summary"]["sample_count"], 2)
        self.assertAlmostEqual(qwen["json_valid_rate"], 0.5)
        self.assertAlmostEqual(qwen["avg_effective_weight"], 0.6)
        self.assertAlmostEqual(qwen["conflict_rate"], 0.5)
        self.assertAlmostEqual(qwen["failure_rate"], 0.5)
        self.assertIn("reduce_weight:qwen", report["recommendations"])
        json.dumps(report, ensure_ascii=False)

    def test_multi_provider_metrics_cover_fusion_and_fallback_signals(self) -> None:
        vision_structured_items = [
            {
                "fusion_decisions": [
                    {
                        "candidates": [
                            {
                                "provider": "qwen",
                                "factors": {"json_validity_factor": 0.95},
                                "effective_weight": 0.72,
                                "rule_flags": [],
                            },
                            {
                                "provider": "doubao",
                                "factors": {"json_validity_factor": 0.45},
                                "effective_weight": 0.28,
                                "rule_flags": ["rule_high_confidence_key_frame_conflict"],
                            },
                        ]
                    }
                ],
                "model_results": [
                    {
                        "provider": "qwen",
                        "quality": {"json_validity_factor": 0.95},
                        "base_factors": {"provider_base_weight": 1.0, "model_confidence": 0.9},
                    },
                    {
                        "provider": "doubao",
                        "quality": {"json_validity_factor": 0.45},
                        "base_factors": {"provider_base_weight": 0.7, "model_confidence": 0.5},
                    },
                ],
            },
            {
                "provider": "openai_compatible",
                "quality": {"json_validity_factor": 0.85},
                "effective_weight": 0.6,
                "quality_flags": ["vision_weighted_fusion_fallback_to_vote"],
            },
        ]
        cross_validation_items = [
            {"conflict_level": "high", "fusion_diagnostics": {"needs_human_review": True}},
            {"conflict_level": "none"},
        ]

        report = summarize_provider_metrics(vision_structured_items, cross_validation_items)

        self.assertEqual(report["summary"]["provider_count"], 3)
        self.assertGreater(report["summary"]["conflict_rate"], 0)
        self.assertGreater(report["summary"]["failure_rate"], 0)
        self.assertIn("qwen", report["providers"])
        self.assertIn("doubao", report["providers"])
        self.assertIn("openai_compatible", report["providers"])
        self.assertIn("review_conflict_patterns:doubao", report["recommendations"])
        self.assertIn("prioritize_fallback_resilience", report["recommendations"])
        json.dumps(report, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
