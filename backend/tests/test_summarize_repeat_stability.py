from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.summarize_repeat_stability import summarize_repeat_stability


class SummarizeRepeatStabilityTests(unittest.TestCase):
    def test_dedupes_analysis_ids_and_reports_jump_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "a.json"
            second = Path(tmpdir) / "b.json"
            first.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "jump.mp4",
                                "analysis_id": "run-1",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "force_score": 70,
                                "keyframes": {
                                    "T": {"timestamp": 1.0},
                                    "A": {"timestamp": 1.2},
                                    "L": {"timestamp": 1.4},
                                    "quality_flags": [
                                        "person_tracker_target_lost",
                                        "semantic_keyframes_unreliable_after_refinement",
                                        "tal_candidate_landing_geometry_weak",
                                    ],
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "jump.mp4",
                                "analysis_id": "run-1",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "force_score": 70,
                                "keyframes": {
                                    "T": {"timestamp": 9.0},
                                    "A": {"timestamp": 9.2},
                                    "L": {"timestamp": 9.4},
                                },
                            },
                            {
                                "video": "jump.mp4",
                                "analysis_id": "run-2",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "force_score": 72,
                                "keyframes": {
                                    "T": {"timestamp": 1.05},
                                    "A": {"timestamp": 1.25},
                                    "L": {"timestamp": 1.55},
                                    "quality_flags": ["keyframe_candidates_motion_fallback"],
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_repeat_stability([first, second], profile="jump", frontend_url="http://localhost:8080/")

        self.assertEqual(summary["completed_unique_analysis_count"], 2)
        self.assertEqual(summary["frontend_url"], "http://localhost:8080/")
        self.assertEqual(summary["repeat_group_count"], 1)
        group = summary["repeat_groups"][0]
        self.assertEqual(group["keyframe_ranges_sec"], {"T": 0.05, "A": 0.05, "L": 0.15})
        self.assertFalse(group["within_0_1_sec"])
        self.assertEqual(group["force_score_range"], 2.0)
        self.assertEqual(group["compare_url"], "http://localhost:8080/compare/run-1/run-2")
        self.assertEqual(
            group["pairwise_comparisons"],
            [
                {
                    "analysis_id_a": "run-1",
                    "analysis_id_b": "run-2",
                    "compare_url": "http://localhost:8080/compare/run-1/run-2",
                    "keyframe_delta_sec": {"T": 0.05, "A": 0.05, "L": 0.15},
                    "max_abs_keyframe_delta_sec": 0.15,
                    "force_score_delta": 2.0,
                }
            ],
        )
        self.assertEqual(
            group["stability_risk_hints"],
            [
                "keyframe_time_unstable",
                "tracking_or_pose_signal",
                "semantic_or_profile_signal",
                "keyframe_candidate_or_fusion_signal",
                "keyframe_instability_with_tracking_signal",
                "keyframe_instability_with_semantic_signal",
            ],
        )
        self.assertEqual(summary["stability_risk_hint_counts"]["keyframe_time_unstable"], 1)

    def test_spin_profile_uses_spin_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "spin.json"
            path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "spin.mp4",
                                "analysis_id": "spin-a",
                                "status": "completed",
                                "analysis_profile": "spin",
                                "force_score": 80,
                                "keyframes": {
                                    "quality_flags": ["keyframe_candidates_not_applicable_for_profile"],
                                    "profile_keyframes": {
                                        "\u65cb\u8f6c\u5165": {"timestamp": 2.0},
                                        "\u65cb\u8f6c\u4e2d": {"timestamp": 3.0},
                                        "\u65cb\u8f6c\u51fa": {"timestamp": 4.0},
                                    }
                                },
                            },
                            {
                                "video": "spin.mp4",
                                "analysis_id": "spin-b",
                                "status": "completed",
                                "analysis_profile": "spin",
                                "force_score": 81,
                                "keyframes": {
                                    "quality_flags": ["keyframe_candidates_not_applicable_for_profile"],
                                    "profile_keyframes": {
                                        "\u65cb\u8f6c\u5165": {"timestamp": 2.03},
                                        "\u65cb\u8f6c\u4e2d": {"timestamp": 3.02},
                                        "\u65cb\u8f6c\u51fa": {"timestamp": 4.04},
                                    }
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_repeat_stability([path], profile="spin")

        group = summary["repeat_groups"][0]
        self.assertEqual(group["keyframe_keys"], ["\u65cb\u8f6c\u5165", "\u65cb\u8f6c\u4e2d", "\u65cb\u8f6c\u51fa"])
        self.assertEqual(
            group["keyframe_ranges_sec"],
            {
                "\u65cb\u8f6c\u5165": 0.03,
                "\u65cb\u8f6c\u4e2d": 0.02,
                "\u65cb\u8f6c\u51fa": 0.04,
            },
        )
        self.assertTrue(group["within_0_1_sec"])
        self.assertEqual(group["stability_risk_hints"], [])
        self.assertEqual(summary["stability_risk_hint_counts"], {})

    def test_spin_profile_accepts_legacy_mojibake_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "spin-legacy.json"
            path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "spin.mp4",
                                "analysis_id": "spin-a",
                                "status": "completed",
                                "analysis_profile": "spin",
                                "keyframes": {
                                    "profile_keyframes": {
                                        "\xe6\u2014\u2039\xe8\xbd\xac\xe5\u2026\xa5": {"timestamp": 2.0},
                                        "\xe6\u2014\u2039\xe8\xbd\xac\xe4\xb8\xad": {"timestamp": 3.0},
                                        "\xe6\u2014\u2039\xe8\xbd\xac\xe5\u2021\xba": {"timestamp": 4.0},
                                    }
                                },
                            },
                            {
                                "video": "spin.mp4",
                                "analysis_id": "spin-b",
                                "status": "completed",
                                "analysis_profile": "spin",
                                "keyframes": {
                                    "profile_keyframes": {
                                        "\xe6\u2014\u2039\xe8\xbd\xac\xe5\u2026\xa5": {"timestamp": 2.04},
                                        "\xe6\u2014\u2039\xe8\xbd\xac\xe4\xb8\xad": {"timestamp": 3.07},
                                        "\xe6\u2014\u2039\xe8\xbd\xac\xe5\u2021\xba": {"timestamp": 4.08},
                                    }
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_repeat_stability([path], profile="spin")

        group = summary["repeat_groups"][0]
        self.assertEqual(group["max_keyframe_range_sec"], 0.08)
        self.assertTrue(group["within_0_1_sec"])

    def test_step_sequence_profile_uses_step_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "step.json"
            path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "step.mp4",
                                "analysis_id": "step-a",
                                "status": "completed",
                                "analysis_profile": "step_sequence",
                                "keyframes": {
                                    "profile_keyframes": {
                                        "\u6b65\u6cd5\u5e8f\u5217": {"timestamp": 1.0},
                                    }
                                },
                            },
                            {
                                "video": "step.mp4",
                                "analysis_id": "step-b",
                                "status": "completed",
                                "analysis_profile": "step_sequence",
                                "keyframes": {
                                    "profile_keyframes": {
                                        "\u6b65\u6cd5\u5e8f\u5217": {"timestamp": 1.09},
                                    }
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_repeat_stability([path], profile="step")

        group = summary["repeat_groups"][0]
        self.assertEqual(group["analysis_profile"], "step")
        self.assertEqual(group["keyframe_ranges_sec"], {"\u6b65\u6cd5\u5e8f\u5217": 0.09})
        self.assertTrue(group["within_0_1_sec"])

    def test_reports_profile_drift_across_same_video_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "drift.json"
            path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "mixed.mp4",
                                "analysis_id": "run-jump",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "force_score": 76,
                                "quality_flags": ["mixed_action_profile_inferred_jump_from_motion"],
                            },
                            {
                                "video": "mixed.mp4",
                                "analysis_id": "run-step",
                                "status": "completed",
                                "analysis_profile": "step",
                                "force_score": 70,
                                "quality_flags": ["mixed_action_profile_overridden_by_video_ai"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_repeat_stability([path])

        self.assertEqual(summary["profile_drift_group_count"], 1)
        drift = summary["profile_drift_groups"][0]
        self.assertEqual(drift["video"], "mixed.mp4")
        self.assertEqual(drift["profile_counts"], {"jump": 1, "step": 1})
        self.assertEqual(
            drift["stability_risk_hints"],
            ["profile_drift", "tal_membership_unstable", "semantic_or_profile_signal"],
        )
        self.assertEqual(summary["stability_risk_hint_counts"]["profile_drift"], 1)

    def test_skips_unreadable_json_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            good = Path(tmpdir) / "good.json"
            bad = Path(tmpdir) / "bad.json"
            good.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "jump.mp4",
                                "analysis_id": "run-1",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "keyframes": {"T": {"timestamp": 1.0}},
                            },
                            {
                                "video": "jump.mp4",
                                "analysis_id": "run-2",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "keyframes": {"T": {"timestamp": 1.04}},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bad.write_bytes(b"\xff\xfe{not-json")

            summary = summarize_repeat_stability([good, bad], profile="jump")

        self.assertEqual(summary["repeat_group_count"], 1)
        self.assertEqual(len(summary["skipped_input_files"]), 1)
        self.assertEqual(summary["skipped_input_files"][0]["path"], str(bad))


if __name__ == "__main__":
    unittest.main()
