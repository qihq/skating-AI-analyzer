from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routers.analysis import _build_dual_path_log_detail


class DualPathProviderLogTests(unittest.TestCase):
    def test_dual_path_log_uses_resolved_model_id(self) -> None:
        detail = _build_dual_path_log_detail(
            path_a={"path": "A", "vision_mode": "video", "frame_analysis": [], "path_desc": "Path A"},
            path_b={"path": "B", "n_frames": 10, "subscores": {}},
            dual_path_meta={"recommended_path": "blend", "weight_a": 0.25, "weight_b": 0.75},
            provider_path_a=SimpleNamespace(provider="qwen", model_id="qwen3-omni-flash", vision_model=None),
            provider_path_b=SimpleNamespace(provider="qwen", model_id="qwen3.6-plus", vision_model=None),
            raw_frame_count=32,
            annotated_frame_count=10,
            annotated_dir=Path("/tmp/annotated"),
            clip_path=Path("/tmp/action_window.mp4"),
            used_key_frames={"frame_0001"},
        )

        payload = json.loads(detail)

        self.assertEqual(payload["path_a"]["provider"], "qwen/qwen3-omni-flash")
        self.assertEqual(payload["path_b"]["provider"], "qwen/qwen3.6-plus")
        self.assertIsNone(payload["path_a"]["provider_fallback"])
        self.assertIsNone(payload["path_b"]["provider_fallback"])

    def test_dual_path_log_marks_provider_slot_fallback(self) -> None:
        detail = _build_dual_path_log_detail(
            path_a={"path": "A", "vision_mode": "frames", "frame_analysis": []},
            path_b={"path": "B", "n_frames": 10, "subscores": {}},
            dual_path_meta={},
            provider_path_a=SimpleNamespace(
                provider="qwen",
                model_id="qwen3.6-plus",
                vision_model=None,
                notes="fallback_from=vision_path_a; fallback_slot=vision",
            ),
            provider_path_b=SimpleNamespace(
                provider="qwen",
                model_id="qwen3.6-plus",
                vision_model=None,
                notes="fallback_from=vision_path_b; fallback_slot=vision",
            ),
            raw_frame_count=32,
            annotated_frame_count=10,
            annotated_dir=Path("/tmp/annotated"),
            clip_path=None,
            used_key_frames=set(),
        )

        payload = json.loads(detail)

        self.assertIn("fallback_from=vision_path_a", payload["path_a"]["provider_fallback"])
        self.assertIn("fallback_from=vision_path_b", payload["path_b"]["provider_fallback"])


if __name__ == "__main__":
    unittest.main()
