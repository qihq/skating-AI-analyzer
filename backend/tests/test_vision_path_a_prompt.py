from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video import FramePayload
from app.services.vision_path_a import analyze_path_a


class VisionPathAPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_path_a_excludes_biomechanics_evidence_but_keeps_motion_context(self) -> None:
        frame_payloads = [
            FramePayload(frame_id="frame_0004", data_url="data:image/jpeg;base64,AAA", timestamp_sec=0.4),
            FramePayload(frame_id="frame_0006", data_url="data:image/jpeg;base64,BBB", timestamp_sec=0.6),
        ]
        provider = SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")
        bio_data = {
            "analysis_profile": "jump",
            "key_frame_candidates": {
                "T": {"frame_id": "SKELETON_SENTINEL"},
            },
            "jump_metrics": {"estimated_rotation_turns": 9.99},
        }
        motion_features = {
            "sample_count": 9,
            "selected": [{"frame_id": "frame_0004", "motion_score": 0.95}],
        }
        response_payload = {
            "frame_analysis": [
                {
                    "frame_id": "frame_0004",
                    "phase": "èµ·è·³",
                    "observations": {"blade_edge": "ä¸å¯åˆ¤æ–­"},
                    "issues": ["åˆƒåž‹ä¸å¯è§"],
                    "positives": [],
                    "confidence": 0.55,
                }
            ],
            "action_phase_summary": {
                "detected_phases": ["èµ·è·³"],
                "weakest_phase": "è½å†°",
                "strongest_phase": "èµ·è·³",
            },
            "overall_raw_text": "ok",
        }

        with patch("app.services.vision_path_a.request_text_completion") as request_mock:
            request_mock.return_value = json.dumps(response_payload, ensure_ascii=False)

            result = await analyze_path_a(
                "jump",
                frame_payloads,
                provider,
                action_subtype="waltz jump",
                analysis_profile="jump",
                profile_evidence={
                    "mixed_jump_gate_passed": True,
                    "airborne_frames_detected": 7,
                    "relative_vertical_range": 0.91,
                    "hip_rotation_signal": 0.73,
                    "jump_subtype_evidence": {
                        "toe_pick_pulse": 0.2,
                        "sentinel": "PATH_A_PROFILE_EVIDENCE_SENTINEL",
                    },
                },
                bio_data=bio_data,
                motion_features=motion_features,
                mode="frames",
            )

        request_kwargs = request_mock.await_args.kwargs
        user_content = request_kwargs["messages"][1]["content"]
        prompt_text = user_content[0]["text"]
        system_prompt = request_kwargs["messages"][0]["content"]

        self.assertNotIn("candidate_key_frames", prompt_text)
        self.assertIn("Free Skate 1", prompt_text)
        self.assertIn("JSON schema:", prompt_text)
        self.assertNotIn("SKELETON_SENTINEL", prompt_text)
        self.assertNotIn("estimated_rotation_turns", prompt_text)
        self.assertNotIn("biomechanics:", prompt_text)
        self.assertNotIn("profile_evidence", prompt_text)
        self.assertNotIn("PATH_A_PROFILE_EVIDENCE_SENTINEL", prompt_text)
        self.assertNotIn("hip_rotation_signal", prompt_text)
        self.assertIn('"motion_score": 0.95', prompt_text)
        self.assertIn("element_confidence<=0.55", prompt_text)
        self.assertIn("不引入骨架或测量数据", system_prompt)
        self.assertEqual(result["path"], "A")
        self.assertEqual(len(result["frame_analysis"]), 2)
        self.assertIn("phase", result["frame_analysis"][0])
        self.assertEqual(result["frame_analysis"][1]["frame_id"], "frame_0006")


if __name__ == "__main__":
    unittest.main()
