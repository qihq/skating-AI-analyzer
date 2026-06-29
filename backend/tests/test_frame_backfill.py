from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Analysis
from app.routers.analysis import _frame_timestamp_map_for_backfill


class FrameBackfillTests(unittest.TestCase):
    def test_frame_timestamp_map_includes_sampled_semantic_partial_and_bio_frames(self) -> None:
        analysis = Analysis(
            id="analysis-frames",
            action_type="jump",
            video_path="/tmp/source.mp4",
            frame_motion_scores={
                "selected": [{"frame_id": "frame_0001", "timestamp": 1.0}],
                "resolved_keyframes": {
                    "selected": [{"frame_id": "semantic_0001", "timestamp": 2.0}],
                    "partial_selected": [{"frame_id": "partial_semantic_0003", "timestamp": 3.0}],
                },
            },
            bio_data={
                "key_frames": {"L": "semantic_0004"},
                "key_frame_timestamps": {"L": 4.0},
                "key_frame_candidates": {"T": {"frame_id": "frame_0005", "timestamp": 5.0}},
            },
        )

        mapping = _frame_timestamp_map_for_backfill(analysis)

        self.assertEqual(mapping["frame_0001"], 1.0)
        self.assertEqual(mapping["semantic_0001"], 2.0)
        self.assertEqual(mapping["partial_semantic_0003"], 3.0)
        self.assertEqual(mapping["semantic_0004"], 4.0)
        self.assertEqual(mapping["frame_0005"], 5.0)


if __name__ == "__main__":
    unittest.main()
