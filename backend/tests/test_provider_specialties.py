from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.provider_specialties import (
    CONSERVATIVE_DEFAULT_SPECIALTY,
    SPECIALTY_WEIGHT_KEYS,
    load_provider_specialty,
)


class ProviderSpecialtiesTests(unittest.TestCase):
    def test_configured_providers_can_be_loaded(self) -> None:
        for provider_name in ("qwen", "doubao", "deepseek", "minimax"):
            with self.subTest(provider_name=provider_name):
                specialty = load_provider_specialty(provider_name)

                self.assertEqual(set(specialty), set(SPECIALTY_WEIGHT_KEYS))
                self.assertNotEqual(specialty, CONSERVATIVE_DEFAULT_SPECIALTY)
                self.assertTrue(all(0.0 <= weight <= 1.0 for weight in specialty.values()))

    def test_provider_lookup_is_case_and_space_insensitive(self) -> None:
        self.assertEqual(load_provider_specialty(" QWEN "), load_provider_specialty("qwen"))

    def test_unconfigured_provider_returns_conservative_defaults(self) -> None:
        self.assertEqual(load_provider_specialty("unknown-provider"), CONSERVATIVE_DEFAULT_SPECIALTY)

    def test_missing_config_does_not_raise(self) -> None:
        with patch("app.services.provider_specialties.PROVIDER_SPECIALTIES_CONFIG_PATH") as config_path:
            config_path.exists.return_value = False

            self.assertEqual(load_provider_specialty("qwen"), CONSERVATIVE_DEFAULT_SPECIALTY)

    def test_incomplete_provider_config_merges_with_defaults(self) -> None:
        fake_config = {
            "defaults": {
                "frame_phase_weight": 0.4,
                "video_temporal_weight": 0.4,
                "jump_subtype_weight": 0.4,
                "blade_edge_weight": 0.4,
                "child_motion_weight": 0.4,
                "json_reliability_weight": 0.4,
            },
            "providers": {
                "partial": {
                    "frame_phase_weight": 0.9,
                    "video_temporal_weight": "invalid",
                    "json_reliability_weight": 1.2,
                }
            },
        }

        with patch("app.services.provider_specialties._load_config", return_value=fake_config):
            specialty = load_provider_specialty("partial")

        self.assertEqual(specialty["frame_phase_weight"], 0.9)
        self.assertEqual(specialty["video_temporal_weight"], 0.4)
        self.assertEqual(specialty["jump_subtype_weight"], 0.4)
        self.assertEqual(specialty["json_reliability_weight"], 1.0)


if __name__ == "__main__":
    unittest.main()
