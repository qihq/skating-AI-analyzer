from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Analysis
from app.services.analysis_corrections import (
    apply_analysis_correction,
    build_chat_share_text,
    create_analysis_correction,
    dismiss_analysis_correction,
    effective_payload_for_analysis,
    list_analysis_corrections,
)


def _analysis() -> Analysis:
    return Analysis(
        id=str(uuid4()),
        action_type="jump",
        action_subtype="Toe Loop",
        analysis_profile="jump",
        video_path="/tmp/source.mp4",
        status="completed",
        note="comments: looks like Salchow",
        force_score=74,
        report={
            "summary": "Original report",
            "issues": [],
            "improvements": [],
            "training_focus": "landing",
            "action_confirmation": {"confirmed_action": "Toe Loop", "confidence": 0.55},
        },
        bio_data={"key_frames": {"T": "frame_001", "A": "frame_002", "L": "frame_003"}},
        frame_motion_scores={
            "video_temporal": {"action_confirmation": {"confirmed_action": "Toe Loop"}},
            "resolved_keyframes": {
                "selected": [{"frame_id": "semantic_001", "phase_code": "T"}],
                "partial_selected": [{"frame_id": "partial_001", "phase_code": "T"}],
            },
        },
        vision_structured={"frame_analysis": []},
    )


class AnalysisCorrectionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_create_apply_and_effective_overlay(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            correction = await create_analysis_correction(
                session,
                analysis,
                kind="action_label",
                payload={
                    "action_subtype": "Salchow",
                    "action_confirmation": {"confirmed_action": "Salchow", "confidence": 0.9},
                },
                rationale="Manual review",
            )
            await apply_analysis_correction(session, analysis, correction.id)

            effective = await effective_payload_for_analysis(session, analysis)
            self.assertTrue(effective["has_applied_corrections"])
            self.assertEqual(effective["analysis"]["action_subtype"], "Salchow")
            self.assertEqual(effective["report"]["action_confirmation"]["confirmed_action"], "Salchow")

    async def test_keyframe_dismissed_correction_is_not_effective(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            correction = await create_analysis_correction(
                session,
                analysis,
                kind="keyframes",
                payload={"key_frames": {"T": "partial_001"}},
                rationale="Use partial candidate",
            )
            await dismiss_analysis_correction(session, analysis, correction.id)

            effective = await effective_payload_for_analysis(session, analysis)
            self.assertFalse(effective["has_applied_corrections"])
            self.assertEqual(effective["bio_data"]["key_frames"]["T"], "frame_001")

    async def test_share_text_includes_applied_and_pending_corrections(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            applied = await create_analysis_correction(
                session,
                analysis,
                kind="action_label",
                payload={"action_subtype": "Salchow"},
                rationale="Manual review",
            )
            await apply_analysis_correction(session, analysis, applied.id)
            await create_analysis_correction(
                session,
                analysis,
                kind="keyframes",
                payload={"key_frames": {"T": "partial_001"}},
                rationale="Use partial candidate",
            )
            corrections = await list_analysis_corrections(session, analysis.id)

            text = build_chat_share_text(analysis, [], corrections, skater_name="Tantan")
            self.assertIn("已应用修正", text)
            self.assertIn("待确认修正", text)
            self.assertIn("Salchow", text)
            self.assertIn("partial_001", text)


if __name__ == "__main__":
    unittest.main()
