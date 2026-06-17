from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.analysis import _build_bbox_per_frame, _tiny_target_pose_tracking_risk_flags
from app.services.person_tracker import (
    PERSON_TRACKER_FAILED_FLAG,
    PERSON_TRACKER_FINAL_UNRECOVERED_FLAG,
    PERSON_TRACKER_MANUAL_LOCK_FALLBACK_BLOCKED_FLAG,
    PERSON_TRACKER_MANUAL_LOCK_SUPPORT_ANCHOR_BLOCKED_FLAG,
    PERSON_TRACKER_TARGET_LOST_FLAG,
    PERSON_TRACKER_UNAVAILABLE_FLAG,
    PersonTrackerUnavailable,
)


class AnalysisBBoxTrackingTests(unittest.TestCase):
    def test_tiny_target_pending_only_tracker_loss_is_not_low_pose_risk(self) -> None:
        target_lock = {
            "selected_bbox": {"x": 0.45, "y": 0.45, "width": 0.025, "height": 0.08},
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_detector_relock_pending",
            ],
            "person_tracker_diagnostics": [
                {"state": "tracked"},
                {"state": "full_frame_yolo_relock_pending"},
                {"state": "tracked"},
                {"state": "tracked"},
            ],
        }
        pose_data = {"pose_diagnostics": {"tracked_frames": 4, "total_frames": 4}}

        self.assertEqual(_tiny_target_pose_tracking_risk_flags(target_lock, pose_data), [])

    def test_tiny_target_hard_rejection_still_flags_low_pose_risk(self) -> None:
        target_lock = {
            "selected_bbox": {"x": 0.45, "y": 0.45, "width": 0.025, "height": 0.08},
            "quality_flags": [
                "person_tracker_target_lost",
                "person_tracker_continuity_rejected",
            ],
            "person_tracker_diagnostics": [
                {"state": "tracked"},
                {"state": "continuity_rejected"},
                {"state": "tracked"},
            ],
        }
        pose_data = {"pose_diagnostics": {"tracked_frames": 3, "total_frames": 3}}

        self.assertEqual(
            _tiny_target_pose_tracking_risk_flags(target_lock, pose_data),
            ["person_tracker_tiny_target_low_pose_tracking_risk"],
        )

    def test_build_bbox_per_frame_prefers_person_tracker(self) -> None:
        frames = [Path("frame_0001.jpg"), Path("frame_0002.jpg")]
        target_lock = {
            "selected_bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            "preview_frame_index": 0,
            "quality_flags": [],
        }
        person_result = [
            {"x": 0.11, "y": 0.2, "width": 0.3, "height": 0.4},
            {"x": 0.12, "y": 0.2, "width": 0.3, "height": 0.4},
        ]

        diagnostics = [{"frame": "frame_0001.jpg", "state": "tracked"}]
        person_mock = Mock(return_value=(person_result, ["person_flag"], diagnostics))
        with (
            patch.dict(_build_bbox_per_frame.__globals__, {"track_person_bbox_detailed": person_mock}),
            patch.dict(_build_bbox_per_frame.__globals__, {"track_bbox": Mock(side_effect=AssertionError("CSRT should not run"))}),
        ):
            result = _build_bbox_per_frame(frames, target_lock, effective_fps=12.0)

        self.assertEqual(result, person_result)
        self.assertEqual(target_lock["bbox_per_frame"], person_result)
        self.assertEqual(target_lock["person_tracker_diagnostics"], diagnostics)
        self.assertEqual(target_lock["tracker_type"], "yolo_bytetrack")
        self.assertIn("person_flag", target_lock["quality_flags"])
        person_mock.assert_called_once_with(
            frames,
            target_lock["selected_bbox"],
            initial_frame_index=0,
            effective_fps=12.0,
            support_anchor_bboxes_by_frame={},
            manual_lock_mode=False,
        )

    def test_build_bbox_per_frame_passes_manual_lock_mode_to_person_tracker(self) -> None:
        frames = [Path("frame_0001.jpg"), Path("frame_0002.jpg")]
        target_lock = {
            "selected_bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            "preview_frame_index": 0,
            "manual_override": True,
            "quality_flags": [],
        }
        person_result = [
            {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        ]
        person_mock = Mock(return_value=(person_result, [], [{"frame": "frame_0001.jpg", "state": "tracked"}]))

        with (
            patch.dict(_build_bbox_per_frame.__globals__, {"track_person_bbox_detailed": person_mock}),
            patch.dict(_build_bbox_per_frame.__globals__, {"track_bbox": Mock(side_effect=AssertionError("CSRT should not run"))}),
        ):
            result = _build_bbox_per_frame(frames, target_lock, effective_fps=12.0)

        self.assertEqual(result, person_result)
        self.assertTrue(person_mock.call_args.kwargs["manual_lock_mode"])

    def test_build_bbox_per_frame_passes_selected_support_anchor_hints(self) -> None:
        frames = [Path("frame_0009.jpg"), Path("frame_0012.jpg"), Path("frame_0019.jpg")]
        selected_bbox = {"x": 0.572, "y": 0.204, "width": 0.042, "height": 0.238}
        support_bbox = {"x": 0.54, "y": 0.22, "width": 0.04, "height": 0.23}
        target_lock = {
            "selected_bbox": selected_bbox,
            "preview_frame_index": 2,
            "selected_candidate_id": "anchor_18_candidate_5",
            "quality_flags": [],
            "candidates": [
                {
                    "id": "anchor_18_candidate_5",
                    "bbox": selected_bbox,
                    "confidence": 0.817,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0019.jpg",
                    "anchor_index": 2,
                    "support_anchor_frames": ["frame_0009.jpg", "frame_0012.jpg", "frame_0019.jpg"],
                },
                {
                    "id": "anchor_18_candidate_5_support_1",
                    "bbox": support_bbox,
                    "confidence": 0.74,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 1,
                },
                {
                    "id": "foreground",
                    "bbox": {"x": 0.3, "y": 0.1, "width": 0.25, "height": 0.7},
                    "confidence": 0.95,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0009.jpg",
                    "anchor_index": 0,
                },
            ],
        }
        person_result = [selected_bbox, support_bbox, selected_bbox]
        diagnostics = [{"frame": frame.name, "state": "tracked"} for frame in frames]
        person_mock = Mock(return_value=(person_result, ["person_flag"], diagnostics))

        with (
            patch.dict(_build_bbox_per_frame.__globals__, {"track_person_bbox_detailed": person_mock}),
            patch.dict(_build_bbox_per_frame.__globals__, {"track_bbox": Mock(side_effect=AssertionError("CSRT should not run"))}),
        ):
            result = _build_bbox_per_frame(frames, target_lock, effective_fps=12.0)

        self.assertEqual(result, person_result)
        kwargs = person_mock.call_args.kwargs
        self.assertEqual(sorted(kwargs["support_anchor_bboxes_by_frame"]), [1, 2])
        self.assertEqual(kwargs["support_anchor_bboxes_by_frame"][1]["bbox"], support_bbox)
        self.assertEqual(kwargs["support_anchor_bboxes_by_frame"][2]["bbox"], selected_bbox)

    def test_manual_lock_blocks_selected_support_anchor_hints(self) -> None:
        frames = [Path("frame_0009.jpg"), Path("frame_0012.jpg"), Path("frame_0019.jpg")]
        selected_bbox = {"x": 0.572, "y": 0.204, "width": 0.042, "height": 0.238}
        support_bbox = {"x": 0.54, "y": 0.22, "width": 0.04, "height": 0.23}
        target_lock = {
            "selected_bbox": selected_bbox,
            "preview_frame_index": 2,
            "selected_candidate_id": "anchor_18_candidate_5",
            "manual_override": True,
            "quality_flags": [],
            "candidates": [
                {
                    "id": "anchor_18_candidate_5",
                    "bbox": selected_bbox,
                    "confidence": 0.817,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0019.jpg",
                    "anchor_index": 2,
                    "support_anchor_frames": ["frame_0009.jpg", "frame_0012.jpg", "frame_0019.jpg"],
                },
                {
                    "id": "anchor_18_candidate_5_support_1",
                    "bbox": support_bbox,
                    "confidence": 0.74,
                    "source": "yolo_zoomed_content",
                    "anchor_frame": "frame_0012.jpg",
                    "anchor_index": 1,
                },
            ],
        }
        person_result = [selected_bbox, selected_bbox, selected_bbox]
        diagnostics = [{"frame": frame.name, "state": "tracked"} for frame in frames]
        person_mock = Mock(return_value=(person_result, [], diagnostics))

        with (
            patch.dict(_build_bbox_per_frame.__globals__, {"track_person_bbox_detailed": person_mock}),
            patch.dict(_build_bbox_per_frame.__globals__, {"track_bbox": Mock(side_effect=AssertionError("CSRT should not run"))}),
        ):
            result = _build_bbox_per_frame(frames, target_lock, effective_fps=12.0)

        self.assertEqual(result, person_result)
        kwargs = person_mock.call_args.kwargs
        self.assertTrue(kwargs["manual_lock_mode"])
        self.assertEqual(kwargs["support_anchor_bboxes_by_frame"], {})
        self.assertIn(PERSON_TRACKER_MANUAL_LOCK_SUPPORT_ANCHOR_BLOCKED_FLAG, target_lock["quality_flags"])

    def test_build_bbox_per_frame_falls_back_to_csrt_when_person_tracker_unavailable(self) -> None:
        frames = [Path("frame_0001.jpg"), Path("frame_0002.jpg")]
        target_lock = {
            "selected_bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            "preview_frame_index": 1,
            "quality_flags": [],
        }
        csrt_result = [
            {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
            {"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.4},
        ]
        csrt_mock = Mock(return_value=(csrt_result, ["csrt_flag"]))

        with (
            patch.dict(_build_bbox_per_frame.__globals__, {"track_person_bbox_detailed": Mock(side_effect=PersonTrackerUnavailable("missing"))}),
            patch.dict(_build_bbox_per_frame.__globals__, {"track_bbox": csrt_mock}),
        ):
            result = _build_bbox_per_frame(frames, target_lock, effective_fps=8.0)

        self.assertEqual(result, csrt_result)
        self.assertEqual(target_lock["tracker_type"], "csrt_fallback")
        self.assertIn(PERSON_TRACKER_UNAVAILABLE_FLAG, target_lock["quality_flags"])
        self.assertIn("csrt_flag", target_lock["quality_flags"])
        csrt_mock.assert_called_once_with(frames, target_lock["selected_bbox"], initial_frame_index=1)

    def test_manual_lock_blocks_csrt_fallback_when_person_tracker_unavailable(self) -> None:
        frames = [Path("frame_0001.jpg"), Path("frame_0002.jpg")]
        selected_bbox = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        target_lock = {
            "selected_bbox": selected_bbox,
            "preview_frame_index": 1,
            "manual_override": True,
            "quality_flags": [],
        }
        csrt_mock = Mock(side_effect=AssertionError("CSRT should not run after manual target lock"))

        with (
            patch.dict(_build_bbox_per_frame.__globals__, {"track_person_bbox_detailed": Mock(side_effect=PersonTrackerUnavailable("missing"))}),
            patch.dict(_build_bbox_per_frame.__globals__, {"track_bbox": csrt_mock}),
        ):
            result = _build_bbox_per_frame(frames, target_lock, effective_fps=8.0)

        self.assertEqual(result, [selected_bbox, selected_bbox])
        self.assertFalse(csrt_mock.called)
        self.assertEqual(target_lock["tracker_type"], "manual_lock_static_lost")
        self.assertIn(PERSON_TRACKER_UNAVAILABLE_FLAG, target_lock["quality_flags"])
        self.assertIn(PERSON_TRACKER_MANUAL_LOCK_FALLBACK_BLOCKED_FLAG, target_lock["quality_flags"])
        self.assertIn(PERSON_TRACKER_TARGET_LOST_FLAG, target_lock["quality_flags"])
        self.assertIn(PERSON_TRACKER_FINAL_UNRECOVERED_FLAG, target_lock["quality_flags"])
        self.assertEqual(
            [item["state"] for item in target_lock["person_tracker_diagnostics"]],
            ["lost_reused", "lost_reused"],
        )
        self.assertIn(
            "manual_lock_fallback_blocked",
            target_lock["person_tracker_diagnostics"][0]["rejected_reasons"],
        )

    def test_manual_lock_blocks_csrt_fallback_when_person_tracker_fails(self) -> None:
        frames = [Path("frame_0001.jpg")]
        selected_bbox = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        target_lock = {
            "selected_bbox": selected_bbox,
            "manual_override": True,
            "quality_flags": [],
        }

        with (
            patch.dict(_build_bbox_per_frame.__globals__, {"track_person_bbox_detailed": Mock(side_effect=RuntimeError("boom"))}),
            patch.dict(_build_bbox_per_frame.__globals__, {"track_bbox": Mock(side_effect=AssertionError("CSRT should not run"))}),
        ):
            result = _build_bbox_per_frame(frames, target_lock)

        self.assertEqual(result, [selected_bbox])
        self.assertEqual(target_lock["tracker_type"], "manual_lock_static_lost")
        self.assertIn(PERSON_TRACKER_FAILED_FLAG, target_lock["quality_flags"])
        self.assertIn(PERSON_TRACKER_MANUAL_LOCK_FALLBACK_BLOCKED_FLAG, target_lock["quality_flags"])

    def test_build_bbox_per_frame_uses_static_bbox_when_all_trackers_fail(self) -> None:
        frames = [Path("frame_0001.jpg"), Path("frame_0002.jpg"), Path("frame_0003.jpg")]
        selected_bbox = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        target_lock = {"selected_bbox": selected_bbox, "quality_flags": []}

        with (
            patch.dict(_build_bbox_per_frame.__globals__, {"track_person_bbox_detailed": Mock(side_effect=RuntimeError("boom"))}),
            patch.dict(_build_bbox_per_frame.__globals__, {"track_bbox": Mock(side_effect=RuntimeError("csrt boom"))}),
        ):
            result = _build_bbox_per_frame(frames, target_lock)

        self.assertEqual(result, [selected_bbox, selected_bbox, selected_bbox])
        self.assertEqual(target_lock["tracker_type"], "static_fallback")
        self.assertIn(PERSON_TRACKER_FAILED_FLAG, target_lock["quality_flags"])
        self.assertIn("bbox_tracker_failed_fallback", target_lock["quality_flags"])


if __name__ == "__main__":
    unittest.main()
