"""Tests for backend/scripts/diff_baselines.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "backend" / "scripts" / "diff_baselines.py"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class DiffBaselinesTests(unittest.TestCase):
    def test_diff_reports_metric_deltas_direction_and_failures(self) -> None:
        baseline = {
            "summary": {
                "sample_count": 4,
                "keyframe_mean_error_sec": 0.42,
                "keyframe_median_error_sec": 0.30,
                "keyframe_max_error_sec": 0.90,
                "identity_accuracy": 0.71,
                "identity_switches": 5,
                "failure_count": 3,
            },
            "stratum_summary": {
                "multi_skater": {
                    "sample_count": 2,
                    "keyframe_mean_error_sec": 0.64,
                    "keyframe_median_error_sec": 0.55,
                    "keyframe_max_error_sec": 1.20,
                    "identity_accuracy": 0.47,
                    "identity_switches": 5,
                    "failure_count": 3,
                },
            },
            "failures": [
                {"sample_id": "vid_03", "failure_reasons": ["identity_switch", "identity_accuracy_low"]},
                {"sample_id": "vid_07", "failure_reasons": ["keyframe_error_high"]},
            ],
            "top_quality_flags": [
                {"flag": "person_tracker_appearance_relock_rejected", "count": 3},
                {"flag": "keyframe_candidates_low_visibility", "count": 2},
            ],
        }
        newer = {
            "summary": {
                "sample_count": 4,
                "keyframe_mean_error_sec": 0.18,
                "keyframe_median_error_sec": 0.12,
                "keyframe_max_error_sec": 0.40,
                "identity_accuracy": 0.93,
                "identity_switches": 1,
                "failure_count": 1,
            },
            "stratum_summary": {
                "multi_skater": {
                    "sample_count": 2,
                    "keyframe_mean_error_sec": 0.16,
                    "keyframe_median_error_sec": 0.14,
                    "keyframe_max_error_sec": 0.40,
                    "identity_accuracy": 0.91,
                    "identity_switches": 1,
                    "failure_count": 1,
                },
            },
            "failures": [
                {"sample_id": "vid_07", "failure_reasons": ["keyframe_error_high"]},
            ],
            "top_quality_flags": [
                {"flag": "person_tracker_appearance_relock_used", "count": 4},
                {"flag": "keyframe_candidates_low_visibility", "count": 2},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            base_path = Path(tmp) / "baseline.json"
            new_path = Path(tmp) / "new.json"
            _write_json(base_path, baseline)
            _write_json(new_path, newer)
            result = subprocess.run(
                [sys.executable, str(_SCRIPT), base_path, new_path],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = result.stdout
        # Direction tags computed from lower-is-better / higher-is-better rules.
        self.assertIn("-57.1%  good", out)  # keyframe_mean_error_sec improved
        self.assertIn("+31.0%  good", out)  # identity_accuracy improved
        self.assertIn("-80.0%  good", out)  # identity_switches improved
        # Stratum section present.
        self.assertIn("Stratum: multi_skater", out)
        # Resolved / introduced failures.
        self.assertIn("Resolved failures", out)
        self.assertIn("+ vid_03", out)
        self.assertNotIn("Introduced failures", out)  # none introduced
        # Quality flag count changes.
        self.assertIn("person_tracker_appearance_relock_rejected", out)
        self.assertIn("person_tracker_appearance_relock_used", out)

    def test_diff_handles_missing_summary_keys_gracefully(self) -> None:
        baseline = {"summary": {"sample_count": 2}, "stratum_summary": {}, "failures": [], "top_quality_flags": []}
        newer = {"summary": {"sample_count": 2, "keyframe_mean_error_sec": 0.1}, "stratum_summary": {}, "failures": [], "top_quality_flags": []}
        with tempfile.TemporaryDirectory() as tmp:
            base_path = Path(tmp) / "baseline.json"
            new_path = Path(tmp) / "new.json"
            _write_json(base_path, baseline)
            _write_json(new_path, newer)
            result = subprocess.run(
                [sys.executable, str(_SCRIPT), base_path, new_path],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("keyframe_mean_error_sec", result.stdout)


if __name__ == "__main__":
    unittest.main()