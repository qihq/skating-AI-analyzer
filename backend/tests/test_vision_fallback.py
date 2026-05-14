from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report import calculate_force_score, generate_report, summarize_vision_for_report
from app.services.video import FramePayload
from app.services.vision import analyze_frames


class VisionFallbackTests(unittest.IsolatedAsyncioTestCase):
    def test_summarize_vision_for_report_marks_low_confidence_results_as_reference_only(self) -> None:
        vision_structured = {
            "frame_analysis": [
                {
                    "frame_id": f"frame_{index:04d}",
                    "phase": "不可分析",
                    "observations": {},
                    "issues": [],
                    "positives": [],
                    "confidence": 0.1,
                }
                for index in range(1, 6)
            ],
            "overall_raw_text": "原始视觉结论",
        }

        summary = summarize_vision_for_report(vision_structured)

        self.assertEqual(len(summary["reliable_frames"]), 5)
        self.assertTrue(summary["fallback_to_all_frames"])
        self.assertIn("仅供参考", summary["reliability_note"])

    async def test_invalid_vision_json_falls_back_and_marks_report_poor(self) -> None:
        frame_payloads = [
            FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA"),
            FramePayload(frame_id="frame_0002", data_url="data:image/jpeg;base64,BBB"),
        ]
        vision_provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")
        report_provider = SimpleNamespace(
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
        vision_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"frame_analysis": ['))]
        )
        report_json = """
        {
          "summary": "可以继续完成报告。",
          "issues": [],
          "improvements": [{"target": "稳定性", "action": "继续基础训练"}],
          "training_focus": "先保证基础动作稳定。",
          "subscores": {
            "takeoff_power": 80,
            "rotation_axis": 79,
            "arm_coordination": 78,
            "landing_absorption": 77,
            "core_stability": 76
          },
          "data_quality": "good"
        }
        """

        with (
            patch("app.services.vision.get_active_provider", AsyncMock(return_value=vision_provider)),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.vision.request_text_completion") as request_mock,
            patch("app.services.report.get_active_provider", AsyncMock(return_value=report_provider)),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", AsyncMock(return_value=report_json)),
        ):
            request_mock.return_value = '{"frame_analysis": ['

            vision_structured = await analyze_frames("跳跃", frame_payloads)
            report = await generate_report("跳跃", vision_structured, bio_data=None)

        self.assertEqual(vision_structured.get("data_quality_hint"), "poor")
        self.assertEqual(vision_structured.get("fallback_reason"), "AI_RESPONSE_PARSE_FAIL")
        self.assertEqual(len(vision_structured["frame_analysis"]), len(frame_payloads))
        self.assertTrue(all(frame["phase"] == "不可分析" for frame in vision_structured["frame_analysis"]))
        self.assertEqual(report["data_quality"], "poor")

    async def test_generate_report_appends_notice_when_all_frames_are_low_confidence(self) -> None:
        report_provider = SimpleNamespace(
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
        vision_structured = {
            "frame_analysis": [
                {
                    "frame_id": f"frame_{index:04d}",
                    "phase": "起跳",
                    "observations": {"knee_bend": "不足"},
                    "issues": ["起跳准备不足"],
                    "positives": [],
                    "confidence": 0.1,
                }
                for index in range(1, 6)
            ],
            "overall_raw_text": "全部帧置信度偏低。",
        }
        report_json = """
        {
          "summary": "本次动作可以继续练习。",
          "issues": [],
          "improvements": [{"target": "起跳", "action": "继续基础练习"}],
          "training_focus": "保持节奏稳定。",
          "subscores": {
            "takeoff_power": 75,
            "rotation_axis": 75,
            "arm_coordination": 75,
            "landing_absorption": 75,
            "core_stability": 75
          },
          "data_quality": "good"
        }
        """

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=report_provider)),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", AsyncMock(return_value=report_json)),
        ):
            report = await generate_report("跳跃", vision_structured, bio_data=None)

        self.assertIn("低置信度帧较多，结果仅供参考", report["summary"])
        self.assertEqual(report["data_quality"], "partial")

    async def test_vision_uses_dynamic_max_tokens_and_preserves_all_20_frames(self) -> None:
        frame_payloads = [
            FramePayload(frame_id=f"frame_{index:04d}", data_url=f"data:image/jpeg;base64,{index}")
            for index in range(1, 21)
        ]
        vision_provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")
        response_payload = {
            "frame_analysis": [
                {
                    "frame_id": frame.frame_id,
                    "phase": "起跳" if idx == 0 else "落冰",
                    "observations": {
                        "knee_bend": "充分",
                        "arm_position": "正确",
                        "axis_alignment": "垂直",
                        "blade_edge": "内刃",
                        "core_stability": "稳定",
                        "landing_absorption": "良好",
                    },
                    "issues": [f"issue-{idx}-1", f"issue-{idx}-2"],
                    "positives": [f"positive-{idx}-1", f"positive-{idx}-2"],
                    "confidence": 0.9,
                }
                for idx, frame in enumerate(frame_payloads)
            ],
            "action_phase_summary": {
                "detected_phases": ["起跳", "落冰"],
                "weakest_phase": "起跳",
                "strongest_phase": "落冰",
            },
            "overall_raw_text": "全部帧已完整输出。",
        }
        vision_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response_payload, ensure_ascii=False)))]
        )

        with (
            patch("app.services.vision.get_active_provider", AsyncMock(return_value=vision_provider)),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.vision.request_text_completion") as request_mock,
        ):
            request_mock.return_value = json.dumps(response_payload, ensure_ascii=False)

            vision_structured = await analyze_frames("跳跃", frame_payloads)

        create_kwargs = request_mock.await_args.kwargs
        self.assertEqual(create_kwargs["max_tokens"], 5400)
        prompt_text = create_kwargs["messages"][1]["content"][0]["text"]
        self.assertIn("candidate_key_frames", prompt_text)
        self.assertIn("Free Skate 1", prompt_text)
        self.assertIn("JSON schema:", prompt_text)
        self.assertEqual(len(vision_structured["frame_analysis"]), 20)
        self.assertEqual(vision_structured["frame_analysis"][-1]["frame_id"], "frame_0020")
        self.assertEqual(vision_structured["frame_analysis"][-1]["issues"], ["issue-19-1", "issue-19-2"])
        self.assertEqual(vision_structured["frame_analysis"][-1]["positives"], ["positive-19-1", "positive-19-2"])

    async def test_ai_request_failures_fall_back_to_biomechanics_report_and_force_score(self) -> None:
        frame_payloads = [
            FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA"),
            FramePayload(frame_id="frame_0002", data_url="data:image/jpeg;base64,BBB"),
        ]
        provider = SimpleNamespace(
            id="provider-1",
            slot="vision",
            name="provider",
            provider="openai_compatible",
            base_url="https://example.com/v1",
            model_id="test-model",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )
        bio_data = {
            "bio_subscores": {
                "takeoff_power": 82,
                "rotation_axis": 78,
                "arm_coordination": 74,
                "landing_absorption": 70,
                "core_stability": 66,
            },
            "quality_flags": ["vision_ai_unavailable_fallback"],
        }

        with (
            patch("app.services.vision.get_active_provider", AsyncMock(return_value=provider)),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.vision.request_text_completion", AsyncMock(side_effect=TimeoutError("timeout"))),
            patch("app.services.report.get_active_provider", AsyncMock(return_value=provider)),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", AsyncMock(side_effect=TimeoutError("timeout"))),
        ):
            vision_structured = await analyze_frames("跳跃", frame_payloads)
            report = await generate_report("跳跃", vision_structured, bio_data=bio_data)

        self.assertTrue(vision_structured["fallback_used"])
        self.assertEqual(vision_structured["action_phase_summary"], "AI 视觉分析暂不可用，以下评分基于生物力学数据。")
        self.assertEqual(len(vision_structured["frame_analysis"]), len(frame_payloads))
        self.assertTrue(report["fallback_used"])
        self.assertEqual(report["data_quality"], "degraded_no_ai")
        self.assertEqual(report["subscores"], bio_data["bio_subscores"])
        self.assertEqual(calculate_force_score(report), 75)


if __name__ == "__main__":
    unittest.main()
