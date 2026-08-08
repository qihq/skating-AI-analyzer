from pathlib import Path

import pytest

from app.analysis_v2.dependency_boundary import (
    FORBIDDEN_LEGACY_FIELDS,
    audit_migrated_modules,
)


def test_migrated_module_rejects_direct_raw_legacy_field_reads(tmp_path: Path) -> None:
    module = tmp_path / "service.py"
    module.write_text("def build(analysis):\n    return analysis.bio_data\n", encoding="utf-8")

    violations = audit_migrated_modules((module,))

    assert violations == ((str(module), "bio_data"),)


def test_migrated_module_rejects_mapping_and_get_reads(tmp_path: Path) -> None:
    module = tmp_path / "service.py"
    module.write_text(
        "def build(record):\n    return record['pose_data'], record.get('report')\n",
        encoding="utf-8",
    )

    violations = audit_migrated_modules((module,))

    assert violations == ((str(module), "pose_data"),)


def test_legacy_adapter_exception_is_bounded_to_explicit_allowlist(tmp_path: Path) -> None:
    adapter = tmp_path / "legacy_prediction_adapter.py"
    adapter.write_text("def adapt(record):\n    return record.get('bio_data')\n", encoding="utf-8")

    assert audit_migrated_modules((adapter,), exceptions=(adapter,)) == ()
    with pytest.raises(ValueError, match="legacy adapter exception"):
        audit_migrated_modules((adapter,), exceptions=(tmp_path / "other.py",))


def test_analysis_v2_boundary_has_no_unallowlisted_raw_reads() -> None:
    root = Path(__file__).resolve().parents[2] / "app" / "analysis_v2"
    modules = tuple(root.rglob("*.py"))
    exceptions = tuple(
        path
        for path in modules
        if path.name in {"presentation.py", "legacy_prediction_adapter.py", "legacy_event_proposal_adapter.py", "pilot12_event_proposals.py"}
    )

    assert FORBIDDEN_LEGACY_FIELDS
    assert audit_migrated_modules(modules, exceptions=exceptions) == ()


def test_iteration_14_downstream_services_have_no_unallowlisted_raw_reads() -> None:
    services = Path(__file__).resolve().parents[2] / "app" / "services"
    modules = tuple(services.glob("*.py"))
    # The correction service adapts historical records as a whole and the
    # prompt-context renderer remains a bounded legacy pipeline utility.  V2
    # callers branch before either raw adapter is used; every other semantic
    # service must consume AnalysisFactsV2/family-safe projections only.
    exceptions = (
        services / "analysis_corrections.py",
        services / "llm_context.py",
    )

    assert audit_migrated_modules(modules, exceptions=exceptions) == ()
