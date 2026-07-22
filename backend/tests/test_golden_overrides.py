from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class GoldenOverrideTests(unittest.TestCase):
    def test_normalizes_legacy_bboxes_with_frame_metadata(self) -> None:
        from app.services.golden_overrides import normalize_golden_label

        label = {
            "revision": 2,
            "keyframes": {"T": 1.2, "A": 1.5, "L": 1.8},
            "target_bboxes": {"0": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.5}},
        }
        result = normalize_golden_label(
            label,
            {
                "id": "run-1",
                "analysis_id": "analysis-1",
                "result_json": {
                    "sampled_frames": [{"frame_id": "frame_0001", "timestamp": 1.0}],
                    "semantic_frames": [{"frame_id": "semantic_0001", "timestamp": 1.5}],
                    "input_window": {
                        "input_window_mode": "manual_window",
                        "input_window_start_sec": 0.8,
                        "input_window_end_sec": 2.2,
                    },
                },
            },
        )

        self.assertEqual(result["tracking_anchors"][0]["source_frame_id"], "sampled:frame_0001")
        self.assertEqual(result["tracking_anchors"][0]["timestamp_sec"], 1.0)
        self.assertEqual(result["keyframes"]["T"]["timestamp_sec"], 1.2)
        self.assertEqual(result["action_window"], {"start_sec": 0.8, "end_sec": 2.2})

        semantic = normalize_golden_label(
            {
                **label,
                "target_bboxes": {
                    "semantic:semantic_0001": {"x": 0.2, "y": 0.1, "width": 0.2, "height": 0.6}
                },
            },
            {
                "id": "run-1",
                "analysis_id": "analysis-1",
                "result_json": {
                    "semantic_frames": [{"frame_id": "semantic_0001", "timestamp": 1.5}]
                },
            },
        )
        self.assertEqual(semantic["tracking_anchors"][0]["source_frame_id"], "semantic:semantic_0001")
        self.assertEqual(semantic["tracking_anchors"][0]["timestamp_sec"], 1.5)

    def test_rejects_invalid_keyframe_order_and_bbox(self) -> None:
        from app.services.golden_overrides import GoldenOverrideValidationError, validate_golden_override

        with self.assertRaises(GoldenOverrideValidationError):
            validate_golden_override(
                {
                    "keyframes": {
                        "T": {"timestamp_sec": 2.0},
                        "A": {"timestamp_sec": 1.5},
                        "L": {"timestamp_sec": 2.5},
                    },
                    "tracking_anchors": [],
                }
            )

    def test_requires_profile_keyframes_before_apply(self) -> None:
        from app.services.golden_overrides import GoldenOverrideValidationError, validate_golden_override

        with self.assertRaises(GoldenOverrideValidationError):
            validate_golden_override(
                {
                    "analysis_profile": "jump",
                    "keyframes": {"T": {"timestamp_sec": 1.0}, "L": {"timestamp_sec": 2.0}},
                    "tracking_anchors": [],
                }
            )

    def test_rejects_keyframes_outside_action_window(self) -> None:
        from app.services.golden_overrides import GoldenOverrideValidationError, validate_golden_override

        with self.assertRaises(GoldenOverrideValidationError):
            validate_golden_override(
                {
                    "analysis_profile": "jump",
                    "action_window": {"start_sec": 1.0, "end_sec": 2.0},
                    "keyframes": {
                        "T": {"timestamp_sec": 0.9},
                        "A": {"timestamp_sec": 1.5},
                        "L": {"timestamp_sec": 1.9},
                    },
                    "tracking_anchors": [],
                }
            )
        with self.assertRaises(GoldenOverrideValidationError):
            validate_golden_override(
                {
                    "keyframes": {},
                    "tracking_anchors": [
                        {"timestamp_sec": 1.0, "bbox": {"x": 0.9, "y": 0.1, "width": 0.2, "height": 0.5}}
                    ],
                }
            )

    def test_hash_is_deterministic_and_retry_stage_uses_earliest_change(self) -> None:
        from app.services.golden_overrides import golden_override_hash, golden_retry_stage

        first = {"keyframes": {"T": {"timestamp_sec": 1.0}}, "tracking_anchors": []}
        reordered = {"tracking_anchors": [], "keyframes": {"T": {"timestamp_sec": 1.0}}}
        self.assertEqual(golden_override_hash(first), golden_override_hash(reordered))
        self.assertEqual(
            golden_override_hash({**first, "source_label_revision": 1}),
            golden_override_hash({**first, "source_label_revision": 2, "applied_at": "later"}),
        )
        self.assertEqual(golden_retry_stage(None, {"action_window": {"start_sec": 1, "end_sec": 3}}), "extract_frames")
        self.assertEqual(golden_retry_stage(None, {"tracking_anchors": [{"timestamp_sec": 1, "bbox": {}}]}), "pose")
        self.assertEqual(golden_retry_stage(None, {"keyframes": {"T": {"timestamp_sec": 1}}}), "biomechanics")

    def test_applies_keyframes_and_preserves_automatic_prediction(self) -> None:
        from app.services.golden_overrides import apply_golden_keyframes

        bio, resolved = apply_golden_keyframes(
            {"key_frame_timestamps": {"T": 1.1, "A": 1.6, "L": 2.1}},
            {
                "source": "video_ai",
                "selected": [
                    {"phase_code": "takeoff", "timestamp": 1.1},
                    {"phase_code": "apex", "timestamp": 1.6},
                    {"phase_code": "landing", "timestamp": 2.1},
                ],
            },
            {
                "source_label_revision": 3,
                "keyframes": {
                    "T": {"timestamp_sec": 1.2},
                    "A": {"timestamp_sec": 1.5},
                    "L": {"timestamp_sec": 2.0},
                },
            },
        )

        self.assertEqual(bio["key_frame_timestamps"], {"T": 1.2, "A": 1.5, "L": 2.0})
        self.assertEqual(bio["key_frames"], {"T": "golden_T", "A": "golden_A", "L": "golden_L"})
        self.assertEqual(resolved["source"], "golden_override")
        self.assertEqual(resolved["automatic_prediction"]["source"], "video_ai")
        self.assertTrue(all(item["selection_reason"] == "golden_override" for item in resolved["selected"]))


if __name__ == "__main__":
    unittest.main()
