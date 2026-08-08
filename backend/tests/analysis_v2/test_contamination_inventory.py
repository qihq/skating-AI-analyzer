from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.analysis_v2.contamination_inventory import (
    FAMILY_CONTAMINATION_DOMAINS,
    FAMILY_DOMAIN_SPECS,
    ISOLATED_SHADOW_RELATIVE_DIRS,
    ISOLATED_SHADOW_TABLES,
    FamilyContaminationError,
    FileSnapshotTarget,
    MappingSnapshotProvider,
    SQLAlchemySnapshotProvider,
    assert_family_inventory_unchanged,
    capture_family_inventory,
    compare_family_inventories,
    validate_shadow_path_exclusions,
    validate_shadow_table_exclusions,
)
from app.database import Base
from app.models import Analysis, AnalysisChatMessage


EXPECTED_DOMAINS = (
    "chat_corrections",
    "plans_sessions",
    "growth_compare",
    "skills_xp",
    "memories",
    "chapters_annual",
    "shares_exports_notifications",
    "settings_providers",
    "published_completed_artifacts",
    "backup_inventory",
)


def _complete_provider() -> MappingSnapshotProvider:
    tables: dict[str, object] = {}
    logical: dict[str, object] = {}
    files: dict[str, object] = {}
    for spec in FAMILY_DOMAIN_SPECS.values():
        tables.update({name: [{"id": f"{name}-1", "stable": True}] for name in spec.tables})
        logical.update({name: {"stable": True, "name": name} for name in spec.logical})
        files.update({name: [{"path": f"{name}.bin", "sha256": "a" * 64}] for name in spec.files})
    return MappingSnapshotProvider(tables=tables, logical=logical, files=files)


def test_inventory_coverage_contract_is_complete_and_shadow_only_exclusions_are_exact() -> None:
    assert FAMILY_CONTAMINATION_DOMAINS == EXPECTED_DOMAINS
    assert tuple(FAMILY_DOMAIN_SPECS) == EXPECTED_DOMAINS
    assert all(spec.tables or spec.logical or spec.files for spec in FAMILY_DOMAIN_SPECS.values())
    assert not any(set(spec.tables) & ISOLATED_SHADOW_TABLES for spec in FAMILY_DOMAIN_SPECS.values())

    assert validate_shadow_table_exclusions(tuple(ISOLATED_SHADOW_TABLES)) == tuple(sorted(ISOLATED_SHADOW_TABLES))
    assert validate_shadow_path_exclusions(ISOLATED_SHADOW_RELATIVE_DIRS) == tuple(sorted(ISOLATED_SHADOW_RELATIVE_DIRS))
    with pytest.raises(ValueError, match="only isolated Shadow tables"):
        validate_shadow_table_exclusions(("analyses",))
    with pytest.raises(ValueError, match="only isolated Shadow directories"):
        validate_shadow_path_exclusions(("uploads",))


def test_every_family_domain_is_hashed_and_any_domain_change_is_located() -> None:
    async def scenario() -> None:
        provider = _complete_provider()
        baseline = await capture_family_inventory(provider)
        repeated = await capture_family_inventory(provider)
        assert baseline.overall_hash == repeated.overall_hash
        assert tuple(baseline.family_hashes) == EXPECTED_DOMAINS
        assert all(value.startswith("sha256:") for value in baseline.family_hashes.values())

        for domain in EXPECTED_DOMAINS:
            spec = FAMILY_DOMAIN_SPECS[domain]
            logical_name = spec.logical[0]
            changed_logical = dict(provider.logical)
            changed_logical[logical_name] = {"stable": False, "domain": domain}
            changed = await capture_family_inventory(
                MappingSnapshotProvider(tables=provider.tables, logical=changed_logical, files=provider.files)
            )
            comparison = compare_family_inventories(baseline, changed)
            assert domain in comparison.changed_domains
            assert f"logical:{logical_name}" in comparison.changed_components[domain]

    asyncio.run(scenario())


