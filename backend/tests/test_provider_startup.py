from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


class ProviderStartupTests(unittest.TestCase):
    def _run_startup_script(self, tmpdir: str, script_body: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["DATA_DIR"] = tmpdir
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tmpdir) / 'test.db'}"
        env["SECRET_KEY"] = "test-secret-key"
        body = textwrap.indent(textwrap.dedent(script_body).strip(), "    ")
        script = "\n".join(
            [
                "import asyncio",
                "import sys",
                "from sqlalchemy import func, select",
                "",
                f"sys.path.insert(0, {str(BACKEND_DIR)!r})",
                "",
                "async def run():",
                body,
                "",
                "asyncio.run(run())",
            ]
        )
        return subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            text=True,
            capture_output=True,
            timeout=90,
        )

    def test_startup_does_not_seed_ai_providers_on_clean_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_startup_script(
                tmpdir,
                """
                import app.main as main
                import app.database as database
                import app.models as models

                async with main.lifespan(main.app):
                    async with database.AsyncSessionLocal() as session:
                        count = await session.scalar(select(func.count()).select_from(models.AIProvider))

                await database.engine.dispose()
                assert count == 0, count
                """,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_startup_ignores_duplicate_legacy_ai_provider_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_startup_script(
                tmpdir,
                """
                import app.database as database
                import app.models as models

                database.ensure_storage_dirs()
                await database.init_db()
                async with database.AsyncSessionLocal() as session:
                    session.add_all(
                        [
                            models.AIProvider(
                                slot="vision",
                                name="Qwen legacy duplicate A",
                                provider="qwen",
                                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                                model_id="qwen3.6-plus",
                                api_key="",
                                is_active=True,
                                notes="系统预置",
                            ),
                            models.AIProvider(
                                slot="vision",
                                name="Qwen legacy duplicate B",
                                provider="qwen",
                                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                                model_id="qwen3.6-plus",
                                api_key="",
                                is_active=True,
                                notes="系统预置",
                            ),
                        ]
                    )
                    await session.commit()

                import app.main as main

                async with main.lifespan(main.app):
                    async with database.AsyncSessionLocal() as session:
                        count = await session.scalar(select(func.count()).select_from(models.AIProvider))

                await database.engine.dispose()
                assert count == 2, count
                """,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
