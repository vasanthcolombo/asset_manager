"""FX rate service: historical rates, live rates, caching."""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import sqlite3
from models.fx_rate import get_cached_rate, store_rate
from config import BASE_CURRENCY


def get_fx_rate(
    conn: sqlite3.Connection, from_currency: str, to_currency: str, date: str
) -> float:
    """Get the FX rate for a specific date. Uses cache, falls back to yfinance."""
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return 1.0

    # Check cache
    cached = get_cached_rate(conn, date, from_currency, to_currency)
    if cached is not None:
        return cached

    # Fetch from yfinance
    rate = _fetch_fx_rate_yfinance(from_currency, to_currency, date)
    if rate is not None:
        store_rate(conn, date, from_currency, to_currency, rate)
        return rate

    # Try triangulation through USD
    if from_currency != "USD" and to_currency != "USD":
        rate1 = get_fx_rate(conn, from_currency, "USD", date)
        rate2 = get_fx_rate(conn, "USD", to_currency, date)
        if rate1 and rate2:
            rate = rate1 * rate2
            store_rate(conn, date, from_currency, to_currency, rate)
            return rate

    return 1.0  # Last resort fallback


def get_live_fx_rate(from_currency: str, to_currency: str) -> float:
    """Get the current live FX rate."""
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return 1.0

    pair = f"{from_currency}{to_currency}=X"
    try:
        t = yf.Ticker(pair)
        fi = t.fast_info
        price = fi.get("lastPrice", None)
        if price and price > 0:
            return float(price)
        # Fallback to history
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass

    # Try triangulation
    if from_currency != "USD" and to_currency != "USD":
        try:
            r1 = get_live_fx_rate(from_currency, "USD")
            r2 = get_live_fx_rate("USD", to_currency)
            return r1 * r2
        except Exception:
            pass

    return 1.0


def get_effective_fx_rate(conn: sqlite3.Connection, txn: dict) -> float:
    """Get the effective FX rate for a transaction: override > stored > fetch."""
    if txn.get("fx_rate_override") and txn["fx_rate_override"] > 0:
        return txn["fx_rate_override"]
    if txn.get("fx_rate_to_sgd") and txn["fx_rate_to_sgd"] > 0:
        return txn["fx_rate_to_sgd"]

    currency = txn.get("currency", "USD")
    date = txn["date"]
    return get_fx_rate(conn, currency, BASE_CURRENCY, date)


def _fetch_fx_rate_yfinance(from_currency: str, to_currency: str, date: str) -> float | None:
    """Fetch FX rate from yfinance for a specific date."""
    pair = f"{from_currency}{to_currency}=X"
    try:
        t = yf.Ticker(pair)
        dt = datetime.strptime(date, "%Y-%m-%d")
        start = dt.strftime("%Y-%m-%d")
        end = (dt + timedelta(days=5)).strftime("%Y-%m-%d")
        hist = t.history(start=start, end=end)
        if hist.empty:
            # Try wider window
            start2 = (dt - timedelta(days=7)).strftime("%Y-%m-%d")
            hist = t.history(start=start2, end=end)
        if not hist.empty:
            # Get the closest date <= target
            target_ts = pd.Timestamp(dt)
            before = hist[hist.index <= target_ts]
            if not before.empty:
                return float(before["Close"].iloc[-1])
            return float(hist["Close"].iloc[0])
    except Exception:
        pass
    return None


def prefetch_fx_rates(
    conn: sqlite3.Connection, from_currency: str, to_currency: str, start: str, end: str
) -> None:
    """Bulk-fetch and cache FX rates for a date range."""
    if from_currency.upper() == to_currency.upper():
        return

    pair = f"{from_currency.upper()}{to_currency.upper()}=X"
    try:
        t = yf.Ticker(pair)
        hist = t.history(start=start, end=end)
        for date_idx, row in hist.iterrows():
            date_str = date_idx.strftime("%Y-%m-%d")
            store_rate(conn, date_str, from_currency.upper(), to_currency.upper(), float(row["Close"]))
    except Exception:
        pass
