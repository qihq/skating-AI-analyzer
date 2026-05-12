from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video import FramePayload
from app.services.vision_path_b import analyze_path_b, sample_frames_path_b


def _frames(count: int) -> list[FramePayload]:
    return [
        FramePayload(
            frame_id=f"frame_{index + 1:04d}",
            data_url=f"data:image/jpeg;base64,{index}",
            timestamp_sec=index * 0.1,
        )
        for index in range(count)
    ]


class VisionPathBTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_frames_return_soft_error(self) -> None:
        provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")

        result = await analyze_path_b("跳跃", [], provider)

        self.assertEqual(result["path"], "B")
        self.assertEqual(result["error"], "no frames")
        self.assertEqual(result["frame_analysis"], [])

    async def test_provider_failure_returns_soft_error(self) -> None:
        provider = SimpleNamespace(api_key="bad-key", base_url="https://example.com/v1", model_id="test-model")

        with patch("app.services.vision_path_b.request_text_completion") as request_mock:
            request_mock.side_effect = RuntimeError("bad api key")

            result = await analyze_path_b("跳跃", _frames(1), provider)

        self.assertEqual(result["path"], "B")
        self.assertIn("bad api key", result["error"])

    async def test_success_path_includes_defaults_and_prompt_grounding(self) -> None:
        frame_payloads = _frames(30)
        provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="qwen3.6-plus")
        response_payload = {
            "frame_analysis": [{"frame_id": "frame_0021", "phase": "起跳", "confidence": 0.8}],
            "subscores": {"takeoff_power": 82},
        }
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response_payload, ensure_ascii=False)))]
        )

        with patch("app.services.vision_path_b.request_text_completion") as request_mock:
            request_mock.return_value = json.dumps(response_payload, ensure_ascii=False)

            result = await analyze_path_b(
                "跳跃",
                frame_payloads,
                provider,
                frame_bio_context={"frame_0021": {"left_knee_angle": 145.2}},
                key_frame_stems={"frame_0021"},
                jump_metrics_text="AirTime=0.45s | Height=24.8cm",
                action_subtype="Axel",
                analysis_profile="jump",
                profile_evidence={"input": "Axel"},
                memory_context="长期训练目标：稳定落冰。",
            )

        create_kwargs = request_mock.await_args.kwargs
        self.assertEqual(create_kwargs["temperature"], 0.25)
        self.assertEqual(create_kwargs["max_tokens"], 2900)

        messages = create_kwargs["messages"]
        self.assertIn("长期训练目标", messages[0]["content"])

        user_content = messages[1]["content"]
        self.assertIn("JUMP_SUBTYPE_EVIDENCE", user_content[0]["text"])
        self.assertIn("【整体生物力学摘要】", user_content[0]["text"])
        self.assertIn("AirTime=0.45s", user_content[0]["text"])

        text_labels = [item["text"] for item in user_content[1::2]]
        self.assertEqual(
            [label.split(" | ")[0].replace("帧编号：", "") for label in text_labels],
            ["frame_0019", "frame_0020", "frame_0021", "frame_0022", "frame_0023"],
        )
        self.assertTrue(any("LKnee=145.20deg" in label for label in text_labels))

        self.assertEqual(result["path"], "B")
        self.assertEqual(result["n_frames"], 5)
        self.assertEqual(result["subscores"]["takeoff_power"], 82)
        self.assertEqual(result["frame_analysis"][0]["frame_id"], "frame_0021")
        self.assertEqual(
            result["action_phase_summary"],
            {"detected_phases": [], "weakest_phase": "", "strongest_phase": ""},
        )
        self.assertEqual(result["top_issues"], [])
        self.assertEqual(result["top_positives"], [])

    async def test_invalid_json_returns_soft_error(self) -> None:
        provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"frame_analysis": ['))])

        with patch("app.services.vision_path_b.request_text_completion") as request_mock:
            request_mock.return_value = '{"frame_analysis": ['

            result = await analyze_path_b("跳跃", _frames(1), provider)

        self.assertIn("json_parse:", result["error"])
        self.assertEqual(result["path"], "B")


class VisionPathBSamplingTests(unittest.TestCase):
    def test_key_frame_sampling_includes_context(self) -> None:
        result = sample_frames_path_b(_frames(30), {"frame_0021"})

        self.assertEqual(
            [frame.frame_id for frame in result],
            ["frame_0019", "frame_0020", "frame_0021", "frame_0022", "frame_0023"],
        )

    def test_uniform_sampling_caps_to_ten_frames(self) -> None:
        result = sample_frames_path_b(_frames(30), None)

        self.assertEqual(len(result), 10)
        self.assertEqual(result[0].frame_id, "frame_0001")
        self.assertEqual(result[-1].frame_id, "frame_0028")

    def test_key_frame_sampling_falls_back_to_uniform_when_no_match(self) -> None:
        result = sample_frames_path_b(_frames(30), {"frame_9999"})

        self.assertEqual(len(result), 10)
        self.assertEqual(result[0].frame_id, "frame_0001")
        self.assertEqual(result[-1].frame_id, "frame_0028")


if __name__ == "__main__":
    unittest.main()
