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
    """
    CREATE TABLE IF NOT EXISTS historical_price_cache (
        ticker          TEXT NOT NULL,
        date            TEXT NOT NULL,
        close_price     REAL NOT NULL,
        currency        TEXT,
        PRIMARY KEY (ticker, date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_hpc_ticker ON historical_price_cache(ticker)",
    """
    CREATE TABLE IF NOT EXISTS performance_cache (
        cache_key               TEXT PRIMARY KEY,
        data_json               TEXT NOT NULL,
        transaction_fingerprint TEXT NOT NULL,
        cached_at               TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── Money Manager tables ──────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS mm_account_groups (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL UNIQUE,
        group_type    TEXT NOT NULL DEFAULT 'ASSET' CHECK(group_type IN ('ASSET','LIABILITY')),
        is_predefined INTEGER NOT NULL DEFAULT 0,
        sort_order    INTEGER NOT NULL DEFAULT 999
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mm_accounts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id        INTEGER NOT NULL REFERENCES mm_account_groups(id) ON DELETE CASCADE,
        name            TEXT NOT NULL,
        currency        TEXT NOT NULL DEFAULT 'SGD',
        initial_balance REAL NOT NULL DEFAULT 0.0,
        broker_name     TEXT,
        is_active       INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(group_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mm_categories (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        type          TEXT NOT NULL CHECK(type IN ('INCOME','EXPENSE')),
        parent_id     INTEGER REFERENCES mm_categories(id) ON DELETE CASCADE,
        is_predefined INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mm_cat_unique ON mm_categories(name, type, COALESCE(parent_id, 0))",
    """
    CREATE TABLE IF NOT EXISTS mm_transactions (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        date               TEXT NOT NULL,
        type               TEXT NOT NULL CHECK(type IN ('INCOME','EXPENSE','TRANSFER')),
        account_id         INTEGER NOT NULL REFERENCES mm_accounts(id),
        to_account_id      INTEGER REFERENCES mm_accounts(id),
        category_id        INTEGER REFERENCES mm_categories(id),
        amount             REAL NOT NULL,
        currency           TEXT NOT NULL DEFAULT 'SGD',
        fx_rate_to_default REAL,
        notes              TEXT,
        created_at         TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mm_txn_date    ON mm_transactions(date)",
    "CREATE INDEX IF NOT EXISTS idx_mm_txn_account ON mm_transactions(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_mm_txn_type    ON mm_transactions(type)",
]

_MM_ACCOUNT_GROUPS = [
    ("Cash",       "ASSET",     1, 1),
    ("Accounts",   "ASSET",     1, 2),
    ("Card",       "LIABILITY", 1, 3),
    ("Investment", "ASSET",     1, 4),
    ("Loan",       "LIABILITY", 1, 5),
    ("Property",   "ASSET",     1, 6),
    ("Retirement", "ASSET",     1, 7),
]

_MM_CATEGORIES = [
    # (name, type, is_predefined)
    ("Food",           "EXPENSE", 1),
    ("Entertainment",  "EXPENSE", 1),
    ("Transportation", "EXPENSE", 1),
    ("Shopping",       "EXPENSE", 1),
    ("Health",         "EXPENSE", 1),
    ("Utilities",      "EXPENSE", 1),
    ("Others",         "EXPENSE", 1),
    ("Salary",         "INCOME",  1),
    ("Bonus",          "INCOME",  1),
    ("Interest",       "INCOME",  1),
    ("Rental",         "INCOME",  1),
    ("Others",         "INCOME",  1),
]


def _seed_mm_defaults(conn: sqlite3.Connection) -> None:
    """Insert predefined Money Manager account groups and categories (idempotent)."""
    conn.executemany(
        "INSERT OR IGNORE INTO mm_account_groups (name, group_type, is_predefined, sort_order) VALUES (?,?,?,?)",
        _MM_ACCOUNT_GROUPS,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO mm_categories (name, type, is_predefined) VALUES (?,?,?)",
        _MM_CATEGORIES,
    )
    conn.commit()


def initialize_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    cursor = conn.cursor()
    for ddl in TABLES:
        cursor.execute(ddl)
    conn.commit()
    _seed_mm_defaults(conn)
