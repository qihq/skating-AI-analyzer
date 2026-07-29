from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, MutableMapping
from urllib.parse import unquote, urlparse


class RuntimeConfigurationError(ValueError):
    """Raised when the selected pipeline cannot use an isolated runtime safely."""


class PipelineMode(str, Enum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    V2 = "v2"


def _resolve_path(raw: str, project_root: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _sqlite_path(database_url: str, project_root: Path) -> Path | None:
    parsed = urlparse(database_url.replace("sqlite+aiosqlite", "sqlite", 1))
    if parsed.scheme != "sqlite":
        return None
    raw_path = unquote(parsed.path)
    if parsed.netloc:
        raw_path = f"//{parsed.netloc}{raw_path}"
    if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    return _resolve_path(raw_path, project_root)


@dataclass(frozen=True)
class RuntimeConfig:
    pipeline_mode: PipelineMode
    project_root: Path
    runtime_root: Path | None
    runtime_paths: Mapping[str, Path]
    database_url: str
    is_isolated: bool

    @property
    def public_authority(self) -> str:
        # Iteration 0 has no V2 authority. Shadow is always legacy-authoritative.
        return "legacy"


def _parse_mode(raw: str | None) -> PipelineMode:
    normalized = (raw or PipelineMode.LEGACY.value).strip().lower()
    try:
        return PipelineMode(normalized)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in PipelineMode)
        raise RuntimeConfigurationError(
            f"Invalid SKATING_ANALYSIS_PIPELINE={raw!r}; expected one of: {allowed}."
        ) from exc


def load_runtime_config(env: Mapping[str, str], *, project_root: Path) -> RuntimeConfig:
    project_root = project_root.resolve()
    mode = _parse_mode(env.get("SKATING_ANALYSIS_PIPELINE"))
    runtime_root_raw = env.get("V2_RUNTIME_ROOT", "").strip()
    runtime_root = _resolve_path(runtime_root_raw, project_root) if runtime_root_raw else None

    if mode is not PipelineMode.LEGACY and runtime_root is None:
        raise RuntimeConfigurationError(
            "V2_RUNTIME_ROOT is required when SKATING_ANALYSIS_PIPELINE is shadow or v2."
        )

    default_root = runtime_root or project_root
    data_dir = _resolve_path(env.get("DATA_DIR", str(default_root / "data")), project_root)
    backups_dir = _resolve_path(env.get("BACKUPS_DIR", str(default_root / "backups")), project_root)
    database_url = env.get(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{(default_root / 'database' / 'skating-analyzer-v2.db').as_posix()}",
    )
    database_path = _sqlite_path(database_url, project_root)
    if mode is not PipelineMode.LEGACY and database_path is None:
        raise RuntimeConfigurationError(
            "Iteration 0 isolation requires DATABASE_URL to use sqlite+aiosqlite beneath V2_RUNTIME_ROOT."
        )
    paths = {
        "data": data_dir,
        "backups": backups_dir,
        "uploads": _resolve_path(
            env.get("UPLOADS_DIR", env.get("V2_UPLOADS_DIR", str(data_dir / "uploads"))), project_root
        ),
        "archive": _resolve_path(env.get("ARCHIVE_DIR", str(data_dir / "archive")), project_root),
        "analysis_artifacts": _resolve_path(
            env.get("V2_ANALYSIS_ARTIFACTS_DIR", str(default_root / "analysis-assets")), project_root
        ),
        "golden": _resolve_path(env.get("V2_GOLDEN_DIR", str(default_root / "golden")), project_root),
        "cache": _resolve_path(env.get("V2_CACHE_DIR", str(default_root / "cache")), project_root),
        "temporary_frames": _resolve_path(
            env.get("VIDEO_PROCESSING_ROOT", env.get("V2_TEMP_FRAMES_DIR", str(default_root / "temp-frames"))),
            project_root,
        ),
        "model_outputs": _resolve_path(
            env.get("V2_MODEL_OUTPUTS_DIR", str(default_root / "model-outputs")), project_root
        ),
        "test_data": _resolve_path(env.get("V2_TEST_DATA_DIR", str(default_root / "test-data")), project_root),
    }
    if database_path is not None:
        paths["database"] = database_path

    is_isolated = runtime_root is not None and all(path.is_relative_to(runtime_root) for path in paths.values())
    if mode is not PipelineMode.LEGACY and not is_isolated:
        outside = sorted(name for name, path in paths.items() if not path.is_relative_to(runtime_root))
        raise RuntimeConfigurationError(
            "All V2 writable paths must resolve beneath V2_RUNTIME_ROOT; outside paths: " + ", ".join(outside)
        )

    return RuntimeConfig(
        pipeline_mode=mode,
        project_root=project_root,
        runtime_root=runtime_root,
        runtime_paths=paths,
        database_url=database_url,
        is_isolated=is_isolated,
    )


def apply_runtime_environment(config: RuntimeConfig, env: MutableMapping[str, str]) -> None:
    """Apply the validated paths before modules with import-time runtime constants load."""
    if config.pipeline_mode is PipelineMode.LEGACY:
        return
    effective = {
        "V2_RUNTIME_ROOT": str(config.runtime_root),
        "DATA_DIR": str(config.runtime_paths["data"]),
        "DATABASE_URL": config.database_url,
        "BACKUPS_DIR": str(config.runtime_paths["backups"]),
        "UPLOADS_DIR": str(config.runtime_paths["uploads"]),
        "ARCHIVE_DIR": str(config.runtime_paths["archive"]),
        "VIDEO_PROCESSING_ROOT": str(config.runtime_paths["temporary_frames"]),
        "V2_ANALYSIS_ARTIFACTS_DIR": str(config.runtime_paths["analysis_artifacts"]),
        "V2_GOLDEN_DIR": str(config.runtime_paths["golden"]),
        "V2_CACHE_DIR": str(config.runtime_paths["cache"]),
        "V2_TEMP_FRAMES_DIR": str(config.runtime_paths["temporary_frames"]),
        "V2_MODEL_OUTPUTS_DIR": str(config.runtime_paths["model_outputs"]),
        "V2_TEST_DATA_DIR": str(config.runtime_paths["test_data"]),
    }
    env.update(effective)
