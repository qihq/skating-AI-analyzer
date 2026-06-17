from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.summarize_api_batch_diagnostics import (
    _aggregate,
    _analysis_row,
    _batch_items,
    _latest_rows_by_video,
    _normalize_precomputed_row,
    _read_json,
    _tracker_sequence_summary,
    _with_refreshed_target_preview,
)


class SummarizeApiBatchDiagnosticsTests(unittest.TestCase):
    def test_read_json_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bom.json"
            path.write_text('{"ok": true}', encoding="utf-8-sig")

            payload = _read_json(path)

        self.assertEqual(payload, {"ok": True})

    def test_analysis_row_extracts_tracker_semantic_and_motion_deltas(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "pipeline_version": "v5.2.26",
            "force_score": 80,
            "target_lock": {
                "status": "auto_locked",
                "selected_candidate_id": "target",
                "quality_flags": ["person_tracker_target_lost", "target_lock_stable_zoomed_candidate_auto_locked"],
                "candidates": [
                    {
                        "id": "target",
                        "bbox": {"x": 0.4, "y": 0.3, "width": 0.05, "height": 0.2},
                        "confidence": 0.86,
                        "source": "yolo_zoomed_content",
                        "support_count": 12,
                        "support_frame_count": 6,
                        "support_confidence": 0.82,
                        "support_anchor_frames": ["frame_0001.jpg", "frame_0002.jpg"],
                        "support_center_span": 0.08,
                        "support_avg_area": 0.012,
                        "support_motion_anchor_hits": 1,
                        "multiperson_ambiguous_frame_count": 2,
                        "multiperson_competitor_count": 3,
                        "multiperson_same_anchor_competitor_count": 1,
                        "multiperson_nearest_center_distance": 0.11,
                        "multiperson_max_competitor_confidence": 0.91,
                        "multiperson_ignored_fragment_count": 1,
                        "anchor_frame": "frame_0001.jpg",
                        "anchor_index": 1,
                    }
                ],
                "person_tracker_diagnostics": [
                    {"state": "tracked"},
                    {
                        "state": "full_frame_yolo_relock_pending",
                        "rejected_candidates": [
                            {"bbox": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.2}, "reasons": ["far_from_prediction"]}
                        ],
                    },
                    {"state": "detector_relocked"},
                ],
            },
            "pose_data": {"pose_diagnostics": {"tracked_frames": 1, "total_frames": 2}},
            "bio_data": {
                "key_frame_timestamps": {"T": 0.8, "A": 1.1, "L": 1.6},
                "quality_flags": ["bio_key_frames_not_synced_tracker_final_loss_motion_fallback"],
                "key_frame_candidates": {
                    "quality_flags": ["tal_candidate_skeleton_drifted_after_takeoff"],
                },
            },
            "auto_eval": {
                "data_quality_flags": ["tal_candidate_unreliable_tracker_final_loss"],
            },
            "frame_motion_scores": {
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 0.8, "motion_score": 0.9},
                    {"frame_id": "frame_0002", "timestamp": 1.6, "motion_score": 0.7},
                ],
                "resolved_keyframes": {
                    "selected": [
                        {"key_moment": "T_takeoff", "phase_code": "takeoff", "timestamp": 0.82},
                        {"key_moment": "A_apex", "phase_code": "air", "timestamp": 1.16},
                        {"key_moment": "L_landing", "phase_code": "landing", "timestamp": 1.55},
                    ]
                },
            },
            "video_temporal_diagnostics": {
                "resolver_source": "skeleton_fallback",
                "used_semantic_frames": True,
                "selected_semantic_frames": [
                    {"phase_code": "takeoff", "timestamp": 0.8},
                    {"phase_code": "air", "timestamp": 1.1},
                    {"phase_code": "landing", "timestamp": 1.6},
                ],
                "quality_flags": ["video_temporal_quality_retry_rejected"],
                "retry_rejection_flags": ["semantic_keyframes_unreliable_fallback_to_sampled_frames"],
            },
        }

        row = _analysis_row({"video": "sample.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertEqual(
            row["tracker_state_counts"],
            {"tracked": 1, "full_frame_yolo_relock_pending": 1, "detector_relocked": 1},
        )
        self.assertEqual(row["tracker_loss_frames"], 1.0)
        self.assertEqual(row["tracker_total_frames"], 3.0)
        self.assertEqual(row["tracker_loss_ratio"], 0.3333)
        self.assertTrue(row["tracker_transient_loss_recovered"])
        self.assertFalse(row["tracker_final_unrecovered"])
        self.assertEqual(row["tracker_rejection_reason_counts"], {"far_from_prediction": 1})
        self.assertTrue(row["tracker_sequence_summary"]["transient_loss_recovered"])
        self.assertEqual(row["target_selected_candidate"]["support_frame_count"], 6)
        self.assertEqual(row["target_selected_candidate"]["bbox_area"], 0.01)
        self.assertEqual(row["target_selected_candidate"]["bbox_width"], 0.05)
        self.assertEqual(row["target_selected_candidate"]["bbox_height"], 0.2)
        self.assertEqual(row["target_selected_candidate"]["bbox_aspect"], 0.25)
        self.assertEqual(row["target_selected_candidate"]["support_center_span"], 0.08)
        self.assertEqual(row["target_selected_candidate"]["support_avg_area"], 0.012)
        self.assertEqual(row["target_selected_candidate"]["support_motion_anchor_hits"], 1)
        self.assertEqual(row["target_selected_candidate"]["multiperson_ambiguous_frame_count"], 2)
        self.assertEqual(row["target_selected_candidate"]["multiperson_competitor_count"], 3)
        self.assertEqual(row["target_selected_candidate"]["multiperson_nearest_center_distance"], 0.11)
        self.assertEqual(row["bio_semantic_delta"], {"T": 0.0, "A": 0.0, "L": 0.0})
        self.assertEqual(row["resolved_timestamps"], {"T": 0.82, "A": 1.16, "L": 1.55})
        self.assertEqual(row["bio_resolved_delta"], {"T": -0.02, "A": -0.06, "L": 0.05})
        self.assertEqual(row["bio_resolved_delta_status"], {"T": "within", "A": "within", "L": "within"})
        self.assertEqual(row["bio_motion_peak_delta"], {"T": 0.0, "A": 0.3, "L": 0.0})
        self.assertEqual(row["resolved_motion_peak_delta"], {"T": 0.02, "A": 0.36, "L": -0.05})
        self.assertFalse(row["full_frame_motion_peak_contaminated"])
        self.assertEqual(row["trusted_resolved_motion_peak_delta"], {"T": 0.02, "A": 0.36, "L": -0.05})
        self.assertIn("person_tracker_target_lost", row["target_quality_flags"])
        self.assertIn("person_tracker_transient_loss_recovered", row["target_quality_flags"])
        self.assertIn("bio_key_frames_not_synced_tracker_final_loss_motion_fallback", row["data_quality_flags"])
        self.assertIn("tal_candidate_unreliable_tracker_final_loss", row["data_quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", row["semantic_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", row["semantic_flags"])

    def test_analysis_row_marks_tiny_target_low_pose_tracking_risk(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {
                "status": "locked",
                "selected_candidate_id": "tiny",
                "quality_flags": ["person_tracker_target_lost"],
                "candidates": [
                    {
                        "id": "tiny",
                        "bbox": {"x": 0.4, "y": 0.3, "width": 0.0205, "height": 0.0893},
                        "confidence": 0.80,
                        "source": "yolo_zoomed_content",
                    }
                ],
                "person_tracker_diagnostics": (
                    [{"state": "tracked"} for _ in range(5)]
                    + [{"state": "lost_reused"} for _ in range(16)]
                    + [{"state": "detector_relocked"} for _ in range(2)]
                ),
            },
            "pose_data": {"pose_diagnostics": {"tracked_frames": 15, "total_frames": 32}},
            "bio_data": {"key_frame_timestamps": {"T": 1.0, "A": 1.3, "L": 1.6}},
            "frame_motion_scores": {"selected": []},
        }

        row = _analysis_row({"video": "tiny.mp4", "analysis_id": "analysis-1"}, analysis)
        aggregate = _aggregate([row])

        self.assertEqual(row["target_selected_candidate"]["bbox_area"], 0.001831)
        self.assertIn("person_tracker_tiny_target_low_pose_tracking_risk", row["target_tracking_risk_flags"])
        self.assertIn("person_tracker_tiny_target_low_pose_tracking_risk", row["target_quality_flags"])
        self.assertEqual(aggregate["target_tracking_risk_count"], 1)
        self.assertEqual(
            aggregate["top_target_tracking_risk_flags"],
            [("person_tracker_tiny_target_low_pose_tracking_risk", 1)],
        )
        self.assertEqual(aggregate["core_tracker_flag_counts"]["person_tracker_tiny_target_low_pose_tracking_risk"], 1)
        self.assertEqual(
            aggregate["tracker_loss_summary"],
            {
                "target_lost_flag_count": 1,
                "transient_loss_recovered_count": 1,
                "final_unrecovered_count": 0,
                "high_loss_ratio_count": 1,
                "high_loss_ratio_threshold": 0.25,
            },
        )
        self.assertEqual(aggregate["tracker_loss_samples"][0]["video"], "tiny.mp4")
        self.assertEqual(aggregate["tracker_loss_samples"][0]["tracker_loss_ratio"], 0.6957)
        self.assertEqual(aggregate["target_tracking_risk_samples"][0]["video"], "tiny.mp4")
        self.assertEqual(aggregate["target_tracking_risk_samples"][0]["tracker_loss_ratio"], 0.6957)

    def test_normalize_precomputed_row_derives_tiny_target_tracking_risk(self) -> None:
        row = {
            "video": "tiny.mp4",
            "status": "completed",
            "target_quality_flags": ["person_tracker_target_lost"],
            "target_selected_candidate": {"bbox_area": 0.001831, "bbox_height": 0.0893},
            "pose_tracked_ratio": 0.4688,
            "tracker_sequence_summary": {"loss_frames": 24, "total_frames": 32},
        }

        normalized = _normalize_precomputed_row(row)

        self.assertIn("person_tracker_tiny_target_low_pose_tracking_risk", normalized["target_tracking_risk_flags"])
        self.assertIn("person_tracker_tiny_target_low_pose_tracking_risk", normalized["target_quality_flags"])

    def test_batch_items_marks_batch_video_rows_as_precomputed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch.json"
            path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "video": "step.mp4",
                                "analysis_id": "analysis-1",
                                "status": "completed",
                                "analysis_profile": "step",
                                "keyframes": {
                                    "profile_keyframes": {
                                        "步法序列": {"frame_id": "semantic_0003", "timestamp": 3.69}
                                    },
                                    "profile_keyframe_coverage_score": 1.0,
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            [item] = _batch_items([path])

        self.assertTrue(item["_precomputed_diagnostics"])
        normalized = _normalize_precomputed_row(item)
        self.assertEqual(normalized["profile_keyframe_summary"]["expected_keys"], ["步法序列"])
        self.assertEqual(normalized["profile_keyframe_summary"]["present_keys"], ["步法序列"])
        self.assertTrue(normalized["profile_keyframe_summary"]["complete"])
        self.assertEqual(normalized["profile_keyframe_summary"]["coverage_score"], 1.0)

    def test_normalize_precomputed_batch_row_maps_summary_flags(self) -> None:
        row = {
            "video": "step.mp4",
            "status": "completed",
            "analysis_profile": "step",
            "target": {
                "status": "auto_locked",
                "lock_confidence": 0.88,
                "quality_flags": ["person_tracker_target_lost", "person_tracker_detector_relocked"],
                "tracker_state_counts": {"tracked": 22, "detector_relocked": 1, "full_frame_yolo_relock_pending": 1},
            },
            "pose": {"tracked_ratio": 1.0, "lost_ratio": 0.0, "low_confidence_ratio": 0.0},
            "keyframes": {
                "profile_keyframes": {"步法序列": {"frame_id": "semantic_0003", "timestamp": 3.69}},
                "profile_keyframe_coverage_score": 1.0,
                "quality_flags": ["keyframe_candidates_not_applicable_for_profile"],
            },
            "video_temporal": {
                "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
                "retry_rejection_flags": ["video_temporal_quality_retry_rejected"],
            },
            "auto_eval": {"data_quality_flags": ["bio_key_frames_synced_from_resolved_keyframes"]},
            "quality_flags": ["person_tracker_target_lost"],
        }

        normalized = _normalize_precomputed_row(row)
        aggregate = _aggregate([normalized])

        self.assertEqual(normalized["target_status"], "auto_locked")
        self.assertEqual(normalized["target_lock_confidence"], 0.88)
        self.assertIn("person_tracker_target_lost", normalized["target_quality_flags"])
        self.assertIn("person_tracker_detector_relocked", normalized["target_quality_flags"])
        self.assertIn("person_tracker_transient_loss_recovered", normalized["target_quality_flags"])
        self.assertTrue(normalized["tracker_transient_loss_recovered"])
        self.assertEqual(normalized["tracker_loss_ratio"], 0.0417)
        self.assertIn("semantic_keyframes_reused_from_matching_video", normalized["semantic_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", normalized["semantic_flags"])
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", normalized["data_quality_flags"])
        self.assertEqual(aggregate["core_tracker_flag_counts"]["person_tracker_target_lost"], 1)
        self.assertEqual(aggregate["core_tracker_flag_counts"]["person_tracker_detector_relocked"], 1)
        self.assertEqual(
            aggregate["top_keyframe_candidate_flags"],
            [("keyframe_candidates_not_applicable_for_profile", 1)],
        )
        self.assertEqual(aggregate["top_actionable_keyframe_candidate_flags"], [])
        self.assertEqual(aggregate["tracker_recovery_counts"], {"transient_loss_recovered": 1})
        self.assertEqual(aggregate["top_semantic_retry_flags"][0], ("semantic_keyframes_reused_from_matching_video", 1))
        self.assertIn(("bio_key_frames_synced_from_resolved_keyframes", 1), aggregate["top_data_quality_flags"])

    def test_aggregate_counts_manual_identity_lock_flags_once_per_row(self) -> None:
        row = {
            "video": "manual-lock.mp4",
            "analysis_id": "manual-lock-1",
            "status": "completed",
            "analysis_profile": "step",
            "target_quality_flags": [
                "person_tracker_manual_lock_relock_blocked",
                "person_tracker_manual_lock_fallback_blocked",
                "person_tracker_manual_lock_support_anchor_blocked",
                "person_tracker_target_lost",
            ],
            "pose_quality_flags": ["pose_manual_lock_unreliable_tracker_blocked"],
            "data_quality_flags": ["pose_manual_lock_unreliable_tracker_blocked"],
            "cross_validation": {"path_b_annotation_source": "semantic_manual_lock_blank_pose"},
            "semantic_flags": [],
            "keyframe_candidate_flags": [],
            "tracker_state_counts": {"lost_reused": 3},
            "tracker_rejection_reason_counts": {"manual_lock_relock_blocked": 2},
            "tracker_sequence_summary": {},
            "pose_tracked_ratio": 0.5,
            "tracker_loss_ratio": 0.5,
        }

        normalized = _normalize_precomputed_row(row)
        aggregate = _aggregate([normalized])

        self.assertEqual(
            aggregate["core_tracker_flag_counts"]["person_tracker_manual_lock_relock_blocked"],
            1,
        )
        self.assertEqual(
            aggregate["core_tracker_flag_counts"]["person_tracker_manual_lock_fallback_blocked"],
            1,
        )
        self.assertEqual(
            aggregate["core_tracker_flag_counts"]["person_tracker_manual_lock_support_anchor_blocked"],
            1,
        )
        self.assertEqual(
            aggregate["pose_identity_lock_flag_counts"]["pose_manual_lock_unreliable_tracker_blocked"],
            1,
        )
        self.assertEqual(
            aggregate["pose_identity_lock_flag_counts"]["semantic_pose_manual_lock_unaligned_blank_pose"],
            1,
        )
        self.assertEqual(
            aggregate["pose_identity_lock_samples"][0]["pose_identity_lock_flags"],
            [
                "pose_manual_lock_unreliable_tracker_blocked",
                "semantic_pose_manual_lock_unaligned_blank_pose",
            ],
        )
        self.assertIn(
            "person_tracker_manual_lock_relock_blocked",
            aggregate["pose_identity_lock_samples"][0]["target_quality_flags"],
        )

    def test_analysis_row_derives_semantic_path_b_manual_lock_flag_from_cross_validation(self) -> None:
        analysis = {
            "id": "semantic-lock-1",
            "status": "completed",
            "analysis_profile": "step",
            "target_lock": {
                "status": "locked",
                "manual_override": True,
                "quality_flags": ["person_tracker_manual_lock_relock_blocked"],
                "person_tracker_diagnostics": [{"state": "lost_reused"}],
            },
            "pose_data": {"pose_diagnostics": {"tracked_frames": 0, "total_frames": 1}},
            "bio_data": {"quality_flags": [], "key_frame_candidates": {"quality_flags": []}},
            "cross_validation": {"path_b_annotation_source": "semantic_manual_lock_blank_pose"},
        }

        row = _analysis_row({"video": "semantic-lock.mp4"}, analysis)
        aggregate = _aggregate([row])

        self.assertIn("semantic_pose_manual_lock_unaligned_blank_pose", row["pose_quality_flags"])
        self.assertIn("semantic_pose_manual_lock_unaligned_blank_pose", row["data_quality_flags"])
        self.assertEqual(
            aggregate["pose_identity_lock_flag_counts"]["semantic_pose_manual_lock_unaligned_blank_pose"],
            1,
        )
        self.assertEqual(
            aggregate["pose_identity_lock_samples"][0]["pose_identity_lock_flags"],
            ["semantic_pose_manual_lock_unaligned_blank_pose"],
        )

    def test_aggregate_counts_target_review_reason_flags(self) -> None:
        row = {
            "video": "manual.mp4",
            "status": "awaiting_target_selection",
            "target_quality_flags": [
                "target_lock_zoomed_multiperson_manual_review",
                "target_lock_zoomed_multiperson_review_same_anchor_competitor",
                "target_lock_zoomed_multiperson_review_low_motion_anchor_support",
                "target_lock_foreground_context_review_selected_pair_competitor",
                "target_lock_stable_zoomed_auto_lock_blocked_by_manual_review",
            ],
        }

        normalized = _normalize_precomputed_row(row)
        aggregate = _aggregate([normalized])

        self.assertIn(
            "target_lock_zoomed_multiperson_review_same_anchor_competitor",
            normalized["target_review_reason_flags"],
        )
        self.assertEqual(
            aggregate["top_target_review_reason_flags"],
            [
                ("target_lock_zoomed_multiperson_review_same_anchor_competitor", 1),
                ("target_lock_zoomed_multiperson_review_low_motion_anchor_support", 1),
                ("target_lock_foreground_context_review_selected_pair_competitor", 1),
            ],
        )
        self.assertEqual(
            aggregate["top_target_manual_review_flags"],
            [("target_lock_zoomed_multiperson_manual_review", 1)],
        )

    def test_normalize_precomputed_row_regraces_cached_terminal_tail_loss(self) -> None:
        row = {
            "video": "tail-loss.mp4",
            "status": "completed",
            "target_quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_final_unrecovered",
            ],
            "tracker_loss_ratio": 0.4583,
            "tracker_sequence_summary": {
                "loss_frames": 11,
                "recovered_frames": 4,
                "tracked_frames": 13,
                "total_frames": 24,
                "final_state": "relock_pending",
                "terminal_loss_frames": 3,
                "terminal_loss_graced": False,
                "final_unrecovered": True,
                "transient_loss_recovered": False,
            },
        }

        normalized = _normalize_precomputed_row(row)
        aggregate = _aggregate([normalized])

        self.assertTrue(normalized["tracker_sequence_summary"]["terminal_loss_graced"])
        self.assertFalse(normalized["tracker_final_unrecovered"])
        self.assertTrue(normalized["tracker_transient_loss_recovered"])
        self.assertNotIn("person_tracker_final_unrecovered", normalized["target_quality_flags"])
        self.assertIn("person_tracker_transient_loss_recovered", normalized["target_quality_flags"])
        self.assertEqual(aggregate["tracker_loss_summary"]["final_unrecovered_count"], 0)
        self.assertEqual(aggregate["tracker_loss_summary"]["transient_loss_recovered_count"], 1)

    def test_normalize_precomputed_row_counts_support_anchor_as_tracked_history(self) -> None:
        row = {
            "video": "support-tail-loss.mp4",
            "status": "completed",
            "target_quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_final_unrecovered",
            ],
            "tracker_sequence_summary": {
                "state_counts": {
                    "tracked": 9,
                    "support_anchor_recovered": 3,
                    "lost_reused": 4,
                    "full_frame_yolo_relock_pending": 2,
                    "relock_pending": 2,
                },
                "loss_frames": 8,
                "recovered_frames": 0,
                "tracked_frames": 9,
                "total_frames": 20,
                "final_state": "relock_pending",
                "terminal_loss_frames": 4,
                "terminal_loss_graced": False,
                "final_unrecovered": True,
            },
        }

        normalized = _normalize_precomputed_row(row)

        self.assertEqual(normalized["tracker_sequence_summary"]["tracked_frames"], 12)
        self.assertFalse(normalized["tracker_final_unrecovered"])
        self.assertTrue(normalized["tracker_sequence_summary"]["terminal_loss_graced"])
        self.assertEqual(normalized["tracker_sequence_summary"]["recovered_frames"], 3)

    def test_tiny_target_pending_only_tracker_loss_is_not_tracking_risk(self) -> None:
        row = {
            "video": "tiny-pending.mp4",
            "status": "completed",
            "target_quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_detector_relock_pending",
            ],
            "target_selected_candidate": {
                "bbox_area": 0.002,
                "bbox_height": 0.08,
            },
            "pose_tracked_ratio": 1.0,
            "tracker_sequence_summary": {
                "loss_frames": 1,
                "total_frames": 12,
                "final_state": "tracked",
                "terminal_loss_graced": False,
                "state_counts": {
                    "tracked": 11,
                    "full_frame_yolo_relock_pending": 1,
                },
            },
        }

        normalized = _normalize_precomputed_row(row)
        aggregate = _aggregate([normalized])

        self.assertNotIn(
            "person_tracker_tiny_target_low_pose_tracking_risk",
            normalized["target_tracking_risk_flags"],
        )
        self.assertEqual(aggregate["target_tracking_risk_count"], 0)

    def test_target_tracking_risk_samples_include_profile_and_rejection_reasons(self) -> None:
        row = {
            "video": "tiny-rejected.mp4",
            "status": "completed",
            "analysis_profile": "spin",
            "target_quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_continuity_rejected",
            ],
            "target_selected_candidate": {
                "bbox_area": 0.002,
                "bbox_height": 0.08,
                "bbox_width": 0.025,
            },
            "pose_tracked_ratio": 1.0,
            "tracker_sequence_summary": {
                "loss_frames": 1,
                "total_frames": 12,
                "final_state": "tracked",
                "terminal_loss_graced": False,
                "state_counts": {
                    "tracked": 11,
                    "continuity_rejected": 1,
                },
            },
            "person_tracker_diagnostics": [
                {
                    "state": "continuity_rejected",
                    "rejected_candidates": [
                        {"reasons": ["center_jump"]},
                    ],
                },
            ],
        }

        normalized = _normalize_precomputed_row(row)
        aggregate = _aggregate([normalized])

        [sample] = aggregate["target_tracking_risk_samples"]
        self.assertEqual(sample["analysis_profile"], "spin")
        self.assertEqual(sample["tracker_rejection_reason_counts"], {"center_jump": 1})

    def test_normalize_precomputed_row_derives_multiperson_relock_instability_risk(self) -> None:
        row = {
            "video": "multiperson.mp4",
            "status": "completed",
            "target_quality_flags": [
                "target_lock_zoomed_multiperson_manual_review",
                "target_lock_zoomed_multiperson_scale_competitor_manual_review",
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
            ],
            "target_selected_candidate": {
                "bbox_area": 0.0358,
                "bbox_height": 0.3749,
                "multiperson_ambiguous_frame_count": 9,
                "multiperson_competitor_count": 26,
                "multiperson_other_frame_ambiguous_count": 9,
            },
            "pose_tracked_ratio": 0.5312,
            "tracker_loss_ratio": 0.4688,
            "tracker_sequence_summary": {
                "loss_frames": 15,
                "total_frames": 32,
                "state_counts": {
                    "tracked": 14,
                    "detector_relocked": 2,
                    "relock_pending": 5,
                    "relock_rejected": 3,
                    "local_zoom_yolo_relock_pending": 2,
                    "full_frame_yolo_relock_pending": 3,
                    "lost_reused": 2,
                    "relocked": 1,
                },
            },
        }

        normalized = _normalize_precomputed_row(row)
        aggregate = _aggregate([normalized])

        self.assertIn(
            "person_tracker_multiperson_relock_instability_risk",
            normalized["target_tracking_risk_flags"],
        )
        self.assertIn(
            "person_tracker_multiperson_relock_instability_risk",
            normalized["target_quality_flags"],
        )
        self.assertEqual(
            aggregate["top_target_tracking_risk_flags"],
            [("person_tracker_multiperson_relock_instability_risk", 1)],
        )

    def test_analysis_row_extracts_semantic_candidate_conflict_summary_from_resolved_keyframes(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 32, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 6.5, "A": 6.85, "L": 7.15},
                "key_frame_candidates": {
                    "quality_flags": ["tal_candidate_core_gap_compressed"],
                    "T": {"timestamp": 14.75},
                    "A": {"timestamp": 14.812},
                    "L": {"timestamp": 14.875},
                },
            },
            "frame_motion_scores": {
                "selected": [
                    {"frame_id": "semantic_t", "timestamp": 6.5, "motion_score": 0.018},
                    {"frame_id": "frame_0031", "timestamp": 14.875, "motion_score": 0.0793},
                ],
                "resolved_keyframes": {
                    "quality_flags": ["semantic_keyframes_candidate_motion_window_conflict_ignored_compressed_candidate"],
                    "selected": [
                        {"phase_code": "takeoff", "timestamp": 6.5},
                        {"phase_code": "air", "timestamp": 6.85},
                        {"phase_code": "landing", "timestamp": 7.15},
                    ],
                    "semantic_candidate_tal_conflict": {
                        "decision": "ignored_compressed_candidate_motion_window_conflict",
                        "takeoff_anchor_core_conflict": False,
                        "motion_window_conflict": {
                            "candidate_conflict_evidence": {
                                "conflict_keys": ["T", "A", "L"],
                                "anchor_deltas_sec": {"T": -8.25, "A": -7.962, "L": -7.725},
                                "candidate_span_sec": 0.125,
                                "semantic_span_sec": 0.65,
                                "untrusted_candidate_reasons": ["tal_candidate_core_gap_compressed"],
                                "motion_context": {
                                    "global_peak_timestamp": 14.875,
                                    "global_peak_motion_score": 0.0793,
                                    "semantic_window": {"peak_ratio": 0.277},
                                    "candidate_window": {"peak_ratio": 1.0},
                                    "diagnostic_labels": [
                                        "candidate_temporal_geometry_unreliable",
                                        "candidate_window_dominant_full_frame_motion_over_semantic_window",
                                    ],
                                },
                            },
                        },
                    },
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": True},
        }

        row = _analysis_row({"video": "conflict.mp4", "analysis_id": "analysis-1"}, analysis)
        aggregate = _aggregate([row])

        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_compressed_candidate",
            row["semantic_flags"],
        )
        summary = row["semantic_candidate_conflict_summary"]
        self.assertEqual(summary["decision"], "ignored_compressed_candidate_motion_window_conflict")
        self.assertEqual(summary["anchor_deltas_sec"], {"T": -8.25, "A": -7.962, "L": -7.725})
        self.assertEqual(summary["candidate_peak_ratio"], 1.0)
        self.assertIn(
            "candidate_window_dominant_full_frame_motion_over_semantic_window",
            summary["diagnostic_labels"],
        )
        self.assertEqual(
            aggregate["semantic_candidate_conflict_decision_counts"],
            [("ignored_compressed_candidate_motion_window_conflict", 1)],
        )
        self.assertIn(
            ("candidate_window_dominant_full_frame_motion_over_semantic_window", 1),
            aggregate["semantic_candidate_conflict_label_counts"],
        )
        self.assertIn(
            ("tal_candidate_core_gap_compressed", 1),
            aggregate["semantic_candidate_conflict_untrusted_reason_counts"],
        )

    def test_analysis_row_prefers_cross_validation_resolved_keyframes(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 1, "total_frames": 1}},
            "bio_data": {"key_frame_timestamps": {"T": 1.0, "A": 1.2, "L": 1.5}},
            "frame_motion_scores": {
                "selected": [],
                "resolved_keyframes": {
                    "selected": [
                        {"phase_code": "takeoff", "timestamp": 9.0},
                        {"phase_code": "air", "timestamp": 9.2},
                        {"phase_code": "landing", "timestamp": 9.5},
                    ],
                },
            },
            "cross_validation": {
                "resolved_keyframes": {
                    "selected": [
                        {"phase_code": "takeoff", "timestamp": 1.05},
                        {"phase_code": "air", "timestamp": 1.25},
                        {"phase_code": "landing", "timestamp": 1.55},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": True},
        }

        row = _analysis_row({"video": "sample.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertEqual(row["resolved_timestamps"], {"T": 1.05, "A": 1.25, "L": 1.55})
        self.assertEqual(row["effective_resolved_timestamps"], {"T": 1.05, "A": 1.25, "L": 1.55})
        self.assertEqual(row["bio_resolved_delta"], {"T": -0.05, "A": -0.05, "L": -0.05})

    def test_aggregate_reports_repeat_tal_and_force_score_delta(self) -> None:
        rows = [
            {
                "video": "same.mp4",
                "status": "completed",
                "analysis_profile": "jump",
                "profile_keyframe_summary": {
                    "expected_keys": ["T", "A", "L"],
                    "present_keys": ["T", "A", "L"],
                    "missing_keys": [],
                    "complete": True,
                    "coverage_score": 1.0,
                },
                "analysis_id": "a",
                "pipeline_version": "v1",
                "force_score": 80,
                "bio_timestamps": {"T": 0.8, "A": 1.1, "L": 1.6},
                "resolved_timestamps": {"T": 0.9, "A": 1.0, "L": 1.72},
                "effective_resolved_timestamps": {"T": 0.8, "A": 1.1, "L": 1.6},
                "bio_resolved_delta": {"T": -0.1, "A": 0.1, "L": -0.12},
                "bio_resolved_delta_status": {"T": "within", "A": "within", "L": "early"},
                "bio_effective_resolved_delta": {"T": 0.0, "A": 0.0, "L": 0.0},
                "bio_effective_resolved_delta_status": {"T": "within", "A": "within", "L": "within"},
                "bio_semantic_delta": {"T": -0.2, "A": 0.0, "L": 0.2},
                "bio_semantic_delta_status": {"T": "early", "A": "within", "L": "late"},
                "target_quality_flags": ["person_tracker_target_lost"],
                "tracker_rejection_reason_counts": {"far_from_prediction": 2},
                "tracker_sequence_summary": {"transient_loss_recovered": True, "final_unrecovered": False},
                "semantic_flags": ["video_temporal_quality_retry_rejected"],
                "keyframe_candidate_flags": [],
                "data_quality_flags": ["tal_candidate_unreliable_tracker_final_loss"],
                "tracker_state_counts": {"tracked": 2},
                "bio_motion_peak_delta": {"T": 0.0, "A": 0.2, "L": 0.5},
                "semantic_motion_peak_delta": {"T": 0.1, "A": 0.3, "L": 0.4},
                "resolved_motion_peak_delta": {"T": 0.1, "A": 0.1, "L": 0.62},
                "effective_resolved_motion_peak_delta": {"T": 0.0, "A": 0.2, "L": 0.5},
            },
            {
                "video": "same.mp4",
                "status": "completed",
                "analysis_profile": "jump",
                "profile_keyframe_summary": {
                    "expected_keys": ["T", "A", "L"],
                    "present_keys": ["T", "A", "L"],
                    "missing_keys": [],
                    "complete": True,
                    "coverage_score": 1.0,
                },
                "analysis_id": "b",
                "pipeline_version": "v1",
                "force_score": 78,
                "bio_timestamps": {"T": 0.9, "A": 1.2, "L": 1.7},
                "resolved_timestamps": {"T": 0.95, "A": 1.1, "L": 1.7},
                "effective_resolved_timestamps": {"T": 0.95, "A": 1.1, "L": 1.7},
                "bio_resolved_delta": {"T": -0.05, "A": 0.1, "L": 0.0},
                "bio_resolved_delta_status": {"T": "within", "A": "within", "L": "within"},
                "bio_effective_resolved_delta": {"T": -0.05, "A": 0.1, "L": 0.0},
                "bio_effective_resolved_delta_status": {"T": "within", "A": "within", "L": "within"},
                "bio_semantic_delta": {"T": -0.3, "A": 0.2, "L": 0.0},
                "bio_semantic_delta_status": {"T": "early", "A": "late", "L": "within"},
                "target_quality_flags": [],
                "tracker_rejection_reason_counts": {"area_ratio": 1},
                "tracker_sequence_summary": {},
                "semantic_flags": [],
                "keyframe_candidate_flags": ["keyframe_candidates_motion_fallback"],
                "data_quality_flags": ["keyframe_candidates_motion_fallback"],
                "tracker_state_counts": {"tracked": 2},
                "bio_motion_peak_delta": {"T": 0.1, "A": 0.3, "L": 0.6},
                "semantic_motion_peak_delta": {"T": 0.2, "A": 0.4, "L": 0.5},
                "resolved_motion_peak_delta": {"T": 0.15, "A": 0.2, "L": 0.6},
                "effective_resolved_motion_peak_delta": {"T": 0.15, "A": 0.2, "L": 0.6},
            },
        ]

        aggregate = _aggregate(rows)

        self.assertEqual(aggregate["analysis_profile_counts"], {"jump": 2})
        self.assertEqual(aggregate["completed_analysis_profile_counts"], {"jump": 2})
        self.assertEqual(aggregate["tal_metric_profile"], "jump")
        self.assertEqual(aggregate["tal_metric_completed_count"], 2)
        self.assertEqual(aggregate["profile_keyframe_average_coverage"], {"jump": 1.0})
        self.assertEqual(aggregate["profile_keyframe_complete_rate"], {"jump": 1.0})
        self.assertEqual(aggregate["core_tracker_flag_counts"]["person_tracker_target_lost"], 1)
        self.assertEqual(aggregate["top_tracker_rejection_reasons"], [("far_from_prediction", 2), ("area_ratio", 1)])
        self.assertEqual(aggregate["tracker_recovery_counts"], {"transient_loss_recovered": 1})
        self.assertEqual(aggregate["repeat_summary"][0]["force_score_delta"], -2)
        self.assertTrue(aggregate["repeat_summary"][0]["same_pipeline_version"])
        self.assertEqual(aggregate["repeat_summary"][0]["tal_delta"], {"T": 0.1, "A": 0.1, "L": 0.1})
        self.assertEqual(aggregate["repeat_summary"][0]["effective_tal_delta"], {"T": 0.15, "A": 0.0, "L": 0.1})
        self.assertEqual(aggregate["repeat_summary"][0]["resolved_tal_delta"], {"T": 0.05, "A": 0.1, "L": -0.02})
        self.assertEqual(aggregate["average_abs_bio_to_nearest_motion_peak_delta"], {"T": 0.05, "A": 0.25, "L": 0.55})
        self.assertEqual(aggregate["average_abs_resolved_to_nearest_motion_peak_delta"], {"T": 0.125, "A": 0.15, "L": 0.61})
        self.assertEqual(aggregate["average_abs_effective_resolved_to_nearest_motion_peak_delta"], {"T": 0.075, "A": 0.2, "L": 0.55})
        self.assertEqual(aggregate["average_abs_bio_minus_semantic_delta"], {"T": 0.25, "A": 0.1, "L": 0.1})
        self.assertEqual(aggregate["average_abs_bio_minus_resolved_delta"], {"T": 0.075, "A": 0.1, "L": 0.06})
        self.assertEqual(aggregate["average_abs_bio_minus_effective_resolved_delta"], {"T": 0.025, "A": 0.05, "L": 0.0})
        self.assertEqual(aggregate["bio_semantic_delta_direction_counts"]["T"], {"within": 0, "early": 2, "late": 0, "missing": 0})
        self.assertEqual(aggregate["bio_resolved_delta_direction_counts"]["L"], {"within": 1, "early": 1, "late": 0, "missing": 0})
        self.assertEqual(aggregate["bio_effective_resolved_delta_direction_counts"]["L"], {"within": 2, "early": 0, "late": 0, "missing": 0})
        self.assertEqual(aggregate["repeat_extrema"]["max_abs_force_score_delta"], 2.0)
        self.assertEqual(aggregate["repeat_extrema"]["max_abs_tal_delta"], {"T": 0.1, "A": 0.1, "L": 0.1})
        self.assertEqual(aggregate["repeat_extrema"]["max_abs_effective_tal_delta"], {"T": 0.15, "A": 0.0, "L": 0.1})
        self.assertEqual(aggregate["repeat_extrema"]["max_abs_resolved_tal_delta"], {"T": 0.05, "A": 0.1, "L": 0.02})
        self.assertEqual(aggregate["repeat_extrema_same_pipeline"]["max_abs_force_score_delta"], 2.0)
        self.assertEqual(aggregate["repeat_extrema_same_pipeline"]["max_abs_tal_delta"], {"T": 0.1, "A": 0.1, "L": 0.1})
        self.assertEqual(
            aggregate["repeat_extrema_same_pipeline"]["max_abs_effective_tal_delta"],
            {"T": 0.15, "A": 0.0, "L": 0.1},
        )
        self.assertEqual(
            aggregate["repeat_extrema_same_pipeline"]["max_abs_resolved_tal_delta"],
            {"T": 0.05, "A": 0.1, "L": 0.02},
        )
        self.assertIn(("tal_candidate_unreliable_tracker_final_loss", 1), aggregate["top_data_quality_flags"])

    def test_aggregate_filters_tal_metrics_to_jump_profile_and_reports_profile_keyframes(self) -> None:
        rows = [
            {
                "video": "jump.mp4",
                "status": "completed",
                "analysis_profile": "jump",
                "profile_keyframe_summary": {
                    "expected_keys": ["T", "A", "L"],
                    "present_keys": ["T", "A", "L"],
                    "missing_keys": [],
                    "complete": True,
                    "coverage_score": 1.0,
                },
                "bio_motion_peak_delta": {"T": 0.1, "A": 0.2, "L": 0.3},
                "bio_semantic_delta": {"T": 0.1, "A": -0.2, "L": 0.3},
                "bio_semantic_delta_status": {"T": "within", "A": "early", "L": "late"},
                "target_quality_flags": [],
                "semantic_flags": [],
                "keyframe_candidate_flags": [],
                "data_quality_flags": [],
                "tracker_state_counts": {},
                "tracker_rejection_reason_counts": {},
                "tracker_sequence_summary": {},
            },
            {
                "video": "spin.mp4",
                "status": "completed",
                "analysis_profile": "spin",
                "profile_keyframe_summary": {
                    "expected_keys": ["旋转入", "旋转中", "旋转出"],
                    "present_keys": ["旋转入", "旋转中"],
                    "missing_keys": ["旋转出"],
                    "complete": False,
                    "coverage_score": 0.6667,
                },
                "bio_motion_peak_delta": {"T": 9.0, "A": 9.0, "L": 9.0},
                "bio_semantic_delta": {"T": 9.0, "A": 9.0, "L": 9.0},
                "bio_semantic_delta_status": {"T": "late", "A": "late", "L": "late"},
                "target_quality_flags": [],
                "semantic_flags": [],
                "keyframe_candidate_flags": [],
                "data_quality_flags": [],
                "tracker_state_counts": {},
                "tracker_rejection_reason_counts": {},
                "tracker_sequence_summary": {},
            },
        ]

        aggregate = _aggregate(rows)

        self.assertEqual(aggregate["analysis_profile_counts"], {"jump": 1, "spin": 1})
        self.assertEqual(aggregate["tal_metric_completed_count"], 1)
        self.assertEqual(aggregate["average_abs_bio_to_nearest_motion_peak_delta"], {"T": 0.1, "A": 0.2, "L": 0.3})
        self.assertEqual(aggregate["bio_semantic_delta_direction_counts"]["L"], {"within": 0, "early": 0, "late": 1, "missing": 0})
        self.assertEqual(aggregate["profile_keyframe_average_coverage"], {"jump": 1.0, "spin": 0.6667})
        self.assertEqual(aggregate["profile_keyframe_complete_rate"], {"jump": 1.0, "spin": 0.0})
        self.assertEqual(aggregate["profile_keyframe_incomplete_samples"][0]["video"], "spin.mp4")

    def test_step_profile_keyframe_accepts_sequence_or_peak_alias(self) -> None:
        rows = [
            _normalize_precomputed_row(
                {
                    "video": "step-sequence.mp4",
                    "status": "completed",
                    "analysis_profile": "step",
                    "keyframes": {
                        "profile_keyframes": {
                            "步法序列": {"frame_id": "semantic_0002", "timestamp": 5.0},
                        }
                    },
                    "target_quality_flags": [],
                    "semantic_flags": [],
                    "keyframe_candidate_flags": [],
                    "tracker_state_counts": {},
                    "tracker_rejection_reason_counts": {},
                    "tracker_sequence_summary": {},
                }
            ),
            _normalize_precomputed_row(
                {
                    "video": "step-peak.mp4",
                    "status": "completed",
                    "analysis_profile": "step",
                    "keyframes": {
                        "profile_keyframes": {
                            "峰值": {"frame_id": "frame_0016", "timestamp": 3.2},
                        }
                    },
                    "target_quality_flags": [],
                    "semantic_flags": [],
                    "keyframe_candidate_flags": [],
                    "tracker_state_counts": {},
                    "tracker_rejection_reason_counts": {},
                    "tracker_sequence_summary": {},
                }
            ),
        ]

        aggregate = _aggregate(rows)

        self.assertEqual(aggregate["profile_keyframe_average_coverage"], {"step": 1.0})
        self.assertEqual(aggregate["profile_keyframe_complete_rate"], {"step": 1.0})
        self.assertEqual(aggregate["profile_keyframe_incomplete_samples"], [])

    def test_latest_rows_by_video_keeps_last_result_for_current_coverage_view(self) -> None:
        rows = [
            {
                "video": "same.mp4",
                "analysis_id": "old",
                "status": "completed",
                "target_status": "auto_locked",
                "target_quality_flags": ["person_tracker_target_lost"],
                "target_manual_review_flags": [],
                "target_auto_lock_blocked_flags": [],
                "target_tracking_risk_flags": [],
                "keyframe_candidate_flags": [],
                "data_quality_flags": [],
                "semantic_flags": [],
                "tracker_state_counts": {},
                "tracker_rejection_reason_counts": {},
                "tracker_sequence_summary": {},
                "bio_timestamps": {"T": 1.0, "A": 1.2, "L": 1.4},
            },
            {
                "video": "other.mp4",
                "analysis_id": "other",
                "status": "completed",
                "target_status": "auto_locked",
                "target_quality_flags": [],
                "target_manual_review_flags": [],
                "target_auto_lock_blocked_flags": [],
                "target_tracking_risk_flags": [],
                "keyframe_candidate_flags": [],
                "data_quality_flags": [],
                "semantic_flags": [],
                "tracker_state_counts": {},
                "tracker_rejection_reason_counts": {},
                "tracker_sequence_summary": {},
                "bio_timestamps": {"T": 2.0, "A": 2.2, "L": 2.4},
            },
            {
                "video": "same.mp4",
                "analysis_id": "new",
                "status": "awaiting_target_selection",
                "target_status": "awaiting_manual",
                "target_quality_flags": ["target_lock_zoomed_multiperson_manual_review"],
                "target_manual_review_flags": ["target_lock_zoomed_multiperson_manual_review"],
                "target_auto_lock_blocked_flags": ["target_lock_auto_lock_blocked_by_manual_review"],
                "target_auto_lock_blocked": True,
                "target_tracking_risk_flags": [],
                "keyframe_candidate_flags": [],
                "data_quality_flags": [],
                "semantic_flags": [],
                "tracker_state_counts": {},
                "tracker_rejection_reason_counts": {},
                "tracker_sequence_summary": {},
                "bio_timestamps": {},
            },
        ]

        latest = _latest_rows_by_video(rows)
        raw_aggregate = _aggregate(rows)
        unique_aggregate = _aggregate(latest)

        self.assertEqual([row["analysis_id"] for row in latest], ["new", "other"])
        self.assertEqual(raw_aggregate["total"], 3)
        self.assertEqual(raw_aggregate["completed"], 2)
        self.assertEqual(unique_aggregate["total"], 2)
        self.assertEqual(unique_aggregate["completed"], 1)
        self.assertEqual(unique_aggregate["awaiting_target_selection"], 1)
        self.assertEqual(unique_aggregate["core_tracker_flag_counts"]["person_tracker_target_lost"], 0)
        self.assertEqual(
            unique_aggregate["top_target_manual_review_flags"],
            [("target_lock_zoomed_multiperson_manual_review", 1)],
        )

    def test_analysis_row_uses_bio_as_effective_resolved_when_semantic_rejected(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 1, "total_frames": 1}},
            "bio_data": {
                "key_frame_timestamps": {"T": 1.438, "A": 1.875, "L": 2.25},
                "key_frame_candidates": {},
            },
            "frame_motion_scores": {
                "selected": [{"frame_id": "frame_0001", "timestamp": 1.438, "motion_score": 0.5}],
                "resolved_keyframes": {
                    "source": "blended",
                    "quality_flags": ["semantic_keyframes_unreliable_fallback_to_sampled_frames"],
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 3.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                        {"frame_id": "semantic_0002", "timestamp": 3.65, "phase_code": "air", "key_moment": "A_air_sec"},
                        {"frame_id": "semantic_0003", "timestamp": 3.95, "phase_code": "landing", "key_moment": "L_landing_sec"},
                    ],
                },
            },
            "video_temporal_diagnostics": {
                "used_semantic_frames": False,
                "selected_semantic_frames": [
                    {"timestamp": 3.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"timestamp": 3.65, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"timestamp": 3.95, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
            },
        }

        row = _analysis_row({"video": "sample.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertEqual(row["raw_resolved_timestamps"], {"T": 3.1, "A": 3.65, "L": 3.95})
        self.assertEqual(row["resolved_timestamps"], {"T": 3.1, "A": 3.65, "L": 3.95})
        self.assertEqual(row["effective_resolved_timestamps"], {"T": 1.438, "A": 1.875, "L": 2.25})
        self.assertEqual(row["bio_resolved_delta"], {"T": -1.662, "A": -1.775, "L": -1.7})
        self.assertEqual(row["bio_effective_resolved_delta"], {"T": 0.0, "A": 0.0, "L": 0.0})
        self.assertEqual(row["bio_effective_resolved_delta_status"], {"T": "within", "A": "within", "L": "within"})
        self.assertFalse(row["video_temporal_used_semantic_frames"])

    def test_analysis_row_does_not_use_candidates_as_final_bio_timestamps_when_keyframes_empty(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 1, "total_frames": 1}},
            "bio_data": {
                "key_frames": {},
                "quality_flags": [
                    "bio_key_frames_not_synced_unreliable_resolved_keyframes",
                    "bio_key_frames_not_restored_unreliable_candidates",
                ],
                "key_frame_candidates": {
                    "quality_flags": ["tal_candidate_temporal_geometry_unreliable"],
                    "T": {"frame_id": "frame_0011", "timestamp": 0.625},
                    "A": {"frame_id": "frame_0012", "timestamp": 0.75},
                    "L": {"frame_id": "frame_0015", "timestamp": 1.312},
                },
            },
            "frame_motion_scores": {
                "selected": [{"frame_id": "frame_0011", "timestamp": 0.625, "motion_score": 0.5}],
                "resolved_keyframes": {
                    "source": "blended",
                    "quality_flags": ["semantic_keyframes_unreliable_fallback_to_sampled_frames"],
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 3.253, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                        {"frame_id": "semantic_0002", "timestamp": 3.6, "phase_code": "air", "key_moment": "A_air_sec"},
                        {"frame_id": "semantic_0003", "timestamp": 3.8, "phase_code": "landing", "key_moment": "L_landing_sec"},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": False},
        }

        row = _analysis_row({"video": "sample.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertEqual(row["bio_timestamps"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["candidate_timestamps"], {"T": 0.625, "A": 0.75, "L": 1.312})
        self.assertEqual(row["resolved_timestamps"], {"T": 3.253, "A": 3.6, "L": 3.8})
        self.assertEqual(row["effective_resolved_timestamps"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["bio_resolved_delta_status"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["bio_effective_resolved_delta_status"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["bio_motion_peak_delta"], {"T": None, "A": None, "L": None})

    def test_analysis_row_marks_tiny_target_motion_fallback_as_contaminated_candidate_delta(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 1, "total_frames": 4}},
            "bio_data": {
                "key_frame_timestamps": {"T": 8.1, "A": 8.5, "L": 8.767},
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
                        "tal_candidate_motion_fallback_foreground_motion_risk",
                    ],
                    "T": {"timestamp": 3.188},
                    "A": {"timestamp": 3.25},
                    "L": {"timestamp": 3.312},
                },
            },
            "frame_motion_scores": {
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 3.188, "motion_score": 0.12},
                    {"frame_id": "frame_0013", "timestamp": 3.25, "motion_score": 0.10},
                    {"frame_id": "frame_0014", "timestamp": 3.312, "motion_score": 0.09},
                ],
                "resolved_keyframes": {
                    "source": "blended",
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 8.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                        {"frame_id": "semantic_0002", "timestamp": 8.5, "phase_code": "air", "key_moment": "A_air_sec"},
                        {"frame_id": "semantic_0003", "timestamp": 8.767, "phase_code": "landing", "key_moment": "L_landing_sec"},
                    ],
                },
            },
            "video_temporal_diagnostics": {
                "used_semantic_frames": True,
                "selected_semantic_frames": [
                    {"timestamp": 8.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"timestamp": 8.5, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"timestamp": 8.767, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
            },
        }

        row = _analysis_row({"video": "tiny.mp4", "analysis_id": "analysis-1"}, analysis)
        aggregate = _aggregate([row])

        self.assertTrue(row["candidate_motion_contaminated"])
        self.assertEqual(row["candidate_semantic_delta"], {"T": -4.912, "A": -5.25, "L": -5.455})
        self.assertEqual(row["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(aggregate["candidate_motion_contaminated_count"], 1)
        self.assertEqual(
            aggregate["trusted_candidate_semantic_delta_direction_counts"]["T"],
            {"within": 0, "early": 0, "late": 0, "missing": 1},
        )

    def test_analysis_row_marks_takeoff_anchor_tail_window_as_contaminated_candidate_delta(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 32, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 2.62, "A": 3.1, "L": 3.667},
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "keyframe_candidates_motion_fallback_takeoff_anchor_tail_window",
                        "tal_candidate_motion_fallback_tail_window",
                    ],
                    "T": {"timestamp": 7.0},
                    "A": {"timestamp": 7.25},
                    "L": {"timestamp": 7.812},
                },
            },
            "frame_motion_scores": {
                "selected": [{"frame_id": "frame_0027", "timestamp": 7.875, "motion_score": 0.1183}],
                "resolved_keyframes": {
                    "source": "blended",
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 2.62, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                        {"frame_id": "semantic_0002", "timestamp": 3.1, "phase_code": "air", "key_moment": "A_air_sec"},
                        {"frame_id": "semantic_0003", "timestamp": 3.667, "phase_code": "landing", "key_moment": "L_landing_sec"},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": True},
        }

        row = _analysis_row({"video": "tail.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertTrue(row["candidate_motion_contaminated"])
        self.assertEqual(row["candidate_semantic_delta_status"], {"T": "late", "A": "late", "L": "late"})
        self.assertEqual(row["trusted_candidate_semantic_delta_status"], {"T": None, "A": None, "L": None})

    def test_analysis_row_marks_tail_window_reselected_candidate_delta_untrusted(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 31, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 2.32, "A": 2.85, "L": 3.033},
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "keyframe_candidates_tail_motion_window_rejected",
                        "keyframe_candidates_tail_motion_window_reselected",
                    ],
                    "T": {"timestamp": 1.75},
                    "A": {"timestamp": 2.25},
                    "L": {"timestamp": 2.625},
                },
            },
            "frame_motion_scores": {
                "selected": [{"frame_id": "frame_0017", "timestamp": 1.75, "motion_score": 0.0211}],
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 2.32, "phase_code": "takeoff"},
                        {"frame_id": "semantic_0002", "timestamp": 2.85, "phase_code": "air"},
                        {"frame_id": "semantic_0003", "timestamp": 3.033, "phase_code": "landing"},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": True},
        }

        row = _analysis_row({"video": "tail-reselected.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertTrue(row["candidate_delta_untrusted"])
        self.assertIn("keyframe_candidates_tail_motion_window_reselected", row["candidate_delta_untrusted_reasons"])
        self.assertEqual(row["candidate_semantic_delta_status"], {"T": "early", "A": "early", "L": "early"})
        self.assertEqual(row["trusted_candidate_semantic_delta_status"], {"T": None, "A": None, "L": None})

    def test_analysis_row_marks_sparse_track_stitched_candidate_delta_untrusted(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 27, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 3.453, "A": 3.8, "L": 4.033},
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                        "tal_candidate_sparse_track_stitched",
                        "tal_candidate_unreliable_sparse_track_stitch",
                    ],
                    "T": {"timestamp": 2.625},
                    "A": {"timestamp": 2.688},
                    "L": {"timestamp": 4.062},
                },
            },
            "frame_motion_scores": {
                "selected": [
                    {"frame_id": "frame_0017", "timestamp": 2.625, "motion_score": 0.0398},
                    {"frame_id": "frame_0024", "timestamp": 4.062, "motion_score": 0.0419},
                ],
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 3.453, "phase_code": "takeoff"},
                        {"frame_id": "semantic_0002", "timestamp": 3.8, "phase_code": "air"},
                        {"frame_id": "semantic_0003", "timestamp": 4.033, "phase_code": "landing"},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": True},
        }

        row = _analysis_row({"video": "sparse.mp4", "analysis_id": "analysis-1"}, analysis)
        aggregate = _aggregate([row])

        self.assertFalse(row["candidate_motion_contaminated"])
        self.assertTrue(row["candidate_delta_untrusted"])
        self.assertIn("tal_candidate_sparse_track_stitched", row["candidate_delta_untrusted_reasons"])
        self.assertEqual(row["candidate_semantic_delta_status"], {"T": "early", "A": "early", "L": "within"})
        self.assertEqual(row["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["trusted_candidate_motion_peak_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(aggregate["candidate_motion_contaminated_count"], 0)
        self.assertEqual(aggregate["candidate_delta_untrusted_count"], 1)
        self.assertEqual(
            aggregate["average_abs_trusted_candidate_to_nearest_motion_peak_delta"],
            {"T": None, "A": None, "L": None},
        )
        self.assertEqual(
            aggregate["trusted_candidate_semantic_delta_direction_counts"]["A"],
            {"within": 0, "early": 0, "late": 0, "missing": 1},
        )

    def test_analysis_row_marks_compressed_takeoff_apex_candidate_delta_untrusted(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 30, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 4.25, "A": 4.312, "L": 5.438},
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_takeoff_apex_gap_unreliable",
                        "tal_candidate_takeoff_apex_gap_compressed",
                    ],
                    "T": {"timestamp": 4.25},
                    "A": {"timestamp": 4.312},
                    "L": {"timestamp": 5.438},
                },
            },
            "frame_motion_scores": {
                "selected": [
                    {"frame_id": "frame_0016", "timestamp": 4.25, "motion_score": 0.0489},
                    {"frame_id": "frame_0017", "timestamp": 4.312, "motion_score": 0.0467},
                    {"frame_id": "frame_0020", "timestamp": 5.438, "motion_score": 0.0933},
                ],
                "resolved_keyframes": {
                    "source": "skeleton_fallback",
                    "selected": [
                        {"frame_id": "frame_0016", "timestamp": 4.25, "phase_code": "takeoff"},
                        {"frame_id": "frame_0017", "timestamp": 4.312, "phase_code": "air"},
                        {"frame_id": "frame_0020", "timestamp": 5.438, "phase_code": "landing"},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": False},
        }

        row = _analysis_row({"video": "compressed-ta.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertTrue(row["candidate_delta_untrusted"])
        self.assertIn("tal_candidate_takeoff_apex_gap_compressed", row["candidate_delta_untrusted_reasons"])
        self.assertEqual(row["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["trusted_candidate_resolved_delta_status"], {"T": None, "A": None, "L": None})

    def test_analysis_row_marks_tail_compressed_core_candidate_delta_untrusted(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 30, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 5.22, "A": 5.8, "L": 6.1},
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_compressed",
                        "tal_candidate_tail_motion_window_compressed_core",
                    ],
                    "T": {"timestamp": 8.188},
                    "A": {"timestamp": 8.312},
                    "L": {"timestamp": 8.375},
                },
            },
            "frame_motion_scores": {
                "selected": [
                    {"frame_id": "frame_0029", "timestamp": 8.188, "motion_score": 0.071},
                    {"frame_id": "frame_0030", "timestamp": 8.312, "motion_score": 0.074},
                    {"frame_id": "frame_0031", "timestamp": 8.375, "motion_score": 0.073},
                ],
                "resolved_keyframes": {
                    "source": "blended",
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 5.22, "phase_code": "takeoff"},
                        {"frame_id": "semantic_0002", "timestamp": 5.8, "phase_code": "air"},
                        {"frame_id": "semantic_0003", "timestamp": 6.1, "phase_code": "landing"},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": True},
        }

        row = _analysis_row({"video": "tail-compressed.mp4", "analysis_id": "analysis-1"}, analysis)
        aggregate = _aggregate([row])

        self.assertTrue(row["candidate_delta_untrusted"])
        self.assertIn("tal_candidate_tail_motion_window_compressed_core", row["candidate_delta_untrusted_reasons"])
        self.assertEqual(row["candidate_semantic_delta_status"], {"T": "late", "A": "late", "L": "late"})
        self.assertEqual(row["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})
        self.assertIn(
            ("tal_candidate_tail_motion_window_compressed_core", 1),
            aggregate["top_candidate_delta_untrusted_reasons"],
        )

    def test_analysis_row_marks_takeoff_anchor_low_precision_candidate_delta_untrusted(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 31, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 3.45, "A": 3.8, "L": 4.1},
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "tal_candidate_motion_fallback_low_precision",
                    ],
                    "T": {"timestamp": 0.062},
                    "A": {"timestamp": 0.25},
                    "L": {"timestamp": 0.938},
                },
            },
            "frame_motion_scores": {
                "selected": [{"frame_id": "frame_0002", "timestamp": 0.062, "motion_score": 0.0556}],
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 3.45, "phase_code": "takeoff"},
                        {"frame_id": "semantic_0002", "timestamp": 3.8, "phase_code": "air"},
                        {"frame_id": "semantic_0003", "timestamp": 4.1, "phase_code": "landing"},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": True},
        }

        row = _analysis_row({"video": "early-anchor.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertFalse(row["candidate_motion_contaminated"])
        self.assertTrue(row["candidate_delta_untrusted"])
        self.assertIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", row["candidate_delta_untrusted_reasons"])
        self.assertIn("tal_candidate_motion_fallback_low_precision", row["candidate_delta_untrusted_reasons"])
        self.assertEqual(row["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})

    def test_analysis_row_marks_early_full_frame_motion_peak_contamination(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {
                "status": "locked",
                "selected_candidate_id": "target",
                "quality_flags": [
                    "target_lock_zoomed_multiperson_manual_review",
                    "person_tracker_target_lost",
                    "person_tracker_transient_loss_recovered",
                ],
                "candidates": [
                    {
                        "id": "target",
                        "bbox": {"x": 0.5, "y": 0.43, "width": 0.076, "height": 0.176},
                        "confidence": 0.78,
                        "source": "yolo_zoomed_content",
                    }
                ],
            },
            "pose_data": {"pose_diagnostics": {"tracked_frames": 24, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 1.938, "A": 2.438, "L": 2.758},
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_compressed",
                    ],
                    "T": {"timestamp": 1.812},
                    "A": {"timestamp": 2.0},
                    "L": {"timestamp": 2.062},
                },
            },
            "frame_motion_scores": {
                "selected": [
                    {"frame_id": "frame_0005", "timestamp": 0.312, "motion_score": 0.3185},
                    {"frame_id": "frame_0018", "timestamp": 1.938, "motion_score": 0.0817},
                    {"frame_id": "frame_0019", "timestamp": 2.0, "motion_score": 0.0692},
                    {"frame_id": "frame_0027", "timestamp": 2.75, "motion_score": 0.041},
                ],
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "quality_flags": [
                        "semantic_keyframes_reused_from_matching_video",
                        "semantic_keyframes_reused_from_phase_range_late_reanchor_source",
                    ],
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 1.938, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                        {"frame_id": "semantic_0002", "timestamp": 2.438, "phase_code": "air", "key_moment": "A_air_sec"},
                        {"frame_id": "semantic_0003", "timestamp": 2.758, "phase_code": "landing", "key_moment": "L_landing_sec"},
                    ],
                },
            },
            "video_temporal_diagnostics": {
                "used_semantic_frames": True,
                "selected_semantic_frames": [
                    {"timestamp": 1.938, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"timestamp": 2.438, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"timestamp": 2.758, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
            },
        }

        row = _analysis_row({"video": "foreground.mp4", "analysis_id": "analysis-1"}, analysis)
        aggregate = _aggregate([row])

        self.assertTrue(row["full_frame_motion_peak_contaminated"])
        self.assertEqual(row["semantic_motion_peak_delta"], {"T": 0.0, "A": -0.312, "L": 0.008})
        self.assertEqual(row["trusted_semantic_motion_peak_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["full_frame_motion_peak_contamination"]["peak_timestamp"], 0.312)
        self.assertGreater(row["full_frame_motion_peak_contamination"]["peak_to_core_ratio"], 2.5)
        self.assertEqual(aggregate["full_frame_motion_peak_contaminated_count"], 1)
        self.assertEqual(aggregate["average_abs_semantic_to_nearest_motion_peak_delta"], {"T": 0.0, "A": 0.312, "L": 0.008})
        self.assertEqual(aggregate["average_abs_trusted_semantic_to_nearest_motion_peak_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(aggregate["full_frame_motion_peak_contamination_samples"][0]["video"], "foreground.mp4")
        self.assertEqual(row["full_frame_motion_peak_contamination"]["direction"], "early")
        self.assertEqual(row["full_frame_motion_peak_contamination"]["offset_sec"], 1.626)

    def test_analysis_row_marks_late_full_frame_motion_peak_contamination(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {
                "status": "locked",
                "selected_candidate_id": "target",
                "quality_flags": [
                    "target_lock_zoomed_multiperson_background_auto_lock_allowed",
                    "person_tracker_target_lost",
                    "person_tracker_detector_relocked",
                ],
                "candidates": [
                    {
                        "id": "target",
                        "bbox": {"x": 0.45, "y": 0.41, "width": 0.099, "height": 0.199},
                        "confidence": 0.94,
                        "source": "yolo_zoomed_content",
                        "multiperson_ambiguous_frame_count": 8,
                        "multiperson_competitor_count": 35,
                        "multiperson_other_frame_ambiguous_count": 8,
                    }
                ],
            },
            "pose_data": {"pose_diagnostics": {"tracked_frames": 31, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 4.617, "A": 5.07, "L": 5.453},
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_apex_geometry_weak",
                        "tal_candidate_landing_geometry_weak",
                    ],
                    "T": {"timestamp": 6.75},
                    "A": {"timestamp": 7.25},
                    "L": {"timestamp": 7.5},
                },
            },
            "frame_motion_scores": {
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 4.625, "motion_score": 0.045},
                    {"frame_id": "semantic_0003", "timestamp": 5.625, "motion_score": 0.0239},
                    {"frame_id": "frame_0024", "timestamp": 7.0, "motion_score": 0.0396},
                    {"frame_id": "frame_0027", "timestamp": 7.25, "motion_score": 0.1454},
                    {"frame_id": "frame_0028", "timestamp": 7.312, "motion_score": 0.1118},
                ],
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 4.617, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                        {"frame_id": "semantic_0002", "timestamp": 5.07, "phase_code": "air", "key_moment": "A_air_sec"},
                        {"frame_id": "semantic_0003", "timestamp": 5.453, "phase_code": "landing", "key_moment": "L_landing_sec"},
                    ],
                },
            },
            "video_temporal_diagnostics": {
                "used_semantic_frames": True,
                "selected_semantic_frames": [
                    {"timestamp": 4.617, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"timestamp": 5.07, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"timestamp": 5.453, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
            },
        }

        row = _analysis_row({"video": "late-foreground.mp4", "analysis_id": "analysis-1"}, analysis)
        aggregate = _aggregate([row])

        self.assertTrue(row["full_frame_motion_peak_contaminated"])
        self.assertEqual(row["full_frame_motion_peak_risk_flags"], ["target_lock_multiperson_full_frame_motion_risk"])
        self.assertIn("target_lock_multiperson_full_frame_motion_risk", row["target_quality_flags"])
        self.assertEqual(row["semantic_motion_peak_delta"], {"T": -0.008, "A": 0.445, "L": -0.172})
        self.assertEqual(row["trusted_semantic_motion_peak_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["trusted_candidate_motion_peak_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(row["full_frame_motion_peak_contamination"]["direction"], "late")
        self.assertEqual(row["full_frame_motion_peak_contamination"]["peak_timestamp"], 7.25)
        self.assertEqual(row["full_frame_motion_peak_contamination"]["offset_sec"], 1.797)
        self.assertLess(row["full_frame_motion_peak_contamination"]["lead_sec"], 0)
        self.assertGreater(row["full_frame_motion_peak_contamination"]["peak_to_core_ratio"], 2.5)
        self.assertEqual(aggregate["full_frame_motion_peak_contaminated_count"], 1)
        self.assertEqual(aggregate["average_abs_trusted_semantic_to_nearest_motion_peak_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(aggregate["full_frame_motion_peak_contamination_samples"][0]["direction"], "late")

    def test_analysis_row_marks_landing_geometry_warning_candidate_delta_untrusted(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "completed",
            "target_lock": {},
            "pose_data": {"pose_diagnostics": {"tracked_frames": 32, "total_frames": 32}},
            "bio_data": {
                "key_frame_timestamps": {"T": 2.053, "A": 2.3, "L": 2.833},
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                    "T": {"timestamp": 1.438},
                    "A": {"timestamp": 1.75},
                    "L": {
                        "timestamp": 1.875,
                        "warnings": ["landing_geometry_weak"],
                        "evidence": {
                            "score_components": {
                                "landing_contact": 0.161,
                                "ankle_return": 0.245,
                                "knee_absorption": 0.0,
                            }
                        },
                    },
                },
            },
            "frame_motion_scores": {
                "selected": [{"frame_id": "frame_0021", "timestamp": 1.875, "motion_score": 0.0128}],
                "resolved_keyframes": {
                    "source": "video_ai_refined",
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 2.053, "phase_code": "takeoff"},
                        {"frame_id": "semantic_0002", "timestamp": 2.3, "phase_code": "air"},
                        {"frame_id": "semantic_0003", "timestamp": 2.833, "phase_code": "landing"},
                    ],
                },
            },
            "video_temporal_diagnostics": {"used_semantic_frames": True},
        }

        row = _analysis_row({"video": "weak-landing.mp4", "analysis_id": "analysis-1"}, analysis)

        self.assertTrue(row["candidate_delta_untrusted"])
        self.assertIn("tal_candidate_landing_geometry_weak", row["candidate_delta_untrusted_reasons"])
        self.assertEqual(row["candidate_semantic_delta_status"], {"T": "early", "A": "early", "L": "early"})
        self.assertEqual(row["trusted_candidate_semantic_delta_status"], {"T": None, "A": None, "L": None})

    def test_normalize_precomputed_row_recomputes_untrusted_candidate_delta(self) -> None:
        row = {
            "video": "old-sparse.mp4",
            "status": "completed",
            "analysis_id": "analysis-1",
            "force_score": 76,
            "bio_timestamps": {"T": 3.453, "A": 3.8, "L": 4.033},
            "candidate_semantic_delta": {"T": -0.828, "A": -1.112, "L": 0.029},
            "candidate_resolved_delta": {"T": -0.828, "A": -1.112, "L": 0.029},
            "trusted_candidate_semantic_delta": {"T": -0.828, "A": -1.112, "L": 0.029},
            "trusted_candidate_resolved_delta": {"T": -0.828, "A": -1.112, "L": 0.029},
            "target_quality_flags": [],
            "semantic_flags": [],
            "keyframe_candidate_flags": ["tal_candidate_sparse_track_stitched"],
            "tracker_state_counts": {},
            "bio_motion_peak_delta": {},
            "candidate_motion_peak_delta": {"T": 0.0, "A": 0.3, "L": 0.1},
            "trusted_candidate_motion_peak_delta": {"T": 0.0, "A": 0.3, "L": 0.1},
        }

        normalized = _normalize_precomputed_row(row)

        self.assertTrue(normalized["candidate_delta_untrusted"])
        self.assertEqual(normalized["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(normalized["trusted_candidate_motion_peak_delta"], {"T": None, "A": None, "L": None})
        self.assertEqual(normalized["trusted_candidate_semantic_delta_status"], {"T": None, "A": None, "L": None})

    def test_normalize_precomputed_row_marks_tiny_target_weak_geometry_untrusted(self) -> None:
        row = {
            "video": "tiny-weak-geometry.mp4",
            "status": "completed",
            "analysis_id": "analysis-1",
            "force_score": 76,
            "bio_timestamps": {"T": 3.7, "A": 4.1, "L": 4.5},
            "candidate_semantic_delta": {"T": -0.533, "A": -0.6, "L": -0.833},
            "candidate_resolved_delta": {"T": -0.533, "A": -0.6, "L": -0.833},
            "trusted_candidate_semantic_delta": {"T": -0.533, "A": -0.6, "L": -0.833},
            "trusted_candidate_resolved_delta": {"T": -0.533, "A": -0.6, "L": -0.833},
            "target_quality_flags": ["person_tracker_tiny_target_low_pose_tracking_risk"],
            "semantic_flags": [],
            "keyframe_candidate_flags": ["tal_candidate_tiny_target_weak_geometry"],
            "tracker_state_counts": {},
            "bio_motion_peak_delta": {},
        }

        normalized = _normalize_precomputed_row(row)

        self.assertTrue(normalized["candidate_delta_untrusted"])
        self.assertIn(
            "tal_candidate_tiny_target_weak_geometry",
            normalized["candidate_delta_untrusted_reasons"],
        )
        self.assertEqual(normalized["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})

    def test_normalize_precomputed_row_marks_late_weak_landing_untrusted(self) -> None:
        row = {
            "video": "late-weak-landing.mp4",
            "status": "completed",
            "analysis_id": "analysis-1",
            "force_score": 76,
            "bio_timestamps": {"T": 1.7, "A": 2.0, "L": 2.3},
            "candidate_semantic_delta": {"T": -0.012, "A": 0.188, "L": 1.388},
            "candidate_resolved_delta": {"T": -0.012, "A": 0.188, "L": 1.388},
            "trusted_candidate_semantic_delta": {"T": -0.012, "A": 0.188, "L": 1.388},
            "trusted_candidate_resolved_delta": {"T": -0.012, "A": 0.188, "L": 1.388},
            "target_quality_flags": [],
            "semantic_flags": [],
            "keyframe_candidate_flags": ["tal_candidate_late_weak_landing"],
            "tracker_state_counts": {},
            "bio_motion_peak_delta": {},
        }

        normalized = _normalize_precomputed_row(row)

        self.assertTrue(normalized["candidate_delta_untrusted"])
        self.assertIn("tal_candidate_late_weak_landing", normalized["candidate_delta_untrusted_reasons"])
        self.assertEqual(normalized["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})

    def test_normalize_precomputed_row_marks_early_weak_motion_window_untrusted(self) -> None:
        row = {
            "video": "early-weak-window.mp4",
            "status": "completed",
            "analysis_id": "analysis-1",
            "force_score": 76,
            "bio_timestamps": {"T": 5.67, "A": 6.17, "L": 6.6},
            "candidate_semantic_delta": {"T": -4.795, "A": -4.67, "L": -4.725},
            "candidate_resolved_delta": {"T": -4.795, "A": -4.67, "L": -4.725},
            "trusted_candidate_semantic_delta": {"T": -4.795, "A": -4.67, "L": -4.725},
            "trusted_candidate_resolved_delta": {"T": -4.795, "A": -4.67, "L": -4.725},
            "target_quality_flags": [],
            "semantic_flags": [],
            "keyframe_candidate_flags": [
                "keyframe_candidates_early_motion_window_weak_geometry",
                "tal_candidate_early_motion_window_weak_geometry",
            ],
            "tracker_state_counts": {},
            "bio_motion_peak_delta": {},
        }

        normalized = _normalize_precomputed_row(row)

        self.assertTrue(normalized["candidate_delta_untrusted"])
        self.assertIn(
            "keyframe_candidates_early_motion_window_weak_geometry",
            normalized["candidate_delta_untrusted_reasons"],
        )
        self.assertIn(
            "tal_candidate_early_motion_window_weak_geometry",
            normalized["candidate_delta_untrusted_reasons"],
        )
        self.assertEqual(normalized["trusted_candidate_semantic_delta"], {"T": None, "A": None, "L": None})

    def test_tracker_sequence_summary_graces_short_terminal_loss(self) -> None:
        diagnostics = [{"state": "tracked"} for _ in range(8)] + [{"state": "lost_reused"}, {"state": "lost_reused"}]

        summary = _tracker_sequence_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 2)
        self.assertEqual(summary["tracked_frames"], 8)
        self.assertEqual(summary["total_frames"], 10)
        self.assertTrue(summary["terminal_loss_graced"])
        self.assertFalse(summary["final_unrecovered"])
        self.assertFalse(summary["transient_loss_recovered"])

    def test_tracker_sequence_summary_recomputes_cached_four_frame_tail(self) -> None:
        diagnostics = (
            [{"state": "tracked"} for _ in range(13)]
            + [{"state": "full_frame_yolo_relock_pending"}, {"state": "detector_relocked"}] * 5
            + [{"state": "tracked"} for _ in range(5)]
            + [{"state": "lost_reused"}, {"state": "relock_rejected"}, {"state": "full_frame_yolo_relock_pending"}]
            + [
                {
                    "state": "lost_reused",
                    "sequence_summary": {"terminal_loss_graced": False, "final_unrecovered": True},
                }
            ]
        )

        summary = _tracker_sequence_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 4)
        self.assertTrue(summary["terminal_loss_graced"])
        self.assertFalse(summary["final_unrecovered"])
        self.assertTrue(summary["transient_loss_recovered"])

    def test_tracker_sequence_summary_keeps_long_terminal_loss_unrecovered(self) -> None:
        diagnostics = [{"state": "tracked"} for _ in range(8)] + [
            {"state": "lost_reused"},
            {"state": "lost_reused"},
            {"state": "lost_reused"},
        ]

        summary = _tracker_sequence_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 3)
        self.assertFalse(summary["terminal_loss_graced"])
        self.assertTrue(summary["final_unrecovered"])

    def test_tracker_sequence_summary_keeps_excessive_terminal_tail_unrecovered(self) -> None:
        diagnostics = [{"state": "tracked"} for _ in range(16)] + [
            {"state": "lost_reused"},
            {"state": "lost_reused"},
            {"state": "lost_reused"},
            {"state": "lost_reused"},
            {"state": "lost_reused"},
            {"state": "relock_pending"},
            {"state": "lost_reused"},
        ]

        summary = _tracker_sequence_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 7)
        self.assertFalse(summary["terminal_loss_graced"])
        self.assertTrue(summary["final_unrecovered"])

    def test_tracker_sequence_summary_graces_moderate_tail_after_stable_history(self) -> None:
        diagnostics = [{"state": "tracked"} for _ in range(12)] + [
            {"state": "full_frame_yolo_relock_pending"},
            {"state": "relock_pending"},
            {"state": "lost_reused"},
        ]

        summary = _tracker_sequence_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 3)
        self.assertEqual(summary["tracked_frames"], 12)
        self.assertTrue(summary["terminal_loss_graced"])
        self.assertFalse(summary["final_unrecovered"])

    def test_tracker_sequence_summary_keeps_moderate_tail_without_stable_history_unrecovered(self) -> None:
        diagnostics = [{"state": "tracked"} for _ in range(8)] + [
            {"state": "full_frame_yolo_relock_pending"},
            {"state": "relock_pending"},
            {"state": "lost_reused"},
        ]

        summary = _tracker_sequence_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 3)
        self.assertEqual(summary["tracked_frames"], 8)
        self.assertFalse(summary["terminal_loss_graced"])
        self.assertTrue(summary["final_unrecovered"])

    def test_aggregate_derives_delta_direction_for_precomputed_rows(self) -> None:
        rows = [
            {
                "video": "old.mp4",
                "status": "completed",
                "analysis_id": "a",
                "force_score": 80,
                "bio_timestamps": {"T": 0.8, "A": 1.1, "L": 1.6},
                "bio_semantic_delta": {"T": -0.2, "A": 0.0, "L": 0.2},
                "bio_resolved_delta": {"T": -0.05, "A": 0.05, "L": 0.15},
                "target_quality_flags": [],
                "semantic_flags": [],
                "keyframe_candidate_flags": [],
                "tracker_state_counts": {},
                "bio_motion_peak_delta": {},
            }
        ]
        normalized = [_normalize_precomputed_row(row) for row in rows]

        aggregate = _aggregate(normalized)

        self.assertEqual(aggregate["bio_semantic_delta_direction_counts"]["T"], {"within": 0, "early": 1, "late": 0, "missing": 0})
        self.assertEqual(aggregate["bio_resolved_delta_direction_counts"]["L"], {"within": 0, "early": 0, "late": 1, "missing": 0})

    def test_refresh_target_preview_replaces_target_lock_candidate_diagnostics(self) -> None:
        analysis = {
            "id": "analysis-1",
            "status": "awaiting_target_selection",
            "target_lock": {
                "status": "awaiting_manual",
                "selected_candidate_id": "old",
                "quality_flags": [
                    "target_lock_stable_zoomed_candidate_auto_locked",
                    "person_tracker_target_lost",
                ],
                "person_tracker_diagnostics": [
                    {"state": "tracked"},
                    {"state": "lost_reused"},
                ],
                "candidates": [
                    {
                        "id": "old",
                        "bbox": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1},
                        "confidence": 0.8,
                        "source": "yolo_zoomed_content",
                    }
                ],
            },
        }
        preview = {
            "target_lock_status": "awaiting_manual",
            "auto_candidate_id": "new",
            "lock_confidence": 0.87,
            "candidates": [
                {
                    "id": "new",
                    "bbox": {"x": 0.2, "y": 0.2, "width": 0.05, "height": 0.2},
                    "confidence": 0.87,
                    "source": "yolo_zoomed_content",
                    "multiperson_ambiguous_frame_count": 2,
                    "multiperson_competitor_count": 3,
                    "quality_flags": [
                        "target_lock_zoomed_multiperson_manual_review",
                        "target_lock_auto_lock_blocked_by_manual_review",
                    ],
                }
            ],
        }

        refreshed = _with_refreshed_target_preview(analysis, preview)
        row = _analysis_row({"video": "sample.mp4", "analysis_id": "analysis-1"}, refreshed)
        aggregate = _aggregate([row])

        self.assertTrue(row["target_preview_refreshed"])
        self.assertEqual(row["target_selected_candidate_id"], "new")
        self.assertEqual(row["target_lock_confidence"], 0.87)
        self.assertEqual(row["target_preview_candidate_count"], 1)
        self.assertTrue(row["target_manual_review_required"])
        self.assertTrue(row["target_auto_lock_blocked"])
        self.assertEqual(row["target_manual_review_flags"], ["target_lock_zoomed_multiperson_manual_review"])
        self.assertEqual(row["target_auto_lock_blocked_flags"], ["target_lock_auto_lock_blocked_by_manual_review"])
        self.assertEqual(row["target_selected_candidate"]["multiperson_ambiguous_frame_count"], 2)
        self.assertEqual(row["target_selected_candidate"]["multiperson_competitor_count"], 3)
        self.assertNotIn("target_lock_stable_zoomed_candidate_auto_locked", row["target_quality_flags"])
        self.assertIn("target_lock_auto_lock_blocked_by_manual_review", row["target_quality_flags"])
        self.assertIn("person_tracker_target_lost", row["target_quality_flags"])
        self.assertEqual(row["tracker_state_counts"], {"tracked": 1, "lost_reused": 1})
        self.assertEqual(aggregate["target_status_counts"], {"awaiting_manual": 1})
        self.assertEqual(aggregate["target_preview_refreshed_count"], 1)
        self.assertEqual(aggregate["target_manual_review_required_count"], 1)
        self.assertEqual(aggregate["target_auto_lock_blocked_count"], 1)
        self.assertEqual(
            aggregate["top_target_manual_review_flags"],
            [("target_lock_zoomed_multiperson_manual_review", 1)],
        )
        self.assertEqual(
            aggregate["top_target_auto_lock_blocked_flags"],
            [("target_lock_auto_lock_blocked_by_manual_review", 1)],
        )
        self.assertEqual(
            aggregate["target_selected_candidate_metric_summary"]["multiperson_competitor_count"],
            {"average": 3.0, "max": 3.0},
        )
        self.assertEqual(aggregate["target_manual_review_samples"][0]["video"], "sample.mp4")
        self.assertEqual(aggregate["target_manual_review_samples"][0]["multiperson_ambiguous_frame_count"], 2)

    def test_batch_items_accepts_precomputed_diagnostics_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "diagnostics.json"
            path.write_text(
                """
                {
                  "rows": [
                    {"video": "same.mp4", "analysis_id": "a", "status": "completed"},
                    {"video": "same.mp4", "analysis_id": "a", "status": "completed"},
                    {"video": "other.mp4", "analysis_id": "b", "status": "completed"}
                  ]
                }
                """,
                encoding="utf-8",
            )

            items = _batch_items([path])

        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["_precomputed_diagnostics"])
        self.assertEqual(items[0]["_batch_file"], "diagnostics.json")


if __name__ == "__main__":
    unittest.main()
