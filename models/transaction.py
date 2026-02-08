"""Transaction CRUD operations."""

import sqlite3
from datetime import datetime


def insert_transaction(conn: sqlite3.Connection, txn: dict) -> int:
    """Insert a single transaction. Returns the new row id."""
    cursor = conn.execute(
        """
        INSERT INTO transactions (date, ticker, side, price, quantity, broker, currency,
                                  fx_rate_to_sgd, fx_rate_override, notes)
        VALUES (:date, :ticker, :side, :price, :quantity, :broker, :currency,
                :fx_rate_to_sgd, :fx_rate_override, :notes)
        """,
        {
            "date": txn["date"],
            "ticker": txn["ticker"].upper().strip(),
            "side": txn["side"].upper().strip(),
            "price": float(txn["price"]),
            "quantity": float(txn["quantity"]),
            "broker": txn["broker"].strip(),
            "currency": txn.get("currency", "USD"),
            "fx_rate_to_sgd": txn.get("fx_rate_to_sgd"),
            "fx_rate_override": txn.get("fx_rate_override"),
            "notes": txn.get("notes"),
        },
    )
    conn.commit()
    return cursor.lastrowid


def upsert_transaction(conn: sqlite3.Connection, txn: dict) -> tuple[int, str]:
    """Insert or update a transaction. Returns (row_id, 'inserted'|'updated')."""
    ticker = txn["ticker"].upper().strip()
    side = txn["side"].upper().strip()
    broker = txn["broker"].strip()
    price = float(txn["price"])
    quantity = float(txn["quantity"])
    date = txn["date"]
    currency = txn.get("currency", "USD")

    existing = conn.execute(
        """
        SELECT id FROM transactions
        WHERE date = ? AND ticker = ? AND side = ? AND broker = ? AND price = ? AND quantity = ?
        """,
        (date, ticker, side, broker, price, quantity),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE transactions
            SET price = ?, quantity = ?, currency = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (price, quantity, currency, existing["id"]),
        )
        conn.commit()
        return existing["id"], "updated"

    row_id = insert_transaction(conn, txn)
    return row_id, "inserted"


def get_transactions(
    conn: sqlite3.Connection,
    tickers: list[str] | None = None,
    brokers: list[str] | None = None,
    sides: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Query transactions with optional filters."""
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []

    if tickers:
        placeholders = ",".join("?" for _ in tickers)
        query += f" AND ticker IN ({placeholders})"
        params.extend([t.upper() for t in tickers])

    if brokers:
        placeholders = ",".join("?" for _ in brokers)
        query += f" AND broker IN ({placeholders})"
        params.extend(brokers)

    if sides:
        placeholders = ",".join("?" for _ in sides)
        query += f" AND side IN ({placeholders})"
        params.extend([s.upper() for s in sides])

    if date_from:
        query += " AND date >= ?"
        params.append(date_from)

    if date_to:
        query += " AND date <= ?"
        params.append(date_to)

    query += " ORDER BY date DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_transaction(conn: sqlite3.Connection, txn_id: int, updates: dict) -> None:
    """Update specific fields on a transaction."""
    allowed = {"date", "ticker", "side", "price", "quantity", "broker", "currency",
               "fx_rate_to_sgd", "fx_rate_override", "notes"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [txn_id]
    conn.execute(f"UPDATE transactions SET {set_clause} WHERE id = ?", values)
    conn.commit()


def delete_transaction(conn: sqlite3.Connection, txn_id: int) -> None:
    """Delete a transaction by id."""
    conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    conn.commit()


def delete_all_transactions(conn: sqlite3.Connection) -> int:
    """Delete all transactions. Returns the number of rows deleted."""
    cursor = conn.execute("DELETE FROM transactions")
    conn.commit()
    return cursor.rowcount


def get_distinct_brokers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT broker FROM transactions ORDER BY broker").fetchall()
    return [r["broker"] for r in rows]


def get_distinct_tickers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT ticker FROM transactions ORDER BY ticker").fetchall()
    return [r["ticker"] for r in rows]
