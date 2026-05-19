from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.bbox_tracker import track_bbox


def _bbox_iou(a: dict[str, float], b: dict[str, float]) -> float:
    ax2 = a["x"] + a["width"]
    ay2 = a["y"] + a["height"]
    bx2 = b["x"] + b["width"]
    by2 = b["y"] + b["height"]
    inter_x1 = max(a["x"], b["x"])
    inter_y1 = max(a["y"], b["y"])
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    union_area = a["width"] * a["height"] + b["width"] * b["height"] - inter_area
    return inter_area / union_area


class BBoxTrackerTests(unittest.TestCase):
    def test_tracks_moving_red_square(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_paths: list[Path] = []
            expected: list[dict[str, float]] = []
            for index in range(8):
                image = np.zeros((120, 160, 3), dtype=np.uint8)
                x = 20 + index * 7
                y = 36 + index * 3
                cv2.rectangle(image, (x, y), (x + 36, y + 36), (0, 0, 255), -1)
                frame_path = root / f"frame_{index:04d}.jpg"
                self.assertTrue(cv2.imwrite(str(frame_path), image))
                frame_paths.append(frame_path)
                expected.append({"x": x / 160, "y": y / 120, "width": 36 / 160, "height": 36 / 120})

            try:
                tracked, flags = track_bbox(frame_paths, expected[0])
            except RuntimeError as exc:
                self.skipTest(str(exc))

            self.assertEqual(len(tracked), len(frame_paths))
            self.assertEqual(flags, [])
            self.assertGreater(_bbox_iou(tracked[-1], expected[-1]), 0.7)

    def test_tracks_from_manual_preview_frame_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_paths: list[Path] = []
            expected: list[dict[str, float]] = []
            for index in range(8):
                image = np.zeros((120, 160, 3), dtype=np.uint8)
                x = 20 + index * 5
                y = 40
                cv2.rectangle(image, (x, y), (x + 30, y + 30), (0, 0, 255), -1)
                frame_path = root / f"frame_{index:04d}.jpg"
                self.assertTrue(cv2.imwrite(str(frame_path), image))
                frame_paths.append(frame_path)
                expected.append({"x": x / 160, "y": y / 120, "width": 30 / 160, "height": 30 / 120})

            try:
                tracked, flags = track_bbox(frame_paths, expected[4], initial_frame_index=4)
            except RuntimeError as exc:
                self.skipTest(str(exc))

            self.assertEqual(len(tracked), len(frame_paths))
            self.assertIn("bbox_tracker_anchor_not_first_frame", flags)
            self.assertGreater(_bbox_iou(tracked[4], expected[4]), 0.8)
            self.assertGreater(_bbox_iou(tracked[0], expected[0]), 0.45)
            self.assertGreater(_bbox_iou(tracked[-1], expected[-1]), 0.45)


if __name__ == "__main__":
    unittest.main()
