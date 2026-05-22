from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.person_tracker import (
    PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG,
    PERSON_TRACKER_CONTINUITY_REJECTED_FLAG,
    PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG,
    PERSON_TRACKER_DETECTOR_RELOCKED_FLAG,
    PERSON_TRACKER_LOCAL_ZOOM_RELOCK_ATTEMPTED_FLAG,
    PERSON_TRACKER_RELOCK_PENDING_FLAG,
    PERSON_TRACKER_RELOCK_REJECTED_FLAG,
    PERSON_TRACKER_RELOCKED_FLAG,
    PERSON_TRACKER_TARGET_LOST_FLAG,
    PersonBBoxTracker,
    PersonTrackerUnavailable,
    _YOLO_MODEL_NAME,
    _YOLO_MODEL_PATH_ENV,
    _resolve_yolo_model_path,
    _xyxy_to_bbox,
    track_person_bbox,
    track_person_bbox_detailed,
)


class _FakeDetections:
    def __init__(
        self,
        xyxy: list[tuple[float, float, float, float]],
        tracker_id: list[int],
        confidence: list[float] | None = None,
    ) -> None:
        self.xyxy = np.array(xyxy, dtype=np.float32)
        self.tracker_id = np.array(tracker_id, dtype=int)
        self.confidence = np.array(confidence or [0.9 for _ in xyxy], dtype=np.float32)

    def __len__(self) -> int:
        return len(self.xyxy)


