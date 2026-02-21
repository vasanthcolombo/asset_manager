"""Market data service wrapping yfinance."""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
from models.fx_rate import (
    get_cached_ticker_metadata,
    store_ticker_metadata,
    get_cached_price,
    store_price,
)
from config import EXCHANGE_TO_COUNTRY, SUFFIX_TO_COUNTRY

# Suffix -> (currency, country) for instant detection (no API call)
_SUFFIX_MAP = {
    ".SI": ("SGD", "SG"),
    ".HK": ("HKD", "HK"),
    ".L": ("GBP", "GB"),
    ".AX": ("AUD", "AU"),
    ".TO": ("CAD", "CA"),
    ".T": ("JPY", "JP"),
}


def _detect_from_suffix(ticker: str) -> tuple[str, str] | None:
    """Detect currency and country from ticker suffix. Returns None if unknown."""
    for suffix, (currency, country) in _SUFFIX_MAP.items():
        if ticker.upper().endswith(suffix):
            return currency, country
    return None


def get_ticker_info(conn: sqlite3.Connection, ticker: str) -> dict:
    """Get ticker metadata. Suffix-first detection avoids slow yfinance .info calls."""
    ticker = ticker.upper().strip()

    # 1. Check DB cache (instant)
    cached = get_cached_ticker_metadata(conn, ticker)
    if cached and cached.get("currency"):
        return cached

    # 2. Fast path: detect from suffix (no API call)
    suffix_result = _detect_from_suffix(ticker)
    if suffix_result:
        currency, country = suffix_result
        metadata = {
            "currency": currency,
            "country": country,
            "exchange": "",
            "name": ticker,
            "sector": "",
        }
        store_ticker_metadata(conn, ticker, metadata)
        return metadata

    # 3. Slow path: call yfinance only for US / unknown-suffix tickers
    try:
        t = yf.Ticker(ticker)
        info = t.info
        exchange = info.get("exchange", "")
        country = EXCHANGE_TO_COUNTRY.get(exchange, "US")

        metadata = {
            "currency": info.get("currency", "USD"),
            "country": country,
            "exchange": exchange,
            "name": info.get("shortName", info.get("longName", ticker)),
            "sector": info.get("sector", ""),
        }
        store_ticker_metadata(conn, ticker, metadata)
        return metadata
    except Exception:
        metadata = {
            "currency": "USD",
            "country": "US",
            "exchange": "",
            "name": ticker,
            "sector": "",
        }
        store_ticker_metadata(conn, ticker, metadata)
        return metadata


def get_live_price(conn: sqlite3.Connection, ticker: str) -> dict:
    """Get the current live price for a ticker. Returns {price, currency, error}."""
    ticker = ticker.upper().strip()

    # Check short-lived cache (5 min TTL in DB)
    cached = get_cached_price(conn, ticker)
    if cached:
        return {"price": cached["price"], "currency": cached["currency"], "error": None}

    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price = fi.get("lastPrice", None)
        if price is None:
            # Fallback to slower .info only if fast_info failed
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0

        meta = get_ticker_info(conn, ticker)
        currency = meta.get("currency", "USD")

        store_price(conn, ticker, price, currency)
        return {"price": price, "currency": currency, "error": None}
    except Exception as e:
        # Even on error, use suffix-detected currency
        meta = get_ticker_info(conn, ticker)
        return {"price": 0.0, "currency": meta.get("currency", "USD"), "error": str(e)}


