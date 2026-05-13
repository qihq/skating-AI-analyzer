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
            model_id="qwen-vl-max-latest",
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
            model_id="qwen-vl-max-latest",
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

    async def test_path_a_video_mode_preserves_path_fields(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=3.25)]
        provider = SimpleNamespace(
            id="vision-provider",
            slot="vision_path_a",
            name="qwen",
            provider="qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_id="qwen-vl-max-latest",
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


if __name__ == "__main__":
    unittest.main()
