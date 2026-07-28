from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.evidence_frames import EVIDENCE_SCHEMA_VERSION, build_evidence_frames, materialize_supplemental_evidence_frames
from app.services.semantic_keyframe_pipeline import merge_frame_motion_payload


class EvidenceFrameTests(unittest.IsolatedAsyncioTestCase):
    def test_conflicting_mimo_and_pose_tal_groups_are_both_retained(self) -> None:
        motion_scores = {
            "window_start": 4.0,
            "window_end": 10.0,
            "selected": [{"frame_id": "frame_0001", "timestamp": 4.0, "motion_score": 0.1}],
        }
        mimo = {
            "confidence": 0.82,
            "phase_segments": [
                {"phase_code": "takeoff", "key_frame_hint": 5.0, "confidence": 0.8},
                {"phase_code": "air", "key_frame_hint": 5.3, "confidence": 0.8},
                {"phase_code": "landing", "key_frame_hint": 5.7, "confidence": 0.8},
            ],
            "key_moments": {"T_takeoff_sec": 5.0, "A_air_sec": 5.3, "L_landing_sec": 5.7},
        }
        bio_data = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0020", "timestamp": 6.2, "confidence": 0.75},
                "A": {"frame_id": "frame_0024", "timestamp": 6.5, "confidence": 0.74},
                "L": {"frame_id": "frame_0028", "timestamp": 6.9, "confidence": 0.73},
            }
        }

        payload = build_evidence_frames(
            motion_scores,
            video_temporal=mimo,
            resolved_keyframes=None,
            bio_data=bio_data,
            analysis_profile="jump",
            source_fps=30.0,
        )

        records = payload["records"]
        self.assertEqual(payload["schema_version"], EVIDENCE_SCHEMA_VERSION)
        self.assertTrue(any(item["source"] == "mimo_key_moment" and item["timestamp"] == 5.0 for item in records))
        self.assertTrue(any(item["source"] == "pose_candidate" and item["timestamp"] == 6.2 for item in records))
        self.assertTrue(payload["diagnostics"]["required_stage_completeness"])
        self.assertTrue(payload["diagnostics"]["tal_ordered"])
        self.assertGreaterEqual(payload["diagnostics"]["source_diversity"], 3)

    def test_missing_stage_is_marked_insufficient_when_no_stage_window_exists(self) -> None:
        payload = build_evidence_frames(
            {"window_start": 0.0, "window_end": 4.0, "selected": []},
            video_temporal={"phase_segments": [{"phase_code": "takeoff", "key_frame_hint": 1.0}]},
            resolved_keyframes=None,
            bio_data=None,
            analysis_profile="jump",
            source_fps=20.0,
        )

        self.assertTrue(payload["diagnostics"]["stage_evidence_insufficient"])
        self.assertFalse(payload["diagnostics"]["supplemental_retry_requested"])
        self.assertFalse(any(item["source"] == "coverage_retry" for item in payload["records"]))

    def test_motion_payload_persists_versioned_evidence(self) -> None:
        merged = merge_frame_motion_payload(
            {"window_start": 0.0, "window_end": 2.0, "selected": []},
            video_temporal={"phase_segments": []},
            resolved_keyframes={"selected": []},
            bio_data={},
            analysis_profile="jump",
            source_fps=30.0,
        )

        self.assertEqual(merged["evidence_frames_v1"]["schema_version"], EVIDENCE_SCHEMA_VERSION)

    async def test_materialization_deduplicates_base_and_nearby_evidence_timestamps(self) -> None:
        payload = {
            "records": [
                {"timestamp": 1.0, "source": "motion_sample"},
                {"timestamp": 1.01, "source": "mimo_key_moment", "phase": "takeoff"},
                {"timestamp": 2.0, "source": "pose_candidate", "phase": "air"},
                {"timestamp": 2.01, "source": "mimo_key_moment", "phase": "air"},
            ]
        }
        extracted = [{"frame_id": "evidence_0001", "timestamp": 2.0}]
        with patch(
            "app.services.evidence_frames.extract_precise_frames_at_timestamps",
            AsyncMock(return_value=([Path("evidence_0001.jpg")], extracted)),
        ) as extract_mock:
            records = await materialize_supplemental_evidence_frames(
                Path("source.mp4"),
                Path("semantic_frames"),
                payload,
                base_records=[{"timestamp": 1.0}],
                source_fps=30.0,
            )

        self.assertEqual(records, extracted)
        self.assertEqual(extract_mock.await_args.args[2][0]["timestamp"], 2.0)
        self.assertEqual(payload["supplemental_frames"], extracted)


if __name__ == "__main__":
    unittest.main()
