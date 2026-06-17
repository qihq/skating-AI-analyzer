from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.biomechanics import (
    analyze_biomechanics,
    calc_arm_symmetry,
    calc_center_of_mass_trajectory,
    sync_key_frames_from_resolved_keyframes,
)


def _build_keypoints(
    *,
    shoulder_left: tuple[float, float],
    shoulder_right: tuple[float, float],
    hip_left: tuple[float, float],
    hip_right: tuple[float, float],
    wrist_left: tuple[float, float],
    wrist_right: tuple[float, float],
) -> list[dict[str, float]]:
    keypoints: list[dict[str, float]] = [{"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0} for index in range(33)]
    for index, (x_value, y_value) in {
        11: shoulder_left,
        12: shoulder_right,
        15: wrist_left,
        16: wrist_right,
        23: hip_left,
        24: hip_right,
    }.items():
        keypoints[index] = {"id": index, "x": x_value, "y": y_value, "z": 0.0, "visibility": 0.99}
    return keypoints


def _scale_point(x_value: float, y_value: float, scale: float) -> tuple[float, float]:
    return x_value * scale, y_value * scale


def _scaled_keypoints(scale: float, com_shift: float = 0.0) -> list[dict[str, float]]:
    return _build_keypoints(
        shoulder_left=_scale_point(0.40, 0.20 + com_shift, scale),
        shoulder_right=_scale_point(0.60, 0.20 + com_shift, scale),
        hip_left=_scale_point(0.43, 0.50 + com_shift, scale),
        hip_right=_scale_point(0.57, 0.50 + com_shift, scale),
        wrist_left=_scale_point(0.25, 0.24 + com_shift, scale),
        wrist_right=_scale_point(0.75, 0.24 + com_shift, scale),
    )


def _spin_keypoints(left_hip_x: float, right_hip_x: float, ankle_y: float = 0.88, y_shift: float = 0.0) -> list[dict[str, float]]:
    keypoints: list[dict[str, float]] = [{"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0} for index in range(33)]
    visible_points = {
        11: (0.42, 0.20 + y_shift),
        12: (0.58, 0.20 + y_shift),
        15: (0.35, 0.30 + y_shift),
        16: (0.65, 0.30 + y_shift),
        23: (left_hip_x, 0.50 + y_shift),
        24: (right_hip_x, 0.50 + y_shift),
        25: (0.45, 0.70 + y_shift),
        26: (0.55, 0.70 + y_shift),
        27: (0.46, ankle_y + y_shift),
        28: (0.54, ankle_y + y_shift),
    }
    for index, (x_value, y_value) in visible_points.items():
        keypoints[index] = {"id": index, "x": x_value, "y": y_value, "z": 0.0, "visibility": 0.99}
    return keypoints


class BiomechanicsNormalizationTests(unittest.TestCase):
    def test_sync_key_frames_from_resolved_keyframes_updates_legacy_jump_frames(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0001", "A": "frame_0002", "L": "frame_0003"},
            "quality_flags": ["existing_flag"],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.87,
            "selected": [
                {"frame_id": "semantic_0001.jpg", "timestamp": 1.2, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002.jpg", "timestamp": 1.5, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003.jpg", "timestamp": 1.8, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["raw_biomechanics_key_frames"], bio_data["key_frames"])
        self.assertEqual(synced["key_frame_timestamps"], {"T": 1.2, "A": 1.5, "L": 1.8})
        self.assertEqual(synced["key_frame_source"], "video_ai_refined")
        self.assertEqual(synced["key_frame_confidence"], 0.87)
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_keeps_jump_frames_when_resolved_tal_is_incomplete(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"},
            "key_frame_timestamps": {"T": 2.645, "L": 3.562},
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0007", "timestamp": 0.625, "confidence": 0.511},
                "A": {"frame_id": "frame_0011", "timestamp": 0.875, "confidence": 0.508},
                "L": {"frame_id": "frame_0016", "timestamp": 1.625, "confidence": 0.506},
            },
            "quality_flags": ["bio_key_frames_synced_from_resolved_keyframes"],
        }
        resolved = {
            "source": "video_ai_refined",
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.2, "phase_code": "takeoff"},
                {"frame_id": "semantic_0002", "timestamp": 1.5, "phase_code": "landing"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0007", "A": "frame_0011", "L": "frame_0016"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 0.625, "A": 0.875, "L": 1.625})
        self.assertEqual(synced["key_frame_source"], "biomechanics_candidates")
        self.assertIn("bio_key_frames_not_synced_incomplete_resolved_tal", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_restores_candidates_when_blended_has_no_core_tal(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0004", "A": "frame_0032", "L": "frame_0032"},
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0015", "timestamp": 1.438, "confidence": 0.459},
                "A": {"frame_id": "frame_0017", "timestamp": 1.875, "confidence": 0.514},
                "L": {"frame_id": "frame_0019", "timestamp": 2.25, "confidence": 0.526},
            },
            "quality_flags": ["bio_key_frames_synced_from_resolved_keyframes"],
        }
        resolved = {
            "source": "blended",
            "quality_flags": ["video_temporal_quality_retry_used"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 3.1, "phase_code": "preparation"},
                {"frame_id": "semantic_0002", "timestamp": 5.0, "phase_code": "glide_out"},
                {"frame_id": "semantic_0003", "timestamp": 1.5, "phase_code": "approach"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0015", "A": "frame_0017", "L": "frame_0019"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 1.438, "A": 1.875, "L": 2.25})
        self.assertEqual(synced["key_frame_source"], "biomechanics_candidates")
        self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_keeps_biomechanics_frames_when_semantic_frames_are_unreliable(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"},
            "raw_biomechanics_key_frames": {"T": "frame_0001", "A": "frame_0002", "L": "frame_0003"},
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0004", "timestamp": 1.1, "confidence": 0.7},
                "A": {"frame_id": "frame_0005", "timestamp": 1.4, "confidence": 0.8},
                "L": {"frame_id": "frame_0006", "timestamp": 1.7, "confidence": 0.9},
            },
            "quality_flags": ["bio_key_frames_synced_from_resolved_keyframes"],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": [
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_quality_retry_rejected",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.2, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 1.5, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 1.8, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
            "video_temporal_quality_retry_rejection_flags": [
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0004", "A": "frame_0005", "L": "frame_0006"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 1.1, "A": 1.4, "L": 1.7})
        self.assertEqual(synced["key_frame_source"], "biomechanics_candidates")
        self.assertEqual(synced["key_frame_confidence"], 0.8)
        self.assertNotIn("raw_biomechanics_key_frames", synced)
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_keeps_biomechanics_frames_when_semantic_conflict_unresolved(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"},
            "raw_biomechanics_key_frames": {"T": "frame_0003", "A": "frame_0016", "L": "frame_0026"},
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0013", "timestamp": 4.125, "confidence": 0.699},
                "A": {"frame_id": "frame_0016", "timestamp": 5.25, "confidence": 0.613},
                "L": {"frame_id": "frame_0020", "timestamp": 7.562, "confidence": 0.68},
            },
            "quality_flags": ["bio_key_frames_synced_from_resolved_keyframes"],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.7,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "video_temporal_quality_retry_skeleton_tal_conflict",
                "video_temporal_quality_retry_skeleton_tal_conflict_rejected",
                "video_temporal_quality_retry_rejected",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 3.153, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 3.8, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 4.233, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
            "video_temporal_quality_retry_rejection_flags": [
                "video_temporal_quality_retry_skeleton_tal_conflict_rejected",
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0013", "A": "frame_0016", "L": "frame_0020"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 4.125, "A": 5.25, "L": 7.562})
        self.assertEqual(synced["key_frame_source"], "biomechanics_candidates")
        self.assertEqual(synced["key_frame_confidence"], 0.664)
        self.assertNotIn("raw_biomechanics_key_frames", synced)
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_synced_unresolved_semantic_tal_conflict", synced["quality_flags"])

    def test_sync_key_frames_does_not_restore_sparse_track_stitched_candidates(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"},
            "raw_biomechanics_key_frames": {"T": "frame_0004", "A": "frame_0005", "L": "frame_0006"},
            "key_frame_candidates": {
                "quality_flags": [
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_sparse_track_stitched",
                    "tal_candidate_unreliable_sparse_track_stitch",
                ],
                "T": {"frame_id": "frame_0013", "timestamp": 4.125, "confidence": 0.34},
                "A": {"frame_id": "frame_0014", "timestamp": 4.188, "confidence": 0.34},
                "L": {"frame_id": "frame_0030", "timestamp": 9.812, "confidence": 0.34},
            },
            "quality_flags": ["bio_key_frames_synced_from_resolved_keyframes"],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.75,
            "quality_flags": [
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_quality_retry_rejected",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.02, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 5.3, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 5.733, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0004", "A": "frame_0005", "L": "frame_0006"})
        self.assertEqual(synced["key_frame_source"], "raw_biomechanics_key_frames")
        self.assertNotIn("key_frame_timestamps", synced)
        self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])

    def test_sync_key_frames_clears_weak_candidate_frames_when_sampled_fallback_is_unreliable(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0022", "A": "frame_0024", "L": "frame_0027"},
            "key_frame_timestamps": {"T": 4.562, "A": 4.688, "L": 5.938},
            "key_frame_source": "biomechanics_candidates",
            "key_frame_confidence": 0.437,
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_landing_geometry_absent",
                    "tal_candidate_weak_geometry",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                ],
                "T": {
                    "frame_id": "frame_0022",
                    "timestamp": 4.562,
                    "confidence": 0.49,
                    "warnings": ["knee_extension_weak", "tal_candidate_temporal_geometry_unreliable"],
                },
                "A": {
                    "frame_id": "frame_0024",
                    "timestamp": 4.688,
                    "confidence": 0.47,
                    "warnings": ["apex_local_minimum_not_clear", "tal_candidate_temporal_geometry_unreliable"],
                },
                "L": {
                    "frame_id": "frame_0027",
                    "timestamp": 5.938,
                    "confidence": 0.35,
                    "warnings": [
                        "landing_geometry_weak",
                        "landing_geometry_absent",
                        "tal_candidate_temporal_geometry_unreliable",
                    ],
                },
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_detector_relocked",
                "person_tracker_transient_loss_recovered",
                "bio_key_frames_synced_from_resolved_keyframes",
            ],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.5,
            "quality_flags": [
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_partial_core_frames_available",
                "video_temporal_quality_retry_rejected",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 4.6, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 4.9, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 5.4, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {})
        self.assertNotIn("key_frame_timestamps", synced)
        self.assertNotIn("key_frame_source", synced)
        self.assertNotIn("key_frame_confidence", synced)
        self.assertNotIn("raw_biomechanics_key_frames", synced)
        self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_restores_bounded_motion_fallback_when_sampled_fallback_is_unreliable(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_candidate_skeleton_drifted_after_takeoff",
                ],
                "T": {
                    "frame_id": "frame_0018",
                    "timestamp": 1.625,
                    "confidence": 0.806,
                    "warnings": ["keyframe_candidates_motion_fallback"],
                },
                "A": {
                    "frame_id": "frame_0019",
                    "timestamp": 1.875,
                    "confidence": 0.487,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                },
                "L": {
                    "frame_id": "frame_0023",
                    "timestamp": 2.312,
                    "confidence": 0.476,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted"],
                },
            },
            "quality_flags": ["bio_key_frames_synced_from_resolved_keyframes"],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.5,
            "quality_flags": [
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_partial_core_frames_available",
                "video_temporal_quality_retry_rejected",
                "video_temporal_quality_retry_motion_cluster_conflict",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.3, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 1.65, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 1.9, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
            "video_temporal_quality_retry_rejection_flags": [
                "video_temporal_quality_retry_motion_cluster_conflict",
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0018", "A": "frame_0019", "L": "frame_0023"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 1.625, "A": 1.875, "L": 2.312})
        self.assertEqual(synced["key_frame_source"], "biomechanics_candidates")
        self.assertEqual(synced["key_frame_confidence"], 0.59)
        self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_restored_bounded_motion_fallback", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_restores_dense_tail_excluded_bounded_motion_fallback_when_sampled_fallback_is_unreliable(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0016", "A": "frame_0017", "L": "frame_0017"},
            "key_frame_timestamps": {"T": 4.812, "A": 5.188, "L": 5.688},
            "key_frame_source": "biomechanics_candidates",
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_excluded_rejected_tail_window",
                    "keyframe_candidates_motion_fallback_dense_scores",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "T": {"frame_id": "frame_0016", "timestamp": 4.812, "confidence": 0.486},
                "A": {"frame_id": "frame_0017", "timestamp": 5.188, "confidence": 0.494},
                "L": {"frame_id": "frame_0017", "timestamp": 5.688, "confidence": 0.498},
            },
            "quality_flags": [
                "target_lock_zoomed_multiperson_manual_review",
                "person_tracker_target_lost",
                "person_tracker_detector_relocked",
                "person_tracker_transient_loss_recovered",
                "bio_key_frames_synced_from_resolved_keyframes",
            ],
        }
        resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.75,
            "quality_flags": [
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_partial_core_frames_available",
                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                "video_temporal_quality_retry_rejected",
                "video_temporal_quality_retry_motion_cluster_conflict",
            ],
            "selected": [
                {
                    "frame_id": "frame_0016",
                    "timestamp": 4.812,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "fallback_to_keyframe_candidates",
                },
                {
                    "frame_id": "frame_0017",
                    "timestamp": 5.188,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "fallback_to_keyframe_candidates",
                },
                {
                    "frame_id": "frame_0017",
                    "timestamp": 5.688,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "fallback_to_keyframe_candidates",
                },
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0016", "A": "frame_0017", "L": "frame_0017"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 4.812, "A": 5.188, "L": 5.688})
        self.assertEqual(synced["key_frame_source"], "biomechanics_candidates")
        self.assertEqual(synced["key_frame_confidence"], 0.493)
        self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_restored_bounded_motion_fallback", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_uses_semantic_when_motion_conflict_matches_unreliable_pose_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0010", "A": "frame_0011", "L": "frame_0015"},
            "key_frame_timestamps": {"T": 1.312, "A": 1.688, "L": 2.562},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    "tal_candidate_motion_fallback_unreliable_pose_low_confidence",
                ],
                "T": {"frame_id": "frame_0010", "timestamp": 1.312, "confidence": 0.617},
                "A": {"frame_id": "frame_0011", "timestamp": 1.688, "confidence": 0.47},
                "L": {
                    "frame_id": "frame_0015",
                    "timestamp": 2.562,
                    "confidence": 0.34,
                    "warnings": ["keyframe_candidates_motion_fallback_unreliable_pose_state"],
                },
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_transient_loss_recovered",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.7,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_quality_retry_motion_cluster_conflict_ignored_unreliable_pose_fallback",
            ],
            "semantic_motion_cluster_conflict": {
                "decision": "ignored_unreliable_pose_motion_fallback_cluster",
            },
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 5.4, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 5.7, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 5.0, "A": 5.4, "L": 5.7})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0010", "A": "frame_0011", "L": "frame_0015"})
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unresolved_semantic_tal_conflict", synced["quality_flags"])

    def test_sync_key_frames_uses_semantic_when_motion_conflict_has_near_skeleton_candidate_support(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0019", "A": "frame_0022", "L": "frame_0023"},
            "key_frame_timestamps": {"T": 1.875, "A": 2.25, "L": 2.312},
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0019", "timestamp": 1.875, "confidence": 0.702},
                "A": {"frame_id": "frame_0022", "timestamp": 2.25, "confidence": 0.481},
                "L": {"frame_id": "frame_0023", "timestamp": 2.312, "confidence": 0.35},
            },
            "quality_flags": [],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate",
            ],
            "semantic_motion_cluster_conflict": {
                "decision": "ignored_near_skeleton_candidate_tal",
            },
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.795, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 2.2, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.333, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 1.795, "A": 2.2, "L": 2.333})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0019", "A": "frame_0022", "L": "frame_0023"})
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unresolved_semantic_tal_conflict", synced["quality_flags"])

    def test_sync_key_frames_uses_semantic_when_motion_conflict_ignored_for_weak_geometry(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0027", "A": "frame_0031", "L": "frame_0032"},
            "key_frame_timestamps": {"T": 5.875, "A": 7.688, "L": 7.75},
            "key_frame_candidates": {
                "quality_flags": [
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_takeoff_apex_gap_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                ],
                "T": {"frame_id": "frame_0027", "timestamp": 5.875, "confidence": 0.34},
                "A": {"frame_id": "frame_0031", "timestamp": 7.688, "confidence": 0.34},
                "L": {"frame_id": "frame_0032", "timestamp": 7.75, "confidence": 0.34},
            },
            "quality_flags": [
                "bio_key_frames_not_synced_unresolved_semantic_tal_conflict",
                "bio_key_frames_not_synced_unreliable_resolved_keyframes",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.75,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry",
                "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
                "video_temporal_quality_retry_motion_cluster_conflict_ignored_weak_temporal_geometry",
            ],
            "semantic_motion_cluster_conflict": {
                "decision": "ignored_weak_temporal_geometry_candidate_motion_cluster",
            },
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 4.887, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 5.3, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 5.6, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 4.887, "A": 5.3, "L": 5.6})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0027", "A": "frame_0031", "L": "frame_0032"})
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unresolved_semantic_tal_conflict", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_uses_motion_cluster_fallback_after_retry_conflict(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0009", "A": "frame_0031", "L": "frame_0032"},
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0009", "timestamp": 0.812, "confidence": 0.843},
                "A": {"frame_id": "frame_0031", "timestamp": 5.875, "confidence": 0.527},
                "L": {"frame_id": "frame_0032", "timestamp": 6.625, "confidence": 0.35},
            },
            "quality_flags": [],
        }
        resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.9,
            "quality_flags": [
                "video_temporal_quality_retry_skeleton_tal_conflict",
                "video_temporal_quality_retry_motion_cluster_conflict",
                "video_temporal_quality_retry_rejected",
                "video_temporal_resolver_motion_cluster_fallback_used",
                "video_temporal_quality_retry_motion_cluster_fallback_used",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 0.812, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.66},
                {"frame_id": "semantic_0002", "timestamp": 1.062, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.66},
                {"frame_id": "semantic_0003", "timestamp": 1.625, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.66},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 0.812, "A": 1.062, "L": 1.625})
        self.assertEqual(synced["key_frame_source"], "skeleton_fallback")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unresolved_semantic_tal_conflict", synced["quality_flags"])

    def test_sync_key_frames_clears_biomechanics_when_tracker_final_loss_forces_motion_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0003", "A": "frame_0013", "L": "frame_0032"},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                ],
                "T": {"frame_id": "frame_0003", "timestamp": 0.438, "confidence": 0.54},
                "A": {"frame_id": "frame_0013", "timestamp": 2.938, "confidence": 0.54},
                "L": {"frame_id": "frame_0032", "timestamp": 11.25, "confidence": 0.54},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_final_unrecovered",
                "bio_key_frames_synced_from_resolved_keyframes",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 6.703, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 7.0, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 7.583, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {})
        self.assertNotIn("key_frame_timestamps", synced)
        self.assertNotIn("key_frame_source", synced)
        self.assertNotIn("key_frame_confidence", synced)
        self.assertIn("bio_key_frames_not_synced_tracker_final_loss_motion_fallback", synced["quality_flags"])
        self.assertIn("tal_candidate_unreliable_tracker_final_loss", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_uses_visible_semantic_promoted_after_tracker_final_loss_motion_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0012", "A": "frame_0013", "L": "frame_0014"},
            "key_frame_timestamps": {"T": 2.875, "A": 2.938, "L": 3.0},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                ],
                "T": {"frame_id": "frame_0012", "timestamp": 2.875, "confidence": 0.54},
                "A": {"frame_id": "frame_0013", "timestamp": 2.938, "confidence": 0.54},
                "L": {"frame_id": "frame_0014", "timestamp": 3.0, "confidence": 0.504},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_final_unrecovered",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": [
                "semantic_keyframes_tracker_final_loss_visual_tal_promoted",
                "video_temporal_resolver_low_confidence_visual_tal_promoted",
                "video_temporal_resolver_low_confidence_zoomed_visual_check",
            ],
            "semantic_tracker_final_loss_visual_promotion": {
                "decision": "promoted_visible_video_tal_over_low_visibility_motion_fallback",
            },
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 6.3,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "semantic_visibility": {"status": "target_visible"},
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 6.65,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "semantic_visibility": {"status": "target_visible"},
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 6.9,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "semantic_visibility": {"status": "target_visible"},
                },
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 6.3, "A": 6.65, "L": 6.9})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0012", "A": "frame_0013", "L": "frame_0014"})
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_motion_fallback", synced["quality_flags"])

    def test_sync_key_frames_uses_semantic_when_tracker_final_loss_motion_fallback_was_ignored(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0016", "A": "frame_0031", "L": "frame_0032"},
            "key_frame_timestamps": {"T": 1.562, "A": 4.812, "L": 4.875},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_insufficient_pose",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    "tal_candidate_motion_fallback_unreliable_pose_low_confidence",
                ],
                "T": {"frame_id": "frame_0016", "timestamp": 1.562, "confidence": 0.34},
                "A": {"frame_id": "frame_0031", "timestamp": 4.812, "confidence": 0.34},
                "L": {"frame_id": "frame_0032", "timestamp": 4.875, "confidence": 0.34},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_final_unrecovered",
                "bio_key_frames_not_synced_tracker_final_loss_motion_fallback",
                "tal_candidate_unreliable_tracker_final_loss",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_tracker_final_loss_motion_fallback_ignored",
            ],
            "semantic_tracker_final_loss_motion_fallback": {
                "candidate_tal_span_sec": 3.313,
                "decision": "ignored_unbounded_motion_fallback",
            },
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 2.453, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 2.6, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.767, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 2.453, "A": 2.6, "L": 2.767})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0016", "A": "frame_0031", "L": "frame_0032"})
        self.assertEqual(synced["key_frame_source"], "blended")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_motion_fallback", synced["quality_flags"])

    def test_sync_key_frames_uses_phase_range_promoted_over_low_visibility_motion_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0009", "A": "frame_0010", "L": "frame_0015"},
            "key_frame_timestamps": {"T": 0.625, "A": 0.812, "L": 1.438},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                ],
                "T": {
                    "frame_id": "frame_0009",
                    "timestamp": 0.625,
                    "confidence": 0.57,
                    "evidence": {"visibility_score": 0.937},
                    "warnings": ["keyframe_candidates_motion_fallback"],
                },
                "A": {
                    "frame_id": "frame_0010",
                    "timestamp": 0.812,
                    "confidence": 0.486,
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                },
                "L": {
                    "frame_id": "frame_0015",
                    "timestamp": 1.438,
                    "confidence": 0.501,
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted"],
                },
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_detector_relocked",
                "person_tracker_transient_loss_recovered",
                "bio_key_frames_not_synced_unreliable_resolved_keyframes",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": [
                "semantic_keyframes_phase_range_visual_tal_promoted",
                "video_temporal_resolver_phase_range_visual_tal_promoted",
                "video_temporal_resolver_phase_range_zoomed_visual_check",
            ],
            "semantic_phase_range_visual_promotion": {
                "decision": "promoted_video_phase_range_tal_over_low_visibility_motion_fallback",
                "low_visibility_motion_fallback_keys": ["A", "L"],
            },
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 3.45,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "semantic_visibility": {"status": "target_visible"},
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 3.75,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "semantic_visibility": {"status": "target_visible"},
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 4.267,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "semantic_visibility": {"status": "target_visible"},
                },
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 3.45, "A": 3.75, "L": 4.267})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0009", "A": "frame_0010", "L": "frame_0015"})
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_motion_fallback", synced["quality_flags"])

    def test_sync_key_frames_uses_reused_semantic_over_low_visibility_bounded_motion_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0012", "A": "frame_0016", "L": "frame_0019"},
            "key_frame_timestamps": {"T": 3.188, "A": 3.438, "L": 3.625},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                ],
                "T": {"frame_id": "frame_0012", "timestamp": 3.188, "confidence": 0.54},
                "A": {"frame_id": "frame_0016", "timestamp": 3.438, "confidence": 0.54},
                "L": {"frame_id": "frame_0019", "timestamp": 3.625, "confidence": 0.512},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_final_unrecovered",
                "bio_key_frames_not_synced_tracker_final_loss_motion_fallback",
                "tal_candidate_unreliable_tracker_final_loss",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": [
                "semantic_keyframes_reused_from_matching_video",
                "semantic_keyframes_reused_ignored_low_visibility_bounded_motion_fallback",
                "semantic_keyframes_reuse_candidate_conflict_ignored_insufficient_pose_low_visibility_fallback",
            ],
            "semantic_tracker_final_loss_motion_fallback": {
                "decision": "ignored_reused_semantic_over_low_visibility_bounded_motion_fallback",
            },
            "semantic_reuse_current_candidate_conflict": {
                "decision": "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
            },
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 6.567,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "semantic_reused_from_matching_video",
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 7.2,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "semantic_reused_from_matching_video",
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 7.6,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "semantic_reused_from_matching_video",
                },
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 6.567, "A": 7.2, "L": 7.6})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0012", "A": "frame_0016", "L": "frame_0019"})
        self.assertEqual(synced["key_frame_source"], "blended")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_motion_fallback", synced["quality_flags"])

    def test_sync_key_frames_uses_current_semantic_over_multiperson_low_visibility_motion_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_excluded_rejected_tail_window",
                    "keyframe_candidates_motion_fallback_dense_scores",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                    "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
                    "tal_candidate_motion_fallback_foreground_motion_risk",
                ],
                "T": {"frame_id": "frame_0046", "timestamp": 7.188, "confidence": 0.468},
                "A": {"frame_id": "frame_0047", "timestamp": 7.375, "confidence": 0.467},
                "L": {"frame_id": "frame_0048", "timestamp": 7.562, "confidence": 0.467},
            },
            "quality_flags": [
                "target_lock_zoomed_multiperson_manual_review",
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_detector_relocked",
                "person_tracker_transient_loss_recovered",
                "person_tracker_multiperson_relock_instability_risk",
                "bio_key_frames_not_synced_unresolved_semantic_tal_conflict",
                "bio_key_frames_not_restored_unreliable_candidates",
                "bio_key_frames_not_synced_unreliable_resolved_keyframes",
            ],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_skeleton_t_below_anchor_confidence",
                "video_temporal_resolver_skeleton_a_below_anchor_confidence",
                "video_temporal_resolver_skeleton_l_below_anchor_confidence",
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_candidate_tal_conflict_ignored_insufficient_pose_low_visibility_fallback",
                "video_temporal_quality_retry_motion_cluster_conflict",
                "semantic_keyframes_unreliable_after_refinement",
                "video_temporal_quality_retry_rejected",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "semantic_candidate_tal_conflict": {
                "conflicts": [],
                "candidate_quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_excluded_rejected_tail_window",
                    "keyframe_candidates_motion_fallback_dense_scores",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                    "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
                    "tal_candidate_motion_fallback_foreground_motion_risk",
                ],
                "low_visibility_motion_fallback_keys": ["A", "L", "T"],
                "decision": "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
            },
            "semantic_motion_cluster_conflict": {
                "core_start_sec": 5.187,
                "core_end_sec": 5.967,
                "peak_timestamp": 7.438,
                "peak_motion_score": 0.196,
                "core_peak_motion_score": 0.0828,
            },
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.187, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 5.7, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 5.967, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 5.187, "A": 5.7, "L": 5.967})
        self.assertEqual(synced["key_frame_source"], "video_ai_refined")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unresolved_semantic_tal_conflict", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_uses_reused_semantic_over_long_unresolved_motion_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0008", "A": "frame_0016", "L": "frame_0032"},
            "key_frame_timestamps": {"T": 1.375, "A": 4.375, "L": 7.688},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "T": {"frame_id": "frame_0008", "timestamp": 1.375, "confidence": 0.497},
                "A": {"frame_id": "frame_0016", "timestamp": 4.375, "confidence": 0.473},
                "L": {"frame_id": "frame_0032", "timestamp": 7.688, "confidence": 0.534},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "bio_key_frames_not_synced_tracker_final_loss_motion_fallback",
                "tal_candidate_unreliable_tracker_final_loss",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.6,
            "quality_flags": [
                "semantic_keyframes_reused_from_matching_video",
                "semantic_keyframes_reused_over_long_unresolved_motion_fallback",
                "semantic_keyframes_reuse_candidate_conflict_ignored_long_unresolved_motion_fallback",
            ],
            "semantic_reuse_current_candidate_conflict": {
                "decision": "ignored_reused_semantic_over_long_unresolved_motion_fallback",
                "candidate_tal_span_sec": 6.313,
            },
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 5.953,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "semantic_reused_from_matching_video",
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 6.8,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "semantic_reused_from_matching_video",
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 7.134,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "semantic_reused_from_matching_video",
                },
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 5.953, "A": 6.8, "L": 7.134})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0008", "A": "frame_0016", "L": "frame_0032"})
        self.assertEqual(synced["key_frame_source"], "blended")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_motion_fallback", synced["quality_flags"])

    def test_sync_key_frames_uses_promoted_partial_tal_over_long_unresolved_motion_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_candidate_motion_fallback_cross_segment_unreliable",
                ],
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_pending",
                "person_tracker_final_unrecovered",
                "keyframe_candidates_motion_fallback",
                "tal_candidate_motion_fallback_low_precision",
                "tal_candidate_incomplete",
                "tal_order_unresolved",
                "bio_key_frames_not_synced_tracker_final_loss_motion_fallback",
                "tal_candidate_unreliable_tracker_final_loss",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.65,
            "quality_flags": [
                "video_temporal_resolver_long_unresolved_motion_fallback_partial_tal_promoted",
                "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted",
            ],
            "semantic_long_unresolved_motion_fallback_partial_promotion": {
                "decision": "promoted_partial_video_tal_over_long_unresolved_motion_fallback",
                "candidate_tal_span_sec": 10.666,
            },
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 4.8,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "confidence": 0.6,
                    "selection_reason": "video_temporal_long_unresolved_motion_fallback_partial_tal_promoted",
                    "partial_semantic_key": "T",
                    "semantic_visual_tal_promotion": True,
                    "long_unresolved_motion_fallback_partial_promotion": True,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 5.3,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.5,
                    "selection_reason": "video_temporal_long_unresolved_motion_fallback_partial_tal_promoted",
                    "partial_semantic_key": "A",
                    "semantic_visual_tal_promotion": True,
                    "long_unresolved_motion_fallback_partial_promotion": True,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 5.8,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.6,
                    "selection_reason": "video_temporal_long_unresolved_motion_fallback_partial_tal_promoted",
                    "partial_semantic_key": "L",
                    "semantic_visual_tal_promotion": True,
                    "long_unresolved_motion_fallback_partial_promotion": True,
                },
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 4.8, "A": 5.3, "L": 5.8})
        self.assertEqual(synced["key_frame_source"], "blended")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_synced_from_long_unresolved_visual_tal", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_motion_fallback", synced["quality_flags"])

    def test_sync_key_frames_clears_biomechanics_when_tracker_final_loss_has_weak_geometry(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0023", "A": "frame_0024", "L": "frame_0025"},
            "key_frame_candidates": {
                "quality_flags": [
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_apex_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {"frame_id": "frame_0023", "timestamp": 8.688, "confidence": 0.365},
                "A": {"frame_id": "frame_0024", "timestamp": 8.75, "confidence": 0.447},
                "L": {"frame_id": "frame_0025", "timestamp": 9.188, "confidence": 0.463},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_final_unrecovered",
                "bio_key_frames_synced_from_resolved_keyframes",
            ],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 3.753, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 4.35, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 4.8, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {})
        self.assertNotIn("key_frame_timestamps", synced)
        self.assertNotIn("key_frame_source", synced)
        self.assertNotIn("key_frame_confidence", synced)
        self.assertIn("bio_key_frames_not_synced_tracker_final_loss_weak_geometry", synced["quality_flags"])
        self.assertIn("tal_candidate_unreliable_tracker_final_loss", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_uses_semantic_when_main_motion_accepts_early_weak_geometry(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0005", "A": "frame_0008", "L": "frame_0011"},
            "key_frame_timestamps": {"T": 0.875, "A": 1.5, "L": 1.875},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {"frame_id": "frame_0005", "timestamp": 0.875, "confidence": 0.616},
                "A": {"frame_id": "frame_0008", "timestamp": 1.5, "confidence": 0.581},
                "L": {"frame_id": "frame_0011", "timestamp": 1.875, "confidence": 0.444},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_final_unrecovered",
                "bio_key_frames_not_synced_tracker_final_loss_weak_geometry",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.70,
            "quality_flags": [
                "semantic_keyframes_candidate_tal_conflict_ignored_main_motion_supported_weak_geometry",
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_quality_retry_rejected",
            ],
            "video_temporal_quality_retry_rejection_flags": [
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_unreliable_after_refinement",
            ],
            "semantic_candidate_tal_conflict": {
                "decision": "ignored_early_weak_geometry_candidate_main_motion_supports_semantic_tal",
            },
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.2, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 5.7, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 6.1, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 5.2, "A": 5.7, "L": 6.1})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0005", "A": "frame_0008", "L": "frame_0011"})
        self.assertEqual(synced["key_frame_source"], "blended")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_weak_geometry", synced["quality_flags"])

    def test_sync_key_frames_rejects_early_takeoff_conflicted_reused_semantic_frames(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0018", "A": "frame_0019", "L": "frame_0020"},
            "key_frame_timestamps": {"T": 1.625, "A": 1.875, "L": 2.125},
            "key_frame_candidates": {
                "quality_flags": [
                    "tal_candidate_skeleton_drifted_after_takeoff",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                ],
                "T": {"frame_id": "frame_0018", "timestamp": 1.625, "confidence": 0.806},
                "A": {"frame_id": "frame_0019", "timestamp": 1.875, "confidence": 0.487},
                "L": {"frame_id": "frame_0020", "timestamp": 2.125, "confidence": 0.48},
            },
            "quality_flags": [],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": [
                "semantic_keyframes_reused_from_matching_video",
                "semantic_keyframes_unreliable_candidate_early_takeoff_conflict",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.3, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 1.75, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.25, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0018", "A": "frame_0019", "L": "frame_0020"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 1.625, "A": 1.875, "L": 2.125})
        self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_clears_weak_takeoff_apex_candidate_when_semantic_unreliable(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0024", "A": "frame_0025", "L": "frame_0027"},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                ],
                "T": {
                    "frame_id": "frame_0024",
                    "timestamp": 5.938,
                    "confidence": 0.587,
                    "warnings": ["knee_extension_weak", "takeoff_geometry_weak"],
                },
                "A": {
                    "frame_id": "frame_0025",
                    "timestamp": 6.0,
                    "confidence": 0.526,
                    "warnings": [
                        "confidence_missing_knee_angle_change",
                        "apex_local_minimum_not_clear",
                        "apex_motion_bounded_unclear_fallback",
                    ],
                },
                "L": {"frame_id": "frame_0027", "timestamp": 7.812, "confidence": 0.65},
            },
            "quality_flags": ["bio_key_frames_synced_from_resolved_keyframes"],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.55,
            "quality_flags": [
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_candidate_fallback_rejected_weak_takeoff_apex",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 6.1, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 6.4, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {})
        self.assertNotIn("key_frame_timestamps", synced)
        self.assertNotIn("key_frame_source", synced)
        self.assertIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])

    def test_sync_key_frames_uses_degraded_semantic_when_low_visibility_motion_fallback_cannot_restore(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0002", "A": "frame_0006", "L": "frame_0009"},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                    "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
                    "tal_candidate_incomplete",
                    "tal_candidate_motion_fallback_foreground_motion_risk",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_order_unresolved",
                ],
                "T": {"frame_id": "frame_0002", "timestamp": 0.062, "confidence": 0.477},
                "A": {"frame_id": "frame_0006", "timestamp": 0.438, "confidence": 0.463},
                "L": {"frame_id": "frame_0009", "timestamp": 1.062, "confidence": 0.444},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_anchor_not_first_frame",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.65,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_tracker_final_loss_motion_fallback_ignored",
                "semantic_keyframes_weak_refinement_late_candidate_conflict_ignored_low_visibility_no_pose_support",
                "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
                "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_partial_core_frames_available",
                "video_temporal_quality_retry_rejected",
            ],
            "semantic_tracker_final_loss_motion_fallback": {
                "decision": "ignored_reliable_pose_bounded_motion_fallback",
            },
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 2.953,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.7,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 3.2,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.7,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 3.867,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.7,
                },
            ],
            "video_temporal_quality_retry_rejection_flags": [
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 2.953, "A": 3.2, "L": 3.867})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0002", "A": "frame_0006", "L": "frame_0009"})
        self.assertEqual(synced["key_frame_source"], "blended")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_synced_from_degraded_semantic_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_degraded_semantic_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])

    def test_sync_key_frames_accepts_late_pose_core_candidate_fallback(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_late_pose_core_reselected",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_apex_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {"frame_id": "frame_0023", "timestamp": 4.188, "confidence": 0.34},
                "A": {"frame_id": "frame_0025", "timestamp": 4.812, "confidence": 0.34},
                "L": {"frame_id": "frame_0026", "timestamp": 4.875, "confidence": 0.34},
            },
            "quality_flags": ["target_lock_stable_zoomed_candidate_auto_locked"],
        }
        resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.85,
            "quality_flags": [
                "semantic_keyframes_unreliable_candidate_tal_conflict",
                "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                "video_temporal_quality_retry_rejected",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "selected": [
                {
                    "frame_id": "frame_0023",
                    "timestamp": 4.188,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "fallback_to_keyframe_candidates",
                },
                {
                    "frame_id": "frame_0025",
                    "timestamp": 4.812,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "fallback_to_keyframe_candidates",
                },
                {
                    "frame_id": "frame_0026",
                    "timestamp": 4.875,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "fallback_to_keyframe_candidates",
                },
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "frame_0023", "A": "frame_0025", "L": "frame_0026"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 4.188, "A": 4.812, "L": 4.875})
        self.assertEqual(synced["key_frame_source"], "skeleton_fallback")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_unreliable_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])

    def test_sync_key_frames_keeps_degraded_semantic_on_second_sync_pass(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"},
            "key_frame_timestamps": {"T": 2.953, "A": 3.2, "L": 3.867},
            "raw_biomechanics_key_frames": {"T": "frame_0002", "A": "frame_0006", "L": "frame_0009"},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                    "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
                    "tal_candidate_incomplete",
                    "tal_candidate_motion_fallback_foreground_motion_risk",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_order_unresolved",
                ],
                "T": {"frame_id": "frame_0002", "timestamp": 0.062, "confidence": 0.477},
                "A": {"frame_id": "frame_0006", "timestamp": 0.438, "confidence": 0.463},
                "L": {"frame_id": "frame_0009", "timestamp": 1.062, "confidence": 0.444},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "bio_key_frames_synced_from_degraded_semantic_keyframes",
                "bio_key_frames_degraded_semantic_unreliable_resolved_keyframes",
                "bio_key_frames_not_restored_unreliable_candidates",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.65,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
                "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_quality_retry_rejected",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 2.953,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.7,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 3.2,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.7,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 3.867,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.7,
                },
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 2.953, "A": 3.2, "L": 3.867})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0002", "A": "frame_0006", "L": "frame_0009"})
        self.assertIn("bio_key_frames_synced_from_degraded_semantic_keyframes", synced["quality_flags"])

    def test_sync_key_frames_uses_degraded_semantic_when_weak_temporal_geometry_cannot_restore(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0021", "A": "frame_0023", "L": "frame_0025"},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_confidence_low",
                ],
                "T": {"frame_id": "frame_0021", "timestamp": 5.938, "confidence": 0.34},
                "A": {"frame_id": "frame_0023", "timestamp": 6.062, "confidence": 0.34},
                "L": {"frame_id": "frame_0025", "timestamp": 6.188, "confidence": 0.34},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_rejected",
                "person_tracker_anchor_not_first_frame",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.65,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
                "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "semantic_keyframes_partial_core_frames_available",
                "video_temporal_quality_retry_rejected",
            ],
            "semantic_candidate_tal_conflict": {
                "decision": "ignored_weak_temporal_geometry_candidate",
            },
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 6.0,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.6,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 6.4,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.5,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 6.567,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.6,
                },
            ],
            "video_temporal_quality_retry_rejection_flags": [
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 6.0, "A": 6.4, "L": 6.567})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0021", "A": "frame_0023", "L": "frame_0025"})
        self.assertEqual(synced["key_frame_source"], "blended")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_synced_from_degraded_semantic_keyframes", synced["quality_flags"])
        self.assertIn("bio_key_frames_degraded_semantic_tracker_final_loss_weak_geometry", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_weak_geometry", synced["quality_flags"])
        self.assertIn("bio_key_frames_not_restored_unreliable_candidates", synced["quality_flags"])

    def test_sync_key_frames_uses_semantic_when_absent_landing_geometry_was_accepted(self) -> None:
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {"T": "frame_0009", "A": "frame_0010", "L": "frame_0012"},
            "key_frame_timestamps": {"T": 0.562, "A": 1.125, "L": 2.25},
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_landing_geometry_absent",
                    "tal_candidate_weak_geometry",
                ],
                "T": {"frame_id": "frame_0009", "timestamp": 0.562, "confidence": 0.60},
                "A": {"frame_id": "frame_0010", "timestamp": 1.125, "confidence": 0.486},
                "L": {"frame_id": "frame_0012", "timestamp": 2.25, "confidence": 0.35},
            },
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_relock_pending",
                "person_tracker_final_unrecovered",
            ],
        }
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_quality_retry_used",
                "semantic_keyframes_candidate_tal_conflict_ignored_weak_geometry",
                "semantic_keyframes_tracker_final_loss_weak_semantic_motion_ignored",
            ],
            "semantic_candidate_tal_conflict": {
                "decision": "ignored_absent_landing_geometry_candidate",
            },
            "semantic_tracker_final_loss_weak_semantic_motion": {
                "decision": "ignored_retry_absent_landing_geometry_candidate",
            },
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 3.187, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 3.8, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 4.667, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }

        synced = sync_key_frames_from_resolved_keyframes(bio_data, resolved, analysis_profile="jump")

        self.assertEqual(synced["key_frames"], {"T": "semantic_0001", "A": "semantic_0002", "L": "semantic_0003"})
        self.assertEqual(synced["key_frame_timestamps"], {"T": 3.187, "A": 3.8, "L": 4.667})
        self.assertEqual(synced["raw_biomechanics_key_frames"], {"T": "frame_0009", "A": "frame_0010", "L": "frame_0012"})
        self.assertEqual(synced["key_frame_source"], "blended")
        self.assertIn("bio_key_frames_synced_from_resolved_keyframes", synced["quality_flags"])
        self.assertNotIn("bio_key_frames_not_synced_tracker_final_loss_weak_geometry", synced["quality_flags"])

    def test_arm_symmetry_is_stable_across_capture_scales(self) -> None:
        full_body = calc_arm_symmetry(_scaled_keypoints(1.0), 1)
        half_body = calc_arm_symmetry(_scaled_keypoints(0.5), 1)

        self.assertIsNotNone(full_body["symmetry"])
        self.assertIsNotNone(half_body["symmetry"])
        difference = abs(float(full_body["symmetry"]) - float(half_body["symmetry"]))
        baseline = max(float(full_body["symmetry"]), 1e-6)
        self.assertLess(difference / baseline, 0.05)

    def test_com_vertical_range_is_stable_across_capture_scales(self) -> None:
        full_body = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": _scaled_keypoints(1.0, 0.00)},
                {"frame": "frame_0002.jpg", "keypoints": _scaled_keypoints(1.0, -0.08)},
            ]
        }
        half_body = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": _scaled_keypoints(0.5, 0.00)},
                {"frame": "frame_0002.jpg", "keypoints": _scaled_keypoints(0.5, -0.08)},
            ]
        }

        full_range = calc_center_of_mass_trajectory(full_body)["vertical_range"]
        half_range = calc_center_of_mass_trajectory(half_body)["vertical_range"]

        self.assertGreater(full_range, 0.0)
        difference = abs(float(full_range) - float(half_range))
        baseline = max(float(full_range), 1e-6)
        self.assertLess(difference / baseline, 0.05)

    def test_spin_profile_uses_spin_key_frame_labels(self) -> None:
        pose_data = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": _spin_keypoints(0.45, 0.55)},
                {"frame": "frame_0002.jpg", "keypoints": _spin_keypoints(0.46, 0.56)},
                {"frame": "frame_0003.jpg", "keypoints": _spin_keypoints(0.62, 0.72)},
                {"frame": "frame_0004.jpg", "keypoints": _spin_keypoints(0.63, 0.73)},
            ]
        }

        result = analyze_biomechanics(pose_data, action_type="spin", analysis_profile="spin")

        self.assertEqual(
            result["key_frames"],
            {"旋转入": "frame_0002", "旋转中": "frame_0003", "旋转出": "frame_0004"},
        )
        self.assertNotIn("T", result["key_frames"])
        self.assertNotIn("A", result["key_frames"])
        self.assertNotIn("L", result["key_frames"])

    def test_non_jump_bio_subscores_are_derived_from_discipline_metrics(self) -> None:
        pose_data = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": _spin_keypoints(0.45, 0.55, ankle_y=0.70, y_shift=0.00)},
                {"frame": "frame_0002.jpg", "keypoints": _spin_keypoints(0.46, 0.56, ankle_y=0.62, y_shift=-0.04)},
                {"frame": "frame_0003.jpg", "keypoints": _spin_keypoints(0.62, 0.72, ankle_y=0.66, y_shift=0.03)},
                {"frame": "frame_0004.jpg", "keypoints": _spin_keypoints(0.63, 0.73, ankle_y=0.75, y_shift=0.01)},
            ]
        }

        result = analyze_biomechanics(pose_data, action_type="spiral", analysis_profile="spiral")

        self.assertTrue(result["discipline_metrics"])
        self.assertNotEqual(result["bio_subscores"]["rotation_axis"], 65)
        self.assertNotEqual(result["bio_subscores"]["landing_absorption"], 65)


if __name__ == "__main__":
    unittest.main()
