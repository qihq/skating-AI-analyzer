from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.plan import PLAN_DAY_THEMES, PlanGenerationError, generate_training_plan


def _report() -> dict[str, object]:
    return {
        "summary": "动作整体稳定，但落冰缓冲不足。",
        "issues": [{"category": "落冰", "description": "膝盖缓冲不够", "severity": "medium"}],
        "training_focus": "落冰平衡",
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


def _ai_plan_json(days: list[int] | None = None) -> str:
    selected_days = days or [day for day, _ in PLAN_DAY_THEMES]
    theme_by_day = dict(PLAN_DAY_THEMES)
    return json.dumps(
        {
            "title": "AI 生成 7 天训练计划",
            "focus_skill": "落冰平衡",
            "days": [
                {
                    "day": day,
                    "theme": theme_by_day[day],
                    "sessions": [
                        {
                            "id": f"d{day}s1",
                            "title": f"AI 训练 {day}",
                            "duration": "6分钟",
                            "description": "由 AI 根据报告生成的训练内容。",
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


class PlanGenerationTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
