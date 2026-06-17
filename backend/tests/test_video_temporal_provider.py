from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.video_temporal import VIDEO_TEMPORAL_MAX_TOKENS, analyze_video_temporal


def _qwen_provider(model_id: str = "qwen-vl-max-latest") -> SimpleNamespace:
    return SimpleNamespace(
        id="vision-provider",
        slot="vision",
        name="qwen",
        provider="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_id=model_id,
        vision_model=None,
        api_key="test-key",
        notes=None,
    )


def _mimo_provider(model_id: str = "mimo-v2.5") -> SimpleNamespace:
    return SimpleNamespace(
        id="mimo-provider",
        slot="vision",
        name="mimo",
        provider="mimo",
        base_url="https://api.xiaomimimo.com/v1",
        model_id=model_id,
        vision_model=None,
        api_key="test-key",
        notes=None,
    )


def _valid_temporal_response() -> dict[str, object]:
    return {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {
            "action_family": "jump",
            "confirmed_action": "Axel",
            "jump_type": "Axel",
            "confidence": 0.86,
            "notes": "",
        },
        "phase_segments": [
            {"phase_code": "takeoff", "phase_label": "起跳", "time_start": 1.0, "time_end": 1.3, "key_frame_hint": 1.16, "confidence": 0.82},
            {"phase_code": "air", "phase_label": "腾空", "time_start": 1.3, "time_end": 1.6, "key_frame_hint": 1.45, "confidence": 0.84},
            {"phase_code": "landing", "phase_label": "落冰", "time_start": 1.6, "time_end": 2.0, "key_frame_hint": 1.75, "confidence": 0.81},
        ],
        "key_moments": {"T_takeoff_sec": 1.16, "A_air_sec": 1.45, "L_landing_sec": 1.75},
        "macro_assessment": {
            "timing_rhythm": "节奏清楚",
            "speed_flow": "速度适中",
            "axis_overall": "轴心基本可控",
            "entry_quality": "入跳稳定",
            "exit_or_landing_quality": "落冰能继续滑出",
            "top_strengths": ["完成积极"],
            "top_issues": ["手臂收紧可更快"],
        },
        "overall_impression": "整体完成积极，适合继续练习。",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.86,
        "fallback_recommendation": "use_video_timestamps",
        "quality_flags": [],
    }


class VideoTemporalProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_video_temporal_uses_qwen_36_plus_and_normalizes_response(self) -> None:
        request_mock = AsyncMock(return_value=json.dumps(_valid_temporal_response(), ensure_ascii=False))

        with patch("app.services.video_temporal.request_dashscope_video_completion", request_mock):
            result = await analyze_video_temporal(
                Path("clip.mp4"),
                action_type="jump",
                action_subtype="Axel",
                video_duration_sec=3.0,
                source_fps=30.0,
                provider=_qwen_provider(),
            )

        self.assertTrue(result["valid"])
        self.assertEqual(result["provider"], "qwen")
        self.assertEqual(result["model"], "qwen3.6-plus")
        self.assertEqual(result["action_confirmation"]["confirmed_action"], "Axel")
        kwargs = request_mock.await_args.kwargs
        self.assertEqual(request_mock.await_args.args[0].model_id, "qwen3.6-plus")
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertEqual(kwargs["max_tokens"], VIDEO_TEMPORAL_MAX_TOKENS)
        self.assertGreaterEqual(kwargs["max_tokens"], 3200)
        self.assertIn("video_temporal_v1", kwargs["user_prompt"])
        self.assertIn("qwen3.6-plus", kwargs["user_prompt"])
        self.assertIn("只输出一个合法 JSON 对象", kwargs["system_prompt"])

    async def test_analyze_video_temporal_fetches_active_provider_when_not_supplied(self) -> None:
        request_mock = AsyncMock(return_value=json.dumps(_valid_temporal_response(), ensure_ascii=False))

        with (
            patch("app.services.video_temporal.get_active_provider", AsyncMock(return_value=_qwen_provider("qwen3.6-plus"))) as provider_mock,
            patch("app.services.video_temporal.request_dashscope_video_completion", request_mock),
        ):
            result = await analyze_video_temporal(
                Path("clip.mp4"),
                action_type="jump",
                video_duration_sec=3.0,
                source_fps=30.0,
            )

        self.assertTrue(result["valid"])
        provider_mock.assert_awaited_once()
        request_mock.assert_awaited_once()

    async def test_analyze_video_temporal_dispatches_to_mimo_provider(self) -> None:
        request_mock = AsyncMock(return_value=json.dumps(_valid_temporal_response(), ensure_ascii=False))

        with patch("app.services.video_temporal.request_mimo_video_completion", request_mock):
            result = await analyze_video_temporal(
                Path("clip.mp4"),
                action_type="jump",
                action_subtype="Axel",
                video_duration_sec=3.0,
                source_fps=30.0,
                provider=_mimo_provider(),
            )

        self.assertTrue(result["valid"])
        self.assertEqual(result["provider"], "mimo")
        self.assertEqual(result["model"], "mimo-v2.5")
        kwargs = request_mock.await_args.kwargs
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertEqual(kwargs["max_tokens"], VIDEO_TEMPORAL_MAX_TOKENS)
        self.assertGreaterEqual(kwargs["max_tokens"], 3200)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertIn("video_temporal_v1", kwargs["user_prompt"])
        self.assertIn("mimo-v2.5", kwargs["user_prompt"])

    async def test_analyze_video_temporal_passes_retry_context_to_prompt(self) -> None:
        request_mock = AsyncMock(return_value=json.dumps(_valid_temporal_response(), ensure_ascii=False))

        with patch("app.services.video_temporal.request_mimo_video_completion", request_mock):
            result = await analyze_video_temporal(
                Path("clip.mp4"),
                action_type="jump",
                action_subtype="Axel",
                video_duration_sec=3.0,
                source_fps=30.0,
                provider=_mimo_provider(),
                retry_context={
                    "retry_reason_flags": ["video_temporal_resolver_coherent_tal_motion_conflict_rejected"],
                    "rejected_key_moments": {"T_takeoff_sec": 1.0, "A_air_sec": 1.2, "L_landing_sec": 1.4},
                },
            )

        self.assertTrue(result["valid"])
        self.assertIn("QUALITY_GATE_RETRY_CONTEXT", request_mock.await_args.kwargs["user_prompt"])
        self.assertIn("rejected_key_moments", request_mock.await_args.kwargs["user_prompt"])

    async def test_analyze_video_temporal_offsets_action_window_clip_timestamps(self) -> None:
        request_mock = AsyncMock(return_value=json.dumps(_valid_temporal_response(), ensure_ascii=False))

        with patch("app.services.video_temporal.request_dashscope_video_completion", request_mock):
            result = await analyze_video_temporal(
                Path("action_window_ai.mp4"),
                action_type="jump",
                action_subtype="Axel",
                video_duration_sec=3.0,
                source_video_duration_sec=10.0,
                source_fps=15.0,
                timestamp_offset_sec=2.0,
                analyzed_video_kind="action_window_ai",
                provider=_qwen_provider("qwen3.6-plus"),
            )

        self.assertTrue(result["valid"])
        self.assertEqual(result["analyzed_video_kind"], "action_window_ai")
        self.assertEqual(result["timestamp_offset_sec"], 2.0)
        self.assertEqual(result["phase_segments"][0]["time_start"], 3.0)
        self.assertEqual(result["phase_segments"][0]["key_frame_hint"], 3.16)
        self.assertEqual(result["key_moments"]["T_takeoff_sec"], 3.16)
        self.assertEqual(result["key_moments"]["A_air_sec"], 3.45)
        self.assertEqual(result["key_moments"]["L_landing_sec"], 3.75)

    async def test_timeout_returns_fallback_diagnostic(self) -> None:
        request_mock = AsyncMock(
            side_effect=AnalysisPipelineError(AnalysisErrorCode.AI_API_TIMEOUT, "video request timeout")
        )

        with patch("app.services.video_temporal.request_dashscope_video_completion", request_mock):
            result = await analyze_video_temporal(
                Path("clip.mp4"),
                action_type="jump",
                video_duration_sec=3.0,
                source_fps=30.0,
                provider=_qwen_provider("qwen3.6-plus"),
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["fallback_recommendation"], "use_existing_skeleton_timestamps")
        self.assertEqual(result["fallback_reason"], "video_temporal_timeout")
        self.assertIn("video_temporal_timeout", result["quality_flags"])

    async def test_invalid_json_returns_parse_fallback_diagnostic(self) -> None:
        with patch(
            "app.services.video_temporal.request_dashscope_video_completion",
            AsyncMock(return_value="{not json"),
        ):
            result = await analyze_video_temporal(
                Path("clip.mp4"),
                action_type="jump",
                video_duration_sec=3.0,
                source_fps=30.0,
                provider=_qwen_provider("qwen3.6-plus"),
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["fallback_recommendation"], "use_existing_skeleton_timestamps")
        self.assertEqual(result["fallback_reason"], "video_temporal_parse_failed")
        self.assertIn("video_temporal_invalid_json", result["quality_flags"])
        self.assertIn("video_temporal_parse_failed", result["quality_flags"])
        self.assertEqual(result["raw_response_excerpt"], "{not json")
        self.assertEqual(result["raw_response_length"], len("{not json"))
        self.assertFalse(result["raw_response_truncated"])
        self.assertIsInstance(result["parse_error_detail"], str)

    async def test_unsupported_provider_is_soft_fallback_and_does_not_call_video_api(self) -> None:
        provider = SimpleNamespace(
            id="doubao-provider",
            slot="vision",
            name="doubao",
            provider="doubao",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            model_id="doubao-vision",
            vision_model=None,
            api_key="test-key",
            notes=None,
        )
        request_mock = AsyncMock()

        with (
            patch("app.services.video_temporal.request_dashscope_video_completion", request_mock),
            patch("app.services.video_temporal.request_mimo_video_completion", AsyncMock()) as mimo_mock,
        ):
            result = await analyze_video_temporal(
                Path("clip.mp4"),
                action_type="jump",
                video_duration_sec=3.0,
                source_fps=30.0,
                provider=provider,
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["fallback_reason"], "video_temporal_provider_not_qwen")
        self.assertIn("video_temporal_provider_not_qwen", result["quality_flags"])
        request_mock.assert_not_awaited()
        mimo_mock.assert_not_awaited()

    async def test_budget_error_returns_budget_fallback_flag(self) -> None:
        request_mock = AsyncMock(
            side_effect=AnalysisPipelineError(
                AnalysisErrorCode.AI_API_QUOTA_EXCEEDED,
                "Qwen vision video daily cost limit exceeded",
            )
        )

        with patch("app.services.video_temporal.request_dashscope_video_completion", request_mock):
            result = await analyze_video_temporal(
                Path("clip.mp4"),
                action_type="jump",
                video_duration_sec=3.0,
                source_fps=30.0,
                provider=_qwen_provider("qwen3.6-plus"),
            )

        self.assertFalse(result["valid"])
        self.assertEqual(result["fallback_reason"], "video_temporal_budget_exceeded")
        self.assertIn("video_temporal_budget_exceeded", result["quality_flags"])


if __name__ == "__main__":
    unittest.main()
