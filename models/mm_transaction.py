"""Money Manager — transaction CRUD."""

import sqlite3


def insert_mm_transaction(conn: sqlite3.Connection, txn: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO mm_transactions
            (date, type, account_id, to_account_id, category_id,
             amount, currency, fx_rate_to_default, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            txn["date"],
            txn["type"],
            txn["account_id"],
            txn.get("to_account_id"),
            txn.get("category_id"),
            txn["amount"],
            txn.get("currency", "SGD"),
            txn.get("fx_rate_to_default"),
            txn.get("notes"),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_mm_transactions(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    type_: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    where = []
    params: list = []

    if account_id is not None:
        where.append("(t.account_id = ? OR t.to_account_id = ?)")
        params.extend([account_id, account_id])
    if type_:
        where.append("t.type = ?")
        params.append(type_.upper())
    if date_from:
        where.append("t.date >= ?")
        params.append(date_from)
    if date_to:
        where.append("t.date <= ?")
        params.append(date_to)

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    limit_clause = f"LIMIT {int(limit)}" if limit else ""

    rows = conn.execute(
        f"""
        SELECT
            t.*,
            a.name  AS account_name,
            a2.name AS to_account_name,
            c.name  AS category_name,
            c.type  AS category_type
        FROM mm_transactions t
        JOIN mm_accounts a ON a.id = t.account_id
        LEFT JOIN mm_accounts a2 ON a2.id = t.to_account_id
        LEFT JOIN mm_categories c ON c.id = t.category_id
        {clause}
        ORDER BY t.date DESC, t.id DESC
        {limit_clause}
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def update_mm_transaction(
    conn: sqlite3.Connection, txn_id: int, fields: dict
) -> None:
    allowed = {
        "date", "type", "account_id", "to_account_id", "category_id",
        "amount", "currency", "fx_rate_to_default", "notes",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = "datetime('now')"
    set_clause = ", ".join(
        f"{k} = datetime('now')" if k == "updated_at" else f"{k} = ?"
        for k in updates
    )
    values = [v for k, v in updates.items() if k != "updated_at"]
    conn.execute(
        f"UPDATE mm_transactions SET {set_clause} WHERE id = ?",
        [*values, txn_id],
    )
    conn.commit()


def delete_mm_transaction(conn: sqlite3.Connection, txn_id: int) -> None:
    conn.execute("DELETE FROM mm_transactions WHERE id = ?", (txn_id,))
    conn.commit()
