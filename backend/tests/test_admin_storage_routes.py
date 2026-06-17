from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class AdminStorageRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_info_runs_directory_size_scans_off_event_loop(self) -> None:
        from app.routers import skaters

        calls: list[object] = []

        async def fake_to_thread(func, *args):
            calls.append((func, args))
            return 123 if args and args[0] == skaters.DATA_DIR / "skating-analyzer.db" else 456

        with patch.object(skaters.asyncio, "to_thread", new=fake_to_thread):
            payload = await skaters.get_system_info()

        self.assertEqual(payload.db_size_bytes, 123)
        self.assertEqual(payload.uploads_size_bytes, 456)
        self.assertEqual(
            calls,
            [
                (skaters.directory_size_bytes, (skaters.DATA_DIR / "skating-analyzer.db",)),
                (skaters.directory_size_bytes, (skaters.UPLOADS_DIR,)),
            ],
        )

    async def test_storage_stats_runs_recursive_scan_off_event_loop(self) -> None:
        from app.routers import skaters

        to_thread_mock = AsyncMock(
            return_value={
                "uploads_mb": 1.0,
                "archive_mb": 2.0,
                "backups_mb": 3.0,
                "total_mb": 6.0,
                "archived_count": 4,
            }
        )

        with patch.object(skaters.asyncio, "to_thread", to_thread_mock):
            payload = await skaters.get_storage_stats()

        to_thread_mock.assert_awaited_once_with(skaters.build_storage_stats)
        self.assertEqual(payload.total_mb, 6.0)
        self.assertEqual(payload.archived_count, 4)

    async def test_backup_routes_run_file_operations_off_event_loop(self) -> None:
        from app.routers import skaters
        from app.schemas import BackupCreateRequest, BackupRestoreRequest

        async def fake_to_thread(func, *args):
            if func is skaters.list_backups:
                return [{"filename": "one.zip", "size_bytes": 10, "created_at": "2026-06-08T00:00:00+00:00"}]
            if func is skaters.create_manual_backup:
                return Path("/backups/manual.zip")
            if func is skaters.restore_backup:
                return Path("/backups/manual.zip")
            raise AssertionError(func)

        with patch.object(skaters.asyncio, "to_thread", new=fake_to_thread):
            backups = await skaters.get_backups()
            created = await skaters.create_backup(BackupCreateRequest(label="manual"))
            restored = await skaters.restore_backup_route(BackupRestoreRequest(filename="manual.zip"))

        self.assertEqual(backups.items[0].filename, "one.zip")
        self.assertEqual(created.filename, "manual.zip")
        self.assertEqual(restored.filename, "manual.zip")


if __name__ == "__main__":
    unittest.main()
