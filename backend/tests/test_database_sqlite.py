from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DatabaseSqliteTests(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_connections_use_busy_timeout_and_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATA_DIR"] = tmpdir
            os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
            os.environ["SQLITE_BUSY_TIMEOUT_SECONDS"] = "7"
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
