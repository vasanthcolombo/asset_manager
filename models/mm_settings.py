"""Money Manager — settings CRUD (key/value store)."""

import sqlite3


def get_mm_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM mm_settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_mm_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO mm_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
