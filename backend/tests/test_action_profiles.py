from __future__ import annotations

import unittest

from app.services.action_profiles import (
    ACTION_SUBTYPE_OPTIONS,
    JUMP_SUBTYPES,
    infer_analysis_profile,
    infer_profile_hint,
)


JUMP_ACTION_TYPE = next(
    action_type for action_type in ACTION_SUBTYPE_OPTIONS if infer_profile_hint(action_type, None) == "jump"
)
JUMP_ACTION_SUBTYPE = next(
    subtype for subtype in ACTION_SUBTYPE_OPTIONS[JUMP_ACTION_TYPE] if subtype in JUMP_SUBTYPES
)


def _frame(
    com_y: float,
    nose_y: float,
    left_ankle_y: float | None,
    right_ankle_y: float | None,
    *,
    center_x: float = 0.5,
    body_facing: float = 1.0,
    visibility: float | None = 0.99,
    frame_id: str | None = None,
    tracking_state: str | None = None,
    ankle_interpolated: bool = False,
) -> dict[str, object]:
    hip_y = com_y - 0.01
    shoulder_y = com_y + 0.01
    shoulder_half_width = 0.04 * body_facing
    hip_half_width = 0.025 * body_facing
    left_ankle = {"id": 27, "x": center_x + 0.02, "y": left_ankle_y, "visibility": visibility}
    right_ankle = {"id": 28, "x": center_x - 0.02, "y": right_ankle_y, "visibility": visibility}
    if ankle_interpolated:
        left_ankle["interpolated"] = True
        right_ankle["interpolated"] = True
    keypoints = [
        {"id": 0, "x": center_x, "y": nose_y, "visibility": visibility},
        {"id": 11, "x": center_x + shoulder_half_width, "y": shoulder_y, "visibility": visibility},
        {"id": 12, "x": center_x - shoulder_half_width, "y": shoulder_y, "visibility": visibility},
        {"id": 23, "x": center_x + hip_half_width, "y": hip_y, "visibility": visibility},
        {"id": 24, "x": center_x - hip_half_width, "y": hip_y, "visibility": visibility},
        left_ankle,
        right_ankle,
    ]
    frame: dict[str, object] = {"keypoints": keypoints}
    if frame_id is not None:
        frame["frame"] = frame_id
    if tracking_state is not None:
        frame["tracking_state"] = tracking_state
    return frame


def _selected_metadata(
    entries: list[tuple[str, float | None]],
    *,
    frame_rate: float | None = 6.0,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "scores": [0.02] * len(entries),
        "selected": [
            {"frame_id": frame_id, "timestamp": timestamp}
            for frame_id, timestamp in entries
        ],
    }
    if frame_rate is not None:
        metadata["frame_rate"] = frame_rate
    return metadata


