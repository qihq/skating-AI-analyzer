from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANALYSIS_V2_ROOT = ROOT / "frontend" / "src" / "analysis-v2"
FORBIDDEN_RAW_SOURCES = ("bio_data", "vision_path_a", "vision_path_b", "pose_data")


def test_iteration_zero_frontend_boundary_does_not_read_raw_analysis_sources() -> None:
    production_files = [
        path
        for path in ANALYSIS_V2_ROOT.rglob("*")
        if path.suffix in {".ts", ".tsx"} and ".test." not in path.name
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in production_files)

    for forbidden in FORBIDDEN_RAW_SOURCES:
        assert forbidden not in source


def test_golden_v2_transport_does_not_reuse_legacy_debug_contracts() -> None:
    golden_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in ANALYSIS_V2_ROOT.rglob("*golden*")
        if path.suffix in {".ts", ".tsx"} and ".test." not in path.name
    )

    for forbidden in ("DebugGoldenLabel", "golden_label", "video_path", "prediction_path"):
        assert forbidden not in golden_sources
