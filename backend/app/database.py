from __future__ import annotations

import os
import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any, Awaitable, Callable, AsyncGenerator

from sqlalchemy.exc import OperationalError
from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_LOCAL_DEV = os.name == "nt"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" if WINDOWS_LOCAL_DEV else (Path("/data") if Path("/data").exists() else PROJECT_ROOT / "data")
DEFAULT_BACKUPS_DIR = PROJECT_ROOT / "backups" if WINDOWS_LOCAL_DEV else (Path("/backups") if Path("/backups").exists() else PROJECT_ROOT / "backups")


def _resolve_runtime_path(raw_path: str | Path, fallback: Path) -> Path:
    path = Path(raw_path)
    if WINDOWS_LOCAL_DEV and path.is_absolute() and not str(path.drive):
        return PROJECT_ROOT / str(path).lstrip("/\\")
    if path.exists():
        return path
    if path.is_absolute() and not str(path.drive):
        fallback_candidate = PROJECT_ROOT / str(path).lstrip("/\\")
        if fallback_candidate.exists() or path == fallback:
            return fallback_candidate
    if not path.is_absolute():
        return PROJECT_ROOT / path
    return path


DATA_DIR = _resolve_runtime_path(os.getenv("DATA_DIR", str(DEFAULT_DATA_DIR)), DEFAULT_DATA_DIR)
UPLOADS_DIR = DATA_DIR / "uploads"
ARCHIVE_DIR = DATA_DIR / "archive"
BACKUPS_DIR = _resolve_runtime_path(os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)), DEFAULT_BACKUPS_DIR)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR / 'skating-analyzer.db'}")
SQLITE_BUSY_TIMEOUT_SECONDS = float(os.getenv("SQLITE_BUSY_TIMEOUT_SECONDS", "30"))
SQLITE_INIT_RETRY_ATTEMPTS = int(os.getenv("SQLITE_INIT_RETRY_ATTEMPTS", "5"))
SQLITE_INIT_RETRY_BASE_SECONDS = float(os.getenv("SQLITE_INIT_RETRY_BASE_SECONDS", "1.0"))
SQLITE_WRITE_RETRY_ATTEMPTS = int(os.getenv("SQLITE_WRITE_RETRY_ATTEMPTS", "3"))
SQLITE_WRITE_RETRY_BASE_SECONDS = float(os.getenv("SQLITE_WRITE_RETRY_BASE_SECONDS", "0.75"))
SQLITE_READ_RETRY_ATTEMPTS = int(os.getenv("SQLITE_READ_RETRY_ATTEMPTS", str(SQLITE_WRITE_RETRY_ATTEMPTS)))
SQLITE_READ_RETRY_BASE_SECONDS = float(os.getenv("SQLITE_READ_RETRY_BASE_SECONDS", str(SQLITE_WRITE_RETRY_BASE_SECONDS)))
SQLITE_BIND_MOUNT_FALLBACK_JOURNAL_MODE = "DELETE"
SQLITE_DEFAULT_JOURNAL_MODE = "WAL"
SQLITE_TRANSIENT_WRITE_ERROR_MARKERS = (
    "database is locked",
    "database is busy",
    "disk i/o error",
)
logger = logging.getLogger(__name__)


def _path_mount_type(path: Path) -> str | None:
    if os.name == "nt":
        return None
    try:
        target = path.resolve()
    except OSError:
        target = path.absolute()
    best_match: tuple[int, str] | None = None
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point = Path(parts[1].replace("\\040", " "))
        try:
            mount_path = mount_point.resolve()
        except OSError:
            mount_path = mount_point.absolute()
        try:
            is_match = target == mount_path or target.is_relative_to(mount_path)
        except ValueError:
            is_match = False
        if not is_match:
            continue
        match_len = len(str(mount_path))
        if best_match is None or match_len > best_match[0]:
            best_match = (match_len, parts[2].lower())
    return best_match[1] if best_match else None


