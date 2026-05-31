from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video_temporal import build_video_temporal_prompts


class VideoTemporalPromptTests(unittest.TestCase):
    def test_prompt_contains_required_temporal_contract_terms(self) -> None:
        system_prompt, user_prompt = build_video_temporal_prompts(
            action_type="jump",
            action_subtype="Axel",
            video_duration_sec=4.25,
            source_fps=30.0,
        )
        combined = f"{system_prompt}\n{user_prompt}"

        self.assertIn("video_temporal_v1", combined)
        self.assertIn("qwen3.6-plus", combined)
        self.assertNotIn("qwen-vl-max-latest", combined)
        self.assertIn("只输出一个合法 JSON 对象", combined)
        self.assertIn("只输出 JSON", combined)
        self.assertIn("所有时间戳单位为秒", combined)
        self.assertIn("5-8 岁儿童", combined)
        self.assertIn("儿童训练标准", combined)
        self.assertIn("Lutz, Flip, Loop, Salchow, Toe Loop, Axel", combined)
        self.assertIn("旋转、步法、螺旋线", combined)
        self.assertIn("time_start", combined)
        self.assertIn("time_end", combined)
        self.assertIn("key_frame_hint", combined)
        self.assertIn("T_takeoff_sec", combined)
        self.assertIn("A_air_sec", combined)
        self.assertIn("L_landing_sec", combined)
        self.assertNotIn("0.5-1 秒误差", combined)
        self.assertIn("最后一只脚离冰", combined)
        self.assertIn("身体重心达到最高点", combined)
        self.assertIn("冰刀首次接触冰面", combined)

    def test_prompt_tells_model_to_ignore_occluders_for_tal(self) -> None:
        system_prompt, user_prompt = build_video_temporal_prompts(
            action_type="jump",
            action_subtype="Axel",
            video_duration_sec=9.6,
            source_fps=30.0,
        )
        combined = f"{system_prompt}\n{user_prompt}"

        self.assertIn("主滑行者", combined)
        self.assertIn("忽略旁人", combined)
        self.assertIn("前景遮挡", combined)
        self.assertIn("第一次触冰", combined)
        self.assertIn("不是落冰后滑出", combined)

    def test_deprecated_model_argument_is_normalized_in_prompt(self) -> None:
        _, user_prompt = build_video_temporal_prompts(
            action_type="jump",
            action_subtype=None,
            video_duration_sec=3.0,
            source_fps=24.0,
            model="qwen-vl-max-latest",
        )

        self.assertIn("- model: qwen3.6-plus", user_prompt)
        self.assertNotIn("- model: qwen-vl-max-latest", user_prompt)

    def test_retry_context_is_included_when_quality_gate_retries(self) -> None:
        _, user_prompt = build_video_temporal_prompts(
            action_type="jump",
            action_subtype=None,
            video_duration_sec=4.6,
            source_fps=15.0,
            retry_context={
                "retry_reason_flags": ["video_temporal_resolver_coherent_tal_motion_conflict_rejected"],
                "rejected_key_moments": {"T_takeoff_sec": 6.12, "A_air_sec": 6.45, "L_landing_sec": 6.72},
                "top_motion_records": [{"timestamp": 7.775, "motion_score": 0.2166}],
            },
        )

        self.assertIn("QUALITY_GATE_RETRY_CONTEXT", user_prompt)
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", user_prompt)
        self.assertIn("rejected_key_moments", user_prompt)
        self.assertIn("7.775", user_prompt)
        self.assertIn("full-frame signals", user_prompt)
        self.assertIn("do not move T/A/L solely", user_prompt)
        self.assertIn("glide_out", user_prompt)

    def test_large_retry_context_remains_valid_json_and_keeps_core_fields(self) -> None:
        _, user_prompt = build_video_temporal_prompts(
            action_type="jump",
            action_subtype=None,
            video_duration_sec=4.6,
            source_fps=15.0,
            retry_context={
                "retry_reason_flags": ["video_temporal_resolver_coherent_tal_motion_conflict_rejected"],
                "retry_instruction_hints": [
                    "Top motion records are full-frame motion signals; verify target motion.",
                    "Keep previous T/A/L when visible evidence supports them.",
                    "Extra hint that should survive unless heavily compressed.",
                ],
                "rejected_key_moments": {"T_takeoff_sec": 6.8, "A_air_sec": 7.1, "L_landing_sec": 7.35},
                "rejected_selected_frames": [
                    {
                        "phase_code": f"phase_{index}",
                        "timestamp": 6.0 + index * 0.1,
                        "key_moment": "T_takeoff_sec" if index == 0 else None,
                        "selection_reason": "video_phase_range_key_moment",
                        "phase_time_start": 5.9 + index * 0.1,
                        "phase_time_end": 6.1 + index * 0.1,
                    }
                    for index in range(12)
                ],
                "video_quality_flags": [f"video_flag_{index}" for index in range(20)],
                "resolver_quality_flags": [f"resolver_flag_{index}" for index in range(20)],
                "rejected_source": "skeleton_fallback",
                "action_window": {"start_sec": 4.65, "end_sec": 9.25},
                "top_motion_records": [
                    {
                        "timestamp": 7.65 + index * 0.063,
                        "motion_score": 0.25 - index * 0.01,
                        "frame_id": f"frame_{index:04d}",
                        "relation_to_rejected_tal": "after_rejected_landing",
                    }
                    for index in range(20)
                ],
            },
        )

        marker = "only.\n"
        start = user_prompt.index(marker) + len(marker)
        end = user_prompt.index("\n", start)
        retry_payload = json.loads(user_prompt[start:end])

        self.assertIn("retry_reason_flags", retry_payload)
        self.assertEqual(retry_payload["rejected_key_moments"]["T_takeoff_sec"], 6.8)
        self.assertEqual(retry_payload["action_window"]["start_sec"], 4.65)
        self.assertLessEqual(len(json.dumps(retry_payload, ensure_ascii=False, separators=(",", ":"))), 1800)
        self.assertTrue(retry_payload["top_motion_records"])
        self.assertIn("relation", retry_payload["top_motion_records"][0])


if __name__ == "__main__":
    unittest.main()
