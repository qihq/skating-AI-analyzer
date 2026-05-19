from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video import FramePayload
from app.services.vision import normalize_vision_payload
from app.services.vision_dual import analyze_frames_dual
from app.services.vision_path_a import analyze_path_a
from app.services.vision_path_b import analyze_path_b


def _provider() -> SimpleNamespace:
    return SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="qwen3.6-plus")


def _video_temporal() -> dict[str, object]:
    return {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {"confirmed_action": "Axel", "jump_type": "Axel"},
        "phase_segments": [
            {"phase_code": "takeoff", "phase_label": "起跳", "time_start": 1.0, "time_end": 1.4},
        ],
        "macro_assessment": {"axis_overall": "整体轴心略向左偏，但滑出可控"},
        "camera_view": "diagonal_front",
        "confidence": 0.78,
    }


def _resolved() -> dict[str, object]:
    return {
        "source": "video_ai_refined",
        "selected": [
            {
                "frame_id": "semantic_0001",
                "timestamp": 1.2,
                "phase_code": "takeoff",
                "phase_label": "起跳",
                "key_moment": "T_takeoff_sec",
            }
        ],
    }


class VisionVideoContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_path_a_prompt_includes_video_context_and_schema_fields(self) -> None:
        frames = [FramePayload(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.2)]
        response_payload = {
            "frame_analysis": [
                {
                    "frame_id": "semantic_0001",
                    "phase": "起跳",
                    "phase_verification": "agree",
                    "conflict_with_video_context": False,
                    "video_context_note": "语义帧与画面一致",
                    "confidence": 0.8,
                }
            ],
            "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
            "overall_raw_text": "ok",
        }

        with patch("app.services.vision_path_a.request_text_completion", AsyncMock(return_value=json.dumps(response_payload, ensure_ascii=False))) as request_mock:
            result = await analyze_path_a(
                "跳跃",
                frames,
                _provider(),
                analysis_profile="jump",
                mode="frames",
                video_context_by_frame={
                    "semantic_0001": {
                        "confirmed_action": "Axel",
                        "phase_label": "起跳",
                        "timestamp_sec": 1.2,
                        "phase_time_start": 1.0,
                        "phase_time_end": 1.4,
                        "key_moment": "T_takeoff_sec",
                        "macro_axis_overall": "整体轴心略向左偏，但滑出可控",
                        "camera_view": "diagonal_front",
                        "video_confidence": 0.78,
                    }
                },
            )

        content = request_mock.await_args.kwargs["messages"][1]["content"]
        prompt_text = content[0]["text"]
        self.assertIn("video_context", prompt_text)
        self.assertIn("phase_verification", prompt_text)
        self.assertIn("conflict_with_video_context", prompt_text)
        self.assertIn("刃面或入跳弧线不可见", prompt_text)
        self.assertIn("不要猜 Lutz/Flip 内外刃", prompt_text)
        self.assertIn("Axel", prompt_text)
        self.assertIn("video_context", content[2]["text"])
        self.assertEqual(result["frame_analysis"][0]["phase_verification"], "agree")
        self.assertFalse(result["frame_analysis"][0]["conflict_with_video_context"])
        self.assertEqual(result["frame_analysis"][0]["video_context_note"], "语义帧与画面一致")

    async def test_path_b_prompt_includes_video_context(self) -> None:
        frames = [FramePayload(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.2)]
        response_payload = {
            "frame_analysis": [
                {
                    "frame_id": "semantic_0001",
                    "phase": "起跳",
                    "phase_verification": "shifted",
                    "conflict_with_video_context": True,
                    "video_context_note": "画面更像准备末段",
                    "confidence": 0.7,
                }
            ],
            "subscores": {},
            "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
        }

        with patch("app.services.vision_path_b.request_text_completion", AsyncMock(return_value=json.dumps(response_payload, ensure_ascii=False))) as request_mock:
            result = await analyze_path_b(
                "跳跃",
                frames,
                _provider(),
                analysis_profile="jump",
                video_context_by_frame={
                    "semantic_0001": {
                        "confirmed_action": "Axel",
                        "phase_label": "起跳",
                        "timestamp_sec": 1.2,
                    }
                },
            )

        content = request_mock.await_args.kwargs["messages"][1]["content"]
        self.assertIn("video_context", content[0]["text"])
        self.assertIn("phase_verification", content[0]["text"])
        self.assertIn("不要猜 Lutz/Flip 内外刃", content[0]["text"])
        self.assertIn("video_context", content[1]["text"])
        self.assertEqual(result["frame_analysis"][0]["phase_verification"], "shifted")

    async def test_dual_path_builds_and_passes_video_context_to_both_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_path = root / "semantic_0001.jpg"
            frame_path.write_bytes(b"frame")
            raw_payloads = [FramePayload(frame_id="semantic_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=1.2)]
            mock_a = AsyncMock(return_value={"frame_analysis": [], "action_phase_summary": {}, "overall_raw_text": ""})
            mock_b = AsyncMock(return_value={"frame_analysis": [], "subscores": {}, "action_phase_summary": {}})

            with (
                patch("app.services.vision_dual.annotate_frames_batch", return_value=[frame_path]),
                patch("app.services.vision_dual.encode_frames", AsyncMock(return_value=raw_payloads)),
                patch("app.services.vision_dual.analyze_path_a", mock_a),
                patch("app.services.vision_dual.analyze_path_b", mock_b),
            ):
                await analyze_frames_dual(
                    "跳跃",
                    [frame_path],
                    raw_payloads,
                    {"frames": [], "connections": []},
                    {"quality_flags": []},
                    _provider(),
                    _provider(),
                    annotated_dir=root / "annotated",
                    video_temporal=_video_temporal(),
                    resolved_keyframes=_resolved(),
                )

        path_a_context = mock_a.await_args.kwargs["video_context_by_frame"]
        path_b_context = mock_b.await_args.kwargs["video_context_by_frame"]
        self.assertEqual(path_a_context["semantic_0001"]["confirmed_action"], "Axel")
        self.assertEqual(path_b_context["semantic_0001"]["phase_label"], "起跳")
        self.assertEqual(path_a_context["semantic_0001"]["phase_time_start"], 1.0)

    async def test_old_call_without_video_context_keeps_prompt_unchanged(self) -> None:
        frames = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA", timestamp_sec=0.5)]
        response_payload = {
            "frame_analysis": [{"frame_id": "frame_0001", "phase": "起跳", "confidence": 0.8}],
            "action_phase_summary": {"detected_phases": ["起跳"], "weakest_phase": "起跳", "strongest_phase": "起跳"},
            "overall_raw_text": "ok",
        }

        with patch("app.services.vision_path_a.request_text_completion", AsyncMock(return_value=json.dumps(response_payload, ensure_ascii=False))) as request_mock:
            await analyze_path_a("跳跃", frames, _provider(), mode="frames")

        prompt_text = request_mock.await_args.kwargs["messages"][1]["content"][0]["text"]
        self.assertNotIn("【video_context 语义帧上下文】", prompt_text)

    def test_normalize_vision_payload_preserves_video_context_fields(self) -> None:
        normalized = normalize_vision_payload(
            {
                "frame_analysis": [
                    {
                        "frame_id": "frame_0001",
                        "phase": "起跳",
                        "phase_verification": "bad-value",
                        "conflict_with_video_context": 1,
                        "video_context_note": "画面与视频上下文略有偏差",
                        "confidence": 0.8,
                    }
                ],
                "action_phase_summary": {"detected_phases": ["起跳"]},
            },
            [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA")],
        )

        frame = normalized["frame_analysis"][0]
        self.assertEqual(frame["phase_verification"], "uncertain")
        self.assertTrue(frame["conflict_with_video_context"])
        self.assertEqual(frame["video_context_note"], "画面与视频上下文略有偏差")


if __name__ == "__main__":
    unittest.main()
