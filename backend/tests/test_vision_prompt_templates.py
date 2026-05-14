from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.vision_prompt_templates import build_specialized_vision_prompt


class VisionPromptTemplateTests(unittest.TestCase):
    def test_specialized_prompt_contains_required_sections_and_schema(self) -> None:
        system_prompt, user_prompt = build_specialized_vision_prompt(
            action_type="jump",
            action_subtype="waltz jump",
            analysis_profile="jump",
            candidate_key_frames={
                "T": {"frame_id": "frame_0004", "confidence": 0.72},
                "A": {"frame_id": "frame_0006", "confidence": 0.81},
                "L": {"frame_id": "frame_0008", "confidence": 0.76},
            },
            motion_features={"scores": [0.1, 0.8, 0.2]},
            biomechanics={"jump_metrics": {"estimated_rotation_turns": 0.5}},
            profile_evidence={"jump_subtype_evidence": {"toe_pick_pulse": 0.2}},
        )

        self.assertIn("专业花样滑冰技术分析师", system_prompt)
        self.assertIn("必须只输出 JSON", system_prompt)
        self.assertIn("candidate_key_frames", user_prompt)
        self.assertIn("Free Skate 1", user_prompt)
        self.assertIn("不可判断", user_prompt)
        self.assertIn("JSON schema:", user_prompt)
        self.assertIn('"data_quality_hint": "good|partial|poor"', user_prompt)
        self.assertIn('"camera_view": "front|side|diagonal_front|diagonal_back|unknown"', user_prompt)
        self.assertIn('"frame_analysis"', user_prompt)
        self.assertIn('"key_frame_agreement"', user_prompt)
        self.assertIn('"overall_raw_text": "2-3句中文总结"', user_prompt)
        self.assertIn('"frame_id": "frame_0004"', user_prompt)
        self.assertIn('"estimated_rotation_turns": 0.5', user_prompt)

    def test_jump_profile_rule_requires_unknown_edge_and_low_element_confidence(self) -> None:
        _, user_prompt = build_specialized_vision_prompt(
            action_type="jump",
            action_subtype="flip",
            analysis_profile="jump",
        )

        self.assertIn('observations.blade_edge="不可判断"', user_prompt)
        self.assertIn("element_confidence<=0.55", user_prompt)
        self.assertIn('"element_confidence": 0.0', user_prompt)

    def test_prompt_builder_is_pure_and_database_independent(self) -> None:
        args = {
            "action_type": "spin",
            "action_subtype": None,
            "analysis_profile": "spin",
            "candidate_key_frames": None,
            "motion_features": [{"frame_id": "frame_0001", "motion_score": 0.3}],
            "biomechanics": {"analysis_profile": "spin"},
            "profile_evidence": None,
        }

        first = build_specialized_vision_prompt(**args)
        second = build_specialized_vision_prompt(**args)

        self.assertEqual(first, second)
        self.assertIn("action_subtype: 未指定", first[1])
        self.assertIn(json.dumps(args["motion_features"], ensure_ascii=False, indent=2, sort_keys=True), first[1])


if __name__ == "__main__":
    unittest.main()
