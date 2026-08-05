from __future__ import annotations

import ast
from pathlib import Path


def test_rotation_duration_and_sampling_use_pts_not_frame_count() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "app" / "analysis_v2" / "rotation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"fps", "frame_rate", "sampled_frame_count"}
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not forbidden.intersection(identifiers)
    assert "duration = exact[-1].pts_sec - exact[0].pts_sec" in source
    assert "current.pts_sec - prior.pts_sec" in source
