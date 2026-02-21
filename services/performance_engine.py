"""XIRR calculation, benchmark comparison, and chart data preparation."""

import pandas as pd
from datetime import datetime, date, timedelta
from pyxirr import xirr
import sqlite3

from services.portfolio_engine import TickerPosition
from services.fx_service import get_fx_rate, get_live_fx_rate
from services.market_data import get_cached_historical_prices, get_live_price, get_ticker_info
from config import BASE_CURRENCY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(d) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def _get_price_on_date(hist_df: pd.DataFrame, target: date) -> float | None:
    """Get Close price on or before target date from a DataFrame with DatetimeIndex."""
    if hist_df.empty or "Close" not in hist_df.columns:
        return None
    idx = hist_df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        idx = idx.tz_localize(None)
    target_ts = pd.Timestamp(target)
    mask = idx <= target_ts
    if mask.any():
        return float(hist_df["Close"].loc[mask].iloc[-1])
    if len(hist_df) > 0:
        return float(hist_df["Close"].iloc[0])
    return None


def _collect_cash_flows(positions: list[TickerPosition]) -> list[tuple]:
    """Return list of (date, sgd_amount, side) from txn_events across all positions."""
    flows = []
    for pos in positions:
        for txn in pos.txn_events:
            sgd_amt = txn["quantity"] * txn["price"] * txn["effective_fx_rate"]
            flows.append((_parse_date(txn["date"]), sgd_amt, txn["side"]))
    flows.sort(key=lambda x: x[0])
    return flows


# ---------------------------------------------------------------------------
# XIRR
# ---------------------------------------------------------------------------

def calculate_portfolio_xirr(positions: list[TickerPosition]) -> float | None:
    """
    XIRR on all portfolio cash flows.
    BUYs = negative outflows, SELLs = positive inflows, dividends = positive,
    terminal market value today = positive.
    """
    dates, amounts = [], []

    for pos in positions:
        for txn in pos.txn_events:
            sgd = txn["quantity"] * txn["price"] * txn["effective_fx_rate"]
            d = _parse_date(txn["date"])
            if txn["side"] == "BUY":
                dates.append(d)
                amounts.append(-sgd)
            elif txn["side"] == "SELL":
                dates.append(d)
                amounts.append(sgd)

        for div in pos.dividend_records:
            dates.append(_parse_date(div["ex_date"]))
            amounts.append(div["net_sgd"])

        if pos.shares > 0:
            dates.append(date.today())
            amounts.append(pos.current_value_sgd)

    if len(dates) < 2:
        return None
    try:
        result = xirr(dates, amounts)
        return result if result is not None else None
    except Exception:
        return None


def calculate_benchmark_xirr(
    conn: sqlite3.Connection,
    positions: list[TickerPosition],
    benchmark_ticker: str = "VOO",
) -> float | None:
    """
    Behavior-matched XIRR: same SGD cash flows invested in the benchmark.
    """
    flows = _collect_cash_flows(positions)
    if not flows:
        return None

    start_date = flows[0][0]
    bench_hist = get_cached_historical_prices(
        conn, benchmark_ticker, start=start_date.strftime("%Y-%m-%d")
    )
    if bench_hist.empty:
        return None

    bench_meta = get_ticker_info(conn, benchmark_ticker)
    bench_currency = bench_meta.get("currency", "USD")

    benchmark_shares = 0.0
    xirr_dates, xirr_amounts = [], []

    for d, amt_sgd, side in flows:
        bp = _get_price_on_date(bench_hist, d)
        if bp is None or bp <= 0:
            continue
        fx = get_fx_rate(conn, bench_currency, BASE_CURRENCY, d.strftime("%Y-%m-%d")) or 1.0

        if side == "BUY":
            benchmark_shares += (amt_sgd / fx) / bp
            xirr_dates.append(d)
            xirr_amounts.append(-amt_sgd)
        elif side == "SELL" and benchmark_shares > 0:
            to_sell = min((amt_sgd / fx) / bp, benchmark_shares)
            benchmark_shares -= to_sell
            xirr_dates.append(d)
            xirr_amounts.append(to_sell * bp * fx)

    if benchmark_shares > 0:
        try:
            live_data = get_live_price(conn, benchmark_ticker)
            live_fx = get_live_fx_rate(bench_currency, BASE_CURRENCY)
            xirr_dates.append(date.today())
            xirr_amounts.append(benchmark_shares * live_data["price"] * live_fx)
        except Exception:
            return None

    if len(xirr_dates) < 2:
        return None
    try:
        result = xirr(xirr_dates, xirr_amounts)
        return result if result is not None else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Chart data
# ---------------------------------------------------------------------------

