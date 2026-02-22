"""Money Manager — category CRUD."""

import sqlite3


def get_categories(
    conn: sqlite3.Connection,
    type_: str | None = None,
) -> list[dict]:
    """Return flat list of categories, optionally filtered by type (INCOME/EXPENSE)."""
    where = []
    params: list = []
    if type_:
        where.append("type = ?")
        params.append(type_.upper())
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT * FROM mm_categories {clause} ORDER BY type, parent_id NULLS FIRST, name",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def create_category(
    conn: sqlite3.Connection,
    name: str,
    type_: str,
    parent_id: int | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO mm_categories (name, type, parent_id, is_predefined) VALUES (?, ?, ?, 0)",
        (name.strip(), type_.upper(), parent_id),
    )
    conn.commit()
    return cursor.lastrowid


def delete_category(conn: sqlite3.Connection, category_id: int) -> None:
    """Delete a user-defined category (predefined categories are protected)."""
    conn.execute(
        "DELETE FROM mm_categories WHERE id = ? AND is_predefined = 0",
        (category_id,),
    )
    conn.commit()
