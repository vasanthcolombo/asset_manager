"""Money Manager — account group and account CRUD."""

import sqlite3


# ── Account Groups ────────────────────────────────────────────────────────────

def get_account_groups(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM mm_account_groups ORDER BY sort_order, name"
    ).fetchall()
    return [dict(r) for r in rows]


def create_account_group(conn: sqlite3.Connection, name: str, group_type: str) -> int:
    cursor = conn.execute(
        "INSERT INTO mm_account_groups (name, group_type, is_predefined) VALUES (?, ?, 0)",
        (name.strip(), group_type.upper()),
    )
    conn.commit()
    return cursor.lastrowid


def delete_account_group(conn: sqlite3.Connection, group_id: int) -> None:
    """Delete a user-defined account group (predefined groups are protected)."""
    conn.execute(
        "DELETE FROM mm_account_groups WHERE id = ? AND is_predefined = 0",
        (group_id,),
    )
    conn.commit()


# ── Accounts ──────────────────────────────────────────────────────────────────

def get_accounts(
    conn: sqlite3.Connection,
    group_id: int | None = None,
    active_only: bool = True,
) -> list[dict]:
    where = []
    params: list = []
    if group_id is not None:
        where.append("a.group_id = ?")
        params.append(group_id)
    if active_only:
        where.append("a.is_active = 1")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"""
        SELECT a.*, g.name AS group_name, g.group_type
        FROM mm_accounts a
        JOIN mm_account_groups g ON g.id = a.group_id
        {clause}
        ORDER BY g.sort_order, g.name, a.name
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def get_account_by_id(conn: sqlite3.Connection, account_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT a.*, g.name AS group_name, g.group_type
        FROM mm_accounts a
        JOIN mm_account_groups g ON g.id = a.group_id
        WHERE a.id = ?
        """,
        (account_id,),
    ).fetchone()
    return dict(row) if row else None


def create_account(
    conn: sqlite3.Connection,
    group_id: int,
    name: str,
    currency: str = "SGD",
    initial_balance: float = 0.0,
    broker_name: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO mm_accounts (group_id, name, currency, initial_balance, broker_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        (group_id, name.strip(), currency.upper().strip(), initial_balance, broker_name),
    )
    conn.commit()
    return cursor.lastrowid


def update_account(conn: sqlite3.Connection, account_id: int, **fields) -> None:
    allowed = {"name", "currency", "initial_balance", "broker_name", "is_active"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE mm_accounts SET {set_clause} WHERE id = ?",
        [*updates.values(), account_id],
    )
    conn.commit()


def delete_account(conn: sqlite3.Connection, account_id: int) -> None:
    conn.execute("DELETE FROM mm_accounts WHERE id = ?", (account_id,))
    conn.commit()
