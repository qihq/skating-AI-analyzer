from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.frame_annotator import annotate_frames_batch, build_pose_by_stem


class FrameAnnotatorTests(unittest.TestCase):
    def test_build_pose_by_stem_strips_suffix(self) -> None:
        pose_data = {
            "frames": [
                {"frame": "frame_0001.jpg", "keypoints": []},
                {"frame": "nested/frame_0002.jpg", "keypoints": [{"id": 0}]},
            ]
        }

        result = build_pose_by_stem(pose_data)

        self.assertEqual(set(result), {"frame_0001", "frame_0002"})
        self.assertEqual(result["frame_0002"]["keypoints"], [{"id": 0}])

    def test_missing_pose_or_lost_keypoints_copy_source_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "frames" / "frame_0001.jpg"
            src.parent.mkdir()
            image = np.full((24, 24, 3), 255, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(src), image))

            out = annotate_frames_batch([src], {"frame_0001": {"keypoints": []}}, root / "annotated")

            self.assertEqual(len(out), 1)
            self.assertTrue(out[0].exists())
            self.assertEqual(out[0].read_bytes(), src.read_bytes())


if __name__ == "__main__":
    unittest.main()
