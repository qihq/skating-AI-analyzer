from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.bio_context import (
    build_frame_bio_context,
    extract_key_frame_stems,
    summarize_jump_metrics,
)


class BioContextTests(unittest.TestCase):
    def test_build_frame_bio_context_maps_one_based_indices_to_stems(self) -> None:
        bio_data = {
            "knee_angles": [
                {"frame_idx": 1, "left": 145.2, "right": 152.0},
                {"frame_idx": 2, "left": None, "right": None},
            ],
            "trunk_tilts": [{"frame_idx": 1, "tilt_degrees": 8.4}],
            "arm_symmetry": [{"frame_idx": 1, "symmetry": 0.93}],
        }

        result = build_frame_bio_context(bio_data, ["frame_0001", "frame_0002"])

        self.assertEqual(
            result,
            {
                "frame_0001": {
                    "left_knee_angle": 145.2,
                    "right_knee_angle": 152.0,
                    "trunk_tilt_deg": 8.4,
                    "arm_symmetry": 0.93,
                }
            },
        )

    def test_build_frame_bio_context_omits_stem_when_all_values_are_none(self) -> None:
        bio_data = {
            "knee_angles": [{"frame_idx": 1, "left": None, "right": None}],
            "trunk_tilts": [{"frame_idx": 1, "tilt_degrees": None}],
            "arm_symmetry": [{"frame_idx": 1, "symmetry": None}],
        }

        self.assertEqual(build_frame_bio_context(bio_data, ["frame_0001"]), {})

    def test_extract_key_frame_stems_returns_jump_values(self) -> None:
        bio_data = {
            "key_frames": {
                "T": "frame_0017",
                "A": "frame_0021",
                "L": "frame_0025",
            }
        }

        self.assertEqual(
            extract_key_frame_stems(bio_data),
            {"frame_0017", "frame_0021", "frame_0025"},
        )

    def test_extract_key_frame_stems_returns_empty_for_non_jump_profiles(self) -> None:
        self.assertEqual(extract_key_frame_stems({"key_frames": {}}), set())

    def test_summarize_jump_metrics_formats_ok_metrics(self) -> None:
        bio_data = {
            "jump_metrics_status": "ok",
            "jump_metrics": {
                "air_time_seconds": 0.45,
                "estimated_height_cm": 24.84,
                "takeoff_speed_mps": 2.1,
                "rotation_rps": 1.234,
            },
        }

        self.assertEqual(
            summarize_jump_metrics(bio_data),
            "AirTime=0.45s | Height=24.8cm | VTakeoff=2.10m/s | Rot=1.23rps",
        )

    def test_summarize_jump_metrics_returns_empty_for_non_ok_or_missing_metrics(self) -> None:
        self.assertEqual(summarize_jump_metrics({"jump_metrics_status": "estimated"}), "")
        self.assertEqual(summarize_jump_metrics({"jump_metrics_status": "ok"}), "")

    def test_all_helpers_tolerate_none_input(self) -> None:
        self.assertEqual(build_frame_bio_context(None, ["frame_0001"]), {})
        self.assertEqual(extract_key_frame_stems(None), set())
        self.assertEqual(summarize_jump_metrics(None), "")


if __name__ == "__main__":
    unittest.main()
