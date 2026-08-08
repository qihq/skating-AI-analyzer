from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.models import Analysis, AnalysisCorrection
from app.routers.analysis import (
    _auto_apply_video_ai_action_if_confident,
    _build_export_text,
    _video_ai_auto_action_payload,
    regenerate_report_from_corrections,
)
from app.services import analysis_corrections as corrections_service
from app.services.analysis_corrections import (
    apply_analysis_correction,
    build_chat_share_image_payload,
    build_chat_share_title,
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

    async def test_v2_applied_correction_revises_facts_without_mutating_legacy_columns(self) -> None:
        from app.analysis_v2.fact_consumers import persist_analysis_facts
        from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2

        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.flush()
            fact = AnalysisFactV2(
                analysis_id=analysis.id,
                event_id=f"{analysis.id}:event:0",
                claim_type="action_profile",
                value="jump",
                authority="v2",
                source_pipeline_fingerprint="v2:test",
                definition_version="profile.v2",
                permissions={"family_display": True, "correction": True},
            )
            facts = AnalysisFactsV2(analysis_id=analysis.id, authority="v2", facts=(fact,))
            persist_analysis_facts(analysis, facts)
            await session.commit()
            original_hash = analysis.source_fact_hash
            original_legacy_subtype = analysis.action_subtype
            original_legacy_frames = analysis.bio_data

            correction = await create_analysis_correction(
                session,
                analysis,
                kind="action_label",
                payload={"action_subtype": "Salchow"},
                status="applied",
            )
            await session.refresh(analysis)
            self.assertEqual(analysis.facts_authority, "v2")
            self.assertEqual(analysis.source_fact_revision, 2)
            self.assertNotEqual(analysis.source_fact_hash, original_hash)
            self.assertEqual(analysis.action_subtype, original_legacy_subtype)
            self.assertEqual(analysis.bio_data, original_legacy_frames)
            self.assertTrue(correction.invalidated_artifacts)

    async def test_v2_report_regeneration_uses_persisted_claims_only(self) -> None:
        from unittest.mock import AsyncMock, patch

        from app.analysis_v2.fact_consumers import persist_analysis_facts
        from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2

        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.flush()
            profile = AnalysisFactV2(
                analysis_id=analysis.id,
                event_id=f"{analysis.id}:event:0",
                claim_type="action_profile",
                value="jump",
                authority="v2",
                source_pipeline_fingerprint="v2:test",
                definition_version="profile.v2",
                sources=("deterministic",),
                source_fingerprints={"deterministic": "fp"},
                permissions={"family_display": True, "correction": True},
            )
            unsupported = AnalysisFactV2(
                analysis_id=analysis.id,
                event_id=f"{analysis.id}:event:0",
                claim_type="rotation",
                value=None,
                authority="v2",
                source_pipeline_fingerprint="v2:test",
                definition_version="rotation.v2",
                status="unobservable",
                observability="unobservable",
                sources=("deterministic",),
                source_fingerprints={"deterministic": "fp"},
            )
            facts = AnalysisFactsV2(analysis_id=analysis.id, authority="v2", facts=(profile, unsupported))
            persist_analysis_facts(analysis, facts)
            await session.commit()

            generated = {
                "summary": "Claim-only regenerated report",
                "issues": [],
                "improvements": [],
                "training_focus": "review landing",
                "subscores": {},
                "data_quality": "partial",
            }
            with patch("app.routers.analysis.generate_report", new=AsyncMock(return_value=generated)) as generate:
                response = await regenerate_report_from_corrections(analysis.id, session)

            kwargs = generate.await_args.kwargs
            claims = kwargs["fused_claims"]
            self.assertEqual(len(claims), 2)
            self.assertEqual(generate.await_args.args[1], {})
            self.assertEqual(generate.await_args.args[2], {})
            self.assertEqual(response.effective["authority"], "v2")
            self.assertEqual(response.correction.kind, "report_regeneration")
            self.assertEqual(response.correction.facts_authority, "v2")
            self.assertEqual(response.effective["source_fact_hash"], analysis.source_fact_hash)

    async def test_v2_share_and_export_use_same_authority_facts(self) -> None:
        from app.analysis_v2.fact_consumers import persist_analysis_facts
        from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, FactPermission

        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.flush()
            permissions = FactPermission(
                family_display=True,
                share=True,
                export=True,
                coaching=True,
            )
            facts = AnalysisFactsV2(
                analysis_id=analysis.id,
                authority="v2",
                facts=(
                    AnalysisFactV2(
                        analysis_id=analysis.id,
                        event_id=f"{analysis.id}:event:0",
                        claim_type="action_label",
                        value="V2 Spin",
                        authority="v2",
                        source_pipeline_fingerprint="v2:share-test",
                        definition_version="action-label.v2",
                        permissions=permissions,
                    ),
                    AnalysisFactV2(
                        analysis_id=analysis.id,
                        event_id=f"{analysis.id}:event:0",
                        claim_type="report_summary",
                        value="V2 summary only",
                        authority="v2",
                        source_pipeline_fingerprint="v2:share-test",
                        definition_version="report-summary.v2",
                        permissions=permissions,
                    ),
                    AnalysisFactV2(
                        analysis_id=analysis.id,
                        event_id=f"{analysis.id}:event:0",
                        claim_type="force_score",
                        value=91,
                        authority="v2",
                        source_pipeline_fingerprint="v2:share-test",
                        definition_version="force-score.v2",
                        permissions=permissions,
                    ),
                ),
            )
            persist_analysis_facts(analysis, facts)
            await session.commit()

            title = build_chat_share_title(analysis, skater_name="Mia")
            text = build_chat_share_text(analysis, [], [], skater_name="Mia")
            image = build_chat_share_image_payload(analysis, [], [], skater_name="Mia")
            export = _build_export_text(analysis, "Mia", "2026-08-08")

            self.assertEqual(title, "Mia · V2 Spin")
            self.assertIn("V2 summary only", text)
            self.assertNotIn("Original report", text)
            self.assertEqual(image["score"], 91)
            self.assertEqual(image["facts_authority"], "v2")
            self.assertEqual(image["source_pipeline_fingerprint"], "v2:share-test")
            self.assertIn("Mia · V2 Spin · 2026-08-08", export)
            self.assertIn("91分", export)
            self.assertNotIn("Toe Loop", export)

    async def test_v2_share_and_export_do_not_backfill_missing_facts_from_legacy(self) -> None:
        from app.analysis_v2.fact_consumers import persist_analysis_facts
        from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2, FactPermission

        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.flush()
            facts = AnalysisFactsV2(
                analysis_id=analysis.id,
                authority="v2",
                facts=(AnalysisFactV2(
                    analysis_id=analysis.id,
                    event_id=f"{analysis.id}:event:0",
                    claim_type="action_profile",
                    value="jump",
                    authority="v2",
                    source_pipeline_fingerprint="v2:missing-test",
                    definition_version="profile.v2",
                    permissions=FactPermission(family_display=True, share=True, export=True),
                ),),
            )
            persist_analysis_facts(analysis, facts)
            await session.commit()

            text = build_chat_share_text(analysis, [], [], skater_name="Mia")
            image = build_chat_share_image_payload(analysis, [], [], skater_name="Mia")
            export = _build_export_text(analysis, "Mia", "2026-08-08")

            self.assertNotIn("Original report", text)
            self.assertIn("摘要暂不可用", text)
            self.assertIsNone(image["score"])
            self.assertIn("综合评分：--分", export)
            self.assertNotIn("74分", export)


    async def test_apply_action_correction_persists_analysis_and_list_cache(self) -> None:
        from app.database import _apply_patch_i

        async with self.engine.begin() as conn:
            await _apply_patch_i(conn)

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

            await session.refresh(analysis)
            self.assertEqual(analysis.action_subtype, "Salchow")
            self.assertEqual(analysis.report["action_confirmation"]["confirmed_action"], "Salchow")

            row = (
                await session.execute(
                    text("SELECT action_subtype FROM analysis_list_items WHERE analysis_id = :analysis_id"),
                    {"analysis_id": analysis.id},
                )
            ).one()
            self.assertEqual(row.action_subtype, "Salchow")

    async def test_create_applied_action_correction_persists_immediately(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            await create_analysis_correction(
                session,
                analysis,
                kind="action_label",
                status="applied",
                payload={
                    "action_subtype": "Loop",
                    "action_confirmation": {"confirmed_action": "Loop", "confidence": 0.91},
                },
                rationale="Auto apply",
            )

            await session.refresh(analysis)
            self.assertEqual(analysis.action_subtype, "Loop")
            self.assertEqual(analysis.report["action_confirmation"]["confirmed_action"], "Loop")

    async def test_apply_keyframe_correction_persists_analysis_evidence(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            correction = await create_analysis_correction(
                session,
                analysis,
                kind="keyframes",
                payload={
                    "key_frames": {
                        "T": {"frame_id": "semantic_010", "timestamp": 1.2, "phase_code": "takeoff"},
                        "A": "frame_011",
                    },
                    "source": "manual_ui",
                },
                rationale="Manual keyframe review",
            )

            await apply_analysis_correction(session, analysis, correction.id)

            await session.refresh(analysis)
            self.assertEqual(analysis.bio_data["key_frames"]["T"], "semantic_010")
            self.assertEqual(analysis.bio_data["key_frames"]["A"], "frame_011")
            self.assertEqual(analysis.bio_data["corrected_key_frames"]["T"]["timestamp"], 1.2)
            self.assertTrue(analysis.frame_motion_scores["resolved_keyframes"]["corrected"])
            self.assertEqual(analysis.frame_motion_scores["resolved_keyframes"]["source"], "manual_ui")

    async def test_backfill_persists_legacy_applied_keyframe_correction(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()
            session.add(
                AnalysisCorrection(
                    id=str(uuid4()),
                    analysis_id=analysis.id,
                    kind="keyframes",
                    payload={"key_frames": {"L": "frame_099"}, "source": "legacy_manual"},
                    rationale="Legacy applied correction",
                    source="manual",
                    status="applied",
                    original_snapshot={},
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    applied_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

            backfill = getattr(corrections_service, "backfill_applied_analysis_corrections", None)
            self.assertIsNotNone(backfill)
            await backfill(session)

            await session.refresh(analysis)
            self.assertEqual(analysis.bio_data["key_frames"]["L"], "frame_099")
            self.assertEqual(analysis.frame_motion_scores["resolved_keyframes"]["source"], "legacy_manual")

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

    async def test_keyframe_payload_preserves_video_ai_diagnostics(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            correction = await create_analysis_correction(
                session,
                analysis,
                kind="keyframes",
                source="video_ai_keyframe_rerun",
                payload={
                    "key_frames": {"T": {"frame_id": "semantic_video_ai_rerun_0001", "timestamp": 1.2}},
                    "selected_semantic_frames": [{"frame_id": "semantic_video_ai_rerun_0001", "phase_code": "takeoff"}],
                    "source": "video_ai_full_video_keyframe_rerun",
                    "diagnostics": {"video_ai_confidence": 0.82, "conflicts": []},
                },
                rationale="Video AI rerun",
            )

            self.assertEqual(correction.source, "video_ai_keyframe_rerun")
            self.assertEqual(correction.payload["diagnostics"]["video_ai_confidence"], 0.82)
            self.assertEqual(correction.payload["source"], "video_ai_full_video_keyframe_rerun")

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

    async def test_chat_share_payload_preserves_full_summary_question_and_answer(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            long_summary = "总结" * 180
            analysis.report = {**analysis.report, "summary": long_summary}
            session.add(analysis)
            await session.commit()

            class _Message:
                def __init__(self, role: str, content: str) -> None:
                    self.role = role
                    self.content = content

            long_question = "重新解释这个关键帧为什么这样选。" * 40
            long_answer = "这里需要完整说明证据链和不确定性。" * 60
            payload = build_chat_share_image_payload(
                analysis,
                [_Message("user", long_question), _Message("assistant", long_answer)],
                [],
            )
            text = build_chat_share_text(
                analysis,
                [_Message("user", long_question), _Message("assistant", long_answer)],
                [],
            )

            self.assertEqual(payload["summary"], long_summary)
            self.assertEqual(payload["question"], long_question)
            self.assertEqual(payload["answer"], long_answer)
            self.assertEqual(len(payload["timeline_items"]), 1)
            self.assertEqual(payload["timeline_items"][0]["question"], long_question)
            self.assertEqual(payload["timeline_items"][0]["answer"], long_answer)
            self.assertIn(long_question, text)
            self.assertIn(long_answer, text)

    async def test_low_confidence_video_ai_action_creates_pending_correction(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            analysis.action_type = "自由滑"
            analysis.action_subtype = "节目片段"
            analysis.analysis_profile = None
            session.add(analysis)
            await session.commit()

            await _auto_apply_video_ai_action_if_confident(
                session,
                analysis,
                video_temporal={
                    "confidence": 0.7,
                    "action_confirmation": {"action_family": "spin", "confirmed_action": "直立旋转", "confidence": 0.7},
                },
                analysis_profile=None,
            )

            corrections = await list_analysis_corrections(session, analysis.id)
            self.assertEqual(len(corrections), 1)
            self.assertEqual(corrections[0].source, "video_ai_auto")
            self.assertEqual(corrections[0].status, "proposed")
            self.assertEqual(corrections[0].payload["analysis_profile"], "spin")
            self.assertEqual(analysis.action_type, "自由滑")

    async def test_high_confidence_video_ai_action_applies_correction(self) -> None:
        async with self.Session() as session:
            analysis = _analysis()
            analysis.action_type = "自由滑"
            analysis.action_subtype = "节目片段"
            analysis.analysis_profile = None
            session.add(analysis)
            await session.commit()

            await _auto_apply_video_ai_action_if_confident(
                session,
                analysis,
                video_temporal={
                    "confidence": 0.9,
                    "action_confirmation": {"action_family": "spin", "confirmed_action": "直立旋转", "confidence": 0.9},
                },
                analysis_profile=None,
            )

            corrections = await list_analysis_corrections(session, analysis.id)
            self.assertEqual(len(corrections), 1)
            self.assertEqual(corrections[0].status, "applied")
            self.assertEqual(analysis.action_type, "旋转")
            self.assertEqual(analysis.action_subtype, "直立旋转")
            self.assertEqual(analysis.analysis_profile, "spin")


class VideoAiAutoActionPayloadTests(unittest.TestCase):
    def test_high_confidence_spin_payload_auto_applies_neutral_input(self) -> None:
        payload = _video_ai_auto_action_payload(
            current_action_type="自由滑",
            current_action_subtype="节目片段",
            analysis_profile=None,
            video_temporal={
                "confidence": 0.9,
                "action_confirmation": {
                    "action_family": "spin",
                    "confirmed_action": "直立旋转",
                    "confidence": 0.88,
                },
            },
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["action_type"], "旋转")
        self.assertEqual(payload["action_subtype"], "直立旋转")
        self.assertEqual(payload["analysis_profile"], "spin")
        self.assertTrue(payload["action_confirmation"]["auto_applied"])

    def test_low_confidence_video_ai_payload_is_not_auto_applied(self) -> None:
        payload = _video_ai_auto_action_payload(
            current_action_type="自由滑",
            current_action_subtype="节目片段",
            analysis_profile=None,
            video_temporal={
                "confidence": 0.6,
                "action_confirmation": {"action_family": "spin", "confirmed_action": "直立旋转", "confidence": 0.6},
            },
        )

        self.assertIsNone(payload)

    def test_strong_existing_action_conflict_is_not_auto_applied(self) -> None:
        payload = _video_ai_auto_action_payload(
            current_action_type="跳跃",
            current_action_subtype="单跳",
            analysis_profile=None,
            video_temporal={
                "confidence": 0.92,
                "action_confirmation": {"action_family": "spin", "confirmed_action": "直立旋转", "confidence": 0.92},
            },
        )

        self.assertIsNone(payload)

    def test_final_profile_match_allows_auto_apply_from_old_label(self) -> None:
        payload = _video_ai_auto_action_payload(
            current_action_type="跳跃",
            current_action_subtype="单跳",
            analysis_profile="spin",
            video_temporal={
                "confidence": 0.92,
                "action_confirmation": {"action_family": "spin", "confirmed_action": "直立旋转", "confidence": 0.92},
            },
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["action_type"], "旋转")
        self.assertEqual(payload["analysis_profile"], "spin")


if __name__ == "__main__":
    unittest.main()
