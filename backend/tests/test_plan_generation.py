from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.plan import PLAN_DAY_THEMES, PLAN_REQUEST_TIMEOUT_SECONDS, PlanGenerationError, _clean_plan_json_text, build_fallback_plan, extend_training_plan, generate_training_plan


def _report() -> dict[str, object]:
    return {
        "summary": "动作整体稳定，但落冰缓冲不足。",
        "issues": [{"category": "落冰", "description": "膝盖缓冲不够", "severity": "medium"}],
        "training_focus": "落冰平衡",
        "user_note": "孩子害怕落冰声音。",
    }


def _provider() -> SimpleNamespace:
    return SimpleNamespace(
        id="report-provider",
        slot="report",
        name="report-provider",
        provider="openai_compatible",
        base_url="https://example.com/v1",
        model_id="test-report-model",
        vision_model=None,
        api_key="test-key",
        notes=None,
    )


def _ai_plan_json(days: list[int] | None = None, *, personalized_themes: bool = False) -> str:
    selected_days = days or [day for day, _ in PLAN_DAY_THEMES]
    theme_by_day = dict(PLAN_DAY_THEMES)
    return json.dumps(
        {
            "title": "AI 生成 7 天训练计划",
            "focus_skill": "落冰平衡",
            "days": [
                {
                    "day": day,
                    "theme": f"落冰缓冲游戏第 {day} 天" if personalized_themes else theme_by_day[day],
                    "sessions": [
                        {
                            "id": f"d{day}s1",
                            "title": f"AI 训练 {day}",
                            "duration": "6分钟",
                            "description": "由 AI 根据报告生成的训练内容。",
                            "related_issue": "落冰缓冲不足",
                            "parent_tip": "听落地声音是否变轻",
                            "is_office_trainable": day != 7,
                            "completed": False,
                        }
                    ],
                }
                for day in selected_days
            ],
        },
        ensure_ascii=False,
    )


def _original_plan() -> dict[str, object]:
    return json.loads(_ai_plan_json())


class PlanGenerationTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_plan_json_text_preserves_array_payloads(self) -> None:
        payload = '[{"day":4,"sessions":[]}]'

        self.assertEqual(_clean_plan_json_text(f"```json\n{payload}\n```"), payload)

    def test_fallback_plan_uses_report_issue_and_child_safe_fields(self) -> None:
        plan = build_fallback_plan("jump", _report(), "昭昭，4岁，启蒙训练")

        self.assertEqual(plan["title"], "7天亲子冰感小游戏")
        self.assertEqual(plan["generation_source"], "fallback")
        self.assertIn("兜底", plan["generation_note"])
        self.assertIn("落冰", plan["days"][0]["theme"])
        self.assertEqual(plan["days"][0]["sessions"][0]["related_issue"], "落冰：膝盖缓冲不够")
        self.assertEqual(plan["days"][0]["sessions"][0]["parent_tip"], "只看是否更稳更放松。")
        self.assertFalse(plan["days"][6]["sessions"][0]["is_office_trainable"])

    async def test_generate_training_plan_uses_ai_payload(self) -> None:
        with (
            patch("app.services.plan.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.plan.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.plan.request_text_completion", AsyncMock(return_value=_ai_plan_json())),
        ):
            plan = await generate_training_plan("jump", _report(), "儿童滑冰学员", "skater-1")

        self.assertEqual(plan["title"], "AI 生成 7 天训练计划")
        self.assertEqual([day["day"] for day in plan["days"]], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(plan["days"][0]["sessions"][0]["title"], "AI 训练 1")
        self.assertEqual(plan["days"][0]["sessions"][0]["related_issue"], "落冰缓冲不足")
        self.assertEqual(plan["days"][0]["sessions"][0]["parent_tip"], "听落地声音是否变轻")
        self.assertEqual(plan["generation_status"], "ai")

    async def test_generate_training_plan_preserves_ai_personalized_themes(self) -> None:
        with (
            patch("app.services.plan.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.plan.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.plan.request_text_completion", AsyncMock(return_value=_ai_plan_json(personalized_themes=True))),
        ):
            plan = await generate_training_plan("jump", _report(), "儿童滑冰学员", "skater-1")

        self.assertEqual(plan["days"][0]["theme"], "落冰缓冲游戏第 1 天")
        self.assertEqual(plan["days"][4]["theme"], "落冰缓冲游戏第 5 天")

    async def test_generate_training_plan_prompt_includes_child_context_and_variation_seed(self) -> None:
        completion = AsyncMock(return_value=_ai_plan_json())
        with (
            patch("app.services.plan.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.plan.build_memory_context", AsyncMock(return_value="历史记忆：更喜欢音乐游戏")),
            patch("app.services.plan.request_text_completion", completion),
        ):
            await generate_training_plan("jump", _report(), "昭昭，4岁，初级", "skater-1", variation_key="seed-123")

        kwargs = completion.await_args.kwargs
        self.assertEqual(kwargs["temperature"], 0.45)
        self.assertEqual(kwargs["max_tokens"], 1800)
        self.assertEqual(kwargs["timeout"], PLAN_REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        messages = kwargs["messages"]
        self.assertIn("child figure-skating coach", messages[0]["content"])
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["skater"], "昭昭，4岁，初级")
        self.assertEqual(payload["variation_key"], "seed-123")
        self.assertIn("历史记忆：更喜欢音乐游戏", payload["memory"])
        self.assertEqual(payload["report"]["user_note"], "孩子害怕落冰声音。")
        self.assertTrue(any("related_issue" in rule for rule in payload["rules"]))
        self.assertTrue(any("Day 7" in rule and "false" in rule for rule in payload["rules"]))

    async def test_generate_training_plan_raises_when_provider_setup_fails(self) -> None:
        with patch("app.services.plan.get_active_provider", AsyncMock(side_effect=RuntimeError("missing key"))):
            with self.assertRaisesRegex(PlanGenerationError, "AI 供应商不可用"):
                await generate_training_plan("jump", _report(), "儿童滑冰学员", "skater-1")

    async def test_generate_training_plan_raises_when_completion_fails(self) -> None:
        with (
            patch("app.services.plan.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.plan.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.plan.request_text_completion", AsyncMock(side_effect=TimeoutError("timeout"))),
        ):
            with self.assertRaisesRegex(PlanGenerationError, "AI 调用失败"):
                await generate_training_plan("jump", _report(), "儿童滑冰学员", "skater-1")

    async def test_generate_training_plan_raises_when_ai_json_is_incomplete(self) -> None:
        with (
            patch("app.services.plan.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.plan.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.plan.request_text_completion", AsyncMock(return_value=_ai_plan_json(days=[1, 2]))),
        ):
            with self.assertRaisesRegex(PlanGenerationError, "不完整"):
                await generate_training_plan("jump", _report(), "儿童滑冰学员", "skater-1")

    async def test_extend_training_plan_prompt_keeps_child_safety_and_report_context(self) -> None:
        completion = AsyncMock(return_value=json.dumps(json.loads(_ai_plan_json(days=[4, 5, 6, 7]))["days"], ensure_ascii=False))
        with (
            patch("app.services.plan.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.plan.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.plan.request_text_completion", completion),
        ):
            await extend_training_plan(
                original_plan=_original_plan(),
                completed_days=[1, 2, 3],
                action_type="jump",
                report=_report(),
                skater_context="昭昭，4岁，初级",
                skater_id="skater-1",
            )

        kwargs = completion.await_args.kwargs
        self.assertEqual(kwargs["temperature"], 0.45)
        prompt = kwargs["messages"][1]["content"]
        self.assertIn("练习对象：昭昭，4岁，初级", prompt)
        self.assertIn("膝盖缓冲不够", prompt)
        self.assertIn("家长/教练备注：孩子害怕落冰声音。", prompt)
        self.assertIn("避免重复已完成项目", prompt)
        self.assertIn("related_issue", prompt)
        self.assertIn("parent_tip", prompt)
        self.assertIn("不要安排负重、Bosu、旋转椅、痛苦拉伸", prompt)
        self.assertIn("Day 7 所有项目必须 is_office_trainable=false", prompt)

    async def test_create_training_plan_ai_failure_does_not_overwrite_existing_ai_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            for module_name in ["app.database", "app.models", "app.routers.analysis"]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.analysis as analysis_router

            database.ensure_storage_dirs()
            await database.init_db()
            existing_plan_json = {**_original_plan(), "generation_source": "ai", "generation_status": "ai"}
            async with database.AsyncSessionLocal() as session:
                session.add(models.Skater(id="skater-1", name="kid"))
                session.add(
                    models.Analysis(
                        id="analysis-1",
                        skater_id="skater-1",
                        action_type="jump",
                        video_path=str(Path(tmpdir) / "source.mp4"),
                        status="completed",
                        report=_report(),
                    )
                )
                session.add(
                    models.TrainingPlan(
                        id="plan-1",
                        analysis_id="analysis-1",
                        skater_id="skater-1",
                        plan_json=existing_plan_json,
                    )
                )
                await session.commit()

                with patch("app.routers.analysis.generate_training_plan", AsyncMock(side_effect=PlanGenerationError("ReadTimeout"))):
                    detail = await analysis_router.create_training_plan("analysis-1", force=True, session=session)

                stored = await session.get(models.TrainingPlan, "plan-1")
                assert stored is not None
                self.assertEqual(detail.plan_json.generation_status, "ai")
                self.assertEqual(stored.plan_json["generation_status"], "ai")
                self.assertEqual(stored.plan_json["title"], existing_plan_json["title"])

    async def test_create_training_plan_missing_report_uses_minimal_context_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            for module_name in ["app.database", "app.models", "app.routers.analysis"]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.analysis as analysis_router

            database.ensure_storage_dirs()
            await database.init_db()
            async with database.AsyncSessionLocal() as session:
                session.add(models.Skater(id="skater-1", name="kid", display_name="昭昭"))
                session.add(
                    models.Analysis(
                        id="analysis-1",
                        skater_id="skater-1",
                        action_type="跳跃",
                        action_subtype="后外点冰跳",
                        skill_category="单周跳",
                        note="后外动作落冰怕响",
                        video_path=str(Path(tmpdir) / "source.mp4"),
                        status="completed",
                        force_score=61,
                        report=None,
                    )
                )
                await session.commit()

                with patch("app.routers.analysis.generate_training_plan", AsyncMock(side_effect=PlanGenerationError("invalid json"))):
                    detail = await analysis_router.create_training_plan("analysis-1", force=True, session=session)

                stored = await session.get(models.TrainingPlan, detail.id)
                assert stored is not None
                self.assertEqual(detail.plan_json.generation_status, "fallback")
                self.assertIn("安全兜底", detail.plan_json.generation_note or "")
                self.assertIn("后外点冰跳", detail.plan_json.focus_skill)
                first_session = detail.plan_json.days[0].sessions[0]
                self.assertIn("后外点冰跳", first_session.related_issue or "")
                self.assertEqual(stored.plan_json["generation_status"], "fallback")

    async def test_extend_plan_ai_failure_returns_fallback_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            for module_name in ["app.database", "app.models", "app.routers.analysis"]:
                sys.modules.pop(module_name, None)

            import app.database as database
            import app.models as models
            import app.routers.analysis as analysis_router
            from app.schemas import ExtendPlanBody

            database.ensure_storage_dirs()
            await database.init_db()
            original_plan_json = _original_plan()
            original_plan_json["days"][0]["sessions"][0]["completed"] = True
            original_title = str(original_plan_json["days"][0]["sessions"][0]["title"])
            async with database.AsyncSessionLocal() as session:
                session.add(models.Skater(id="skater-1", name="kid", display_name="昭昭"))
                session.add(
                    models.Analysis(
                        id="analysis-1",
                        skater_id="skater-1",
                        action_type="jump",
                        action_subtype="后外点冰跳",
                        video_path=str(Path(tmpdir) / "source.mp4"),
                        status="completed",
                        report=None,
                        force_score=63,
                    )
                )
                session.add(
                    models.TrainingPlan(
                        id="plan-1",
                        analysis_id="analysis-1",
                        skater_id="skater-1",
                        plan_json=original_plan_json,
                    )
                )
                await session.commit()

                with patch("app.routers.analysis.extend_training_plan", AsyncMock(side_effect=PlanGenerationError("timeout"))):
                    detail = await analysis_router.extend_plan("plan-1", ExtendPlanBody(completed_days=[1, 2, 3]), session=session)

                stored = await session.get(models.TrainingPlan, "plan-1")
                assert stored is not None
                self.assertEqual(detail.plan_json.generation_status, "fallback")
                self.assertIn("兜底续期", detail.plan_json.generation_note or "")
                self.assertEqual(detail.plan_json.days[0].sessions[0].title, original_title)
                self.assertEqual(stored.plan_json["generation_status"], "fallback")


if __name__ == "__main__":
    unittest.main()
