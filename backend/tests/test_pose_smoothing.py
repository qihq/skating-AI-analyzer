from __future__ import annotations

import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.biomechanics import _point
from app.services.pose import (
    _MANUAL_LOCK_TRACKER_BLOCKED_SOURCE,
    _MANUAL_LOCK_UNRELIABLE_TRACKER_POSE_FLAG,
    _MANUAL_LOCK_UNRELIABLE_TRACKER_POSE_REASON,
    _apply_short_gap_interpolation,
    _candidate_rejection_reasons,
    _crop_bounds,
    _empty_payload,
    _manual_lock_blocks_unreliable_tracker_pose,
    _pending_relock_bbox_from_diagnostic,
    _reference_crop_padding_ratio,
    _reference_crop_source,
    _rejected_detector_bbox_for_crop,
    _score_pose_candidate,
    _tracker_bbox_is_reliable,
    _unreliable_tracker_bbox_for_crop,
    _validation_bbox_for_candidate,
    extract_pose,
)
from app.services.smoothing import smooth_keypoint_sequence


def _empty_keypoints() -> list[dict[str, float | int | str]]:
    return [
        {
            "id": index,
            "name": f"landmark_{index}",
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
            "visibility": 0.0,
        }
        for index in range(33)
    ]


def _visible_pose_keypoints(x: float = 0.45, y: float = 0.45) -> list[dict[str, float | int | str]]:
    keypoints = _empty_keypoints()
    for offset, keypoint_id in enumerate((11, 12, 23, 24)):
        keypoints[keypoint_id] = {
            "id": keypoint_id,
            "name": f"landmark_{keypoint_id}",
            "x": x + offset * 0.005,
            "y": y + offset * 0.01,
            "z": 0.0,
            "visibility": 0.9,
        }
    return keypoints


def _full_body_pose_keypoints(bbox: dict[str, float], *, visibility: float = 0.9) -> list[dict[str, float | int | str]]:
    keypoints = _empty_keypoints()
    left = float(bbox["x"])
    top = float(bbox["y"])
    width = float(bbox["width"])
    height = float(bbox["height"])
    for index in range(33):
        column = index % 5
        row = index // 5
        x_ratio = 0.05 + min(column, 4) * 0.225
        y_ratio = 0.03 + min(row, 6) * 0.155
        keypoints[index] = {
            "id": index,
            "name": f"landmark_{index}",
            "x": round(left + width * x_ratio, 4),
            "y": round(top + height * y_ratio, 4),
            "z": 0.0,
            "visibility": visibility,
        }
    return keypoints


class _FakeLandmark:
    def __init__(self, x: float, y: float, visibility: float = 0.9) -> None:
        self.x = x
        self.y = y
        self.z = 0.0
        self.visibility = visibility


class _FakePoseResult:
    def __init__(self) -> None:
        self.pose_landmarks = types.SimpleNamespace(
            landmark=[_FakeLandmark(0.45, 0.45) for _ in range(33)]
        )


class _CountingPose:
    process_calls = 0

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def process(self, image: object) -> _FakePoseResult:
        type(self).process_calls += 1
        return _FakePoseResult()

    def close(self) -> None:
        pass


class _FakeCV2:
    COLOR_BGR2RGB = 1

    @staticmethod
    def imread(path: str) -> np.ndarray:
        return np.zeros((100, 100, 3), dtype=np.uint8)

    @staticmethod
    def cvtColor(image: np.ndarray, color: int) -> np.ndarray:
        return image


def _frames_from_signal(values: list[float], *, missing: set[int] | None = None) -> list[dict[str, object]]:
    missing = missing or set()
    frames: list[dict[str, object]] = []
    for frame_index, value in enumerate(values):
        keypoints = _empty_keypoints()
        visibility = 0.0 if frame_index in missing else 0.99
        for keypoint_id in (11, 12, 23, 24):
            keypoints[keypoint_id] = {
                "id": keypoint_id,
                "name": f"landmark_{keypoint_id}",
                "x": value,
                "y": 0.2 + keypoint_id * 0.01,
                "z": 0.0,
                "visibility": visibility,
            }
        frames.append({"frame": f"frame_{frame_index + 1:04d}.jpg", "keypoints": keypoints})
    return frames


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def _second_difference(values: list[float]) -> list[float]:
    return [values[index + 1] - 2 * values[index] + values[index - 1] for index in range(1, len(values) - 1)]


