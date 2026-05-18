from __future__ import annotations

import sys
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


if __name__ == "__main__":
    unittest.main()
