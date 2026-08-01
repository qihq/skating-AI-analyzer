from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
V2_ROOT = ROOT / "backend" / "app" / "analysis_v2"


def test_v2_has_no_sampled_count_or_fps_only_physical_timing() -> None:
    violations: list[str] = []
    forbidden_names = {"effective_fps", "average_fps", "sampled_frame_count", "frame_count"}
    for path in V2_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
                continue
            names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            attrs = {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}
            if forbidden_names & (names | attrs):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_v2_frontend_does_not_reconstruct_pts_from_fps() -> None:
    files = [ROOT / "frontend" / "src" / "analysis-v2", ROOT / "frontend" / "src" / "media", ROOT / "frontend" / "src" / "components" / "ModernAnalysisWorkspace.tsx"]
    violations: list[str] = []
    for entry in files:
        paths = entry.rglob("*.ts*") if entry.is_dir() else [entry]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            if "index / Math.max(pose.effective_fps" in text or "source_frame_count / source.duration_pts" in text:
                violations.append(str(path.relative_to(ROOT)))
    assert violations == []