class PoseSmoothingTests(unittest.TestCase):
    def test_one_euro_filter_reduces_high_frequency_jitter_and_keeps_trend(self) -> None:
        sample_count = 90
        effective_fps = 30.0
        trend = [0.1 + 0.08 * math.sin(index / 12.0) for index in range(sample_count)]
        noisy = [
            value + (0.02 if index % 2 == 0 else -0.02)
            for index, value in enumerate(trend)
        ]

        smoothed = smooth_keypoint_sequence(_frames_from_signal(noisy), effective_fps)
        smoothed_x = [float(frame["keypoints"][11]["x"]) for frame in smoothed]
        raw_jitter = [(noisy[index] - trend[index]) for index in range(sample_count)]
        raw_high_frequency = _second_difference(noisy)
        smoothed_high_frequency = _second_difference(smoothed_x)
        trend_mae = sum(abs(smoothed_x[index] - trend[index]) for index in range(sample_count)) / sample_count

        self.assertGreater(_rms(raw_jitter), 0.015)
        self.assertLess(_rms(smoothed_high_frequency), _rms(raw_high_frequency) * 0.12)
        self.assertLess(trend_mae, 0.02)

    def test_low_visibility_gap_is_linearly_interpolated_before_smoothing(self) -> None:
        values = [0.1 + index * 0.01 for index in range(10)]
        smoothed = smooth_keypoint_sequence(_frames_from_signal(values, missing={3, 4, 5}), effective_fps=10.0)

        for frame_index in (3, 4, 5):
            keypoint = smoothed[frame_index]["keypoints"][11]
            self.assertTrue(keypoint["interpolated"])
            self.assertEqual(keypoint["visibility"], 0.0)
            self.assertGreater(float(keypoint["x"]), float(smoothed[frame_index - 1]["keypoints"][11]["x"]))

    def test_biomechanics_point_accepts_smoothed_low_visibility_coordinates(self) -> None:
        keypoints = _empty_keypoints()
        keypoints[11] = {"id": 11, "x": 0.42, "y": 0.24, "z": 0.0, "visibility": 0.4}
        keypoints[12] = {"id": 12, "x": 0.58, "y": 0.24, "z": 0.0, "visibility": 0.1, "interpolated": True}

        self.assertEqual(_point(keypoints, 11), {"x": 0.42, "y": 0.24, "z": 0.0})
        self.assertIsNone(_point(keypoints, 12))

    def test_fully_invisible_keypoint_remains_unusable(self) -> None:
        smoothed = smooth_keypoint_sequence(_frames_from_signal([0.1, 0.2, 0.3]), effective_fps=10.0)

        self.assertIsNone(smoothed[0]["keypoints"][0]["x"])
        self.assertIsNone(_point(smoothed[0]["keypoints"], 0))

    def test_empty_pose_payload_includes_diagnostics(self) -> None:
        payload = _empty_payload()

        self.assertEqual(payload["pose_diagnostics"]["total_frames"], 0)
        self.assertEqual(payload["pose_diagnostics"]["candidate_count_histogram"], {})

    def test_tracker_gate_rejects_pose_candidate_that_is_much_wider_than_tracker_bbox(self) -> None:
        tracker_bbox = {"x": 0.44, "y": 0.43, "width": 0.025, "height": 0.11}
        wide_pose_candidate = {
            "bbox": {"x": 0.40, "y": 0.37, "width": 0.19, "height": 0.10},
            "keypoints": _visible_pose_keypoints(0.45, 0.45),
            "source": "tasks_multi_pose",
        }

        reasons = _candidate_rejection_reasons(
            wide_pose_candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertIn("tracker_width_ratio", reasons)
        self.assertIn("oversized_multi_pose_candidate", reasons)

    def test_stale_tracker_allows_unique_full_body_multi_pose_recovery(self) -> None:
        reference_bbox = {"x": 0.3284, "y": 0.1843, "width": 0.087, "height": 0.4765}
        stale_tracker_bbox = {"x": 0.3416, "y": 0.17, "width": 0.0442, "height": 0.5041}
        seed_bbox = {"x": 0.4313, "y": 0.2, "width": 0.0955, "height": 0.3749}
        candidate_bbox = {"x": 0.3978, "y": 0.216, "width": 0.1027, "height": 0.784}
        candidate = {
            "bbox": candidate_bbox,
            "visibility_sum": 29.7,
            "keypoints": _full_body_pose_keypoints(candidate_bbox),
            "source": "tasks_multi_pose",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=reference_bbox,
            tracker_bbox=reference_bbox,
            seed_bbox=seed_bbox,
            previous_core_center={"x": 0.30, "y": 0.30},
            tracker_state="lost_reused",
            full_body_multi_pose_candidate_count=1,
        )
        scored = _score_pose_candidate(
            candidate,
            reference_bbox=reference_bbox,
            current_tracker_bbox=None,
            motion_bbox=stale_tracker_bbox,
            seed_bbox=seed_bbox,
        )

        self.assertEqual(reasons, [])
        self.assertIn("stale_tracker_multi_pose_recovery", candidate["candidate_validation"])
        self.assertGreaterEqual(scored["score"], 0.24)

    def test_manual_lock_disables_unique_full_body_multi_pose_recovery(self) -> None:
        reference_bbox = {"x": 0.3284, "y": 0.1843, "width": 0.087, "height": 0.4765}
        seed_bbox = {"x": 0.4313, "y": 0.2, "width": 0.0955, "height": 0.3749}
        candidate_bbox = {"x": 0.3978, "y": 0.216, "width": 0.1027, "height": 0.784}
        candidate = {
            "bbox": candidate_bbox,
            "visibility_sum": 29.7,
            "keypoints": _full_body_pose_keypoints(candidate_bbox),
            "source": "tasks_multi_pose",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=reference_bbox,
            tracker_bbox=reference_bbox,
            seed_bbox=seed_bbox,
            previous_core_center={"x": 0.30, "y": 0.30},
            tracker_state="lost_reused",
            full_body_multi_pose_candidate_count=1,
            manual_lock_mode=True,
        )

        self.assertIn("tracker_center_distance", reasons)
        self.assertIn("oversized_multi_pose_candidate", reasons)
        self.assertNotIn("stale_tracker_multi_pose_recovery", candidate["candidate_validation"])

    def test_manual_lock_blocks_pose_when_tracker_state_is_unreliable(self) -> None:
        target_lock = {"manual_override": True}

        self.assertTrue(
            _manual_lock_blocks_unreliable_tracker_pose(
                target_lock,
                None,
            )
        )
        self.assertTrue(
            _manual_lock_blocks_unreliable_tracker_pose(
                target_lock,
                {"state": "lost_reused"},
            )
        )
        self.assertTrue(
            _manual_lock_blocks_unreliable_tracker_pose(
                target_lock,
                {"state": "detector_relocked", "candidate_geometry": {"area_ratio": 0.2, "reference_coverage": 0.0}},
            )
        )
        self.assertTrue(
            _manual_lock_blocks_unreliable_tracker_pose(
                target_lock,
                {"state": "detector_relocked"},
            )
        )
        self.assertTrue(
            _manual_lock_blocks_unreliable_tracker_pose(
                target_lock,
                {"state": "relocked"},
            )
        )
        self.assertFalse(
            _manual_lock_blocks_unreliable_tracker_pose(
                target_lock,
                {"state": "tracked"},
            )
        )
        self.assertTrue(
            _manual_lock_blocks_unreliable_tracker_pose(
                target_lock,
                {"state": "support_anchor_recovered"},
            )
        )
        self.assertFalse(
            _manual_lock_blocks_unreliable_tracker_pose(
                {"manual_override": False},
                None,
            )
        )

    def test_extract_pose_blocks_manual_lock_unreliable_tracker_before_mediapipe(self) -> None:
        bbox = {"x": 0.4, "y": 0.4, "width": 0.08, "height": 0.2}
        fake_cv2 = types.SimpleNamespace(
            COLOR_BGR2RGB=_FakeCV2.COLOR_BGR2RGB,
            imread=_FakeCV2.imread,
            cvtColor=_FakeCV2.cvtColor,
        )
        fake_mp = types.SimpleNamespace(
            solutions=types.SimpleNamespace(
                pose=types.SimpleNamespace(Pose=_CountingPose),
            ),
        )
        _CountingPose.process_calls = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            frame_path = Path(tmpdir) / "frame_0001.jpg"
            frame_path.touch()
            with (
                patch.dict(sys.modules, {"cv2": fake_cv2, "mediapipe": fake_mp}),
                patch("app.services.pose._resolve_tasks_landmarker", return_value=None),
                patch("app.services.pose.smooth_keypoint_sequence", side_effect=lambda frames, _fps: frames),
            ):
                payload = extract_pose(
                    tmpdir,
                    target_lock={
                        "manual_override": True,
                        "selected_bbox": bbox,
                        "person_tracker_diagnostics": [
                            {
                                "frame_index": 0,
                                "state": "lost_reused",
                                "bbox": bbox,
                                "lost_frames": 1,
                            }
                        ],
                    },
                    bbox_per_frame=[bbox],
                    effective_fps=10.0,
                )

        self.assertEqual(_CountingPose.process_calls, 0)
        self.assertIn(_MANUAL_LOCK_UNRELIABLE_TRACKER_POSE_FLAG, payload["quality_flags"])
        self.assertEqual(payload["frames"][0]["tracking_state"], "lost")
        self.assertEqual(payload["frames"][0]["keypoints"], [])
        diagnostics = payload["pose_diagnostics"]
        self.assertEqual(diagnostics["manual_lock_unreliable_tracker_blocked_frames"], 1)
        self.assertEqual(diagnostics["frames"][0]["reason"], "manual_lock_unreliable_tracker_blocked")
        self.assertEqual(diagnostics["frames"][0]["pose_reference_source"], "manual_lock_tracker_blocked")

    def test_extract_pose_blocks_manual_lock_missing_tracker_diagnostics(self) -> None:
        bbox = {"x": 0.4, "y": 0.4, "width": 0.08, "height": 0.2}
        fake_cv2 = types.SimpleNamespace(
            COLOR_BGR2RGB=_FakeCV2.COLOR_BGR2RGB,
            imread=_FakeCV2.imread,
            cvtColor=_FakeCV2.cvtColor,
        )
        fake_mp = types.SimpleNamespace(
            solutions=types.SimpleNamespace(
                pose=types.SimpleNamespace(Pose=_CountingPose),
            ),
        )
        _CountingPose.process_calls = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            frame_path = Path(tmpdir) / "frame_0001.jpg"
            frame_path.touch()
            with (
                patch.dict(sys.modules, {"cv2": fake_cv2, "mediapipe": fake_mp}),
                patch("app.services.pose._resolve_tasks_landmarker", return_value=None),
                patch("app.services.pose.smooth_keypoint_sequence", side_effect=lambda frames, _fps: frames),
            ):
                payload = extract_pose(
                    tmpdir,
                    target_lock={
                        "manual_override": True,
                        "selected_bbox": bbox,
                    },
                    bbox_per_frame=[bbox],
                    effective_fps=10.0,
                )

        self.assertEqual(_CountingPose.process_calls, 0)
        self.assertIn(_MANUAL_LOCK_UNRELIABLE_TRACKER_POSE_FLAG, payload["quality_flags"])
        self.assertEqual(payload["frames"][0]["tracking_state"], "lost")
        self.assertEqual(payload["frames"][0]["keypoints"], [])
        diagnostics = payload["pose_diagnostics"]
        self.assertEqual(diagnostics["manual_lock_unreliable_tracker_blocked_frames"], 1)
        self.assertEqual(diagnostics["frames"][0]["reason"], "manual_lock_unreliable_tracker_blocked")

    def test_stale_tracker_recovery_still_rejects_ambiguous_multi_pose_candidates(self) -> None:
        reference_bbox = {"x": 0.3284, "y": 0.1843, "width": 0.087, "height": 0.4765}
        seed_bbox = {"x": 0.4313, "y": 0.2, "width": 0.0955, "height": 0.3749}
        candidate_bbox = {"x": 0.4474, "y": 0.2062, "width": 0.1007, "height": 0.7938}
        candidate = {
            "bbox": candidate_bbox,
            "keypoints": _full_body_pose_keypoints(candidate_bbox),
            "source": "tasks_multi_pose",
        }

        tracked_reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=reference_bbox,
            tracker_bbox=reference_bbox,
            seed_bbox=seed_bbox,
            tracker_state="tracked",
            full_body_multi_pose_candidate_count=1,
        )
        ambiguous_reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=reference_bbox,
            tracker_bbox=reference_bbox,
            seed_bbox=seed_bbox,
            tracker_state="lost_reused",
            full_body_multi_pose_candidate_count=2,
        )

        self.assertIn("tracker_center_distance", tracked_reasons)
        self.assertIn("oversized_multi_pose_candidate", tracked_reasons)
        self.assertIn("tracker_center_distance", ambiguous_reasons)
        self.assertIn("oversized_multi_pose_candidate", ambiguous_reasons)

    def test_tracker_gate_allows_reasonable_pose_candidate_near_tracker_bbox(self) -> None:
        tracker_bbox = {"x": 0.44, "y": 0.43, "width": 0.04, "height": 0.12}
        pose_candidate = {
            "bbox": {"x": 0.435, "y": 0.42, "width": 0.06, "height": 0.15},
            "keypoints": _visible_pose_keypoints(0.455, 0.45),
            "source": "single_pose_crop",
        }

        reasons = _candidate_rejection_reasons(
            pose_candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertEqual(reasons, [])

    def test_keypoint_gate_rejects_candidate_when_core_points_are_outside_tracker_roi(self) -> None:
        tracker_bbox = {"x": 0.44, "y": 0.43, "width": 0.04, "height": 0.12}
        candidate = {
            "bbox": {"x": 0.435, "y": 0.42, "width": 0.06, "height": 0.15},
            "keypoints": _visible_pose_keypoints(0.15, 0.15),
            "source": "single_pose_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertIn("keypoint_roi_coverage", reasons)
        self.assertIn("core_center_outside_roi", reasons)

    def test_keypoint_gate_rejects_predicted_crop_when_core_center_drifts_from_tracker(self) -> None:
        tracker_bbox = {"x": 0.44, "y": 0.43, "width": 0.08, "height": 0.18}
        candidate = {
            "bbox": {"x": 0.50, "y": 0.42, "width": 0.06, "height": 0.18},
            "keypoints": _visible_pose_keypoints(0.535, 0.47),
            "source": "single_pose_predicted_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertIn("core_center_offset_from_tracker", reasons)
        self.assertIn("core_center_tracker_offset", candidate["candidate_validation"])

    def test_tracker_aligned_crop_allows_fast_core_motion(self) -> None:
        previous_bbox = {"x": 0.31, "y": 0.32, "width": 0.16, "height": 0.42}
        tracker_bbox = {"x": 0.34, "y": 0.32, "width": 0.16, "height": 0.42}
        candidate = {
            "bbox": {"x": 0.34, "y": 0.32, "width": 0.16, "height": 0.42},
            "keypoints": _visible_pose_keypoints(0.45, 0.47),
            "source": "single_pose_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=previous_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=previous_bbox,
            previous_core_center={"x": 0.29, "y": 0.30},
        )

        self.assertNotIn("temporal_pose_jump", reasons)

    def test_seed_bbox_no_overlap_does_not_penalize_tracker_aligned_motion(self) -> None:
        tracker_bbox = {"x": 0.60, "y": 0.43, "width": 0.04, "height": 0.16}
        seed_bbox = {"x": 0.30, "y": 0.43, "width": 0.04, "height": 0.16}
        candidate = {
            "bbox": tracker_bbox,
            "keypoints": _visible_pose_keypoints(0.62, 0.48),
            "source": "single_pose_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=seed_bbox,
        )

        self.assertEqual(reasons, [])

    def test_pending_relock_bbox_is_crop_hint_but_reused_tracker_bbox_is_not_reliable(self) -> None:
        diagnostic = {
            "state": "full_frame_yolo_relock_pending",
            "bbox": {"x": 0.30, "y": 0.40, "width": 0.03, "height": 0.14},
            "pending_relock_bbox": {"x": 0.50, "y": 0.42, "width": 0.04, "height": 0.18},
        }

        self.assertFalse(_tracker_bbox_is_reliable(diagnostic))
        self.assertEqual(
            _pending_relock_bbox_from_diagnostic(diagnostic),
            {"x": 0.5, "y": 0.42, "width": 0.04, "height": 0.18},
        )
        self.assertTrue(_tracker_bbox_is_reliable({"state": "detector_relocked"}))

    def test_partial_detector_relock_bbox_is_not_reliable_for_pose_crop(self) -> None:
        diagnostic = {
            "state": "detector_relocked",
            "candidate_geometry": {
                "area_ratio": 0.31,
                "reference_coverage": 0.0,
                "center_distance_ratio": 0.09,
            },
        }

        self.assertFalse(_tracker_bbox_is_reliable(diagnostic))

    def test_detector_relock_with_overlap_remains_reliable_for_pose_crop(self) -> None:
        diagnostic = {
            "state": "detector_relocked",
            "candidate_geometry": {
                "area_ratio": 0.62,
                "reference_coverage": 0.35,
                "center_distance_ratio": 0.04,
            },
        }

        self.assertTrue(_tracker_bbox_is_reliable(diagnostic))

    def test_regular_crop_validation_keeps_reference_bbox_when_prediction_is_also_available(self) -> None:
        reference_bbox = {"x": 0.37, "y": 0.37, "width": 0.13, "height": 0.18}
        predicted_bbox = {"x": 0.54, "y": 0.54, "width": 0.08, "height": 0.20}
        candidate = {
            "bbox": reference_bbox,
            "keypoints": _visible_pose_keypoints(0.43, 0.44),
            "source": "single_pose_crop",
        }

        validation_bbox = _validation_bbox_for_candidate(
            candidate,
            current_tracker_bbox=None,
            pending_relock_bbox=None,
            reference_bbox=reference_bbox,
            predicted_bbox=predicted_bbox,
        )
        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=reference_bbox,
            tracker_bbox=validation_bbox,
            seed_bbox=reference_bbox,
        )

        self.assertEqual(validation_bbox, reference_bbox)
        self.assertNotIn("tracker_center_distance", reasons)
        self.assertNotIn("core_center_outside_roi", reasons)

    def test_pending_relock_crop_is_validated_against_existing_reference_bbox(self) -> None:
        reference_bbox = {"x": 0.50, "y": 0.52, "width": 0.05, "height": 0.15}
        pending_relock_bbox = {"x": 0.34, "y": 0.45, "width": 0.25, "height": 0.55}
        candidate = {
            "bbox": pending_relock_bbox,
            "keypoints": _visible_pose_keypoints(0.44, 0.68),
            "source": "single_pose_pending_relock_crop",
        }

        validation_bbox = _validation_bbox_for_candidate(
            candidate,
            current_tracker_bbox=None,
            pending_relock_bbox=pending_relock_bbox,
            reference_bbox=reference_bbox,
            predicted_bbox=None,
        )
        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=reference_bbox,
            tracker_bbox=validation_bbox,
            seed_bbox=reference_bbox,
        )

        self.assertEqual(validation_bbox, reference_bbox)
        self.assertIn("tracker_width_ratio", reasons)
        self.assertIn("tracker_center_distance", reasons)

    def test_relock_pending_reference_crop_keeps_distinct_source(self) -> None:
        reference_bbox = {"x": 0.50, "y": 0.52, "width": 0.05, "height": 0.15}
        pending_relock_bbox = {"x": 0.34, "y": 0.45, "width": 0.25, "height": 0.55}

        self.assertEqual(
            _reference_crop_source(
                current_tracker_bbox=None,
                pending_relock_bbox=pending_relock_bbox,
                unreliable_tracker_crop_bbox=None,
                reference_bbox=reference_bbox,
            ),
            "single_pose_relock_reference_crop",
        )
        self.assertEqual(
            _reference_crop_source(
                current_tracker_bbox=None,
                pending_relock_bbox=pending_relock_bbox,
                unreliable_tracker_crop_bbox=None,
                reference_bbox=pending_relock_bbox,
            ),
            "single_pose_pending_relock_crop",
        )

    def test_relock_reference_crop_rejects_core_center_drift(self) -> None:
        reference_bbox = {"x": 0.5103, "y": 0.5571, "width": 0.0484, "height": 0.1482}
        candidate = {
            "bbox": reference_bbox,
            "keypoints": _visible_pose_keypoints(0.555, 0.56),
            "source": "single_pose_relock_reference_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=reference_bbox,
            tracker_bbox=reference_bbox,
            seed_bbox=reference_bbox,
        )

        self.assertIn("core_center_offset_from_relock_reference", reasons)
        self.assertIn("core_center_tracker_offset", candidate["candidate_validation"])

    def test_continuity_rejected_tracker_bbox_can_be_conservative_crop_hint(self) -> None:
        previous_bbox = {"x": 0.37, "y": 0.37, "width": 0.13, "height": 0.18}
        rejected_bbox = {"x": 0.35, "y": 0.32, "width": 0.17, "height": 0.23}
        diagnostic = {"state": "continuity_rejected", "bbox": rejected_bbox}

        self.assertEqual(
            _unreliable_tracker_bbox_for_crop(diagnostic, rejected_bbox, previous_bbox),
            rejected_bbox,
        )
        self.assertIsNone(
            _unreliable_tracker_bbox_for_crop(
                diagnostic,
                {"x": 0.80, "y": 0.20, "width": 0.08, "height": 0.20},
                previous_bbox,
            )
        )

    def test_lost_reused_tracker_bbox_can_be_conservative_crop_hint(self) -> None:
        previous_bbox = {"x": 0.5171, "y": 0.3763, "width": 0.0486, "height": 0.1189}
        diagnostic = {"state": "lost_reused", "bbox": previous_bbox}

        self.assertEqual(
            _unreliable_tracker_bbox_for_crop(diagnostic, previous_bbox, previous_bbox),
            previous_bbox,
        )

    def test_area_only_rejected_detector_bbox_can_be_conservative_crop_hint(self) -> None:
        reference_bbox = {"x": 0.4376, "y": 0.4391, "width": 0.0378, "height": 0.1168}
        rejected_bbox = {"x": 0.3426, "y": 0.2771, "width": 0.1473, "height": 0.7177}
        diagnostic = {
            "state": "lost_reused",
            "rejected_candidates": [
                {
                    "bbox": rejected_bbox,
                    "source": "full_frame_yolo_relock",
                    "reasons": ["area_ratio"],
                    "reference_coverage": 1.0,
                    "candidate_coverage": 0.0418,
                    "area_ratio": 23.9155,
                    "center_distance_ratio": 0.0764,
                }
            ],
        }

        self.assertEqual(
            _rejected_detector_bbox_for_crop(diagnostic, reference_bbox),
            rejected_bbox,
        )

    def test_rejected_detector_crop_hint_rejects_weak_identity_candidate(self) -> None:
        reference_bbox = {"x": 0.486, "y": 0.3933, "width": 0.0402, "height": 0.1258}
        diagnostic = {
            "state": "lost_reused",
            "rejected_candidates": [
                {
                    "bbox": {"x": 0.399, "y": 0.3329, "width": 0.0382, "height": 0.15},
                    "source": "full_frame_yolo_relock",
                    "reasons": ["weak_identity_support", "far_from_reference"],
                    "reference_coverage": 0.0,
                    "candidate_coverage": 0.0,
                    "area_ratio": 1.1331,
                    "center_distance_ratio": 0.0803,
                }
            ],
        }

        self.assertIsNone(_rejected_detector_bbox_for_crop(diagnostic, reference_bbox))

    def test_unreliable_tracker_crop_hint_uses_tracker_padding_even_as_reference(self) -> None:
        rejected_bbox = {"x": 0.35, "y": 0.32, "width": 0.17, "height": 0.23}

        self.assertEqual(
            _reference_crop_source(
                current_tracker_bbox=None,
                pending_relock_bbox=None,
                unreliable_tracker_crop_bbox=rejected_bbox,
            ),
            "single_pose_unreliable_tracker_crop",
        )
        self.assertGreater(
            _reference_crop_padding_ratio(
                current_tracker_bbox=None,
                pending_relock_bbox=None,
                unreliable_tracker_crop_bbox=rejected_bbox,
            ),
            0.0,
        )

    def test_small_tracker_crop_rejects_partial_foreground_body(self) -> None:
        tracker_bbox = {"x": 0.4376, "y": 0.4391, "width": 0.0385, "height": 0.1163}
        keypoints = _empty_keypoints()
        for keypoint_id, x, y in (
            (11, 0.455, 0.484),
            (12, 0.381, 0.486),
        ):
            keypoints[keypoint_id] = {
                "id": keypoint_id,
                "name": f"landmark_{keypoint_id}",
                "x": x,
                "y": y,
                "z": 0.0,
                "visibility": 0.99,
            }
        candidate = {
            "bbox": tracker_bbox,
            "keypoints": keypoints,
            "source": "single_pose_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertIn("core_keypoints_insufficient", reasons)
        self.assertIn("visible_keypoint_bbox", candidate["candidate_validation"])

    def test_small_tracker_crop_rejects_large_keypoint_spread(self) -> None:
        tracker_bbox = {"x": 0.5103, "y": 0.5571, "width": 0.0484, "height": 0.1482}
        keypoints = _empty_keypoints()
        for keypoint_id, x, y in (
            (11, 0.54, 0.54),
            (12, 0.57, 0.56),
            (23, 0.55, 0.64),
            (24, 0.56, 0.66),
            (25, 0.55, 0.84),
            (26, 0.57, 0.86),
        ):
            keypoints[keypoint_id] = {
                "id": keypoint_id,
                "name": f"landmark_{keypoint_id}",
                "x": x,
                "y": y,
                "z": 0.0,
                "visibility": 0.99,
            }
        candidate = {
            "bbox": tracker_bbox,
            "keypoints": keypoints,
            "source": "single_pose_pending_relock_crop",
        }

        reasons = _candidate_rejection_reasons(
            candidate,
            previous_bbox=tracker_bbox,
            tracker_bbox=tracker_bbox,
            seed_bbox=tracker_bbox,
        )

        self.assertIn("crop_keypoint_spread", reasons)

    def test_short_lost_gap_is_interpolated_for_display_only(self) -> None:
        frames = [
            {"frame": "frame_0001.jpg", "tracking_state": "tracked", "keypoints": _visible_pose_keypoints(0.4, 0.4), "target_bbox": {"x": 0.4, "y": 0.4, "width": 0.05, "height": 0.1}},
            {"frame": "frame_0002.jpg", "tracking_state": "lost", "keypoints": [], "target_bbox": {"x": 0.41, "y": 0.4, "width": 0.05, "height": 0.1}},
            {"frame": "frame_0003.jpg", "tracking_state": "tracked", "keypoints": _visible_pose_keypoints(0.5, 0.5), "target_bbox": {"x": 0.5, "y": 0.5, "width": 0.05, "height": 0.1}},
        ]
        diagnostics = [{"tracking_state": frame["tracking_state"]} for frame in frames]

        interpolated, remaining_lost = _apply_short_gap_interpolation(frames, diagnostics)

        self.assertEqual(interpolated, 1)
        self.assertEqual(remaining_lost, 0)
        self.assertEqual(frames[1]["tracking_state"], "interpolated")
        self.assertEqual(frames[1]["tracking_confidence"], 0.05)
        self.assertTrue(all(point["interpolated"] for point in frames[1]["keypoints"]))
        self.assertEqual(diagnostics[1]["reason"], "pose_interpolated")

    def test_manual_lock_blocked_gap_is_not_interpolated(self) -> None:
        frames = [
            {"frame": "frame_0001.jpg", "tracking_state": "tracked", "keypoints": _visible_pose_keypoints(0.4, 0.4), "target_bbox": {"x": 0.4, "y": 0.4, "width": 0.05, "height": 0.1}},
            {"frame": "frame_0002.jpg", "tracking_state": "lost", "keypoints": [], "target_bbox": {"x": 0.41, "y": 0.4, "width": 0.05, "height": 0.1}},
            {"frame": "frame_0003.jpg", "tracking_state": "tracked", "keypoints": _visible_pose_keypoints(0.5, 0.5), "target_bbox": {"x": 0.5, "y": 0.5, "width": 0.05, "height": 0.1}},
        ]
        diagnostics = [
            {"tracking_state": "tracked"},
            {
                "tracking_state": "lost",
                "reason": _MANUAL_LOCK_UNRELIABLE_TRACKER_POSE_REASON,
                "pose_reference_source": _MANUAL_LOCK_TRACKER_BLOCKED_SOURCE,
            },
            {"tracking_state": "tracked"},
        ]

        interpolated, remaining_lost = _apply_short_gap_interpolation(frames, diagnostics)

        self.assertEqual(interpolated, 0)
        self.assertEqual(remaining_lost, 1)
        self.assertEqual(frames[1]["tracking_state"], "lost")
        self.assertEqual(frames[1]["keypoints"], [])
        self.assertEqual(diagnostics[1]["reason"], _MANUAL_LOCK_UNRELIABLE_TRACKER_POSE_REASON)

    def test_tracker_crop_expands_bbox_for_single_pose_fallback(self) -> None:
        bbox = {"x": 0.40, "y": 0.40, "width": 0.10, "height": 0.20}

        left, top, right, bottom = _crop_bounds(1000, 500, bbox, padding_ratio=0.75)

        self.assertEqual((left, top, right, bottom), (325, 125, 575, 375))

    def test_tiny_tracker_crop_keeps_legacy_bounds_without_retry_minimum(self) -> None:
        bbox = {"x": 0.632, "y": 0.3566, "width": 0.02, "height": 0.1052}

        left, top, right, bottom = _crop_bounds(854, 480, bbox, padding_ratio=0.0)

        self.assertEqual((right - left, bottom - top), (17, 50))

    def test_tiny_tracker_crop_retry_uses_minimum_pose_roi_even_without_padding(self) -> None:
        bbox = {"x": 0.632, "y": 0.3566, "width": 0.02, "height": 0.1052}

        left, top, right, bottom = _crop_bounds(854, 480, bbox, padding_ratio=0.0, enforce_tiny_min_roi=True)

        self.assertGreaterEqual(right - left, 96)
        self.assertGreaterEqual(bottom - top, 112)
        self.assertAlmostEqual((left + right) / 2 / 854, bbox["x"] + bbox["width"] / 2, delta=0.01)
        self.assertAlmostEqual((top + bottom) / 2 / 480, bbox["y"] + bbox["height"] / 2, delta=0.01)

    def test_tiny_tracker_crop_minimum_roi_applies_after_padding(self) -> None:
        bbox = {"x": 0.6086, "y": 0.4128, "width": 0.02, "height": 0.0833}

        left, top, right, bottom = _crop_bounds(854, 480, bbox, padding_ratio=0.75, enforce_tiny_min_roi=True)

        self.assertGreaterEqual(right - left, 96)
        self.assertGreaterEqual(bottom - top, 112)


if __name__ == "__main__":
    unittest.main()