def compute_investment_over_time(positions: list[TickerPosition]) -> pd.DataFrame:
    """Cumulative net SGD invested over time (buys positive, sells negative)."""
    events = []
    for pos in positions:
        for txn in pos.txn_events:
            sgd = txn["quantity"] * txn["price"] * txn["effective_fx_rate"]
            amount = sgd if txn["side"] == "BUY" else -sgd
            events.append({"date": txn["date"], "amount_sgd": amount})

    if not events:
        return pd.DataFrame(columns=["date", "cumulative_investment"])

    df = pd.DataFrame(events)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["cumulative_investment"] = df["amount_sgd"].cumsum()
    return df


def compute_portfolio_value_over_time(
    conn: sqlite3.Connection,
    positions: list[TickerPosition],
    freq: str = "W",
) -> pd.DataFrame:
    """
    Portfolio market value over time by replaying transactions and using
    DB-cached historical prices. freq: 'W' weekly, 'ME' monthly.
    """
    if not positions:
        return pd.DataFrame(columns=["date", "value_sgd"])

    # Collect transaction events (date, ticker, side, qty)
    all_events = []
    tickers = set()
    for pos in positions:
        for txn in pos.txn_events:
            all_events.append({
                "date": txn["date"],
                "ticker": pos.ticker,
                "side": txn["side"],
                "qty": txn["quantity"],
            })
            tickers.add(pos.ticker)

    if not all_events:
        return pd.DataFrame(columns=["date", "value_sgd"])

    all_events.sort(key=lambda e: e["date"])
    start_date = all_events[0]["date"]

    # Fetch historical prices for all tickers using DB cache
    hist_prices = {}
    for ticker in tickers:
        hp = get_cached_historical_prices(conn, ticker, start=start_date)
        if not hp.empty:
            hist_prices[ticker] = hp

    date_range = pd.date_range(
        start=start_date,
        end=datetime.now().strftime("%Y-%m-%d"),
        freq=freq,
    )

    ticker_currencies = {pos.ticker: pos.currency for pos in positions}
    values = []

    for grid_date in date_range:
        grid_str = grid_date.strftime("%Y-%m-%d")
        holdings = {}
        for evt in all_events:
            if evt["date"] > grid_str:
                break
            t = evt["ticker"]
            holdings[t] = holdings.get(t, 0.0)
            if evt["side"] == "BUY":
                holdings[t] += evt["qty"]
            else:
                holdings[t] -= evt["qty"]

        total_sgd = 0.0
        for t, qty in holdings.items():
            if qty <= 0 or t not in hist_prices:
                continue
            price = _get_price_on_date(hist_prices[t], grid_date.date())
            if price is None:
                continue
            currency = ticker_currencies.get(t, "USD")
            fx = get_fx_rate(conn, currency, BASE_CURRENCY, grid_str) if currency != BASE_CURRENCY else 1.0
            total_sgd += qty * price * fx

        values.append({"date": grid_date, "value_sgd": total_sgd})

    return pd.DataFrame(values)


def compute_benchmark_value_over_time(
    conn: sqlite3.Connection,
    positions: list[TickerPosition],
    benchmark_ticker: str = "VOO",
    freq: str = "W",
) -> pd.DataFrame:
    """
    Behavior-matched benchmark: same SGD cash flows invested in the benchmark ETF,
    portfolio value plotted over time.
    """
    flows = _collect_cash_flows(positions)
    if not flows:
        return pd.DataFrame(columns=["date", "value_sgd"])

    start = flows[0][0]
    bench_hist = get_cached_historical_prices(
        conn, benchmark_ticker, start=start.strftime("%Y-%m-%d")
    )
    if bench_hist.empty:
        return pd.DataFrame(columns=["date", "value_sgd"])

    bench_meta = get_ticker_info(conn, benchmark_ticker)
    bench_currency = bench_meta.get("currency", "USD")

    date_range = pd.date_range(
        start=start, end=datetime.now().strftime("%Y-%m-%d"), freq=freq
    )

    values = []
    for grid_date in date_range:
        grid_d = grid_date.date()
        grid_str = grid_date.strftime("%Y-%m-%d")

        # Simulate benchmark shares held at this grid date
        bench_shares = 0.0
        for d, amt_sgd, side in flows:
            if d > grid_d:
                break
            bp = _get_price_on_date(bench_hist, d)
            if bp is None or bp <= 0:
                continue
            fx = get_fx_rate(conn, bench_currency, BASE_CURRENCY, d.strftime("%Y-%m-%d")) or 1.0
            if side == "BUY":
                bench_shares += (amt_sgd / fx) / bp
            elif side == "SELL":
                bench_shares -= min((amt_sgd / fx) / bp, bench_shares)

        bp_now = _get_price_on_date(bench_hist, grid_d) or 0.0
        fx_now = get_fx_rate(conn, bench_currency, BASE_CURRENCY, grid_str) or 1.0
        values.append({"date": grid_date, "value_sgd": bench_shares * bp_now * fx_now})

    return pd.DataFrame(values)
