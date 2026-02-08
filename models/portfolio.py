"""Custom portfolio CRUD operations."""

import sqlite3


def create_portfolio(conn: sqlite3.Connection, name: str, description: str = "") -> int:
    """Create a custom portfolio. Returns the new id."""
    cursor = conn.execute(
        "INSERT INTO custom_portfolios (name, description) VALUES (?, ?)",
        (name, description),
    )
    conn.commit()
    return cursor.lastrowid


def get_portfolios(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM custom_portfolios ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_portfolio_by_id(conn: sqlite3.Connection, portfolio_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM custom_portfolios WHERE id = ?", (portfolio_id,)
    ).fetchone()
    return dict(row) if row else None


def delete_portfolio(conn: sqlite3.Connection, portfolio_id: int) -> None:
    conn.execute("DELETE FROM custom_portfolios WHERE id = ?", (portfolio_id,))
    conn.commit()


def add_rule(conn: sqlite3.Connection, portfolio_id: int, rule_type: str, rule_value: str) -> int:
    """Add a rule (BROKER or TICKER) to a custom portfolio."""
    cursor = conn.execute(
        "INSERT INTO custom_portfolio_rules (portfolio_id, rule_type, rule_value) VALUES (?, ?, ?)",
        (portfolio_id, rule_type.upper(), rule_value.upper().strip()),
    )
    conn.commit()
    return cursor.lastrowid


def get_rules(conn: sqlite3.Connection, portfolio_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM custom_portfolio_rules WHERE portfolio_id = ? ORDER BY rule_type, rule_value",
        (portfolio_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.execute("DELETE FROM custom_portfolio_rules WHERE id = ?", (rule_id,))
    conn.commit()


def clear_rules(conn: sqlite3.Connection, portfolio_id: int) -> None:
    conn.execute("DELETE FROM custom_portfolio_rules WHERE portfolio_id = ?", (portfolio_id,))
    conn.commit()


def get_portfolio_filters(conn: sqlite3.Connection, portfolio_id: int) -> dict:
    """Return broker and ticker filters for a custom portfolio."""
    rules = get_rules(conn, portfolio_id)
    brokers = [r["rule_value"] for r in rules if r["rule_type"] == "BROKER"]
    tickers = [r["rule_value"] for r in rules if r["rule_type"] == "TICKER"]
    return {"brokers": brokers or None, "tickers": tickers or None}
