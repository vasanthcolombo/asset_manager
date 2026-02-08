"""Watchlist CRUD operations."""

import sqlite3


def add_to_watchlist(conn: sqlite3.Connection, ticker: str, notes: str = "") -> int:
    cursor = conn.execute(
        "INSERT OR IGNORE INTO watchlist (ticker, notes) VALUES (?, ?)",
        (ticker.upper().strip(), notes),
    )
    conn.commit()
    return cursor.lastrowid


def get_watchlist(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM watchlist ORDER BY ticker").fetchall()
    return [dict(r) for r in rows]


def remove_from_watchlist(conn: sqlite3.Connection, ticker: str) -> None:
    conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper().strip(),))
    conn.commit()


def update_watchlist_notes(conn: sqlite3.Connection, ticker: str, notes: str) -> None:
    conn.execute(
        "UPDATE watchlist SET notes = ? WHERE ticker = ?",
        (notes, ticker.upper().strip()),
    )
    conn.commit()
