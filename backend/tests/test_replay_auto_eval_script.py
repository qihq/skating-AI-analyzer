from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ReplayAutoEvalScriptTests(unittest.TestCase):
    def test_script_outputs_degraded_samples_and_metrics(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        script_path = project_root / "scripts" / "replay-auto-eval.py"

        snapshots = {
            "snapshots": [
                {
                    "analysis_id": "a-001",
                    "created_at": "2026-05-01T10:00:00+00:00",
                    "pipeline_version": "v1",
                    "analysis_profile": "jump",
                    "action_type": "跳跃",
                    "auto_eval": {
                        "key_frame_order_valid": True,
                        "phase_sequence_valid": True,
                        "high_confidence_conflicts": [],
                    },
                    "key_frame_candidates": {"T": {"frame_id": "frame_0001"}},
                    "fusion_diagnostics": ["conflict_level=low"],
                },
                {
                    "analysis_id": "a-002",
                    "created_at": "2026-05-01T11:00:00+00:00",
                    "pipeline_version": "v1",
                    "analysis_profile": "jump",
                    "action_type": "跳跃",
                    "auto_eval": {
                        "key_frame_order_valid": True,
                        "phase_sequence_valid": False,
                        "high_confidence_conflicts": [{"frame_id": "frame_0004"}],
                    },
                    "key_frame_candidates": {"T": {"frame_id": "frame_0002"}},
                    "fusion_diagnostics": ["conflict_level=high"],
                },
                {
                    "analysis_id": "a-001",
                    "created_at": "2026-05-02T10:00:00+00:00",
                    "pipeline_version": "v2",
                    "analysis_profile": "jump",
                    "action_type": "跳跃",
                    "auto_eval": {
                        "key_frame_order_valid": False,
                        "phase_sequence_valid": True,
                        "high_confidence_conflicts": [{"frame_id": "frame_0001"}],
                    },
                    "key_frame_candidates": {"T": {"frame_id": "frame_0001"}},
                    "fusion_diagnostics": ["conflict_level=high", "needs_human_review=True"],
                },
                {
                    "analysis_id": "a-002",
                    "created_at": "2026-05-02T11:00:00+00:00",
                    "pipeline_version": "v2",
                    "analysis_profile": "jump",
                    "action_type": "跳跃",
                    "auto_eval": {
                        "key_frame_order_valid": False,
                        "phase_sequence_valid": False,
                        "high_confidence_conflicts": [{"frame_id": "frame_0005"}],
                    },
                    "key_frame_candidates": {"T": {"frame_id": "frame_0002"}},
                    "fusion_diagnostics": ["conflict_level=high", "needs_human_review=True"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "snapshots.json"
            snapshot_path.write_text(json.dumps(snapshots, ensure_ascii=False), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(script_path), str(snapshot_path)],
                check=True,
                capture_output=True,
                text=True,
                cwd=project_root,
            )

            report = json.loads(completed.stdout)
            self.assertEqual(report["baseline_version"], "v1")
            self.assertEqual(report["candidate_version"], "v2")
            self.assertLess(report["accuracy_proxy_delta"], 0)
            self.assertEqual(report["degraded_sample_ids"], ["a-001", "a-002"])
            self.assertGreater(report["high_confidence_conflict_rate_delta"], 0)

            markdown = subprocess.run(
                [sys.executable, str(script_path), str(snapshot_path), "--format", "markdown"],
                check=True,
                capture_output=True,
                text=True,
                cwd=project_root,
            )
            self.assertIn("Auto Eval Replay", markdown.stdout)
            self.assertIn("a-001", markdown.stdout)
            self.assertIn("a-002", markdown.stdout)


if __name__ == "__main__":
    unittest.main()
