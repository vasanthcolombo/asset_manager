"""FX rate cache operations."""

import sqlite3


def get_cached_rate(
    conn: sqlite3.Connection, date: str, from_currency: str, to_currency: str = "SGD"
) -> float | None:
    row = conn.execute(
        """
        SELECT rate FROM fx_rate_cache
        WHERE date = ? AND from_currency = ? AND to_currency = ?
        """,
        (date, from_currency.upper(), to_currency.upper()),
    ).fetchone()
    return row["rate"] if row else None


def store_rate(
    conn: sqlite3.Connection,
    date: str,
    from_currency: str,
    to_currency: str,
    rate: float,
    source: str = "yfinance",
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO fx_rate_cache (date, from_currency, to_currency, rate, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (date, from_currency.upper(), to_currency.upper(), rate, source),
    )
    conn.commit()


def get_cached_ticker_metadata(conn: sqlite3.Connection, ticker: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ticker_metadata_cache WHERE ticker = ?", (ticker.upper(),)
    ).fetchone()
    return dict(row) if row else None


def store_ticker_metadata(conn: sqlite3.Connection, ticker: str, metadata: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO ticker_metadata_cache (ticker, currency, country, exchange, name, sector, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            ticker.upper(),
            metadata.get("currency"),
            metadata.get("country"),
            metadata.get("exchange"),
            metadata.get("name"),
            metadata.get("sector"),
        ),
    )
    conn.commit()


def get_cached_price(conn: sqlite3.Connection, ticker: str) -> dict | None:
    row = conn.execute(
        """
        SELECT price, currency, fetched_at FROM price_cache
        WHERE ticker = ?
        AND (julianday('now') - julianday(fetched_at)) * 86400 < 300
        """,
        (ticker.upper(),),
    ).fetchone()
    return dict(row) if row else None


def store_price(conn: sqlite3.Connection, ticker: str, price: float, currency: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO price_cache (ticker, price, currency, fetched_at)
        VALUES (?, ?, ?, datetime('now'))
        """,
        (ticker.upper(), price, currency),
    )
    conn.commit()
