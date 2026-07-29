from __future__ import annotations

from copy import deepcopy
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.analysis_v2.config import (
    PipelineMode,
    RuntimeConfigurationError,
    apply_runtime_environment,
    load_runtime_config,
)
from app.analysis_v2.orchestration import NoOpShadowOrchestrator


def test_pipeline_mode_defaults_to_legacy(tmp_path: Path) -> None:
    config = load_runtime_config({}, project_root=tmp_path)

    assert config.pipeline_mode is PipelineMode.LEGACY
    assert config.public_authority == "legacy"


def test_legacy_mode_preserves_external_database_configuration(tmp_path: Path) -> None:
    config = load_runtime_config(
        {"DATABASE_URL": "postgresql+asyncpg://database.example/skating"},
        project_root=tmp_path,
    )

    assert config.pipeline_mode is PipelineMode.LEGACY
    assert config.database_url == "postgresql+asyncpg://database.example/skating"
    assert "database" not in config.runtime_paths


def test_invalid_pipeline_mode_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeConfigurationError, match="SKATING_ANALYSIS_PIPELINE"):
        load_runtime_config({"SKATING_ANALYSIS_PIPELINE": "mixed"}, project_root=tmp_path)


def test_v2_runtime_paths_must_resolve_beneath_runtime_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    config = load_runtime_config(
        {
            "SKATING_ANALYSIS_PIPELINE": "shadow",
            "V2_RUNTIME_ROOT": str(runtime_root),
            "DATA_DIR": str(runtime_root / "data"),
            "DATABASE_URL": f"sqlite+aiosqlite:///{runtime_root / 'database' / 'v2.db'}",
            "BACKUPS_DIR": str(runtime_root / "backups"),
        },
        project_root=tmp_path,
    )

    assert config.is_isolated
    assert all(path.is_relative_to(runtime_root.resolve()) for path in config.runtime_paths.values())


def test_shadow_mode_rejects_path_outside_runtime_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    with pytest.raises(RuntimeConfigurationError, match="beneath V2_RUNTIME_ROOT"):
        load_runtime_config(
            {
                "SKATING_ANALYSIS_PIPELINE": "shadow",
                "V2_RUNTIME_ROOT": str(runtime_root),
                "DATA_DIR": str(tmp_path / "shared-data"),
            },
            project_root=tmp_path,
        )


@pytest.mark.parametrize("setting", ["UPLOADS_DIR", "ARCHIVE_DIR", "VIDEO_PROCESSING_ROOT"])
def test_shadow_mode_validates_effective_writable_paths(tmp_path: Path, setting: str) -> None:
    with pytest.raises(RuntimeConfigurationError, match="beneath V2_RUNTIME_ROOT"):
        load_runtime_config(
            {
                "SKATING_ANALYSIS_PIPELINE": "shadow",
                "V2_RUNTIME_ROOT": str(tmp_path / "runtime"),
                setting: str(tmp_path / "shared" / setting.lower()),
            },
            project_root=tmp_path,
        )


def test_validated_shadow_paths_are_applied_before_runtime_modules_load(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    env = {"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(root)}
    config = load_runtime_config(env, project_root=tmp_path)

    apply_runtime_environment(config, env)

    assert Path(env["DATA_DIR"]).is_relative_to(root)
    assert Path(env["UPLOADS_DIR"]).is_relative_to(root)
    assert Path(env["BACKUPS_DIR"]).is_relative_to(root)
    assert Path(env["VIDEO_PROCESSING_ROOT"]).is_relative_to(root)
    assert root.resolve().as_posix() in env["DATABASE_URL"]


def test_noop_shadow_orchestrator_never_mutates_legacy_result(tmp_path: Path) -> None:
    config = load_runtime_config(
        {
            "SKATING_ANALYSIS_PIPELINE": "shadow",
            "V2_RUNTIME_ROOT": str(tmp_path / "runtime"),
        },
        project_root=tmp_path,
    )
    legacy = {"report": {"summary": "legacy"}, "bio_data": {"air_time": 0.4}}
    before = deepcopy(legacy)

    result = asyncio.run(NoOpShadowOrchestrator(config).run(legacy))

    assert legacy == before
    assert result.status == "ready"
    assert result.writes_performed == 0
    assert result.artifact_references == ()


def test_application_import_rejects_invalid_pipeline_mode(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "SKATING_ANALYSIS_PIPELINE": "invalid-mode",
            "DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'database' / 'test.db'}",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "Invalid SKATING_ANALYSIS_PIPELINE" in result.stderr


def test_application_import_accepts_fully_isolated_shadow_runtime(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    env = os.environ.copy()
    env.update(
        {
            "SKATING_ANALYSIS_PIPELINE": "shadow",
            "V2_RUNTIME_ROOT": str(root),
            "DATA_DIR": str(root / "data"),
            "DATABASE_URL": f"sqlite+aiosqlite:///{root / 'database' / 'test.db'}",
            "BACKUPS_DIR": str(root / "backups"),
            "UPLOADS_DIR": str(root / "uploads"),
            "ARCHIVE_DIR": str(root / "archive"),
            "VIDEO_PROCESSING_ROOT": str(root / "temp-frames"),
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print(app.main.runtime_config.is_isolated)"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "True" in result.stdout


def test_application_import_applies_root_only_shadow_defaults(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    env = os.environ.copy()
    for name in (
        "DATA_DIR", "DATABASE_URL", "BACKUPS_DIR", "UPLOADS_DIR", "ARCHIVE_DIR", "VIDEO_PROCESSING_ROOT",
    ):
        env.pop(name, None)
    env.update({"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(root)})
    script = (
        "import app.main, app.database as db; "
        "print(db.DATA_DIR); print(db.UPLOADS_DIR); print(db.BACKUPS_DIR); print(db.DATABASE_URL)"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    output_paths = result.stdout.strip().splitlines()
    normalized_root = root.resolve().as_posix().lower()
    assert all(normalized_root in value.replace("\\", "/").lower() for value in output_paths)


def test_backup_restore_round_trip_uses_an_isolated_copy(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    env = os.environ.copy()
    env.update(
        {
            "DATA_DIR": str(root / "data"),
            "DATABASE_URL": f"sqlite+aiosqlite:///{root / 'database' / 'test.db'}",
            "BACKUPS_DIR": str(root / "backups"),
        }
    )
    script = """
from pathlib import Path
from app.database import DATA_DIR, ensure_storage_dirs
from app.services.archive_policy import create_manual_backup, restore_backup
ensure_storage_dirs()
marker = DATA_DIR / 'marker.txt'
marker.write_text('before', encoding='utf-8')
backup = create_manual_backup('iteration-0')
marker.write_text('after', encoding='utf-8')
restore_backup(backup.name)
assert marker.read_text(encoding='utf-8') == 'before'
print(backup)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert root.resolve().as_posix().lower() in result.stdout.replace("\\", "/").lower()
