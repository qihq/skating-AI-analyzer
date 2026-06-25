from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Analysis
from app.services.analysis_chat import (
    AnalysisChatError,
    build_analysis_chat_context,
    create_analysis_chat_reply,
    list_analysis_chat_messages,
    render_analysis_chat_context,
)
from app.services.analysis_corrections import list_analysis_corrections


def _provider(
    *,
    id: str = "report-provider",
    slot: str = "report",
    name: str = "report-provider",
    model_id: str = "test-report-model",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        slot=slot,
        name=name,
        provider="openai_compatible",
        base_url="https://example.com/v1",
        model_id=model_id,
        vision_model=None,
        api_key="test-key",
        notes=None,
    )


def _analysis() -> Analysis:
    return Analysis(
        id=str(uuid4()),
        action_type="jump",
        action_subtype="Toe Loop",
        analysis_profile="jump",
        video_path="/tmp/source.mp4",
        status="completed",
        note="comments: 我觉得像 Salchow，落冰飘。",
        force_score=76,
        report={
            "summary": "整体完成，但落冰控制不足。",
            "issues": [{"category": "落冰", "description": "落冰后重心外飘", "severity": "medium"}],
            "improvements": [{"target": "落冰", "action": "保持软膝滑出。"}],
            "training_focus": "落冰稳定",
            "user_note": "comments: 我觉得像 Salchow，落冰飘。",
            "user_note_response": "备注已作为线索，落冰问题有证据支持。",
            "action_confirmation": {"confirmed_action": "Toe Loop", "confidence": 0.62},
        },
        vision_structured={
            "action_phase_summary": {"takeoff": "outside edge"},
            "frame_analysis": [{"frame_id": "frame_0001", "phase": "takeoff"}],
        },
        frame_motion_scores={
            "video_temporal": {
                "action_confirmation": {"confirmed_action": "Toe Loop", "confidence": 0.62},
                "confidence": 0.62,
                "provider": "qwen",
                "model": "video-model",
            },
            "resolved_keyframes": {
                "selected": [{"frame_id": "semantic_0001", "phase_code": "T"}],
                "partial_selected": [
                    {
                        "frame_id": "partial_semantic_0001",
                        "phase_code": "T",
                        "selection_reason": "partial_semantic_candidate",
                    }
                ],
                "confidence": 0.71,
                "quality_flags": ["semantic_keyframes_post_vision_partial_phase_frames_available"],
            },
        },
        cross_validation={
            "recommended_path": "B",
            "conflict_level": "medium",
            "path_b_evidence": {"jump_type": "Salchow candidate"},
        },
        bio_data={"key_frames": {"T": "frame_0001"}, "bio_subscores": {"landing_absorption": 62}},
    )


class AnalysisChatServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_context_includes_comments_action_confirmation_and_partial_candidates(self) -> None:
        context = build_analysis_chat_context(_analysis())
        rendered = render_analysis_chat_context(context)

        self.assertIn("comments: 我觉得像 Salchow", rendered)
        self.assertIn("user_note_response", rendered)
        self.assertIn("Toe Loop", rendered)
        self.assertIn("partial_semantic_0001", rendered)
        self.assertIn("partial_semantic_candidate", rendered)
        self.assertIn("Salchow candidate", rendered)

    async def test_create_reply_persists_user_and_assistant_messages(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        completion = AsyncMock(return_value="这次 Toe Loop 置信度不高，partial candidates 支持复核。")
        async with Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            with (
                patch("app.services.analysis_chat.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.analysis_chat.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.analysis_chat.request_text_completion", completion),
            ):
                assistant_message, messages = await create_analysis_chat_reply(session, analysis, message="动作是不是识别错了？")

            self.assertEqual(assistant_message.role, "assistant")
            self.assertEqual(len(messages), 2)
            self.assertEqual(assistant_message.context_snapshot["provider"]["id"], "report-provider")
            self.assertEqual(assistant_message.context_snapshot["provider"]["model_id"], "test-report-model")
            stored = await list_analysis_chat_messages(session, analysis.id)
            self.assertEqual([item.role for item in stored], ["user", "assistant"])

        kwargs = completion.await_args.kwargs
        prompt_text = "\n".join(item["content"] for item in kwargs["messages"])
        self.assertIn("partial_semantic_0001", prompt_text)
        self.assertIn("comments: 我觉得像 Salchow", prompt_text)
        await engine.dispose()

    async def test_create_reply_can_use_selected_report_provider(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        selected_provider = _provider(id="selected-report", name="second report", model_id="second-model")
        completion = AsyncMock(return_value="使用指定模型回复。")
        get_by_id = AsyncMock(return_value=selected_provider)
        async with Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            with (
                patch("app.services.analysis_chat.get_provider_config_by_id", get_by_id),
                patch("app.services.analysis_chat.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.analysis_chat.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.analysis_chat.request_text_completion", completion),
            ):
                assistant_message, _messages = await create_analysis_chat_reply(
                    session,
                    analysis,
                    message="换一个模型回答",
                    provider_id="selected-report",
                )

            get_by_id.assert_awaited_once()
            self.assertEqual(completion.await_args.args[0].id, "selected-report")
            self.assertEqual(assistant_message.context_snapshot["provider"]["model_id"], "second-model")

        await engine.dispose()

    async def test_model_identity_question_uses_actual_provider_without_completion(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        provider = _provider(
            id="mimo-report",
            name="MiMo V2.5 Pro",
            model_id="mimo-v2.5-pro",
        )
        completion = AsyncMock(return_value="我是 Claude。")
        async with Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            with (
                patch("app.services.analysis_chat.get_active_provider", AsyncMock(return_value=provider)),
                patch("app.services.analysis_chat.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.analysis_chat.request_text_completion", completion),
            ):
                assistant_message, messages = await create_analysis_chat_reply(
                    session,
                    analysis,
                    message="你现在是哪个模型？",
                )

            completion.assert_not_awaited()
            self.assertIn("MiMo V2.5 Pro", assistant_message.content)
            self.assertIn("mimo-v2.5-pro", assistant_message.content)
            self.assertNotIn("Claude", assistant_message.content)
            self.assertEqual(assistant_message.context_snapshot["provider"]["id"], "mimo-report")
            self.assertEqual(assistant_message.context_snapshot["request_model"]["model_id"], "mimo-v2.5-pro")
            self.assertEqual([item.role for item in messages], ["user", "assistant"])

        await engine.dispose()

    async def test_selected_provider_must_be_report_slot(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            with (
                patch("app.services.analysis_chat.get_provider_config_by_id", AsyncMock(side_effect=ValueError("wrong slot"))),
                patch("app.services.analysis_chat.build_memory_context", AsyncMock(return_value="")),
            ):
                with self.assertRaises(AnalysisChatError):
                    await create_analysis_chat_reply(
                        session,
                        analysis,
                        message="用 vision 模型回答",
                        provider_id="vision-provider",
                    )

            stored = await list_analysis_chat_messages(session, analysis.id)
            self.assertEqual(stored, [])

        await engine.dispose()

    async def test_provider_failure_does_not_persist_messages(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            with (
                patch("app.services.analysis_chat.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.analysis_chat.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.analysis_chat.request_text_completion", AsyncMock(side_effect=TimeoutError("timeout"))),
            ):
                with self.assertRaises(TimeoutError):
                    await create_analysis_chat_reply(session, analysis, message="comments 有没有被考虑？")

            stored = await list_analysis_chat_messages(session, analysis.id)
            self.assertEqual(stored, [])

        await engine.dispose()

    async def test_chat_correction_suggestion_is_persisted_but_not_applied(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        completion = AsyncMock(
            return_value=(
                "可以把这个作为待确认修正，应用前不会写入系统。\n"
                'CORRECTION_SUGGESTION_JSON={"kind":"action_label","payload":{"action_subtype":"Salchow","action_confirmation":{"confirmed_action":"Salchow"}},"rationale":"comments and partial candidates support review"}'
            )
        )
        async with Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            with (
                patch("app.services.analysis_chat.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.analysis_chat.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.analysis_chat.request_text_completion", completion),
            ):
                assistant_message, _messages = await create_analysis_chat_reply(session, analysis, message="把动作修正成 Salchow")

            self.assertNotIn("CORRECTION_SUGGESTION_JSON", assistant_message.content)
            corrections = await list_analysis_corrections(session, analysis.id)
            self.assertEqual(len(corrections), 1)
            self.assertEqual(corrections[0].status, "proposed")
            self.assertEqual(corrections[0].payload["action_subtype"], "Salchow")

        await engine.dispose()

    async def test_chat_keyframe_suggestion_is_persisted_but_not_applied(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        completion = AsyncMock(
            return_value=(
                "可以先作为待确认关键帧草稿。\n"
                'CORRECTION_SUGGESTION_JSON={"kind":"keyframes","payload":{"key_frames":{"T":"frame_0002","A":"frame_0005","L":"frame_0008"},"source":"chat_confirmed"},"rationale":"user confirmed the T/A/L frames"}'
            )
        )
        async with Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            with (
                patch("app.services.analysis_chat.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.analysis_chat.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.analysis_chat.request_text_completion", completion),
            ):
                assistant_message, _messages = await create_analysis_chat_reply(session, analysis, message="T 是 frame_0002，A 是 frame_0005，L 是 frame_0008")

            self.assertNotIn("CORRECTION_SUGGESTION_JSON", assistant_message.content)
            corrections = await list_analysis_corrections(session, analysis.id)
            self.assertEqual(len(corrections), 1)
            self.assertEqual(corrections[0].kind, "keyframes")
            self.assertEqual(corrections[0].status, "proposed")
            self.assertEqual(corrections[0].payload["key_frames"]["T"], "frame_0002")
            refreshed = await session.get(Analysis, analysis.id)
            self.assertEqual(refreshed.bio_data["key_frames"]["T"], "frame_0001")

        await engine.dispose()

    async def test_json_only_correction_suggestion_gets_user_facing_fallback(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        completion = AsyncMock(
            return_value='CORRECTION_SUGGESTION_JSON={"kind":"action_label","payload":{"action_type":"跳跃","action_subtype":"Toe Loop","action_confirmation":{"confirmed_action":"Toe Loop"}},"rationale":"user confirmed action"}'
        )
        async with Session() as session:
            analysis = _analysis()
            session.add(analysis)
            await session.commit()

            with (
                patch("app.services.analysis_chat.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.analysis_chat.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.analysis_chat.request_text_completion", completion),
            ):
                assistant_message, _messages = await create_analysis_chat_reply(session, analysis, message="动作是 Toe Loop")

            self.assertIn("待确认草稿", assistant_message.content)
            self.assertNotIn("暂时没有拿到稳定回复", assistant_message.content)
            corrections = await list_analysis_corrections(session, analysis.id)
            self.assertEqual(corrections[0].kind, "action_label")
            self.assertEqual(corrections[0].status, "proposed")

        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
