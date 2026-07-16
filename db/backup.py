"""SQLite backup and restore helpers for operational recovery."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db.database import initialize_database


class DatabaseBackupError(RuntimeError):
    """A controlled SQLite backup or restore failure."""


def backup_database(source_path: str | Path, backup_path: str | Path) -> Path:
    """Create a consistent SQLite backup without copying environment files."""
    source = Path(source_path).expanduser().resolve()
    destination = Path(backup_path).expanduser().resolve()
    if not source.is_file():
        raise DatabaseBackupError("Source database does not exist.")
    if source == destination:
        raise DatabaseBackupError("Backup destination must differ from the source database.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
            source_db.backup(backup_db)
    except sqlite3.Error as exc:
        raise DatabaseBackupError("SQLite backup failed.") from exc
    return destination


def restore_database(backup_path: str | Path, destination_path: str | Path) -> Path:
    """Restore a backup and apply backward-compatible initialization only."""
    backup = Path(backup_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    if not backup.is_file():
        raise DatabaseBackupError("Backup database does not exist.")
    if backup == destination:
        raise DatabaseBackupError("Restore destination must differ from the backup database.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(backup) as backup_db, sqlite3.connect(destination) as destination_db:
            backup_db.backup(destination_db)
    except sqlite3.Error as exc:
        raise DatabaseBackupError("SQLite restore failed.") from exc
    initialize_database(destination)
    return destination
