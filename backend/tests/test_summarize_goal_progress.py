from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.summarize_goal_progress import summarize_goal_progress


class SummarizeGoalProgressTests(unittest.TestCase):
    def test_summarizes_jump_offsets_and_tracking_flags_from_diagnostics_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "diagnostics.json"
            path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video": "jump.mp4",
                                "analysis_id": "jump-1",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "force_score": 76,
                                "profile_keyframe_summary": {"complete": True, "coverage_score": 1.0},
                                "bio_effective_resolved_delta": {"T": 0.0, "A": 0.0, "L": 0.0},
                                "candidate_effective_resolved_delta": {"T": -0.03, "A": -0.25, "L": 0.32},
                                "trusted_candidate_effective_resolved_delta": {"T": -0.03, "A": -0.25, "L": 0.32},
                                "bio_motion_peak_delta": {"T": 0.05, "A": 0.3, "L": -0.2},
                                "candidate_motion_peak_delta": {"T": 0.02, "A": 0.1, "L": 0.1},
                                "effective_resolved_motion_peak_delta": {"T": 0.05, "A": 0.3, "L": -0.2},
                                "candidate_delta_untrusted": False,
                                "candidate_delta_untrusted_reasons": [],
                                "keyframe_candidate_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                                "semantic_flags": ["semantic_keyframe_refinement_delta_rejected"],
                                "target_quality_flags": [
                                    "person_tracker_target_lost",
                                    "person_tracker_detector_relocked",
                                    "person_tracker_manual_lock_relock_blocked",
                                    "person_tracker_manual_lock_fallback_blocked",
                                    "person_tracker_manual_lock_support_anchor_blocked",
                                ],
                                "pose_quality_flags": ["pose_manual_lock_unreliable_tracker_blocked"],
                                "data_quality_flags": ["pose_manual_lock_unreliable_tracker_blocked"],
                                "cross_validation": {"path_b_annotation_source": "semantic_manual_lock_blank_pose"},
                                "target_tracking_risk_flags": ["person_tracker_tiny_target_low_pose_tracking_risk"],
                                "tracker_rejection_reason_counts": {"area_ratio": 2, "weak_identity_support": 1},
                                "pose_tracked_ratio": 0.5,
                                "tracker_loss_ratio": 0.5,
                            },
                            {
                                "video": "step.mp4",
                                "analysis_id": "step-1",
                                "status": "completed",
                                "analysis_profile": "step",
                                "profile_keyframe_summary": {"complete": True, "coverage_score": 1.0},
                                "target_manual_review_flags": ["target_lock_zoomed_multiperson_manual_review"],
                                "target_auto_lock_blocked_flags": ["target_lock_auto_lock_blocked_by_manual_review"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_goal_progress([path])

        self.assertEqual(summary["completed_profile_counts"], {"jump": 1, "step": 1})
        self.assertEqual(summary["profile_keyframe_coverage"]["jump"]["complete_rate"], 1.0)
        self.assertEqual(summary["jump_tal"]["row_count"], 1)
        self.assertEqual(
            summary["jump_tal"]["candidate_vs_effective_resolved_delta"]["A"]["direction_counts"],
            {"early": 1},
        )
        self.assertEqual(
            summary["jump_tal"]["candidate_vs_effective_resolved_delta"]["L"]["direction_counts"],
            {"late": 1},
        )
        self.assertEqual(summary["jump_tal"]["largest_candidate_offset_samples"][0]["video"], "jump.mp4")
        self.assertEqual(summary["tracking"]["core_tracker_flag_counts"]["person_tracker_target_lost"], 1)
        self.assertEqual(summary["tracking"]["core_tracker_flag_counts"]["person_tracker_detector_relocked"], 1)
        self.assertEqual(summary["tracking"]["core_tracker_flag_counts"]["person_tracker_manual_lock_relock_blocked"], 1)
        self.assertEqual(summary["tracking"]["core_tracker_flag_counts"]["person_tracker_manual_lock_fallback_blocked"], 1)
        self.assertEqual(summary["tracking"]["core_tracker_flag_counts"]["person_tracker_manual_lock_support_anchor_blocked"], 1)
        self.assertEqual(
            summary["tracking"]["pose_identity_lock_flag_counts"]["pose_manual_lock_unreliable_tracker_blocked"],
            1,
        )
        self.assertEqual(
            summary["tracking"]["pose_identity_lock_flag_counts"]["semantic_pose_manual_lock_unaligned_blank_pose"],
            1,
        )
        self.assertEqual(
            summary["tracking"]["pose_identity_lock_samples"][0]["pose_identity_lock_flags"],
            [
                "pose_manual_lock_unreliable_tracker_blocked",
                "semantic_pose_manual_lock_unaligned_blank_pose",
            ],
        )
        self.assertEqual(summary["tracking"]["top_tracker_rejection_reasons"], {"area_ratio": 2, "weak_identity_support": 1})
        self.assertEqual(
            summary["tracking"]["top_target_manual_review_flags"],
            {"target_lock_zoomed_multiperson_manual_review": 1},
        )

    def test_accepts_batch_video_rows_and_limits_tal_to_jump(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch.json"
            path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "jump.mp4",
                                "analysis_id": "jump-1",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "keyframes": {
                                    "T": {"timestamp": 1.0},
                                    "A": {"timestamp": 1.2},
                                    "L": {"timestamp": 1.5},
                                    "complete": True,
                                    "profile_keyframe_complete": True,
                                    "profile_keyframe_coverage_score": 1.0,
                                },
                            },
                            {
                                "video": "spin.mp4",
                                "analysis_id": "spin-1",
                                "status": "completed",
                                "analysis_profile": "spin",
                                "keyframes": {
                                    "complete": False,
                                    "profile_keyframe_complete": True,
                                    "profile_keyframe_coverage_score": 1.0,
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_goal_progress([path])

        self.assertEqual(summary["completed_profile_counts"], {"jump": 1, "spin": 1})
        self.assertEqual(summary["jump_tal"]["row_count"], 1)
        self.assertEqual(summary["jump_tal"]["bio_vs_effective_resolved_delta"]["T"]["count"], 1)
        self.assertEqual(summary["profile_keyframe_coverage"]["spin"]["complete_rate"], 1.0)

    def test_reports_same_profile_compare_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch.json"
            path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "video": "jump-a.mp4",
                                "analysis_id": "jump-a",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "force_score": 70,
                                "profile_keyframe_summary": {"complete": True, "coverage_score": 1.0},
                            },
                            {
                                "video": "jump-b.mp4",
                                "analysis_id": "jump-b",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "force_score": 74,
                                "profile_keyframe_summary": {"complete": True, "coverage_score": 0.75},
                            },
                            {
                                "video": "step-a.mp4",
                                "analysis_id": "step-a",
                                "status": "completed",
                                "analysis_profile": "step",
                                "force_score": 80,
                                "profile_keyframe_summary": {"complete": True, "coverage_score": 1.0},
                            },
                            {
                                "video": "step-b.mp4",
                                "analysis_id": "step-b",
                                "status": "completed",
                                "analysis_profile": "step",
                                "force_score": 81,
                                "profile_keyframe_summary": {"complete": True, "coverage_score": 1.0},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_goal_progress(
                [path],
                frontend_url="http://localhost:8080/",
                sample_limit=1,
            )

        jump_pair = summary["same_profile_compare_candidates"]["jump"]["largest_delta"][0]
        self.assertEqual(jump_pair["compare_url"], "http://localhost:8080/compare/jump-a/jump-b")
        self.assertEqual(jump_pair["force_score_delta"], 4.0)
        self.assertEqual(jump_pair["profile_keyframe_coverage_delta"], -0.25)
        self.assertEqual(
            summary["same_profile_compare_candidates"]["jump"]["closest_match"][0]["compare_url"],
            "http://localhost:8080/compare/jump-a/jump-b",
        )
        step_pair = summary["same_profile_compare_candidates"]["step"]["closest_match"][0]
        self.assertEqual(step_pair["compare_url"], "http://localhost:8080/compare/step-a/step-b")
        self.assertEqual(step_pair["force_score_delta"], 1.0)
        self.assertEqual(step_pair["profile_keyframe_coverage_delta"], 0.0)

    def test_reports_profile_drift_that_changes_tal_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first.json"
            second = Path(tmpdir) / "second.json"
            first.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "mixed.mp4",
                                "analysis_id": "run-1",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "force_score": 76,
                                "keyframes": {
                                    "T": {"timestamp": 1.0},
                                    "A": {"timestamp": 1.4},
                                    "L": {"timestamp": 1.8},
                                    "profile_keyframe_complete": True,
                                    "profile_keyframe_coverage_score": 1.0,
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
                                "video": "mixed.mp4",
                                "analysis_id": "run-2",
                                "status": "completed",
                                "analysis_profile": "step",
                                "force_score": 70,
                                "keyframes": {
                                    "profile_keyframe_complete": True,
                                    "profile_keyframe_coverage_score": 1.0,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_goal_progress([first, second])

        stability = summary["profile_stability"]
        self.assertEqual(stability["profile_drift_group_count"], 1)
        self.assertEqual(stability["unstable_tal_membership_count"], 1)
        self.assertEqual(stability["profile_drift_samples"][0]["video"], "mixed.mp4")
        self.assertEqual(stability["profile_drift_samples"][0]["profile_counts"], {"jump": 1, "step": 1})
        self.assertTrue(stability["profile_drift_samples"][0]["unstable_tal_membership"])

    def test_latest_by_video_keeps_newer_profile_fix_for_current_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "old.json"
            second = Path(tmpdir) / "new.json"
            first.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "mixed.mp4",
                                "analysis_id": "old-jump",
                                "status": "completed",
                                "analysis_profile": "jump",
                                "pipeline_version": "v5.2.291",
                                "updated_at": "2026-06-12T01:00:00Z",
                                "keyframes": {
                                    "T": {"timestamp": 1.0},
                                    "A": {"timestamp": 1.4},
                                    "L": {"timestamp": 1.8},
                                    "profile_keyframe_complete": True,
                                    "profile_keyframe_coverage_score": 1.0,
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
                                "video": "mixed.mp4",
                                "analysis_id": "new-spin",
                                "status": "completed",
                                "analysis_profile": "spin",
                                "pipeline_version": "v5.2.294",
                                "updated_at": "2026-06-12T07:00:00Z",
                                "keyframes": {
                                    "profile_keyframe_complete": True,
                                    "profile_keyframe_coverage_score": 1.0,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_goal_progress([first, second], latest_by_video=True)

        self.assertEqual(summary["loaded_row_count"], 2)
        self.assertEqual(summary["row_count"], 1)
        self.assertTrue(summary["latest_by_video"])
        self.assertEqual(summary["completed_profile_counts"], {"spin": 1})
        self.assertEqual(summary["jump_tal"]["row_count"], 0)
        self.assertEqual(summary["profile_stability"]["profile_drift_group_count"], 0)

    def test_batch_auto_eval_flags_feed_profile_decision_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch.json"
            path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "spin.mp4",
                                "analysis_id": "spin-1",
                                "status": "completed",
                                "analysis_profile": "spin",
                                "keyframes": {
                                    "profile_keyframe_complete": True,
                                    "profile_keyframe_coverage_score": 1.0,
                                },
                                "auto_eval": {
                                    "data_quality_flags": [
                                        "mixed_action_profile_overridden_by_video_ai",
                                        "mixed_action_profile_overridden_by_non_jump_history_stability",
                                    ]
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = summarize_goal_progress([path])

        self.assertEqual(
            summary["jump_tal"]["top_profile_decision_flags"],
            {
                "mixed_action_profile_overridden_by_video_ai": 1,
                "mixed_action_profile_overridden_by_non_jump_history_stability": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
