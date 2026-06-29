from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.target_lock import (
    TargetPreview,
    _stable_zoomed_multiperson_background_auto_lock_allowed,
    _stable_zoomed_multiperson_background_auto_lock_blocked_flags,
    build_target_lock_payload,
    build_target_preview,
    select_stable_target_candidate,
    validate_manual_bbox,
)


class TargetPreviewRouteCacheTests(unittest.TestCase):
    def test_saved_target_lock_preview_reuses_candidates_without_detection(self) -> None:
        from app.routers.analysis import _build_target_preview_cached_first
        from app.models import Analysis

        analysis = Analysis(
            id="analysis-cache",
            action_type="jump",
            video_path="/tmp/source.mp4",
            status="awaiting_target_selection",
            target_lock_status="awaiting_manual",
            target_lock={
                "preview_frame": "frame_0002.jpg",
                "selected_candidate_id": "candidate-1",
                "lock_confidence": 0.61,
                "status": "awaiting_manual",
                "candidates": [
                    {
                        "id": "candidate-1",
                        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                        "confidence": 0.61,
                        "source": "cached",
                    }
                ],
            },
        )

        preview = _build_target_preview_cached_first(analysis, ["frame_0001.jpg", "frame_0002.jpg"], None)

        self.assertEqual(preview.preview_frame, "frame_0002.jpg")
        self.assertEqual(preview.auto_candidate_id, "candidate-1")
        self.assertEqual(preview.candidates[0]["source"], "cached")


