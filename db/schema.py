"""Database schema DDL and initialization."""

import sqlite3

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        ticker          TEXT NOT NULL,
        side            TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
        price           REAL NOT NULL,
        quantity        REAL NOT NULL,
        broker          TEXT NOT NULL,
        currency        TEXT NOT NULL DEFAULT 'USD',
        fx_rate_to_sgd  REAL,
        fx_rate_override REAL,
        notes           TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(date, ticker, side, broker, price, quantity)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_txn_ticker ON transactions(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_txn_broker ON transactions(broker)",
    "CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date)",
    """
    CREATE TABLE IF NOT EXISTS custom_portfolios (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        description TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS custom_portfolio_rules (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        portfolio_id    INTEGER NOT NULL REFERENCES custom_portfolios(id) ON DELETE CASCADE,
        rule_type       TEXT NOT NULL CHECK(rule_type IN ('BROKER','TICKER')),
        rule_value      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cpr_portfolio ON custom_portfolio_rules(portfolio_id)",
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker      TEXT NOT NULL UNIQUE,
        added_at    TEXT NOT NULL DEFAULT (datetime('now')),
        notes       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fx_rate_cache (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        date            TEXT NOT NULL,
        from_currency   TEXT NOT NULL,
        to_currency     TEXT NOT NULL DEFAULT 'SGD',
        rate            REAL NOT NULL,
        source          TEXT NOT NULL DEFAULT 'yfinance',
        fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(date, from_currency, to_currency)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ticker_metadata_cache (
        ticker          TEXT PRIMARY KEY,
        currency        TEXT,
        country         TEXT,
        exchange        TEXT,
        name            TEXT,
        sector          TEXT,
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dividend_cache (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT NOT NULL,
        ex_date         TEXT NOT NULL,
        amount          REAL NOT NULL,
        currency        TEXT NOT NULL,
        fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(ticker, ex_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_cache (
        ticker          TEXT PRIMARY KEY,
        price           REAL NOT NULL,
        currency        TEXT NOT NULL,
        fetched_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]


def initialize_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    cursor = conn.cursor()
    for ddl in TABLES:
        cursor.execute(ddl)
    conn.commit()
