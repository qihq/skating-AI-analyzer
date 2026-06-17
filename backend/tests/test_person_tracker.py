from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.person_tracker import (
    PERSON_TRACKER_ANCHOR_NOT_FIRST_FLAG,
    PERSON_TRACKER_CONFIRMED_PARTIAL_RECOVERY_FLAG,
    PERSON_TRACKER_CONTINUITY_REJECTED_FLAG,
    PERSON_TRACKER_CONTINUITY_DETECTOR_RELOCK_ATTEMPTED_FLAG,
    PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG,
    PERSON_TRACKER_DETECTOR_RELOCKED_FLAG,
    PERSON_TRACKER_FINAL_UNRECOVERED_FLAG,
    PERSON_TRACKER_LOCAL_ZOOM_RELOCK_ATTEMPTED_FLAG,
    PERSON_TRACKER_MANUAL_LOCK_IDENTITY_REJECTED_FLAG,
    PERSON_TRACKER_MANUAL_LOCK_RELOCK_BLOCKED_FLAG,
    PERSON_TRACKER_MANUAL_LOCK_SUPPORT_ANCHOR_BLOCKED_FLAG,
    PERSON_TRACKER_RELOCK_PENDING_FLAG,
    PERSON_TRACKER_RELOCK_REJECTED_FLAG,
    PERSON_TRACKER_RELOCKED_FLAG,
    PERSON_TRACKER_SUPPORT_ANCHOR_HANDOFF_REUSED_FLAG,
    PERSON_TRACKER_SUPPORT_ANCHOR_RECOVERED_FLAG,
    PERSON_TRACKER_SUPPORT_ANCHOR_REJECTED_FLAG,
    PERSON_TRACKER_TARGET_LOST_FLAG,
    PERSON_TRACKER_TRANSIENT_LOSS_RECOVERED_FLAG,
    PersonBBoxTracker,
    PersonTrackerUnavailable,
    _YOLO_MODEL_NAME,
    _loss_recovery_summary,
    _YOLO_MODEL_PATH_ENV,
    _resolve_yolo_model_path,
    _zoomed_content_crop_bounds,
    _xyxy_to_bbox,
    detect_person_candidates,
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

    def test_zoomed_content_crop_bounds_trim_black_side_bars(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[:, 50:150] = 80

        self.assertEqual(_zoomed_content_crop_bounds(frame), (50, 20, 150, 85))

    def test_detect_person_candidates_can_use_zoomed_content_detection(self) -> None:
        tracker_frame = np.zeros((100, 200, 3), dtype=np.uint8)
        tracker_frame[:, 50:150] = 80
        calls: list[tuple[int, int, int]] = []

        def fake_detect(self: PersonBBoxTracker, frame: np.ndarray, *, conf_threshold: float = 0.4):
            calls.append(frame.shape)
            if len(calls) == 1:
                return []
            return [(30.0, 30.0, 54.0, 120.0, 0.64)]

        with (
            patch.object(PersonBBoxTracker, "_read_frame", return_value=tracker_frame),
            patch.object(PersonBBoxTracker, "_detect", fake_detect),
        ):
            candidates = detect_person_candidates(
                Path("frame_0001.jpg"),
                min_confidence=0.25,
                include_zoomed_small_targets=True,
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], (195, 300, 3))
        self.assertEqual(candidates[0]["source"], "yolo_zoomed_content")
        self.assertEqual(candidates[0]["confidence"], 0.64)
        self.assertEqual(candidates[0]["bbox"], {"x": 0.3, "y": 0.3, "width": 0.04, "height": 0.3})

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

    def test_manual_lock_blocks_bytetrack_relock_even_for_near_candidate(self) -> None:
        tracker = PersonBBoxTracker(
            yolo_model=object(),
            byte_tracker_factory=lambda _fps: object(),
            manual_lock_mode=True,
        )
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 3
        near_other = (22.0, 20.0, 62.0, 100.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*near_other, 0.92)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([near_other], [2], [0.92])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((120, 240, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=4,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "relock_rejected")
        self.assertEqual(diagnostic["rejected_reasons"], ["manual_lock_relock_blocked"])
        self.assertEqual(tracker._target_tracker_id, 1)
        self.assertIn(PERSON_TRACKER_MANUAL_LOCK_RELOCK_BLOCKED_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_RELOCKED_FLAG, tracker.quality_flags)

    def test_manual_lock_initial_target_selection_requires_identity_overlap(self) -> None:
        tracker = PersonBBoxTracker(
            yolo_model=object(),
            byte_tracker_factory=lambda _fps: object(),
            manual_lock_mode=True,
        )
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        nearby_other = (72.0, 20.0, 112.0, 100.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*nearby_other, 0.92)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([nearby_other], [7], [0.92])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((120, 240, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=0,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn(PERSON_TRACKER_MANUAL_LOCK_IDENTITY_REJECTED_FLAG, tracker.quality_flags)
        self.assertIsNone(tracker._target_tracker_id)

    def test_relock_allows_tiny_partial_bbox_to_recover_from_history(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        full_body = (240.0, 150.0, 336.0, 404.0)
        tiny_partial = (252.0, 170.0, 265.0, 216.0)
        tracker._record_accepted_bbox(0, (238.0, 150.0, 334.0, 404.0))
        tracker._record_accepted_bbox(1, full_body)
        tracker._record_accepted_bbox(2, tiny_partial)
        tracker._last_known_xyxy = tiny_partial
        tracker._target_tracker_id = 1
        tracker._lost_frames = 3
        candidate = (242.0, 148.0, 338.0, 406.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([candidate], [2])),
        ):
            first, first_diag = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=3,
            )
            second, second_diag = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=4,
            )

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertEqual(second, candidate)
        self.assertEqual(second_diag["state"], "relocked")
        self.assertEqual(tracker._target_tracker_id, 2)

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
        self.assertEqual(
            diagnostics[0]["candidate_bbox"],
            {"x": 0.0625, "y": 0.0417, "width": 0.4375, "height": 0.9417},
        )
        self.assertEqual(diagnostics[0]["rejected_candidates"][0]["tracker_id"], 1)
        self.assertIn("area_ratio", diagnostics[0]["rejected_candidates"][0]["reasons"])
        self.assertGreater(diagnostics[0]["candidate_geometry"]["area_ratio"], 3.0)
        self.assertGreater(diagnostics[0]["rejected_candidates"][0]["area_ratio"], 3.0)

    def test_continuity_allows_partial_bbox_recovery_to_full_body(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (180.0, 220.0, 200.0, 295.0)
        tracker._record_accepted_bbox(0, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        candidate = (175.0, 160.0, 245.0, 380.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([candidate], [1])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=1,
            )

        self.assertIsNotNone(result)
        np.testing.assert_allclose(result, candidate, rtol=0.0, atol=1e-3)
        self.assertEqual(diagnostic["state"], "tracked")
        self.assertNotIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, tracker.quality_flags)

    def test_continuity_allows_tiny_partial_bbox_to_recover_from_history(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        full_body = (240.0, 150.0, 336.0, 404.0)
        tiny_partial = (252.0, 170.0, 265.0, 216.0)
        tracker._record_accepted_bbox(0, (238.0, 150.0, 334.0, 404.0))
        tracker._record_accepted_bbox(1, full_body)
        tracker._record_accepted_bbox(2, tiny_partial)
        tracker._last_known_xyxy = tiny_partial
        tracker._target_tracker_id = 1
        candidate = (242.0, 148.0, 338.0, 406.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([candidate], [1])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=3,
            )

        self.assertIsNotNone(result)
        np.testing.assert_allclose(result, candidate, rtol=0.0, atol=1e-3)
        self.assertEqual(diagnostic["state"], "tracked")
        self.assertNotIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, tracker.quality_flags)

    def test_manual_lock_rejects_same_id_partial_to_full_recovery_without_support_anchor(self) -> None:
        tracker = PersonBBoxTracker(
            yolo_model=object(),
            byte_tracker_factory=lambda _fps: object(),
            manual_lock_mode=True,
        )
        tiny_partial = (252.0, 170.0, 265.0, 216.0)
        tracker._record_accepted_bbox(0, (238.0, 150.0, 334.0, 404.0))
        tracker._record_accepted_bbox(1, tiny_partial)
        tracker._last_known_xyxy = tiny_partial
        tracker._target_tracker_id = 1
        candidate = (242.0, 148.0, 338.0, 406.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([candidate], [1])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=2,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "continuity_rejected")
        self.assertIn("area_ratio", diagnostic["rejected_reasons"])
        self.assertIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_CONFIRMED_PARTIAL_RECOVERY_FLAG, tracker.quality_flags)

    def test_continuity_allows_late_small_relock_to_return_to_plausible_full_body(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        prior_full = (365.0, 200.0, 422.0, 423.0)
        small_relock = (321.0, 181.0, 350.0, 288.0)
        recovered_full = (340.0, 137.0, 475.0, 477.0)
        tracker._record_accepted_bbox(26, prior_full)
        tracker._record_accepted_bbox(28, small_relock)
        tracker._last_known_xyxy = small_relock
        tracker._target_tracker_id = 13

        with (
            patch.object(tracker, "_detect", return_value=[(*recovered_full, 0.89)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([recovered_full], [13])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=29,
            )

        self.assertEqual(result, recovered_full)
        self.assertEqual(diagnostic["state"], "tracked")
        self.assertNotIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, tracker.quality_flags)

    def test_continuity_allows_same_track_scale_jump_when_history_supports_motion(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame_w = 640
        frame_h = 480
        history = [
            (120.0, 155.0, 180.0, 335.0),
            (170.0, 152.0, 230.0, 332.0),
            (220.0, 150.0, 280.0, 330.0),
        ]
        for frame_index, bbox in enumerate(history):
            tracker._record_accepted_bbox(frame_index, bbox)
        tracker._center_history[8] = [
            ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
            for bbox in history
        ]
        tracker._last_known_xyxy = history[-1]
        tracker._target_tracker_id = 8
        candidate = (270.0, 118.0, 390.0, 418.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.88)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([candidate], [8], [0.88])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((frame_h, frame_w, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=3,
            )

        self.assertEqual(result, candidate)
        self.assertEqual(diagnostic["state"], "tracked")
        self.assertNotIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, tracker.quality_flags)

    def test_post_detector_relock_rejects_unanchored_foreground_growth(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tiny_reference = (396.5, 183.0, 411.7, 241.1)
        detector_relock = (371.8, 124.8, 421.5, 315.0)
        foreground = (336.5, 123.5, 421.3, 476.8)
        tracker._record_accepted_bbox(14, (397.2, 194.8, 411.9, 241.4))
        tracker._record_accepted_bbox(15, tiny_reference)
        tracker._record_accepted_bbox(17, detector_relock)
        tracker._last_known_xyxy = detector_relock
        tracker._target_tracker_id = None
        tracker._detector_relock_pending_identity_confirmation = True

        with (
            patch.object(tracker, "_detect", return_value=[(*foreground, 0.91)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([foreground], [1])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=18,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "continuity_rejected")
        self.assertIn("area_ratio", diagnostic["rejected_reasons"])

    def test_same_track_rejects_unanchored_tall_foreground_growth(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame_w = 854
        frame_h = 480
        reference = (
            0.4854 * frame_w,
            0.3992 * frame_h,
            (0.4854 + 0.1574) * frame_w,
            (0.3992 + 0.2788) * frame_h,
        )
        foreground = (
            0.4692 * frame_w,
            0.3137 * frame_h,
            (0.4692 + 0.1434) * frame_w,
            (0.3137 + 0.5236) * frame_h,
        )
        tracker._record_accepted_bbox(
            15,
            (
                0.4825 * frame_w,
                0.3438 * frame_h,
                (0.4825 + 0.078) * frame_w,
                (0.3438 + 0.3248) * frame_h,
            ),
        )
        tracker._record_accepted_bbox(16, reference)
        tracker._last_known_xyxy = reference
        tracker._target_tracker_id = 1

        with (
            patch.object(tracker, "_detect", return_value=[(*foreground, 0.92)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([foreground], [1], [0.92])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((frame_h, frame_w, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=17,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "continuity_rejected")
        self.assertIn("foreground_height_growth", diagnostic["rejected_reasons"])
        self.assertIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, tracker.quality_flags)

    def test_continuity_still_rejects_large_jump_without_reference_coverage(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (180.0, 220.0, 200.0, 295.0)
        tracker._record_accepted_bbox(0, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        candidate = (260.0, 160.0, 330.0, 380.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([candidate], [1])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=1,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "continuity_rejected")
        self.assertIn("area_ratio", diagnostic["rejected_reasons"])

    def test_confirmed_track_allows_same_id_tiny_partial_to_full_recovery_after_two_frames(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tiny_partial = (304.8, 189.1, 320.0, 246.3)
        first_full = (219.4, 189.9, 246.7, 339.4)
        second_full = (220.2, 188.5, 247.4, 338.8)
        tracker._last_known_xyxy = tiny_partial
        tracker._record_accepted_bbox(16, tiny_partial)
        tracker._target_tracker_id = 4

        with (
            patch.object(tracker, "_detect", side_effect=[
                [(*first_full, 0.89)],
                [(*second_full, 0.91)],
            ]),
            patch.object(
                tracker,
                "_update_tracks",
                side_effect=[
                    _FakeDetections([first_full], [4]),
                    _FakeDetections([second_full], [4]),
                ],
            ),
        ):
            first, first_diag = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tiny_partial,
                frame_index=17,
            )
            second, second_diag = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tiny_partial,
                frame_index=18,
            )

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "continuity_rejected")
        self.assertEqual(first_diag["rejected_reasons"], ["area_ratio"])
        np.testing.assert_allclose(second, second_full, rtol=0.0, atol=1e-3)
        self.assertEqual(second_diag["state"], "tracked")
        self.assertIn(PERSON_TRACKER_CONFIRMED_PARTIAL_RECOVERY_FLAG, tracker.quality_flags)

    def test_confirmed_track_allows_small_shape_recovery_with_area_and_aspect_after_two_frames(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tiny_reference = (307.1, 160.0, 320.0, 215.8)
        first_candidate = (303.3, 195.4, 354.4, 270.7)
        second_candidate = (305.5, 195.2, 352.6, 270.1)
        tracker._last_known_xyxy = tiny_reference
        tracker._record_accepted_bbox(18, tiny_reference)
        tracker._target_tracker_id = 9

        with (
            patch.object(tracker, "_detect", side_effect=[
                [(*first_candidate, 0.9)],
                [(*second_candidate, 0.91)],
            ]),
            patch.object(
                tracker,
                "_update_tracks",
                side_effect=[
                    _FakeDetections([first_candidate], [9]),
                    _FakeDetections([second_candidate], [9]),
                ],
            ),
        ):
            first, first_diag = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tiny_reference,
                frame_index=19,
            )
            second, second_diag = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tiny_reference,
                frame_index=20,
            )

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "continuity_rejected")
        self.assertEqual(set(first_diag["rejected_reasons"]), {"area_ratio", "aspect_ratio"})
        np.testing.assert_allclose(second, second_candidate, rtol=0.0, atol=1e-3)
        self.assertEqual(second_diag["state"], "tracked")
        self.assertIn(PERSON_TRACKER_CONFIRMED_PARTIAL_RECOVERY_FLAG, tracker.quality_flags)

    def test_confirmed_track_still_rejects_oversized_foreground_partial_recovery_candidate(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tiny_partial = (304.8, 189.1, 320.0, 246.3)
        foreground = (150.0, 80.0, 355.0, 470.0)
        tracker._last_known_xyxy = tiny_partial
        tracker._record_accepted_bbox(16, tiny_partial)
        tracker._target_tracker_id = 4

        with (
            patch.object(tracker, "_detect", return_value=[(*foreground, 0.92)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([foreground], [4])),
        ):
            first, first_diag = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tiny_partial,
                frame_index=17,
            )
            second, second_diag = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                tiny_partial,
                frame_index=18,
            )

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(first_diag["state"], "continuity_rejected")
        self.assertEqual(second_diag["state"], "continuity_rejected")
        self.assertIn("area_ratio", second_diag["rejected_reasons"])
        self.assertNotIn(PERSON_TRACKER_CONFIRMED_PARTIAL_RECOVERY_FLAG, tracker.quality_flags)

    def test_continuity_allows_aspect_only_skating_pose_change(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (100.0, 50.0, 140.0, 150.0)
        tracker._record_accepted_bbox(0, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        candidate = (104.0, 30.0, 124.0, 170.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([candidate], [1])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((200, 240, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=1,
            )

        self.assertEqual(result, candidate)
        self.assertEqual(diagnostic["state"], "tracked")
        self.assertNotIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, tracker.quality_flags)

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

    def test_initial_tiny_anchor_can_bootstrap_nearby_non_overlapping_full_body(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        seed = (470.47, 112.8, 489.43, 172.03)
        candidate = (474.14, 295.06, 517.52, 367.88)
        tracker._last_known_xyxy = seed

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.88)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([candidate], [7])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((480, 854, 3), dtype=np.uint8),
                seed,
                frame_index=0,
            )

        self.assertIsNotNone(result)
        np.testing.assert_allclose(result, candidate, rtol=0.0, atol=1e-3)
        self.assertEqual(diagnostic["state"], "tracked")
        self.assertNotIn(PERSON_TRACKER_CONTINUITY_REJECTED_FLAG, tracker.quality_flags)

    def test_initial_tiny_anchor_still_rejects_nearby_large_foreground(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        seed = (420.0, 160.0, 468.0, 210.0)
        foreground = (260.0, 30.0, 520.0, 470.0)
        tracker._last_known_xyxy = seed

        with (
            patch.object(tracker, "_detect", return_value=[(*foreground, 0.91)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([foreground], [7])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((480, 640, 3), dtype=np.uint8),
                seed,
                frame_index=0,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "continuity_rejected")
        self.assertIn("area_ratio", diagnostic["rejected_reasons"])

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
        self.assertIn("center_distance_ratio", diagnostic["rejected_candidates"][0])
        self.assertIn("iou", diagnostic["rejected_candidates"][0])
        self.assertIn("prediction_iou", diagnostic["rejected_candidates"][0])

    def test_long_lost_relock_rejects_stable_far_candidate_after_occlusion(self) -> None:
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
        self.assertEqual(first_diag["state"], "relock_rejected")
        self.assertIsNone(second)
        self.assertEqual(second_diag["state"], "relock_rejected")

    def test_relock_allows_static_candidate_when_it_still_overlaps_reference(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (100.0, 100.0, 132.0, 220.0)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 7
        tracker._center_history[9] = [
            (117.0, 160.0),
            (117.5, 160.2),
            (118.0, 160.1),
            (118.2, 160.0),
            (118.1, 160.3),
            (118.0, 160.2),
        ]
        candidate = (106.0, 102.0, 134.0, 222.0)
        detections = _FakeDetections([candidate], [9], [0.86])

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.86)]),
            patch.object(tracker, "_update_tracks", return_value=detections),
        ):
            first, first_diag = tracker.process_frame_detailed(
                np.zeros((300, 400, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=10,
            )
            second, second_diag = tracker.process_frame_detailed(
                np.zeros((300, 400, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=11,
            )

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertEqual(second, candidate)
        self.assertEqual(second_diag["state"], "relocked")
        self.assertIn(PERSON_TRACKER_RELOCKED_FLAG, tracker.quality_flags)

    def test_long_lost_relock_can_reacquire_far_moving_candidate_after_two_frames(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 4
        tracker._center_history[7] = [(120.0, 70.0), (150.0, 82.0)]
        candidate = (160.0, 45.0, 200.0, 145.0)
        detections = _FakeDetections([candidate], [7], [0.9])

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=detections),
        ):
            first, first_diag = tracker.process_frame_detailed(
                np.zeros((240, 320, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=5,
            )
            second, second_diag = tracker.process_frame_detailed(
                np.zeros((240, 320, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=6,
            )

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertEqual(second, candidate)
        self.assertEqual(second_diag["state"], "relocked")
        self.assertIn(PERSON_TRACKER_RELOCKED_FLAG, tracker.quality_flags)

    def test_relock_allows_terminal_small_body_candidate_after_short_track_loss(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (274.5, 234.1, 303.4, 331.3)
        tracker._record_accepted_bbox(25, (279.9, 230.4, 302.7, 328.7))
        tracker._record_accepted_bbox(26, (276.0, 233.3, 303.0, 331.0))
        tracker._record_accepted_bbox(27, tracker._last_known_xyxy)
        tracker._target_tracker_id = 26
        tracker._lost_frames = 2
        first_candidate = (233.2, 189.1, 246.3, 246.1)
        second_candidate = (231.9, 192.1, 246.0, 249.3)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[(*first_candidate, 0.75)]),
            patch.object(
                tracker,
                "_update_tracks",
                side_effect=[
                    _FakeDetections([first_candidate], [37], [0.75]),
                    _FakeDetections([second_candidate], [37], [0.78]),
                ],
            ),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=30)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=31)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertEqual(first_diag["candidate_tracker_id"], 37)
        self.assertIsNotNone(second)
        np.testing.assert_allclose(second, second_candidate)
        self.assertEqual(second_diag["state"], "relocked")
        self.assertEqual(second_diag["candidate_tracker_id"], 37)
        self.assertIn(PERSON_TRACKER_RELOCKED_FLAG, tracker.quality_flags)

    def test_small_body_relock_rejects_ambiguous_nearby_candidates(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (274.5, 234.1, 303.4, 331.3)
        tracker._record_accepted_bbox(25, (279.9, 230.4, 302.7, 328.7))
        tracker._record_accepted_bbox(26, (276.0, 233.3, 303.0, 331.0))
        tracker._record_accepted_bbox(27, tracker._last_known_xyxy)
        tracker._target_tracker_id = 26
        tracker._lost_frames = 2
        target_like = (231.9, 192.1, 246.0, 249.3)
        adjacent_like = (244.0, 190.0, 258.0, 247.0)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[(*target_like, 0.78), (*adjacent_like, 0.76)]),
            patch.object(
                tracker,
                "_update_tracks",
                return_value=_FakeDetections([target_like, adjacent_like], [37, 43], [0.78, 0.76]),
            ),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=30)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "relock_rejected")
        self.assertIn("low_iou_and_far_from_previous_bbox", diagnostic["rejected_candidates"][0]["reasons"])
        self.assertIn(PERSON_TRACKER_RELOCK_REJECTED_FLAG, tracker.quality_flags)

    def test_long_lost_relock_can_reacquire_stable_small_body_after_stale_tiny_reference(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (396.5, 183.0, 411.7, 241.1)
        tracker._record_accepted_bbox(14, (397.2, 194.8, 411.9, 241.4))
        tracker._record_accepted_bbox(15, tracker._last_known_xyxy)
        tracker._target_tracker_id = 2
        tracker._lost_frames = 12
        first_candidate = (315.4, 222.6, 334.5, 269.8)
        second_candidate = (316.2, 225.7, 335.6, 269.1)
        tracker._center_history[12] = [(326.0, 248.0), (326.8, 247.2)]
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", side_effect=[
                [(*first_candidate, 0.64)],
                [(*second_candidate, 0.67)],
            ]),
            patch.object(
                tracker,
                "_update_tracks",
                side_effect=[
                    _FakeDetections([first_candidate], [12], [0.64]),
                    _FakeDetections([second_candidate], [12], [0.67]),
                ],
            ),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=28)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=29)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertEqual(first_diag["candidate_tracker_id"], 12)
        np.testing.assert_allclose(second, second_candidate, rtol=0.0, atol=1e-3)
        self.assertEqual(second_diag["state"], "relocked")
        self.assertEqual(second_diag["candidate_tracker_id"], 12)
        self.assertIn(PERSON_TRACKER_RELOCKED_FLAG, tracker.quality_flags)

    def test_long_lost_stable_small_relock_requires_unique_small_candidate(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (396.5, 183.0, 411.7, 241.1)
        tracker._record_accepted_bbox(14, (397.2, 194.8, 411.9, 241.4))
        tracker._record_accepted_bbox(15, tracker._last_known_xyxy)
        tracker._target_tracker_id = 2
        tracker._lost_frames = 12
        target_like = (315.4, 222.6, 334.5, 269.8)
        adjacent_like = (343.4, 222.6, 362.5, 269.8)
        tracker._center_history[12] = [(326.0, 248.0), (326.8, 247.2)]
        tracker._center_history[13] = [(354.0, 248.0), (354.8, 247.2)]
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[(*target_like, 0.64), (*adjacent_like, 0.65)]),
            patch.object(
                tracker,
                "_update_tracks",
                return_value=_FakeDetections([target_like, adjacent_like], [12, 13], [0.64, 0.65]),
            ),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=28)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "relock_rejected")
        self.assertIn("low_iou_and_far_from_previous_bbox", diagnostic["rejected_candidates"][0]["reasons"])
        self.assertIn(PERSON_TRACKER_RELOCK_REJECTED_FLAG, tracker.quality_flags)

    def test_long_lost_stable_small_relock_uses_pixel_aspect_on_wide_video(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame_w = 854
        frame_h = 480
        tiny_reference = (0.6195 * frame_w, 0.3813 * frame_h, (0.6195 + 0.0237) * frame_w, (0.3813 + 0.1211) * frame_h)
        frame_29 = (0.4941 * frame_w, 0.4701 * frame_h, (0.4941 + 0.0303) * frame_w, (0.4701 + 0.0904) * frame_h)
        frame_30 = (0.4626 * frame_w, 0.4552 * frame_h, (0.4626 + 0.0225) * frame_w, (0.4552 + 0.1037) * frame_h)
        frame_31 = (0.4622 * frame_w, 0.4547 * frame_h, (0.4622 + 0.0214) * frame_w, (0.4547 + 0.1032) * frame_h)
        tracker._last_known_xyxy = tiny_reference
        tracker._record_accepted_bbox(15, tiny_reference)
        tracker._target_tracker_id = 2
        tracker._lost_frames = 13
        tracker._center_history[11] = [(431.0, 249.0), (432.0, 248.5)]
        tracker._center_history[12] = [(404.0, 244.0), (404.8, 244.5)]
        frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", side_effect=[
                [(*frame_29, 0.61)],
                [(*frame_30, 0.70)],
                [(*frame_31, 0.58)],
            ]),
            patch.object(
                tracker,
                "_update_tracks",
                side_effect=[
                    _FakeDetections([frame_29], [11], [0.61]),
                    _FakeDetections([frame_30], [12], [0.70]),
                    _FakeDetections([frame_31], [12], [0.58]),
                ],
            ),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=29)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=30)
            third, third_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=31)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertIsNone(second)
        self.assertEqual(second_diag["state"], "relock_pending")
        self.assertEqual(second_diag["candidate_tracker_id"], 12)
        np.testing.assert_allclose(third, frame_31, rtol=0.0, atol=1e-3)
        self.assertEqual(third_diag["state"], "relocked")
        self.assertEqual(third_diag["candidate_tracker_id"], 12)
        self.assertIn(PERSON_TRACKER_RELOCKED_FLAG, tracker.quality_flags)

    def test_long_lost_stable_moving_small_relock_allows_stale_reference_drift(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame_w = 854
        frame_h = 480
        stale_reference = (0.5036 * frame_w, 0.5206 * frame_h, (0.5036 + 0.0484) * frame_w, (0.5206 + 0.1482) * frame_h)
        first_candidate = (0.3964 * frame_w, 0.4990 * frame_h, (0.3964 + 0.0578) * frame_w, (0.4990 + 0.1679) * frame_h)
        second_candidate = (0.4050 * frame_w, 0.4998 * frame_h, (0.4050 + 0.0616) * frame_w, (0.4998 + 0.1657) * frame_h)
        tracker._last_known_xyxy = stale_reference
        tracker._record_accepted_bbox(8, stale_reference)
        tracker._target_tracker_id = 2
        tracker._lost_frames = 20
        tracker._center_history[16] = [
            (343.1, 266.8),
            (347.6, 268.7),
            (352.4, 280.5),
            (358.6, 281.5),
        ]
        frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", side_effect=[
                [(*first_candidate, 0.80)],
                [(*second_candidate, 0.85)],
            ]),
            patch.object(
                tracker,
                "_update_tracks",
                side_effect=[
                    _FakeDetections([first_candidate], [16], [0.80]),
                    _FakeDetections([second_candidate], [16], [0.85]),
                ],
            ),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=28)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=29)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "relock_pending")
        self.assertEqual(first_diag["candidate_tracker_id"], 16)
        np.testing.assert_allclose(second, second_candidate, rtol=0.0, atol=1e-3)
        self.assertEqual(second_diag["state"], "relocked")
        self.assertEqual(second_diag["candidate_tracker_id"], 16)
        self.assertIn(PERSON_TRACKER_RELOCKED_FLAG, tracker.quality_flags)

    def test_long_lost_stable_moving_small_relock_requires_unique_candidate(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame_w = 854
        frame_h = 480
        stale_reference = (0.5036 * frame_w, 0.5206 * frame_h, (0.5036 + 0.0484) * frame_w, (0.5206 + 0.1482) * frame_h)
        target_like = (0.3964 * frame_w, 0.4990 * frame_h, (0.3964 + 0.0578) * frame_w, (0.4990 + 0.1679) * frame_h)
        adjacent_like = (0.4130 * frame_w, 0.4980 * frame_h, (0.4130 + 0.0550) * frame_w, (0.4980 + 0.1640) * frame_h)
        tracker._last_known_xyxy = stale_reference
        tracker._record_accepted_bbox(8, stale_reference)
        tracker._target_tracker_id = 2
        tracker._lost_frames = 20
        tracker._center_history[16] = [
            (343.1, 266.8),
            (347.6, 268.7),
            (352.4, 280.5),
            (358.6, 281.5),
        ]
        tracker._center_history[17] = [
            (356.0, 279.0),
            (361.0, 280.0),
            (366.0, 280.0),
            (372.0, 281.0),
        ]
        frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[(*target_like, 0.80), (*adjacent_like, 0.82)]),
            patch.object(
                tracker,
                "_update_tracks",
                return_value=_FakeDetections([target_like, adjacent_like], [16, 17], [0.80, 0.82]),
            ),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=28)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "relock_rejected")
        self.assertIn("low_iou_and_far_from_previous_bbox", diagnostic["rejected_candidates"][0]["reasons"])
        self.assertIn(PERSON_TRACKER_RELOCK_REJECTED_FLAG, tracker.quality_flags)

    def test_long_lost_moving_relock_rejects_foreground_scale_jump_after_small_target_loss(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame_w = 854
        frame_h = 480
        stale_reference = (
            0.5496 * frame_w,
            0.2324 * frame_h,
            (0.5496 + 0.0418) * frame_w,
            (0.2324 + 0.2362) * frame_h,
        )
        foreground_candidate = (
            0.5491 * frame_w,
            0.4793 * frame_h,
            (0.5491 + 0.1079) * frame_w,
            (0.4793 + 0.5129) * frame_h,
        )
        tracker._last_known_xyxy = stale_reference
        tracker._record_accepted_bbox(18, stale_reference)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 9
        tracker._center_history[9] = [
            (0.59 * frame_w, 0.70 * frame_h),
            (0.60 * frame_w, 0.72 * frame_h),
            (0.61 * frame_w, 0.74 * frame_h),
        ]
        frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[(*foreground_candidate, 0.86)]),
            patch.object(
                tracker,
                "_update_tracks",
                return_value=_FakeDetections([foreground_candidate], [9], [0.86]),
            ),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=30)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "relock_rejected")
        rejected = diagnostic["rejected_candidates"][0]
        self.assertEqual(rejected["tracker_id"], 9)
        self.assertIn("foreground_scale_jump", rejected["reasons"])
        self.assertIn("low_iou_and_far_from_previous_bbox", rejected["reasons"])
        self.assertIn(PERSON_TRACKER_RELOCK_REJECTED_FLAG, tracker.quality_flags)

    def test_prediction_caps_long_lost_extrapolation_near_last_reliable_bbox(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._record_accepted_bbox(0, (100.0, 100.0, 140.0, 220.0))
        tracker._record_accepted_bbox(1, (130.0, 100.0, 170.0, 220.0))
        tracker._last_known_xyxy = (130.0, 100.0, 170.0, 220.0)

        tracker._lost_frames = 2
        short_prediction = tracker._predict_next_xyxy(400, 300)
        tracker._lost_frames = 15
        long_prediction = tracker._predict_next_xyxy(400, 300)

        self.assertEqual(short_prediction, (190.0, 100.0, 230.0, 220.0))
        self.assertEqual(long_prediction, (220.0, 100.0, 260.0, 220.0))

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
        self.assertEqual(first_diag["pending_relock_bbox"], _xyxy_to_bbox((22.0, 20.0, 62.0, 100.0), 240, 120))
        self.assertEqual(second, (22.0, 20.0, 62.0, 100.0))
        self.assertEqual(second_diag["state"], "detector_relocked")
        self.assertEqual(second_diag["relock_source"], "full_frame_yolo_relock")
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG, tracker.quality_flags)
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_manual_lock_blocks_full_frame_detector_relock_to_prevent_identity_swap(self) -> None:
        tracker = PersonBBoxTracker(
            yolo_model=object(),
            byte_tracker_factory=lambda _fps: object(),
            manual_lock_mode=True,
        )
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._record_accepted_bbox(0, (18.0, 20.0, 58.0, 100.0))
        tracker._record_accepted_bbox(1, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((120, 240, 3), dtype=np.uint8)
        passerby = (22.0, 20.0, 62.0, 100.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*passerby, 0.95)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([(*passerby, 0.95)], [0, 0, 100, 100])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=3)

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(first_diag["state"], "lost_reused")
        self.assertEqual(second_diag["state"], "lost_reused")
        self.assertIn("manual_lock_relock_blocked", first_diag["rejected_reasons"])
        self.assertIn("manual_lock_relock_blocked", second_diag["rejected_reasons"])
        self.assertIn(PERSON_TRACKER_MANUAL_LOCK_RELOCK_BLOCKED_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_continuity_rejection_can_recover_same_frame_from_alternate_detector_box(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        reference = (100.0, 100.0, 140.0, 220.0)
        wrong_same_id = (260.0, 45.0, 286.0, 126.0)
        recovered_target = (102.0, 100.0, 142.0, 220.0)
        tracker._last_known_xyxy = reference
        tracker._record_accepted_bbox(0, reference)
        tracker._target_tracker_id = 7
        frame = np.zeros((300, 400, 3), dtype=np.uint8)

        with (
            patch.object(
                tracker,
                "_detect",
                return_value=[
                    (*wrong_same_id, 0.86),
                    (*recovered_target, 0.91),
                ],
            ),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([wrong_same_id], [7], [0.86])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=1)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "full_frame_yolo_relock_pending")
        self.assertEqual(first_diag["continuity_rejected_candidate_bbox"], _xyxy_to_bbox(wrong_same_id, 400, 300))
        self.assertIn("center_jump", first_diag["continuity_rejected_reasons"])
        self.assertEqual(first_diag["rejected_candidates"][0]["tracker_id"], 7)
        self.assertEqual(first_diag["pending_relock_bbox"], _xyxy_to_bbox(recovered_target, 400, 300))
        self.assertEqual(second, recovered_target)
        self.assertEqual(second_diag["state"], "detector_relocked")
        self.assertIn(PERSON_TRACKER_CONTINUITY_DETECTOR_RELOCK_ATTEMPTED_FLAG, tracker.quality_flags)
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_continuity_rejection_keeps_far_alternate_detector_box_rejected(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        reference = (100.0, 100.0, 140.0, 220.0)
        wrong_same_id = (260.0, 45.0, 286.0, 126.0)
        passerby = (300.0, 95.0, 340.0, 215.0)
        tracker._last_known_xyxy = reference
        tracker._record_accepted_bbox(0, reference)
        tracker._target_tracker_id = 7
        frame = np.zeros((300, 400, 3), dtype=np.uint8)

        with (
            patch.object(
                tracker,
                "_detect",
                return_value=[
                    (*wrong_same_id, 0.86),
                    (*passerby, 0.92),
                ],
            ),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([wrong_same_id], [7], [0.86])),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=1)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "continuity_rejected")
        self.assertIn("center_jump", diagnostic["rejected_reasons"])
        self.assertIn(PERSON_TRACKER_CONTINUITY_DETECTOR_RELOCK_ATTEMPTED_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG, tracker.quality_flags)
        self.assertIn("weak_identity_support", diagnostic["rejected_candidates"][1]["reasons"])

    def test_confirmed_track_clears_stale_detector_relock_pending(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (310.0, 190.0, 411.0, 325.0)
        tracker._record_accepted_bbox(16, (300.0, 186.0, 402.0, 320.0))
        tracker._record_accepted_bbox(17, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        pending_candidate = (266.9, 134.4, 419.9, 346.4)
        recovered_track = (312.0, 188.0, 408.0, 328.0)
        later_detector = (266.9, 134.4, 419.9, 346.4)

        with (
            patch.object(
                tracker,
                "_detect",
                side_effect=[
                    [(*pending_candidate, 0.42)],
                    [(*recovered_track, 0.91)],
                    [(*later_detector, 0.83)],
                ],
            ),
            patch.object(
                tracker,
                "_update_tracks",
                side_effect=[
                    _FakeDetections([], []),
                    _FakeDetections([recovered_track], [1], [0.91]),
                    _FakeDetections([], []),
                ],
            ),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [220, 80, 450, 430])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=18)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=19)
            third, third_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=20)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "full_frame_yolo_relock_pending")
        np.testing.assert_allclose(second, recovered_track, rtol=0.0, atol=1e-3)
        self.assertEqual(second_diag["state"], "tracked")
        self.assertIsNone(third)
        self.assertEqual(third_diag["state"], "full_frame_yolo_relock_pending")
        self.assertNotIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_detailed_sequence_marks_transient_detector_loss_recovered(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame = np.zeros((120, 240, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_read_frame", return_value=frame),
            patch.object(tracker, "_detect", return_value=[(22.0, 20.0, 62.0, 100.0, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
        ):
            tracked, flags, diagnostics = tracker.track_sequence_detailed(
                [Path("frame_0001.jpg"), Path("frame_0002.jpg")],
                {"x": 0.0833, "y": 0.1667, "width": 0.1667, "height": 0.6667},
            )

        self.assertEqual(diagnostics[0]["state"], "full_frame_yolo_relock_pending")
        self.assertEqual(diagnostics[1]["state"], "detector_relocked")
        self.assertIn(PERSON_TRACKER_TARGET_LOST_FLAG, flags)
        self.assertIn(PERSON_TRACKER_TRANSIENT_LOSS_RECOVERED_FLAG, flags)
        self.assertTrue(diagnostics[-1]["sequence_summary"]["transient_loss_recovered"])
        self.assertFalse(diagnostics[-1]["sequence_summary"]["final_unrecovered"])
        self.assertEqual(tracked[-1], {"x": 0.0917, "y": 0.1667, "width": 0.1667, "height": 0.6667})

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

    def test_detector_relock_allows_close_scale_jump_candidate(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (95.0, 95.0, 120.0, 160.0)
        tracker._record_accepted_bbox(0, (96.0, 96.0, 121.0, 161.0))
        tracker._record_accepted_bbox(1, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        candidate = (80.0, 55.0, 160.0, 235.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.88)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [0, 0, 100, 100])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=3)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "full_frame_yolo_relock_pending")
        self.assertEqual(second, candidate)
        self.assertEqual(second_diag["state"], "detector_relocked")

    def test_detector_relock_allows_near_prediction_scale_shrink_pose_change(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (220.0, 145.0, 281.0, 287.0)
        tracker._record_accepted_bbox(0, (219.0, 146.0, 280.0, 288.0))
        tracker._record_accepted_bbox(1, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        shrunk_side_pose = (241.0, 146.0, 281.0, 274.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*shrunk_side_pose, 0.82)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [180, 80, 320, 340])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=3)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "full_frame_yolo_relock_pending")
        self.assertEqual(second, shrunk_side_pose)
        self.assertEqual(second_diag["state"], "detector_relocked")

    def test_detector_relock_still_rejects_nearby_shrink_without_identity_support(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (220.0, 145.0, 281.0, 287.0)
        tracker._record_accepted_bbox(0, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        adjacent_person = (300.0, 145.0, 340.0, 274.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*adjacent_person, 0.82)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [250, 80, 380, 340])),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn("weak_identity_support", diagnostic["rejected_candidates"][0]["reasons"])

    def test_detector_relock_allows_tiny_partial_to_full_recovery_with_history_anchor(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        full_body = (240.0, 150.0, 336.0, 404.0)
        tiny_partial = (252.0, 170.0, 265.0, 216.0)
        tracker._record_accepted_bbox(0, (238.0, 150.0, 334.0, 404.0))
        tracker._record_accepted_bbox(1, full_body)
        tracker._record_accepted_bbox(2, tiny_partial)
        tracker._last_known_xyxy = tiny_partial
        tracker._target_tracker_id = 1
        tracker._lost_frames = 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        candidate = (242.0, 148.0, 338.0, 406.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.91)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [0, 0, 100, 100])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=3)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=4)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "full_frame_yolo_relock_pending")
        self.assertEqual(second, candidate)
        self.assertEqual(second_diag["state"], "detector_relocked")

    def test_long_lost_detector_relock_confirms_stable_pending_candidate(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (400.0, 277.0, 419.0, 375.0)
        tracker._record_accepted_bbox(0, (390.0, 240.0, 415.0, 338.0))
        tracker._record_accepted_bbox(1, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 18
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        first_candidate = (315.0, 207.0, 346.0, 267.0)
        second_candidate = (323.0, 200.0, 350.0, 260.0)

        with (
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [0, 0, 100, 100])),
            patch.object(tracker, "_detect", side_effect=[
                [(*first_candidate, 0.72)],
                [(*second_candidate, 0.81), (285.0, 134.0, 298.0, 187.0, 0.52)],
            ]),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=29)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=30)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "full_frame_yolo_relock_pending")
        self.assertEqual(second, second_candidate)
        self.assertEqual(second_diag["state"], "detector_relocked")
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_detector_relock_rejects_nearby_foreground_scale_explosion(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (100.0, 70.0, 124.0, 110.0)
        tracker._record_accepted_bbox(0, (98.0, 70.0, 122.0, 110.0))
        tracker._record_accepted_bbox(1, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        foreground = (72.0, 25.0, 182.0, 235.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*foreground, 0.9)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [0, 0, 100, 100])),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn("area_ratio", diagnostic["rejected_candidates"][0]["reasons"])

    def test_detector_relock_rejects_close_tall_foreground_after_small_target_loss(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (288.0, 222.0, 332.0, 334.0)
        tracker._record_accepted_bbox(0, (269.0, 232.0, 338.0, 340.0))
        tracker._record_accepted_bbox(1, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        foreground = (220.0, 128.0, 376.0, 476.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*foreground, 0.89)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [120, 20, 480, 480])),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn("area_ratio", diagnostic["rejected_candidates"][0]["reasons"])

    def test_local_zoom_relock_allows_tiny_scale_recovery_near_prediction(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (397.0, 183.0, 412.0, 241.0)
        tracker._record_accepted_bbox(0, (370.0, 121.0, 420.0, 313.0))
        tracker._record_accepted_bbox(1, (391.0, 178.0, 406.0, 236.0))
        tracker._record_accepted_bbox(2, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        recovered = (372.0, 122.0, 421.0, 312.0)

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([(*recovered, 0.84)], [350, 80, 450, 350])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=3)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=4)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "local_zoom_yolo_relock_pending")
        self.assertEqual(second, recovered)
        self.assertEqual(second_diag["state"], "detector_relocked")
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_local_zoom_relock_allows_near_full_body_recovery_after_tiny_reference(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (373.6, 210.8, 405.9, 266.9)
        tracker._record_accepted_bbox(10, (371.9, 211.5, 403.7, 264.2))
        tracker._record_accepted_bbox(11, tracker._last_known_xyxy)
        tracker._target_tracker_id = 4
        frame = np.zeros((480, 854, 3), dtype=np.uint8)
        first_recovered = (326.8, 133.8, 410.4, 349.7)
        second_recovered = (325.6, 132.7, 434.4, 349.3)

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(
                tracker,
                "_local_zoom_relock_boxes",
                side_effect=[
                    ([(*first_recovered, 0.62)], [300, 120, 450, 380]),
                    ([(*second_recovered, 0.84)], [300, 120, 460, 380]),
                ],
            ),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=12)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=13)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "local_zoom_yolo_relock_pending")
        self.assertEqual(first_diag["relock_source"], "local_zoom_yolo_relock")
        self.assertEqual(second, second_recovered)
        self.assertEqual(second_diag["state"], "detector_relocked")
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_local_zoom_relock_rejects_42901_tiny_to_foreground_scale_jump(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tiny_reference = (396.5, 183.0, 411.7, 241.1)
        pending_tiny = (395.6, 196.8, 411.0, 240.3)
        foreground_fragment = (371.8, 124.8, 421.5, 315.0)
        tracker._last_known_xyxy = tiny_reference
        tracker._record_accepted_bbox(14, (397.2, 194.8, 411.9, 241.4))
        tracker._record_accepted_bbox(15, tiny_reference)
        tracker._target_tracker_id = 2
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(
                tracker,
                "_local_zoom_relock_boxes",
                side_effect=[
                    ([(*pending_tiny, 0.4462)], [497, 89, 578, 321]),
                    ([(*foreground_fragment, 0.8417)], [496, 83, 577, 315]),
                ],
            ),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=16)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=17)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "local_zoom_yolo_relock_pending")
        self.assertIsNone(second)
        self.assertEqual(second_diag["state"], "lost_reused")
        self.assertNotIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)
        rejected = second_diag["rejected_candidates"][0]
        self.assertEqual(rejected["source"], "local_zoom_yolo_relock")
        self.assertIn("area_ratio", rejected["reasons"])

    def test_local_zoom_relock_still_rejects_foreground_scale_explosion(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (397.0, 183.0, 412.0, 241.0)
        tracker._record_accepted_bbox(0, (391.0, 178.0, 406.0, 236.0))
        tracker._record_accepted_bbox(1, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        foreground = (318.0, 121.0, 421.0, 470.0)

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([(*foreground, 0.84)], [270, 80, 470, 480])),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=2)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn("area_ratio", diagnostic["rejected_candidates"][0]["reasons"])

    def test_local_zoom_relock_rejects_shrunk_fragment_after_small_target_loss(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (437.0, 190.0, 475.0, 239.0)
        tracker._record_accepted_bbox(8, (420.0, 188.0, 458.0, 237.0))
        tracker._record_accepted_bbox(9, tracker._last_known_xyxy)
        tracker._target_tracker_id = 1
        tracker._lost_frames = 4
        frame = np.zeros((480, 854, 3), dtype=np.uint8)
        tiny_fragment = (480.0, 191.0, 497.0, 225.0)

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(
                tracker,
                "_local_zoom_relock_boxes",
                return_value=([(*tiny_fragment, 0.80)], [395, 119, 546, 314]),
            ),
        ):
            result, diagnostic = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=16)

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn("shrunk_fragment", diagnostic["rejected_candidates"][0]["reasons"])
        self.assertNotIn(PERSON_TRACKER_DETECTOR_RELOCK_PENDING_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

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

    def test_long_lost_full_frame_detector_relock_rejects_far_plausible_person(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._record_accepted_bbox(0, (20.0, 20.0, 60.0, 100.0))
        tracker._target_tracker_id = 1
        tracker._lost_frames = 4

        reasons = tracker._detector_relock_rejection_reasons(
            (170.0, 15.0, 210.0, 105.0),
            tracker._last_known_xyxy,
            tracker._predict_next_xyxy(240, 120),
            frame_w=240,
            frame_h=120,
            confidence=0.92,
            source="full_frame_yolo_relock",
        )

        self.assertIn("far_from_reference", reasons)
        self.assertIn("far_from_prediction", reasons)

    def test_detector_relock_rejects_adjacent_full_frame_candidate_without_identity_support(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (100.0, 100.0, 132.0, 220.0)
        tracker._record_accepted_bbox(0, (100.0, 100.0, 132.0, 220.0))
        tracker._target_tracker_id = 1
        adjacent_person = (150.0, 100.0, 182.0, 220.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*adjacent_person, 0.92)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [70, 20, 230, 300])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((300, 400, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=1,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn("weak_identity_support", diagnostic["rejected_candidates"][0]["reasons"])

    def test_full_frame_relock_does_not_preempt_local_zoom_identity_candidate(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (100.0, 100.0, 132.0, 220.0)
        tracker._record_accepted_bbox(0, (100.0, 100.0, 132.0, 220.0))
        tracker._target_tracker_id = 1
        adjacent_person = (150.0, 100.0, 182.0, 220.0)
        target_recovery = (102.0, 100.0, 134.0, 220.0)

        with (
            patch.object(tracker, "_detect", return_value=[(*adjacent_person, 0.92)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([(*target_recovery, 0.88)], [70, 20, 230, 300])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                np.zeros((300, 400, 3), dtype=np.uint8),
                tracker._last_known_xyxy,
                frame_index=1,
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "local_zoom_yolo_relock_pending")
        self.assertEqual(diagnostic["relock_source"], "local_zoom_yolo_relock")
        self.assertEqual(diagnostic["pending_relock_bbox"], _xyxy_to_bbox(target_recovery, 400, 300))

    def test_long_lost_local_zoom_detector_relock_can_relax_reference_distance(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (20.0, 20.0, 60.0, 100.0)
        tracker._record_accepted_bbox(0, (20.0, 20.0, 60.0, 100.0))
        tracker._target_tracker_id = 1
        tracker._lost_frames = 4
        prediction = (70.0, 20.0, 110.0, 100.0)

        reasons = tracker._detector_relock_rejection_reasons(
            (72.0, 20.0, 112.0, 100.0),
            tracker._last_known_xyxy,
            prediction,
            frame_w=240,
            frame_h=120,
            confidence=0.92,
            source="local_zoom_yolo_relock",
        )

        self.assertNotIn("far_from_reference", reasons)
        self.assertNotIn("far_from_prediction", reasons)

    def test_long_lost_single_full_frame_detector_can_reacquire_after_no_active_tracks(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (40.0, 20.0, 80.0, 120.0)
        tracker._record_accepted_bbox(0, (40.0, 20.0, 80.0, 120.0))
        tracker._target_tracker_id = 1
        tracker._lost_frames = 4
        candidate = (170.0, 95.0, 202.0, 180.0)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[(*candidate, 0.82)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [120, 40, 240, 220])),
        ):
            first, first_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=12)
            second, second_diag = tracker.process_frame_detailed(frame, tracker._last_known_xyxy, frame_index=13)

        self.assertIsNone(first)
        self.assertEqual(first_diag["state"], "full_frame_yolo_relock_pending")
        self.assertEqual(second, candidate)
        self.assertEqual(second_diag["state"], "detector_relocked")
        self.assertIn(PERSON_TRACKER_DETECTOR_RELOCKED_FLAG, tracker.quality_flags)

    def test_long_lost_single_full_frame_relaxation_requires_single_plausible_person(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (40.0, 20.0, 80.0, 120.0)
        tracker._record_accepted_bbox(0, (40.0, 20.0, 80.0, 120.0))
        tracker._target_tracker_id = 1
        tracker._lost_frames = 4
        target_candidate = (170.0, 95.0, 202.0, 180.0)
        other_person = (230.0, 95.0, 262.0, 180.0)

        reasons = tracker._detector_relock_rejection_reasons(
            target_candidate,
            tracker._last_known_xyxy,
            tracker._predict_next_xyxy(320, 240),
            frame_w=320,
            frame_h=240,
            confidence=0.82,
            source="full_frame_yolo_relock",
            relax_long_lost_single_candidate=tracker._long_lost_single_detector_reacquire_allowed(
                [(*target_candidate, 0.82), (*other_person, 0.8)],
                target_candidate,
                0.82,
                frame_w=320,
                frame_h=240,
            ),
        )

        self.assertIn("weak_identity_support", reasons)
        self.assertIn("far_from_reference", reasons)

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
        self.assertIn(PERSON_TRACKER_FINAL_UNRECOVERED_FLAG, flags)

    def test_detailed_sequence_graces_short_terminal_loss_after_stable_tracking(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        detections = [
            _FakeDetections([(20.0 + index, 10.0, 60.0 + index, 70.0)], [1])
            for index in range(8)
        ]

        with (
            patch.object(tracker, "_read_frame", return_value=frame),
            patch.object(
                tracker,
                "_detect",
                side_effect=[[(20.0 + index, 10.0, 60.0 + index, 70.0, 0.9)] for index in range(8)] + [[], []],
            ),
            patch.object(tracker, "_update_tracks", side_effect=detections),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [0, 0, 100, 100])),
        ):
            tracked, flags, diagnostics = tracker.track_sequence_detailed(
                [Path(f"frame_{index:04d}.jpg") for index in range(10)],
                {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.6},
            )

        self.assertIn(PERSON_TRACKER_TARGET_LOST_FLAG, flags)
        self.assertNotIn(PERSON_TRACKER_FINAL_UNRECOVERED_FLAG, flags)
        self.assertTrue(diagnostics[-1]["sequence_summary"]["terminal_loss_graced"])
        self.assertFalse(diagnostics[-1]["sequence_summary"]["final_unrecovered"])
        self.assertEqual(tracked[-1], tracked[-2])

    def test_detailed_sequence_marks_long_terminal_loss_unrecovered(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        detections = [
            _FakeDetections([(20.0 + index, 10.0, 60.0 + index, 70.0)], [1])
            for index in range(8)
        ]

        with (
            patch.object(tracker, "_read_frame", return_value=frame),
            patch.object(
                tracker,
                "_detect",
                side_effect=[[(20.0 + index, 10.0, 60.0 + index, 70.0, 0.9)] for index in range(8)] + [[], [], []],
            ),
            patch.object(tracker, "_update_tracks", side_effect=detections),
            patch.object(tracker, "_local_zoom_relock_boxes", return_value=([], [0, 0, 100, 100])),
        ):
            _tracked, flags, diagnostics = tracker.track_sequence_detailed(
                [Path(f"frame_{index:04d}.jpg") for index in range(11)],
                {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.6},
            )

        self.assertIn(PERSON_TRACKER_FINAL_UNRECOVERED_FLAG, flags)
        self.assertFalse(diagnostics[-1]["sequence_summary"]["terminal_loss_graced"])
        self.assertTrue(diagnostics[-1]["sequence_summary"]["final_unrecovered"])

    def test_loss_summary_graces_four_frame_tail_after_stable_history(self) -> None:
        diagnostics = (
            [{"state": "tracked"} for _ in range(13)]
            + [{"state": "full_frame_yolo_relock_pending"}, {"state": "detector_relocked"}] * 5
            + [{"state": "tracked"} for _ in range(5)]
            + [{"state": "lost_reused"}, {"state": "relock_rejected"}, {"state": "full_frame_yolo_relock_pending"}, {"state": "lost_reused"}]
        )

        summary = _loss_recovery_summary(diagnostics)

        self.assertEqual(summary["total_frames"], 32)
        self.assertEqual(summary["tracked_frames"], 23)
        self.assertEqual(summary["terminal_loss_frames"], 4)
        self.assertTrue(summary["terminal_loss_graced"])
        self.assertFalse(summary["final_unrecovered"])
        self.assertTrue(summary["transient_loss_recovered"])

    def test_loss_summary_keeps_excessive_terminal_tail_unrecovered(self) -> None:
        diagnostics = (
            [{"state": "tracked"} for _ in range(16)]
            + [
                {"state": "lost_reused"},
                {"state": "relock_rejected"},
                {"state": "full_frame_yolo_relock_pending"},
                {"state": "lost_reused"},
                {"state": "lost_reused"},
                {"state": "relock_pending"},
                {"state": "lost_reused"},
            ]
        )

        summary = _loss_recovery_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 7)
        self.assertFalse(summary["terminal_loss_graced"])
        self.assertTrue(summary["final_unrecovered"])

    def test_loss_summary_graces_moderate_tail_after_stable_history(self) -> None:
        diagnostics = (
            [{"state": "tracked"} for _ in range(12)]
            + [{"state": "full_frame_yolo_relock_pending"}, {"state": "relock_pending"}, {"state": "lost_reused"}]
        )

        summary = _loss_recovery_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 3)
        self.assertEqual(summary["tracked_frames"], 12)
        self.assertTrue(summary["terminal_loss_graced"])
        self.assertFalse(summary["final_unrecovered"])

    def test_loss_summary_keeps_moderate_tail_without_stable_history_unrecovered(self) -> None:
        diagnostics = (
            [{"state": "tracked"} for _ in range(8)]
            + [{"state": "full_frame_yolo_relock_pending"}, {"state": "relock_pending"}, {"state": "lost_reused"}]
        )

        summary = _loss_recovery_summary(diagnostics)

        self.assertEqual(summary["terminal_loss_frames"], 3)
        self.assertEqual(summary["tracked_frames"], 8)
        self.assertFalse(summary["terminal_loss_graced"])
        self.assertTrue(summary["final_unrecovered"])

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
        self.assertFalse(diagnostics[-1]["sequence_summary"]["final_unrecovered"])

    def test_detailed_tracking_recomputes_summary_after_anchor_splice(self) -> None:
        frame_paths = [Path(f"frame_{index:04d}.jpg") for index in range(3)]
        backward = (
            [{"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2}, {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.2}],
            [PERSON_TRACKER_TARGET_LOST_FLAG, PERSON_TRACKER_FINAL_UNRECOVERED_FLAG],
            [
                {"state": "tracked"},
                {"state": "lost_reused", "sequence_summary": {"final_unrecovered": True, "state_counts": {"lost_reused": 1}}},
            ],
        )
        forward = (
            [{"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2}, {"x": 0.3, "y": 0.2, "width": 0.1, "height": 0.2}],
            [],
            [{"state": "detector_relocked"}, {"state": "tracked", "sequence_summary": {"state_counts": {"tracked": 2}}}],
        )

        with patch("app.services.person_tracker._track_forward_detailed", side_effect=[backward, forward]):
            _tracked, flags, diagnostics = track_person_bbox_detailed(
                frame_paths,
                {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2},
                initial_frame_index=1,
            )

        self.assertNotIn(PERSON_TRACKER_FINAL_UNRECOVERED_FLAG, flags)
        self.assertIn(PERSON_TRACKER_TRANSIENT_LOSS_RECOVERED_FLAG, flags)
        self.assertEqual(diagnostics[-1]["sequence_summary"]["state_counts"], {"lost_reused": 1, "detector_relocked": 1, "tracked": 1})
        self.assertFalse(diagnostics[-1]["sequence_summary"]["final_unrecovered"])
        self.assertTrue(diagnostics[-1]["sequence_summary"]["transient_loss_recovered"])

    def test_support_anchor_recovers_distant_target_when_tracker_has_no_detections(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (490.0, 98.0, 526.0, 218.0)
        tracker._target_tracker_id = 2
        frame = np.zeros((480, 854, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                frame,
                tracker._last_known_xyxy,
                frame_index=17,
                frame_path=Path("frame_0017.jpg"),
                support_anchor_bbox={
                    "bbox": {"x": 0.574, "y": 0.206, "width": 0.041, "height": 0.238},
                    "confidence": 0.76,
                },
            )

        expected = (0.574 * 854, 0.206 * 480, (0.574 + 0.041) * 854, (0.206 + 0.238) * 480)
        np.testing.assert_allclose(result, expected, rtol=0.0, atol=0.5)
        self.assertEqual(diagnostic["state"], "support_anchor_recovered")
        self.assertEqual(diagnostic["relock_source"], "target_lock_support_anchor")
        self.assertIn(PERSON_TRACKER_SUPPORT_ANCHOR_RECOVERED_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_FINAL_UNRECOVERED_FLAG, tracker.quality_flags)

    def test_manual_lock_blocks_support_anchor_recovery(self) -> None:
        tracker = PersonBBoxTracker(
            yolo_model=object(),
            byte_tracker_factory=lambda _fps: object(),
            manual_lock_mode=True,
        )
        tracker._last_known_xyxy = (490.0, 98.0, 526.0, 218.0)
        tracker._target_tracker_id = 2
        frame = np.zeros((480, 854, 3), dtype=np.uint8)

        with patch.object(tracker, "_detect", return_value=[]):
            result, diagnostic = tracker.process_frame_detailed(
                frame,
                tracker._last_known_xyxy,
                frame_index=17,
                frame_path=Path("frame_0017.jpg"),
                support_anchor_bbox={
                    "bbox": {"x": 0.574, "y": 0.206, "width": 0.041, "height": 0.238},
                    "confidence": 0.76,
                },
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertEqual(diagnostic["relock_source"], "manual_lock")
        self.assertIn("manual_lock_relock_blocked", diagnostic["rejected_reasons"])
        self.assertEqual(
            diagnostic["rejected_candidates"][0]["reasons"],
            ["manual_lock_support_anchor_blocked"],
        )
        self.assertIn(PERSON_TRACKER_MANUAL_LOCK_SUPPORT_ANCHOR_BLOCKED_FLAG, tracker.quality_flags)
        self.assertIn(PERSON_TRACKER_SUPPORT_ANCHOR_REJECTED_FLAG, tracker.quality_flags)
        self.assertIn(PERSON_TRACKER_MANUAL_LOCK_RELOCK_BLOCKED_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_SUPPORT_ANCHOR_RECOVERED_FLAG, tracker.quality_flags)

    def test_support_anchor_allows_nearby_wide_pose_recovery(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (520.9, 179.0, 561.9, 259.1)
        frame = np.zeros((480, 854, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                frame,
                tracker._last_known_xyxy,
                frame_index=17,
                frame_path=Path("frame_0017.jpg"),
                support_anchor_bbox={
                    "bbox": {"x": 0.59, "y": 0.36, "width": 0.111, "height": 0.193},
                    "confidence": 0.88,
                },
            )

        expected = (0.59 * 854, 0.36 * 480, (0.59 + 0.111) * 854, (0.36 + 0.193) * 480)
        np.testing.assert_allclose(result, expected, rtol=0.0, atol=0.5)
        self.assertEqual(diagnostic["state"], "support_anchor_recovered")
        self.assertIn(PERSON_TRACKER_SUPPORT_ANCHOR_RECOVERED_FLAG, tracker.quality_flags)
        self.assertNotIn(PERSON_TRACKER_SUPPORT_ANCHOR_REJECTED_FLAG, tracker.quality_flags)

    def test_support_anchor_rejects_foreground_scale_jump_after_small_target_loss(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (490.0, 98.0, 526.0, 218.0)
        tracker._target_tracker_id = 2
        frame = np.zeros((480, 854, 3), dtype=np.uint8)

        with patch.object(tracker, "_detect", return_value=[]):
            result, diagnostic = tracker.process_frame_detailed(
                frame,
                tracker._last_known_xyxy,
                frame_index=17,
                frame_path=Path("frame_0017.jpg"),
                support_anchor_bbox={
                    "bbox": {"x": 0.44, "y": 0.16, "width": 0.18, "height": 0.62},
                    "confidence": 0.88,
                },
            )

        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "lost_reused")
        self.assertIn(PERSON_TRACKER_SUPPORT_ANCHOR_REJECTED_FLAG, tracker.quality_flags)
        self.assertEqual(diagnostic["rejected_candidates"][0]["source"], "target_lock_support_anchor")
        self.assertIn("foreground_scale_jump", diagnostic["rejected_candidates"][0]["reasons"])
        self.assertNotIn(PERSON_TRACKER_SUPPORT_ANCHOR_RECOVERED_FLAG, tracker.quality_flags)

    def test_support_anchor_seed_selects_target_when_tracker_identity_was_reset(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        tracker._last_known_xyxy = (490.0, 98.0, 526.0, 218.0)
        target = (490.0, 98.0, 526.0, 218.0)
        foreground = (290.0, 70.0, 510.0, 470.0)
        frame = np.zeros((480, 854, 3), dtype=np.uint8)

        with (
            patch.object(tracker, "_detect", return_value=[(*foreground, 0.92), (*target, 0.78)]),
            patch.object(
                tracker,
                "_update_tracks",
                return_value=_FakeDetections([foreground, target], [5, 7], [0.92, 0.78]),
            ),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                frame,
                tracker._last_known_xyxy,
                frame_index=12,
                frame_path=Path("frame_0012.jpg"),
                support_anchor_bbox={
                    "bbox": {"x": 490.0 / 854.0, "y": 98.0 / 480.0, "width": 36.0 / 854.0, "height": 120.0 / 480.0},
                    "confidence": 0.78,
                },
            )

        self.assertEqual(result, target)
        self.assertEqual(diagnostic["state"], "tracked")
        self.assertEqual(tracker._target_tracker_id, 7)

    def test_support_anchor_handoff_rejects_far_track_after_recovery(self) -> None:
        tracker = PersonBBoxTracker(yolo_model=object(), byte_tracker_factory=lambda _fps: object())
        frame = np.zeros((480, 854, 3), dtype=np.uint8)
        tracker._last_known_xyxy = (420.0, 175.0, 460.0, 245.0)
        tracker._target_tracker_id = 3

        with (
            patch.object(tracker, "_detect", return_value=[]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([], [])),
        ):
            recovered, recovered_diag = tracker.process_frame_detailed(
                frame,
                tracker._last_known_xyxy,
                frame_index=12,
                frame_path=Path("frame_0012.jpg"),
                support_anchor_bbox={
                    "bbox": {"x": 0.5472, "y": 0.4193, "width": 0.0574, "height": 0.1024},
                    "confidence": 0.894,
                },
            )

        wrong_track = (315.3, 198.8, 352.1, 265.9)
        with (
            patch.object(tracker, "_detect", return_value=[(*wrong_track, 0.83)]),
            patch.object(tracker, "_update_tracks", return_value=_FakeDetections([wrong_track], [6], [0.83])),
        ):
            result, diagnostic = tracker.process_frame_detailed(
                frame,
                tracker._last_known_xyxy,
                frame_index=13,
                frame_path=Path("frame_0013.jpg"),
            )

        self.assertIsNotNone(recovered)
        self.assertEqual(recovered_diag["state"], "support_anchor_recovered")
        self.assertIsNone(result)
        self.assertEqual(diagnostic["state"], "support_anchor_handoff_reused")
        self.assertEqual(diagnostic["rejected_reasons"], ["initial_target_not_found"])
        self.assertIsNone(tracker._target_tracker_id)
        self.assertIn(PERSON_TRACKER_SUPPORT_ANCHOR_HANDOFF_REUSED_FLAG, tracker.quality_flags)

    def test_detailed_tracking_maps_support_anchors_across_anchor_splice(self) -> None:
        frame_paths = [Path(f"frame_{index:04d}.jpg") for index in range(4)]
        backward = ([{"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2}] * 3, [], [{"state": "tracked"}] * 3)
        forward = ([{"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2}] * 2, [], [{"state": "tracked"}] * 2)
        calls: list[dict[int, dict[str, object]]] = []

        def fake_track_forward(
            frame_paths_arg,
            initial_bbox,
            *,
            effective_fps,
            support_anchor_bboxes_by_frame=None,
            manual_lock_mode=False,
        ):
            calls.append(dict(support_anchor_bboxes_by_frame or {}))
            return backward if len(calls) == 1 else forward

        with patch("app.services.person_tracker._track_forward_detailed", side_effect=fake_track_forward):
            track_person_bbox_detailed(
                frame_paths,
                {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2},
                initial_frame_index=2,
                support_anchor_bboxes_by_frame={
                    1: {"bbox": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.2}},
                    2: {"bbox": {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.2}},
                    3: {"bbox": {"x": 0.3, "y": 0.2, "width": 0.1, "height": 0.2}},
                },
            )

        self.assertEqual(sorted(calls[0]), [0, 1])
        self.assertEqual(sorted(calls[1]), [0, 1])
        self.assertEqual(calls[0][1]["bbox"]["x"], 0.1)
        self.assertEqual(calls[1][1]["bbox"]["x"], 0.3)


if __name__ == "__main__":
    unittest.main()
