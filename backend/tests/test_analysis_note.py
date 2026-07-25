from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.analysis import _sync_report_user_note
from app.services.llm_context import split_user_note_questions
from app.services.report import _answer_single_user_note_question, normalize_report


class AnalysisNoteTests(unittest.TestCase):
    def test_normalize_report_preserves_user_note_metadata(self) -> None:
        report = normalize_report(
            {
                "summary": "ok",
                "issues": [],
                "improvements": [],
                "training_focus": "focus",
                "subscores": {},
                "data_quality": "good",
                "user_note": "landing felt tight",
                "user_note_response": "家长备注提到 landing felt tight，建议复核落冰。",
                "action_confirmation": {"confirmed_action": "Toe Loop", "confidence": 0.75},
            }
        )

        self.assertEqual(report["user_note"], "landing felt tight")
        self.assertEqual(report["user_note_response"], "家长备注提到 landing felt tight，建议复核落冰。")
        self.assertEqual(report["action_confirmation"]["confirmed_action"], "Toe Loop")

    def test_sync_report_user_note_adds_updates_and_clears_note(self) -> None:
        report = {
            "summary": "ok",
            "issues": [],
            "improvements": [],
            "training_focus": "focus",
            "subscores": {},
            "data_quality": "partial",
        }

        updated = _sync_report_user_note(report, "  new note  ")
        assert updated is not None
        self.assertEqual(updated["user_note"], "new note")

        cleared = _sync_report_user_note(updated, " ")
        assert cleared is not None
        self.assertNotIn("user_note", cleared)

    def test_split_user_note_questions_extracts_multiple_questions(self) -> None:
        questions = split_user_note_questions("这个具体是哪个动作？落冰为什么不稳？能不能给训练重点")

        self.assertEqual(questions, ["这个具体是哪个动作", "落冰为什么不稳", "能不能给训练重点"])

    def test_note_questions_get_specific_answers_without_confirmation_template(self) -> None:
        report = {
            "issues": [{"category": "起跳", "phase": "起跳", "description": "蹬冰结束偏早，离地前力量没有完整传递"}],
            "subscores": {"takeoff_power": 58, "arm_coordination": 74, "core_stability": 70},
        }

        symmetry = _answer_single_user_note_question("手对称了吗", report, "jump")
        power = _answer_single_user_note_question("小朋友哪里用力不够", report, "jump")

        self.assertIn("左右手对比", symmetry)
        self.assertIn("蹬冰结束偏早", power)
        self.assertNotIn("能确认的是", symmetry + power)
        self.assertNotIn("不能确认的是", symmetry + power)


if __name__ == "__main__":
    unittest.main()
