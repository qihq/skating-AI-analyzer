from __future__ import annotations

import json
import unittest

from app.services.vision_fusion import FUSION_VERSION, fuse_vision_results_weighted


TAKEOFF = "\u8d77\u8df3"
AIR = "\u817e\u7a7a"
LANDING = "\u843d\u51b0"


def _model(
    provider: str,
    phases: list[tuple[str, str, float]],
    *,
    data_quality_hint: str = "good",
    model_confidence: float | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider": provider,
        "model": f"{provider}-vision",
        "data_quality_hint": data_quality_hint,
        "frame_analysis": [
            {
                "frame_id": frame_id,
                "phase": phase,
                "confidence": confidence,
                "observations": {"blade_edge": "\u4e0d\u53ef\u5224\u65ad"},
                "issues": [f"{provider}:{phase}:issue"],
                "positives": [f"{provider}:{phase}:positive"],
            }
            for frame_id, phase, confidence in phases
        ],
        "action_phase_summary": {"detected_phases": [phase for _, phase, _ in phases]},
        "overall_raw_text": f"{provider} result",
    }
    if model_confidence is not None:
        payload["model_confidence"] = model_confidence
    if extra:
        payload.update(extra)
    return payload


def _bio_candidates() -> dict[str, object]:
    return {
        "quality_flags": [],
        "key_frame_candidates": {
            "T": {"frame_id": "frame_0001", "confidence": 0.92},
            "A": {"frame_id": "frame_0002", "confidence": 0.9},
            "L": {"frame_id": "frame_0003", "confidence": 0.9},
            "quality_flags": [],
        },
    }


class VisionFusionTests(unittest.TestCase):
    def test_consistent_models_fuse_without_conflict(self) -> None:
        payload = fuse_vision_results_weighted(
            [
                _model("qwen", [("frame_0001", TAKEOFF, 0.9), ("frame_0002", AIR, 0.86), ("frame_0003", LANDING, 0.84)]),
                _model("doubao", [("frame_0001", TAKEOFF, 0.85), ("frame_0002", AIR, 0.8), ("frame_0003", LANDING, 0.78)]),
            ],
            _bio_candidates(),
            "jump",
        )

        self.assertEqual(payload["fusion_version"], FUSION_VERSION)
        self.assertEqual(payload["conflict_level"], "none")
        self.assertEqual([frame["phase"] for frame in payload["final_frame_analysis"]], [TAKEOFF, AIR, LANDING])
        self.assertEqual(payload["fusion_decisions"][0]["phase_scores"].keys(), {TAKEOFF})
        self.assertGreater(payload["final_frame_analysis"][0]["confidence"], 0.99)
        json.dumps(payload, ensure_ascii=False)

    def test_conflicting_models_choose_highest_weighted_phase_with_evidence(self) -> None:
        payload = fuse_vision_results_weighted(
            [
                _model("qwen", [("frame_0001", TAKEOFF, 0.95)]),
                _model("doubao", [("frame_0001", LANDING, 0.45)]),
            ],
            None,
            "jump",
        )

        decision = payload["fusion_decisions"][0]

        self.assertEqual(payload["final_frame_analysis"][0]["phase"], TAKEOFF)
        self.assertIn(LANDING, decision["phase_scores"])
        self.assertEqual(decision["selected_phase"], TAKEOFF)
        self.assertIn(payload["conflict_level"], {"low", "medium", "high"})
        self.assertEqual(decision["evidence"]["supporting_providers"], ["qwen"])
        self.assertEqual(decision["evidence"]["opposing_providers"], ["doubao"])

    def test_low_quality_json_is_downweighted(self) -> None:
        low_quality = {
            "provider": "qwen",
            "frame_analysis": [
                {
                    "frame_id": "frame_0001",
                    "phase": LANDING,
                    "confidence": 0.99,
                }
            ],
        }
        good_quality = _model("doubao", [("frame_0001", TAKEOFF, 0.72)])

        payload = fuse_vision_results_weighted([low_quality, good_quality], None, "jump")
        qwen_candidate = next(
            candidate
            for candidate in payload["fusion_decisions"][0]["candidates"]
            if candidate["provider"] == "qwen"
        )

        self.assertEqual(payload["final_frame_analysis"][0]["phase"], TAKEOFF)
        self.assertLess(qwen_candidate["factors"]["json_validity_factor"], 0.5)
        self.assertIn("vision_quality_invalid_or_missing_data_quality_hint", qwen_candidate["json_warnings"])

    def test_rule_conflict_downweights_high_confidence_wrong_key_frame_phase(self) -> None:
        rule_conflicting = _model("qwen", [("frame_0001", LANDING, 0.98)])
        rule_consistent = _model("doubao", [("frame_0001", TAKEOFF, 0.68)])

        payload = fuse_vision_results_weighted([rule_conflicting, rule_consistent], _bio_candidates(), "jump")
        qwen_candidate = next(
            candidate
            for candidate in payload["fusion_decisions"][0]["candidates"]
            if candidate["provider"] == "qwen"
        )

        self.assertEqual(payload["final_frame_analysis"][0]["phase"], TAKEOFF)
        self.assertEqual(payload["conflict_level"], "high")
        self.assertIn("rule_high_confidence_key_frame_conflict", qwen_candidate["rule_flags"])
        self.assertLess(qwen_candidate["factors"]["rule_consistency_factor"], 0.5)


if __name__ == "__main__":
    unittest.main()
