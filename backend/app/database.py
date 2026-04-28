from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


DEFAULT_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).resolve().parents[2] / "data"
DATA_DIR = Path(os.getenv("DATA_DIR", str(DEFAULT_DATA_DIR)))
UPLOADS_DIR = DATA_DIR / "uploads"
ARCHIVE_DIR = DATA_DIR / "archive"
BACKUPS_DIR = Path("/backups") if Path("/backups").exists() else Path(__file__).resolve().parents[2] / "backups"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR / 'skating-analyzer.db'}")


class Base(DeclarativeBase):
    pass


engine = create_async_engine(DATABASE_URL, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


def ensure_storage_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
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
        ("vision_structured", "JSON"),
        ("pose_data", "JSON"),
        ("bio_data", "JSON"),
        ("frame_motion_scores", "JSON"),
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