def test_shadow_only_file_writes_are_excluded_but_family_bytes_are_not(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / "copied-runtime"
        family = root / "family" / "published-report.json"
        family.parent.mkdir(parents=True)
        family.write_bytes(b'{"authority":"legacy","status":"completed"}')
        target = FileSnapshotTarget(root, excluded_relative_dirs=ISOLATED_SHADOW_RELATIVE_DIRS)
        provider = MappingSnapshotProvider(files={"published_completed_artifacts": target})
        before = await capture_family_inventory(provider)

        run_artifact = root / "shadow" / "v2" / "runs" / "run-1" / "artifacts" / "claims.json"
        run_artifact.parent.mkdir(parents=True)
        run_artifact.write_bytes(b'{"authority":"v2","diagnostic_only":true}')
        audit = root / "shadow" / "v2" / "audits" / "run-1.jsonl"
        audit.parent.mkdir(parents=True)
        audit.write_text('{"kind":"shadow_run"}\n', encoding="utf-8")

        after_shadow_write = await capture_family_inventory(provider)
        assert assert_family_inventory_unchanged(before, after_shadow_write).unchanged

        family.write_bytes(b'{"authority":"v2","status":"completed"}')
        after_family_write = await capture_family_inventory(provider)
        comparison = compare_family_inventories(before, after_family_write)
        assert comparison.unchanged is False
        assert comparison.changed_domains == ("published_completed_artifacts",)
        assert comparison.changed_components["published_completed_artifacts"] == (
            "file:published_completed_artifacts",
        )
        with pytest.raises(FamilyContaminationError, match="published_completed_artifacts"):
            assert_family_inventory_unchanged(before, after_family_write)

    asyncio.run(scenario())


def test_injected_test_database_snapshot_detects_family_row_mutation(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        copied_root = tmp_path / "copied-runtime"
        copied_root.mkdir()
        family_file = copied_root / "legacy-result.json"
        family_file.write_text('{"status":"completed"}', encoding="utf-8")
        file_targets = {
            file_name: FileSnapshotTarget(copied_root, excluded_relative_dirs=ISOLATED_SHADOW_RELATIVE_DIRS)
            for spec in FAMILY_DOMAIN_SPECS.values()
            for file_name in spec.files
        }

        try:
            async with session_factory() as session:
                session.add(
                    Analysis(
                        id="analysis-1",
                        action_type="jump",
                        video_path="copied/source.mp4",
                        status="completed",
                        report={"summary": "legacy remains authoritative"},
                    )
                )
                await session.commit()
                provider = SQLAlchemySnapshotProvider(session, files=file_targets)
                before = await capture_family_inventory(provider)

                shadow_artifact = copied_root / "shadow" / "v2" / "runs" / "run-1" / "artifacts" / "timebase.json"
                shadow_artifact.parent.mkdir(parents=True)
                shadow_artifact.write_text('{"diagnostic_only":true}', encoding="utf-8")
                after_shadow_write = await capture_family_inventory(provider)
                assert assert_family_inventory_unchanged(before, after_shadow_write).unchanged

                session.add(
                    AnalysisChatMessage(
                        id="chat-1",
                        analysis_id="analysis-1",
                        role="assistant",
                        content="unexpected family-side write",
                    )
                )
                await session.commit()
                after_family_write = await capture_family_inventory(provider)
                comparison = compare_family_inventories(before, after_family_write)
                assert comparison.changed_domains == ("chat_corrections",)
                assert comparison.changed_components["chat_corrections"] == (
                    "table:analysis_chat_messages",
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _legacy_async_tests_removed() -> None:
    """Keep the test body below out of collection; scenario wrappers above run it."""
    return None


async def _old_test_every_family_domain_is_hashed_and_any_domain_change_is_located() -> None:
    provider = _complete_provider()
    baseline = await capture_family_inventory(provider)
    repeated = await capture_family_inventory(provider)
    assert baseline.overall_hash == repeated.overall_hash
    assert tuple(baseline.family_hashes) == EXPECTED_DOMAINS
    assert all(value.startswith("sha256:") for value in baseline.family_hashes.values())

    for domain in EXPECTED_DOMAINS:
        spec = FAMILY_DOMAIN_SPECS[domain]
        logical_name = spec.logical[0]
        changed_logical = dict(provider.logical)
        changed_logical[logical_name] = {"stable": False, "domain": domain}
        changed = await capture_family_inventory(
            MappingSnapshotProvider(tables=provider.tables, logical=changed_logical, files=provider.files)
        )
        comparison = compare_family_inventories(baseline, changed)
        assert domain in comparison.changed_domains
        assert f"logical:{logical_name}" in comparison.changed_components[domain]


async def _old_test_shadow_only_file_writes_are_excluded_but_family_bytes_are_not(tmp_path: Path) -> None:
    root = tmp_path / "copied-runtime"
    family = root / "family" / "published-report.json"
    family.parent.mkdir(parents=True)
    family.write_bytes(b'{"authority":"legacy","status":"completed"}')
    target = FileSnapshotTarget(root, excluded_relative_dirs=ISOLATED_SHADOW_RELATIVE_DIRS)
    provider = MappingSnapshotProvider(files={"published_completed_artifacts": target})
    before = await capture_family_inventory(provider)

    run_artifact = root / "shadow" / "v2" / "runs" / "run-1" / "artifacts" / "claims.json"
    run_artifact.parent.mkdir(parents=True)
    run_artifact.write_bytes(b'{"authority":"v2","diagnostic_only":true}')
    audit = root / "shadow" / "v2" / "audits" / "run-1.jsonl"
    audit.parent.mkdir(parents=True)
    audit.write_text('{"kind":"shadow_run"}\n', encoding="utf-8")

    after_shadow_write = await capture_family_inventory(provider)
    assert assert_family_inventory_unchanged(before, after_shadow_write).unchanged

    family.write_bytes(b'{"authority":"v2","status":"completed"}')
    after_family_write = await capture_family_inventory(provider)
    comparison = compare_family_inventories(before, after_family_write)
    assert comparison.unchanged is False
    assert comparison.changed_domains == ("published_completed_artifacts",)
    assert comparison.changed_components["published_completed_artifacts"] == (
        "file:published_completed_artifacts",
    )
    with pytest.raises(FamilyContaminationError, match="published_completed_artifacts"):
        assert_family_inventory_unchanged(before, after_family_write)


async def _old_test_injected_test_database_snapshot_detects_family_row_mutation(tmp_path: Path) -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    copied_root = tmp_path / "copied-runtime"
    copied_root.mkdir()
    family_file = copied_root / "legacy-result.json"
    family_file.write_text('{"status":"completed"}', encoding="utf-8")
    file_targets = {
        file_name: FileSnapshotTarget(copied_root, excluded_relative_dirs=ISOLATED_SHADOW_RELATIVE_DIRS)
        for spec in FAMILY_DOMAIN_SPECS.values()
        for file_name in spec.files
    }

    try:
        async with session_factory() as session:
            session.add(
                Analysis(
                    id="analysis-1",
                    action_type="jump",
                    video_path="copied/source.mp4",
                    status="completed",
                    report={"summary": "legacy remains authoritative"},
                )
            )
            await session.commit()
            provider = SQLAlchemySnapshotProvider(session, files=file_targets)
            before = await capture_family_inventory(provider)

            shadow_artifact = copied_root / "shadow" / "v2" / "runs" / "run-1" / "artifacts" / "timebase.json"
            shadow_artifact.parent.mkdir(parents=True)
            shadow_artifact.write_text('{"diagnostic_only":true}', encoding="utf-8")
            after_shadow_write = await capture_family_inventory(provider)
            assert assert_family_inventory_unchanged(before, after_shadow_write).unchanged

            session.add(
                AnalysisChatMessage(
                    id="chat-1",
                    analysis_id="analysis-1",
                    role="assistant",
                    content="unexpected family-side write",
                )
            )
            await session.commit()
            after_family_write = await capture_family_inventory(provider)
            comparison = compare_family_inventories(before, after_family_write)
            assert comparison.changed_domains == ("chat_corrections",)
            assert comparison.changed_components["chat_corrections"] == (
                "table:analysis_chat_messages",
            )
    finally:
        await engine.dispose()


def test_ordinary_frontend_and_backend_sources_do_not_read_raw_shadow_resources() -> None:
    root = Path(__file__).resolve().parents[3]
    ordinary_frontend = (
        root / "frontend" / "src" / "modern" / "ModernTodayIsland.tsx",
        root / "frontend" / "src" / "modern" / "ModernReviewSpace.tsx",
        root / "frontend" / "src" / "modern" / "ModernAnalysisDetail.tsx",
        root / "frontend" / "src" / "modern" / "ModernGrowthSpace.tsx",
        root / "frontend" / "src" / "pages" / "ReviewPage.tsx",
        root / "frontend" / "src" / "pages" / "GrowthHomePage.tsx",
    )
    forbidden_frontend = (
        "/shadow/",
        "ShadowWorkspace",
        "createShadowRun",
        "fetchShadowArtifact",
        "fetchShadowDiff",
        "fetchShadowRuns",
        "fetchShadowStatus",
        "retryShadowRun",
        "shadow-contracts",
    )
    for source in ordinary_frontend:
        text = source.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden_frontend), source

    ordinary_backend = (
        root / "backend" / "app" / "routers" / "analysis.py",
        root / "backend" / "app" / "routers" / "growth.py",
        root / "backend" / "app" / "routers" / "skaters.py",
    )
    forbidden_backend = (
        "analysis_v2.shadow_contracts",
        "analysis_v2.shadow_store",
        "routers.shadow",
        "ShadowArtifactResponse",
        "ShadowRunRecord",
    )
    for source in ordinary_backend:
        text = source.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden_backend), source
