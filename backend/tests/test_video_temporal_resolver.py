from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video_temporal import normalize_video_temporal_payload, resolve_semantic_keyframes, validate_video_temporal_payload


def _video_payload(confidence: float = 0.86) -> dict[str, object]:
    return {
        "schema_version": "video_temporal_v1",
        "provider": "qwen",
        "model": "qwen3.6-plus",
        "action_confirmation": {
            "action_family": "jump",
            "confirmed_action": "Axel",
            "jump_type": "Axel",
            "confidence": confidence,
            "notes": "",
        },
        "phase_segments": [
            {"phase_code": "takeoff", "phase_label": "起跳", "time_start": 1.0, "time_end": 1.4, "key_frame_hint": 1.18, "confidence": 0.82},
            {"phase_code": "air", "phase_label": "腾空", "time_start": 1.4, "time_end": 1.8, "key_frame_hint": 1.6, "confidence": 0.84},
            {"phase_code": "landing", "phase_label": "落冰", "time_start": 1.8, "time_end": 2.2, "key_frame_hint": 1.96, "confidence": 0.83},
        ],
        "key_moments": {"T_takeoff_sec": 1.2, "A_air_sec": 1.6, "L_landing_sec": 2.0},
        "macro_assessment": {},
        "overall_impression": "ok",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": confidence,
        "fallback_recommendation": "use_video_timestamps",
        "quality_flags": [],
    }


def _validated_video(confidence: float = 0.86) -> dict[str, object]:
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(_video_payload(confidence), "qwen", "qwen3.6-plus"),
        duration_sec=3.0,
    )


def _motion_scores() -> dict[str, object]:
    return {
        "selected": [
            {"frame_id": "frame_0001", "timestamp": 1.05, "motion_score": 0.2},
            {"frame_id": "frame_0002", "timestamp": 1.2, "motion_score": 0.45},
            {"frame_id": "frame_0003", "timestamp": 1.3, "motion_score": 0.95},
            {"frame_id": "frame_0004", "timestamp": 1.55, "motion_score": 0.8},
            {"frame_id": "frame_0005", "timestamp": 1.95, "motion_score": 0.9},
        ],
        "scores": [0.2, 0.45, 0.95, 0.8, 0.9],
    }


def _motion_series() -> dict[str, object]:
    return {
        "frame_rate": 10,
        "window_start": 1.0,
        "scores": [0.05, 0.1, 0.2, 0.95, 0.4, 0.7, 0.1, 0.2, 0.1, 0.9, 0.2, 0.1, 0.05],
        "selected": [
            {"frame_id": "frame_0001", "timestamp": 1.0, "motion_score": 0.05},
            {"frame_id": "frame_0002", "timestamp": 1.5, "motion_score": 0.7},
            {"frame_id": "frame_0003", "timestamp": 1.9, "motion_score": 0.9},
        ],
    }


def _skeleton() -> dict[str, object]:
    return {
        "key_frame_candidates": {
            "T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.81},
            "A": {"frame_id": "frame_0004", "timestamp": 1.55, "confidence": 0.79},
            "L": {"frame_id": "frame_0005", "timestamp": 1.95, "confidence": 0.82},
        }
    }


class VideoTemporalResolverTests(unittest.TestCase):
    def test_high_confidence_uses_video_ai_refined_plan(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual(plan["confidence"], 0.86)
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["takeoff", "air", "landing"])
        self.assertLessEqual(len(plan["selected"]), 12)
        self.assertEqual(plan["selected"][0]["frame_id"], "semantic_0001")
        self.assertEqual(plan["selected"][0]["timestamp"], 1.3)

    def test_medium_confidence_blended_prefers_skeleton_inside_video_interval(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.68),
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertEqual(plan["selected"][0]["timestamp"], 1.3)
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_skeleton_takeoff_motion_peak")

    def test_low_confidence_falls_back_to_skeleton_candidates(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.42),
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_low_video_confidence", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [1.3, 1.55, 1.95])
        self.assertEqual(plan["selected"][0]["selection_reason"], "skeleton_fallback_motion_peak")

    def test_low_confidence_skeleton_fallback_rejects_weak_candidates(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.52},
                "A": {"frame_id": "frame_0004", "timestamp": 1.55, "confidence": 0.79},
                "L": {"frame_id": "frame_0005", "timestamp": 1.95, "confidence": 0.34},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.42),
            skeleton,
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["air"])
        self.assertIn("video_temporal_resolver_skeleton_t_below_anchor_confidence", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_skeleton_l_below_anchor_confidence", plan["quality_flags"])

    def test_no_motion_score_uses_key_frame_hint_when_skeleton_missing(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            None,
            None,
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [1.18, 1.6, 1.96])
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_key_hint")

    def test_skeleton_takeoff_snaps_to_full_motion_score_peak(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.81},
                "A": {"frame_id": "frame_0005", "timestamp": 1.5, "confidence": 0.79},
                "L": {"frame_id": "frame_0009", "timestamp": 1.9, "confidence": 0.82},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            skeleton,
            _motion_series(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["selected"][0]["timestamp"], 1.3)
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_skeleton_takeoff_motion_peak")

    def test_skeleton_takeoff_outside_motion_tolerance_preserves_anchor(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0002", "timestamp": 1.0, "confidence": 0.81},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            skeleton,
            _motion_series(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["selected"][0]["timestamp"], 1.0)
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_skeleton_takeoff_anchor")

    def test_low_skeleton_confidence_falls_through_to_motion_peak(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.58},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.68),
            skeleton,
            _motion_series(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["selected"][0]["timestamp"], 1.3)
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_motion_peak")

    def test_apex_is_not_pulled_to_motion_peak(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "A": {"frame_id": "frame_0005", "timestamp": 1.5, "confidence": 0.81},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            skeleton,
            _motion_series(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        apex = [item for item in plan["selected"] if item["phase_code"] == "air"][0]
        self.assertEqual(apex["timestamp"], 1.5)
        self.assertEqual(apex["selection_reason"], "video_phase_range_skeleton_apex")

    def test_tal_out_of_order_switches_to_blended_and_flags(self) -> None:
        payload = _video_payload(0.88)
        payload["key_moments"] = {"T_takeoff_sec": 2.0, "A_air_sec": 1.6, "L_landing_sec": 1.2}
        validated = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus"),
            duration_sec=3.0,
        )

        plan = resolve_semantic_keyframes(
            validated,
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_tal_order_blended", plan["quality_flags"])
        self.assertTrue(plan["selected"])

    def test_out_of_bounds_video_interval_falls_back_per_phase(self) -> None:
        payload = _video_payload(0.86)
        payload["phase_segments"] = [
            {"phase_code": "takeoff", "phase_label": "起跳", "time_start": 3.5, "time_end": 4.0, "key_frame_hint": 3.6, "confidence": 0.82}
        ]
        validated = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus"),
            duration_sec=3.0,
        )

        plan = resolve_semantic_keyframes(
            validated,
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_phase_takeoff_fallback", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [1.3, 1.55, 1.95])

    def test_plan_is_json_serializable_and_respects_frame_budget(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
            max_frames=2,
        )

        json.dumps(plan, ensure_ascii=False)
        self.assertEqual(len(plan["selected"]), 2)


if __name__ == "__main__":
    unittest.main()
