from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.person_tracker import (
    PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG,
    PERSON_TRACKER_TARGET_LOST_FLAG,
    PersonBBoxTracker,
    PersonTrackerUnavailable,
    _YOLO_MODEL_NAME,
    _YOLO_MODEL_PATH_ENV,
    _resolve_yolo_model_path,
    _xyxy_to_bbox,
    track_person_bbox,
)


class _FakeDetections:
    def __init__(self, xyxy: list[tuple[float, float, float, float]], tracker_id: list[int]) -> None:
        self.xyxy = np.array(xyxy, dtype=np.float32)
        self.tracker_id = np.array(tracker_id, dtype=int)

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


if __name__ == "__main__":
    unittest.main()
