from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report import generate_report


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


def _report_json(data_quality: str = "good") -> str:
    return f"""
    {{
      "summary": "动作节奏清楚，落冰还可以更柔和。",
      "issues": [{{"category":"落冰","description":"落冰缓冲略硬","severity":"medium","phase":"落冰","frames":["semantic_0003"]}}],
      "improvements": [{{"target":"落冰缓冲","action":"练习软膝盖落冰停住"}}],
      "training_focus": "稳定起跳节奏和落冰缓冲。",
      "subscores": {{
        "takeoff_power": 76,
        "rotation_axis": 72,
        "arm_coordination": 74,
        "landing_absorption": 68,
        "core_stability": 73
      }},
      "data_quality": "{data_quality}"
    }}
    """


class ReportVideoTemporalContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_prompt_includes_video_image_and_mediapipe_evidence_layers(self) -> None:
        request_mock = AsyncMock(return_value=_report_json())
        vision_structured = {
            "frame_analysis": [
                {
                    "frame_id": "semantic_0002",
                    "phase": "腾空",
                    "confidence": 0.86,
                    "phase_verification": "shifted",
                    "conflict_with_video_context": True,
                    "video_context_note": "画面更接近起跳末段，不是腾空稳定点",
                    "issues": ["轴心略向左偏"],
                }
            ]
        }
        dual_path_meta = {
            "overall_agreement_rate": 0.78,
            "skeleton_reliability_signal": "reliable",
            "recommended_path": "blend",
            "video_temporal": {
                "schema_version": "video_temporal_v1",
                "provider": "qwen",
                "model": "qwen3.6-plus",
                "confidence": 0.82,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {"confirmed_action": "Axel", "confidence": 0.8},
                "phase_segments": [
                    {
                        "phase_code": "air",
                        "phase_label": "腾空",
                        "time_start": 2.4,
                        "time_end": 2.8,
                        "key_frame_hint": 2.62,
                        "confidence": 0.76,
                    }
                ],
                "macro_assessment": {
                    "timing_rhythm": "起跳节奏比较连贯",
                    "axis_overall": "整体轴心略向左偏，但滑出可控",
                },
                "overall_impression": "整体完成度适合儿童初级继续打磨。",
            },
            "resolved_keyframes": {
                "source": "video_ai_refined",
                "confidence": 0.82,
                "selected": [
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 2.61,
                        "phase_code": "air",
                        "phase_label": "腾空",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_motion_peak",
                    }
                ],
            },
        }
        bio_data = {
            "jump_metrics": {"axis_tilt_deg": 9.5, "landing_knee_angle_deg": 142},
            "bio_subscores": {"rotation_axis": 70, "landing_absorption": 66},
        }

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            report = await generate_report("Axel", vision_structured, bio_data=bio_data, dual_path_meta=dual_path_meta)

        prompt = request_mock.await_args.kwargs["messages"][1]["content"]
        self.assertIn("视频语义时序融合参考", prompt)
        self.assertIn("video_temporal", prompt)
        self.assertIn("macro_assessment", prompt)
        self.assertIn("overall_impression", prompt)
        self.assertIn('"source": "video_ai_refined"', prompt)
        self.assertIn("conflict_with_video_context", prompt)
        self.assertIn("画面更接近起跳末段", prompt)
        self.assertIn("MediaPipe/bio_data", prompt)
        self.assertIn("图片路优先但保留差异", prompt)
        self.assertIn("axis_tilt_deg", prompt)
        self.assertEqual(report["data_quality"], "good")

    async def test_severe_video_context_conflict_downgrades_good_report_quality(self) -> None:
        request_mock = AsyncMock(return_value=_report_json(data_quality="good"))
        dual_path_meta = {
            "conflict_level": "high",
            "needs_human_review": True,
            "video_temporal": {
                "schema_version": "video_temporal_v1",
                "macro_assessment": {"speed_flow": "速度保持尚可"},
                "overall_impression": "视频路认为阶段完整。",
            },
            "resolved_keyframes": {"source": "blended", "selected": []},
        }
        vision_structured = {
            "frame_analysis": [
                {
                    "frame_id": "semantic_0001",
                    "phase": "起跳",
                    "confidence": 0.8,
                    "phase_verification": "disagree",
                    "conflict_with_video_context": True,
                    "video_context_note": "图片更像准备阶段，关键帧可能提前。",
                }
            ]
        }

        with (
            patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
            patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
            patch("app.services.report.request_text_completion", request_mock),
        ):
            report = await generate_report("jump", vision_structured, bio_data=None, dual_path_meta=dual_path_meta)

        prompt = request_mock.await_args.kwargs["messages"][1]["content"]
        self.assertIn("将 data_quality 降为 partial 或 poor", prompt)
        self.assertEqual(report["data_quality"], "partial")


if __name__ == "__main__":
    unittest.main()
