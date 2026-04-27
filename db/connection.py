"""SQLite connection factory — with optional Google Drive sync."""

import sqlite3
import os
from config import DB_PATH


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """
    Get a SQLite connection with WAL mode and row factory enabled.

    If DRIVE_FILE_ID is set, downloads the DB from Google Drive before
    opening and patches conn.commit() to upload after every write.
    """
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # --- Google Drive sync (no-op when DRIVE_FILE_ID not set) ---
    try:
        from db.drive_sync import download_db, make_syncing_connection
        download_db(path)          # downloads if DRIVE_FILE_ID is set
    except ImportError:
        make_syncing_connection = None  # type: ignore

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Patch commit() to auto-upload on every write
    try:
        from db.drive_sync import make_syncing_connection as _patch
        _patch(conn, path)
    except Exception:
        pass

    return conn