def _default_sqlite_journal_mode() -> str:
    mount_type = _path_mount_type(DATA_DIR)
    if mount_type in {"9p", "drvfs"}:
        return SQLITE_BIND_MOUNT_FALLBACK_JOURNAL_MODE
    return SQLITE_DEFAULT_JOURNAL_MODE


SQLITE_JOURNAL_MODE = os.getenv("SQLITE_JOURNAL_MODE", _default_sqlite_journal_mode()).strip().upper()
SQLITE_ALLOWED_JOURNAL_MODES = {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}
if SQLITE_JOURNAL_MODE not in SQLITE_ALLOWED_JOURNAL_MODES:
    SQLITE_JOURNAL_MODE = SQLITE_DEFAULT_JOURNAL_MODE


class Base(DeclarativeBase):
    pass


_sqlite_connect_args = {"timeout": SQLITE_BUSY_TIMEOUT_SECONDS} if DATABASE_URL.startswith("sqlite") else {}
_engine_kwargs = {"connect_args": _sqlite_connect_args}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["poolclass"] = NullPool
engine = create_async_engine(DATABASE_URL, future=True, **_engine_kwargs)


if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _exception_messages(exc: BaseException) -> list[str]:
    messages: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(str(current))
        orig = getattr(current, "orig", None)
        if isinstance(orig, BaseException):
            current = orig
            continue
        if orig is not None:
            messages.append(str(orig))
        current = current.__cause__ or current.__context__
    return messages


def is_transient_sqlite_write_error(exc: BaseException) -> bool:
    if not DATABASE_URL.startswith("sqlite"):
        return False
    return any(
        marker in message.lower()
        for message in _exception_messages(exc)
        for marker in SQLITE_TRANSIENT_WRITE_ERROR_MARKERS
    )


async def run_db_write_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    context: str,
    attempts: int | None = None,
    base_delay_seconds: float | None = None,
) -> Any:
    return await _run_db_operation_with_retry(
        operation,
        context=context,
        operation_kind="write",
        attempts=attempts,
        default_attempts=SQLITE_WRITE_RETRY_ATTEMPTS,
        base_delay_seconds=base_delay_seconds,
        default_base_delay_seconds=SQLITE_WRITE_RETRY_BASE_SECONDS,
    )


async def run_db_read_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    context: str,
    attempts: int | None = None,
    base_delay_seconds: float | None = None,
) -> Any:
    return await _run_db_operation_with_retry(
        operation,
        context=context,
        operation_kind="read",
        attempts=attempts,
        default_attempts=SQLITE_READ_RETRY_ATTEMPTS,
        base_delay_seconds=base_delay_seconds,
        default_base_delay_seconds=SQLITE_READ_RETRY_BASE_SECONDS,
    )


async def _run_db_operation_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    context: str,
    operation_kind: str,
    attempts: int | None,
    default_attempts: int,
    base_delay_seconds: float | None,
    default_base_delay_seconds: float,
) -> Any:
    max_attempts = max(1, attempts if attempts is not None else default_attempts)
    base_delay = max(0.0, base_delay_seconds if base_delay_seconds is not None else default_base_delay_seconds)
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except (OperationalError, sqlite3.OperationalError) as exc:
            if not is_transient_sqlite_write_error(exc):
                raise
            last_error = exc
            if attempt >= max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Transient SQLite %s error during %s (attempt %s/%s), retrying in %.2fs: %s",
                operation_kind,
                context,
                attempt,
                max_attempts,
                delay,
                exc,
            )
            if delay:
                await asyncio.sleep(delay)
    assert last_error is not None
    logger.error(
        "Transient SQLite %s error during %s persisted after %s attempts: %s",
        operation_kind,
        context,
        max_attempts,
        last_error,
    )
    raise last_error


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401

    attempts = max(1, SQLITE_INIT_RETRY_ATTEMPTS if DATABASE_URL.startswith("sqlite") else 1)
    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                if DATABASE_URL.startswith("sqlite"):
                    await conn.execute(text(f"PRAGMA journal_mode={SQLITE_JOURNAL_MODE}"))
                await conn.run_sync(Base.metadata.create_all)
                await _run_migrations(conn)
            return
        except OperationalError as exc:
            message = str(exc).lower()
            if "database is locked" not in message or attempt >= attempts:
                raise
            await asyncio.sleep(SQLITE_INIT_RETRY_BASE_SECONDS * attempt)