def get_live_prices_batch(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, dict]:
    """Get live prices for multiple tickers using a single yf.download() call."""
    tickers = [t.upper().strip() for t in tickers]
    results = {}

    # Separate cached from uncached
    uncached = []
    for t in tickers:
        cached = get_cached_price(conn, t)
        if cached:
            results[t] = {"price": cached["price"], "currency": cached["currency"], "error": None}
        else:
            uncached.append(t)

    if not uncached:
        return results

    # Batch download all uncached tickers in one API call
    try:
        df = yf.download(uncached, period="1d", progress=False, threads=True)
        if df.empty:
            raise ValueError("Empty result")

        if len(uncached) == 1:
            # Single ticker: df has simple columns
            ticker = uncached[0]
            price = float(df["Close"].iloc[-1]) if "Close" in df.columns and len(df) > 0 else 0.0
            meta = get_ticker_info(conn, ticker)
            currency = meta.get("currency", "USD")
            store_price(conn, ticker, price, currency)
            results[ticker] = {"price": price, "currency": currency, "error": None}
        else:
            # Multi-ticker: df has MultiIndex columns (metric, ticker)
            for ticker in uncached:
                try:
                    price = float(df["Close"][ticker].iloc[-1])
                    meta = get_ticker_info(conn, ticker)
                    currency = meta.get("currency", "USD")
                    store_price(conn, ticker, price, currency)
                    results[ticker] = {"price": price, "currency": currency, "error": None}
                except Exception:
                    meta = get_ticker_info(conn, ticker)
                    results[ticker] = {"price": 0.0, "currency": meta.get("currency", "USD"), "error": "No data"}
    except Exception:
        # Fallback to individual fetches
        for ticker in uncached:
            results[ticker] = get_live_price(conn, ticker)

    return results


def get_historical_prices(ticker: str, start: str, end: str | None = None) -> pd.DataFrame:
    """Get historical OHLCV data. Returns DataFrame with tz-naive DatetimeIndex."""
    if end is None:
        end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        t = yf.Ticker(ticker.upper().strip())
        hist = t.history(start=start, end=end, auto_adjust=True)
        if not hist.empty and hist.index.tz is not None:
            hist.index = hist.index.tz_localize(None)
        return hist
    except Exception:
        return pd.DataFrame()


def get_cached_historical_prices(
    conn, ticker: str, start: str, end: str | None = None
) -> pd.DataFrame:
    """
    Get historical close prices using DB cache.
    Fetches from yfinance only when cache is stale (last cached date < yesterday).
    Returns a DataFrame with DatetimeIndex and a 'Close' column.
    """
    ticker = ticker.upper().strip()
    if end is None:
        end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Check cache coverage: do we have data up to at least yesterday?
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    last_row = conn.execute(
        "SELECT MAX(date) as last_date FROM historical_price_cache WHERE ticker = ? AND date >= ?",
        (ticker, start),
    ).fetchone()
    last_cached = last_row["last_date"] if last_row else None

    if not last_cached or last_cached < yesterday:
        # Fetch fresh from yfinance and upsert into cache
        fresh = get_historical_prices(ticker, start=start, end=end)
        if not fresh.empty and "Close" in fresh.columns:
            rows_to_insert = [
                (ticker, ts.strftime("%Y-%m-%d"), float(row["Close"]), None)
                for ts, row in fresh.iterrows()
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO historical_price_cache (ticker, date, close_price, currency) "
                "VALUES (?, ?, ?, ?)",
                rows_to_insert,
            )
            conn.commit()
        return fresh

    # Return from DB cache
    rows = conn.execute(
        "SELECT date, close_price FROM historical_price_cache "
        "WHERE ticker = ? AND date >= ? AND date <= ? ORDER BY date",
        (ticker, start, end),
    ).fetchall()
    if not rows:
        return pd.DataFrame()
    dates = [pd.Timestamp(r["date"]) for r in rows]
    closes = [r["close_price"] for r in rows]
    df = pd.DataFrame({"Close": closes}, index=dates)
    return df


def get_dividends(ticker: str, start: str, end: str | None = None) -> pd.Series:
    """Get dividend history for a ticker. Returns Series with tz-naive DatetimeIndex."""
    if end is None:
        end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        t = yf.Ticker(ticker.upper().strip())
        divs = t.dividends
        if divs.empty:
            return divs
        # Normalize to tz-naive so comparisons work
        if divs.index.tz is not None:
            divs.index = divs.index.tz_localize(None)
        # Filter by date range
        mask = divs.index >= pd.Timestamp(start)
        if end:
            mask &= divs.index <= pd.Timestamp(end)
        return divs[mask]
    except Exception:
        return pd.Series(dtype=float)


def _guess_country_from_suffix(ticker: str) -> str:
    """Guess country from ticker suffix."""
    for suffix, country in SUFFIX_TO_COUNTRY.items():
        if ticker.endswith(suffix):
            return country
    return "US"


def _fallback_currency(ticker: str) -> tuple[str, str]:
    """Fallback currency detection from ticker suffix."""
    result = _detect_from_suffix(ticker)
    return result if result else ("USD", "US")