class TargetLockTests(unittest.TestCase):
    @staticmethod
    def _zoomed_track_candidates(
        frame_names: list[str],
        *,
        selected_id: str,
        selected_frame_index: int,
        bbox: dict[str, float],
        support_count: int,
        selected_confidence: float,
        support_confidence: float,
        center_span: float,
    ) -> list[dict[str, object]]:
        selected_frame_index = max(0, min(selected_frame_index, len(frame_names) - 1))

        def bbox_for_slot(slot: int) -> dict[str, float]:
            if len(frame_names) <= 1:
                offset = 0.0
            else:
                offset = center_span * (slot / (len(frame_names) - 1))
            return {**bbox, "x": bbox["x"] + offset}

        candidates: list[dict[str, object]] = [
            {
                "id": selected_id,
                "bbox": bbox_for_slot(selected_frame_index),
                "confidence": selected_confidence,
                "source": "yolo_zoomed_content",
                "anchor_frame": frame_names[selected_frame_index],
                "anchor_index": selected_frame_index,
            }
        ]
        for index in range(max(0, support_count - 1)):
            slot = index % len(frame_names)
            candidates.append(
                {
                    "id": f"{selected_id}_support_{index}",
                    "bbox": bbox_for_slot(slot),
                    "confidence": support_confidence,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": frame_names[slot],
                    "anchor_index": slot,
                }
            )
        return candidates

    def test_build_target_lock_payload_accepts_manual_bbox(self) -> None:
        preview = build_target_preview("analysis-1", ["frame_0001.jpg"])

        payload = build_target_lock_payload(preview, manual_bbox={"x": 0.2, "y": 0.1, "w": 0.3, "h": 0.5})

        self.assertEqual(payload["status"], "manual")
        self.assertTrue(payload["manual_override"])
        self.assertEqual(payload["lock_confidence"], 1.0)
        self.assertEqual(payload["selected_bbox"], {"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.5})
        self.assertEqual(payload["candidates"], preview.candidates)
        self.assertEqual(payload["preview_frame_index"], 0)

    def test_build_target_lock_payload_marks_user_selected_candidate_as_manual_override(self) -> None:
        candidate = {
            "id": "candidate-main",
            "bbox": {"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.5},
            "confidence": 0.81,
            "source": "yolo_preview",
        }
        preview = TargetPreview(
            preview_frame="frame_0001.jpg",
            preview_frame_url="/api/frames/analysis-1/frame_0001.jpg",
            preview_frame_index=0,
            auto_candidate_id="candidate-main",
            lock_confidence=0.81,
            candidates=[candidate],
            target_lock_status="awaiting_manual",
        )

        payload = build_target_lock_payload(preview, selected_candidate=candidate, manual=True)

        self.assertEqual(payload["status"], "locked")
        self.assertTrue(payload["manual_override"])
        self.assertEqual(payload["selected_candidate_id"], "candidate-main")
        self.assertEqual(payload["selected_bbox"], candidate["bbox"])

    def test_build_target_preview_preserves_manual_lock_with_review_flags(self) -> None:
        selected_bbox = {"x": 0.22, "y": 0.18, "width": 0.14, "height": 0.48}
        existing_lock = {
            "status": "locked",
            "manual_override": True,
            "preview_frame": "frame_0002.jpg",
            "preview_frame_index": 1,
            "selected_candidate_id": "candidate-main",
            "selected_bbox": selected_bbox,
            "lock_confidence": 0.74,
            "quality_flags": ["target_lock_zoomed_multiperson_manual_review"],
            "candidates": [
                {
                    "id": "candidate-main",
                    "bbox": selected_bbox,
                    "confidence": 0.74,
                    "source": "yolo_zoomed_content",
                    "quality_flags": ["target_lock_zoomed_multiperson_manual_review"],
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        }

        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"],
            existing_target_lock=existing_lock,
            detected_candidates=[
                {
                    "id": "candidate-other",
                    "bbox": {"x": 0.64, "y": 0.16, "width": 0.16, "height": 0.52},
                    "confidence": 0.96,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "locked")
        self.assertEqual(preview.auto_candidate_id, "candidate-main")
        self.assertEqual(preview.preview_frame, "frame_0002.jpg")
        self.assertEqual(preview.preview_frame_index, 1)
        self.assertEqual(preview.lock_confidence, 0.74)
        self.assertEqual(preview.candidates[0]["id"], "candidate-main")
        self.assertEqual(preview.candidates[0]["bbox"], selected_bbox)

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

    def test_build_target_lock_payload_anchors_to_selected_candidate_frame(self) -> None:
        preview = TargetPreview(
            preview_frame="frame_0001.jpg",
            preview_frame_url="/api/frames/analysis-1/frame_0001.jpg",
            preview_frame_index=0,
            auto_candidate_id="candidate_late",
            lock_confidence=0.86,
            candidates=[
                {
                    "id": "candidate_late",
                    "bbox": {"x": 0.35, "y": 0.2, "width": 0.16, "height": 0.42},
                    "confidence": 0.86,
                    "source": "yolo_preview",
                    "anchor_frame": "frame_0004.jpg",
                    "anchor_index": 3,
                }
            ],
            target_lock_status="auto_locked",
        )

        payload = build_target_lock_payload(preview)

        self.assertEqual(preview.preview_frame, "frame_0001.jpg")
        self.assertEqual(payload["preview_frame"], "frame_0004.jpg")
        self.assertEqual(payload["preview_frame_index"], 3)

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

    def test_build_target_preview_deprioritizes_zoomed_foreground_when_stable_small_target_exists(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 0.0, "motion_score": 0.9},
                    {"frame_id": "frame_0002", "timestamp": 0.5, "motion_score": 0.8},
                    {"frame_id": "frame_0003", "timestamp": 1.0, "motion_score": 0.7},
                ]
            },
            detected_candidates=[
                {
                    "id": "foreground_adult",
                    "bbox": {"x": 0.38, "y": 0.31, "width": 0.15, "height": 0.53},
                    "confidence": 0.89,
                    "source": "yolo_zoomed_content",
                    "support_count": 14,
                    "support_frame_count": 8,
                    "support_confidence": 0.80,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "stable_child",
                    "bbox": {"x": 0.62, "y": 0.43, "width": 0.021, "height": 0.095},
                    "confidence": 0.84,
                    "source": "yolo_zoomed_content",
                    "support_count": 32,
                    "support_frame_count": 9,
                    "support_confidence": 0.75,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "stable_child_later",
                    "bbox": {"x": 0.58, "y": 0.41, "width": 0.038, "height": 0.18},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "support_count": 28,
                    "support_frame_count": 9,
                    "support_confidence": 0.74,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0003.jpg",
                    "anchor_index": 2,
                },
            ],
        )

        self.assertIn(preview.auto_candidate_id, {"stable_child", "stable_child_later"})
        foreground = next(item for item in preview.candidates if item["id"] == "foreground_adult")
        self.assertIn("target_lock_zoomed_foreground_deprioritized_for_stable_small_target", foreground["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertIn(payload["selected_candidate_id"], {"stable_child", "stable_child_later"})

    def test_build_target_preview_deprioritizes_moderate_zoomed_foreground_when_tiny_skater_is_stable(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0009.jpg", "frame_0013.jpg", "frame_0016.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 0.0, "motion_score": 0.9},
                    {"frame_id": "frame_0013", "timestamp": 0.5, "motion_score": 0.85},
                ]
            },
            detected_candidates=[
                {
                    "id": "foreground_adult",
                    "bbox": {"x": 0.5129, "y": 0.2568, "width": 0.1424, "height": 0.5911},
                    "confidence": 0.8381,
                    "source": "yolo_zoomed_content",
                    "support_count": 18,
                    "support_frame_count": 9,
                    "support_confidence": 0.8074,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "foreground_adult_support",
                    "bbox": {"x": 0.4436, "y": 0.2517, "width": 0.1582, "height": 0.5895},
                    "confidence": 0.8297,
                    "source": "yolo_zoomed_content",
                    "support_count": 18,
                    "support_frame_count": 9,
                    "support_confidence": 0.8074,
                    "anchor_frame": "frame_0016.jpg",
                    "anchor_index": 2,
                },
                {
                    "id": "stable_tiny_skater",
                    "bbox": {"x": 0.6260, "y": 0.4172, "width": 0.0208, "height": 0.0846},
                    "confidence": 0.5931,
                    "source": "yolo_zoomed_content",
                    "support_count": 16,
                    "support_frame_count": 8,
                    "support_confidence": 0.5502,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "stable_tiny_skater_support",
                    "bbox": {"x": 0.6175, "y": 0.4130, "width": 0.0204, "height": 0.0861},
                    "confidence": 0.5705,
                    "source": "yolo_zoomed_content",
                    "support_count": 16,
                    "support_frame_count": 8,
                    "support_confidence": 0.5502,
                    "anchor_frame": "frame_0009.jpg",
                    "anchor_index": 0,
                },
                {
                    "id": "other_foreground_early",
                    "bbox": {"x": 0.3493, "y": 0.2935, "width": 0.1469, "height": 0.5565},
                    "confidence": 0.7319,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0009.jpg",
                    "anchor_index": 0,
                },
                {
                    "id": "other_tiny_late",
                    "bbox": {"x": 0.6244, "y": 0.4155, "width": 0.0200, "height": 0.0849},
                    "confidence": 0.5883,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0016.jpg",
                    "anchor_index": 2,
                },
                {
                    "id": "foreground_preview_person",
                    "bbox": {"x": 0.4436, "y": 0.2562, "width": 0.1627, "height": 0.7386},
                    "confidence": 0.9177,
                    "source": "yolo_preview",
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 1,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "stable_tiny_skater")
        foreground = next(item for item in preview.candidates if item["id"] == "foreground_adult")
        self.assertIn("target_lock_zoomed_foreground_deprioritized_for_stable_small_target", foreground["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_moderate_foreground_deprioritized_for_stable_small_target",
            foreground["quality_flags"],
        )
        top_flags = preview.candidates[0].get("quality_flags", [])
        self.assertIn("target_lock_foreground_context_small_target_manual_review", top_flags)
        self.assertIn(
            "target_lock_foreground_context_review_deprioritized_foreground_competitor",
            top_flags,
        )
        self.assertIn("target_lock_foreground_context_review_selected_pair_competitor", top_flags)
        self.assertNotIn("target_lock_complete_body_candidate_preferred_over_tiny_stable", preview.candidates[0].get("quality_flags", []))
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["selected_candidate_id"], "stable_tiny_skater")
        self.assertIsNone(payload["selected_bbox"])
        self.assertEqual(payload["status"], "awaiting_manual")

    def test_build_target_preview_prefers_supported_small_skater_over_8f17_foreground_adult(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(9, 24)]
        preview = build_target_preview(
            "analysis-8f17",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0011", "timestamp": 4.6, "motion_score": 0.9},
                    {"frame_id": "frame_0018", "timestamp": 5.7, "motion_score": 0.86},
                    {"frame_id": "frame_0021", "timestamp": 6.6, "motion_score": 0.82},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_20_candidate_2",
                    selected_frame_index=12,
                    bbox={"x": 0.3396, "y": 0.2176, "width": 0.2311, "height": 0.6324},
                    support_count=15,
                    selected_confidence=0.8249,
                    support_confidence=0.7509,
                    center_span=0.3388,
                ),
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_18_candidate_5",
                    selected_frame_index=9,
                    bbox={"x": 0.5722, "y": 0.2038, "width": 0.0417, "height": 0.2380},
                    support_count=15,
                    selected_confidence=0.8170,
                    support_confidence=0.7378,
                    center_span=0.3368,
                ),
                {
                    "id": "anchor_20_candidate_1",
                    "bbox": {"x": 0.3397, "y": 0.1701, "width": 0.2617, "height": 0.8203},
                    "confidence": 0.9413,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0021.jpg",
                    "anchor_index": 20,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_18_candidate_5")
        self.assertEqual(preview.candidates[0]["id"], "anchor_18_candidate_5")
        foreground = next(item for item in preview.candidates if item["id"] == "anchor_20_candidate_2")
        self.assertIn("target_lock_zoomed_foreground_deprioritized_for_stable_small_target", foreground["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["selected_candidate_id"], "anchor_18_candidate_5")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_prefers_narrow_skater_over_8f17_wide_partial_review_box(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(9, 25)]
        preview = build_target_preview(
            "analysis-8f17-wide-partial",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.875, "motion_score": 0.32},
                    {"frame_id": "frame_0022", "timestamp": 9.188, "motion_score": 0.338},
                    {"frame_id": "frame_0023", "timestamp": 9.25, "motion_score": 0.313},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_18_candidate_7",
                    "bbox": {"x": 0.3404, "y": 0.4210, "width": 0.1308, "height": 0.2230},
                    "confidence": 0.7907,
                    "source": "yolo_zoomed_content",
                    "support_count": 14,
                    "support_frame_count": 8,
                    "support_confidence": 0.6818,
                    "support_center_span": 0.3554,
                    "support_motion_anchor_hits": 2,
                    "multiperson_ambiguous_frame_count": 5,
                    "multiperson_competitor_count": 12,
                    "multiperson_same_anchor_competitor_count": 2,
                    "multiperson_selected_pair_frame_count": 1,
                    "anchor_frame": "frame_0019.jpg",
                    "anchor_index": 18,
                },
                {
                    "id": "anchor_18_candidate_5",
                    "bbox": {"x": 0.5722, "y": 0.2038, "width": 0.0417, "height": 0.2380},
                    "confidence": 0.8170,
                    "source": "yolo_zoomed_content",
                    "support_count": 15,
                    "support_frame_count": 5,
                    "support_confidence": 0.7378,
                    "support_center_span": 0.3368,
                    "support_motion_anchor_hits": 1,
                    "multiperson_ambiguous_frame_count": 5,
                    "multiperson_competitor_count": 12,
                    "multiperson_same_anchor_competitor_count": 2,
                    "multiperson_selected_pair_frame_count": 1,
                    "anchor_frame": "frame_0019.jpg",
                    "anchor_index": 18,
                },
                {
                    "id": "anchor_11_background_a",
                    "bbox": {"x": 0.4611, "y": 0.3940, "width": 0.0864, "height": 0.1666},
                    "confidence": 0.6100,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 11,
                },
                {
                    "id": "anchor_11_background_b",
                    "bbox": {"x": 0.5721, "y": 0.2048, "width": 0.0402, "height": 0.2378},
                    "confidence": 0.6200,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 11,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_18_candidate_5")
        self.assertEqual(preview.candidates[0]["id"], "anchor_18_candidate_5")
        self.assertIn(
            "target_lock_narrow_skater_review_candidate_preferred_over_wide_partial",
            preview.candidates[0]["quality_flags"],
        )
        wide_partial = next(item for item in preview.candidates if item["id"] == "anchor_18_candidate_7")
        self.assertIn(
            "target_lock_wide_partial_review_candidate_deprioritized_for_narrow_skater",
            wide_partial["quality_flags"],
        )
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["selected_candidate_id"], "anchor_18_candidate_5")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_prefers_compact_child_skater_over_a3df_foreground_adult(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(7, 24)]
        preview = build_target_preview(
            "analysis-a3df",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0018", "timestamp": 4.8, "motion_score": 0.92},
                    {"frame_id": "frame_0020", "timestamp": 5.3, "motion_score": 0.88},
                    {"frame_id": "frame_0023", "timestamp": 5.9, "motion_score": 0.84},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_18_candidate_3",
                    selected_frame_index=11,
                    bbox={"x": 0.5746, "y": 0.3296, "width": 0.0835, "height": 0.5184},
                    support_count=15,
                    selected_confidence=0.8747,
                    support_confidence=0.7697,
                    center_span=0.3463,
                ),
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_23_candidate_4",
                    selected_frame_index=16,
                    bbox={"x": 0.4229, "y": 0.3429, "width": 0.0825, "height": 0.3088},
                    support_count=16,
                    selected_confidence=0.8698,
                    support_confidence=0.7541,
                    center_span=0.4402,
                ),
                {
                    "id": "foreground_support_box",
                    "bbox": {"x": 0.4590, "y": 0.4461, "width": 0.1990, "height": 0.4039},
                    "confidence": 0.8811,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0007.jpg",
                    "anchor_index": 0,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_23_candidate_4")
        foreground = next(item for item in preview.candidates if item["id"] == "anchor_18_candidate_3")
        self.assertIn(
            "target_lock_zoomed_foreground_deprioritized_for_compact_skater_target",
            foreground["quality_flags"],
        )
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["selected_candidate_id"], "anchor_23_candidate_4")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_prefers_compact_skater_over_ac33_environment_box(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(11, 32)]
        preview = build_target_preview(
            "analysis-ac33",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0011", "timestamp": 2.2, "motion_score": 0.94},
                    {"frame_id": "frame_0020", "timestamp": 3.1, "motion_score": 0.90},
                    {"frame_id": "frame_0031", "timestamp": 4.0, "motion_score": 0.86},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_31_candidate_2",
                    selected_frame_index=20,
                    bbox={"x": 0.5275, "y": 0.5312, "width": 0.1304, "height": 0.3027},
                    support_count=14,
                    selected_confidence=0.9240,
                    support_confidence=0.8805,
                    center_span=0.2597,
                ),
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_11_candidate_3",
                    selected_frame_index=0,
                    bbox={"x": 0.4082, "y": 0.4058, "width": 0.0775, "height": 0.1773},
                    support_count=32,
                    selected_confidence=0.8824,
                    support_confidence=0.8875,
                    center_span=0.3580,
                ),
                {
                    "id": "anchor_20_candidate_3",
                    "bbox": {"x": 0.4497, "y": 0.4755, "width": 0.1182, "height": 0.2618},
                    "confidence": 0.9133,
                    "source": "yolo_zoomed_content",
                    "support_count": 25,
                    "support_frame_count": 11,
                    "support_confidence": 0.8240,
                    "anchor_frame": "frame_0020.jpg",
                    "anchor_index": 9,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertTrue(str(preview.auto_candidate_id).startswith("anchor_11_candidate_3"))
        foreground = next(item for item in preview.candidates if item["id"] == "anchor_31_candidate_2")
        self.assertIn(
            "target_lock_zoomed_foreground_deprioritized_for_compact_skater_target",
            foreground["quality_flags"],
        )
        payload = build_target_lock_payload(preview)
        self.assertTrue(str(payload["selected_candidate_id"]).startswith("anchor_11_candidate_3"))
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_prefers_fuller_aggregate_skater_over_near_foreground_adult(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0009.jpg", "frame_0013.jpg", "frame_0026.jpg", "frame_0027.jpg", "frame_0028.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.8, "motion_score": 0.96},
                    {"frame_id": "frame_0013", "timestamp": 2.6, "motion_score": 0.92},
                    {"frame_id": "frame_0027", "timestamp": 5.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_26_foreground_adult",
                    "bbox": {"x": 0.5575, "y": 0.2675, "width": 0.084, "height": 0.5824},
                    "confidence": 0.8642,
                    "source": "yolo_zoomed_content",
                    "support_count": 19,
                    "support_frame_count": 10,
                    "support_confidence": 0.8227,
                    "anchor_frame": "frame_0027.jpg",
                    "anchor_index": 26,
                },
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4892, "y": 0.4244, "width": 0.0726, "height": 0.1921},
                    "confidence": 0.9216,
                    "source": "yolo_zoomed_content",
                    "support_count": 44,
                    "support_frame_count": 10,
                    "support_confidence": 0.8799,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "same_anchor_small_skater",
                    "bbox": {"x": 0.4799, "y": 0.3884, "width": 0.0255, "height": 0.1131},
                    "confidence": 0.8311,
                    "source": "yolo_zoomed_content",
                    "support_count": 50,
                    "support_frame_count": 10,
                    "support_confidence": 0.8372,
                    "anchor_frame": "frame_0027.jpg",
                    "anchor_index": 26,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.candidates[0]["id"], "candidate_auto_stable")
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_stable_zoomed_candidate_auto_locked", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertEqual(payload["selected_candidate_id"], "candidate_auto_stable")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_prefers_fuller_zoomed_body_over_medium_partial_motion_box(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(1, 34)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0003", "timestamp": 0.4, "motion_score": 0.96},
                    {"frame_id": "frame_0014", "timestamp": 1.8, "motion_score": 0.92},
                    {"frame_id": "frame_0017", "timestamp": 2.2, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4576, "y": 0.4015, "width": 0.0588, "height": 0.1206},
                    "confidence": 0.8041,
                    "source": "yolo_zoomed_content",
                    "support_count": 51,
                    "support_frame_count": 10,
                    "support_confidence": 0.8746,
                    "support_center_span": 0.3004,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "fuller_same_skater",
                    "bbox": {"x": 0.4336, "y": 0.4463, "width": 0.1191, "height": 0.1951},
                    "confidence": 0.9212,
                    "source": "yolo_zoomed_content",
                    "support_count": 50,
                    "support_frame_count": 10,
                    "support_confidence": 0.8520,
                    "support_center_span": 0.251,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0003.jpg",
                    "anchor_index": 2,
                },
                {
                    "id": "background_small_a",
                    "bbox": {"x": 0.28, "y": 0.41, "width": 0.034, "height": 0.120},
                    "confidence": 0.89,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "background_small_b",
                    "bbox": {"x": 0.60, "y": 0.38, "width": 0.035, "height": 0.113},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 13,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "fuller_same_skater")
        self.assertEqual(preview.candidates[0]["id"], "fuller_same_skater")
        self.assertIn(
            "target_lock_fuller_zoomed_body_candidate_preferred_over_medium_partial_target",
            preview.candidates[0]["quality_flags"],
        )

    def test_build_target_preview_keeps_manual_when_medium_partial_fuller_candidate_is_far(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(1, 34)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.0, "motion_score": 0.96},
                    {"frame_id": "frame_0031", "timestamp": 3.2, "motion_score": 0.92},
                    {"frame_id": "frame_0032", "timestamp": 3.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4839, "y": 0.5486, "width": 0.0205, "height": 0.0893},
                    "confidence": 0.7987,
                    "source": "yolo_zoomed_content",
                    "support_count": 14,
                    "support_frame_count": 6,
                    "support_confidence": 0.8068,
                    "support_center_span": 0.2499,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0009.jpg",
                    "anchor_index": 8,
                },
                {
                    "id": "adult_far_competitor",
                    "bbox": {"x": 0.6133, "y": 0.5734, "width": 0.039, "height": 0.2027},
                    "confidence": 0.8712,
                    "source": "yolo_zoomed_content",
                    "support_count": 8,
                    "support_frame_count": 5,
                    "support_confidence": 0.6872,
                    "support_center_span": 0.2761,
                    "support_motion_anchor_hits": 2,
                    "anchor_frame": "frame_0009.jpg",
                    "anchor_index": 8,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertNotIn(
            "target_lock_fuller_zoomed_body_candidate_preferred_over_medium_partial_target",
            preview.candidates[0].get("quality_flags", []),
        )

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
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_stable_zoomed_candidate_auto_locked", preview.candidates[0]["quality_flags"])
        self.assertEqual(preview.candidates[0]["multiperson_ambiguous_frame_count"], 1)
        self.assertEqual(preview.candidates[0]["multiperson_competitor_count"], 1)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 1)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 1)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_competitor_count"], 1)
        self.assertEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 0)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_nearest_center_distance"], 0.08)
        self.assertEqual(preview.candidates[0]["multiperson_max_competitor_confidence"], 0.8614)
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_zoomed_multiperson_manual_review", payload["quality_flags"])

    def test_build_target_preview_ignores_weak_zoomed_fragment_near_stable_target(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.44, "y": 0.42, "width": 0.09, "height": 0.20},
                    "confidence": 0.91,
                    "source": "yolo_zoomed_content",
                    "support_count": 24,
                    "support_frame_count": 8,
                    "support_confidence": 0.86,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "tiny_fragment",
                    "bbox": {"x": 0.62, "y": 0.39, "width": 0.025, "height": 0.08},
                    "confidence": 0.70,
                    "source": "yolo_zoomed_content",
                    "support_count": 14,
                    "support_frame_count": 6,
                    "support_confidence": 0.74,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertIn("target_lock_zoomed_multiperson_fragment_ignored", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertEqual(preview.candidates[0]["multiperson_ambiguous_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_competitor_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_ignored_fragment_count"], 1)
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "auto_locked")
        self.assertIsNotNone(payload["selected_bbox"])

    def test_select_stable_target_candidate_does_not_merge_far_zoomed_fragments_as_support(self) -> None:
        candidates = [
            {
                "id": "near_motion_skater",
                "bbox": {"x": 0.61, "y": 0.57, "width": 0.04, "height": 0.20},
                "confidence": 0.87,
                "source": "yolo_zoomed_content",
                "anchor_frame": "frame_0009.jpg",
                "anchor_index": 8,
            },
            {
                "id": "tiny_far_fragment_1",
                "bbox": {"x": 0.48, "y": 0.53, "width": 0.022, "height": 0.08},
                "confidence": 0.80,
                "source": "yolo_zoomed_content",
                "anchor_frame": "frame_0012.jpg",
                "anchor_index": 11,
            },
            {
                "id": "tiny_far_fragment_2",
                "bbox": {"x": 0.49, "y": 0.55, "width": 0.021, "height": 0.09},
                "confidence": 0.82,
                "source": "yolo_zoomed_content",
                "anchor_frame": "frame_0014.jpg",
                "anchor_index": 13,
            },
        ]

        selected = select_stable_target_candidate(candidates)

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertIn(selected["id"], {"tiny_far_fragment_1", "tiny_far_fragment_2"})
        self.assertLessEqual(selected["support_frame_count"], 2)

    def test_build_target_preview_requires_manual_for_strong_zoomed_fragment_competitor(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.44, "y": 0.42, "width": 0.09, "height": 0.20},
                    "confidence": 0.91,
                    "source": "yolo_zoomed_content",
                    "support_count": 24,
                    "support_frame_count": 8,
                    "support_confidence": 0.86,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "other_person_sized_competitor",
                    "bbox": {"x": 0.62, "y": 0.34, "width": 0.058, "height": 0.14},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "support_count": 14,
                    "support_frame_count": 6,
                    "support_confidence": 0.80,
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_stable_zoomed_candidate_auto_locked", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])

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
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_stable_zoomed_candidate_auto_locked", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_zoomed_multiperson_manual_review", payload["quality_flags"])
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 1)

    def test_build_target_preview_auto_locks_strong_supported_zoomed_target_with_background_people(self) -> None:
        frame_names = [
            "frame_0009.jpg",
            "frame_0011.jpg",
            "frame_0012.jpg",
            "frame_0014.jpg",
            "frame_0017.jpg",
            "frame_0019.jpg",
            "frame_0021.jpg",
            "frame_0024.jpg",
            "frame_0026.jpg",
        ]
        support_candidates = [
            {
                "id": f"target_support_{index}",
                "bbox": {"x": 0.50 + index * 0.002, "y": 0.40, "width": 0.070, "height": 0.125},
                "confidence": 0.84,
                "source": "yolo_zoomed_content",
                "anchor_frame": frame,
                "anchor_index": index,
            }
            for index, frame in enumerate(frame_names)
        ]
        support_candidates[4].update(
            {
                "id": "candidate_auto_stable",
                "confidence": 0.8692,
                "support_count": 42,
                "support_frame_count": 9,
                "support_confidence": 0.8377,
                "quality_flags": [
                    "target_lock_zoomed_multiperson_manual_review",
                    "target_lock_stable_zoomed_auto_lock_blocked_by_manual_review",
                    "target_lock_auto_lock_blocked_by_manual_review",
                ],
            }
        )
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0014", "timestamp": 2.8, "motion_score": 0.96},
                    {"frame_id": "frame_0017", "timestamp": 3.4, "motion_score": 0.92},
                    {"frame_id": "frame_0021", "timestamp": 4.2, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *support_candidates,
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.20, "y": 0.30, "width": 0.055, "height": 0.155},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0024.jpg",
                    "anchor_index": 7,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.36, "y": 0.31, "width": 0.050, "height": 0.145},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0024.jpg",
                    "anchor_index": 7,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertIn("target_lock_stable_zoomed_candidate_auto_locked", preview.candidates[0]["quality_flags"])
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 1)
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "auto_locked")
        self.assertIsNotNone(payload["selected_bbox"])

    def test_build_target_preview_removes_background_auto_lock_allowed_when_manual_review_overrides(self) -> None:
        frame_names = [
            "frame_0009.jpg",
            "frame_0011.jpg",
            "frame_0012.jpg",
            "frame_0014.jpg",
            "frame_0017.jpg",
            "frame_0019.jpg",
            "frame_0021.jpg",
            "frame_0024.jpg",
            "frame_0026.jpg",
        ]
        support_candidates = [
            {
                "id": f"target_support_{index}",
                "bbox": {"x": 0.50 + index * 0.002, "y": 0.40, "width": 0.070, "height": 0.125},
                "confidence": 0.84,
                "source": "yolo_zoomed_content",
                "anchor_frame": frame,
                "anchor_index": index,
            }
            for index, frame in enumerate(frame_names)
        ]
        support_candidates[4].update(
            {
                "id": "candidate_auto_stable",
                "confidence": 0.8692,
                "support_count": 42,
                "support_frame_count": 9,
                "support_confidence": 0.8377,
                "quality_flags": [
                    "target_lock_zoomed_multiperson_manual_review",
                    "target_lock_foreground_context_small_target_manual_review",
                    "target_lock_stable_zoomed_auto_lock_blocked_by_manual_review",
                    "target_lock_auto_lock_blocked_by_manual_review",
                ],
            }
        )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0014", "timestamp": 2.8, "motion_score": 0.96},
                    {"frame_id": "frame_0017", "timestamp": 3.4, "motion_score": 0.92},
                    {"frame_id": "frame_0021", "timestamp": 4.2, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *support_candidates,
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.20, "y": 0.30, "width": 0.055, "height": 0.155},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0024.jpg",
                    "anchor_index": 7,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.36, "y": 0.31, "width": 0.050, "height": 0.145},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0024.jpg",
                    "anchor_index": 7,
                },
            ],
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertIn("target_lock_foreground_context_small_target_manual_review", flags)
        self.assertIn(
            "target_lock_zoomed_multiperson_background_auto_lock_allowed_overridden_by_manual_review",
            flags,
        )
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", flags)
        self.assertIn("target_lock_auto_lock_blocked_by_manual_review", flags)
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", flags)
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_cleans_legacy_background_allowed_manual_conflict(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg"],
            existing_target_lock={
                "status": "awaiting_manual",
                "preview_frame": "frame_0001.jpg",
                "selected_candidate_id": "candidate_1",
                "lock_confidence": 0.88,
                "candidates": [
                    {
                        "id": "candidate_1",
                        "bbox": {"x": 0.38, "y": 0.22, "width": 0.08, "height": 0.26},
                        "confidence": 0.88,
                        "source": "yolo_zoomed_content",
                        "quality_flags": [
                            "target_lock_zoomed_multiperson_background_auto_lock_allowed",
                            "target_lock_zoomed_multiperson_manual_review",
                            "target_lock_auto_lock_blocked_by_manual_review",
                        ],
                    }
                ],
            },
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", flags)
        self.assertIn(
            "target_lock_zoomed_multiperson_background_auto_lock_allowed_overridden_by_manual_review",
            flags,
        )
        self.assertIn("target_lock_zoomed_multiperson_manual_review", flags)

    def test_build_target_preview_auto_locks_wide_supported_zoomed_target_when_multiperson_is_background_only(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(9, 20)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 1.8, "motion_score": 0.96},
                    {"frame_id": "frame_0015", "timestamp": 2.1, "motion_score": 0.92},
                    {"frame_id": "frame_0018", "timestamp": 2.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_20_candidate_2",
                    selected_frame_index=5,
                    bbox={"x": 0.03, "y": 0.31, "width": 0.14, "height": 0.2925},
                    support_count=19,
                    selected_confidence=0.9152,
                    support_confidence=0.854,
                    center_span=0.232,
                ),
                {
                    "id": "background_person_left",
                    "bbox": {"x": 0.70, "y": 0.36, "width": 0.055, "height": 0.155},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 9,
                },
                {
                    "id": "background_person_right",
                    "bbox": {"x": 0.82, "y": 0.34, "width": 0.050, "height": 0.145},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 9,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_20_candidate_2")
        self.assertGreater(preview.candidates[0]["support_center_span"], 0.18)
        self.assertGreater(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_keeps_large_moving_background_multiperson_manual(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(9, 25)]
        background_candidates: list[dict[str, object]] = []
        for index, frame in enumerate(frame_names[1:8], start=1):
            background_candidates.extend(
                [
                    {
                        "id": f"background_left_{index}",
                        "bbox": {"x": 0.18, "y": 0.31, "width": 0.055, "height": 0.155},
                        "confidence": 0.88,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": index,
                    },
                    {
                        "id": f"background_right_{index}",
                        "bbox": {"x": 0.34, "y": 0.32, "width": 0.052, "height": 0.150},
                        "confidence": 0.86,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": index,
                    },
                ]
            )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 1.8, "motion_score": 0.96},
                    {"frame_id": "frame_0016", "timestamp": 2.1, "motion_score": 0.92},
                    {"frame_id": "frame_0021", "timestamp": 2.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_20_candidate_3",
                    selected_frame_index=11,
                    bbox={"x": 0.524, "y": 0.3892, "width": 0.1136, "height": 0.2119},
                    support_count=24,
                    selected_confidence=0.9176,
                    support_confidence=0.8395,
                    center_span=0.2206,
                ),
                *background_candidates,
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_20_candidate_3")
        self.assertGreaterEqual(preview.candidates[0]["multiperson_competitor_count"], 12)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 5)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_auto_locks_foreground_skater_when_competitors_are_tiny_background(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(9, 25)]
        background_candidates: list[dict[str, object]] = []
        for index, frame in enumerate(frame_names[1:8], start=1):
            background_anchor_index = 11 if index <= 5 else index
            background_anchor_frame = "frame_0021.jpg" if index <= 5 else frame
            background_candidates.extend(
                [
                    {
                        "id": f"background_left_{index}",
                        "bbox": {"x": 0.55 + index * 0.005, "y": 0.22 + index * 0.006, "width": 0.020, "height": 0.055},
                        "confidence": 0.73,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": background_anchor_frame,
                        "anchor_index": background_anchor_index,
                    },
                    {
                        "id": f"background_right_{index}",
                        "bbox": {"x": 0.61 - index * 0.004, "y": 0.23 + index * 0.005, "width": 0.021, "height": 0.058},
                        "confidence": 0.70,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": background_anchor_frame,
                        "anchor_index": background_anchor_index,
                    },
                ]
            )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 1.8, "motion_score": 0.96},
                    {"frame_id": "frame_0016", "timestamp": 2.1, "motion_score": 0.92},
                    {"frame_id": "frame_0021", "timestamp": 2.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_20_candidate_3",
                    "bbox": {"x": 0.3971, "y": 0.4062, "width": 0.1702, "height": 0.2746},
                    "confidence": 0.9158,
                    "source": "yolo_zoomed_content",
                    "support_count": 20,
                    "support_frame_count": 10,
                    "support_confidence": 0.8414,
                    "support_center_span": 0.2693,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0021.jpg",
                    "anchor_index": 11,
                },
                *background_candidates,
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_20_candidate_3")
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_marks_foreground_background_auto_lock_allowed(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(1, 33)]
        candidates: list[dict[str, object]] = [
            {
                "id": "anchor_20_candidate_3",
                "bbox": {"x": 0.3971, "y": 0.4062, "width": 0.1702, "height": 0.2746},
                "confidence": 0.9158,
                "source": "yolo_zoomed_content",
                "support_count": 20,
                "support_frame_count": 10,
                "support_confidence": 0.8414,
                "support_center_span": 0.2693,
                "support_motion_anchor_hits": 3,
                "anchor_frame": "frame_0021.jpg",
                "anchor_index": 20,
            },
            {
                "id": "anchor_23_candidate_4",
                "bbox": {"x": 0.4169, "y": 0.3934, "width": 0.129, "height": 0.3226},
                "confidence": 0.9144,
                "source": "yolo_zoomed_content",
                "support_count": 20,
                "support_frame_count": 10,
                "support_confidence": 0.8414,
                "support_center_span": 0.2693,
                "support_motion_anchor_hits": 3,
                "anchor_frame": "frame_0024.jpg",
                "anchor_index": 23,
            },
            {
                "id": "anchor_18_candidate_3",
                "bbox": {"x": 0.395, "y": 0.4049, "width": 0.1455, "height": 0.2876},
                "confidence": 0.9135,
                "source": "yolo_zoomed_content",
                "support_count": 20,
                "support_frame_count": 10,
                "support_confidence": 0.8414,
                "support_center_span": 0.2693,
                "support_motion_anchor_hits": 3,
                "anchor_frame": "frame_0019.jpg",
                "anchor_index": 18,
            },
            {
                "id": "anchor_9_candidate_4",
                "bbox": {"x": 0.6168, "y": 0.2169, "width": 0.0215, "height": 0.0868},
                "confidence": 0.7276,
                "source": "yolo_zoomed_content",
                "anchor_frame": "frame_0010.jpg",
                "anchor_index": 9,
            },
            {
                "id": "anchor_9_candidate_5",
                "bbox": {"x": 0.5665, "y": 0.2041, "width": 0.0274, "height": 0.0938},
                "confidence": 0.6254,
                "source": "yolo_zoomed_content",
                "anchor_frame": "frame_0010.jpg",
                "anchor_index": 9,
            },
        ]
        for index, frame_index in enumerate([9, 10, 11, 13, 16, 18, 20, 23, 24, 26, 28, 30], start=1):
            candidates.append(
                {
                    "id": f"tiny_background_left_{index}",
                    "bbox": {
                        "x": 0.53 + (index % 5) * 0.018,
                        "y": 0.20 + (index % 6) * 0.015,
                        "width": 0.022,
                        "height": 0.085,
                    },
                    "confidence": 0.64,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": f"frame_{frame_index:04d}.jpg",
                    "anchor_index": frame_index - 1,
                }
            )
            candidates.append(
                {
                    "id": f"tiny_background_right_{index}",
                    "bbox": {
                        "x": 0.61 - (index % 4) * 0.017,
                        "y": 0.22 + (index % 5) * 0.014,
                        "width": 0.020,
                        "height": 0.058,
                    },
                    "confidence": 0.62,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": f"frame_{frame_index:04d}.jpg",
                    "anchor_index": frame_index - 1,
                }
            )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 1.5, "motion_score": 0.96},
                    {"frame_id": "frame_0019", "timestamp": 2.0, "motion_score": 0.92},
                    {"frame_id": "frame_0021", "timestamp": 2.3, "motion_score": 0.88},
                ]
            },
            detected_candidates=candidates,
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_20_candidate_3")
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_multiperson_foreground_background_auto_lock_allowed",
            preview.candidates[0]["quality_flags"],
        )
        self.assertNotIn(
            "target_lock_zoomed_multiperson_background_auto_lock_blocked_large_moving_risk",
            preview.candidates[0]["quality_flags"],
        )
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_ignores_overlapping_duplicate_body_boxes(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 22)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 1.8, "motion_score": 0.96},
                    {"frame_id": "frame_0015", "timestamp": 2.1, "motion_score": 0.92},
                    {"frame_id": "frame_0018", "timestamp": 2.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_16_candidate_3",
                    "bbox": {"x": 0.4611, "y": 0.202, "width": 0.2965, "height": 0.4942},
                    "confidence": 0.8989,
                    "source": "yolo_zoomed_content",
                    "support_count": 16,
                    "support_frame_count": 9,
                    "support_confidence": 0.8001,
                    "support_center_span": 0.2908,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0016.jpg",
                    "anchor_index": 8,
                },
                {
                    "id": "same_skater_wide_box",
                    "bbox": {"x": 0.3883, "y": 0.1618, "width": 0.4941, "height": 0.8311},
                    "confidence": 0.9241,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
                {
                    "id": "same_skater_mid_box",
                    "bbox": {"x": 0.4326, "y": 0.2, "width": 0.45, "height": 0.6395},
                    "confidence": 0.9212,
                    "source": "yolo_zoomed_content",
                    "support_count": 13,
                    "support_frame_count": 7,
                    "support_confidence": 0.8037,
                    "support_center_span": 0.271,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
                {
                    "id": "same_skater_offset_box",
                    "bbox": {"x": 0.3259, "y": 0.2233, "width": 0.3883, "height": 0.6178},
                    "confidence": 0.9197,
                    "source": "yolo_zoomed_content",
                    "support_count": 18,
                    "support_frame_count": 10,
                    "support_confidence": 0.8104,
                    "support_center_span": 0.3542,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_16_candidate_3")
        self.assertIn(
            "target_lock_zoomed_multiperson_duplicate_body_box_ignored",
            preview.candidates[0]["quality_flags"],
        )
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertGreater(preview.candidates[0]["multiperson_ignored_duplicate_body_box_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "auto_locked")
        self.assertIsNotNone(payload["selected_bbox"])

    def test_build_target_preview_keeps_manual_for_non_overlapping_same_frame_people(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 17)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 1.9, "motion_score": 0.96},
                    {"frame_id": "frame_0014", "timestamp": 2.2, "motion_score": 0.92},
                    {"frame_id": "frame_0015", "timestamp": 2.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.42, "y": 0.30, "width": 0.18, "height": 0.36},
                    "confidence": 0.91,
                    "source": "yolo_zoomed_content",
                    "support_count": 20,
                    "support_frame_count": 9,
                    "support_confidence": 0.84,
                    "support_center_span": 0.18,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
                {
                    "id": "same_frame_other_person",
                    "bbox": {"x": 0.15, "y": 0.32, "width": 0.17, "height": 0.34},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "support_count": 18,
                    "support_frame_count": 8,
                    "support_confidence": 0.82,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 1)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn(
            "target_lock_zoomed_multiperson_duplicate_body_box_ignored",
            preview.candidates[0]["quality_flags"],
        )

    def test_build_target_preview_auto_locks_strong_foreground_with_transient_background_ambiguity(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 25)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0017", "timestamp": 2.1, "motion_score": 0.92},
                    {"frame_id": "frame_0019", "timestamp": 2.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_16_candidate_3",
                    "bbox": {"x": 0.4611, "y": 0.202, "width": 0.2965, "height": 0.4942},
                    "confidence": 0.8989,
                    "source": "yolo_zoomed_content",
                    "support_count": 16,
                    "support_frame_count": 9,
                    "support_confidence": 0.8001,
                    "support_center_span": 0.2908,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0017.jpg",
                    "anchor_index": 9,
                },
                {
                    "id": "target_support_20",
                    "bbox": {"x": 0.4127, "y": 0.2026, "width": 0.0946, "height": 0.4402},
                    "confidence": 0.8112,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0021.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "background_edge_20",
                    "bbox": {"x": 0.0001, "y": 0.2007, "width": 0.07, "height": 0.1746},
                    "confidence": 0.8783,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0021.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "target_support_23",
                    "bbox": {"x": 0.4332, "y": 0.2015, "width": 0.0906, "height": 0.4444},
                    "confidence": 0.7743,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0024.jpg",
                    "anchor_index": 16,
                },
                {
                    "id": "background_edge_23",
                    "bbox": {"x": 0.1813, "y": 0.201, "width": 0.066, "height": 0.2062},
                    "confidence": 0.746,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0024.jpg",
                    "anchor_index": 16,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_16_candidate_3")
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 2)
        self.assertIn(
            "target_lock_zoomed_multiperson_foreground_transient_background_auto_lock_allowed",
            preview.candidates[0]["quality_flags"],
        )
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_keeps_manual_for_persistent_foreground_background_ambiguity(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 25)]
        background_candidates: list[dict[str, object]] = []
        for index, frame in enumerate(frame_names[3:9], start=3):
            background_candidates.extend(
                [
                    {
                        "id": f"target_support_{index}",
                        "bbox": {"x": 0.43, "y": 0.20, "width": 0.09, "height": 0.44},
                        "confidence": 0.82,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": index,
                    },
                    {
                        "id": f"background_edge_{index}",
                        "bbox": {"x": 0.11 + index * 0.005, "y": 0.20, "width": 0.066, "height": 0.20},
                        "confidence": 0.78,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": index,
                    },
                ]
            )
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0017", "timestamp": 2.1, "motion_score": 0.92},
                    {"frame_id": "frame_0019", "timestamp": 2.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_16_candidate_3",
                    "bbox": {"x": 0.4611, "y": 0.202, "width": 0.2965, "height": 0.4942},
                    "confidence": 0.8989,
                    "source": "yolo_zoomed_content",
                    "support_count": 16,
                    "support_frame_count": 9,
                    "support_confidence": 0.8001,
                    "support_center_span": 0.2908,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0017.jpg",
                    "anchor_index": 9,
                },
                *background_candidates,
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertGreater(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 2)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn(
            "target_lock_zoomed_multiperson_foreground_transient_background_auto_lock_allowed",
            preview.candidates[0]["quality_flags"],
        )

    def test_build_target_preview_keeps_small_moving_background_multiperson_manual_when_motion_support_is_weak(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 20)]
        background_candidates: list[dict[str, object]] = []
        for index, frame in enumerate(frame_names[2:10], start=2):
            background_candidates.extend(
                [
                    {
                        "id": f"background_left_{index}",
                        "bbox": {"x": 0.72, "y": 0.33, "width": 0.050, "height": 0.150},
                        "confidence": 0.88,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": index,
                    },
                    {
                        "id": f"background_right_{index}",
                        "bbox": {"x": 0.84, "y": 0.34, "width": 0.046, "height": 0.145},
                        "confidence": 0.86,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": index,
                    },
                ]
            )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 1.4, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 1.9, "motion_score": 0.92},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_11_candidate_2",
                    selected_frame_index=3,
                    bbox={"x": 0.4561, "y": 0.412, "width": 0.0611, "height": 0.2159},
                    support_count=21,
                    selected_confidence=0.8932,
                    support_confidence=0.8454,
                    center_span=0.30,
                ),
                *background_candidates,
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertTrue(str(preview.auto_candidate_id).startswith("anchor_11_candidate_2"))
        self.assertGreaterEqual(preview.candidates[0]["multiperson_competitor_count"], 2)
        self.assertGreaterEqual(preview.candidates[0]["support_center_span"], 0.20)
        self.assertLess(preview.candidates[0]["support_motion_anchor_hits"], 3)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_multiperson_background_auto_lock_blocked_small_moving_risk",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_allows_high_support_small_moving_background_target(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(1, 25)]
        background_candidates: list[dict[str, object]] = []
        for index, frame in enumerate(["frame_0007.jpg", "frame_0015.jpg", "frame_0024.jpg"], start=1):
            background_candidates.extend(
                [
                    {
                        "id": f"background_left_{index}",
                        "bbox": {"x": 0.66, "y": 0.34, "width": 0.052, "height": 0.151},
                        "confidence": 0.88,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": int(frame[6:10]) - 1,
                    },
                    {
                        "id": f"background_right_{index}",
                        "bbox": {"x": 0.81, "y": 0.35, "width": 0.047, "height": 0.142},
                        "confidence": 0.86,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": int(frame[6:10]) - 1,
                    },
                ]
            )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0007", "timestamp": 2.0, "motion_score": 0.96},
                    {"frame_id": "frame_0015", "timestamp": 7.5, "motion_score": 0.92},
                    {"frame_id": "frame_0024", "timestamp": 9.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="candidate_auto_stable",
                    selected_frame_index=10,
                    bbox={"x": 0.42, "y": 0.41, "width": 0.062, "height": 0.1954},
                    support_count=31,
                    selected_confidence=0.8039,
                    support_confidence=0.745,
                    center_span=0.228,
                ),
                *background_candidates,
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertGreaterEqual(preview.candidates[0]["support_count"], 30)
        self.assertGreaterEqual(preview.candidates[0]["support_frame_count"], 10)
        self.assertGreaterEqual(preview.candidates[0]["support_motion_anchor_hits"], 3)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn(
            "target_lock_zoomed_multiperson_background_auto_lock_blocked_small_moving_risk",
            preview.candidates[0]["quality_flags"],
        )

    def test_build_target_preview_allows_stable_small_background_multiperson_when_support_is_strong(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 20)]
        background_candidates: list[dict[str, object]] = []
        for index, frame in enumerate(frame_names[2:8], start=2):
            background_candidates.extend(
                [
                    {
                        "id": f"background_left_{index}",
                        "bbox": {"x": 0.72, "y": 0.33, "width": 0.050, "height": 0.150},
                        "confidence": 0.88,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": index,
                    },
                    {
                        "id": f"background_right_{index}",
                        "bbox": {"x": 0.84, "y": 0.34, "width": 0.046, "height": 0.145},
                        "confidence": 0.86,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": index,
                    },
                ]
            )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 1.4, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 1.9, "motion_score": 0.92},
                    {"frame_id": "frame_0015", "timestamp": 2.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_16_candidate_3",
                    selected_frame_index=8,
                    bbox={"x": 0.4114, "y": 0.4346, "width": 0.0741, "height": 0.1071},
                    support_count=33,
                    selected_confidence=0.9417,
                    support_confidence=0.86,
                    center_span=0.0877,
                ),
                *background_candidates,
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_16_candidate_3")
        self.assertGreaterEqual(preview.candidates[0]["support_motion_anchor_hits"], 3)
        self.assertGreaterEqual(preview.candidates[0]["support_confidence"], 0.82)
        self.assertLess(preview.candidates[0]["support_center_span"], 0.20)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn(
            "target_lock_zoomed_multiperson_background_auto_lock_blocked_small_moving_risk",
            preview.candidates[0]["quality_flags"],
        )

    def test_build_target_preview_auto_locks_dense_tiny_target_when_background_only_conflict_is_unrelated(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 17)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.4, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 1.9, "motion_score": 0.92},
                    {"frame_id": "frame_0015", "timestamp": 2.3, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_8_candidate_4",
                    selected_frame_index=4,
                    bbox={"x": 0.38, "y": 0.42, "width": 0.030, "height": 0.1233},
                    support_count=47,
                    selected_confidence=0.7987,
                    support_confidence=0.7764,
                    center_span=0.309,
                ),
                {
                    "id": "background_far_a",
                    "bbox": {"x": 0.18, "y": 0.33, "width": 0.045, "height": 0.120},
                    "confidence": 0.78,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0015.jpg",
                    "anchor_index": 7,
                },
                {
                    "id": "background_far_b",
                    "bbox": {"x": 0.29, "y": 0.34, "width": 0.042, "height": 0.118},
                    "confidence": 0.76,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0015.jpg",
                    "anchor_index": 7,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_8_candidate_4")
        self.assertLess(preview.candidates[0]["support_confidence"], 0.80)
        self.assertGreaterEqual(preview.candidates[0]["support_count"], 40)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_keeps_dense_tiny_multiperson_target_manual(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 17)]
        selected_frame_index = 4
        background_candidates: list[dict[str, object]] = []
        for frame_index, frame in enumerate(frame_names):
            per_frame_count = 1 if frame_index == selected_frame_index else 4
            for competitor_index in range(per_frame_count):
                background_candidates.append(
                    {
                        "id": f"dense_background_{frame_index}_{competitor_index}",
                        "bbox": {
                            "x": 0.18 + competitor_index * 0.11,
                            "y": 0.32 + (frame_index % 3) * 0.01,
                            "width": 0.052,
                            "height": 0.150,
                        },
                        "confidence": 0.82,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": frame_index,
                    }
                )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0008", "timestamp": 1.0, "motion_score": 0.96},
                    {"frame_id": "frame_0011", "timestamp": 1.4, "motion_score": 0.92},
                    {"frame_id": "frame_0014", "timestamp": 1.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_12_candidate_3",
                    selected_frame_index=selected_frame_index,
                    bbox={"x": 0.5348, "y": 0.3856, "width": 0.080, "height": 0.0974},
                    support_count=38,
                    selected_confidence=0.8892,
                    support_confidence=0.8242,
                    center_span=0.356,
                ),
                *background_candidates,
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_12_candidate_3")
        self.assertGreaterEqual(preview.candidates[0]["multiperson_competitor_count"], 24)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 5)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_multiperson_background_auto_lock_blocked_tiny_dense_risk",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_auto_locks_wide_moving_target_when_multiperson_is_background_only(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 19)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.4, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 1.9, "motion_score": 0.92},
                    {"frame_id": "frame_0015", "timestamp": 2.3, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4319, "y": 0.20, "width": 0.0939, "height": 0.3759},
                    "confidence": 0.8845,
                    "source": "yolo_zoomed_content",
                    "support_count": 46,
                    "support_frame_count": 11,
                    "support_confidence": 0.8811,
                    "support_center_span": 0.3886,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 6,
                },
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.18, "y": 0.33, "width": 0.050, "height": 0.150},
                    "confidence": 0.92,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 10,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.28, "y": 0.34, "width": 0.045, "height": 0.140},
                    "confidence": 0.90,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 10,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertGreater(preview.candidates[0]["support_center_span"], 0.32)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_background_auto_lock_blocks_same_anchor_competitor(self) -> None:
        candidate = {
            "id": "candidate_auto_stable",
            "bbox": {"x": 0.44, "y": 0.31, "width": 0.115, "height": 0.245},
            "confidence": 0.894,
            "source": "yolo_zoomed_content",
            "support_count": 34,
            "support_frame_count": 10,
            "support_confidence": 0.861,
            "support_center_span": 0.18,
            "support_motion_anchor_hits": 3,
            "multiperson_selected_pair_frame_count": 0,
            "multiperson_same_anchor_competitor_count": 1,
            "multiperson_competitor_count": 3,
            "multiperson_other_frame_ambiguous_count": 2,
        }

        flags = _stable_zoomed_multiperson_background_auto_lock_blocked_flags(candidate)

        self.assertFalse(_stable_zoomed_multiperson_background_auto_lock_allowed(candidate))
        self.assertEqual(flags, ["target_lock_zoomed_multiperson_background_auto_lock_blocked_direct_competitor_risk"])

    def test_build_target_preview_keeps_dense_moving_background_target_manual(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 21)]
        background_candidates: list[dict[str, object]] = []
        for offset, frame_index in enumerate((1, 3, 5, 7, 9, 11), start=1):
            frame = frame_names[frame_index]
            background_candidates.extend(
                [
                    {
                        "id": f"dense_background_left_{offset}",
                        "bbox": {"x": 0.14 + offset * 0.015, "y": 0.32, "width": 0.050, "height": 0.150},
                        "confidence": 0.89,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": frame_index,
                    },
                    {
                        "id": f"dense_background_right_{offset}",
                        "bbox": {"x": 0.72 - offset * 0.012, "y": 0.33, "width": 0.052, "height": 0.155},
                        "confidence": 0.88,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": frame_index,
                    },
                ]
            )
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 1.4, "motion_score": 0.96},
                    {"frame_id": "frame_0014", "timestamp": 2.0, "motion_score": 0.92},
                    {"frame_id": "frame_0018", "timestamp": 2.6, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_12_candidate_4",
                    selected_frame_index=5,
                    bbox={"x": 0.42, "y": 0.34, "width": 0.075, "height": 0.195},
                    support_count=42,
                    selected_confidence=0.892,
                    support_confidence=0.875,
                    center_span=0.34,
                ),
                *background_candidates,
            ],
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertTrue(str(preview.auto_candidate_id).startswith("anchor_12_candidate_4"))
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_competitor_count"], 12)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 5)
        self.assertGreaterEqual(preview.candidates[0]["support_center_span"], 0.28)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", flags)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_blocked_dense_moving_risk", flags)
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", flags)

    def test_build_target_preview_keeps_manual_for_supported_smaller_scale_competitor(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 19)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0011", "timestamp": 2.2, "motion_score": 0.96},
                    {"frame_id": "frame_0014", "timestamp": 2.8, "motion_score": 0.92},
                    {"frame_id": "frame_0017", "timestamp": 3.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4313, "y": 0.2000, "width": 0.0955, "height": 0.3749},
                    "confidence": 0.8839,
                    "source": "yolo_zoomed_content",
                    "support_count": 50,
                    "support_frame_count": 11,
                    "support_confidence": 0.8839,
                    "support_center_span": 0.3886,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 6,
                },
                {
                    "id": "anchor_20_candidate_5",
                    "bbox": {"x": 0.3961, "y": 0.2914, "width": 0.0795, "height": 0.1804},
                    "confidence": 0.8448,
                    "source": "yolo_zoomed_content",
                    "support_count": 51,
                    "support_frame_count": 10,
                    "support_confidence": 0.8448,
                    "support_center_span": 0.3886,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 6,
                },
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.18, "y": 0.33, "width": 0.050, "height": 0.150},
                    "confidence": 0.92,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 10,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.31, "y": 0.34, "width": 0.045, "height": 0.140},
                    "confidence": 0.90,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 10,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_multiperson_scale_competitor_manual_review",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_auto_locks_small_stable_target_with_background_only_competitors(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 18)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0011", "timestamp": 2.2, "motion_score": 0.96},
                    {"frame_id": "frame_0014", "timestamp": 2.8, "motion_score": 0.92},
                    {"frame_id": "frame_0017", "timestamp": 3.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_11_candidate_2",
                    selected_frame_index=3,
                    bbox={"x": 0.4561, "y": 0.412, "width": 0.0611, "height": 0.2159},
                    support_count=21,
                    selected_confidence=0.8932,
                    support_confidence=0.8454,
                    center_span=0.2131,
                ),
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.20, "y": 0.34, "width": 0.055, "height": 0.155},
                    "confidence": 0.91,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0017.jpg",
                    "anchor_index": 9,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.30, "y": 0.35, "width": 0.050, "height": 0.145},
                    "confidence": 0.90,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0017.jpg",
                    "anchor_index": 9,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_11_candidate_2")
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertGreater(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 0)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_auto_locks_sparse_background_multiperson_when_target_is_stable(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(7, 19)]
        target_candidates = self._zoomed_track_candidates(
            frame_names,
            selected_id="anchor_13_candidate_3",
            selected_frame_index=6,
            bbox={"x": 0.42, "y": 0.31, "width": 0.1439, "height": 0.2733},
            support_count=18,
            selected_confidence=0.9263,
            support_confidence=0.829,
            center_span=0.2525,
        )
        target_candidates[0].update(
            {
                "support_count": 18,
                "support_frame_count": 9,
                "support_confidence": 0.829,
            }
        )
        background_candidates = [
            {
                "id": f"sparse_background_{index}",
                "bbox": {"x": 0.18, "y": 0.33, "width": 0.050, "height": 0.150},
                "confidence": 0.89,
                "source": "yolo_zoomed_content",
                "anchor_frame": frame_names[index],
                "anchor_index": index,
            }
            for index in (1, 3, 8, 10)
        ]

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0013", "timestamp": 2.2, "motion_score": 0.92},
                    {"frame_id": "frame_0016", "timestamp": 2.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *target_candidates,
                *background_candidates,
            ],
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_13_candidate_3")
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertLessEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 4)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_nearest_center_distance"], 0.16)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", flags)
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", flags)

    def test_build_target_preview_auto_locks_isolated_high_confidence_zoomed_target(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(6, 17)]
        target_candidates = self._zoomed_track_candidates(
            frame_names,
            selected_id="anchor_12_candidate_3",
            selected_frame_index=6,
            bbox={"x": 0.44, "y": 0.32, "width": 0.1400, "height": 0.2700},
            support_count=26,
            selected_confidence=0.9311,
            support_confidence=0.932,
            center_span=0.281,
        )
        for candidate in target_candidates:
            candidate.update(
                {
                    "support_count": 26,
                    "support_frame_count": 10,
                    "support_confidence": 0.932,
                    "support_center_span": 0.281,
                    "support_motion_anchor_hits": 3,
                }
            )
        background_candidates = [
            {
                "id": f"isolated_background_{index}",
                "bbox": {"x": 0.18 + index * 0.03, "y": 0.34, "width": 0.050, "height": 0.150},
                "confidence": 0.91,
                "source": "yolo_zoomed_content",
                "anchor_frame": frame_names[index],
                "anchor_index": index,
            }
            for index in (1,)
        ]

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0008", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 2.2, "motion_score": 0.92},
                    {"frame_id": "frame_0015", "timestamp": 2.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[*target_candidates, *background_candidates],
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertTrue(str(preview.auto_candidate_id).startswith("anchor_12_candidate_3"))
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertLessEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 2)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_nearest_center_distance"], 0.20)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", flags)
        self.assertIn("target_lock_zoomed_multiperson_isolated_background_auto_lock_allowed", flags)
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", flags)

    def test_build_target_preview_keeps_isolated_zoomed_target_manual_when_competitor_is_close(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(6, 17)]
        target_candidates = self._zoomed_track_candidates(
            frame_names,
            selected_id="anchor_12_candidate_3",
            selected_frame_index=6,
            bbox={"x": 0.44, "y": 0.32, "width": 0.1400, "height": 0.2700},
            support_count=26,
            selected_confidence=0.9311,
            support_confidence=0.9039,
            center_span=0.281,
        )
        for candidate in target_candidates:
            candidate.update(
                {
                    "support_count": 26,
                    "support_frame_count": 10,
                    "support_confidence": 0.9039,
                    "support_center_span": 0.281,
                    "support_motion_anchor_hits": 3,
                }
            )
        close_background = {
            "id": "close_background",
            "bbox": {"x": 0.78, "y": 0.34, "width": 0.055, "height": 0.155},
            "confidence": 0.91,
            "source": "yolo_zoomed_content",
            "anchor_frame": frame_names[6],
            "anchor_index": 6,
        }

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0008", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 2.2, "motion_score": 0.92},
                    {"frame_id": "frame_0015", "timestamp": 2.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[*target_candidates, close_background],
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertIn("target_lock_zoomed_multiperson_manual_review", flags)
        self.assertNotIn("target_lock_zoomed_multiperson_isolated_background_auto_lock_allowed", flags)

    def test_build_target_preview_keeps_sparse_background_manual_when_competitors_are_close(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(7, 19)]
        target_candidates = self._zoomed_track_candidates(
            frame_names,
            selected_id="anchor_13_candidate_3",
            selected_frame_index=6,
            bbox={"x": 0.42, "y": 0.31, "width": 0.1439, "height": 0.2733},
            support_count=18,
            selected_confidence=0.9263,
            support_confidence=0.829,
            center_span=0.2525,
        )
        target_candidates[0].update(
            {
                "support_count": 18,
                "support_frame_count": 9,
                "support_confidence": 0.829,
            }
        )
        background_candidates = [
            {
                "id": f"close_background_{index}",
                "bbox": {"x": 0.36, "y": 0.33, "width": 0.050, "height": 0.150},
                "confidence": 0.89,
                "source": "yolo_zoomed_content",
                "anchor_frame": frame_names[index],
                "anchor_index": index,
            }
            for index in (1, 3, 8, 10)
        ]

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0013", "timestamp": 2.2, "motion_score": 0.92},
                    {"frame_id": "frame_0016", "timestamp": 2.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *target_candidates,
                *background_candidates,
            ],
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_13_candidate_3")
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertLess(preview.candidates[0]["multiperson_nearest_center_distance"], 0.16)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", flags)
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", flags)
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", flags)

    def test_build_target_preview_auto_locks_clear_compact_target_through_dense_other_frame_competitors(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(6, 18)]
        target_candidates = self._zoomed_track_candidates(
            frame_names,
            selected_id="anchor_13_candidate_2",
            selected_frame_index=7,
            bbox={"x": 0.4038, "y": 0.4413, "width": 0.1235, "height": 0.2562},
            support_count=27,
            selected_confidence=0.9145,
            support_confidence=0.8507,
            center_span=0.2447,
        )
        for candidate in target_candidates:
            candidate.update(
                {
                    "support_count": 27,
                    "support_frame_count": 11,
                    "support_confidence": 0.8507,
                    "support_center_span": 0.2447,
                    "support_motion_anchor_hits": 3,
                }
            )
        background_candidates: list[dict[str, object]] = []
        for offset, frame_index in enumerate([1, 2, 3, 4, 5, 8, 9, 10, 11], start=1):
            frame = frame_names[frame_index]
            background_candidates.extend(
                [
                    {
                        "id": f"dense_background_left_{offset}",
                        "bbox": {"x": 0.18 + offset * 0.006, "y": 0.34, "width": 0.050, "height": 0.150},
                        "confidence": 0.90,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": frame_index,
                    },
                    {
                        "id": f"dense_background_right_{offset}",
                        "bbox": {"x": 0.69 - offset * 0.005, "y": 0.35, "width": 0.052, "height": 0.145},
                        "confidence": 0.89,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": frame_index,
                    },
                ]
            )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0008", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 2.2, "motion_score": 0.92},
                    {"frame_id": "frame_0016", "timestamp": 2.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[*target_candidates, *background_candidates],
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_13_candidate_2")
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 5)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_competitor_count"], 12)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", flags)
        self.assertIn("target_lock_zoomed_multiperson_clear_compact_target_auto_lock_allowed", flags)
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", flags)

    def test_build_target_preview_keeps_clear_compact_like_target_manual_when_track_spans_too_far(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(6, 18)]
        target_candidates = self._zoomed_track_candidates(
            frame_names,
            selected_id="anchor_6_candidate_3",
            selected_frame_index=1,
            bbox={"x": 0.4317, "y": 0.3252, "width": 0.1127, "height": 0.2449},
            support_count=39,
            selected_confidence=0.9236,
            support_confidence=0.8083,
            center_span=0.3282,
        )
        for candidate in target_candidates:
            candidate.update(
                {
                    "support_count": 39,
                    "support_frame_count": 9,
                    "support_confidence": 0.8083,
                    "support_center_span": 0.3282,
                    "support_motion_anchor_hits": 3,
                }
            )
        background_candidates = [
            {
                "id": f"drifting_background_{index}",
                "bbox": {"x": 0.18 + index * 0.02, "y": 0.34, "width": 0.055, "height": 0.155},
                "confidence": 0.91,
                "source": "yolo_zoomed_content",
                "anchor_frame": frame_names[index],
                "anchor_index": index,
            }
            for index in (2, 3, 4, 5, 8, 9, 10)
        ]

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0008", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 2.2, "motion_score": 0.92},
                    {"frame_id": "frame_0016", "timestamp": 2.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[*target_candidates, *background_candidates],
        )

        flags = preview.candidates[0]["quality_flags"]
        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertGreater(preview.candidates[0]["support_center_span"], 0.26)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", flags)
        self.assertNotIn("target_lock_zoomed_multiperson_clear_compact_target_auto_lock_allowed", flags)

    def test_build_target_preview_keeps_dispersed_small_background_target_manual(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 32)]
        background_candidates: list[dict[str, object]] = []
        for offset, frame_index in enumerate([3, 6, 9, 12, 15, 18], start=1):
            frame = frame_names[frame_index]
            background_candidates.extend(
                [
                    {
                        "id": f"dispersed_background_left_{offset}",
                        "bbox": {"x": 0.18 + offset * 0.01, "y": 0.34, "width": 0.052, "height": 0.150},
                        "confidence": 0.89,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": frame_index,
                    },
                    {
                        "id": f"dispersed_background_right_{offset}",
                        "bbox": {"x": 0.72 - offset * 0.008, "y": 0.35, "width": 0.050, "height": 0.145},
                        "confidence": 0.86,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": frame_index,
                    },
                    {
                        "id": f"dispersed_background_far_{offset}",
                        "bbox": {"x": 0.84, "y": 0.36, "width": 0.045, "height": 0.135},
                        "confidence": 0.82,
                        "source": "yolo_zoomed_content",
                        "anchor_frame": frame,
                        "anchor_index": frame_index,
                    },
                ]
            )

        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 1.0, "motion_score": 0.96},
                    {"frame_id": "frame_0018", "timestamp": 1.8, "motion_score": 0.92},
                    {"frame_id": "frame_0026", "timestamp": 2.6, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_21_candidate_2",
                    selected_frame_index=13,
                    bbox={"x": 0.42, "y": 0.43, "width": 0.0567, "height": 0.1615},
                    support_count=24,
                    selected_confidence=0.8909,
                    support_confidence=0.8272,
                    center_span=0.3668,
                ),
                *background_candidates,
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_21_candidate_2")
        self.assertGreaterEqual(preview.candidates[0]["multiperson_competitor_count"], 12)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 5)
        self.assertGreaterEqual(preview.candidates[0]["support_center_span"], 0.32)
        self.assertLess(preview.candidates[0]["support_confidence"], 0.84)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_multiperson_background_auto_lock_blocked_dispersed_small_risk",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_keeps_moderate_small_moving_background_target_manual_with_two_motion_hits(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 18)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0013", "timestamp": 2.6, "motion_score": 0.96},
                    {"frame_id": "frame_0016", "timestamp": 3.2, "motion_score": 0.92},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="candidate_auto_stable",
                    selected_frame_index=5,
                    bbox={"x": 0.5151, "y": 0.4341, "width": 0.0764, "height": 0.1757},
                    support_count=22,
                    selected_confidence=0.7674,
                    support_confidence=0.7843,
                    center_span=0.2026,
                ),
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.22, "y": 0.32, "width": 0.060, "height": 0.170},
                    "confidence": 0.84,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0017.jpg",
                    "anchor_index": 9,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.40, "y": 0.33, "width": 0.055, "height": 0.160},
                    "confidence": 0.83,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0017.jpg",
                    "anchor_index": 9,
                },
                {
                    "id": "background_person_c",
                    "bbox": {"x": 0.21, "y": 0.32, "width": 0.060, "height": 0.170},
                    "confidence": 0.82,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 6,
                },
                {
                    "id": "background_person_d",
                    "bbox": {"x": 0.39, "y": 0.33, "width": 0.055, "height": 0.160},
                    "confidence": 0.81,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 6,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.candidates[0]["support_motion_anchor_hits"], 2)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_multiperson_background_auto_lock_blocked_small_moving_risk",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn("target_lock_stable_zoomed_auto_lock_blocked_by_manual_review", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_prefers_foreground_review_candidate_over_background_risk(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 33)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 1.2, "motion_score": 0.96},
                    {"frame_id": "frame_0019", "timestamp": 1.9, "motion_score": 0.92},
                    {"frame_id": "frame_0028", "timestamp": 2.8, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "stable_background_small",
                    "bbox": {"x": 0.4513, "y": 0.4584, "width": 0.0451, "height": 0.1048},
                    "confidence": 0.8676,
                    "source": "yolo_zoomed_content",
                    "support_count": 47,
                    "support_frame_count": 10,
                    "support_confidence": 0.7907,
                    "support_center_span": 0.3406,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
                {
                    "id": "stable_background_small_support_1",
                    "bbox": {"x": 0.4747, "y": 0.4547, "width": 0.0420, "height": 0.1119},
                    "confidence": 0.7202,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0009.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "stable_background_small_support_2",
                    "bbox": {"x": 0.5137, "y": 0.4623, "width": 0.0423, "height": 0.0792},
                    "confidence": 0.7250,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0017.jpg",
                    "anchor_index": 9,
                },
                {
                    "id": "foreground_skater",
                    "bbox": {"x": 0.5613, "y": 0.4863, "width": 0.0829, "height": 0.3612},
                    "confidence": 0.9235,
                    "source": "yolo_zoomed_content",
                    "support_count": 6,
                    "support_frame_count": 3,
                    "support_confidence": 0.9009,
                    "support_center_span": 0.1399,
                    "support_motion_anchor_hits": 1,
                    "multiperson_selected_pair_frame_count": 1,
                    "anchor_frame": "frame_0028.jpg",
                    "anchor_index": 20,
                },
                {
                    "id": "foreground_skater_early",
                    "bbox": {"x": 0.4655, "y": 0.4873, "width": 0.0736, "height": 0.3308},
                    "confidence": 0.8956,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0024.jpg",
                    "anchor_index": 16,
                },
                {
                    "id": "foreground_skater_duplicate",
                    "bbox": {"x": 0.5616, "y": 0.4855, "width": 0.0821, "height": 0.3633},
                    "confidence": 0.8287,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0028.jpg",
                    "anchor_index": 20,
                },
                {
                    "id": "background_competitor_left",
                    "bbox": {"x": 0.1500, "y": 0.4742, "width": 0.0217, "height": 0.0773},
                    "confidence": 0.8221,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0032.jpg",
                    "anchor_index": 24,
                },
                {
                    "id": "background_competitor_left_pair",
                    "bbox": {"x": 0.7500, "y": 0.4600, "width": 0.0350, "height": 0.1250},
                    "confidence": 0.8121,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0032.jpg",
                    "anchor_index": 24,
                },
                {
                    "id": "background_competitor_right",
                    "bbox": {"x": 0.1300, "y": 0.4950, "width": 0.0476, "height": 0.1052},
                    "confidence": 0.8254,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0019.jpg",
                    "anchor_index": 11,
                },
                {
                    "id": "background_competitor_right_pair",
                    "bbox": {"x": 0.7200, "y": 0.4550, "width": 0.0420, "height": 0.1250},
                    "confidence": 0.8154,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0019.jpg",
                    "anchor_index": 11,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "foreground_skater")
        self.assertEqual(preview.candidates[0]["id"], "foreground_skater")
        self.assertIn(
            "target_lock_foreground_manual_review_candidate_preferred_over_background_risk",
            preview.candidates[0]["quality_flags"],
        )
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["selected_candidate_id"], "foreground_skater")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_auto_locks_medium_background_only_target_at_relaxed_confidence(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 19)]
        support_candidates = [
            {
                "id": f"target_support_{index}",
                "bbox": {"x": 0.4021 + index * 0.002, "y": 0.3296, "width": 0.1226, "height": 0.2404},
                "confidence": 0.8358,
                "source": "yolo_zoomed_content",
                "anchor_frame": frame,
                "anchor_index": index,
            }
            for index, frame in enumerate(frame_names)
        ]
        support_candidates[4].update(
            {
                "id": "anchor_20_candidate_4",
                "confidence": 0.9164,
                "support_count": 20,
                "support_frame_count": 10,
                "support_confidence": 0.8358,
            }
        )
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 2.0, "motion_score": 0.96},
                    {"frame_id": "frame_0014", "timestamp": 2.8, "motion_score": 0.92},
                    {"frame_id": "frame_0017", "timestamp": 3.4, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *support_candidates,
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.18, "y": 0.33, "width": 0.050, "height": 0.150},
                    "confidence": 0.94,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 10,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.29, "y": 0.34, "width": 0.045, "height": 0.140},
                    "confidence": 0.91,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 10,
                },
                {
                    "id": "background_person_c",
                    "bbox": {"x": 0.20, "y": 0.32, "width": 0.050, "height": 0.150},
                    "confidence": 0.89,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0015.jpg",
                    "anchor_index": 7,
                },
                {
                    "id": "background_person_d",
                    "bbox": {"x": 0.31, "y": 0.33, "width": 0.045, "height": 0.140},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0015.jpg",
                    "anchor_index": 7,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_20_candidate_4")
        self.assertEqual(preview.candidates[0]["support_motion_anchor_hits"], 3)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_auto_locks_medium_stable_target_with_transient_background_person(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 19)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.8, "motion_score": 0.96},
                    {"frame_id": "frame_0014", "timestamp": 2.8, "motion_score": 0.92},
                    {"frame_id": "frame_0018", "timestamp": 3.6, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.39, "y": 0.26, "width": 0.218, "height": 0.5777},
                    "confidence": 0.8471,
                    "source": "yolo_zoomed_content",
                    "support_count": 20,
                    "support_frame_count": 11,
                    "support_confidence": 0.8933,
                    "support_center_span": 0.3056,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 5,
                },
                {
                    "id": "transient_background_left",
                    "bbox": {"x": 0.18, "y": 0.33, "width": 0.050, "height": 0.150},
                    "confidence": 0.91,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 10,
                },
                {
                    "id": "transient_background_right",
                    "bbox": {"x": 0.30, "y": 0.34, "width": 0.045, "height": 0.140},
                    "confidence": 0.89,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 10,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertGreater(preview.candidates[0]["bbox"]["height"], 0.40)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertLessEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 1)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_auto_locks_compact_stable_target_with_two_background_frames(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 19)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.8, "motion_score": 0.96},
                    {"frame_id": "frame_0014", "timestamp": 2.8, "motion_score": 0.92},
                    {"frame_id": "frame_0018", "timestamp": 3.6, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_6_candidate_2",
                    "bbox": {"x": 0.41, "y": 0.35, "width": 0.1126, "height": 0.2278},
                    "confidence": 0.9396,
                    "source": "yolo_zoomed_content",
                    "support_count": 22,
                    "support_frame_count": 11,
                    "support_confidence": 0.8307,
                    "support_center_span": 0.2513,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.18, "y": 0.33, "width": 0.050, "height": 0.150},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0016_bg.jpg",
                    "anchor_index": 80,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.30, "y": 0.34, "width": 0.045, "height": 0.140},
                    "confidence": 0.87,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0016_bg.jpg",
                    "anchor_index": 80,
                },
                {
                    "id": "background_person_c",
                    "bbox": {"x": 0.20, "y": 0.32, "width": 0.050, "height": 0.150},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018_bg.jpg",
                    "anchor_index": 100,
                },
                {
                    "id": "background_person_d",
                    "bbox": {"x": 0.31, "y": 0.33, "width": 0.045, "height": 0.140},
                    "confidence": 0.85,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0018_bg.jpg",
                    "anchor_index": 100,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "auto_locked")
        self.assertEqual(preview.auto_candidate_id, "anchor_6_candidate_2")
        self.assertEqual(preview.candidates[0]["support_motion_anchor_hits"], 3)
        self.assertEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 0)
        self.assertEqual(preview.candidates[0]["multiperson_other_frame_ambiguous_count"], 2)
        self.assertIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])
        self.assertNotIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_keeps_compact_target_manual_when_motion_support_is_weak(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 15)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0013", "timestamp": 2.6, "motion_score": 0.96},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="anchor_8_candidate_2",
                    selected_frame_index=4,
                    bbox={"x": 0.42, "y": 0.35, "width": 0.0850, "height": 0.2312},
                    support_count=17,
                    selected_confidence=0.8818,
                    support_confidence=0.7455,
                    center_span=0.2468,
                ),
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.20, "y": 0.33, "width": 0.050, "height": 0.150},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 6,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.31, "y": 0.33, "width": 0.045, "height": 0.140},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 6,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_8_candidate_2")
        self.assertLess(preview.candidates[0]["support_motion_anchor_hits"], 3)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_multiperson_review_low_motion_anchor_support",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn(
            "target_lock_zoomed_multiperson_review_low_support_confidence",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn(
            "target_lock_zoomed_multiperson_review_other_frame_competitors",
            preview.candidates[0]["quality_flags"],
        )
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_keeps_manual_when_supported_target_has_same_frame_competitors(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 17)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 1.4, "motion_score": 0.96},
                    {"frame_id": "frame_0012", "timestamp": 1.9, "motion_score": 0.92},
                    {"frame_id": "frame_0015", "timestamp": 2.3, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                *self._zoomed_track_candidates(
                    frame_names,
                    selected_id="candidate_auto_stable",
                    selected_frame_index=4,
                    bbox={"x": 0.42, "y": 0.42, "width": 0.060, "height": 0.1976},
                    support_count=36,
                    selected_confidence=0.8692,
                    support_confidence=0.8657,
                    center_span=0.215,
                ),
                {
                    "id": "same_frame_competitor_a",
                    "bbox": {"x": 0.24, "y": 0.34, "width": 0.050, "height": 0.145},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
                {
                    "id": "same_frame_competitor_b",
                    "bbox": {"x": 0.31, "y": 0.35, "width": 0.045, "height": 0.135},
                    "confidence": 0.84,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
                {
                    "id": "same_frame_competitor_c",
                    "bbox": {"x": 0.55, "y": 0.35, "width": 0.045, "height": 0.135},
                    "confidence": 0.82,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 4,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.candidates[0]["multiperson_selected_pair_frame_count"], 1)
        self.assertGreaterEqual(preview.candidates[0]["multiperson_same_anchor_competitor_count"], 3)
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])
        self.assertIn(
            "target_lock_zoomed_multiperson_review_same_anchor_competitor",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn(
            "target_lock_zoomed_multiperson_review_selected_pair_competitor",
            preview.candidates[0]["quality_flags"],
        )
        self.assertNotIn("target_lock_zoomed_multiperson_background_auto_lock_allowed", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_prefers_compact_motion_candidate_over_tall_multiperson_risk(self) -> None:
        frame_names = [f"frame_{index:04d}.jpg" for index in range(8, 20)]
        preview = build_target_preview(
            "analysis-1",
            frame_names,
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 1.0, "motion_score": 0.96},
                    {"frame_id": "frame_0013", "timestamp": 1.3, "motion_score": 0.92},
                    {"frame_id": "frame_0017", "timestamp": 1.7, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "standing_person_risk",
                    "bbox": {"x": 0.53, "y": 0.20, "width": 0.069, "height": 0.324},
                    "confidence": 0.9297,
                    "source": "yolo_zoomed_content",
                    "support_count": 48,
                    "support_frame_count": 11,
                    "support_confidence": 0.7635,
                    "support_center_span": 0.3301,
                    "support_motion_anchor_hits": 3,
                    "multiperson_selected_pair_frame_count": 1,
                    "multiperson_same_anchor_competitor_count": 2,
                    "multiperson_other_frame_ambiguous_count": 8,
                    "anchor_frame": "frame_0011.jpg",
                    "anchor_index": 3,
                },
                {
                    "id": "compact_motion_skater",
                    "bbox": {"x": 0.39, "y": 0.30, "width": 0.084, "height": 0.175},
                    "confidence": 0.8847,
                    "source": "yolo_zoomed_content",
                    "support_count": 51,
                    "support_frame_count": 10,
                    "support_confidence": 0.8448,
                    "support_center_span": 0.3215,
                    "support_motion_anchor_hits": 3,
                    "multiperson_selected_pair_frame_count": 1,
                    "multiperson_same_anchor_competitor_count": 2,
                    "multiperson_other_frame_ambiguous_count": 8,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 5,
                },
                {
                    "id": "background_person_a",
                    "bbox": {"x": 0.18, "y": 0.32, "width": 0.050, "height": 0.150},
                    "confidence": 0.90,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 5,
                },
                {
                    "id": "background_person_b",
                    "bbox": {"x": 0.76, "y": 0.34, "width": 0.050, "height": 0.145},
                    "confidence": 0.89,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 5,
                },
                {
                    "id": "background_person_c",
                    "bbox": {"x": 0.18, "y": 0.32, "width": 0.050, "height": 0.150},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0016.jpg",
                    "anchor_index": 8,
                },
                {
                    "id": "background_person_d",
                    "bbox": {"x": 0.76, "y": 0.34, "width": 0.050, "height": 0.145},
                    "confidence": 0.87,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0016.jpg",
                    "anchor_index": 8,
                },
                {
                    "id": "background_person_e",
                    "bbox": {"x": 0.18, "y": 0.32, "width": 0.050, "height": 0.150},
                    "confidence": 0.86,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0011.jpg",
                    "anchor_index": 3,
                },
                {
                    "id": "background_person_f",
                    "bbox": {"x": 0.76, "y": 0.34, "width": 0.050, "height": 0.145},
                    "confidence": 0.85,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0011.jpg",
                    "anchor_index": 3,
                },
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "compact_motion_skater")
        self.assertEqual(preview.candidates[0]["id"], "compact_motion_skater")
        self.assertIn(
            "target_lock_compact_motion_review_candidate_preferred_over_tall_multiperson_risk",
            preview.candidates[0]["quality_flags"],
        )
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

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
        self.assertEqual(selected["support_anchor_frames"][0], "frame_0001.jpg")
        self.assertEqual(selected["support_anchor_frames"][-1], "frame_0010.jpg")
        self.assertGreater(selected["support_center_span"], 0.0)
        self.assertGreater(selected["support_avg_area"], 0.0)

    def test_build_target_preview_exposes_candidate_support_motion_diagnostics(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg", "frame_0004.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0002", "timestamp": 0.4, "motion_score": 0.92},
                    {"frame_id": "frame_0004", "timestamp": 0.8, "motion_score": 0.84},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.44, "y": 0.42, "width": 0.09, "height": 0.20},
                    "confidence": 0.91,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0002.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "support_later",
                    "bbox": {"x": 0.47, "y": 0.41, "width": 0.085, "height": 0.21},
                    "confidence": 0.88,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0004.jpg",
                    "anchor_index": 3,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        candidate = preview.candidates[0]
        self.assertGreaterEqual(candidate["support_frame_count"], 2)
        self.assertEqual(candidate["support_motion_anchor_hits"], 2)
        self.assertEqual(candidate["support_anchor_frames"], ["frame_0002.jpg", "frame_0004.jpg"])
        self.assertGreater(candidate["support_center_span"], 0.0)
        self.assertGreater(candidate["support_avg_area"], 0.0)

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

    def test_build_target_preview_prefers_motion_supported_zoomed_target_over_higher_confidence_decoy(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0008.jpg", "frame_0012.jpg", "frame_0013.jpg", "frame_0030.jpg", "frame_0031.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 2.4, "motion_score": 0.96},
                    {"frame_id": "frame_0013", "timestamp": 2.6, "motion_score": 0.92},
                    {"frame_id": "frame_0030", "timestamp": 6.0, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "high_confidence_decoy",
                    "bbox": {"x": 0.6133, "y": 0.5734, "width": 0.039, "height": 0.2027},
                    "confidence": 0.8712,
                    "source": "yolo_zoomed_content",
                    "support_count": 8,
                    "support_frame_count": 5,
                    "support_confidence": 0.6872,
                    "anchor_frame": "frame_0008.jpg",
                    "anchor_index": 8,
                },
                {
                    "id": "motion_supported_skater",
                    "bbox": {"x": 0.4839, "y": 0.5486, "width": 0.0205, "height": 0.0893},
                    "confidence": 0.7987,
                    "source": "yolo_zoomed_content",
                    "support_count": 14,
                    "support_frame_count": 6,
                    "support_confidence": 0.8068,
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 12,
                },
                {
                    "id": "motion_supported_skater_later",
                    "bbox": {"x": 0.4861, "y": 0.5536, "width": 0.02, "height": 0.0912},
                    "confidence": 0.8153,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "motion_supported_skater_exit",
                    "bbox": {"x": 0.5038, "y": 0.4158, "width": 0.0424, "height": 0.1305},
                    "confidence": 0.8282,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0030.jpg",
                    "anchor_index": 30,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "motion_supported_skater")
        self.assertEqual(preview.candidates[0]["id"], "motion_supported_skater")
        self.assertGreaterEqual(preview.candidates[0]["support_confidence"], 0.8)
        self.assertEqual(preview.candidates[0]["support_motion_anchor_hits"], 3)

    def test_build_target_preview_keeps_partial_tiny_target_when_fuller_body_has_marginal_support_and_more_competitors(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0009.jpg", "frame_0012.jpg", "frame_0013.jpg", "frame_0030.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 2.4, "motion_score": 0.96},
                    {"frame_id": "frame_0013", "timestamp": 2.6, "motion_score": 0.92},
                    {"frame_id": "frame_0030", "timestamp": 6.0, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4839, "y": 0.5486, "width": 0.0205, "height": 0.0893},
                    "confidence": 0.7987,
                    "source": "yolo_zoomed_content",
                    "support_count": 14,
                    "support_frame_count": 6,
                    "support_confidence": 0.8068,
                    "support_center_span": 0.2499,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 12,
                },
                {
                    "id": "fuller_same_skater",
                    "bbox": {"x": 0.5038, "y": 0.4158, "width": 0.0424, "height": 0.1305},
                    "confidence": 0.8282,
                    "source": "yolo_zoomed_content",
                    "support_count": 15,
                    "support_frame_count": 6,
                    "support_confidence": 0.7748,
                    "support_center_span": 0.2879,
                    "multiperson_same_anchor_competitor_count": 1,
                    "multiperson_selected_pair_frame_count": 1,
                    "anchor_frame": "frame_0030.jpg",
                    "anchor_index": 30,
                },
                {
                    "id": "same_anchor_background_competitor",
                    "bbox": {"x": 0.4456, "y": 0.2759, "width": 0.02, "height": 0.1107},
                    "confidence": 0.5673,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0030.jpg",
                    "anchor_index": 30,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.candidates[0]["id"], "candidate_auto_stable")
        fuller = next(item for item in preview.candidates if item["id"] == "fuller_same_skater")
        self.assertNotIn(
            "target_lock_fuller_zoomed_body_candidate_preferred_over_partial_tiny_target",
            fuller.get("quality_flags", []),
        )
        payload = build_target_lock_payload(preview)
        self.assertEqual(payload["selected_candidate_id"], "candidate_auto_stable")
        self.assertEqual(payload["status"], "awaiting_manual")
        self.assertIsNone(payload["selected_bbox"])

    def test_build_target_preview_prefers_high_support_fuller_zoomed_body_over_tiny_box(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0008.jpg", "frame_0018.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0008", "timestamp": 1.6, "motion_score": 0.96},
                    {"frame_id": "frame_0018", "timestamp": 3.6, "motion_score": 0.92},
                ]
            },
            detected_candidates=[
                {
                    "id": "tiny_high_confidence_track",
                    "bbox": {"x": 0.6252, "y": 0.4289, "width": 0.021, "height": 0.0952},
                    "confidence": 0.8404,
                    "source": "yolo_zoomed_content",
                    "support_count": 32,
                    "support_frame_count": 9,
                    "support_confidence": 0.7544,
                    "support_center_span": 0.2555,
                    "anchor_frame": "frame_0018.jpg",
                    "anchor_index": 18,
                },
                {
                    "id": "fuller_high_support_track",
                    "bbox": {"x": 0.4921, "y": 0.4621, "width": 0.038, "height": 0.1373},
                    "confidence": 0.8374,
                    "source": "yolo_zoomed_content",
                    "support_count": 54,
                    "support_frame_count": 9,
                    "support_confidence": 0.7789,
                    "support_center_span": 0.3086,
                    "anchor_frame": "frame_0008.jpg",
                    "anchor_index": 8,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "fuller_high_support_track")
        self.assertEqual(preview.candidates[0]["id"], "fuller_high_support_track")
        self.assertIn(
            "target_lock_fuller_zoomed_body_candidate_preferred_over_partial_tiny_target",
            preview.candidates[0]["quality_flags"],
        )

    def test_build_target_preview_prefers_aggregate_zoomed_target_over_late_same_anchor_decoy(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0009.jpg", "frame_0012.jpg", "frame_0013.jpg", "frame_0014.jpg", "frame_0031.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 2.4, "motion_score": 0.96},
                    {"frame_id": "frame_0013", "timestamp": 2.6, "motion_score": 0.92},
                    {"frame_id": "frame_0031", "timestamp": 6.2, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4839, "y": 0.5486, "width": 0.0205, "height": 0.0893},
                    "confidence": 0.7987,
                    "source": "yolo_zoomed_content",
                    "support_count": 14,
                    "support_frame_count": 6,
                    "support_confidence": 0.8068,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 12,
                },
                {
                    "id": "anchor_11_candidate_2",
                    "bbox": {"x": 0.4754, "y": 0.5295, "width": 0.0225, "height": 0.089},
                    "confidence": 0.7423,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 11,
                },
                {
                    "id": "anchor_13_candidate_2",
                    "bbox": {"x": 0.4861, "y": 0.5536, "width": 0.02, "height": 0.0912},
                    "confidence": 0.8153,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "anchor_30_candidate_3",
                    "bbox": {"x": 0.5038, "y": 0.4158, "width": 0.0424, "height": 0.1305},
                    "confidence": 0.8282,
                    "source": "yolo_zoomed_content",
                    "support_count": 15,
                    "support_frame_count": 6,
                    "support_confidence": 0.7748,
                    "anchor_frame": "frame_0031.jpg",
                    "anchor_index": 30,
                },
                {
                    "id": "anchor_30_competitor",
                    "bbox": {"x": 0.4456, "y": 0.2759, "width": 0.02, "height": 0.1107},
                    "confidence": 0.5673,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0031.jpg",
                    "anchor_index": 30,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        selected = next(item for item in preview.candidates if item["id"] == "candidate_auto_stable")
        payload = build_target_lock_payload(preview, selected_candidate=selected, manual=True)
        self.assertEqual(payload["preview_frame"], "frame_0013.jpg")
        self.assertEqual(payload["preview_frame_index"], 12)

    def test_build_target_preview_prefers_aggregate_fuller_zoomed_target_over_supported_fragments(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0009.jpg", "frame_0012.jpg", "frame_0013.jpg", "frame_0014.jpg", "frame_0017.jpg", "frame_0019.jpg", "frame_0020.jpg", "frame_0021.jpg", "frame_0022.jpg", "frame_0024.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0013", "timestamp": 2.6, "motion_score": 0.96},
                    {"frame_id": "frame_0017", "timestamp": 3.4, "motion_score": 0.92},
                    {"frame_id": "frame_0021", "timestamp": 4.2, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_13_fragment",
                    "bbox": {"x": 0.4586, "y": 0.3512, "width": 0.0422, "height": 0.0946},
                    "confidence": 0.8867,
                    "source": "yolo_zoomed_content",
                    "support_count": 65,
                    "support_frame_count": 9,
                    "support_confidence": 0.8628,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "anchor_11_fragment",
                    "bbox": {"x": 0.4747, "y": 0.369, "width": 0.0371, "height": 0.0823},
                    "confidence": 0.8808,
                    "source": "yolo_zoomed_content",
                    "support_count": 66,
                    "support_frame_count": 9,
                    "support_confidence": 0.8628,
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 12,
                },
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.4146, "y": 0.4521, "width": 0.0297, "height": 0.1871},
                    "confidence": 0.8088,
                    "source": "yolo_zoomed_content",
                    "support_count": 41,
                    "support_frame_count": 9,
                    "support_confidence": 0.8628,
                    "anchor_frame": "frame_0013.jpg",
                    "anchor_index": 13,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "candidate_auto_stable")
        self.assertEqual(preview.candidates[0]["id"], "candidate_auto_stable")
        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertIn("target_lock_zoomed_multiperson_manual_review", preview.candidates[0]["quality_flags"])

    def test_build_target_preview_keeps_supported_fragment_when_aggregate_is_not_fuller_or_stabler(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0009.jpg", "frame_0011.jpg", "frame_0012.jpg", "frame_0014.jpg", "frame_0017.jpg", "frame_0019.jpg", "frame_0021.jpg", "frame_0024.jpg", "frame_0026.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0014", "timestamp": 2.8, "motion_score": 0.96},
                    {"frame_id": "frame_0017", "timestamp": 3.4, "motion_score": 0.92},
                    {"frame_id": "frame_0021", "timestamp": 4.2, "motion_score": 0.88},
                ]
            },
            detected_candidates=[
                {
                    "id": "anchor_16_candidate_5",
                    "bbox": {"x": 0.456, "y": 0.428, "width": 0.0739, "height": 0.1044},
                    "confidence": 0.8692,
                    "source": "yolo_zoomed_content",
                    "support_count": 42,
                    "support_frame_count": 9,
                    "support_confidence": 0.8377,
                    "anchor_frame": "frame_0017.jpg",
                    "anchor_index": 16,
                },
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.445, "y": 0.405, "width": 0.0677, "height": 0.1253},
                    "confidence": 0.8669,
                    "source": "yolo_zoomed_content",
                    "support_count": 41,
                    "support_frame_count": 9,
                    "support_confidence": 0.8405,
                    "anchor_frame": "frame_0014.jpg",
                    "anchor_index": 13,
                },
                {
                    "id": "anchor_09_same_track",
                    "bbox": {"x": 0.286, "y": 0.408, "width": 0.068, "height": 0.125},
                    "confidence": 0.842,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0009.jpg",
                    "anchor_index": 9,
                },
                {
                    "id": "anchor_26_same_track",
                    "bbox": {"x": 0.616, "y": 0.408, "width": 0.068, "height": 0.126},
                    "confidence": 0.821,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0026.jpg",
                    "anchor_index": 26,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "anchor_16_candidate_5")
        self.assertEqual(preview.candidates[0]["id"], "anchor_16_candidate_5")
        aggregate = next(item for item in preview.candidates if item["id"] == "candidate_auto_stable")
        self.assertGreater(aggregate["support_center_span"], 0.32)
        self.assertLess(aggregate["bbox"]["height"], 0.14)

    def test_build_target_preview_prefers_stronger_same_scale_track_over_aggregate_empty_box(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0009.jpg", "frame_0011.jpg", "frame_0020.jpg", "frame_0028.jpg"],
            motion_scores={
                "selected": [
                    {"frame_id": "frame_0009", "timestamp": 0.3, "motion_score": 0.88},
                    {"frame_id": "frame_0020", "timestamp": 0.67, "motion_score": 0.92},
                    {"frame_id": "frame_0028", "timestamp": 0.93, "motion_score": 0.96},
                ]
            },
            detected_candidates=[
                {
                    "id": "candidate_auto_stable",
                    "bbox": {"x": 0.3729, "y": 0.495, "width": 0.0476, "height": 0.1052},
                    "confidence": 0.8254,
                    "source": "yolo_zoomed_content",
                    "support_count": 34,
                    "support_frame_count": 10,
                    "support_confidence": 0.815,
                    "support_center_span": 0.259,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0028.jpg",
                    "anchor_index": 27,
                },
                {
                    "id": "red_skater_same_scale_track",
                    "bbox": {"x": 0.4513, "y": 0.4584, "width": 0.0451, "height": 0.1048},
                    "confidence": 0.8676,
                    "source": "yolo_zoomed_content",
                    "support_count": 47,
                    "support_frame_count": 10,
                    "support_confidence": 0.7907,
                    "support_center_span": 0.3406,
                    "support_motion_anchor_hits": 3,
                    "anchor_frame": "frame_0011.jpg",
                    "anchor_index": 11,
                },
            ],
        )

        self.assertEqual(preview.auto_candidate_id, "red_skater_same_scale_track")
        self.assertEqual(preview.candidates[0]["id"], "red_skater_same_scale_track")

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

    def test_build_target_preview_keeps_weak_distant_single_jump_candidate_manual(self) -> None:
        preview = build_target_preview(
            "analysis-1",
            ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg", "frame_0004.jpg"],
            analysis_profile="jump",
            detected_candidates=[
                {
                    "id": "anchor_18_candidate_1",
                    "bbox": {"x": 0.4459, "y": 0.5062, "width": 0.0382, "height": 0.0993},
                    "confidence": 0.5427,
                    "source": "yolo_zoomed_content",
                    "support_count": 4,
                    "support_frame_count": 3,
                    "support_confidence": 0.4921,
                    "anchor_frame": "frame_0003.jpg",
                    "anchor_index": 2,
                }
            ],
        )

        self.assertEqual(preview.target_lock_status, "awaiting_manual")
        self.assertEqual(preview.auto_candidate_id, "anchor_18_candidate_1")
        self.assertNotIn("target_lock_distant_single_jump_auto_locked", preview.candidates[0].get("quality_flags", []))
        payload = build_target_lock_payload(preview)
        self.assertIsNone(payload["selected_bbox"])
        self.assertIn("target_lock_manual_review_low_confidence", payload["quality_flags"])

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
