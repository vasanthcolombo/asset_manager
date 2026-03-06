"""Portfolio Manager — broker CRUD."""

import sqlite3


def get_pm_brokers(conn: sqlite3.Connection) -> list[str]:
    """Return broker names sorted alphabetically."""
    rows = conn.execute("SELECT name FROM pm_brokers ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def add_pm_broker(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("INSERT INTO pm_brokers (name) VALUES (?)", (name.strip(),))
    conn.commit()


def delete_pm_broker(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM pm_brokers WHERE name = ?", (name,))
    conn.commit()
