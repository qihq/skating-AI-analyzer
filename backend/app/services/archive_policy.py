from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.database import ARCHIVE_DIR, BACKUPS_DIR, DATA_DIR, UPLOADS_DIR


ARCHIVE_DAYS = 90
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv"}
BACKUP_DATETIME_FORMAT = "%Y%m%d-%H%M%S"
BACKUP_FILENAME_PREFIX = "skating-analyzer-backup-"
BACKUP_RETENTION = 20
logger = logging.getLogger(__name__)


def _as_utc_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def directory_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total_bytes = 0
    for child in path.rglob("*"):
        if child.is_file():
            total_bytes += child.stat().st_size
    return round(total_bytes / (1024 * 1024), 1)


def count_archived_items() -> int:
    if not ARCHIVE_DIR.exists():
        return 0
    return sum(1 for child in ARCHIVE_DIR.iterdir() if child.is_dir())


def _backup_file_path(label: str | None = None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime(BACKUP_DATETIME_FORMAT)
    suffix = f"-{label.strip()}" if label and label.strip() else ""
    safe_suffix = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in suffix)
    return BACKUPS_DIR / f"{BACKUP_FILENAME_PREFIX}{timestamp}{safe_suffix}.zip"


def _iter_backup_files() -> list[Path]:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        [path for path in BACKUPS_DIR.glob(f"{BACKUP_FILENAME_PREFIX}*.zip") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _write_directory_to_zip(archive: ZipFile, source_dir: Path, archive_root: Path) -> None:
    if not source_dir.exists():
        return

    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        archive.write(path, arcname=str(archive_root / path.relative_to(source_dir)))


def create_manual_backup(label: str | None = None) -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = _backup_file_path(label)

    with ZipFile(backup_path, "w", compression=ZIP_DEFLATED) as archive:
        _write_directory_to_zip(archive, DATA_DIR, Path("data"))

    _prune_old_backups()
    logger.info("Created manual backup %s", backup_path)
    return backup_path


def list_backups() -> list[dict[str, str | int]]:
    items: list[dict[str, str | int]] = []
    for path in _iter_backup_files():
        stat = path.stat()
        items.append(
            {
                "filename": path.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return items


def restore_backup(filename: str) -> Path:
    candidate = (BACKUPS_DIR / filename).resolve()
    backups_root = BACKUPS_DIR.resolve()
    if backups_root not in candidate.parents or not candidate.exists() or candidate.suffix.lower() != ".zip":
        raise FileNotFoundError("未找到指定备份文件。")

    staging_dir = BACKUPS_DIR / f".restore-{candidate.stem}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        with ZipFile(candidate, "r") as archive:
            archive.extractall(staging_dir)

        restored_data_dir = staging_dir / "data"
        if not restored_data_dir.exists():
            raise FileNotFoundError("备份文件缺少 data 目录，无法恢复。")

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for child in DATA_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

        for child in restored_data_dir.iterdir():
            destination = DATA_DIR / child.name
            if child.is_dir():
                shutil.copytree(child, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(child, destination)

        logger.info("Restored backup %s", candidate)
        return candidate
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _prune_old_backups() -> None:
    backups = _iter_backup_files()
    for obsolete in backups[BACKUP_RETENTION:]:
        obsolete.unlink(missing_ok=True)


async def run_archive_policy() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for upload_dir in UPLOADS_DIR.iterdir() if UPLOADS_DIR.exists() else []:
        if not upload_dir.is_dir():
            continue

        modified_at = _as_utc_datetime(upload_dir.stat().st_mtime)
        if modified_at > cutoff:
            continue

        archived_any = False
        for item in upload_dir.iterdir():
            if item.is_dir() or item.suffix.lower() not in VIDEO_SUFFIXES:
                continue

            destination_dir = ARCHIVE_DIR / upload_dir.name
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination_path = destination_dir / item.name
            shutil.move(str(item), str(destination_path))
            archived_any = True
            logger.info("Archived original video %s -> %s", item, destination_path)

        if archived_any:
            logger.info("Archive policy processed upload directory %s", upload_dir)


def build_storage_stats() -> dict[str, float | int]:
    uploads_mb = directory_size_mb(UPLOADS_DIR)
    archive_mb = directory_size_mb(ARCHIVE_DIR)
    backups_mb = directory_size_mb(BACKUPS_DIR)
    total_mb = round(uploads_mb + archive_mb + backups_mb, 1)
    return {
        "uploads_mb": uploads_mb,
        "archive_mb": archive_mb,
        "backups_mb": backups_mb,
        "total_mb": total_mb,
        "archived_count": count_archived_items(),
    }
