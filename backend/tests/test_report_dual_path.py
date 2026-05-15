from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report import generate_report, normalize_report


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


def _deepseek_v4_provider() -> SimpleNamespace:
    provider = _provider()
    provider.provider = "deepseek"
    provider.model_id = "deepseek-v4-pro"
    return provider


def _report_json(data_quality: str = "good") -> str:
    return f"""
    {{
      "summary": "动作整体稳定。",
      "issues": [],
      "improvements": [{{"target": "轴心", "action": "保持基础练习"}}],
      "training_focus": "稳定轴心。",
      "subscores": {{
        "takeoff_power": 90,
        "rotation_axis": 80,
        "arm_coordination": 70,
        "landing_absorption": 60,
        "core_stability": 50
      }},
      "data_quality": "{data_quality}"
    }}
    """


class ReportDualPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_report_without_dual_meta_keeps_prompt_free_of_dual_block(self) -> None:
        request_mock = AsyncMock(return_value=_report_json())

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            report = await generate_report("jump", {"frame_analysis": []}, bio_data=None)

        prompt = request_mock.await_args.kwargs["messages"][1]["content"]
        self.assertNotIn("双路交叉验证参考", prompt)
        self.assertEqual(report["data_quality"], "good")

    async def test_generate_report_with_likely_wrong_dual_meta_adds_retarget_prompt(self) -> None:
        request_mock = AsyncMock(return_value=_report_json(data_quality="poor"))
        dual_path_meta = {
            "overall_agreement_rate": "0.42",
            "skeleton_reliability_signal": "likely_wrong",
            "recommended_path": "A",
            "conflict_fields": ["rotation_axis"],
            "conflict_summary": "Path B 轴心判断偏差较大",
            "path_b_subscores": {"rotation_axis": 30},
        }

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            report = await generate_report("jump", {"frame_analysis": []}, bio_data=None, dual_path_meta=dual_path_meta)

        prompt = request_mock.await_args.kwargs["messages"][1]["content"]
        self.assertIn("双路交叉验证参考", prompt)
        self.assertIn("两路一致率：42%", prompt)
        self.assertIn("建议用户重选目标", prompt)
        self.assertIn("你不要自行加权", prompt)
        self.assertEqual(report["subscores"]["rotation_axis"], 80)
        self.assertEqual(report["data_quality"], "poor")

    async def test_generate_report_handles_none_agreement_rate(self) -> None:
        request_mock = AsyncMock(return_value=_report_json())
        dual_path_meta = {
            "overall_agreement_rate": None,
            "skeleton_reliability_signal": "uncertain",
        }

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            await generate_report("jump", {"frame_analysis": []}, bio_data=None, dual_path_meta=dual_path_meta)

        prompt = request_mock.await_args.kwargs["messages"][1]["content"]
        self.assertIn("两路一致率：0%", prompt)

    async def test_generate_report_invalid_json_returns_fallback_report(self) -> None:
        request_mock = AsyncMock(return_value="{not json")
        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            report = await generate_report("jump", {"frame_analysis": []}, bio_data=None, dual_path_meta={"overall_agreement_rate": None})

        self.assertEqual(request_mock.await_count, 3)
        self.assertEqual(report["fallback_reason"], "AI_RESPONSE_PARSE_FAIL")
        self.assertEqual(report["data_quality"], "partial")
        self.assertTrue(report["summary"])

    async def test_generate_report_empty_response_returns_fallback_report(self) -> None:
        request_mock = AsyncMock(return_value="")
        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            report = await generate_report("jump", {"frame_analysis": []}, bio_data=None)

        self.assertEqual(request_mock.await_count, 3)
        self.assertEqual(report["fallback_reason"], "AI_RESPONSE_PARSE_FAIL")
        self.assertIn("line 1 column 1", report["fallback_detail"])

    async def test_generate_report_retries_parse_failure_then_uses_successful_json(self) -> None:
        request_mock = AsyncMock(side_effect=["", "{not json", _report_json()])

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            report = await generate_report("jump", {"frame_analysis": []}, bio_data=None)

        self.assertEqual(request_mock.await_count, 3)
        self.assertEqual(report["data_quality"], "good")
        self.assertEqual(report["report_retry_count"], 2)
        self.assertNotIn("fallback_reason", report)

    async def test_deepseek_v4_report_uses_json_response_format_and_lower_temperature(self) -> None:
        request_mock = AsyncMock(return_value=_report_json())

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_deepseek_v4_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            await generate_report("jump", {"frame_analysis": []}, bio_data=None)

        kwargs = request_mock.await_args.kwargs
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["temperature"], 0.15)
        self.assertIn("Output constraints", kwargs["messages"][1]["content"])

    async def test_generate_report_keeps_technical_conclusion_for_partial_side_view(self) -> None:
        request_mock = AsyncMock(
            return_value="""
            {
              "summary": "起跳阶段膝关节准备不足，落冰缓冲偏硬，需要先稳定起跳节奏。",
              "issues": [{"category":"起跳准备","description":"起跳前膝关节压缩不足","severity":"medium","phase":"起跳","frames":["frame_0001"]}],
              "improvements": [{"target":"起跳准备","action":"做两组慢速压膝起跳节奏练习"}],
              "training_focus": "先练稳定压膝和落冰缓冲。",
              "subscores": {
                "takeoff_power": 74,
                "rotation_axis": 72,
                "arm_coordination": 70,
                "landing_absorption": 68,
                "core_stability": 73
              },
              "data_quality": "good"
            }
            """
        )
        vision_structured = {
            "data_quality_hint": "partial",
            "camera_view": "side",
            "frame_analysis": [
                {
                    "frame_id": "frame_0001",
                    "phase": "起跳",
                    "observations": {"knee_bend": "不足"},
                    "issues": ["起跳前膝关节压缩不足"],
                    "positives": [],
                    "confidence": 0.82,
                },
                {
                    "frame_id": "frame_0002",
                    "phase": "腾空",
                    "observations": {"axis_alignment": "轻微侧倾"},
                    "issues": ["腾空轴心略偏"],
                    "positives": [],
                    "confidence": 0.74,
                },
                {
                    "frame_id": "frame_0003",
                    "phase": "落冰",
                    "observations": {"landing_absorption": "不足"},
                    "issues": ["落冰缓冲偏硬"],
                    "positives": [],
                    "confidence": 0.7,
                },
            ],
            "overall_raw_text": "侧面视角下仍可见起跳和落冰问题。",
        }

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            report = await generate_report("jump", vision_structured, bio_data=None)

        prompt = request_mock.await_args.kwargs["messages"][1]["content"]
        self.assertIn("不要让 summary 只剩画质、视角或骨架不确定性", prompt)
        self.assertNotIn("低置信度帧较多", report["summary"])
        self.assertIn("起跳", report["summary"])
        self.assertEqual(report["data_quality"], "partial")


class ReportNormalizeTests(unittest.TestCase):
    def test_bio_subscores_are_fused_without_key_frames(self) -> None:
        report = normalize_report(
            {
                "summary": "ok",
                "issues": [],
                "improvements": [],
                "training_focus": "focus",
                "subscores": {
                    "takeoff_power": 50,
                    "rotation_axis": 50,
                    "arm_coordination": 50,
                    "landing_absorption": 50,
                    "core_stability": 50,
                },
            },
            bio_data={
                "bio_subscores": {
                    "takeoff_power": 100,
                    "rotation_axis": 100,
                    "arm_coordination": 100,
                    "landing_absorption": 100,
                    "core_stability": 100,
                },
                "quality_flags": [],
                "key_frames": {},
            },
        )

        self.assertEqual(report["subscores"]["takeoff_power"], 80)


if __name__ == "__main__":
    unittest.main()
