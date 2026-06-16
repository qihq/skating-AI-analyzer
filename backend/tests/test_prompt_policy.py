from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.llm_context import AnalysisPromptContext, render_prompt_context
from app.services.memory_suggest import MEMORY_SUGGEST_SYSTEM_PROMPT


class PromptPolicyTests(unittest.TestCase):
    def test_render_prompt_context_includes_uncertainty_and_note_policy(self) -> None:
        context = AnalysisPromptContext(
            action_type="跳跃",
            action_subtype=None,
            skill_category=None,
            analysis_profile="jump",
            profile_evidence={"source": "test"},
            motion_features={"sample_count": 12},
            bio_data={"quality_flags": []},
            user_note="我只知道是跳跃，不确定具体名字。",
            memory_context="长期目标：落冰更稳。",
        )

        rendered = render_prompt_context(context, include_bio=True)

        self.assertIn("action_subtype: 未指定", rendered)
        self.assertIn("用户不确定细项", rendered)
        self.assertIn("不能强行猜成具体动作名", rendered)
        self.assertIn("上传备注/comments 是用户观察线索", rendered)
        self.assertIn("不等同于已验证事实", rendered)
        self.assertIn("bio_data", rendered)
        self.assertIn("长期目标：落冰更稳", rendered)

    def test_memory_suggestion_prompt_is_conservative(self) -> None:
        self.assertIn("稳定偏好", MEMORY_SUGGEST_SYSTEM_PROMPT)
        self.assertIn("反复出现的卡点", MEMORY_SUGGEST_SYSTEM_PROMPT)
        self.assertIn("不要因为单次表现波动", MEMORY_SUGGEST_SYSTEM_PROMPT)
        self.assertIn("用户备注可以作为线索", MEMORY_SUGGEST_SYSTEM_PROMPT)
        self.assertIn("不能单独作为事实", MEMORY_SUGGEST_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
