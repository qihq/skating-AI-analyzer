from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.video import FramePayload
from app.services.vision import analyze_frames
from app.services.vision_fusion import FUSION_VERSION


TAKEOFF = "\u8d77\u8df3"
AIR = "\u817e\u7a7a"
LANDING = "\u843d\u51b0"


def _provider(provider_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=provider_name,
        slot="vision",
        name=provider_name,
        provider=provider_name,
        base_url="https://example.com/v1",
        model_id=f"{provider_name}-vision",
        vision_model=None,
        api_key=f"{provider_name}-key",
        notes=None,
    )


def _payload(phase: str, confidence: float, provider: str) -> dict[str, object]:
    return {
        "data_quality_hint": "good",
        "frame_analysis": [
            {
                "frame_id": "frame_0001",
                "phase": phase,
                "confidence": confidence,
                "observations": {"blade_edge": "\u4e0d\u53ef\u5224\u65ad"},
                "issues": [f"{provider}:{phase}:issue"],
                "positives": [f"{provider}:{phase}:positive"],
            }
        ],
        "action_phase_summary": {"detected_phases": [phase], "weakest_phase": phase, "strongest_phase": phase},
        "overall_raw_text": provider,
    }


class VisionWeightedFusionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_provider_frame_results_use_weighted_fusion_by_default(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA")]
        qwen = _provider("qwen")
        doubao = _provider("doubao")

        with (
            patch("app.services.vision.get_vision_providers", AsyncMock(return_value=[qwen, doubao])),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch(
                "app.services.vision.request_text_completion",
                AsyncMock(
                    side_effect=[
                        json.dumps(_payload(TAKEOFF, 0.95, "qwen"), ensure_ascii=False),
                        json.dumps(_payload(LANDING, 0.4, "doubao"), ensure_ascii=False),
                    ]
                ),
            ),
        ):
            result = await analyze_frames("\u8df3\u8dc3", frame_payloads, mode="frames", n_votes=2, analysis_profile="jump")

        self.assertEqual(result["vision_mode"], "frames_provider_voted")
        self.assertEqual(result["fusion_version"], FUSION_VERSION)
        self.assertEqual(result["vote_metadata"]["fusion_version"], FUSION_VERSION)
        self.assertIn("fusion_decisions", result)
        self.assertEqual(result["frame_analysis"][0]["phase"], TAKEOFF)
        self.assertEqual(result["frame_analysis"][0]["phase_votes"], {TAKEOFF: 1, LANDING: 1})
        self.assertIn("phase_scores", result["frame_analysis"][0])
        self.assertIn("vision_weighted_fusion", result["quality_flags"])

    async def test_weighted_fusion_failure_falls_back_to_legacy_vote_merge(self) -> None:
        frame_payloads = [FramePayload(frame_id="frame_0001", data_url="data:image/jpeg;base64,AAA")]
        qwen = _provider("qwen")
        doubao = _provider("doubao")

        with (
            patch("app.services.vision.get_vision_providers", AsyncMock(return_value=[qwen, doubao])),
            patch("app.services.vision.build_memory_context", AsyncMock(return_value="")),
            patch(
                "app.services.vision.request_text_completion",
                AsyncMock(
                    side_effect=[
                        json.dumps(_payload(TAKEOFF, 0.8, "qwen"), ensure_ascii=False),
                        json.dumps(_payload(AIR, 0.7, "doubao"), ensure_ascii=False),
                    ]
                ),
            ),
            patch("app.services.vision.fuse_vision_results_weighted", side_effect=RuntimeError("fusion failed")),
        ):
            result = await analyze_frames("\u8df3\u8dc3", frame_payloads, mode="frames", n_votes=2, analysis_profile="jump")

        self.assertNotIn("fusion_version", result)
        self.assertNotIn("fusion_decisions", result)
        self.assertEqual(result["frame_analysis"][0]["phase_votes"], {TAKEOFF: 1, AIR: 1})
        self.assertIn("vision_weighted_fusion_fallback_to_vote", result["quality_flags"])


if __name__ == "__main__":
    unittest.main()
