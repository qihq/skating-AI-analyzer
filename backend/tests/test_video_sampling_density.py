from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video import get_sampling_density


class VideoSamplingDensityTests(unittest.TestCase):
    def assert_density(
        self,
        profile: str | None,
        duration: float,
        expected_count: int,
        expected_cap: int,
        expected_policy: str,
        **kwargs: object,
    ) -> None:
        self.assertEqual(
            get_sampling_density(profile, duration, **kwargs),
            (expected_count, expected_cap, expected_policy),
        )

    def test_jump_uses_fixed_dense_count_and_manual_cap(self) -> None:
        self.assert_density("jump", 0.5, 48, 48, "jump_fixed_dense")
        self.assert_density("jump", 10.0, 48, 48, "jump_fixed_dense")
        self.assert_density("jump", 2.0, 64, 64, "manual_window_dense", manual_window=True)

    def test_spin_scales_after_six_seconds_and_clamps(self) -> None:
        self.assert_density("spin", 6.0, 36, 52, "duration_aware_dense")
        self.assert_density("spin", 6.1, 37, 52, "duration_aware_dense")
        self.assert_density("spin", 10.0, 52, 52, "duration_aware_dense")
        self.assert_density("spin", 10.0, 64, 64, "manual_window_dense", manual_window=True)

    def test_step_scales_after_eight_seconds_and_clamps(self) -> None:
        self.assert_density("step", 8.0, 32, 48, "duration_aware_dense")
        self.assert_density("step", 8.1, 33, 48, "duration_aware_dense")
        self.assert_density("step", 14.0, 48, 48, "duration_aware_dense")
        self.assert_density("step", 14.0, 56, 56, "manual_window_dense", manual_window=True)

    def test_spiral_scales_after_six_seconds_and_clamps(self) -> None:
        self.assert_density("spiral", 6.0, 28, 40, "duration_aware_dense")
        self.assert_density("spiral", 6.1, 29, 40, "duration_aware_dense")
        self.assert_density("spiral", 10.0, 40, 40, "duration_aware_dense")
        self.assert_density("spiral", 10.0, 48, 48, "manual_window_dense", manual_window=True)

    def test_free_skate_scales_with_minimum_and_cap(self) -> None:
        self.assert_density(None, 1.0, 32, 64, "free_skate_duration_dense", action_type="free skate")
        self.assert_density(None, 8.0, 32, 64, "free_skate_duration_dense", action_type="free skate")
        self.assert_density(None, 8.1, 33, 64, "free_skate_duration_dense", action_type="free skate")
        self.assert_density(None, 20.0, 64, 64, "free_skate_duration_dense", action_type="free skate")

    def test_unknown_profile_uses_legacy_fallback(self) -> None:
        self.assert_density("unknown", 10.0, 20, 20, "profile_fixed")


if __name__ == "__main__":
    unittest.main()