def ensure_storage_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOADS_DIR / "_debug").mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


async def _rebuild_analyses_for_skill_category_text(conn) -> None:
    table_info_result = await conn.execute(text("PRAGMA table_info(analyses)"))
    table_info = table_info_result.fetchall()
    if not table_info:
        return

    index_result = await conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'analyses' AND sql IS NOT NULL")
    )
    index_sql = [row[0] for row in index_result.fetchall()]

    column_defs: list[str] = []
    column_names: list[str] = []
    for row in table_info:
        name = row[1]
        column_type = "TEXT" if name == "skill_category" else (row[2] or "TEXT")
        definition = f"{_quote_identifier(name)} {column_type}"
        if row[3] and not row[5]:
            definition += " NOT NULL"
        if row[4] is not None:
            definition += f" DEFAULT {row[4]}"
        if row[5]:
            definition += " PRIMARY KEY"
        column_defs.append(definition)
        column_names.append(name)

    columns_sql = ", ".join(_quote_identifier(name) for name in column_names)
    await conn.execute(text(f"CREATE TABLE analyses_new ({', '.join(column_defs)})"))
    await conn.execute(text(f"INSERT INTO analyses_new ({columns_sql}) SELECT {columns_sql} FROM analyses"))
    await conn.execute(text("DROP TABLE analyses"))
    await conn.execute(text("ALTER TABLE analyses_new RENAME TO analyses"))

    for sql in index_sql:
        await conn.execute(text(sql))


