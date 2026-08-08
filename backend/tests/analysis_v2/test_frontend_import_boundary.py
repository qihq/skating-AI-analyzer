from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANALYSIS_V2_ROOT = ROOT / "frontend" / "src" / "analysis-v2"
FORBIDDEN_RAW_SOURCES = ("bio_data", "vision_path_a", "vision_path_b", "pose_data")

# These are the ordinary family routes/components migrated in Iteration 14.
# Parent diagnostics and explicit legacy adapters are intentionally excluded
# below; they may inspect a whole legacy record, but must never be imported by
# these surfaces as a field-level fallback.
ORDINARY_FRONTEND_FILES = (
    "pages/AnalysisChatPage.tsx",
    "pages/ArchivePage.tsx",
    "pages/ComparePage.tsx",
    "pages/GrowthHomePage.tsx",
    "pages/HistoryPage.tsx",
    "pages/ProgressPage.tsx",
    "pages/PlanPage.tsx",
    "modern/ModernAnalysisDetail.tsx",
    "modern/GrowthCompareHub.tsx",
    "modern/GrowthPlanHub.tsx",
    "modern/ModernTodayIsland.tsx",
    "analysis-v2/components/AnalysisExperienceReport.tsx",
    "analysis-v2/components/AnalysisExperienceSummary.tsx",
    "analysis-v2/components/AnalysisExperienceBody.tsx",
    "analysis-v2/components/AnalysisExperienceMore.tsx",
)


def _ordinary_frontend_sources() -> tuple[Path, ...]:
    root = ROOT / "frontend" / "src"
    return tuple(root / relative for relative in ORDINARY_FRONTEND_FILES)


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


def test_iteration_14_ordinary_frontend_routes_have_no_raw_path_or_pose_reads() -> None:
    missing = [str(path.relative_to(ROOT)) for path in _ordinary_frontend_sources() if not path.exists()]
    assert missing == []

    violations: list[str] = []
    for path in _ordinary_frontend_sources():
        if ".test." in path.name:
            continue
        source = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_RAW_SOURCES:
            if forbidden in source:
                violations.append(f"{path.relative_to(ROOT)}:{forbidden}")

    assert violations == []


def test_iteration_14_ordinary_frontend_routes_use_authority_presenter_or_experience_loader() -> None:
    violations: list[str] = []
    for path in _ordinary_frontend_sources():
        source = path.read_text(encoding="utf-8")
        # Artifact pages such as the training-plan reader do not render an
        # analysis experience directly; they are safe when they consume the
        # backend-owned provenance envelope (authority/hash) instead.
        if (
            "presentAnalysisExperience" not in source
            and "useAnalysisExperiences" not in source
            and "AnalysisExperience" not in source
            and not ({"source_fact_hash", "facts_authority"} <= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", source)))
        ):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []
