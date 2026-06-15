from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DatabaseSqliteTests(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_connections_use_busy_timeout_and_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            os.environ["SQLITE_BUSY_TIMEOUT_SECONDS"] = "7"
            os.environ.pop("SQLITE_JOURNAL_MODE", None)
            for module_name in ["app.database", "app.models"]:
                sys.modules.pop(module_name, None)
            app_pkg = sys.modules.get("app")
            if app_pkg is not None:
                for attr in ("database", "models"):
                    if hasattr(app_pkg, attr):
                        delattr(app_pkg, attr)

            import app.database as database

            database.ensure_storage_dirs()
            await database.init_db()

            async with database.engine.begin() as conn:
                busy_timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one()
                journal_mode = str((await conn.execute(text("PRAGMA journal_mode"))).scalar_one()).lower()

            self.assertEqual(busy_timeout, 7000)
            self.assertEqual(journal_mode, "wal")
            self.assertIsInstance(database.engine.sync_engine.pool, NullPool)

    async def test_sqlite_journal_mode_can_be_overridden_for_bind_mounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            os.environ["SQLITE_BUSY_TIMEOUT_SECONDS"] = "7"
            os.environ["SQLITE_JOURNAL_MODE"] = "DELETE"
            for module_name in ["app.database", "app.models"]:
                sys.modules.pop(module_name, None)
            app_pkg = sys.modules.get("app")
            if app_pkg is not None:
                for attr in ("database", "models"):
                    if hasattr(app_pkg, attr):
                        delattr(app_pkg, attr)

            import app.database as database

            database.ensure_storage_dirs()
            await database.init_db()

            async with database.engine.begin() as conn:
                busy_timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one()
                journal_mode = str((await conn.execute(text("PRAGMA journal_mode"))).scalar_one()).lower()

            self.assertEqual(busy_timeout, 7000)
            self.assertEqual(journal_mode, "delete")

    async def test_init_db_retries_transient_sqlite_locked_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            os.environ["SQLITE_INIT_RETRY_ATTEMPTS"] = "2"
            os.environ["SQLITE_INIT_RETRY_BASE_SECONDS"] = "0"
            for module_name in ["app.database", "app.models"]:
                sys.modules.pop(module_name, None)
            app_pkg = sys.modules.get("app")
            if app_pkg is not None:
                for attr in ("database", "models"):
                    if hasattr(app_pkg, attr):
                        delattr(app_pkg, attr)

            import app.database as database

            class FakeConnection:
                executed: list[str] = []
                create_all_calls = 0

                async def execute(self, statement):
                    self.executed.append(str(statement))

                async def run_sync(self, callback):
                    self.create_all_calls += 1

            class FakeBegin:
                def __init__(self, should_fail: bool, connection: FakeConnection) -> None:
                    self.should_fail = should_fail
                    self.connection = connection

                async def __aenter__(self):
                    if self.should_fail:
                        raise OperationalError("PRAGMA journal_mode", None, Exception("database is locked"))
                    return self.connection

                async def __aexit__(self, exc_type, exc, tb) -> bool:
                    return False

            class FakeEngine:
                def __init__(self) -> None:
                    self.calls = 0
                    self.connection = FakeConnection()

                def begin(self):
                    self.calls += 1
                    return FakeBegin(self.calls == 1, self.connection)

            async def noop_sleep(seconds: float) -> None:
                return None

            async def noop_migrations(conn) -> None:
                return None

            fake_engine = FakeEngine()
            with (
                mock.patch.object(database, "engine", fake_engine),
                mock.patch.object(database, "_run_migrations", new=noop_migrations),
                mock.patch.object(database.asyncio, "sleep", new=noop_sleep),
            ):
                await database.init_db()

            self.assertEqual(fake_engine.calls, 2)
            self.assertEqual(fake_engine.connection.create_all_calls, 1)
            self.assertTrue(any("PRAGMA journal_mode" in statement for statement in fake_engine.connection.executed))

    async def test_db_write_retry_handles_transient_sqlite_disk_io_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            os.environ["SQLITE_WRITE_RETRY_ATTEMPTS"] = "2"
            os.environ["SQLITE_WRITE_RETRY_BASE_SECONDS"] = "0"
            for module_name in ["app.database", "app.models"]:
                sys.modules.pop(module_name, None)
            app_pkg = sys.modules.get("app")
            if app_pkg is not None:
                for attr in ("database", "models"):
                    if hasattr(app_pkg, attr):
                        delattr(app_pkg, attr)

            import app.database as database

            calls = 0

            async def flaky_operation() -> str:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OperationalError("COMMIT", {}, sqlite3.OperationalError("disk I/O error"))
                return "ok"

            async def noop_sleep(seconds: float) -> None:
                return None

            with mock.patch.object(database.asyncio, "sleep", new=noop_sleep):
                result = await database.run_db_write_with_retry(flaky_operation, context="unit-test")

            self.assertEqual(result, "ok")
            self.assertEqual(calls, 2)

    async def test_db_read_retry_handles_transient_sqlite_disk_io_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            os.environ["SQLITE_READ_RETRY_ATTEMPTS"] = "2"
            os.environ["SQLITE_READ_RETRY_BASE_SECONDS"] = "0"
            for module_name in ["app.database", "app.models"]:
                sys.modules.pop(module_name, None)
            app_pkg = sys.modules.get("app")
            if app_pkg is not None:
                for attr in ("database", "models"):
                    if hasattr(app_pkg, attr):
                        delattr(app_pkg, attr)

            import app.database as database

            calls = 0

            async def flaky_operation() -> str:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OperationalError("SELECT", {}, sqlite3.OperationalError("disk I/O error"))
                return "ok"

            async def noop_sleep(seconds: float) -> None:
                return None

            with mock.patch.object(database.asyncio, "sleep", new=noop_sleep):
                result = await database.run_db_read_with_retry(flaky_operation, context="unit-test")

            self.assertEqual(result, "ok")
            self.assertEqual(calls, 2)
