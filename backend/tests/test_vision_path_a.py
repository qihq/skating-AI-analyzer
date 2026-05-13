from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.video import FramePayload
from app.services.vision_path_a import analyze_path_a


class VisionPathATests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_frames_raise_frame_extract_failed(self) -> None:
        provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")

        with self.assertRaises(AnalysisPipelineError) as caught:
            await analyze_path_a("跳跃", [], provider)

        self.assertEqual(caught.exception.code, AnalysisErrorCode.FRAME_EXTRACT_FAILED)

    async def test_path_a_normalizes_payload_and_preserves_extension_fields(self) -> None:
        frame_payloads = [
            FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.25),
            FramePayload(frame_id="frame_0002", data_url="data:image/jpeg;base64,BBB", timestamp_sec=1.50),
        ]
        provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="qwen3.6-plus")
        response_payload = {
            "frame_analysis": [
                {
                    "frame_id": "frame_0001",
                    "phase": "起跳",
                    "observations": {"knee_bend": "充分"},
                    "issues": ["节奏略急"],
                    "positives": ["蹬冰明确"],
                    "confidence": 0.8,
                }
            ],
            "action_phase_summary": {
                "detected_phases": ["起跳"],
                "weakest_phase": "落冰",
                "strongest_phase": "起跳",
            },
            "pure_vision_subscores": {
                "takeoff_power": 82,
                "rotation_axis": 78,
                "arm_coordination": 76,
                "landing_absorption": 74,
                "core_stability": 80,
            },
            "overall_raw_text": "纯视觉判断完成。",
        }
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response_payload, ensure_ascii=False)))]
        )

        with patch("app.services.vision_path_a.request_text_completion") as request_mock:
            request_mock.return_value = json.dumps(response_payload, ensure_ascii=False)

            result = await analyze_path_a(
                "跳跃",
                frame_payloads,
                provider,
                action_subtype="Axel",
                analysis_profile="jump",
                profile_evidence={"input": "Axel"},
                memory_context="长期训练目标：稳定落冰。",
            )

        create_kwargs = request_mock.await_args.kwargs
        self.assertEqual(create_kwargs["temperature"], 0.1)
        self.assertEqual(create_kwargs["max_tokens"], 1360)
        user_content = create_kwargs["messages"][1]["content"]
        self.assertIn("JUMP_SUBTYPE_EVIDENCE", user_content[0]["text"])
        self.assertIn("时间：1.25s", user_content[1]["text"])
        self.assertIn("时间：1.50s", user_content[3]["text"])

        self.assertEqual(result["path"], "A")
        self.assertEqual(result["pure_vision_subscores"]["takeoff_power"], 82)
        self.assertEqual(len(result["frame_analysis"]), 2)
        self.assertEqual(result["frame_analysis"][0]["phase"], "起跳")
        self.assertEqual(result["frame_analysis"][1]["frame_id"], "frame_0002")
        self.assertEqual(result["frame_analysis"][1]["phase"], "不可分析")
        self.assertEqual(result["action_phase_summary"]["detected_phases"], ["起跳"])

    async def test_invalid_json_raises_parse_fail(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA")]
        provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"frame_analysis": ['))])

        with patch("app.services.vision_path_a.request_text_completion") as request_mock:
            request_mock.return_value = '{"frame_analysis": ['

            with self.assertRaises(AnalysisPipelineError) as caught:
                await analyze_path_a("跳跃", frame_payloads, provider)

        self.assertEqual(caught.exception.code, AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL)


if __name__ == "__main__":
    unittest.main()
