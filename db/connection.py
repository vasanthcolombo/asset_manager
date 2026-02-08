"""SQLite connection factory."""

import sqlite3
import os
from config import DB_PATH


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode and row factory enabled."""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
