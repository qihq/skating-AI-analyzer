from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.analysis import _sync_report_user_note
from app.services.report import normalize_report


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


if __name__ == "__main__":
    unittest.main()
