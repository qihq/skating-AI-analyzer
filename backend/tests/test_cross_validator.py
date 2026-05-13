from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.cross_validator import compute_blend_weights, cross_validate


def _path_a(**subscores: int) -> dict:
    return {
        "action_phase_summary": {"detected_phases": ["takeoff", "air", "landing"]},
        "pure_vision_subscores": {
            "takeoff_power": 80,
            "rotation_axis": 80,
            "arm_coordination": 80,
            "landing_absorption": 80,
            "core_stability": 80,
            **subscores,
        },
    }


def _path_b(**subscores: int) -> dict:
    return {
        "action_phase_summary": {"detected_phases": ["takeoff", "air", "landing"]},
        "subscores": {
            "takeoff_power": 80,
            "rotation_axis": 80,
            "arm_coordination": 80,
            "landing_absorption": 80,
            "core_stability": 80,
            **subscores,
        },
    }


class CrossValidatorTests(unittest.TestCase):
    def assertWeightsSumToOne(self, weights: tuple[float, float]) -> None:
        self.assertAlmostEqual(sum(weights), 1.0, delta=0.001)

    def test_subscore_diff_within_objective_agree_threshold_is_reliable_blend(self) -> None:
        report = cross_validate(_path_a(), _path_b(rotation_axis=74, core_stability=86))

        self.assertEqual(report.skeleton_reliability_signal, "reliable")
        self.assertEqual(report.recommended_path, "blend")
        self.assertNotIn("rotation_axis", report.conflict_fields)
        self.assertNotIn("core_stability", report.conflict_fields)
        self.assertWeightsSumToOne(compute_blend_weights(report))

    def test_two_objective_major_conflicts_mark_likely_wrong_and_path_a(self) -> None:
        report = cross_validate(_path_a(), _path_b(rotation_axis=60, core_stability=60))

        self.assertEqual(report.skeleton_reliability_signal, "likely_wrong")
        self.assertEqual(report.recommended_path, "A")
        self.assertEqual(compute_blend_weights(report), (1.0, 0.0))
        self.assertWeightsSumToOne(compute_blend_weights(report))

    def test_only_subjective_major_conflicts_are_uncertain(self) -> None:
        report = cross_validate(
            _path_a(),
            _path_b(takeoff_power=50, arm_coordination=50, landing_absorption=50),
        )

        self.assertEqual(report.skeleton_reliability_signal, "uncertain")
        self.assertEqual(report.recommended_path, "blend")
        self.assertEqual(
            set(report.conflict_fields),
            {"takeoff_power", "arm_coordination", "landing_absorption"},
        )
        self.assertWeightsSumToOne(compute_blend_weights(report))

    def test_missing_path_a_recommends_path_b(self) -> None:
        report = cross_validate(None, _path_b())

        self.assertEqual(report.recommended_path, "B")
        self.assertEqual(compute_blend_weights(report), (0.0, 1.0))
        self.assertWeightsSumToOne(compute_blend_weights(report))

    def test_both_paths_missing_recommends_neither(self) -> None:
        report = cross_validate(None, None)

        self.assertEqual(report.recommended_path, "neither")
        self.assertEqual(compute_blend_weights(report), (0.5, 0.5))
        self.assertWeightsSumToOne(compute_blend_weights(report))

    def test_to_dict_is_json_serializable(self) -> None:
        report = cross_validate(_path_a(), _path_b(rotation_axis=74))

        encoded = json.dumps(report.to_dict(), ensure_ascii=False)

        self.assertIn("field_validations", encoded)
        self.assertIn("rotation_axis", encoded)


if __name__ == "__main__":
    unittest.main()
