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


class VisionPhaseVotingTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_frames_merges_two_votes_and_records_metadata(self) -> None:
        frame_payloads = [
            FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA"),
            FramePayload(frame_id="frame_0002", data_url="data:image/jpeg;base64,BBB"),
        ]
        provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")
        first = {
            "frame_analysis": [
                {
                    "frame_id": "frame_0001",
                    "phase": "起跳",
                    "observations": {"knee_bend": "充分"},
                    "issues": ["节奏略急"],
                    "positives": ["起跳清晰"],
                    "confidence": 0.8,
                },
                {"frame_id": "frame_0002", "phase": "腾空", "issues": ["手臂稍散"], "confidence": 0.6},
            ],
            "action_phase_summary": {"detected_phases": ["起跳", "腾空"], "weakest_phase": "腾空", "strongest_phase": "起跳"},
            "overall_raw_text": "vote one",
        }
        second = {
            "frame_analysis": [
                {
                    "frame_id": "frame_0001",
                    "phase": "起跳",
                    "observations": {"arm_position": "正确"},
                    "issues": ["节奏略急"],
                    "positives": ["蹬冰清楚"],
                    "confidence": 1.0,
                },
                {"frame_id": "frame_0002", "phase": "落冰", "issues": ["手臂偏散"], "confidence": 0.8},
            ],
            "action_phase_summary": {"detected_phases": ["起跳", "落冰"], "weakest_phase": "落冰", "strongest_phase": "起跳"},
            "overall_raw_text": "vote two",
        }

        with (
            patch("app.services.vision.get_active_provider", AsyncMock(return_value=provider)),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch(
                "app.services.vision.request_text_completion",
                AsyncMock(side_effect=[json.dumps(first, ensure_ascii=False), json.dumps(second, ensure_ascii=False)]),
            ) as request_mock,
        ):
            result = await analyze_frames(
                "跳跃",
                frame_payloads,
                mode="frames",
                n_votes=2,
                vote_temperature=0.2,
                analysis_profile="jump",
            )

        self.assertEqual(request_mock.await_count, 2)
        self.assertEqual(result["vision_mode"], "frames_voted")
        self.assertEqual(result["vote_metadata"]["n_votes_requested"], 2)
        self.assertEqual(result["vote_metadata"]["n_votes_valid"], 2)
        self.assertEqual(result["frame_analysis"][0]["phase"], "起跳")
        self.assertEqual(result["frame_analysis"][0]["confidence"], 0.9)
        self.assertEqual(result["frame_analysis"][1]["phase_votes"], {"腾空": 1, "落冰": 1})
        self.assertIn("vision_self_consistency_vote", result["quality_flags"])
        self.assertIn("手臂稍散", result["frame_analysis"][1]["issues"])
        self.assertIn("手臂偏散", result["frame_analysis"][1]["issues"])

    async def test_analyze_frames_merges_qwen_and_doubao_provider_votes(self) -> None:
        frame_payloads = [
            FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA"),
            FramePayload(frame_id="frame_0002", data_url="data:image/jpeg;base64,BBB"),
        ]
        qwen = SimpleNamespace(
            id="qwen",
            slot="vision",
            name="qwen",
            provider="qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_id="qwen3.6-plus",
            vision_model=None,
            api_key="qwen-key",
            notes=None,
        )
        doubao = SimpleNamespace(
            id="doubao",
            slot="vision",
            name="doubao",
            provider="doubao",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            model_id="doubao-1.5-vision-pro-32k",
            vision_model=None,
            api_key="doubao-key",
            notes=None,
        )
        takeoff = "\u8d77\u8df3"
        airborne = "\u817e\u7a7a"
        landing = "\u843d\u51b0"
        qwen_payload = {
            "frame_analysis": [
                {"frame_id": "frame_0001", "phase": takeoff, "issues": ["Lutz edge unstable"], "confidence": 0.8},
                {"frame_id": "frame_0002", "phase": airborne, "issues": ["arms open"], "confidence": 0.7},
            ],
            "action_phase_summary": {"detected_phases": [takeoff, airborne], "weakest_phase": airborne, "strongest_phase": takeoff},
            "overall_raw_text": "qwen",
        }
        doubao_payload = {
            "frame_analysis": [
                {"frame_id": "frame_0001", "phase": takeoff, "issues": ["Flip edge inside"], "confidence": 0.9},
                {"frame_id": "frame_0002", "phase": landing, "issues": ["landing absorption weak"], "confidence": 0.6},
            ],
            "action_phase_summary": {"detected_phases": [takeoff, landing], "weakest_phase": landing, "strongest_phase": takeoff},
            "overall_raw_text": "doubao",
        }

        with (
            patch("app.services.vision.get_vision_providers", AsyncMock(return_value=[qwen, doubao])),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch(
                "app.services.vision.request_text_completion",
                AsyncMock(side_effect=[json.dumps(qwen_payload, ensure_ascii=False), json.dumps(doubao_payload, ensure_ascii=False)]),
            ) as request_mock,
        ):
            result = await analyze_frames("\u8df3\u8dc3", frame_payloads, mode="frames", n_votes=3, analysis_profile="jump")

        self.assertEqual(request_mock.await_count, 2)
        self.assertEqual(result["vision_mode"], "frames_provider_voted")
        self.assertEqual(result["vote_metadata"]["n_votes_requested"], 2)
        self.assertEqual(result["vote_metadata"]["n_votes_valid"], 2)
        self.assertEqual(result["vote_metadata"]["providers"], ["qwen", "doubao"])
        self.assertEqual(result["frame_analysis"][0]["phase"], takeoff)
        self.assertEqual(result["frame_analysis"][1]["phase_votes"], {airborne: 1, landing: 1})
        self.assertIn("Lutz edge unstable", result["frame_analysis"][0]["issues"])
        self.assertIn("Flip edge inside", result["frame_analysis"][0]["issues"])


if __name__ == "__main__":
    unittest.main()
