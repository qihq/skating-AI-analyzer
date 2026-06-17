from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path


SOURCE_DB = Path(os.getenv("SQLITE_BACKUP_SOURCE", "/data/skating-analyzer.db"))
BACKUP_DIR = Path(os.getenv("SQLITE_BACKUP_DIR", "/backups"))
INTERVAL_SECONDS = int(os.getenv("SQLITE_BACKUP_INTERVAL_SECONDS", "86400"))
RETENTION_DAYS = int(os.getenv("SQLITE_BACKUP_RETENTION_DAYS", "7"))
MAX_ATTEMPTS = int(os.getenv("SQLITE_BACKUP_MAX_ATTEMPTS", "5"))
RETRY_SECONDS = int(os.getenv("SQLITE_BACKUP_RETRY_SECONDS", "30"))
STARTUP_DELAY_SECONDS = int(os.getenv("SQLITE_BACKUP_STARTUP_DELAY_SECONDS", "20"))


def _prune_old_backups(protected_backup: Path | None = None) -> None:
    cutoff = time.time() - RETENTION_DAYS * 86400
    for backup in BACKUP_DIR.glob("skating_*.db"):
        try:
            if protected_backup is not None and backup.name == protected_backup.name:
                continue
            if backup.stat().st_mtime < cutoff:
                backup.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"Failed to prune {backup.name}: {exc}", flush=True)


def _backup_once() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    backup_path = BACKUP_DIR / f"skating_{timestamp}.db"
    tmp_path = backup_path.with_suffix(".db.tmp")
    tmp_path.unlink(missing_ok=True)

    uri = f"file:{SOURCE_DB.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as source:
        with sqlite3.connect(tmp_path, timeout=30) as target:
            source.backup(target)
    tmp_path.replace(backup_path)
    return backup_path


def main() -> None:
    print("SQLite online backup service started", flush=True)
    if STARTUP_DELAY_SECONDS > 0:
        time.sleep(STARTUP_DELAY_SECONDS)
    while True:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                backup_path = _backup_once()
                print(f"Backup completed: {backup_path.name}", flush=True)
                _prune_old_backups(protected_backup=backup_path)
                break
            except sqlite3.Error as exc:
                print(f"Backup attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}", flush=True)
                if attempt == MAX_ATTEMPTS:
                    break
                time.sleep(RETRY_SECONDS)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
