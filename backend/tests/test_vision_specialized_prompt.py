from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video import FramePayload
from app.services.vision import analyze_frames


def _provider(provider_name: str = "openai_compatible") -> SimpleNamespace:
    return SimpleNamespace(
        id="vision-provider",
        slot="vision",
        name=provider_name,
        provider=provider_name,
        base_url="https://example.com/v1",
        model_id="vision-model",
        vision_model=None,
        api_key="test-key",
        notes=None,
    )


class VisionSpecializedPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_frame_mode_uses_specialized_prompt_with_empty_bio_defaults(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA")]
        response_payload = {
            "frame_analysis": [{"frame_id": "frame_0001", "phase": "起跳", "confidence": 0.8}],
            "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
            "overall_raw_text": "ok",
        }
        request_mock = AsyncMock(return_value=json.dumps(response_payload, ensure_ascii=False))

        with (
            patch("app.services.vision.get_vision_providers", AsyncMock(return_value=[_provider()])),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.vision.request_text_completion", request_mock),
        ):
            await analyze_frames(
                "jump",
                frame_payloads,
                analysis_profile="jump",
                mode="frames",
                n_votes=1,
            )

        kwargs = request_mock.await_args.kwargs
        system_prompt = kwargs["messages"][0]["content"]
        prompt_text = kwargs["messages"][1]["content"][0]["text"]

        self.assertIn("学员是儿童", system_prompt)
        self.assertIn("对儿童训练水平做保守判断", prompt_text)
        self.assertIn("candidate_key_frames", prompt_text)
        self.assertIn("Free Skate 1", prompt_text)
        self.assertIn("biomechanics:\n{}", prompt_text)
        self.assertIn("motion_features:\n{}", prompt_text)
        self.assertIn("JSON schema:", prompt_text)

    async def test_video_mode_uses_specialized_prompt_and_preserves_phase_segments_requirement(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=2.2)]
        response_payload = {
            "phase_segments": [{"start_sec": 0.0, "end_sec": 0.5, "phase": "起跳", "confidence": 0.8}],
            "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
            "overall_raw_text": "ok",
        }
        request_mock = AsyncMock(return_value=json.dumps(response_payload, ensure_ascii=False))

        with (
            patch("app.services.vision.get_vision_providers", AsyncMock(return_value=[_provider("qwen")])),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.vision.request_dashscope_video_completion", request_mock),
        ):
            await analyze_frames(
                "jump",
                frame_payloads,
                analysis_profile="jump",
                bio_data={"key_frame_candidates": {"T": {"frame_id": "frame_0001", "confidence": 0.7}}},
                motion_features={"selected": [{"frame_id": "frame_0001", "motion_score": 0.9}]},
                mode="video",
                clip_path=Path("clip.mp4"),
                window_start_sec=2.0,
            )

        kwargs = request_mock.await_args.kwargs
        self.assertIn("学员是儿童", kwargs["system_prompt"])
        self.assertIn("对儿童训练水平做保守判断", kwargs["user_prompt"])
        self.assertIn("candidate_key_frames", kwargs["user_prompt"])
        self.assertIn('"frame_id": "frame_0001"', kwargs["user_prompt"])
        self.assertIn('"motion_score": 0.9', kwargs["user_prompt"])
        self.assertIn("phase_segments", kwargs["user_prompt"])


if __name__ == "__main__":
    unittest.main()
