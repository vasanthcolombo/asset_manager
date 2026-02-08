"""XIRR calculation, benchmark comparison, and chart data preparation."""

import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from pyxirr import xirr
import yfinance as yf
import sqlite3

from services.portfolio_engine import TickerPosition
from services.fx_service import get_fx_rate, get_live_fx_rate
from services.market_data import get_historical_prices, get_live_price
from config import BASE_CURRENCY


def calculate_portfolio_xirr(
    positions: list[TickerPosition],
) -> float | None:
    """
    Calculate XIRR for the portfolio based on all cash flows.
    Cash flows: BUYs (negative), SELLs (positive), dividends (positive),
    terminal portfolio value (positive, today).
    """
    dates = []
    amounts = []

    for pos in positions:
        # Open lots: original buys still held
        for lot in pos.open_lots:
            dates.append(_parse_date(lot.date))
            amounts.append(-(lot.quantity * lot.price_native * lot.fx_rate_to_sgd))

        # Closed lots: buy and sell
        for cl in pos.closed_lots:
            dates.append(_parse_date(cl.buy_date))
            amounts.append(-(cl.quantity * cl.buy_price_native * cl.buy_fx_rate))
            dates.append(_parse_date(cl.sell_date))
            amounts.append(cl.quantity * cl.sell_price_native * cl.sell_fx_rate)

        # Dividend cash flows
        for div in pos.dividend_records:
            dates.append(_parse_date(div["ex_date"]))
            amounts.append(div["net_sgd"])

        # Terminal value for open positions
        if pos.shares > 0:
            dates.append(date.today())
            amounts.append(pos.current_value_sgd)

    if not dates or len(dates) < 2:
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
    Calculate what the XIRR would have been if the same SGD amounts were
    invested in a benchmark at the same dates.
    """
    # Collect all buy/sell cash flows with dates and SGD amounts
    cash_flows = []

    for pos in positions:
        for lot in pos.open_lots:
            amt_sgd = lot.quantity * lot.price_native * lot.fx_rate_to_sgd
            cash_flows.append((_parse_date(lot.date), amt_sgd, "BUY"))

        for cl in pos.closed_lots:
            amt_buy = cl.quantity * cl.buy_price_native * cl.buy_fx_rate
            cash_flows.append((_parse_date(cl.buy_date), amt_buy, "BUY"))

            amt_sell = cl.quantity * cl.sell_price_native * cl.sell_fx_rate
            cash_flows.append((_parse_date(cl.sell_date), amt_sell, "SELL"))

    if not cash_flows:
        return None

    cash_flows.sort(key=lambda x: x[0])
    start_date = cash_flows[0][0]

    # Fetch benchmark historical prices
    bench_hist = get_historical_prices(
        benchmark_ticker,
        start=start_date.strftime("%Y-%m-%d"),
    )
    if bench_hist.empty:
        return None

    # Get benchmark currency
    try:
        bench_t = yf.Ticker(benchmark_ticker)
        bench_currency = bench_t.info.get("currency", "USD")
    except Exception:
        bench_currency = "USD"

    # Simulate benchmark investment
    benchmark_shares = 0.0
    xirr_dates = []
    xirr_amounts = []

    for d, amt_sgd, side in cash_flows:
        bench_price = _get_price_on_date(bench_hist, d)
        if bench_price is None or bench_price <= 0:
            continue

        fx_rate = get_fx_rate(conn, bench_currency, BASE_CURRENCY, d.strftime("%Y-%m-%d"))
        if fx_rate <= 0:
            fx_rate = 1.0

        if side == "BUY":
            # Convert SGD to benchmark currency: SGD / fx_rate(bench_ccy->SGD) = bench_ccy
            amt_bench = amt_sgd / fx_rate
            shares_bought = amt_bench / bench_price
            benchmark_shares += shares_bought
            xirr_dates.append(d)
            xirr_amounts.append(-amt_sgd)

        elif side == "SELL":
            if benchmark_shares <= 0:
                continue
            # Sell proportional benchmark shares (same SGD worth)
            amt_bench = amt_sgd / fx_rate
            shares_to_sell = min(amt_bench / bench_price, benchmark_shares)
            benchmark_shares -= shares_to_sell
            actual_proceeds = shares_to_sell * bench_price * fx_rate
            xirr_dates.append(d)
            xirr_amounts.append(actual_proceeds)

    # Terminal value
    if benchmark_shares > 0:
        try:
            live_data = get_live_price(conn, benchmark_ticker)
            live_bench_price = live_data["price"]
            live_fx = get_live_fx_rate(bench_currency, BASE_CURRENCY)
            terminal = benchmark_shares * live_bench_price * live_fx
            xirr_dates.append(date.today())
            xirr_amounts.append(terminal)
        except Exception:
            return None

    if len(xirr_dates) < 2:
        return None

    try:
        result = xirr(xirr_dates, xirr_amounts)
        return result if result is not None else None
    except Exception:
        return None


def compute_investment_over_time(positions: list[TickerPosition]) -> pd.DataFrame:
    """Compute cumulative investment (SGD) over time from all positions."""
    events = []

    for pos in positions:
        for lot in pos.open_lots:
            events.append({
                "date": lot.date,
                "amount_sgd": lot.quantity * lot.price_native * lot.fx_rate_to_sgd,
            })
        for cl in pos.closed_lots:
            events.append({
                "date": cl.buy_date,
                "amount_sgd": cl.quantity * cl.buy_price_native * cl.buy_fx_rate,
            })
            events.append({
                "date": cl.sell_date,
                "amount_sgd": -(cl.quantity * cl.sell_price_native * cl.sell_fx_rate),
            })

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
    Compute portfolio value over time by replaying transactions and using
    historical prices. freq: 'D' daily, 'W' weekly, 'M' monthly.
    """
    if not positions:
        return pd.DataFrame(columns=["date", "value_sgd"])

    # Collect all transactions sorted by date
    all_events = []
    tickers = set()
    for pos in positions:
        for lot in pos.open_lots:
            all_events.append({"date": lot.date, "ticker": pos.ticker, "side": "BUY", "qty": lot.quantity})
            tickers.add(pos.ticker)
        for cl in pos.closed_lots:
            all_events.append({"date": cl.buy_date, "ticker": pos.ticker, "side": "BUY", "qty": cl.quantity})
            all_events.append({"date": cl.sell_date, "ticker": pos.ticker, "side": "SELL", "qty": cl.quantity})
            tickers.add(pos.ticker)

    if not all_events:
        return pd.DataFrame(columns=["date", "value_sgd"])

    all_events.sort(key=lambda e: e["date"])
    start_date = all_events[0]["date"]

    # Fetch historical prices for all tickers
    hist_prices = {}
    for ticker in tickers:
        hp = get_historical_prices(ticker, start=start_date)
        if not hp.empty:
            hist_prices[ticker] = hp

    # Create date grid
    date_range = pd.date_range(
        start=start_date,
        end=datetime.now().strftime("%Y-%m-%d"),
        freq=freq,
    )

    # Compute holdings at each date
    ticker_currencies = {pos.ticker: pos.currency for pos in positions}
    values = []

    for grid_date in date_range:
        grid_str = grid_date.strftime("%Y-%m-%d")

        # Replay events to find holdings at grid_date
        holdings = {}
        for evt in all_events:
            if evt["date"] > grid_str:
                break
            t = evt["ticker"]
            if t not in holdings:
                holdings[t] = 0
            if evt["side"] == "BUY":
                holdings[t] += evt["qty"]
            else:
                holdings[t] -= evt["qty"]

        # Compute total value
        total_sgd = 0.0
        for t, qty in holdings.items():
            if qty <= 0 or t not in hist_prices:
                continue
            hp = hist_prices[t]
            price = _get_price_on_date(hp, grid_date.date())
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
    Compute what the portfolio value would have been if invested in benchmark,
    over time.
    """
    # Collect buy cash flows
    cash_flows = []
    for pos in positions:
        for lot in pos.open_lots:
            amt_sgd = lot.quantity * lot.price_native * lot.fx_rate_to_sgd
            cash_flows.append((_parse_date(lot.date), amt_sgd, "BUY"))
        for cl in pos.closed_lots:
            amt_buy = cl.quantity * cl.buy_price_native * cl.buy_fx_rate
            cash_flows.append((_parse_date(cl.buy_date), amt_buy, "BUY"))
            amt_sell = cl.quantity * cl.sell_price_native * cl.sell_fx_rate
            cash_flows.append((_parse_date(cl.sell_date), amt_sell, "SELL"))

    if not cash_flows:
        return pd.DataFrame(columns=["date", "value_sgd"])

    cash_flows.sort(key=lambda x: x[0])
    start = cash_flows[0][0]

    bench_hist = get_historical_prices(
        benchmark_ticker, start=start.strftime("%Y-%m-%d")
    )
    if bench_hist.empty:
        return pd.DataFrame(columns=["date", "value_sgd"])

    try:
        bench_t = yf.Ticker(benchmark_ticker)
        bench_currency = bench_t.info.get("currency", "USD")
    except Exception:
        bench_currency = "USD"

    date_range = pd.date_range(
        start=start, end=datetime.now().strftime("%Y-%m-%d"), freq=freq
    )

    values = []
    for grid_date in date_range:
        grid_d = grid_date.date()
        # Simulate benchmark shares held at this date
        bench_shares = 0.0
        for d, amt_sgd, side in cash_flows:
            if d > grid_d:
                break
            bp = _get_price_on_date(bench_hist, d)
            if bp is None or bp <= 0:
                continue
            fx = get_fx_rate(conn, bench_currency, BASE_CURRENCY, d.strftime("%Y-%m-%d"))
            if side == "BUY":
                bench_shares += (amt_sgd / fx) / bp
            elif side == "SELL":
                to_sell = min((amt_sgd / fx) / bp, bench_shares)
                bench_shares -= to_sell

        # Value at grid_date
        bp_now = _get_price_on_date(bench_hist, grid_d)
        if bp_now is None:
            bp_now = 0
        fx_now = get_fx_rate(conn, bench_currency, BASE_CURRENCY, grid_date.strftime("%Y-%m-%d"))
        val = bench_shares * bp_now * fx_now

        values.append({"date": grid_date, "value_sgd": val})

    return pd.DataFrame(values)


def _parse_date(d) -> date:
    """Parse a date string or datetime to date object."""
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def _get_price_on_date(hist_df: pd.DataFrame, target: date) -> float | None:
    """Get Close price on or before target date."""
    if hist_df.empty:
        return None
    # Ensure tz-naive comparison
    idx = hist_df.index
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    target_ts = pd.Timestamp(target)
    mask = idx <= target_ts
    if mask.any():
        return float(hist_df.loc[mask, "Close"].iloc[-1])
    return float(hist_df["Close"].iloc[0])