class ActionProfileInferenceTests(unittest.TestCase):
    def test_english_action_type_preserves_jump_profile(self) -> None:
        profile, evidence = infer_analysis_profile("jump", None, {"frames": []}, {"scores": []})

        self.assertEqual(profile, "jump")
        self.assertEqual(evidence["profile_hint"], "jump")
        self.assertIn("jump_gate_not_passed", evidence["quality_flags"])

    def test_vertical_range_without_airborne_transition_does_not_confirm_wide_shot_jump(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.45, right_ankle_y=0.45),
                _frame(com_y=0.57, nose_y=0.20, left_ankle_y=0.45, right_ankle_y=0.45),
            ]
        }
        motion_scores = {"scores": [0.02, 0.07]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertFalse(evidence["jump_gate_passed"])
        self.assertEqual(evidence["airborne_frames_detected"], 0)
        self.assertAlmostEqual(evidence["com_vertical_range"], 0.03, places=4)
        self.assertAlmostEqual(evidence["person_height_reference"], 0.25, places=4)
        self.assertAlmostEqual(evidence["relative_vertical_range"], 0.12, places=4)

    def test_scale_change_without_airborne_transition_does_not_confirm_close_shot_jump(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.72, nose_y=0.10, left_ankle_y=0.90, right_ankle_y=0.90),
                _frame(com_y=0.62, nose_y=0.10, left_ankle_y=0.90, right_ankle_y=0.90),
            ]
        }
        motion_scores = {"scores": [0.03, 0.08]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertFalse(evidence["jump_gate_passed"])
        self.assertEqual(evidence["airborne_frames_detected"], 0)
        self.assertAlmostEqual(evidence["com_vertical_range"], 0.1, places=4)
        self.assertAlmostEqual(evidence["person_height_reference"], 0.8, places=4)
        self.assertAlmostEqual(evidence["relative_vertical_range"], 0.125, places=4)

    def test_mixed_profile_does_not_treat_horizontal_translation_as_rotation(self) -> None:
        pose_data = {
            "frames": [
                _frame(0.60, 0.20, 0.80, 0.80, center_x=0.20),
                _frame(0.60, 0.20, 0.80, 0.80, center_x=0.42),
                _frame(0.60, 0.20, 0.80, 0.80, center_x=0.68),
                _frame(0.60, 0.20, 0.80, 0.80, center_x=0.82),
            ]
        }

        profile, evidence = infer_analysis_profile(
            "自由滑",
            "节目片段",
            pose_data,
            {"scores": [0.02, 0.08, 0.09, 0.07]},
        )

        self.assertEqual(profile, "step")
        self.assertEqual(evidence["hip_rotation_signal"], 0.0)
        self.assertIn("mixed_action_profile_defaulted_step", evidence["quality_flags"])

    def test_mixed_profile_accepts_repeated_internal_body_orientation_changes_as_rotation(self) -> None:
        pose_data = {
            "frames": [
                _frame(0.60, 0.20, 0.80, 0.80, body_facing=facing)
                for facing in (1.0, 0.2, -1.0, -0.2, 1.0, 0.2, -1.0)
            ]
        }

        profile, evidence = infer_analysis_profile(
            "自由滑",
            "节目片段",
            pose_data,
            {"scores": [0.02, 0.08, 0.09, 0.07, 0.08, 0.09, 0.07]},
        )

        self.assertEqual(profile, "spin")
        self.assertGreaterEqual(evidence["hip_rotation_signal"], 0.15)

    def test_jump_profile_detected_from_airborne_ankles_when_com_signal_is_weak(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
                _frame(com_y=0.595, nose_y=0.20, left_ankle_y=0.66, right_ankle_y=0.65),
                _frame(com_y=0.59, nose_y=0.20, left_ankle_y=0.64, right_ankle_y=0.63),
                _frame(com_y=0.598, nose_y=0.20, left_ankle_y=0.79, right_ankle_y=0.80),
            ]
        }
        motion_scores = {"scores": [0.01, 0.03, 0.04, 0.02]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])
        self.assertGreaterEqual(evidence["airborne_frames_detected"], 2)
        self.assertAlmostEqual(evidence["com_vertical_range"], 0.01, places=4)
        self.assertAlmostEqual(evidence["relative_vertical_range"], 0.0192, places=4)

    def test_jump_hint_is_preserved_when_jump_gate_fails(self) -> None:
        pose_data = {
            "frames": [
                _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
                _frame(com_y=0.595, nose_y=0.20, left_ankle_y=0.79, right_ankle_y=0.79),
                _frame(com_y=0.592, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80),
            ]
        }
        motion_scores = {"scores": [0.01, 0.02, 0.03]}

        profile, evidence = infer_analysis_profile(JUMP_ACTION_TYPE, JUMP_ACTION_SUBTYPE, pose_data, motion_scores)

        self.assertEqual(profile, "jump")
        self.assertFalse(evidence["jump_gate_passed"])
        self.assertEqual(evidence["profile_confidence"], "low")
        self.assertIn("jump_gate_not_passed", evidence["quality_flags"])
        self.assertTrue(any("几何证据不足" in message for message in evidence["negative_constraints"]))

    def test_explicit_jump_input_wins_over_rotation_signal_without_airborne(self) -> None:
        # Input-priority regression only: the same skeleton has a clear rotation
        # signal but no airborne phase. Explicit jump must remain jump; this does
        # not assert that automatic classification is correct.
        pose_data = {
            "frames": [
                _frame(com_y=0.60, nose_y=0.20, left_ankle_y=0.80, right_ankle_y=0.80, body_facing=facing)
                for facing in (1.0, 0.2, -1.0, -0.2, 1.0, 0.2, -1.0)
            ]
        }
        motion_scores = {"scores": [0.02, 0.08, 0.09, 0.07, 0.08, 0.09, 0.07]}

        explicit_profile, explicit_evidence = infer_analysis_profile(
            JUMP_ACTION_TYPE,
            JUMP_ACTION_SUBTYPE,
            pose_data,
            motion_scores,
        )
        mixed_profile, mixed_evidence = infer_analysis_profile(
            "自由滑",
            "节目片段",
            pose_data,
            motion_scores,
        )

        self.assertEqual(explicit_profile, "jump")
        self.assertFalse(explicit_evidence["jump_gate_passed"])
        self.assertIn("jump_gate_not_passed", explicit_evidence["quality_flags"])
        self.assertEqual(explicit_evidence["airborne_frames_detected"], 0)
        self.assertGreaterEqual(explicit_evidence["hip_rotation_signal"], 0.15)

        self.assertEqual(mixed_profile, "spin")
        self.assertEqual(mixed_evidence["airborne_frames_detected"], 0)
        self.assertGreaterEqual(mixed_evidence["hip_rotation_signal"], 0.15)
        self.assertIn("mixed_action_profile_inferred_spin_from_rotation", mixed_evidence["quality_flags"])

    def test_contiguous_trusted_segment_still_passes_jump_gate(self) -> None:
        pose_data = {
            "frames": [
                _frame(0.60, 0.20, 0.80, 0.80, frame_id="frame_0001.jpg"),
                _frame(0.595, 0.20, 0.66, 0.65, frame_id="frame_0002.jpg"),
                _frame(0.59, 0.20, 0.64, 0.63, frame_id="frame_0003.jpg"),
                _frame(0.598, 0.20, 0.79, 0.80, frame_id="frame_0004.jpg"),
            ]
        }
        motion_scores = _selected_metadata(
            [
                ("frame_0001", 0.0),
                ("frame_0002", 0.166),
                ("frame_0003", 0.333),
                ("frame_0004", 0.499),
            ]
        )

        profile, evidence = infer_analysis_profile(
            JUMP_ACTION_TYPE,
            JUMP_ACTION_SUBTYPE,
            pose_data,
            motion_scores,
        )

        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])
        self.assertGreaterEqual(evidence["airborne_frames_detected"], 2)

    def test_untrusted_frame_breaks_airborne_continuity(self) -> None:
        cases = [
            ("low_visibility", _frame(0.60, 0.20, 0.80, 0.80, visibility=0.1)),
            ("missing_keypoints", {"keypoints": []}),
            ("lost", _frame(0.60, 0.20, 0.80, 0.80, tracking_state="lost")),
            ("interpolated_frame", _frame(0.60, 0.20, 0.80, 0.80, tracking_state="interpolated")),
            ("low_confidence", _frame(0.60, 0.20, 0.80, 0.80, tracking_state="low_confidence")),
            ("interpolated_ankle", _frame(0.60, 0.20, 0.80, 0.80, ankle_interpolated=True)),
            ("missing_y", _frame(0.60, 0.20, None, None)),
            ("nan_y", _frame(0.60, 0.20, float("nan"), float("nan"))),
            ("infinite_y", _frame(0.60, 0.20, float("inf"), float("inf"))),
            ("missing_visibility", _frame(0.60, 0.20, 0.80, 0.80, visibility=None)),
            ("nan_visibility", _frame(0.60, 0.20, 0.80, 0.80, visibility=float("nan"))),
        ]
        for name, bad_frame in cases:
            with self.subTest(case=name):
                pose_data = {
                    "frames": [
                        _frame(0.60, 0.20, 0.80, 0.80),
                        _frame(0.595, 0.20, 0.66, 0.65),
                        _frame(0.59, 0.20, 0.64, 0.63),
                        bad_frame,
                        _frame(0.595, 0.20, 0.66, 0.65),
                        _frame(0.59, 0.20, 0.64, 0.63),
                        _frame(0.598, 0.20, 0.79, 0.80),
                    ]
                }
                profile, evidence = infer_analysis_profile(
                    JUMP_ACTION_TYPE,
                    JUMP_ACTION_SUBTYPE,
                    pose_data,
                    {"scores": [0.02] * 7},
                )

                self.assertEqual(profile, "jump")
                self.assertEqual(evidence["airborne_frames_detected"], 0)
                self.assertFalse(evidence["jump_gate_passed"])

    def test_contact_frames_do_not_bridge_evidence_gap(self) -> None:
        pose_data = {
            "frames": [
                _frame(0.60, 0.20, 0.80, 0.80),
                _frame(0.60, 0.20, 0.80, 0.80),
                _frame(0.595, 0.20, 0.66, 0.65),
                _frame(0.59, 0.20, 0.64, 0.63),
                _frame(0.60, 0.20, 0.80, 0.80, visibility=0.1),
                _frame(0.595, 0.20, 0.66, 0.65),
                _frame(0.59, 0.20, 0.64, 0.63),
                _frame(0.598, 0.20, 0.79, 0.80),
                _frame(0.60, 0.20, 0.80, 0.80),
            ]
        }

        _, evidence = infer_analysis_profile(
            JUMP_ACTION_TYPE,
            JUMP_ACTION_SUBTYPE,
            pose_data,
            {"scores": [0.02] * 9},
        )

        self.assertEqual(evidence["airborne_frames_detected"], 0)
        self.assertFalse(evidence["jump_gate_passed"])

    def test_selected_records_match_by_frame_id_not_list_order(self) -> None:
        pose_data = {
            "frames": [
                _frame(0.60, 0.20, 0.80, 0.80, frame_id="frame_0001.jpg"),
                _frame(0.60, 0.20, 0.80, 0.80, frame_id="frame_0002.jpg"),
                _frame(0.595, 0.20, 0.66, 0.65, frame_id="frame_0003.jpg"),
                _frame(0.59, 0.20, 0.64, 0.63, frame_id="frame_0004.jpg"),
                _frame(0.595, 0.20, 0.66, 0.65, frame_id="frame_0005.jpg"),
                _frame(0.59, 0.20, 0.64, 0.63, frame_id="frame_0006.jpg"),
                _frame(0.598, 0.20, 0.79, 0.80, frame_id="frame_0007.jpg"),
                _frame(0.60, 0.20, 0.80, 0.80, frame_id="frame_0008.jpg"),
            ]
        }
        motion_scores = _selected_metadata(
            [
                ("frame_0004", 0.499),
                ("frame_0002", 0.166),
                ("frame_0007", 0.999),
                ("frame_0001", 0.0),
                ("frame_0005", 0.665),
                ("frame_0003", 0.333),
                ("frame_0008", 1.165),
                ("frame_0006", 0.832),
            ]
        )

        profile, evidence = infer_analysis_profile(
            JUMP_ACTION_TYPE,
            JUMP_ACTION_SUBTYPE,
            pose_data,
            motion_scores,
        )

        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])
        self.assertGreaterEqual(evidence["airborne_frames_detected"], 2)

    def test_selected_gap_and_bad_records_break_continuity(self) -> None:
        pose_data = {
            "frames": [
                _frame(0.60, 0.20, 0.80, 0.80, frame_id="frame_0001.jpg"),
                _frame(0.60, 0.20, 0.80, 0.80, frame_id="frame_0002.jpg"),
                _frame(0.595, 0.20, 0.66, 0.65, frame_id="frame_0003.jpg"),
                _frame(0.59, 0.20, 0.64, 0.63, frame_id="frame_0004.jpg"),
                _frame(0.595, 0.20, 0.66, 0.65, frame_id="frame_0005.jpg"),
                _frame(0.59, 0.20, 0.64, 0.63, frame_id="frame_0006.jpg"),
                _frame(0.598, 0.20, 0.79, 0.80, frame_id="frame_0007.jpg"),
                _frame(0.60, 0.20, 0.80, 0.80, frame_id="frame_0008.jpg"),
            ]
        }
        cases = {
            "long_gap": [
                ("frame_0001", 0.0),
                ("frame_0002", 0.166),
                ("frame_0003", 0.333),
                ("frame_0004", 0.5),
                ("frame_0005", 4.0),
                ("frame_0006", 4.166),
                ("frame_0007", 4.333),
                ("frame_0008", 4.5),
            ],
            "invalid_time": [
                ("frame_0001", 0.0),
                ("frame_0002", 0.166),
                ("frame_0003", 0.333),
                ("frame_0004", 0.5),
                ("frame_0005", None),
                ("frame_0006", 0.832),
                ("frame_0007", 0.999),
                ("frame_0008", 1.165),
            ],
            "duplicate_id": [
                ("frame_0001", 0.0),
                ("frame_0002", 0.166),
                ("frame_0003", 0.333),
                ("frame_0004", 0.5),
                ("frame_0005", 0.665),
                ("frame_0005", 0.7),
                ("frame_0006", 0.832),
                ("frame_0007", 0.999),
                ("frame_0008", 1.165),
            ],
            "missing_id": [
                ("frame_0001", 0.0),
                ("frame_0002", 0.166),
                ("frame_0003", 0.333),
                ("frame_0004", 0.5),
                ("frame_0006", 0.832),
                ("frame_0007", 0.999),
                ("frame_0008", 1.165),
            ],
            "non_increasing_time": [
                ("frame_0001", 0.0),
                ("frame_0002", 0.166),
                ("frame_0003", 0.333),
                ("frame_0004", 0.5),
                ("frame_0005", 0.4),
                ("frame_0006", 0.832),
                ("frame_0007", 0.999),
                ("frame_0008", 1.165),
            ],
        }
        for name, entries in cases.items():
            with self.subTest(case=name):
                _, evidence = infer_analysis_profile(
                    JUMP_ACTION_TYPE,
                    JUMP_ACTION_SUBTYPE,
                    pose_data,
                    _selected_metadata(entries),
                )

                self.assertEqual(evidence["airborne_frames_detected"], 0)
                self.assertFalse(evidence["jump_gate_passed"])
                self.assertIn("jump_gate_not_passed", evidence["quality_flags"])



