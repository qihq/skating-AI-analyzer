from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.analysis import _build_bbox_per_frame
from app.services.person_tracker import PERSON_TRACKER_FAILED_FLAG, PERSON_TRACKER_UNAVAILABLE_FLAG, PersonTrackerUnavailable


class AnalysisBBoxTrackingTests(unittest.TestCase):
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
        with (
            patch("app.routers.analysis.track_person_bbox_detailed", return_value=(person_result, ["person_flag"], diagnostics)) as person_mock,
            patch("app.routers.analysis.track_bbox", side_effect=AssertionError("CSRT should not run")),
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
        )

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

        with (
            patch("app.routers.analysis.track_person_bbox_detailed", side_effect=PersonTrackerUnavailable("missing")),
            patch("app.routers.analysis.track_bbox", return_value=(csrt_result, ["csrt_flag"])) as csrt_mock,
        ):
            result = _build_bbox_per_frame(frames, target_lock, effective_fps=8.0)

        self.assertEqual(result, csrt_result)
        self.assertEqual(target_lock["tracker_type"], "csrt_fallback")
        self.assertIn(PERSON_TRACKER_UNAVAILABLE_FLAG, target_lock["quality_flags"])
        self.assertIn("csrt_flag", target_lock["quality_flags"])
        csrt_mock.assert_called_once_with(frames, target_lock["selected_bbox"], initial_frame_index=1)

    def test_build_bbox_per_frame_uses_static_bbox_when_all_trackers_fail(self) -> None:
        frames = [Path("frame_0001.jpg"), Path("frame_0002.jpg"), Path("frame_0003.jpg")]
        selected_bbox = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
        target_lock = {"selected_bbox": selected_bbox, "quality_flags": []}

        with (
            patch("app.routers.analysis.track_person_bbox_detailed", side_effect=RuntimeError("boom")),
            patch("app.routers.analysis.track_bbox", side_effect=RuntimeError("csrt boom")),
        ):
            result = _build_bbox_per_frame(frames, target_lock)

        self.assertEqual(result, [selected_bbox, selected_bbox, selected_bbox])
        self.assertEqual(target_lock["tracker_type"], "static_fallback")
        self.assertIn(PERSON_TRACKER_FAILED_FLAG, target_lock["quality_flags"])
        self.assertIn("bbox_tracker_failed_fallback", target_lock["quality_flags"])


if __name__ == "__main__":
    unittest.main()
