from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.target_lock import build_target_lock_payload, build_target_preview, select_stable_target_candidate, validate_manual_bbox


class TargetLockTests(unittest.TestCase):
    def test_build_target_lock_payload_accepts_manual_bbox(self) -> None:
        preview = build_target_preview("analysis-1", ["frame_0001.jpg"])

        payload = build_target_lock_payload(preview, manual_bbox={"x": 0.2, "y": 0.1, "w": 0.3, "h": 0.5})

        self.assertEqual(payload["status"], "manual")
        self.assertTrue(payload["manual_override"])
        self.assertEqual(payload["lock_confidence"], 1.0)
        self.assertEqual(payload["selected_bbox"], {"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.5})
        self.assertEqual(payload["candidates"], preview.candidates)
        self.assertEqual(payload["preview_frame_index"], 0)

    def test_low_confidence_fallback_candidate_is_not_auto_selected_bbox(self) -> None:
        preview = build_target_preview("analysis-1", ["frame_0001.jpg"])

        payload = build_target_lock_payload(preview)

        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertEqual(payload["selected_candidate_id"], "fallback_center")
        self.assertIsNone(payload["selected_bbox"])
        self.assertFalse(payload["manual_override"])

    def test_build_target_lock_payload_preserves_existing_preview_frame_index(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"],
            existing_target_lock={"preview_frame": "frame_0002.jpg", "status": "manual"},
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0003", "timestamp": 2.0, "motion_score": 1.0},
                ]
            },
        )

        payload = build_target_lock_payload(preview, manual_bbox={"x": 0.2, "y": 0.1, "w": 0.3, "h": 0.5})

        self.assertEqual(preview.preview_frame, "frame_0002.jpg")
        self.assertEqual(preview.preview_frame_index, 1)
        self.assertEqual(payload["preview_frame_index"], 1)

    def test_build_target_preview_uses_highest_motion_selected_frame_as_anchor(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg", "frame_0004.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 0.2, "motion_score": 0.1},
                    {"frame_id": "frame_0003", "timestamp": 0.6, "motion_score": 0.95},
                    {"frame_id": "frame_0004", "timestamp": 0.8, "motion_score": 0.6},
                ]
            },
        )

        self.assertEqual(preview.preview_frame, "frame_0003.jpg")
        self.assertEqual(preview.preview_frame_index, 2)

    def test_build_target_preview_adds_low_confidence_fallback_candidate(self) -> None:
        preview = build_target_preview("analysis-1", ["frame_0001.jpg"])

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "fallback_center")
        self.assertEqual(preview.lock_confidence, 0.22)
        self.assertEqual(preview.candidates[0]["source"], "layout_fallback")
        self.assertLess(preview.lock_confidence, 0.72)

    def test_build_target_preview_rejects_all_low_confidence_candidates(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg"],
            existing_target_lock={
                "candidates": [
                    {
                        "id": "candidate_low",
                        "bbox": {"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.5},
                        "confidence": 0.14,
                        "source": "detector",
                    }
                ]
            },
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "fallback_center")
        self.assertEqual(preview.lock_confidence, 0.22)

    def test_build_target_preview_uses_detected_candidate_before_fallback(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "detected_1",
                    "bbox": {"x": 0.35, "y": 0.2, "width": 0.16, "height": 0.42},
                    "confidence": 0.86,
                    "source": "yolo_preview",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.preview_frame, "frame_0002.jpg")
        self.assertEqual(preview.preview_frame_index, 1)
        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "detected_1")
        self.assertEqual(preview.lock_confidence, 0.86)
        self.assertEqual(preview.candidates[0]["source"], "yolo_preview")

        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "auto_locked")
        self.assertEqual(payload["selected_bbox"], {"x": 0.35, "y": 0.2, "width": 0.16, "height": 0.42})

    def test_build_target_preview_refreshes_unconfirmed_existing_fallback(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            existing_target_lock={
                "status": "awaiting_manual",
                "selected_candidate_id": "fallback_center",
                "lock_confidence": 0.22,
                "candidates": [
                    {
                        "id": "fallback_center",
                        "bbox": {"x": 0.4, "y": 0.24, "width": 0.2, "height": 0.42},
                        "confidence": 0.22,
                        "source": "layout_fallback",
                    }
                ],
            },
            detected_candidates=[
                {
                    "id": "detected_1",
                    "bbox": {"x": 0.35, "y": 0.2, "width": 0.16, "height": 0.42},
                    "confidence": 0.86,
                    "source": "yolo_preview",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "detected_1")
        self.assertEqual(preview.lock_confidence, 0.86)
        self.assertEqual(preview.candidates[0]["id"], "detected_1")

    def test_build_target_preview_prefers_stable_zoomed_target_over_single_foreground_person(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "foreground",
                    "bbox": {"x": 0.34, "y": 0.06, "width": 0.31, "height": 0.91},
                    "confidence": 0.91,
                    "source": "yolo_preview",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "stable_small",
                    "bbox": {"x": 0.40, "y": 0.36, "width": 0.07, "height": 0.19},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "support_count": 4,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "stable_small")
        self.assertEqual(preview.lock_confidence, 0.88)
        self.assertEqual(preview.candidates[0]["id"], "stable_small")
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["selected_candidate_id"], "stable_small")
        self.assertEqual(payload["selected_bbox"], {"x": 0.40, "y": 0.36, "width": 0.07, "height": 0.19})

    def test_build_target_preview_prefers_high_confidence_full_body_over_tiny_stable_box(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.6258, "y": 0.4159, "width": 0.0208, "height": 0.0859},
                    "confidence": 0.5909,
                    "source": "yolo_zoomed_content",
                    "support_count": 34,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "anchor_9_candidate_1",
                    "bbox": {"x": 0.4434, "y": 0.2562, "width": 0.1628, "height": 0.7387},
                    "confidence": 0.918,
                    "source": "yolo_preview",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "anchor_8_candidate_1",
                    "bbox": {"x": 0.4471, "y": 0.259, "width": 0.158, "height": 0.7288},
                    "confidence": 0.9084,
                    "source": "yolo_preview",
                    "anchor_frame": "frame_0001.jpg",
                    "anchor_index": 0,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_9_candidate_1")
        self.assertEqual(preview.lock_confidence, 0.918)
        self.assertEqual(preview.candidates[0]["id"], "anchor_9_candidate_1")
        self.assertIn("target_lock_complete_body_candidate_preferred_over_tiny_stable", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["selected_candidate_id"], "anchor_9_candidate_1")
        self.assertEqual(payload["selected_bbox"], {"x": 0.4434, "y": 0.2562, "width": 0.1628, "height": 0.7387})

    def test_build_target_preview_auto_locks_stable_zoomed_candidate_just_below_global_threshold(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.3854, "y": 0.2043, "width": 0.0727, "height": 0.2868},
                    "confidence": 0.7113,
                    "source": "yolo_zoomed_content",
                    "support_count": 8,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.lock_confidence, 0.7113)
        self.assertIn("target_lock_stable_zoomed_candidate_auto_locked", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "auto_locked")
        self.assertEqual(payload["selected_bbox"], {"x": 0.3854, "y": 0.2043, "width": 0.0727, "height": 0.2868})

    def test_build_target_preview_auto_locks_high_support_zoomed_candidate_near_global_threshold(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4231, "y": 0.2, "width": 0.165, "height": 0.6461},
                    "confidence": 0.7171,
                    "source": "yolo_zoomed_content",
                    "support_count": 32,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.lock_confidence, 0.7171)
        self.assertIn("target_lock_stable_zoomed_near_threshold_auto_locked", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "auto_locked")
        self.assertEqual(payload["selected_bbox"], {"x": 0.4231, "y": 0.2, "width": 0.165, "height": 0.6461})

    def test_build_target_preview_auto_locks_stable_zoomed_candidate_by_aggregate_confidence(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.6198, "y": 0.456, "width": 0.0382, "height": 0.194},
                    "confidence": 0.4304,
                    "source": "yolo_zoomed_content",
                    "support_count": 34,
                    "support_frame_count": 10,
                    "support_confidence": 0.86,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertGreaterEqual(preview.lock_confidence, 0.78)
        self.assertIn("target_lock_stable_zoomed_aggregate_confidence_auto_locked", preview.candidates[0]["quality_flags"])
        self.assertEqual(preview.candidates[0]["support_frame_count"], 10)
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "auto_locked")
        self.assertIsNotNone(payload["selected_bbox"])
        self.assertGreaterEqual(payload["lock_confidence"], 0.78)
        self.assertIn("target_lock_stable_zoomed_aggregate_confidence_auto_locked", payload["quality_flags"])

    def test_build_target_preview_requires_manual_for_ambiguous_zoomed_people(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.6066, "y": 0.2, "width": 0.0486, "height": 0.2605},
                    "confidence": 0.8975,
                    "source": "yolo_zoomed_content",
                    "support_count": 35,
                    "support_frame_count": 9,
                    "support_confidence": 0.8743,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "other_zoomed_person",
                    "bbox": {"x": 0.4804, "y": 0.2676, "width": 0.032, "height": 0.1201},
                    "confidence": 0.8614,
                    "source": "yolo_zoomed_content",
                    "support_count": 35,
                    "support_frame_count": 9,
                    "support_confidence": 0.8743,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_zoomed_multiperson_manual_review", payload["quality_flags"])

    def test_build_target_preview_requires_manual_when_any_anchor_frame_has_multiple_zoomed_people(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg", "frame_0004.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4402, "y": 0.2001, "width": 0.0484, "height": 0.234},
                    "confidence": 0.909,
                    "source": "yolo_zoomed_content",
                    "support_count": 32,
                    "support_frame_count": 7,
                    "support_confidence": 0.8571,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "other_anchor_person_1",
                    "bbox": {"x": 0.3828, "y": 0.2, "width": 0.0502, "height": 0.1524},
                    "confidence": 0.8741,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0004.jpg",
                    "anchor_index": 3,
                },
                {
                    "id": "other_anchor_person_2",
                    "bbox": {"x": 0.5354, "y": 0.237, "width": 0.0303, "height": 0.1245},
                    "confidence": 0.8685,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0004.jpg",
                    "anchor_index": 3,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_zoomed_multiperson_manual_review", payload["quality_flags"])

    def test_select_stable_target_candidate_computes_frame_level_support_confidence(self) -> None:
        candidates = []
        for index, confidence in enumerate([0.84, 0.90, 0.88, 0.86, 0.83, 0.81, 0.89, 0.87, 0.85, 0.82], start=1):
            candidates.append(
                {
                    "id": f"anchor_{index}_candidate_1",
                    "bbox": {"x": 0.50 + index * 0.002, "y": 0.44, "width": 0.038, "height": 0.12},
                    "confidence": confidence,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": f"frame_{index:04d}.jpg",
                    "anchor_index": index - 1,
                }
            )

        selected = select_stable_target_candidate(candidates)

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected["support_count"], 10)
        self.assertEqual(selected["support_frame_count"], 10)
        self.assertGreaterEqual(selected["support_confidence"], 0.85)

    def test_build_target_preview_does_not_auto_lock_high_support_large_foreground_near_threshold(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_large_foreground",
                    "bbox": {"x": 0.2, "y": 0.05, "width": 0.34, "height": 0.78},
                    "confidence": 0.7171,
                    "source": "yolo_zoomed_content",
                    "support_count": 32,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_large_foreground")
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_does_not_auto_lock_low_confidence_even_with_high_support(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_weak_stable",
                    "bbox": {"x": 0.4459, "y": 0.5088, "width": 0.0347, "height": 0.0947},
                    "confidence": 0.4089,
                    "source": "yolo_zoomed_content",
                    "support_count": 32,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_weak_stable")
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_manual_review_low_confidence", payload["quality_flags"])
        self.assertIn("target_lock_tiny_zoomed_low_support_manual_review", payload["quality_flags"])

    def test_build_target_preview_does_not_auto_lock_weak_aggregate_support(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4601, "y": 0.5922, "width": 0.033, "height": 0.0685},
                    "confidence": 0.462,
                    "source": "yolo_zoomed_content",
                    "support_count": 4,
                    "support_frame_count": 3,
                    "support_confidence": 0.5642,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_manual_review_low_confidence", payload["quality_flags"])

    def test_build_target_preview_does_not_auto_lock_single_low_confidence_zoomed_candidate(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_weak_zoomed",
                    "bbox": {"x": 0.38, "y": 0.20, "width": 0.07, "height": 0.28},
                    "confidence": 0.69,
                    "source": "yolo_zoomed_content",
                    "support_count": 1,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_weak_zoomed")
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_does_not_auto_lock_tiny_zoomed_single_high_confidence_box(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "tiny_high_confidence",
                    "bbox": {"x": 0.484, "y": 0.5488, "width": 0.0204, "height": 0.0893},
                    "confidence": 0.7955,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_tiny_zoomed_low_support_manual_review", payload["quality_flags"])

    def test_build_target_preview_auto_locks_distant_single_jump_candidate(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"],
            analysis_profile="jump",
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4601, "y": 0.5922, "width": 0.033, "height": 0.0685},
                    "confidence": 0.462,
                    "source": "yolo_zoomed_content",
                    "support_count": 5,
                    "support_frame_count": 3,
                    "support_confidence": 0.5642,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertIn("target_lock_distant_single_jump_auto_locked", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_tiny_zoomed_low_support_manual_review", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "auto_locked")
        self.assertEqual(payload["selected_bbox"], {"x": 0.4601, "y": 0.5922, "width": 0.033, "height": 0.0685})
        self.assertIn("target_lock_distant_single_jump_auto_locked", payload["quality_flags"])

    def test_build_target_preview_does_not_auto_lock_distant_single_candidate_for_spiral(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"],
            analysis_profile="spiral",
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4601, "y": 0.5922, "width": 0.033, "height": 0.0685},
                    "confidence": 0.462,
                    "source": "yolo_zoomed_content",
                    "support_count": 5,
                    "support_frame_count": 3,
                    "support_confidence": 0.5642,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_manual_review_low_confidence", payload["quality_flags"])

    def test_build_target_preview_does_not_auto_lock_distant_jump_when_competing_person_exists(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"],
            analysis_profile="jump",
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4601, "y": 0.5922, "width": 0.033, "height": 0.0685},
                    "confidence": 0.462,
                    "source": "yolo_zoomed_content",
                    "support_count": 5,
                    "support_frame_count": 3,
                    "support_confidence": 0.5642,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "other_person",
                    "bbox": {"x": 0.20, "y": 0.30, "width": 0.05, "height": 0.12},
                    "confidence": 0.72,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])
        self.assertNotIn("target_lock_distant_single_jump_auto_locked", payload["quality_flags"])

    def test_validate_manual_bbox_rejects_tiny_bbox(self) -> None:
        with self.assertRaises(AnalysisPipelineError) as raised:
            validate_manual_bbox({"x": 0.2, "y": 0.1, "w": 0.01, "h": 0.5})

        self.assertEqual(raised.exception.code, AnalysisErrorCode.TARGET_BBOX_INVALID)


if __name__ == "__main__":
    unittest.main()
