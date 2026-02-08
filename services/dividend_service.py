"""Dividend fetching, withholding tax calculation, and SGD conversion."""

import pandas as pd
from datetime import datetime
import sqlite3
from services.market_data import get_dividends, get_ticker_info
from services.fx_service import get_fx_rate
from config import WITHHOLDING_TAX_RATES, BASE_CURRENCY


def get_withholding_tax_rate(country: str) -> float:
    """Get the withholding tax rate for a country."""
    return WITHHOLDING_TAX_RATES.get(country.upper(), WITHHOLDING_TAX_RATES["DEFAULT"])


def fetch_dividends_for_ticker(
    conn: sqlite3.Connection, ticker: str, years_back: int = 3
) -> pd.Series:
    """Fetch dividend history for a ticker going back N years."""
    start = f"{datetime.now().year - years_back}-01-01"
    return get_dividends(ticker, start=start)


def calculate_dividends_received(
    conn: sqlite3.Connection,
    ticker: str,
    transactions: list[dict],
    dividend_history: pd.Series,
    country: str,
    currency: str,
) -> tuple[float, list[dict]]:
    """
    Calculate net dividends received for a ticker based on shares held at each ex-date.

    Returns (total_net_div_sgd, list_of_dividend_records).
    """
    if dividend_history.empty:
        return 0.0, []

    wht_rate = get_withholding_tax_rate(country)
    total_net_div_sgd = 0.0
    records = []

    # Sort transactions by date for replay
    sorted_txns = sorted(transactions, key=lambda t: t["date"])

    for ex_date, div_per_share in dividend_history.items():
        ex_date_str = ex_date.strftime("%Y-%m-%d") if hasattr(ex_date, "strftime") else str(ex_date)[:10]

        # Replay transactions to find shares held on ex_date
        shares_held = 0.0
        for txn in sorted_txns:
            if txn["date"] > ex_date_str:
                break
            if txn["side"] == "BUY":
                shares_held += txn["quantity"]
            elif txn["side"] == "SELL":
                shares_held -= txn["quantity"]

        if shares_held <= 0:
            continue

        gross_native = shares_held * div_per_share
        tax_native = gross_native * wht_rate
        net_native = gross_native - tax_native

        fx_rate = get_fx_rate(conn, currency, BASE_CURRENCY, ex_date_str)
        net_sgd = net_native * fx_rate

        total_net_div_sgd += net_sgd
        records.append({
            "ex_date": ex_date_str,
            "div_per_share": div_per_share,
            "shares_held": shares_held,
            "gross_native": gross_native,
            "wht_rate": wht_rate,
            "tax_native": tax_native,
            "net_native": net_native,
            "fx_rate": fx_rate,
            "net_sgd": net_sgd,
            "currency": currency,
            "year": int(ex_date_str[:4]),
        })

    return total_net_div_sgd, records


def get_dividend_summary_by_year(
    conn: sqlite3.Connection, positions: list, current_year: int | None = None
) -> dict:
    """
    Aggregate dividend data by year across all positions.
    Returns {year: total_net_sgd}.
    """
    if current_year is None:
        current_year = datetime.now().year

    summary = {}
    for pos in positions:
        if not hasattr(pos, "dividend_records"):
            continue
        for rec in pos.dividend_records:
            year = rec["year"]
            summary[year] = summary.get(year, 0.0) + rec["net_sgd"]

    return dict(sorted(summary.items()))
