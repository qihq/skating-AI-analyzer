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
from app.services.vision_path_a import analyze_path_a


class VisionVideoModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_mode_phase_segments_map_to_frame_contract(self) -> None:
        frame_payloads = [
            FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=10.2),
            FramePayload(frame_id="frame_0002", data_url="data:image/jpeg;base64,BBB", timestamp_sec=10.8),
        ]
        provider = SimpleNamespace(
            id="vision-provider",
            slot="vision",
            name="qwen",
            provider="qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_id="qwen3.6-plus",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )
        payload = {
            "phase_segments": [
                {
                    "start_sec": 0.0,
                    "end_sec": 0.4,
                    "phase": "起跳",
                    "observations": {"knee_bend": "充分"},
                    "issues": [],
                    "positives": ["起跳清晰"],
                    "confidence": 0.9,
                },
                {
                    "start_sec": 0.5,
                    "end_sec": 1.0,
                    "phase": "落冰",
                    "observations": {"landing_absorption": "良好"},
                    "issues": ["落冰略急"],
                    "positives": [],
                    "confidence": 0.8,
                },
            ],
            "action_phase_summary": {
                "detected_phases": ["起跳", "落冰"],
                "weakest_phase": "落冰",
                "strongest_phase": "起跳",
            },
            "overall_raw_text": "video ok",
        }

        with (
            patch("app.services.vision.get_active_provider", AsyncMock(return_value=provider)),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch(
                "app.services.vision.request_dashscope_video_completion",
                AsyncMock(return_value=json.dumps(payload, ensure_ascii=False)),
            ) as video_mock,
            patch("app.services.vision.request_text_completion", AsyncMock()) as frame_mock,
        ):
            result = await analyze_frames(
                "跳跃",
                frame_payloads,
                mode="video",
                clip_path=Path("clip.mp4"),
                window_start_sec=10.0,
            )

        self.assertEqual(result["vision_mode"], "video")
        self.assertEqual(result["frame_analysis"][0]["phase"], "起跳")
        self.assertEqual(result["frame_analysis"][1]["phase"], "落冰")
        self.assertIn("phase_segments", result)
        video_mock.assert_awaited_once()
        frame_mock.assert_not_awaited()

    async def test_video_failure_falls_back_to_frames_with_quality_flag(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.0)]
        provider = SimpleNamespace(
            id="vision-provider",
            slot="vision",
            name="qwen",
            provider="qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_id="qwen3.6-plus",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )
        frame_payload = {
            "frame_analysis": [{"frame_id": "frame_0001", "phase": "起跳", "confidence": 0.8}],
            "action_phase_summary": {
                "detected_phases": ["起跳"],
                "weakest_phase": "起跳",
                "strongest_phase": "起跳",
            },
            "overall_raw_text": "frames ok",
        }

        with (
            patch("app.services.vision.get_active_provider", AsyncMock(return_value=provider)),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch(
                "app.services.vision.request_dashscope_video_completion",
                AsyncMock(side_effect=TimeoutError("upload timeout")),
            ),
            patch(
                "app.services.vision.request_text_completion",
                AsyncMock(return_value=json.dumps(frame_payload, ensure_ascii=False)),
            ) as frame_mock,
        ):
            result = await analyze_frames(
                "跳跃",
                frame_payloads,
                mode="video",
                clip_path=Path("clip.mp4"),
                window_start_sec=1.0,
            )

        self.assertEqual(result["vision_mode"], "frames")
        self.assertIn("vision_fallback_to_frames", result["quality_flags"])
        self.assertEqual(frame_mock.await_count, 2)

    async def test_video_mode_dispatches_to_mimo_video_provider(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=5.0)]
        provider = SimpleNamespace(
            id="mimo-provider",
            slot="vision",
            name="mimo",
            provider="mimo",
            base_url="https://api.xiaomimimo.com/v1",
            model_id="mimo-v2.5",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )
        payload = {
            "phase_segments": [{"start_sec": 0.0, "end_sec": 0.5, "phase": "èµ·è·³", "confidence": 0.9}],
            "action_phase_summary": {
                "detected_phases": ["èµ·è·³"],
                "weakest_phase": "èµ·è·³",
                "strongest_phase": "èµ·è·³",
            },
            "overall_raw_text": "mimo video",
        }

        with (
            patch("app.services.vision.get_active_provider", AsyncMock(return_value=provider)),
            patch("app.services.vision.get_vision_providers", AsyncMock(return_value=[provider])),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch(
                "app.services.vision.request_mimo_video_completion",
                AsyncMock(return_value=json.dumps(payload, ensure_ascii=False)),
            ) as video_mock,
            patch("app.services.vision.request_text_completion", AsyncMock()) as frame_mock,
        ):
            result = await analyze_frames(
                "è·³è·ƒ",
                frame_payloads,
                mode="video",
                clip_path=Path("clip.mp4"),
                window_start_sec=5.0,
            )

        self.assertEqual(result["vision_mode"], "video")
        self.assertEqual(result["provider"], "mimo")
        video_mock.assert_awaited_once()
        frame_mock.assert_not_awaited()

    async def test_path_a_video_mode_preserves_path_fields(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=3.25)]
        provider = SimpleNamespace(
            id="vision-provider",
            slot="vision_path_a",
            name="qwen",
            provider="qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_id="qwen3.6-plus",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )
        video_payload = {
            "phase_segments": [
                {"start_sec": 0.0, "end_sec": 0.5, "phase": "起跳", "confidence": 0.9},
            ],
            "pure_vision_subscores": {"takeoff_power": 88},
            "action_phase_summary": {
                "detected_phases": ["起跳"],
                "weakest_phase": "落冰",
                "strongest_phase": "起跳",
            },
            "overall_raw_text": "path a video",
        }

        with patch(
            "app.services.vision_path_a.request_dashscope_video_completion",
            AsyncMock(return_value=json.dumps(video_payload, ensure_ascii=False)),
        ):
            result = await analyze_path_a(
                "跳跃",
                frame_payloads,
                provider,
                mode="video",
                clip_path=Path("clip.mp4"),
                window_start_sec=3.0,
            )

        self.assertEqual(result["path"], "A")
        self.assertEqual(result["vision_mode"], "video")
        self.assertEqual(result["pure_vision_subscores"]["takeoff_power"], 88)
        self.assertEqual(result["frame_analysis"][0]["phase"], "起跳")

    async def test_path_a_video_mode_dispatches_to_mimo(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=3.25)]
        provider = SimpleNamespace(
            id="mimo-provider",
            slot="vision_path_a",
            name="mimo",
            provider="mimo",
            base_url="https://api.xiaomimimo.com/v1",
            model_id="mimo-v2.5",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )
        video_payload = {
            "phase_segments": [
                {"start_sec": 0.0, "end_sec": 0.5, "phase": "èµ·è·³", "confidence": 0.9},
            ],
            "pure_vision_subscores": {"takeoff_power": 88},
            "action_phase_summary": {
                "detected_phases": ["èµ·è·³"],
                "weakest_phase": "è½å†°",
                "strongest_phase": "èµ·è·³",
            },
            "overall_raw_text": "path a mimo video",
        }

        with patch(
            "app.services.vision_path_a.request_mimo_video_completion",
            AsyncMock(return_value=json.dumps(video_payload, ensure_ascii=False)),
        ) as video_mock:
            result = await analyze_path_a(
                "è·³è·ƒ",
                frame_payloads,
                provider,
                mode="video",
                clip_path=Path("clip.mp4"),
                window_start_sec=3.0,
            )

        self.assertEqual(result["path"], "A")
        self.assertEqual(result["vision_mode"], "video")
        video_mock.assert_awaited_once()


    async def test_path_a_video_prompt_uses_only_phase_segment_schema(self) -> None:
        frames = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA")]
        provider = SimpleNamespace(provider="qwen", api_key="test-key", base_url="https://example.com/v1", model_id="test-model")
        payload = {"phase_segments": [], "pure_vision_subscores": {}, "action_phase_summary": {}, "overall_raw_text": "ok"}

        with patch(
            "app.services.vision_path_a.request_dashscope_video_completion",
            AsyncMock(return_value=json.dumps(payload)),
        ) as video_mock:
            await analyze_path_a(
                "jump",
                frames,
                provider,
                mode="video",
                clip_path=Path("clip.mp4"),
                video_context_by_frame={
                    "frame_0001": {
                        "confirmed_action": "Axel",
                        "phase_label": "起跳",
                        "timestamp_sec": 0.2,
                    }
                },
            )

        user_prompt = video_mock.await_args.kwargs["user_prompt"]
        self.assertEqual(user_prompt.count('"phase_segments"'), 1)
        self.assertNotIn("每个 frame_analysis 项", user_prompt)
        self.assertNotIn("video_context_note", user_prompt)
        self.assertIn("每个 phase_segments 项", user_prompt)

    async def test_path_a_video_failure_rebuilds_frame_prompt_for_image_fallback(self) -> None:
        frames = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=0.2)]
        provider = SimpleNamespace(provider="qwen", api_key="test-key", base_url="https://example.com/v1", model_id="test-model")
        fallback_payload = {
            "frame_analysis": [{"frame_id": "frame_0001", "phase": "起跳", "confidence": 0.8}],
            "pure_vision_subscores": {},
            "action_phase_summary": {},
            "overall_raw_text": "fallback",
        }

        with (
            patch(
                "app.services.vision_path_a.request_dashscope_video_completion",
                AsyncMock(side_effect=TimeoutError("native video failed")),
            ),
            patch(
                "app.services.vision_path_a.request_text_completion",
                AsyncMock(return_value=json.dumps(fallback_payload, ensure_ascii=False)),
            ) as frame_mock,
        ):
            result = await analyze_path_a(
                "jump",
                frames,
                provider,
                mode="video",
                clip_path=Path("clip.mp4"),
                video_context_by_frame={"frame_0001": {"confirmed_action": "Axel", "timestamp_sec": 0.2}},
            )

        prompt_text = frame_mock.await_args.kwargs["messages"][1]["content"][0]["text"]
        content = frame_mock.await_args.kwargs["messages"][1]["content"]
        self.assertEqual(prompt_text.count('"frame_analysis"'), 1)
        self.assertNotIn("phase_segments", prompt_text)
        self.assertIn("每个 frame_analysis 项", prompt_text)
        self.assertTrue(any(item["type"] == "image_url" for item in content))
        self.assertIn("vision_fallback_to_frames", result["quality_flags"])
        self.assertEqual(result["vision_mode"], "frames")


if __name__ == "__main__":
    unittest.main()
