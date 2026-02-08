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


def get_ticker_info(conn: sqlite3.Connection, ticker: str) -> dict:
    """Get ticker metadata (currency, country, name, etc). Uses cache."""
    ticker = ticker.upper().strip()

    cached = get_cached_ticker_metadata(conn, ticker)
    if cached and cached.get("currency"):
        return cached

    try:
        t = yf.Ticker(ticker)
        info = t.info
        exchange = info.get("exchange", "")
        country = EXCHANGE_TO_COUNTRY.get(exchange, _guess_country_from_suffix(ticker))

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
        # Fallback based on ticker suffix
        currency, country = _fallback_currency(ticker)
        metadata = {
            "currency": currency,
            "country": country,
            "exchange": "",
            "name": ticker,
            "sector": "",
        }
        store_ticker_metadata(conn, ticker, metadata)
        return metadata


def get_live_price(conn: sqlite3.Connection, ticker: str) -> dict:
    """Get the current live price for a ticker. Returns {price, currency, error}."""
    ticker = ticker.upper().strip()

    # Check short-lived cache
    cached = get_cached_price(conn, ticker)
    if cached:
        return {"price": cached["price"], "currency": cached["currency"], "error": None}

    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price = fi.get("lastPrice", None)
        if price is None:
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0

        meta = get_ticker_info(conn, ticker)
        currency = meta.get("currency", "USD")

        store_price(conn, ticker, price, currency)
        return {"price": price, "currency": currency, "error": None}
    except Exception as e:
        return {"price": 0.0, "currency": "USD", "error": str(e)}


def get_live_prices_batch(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, dict]:
    """Get live prices for multiple tickers."""
    results = {}
    for ticker in tickers:
        results[ticker.upper()] = get_live_price(conn, ticker)
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
    return "US"  # Default assumption


def _fallback_currency(ticker: str) -> tuple[str, str]:
    """Fallback currency detection from ticker suffix."""
    suffix_map = {
        ".SI": ("SGD", "SG"),
        ".HK": ("HKD", "HK"),
        ".L": ("GBP", "GB"),
        ".AX": ("AUD", "AU"),
        ".TO": ("CAD", "CA"),
        ".T": ("JPY", "JP"),
    }
    for suffix, (currency, country) in suffix_map.items():
        if ticker.endswith(suffix):
            return currency, country
    return "USD", "US"
