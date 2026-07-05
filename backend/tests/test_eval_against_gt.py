from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "scripts"))

from eval_against_gt import evaluate_manifest


class EvalAgainstGoldenTests(unittest.TestCase):
    def test_evaluates_keyframe_and_identity_metrics_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prediction = {
                "resolved_keyframes": {
                    "selected": [
                        {"phase_code": "takeoff", "timestamp": 1.08},
                        {"phase_code": "air", "timestamp": 1.52},
                        {"phase_code": "landing", "timestamp": 2.1},
                    ]
                },
                "bbox_per_frame": [
                    {"frame_index": 10, "x": 0.10, "y": 0.20, "width": 0.20, "height": 0.40},
                    {"frame_index": 11, "x": 0.62, "y": 0.20, "width": 0.20, "height": 0.40},
                    {"frame_index": 12, "x": 0.63, "y": 0.20, "width": 0.20, "height": 0.40},
                ],
                "quality_flags": ["person_tracker_appearance_relock_rejected"],
            }
            prediction_path = root / "prediction.json"
            prediction_path.write_text(json.dumps(prediction), encoding="utf-8")
            manifest = {
                "samples": [
                    {
                        "id": "sample-1",
                        "video_path": "sample.mp4",
                        "skater_id": "child-a",
                        "action_type": "jump",
                        "fps": 25,
                        "prediction_path": "prediction.json",
                        "keyframes": {"T": 1.0, "A": 1.5, "L": 2.0},
                        "target_bboxes": {
                            "10": {"x": 0.10, "y": 0.20, "width": 0.20, "height": 0.40},
                            "11": {"x": 0.10, "y": 0.20, "width": 0.20, "height": 0.40},
                            "12": {"x": 0.10, "y": 0.20, "width": 0.20, "height": 0.40},
                        },
                    }
                ]
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = evaluate_manifest(manifest_path, iou_threshold=0.3, switch_frames=2)

        self.assertEqual(report["summary"]["sample_count"], 1)
        self.assertEqual(report["summary"]["keyframe_median_error_sec"], 0.08)
        self.assertEqual(report["summary"]["identity_switches"], 1)
        self.assertEqual(report["summary"]["failure_count"], 1)
        self.assertIn("unspecified", report["stratum_summary"])
        self.assertEqual(report["stratum_summary"]["unspecified"]["sample_count"], 1)
        self.assertEqual(report["failures"][0]["failure_reasons"], ["identity_switch", "identity_accuracy_low"])
        self.assertEqual(report["top_quality_flags"][0], {"flag": "person_tracker_appearance_relock_rejected", "count": 1})
        self.assertEqual(report["samples"][0]["identity"]["identity_accuracy"], 0.3333)

    def test_evaluates_spin_phase_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prediction_path = root / "prediction.json"
            prediction_path.write_text(
                json.dumps(
                    {
                        "resolved_keyframes": {
                            "selected": [
                                {"phase_code": "spin_entry", "timestamp": 4.9},
                                {"phase_code": "spin_main", "timestamp": 5.5},
                                {"phase_code": "spin_exit", "timestamp": 6.2},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "samples": [
                            {
                                "id": "spin-1",
                                "video_path": "spin.mp4",
                                "action_type": "spin",
                                "fps": 25,
                                "prediction_path": "prediction.json",
                                "keyframes": {"spin_entry": 5.0, "spin_main": 5.5, "spin_exit": 6.0},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = evaluate_manifest(manifest_path, iou_threshold=0.3, switch_frames=2)

        self.assertEqual(report["summary"]["sample_count"], 1)
        self.assertEqual(report["samples"][0]["keyframes"]["errors_sec"], {"spin_entry": 0.1, "spin_main": 0.0, "spin_exit": 0.2})

    def test_groups_samples_by_stratum_and_reports_expected_flag_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good_prediction = root / "good.json"
            good_prediction.write_text(
                json.dumps(
                    {
                        "resolved_keyframes": {"selected": [{"phase_code": "takeoff", "timestamp": 1.0}]},
                        "quality_flags": ["expected_review"],
                    }
                ),
                encoding="utf-8",
            )
            bad_prediction = root / "bad.json"
            bad_prediction.write_text(
                json.dumps(
                    {
                        "resolved_keyframes": {"selected": [{"phase_code": "takeoff", "timestamp": 1.7}]},
                        "quality_flags": [],
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "samples": [
                            {
                                "id": "ok",
                                "video_path": "ok.mp4",
                                "prediction_path": "good.json",
                                "stratum": "single_skater",
                                "keyframes": {"T": 1.0},
                                "expected_review_flags": ["expected_review"],
                            },
                            {
                                "id": "bad",
                                "video_path": "bad.mp4",
                                "prediction_path": "bad.json",
                                "stratum": "multi_skater",
                                "keyframes": {"T": 1.0},
                                "expected_review_flags": ["needs_review"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = evaluate_manifest(manifest_path, iou_threshold=0.3, switch_frames=2)

        self.assertEqual(report["stratum_summary"]["single_skater"]["failure_count"], 0)
        self.assertEqual(report["stratum_summary"]["multi_skater"]["failure_count"], 1)
        self.assertEqual(report["failures"][0]["sample_id"], "bad")
        self.assertEqual(
            report["failures"][0]["failure_reasons"],
            ["keyframe_error_high", "missing_expected_review_flags"],
        )
        self.assertEqual(report["failures"][0]["failure_tags"], ["takeoff_late"])

    def test_reports_fixed_failure_tags_for_keyframe_direction_and_multi_person_pollution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prediction_path = root / "prediction.json"
            prediction_path.write_text(
                json.dumps(
                    {
                        "resolved_keyframes": {
                            "selected": [
                                {"phase_code": "takeoff", "timestamp": 0.4},
                                {"phase_code": "air", "timestamp": 1.7},
                                {"phase_code": "landing", "timestamp": 2.5},
                            ]
                        },
                        "bbox_per_frame": [
                            {"frame_index": 1, "x": 0.7, "y": 0.1, "width": 0.1, "height": 0.2},
                            {"frame_index": 2, "x": 0.7, "y": 0.1, "width": 0.1, "height": 0.2},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "samples": [
                            {
                                "id": "polluted",
                                "prediction_path": "prediction.json",
                                "stratum": "multi_skater",
                                "keyframes": {"T": 1.0, "A": 1.2, "L": 2.0},
                                "target_bboxes": {
                                    "1": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.2},
                                    "2": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.2},
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = evaluate_manifest(manifest_path, iou_threshold=0.3, switch_frames=1)

        self.assertEqual(
            report["failures"][0]["failure_tags"],
            ["identity_switch", "target_lost", "takeoff_early", "apex_drift", "landing_glideout", "multi_person_motion_pollution"],
        )


if __name__ == "__main__":
    unittest.main()