async def _run_migrations(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(analyses)"))
    table_info = result.fetchall()
    existing_columns = {row[1] for row in table_info}

    new_columns = [
        ("skater_id", "VARCHAR(36)"),
        ("session_id", "VARCHAR(36) REFERENCES training_sessions(id)"),
        ("skill_node_id", "TEXT REFERENCES skill_nodes(id)"),
        ("skill_category", "TEXT"),
        ("action_subtype", "TEXT"),
        ("analysis_profile", "TEXT"),
        ("retry_from_stage", "TEXT"),
        ("pipeline_version", "TEXT NOT NULL DEFAULT 'v1.0.0'"),
        ("vision_structured", "JSON"),
        ("vision_path_a", "JSON"),
        ("vision_path_b", "JSON"),
        ("cross_validation", "JSON"),
        ("pose_data", "JSON"),
        ("bio_data", "JSON"),
        ("frame_motion_scores", "JSON"),
        ("processing_timings", "JSON"),
        ("processing_logs", "JSON"),
        ("target_lock", "JSON"),
        ("target_lock_status", "TEXT"),
        ("manual_action_window_start", "REAL"),
        ("manual_action_window_end", "REAL"),
        ("auto_unlocked_skill", "TEXT REFERENCES skill_nodes(id)"),
    ]

    for column_name, column_type in new_columns:
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE analyses ADD COLUMN {column_name} {column_type}"))

    result = await conn.execute(text("PRAGMA table_info(analyses)"))
    column_types = {row[1]: str(row[2]).upper() for row in result.fetchall()}
    if column_types.get("skill_category") not in {None, "TEXT"}:
        await _rebuild_analyses_for_skill_category_text(conn)

    skater_columns_result = await conn.execute(text("PRAGMA table_info(skaters)"))
    existing_skater_columns = {row[1] for row in skater_columns_result.fetchall()}
    skater_new_columns = [
        ("display_name", "VARCHAR(80) DEFAULT ''"),
        ("avatar_emoji", "VARCHAR(12) DEFAULT '⛸️'"),
        ("avatar_type", "VARCHAR(24) NOT NULL DEFAULT 'emoji'"),
        ("birth_year", "INTEGER DEFAULT 2021"),
        ("current_level", "VARCHAR(40) DEFAULT 'snowplow'"),
        ("avatar_level", "INTEGER DEFAULT 1"),
        ("total_xp", "INTEGER DEFAULT 0"),
        ("current_streak", "INTEGER DEFAULT 0"),
        ("longest_streak", "INTEGER DEFAULT 0"),
        ("last_active_date", "VARCHAR(20)"),
        ("is_default", "BOOLEAN DEFAULT 0"),
    ]
    for column_name, column_type in skater_new_columns:
        if column_name not in existing_skater_columns:
            await conn.execute(text(f"ALTER TABLE skaters ADD COLUMN {column_name} {column_type}"))

    skater_skill_columns_result = await conn.execute(text("PRAGMA table_info(skater_skills)"))
    existing_skater_skill_columns = {row[1] for row in skater_skill_columns_result.fetchall()}
    if "unlock_note" not in existing_skater_skill_columns:
        await conn.execute(text("ALTER TABLE skater_skills ADD COLUMN unlock_note TEXT"))

    await run_migrations_patch_d(conn)
    await run_migrations_patch_e(conn)

    provider_columns_result = await conn.execute(text("PRAGMA table_info(ai_providers)"))
    existing_provider_columns = {row[1] for row in provider_columns_result.fetchall()}
    if "vision_model" not in existing_provider_columns:
        await conn.execute(text("ALTER TABLE ai_providers ADD COLUMN vision_model VARCHAR(120)"))

    await run_migrations_patch_a(conn)
    await run_migrations_patch_c(conn)
    await run_migrations_phase6(conn)
    await run_migrations_patch_f(conn)
    await run_migrations_patch_g(conn)
    await run_migrations_patch_h(conn)
    await run_migrations_patch_i(conn)
    await run_migrations_debug_runs(conn)


async def run_migrations_patch_a(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _apply_patch_a(conn)
        return

    async with engine.begin() as conn:
        await _apply_patch_a(conn)


async def _apply_patch_a(conn) -> None:
    skater_columns_result = await conn.execute(text("PRAGMA table_info(skaters)"))
    existing_skater_columns = {row[1] for row in skater_columns_result.fetchall()}
    if "avatar_type" not in existing_skater_columns:
        await conn.execute(text("ALTER TABLE skaters ADD COLUMN avatar_type TEXT NOT NULL DEFAULT 'emoji'"))

    await conn.execute(
        text(
            "UPDATE skaters SET avatar_type='zodiac_rat', display_name='坦坦', "
            "avatar_emoji='🐭', birth_year=2020 WHERE name='tantan'"
        )
    )
    await conn.execute(
        text(
            "UPDATE skaters SET avatar_type='zodiac_tiger', display_name='昭昭', "
            "avatar_emoji='🐯', birth_year=2022 WHERE name='zhaozao'"
        )
    )
    await conn.execute(
        text(
            "UPDATE skaters SET avatar_type='zodiac_tiger', display_name='昭昭', "
            "name='zhaozao', avatar_emoji='🐯', birth_year=2022 WHERE name='didi'"
        )
    )


async def run_migrations_phase6(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _create_phase6_tables(conn)
        return

    async with engine.begin() as conn:
        await _create_phase6_tables(conn)


async def run_migrations_patch_c(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _apply_patch_c(conn)
        return

    async with engine.begin() as conn:
        await _apply_patch_c(conn)


async def _apply_patch_c(conn) -> None:
    parent_auth_columns_result = await conn.execute(text("PRAGMA table_info(parent_auth)"))
    existing_parent_auth_columns = {row[1] for row in parent_auth_columns_result.fetchall()}
    if "pin_length" not in existing_parent_auth_columns:
        await conn.execute(text("ALTER TABLE parent_auth ADD COLUMN pin_length INTEGER NOT NULL DEFAULT 4"))


async def run_migrations_patch_d(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _apply_patch_d(conn)
        return

    async with engine.begin() as conn:
        await _apply_patch_d(conn)


async def _apply_patch_d(conn) -> None:
    analysis_columns_result = await conn.execute(text("PRAGMA table_info(analyses)"))
    analysis_columns = {row[1] for row in analysis_columns_result.fetchall()}
    if "skill_node_id" not in analysis_columns:
        await conn.execute(text("ALTER TABLE analyses ADD COLUMN skill_node_id TEXT REFERENCES skill_nodes(id)"))
    if "auto_unlocked_skill" not in analysis_columns:
        await conn.execute(text("ALTER TABLE analyses ADD COLUMN auto_unlocked_skill TEXT REFERENCES skill_nodes(id)"))

    skater_skill_columns_result = await conn.execute(text("PRAGMA table_info(skater_skills)"))
    skater_skill_columns = {row[1] for row in skater_skill_columns_result.fetchall()}
    if "attempt_count" not in skater_skill_columns:
        await conn.execute(text("ALTER TABLE skater_skills ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"))
    if "best_score" not in skater_skill_columns:
        await conn.execute(text("ALTER TABLE skater_skills ADD COLUMN best_score INTEGER NOT NULL DEFAULT 0"))
    if "unlocked_by" not in skater_skill_columns:
        await conn.execute(text("ALTER TABLE skater_skills ADD COLUMN unlocked_by TEXT"))

    if "is_unlocked" in skater_skill_columns:
        await conn.execute(
            text(
                "UPDATE skater_skills SET status='unlocked', unlocked_by='parent' "
                "WHERE is_unlocked=1"
            )
        )

    await conn.execute(text("UPDATE skater_skills SET status='attempting' WHERE status='in_progress'"))
    await conn.execute(text("UPDATE skater_skills SET status='unlocked', unlocked_by='auto' WHERE status='unlocked_ai'"))
    await conn.execute(text("UPDATE skater_skills SET status='unlocked', unlocked_by='parent' WHERE status='unlocked_parent'"))
    await conn.execute(text("UPDATE skater_skills SET unlocked_by='auto' WHERE unlocked_by IS NULL AND status='unlocked'"))


async def run_migrations_patch_e(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _apply_patch_e(conn)
        return

    async with engine.begin() as conn:
        await _apply_patch_e(conn)


async def _apply_patch_e(conn) -> None:
    analysis_columns_result = await conn.execute(text("PRAGMA table_info(analyses)"))
    analysis_columns = {row[1] for row in analysis_columns_result.fetchall()}
    for column_name, column_type in [
        ("action_window_start", "REAL"),
        ("action_window_end", "REAL"),
        ("manual_action_window_start", "REAL"),
        ("manual_action_window_end", "REAL"),
        ("source_fps", "REAL"),
        ("is_slow_motion", "INTEGER DEFAULT 0"),
    ]:
        if column_name not in analysis_columns:
            await conn.execute(text(f"ALTER TABLE analyses ADD COLUMN {column_name} {column_type}"))


async def run_migrations_patch_f(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _apply_patch_f(conn)
        return

    async with engine.begin() as conn:
        await _apply_patch_f(conn)


async def _apply_patch_f(conn) -> None:
    memory_columns_result = await conn.execute(text("PRAGMA table_info(snowball_memories)"))
    memory_columns = {row[1] for row in memory_columns_result.fetchall()}
    if "expires_at" not in memory_columns:
        await conn.execute(text("ALTER TABLE snowball_memories ADD COLUMN expires_at TIMESTAMP"))

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS memory_suggestions (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                skater_id TEXT NOT NULL,
                suggestions JSON NOT NULL,
                is_reviewed INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id),
                FOREIGN KEY (skater_id) REFERENCES skaters(id)
            )
            """
        )
    )


async def run_migrations_patch_g(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _apply_patch_g(conn)
        return

    async with engine.begin() as conn:
        await _apply_patch_g(conn)


async def _apply_patch_g(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS training_sessions (
                id TEXT PRIMARY KEY,
                skater_id TEXT NOT NULL REFERENCES skaters(id),
                session_date DATE NOT NULL,
                location TEXT NOT NULL DEFAULT '冰场',
                session_type TEXT NOT NULL DEFAULT '上冰',
                duration_minutes INTEGER,
                coach_present INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_training_sessions_skater_id ON training_sessions(skater_id)"))
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_training_sessions_session_date ON training_sessions(session_date DESC)")
    )

    analysis_columns_result = await conn.execute(text("PRAGMA table_info(analyses)"))
    analysis_columns = {row[1] for row in analysis_columns_result.fetchall()}
    if "session_id" not in analysis_columns:
        await conn.execute(text("ALTER TABLE analyses ADD COLUMN session_id TEXT REFERENCES training_sessions(id)"))


async def run_migrations_patch_h(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _apply_patch_h(conn)
        return

    async with engine.begin() as conn:
        await _apply_patch_h(conn)


async def _apply_patch_h(conn) -> None:
    analysis_columns_result = await conn.execute(text("PRAGMA table_info(analyses)"))
    analysis_columns = {row[1] for row in analysis_columns_result.fetchall()}
    if "error_code" not in analysis_columns:
        await conn.execute(text("ALTER TABLE analyses ADD COLUMN error_code TEXT"))
    if "error_detail" not in analysis_columns:
        await conn.execute(text("ALTER TABLE analyses ADD COLUMN error_detail TEXT"))


async def run_migrations_patch_i(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _apply_patch_i(conn)
        return

    async with engine.begin() as conn:
        await _apply_patch_i(conn)


async def _apply_patch_i(conn) -> None:
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analyses_created_at ON analyses(created_at DESC)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analyses_skater_id ON analyses(skater_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analyses_skater_created_at ON analyses(skater_id, created_at DESC)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analyses_status_created_at ON analyses(status, created_at DESC)"))


async def run_migrations_debug_runs(engine) -> None:
    if hasattr(engine, "execute"):
        async with _noop_context(engine) as conn:
            await _create_debug_run_tables(conn)
        return

    async with engine.begin() as conn:
        await _create_debug_run_tables(conn)


async def _create_debug_run_tables(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS debug_runs (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                source_type TEXT NOT NULL,
                analysis_id TEXT REFERENCES analyses(id),
                video_path TEXT,
                action_type TEXT NOT NULL,
                action_subtype TEXT,
                analysis_profile TEXT,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                summary JSON,
                result_json JSON,
                error_code TEXT,
                error_detail TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    columns_result = await conn.execute(text("PRAGMA table_info(debug_runs)"))
    existing_columns = {row[1] for row in columns_result.fetchall()}
    if "note" not in existing_columns:
        await conn.execute(text("ALTER TABLE debug_runs ADD COLUMN note TEXT"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_debug_runs_created_at ON debug_runs(created_at DESC)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_debug_runs_status_created_at ON debug_runs(status, created_at DESC)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_debug_runs_analysis_id ON debug_runs(analysis_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_debug_runs_mode ON debug_runs(mode)"))


async def _create_phase6_tables(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS snowball_memories (
                id TEXT PRIMARY KEY,
                skater_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                is_pinned INTEGER NOT NULL DEFAULT 0,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (skater_id) REFERENCES skaters(id)
            )
            """
        )
    )


class _noop_context:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False