class AirborneEvidenceContinuityTests(unittest.TestCase):
    @staticmethod
    def pose(ys=(0.8, 0.65, 0.64, 0.8)):
        return {"frames": [
            _frame(0.6, 0.2, y, y, frame_id=f"frame_{i + 1:04d}.jpg")
            for i, y in enumerate(ys)
        ]}

    def test_mixed_auto_path_uses_observations_without_action_label(self):
        pose = self.pose()
        metadata = _selected_metadata([(f"frame_{i+1:04d}", i / 6) for i in range(4)])
        profile, evidence = infer_analysis_profile("自由滑", "节目片段", pose, metadata)
        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["jump_gate_passed"])
        self.assertEqual(evidence["profile_hint"], "mixed_auto")
        pose["frames"][1]["tracking_state"] = "interpolated"
        profile, evidence = infer_analysis_profile("自由滑", "节目片段", pose, metadata)
        self.assertNotEqual(profile, "jump")
        self.assertFalse(evidence["jump_gate_passed"])

    def test_empty_or_malformed_selected_does_not_fall_back_to_adjacency(self):
        from app.services.action_profiles import _detect_airborne_frames
        for selected in (None, [], {}, "invalid"):
            with self.subTest(selected=selected):
                _, evidence = infer_analysis_profile(
                    "自由滑", "节目片段", self.pose(), {"selected": selected}
                )
                self.assertEqual(evidence["airborne_frames_detected"], 0)
        self.assertEqual(_detect_airborne_frames(self.pose()), 2)

    def test_valid_segment_after_gap_can_supply_its_own_contacts(self):
        pose = self.pose()
        pose["frames"] = [{"tracking_state": "lost", "keypoints": []}] + pose["frames"]
        profile, evidence = infer_analysis_profile("自由滑", "节目片段", pose, None)
        self.assertEqual(profile, "jump")
        self.assertEqual(evidence["airborne_frames_detected"], 2)

    def test_one_raised_frame_is_not_enough(self):
        _, evidence = infer_analysis_profile("自由滑", "节目片段", self.pose((.8, .65, .8)), None)
        self.assertFalse(evidence["jump_gate_passed"])

    def test_sampling_gap_boundary_and_no_effective_fps_substitution(self):
        from app.services.action_profiles import _detect_airborne_frames
        for gap, expected in ((2 / 6 + .001, 2), (2 / 6 + .003, 0)):
            with self.subTest(gap=gap):
                meta = _selected_metadata([("frame_0001", 0), ("frame_0002", .1),
                                           ("frame_0003", .1 + gap), ("frame_0004", .2 + gap)])
                self.assertEqual(_detect_airborne_frames(self.pose(), meta), expected)
        meta = _selected_metadata([("frame_0001", 0), ("frame_0002", 1),
                                   ("frame_0003", 2), ("frame_0004", 3)], frame_rate=None)
        meta["effective_fps"] = 100
        self.assertEqual(_detect_airborne_frames(self.pose(), meta), 2)

    def test_invalid_numeric_observations_break_the_segment(self):
        from app.services.action_profiles import _detect_airborne_frames
        for field in ("y", "visibility"):
            for value in (None, "bad", float("nan"), float("inf"), True, 10 ** 400):
                with self.subTest(field=field, kind=type(value).__name__):
                    pose = self.pose()
                    for point in pose["frames"][1]["keypoints"]:
                        if point["id"] in (27, 28):
                            point[field] = value
                    self.assertEqual(_detect_airborne_frames(pose), 0)

    def test_invalid_and_duplicate_timestamps_cannot_supply_airborne_evidence(self):
        from app.services.action_profiles import _detect_airborne_frames
        for timestamp in (None, "bad", float("nan"), float("inf"), -1, True, 10 ** 400, 0):
            with self.subTest(kind=type(timestamp).__name__):
                meta = _selected_metadata([("frame_0001", 0), ("frame_0002", timestamp),
                                           ("frame_0003", .3), ("frame_0004", .5)])
                self.assertEqual(_detect_airborne_frames(self.pose(), meta), 0)

    def test_one_visible_ankle_cannot_supply_bilateral_contact_for_legacy_input(self):
        from app.services.action_profiles import _detect_airborne_frames
        pose = self.pose()
        for frame in pose["frames"]:
            frame["keypoints"] = [p for p in frame["keypoints"] if p["id"] != 28]
        self.assertEqual(_detect_airborne_frames(pose), 0)


if __name__ == "__main__":
    unittest.main()
