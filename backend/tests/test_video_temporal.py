from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video_temporal import normalize_video_temporal_payload, validate_video_temporal_payload


def _valid_jump_payload() -> dict[str, object]:
    return {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {
            "action_family": "jump",
            "confirmed_action": "Axel",
            "jump_type": "Axel",
            "confidence": 1.2,
            "notes": "",
        },
        "phase_segments": [
            {
                "phase_code": "preparation",
                "phase_label": "准备",
                "time_start": 1.5,
                "time_end": 2.0,
                "key_frame_hint": 1.8,
                "confidence": 0.72,
            },
            {
                "phase_code": "takeoff",
                "phase_label": "起跳",
                "time_start": 2.1,
                "time_end": 2.5,
                "key_frame_hint": 2.32,
                "confidence": 0.76,
                "observations": ["起跳节奏清楚"],
                "issues": [],
            },
            {
                "phase_code": "air",
                "phase_label": "腾空",
                "time_start": 2.5,
                "time_end": 2.8,
                "key_frame_hint": 2.64,
                "confidence": 0.82,
            },
            {
                "phase_code": "landing",
                "phase_label": "落冰",
                "time_start": 2.8,
                "time_end": 3.2,
                "key_frame_hint": 2.94,
                "confidence": 0.8,
            },
        ],
        "key_moments": {
            "T_takeoff_sec": 2.32,
            "A_air_sec": 2.64,
            "L_landing_sec": 2.94,
        },
        "macro_assessment": {
            "timing_rhythm": "节奏基本连贯",
            "speed_flow": "滑行速度适合儿童初级训练",
            "axis_overall": "轴心略偏但可控",
            "entry_quality": "入跳准备较清楚",
            "exit_or_landing_quality": "落冰有缓冲",
            "top_strengths": ["敢于完成动作"],
            "top_issues": ["手臂收紧还可以更快"],
        },
        "overall_impression": "整体完成积极，适合继续练习起跳节奏。",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.86,
        "fallback_recommendation": "use_video_timestamps",
        "quality_flags": [],
    }