class PersonTrackerTests(unittest.TestCase):
    def test_converts_pixel_xyxy_to_normalized_bbox(self) -> None:
        bbox = _xyxy_to_bbox((20, 12, 60, 72), frame_width=200, frame_height=120)

        self.assertEqual(bbox, {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.5})

    def test_tracks_from_manual_preview_frame_index_and_splices_sequences(self) -> None:
        frame_paths = [Path(f"frame_{index:04d}.jpg") for index in range(5)]
        initial = {"x": 0.3, "y": 0.2, "width": 0.1, "height": 0.2}
        backward = [
            {"x": 0.3, "y": 0.2, "width": 0.1, "height": 0.2},
            {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2},
            {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.2},
        ]
        forward = [
            {"x": 0.3, "y": 0.2, "width": 0.1, "height": 0.2},
            {"x": 0.4, "y": 0.2, "width": 0.1, "height": 0.2},
            {"x": 0.5, "y": 0.2, "width": 0.1, "height": 0.2},
        ]

        with patch("app.services.person_tracker._track_forward", side_effect=[(backward, []), (forward, [])]):
            tracked, flags = track_person_bbox(frame_paths, initial, initial_frame_index=2, effective_fps=12.0)

        self.assertEqual([item["x"] for item in tracked], [0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertIn(PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG, flags)

    def test_dependency_unavailable_surfaces_controlled_exception(self) -> None:
        frame_paths = [Path("frame_0001.jpg")]
        with patch("app.services.person_tracker._track_forward", side_effect=PersonTrackerUnavailable("missing")):
            with self.assertRaises(PersonTrackerUnavailable):
                track_person_bbox(frame_paths, {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2})

    def test_yolo_model_path_uses_env_before_default(self) -> None:
        with patch.dict("os.environ", {_YOLO_MODEL_PATH_ENV: "/models/custom-yolo.pt"}):
            self.assertEqual(_resolve_yolo_model_path(), "/models/custom-yolo.pt")

    def test_yolo_model_path_falls_back_to_model_name_when_not_mounted(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("app.services.person_tracker._YOLO_MOUNTED_MODEL_PATH") as mounted_path,
        ):
            mounted_path.exists.return_value = False
            self.assertEqual(_resolve_yolo_model_path(), _YOLO_MODEL_NAME)

    def test_relock_rejects_far_passerby_after_lost_frames(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (10.0, 10.0, 50.0, 90.0)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 3

        with (
            patch.object(tracker, "_detect", return_value=[(180.0, 10.0, 220.0, 90.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([(180.0, 10.0, 220.0, 90.0)], [2])),
        ):
            result = tracker.process_frame(np.zeros((120, 240, 3), dtype=np.uint8), tracker._last_known_xyxy)

        self.assertIsNone(result)
        self.assertNotEqual(tracker._target_tracker_id, 2)

    def test_continuity_rejects_sudden_area_jump_and_reuses_previous_bbox(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._target_tracker_id = 1

        with (
            patch.object(tracker, "_read_frame", return_value=np.zeros((120, 240, 3), dtype=np.uint8)),
            patch.object(tracker, "_detect", return_value=[(15.0, 5.0, 120.0, 118.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([(15.0, 5.0, 120.0, 118.0)], [1])),
        ):
            tracked, flags, diagnostics = tracker.track_sequence_detailed(
                [Path("frame_0001.jpg")],
                {"x": 0.0833, "y": 0.1667, "width": 0.1667, "height": 0.6667},
            )

        self.assertEqual(tracked[0], {"x": 0.0833, "y": 0.1667, "width": 0.1667, "height": 0.6667})
        self.assertIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, flags)
        self.assertEqual(diagnostics[0]["state"], "continuity_rejected")
        self.assertIn("area_ratio", diagnostics[0]["rejected_reasons"])

    def test_initial_small_manual_bbox_can_bootstrap_to_full_person_detection(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())

        with (
            patch.object(tracker, "_read_frame", return_value=np.zeros((240, 320, 3), dtype=np.uint8)),
            patch.object(tracker, "_detect", return_value=[(100.0, 45.0, 124.0, 170.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([(100.0, 45.0, 124.0, 170.0)], [1])),
        ):
            tracked, flags, diagnostics = tracker.track_sequence_detailed(
                [Path("frame_0001.jpg")],
                {"x": 0.31, "y": 0.29, "width": 0.055, "height": 0.21},
            )

        self.assertEqual(diagnostics[0]["state"], "tracked")
        self.assertEqual(tracked[0], {"x": 0.3125, "y": 0.1875, "width": 0.075, "height": 0.5208})
        self.assertNotIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, flags)

    def test_relock_requires_two_consecutive_confirmations_before_switching_id(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 3

        frame = np.zeros((120, 240, 3), dtype=np.uint8)
        relock_detection = _FakeDetections([(22.0, 22.0, 62.0, 102.0)], [2])
        with (
            patch.object(tracker, "_detect", return_value=[(22.0, 22.0, 62.0, 102.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=relock_detection),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertEqual(tracker._target_tracker_id, 2)
        self.assertEqual(second, (22.0, 22.0, 62.0, 102.0))
        self.assertEqual(second_diag["state"], "relocked")
        self.assertIn(PERSON_TRACKER_RELOCK_PENDING_FLAG, tracker.quality_flags)
        self.assertIn(PERSON_TRACKER_RELOCKED_FLAG, tracker.quality_flags)

    def test_relock_records_rejected_candidate_diagnostics(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (10.0, 10.0, 50.0, 90.0)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 3

        with (
            patch.object(tracker, "_detect", return_value=[(180.0, 10.0, 220.0, 90.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([(180.0, 10.0, 220.0, 90.0)], [2])),
        ):
            result, diagnostic = tracker.process_frame_detailed(np.zeros((120, 240, 3), dtype=np.uint8), tracker._last_known_xyxy)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "relock_rejected")
        self.assertIn(PERSON_TRACKER_RELOCK_REJECTED_FLAG, tracker.quality_flags)
        self.assertEqual(diagnostic["rejected_candidates"][0]["tracker_id"], 2)

    def test_long_lost_relock_allows_stable_far_candidate_after_occlusion(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 4
        tracker._center_history[9] = [(200.0, 95.0), (202.0, 96.0)]

        detections = _FakeDetections([(180.0, 50.0, 220.0, 150.0)], [9], [0.88])
        with (
            patch.object(tracker, "_detect", return_value=[(180.0, 50.0, 220.0, 150.0, 0.88)]),
            patch.object(tracker, "_update_tracks", return_value=detections),
        ):
            first, first_diag = tracker.process_frame_detailed(np.zeros((240, 320, 3), dtype=np.uint8), tracker._last_known_xyxy)
            second, second_diag = tracker.process_frame_detailed(np.zeros((240, 320, 3), dtype=np.uint8), tracker._last_known_xyxy)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertEqual(second, (180.0, 50.0, 220.0, 150.0))
        self.assertEqual(second_diag["state"], "relocked")

    def test_detector_relock_confirms_full_frame_yolo_candidate_after_two_frames(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._record_accepted_bbox(0, (18.0, 20.0, 58.0, 100.0))
        tracker._record_accepted_bbox(1, (20.0, 20.0, 60.0, 100.0))
        tracker._target_tracker_id = 1
        frame = np.zeros((120, 240, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[(22.0, 20.0, 62.0, 100.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=3)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "full_frame_yolo_relock_pending")
        self.assertEqual(second, (22.0, 20.0, 62.0, 100.0))
        self.assertEqual(second_diag["state"], "detector_relocked")
        self.assertEqual(second_diag["relock_source"], "full_frame_yolo_relock")
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG, tracker.quality_flags)
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_detector_relock_rejects_far_full_frame_passerby_on_target_track_missing(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._record_accepted_bbox(0, (20.0, 20.0, 60.0, 100.0))
        tracker._target_tracker_id = 1

        with (
            patch.object(tracker, "_detect", return_value=[(180.0, 20.0, 220.0, 100.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([(180.0, 20.0, 220.0, 100.0)], [2])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [0, 0, 100, 100])),
        ):
            result, diagnostic = tracker.process_frame_detailed(np.zeros((120, 240, 3), dtype=np.uint8), tracker._last_known_xyxy)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn("target_track_missing", diagnostic["rejected_reasons"])
        self.assertIn("far_from_reference", diagnostic["rejected_candidates"][0]["reasons"])

    def test_local_zoom_relock_maps_crop_detection_back_to_full_frame(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._record_accepted_bbox(0, (20.0, 20.0, 60.0, 100.0))
        tracker._target_tracker_id = 1
        calls: list[tuple[int, int, int]] = []

        def fake_detect(frame: np.ndarray, *, conf_threshold: float = 0.4) -> list[tuple[float, float, float, float, float]]:
            calls.append(frame.shape)
            if len(calls) == 1:
                return []
            return [(80.0, 40.0, 160.0, 200.0, 0.92)]

        with patch.object(tracker, "_detect", side_effect=fake_detect):
            result, diagnostic = tracker.process_frame_detailed(np.zeros((120, 240, 3), dtype=np.uint8), tracker._last_known_xyxy)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "local_zoom_yolo_relock_pending")
        self.assertEqual(diagnostic["relock_source"], "local_zoom_yolo_relock")
        self.assertEqual(diagnostic["local_crop_bounds"], [0, 0, 160, 120])
        self.assertEqual(diagnostic["candidate_confidence"], 0.92)
        self.assertIn(PERSON_TRACKER_LOCAL_ZOOM_RELOCK_ATTEMPTED_FLAG, tracker.quality_flags)

    def test_local_zoom_relock_single_frame_pending_does_not_switch_bbox(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._record_accepted_bbox(0, (20.0, 20.0, 60.0, 100.0))
        tracker._target_tracker_id = 1

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([(22.0, 20.0, 62.0, 100.0, 0.9)], [0, 0, 100, 100])),
        ):
            result, diagnostic = tracker.process_frame_detailed(np.zeros((120, 240, 3), dtype=np.uint8), tracker._last_known_xyxy)

        self.assertIsNone(result)
        self.assertEqual(tracker._last_known_xyxy, (20.0, 20.0, 60.0, 100.0))
        self.assertEqual(diagnostic["state"], "local_zoom_yolo_relock_pending")

    def test_detector_relock_records_area_and_aspect_rejections(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._record_accepted_bbox(0, (20.0, 20.0, 60.0, 100.0))
        tracker._target_tracker_id = 1

        with (
            patch.object(tracker, "_detect", return_value=[(0.0, 10.0, 100.0, 110.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [0, 0, 100, 100])),
        ):
            result, diagnostic = tracker.process_frame_detailed(np.zeros((120, 240, 3), dtype=np.uint8), tracker._last_known_xyxy)

        self.assertIsNone(result)
        reasons = diagnostic["rejected_candidates"][0]["reasons"]
        self.assertIn("area_ratio", reasons)
        self.assertIn("aspect_ratio", reasons)

    def test_track_sequence_reuses_last_bbox_when_target_lost(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())

        with (
            patch.object(tracker, "_read_frame", return_value=np.zeros((100, 200, 3), dtype=np.uint8)),
            patch.object(tracker, "process_frame", side_effect=[(20.0, 10.0, 60.0, 70.0), None]),
        ):
            tracked, flags = tracker.track_sequence(
                [Path("frame_0001.jpg"), Path("frame_0002.jpg")],
                {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.6},
            )

        self.assertEqual(tracked[0], tracked[1])
        self.assertIn(PERSON_TRACKER_TARGET_LOST_FLAG, flags)

    def test_detailed_tracking_splices_diagnostics_from_anchor_frame(self) -> None:
        frame_paths = [Path(f"frame_{index:04d}.jpg") for index in range(3)]
        backward = ([{"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2}, {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.2}], [], [{"state": "tracked"}, {"state": "tracked"}])
        forward = ([{"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2}, {"x": 0.3, "y": 0.2, "width": 0.1, "height": 0.2}], [], [{"state": "tracked"}, {"state": "tracked"}])

        with patch("app.services.person_tracker._track_forward_detailed", side_effect=[backward, forward]):
            tracked, flags, diagnostics = track_person_bbox_detailed(
                frame_paths,
                {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2},
                initial_frame_index=1,
            )

        self.assertEqual([item["x"] for item in tracked], [0.1, 0.2, 0.3])
        self.assertIn(PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG, flags)
        self.assertEqual([item["frame"] for item in diagnostics], ["frame_0000.jpg", "frame_0001.jpg", "frame_0002.jpg"])


if __name__ == "__main__":
    unittest.main()
