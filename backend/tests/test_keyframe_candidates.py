from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import keyframe_candidates as keyframe_candidates_module
from app.services.keyframe_candidates import (
    detect_key_frame_candidates,
    _tiny_target_weak_geometry_flags,
    _temporal_geometry_unreliable_flags,
    _weak_geometry_flags,
)


def _keypoints(
    *,
    com_y: float,
    knee_angle: str = "bent",
    ankle_y: float | None = None,
    visibility: float = 0.95,
) -> list[dict[str, float | int]]:
    keypoints: list[dict[str, float | int]] = [
        {"id": index, "x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}
        for index in range(33)
    ]
    shoulder_y = com_y - 0.16
    hip_y = com_y + 0.16
    left_hip = (0.44, hip_y)
    right_hip = (0.56, hip_y)

    if knee_angle == "straight":
        knee_offset_x = 0.0
        lower_dx = 0.0
        lower_dy = 0.18
    elif knee_angle == "soft":
        knee_offset_x = 0.02
        lower_dx = 0.06
        lower_dy = 0.16
    else:
        knee_offset_x = 0.03
        lower_dx = 0.13
        lower_dy = 0.10

    left_knee = (left_hip[0] + knee_offset_x, hip_y + 0.18)
    right_knee = (right_hip[0] - knee_offset_x, hip_y + 0.18)
    left_ankle = (left_knee[0] + lower_dx, left_knee[1] + lower_dy)
    right_ankle = (right_knee[0] - lower_dx, right_knee[1] + lower_dy)

    if ankle_y is not None:
        left_ankle = (left_ankle[0], ankle_y)
        right_ankle = (right_ankle[0], ankle_y)

    visible = {
        11: (0.42, shoulder_y),
        12: (0.58, shoulder_y),
        23: left_hip,
        24: right_hip,
        25: left_knee,
        26: right_knee,
        27: left_ankle,
        28: right_ankle,
    }
    for index, (x_value, y_value) in visible.items():
        keypoints[index] = {
            "id": index,
            "x": x_value,
            "y": y_value,
            "z": 0.0,
            "visibility": visibility,
        }
    return keypoints


def _pose(
    com_values: list[float],
    knee_states: list[str],
    ankle_values: list[float | None],
    *,
    visibility: float = 0.95,
    tracking_states: list[str] | None = None,
    tracker_states: list[str | None] | None = None,
    target_bboxes: list[dict[str, float] | None] | None = None,
    quality_flags: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "frames": [
            {
                "frame": f"frame_{index + 1:04d}.jpg",
                "tracking_state": tracking_states[index] if tracking_states else "tracked",
                **({"tracker_state": tracker_states[index]} if tracker_states and tracker_states[index] else {}),
                **({"target_bbox": target_bboxes[index]} if target_bboxes and target_bboxes[index] else {}),
                "keypoints": _keypoints(
                    com_y=com_values[index],
                    knee_angle=knee_states[index],
                    ankle_y=ankle_values[index],
                    visibility=visibility,
                ),
            }
            for index in range(len(com_values))
        ]
    }
    if quality_flags:
        payload["quality_flags"] = quality_flags
    return payload


def _motion(scores: list[float]) -> dict[str, object]:
    return {
        "scores": scores,
        "selected": [
            {
                "frame_id": f"frame_{index + 1:04d}",
                "timestamp": round(index / 10.0, 3),
                "motion_score": score,
            }
            for index, score in enumerate(scores)
        ],
    }


class KeyframeCandidateTests(unittest.TestCase):
    def test_detects_ordered_jump_candidates_with_evidence(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.60, 0.56, 0.49, 0.43, 0.38, 0.42, 0.50, 0.58],
            knee_states=["bent", "bent", "soft", "straight", "straight", "straight", "straight", "soft", "bent"],
            ankle_values=[None, None, None, None, None, None, None, None, None],
        )
        motion_scores = _motion([0.05, 0.12, 0.35, 0.95, 0.45, 0.25, 0.35, 0.9, 0.25])

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertEqual(result["quality_flags"], [])
        self.assertEqual(result["T"]["frame_id"], "frame_0004")
        self.assertEqual(result["A"]["frame_id"], "frame_0006")
        self.assertEqual(result["L"]["frame_id"], "frame_0007")
        self.assertLess(result["T"]["timestamp"], result["A"]["timestamp"])
        self.assertLess(result["A"]["timestamp"], result["L"]["timestamp"])
        self.assertGreaterEqual(result["T"]["confidence"], 0.6)
        self.assertGreaterEqual(result["A"]["confidence"], 0.6)
        self.assertGreaterEqual(result["L"]["confidence"], 0.6)
        self.assertIn("knee_extension_deg", result["T"]["evidence"])
        self.assertIn("local_minimum", result["A"]["evidence"])
        self.assertIn("ankle_return_delta", result["L"]["evidence"])

    def test_landing_prefers_first_contact_over_late_glide_motion_peak(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.60, 0.56, 0.49, 0.43, 0.38, 0.42, 0.50, 0.58, 0.59, 0.60],
            knee_states=["bent", "bent", "soft", "straight", "straight", "straight", "straight", "soft", "bent", "soft", "soft"],
            ankle_values=[None, None, None, None, None, None, None, None, None, None, None],
        )
        motion_scores = _motion([0.05, 0.12, 0.35, 0.95, 0.45, 0.25, 0.35, 1.0, 0.25])

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertEqual(result["L"]["frame_id"], "frame_0007")
        self.assertGreaterEqual(result["L"]["evidence"]["score_components"]["landing_contact"], 0.8)

    def test_motion_cluster_window_prevents_apex_and_landing_from_drifting_to_late_glide(self) -> None:
        pose_data = _pose(
            com_values=[
                0.62,
                0.58,
                0.50,
                0.43,
                0.38,
                0.42,
                0.50,
                0.58,
                0.54,
                0.49,
                0.44,
                0.35,
            ],
            knee_states=[
                "bent",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "bent",
                "soft",
                "soft",
                "straight",
                "straight",
            ],
            ankle_values=[None, None, None, None, None, None, None, None, None, None, None, None],
        )
        motion_scores = _motion([0.05, 0.18, 0.55, 0.95, 0.45, 0.30, 0.35, 0.25, 0.02, 0.02, 0.02, 0.02])

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertIn("motion_cluster_window", result["A"]["evidence"])
        self.assertEqual(result["A"]["frame_id"], "frame_0005")
        self.assertLess(result["A"]["timestamp"], 1.0)
        self.assertLess(result["L"]["timestamp"], 1.0)
        self.assertNotEqual(result["A"]["frame_id"], "frame_0012")
        self.assertNotEqual(result["L"]["frame_id"], "frame_0012")

    def test_motion_cluster_window_prefers_strong_later_core_over_early_multiperson_motion(self) -> None:
        com_values = [
            0.50,
            0.49,
            0.47,
            0.45,
            0.43,
            0.44,
            0.42,
            0.46,
            0.48,
            0.49,
            0.50,
            0.50,
            0.50,
            0.50,
            0.50,
            0.50,
            0.50,
            0.48,
            0.46,
            0.44,
            0.42,
            0.41,
            0.405,
            0.415,
            0.43,
            0.45,
            0.47,
            0.48,
        ]
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "bent",
                "soft",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "bent",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "bent",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "bent",
                "bent",
                "soft",
            ],
            ankle_values=[None for _ in com_values],
            tracker_states=[
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "continuity_rejected",
                "continuity_rejected",
            ],
        )
        timestamps = [
            0.0,
            0.375,
            0.625,
            0.75,
            0.875,
            1.125,
            1.5,
            1.875,
            2.25,
            2.312,
            2.375,
            2.438,
            2.5,
            2.625,
            3.062,
            3.625,
            4.125,
            5.75,
            5.812,
            5.875,
            5.938,
            6.0,
            6.062,
            6.125,
            6.188,
            6.25,
            7.625,
            7.688,
        ]
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(
                    zip(
                        timestamps,
                        [
                            0.0,
                            0.0262,
                            0.0434,
                            0.0268,
                            0.0359,
                            0.0307,
                            0.0159,
                            0.0333,
                            0.0335,
                            0.0405,
                            0.0425,
                            0.0397,
                            0.0261,
                            0.0339,
                            0.0280,
                            0.0174,
                            0.0130,
                            0.0449,
                            0.0429,
                            0.0465,
                            0.0454,
                            0.0302,
                            0.0431,
                            0.0441,
                            0.0421,
                            0.0387,
                            0.0287,
                            0.0250,
                        ],
                    )
                )
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 2.619)

        self.assertIn("keyframe_candidates_excluded_unreliable_pose_frames", result["quality_flags"])
        self.assertIn("tal_candidate_temporal_geometry_unreliable", result["quality_flags"])
        window = result["T"]["evidence"]["motion_cluster_window"]
        self.assertGreaterEqual(window["start_timestamp"], 5.7)
        self.assertLessEqual(window["end_timestamp"], 6.3)
        self.assertGreaterEqual(result["T"]["timestamp"], 5.75)
        self.assertGreaterEqual(result["A"]["timestamp"], 5.75)
        self.assertGreaterEqual(result["L"]["timestamp"], 5.75)
        self.assertNotEqual(result["T"]["frame_id"], "frame_0005")
        self.assertNotIn("keyframe_candidates_sparse_takeoff_prepeak_estimated", result["quality_flags"])
        self.assertNotIn("takeoff_sparse_prepeak_estimated", result["T"]["warnings"])

    def test_unclear_apex_takeoff_requires_joint_ascent_not_early_motion_spike(self) -> None:
        pose_data = _pose(
            com_values=[
                0.5141,
                0.5449,
                0.5229,
                0.5081,
                0.4933,
                0.4918,
                0.4941,
                0.4984,
                0.4983,
                0.4985,
                0.5066,
                0.5068,
                0.5026,
                0.4928,
                0.4833,
                0.4770,
            ],
            knee_states=[
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "bent",
                "straight",
                "bent",
                "bent",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
            ],
            ankle_values=[
                0.6282,
                0.6235,
                0.6175,
                0.5944,
                0.5761,
                0.5913,
                0.5972,
                0.5956,
                0.5924,
                0.6011,
                0.6008,
                0.5988,
                0.5884,
                0.5793,
                0.5694,
                0.5604,
            ],
            visibility=0.82,
        )
        timestamps = [
            0.125,
            0.312,
            0.438,
            0.625,
            0.688,
            0.875,
            1.062,
            1.25,
            1.312,
            1.5,
            1.75,
            1.812,
            1.875,
            1.938,
            2.0,
            2.062,
        ]
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(
                    zip(
                        timestamps,
                        [
                            0.1736,
                            0.3185,
                            0.0530,
                            0.0566,
                            0.0607,
                            0.0610,
                            0.0419,
                            0.0495,
                            0.0574,
                            0.0441,
                            0.0246,
                            0.0364,
                            0.0573,
                            0.0817,
                            0.0692,
                            0.0149,
                        ],
                    )
                )
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 4.557)

        self.assertNotEqual(result["T"]["timestamp"], 0.312)
        self.assertGreater(result["T"]["timestamp"], 0.875)
        self.assertLess(result["T"]["confidence"], 0.40)
        self.assertIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_low_visibility_weak_boundary", result["quality_flags"])

    def test_unclear_monotonic_com_apex_stays_near_main_motion_peak(self) -> None:
        com_values = [
            0.4227,
            0.4287,
            0.4343,
            0.4369,
            0.4377,
            0.4432,
            0.4961,
            0.5514,
            0.5755,
            0.5913,
            0.5996,
            0.5991,
            0.5924,
            0.5863,
            0.5714,
            0.5536,
            0.5369,
            0.5175,
            0.4822,
            0.4705,
            0.4617,
            0.4584,
            0.4352,
            0.4252,
            0.3910,
            0.4049,
            0.4191,
            0.4255,
        ]
        knee_states = [
            "straight",
            "straight",
            "straight",
            "straight",
            "straight",
            "soft",
            "soft",
            "soft",
            "bent",
            "bent",
            "bent",
            "bent",
            "soft",
            "soft",
            "soft",
            "soft",
            "straight",
            "straight",
            "straight",
            "straight",
            "soft",
            "soft",
            "soft",
            "soft",
            "soft",
            "soft",
            "straight",
            "straight",
        ]
        ankle_values = [
            0.5997,
            0.6075,
            0.6108,
            0.6145,
            0.6127,
            0.6093,
            0.6312,
            0.6782,
            0.7246,
            0.7523,
            0.7852,
            0.8118,
            0.8324,
            0.8370,
            0.8260,
            0.8066,
            0.7844,
            0.7661,
            0.6641,
            0.6046,
            0.5984,
            0.6021,
            0.5859,
            0.5750,
            0.5244,
            0.5390,
            0.5494,
            0.5708,
        ]
        pose_data = _pose(com_values=com_values, knee_states=knee_states, ankle_values=ankle_values)
        timestamps = [
            0.0,
            0.188,
            0.25,
            0.312,
            0.625,
            0.938,
            1.25,
            1.562,
            1.688,
            1.75,
            1.812,
            1.875,
            1.938,
            2.0,
            2.062,
            2.125,
            2.188,
            2.25,
            2.438,
            2.75,
            2.875,
            2.938,
            3.812,
            3.875,
            6.812,
            6.875,
            8.438,
            9.0,
        ]
        motion_values = [
            0.0,
            0.0333,
            0.0283,
            0.0246,
            0.0181,
            0.0158,
            0.0372,
            0.0966,
            0.0973,
            0.1027,
            0.1209,
            0.1275,
            0.1560,
            0.1112,
            0.1643,
            0.1318,
            0.1156,
            0.1007,
            0.0728,
            0.0474,
            0.0372,
            0.0383,
            0.0202,
            0.0182,
            0.0275,
            0.0275,
            0.0150,
            0.0126,
        ]
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 3.241)

        self.assertNotIn("tal_candidate_skeleton_drifted_after_takeoff", result["quality_flags"])
        self.assertNotIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertIn(result["A"]["frame_id"], {"frame_0016", "frame_0017"})
        self.assertLessEqual(result["A"]["timestamp"], 2.25)
        self.assertLessEqual(result["L"]["timestamp"], 2.45)
        self.assertNotEqual(result["L"]["frame_id"], "frame_0022")
        self.assertIn("apex_motion_bounded_unclear_fallback", result["A"]["warnings"])
        self.assertTrue(result["A"]["evidence"]["motion_bounded_unclear_apex"])

    def test_unclear_apex_after_takeoff_uses_motion_fallback_instead_of_late_com_minimum(self) -> None:
        com_values = [
            0.512,
            0.547,
            0.573,
            0.594,
            0.604,
            0.604,
            0.577,
            0.555,
            0.535,
            0.516,
            0.497,
            0.481,
            0.464,
            0.447,
            0.429,
            0.413,
            0.392,
            0.374,
            0.364,
            0.352,
            0.347,
            0.349,
            0.345,
            0.350,
            0.351,
            0.353,
            0.353,
            0.351,
            0.350,
            0.331,
            0.316,
            0.292,
        ]
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "bent",
                "bent",
                "bent",
                "bent",
                "soft",
                "soft",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "soft",
                "bent",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
            ],
            ankle_values=[None for _ in com_values],
        )
        motion_scores = _motion(
            [
                0.0,
                0.1193,
                0.1481,
                0.144,
                0.1253,
                0.0743,
                0.1278,
                0.1384,
                0.1384,
                0.1284,
                0.1142,
                0.0661,
                0.1051,
                0.0963,
                0.0763,
                0.0589,
                0.042,
                0.0614,
                0.0491,
                0.0427,
                0.0386,
                0.0427,
                0.0385,
                0.0359,
                0.0371,
                0.0287,
                0.0247,
                0.0232,
                0.0229,
                0.0223,
                0.0173,
                0.0176,
            ]
        )

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 5.0)

        self.assertIn("tal_candidate_skeleton_drifted_after_takeoff", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertEqual(result["T"]["frame_id"], "frame_0009")
        self.assertLessEqual(result["A"]["timestamp"] - result["T"]["timestamp"], 0.55)
        self.assertLessEqual(result["L"]["timestamp"] - result["T"]["timestamp"], 1.35)
        self.assertNotEqual(result["A"]["frame_id"], "frame_0031")
        self.assertNotEqual(result["L"]["frame_id"], "frame_0032")

    def test_takeoff_anchor_motion_fallback_marks_unreliable_pose_state_records(self) -> None:
        com_values = [
            0.512,
            0.547,
            0.573,
            0.594,
            0.604,
            0.604,
            0.577,
            0.555,
            0.535,
            0.516,
            0.497,
            0.481,
            0.464,
            0.447,
            0.429,
            0.413,
            0.392,
            0.374,
            0.364,
            0.352,
            0.347,
            0.349,
            0.345,
            0.350,
            0.351,
            0.353,
            0.353,
            0.351,
            0.350,
            0.331,
            0.316,
            0.292,
        ]
        tracking_states = ["tracked"] * len(com_values)
        tracking_states[10] = "interpolated"
        tracking_states[13] = "lost"
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "bent",
                "bent",
                "bent",
                "bent",
                "soft",
                "soft",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "soft",
                "bent",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
            ],
            ankle_values=[None for _ in com_values],
            tracking_states=tracking_states,
        )
        motion_scores = _motion(
            [
                0.0,
                0.1193,
                0.1481,
                0.144,
                0.1253,
                0.0743,
                0.1278,
                0.1384,
                0.1384,
                0.1284,
                0.1142,
                0.0661,
                0.1051,
                0.0963,
                0.0763,
                0.0589,
                0.042,
                0.0614,
                0.0491,
                0.0427,
                0.0386,
                0.0427,
                0.0385,
                0.0359,
                0.0371,
                0.0287,
                0.0247,
                0.0232,
                0.0229,
                0.0223,
                0.0173,
                0.0176,
            ]
        )

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 5.0)

        self.assertIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_unreliable_pose_low_confidence", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["A"]["warnings"])
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["L"]["warnings"])
        self.assertEqual(result["A"]["confidence"], 0.34)
        self.assertEqual(result["L"]["confidence"], 0.34)
        self.assertGreater(result["A"]["evidence"]["motion_fallback_unreliable_pose_confidence_cap"]["raw_confidence"], 0.34)
        self.assertGreater(result["L"]["evidence"]["motion_fallback_unreliable_pose_confidence_cap"]["raw_confidence"], 0.34)
        self.assertEqual(
            result["motion_fallback_unreliable_pose_records"],
            {
                "A": {"frame_id": "frame_0011", "tracking_state": "interpolated", "tracker_state": ""},
                "L": {"frame_id": "frame_0014", "tracking_state": "lost", "tracker_state": ""},
            },
        )
        self.assertEqual(result["A"]["evidence"]["motion_fallback_unreliable_pose_state"]["tracking_state"], "interpolated")
        self.assertEqual(result["L"]["evidence"]["motion_fallback_unreliable_pose_state"]["tracking_state"], "lost")

    def test_takeoff_anchor_low_visibility_motion_fallback_caps_weak_boundary_candidates(self) -> None:
        takeoff = {
            "frame_id": "frame_0010",
            "timestamp": 0.625,
            "confidence": 0.568,
            "evidence": {
                "motion_score": 0.0423,
                "visibility_score": 0.99,
                "score_components": {
                    "motion_peak": 1.0,
                    "takeoff_event": 0.269,
                    "takeoff_timing": 0.0,
                },
            },
            "warnings": ["knee_extension_weak", "takeoff_timing_window_weak"],
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0008", "timestamp": 0.500, "motion_score": 0.0200},
                {"frame_id": "frame_0010", "timestamp": 0.625, "motion_score": 0.0423},
                {"frame_id": "frame_0014", "timestamp": 0.875, "motion_score": 0.0346},
                {"frame_id": "frame_0017", "timestamp": 1.625, "motion_score": 0.0334},
                {"frame_id": "frame_0020", "timestamp": 1.875, "motion_score": 0.0180},
            ]
        }

        result = keyframe_candidates_module._motion_fallback_from_takeoff_anchor(
            motion_scores,
            16.0,
            takeoff,
            ["tal_candidate_skeleton_drifted_after_takeoff"],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("keyframe_candidates_motion_fallback_low_visibility_weak_boundary", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_low_visibility_weak_boundary", result["quality_flags"])
        self.assertIn("tal_candidate_confidence_low", result["quality_flags"])
        self.assertEqual(result["A"]["confidence"], 0.34)
        self.assertEqual(result["L"]["confidence"], 0.34)
        self.assertGreater(
            result["A"]["evidence"]["tal_candidate_motion_fallback_low_visibility_weak_boundary_confidence_cap"]["raw_confidence"],
            0.34,
        )
        self.assertEqual(
            result["motion_fallback_low_visibility_weak_boundary"]["reason"],
            "takeoff_anchor_low_visibility_motion_only_boundary",
        )
        self.assertEqual(
            result["motion_fallback_low_visibility_weak_boundary"]["low_visibility_motion_roles"],
            ["A", "L"],
        )
        self.assertIn("tal_candidate_motion_fallback_low_visibility_weak_boundary", result["A"]["warnings"])
        self.assertIn("motion_fallback_low_visibility_weak_boundary", result["L"]["evidence"])

    def test_tail_motion_window_with_weak_geometry_rechecks_full_pose_sequence(self) -> None:
        com_values = [
            0.503,
            0.507,
            0.513,
            0.515,
            0.513,
            0.509,
            0.507,
            0.502,
            0.496,
            0.490,
            0.479,
            0.469,
            0.465,
            0.464,
            0.464,
            0.458,
            0.454,
            0.455,
            0.459,
            0.466,
            0.467,
            0.469,
            0.465,
            0.471,
            0.477,
            0.477,
            0.477,
            0.479,
            0.474,
            0.456,
            0.442,
        ]
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "bent",
                "bent",
                "bent",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "bent",
                "bent",
                "straight",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "bent",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
            ],
            ankle_values=[None for _ in com_values],
        )
        timestamps = [
            0.0,
            0.062,
            0.125,
            0.188,
            0.25,
            0.312,
            0.375,
            0.438,
            0.625,
            0.812,
            1.062,
            1.25,
            1.312,
            1.375,
            1.438,
            1.688,
            1.875,
            2.188,
            2.25,
            2.812,
            2.875,
            3.25,
            3.625,
            4.5,
            4.562,
            4.625,
            5.188,
            5.25,
            6.375,
            6.438,
            6.5,
        ]
        motion_values = [
            0.0,
            0.0509,
            0.0577,
            0.0414,
            0.0563,
            0.0451,
            0.0427,
            0.0415,
            0.0304,
            0.0266,
            0.021,
            0.0324,
            0.0351,
            0.0371,
            0.0355,
            0.0239,
            0.0267,
            0.0313,
            0.0299,
            0.0233,
            0.0229,
            0.019,
            0.0147,
            0.0152,
            0.0225,
            0.0162,
            0.0176,
            0.0151,
            0.0178,
            0.0815,
            0.0609,
        ]
        motion_scores = {
            "selected": [
                {
                    "frame_id": f"frame_{index + 1:04d}",
                    "timestamp": timestamp,
                    "motion_score": score,
                }
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 4.72)

        self.assertIn("keyframe_candidates_tail_motion_window_rejected", result["quality_flags"])
        self.assertNotIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertLess(result["T"]["timestamp"], 3.0)
        self.assertLess(result["A"]["timestamp"], 3.0)
        self.assertLess(result["L"]["timestamp"], 3.0)
        self.assertAlmostEqual(result["T"]["timestamp"], 1.312, places=3)
        self.assertAlmostEqual(result["A"]["timestamp"], 1.875, places=3)
        self.assertAlmostEqual(result["L"]["timestamp"], 2.25, places=3)
        self.assertIn("takeoff_reselected_from_late_plausible_candidate", result["T"]["warnings"])
        self.assertEqual(
            result["T"]["evidence"]["takeoff_late_plausible_reselection"]["original_timestamp"],
            1.062,
        )
        self.assertNotEqual(result["A"]["frame_id"], "frame_0030")
        self.assertNotEqual(result["L"]["frame_id"], "frame_0031")

    def test_tail_motion_window_with_secondary_cluster_reselects_before_full_sequence_stitch(self) -> None:
        com_values = [
            0.502,
            0.503,
            0.504,
            0.501,
            0.496,
            0.498,
            0.497,
            0.491,
            0.491,
            0.499,
            0.527,
            0.539,
            0.541,
            0.543,
            0.545,
            0.540,
            0.538,
            0.528,
            0.527,
            0.504,
            0.506,
            0.518,
            0.517,
            0.515,
            0.506,
        ]
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "straight",
                "soft",
                "soft",
                "bent",
                "soft",
                "bent",
                "soft",
                "straight",
                "soft",
                "straight",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "bent",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
            ],
            ankle_values=[
                0.623,
                0.629,
                0.629,
                0.626,
                0.624,
                0.623,
                0.621,
                0.617,
                0.616,
                0.619,
                0.635,
                0.640,
                0.641,
                0.641,
                0.641,
                0.636,
                0.632,
                0.598,
                0.588,
                0.579,
                0.587,
                0.605,
                0.602,
                0.598,
                0.589,
            ],
        )
        timestamps = [
            0.0,
            0.125,
            0.188,
            0.312,
            0.625,
            0.938,
            1.125,
            1.25,
            1.312,
            2.5,
            3.562,
            3.625,
            3.688,
            3.75,
            3.812,
            3.938,
            4.0,
            4.875,
            5.0,
            6.188,
            7.375,
            9.438,
            9.625,
            9.688,
            9.75,
        ]
        motion_values = [
            0.0,
            0.0214,
            0.0193,
            0.0179,
            0.0159,
            0.0264,
            0.0198,
            0.0190,
            0.0171,
            0.0220,
            0.0525,
            0.0517,
            0.0527,
            0.0546,
            0.0494,
            0.0364,
            0.0224,
            0.0168,
            0.0201,
            0.0214,
            0.0167,
            0.0627,
            0.0533,
            0.0434,
            0.0888,
        ]
        motion_scores = {
            "selected": [
                {
                    "frame_id": f"frame_{index + 1:04d}",
                    "timestamp": timestamp,
                    "motion_score": score,
                }
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 16.0)

        self.assertIn("keyframe_candidates_tail_motion_window_rejected", result["quality_flags"])
        self.assertIn("keyframe_candidates_tail_motion_window_reselected", result["quality_flags"])
        self.assertLess(result["T"]["timestamp"], 6.5)
        self.assertLess(result["A"]["timestamp"], 6.5)
        self.assertLess(result["L"]["timestamp"], 6.5)
        self.assertNotEqual(result["L"]["frame_id"], "frame_0025")
        self.assertNotIn("tal_candidate_sparse_track_stitched", result["quality_flags"])

    def test_compressed_tail_window_reselects_before_tail_motion_fallback(self) -> None:
        com_values = [
            0.62,
            0.60,
            0.58,
            0.56,
            0.54,
            0.52,
            0.50,
            0.48,
            0.47,
            0.46,
            0.455,
            0.450,
            0.445,
            0.440,
            0.420,
            0.390,
            0.370,
            0.360,
            0.365,
            0.380,
            0.405,
            0.530,
            0.525,
            0.535,
            0.540,
        ]
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "bent",
                "bent",
                "soft",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
            ],
            ankle_values=[
                0.72,
                0.71,
                0.70,
                0.69,
                0.68,
                0.67,
                0.66,
                0.65,
                0.64,
                0.63,
                0.62,
                0.61,
                0.60,
                0.59,
                0.58,
                0.57,
                0.56,
                0.55,
                0.55,
                0.56,
                0.58,
                0.62,
                0.63,
                0.69,
                0.70,
            ],
            tracker_states=[
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "lost_reused",
                "lost_reused",
                "lost_reused",
                "lost_reused",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ],
        )
        timestamps = [
            0.0,
            0.25,
            0.5,
            0.75,
            1.0,
            1.25,
            1.5,
            1.75,
            2.0,
            2.25,
            3.75,
            4.25,
            4.5,
            4.625,
            7.062,
            7.125,
            7.188,
            7.25,
            7.312,
            8.0,
            8.062,
            14.75,
            14.812,
            14.875,
            14.938,
        ]
        motion_values = [
            0.01,
            0.012,
            0.014,
            0.016,
            0.018,
            0.020,
            0.018,
            0.016,
            0.014,
            0.012,
            0.0307,
            0.0377,
            0.0334,
            0.0324,
            0.0446,
            0.0487,
            0.0592,
            0.0555,
            0.0504,
            0.0375,
            0.0401,
            0.0791,
            0.0666,
            0.0793,
            0.0746,
        ]
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 2.066)

        self.assertIn("keyframe_candidates_tail_motion_window_rejected", result["quality_flags"])
        self.assertIn("keyframe_candidates_tail_motion_window_reselected", result["quality_flags"])
        self.assertLess(result["T"]["timestamp"], 9.0)
        self.assertLess(result["A"]["timestamp"], 9.0)
        self.assertLess(result["L"]["timestamp"], 9.0)
        self.assertNotIn(result["T"]["timestamp"], {14.75, 14.812, 14.875, 14.938})
        self.assertNotIn(result["A"]["timestamp"], {14.75, 14.812, 14.875, 14.938})
        self.assertNotIn(result["L"]["timestamp"], {14.75, 14.812, 14.875, 14.938})

    def test_compressed_weak_motion_window_reselects_stronger_early_jump_window(self) -> None:
        com_values = [
            0.3520,
            0.3714,
            0.3767,
            0.4468,
            0.4683,
            0.4783,
            0.4825,
            0.4860,
            0.4850,
            0.4540,
            0.4575,
            0.4500,
            0.4439,
            0.4388,
            0.4310,
            0.4244,
            0.4242,
            0.4226,
            0.4398,
            0.4463,
            0.4442,
            0.4500,
            0.4500,
            0.4492,
            0.4468,
            0.4460,
            0.4467,
            0.4516,
            0.4500,
            0.4514,
            0.4646,
            0.4513,
        ]
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "straight",
                "straight",
                "straight",
                "bent",
                "bent",
                "bent",
                "bent",
                "bent",
                "bent",
                "soft",
                "soft",
                "soft",
                "bent",
                "straight",
                "straight",
                "soft",
                "soft",
                "soft",
                "soft",
                "straight",
                "soft",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "soft",
                "straight",
                "straight",
            ],
            ankle_values=[
                0.5394,
                0.5536,
                0.4958,
                0.6452,
                0.6796,
                0.6957,
                0.7021,
                0.7057,
                0.6936,
                0.6090,
                None,
                None,
                0.5203,
                0.5138,
                0.5058,
                0.4984,
                0.5000,
                0.5039,
                0.5212,
                0.5288,
                0.5325,
                None,
                None,
                0.5468,
                0.5494,
                0.5480,
                0.5488,
                0.5535,
                None,
                0.5622,
                0.5979,
                0.5903,
            ],
            tracking_states=[
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "interpolated",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "interpolated",
                "interpolated",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "interpolated",
                "tracked",
                "tracked",
                "tracked",
            ],
            tracker_states=[
                "full_frame_yolo_relock_pending",
                "detector_relocked",
                "local_zoom_yolo_relock_pending",
                "tracked",
                "tracked",
                "tracked",
                "relocked",
                "relock_pending",
                "relock_pending",
                "relock_rejected",
                "lost_reused",
                "local_zoom_yolo_relock_pending",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "detector_relocked",
                "local_zoom_yolo_relock_pending",
                "tracked",
                "tracked",
                "full_frame_yolo_relock_pending",
                "local_zoom_yolo_relock_pending",
                "relock_rejected",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
            ],
        )
        timestamps = [
            0.0,
            0.312,
            0.688,
            0.875,
            1.0,
            1.062,
            1.125,
            1.188,
            1.25,
            1.312,
            1.375,
            1.438,
            1.5,
            1.688,
            2.062,
            2.188,
            2.312,
            2.375,
            3.688,
            4.875,
            5.125,
            6.188,
            6.25,
            6.5,
            6.562,
            6.625,
            6.688,
            6.75,
            7.5,
            8.812,
            10.438,
            10.5,
        ]
        motion_values = [
            0.0,
            0.0375,
            0.0477,
            0.1047,
            0.0714,
            0.1234,
            0.1146,
            0.1145,
            0.107,
            0.2057,
            0.242,
            0.2662,
            0.1294,
            0.044,
            0.0437,
            0.0533,
            0.0602,
            0.0611,
            0.0424,
            0.0596,
            0.0623,
            0.1084,
            0.124,
            0.0813,
            0.1357,
            0.1238,
            0.0942,
            0.0684,
            0.0308,
            0.0385,
            0.0937,
            0.1123,
        ]
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 2.933)

        self.assertIn("keyframe_candidates_compressed_weak_motion_window_reselected", result["quality_flags"])
        self.assertLess(result["T"]["timestamp"], 2.0)
        self.assertLess(result["A"]["timestamp"], 2.4)
        self.assertLess(result["L"]["timestamp"], 2.6)
        self.assertNotEqual(result["T"]["frame_id"], "frame_0024")
        self.assertNotEqual(result["A"]["frame_id"], "frame_0026")
        self.assertNotEqual(result["L"]["frame_id"], "frame_0028")
        self.assertIn("landing_weak_contact_early_candidate_selected", result["L"]["warnings"])

    def test_motion_supported_low_prominence_apex_prevents_late_com_drift(self) -> None:
        pose_data = _pose(
            com_values=[
                0.47411,
                0.49958,
                0.51395,
                0.51723,
                0.52015,
                0.52183,
                0.51202,
                0.49605,
                0.45585,
                0.42063,
                0.40316,
                0.40032,
                0.40366,
                0.40414,
                0.40428,
                0.40251,
                0.40154,
                0.39662,
                0.39381,
                0.39582,
                0.39554,
                0.39057,
                0.37171,
            ],
            knee_states=[
                "soft",
                "straight",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "soft",
            ],
            ankle_values=[
                0.63032,
                0.63776,
                0.65432,
                0.67062,
                0.71743,
                0.74083,
                0.72326,
                0.68855,
                0.59638,
                0.54810,
                0.54660,
                0.54088,
                0.54291,
                0.53773,
                0.53808,
                0.53903,
                0.53894,
                0.53262,
                0.52792,
                0.53242,
                0.52777,
                0.51984,
                0.46500,
            ],
        )
        timestamps = [
            0.0,
            0.333,
            0.5,
            0.667,
            0.833,
            1.0,
            1.167,
            1.333,
            1.667,
            2.0,
            2.333,
            2.5,
            2.667,
            2.833,
            3.0,
            3.167,
            3.333,
            3.5,
            3.667,
            3.833,
            4.0,
            4.167,
            6.5,
        ]
        motion_values = [
            0.0,
            0.1042,
            0.1139,
            0.1075,
            0.1194,
            0.1079,
            0.1035,
            0.0939,
            0.0657,
            0.0697,
            0.0399,
            0.0592,
            0.0429,
            0.0490,
            0.0429,
            0.0352,
            0.0316,
            0.0366,
            0.0382,
            0.0334,
            0.0385,
            0.0356,
            0.0447,
        ]
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 3.432)

        self.assertAlmostEqual(result["T"]["timestamp"], 2.0, places=3)
        self.assertAlmostEqual(result["A"]["timestamp"], 2.5, places=3)
        self.assertLess(result["L"]["timestamp"], 3.0)
        self.assertNotEqual(result["A"]["frame_id"], "frame_0021")
        self.assertIn("apex_motion_supported_low_prominence_minimum", result["A"]["warnings"])
        self.assertTrue(result["A"]["evidence"]["motion_supported_low_prominence_minimum"])

    def test_early_weak_geometry_motion_window_is_capped_when_later_motion_support_exists(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(
                index=index,
                frame_id=f"frame_{index + 1:04d}",
                timestamp=timestamp,
                com_y=0.50,
                hip_y=0.55,
                ankle_y=0.70,
                knee_angle=170.0,
                motion_score=motion,
                visibility_score=0.95,
            )
            for index, (timestamp, motion) in enumerate(
                [
                    (0.0, 0.02),
                    (1.0, 0.10),
                    (2.0, 0.07),
                    (3.0, 0.03),
                    (6.0, 0.11),
                    (7.0, 0.04),
                ]
            )
        ]
        motion_scores = {
            "selected": [
                {"frame_id": signal.frame_id, "timestamp": signal.timestamp, "motion_score": signal.motion_score}
                for signal in signals
            ]
        }
        candidates = [
            {"frame_id": "frame_0001", "timestamp": 0.0, "confidence": 0.62, "evidence": {}, "warnings": []},
            {"frame_id": "frame_0002", "timestamp": 1.0, "confidence": 0.58, "evidence": {}, "warnings": []},
            {"frame_id": "frame_0003", "timestamp": 2.0, "confidence": 0.44, "evidence": {}, "warnings": []},
        ]

        flags = keyframe_candidates_module._early_weak_motion_window_flags(
            signals,
            (0, 2),
            motion_scores,
            1.0,
            ["tal_candidate_takeoff_geometry_weak", "tal_candidate_landing_geometry_weak", "tal_candidate_weak_geometry"],
            candidates[0],
            candidates[1],
            candidates[2],
        )

        self.assertEqual(
            flags,
            [
                "keyframe_candidates_early_motion_window_weak_geometry",
                "tal_candidate_early_motion_window_weak_geometry",
            ],
        )
        for candidate in candidates:
            self.assertEqual(candidate["confidence"], 0.34)
            self.assertIn("tal_candidate_early_motion_window_weak_geometry", candidate["warnings"])
            diagnostic = candidate["evidence"]["early_weak_motion_window"]
            self.assertEqual(diagnostic["window"]["start_timestamp"], 0.0)
            self.assertEqual(diagnostic["later_peak_timestamp"], 6.0)
            self.assertGreaterEqual(diagnostic["later_to_window_peak_ratio"], 0.9)

    def test_compressed_window_does_not_reselect_early_approach_when_current_peak_is_comparable(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(
                index=index,
                frame_id=f"frame_{index + 1:04d}",
                timestamp=timestamp,
                com_y=0.50,
                hip_y=0.55,
                ankle_y=0.70,
                knee_angle=170.0,
                motion_score=motion,
                visibility_score=0.95,
            )
            for index, (timestamp, motion) in enumerate(
                [
                    (0.0, 0.0),
                    (0.625, 0.0434),
                    (1.5, 0.0159),
                    (1.875, 0.0333),
                    (4.125, 0.0261),
                    (5.75, 0.0449),
                    (5.875, 0.0465),
                    (6.125, 0.0441),
                ]
            )
        ]

        current_takeoff = {
            "frame_id": "frame_0006",
            "timestamp": 5.75,
            "confidence": 0.30,
            "evidence": {
                "score_components": {
                    "takeoff_event": 0.20,
                    "knee_extension": 0.05,
                    "takeoff_timing": 0.0,
                }
            },
            "warnings": ["takeoff_geometry_weak"],
        }
        current_apex = {
            "frame_id": "frame_0007",
            "timestamp": 5.812,
            "confidence": 0.30,
            "evidence": {"score_components": {"com_velocity": 0.20, "motion_peak": 0.40}},
            "warnings": ["apex_local_minimum_not_clear"],
        }
        current_landing = {
            "frame_id": "frame_0008",
            "timestamp": 5.875,
            "confidence": 0.30,
            "evidence": {
                "score_components": {
                    "landing_contact": 0.10,
                    "ankle_return": 0.0,
                    "knee_absorption": 0.0,
                    "com_descent": 0.0,
                }
            },
            "warnings": ["landing_geometry_weak"],
        }
        early_takeoff = {
            "frame_id": "frame_0002",
            "timestamp": 0.875,
            "confidence": 0.62,
            "evidence": {
                "score_components": {
                    "takeoff_event": 0.45,
                    "knee_extension": 0.16,
                    "takeoff_timing": 0.86,
                }
            },
            "warnings": [],
        }
        early_apex = {
            "frame_id": "frame_0003",
            "timestamp": 1.5,
            "confidence": 0.58,
            "evidence": {"score_components": {"com_velocity": 0.79, "motion_peak": 0.50}},
            "warnings": [],
        }
        early_landing = {
            "frame_id": "frame_0004",
            "timestamp": 1.875,
            "confidence": 0.56,
            "evidence": {
                "score_components": {
                    "landing_contact": 0.31,
                    "ankle_return": 0.0,
                    "knee_absorption": 0.0,
                    "com_descent": 0.2,
                }
            },
            "warnings": [],
        }

        result = keyframe_candidates_module._reselect_from_noncompressed_motion_window(
            [
                ((5, 7), current_takeoff, current_apex, current_landing, 6),
                ((0, 4), early_takeoff, early_apex, early_landing, 2),
            ],
            signals,
        )

        self.assertIsNone(result)

    def test_motion_fallback_excludes_rejected_tail_window_records(self) -> None:
        pose_data = _pose(
            com_values=[0.50] * 8,
            knee_states=["straight"] * 8,
            ankle_values=[None] * 8,
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 6.50, "motion_score": 0.042},
                {"frame_id": "frame_0002", "timestamp": 6.85, "motion_score": 0.057},
                {"frame_id": "frame_0003", "timestamp": 7.20, "motion_score": 0.052},
                {"frame_id": "frame_0004", "timestamp": 7.55, "motion_score": 0.039},
                {"frame_id": "frame_0005", "timestamp": 14.75, "motion_score": 0.0791},
                {"frame_id": "frame_0006", "timestamp": 14.812, "motion_score": 0.0666},
                {"frame_id": "frame_0007", "timestamp": 14.875, "motion_score": 0.0793},
                {"frame_id": "frame_0008", "timestamp": 14.938, "motion_score": 0.0746},
            ]
        }

        result = keyframe_candidates_module._motion_fallback_candidates(
            motion_scores,
            2.066,
            ["keyframe_candidates_tail_motion_window_rejected"],
            pose_data=pose_data,
            excluded_time_windows=[(14.75, 14.938)],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn(
            "keyframe_candidates_motion_fallback_excluded_rejected_tail_window",
            result["quality_flags"],
        )
        self.assertLess(result["T"]["timestamp"], 8.0)
        self.assertLess(result["A"]["timestamp"], 8.0)
        self.assertLess(result["L"]["timestamp"], 8.0)
        excluded_records = result["motion_fallback_excluded_rejected_tail_window"]["excluded_records"]
        self.assertEqual([item["timestamp"] for item in excluded_records], [14.75, 14.812, 14.875, 14.938])

    def test_motion_fallback_uses_dense_scores_after_rejected_tail_window(self) -> None:
        scores = [0.005] * 240
        for index, score in {
            109: 0.0536,
            110: 0.0504,
            111: 0.0542,
            115: 0.0592,
            116: 0.0573,
            117: 0.0543,
            127: 0.0408,
            129: 0.0419,
            236: 0.0791,
            237: 0.0666,
            238: 0.0793,
            239: 0.0746,
        }.items():
            scores[index] = score
        motion_scores = {
            "frame_rate": 16.0,
            "window_start": 0.0,
            "scores": scores,
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 6.5, "motion_score": 0.04},
                {"frame_id": "frame_0002", "timestamp": 7.2, "motion_score": 0.05},
                {"frame_id": "frame_0003", "timestamp": 8.1, "motion_score": 0.04},
                {"frame_id": "frame_0004", "timestamp": 14.75, "motion_score": 0.0791},
                {"frame_id": "frame_0005", "timestamp": 14.812, "motion_score": 0.0666},
                {"frame_id": "frame_0006", "timestamp": 14.875, "motion_score": 0.0793},
                {"frame_id": "frame_0007", "timestamp": 14.938, "motion_score": 0.0746},
            ],
        }

        result = keyframe_candidates_module._motion_fallback_candidates(
            motion_scores,
            2.066,
            ["keyframe_candidates_tail_motion_window_rejected"],
            excluded_time_windows=[(14.75, 14.938)],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("keyframe_candidates_motion_fallback_dense_scores", result["quality_flags"])
        self.assertEqual(result["motion_fallback_dense_scores"]["dense_record_count"], 240)
        self.assertAlmostEqual(result["T"]["timestamp"], 6.812, places=3)
        self.assertAlmostEqual(result["A"]["timestamp"], 7.188, places=3)
        self.assertAlmostEqual(result["L"]["timestamp"], 7.938, places=3)
        self.assertEqual(result["T"]["frame_id"], "frame_0001")
        self.assertEqual(result["A"]["frame_id"], "frame_0002")
        self.assertEqual(result["L"]["frame_id"], "frame_0003")
        self.assertEqual(result["A"]["evidence"]["motion_fallback_dense_score_record"]["thumb_index"], 115)

    def test_compressed_tail_motion_window_marks_candidate_untrusted_even_with_moderate_landing_contact(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(
                index,
                f"frame_{index + 1:04d}",
                float(index),
                0.50,
                0.50,
                0.60,
                170.0,
                motion_score,
                0.90,
            )
            for index, motion_score in enumerate(
                [0.01, 0.02, 0.03, 0.02, 0.04, 0.03, 0.02, 0.03, 0.06, 0.09, 0.11, 0.10, 0.08]
            )
        ]
        takeoff = {
            "timestamp": 8.12,
            "evidence": {"score_components": {"takeoff_event": 0.49, "knee_extension": 0.18}},
            "warnings": [],
        }
        apex = {
            "timestamp": 8.25,
            "evidence": {"score_components": {"com_velocity": 0.72}},
            "warnings": [],
        }
        landing = {
            "timestamp": 8.36,
            "evidence": {
                "score_components": {
                    "landing_contact": 0.30,
                    "ankle_return": 0.32,
                    "knee_absorption": 0.24,
                    "com_descent": 0.25,
                }
            },
            "warnings": [],
        }

        flags = keyframe_candidates_module._apply_tail_compressed_motion_window_diagnostic(
            signals,
            (8, 12),
            takeoff,
            apex,
            landing,
        )

        self.assertIn("tal_candidate_tail_motion_window_compressed_core", flags)
        self.assertIn("tal_candidate_temporal_geometry_unreliable", flags)
        for candidate in (takeoff, apex, landing):
            self.assertIn("tal_candidate_tail_motion_window_compressed_core", candidate["warnings"])
            self.assertEqual(
                candidate["evidence"]["tail_motion_window_compressed_core"]["reason"],
                "tail_motion_window_compressed_core_tal",
            )

    def test_takeoff_anchor_motion_fallback_uses_motion_support_not_only_target_gap(self) -> None:
        com_values = [
            0.512,
            0.547,
            0.573,
            0.594,
            0.604,
            0.604,
            0.577,
            0.555,
            0.535,
            0.516,
            0.497,
            0.481,
            0.464,
            0.447,
            0.429,
            0.413,
            0.392,
            0.374,
            0.364,
            0.352,
            0.347,
            0.349,
            0.345,
            0.350,
            0.351,
            0.353,
            0.353,
            0.351,
            0.350,
            0.331,
            0.316,
            0.292,
        ]
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "bent",
                "bent",
                "bent",
                "bent",
                "soft",
                "soft",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "soft",
                "bent",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
            ],
            ankle_values=[None for _ in com_values],
        )
        motion_scores = _motion(
            [
                0.0,
                0.0815,
                0.0824,
                0.0424,
                0.0754,
                0.101,
                0.0881,
                0.0873,
                0.1071,
                0.0775,
                0.0488,
                0.0491,
                0.0681,
                0.0849,
                0.2292,
                0.2258,
                0.1998,
                0.1515,
                0.0188,
                0.0271,
                0.035,
                0.0919,
                0.1067,
                0.1028,
                0.0659,
                0.0691,
                0.0666,
                0.0784,
                0.0923,
                0.0621,
                0.0895,
                0.1487,
            ]
        )

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 5.0)

        self.assertIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertEqual(result["A"]["frame_id"], "frame_0022")
        self.assertGreater(result["A"]["evidence"]["motion_score"], 0.08)
        self.assertNotIn(result["A"]["frame_id"], {"frame_0020", "frame_0021"})
        self.assertLessEqual(result["A"]["timestamp"] - result["T"]["timestamp"], 0.55)
        self.assertLessEqual(result["L"]["timestamp"] - result["T"]["timestamp"], 1.35)

    def test_takeoff_anchor_motion_fallback_prefers_early_landing_on_low_tail_plateau(self) -> None:
        takeoff = {
            "frame_id": "frame_0018",
            "timestamp": 1.625,
            "confidence": 0.806,
            "evidence": {"signal_index": 17, "motion_score": 0.0614},
            "warnings": ["keyframe_candidates_motion_fallback"],
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0003", "timestamp": 0.312, "motion_score": 0.1481},
                {"frame_id": "frame_0004", "timestamp": 0.375, "motion_score": 0.1440},
                {"frame_id": "frame_0009", "timestamp": 0.812, "motion_score": 0.1385},
                {"frame_id": "frame_0010", "timestamp": 0.875, "motion_score": 0.1284},
                {"frame_id": "frame_0018", "timestamp": 1.625, "motion_score": 0.0614},
                {"frame_id": "frame_0019", "timestamp": 1.875, "motion_score": 0.0492},
                {"frame_id": "frame_0020", "timestamp": 2.125, "motion_score": 0.0427},
                {"frame_id": "frame_0021", "timestamp": 2.188, "motion_score": 0.0387},
                {"frame_id": "frame_0022", "timestamp": 2.25, "motion_score": 0.0427},
                {"frame_id": "frame_0023", "timestamp": 2.312, "motion_score": 0.0385},
                {"frame_id": "frame_0024", "timestamp": 2.562, "motion_score": 0.0359},
                {"frame_id": "frame_0025", "timestamp": 2.812, "motion_score": 0.0372},
                {"frame_id": "frame_0026", "timestamp": 3.125, "motion_score": 0.0287},
            ],
        }

        result = keyframe_candidates_module._motion_fallback_from_takeoff_anchor(
            motion_scores,
            16.0,
            takeoff,
            ["tal_candidate_skeleton_drifted_after_takeoff"],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["A"]["frame_id"], "frame_0019")
        self.assertEqual(result["L"]["frame_id"], "frame_0020")
        self.assertAlmostEqual(result["L"]["timestamp"], 2.125, places=3)
        self.assertIn("landing_low_tail_motion_plateau_early_contact", result["L"]["warnings"])
        self.assertEqual(
            result["L"]["evidence"]["motion_fallback_low_tail_early_landing"]["reason"],
            "early_landing_from_low_tail_motion_plateau",
        )

    def test_takeoff_anchor_tail_motion_fallback_marks_untrusted_tail_window(self) -> None:
        takeoff = {
            "frame_id": "frame_0019",
            "timestamp": 7.0,
            "confidence": 0.573,
            "evidence": {
                "motion_score": 0.0396,
                "visibility_score": 0.976,
                "score_components": {"takeoff_event": 0.445},
            },
            "warnings": ["takeoff_timing_window_weak"],
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 0.0, "motion_score": 0.015},
                {"frame_id": "frame_0012", "timestamp": 3.0, "motion_score": 0.042},
                {"frame_id": "frame_0019", "timestamp": 7.0, "motion_score": 0.0396},
                {"frame_id": "frame_0023", "timestamp": 7.25, "motion_score": 0.0833},
                {"frame_id": "frame_0026", "timestamp": 7.812, "motion_score": 0.1159},
                {"frame_id": "frame_0027", "timestamp": 7.875, "motion_score": 0.1183},
            ]
        }

        result = keyframe_candidates_module._motion_fallback_from_takeoff_anchor(
            motion_scores,
            16.0,
            takeoff,
            ["tal_candidate_skeleton_drifted_after_takeoff"],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn(
            "keyframe_candidates_motion_fallback_takeoff_anchor_tail_window",
            result["quality_flags"],
        )
        self.assertIn("tal_candidate_motion_fallback_tail_window", result["quality_flags"])
        self.assertEqual(
            result["motion_fallback_takeoff_anchor_tail_window"]["reason"],
            "late_takeoff_anchor_low_visibility_motion_tail",
        )
        self.assertGreaterEqual(result["motion_fallback_takeoff_anchor_tail_window"]["fallback_start_ratio"], 0.70)
        self.assertIn("tal_candidate_motion_fallback_tail_window", result["A"]["warnings"])
        self.assertIn("motion_fallback_takeoff_anchor_tail_window", result["L"]["evidence"])
        self.assertIn("tal_candidate_confidence_low", result["quality_flags"])
        for role in ("T", "A", "L"):
            self.assertLessEqual(result[role]["confidence"], keyframe_candidates_module.TAKEOFF_ANCHOR_TAIL_WINDOW_CONFIDENCE_CAP)
            self.assertIn(
                "tal_candidate_motion_fallback_tail_window_confidence_cap",
                result[role]["evidence"],
            )

    def test_long_takeoff_apex_gap_with_weak_timing_is_flagged_unreliable(self) -> None:
        pose_data = _pose(
            com_values=[0.54, 0.52, 0.50, 0.47, 0.45, 0.43, 0.46, 0.48],
            knee_states=["soft", "soft", "straight", "straight", "soft", "bent", "soft", "straight"],
            ankle_values=[None, None, None, None, None, None, None, None],
        )
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(
                    zip(
                        [0.0, 0.2, 0.4, 0.6, 1.0, 2.4, 2.5, 2.6],
                        [0.02, 0.03, 0.04, 0.05, 0.07, 0.12, 0.11, 0.09],
                    )
                )
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 5.0)

        self.assertIn("tal_candidate_temporal_geometry_unreliable", result["quality_flags"])
        self.assertIn("tal_candidate_takeoff_apex_gap_unreliable", result["quality_flags"])
        self.assertIn("tal_candidate_temporal_geometry_unreliable", result["T"]["warnings"])
        self.assertGreaterEqual(
            result["T"]["evidence"]["temporal_geometry_unreliable"]["takeoff_apex_gap_sec"],
            1.2,
        )

    def test_sparse_pose_gap_between_unclear_apex_and_landing_caps_stitched_candidates(self) -> None:
        takeoff = {
            "frame_id": "frame_0017",
            "timestamp": 2.625,
            "confidence": 0.49,
            "evidence": {"signal_index": 14, "pose_index": 16, "score_components": {"takeoff_event": 0.31}},
            "warnings": [],
        }
        apex = {
            "frame_id": "frame_0018",
            "timestamp": 2.688,
            "confidence": 0.49,
            "evidence": {"signal_index": 15, "pose_index": 17, "score_components": {"com_velocity": 0.29}},
            "warnings": ["apex_local_minimum_not_clear"],
        }
        landing = {
            "frame_id": "frame_0024",
            "timestamp": 4.062,
            "confidence": 0.404,
            "evidence": {"signal_index": 16, "pose_index": 23, "score_components": {"landing_contact": 0.086}},
            "warnings": [],
        }

        flags = keyframe_candidates_module._sparse_track_stitched_tal_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_sparse_track_stitched", flags)
        self.assertIn("tal_candidate_unreliable_sparse_track_stitch", flags)
        self.assertEqual(takeoff["confidence"], 0.34)
        self.assertEqual(apex["confidence"], 0.34)
        self.assertEqual(landing["confidence"], 0.34)
        self.assertIn("tal_candidate_sparse_track_stitched", apex["warnings"])
        self.assertEqual(apex["evidence"]["sparse_track_stitched_tal"]["apex_landing_pose_gap"], 6)
        self.assertGreaterEqual(
            apex["evidence"]["sparse_track_stitched_tal"]["apex_landing_gap_sec"],
            1.2,
        )

    def test_takeoff_rank_penalizes_early_high_motion_when_later_geometry_is_plausible(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(
                index,
                f"frame_{index + 1:04d}",
                timestamp,
                com_y,
                com_y,
                None,
                knee_angle,
                motion,
                0.95,
            )
            for index, (timestamp, com_y, knee_angle, motion) in enumerate(
                [
                    (0.0, 0.600, 100.0, 0.05),
                    (0.2, 0.560, 130.0, 1.00),
                    (0.9, 0.568, 109.0, 0.30),
                    (1.4, 0.590, 109.0, 0.05),
                ]
            )
        ]

        takeoff = keyframe_candidates_module._detect_takeoff(
            signals,
            smoothed_com=[0.600, 0.560, 0.568, 0.590],
            smoothed_knee=[100.0, 130.0, 109.0, 109.0],
            motion_norm=[0.05, 1.0, 0.30, 0.05],
            apex_index=3,
            search_window=(0, 3),
        )

        self.assertEqual(takeoff["frame_id"], "frame_0003")
        self.assertEqual(takeoff["timestamp"], 0.9)
        self.assertEqual(takeoff["evidence"]["score_components"]["takeoff_timing"], 1.0)
        self.assertNotIn("takeoff_timing_window_weak", takeoff["warnings"])

    def test_takeoff_rank_avoids_zero_timing_high_motion_when_later_joint_event_exists(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(
                index,
                f"frame_{index + 1:04d}",
                timestamp,
                com_y,
                com_y,
                None,
                knee_angle,
                motion,
                visibility,
            )
            for index, (timestamp, com_y, knee_angle, motion, visibility) in enumerate(
                [
                    (0.00, 0.62, 100.0, 0.05, 0.95),
                    (0.62, 0.58, 118.0, 1.00, 0.99),
                    (0.75, 0.56, 125.0, 0.82, 0.99),
                    (0.94, 0.54, 126.0, 0.79, 0.97),
                    (1.25, 0.50, 138.0, 0.70, 0.84),
                    (1.62, 0.47, 145.0, 0.79, 0.87),
                    (3.31, 0.40, 150.0, 0.24, 0.92),
                ]
            )
        ]

        takeoff = keyframe_candidates_module._detect_takeoff(
            signals,
            smoothed_com=[0.62, 0.58, 0.56, 0.54, 0.50, 0.47, 0.40],
            smoothed_knee=[100.0, 118.0, 125.0, 126.0, 138.0, 145.0, 150.0],
            motion_norm=[0.05, 1.0, 0.82, 0.79, 0.70, 0.79, 0.24],
            apex_index=6,
            search_window=(0, 6),
        )

        self.assertEqual(takeoff["frame_id"], "frame_0006")
        self.assertGreater(takeoff["timestamp"], 1.0)
        self.assertLess(
            takeoff["evidence"]["score_components"]["takeoff_timing_rank"],
            takeoff["evidence"]["score_components"]["takeoff_rank"] + 0.4,
        )
        self.assertNotEqual(takeoff["frame_id"], "frame_0002")

    def test_takeoff_late_reselection_allows_adjacent_sample_before_apex(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(
                index,
                f"frame_{index + 1:04d}",
                timestamp,
                com_y,
                com_y,
                None,
                knee_angle,
                motion,
                0.95,
            )
            for index, (timestamp, com_y, knee_angle, motion) in enumerate(
                [
                    (0.0, 0.620, 110.0, 0.05),
                    (0.2, 0.560, 110.0, 1.00),
                    (2.20, 0.540, 112.0, 0.45),
                    (2.26, 0.512, 116.5, 0.20),
                ]
            )
        ]

        takeoff = keyframe_candidates_module._detect_takeoff(
            signals,
            smoothed_com=[0.620, 0.560, 0.540, 0.512],
            smoothed_knee=[110.0, 110.0, 112.0, 116.5],
            motion_norm=[0.05, 1.0, 0.41, 0.20],
            apex_index=3,
            search_window=(0, 3),
        )

        self.assertEqual(takeoff["frame_id"], "frame_0003")
        self.assertIn("takeoff_reselected_from_late_plausible_candidate", takeoff["warnings"])
        self.assertAlmostEqual(
            takeoff["evidence"]["takeoff_late_plausible_reselection"]["reselected_apex_gap_sec"],
            0.06,
            places=3,
        )

    def test_takeoff_sparse_prepeak_estimates_start_before_compressed_peak_sample(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(
                index,
                f"frame_{index + 1:04d}",
                timestamp,
                com_y,
                com_y,
                None,
                knee_angle,
                motion,
                visibility,
            )
            for index, (timestamp, com_y, knee_angle, motion, visibility) in enumerate(
                [
                    (6.688, 0.561, 176.4, 0.0418, 0.98),
                    (7.500, 0.525, 169.5, 0.0507, 0.92),
                    (7.562, 0.517, 163.8, 0.0864, 0.98),
                    (7.688, 0.476, 164.9, 0.0700, 0.80),
                ]
            )
        ]

        takeoff = keyframe_candidates_module._detect_takeoff(
            signals,
            smoothed_com=[0.561, 0.525, 0.517, 0.476],
            smoothed_knee=[176.4, 169.5, 163.8, 164.9],
            motion_norm=[0.15, 0.42, 0.82, 0.60],
            apex_index=3,
            search_window=(1, 3),
        )

        self.assertEqual(takeoff["frame_id"], "frame_0003")
        self.assertAlmostEqual(takeoff["timestamp"], 7.128, places=3)
        self.assertIn("takeoff_sparse_prepeak_estimated", takeoff["warnings"])
        self.assertIn("t_pose_signal_sparse", takeoff["warnings"])
        self.assertAlmostEqual(
            takeoff["evidence"]["sparse_prepeak_takeoff_estimate"]["estimated_apex_gap_sec"],
            0.56,
            places=3,
        )

    def test_compressed_late_reselected_takeoff_apex_gap_is_flagged_unreliable(self) -> None:
        takeoff = {
            "frame_id": "frame_0016",
            "timestamp": 4.25,
            "confidence": 0.602,
            "evidence": {
                "score_components": {
                    "takeoff_timing": 0.517,
                    "takeoff_event": 0.437,
                    "knee_extension": 0.163,
                },
                "takeoff_late_plausible_reselection": {
                    "original_timestamp": 2.25,
                    "original_apex_gap_sec": 2.062,
                    "reselected_apex_gap_sec": 0.062,
                },
            },
            "warnings": ["knee_extension_weak", "takeoff_reselected_from_late_plausible_candidate"],
        }
        apex = {
            "frame_id": "frame_0017",
            "timestamp": 4.312,
            "confidence": 0.61,
            "evidence": {"score_components": {"motion_peak": 0.5, "com_velocity": 0.811}},
            "warnings": ["confidence_missing_knee_angle_change"],
        }
        landing = {
            "frame_id": "frame_0020",
            "timestamp": 5.438,
            "confidence": 0.76,
            "evidence": {"score_components": {"landing_contact": 0.704, "ankle_return": 1.0}},
            "warnings": ["knee_absorption_weak", "landing_timing_window_weak"],
        }

        flags = _temporal_geometry_unreliable_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_temporal_geometry_unreliable", flags)
        self.assertIn("tal_candidate_takeoff_apex_gap_unreliable", flags)
        self.assertIn("tal_candidate_takeoff_apex_gap_compressed", flags)
        self.assertNotIn("tal_candidate_core_gap_compressed", flags)
        for candidate in (takeoff, apex, landing):
            self.assertIn("tal_candidate_compressed_temporal_geometry", candidate["warnings"])
            self.assertEqual(candidate["confidence"], 0.34)
            self.assertEqual(
                candidate["evidence"]["temporal_geometry_unreliable"]["takeoff_apex_gap_sec"],
                0.062,
            )

    def test_compressed_weak_takeoff_apex_gap_is_flagged_without_late_reselection(self) -> None:
        takeoff = {
            "frame_id": "frame_0016",
            "timestamp": 4.25,
            "confidence": 0.603,
            "evidence": {
                "score_components": {
                    "takeoff_timing": 0.517,
                    "takeoff_event": 0.437,
                    "knee_extension": 0.163,
                },
            },
            "warnings": ["knee_extension_weak", "takeoff_geometry_weak"],
        }
        apex = {
            "frame_id": "frame_0017",
            "timestamp": 4.312,
            "confidence": 0.602,
            "evidence": {"score_components": {"motion_peak": 0.5, "com_velocity": 0.811}},
            "warnings": ["confidence_missing_knee_angle_change"],
        }
        landing = {
            "frame_id": "frame_0020",
            "timestamp": 5.438,
            "confidence": 0.744,
            "evidence": {"score_components": {"landing_contact": 0.704, "ankle_return": 1.0}},
            "warnings": ["knee_absorption_weak", "landing_timing_window_weak"],
        }

        flags = _temporal_geometry_unreliable_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_temporal_geometry_unreliable", flags)
        self.assertIn("tal_candidate_takeoff_apex_gap_unreliable", flags)
        self.assertIn("tal_candidate_takeoff_apex_gap_compressed", flags)
        self.assertNotIn("tal_candidate_core_gap_compressed", flags)
        for candidate in (takeoff, apex, landing):
            self.assertIn("tal_candidate_compressed_temporal_geometry", candidate["warnings"])
            self.assertEqual(candidate["confidence"], 0.34)
            self.assertEqual(
                candidate["evidence"]["temporal_geometry_unreliable"]["takeoff_apex_gap_sec"],
                0.062,
            )

    def test_compressed_late_reselect_uses_original_takeoff_anchor_fallback(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48, 0.47, 0.42, 0.406, 0.484, 0.508],
            knee_states=["soft", "soft", "soft", "soft", "soft", "straight", "bent", "soft"],
            ankle_values=[0.70, 0.69, 0.68, 0.67, 0.60, 0.58, 0.69, 0.70],
            tracking_states=["tracked", "tracked", "tracked", "interpolated", "tracked", "tracked", "tracked", "tracked"],
            tracker_states=[
                None,
                None,
                "local_zoom_yolo_relock_pending",
                "lost_reused",
                None,
                None,
                None,
                None,
            ],
        )
        timestamps = [2.188, 2.25, 2.375, 3.125, 4.25, 4.312, 5.438, 5.5]
        motion_values = [0.1005, 0.1076, 0.0954, 0.0621, 0.0489, 0.0467, 0.0933, 0.0821]
        motion_scores = {
            "selected": [
                {
                    "frame_id": f"frame_{index + 1:04d}",
                    "timestamp": timestamp,
                    "motion_score": score,
                }
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }
        takeoff = {
            "frame_id": "frame_0005",
            "timestamp": 4.25,
            "confidence": 0.603,
            "evidence": {
                "motion_score": 0.0489,
                "score_components": {
                    "takeoff_timing": 0.517,
                    "takeoff_event": 0.434,
                    "knee_extension": 0.163,
                },
                "takeoff_late_plausible_reselection": {
                    "original_timestamp": 2.25,
                    "original_apex_gap_sec": 2.062,
                    "original_rank_score": 0.791,
                    "reselected_apex_gap_sec": 0.062,
                    "original_candidate": {
                        "frame_id": "frame_0002",
                        "timestamp": 2.25,
                        "confidence": 0.603,
                        "evidence": {
                            "signal_index": 1,
                            "motion_score": 0.1076,
                            "score_components": {"takeoff_event": 0.434},
                        },
                        "warnings": ["knee_extension_weak"],
                    },
                },
            },
            "warnings": ["knee_extension_weak", "takeoff_reselected_from_late_plausible_candidate"],
        }
        apex = {
            "frame_id": "frame_0006",
            "timestamp": 4.312,
            "confidence": 0.606,
            "evidence": {"signal_index": 5, "score_components": {"motion_peak": 0.5, "com_velocity": 0.811}},
            "warnings": ["confidence_missing_knee_angle_change"],
        }
        landing = {
            "frame_id": "frame_0007",
            "timestamp": 5.438,
            "confidence": 0.751,
            "evidence": {"signal_index": 6, "score_components": {"landing_contact": 0.704}},
            "warnings": ["knee_absorption_weak", "landing_timing_window_weak"],
        }

        with (
            patch.object(keyframe_candidates_module, "_detect_takeoff", return_value=takeoff),
            patch.object(keyframe_candidates_module, "_detect_apex", return_value=apex),
            patch.object(keyframe_candidates_module, "_detect_landing", return_value=landing),
        ):
            result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 30.0)

        self.assertIn(
            "tal_candidate_compressed_late_reselect_restored_takeoff_anchor",
            result["quality_flags"],
        )
        self.assertIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertLess(result["T"]["timestamp"], 3.0)
        self.assertNotEqual(result["T"]["timestamp"], 4.25)
        self.assertIn("takeoff_compressed_late_reselection_restored_anchor", result["T"]["warnings"])
        self.assertIn("keyframe_candidates_motion_fallback", result["A"]["warnings"])
        self.assertLess(result["A"]["timestamp"], 5.0)
        self.assertLess(result["L"]["timestamp"], 5.5)

    def test_compressed_core_gap_with_weak_apex_or_landing_is_flagged_unreliable(self) -> None:
        takeoff = {
            "frame_id": "frame_0018",
            "timestamp": 8.625,
            "confidence": 0.737,
            "evidence": {"score_components": {"takeoff_timing": 0.525}},
            "warnings": [],
        }
        apex = {
            "frame_id": "frame_0019",
            "timestamp": 8.688,
            "confidence": 0.628,
            "evidence": {"score_components": {"motion_peak": 0.5, "com_velocity": 0.871}},
            "warnings": ["confidence_missing_knee_angle_change"],
        }
        landing = {
            "frame_id": "frame_0021",
            "timestamp": 8.812,
            "confidence": 0.669,
            "evidence": {"score_components": {"landing_contact": 0.536, "ankle_return": 0.492}},
            "warnings": ["knee_absorption_weak"],
        }

        flags = _temporal_geometry_unreliable_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_temporal_geometry_unreliable", flags)
        self.assertIn("tal_candidate_apex_landing_gap_unreliable", flags)
        self.assertIn("tal_candidate_core_gap_compressed", flags)
        for candidate in (takeoff, apex, landing):
            self.assertIn("tal_candidate_temporal_geometry_unreliable", candidate["warnings"])
            self.assertIn("tal_candidate_compressed_temporal_geometry", candidate["warnings"])
            self.assertEqual(candidate["confidence"], 0.34)
            self.assertEqual(
                candidate["evidence"]["tal_candidate_compressed_temporal_geometry_confidence_cap"]["cap"],
                0.34,
            )
            self.assertEqual(
                candidate["evidence"]["temporal_geometry_unreliable"]["apex_landing_gap_sec"],
                0.124,
            )

    def test_compressed_apex_landing_gap_with_missing_apex_signal_is_flagged_unreliable(self) -> None:
        takeoff = {
            "frame_id": "frame_0014",
            "timestamp": 1.312,
            "confidence": 0.726,
            "evidence": {"score_components": {"takeoff_timing": 0.0}},
            "warnings": [],
        }
        apex = {
            "frame_id": "frame_0017",
            "timestamp": 2.438,
            "confidence": 0.607,
            "evidence": {"score_components": {"motion_peak": 0.5, "com_velocity": 0.803}},
            "warnings": ["confidence_missing_knee_angle_change"],
        }
        landing = {
            "frame_id": "frame_0018",
            "timestamp": 2.5,
            "confidence": 0.667,
            "evidence": {"score_components": {"landing_contact": 0.704, "ankle_return": 1.0}},
            "warnings": [],
        }

        flags = _temporal_geometry_unreliable_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_temporal_geometry_unreliable", flags)
        self.assertIn("tal_candidate_apex_landing_gap_unreliable", flags)
        self.assertIn("tal_candidate_apex_landing_gap_compressed", flags)
        self.assertNotIn("tal_candidate_core_gap_compressed", flags)
        for candidate in (takeoff, apex, landing):
            self.assertIn("tal_candidate_compressed_temporal_geometry", candidate["warnings"])
            self.assertEqual(candidate["confidence"], 0.34)

    def test_late_low_motion_landing_without_knee_absorption_is_flagged_unreliable(self) -> None:
        takeoff = {
            "frame_id": "frame_0014",
            "timestamp": 1.688,
            "confidence": 0.865,
            "evidence": {"score_components": {"takeoff_timing": 1.0, "takeoff_event": 0.925, "knee_extension": 1.0}},
            "warnings": [],
        }
        apex = {
            "frame_id": "frame_0016",
            "timestamp": 2.188,
            "confidence": 0.577,
            "evidence": {"score_components": {"motion_peak": 0.5, "com_velocity": 0.798}},
            "warnings": ["confidence_missing_knee_angle_change"],
        }
        landing = {
            "frame_id": "frame_0019",
            "timestamp": 3.688,
            "confidence": 0.51,
            "evidence": {
                "score_components": {
                    "motion_peak": 0.04,
                    "landing_timing": 0.0,
                    "landing_contact": 0.436,
                    "ankle_return": 1.0,
                    "knee_absorption": 0.0,
                    "com_descent": 0.386,
                }
            },
            "warnings": ["knee_absorption_weak", "landing_timing_window_weak"],
        }

        flags = _temporal_geometry_unreliable_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_temporal_geometry_unreliable", flags)
        self.assertIn("tal_candidate_apex_landing_gap_unreliable", flags)
        self.assertIn("tal_candidate_late_weak_landing", flags)
        self.assertIn("tal_candidate_temporal_geometry_unreliable", landing["warnings"])
        self.assertEqual(landing["confidence"], 0.49)
        self.assertEqual(
            landing["evidence"]["temporal_geometry_unreliable"]["apex_landing_gap_sec"],
            1.5,
        )
        self.assertEqual(
            landing["evidence"]["temporal_geometry_unreliable"]["landing_knee_absorption"],
            0.0,
        )

    def test_secondary_motion_cluster_avoids_discontinuous_sparse_track_stitch(self) -> None:
        tracked_pose_indices = [2, 5, 6, 7, 10, 11, 12, 13, 29]
        tracked_com_values = [0.52, 0.51, 0.505, 0.503, 0.509, 0.503, 0.493, 0.487, 0.461]
        tracked_knee_states = ["soft", "straight", "straight", "straight", "soft", "soft", "straight", "straight", "soft"]
        tracked_ankle_values = [0.556, 0.549, 0.553, 0.548, 0.561, 0.554, 0.544, 0.538, 0.481]
        tracked_by_index = {
            pose_index: (com, knee, ankle)
            for pose_index, com, knee, ankle in zip(
                tracked_pose_indices,
                tracked_com_values,
                tracked_knee_states,
                tracked_ankle_values,
            )
        }
        com_values = [tracked_by_index.get(index, (0.50, "soft", 0.55))[0] for index in range(30)]
        knee_states = [tracked_by_index.get(index, (0.50, "soft", 0.55))[1] for index in range(30)]
        ankle_values = [tracked_by_index.get(index, (0.50, "soft", 0.55))[2] for index in range(30)]
        tracking_states = ["tracked" if index in tracked_by_index else "lost" for index in range(30)]
        pose_data = _pose(
            com_values=com_values,
            knee_states=knee_states,
            ankle_values=ankle_values,
            tracking_states=tracking_states,
        )
        timestamps = [0.188, 0.938, 1.312, 1.625, 3.875, 3.938, 4.125, 4.188, 9.812]
        motion_values = [0.0422, 0.0382, 0.0355, 0.0157, 0.0611, 0.065, 0.0582, 0.0541, 0.113]
        motion_scores = {
            "selected": [
                {
                    "frame_id": f"frame_{pose_index + 1:04d}",
                    "timestamp": timestamp,
                    "motion_score": score,
                }
                for pose_index, timestamp, score in zip(tracked_pose_indices, timestamps, motion_values)
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 3.099)

        self.assertNotIn("tal_candidate_sparse_track_stitched", result["quality_flags"])
        self.assertNotIn("tal_candidate_unreliable_sparse_track_stitch", result["quality_flags"])
        self.assertLess(result["L"]["timestamp"], 5.0)
        self.assertEqual(result["T"]["timestamp"], 3.938)
        self.assertEqual(result["A"]["timestamp"], 4.125)
        self.assertEqual(result["L"]["timestamp"], 4.188)
        self.assertEqual(
            result["T"]["evidence"]["motion_cluster_window"],
            {
                "start_signal_index": 4,
                "end_signal_index": 7,
                "start_timestamp": 3.875,
                "end_timestamp": 4.188,
            },
        )

    def test_sparse_pose_gap_refines_takeoff_from_motion_between_takeoff_and_apex(self) -> None:
        pose_data = _pose(
            com_values=[0.60, 0.56, 0.52, 0.50, 0.48, 0.42, 0.36, 0.43, 0.50],
            knee_states=["bent", "soft", "straight", "straight", "straight", "straight", "straight", "soft", "bent"],
            ankle_values=[None, None, None, None, None, None, None, None, None],
            tracker_states=[
                None,
                None,
                None,
                None,
                "full_frame_yolo_relock_pending",
                "local_zoom_yolo_relock_pending",
                None,
                None,
                None,
            ],
        )
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(
                    zip(
                        [0.0, 0.3, 0.6, 0.9, 1.5, 1.8, 2.1, 2.4, 2.7],
                        [0.02, 0.03, 0.04, 0.05, 0.09, 0.12, 0.10, 0.08, 0.04],
                    )
                )
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertIn("keyframe_candidates_sparse_takeoff_motion_refined", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["quality_flags"])
        self.assertNotIn("tal_order_invalid", result["quality_flags"])
        self.assertEqual(result["T"]["timestamp"], 1.8)
        self.assertEqual(result["T"]["confidence"], 0.34)
        self.assertIn("takeoff_sparse_pose_motion_refined", result["T"]["warnings"])
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["T"]["warnings"])
        self.assertLess(result["T"]["timestamp"], result["A"]["timestamp"])
        self.assertLess(result["A"]["timestamp"], result["L"]["timestamp"])
        self.assertEqual(
            result["T"]["evidence"]["sparse_pose_takeoff_refinement"]["original_timestamp"],
            0.6,
        )

    def test_weak_landing_contact_prefers_early_plausible_candidate_over_late_tail(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(i, f"frame_{i + 1:04d}", timestamp, 0.50, 0.50, 0.50, 170.0, 0.02, 0.95)
            for i, timestamp in enumerate([0.0, 1.0, 1.5, 2.0])
        ]
        smoothed_com = [0.50, 0.42, 0.42, 0.42]
        smoothed_ankle = [0.50, 0.50, 0.50, 0.50]
        smoothed_knee = [170.0, 170.0, 170.0, 170.0]
        motion_norm = [0.0, 0.5, 0.01, 0.25]

        landing = keyframe_candidates_module._detect_landing(
            signals,
            smoothed_com,
            smoothed_ankle,
            smoothed_knee,
            motion_norm,
            apex_index=1,
            search_window=(0, 3),
        )

        self.assertEqual(landing["timestamp"], 1.5)
        self.assertIn("landing_weak_contact_early_candidate_selected", landing["warnings"])
        self.assertLessEqual(landing["evidence"]["score_components"]["landing_contact"], 0.12)

    def test_weak_foot_contact_uses_motion_supported_landing_before_late_knee_only_buffer(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(i, f"frame_{i + 1:04d}", timestamp, 0.50, 0.50, 0.50, 170.0, 0.02, 0.95)
            for i, timestamp in enumerate([0.0, 1.0, 1.25, 1.5, 1.75])
        ]
        smoothed_com = [0.50, 0.42, 0.42, 0.42, 0.42]
        smoothed_ankle = [0.50, 0.50, 0.50, 0.50, 0.50]
        smoothed_knee = [170.0, 170.0, 170.0, 166.0, 158.0]
        motion_norm = [0.0, 0.7, 0.55, 0.28, 0.18]

        landing = keyframe_candidates_module._detect_landing(
            signals,
            smoothed_com,
            smoothed_ankle,
            smoothed_knee,
            motion_norm,
            apex_index=1,
            search_window=(0, 4),
        )

        self.assertEqual(landing["timestamp"], 1.25)
        self.assertIn("landing_weak_foot_contact_motion_supported_early_candidate_selected", landing["warnings"])
        self.assertLessEqual(landing["evidence"]["score_components"]["ankle_return"], 0.12)
        self.assertLessEqual(landing["evidence"]["score_components"]["com_descent"], 0.12)

    def test_strong_landing_contact_ignores_contact_too_close_to_apex(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(i, f"frame_{i + 1:04d}", timestamp, 0.50, 0.50, 0.50, 170.0, 0.02, 0.95)
            for i, timestamp in enumerate([0.0, 1.0, 1.06, 1.25])
        ]
        smoothed_com = [0.50, 0.40, 0.58, 0.64]
        smoothed_ankle = [0.50, 0.52, 0.72, 0.74]
        smoothed_knee = [170.0, 170.0, 155.0, 145.0]
        motion_norm = [0.0, 0.2, 0.7, 0.6]

        landing = keyframe_candidates_module._detect_landing(
            signals,
            smoothed_com,
            smoothed_ankle,
            smoothed_knee,
            motion_norm,
            apex_index=1,
            search_window=(0, 3),
        )

        self.assertEqual(landing["timestamp"], 1.25)
        self.assertGreaterEqual(
            landing["evidence"]["apex_gap_sec"],
            keyframe_candidates_module.LANDING_STRONG_CONTACT_MIN_APEX_GAP_SEC,
        )

    def test_landing_reselects_strong_contact_when_it_compresses_apex_gap(self) -> None:
        signals = [
            keyframe_candidates_module._FrameSignal(i, f"frame_{i + 1:04d}", timestamp, 0.50, 0.50, 0.50, 170.0, motion, 0.95)
            for i, (timestamp, motion) in enumerate([(0.8, 0.02), (1.0, 0.2), (1.10, 0.7), (1.25, 0.8), (1.40, 0.4)])
        ]
        smoothed_com = [0.50, 0.42, 0.40, 0.50, 0.52]
        smoothed_ankle = [0.50, 0.50, 0.52, 0.54, 0.56]
        smoothed_knee = [170.0, 170.0, 170.0, 160.0, 155.0]
        motion_norm = [0.0, 0.2, 0.7, 0.8, 0.4]

        landing = keyframe_candidates_module._detect_landing(
            signals,
            smoothed_com,
            smoothed_ankle,
            smoothed_knee,
            motion_norm,
            apex_index=1,
            search_window=(0, 4),
        )

        self.assertEqual(landing["timestamp"], 1.25)
        self.assertIn("landing_reselected_from_compressed_apex_gap", landing["warnings"])
        self.assertAlmostEqual(
            landing["evidence"]["landing_compressed_gap_reselection"]["original_apex_gap_sec"],
            0.10,
            places=3,
        )

    def test_weak_apex_landing_gap_is_compressed_when_landing_signal_is_weak(self) -> None:
        takeoff = {
            "timestamp": 0.8,
            "confidence": 0.7,
            "warnings": [],
            "evidence": {"score_components": {"takeoff_timing": 1.0, "takeoff_event": 0.6, "knee_extension": 0.5}},
        }
        apex = {
            "timestamp": 1.0,
            "confidence": 0.7,
            "warnings": ["apex_local_minimum_not_clear"],
            "evidence": {"score_components": {"com_velocity": 0.31, "motion_peak": 0.5}},
        }
        landing = {
            "timestamp": 1.125,
            "confidence": 0.7,
            "warnings": ["ankle_return_weak", "knee_absorption_weak", "com_descent_weak"],
            "evidence": {
                "score_components": {
                    "landing_contact": 0.16,
                    "ankle_return": 0.2,
                    "knee_absorption": 0.0,
                    "com_descent": 0.1,
                }
            },
        }

        flags = _temporal_geometry_unreliable_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_temporal_geometry_unreliable", flags)
        self.assertIn("tal_candidate_apex_landing_gap_unreliable", flags)
        self.assertIn("tal_candidate_apex_landing_gap_compressed", flags)
        self.assertEqual(landing["confidence"], 0.34)
        self.assertIn("tal_candidate_compressed_temporal_geometry", landing["warnings"])

    def test_missing_pose_returns_warnings_without_exception(self) -> None:
        result = detect_key_frame_candidates(None, {"scores": [0.1, 0.2]}, "jump", 10.0)

        self.assertIn("keyframe_candidates_missing_pose", result["quality_flags"])
        self.assertIsNone(result["T"]["frame_id"])
        self.assertEqual(result["T"]["confidence"], 0.0)
        self.assertIn("keyframe_candidates_missing_pose", result["A"]["warnings"])

    def test_low_visibility_returns_quality_flag_and_low_confidence_candidates(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.58, 0.54, 0.50],
            knee_states=["bent", "soft", "straight", "soft"],
            ankle_values=[None, None, None, None],
            visibility=0.1,
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.1, 0.4, 0.8, 0.3]), "jump", 10.0)

        self.assertIn("keyframe_candidates_low_visibility", result["quality_flags"])
        self.assertIn("keyframe_candidates_insufficient_pose", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_compressed", result["quality_flags"])
        self.assertIn("tal_candidate_confidence_low", result["quality_flags"])
        self.assertEqual(result["A"]["frame_id"], "frame_0003")
        self.assertLessEqual(result["L"]["confidence"], 0.34)
        self.assertIn("keyframe_candidates_motion_fallback", result["A"]["warnings"])

    def test_order_anomaly_returns_warning_instead_of_raising(self) -> None:
        pose_data = _pose(
            com_values=[0.40, 0.46, 0.55, 0.61, 0.64, 0.63],
            knee_states=["straight", "straight", "soft", "bent", "soft", "straight"],
            ankle_values=[None, None, None, None, None, None],
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.8, 0.4, 0.2, 0.1, 0.4, 0.9]), "jump", 10.0)

        self.assertIn("tal_order_unresolved", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_compressed", result["quality_flags"])
        self.assertIn("tal_candidate_confidence_low", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback", result["T"]["warnings"])
        self.assertIsNotNone(result["T"]["frame_id"])
        self.assertLessEqual(result["T"]["confidence"], 0.34)

    def test_partial_geometry_uses_low_motion_fallback_to_complete_tal(self) -> None:
        pose_data = _pose(
            com_values=[0.38, 0.43, 0.49, 0.55, 0.61, 0.65],
            knee_states=["straight", "straight", "soft", "bent", "soft", "straight"],
            ankle_values=[None, None, None, None, None, None],
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.012, 0.018, 0.027, 0.02, 0.019, 0.016]), "jump", 10.0)

        self.assertIn("tal_order_unresolved", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_low_motion", result["quality_flags"])
        self.assertIsNotNone(result["T"]["frame_id"])
        self.assertIsNotNone(result["A"]["frame_id"])
        self.assertIsNotNone(result["L"]["frame_id"])

    def test_low_motion_fallback_caps_motion_only_candidate_confidence(self) -> None:
        pose_data = _pose(
            com_values=[0.38, 0.43, 0.49, 0.55, 0.61, 0.65],
            knee_states=["straight", "straight", "soft", "bent", "soft", "straight"],
            ankle_values=[None, None, None, None, None, None],
            visibility=0.0,
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.011, 0.014, 0.027, 0.02, 0.019, 0.016]), "jump", 10.0)

        self.assertIn("tal_candidate_motion_fallback_low_motion", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_low_motion_low_confidence", result["quality_flags"])
        self.assertIn("tal_candidate_confidence_low", result["quality_flags"])
        for role in ("T", "A", "L"):
            self.assertLessEqual(result[role]["confidence"], 0.34)
            self.assertIn("tal_candidate_motion_fallback_low_motion_low_confidence", result[role]["warnings"])
            self.assertGreaterEqual(
                result[role]["evidence"]["motion_fallback_low_motion_confidence_cap"]["raw_confidence"],
                result[role]["confidence"],
            )

    def test_motion_fallback_with_final_tracker_loss_is_bounded_to_reliable_pose_window(self) -> None:
        pose_data = _pose(
            com_values=[
                0.50,
                0.49,
                0.48,
                0.47,
                0.46,
                0.45,
                0.44,
                0.43,
                0.42,
                0.41,
                0.40,
                0.39,
                0.38,
                0.37,
                0.36,
                0.35,
                0.34,
                0.33,
                0.32,
                0.31,
                0.30,
                0.29,
                0.28,
                0.27,
                0.26,
                0.25,
                0.24,
                0.23,
                0.22,
                0.21,
                0.20,
                0.19,
            ],
            knee_states=["straight"] * 32,
            ankle_values=[None] * 32,
            visibility=0.1,
            tracking_states=["tracked"] * 10 + ["lost"] * 22,
            tracker_states=["tracked"] * 10
            + ["tracked", "local_zoom_yolo_relock_pending"]
            + ["lost_reused"] * 18
            + ["relock_rejected", "lost_reused"],
        )
        timestamps = [
            0.0,
            0.375,
            0.438,
            0.75,
            1.062,
            1.438,
            1.812,
            2.188,
            2.562,
            2.75,
            2.812,
            2.875,
            2.938,
            3.0,
            4.188,
            4.25,
            4.312,
            4.375,
            4.438,
            4.75,
            4.812,
            5.875,
            6.312,
            7.312,
            7.375,
            8.812,
            8.875,
            9.125,
            10.125,
            11.125,
            11.188,
            11.25,
        ]
        motion_values = [
            0.0,
            0.0851,
            0.1206,
            0.0396,
            0.0418,
            0.0378,
            0.0787,
            0.0874,
            0.0214,
            0.0528,
            0.0977,
            0.1248,
            0.1387,
            0.074,
            0.0886,
            0.108,
            0.1039,
            0.1254,
            0.0989,
            0.0926,
            0.106,
            0.0751,
            0.0656,
            0.0884,
            0.0735,
            0.0603,
            0.0806,
            0.0736,
            0.0724,
            0.078,
            0.131,
            0.1403,
        ]
        motion_scores = {
            "selected": [
                {
                    "frame_id": f"frame_{index + 1:04d}",
                    "timestamp": timestamp,
                    "motion_score": score,
                }
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 4.72)

        self.assertIn("keyframe_candidates_motion_fallback_bounded_to_reliable_pose", result["quality_flags"])
        self.assertLess(result["L"]["timestamp"], 4.2)
        self.assertNotEqual(result["L"]["frame_id"], "frame_0032")
        self.assertLess(
            result["motion_fallback_time_bounds"]["end_timestamp"],
            4.2,
        )

    def test_motion_fallback_marks_unreliable_tracker_state_records_when_no_reliable_pose_remains(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48, 0.47, 0.46],
            knee_states=["straight"] * 5,
            ankle_values=[None] * 5,
            visibility=0.1,
            tracking_states=["lost", "low_confidence", "interpolated", "tracked", "lost"],
            tracker_states=[
                "lost_reused",
                "relock_rejected",
                "tracked",
                "local_zoom_yolo_relock_pending",
                "lost_reused",
            ],
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 0.0, "motion_score": 0.02},
                {"frame_id": "frame_0002", "timestamp": 0.1, "motion_score": 0.13},
                {"frame_id": "frame_0003", "timestamp": 0.2, "motion_score": 0.21},
                {"frame_id": "frame_0004", "timestamp": 0.3, "motion_score": 0.20},
                {"frame_id": "frame_0005", "timestamp": 0.4, "motion_score": 0.04},
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_unreliable_pose_low_confidence", result["quality_flags"])
        self.assertEqual(result["T"]["frame_id"], "frame_0002")
        self.assertEqual(result["A"]["frame_id"], "frame_0003")
        self.assertEqual(result["L"]["frame_id"], "frame_0004")
        self.assertEqual(result["T"]["confidence"], 0.34)
        self.assertEqual(result["A"]["confidence"], 0.34)
        self.assertEqual(result["L"]["confidence"], 0.34)
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["T"]["warnings"])
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["A"]["warnings"])
        self.assertIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["L"]["warnings"])
        self.assertEqual(
            result["motion_fallback_unreliable_pose_records"],
            {
                "T": {"frame_id": "frame_0002", "tracking_state": "low_confidence", "tracker_state": "relock_rejected"},
                "A": {"frame_id": "frame_0003", "tracking_state": "interpolated", "tracker_state": "tracked"},
                "L": {
                    "frame_id": "frame_0004",
                    "tracking_state": "tracked",
                    "tracker_state": "local_zoom_yolo_relock_pending",
                },
            },
        )

    def test_motion_fallback_filters_unreliable_tracker_peaks_when_reliable_records_exist(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48, 0.47, 0.46, 0.45, 0.44],
            knee_states=["straight"] * 7,
            ankle_values=[None] * 7,
            visibility=0.1,
            tracking_states=["lost", "tracked", "tracked", "tracked", "lost", "tracked", "tracked"],
            tracker_states=[
                "local_zoom_yolo_relock_pending",
                "tracked",
                "tracked",
                "tracked",
                "detector_relocked",
                "tracked",
                "tracked",
            ],
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 3.0, "motion_score": 0.20},
                {"frame_id": "frame_0002", "timestamp": 3.1, "motion_score": 0.08},
                {"frame_id": "frame_0003", "timestamp": 3.2, "motion_score": 0.09},
                {"frame_id": "frame_0004", "timestamp": 3.3, "motion_score": 0.07},
                {"frame_id": "frame_0005", "timestamp": 3.4, "motion_score": 0.18},
                {"frame_id": "frame_0006", "timestamp": 3.5, "motion_score": 0.06},
                {"frame_id": "frame_0007", "timestamp": 3.6, "motion_score": 0.05},
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback_filtered_unreliable_pose_records", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback_bounded_to_reliable_pose", result["quality_flags"])
        self.assertEqual(result["T"]["frame_id"], "frame_0002")
        self.assertEqual(result["A"]["frame_id"], "frame_0003")
        self.assertEqual(result["L"]["frame_id"], "frame_0004")
        selected = {result[key]["frame_id"] for key in ("T", "A", "L")}
        self.assertNotIn("frame_0001", selected)
        self.assertNotIn("frame_0005", selected)
        self.assertNotIn("keyframe_candidates_motion_fallback_unreliable_pose_state", result["quality_flags"])
        filtered = {item["frame_id"] for item in result["motion_fallback_filtered_unreliable_pose_records"]}
        self.assertIn("frame_0005", filtered)

    def test_motion_fallback_caps_cross_segment_peak_stitching(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48],
            knee_states=["straight"] * 3,
            ankle_values=[None] * 3,
            visibility=0.1,
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 1.375, "motion_score": 0.115},
                {"frame_id": "frame_0002", "timestamp": 4.375, "motion_score": 0.118},
                {"frame_id": "frame_0003", "timestamp": 7.688, "motion_score": 0.126},
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 4.72)

        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_cross_segment_unreliable", result["quality_flags"])
        self.assertIn("tal_candidate_confidence_low", result["quality_flags"])
        self.assertGreater(result["L"]["timestamp"] - result["T"]["timestamp"], 6.0)
        self.assertLessEqual(result["T"]["confidence"], 0.28)
        self.assertLessEqual(result["A"]["confidence"], 0.28)
        self.assertLessEqual(result["L"]["confidence"], 0.28)
        self.assertIn(
            "tal_candidate_motion_fallback_cross_segment_unreliable",
            result["A"]["warnings"],
        )
        self.assertTrue(result["motion_fallback_cross_segment_diagnostic"]["cross_segment"])

    def test_motion_fallback_caps_compressed_local_triplets(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48],
            knee_states=["straight"] * 3,
            ankle_values=[None] * 3,
            visibility=0.1,
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0014", "timestamp": 4.188, "motion_score": 0.0999},
                {"frame_id": "frame_0015", "timestamp": 4.312, "motion_score": 0.0998},
                {"frame_id": "frame_0016", "timestamp": 4.375, "motion_score": 0.077},
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 4.72)

        self.assertIn("keyframe_candidates_motion_fallback", result["quality_flags"])
        self.assertIn("tal_candidate_motion_fallback_compressed", result["quality_flags"])
        self.assertIn("tal_candidate_core_gap_compressed", result["quality_flags"])
        self.assertIn("tal_candidate_confidence_low", result["quality_flags"])
        self.assertLess(result["L"]["timestamp"] - result["T"]["timestamp"], 0.32)
        self.assertLessEqual(result["T"]["confidence"], 0.34)
        self.assertLessEqual(result["A"]["confidence"], 0.34)
        self.assertLessEqual(result["L"]["confidence"], 0.34)
        self.assertIn("tal_candidate_motion_fallback_compressed", result["L"]["warnings"])
        self.assertTrue(result["motion_fallback_local_window"]["compressed"])

    def test_tiny_target_low_visibility_motion_fallback_marks_foreground_motion_risk(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48],
            knee_states=["straight"] * 3,
            ankle_values=[None] * 3,
            visibility=0.1,
            target_bboxes=[
                {"x": 0.60, "y": 0.40, "width": 0.021, "height": 0.086},
                {"x": 0.61, "y": 0.40, "width": 0.023, "height": 0.096},
                {"x": 0.62, "y": 0.40, "width": 0.024, "height": 0.094},
            ],
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0012", "timestamp": 3.188, "motion_score": 0.0999},
                {"frame_id": "frame_0013", "timestamp": 3.25, "motion_score": 0.0897},
                {"frame_id": "frame_0014", "timestamp": 3.312, "motion_score": 0.0904},
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 4.72)

        self.assertIn(
            "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
            result["quality_flags"],
        )
        self.assertIn("tal_candidate_motion_fallback_foreground_motion_risk", result["quality_flags"])
        self.assertIn("motion_fallback_tiny_target_diagnostic", result)
        self.assertEqual(
            result["motion_fallback_tiny_target_diagnostic"]["reason"],
            "tiny_target_low_visibility_motion_only_fallback",
        )
        self.assertLessEqual(result["motion_fallback_tiny_target_diagnostic"]["bbox_stats"]["median_area"], 0.004)
        self.assertIn("tal_candidate_motion_fallback_foreground_motion_risk", result["T"]["warnings"])
        self.assertIn("motion_fallback_tiny_target_foreground_motion_risk", result["A"]["evidence"])
        self.assertLessEqual(result["T"]["confidence"], 0.34)
        self.assertLessEqual(result["A"]["confidence"], 0.34)
        self.assertLessEqual(result["L"]["confidence"], 0.34)

    def test_narrow_target_motion_fallback_caps_foreground_motion_risk_confidence(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48],
            knee_states=["straight"] * 3,
            ankle_values=[None] * 3,
            visibility=0.1,
            target_bboxes=[
                {"x": 0.60, "y": 0.40, "width": 0.031, "height": 0.160},
                {"x": 0.61, "y": 0.40, "width": 0.032, "height": 0.165},
                {"x": 0.62, "y": 0.40, "width": 0.033, "height": 0.163},
            ],
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0018", "timestamp": 3.667, "motion_score": 0.0197},
                {"frame_id": "frame_0020", "timestamp": 4.0, "motion_score": 0.021},
                {"frame_id": "frame_0024", "timestamp": 4.667, "motion_score": 0.0611},
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 5.0)

        self.assertIn(
            "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
            result["quality_flags"],
        )
        self.assertIn("tal_candidate_motion_fallback_foreground_motion_risk", result["quality_flags"])
        self.assertIn("tal_candidate_confidence_low", result["quality_flags"])
        self.assertLessEqual(result["motion_fallback_tiny_target_diagnostic"]["bbox_stats"]["median_area"], 0.006)
        for role in ("T", "A", "L"):
            self.assertLessEqual(result[role]["confidence"], 0.34)
            self.assertIn("tal_candidate_motion_fallback_foreground_motion_risk", result[role]["warnings"])
            self.assertIn(
                "tal_candidate_motion_fallback_foreground_motion_risk_confidence_cap",
                result[role]["evidence"],
            )

    def test_regular_target_motion_fallback_does_not_mark_foreground_motion_risk(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48],
            knee_states=["straight"] * 3,
            ankle_values=[None] * 3,
            visibility=0.1,
            target_bboxes=[
                {"x": 0.40, "y": 0.30, "width": 0.08, "height": 0.22},
                {"x": 0.41, "y": 0.30, "width": 0.08, "height": 0.22},
                {"x": 0.42, "y": 0.30, "width": 0.08, "height": 0.22},
            ],
        )

        result = detect_key_frame_candidates(
            pose_data,
            {
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 1.0, "motion_score": 0.10},
                    {"frame_id": "frame_0002", "timestamp": 1.1, "motion_score": 0.11},
                    {"frame_id": "frame_0003", "timestamp": 1.2, "motion_score": 0.09},
                ]
            },
            "jump",
            10.0,
        )

        self.assertNotIn(
            "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
            result["quality_flags"],
        )
        self.assertNotIn("tal_candidate_motion_fallback_foreground_motion_risk", result["quality_flags"])

    def test_multiperson_relock_motion_fallback_marks_foreground_motion_risk(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48],
            knee_states=["straight"] * 3,
            ankle_values=[None] * 3,
            visibility=0.1,
            quality_flags=["person_tracker_multiperson_relock_instability_risk"],
        )

        result = detect_key_frame_candidates(
            pose_data,
            {
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 1.0, "motion_score": 0.10},
                    {"frame_id": "frame_0002", "timestamp": 1.1, "motion_score": 0.11},
                    {"frame_id": "frame_0003", "timestamp": 1.2, "motion_score": 0.09},
                ]
            },
            "jump",
            10.0,
        )

        self.assertIn(
            "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
            result["quality_flags"],
        )
        self.assertIn("tal_candidate_motion_fallback_foreground_motion_risk", result["quality_flags"])
        self.assertEqual(
            result["motion_fallback_multiperson_relock_diagnostic"]["reason"],
            "multiperson_relock_instability_motion_only_fallback",
        )
        self.assertIn("motion_fallback_multiperson_relock_instability_risk", result["T"]["evidence"])

    def test_excludes_unreliable_pose_states_from_candidates(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.60, 0.56, 0.49, 0.43, 0.38, 0.42, 0.50, 0.58],
            knee_states=["bent", "bent", "soft", "straight", "straight", "straight", "straight", "soft", "bent"],
            ankle_values=[None, None, None, None, None, None, None, None, None],
            tracking_states=[
                "tracked",
                "tracked",
                "tracked",
                "low_confidence",
                "tracked",
                "tracked",
                "interpolated",
                "tracked",
                "lost",
            ],
        )

        result = detect_key_frame_candidates(pose_data, _motion([0.05, 0.12, 0.35, 0.95, 0.45, 0.25, 0.35, 0.9, 0.25]), "jump", 10.0)

        self.assertIn("keyframe_candidates_excluded_unreliable_pose_frames", result["quality_flags"])
        self.assertEqual(result["excluded_pose_frames"], {"low_confidence": 1, "interpolated": 1, "lost": 1})
        self.assertNotEqual(result["T"]["frame_id"], "frame_0004")
        self.assertNotEqual(result["L"]["frame_id"], "frame_0009")

    def test_filtered_pose_indices_do_not_overflow_detector_windows(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.61, 0.59, 0.56, 0.50, 0.43, 0.39, 0.44, 0.52, 0.59, 0.63],
            knee_states=["bent", "bent", "soft", "soft", "straight", "straight", "straight", "soft", "bent", "bent", "soft"],
            ankle_values=[None, None, None, None, None, None, None, None, None, None, None],
            tracking_states=[
                "tracked",
                "low_confidence",
                "tracked",
                "interpolated",
                "tracked",
                "tracked",
                "tracked",
                "lost",
                "tracked",
                "tracked",
                "tracked",
            ],
        )

        result = detect_key_frame_candidates(
            pose_data,
            _motion([0.03, 0.04, 0.06, 0.08, 0.14, 0.30, 0.42, 0.20, 0.36, 0.18, 0.10]),
            "jump",
            10.0,
        )

        self.assertIn("keyframe_candidates_excluded_unreliable_pose_frames", result["quality_flags"])
        self.assertNotIn("keyframe_candidates_detection_failed", result["quality_flags"])
        self.assertIsNotNone(result["A"]["frame_id"])
        self.assertIsInstance(result["A"]["evidence"].get("pose_index"), int)
        self.assertIsInstance(result["A"]["evidence"].get("signal_index"), int)

    def test_excludes_person_tracker_unrecovered_states_from_candidates(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.60, 0.56, 0.49, 0.43, 0.38, 0.42, 0.50, 0.58, 0.59, 0.60],
            knee_states=["bent", "bent", "soft", "straight", "straight", "straight", "straight", "soft", "bent", "soft", "soft"],
            ankle_values=[None, None, None, None, None, None, None, None, None, None, None],
            tracker_states=[
                None,
                None,
                None,
                "full_frame_yolo_relock_pending",
                None,
                None,
                "detector_relocked",
                "continuity_rejected",
                "relock_rejected",
                "relocked",
                None,
            ],
        )

        result = detect_key_frame_candidates(
            pose_data,
            _motion([0.05, 0.12, 0.35, 0.95, 0.45, 0.25, 0.35, 0.9, 0.25, 0.22, 0.18]),
            "jump",
            10.0,
        )

        self.assertIn("keyframe_candidates_excluded_unreliable_pose_frames", result["quality_flags"])
        self.assertEqual(
            result["excluded_pose_frames"],
            {
                "tracker_full_frame_yolo_relock_pending": 1,
                "tracker_detector_relocked": 1,
                "tracker_continuity_rejected": 1,
                "tracker_relock_rejected": 1,
                "tracker_relocked": 1,
            },
        )
        self.assertNotEqual(result["T"]["frame_id"], "frame_0004")
        self.assertNotEqual(result["L"]["frame_id"], "frame_0008")

    def test_unclear_apex_with_late_weak_landing_uses_takeoff_anchor_fallback(self) -> None:
        pose_data = _pose(
            com_values=[0.58, 0.52, 0.50, 0.51, 0.52],
            knee_states=["bent", "straight", "straight", "straight", "straight"],
            ankle_values=[0.68, 0.64, 0.62, 0.62, 0.62],
        )
        motion_scores = _motion([0.04, 0.20, 0.12, 0.08, 0.07])
        takeoff = {
            "frame_id": "frame_0002",
            "timestamp": 1.0,
            "confidence": 0.54,
            "evidence": {"signal_index": 1, "motion_score": 0.2, "score_components": {"takeoff_event": 0.42}},
            "warnings": [],
        }
        apex = {
            "frame_id": "frame_0003",
            "timestamp": 1.12,
            "confidence": 0.46,
            "evidence": {"signal_index": 2, "score_components": {"com_velocity": 0.31}},
            "warnings": ["apex_local_minimum_not_clear"],
        }
        landing = {
            "frame_id": "frame_0005",
            "timestamp": 2.24,
            "confidence": 0.33,
            "evidence": {"signal_index": 4, "score_components": {"motion_peak": 0.24, "landing_contact": 0.05}},
            "warnings": ["landing_confidence_low"],
        }
        fallback = {
            "quality_flags": [
                "tal_candidate_skeleton_drifted_after_takeoff",
                "keyframe_candidates_motion_fallback",
                "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                "tal_candidate_motion_fallback_low_precision",
            ],
            "T": takeoff,
            "A": {**apex, "frame_id": "frame_0003", "timestamp": 1.12},
            "L": {**landing, "frame_id": "frame_0004", "timestamp": 1.8},
        }

        with (
            patch.object(keyframe_candidates_module, "_detect_apex", return_value=apex),
            patch.object(keyframe_candidates_module, "_detect_takeoff", return_value=takeoff),
            patch.object(keyframe_candidates_module, "_detect_landing", return_value=landing),
            patch.object(keyframe_candidates_module, "_tail_motion_window_has_weak_geometry", return_value=False),
            patch.object(
                keyframe_candidates_module,
                "_motion_fallback_from_takeoff_anchor",
                return_value=fallback,
            ) as fallback_mock,
        ):
            result = keyframe_candidates_module.detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        fallback_mock.assert_called_once()
        self.assertIn("tal_candidate_skeleton_drifted_after_takeoff", result["quality_flags"])
        self.assertIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertEqual(result["L"]["frame_id"], "frame_0004")

    def test_ordered_visible_landing_candidate_marks_unclear_apex_and_landing_weak(self) -> None:
        pose_data = _pose(
            com_values=[0.62, 0.60, 0.56, 0.50, 0.44, 0.39, 0.40, 0.401],
            knee_states=["bent", "bent", "soft", "straight", "straight", "straight", "straight", "straight"],
            ankle_values=[0.72, 0.70, 0.68, 0.66, 0.64, 0.62, 0.62, 0.62],
            visibility=0.42,
        )
        motion_scores = _motion([0.02, 0.05, 0.10, 0.70, 0.20, 0.30, 0.04, 0.05])

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertEqual(
            result["quality_flags"],
            [
                "tal_candidate_apex_geometry_weak",
                "tal_candidate_landing_geometry_weak",
                "tal_candidate_weak_geometry",
                "tal_candidate_confidence_low",
            ],
        )
        self.assertEqual(result["L"]["confidence"], 0.34)
        self.assertIn("landing_confidence_low", result["L"]["warnings"])
        self.assertIn("confidence_floor_from_ordered_tal", result["L"]["warnings"])
        self.assertIn("apex_geometry_weak", result["A"]["warnings"])
        self.assertIn("landing_geometry_weak", result["L"]["warnings"])
        self.assertIn("tal_candidate_weak_geometry", result["L"]["warnings"])

    def test_weak_geometry_flags_mark_complete_but_unreliable_tal_candidates(self) -> None:
        takeoff = {
            "confidence": 0.651,
            "warnings": ["knee_extension_weak", "com_ascent_weak"],
            "evidence": {"score_components": {"takeoff_event": 0.153, "knee_extension": 0.08}},
        }
        apex = {
            "confidence": 0.602,
            "warnings": ["apex_local_minimum_not_clear"],
            "evidence": {"score_components": {"com_velocity": 0.275}},
        }
        landing = {
            "confidence": 0.744,
            "warnings": ["ankle_return_weak", "com_descent_weak"],
            "evidence": {
                "score_components": {
                    "landing_contact": 0.248,
                    "ankle_return": 0.1,
                    "knee_absorption": 0.05,
                }
            },
        }

        flags = _weak_geometry_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_takeoff_geometry_weak", flags)
        self.assertIn("tal_candidate_apex_geometry_weak", flags)
        self.assertIn("tal_candidate_landing_geometry_weak", flags)
        self.assertIn("tal_candidate_weak_geometry", flags)
        self.assertIn("takeoff_geometry_weak", takeoff["warnings"])
        self.assertIn("apex_geometry_weak", apex["warnings"])
        self.assertIn("landing_geometry_weak", landing["warnings"])
        for candidate in (takeoff, apex, landing):
            self.assertEqual(candidate["confidence"], 0.34)
            self.assertIn("tal_candidate_weak_geometry", candidate["warnings"])
            self.assertIn("weak_geometry_confidence_cap", candidate["evidence"])
            self.assertIn("tal_candidate_weak_geometry_confidence_cap", candidate["evidence"])

    def test_tiny_target_weak_geometry_adds_specific_candidate_flag(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48],
            knee_states=["straight"] * 3,
            ankle_values=[None] * 3,
            target_bboxes=[
                {"x": 0.60, "y": 0.40, "width": 0.020, "height": 0.108},
                {"x": 0.61, "y": 0.40, "width": 0.021, "height": 0.109},
                {"x": 0.62, "y": 0.40, "width": 0.020, "height": 0.107},
            ],
        )
        takeoff = {"confidence": 0.52, "warnings": [], "evidence": {}}
        apex = {"confidence": 0.45, "warnings": [], "evidence": {}}
        landing = {"confidence": 0.50, "warnings": [], "evidence": {}}

        flags = _tiny_target_weak_geometry_flags(
            pose_data,
            ["tal_candidate_weak_geometry"],
            takeoff,
            apex,
            landing,
        )

        self.assertEqual(flags, ["tal_candidate_tiny_target_weak_geometry"])
        for candidate in (takeoff, apex, landing):
            self.assertEqual(candidate["confidence"], 0.34)
            self.assertIn("tal_candidate_tiny_target_weak_geometry", candidate["warnings"])
            self.assertIn("tiny_target_weak_geometry", candidate["evidence"])
            self.assertIn("tal_candidate_tiny_target_weak_geometry_confidence_cap", candidate["evidence"])

    def test_regular_target_weak_geometry_does_not_add_tiny_target_flag(self) -> None:
        pose_data = _pose(
            com_values=[0.50, 0.49, 0.48],
            knee_states=["straight"] * 3,
            ankle_values=[None] * 3,
            target_bboxes=[
                {"x": 0.40, "y": 0.30, "width": 0.08, "height": 0.22},
                {"x": 0.41, "y": 0.30, "width": 0.08, "height": 0.22},
                {"x": 0.42, "y": 0.30, "width": 0.08, "height": 0.22},
            ],
        )
        takeoff = {"confidence": 0.52, "warnings": [], "evidence": {}}
        apex = {"confidence": 0.45, "warnings": [], "evidence": {}}
        landing = {"confidence": 0.50, "warnings": [], "evidence": {}}

        flags = _tiny_target_weak_geometry_flags(
            pose_data,
            ["tal_candidate_weak_geometry"],
            takeoff,
            apex,
            landing,
        )

        self.assertEqual(flags, [])
        self.assertNotIn("tal_candidate_tiny_target_weak_geometry", takeoff["warnings"])

    def test_unclear_apex_with_weak_descent_support_marks_geometry_weak(self) -> None:
        takeoff = {
            "warnings": [],
            "evidence": {"score_components": {"takeoff_event": 0.6, "knee_extension": 0.4}},
        }
        apex = {
            "warnings": ["apex_local_minimum_not_clear"],
            "evidence": {
                "descent_support": 0.155,
                "score_components": {"com_velocity": 0.531},
            },
        }
        landing = {
            "warnings": [],
            "evidence": {
                "score_components": {
                    "landing_contact": 0.5,
                    "ankle_return": 0.6,
                    "knee_absorption": 0.4,
                    "com_descent": 0.5,
                }
            },
        }

        flags = _weak_geometry_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_apex_geometry_weak", flags)
        self.assertNotIn("tal_candidate_weak_geometry", flags)
        self.assertIn("apex_geometry_weak", apex["warnings"])

    def test_early_weak_landing_candidate_marks_geometry_weak(self) -> None:
        takeoff = {
            "warnings": [],
            "evidence": {"score_components": {"takeoff_event": 0.6, "knee_extension": 0.4}},
        }
        apex = {
            "warnings": [],
            "evidence": {"score_components": {"com_velocity": 0.6}},
        }
        landing = {
            "warnings": ["landing_weak_contact_early_candidate_selected"],
            "evidence": {
                "score_components": {
                    "landing_contact": 0.372,
                    "ankle_return": 0.741,
                    "knee_absorption": 0.0,
                    "com_descent": 0.276,
                }
            },
        }

        flags = _weak_geometry_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_landing_geometry_weak", flags)
        self.assertNotIn("tal_candidate_weak_geometry", flags)
        self.assertIn("landing_geometry_weak", landing["warnings"])

    def test_weak_geometry_flags_mark_absent_landing_geometry_as_unreliable(self) -> None:
        takeoff = {
            "warnings": [],
            "evidence": {"score_components": {"takeoff_event": 0.6}},
        }
        apex = {
            "warnings": ["apex_local_minimum_not_clear"],
            "evidence": {"score_components": {"com_velocity": 0.4}},
        }
        landing = {
            "warnings": ["ankle_return_weak", "knee_absorption_weak", "com_descent_weak"],
            "evidence": {
                "apex_gap_sec": 1.125,
                "score_components": {
                    "landing_contact": 0.04,
                    "ankle_return": 0.0,
                    "knee_absorption": 0.0,
                    "com_descent": 0.0,
                }
            },
        }

        flags = _weak_geometry_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_landing_geometry_absent", flags)
        self.assertIn("tal_candidate_weak_geometry", flags)
        self.assertIn("landing_geometry_absent", landing["warnings"])

    def test_weak_geometry_flags_preserve_single_landing_geometry_flag(self) -> None:
        takeoff = {
            "warnings": [],
            "evidence": {"score_components": {"takeoff_event": 0.6}},
        }
        apex = {
            "warnings": [],
            "evidence": {"score_components": {"com_velocity": 0.6}},
        }
        landing = {
            "warnings": ["ankle_return_weak", "knee_absorption_weak"],
            "evidence": {
                "score_components": {
                    "landing_contact": 0.161,
                    "ankle_return": 0.245,
                    "knee_absorption": 0.0,
                }
            },
        }

        flags = _weak_geometry_flags(takeoff, apex, landing)

        self.assertIn("tal_candidate_landing_geometry_weak", flags)
        self.assertNotIn("tal_candidate_weak_geometry", flags)
        self.assertIn("landing_geometry_weak", landing["warnings"])

    def test_occluded_motion_window_marks_candidates_contaminated(self) -> None:
        pose_data = _pose(
            com_values=[
                0.58,
                0.57,
                0.56,
                0.55,
                0.54,
                0.53,
                0.52,
                0.51,
                0.50,
                0.49,
                0.48,
                0.47,
                0.46,
                0.45,
                0.44,
                0.43,
                0.42,
                0.46,
                0.461,
                0.462,
            ],
            knee_states=[
                "bent",
                "bent",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
            ],
            ankle_values=[0.72] * 20,
            tracker_states=[
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "local_zoom_yolo_relock_pending",
                "lost_reused",
                "relock_rejected",
                "relock_rejected",
                None,
                None,
                None,
            ],
            tracking_states=[
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "interpolated",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
                "tracked",
            ],
        )
        motion_scores = _motion(
            [
                0.0,
                0.02,
                0.02,
                0.03,
                0.05,
                0.06,
                0.07,
                0.08,
                0.09,
                0.08,
                0.07,
                0.06,
                0.07,
                0.08,
                0.23,
                0.22,
                0.20,
                0.15,
                0.02,
                0.02,
            ]
        )

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 10.0)

        self.assertIn("tal_candidate_motion_window_occlusion_contaminated", result["quality_flags"])
        self.assertIn("tal_candidate_motion_window_unreliable_tracker_state", result["quality_flags"])
        for key in ("T", "A", "L"):
            self.assertIn("motion_window_occlusion_contaminated", result[key]["warnings"])
            diagnostic = result[key]["evidence"]["motion_window_occlusion_contamination"]
            self.assertEqual(diagnostic["peak_timestamp"], 1.4)
            self.assertGreaterEqual(diagnostic["unreliable_state_count"], 2)

    def test_occluded_main_motion_peak_prevents_candidates_from_drifting_to_post_relock_tail(self) -> None:
        pose_data = _pose(
            com_values=[
                0.50,
                0.50,
                0.50,
                0.49,
                0.48,
                0.47,
                0.46,
                0.52,
                0.50,
                0.48,
                0.45,
                0.40,
                0.46,
            ],
            knee_states=[
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "bent",
            ],
            ankle_values=[0.66] * 13,
            tracker_states=[
                None,
                None,
                None,
                "full_frame_yolo_relock_pending",
                "continuity_rejected",
                "continuity_rejected",
                "continuity_rejected",
                "relock_pending",
                "relocked",
                None,
                None,
                None,
                None,
            ],
        )
        timestamps = [
            4.188,
            4.625,
            4.688,
            4.750,
            4.812,
            4.875,
            4.938,
            6.000,
            6.062,
            6.125,
            6.250,
            6.375,
            6.438,
        ]
        motion_values = [
            0.0417,
            0.0459,
            0.0580,
            0.1138,
            0.1153,
            0.0832,
            0.0728,
            0.0454,
            0.0792,
            0.0798,
            0.0782,
            0.1045,
            0.0481,
        ]
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 5.0)

        self.assertIn("keyframe_candidates_occluded_motion_peak_override", result["quality_flags"])
        self.assertIn("tal_candidate_motion_window_occlusion_contaminated", result["quality_flags"])
        self.assertEqual(result["T"]["frame_id"], "frame_0001")
        self.assertAlmostEqual(result["T"]["timestamp"], 4.188, places=3)
        self.assertEqual(result["A"]["frame_id"], "frame_0005")
        self.assertAlmostEqual(result["A"]["timestamp"], 4.812, places=3)
        self.assertEqual(result["L"]["frame_id"], "frame_0007")
        self.assertAlmostEqual(result["L"]["timestamp"], 5.152, places=3)
        self.assertLess(result["L"]["timestamp"], 5.3)
        self.assertNotEqual(result["T"]["frame_id"], "frame_0011")
        self.assertNotEqual(result["A"]["frame_id"], "frame_0012")
        self.assertTrue(result["L"]["evidence"]["estimated_timestamp"])
        self.assertAlmostEqual(result["L"]["evidence"]["nearest_motion_record_timestamp"], 4.938, places=3)
        for key in ("T", "A", "L"):
            self.assertEqual(result[key]["confidence"], 0.34)
            self.assertIn("motion_window_occlusion_contaminated", result[key]["warnings"])

    def test_compressed_unclear_apex_landing_uses_takeoff_anchor_motion_fallback(self) -> None:
        pose_data = _pose(
            com_values=[
                0.51282,
                0.54708,
                0.57307,
                0.59407,
                0.60386,
                0.60395,
                0.57691,
                0.55546,
                0.53476,
                0.51619,
                0.49665,
                0.48095,
                0.46390,
                0.44687,
                0.42906,
                0.41340,
                0.39168,
                0.37361,
                0.36387,
                0.35198,
                0.34739,
                0.34929,
                0.34480,
                0.34977,
                0.35063,
                0.35330,
                0.35310,
            ],
            knee_states=[
                "straight",
                "straight",
                "straight",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "bent",
                "straight",
                "straight",
                "straight",
                "straight",
                "straight",
                "soft",
                "straight",
                "straight",
                "straight",
                "straight",
            ],
            ankle_values=[
                0.71892,
                0.78681,
                0.79247,
                0.80496,
                0.81968,
                0.83313,
                0.85869,
                0.85962,
                0.84042,
                0.81043,
                0.83806,
                0.81821,
                0.71188,
                0.66859,
                0.62607,
                0.58934,
                0.58182,
                0.57017,
                0.56801,
                0.55473,
                0.54980,
                0.55099,
                0.54276,
                0.53992,
                0.53528,
                0.53621,
                0.53313,
            ],
        )
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(
                    [
                        (0.0, 0.0),
                        (0.25, 0.1193),
                        (0.312, 0.1481),
                        (0.375, 0.1440),
                        (0.438, 0.1253),
                        (0.5, 0.0743),
                        (0.688, 0.1278),
                        (0.75, 0.1384),
                        (0.812, 0.1384),
                        (0.875, 0.1284),
                        (0.938, 0.1142),
                        (1.0, 0.0661),
                        (1.062, 0.1051),
                        (1.125, 0.0963),
                        (1.188, 0.0763),
                        (1.25, 0.0589),
                        (1.375, 0.0420),
                        (1.625, 0.0614),
                        (1.875, 0.0491),
                        (2.125, 0.0427),
                        (2.188, 0.0386),
                        (2.25, 0.0427),
                        (2.312, 0.0385),
                        (2.562, 0.0359),
                        (2.812, 0.0371),
                        (3.125, 0.0287),
                        (3.188, 0.0247),
                    ]
                )
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 16.0)

        self.assertTrue(
            {
                "tal_candidate_apex_landing_gap_compressed",
                "tal_candidate_skeleton_drifted_after_takeoff",
            }
            & set(result["quality_flags"])
        )
        self.assertIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertLess(result["T"]["timestamp"], result["A"]["timestamp"])
        self.assertLess(result["A"]["timestamp"], result["L"]["timestamp"])
        self.assertGreater(result["L"]["timestamp"] - result["A"]["timestamp"], 0.10)

    def test_rejected_tail_window_does_not_reselect_early_noise_when_late_pose_core_exists(self) -> None:
        com_values = [
            0.51036,
            0.51352,
            0.51592,
            0.51686,
            0.51803,
            0.51645,
            0.50780,
            0.50177,
            0.49723,
            0.48384,
            0.47585,
            0.47177,
            0.46857,
            0.46223,
            0.45099,
            0.44500,
            0.44144,
            0.44157,
            0.44591,
            0.45207,
            0.45566,
            0.45881,
            0.45873,
            0.45663,
            0.45744,
            0.46658,
            0.47081,
            0.47732,
            0.47586,
            0.47233,
            0.47598,
        ]
        knee_angles = [
            152.8,
            156.4,
            162.2,
            163.1,
            164.0,
            162.5,
            161.7,
            160.4,
            159.6,
            159.6,
            160.4,
            160.6,
            163.6,
            163.1,
            169.8,
            177.8,
            169.8,
            146.4,
            161.1,
            175.0,
            176.7,
            178.6,
            174.1,
            175.3,
            171.7,
            171.1,
            164.6,
            176.8,
            178.1,
            178.9,
            179.2,
        ]
        pose_data = _pose(
            com_values=com_values,
            knee_states=[
                "straight" if angle >= 170.0 else "soft" if angle >= 155.0 else "bent"
                for angle in knee_angles
            ],
            ankle_values=[
                0.76,
                0.77,
                0.78,
                0.78,
                0.78,
                0.77,
                0.75,
                0.74,
                0.73,
                0.72,
                0.71,
                0.70,
                0.69,
                0.68,
                0.67,
                0.66,
                0.65,
                0.64,
                0.64,
                0.65,
                0.65,
                0.66,
                0.66,
                0.64,
                0.67,
                0.70,
                0.71,
                0.72,
                0.72,
                0.72,
                0.72,
            ],
        )
        timestamps = [
            0.0,
            0.062,
            0.125,
            0.188,
            0.25,
            0.312,
            0.375,
            0.438,
            0.5,
            0.688,
            0.75,
            0.812,
            0.938,
            1.188,
            1.438,
            1.625,
            2.062,
            2.125,
            2.25,
            2.938,
            3.0,
            4.188,
            4.25,
            4.812,
            4.875,
            5.812,
            5.875,
            6.125,
            7.188,
            7.25,
            7.312,
        ]
        motion_values = [
            0.0,
            0.0502,
            0.0518,
            0.0498,
            0.0463,
            0.0446,
            0.0633,
            0.0514,
            0.0257,
            0.0362,
            0.0318,
            0.0294,
            0.0244,
            0.0190,
            0.0226,
            0.0206,
            0.0277,
            0.0302,
            0.0267,
            0.0240,
            0.0141,
            0.0148,
            0.0239,
            0.0114,
            0.0124,
            0.0175,
            0.0130,
            0.0123,
            0.0235,
            0.0238,
            0.0675,
        ]
        motion_scores = {
            "selected": [
                {"frame_id": f"frame_{index + 1:04d}", "timestamp": timestamp, "motion_score": score}
                for index, (timestamp, score) in enumerate(zip(timestamps, motion_values))
            ]
        }

        result = detect_key_frame_candidates(pose_data, motion_scores, "jump", 16.0)

        self.assertIn("keyframe_candidates_tail_motion_window_rejected", result["quality_flags"])
        self.assertIn("keyframe_candidates_tail_motion_window_reselected", result["quality_flags"])
        self.assertIn("keyframe_candidates_late_pose_core_reselected", result["quality_flags"])
        self.assertNotIn("keyframe_candidates_motion_fallback_from_takeoff_anchor", result["quality_flags"])
        self.assertAlmostEqual(result["T"]["timestamp"], 4.25, places=3)
        self.assertAlmostEqual(result["A"]["timestamp"], 4.812, places=3)
        self.assertAlmostEqual(result["L"]["timestamp"], 4.875, places=3)
        for key in ("T", "A", "L"):
            self.assertEqual(
                result[key]["evidence"]["late_pose_core_reselection"]["pose_core_window"]["start_timestamp"],
                4.188,
            )


if __name__ == "__main__":
    unittest.main()