class VideoTemporalPayloadTests(unittest.TestCase):
    def test_normalize_and_validate_valid_payload(self) -> None:
        normalized = normalize_video_temporal_payload(_valid_jump_payload(), provider="qwen", model="qwen3.6-plus")
        validated = validate_video_temporal_payload(normalized, duration_sec=5.0)

        self.assertTrue(validated["valid"])
        self.assertEqual(validated["schema_version"], "video_temporal_v1")
        self.assertEqual(validated["provider"], "qwen")
        self.assertEqual(validated["model"], "qwen3.6-plus")
        self.assertEqual(validated["action_confirmation"]["action_family"], "jump")
        self.assertEqual(validated["action_confirmation"]["confidence"], 1.0)
        self.assertEqual(validated["phase_segments"][1]["phase_code"], "takeoff")
        self.assertEqual(validated["phase_segments"][1]["observations"], ["起跳节奏清楚"])
        self.assertEqual(validated["key_moments"]["T_takeoff_sec"], 2.32)
        self.assertEqual(validated["quality_flags"], [])

    def test_normalize_accepts_json_string_and_alias_fields(self) -> None:
        raw = {
            "schema_version": "video_temporal_v1",
            "action_confirmation": {"action_family": "跳跃", "confirmed_action": "Axel", "confidence": "0.7"},
            "phase_segments": [
                {
                    "phase": "起跳",
                    "start_sec": "1.1",
                    "end_sec": "1.4",
                    "representative_sec": "1.2",
                    "confidence": "0.9",
                }
            ],
            "key_moments": {"T": "1.2"},
            "confidence": "0.7",
        }

        normalized = normalize_video_temporal_payload(json.dumps(raw, ensure_ascii=False), "qwen", "qwen3.6-plus")

        self.assertTrue(normalized["valid"])
        self.assertEqual(normalized["action_confirmation"]["action_family"], "jump")
        self.assertEqual(normalized["phase_segments"][0]["phase_code"], "takeoff")
        self.assertEqual(normalized["phase_segments"][0]["time_start"], 1.1)
        self.assertEqual(normalized["phase_segments"][0]["key_frame_hint"], 1.2)
        self.assertEqual(normalized["key_moments"]["T_takeoff_sec"], 1.2)

    def test_normalize_accepts_provider_phase_and_keyframe_aliases(self) -> None:
        raw = {
            "action_family": "jump",
            "confirmed_action": "Toe Loop",
            "phases": [
                {"phase": "takeoff", "start": "6.85", "end": "7.15", "timestamp": "6.95", "confidence": "0.8"},
                {"phase": "air", "start_time": "7.15", "end_time": "7.55", "keyframe_sec": "7.35", "confidence": "0.75"},
                {"phase": "landing", "start": "7.55", "end": "7.85", "time": "7.65", "confidence": "0.85"},
            ],
            "keyframes": {
                "takeoff": {"timestamp": "6.95"},
                "apex": {"timestamp": "7.35"},
                "landing": {"timestamp": "7.65"},
            },
            "confidence": 0.85,
            "fallback_recommendation": "use_video_timestamps",
        }

        normalized = normalize_video_temporal_payload(raw, "mimo", "mimo-v2.5")
        validated = validate_video_temporal_payload(normalized, duration_sec=9.568)

        self.assertTrue(validated["valid"])
        self.assertIn("video_temporal_phase_segments_alias_phases", validated["quality_flags"])
        self.assertEqual(validated["phase_segments"][0]["phase_code"], "takeoff")
        self.assertEqual(validated["phase_segments"][0]["time_start"], 6.85)
        self.assertEqual(validated["phase_segments"][0]["key_frame_hint"], 6.95)
        self.assertEqual(validated["key_moments"]["T_takeoff_sec"], 6.95)
        self.assertEqual(validated["key_moments"]["A_air_sec"], 7.35)
        self.assertEqual(validated["key_moments"]["L_landing_sec"], 7.65)

    def test_normalize_corrects_spiral_family_when_provider_reports_step(self) -> None:
        raw = {
            "schema_version": "video_temporal_v1",
            "action_confirmation": {
                "action_family": "step",
                "confirmed_action": "spiral",
                "confidence": 0.9,
            },
            "phase_segments": [
                {"phase_code": "spiral_entry", "time_start": 1.0, "time_end": 2.0, "key_frame_hint": 1.5, "confidence": 0.8},
                {"phase_code": "spiral_hold", "time_start": 2.0, "time_end": 4.0, "key_frame_hint": 3.0, "confidence": 0.85},
                {"phase_code": "spiral_exit", "time_start": 4.0, "time_end": 5.0, "key_frame_hint": 4.5, "confidence": 0.8},
            ],
            "confidence": 0.8,
            "fallback_recommendation": "use_video_timestamps",
        }

        normalized = normalize_video_temporal_payload(raw, "mimo", "mimo-v2.5")
        validated = validate_video_temporal_payload(normalized, duration_sec=6.0)

        self.assertEqual(validated["action_confirmation"]["action_family"], "spiral")
        self.assertTrue(validated["valid"])
        self.assertNotIn("video_temporal_phase_0_invalid_code", validated["quality_flags"])

    def test_normalize_recovers_json_from_markdown_fence(self) -> None:
        raw = f"```json\n{json.dumps(_valid_jump_payload(), ensure_ascii=False)}\n```"

        normalized = normalize_video_temporal_payload(raw, "mimo", "mimo-v2.5")

        self.assertTrue(normalized["valid"])
        self.assertEqual(normalized["provider"], "mimo")
        self.assertEqual(normalized["action_confirmation"]["action_family"], "jump")

    def test_normalize_recovers_json_with_surrounding_text(self) -> None:
        raw = f"模型说明：下面是结果\n{json.dumps(_valid_jump_payload(), ensure_ascii=False)}\n请查收"

        normalized = normalize_video_temporal_payload(raw, "qwen", "qwen3.6-plus")

        self.assertTrue(normalized["valid"])
        self.assertEqual(normalized["key_moments"]["L_landing_sec"], 2.94)

    def test_normalize_accepts_nested_content_text(self) -> None:
        raw = {"content": [{"type": "text", "text": json.dumps(_valid_jump_payload(), ensure_ascii=False)}]}

        normalized = normalize_video_temporal_payload(raw, "mimo", "mimo-v2.5")

        self.assertTrue(normalized["valid"])
        self.assertEqual(normalized["model"], "mimo-v2.5")

    def test_invalid_json_returns_diagnostic_payload(self) -> None:
        raw = "{bad json"
        normalized = normalize_video_temporal_payload(raw, provider="qwen", model="qwen3.6-plus")

        self.assertFalse(normalized["valid"])
        self.assertEqual(normalized["phase_segments"], [])
        self.assertIn("video_temporal_invalid_json", normalized["quality_flags"])
        self.assertEqual(normalized["fallback_recommendation"], "use_sampled_frames")
        self.assertEqual(normalized["raw_response_excerpt"], raw)
        self.assertEqual(normalized["raw_response_length"], len(raw))
        self.assertFalse(normalized["raw_response_truncated"])
        self.assertIsInstance(normalized["parse_error_detail"], str)

    def test_missing_required_fields_is_invalid_without_exception(self) -> None:
        normalized = normalize_video_temporal_payload(
            {"schema_version": "video_temporal_v1", "confidence": 0.9},
            provider="qwen",
            model="qwen3.6-plus",
        )
        validated = validate_video_temporal_payload(normalized, duration_sec=4.0)

        self.assertFalse(validated["valid"])
        self.assertIn("video_temporal_missing_phase_segments", validated["quality_flags"])
        self.assertEqual(validated["validation"]["errors"], ["video_temporal_missing_phase_segments"])
        self.assertIn("raw_response_excerpt", validated)
        self.assertIn("normalized payload missing phase_segments", validated["parse_error_detail"])

    def test_truncated_json_salvages_top_level_phase_segments(self) -> None:
        raw = (
            '{\n'
            '  "schema_version": "video_temporal_v1",\n'
            '  "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.75},\n'
            '  "phase_segments": [\n'
            '    {"phase_code": "approach", "time_start": 0.0, "time_end": 1.8, "key_frame_hint": 0.9, "confidence": 0.85},\n'
            '    {"phase_code": "takeoff", "time_start": 2.1, "time_end": 2.4, "key_frame_hint": 2.3, "confidence": 0.7},\n'
            '    {"phase_code": "air", "time_start": 2.4, "time_end": 2.8, "key_frame_hint": 2.6, "confidence": 0.65},\n'
            '    {"phase_code": "landing", "time_start": 2.8, "time_end": 3.1, "key_frame_hint": 2.9, "confidence": 0.7}\n'
            '  ],\n'
            '  "key_moments"'
        )

        normalized = normalize_video_temporal_payload(raw, "mimo", "mimo-v2.5")
        validated = validate_video_temporal_payload(normalized, duration_sec=4.6)

        self.assertGreaterEqual(len(validated["phase_segments"]), 3)
        self.assertIn("video_temporal_partial_json_salvaged", validated["quality_flags"])
        self.assertNotIn("video_temporal_missing_phase_segments", validated["quality_flags"])
        self.assertEqual(validated["phase_segments"][1]["phase_code"], "takeoff")
        self.assertIn("partial JSON salvaged", validated["parse_error_detail"])

    def test_time_out_of_bounds_marks_phase_invalid(self) -> None:
        payload = _valid_jump_payload()
        payload["phase_segments"] = [
            {
                "phase_code": "takeoff",
                "time_start": 3.8,
                "time_end": 4.8,
                "key_frame_hint": 4.2,
                "confidence": 0.9,
            }
        ]
        normalized = normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus")
        validated = validate_video_temporal_payload(normalized, duration_sec=4.0)

        self.assertFalse(validated["valid"])
        self.assertFalse(validated["phase_segments"][0]["valid"])
        self.assertIn("video_temporal_phase_0_invalid_time_range", validated["quality_flags"])

    def test_low_confidence_disables_video_timestamp_use(self) -> None:
        payload = _valid_jump_payload()
        payload["confidence"] = 0.42
        normalized = normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus")
        validated = validate_video_temporal_payload(normalized, duration_sec=5.0)

        self.assertFalse(validated["valid"])
        self.assertIn("video_temporal_low_confidence", validated["quality_flags"])
        self.assertEqual(validated["fallback_recommendation"], "use_sampled_frames")

    def test_phase_low_confidence_is_flagged_independently(self) -> None:
        payload = _valid_jump_payload()
        segments = list(payload["phase_segments"])  # type: ignore[index]
        segments[1] = dict(segments[1], confidence=0.59)
        payload["phase_segments"] = segments

        normalized = normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus")
        validated = validate_video_temporal_payload(normalized, duration_sec=5.0)

        self.assertTrue(validated["valid"])
        self.assertFalse(validated["phase_segments"][1]["valid"])
        self.assertIn("video_temporal_phase_1_low_confidence", validated["quality_flags"])

    def test_tal_out_of_order_degrades_with_warning(self) -> None:
        payload = _valid_jump_payload()
        payload["key_moments"] = {
            "T_takeoff_sec": 2.9,
            "A_air_sec": 2.6,
            "L_landing_sec": 2.4,
        }

        normalized = normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus")
        validated = validate_video_temporal_payload(normalized, duration_sec=5.0)

        self.assertTrue(validated["valid"])
        self.assertIn("video_temporal_tal_order_invalid", validated["quality_flags"])
        self.assertIn("video_temporal_T_takeoff_outside_takeoff_phase", validated["quality_flags"])
        self.assertIn("video_temporal_L_landing_outside_landing_phase", validated["quality_flags"])

    def test_invalid_phase_for_action_family_fails_validation(self) -> None:
        payload = _valid_jump_payload()
        payload["phase_segments"] = [
            {
                "phase_code": "spin_main",
                "time_start": 1.0,
                "time_end": 2.0,
                "key_frame_hint": 1.5,
                "confidence": 0.8,
            }
        ]

        normalized = normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus")
        validated = validate_video_temporal_payload(normalized, duration_sec=5.0)

        self.assertFalse(validated["valid"])
        self.assertIn("video_temporal_phase_0_invalid_code", validated["quality_flags"])


if __name__ == "__main__":
    unittest.main()
