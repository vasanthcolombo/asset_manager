"""Watchlist page: stock price charts with buy/sell/dividend overlays."""

import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, date, timedelta

from models.watchlist import add_to_watchlist, get_watchlist, remove_from_watchlist
from models.transaction import get_transactions, get_distinct_tickers
from services.market_data import get_live_prices_batch, get_ticker_info
from services.cache import get_cached_portfolio

# Plotly color cycle for comparison mode
_COMPARE_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]

PERIODS = ["1D", "5D", "1W", "1M", "3M", "6M", "YTD", "1Y", "2Y", "3Y", "5Y", "10Y", "All"]
PERIOD_CONFIG = {
    "1D":  {"yf_period": "1d",   "interval": "5m"},
    "5D":  {"yf_period": "5d",   "interval": "30m"},
    "1W":  {"start_days": 7,     "interval": "1d"},
    "1M":  {"start_days": 30,    "interval": "1d"},
    "3M":  {"start_days": 90,    "interval": "1d"},
    "6M":  {"start_days": 180,   "interval": "1d"},
    "YTD": {"start_ytd": True,   "interval": "1d"},
    "1Y":  {"start_days": 365,   "interval": "1d"},
    "2Y":  {"start_days": 730,   "interval": "1wk"},
    "3Y":  {"start_days": 1095,  "interval": "1wk"},
    "5Y":  {"start_days": 1825,  "interval": "1wk"},
    "10Y": {"start_days": 3650,  "interval": "1mo"},
    "All": {"yf_period": "max",  "interval": "1mo"},
}


def _build_start(cfg: dict) -> dict:
    """Return kwargs for yf.Ticker.history() or yf.download()."""
    if "yf_period" in cfg:
        return {"period": cfg["yf_period"]}
    if cfg.get("start_ytd"):
        return {"start": date(datetime.now().year, 1, 1).strftime("%Y-%m-%d")}
    return {"start": (datetime.now() - timedelta(days=cfg["start_days"])).strftime("%Y-%m-%d")}


def _tz_strip(df: pd.DataFrame) -> pd.DataFrame:
    if not df.empty and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_single(ticker: str, cfg: dict) -> pd.DataFrame:
    """Fetch full OHLCV for a single ticker."""
    try:
        kwargs = _build_start(cfg)
        h = yf.Ticker(ticker).history(interval=cfg["interval"], **kwargs)
        return _tz_strip(h)
    except Exception:
        return pd.DataFrame()


def fetch_closes(tickers: list[str], cfg: dict) -> dict[str, pd.Series]:
    """Fetch Close series for multiple tickers in one yf.download call."""
    if not tickers:
        return {}
    try:
        kwargs = _build_start(cfg)
        df = yf.download(tickers, interval=cfg["interval"], progress=False,
                         threads=True, **kwargs)
        df = _tz_strip(df)
        if df.empty:
            return {}
        result = {}
        if len(tickers) == 1:
            result[tickers[0]] = df["Close"].dropna() if "Close" in df.columns else pd.Series()
        else:
            for t in tickers:
                try:
                    result[t] = df["Close"][t].dropna()
                except Exception:
                    result[t] = pd.Series()
        return result
    except Exception:
        return {}


# ===========================================================================
st.header("Watchlist")
conn = st.session_state.conn

# --- Add to watchlist ---
with st.form("add_watchlist", clear_on_submit=True):
    cols = st.columns([3, 1])
    with cols[0]:
        new_ticker = st.text_input("Add Ticker", placeholder="e.g. AAPL, MSFT, D05.SI")
    with cols[1]:
        st.markdown("")
        st.markdown("")
        if st.form_submit_button("Add to Watchlist", use_container_width=True):
            if new_ticker.strip():
                add_to_watchlist(conn, new_ticker.strip().upper())
                st.rerun()

# --- Watchlist price table ---
watchlist = get_watchlist(conn)
watchlist_tickers = [item["ticker"] for item in watchlist]

if watchlist_tickers:
    with st.spinner("Fetching prices..."):
        live_prices = get_live_prices_batch(conn, watchlist_tickers)
        day_changes = {}
        try:
            start_5d = (pd.Timestamp.now() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
            hist_df = yf.download(watchlist_tickers, start=start_5d, progress=False, threads=True)
            if not hist_df.empty:
                if len(watchlist_tickers) == 1:
                    closes = hist_df["Close"]
                    if len(closes) >= 2:
                        day_changes[watchlist_tickers[0]] = float(
                            (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100
                        )
                else:
                    for t in watchlist_tickers:
                        try:
                            closes = hist_df["Close"][t].dropna()
                            if len(closes) >= 2:
                                day_changes[t] = float(
                                    (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100
                                )
                        except Exception:
                            pass
        except Exception:
            pass

    rows = []
    for item in watchlist:
        t = item["ticker"]
        pd_data = live_prices.get(t, {"price": 0.0, "currency": "USD"})
        info = get_ticker_info(conn, t)
        rows.append({
            "Ticker": t,
            "Name": info.get("name", t),
            "Price": float(pd_data.get("price", 0.0)),
            "Currency": pd_data.get("currency", "USD"),
            "Day Change %": day_changes.get(t, 0.0),
        })
    st.dataframe(
        pd.DataFrame(rows).style.format({
            "Price": "{:.2f}",
            "Day Change %": "{:+.2f}%",
        }).map(
            lambda v: "color: green" if isinstance(v, (int, float)) and v > 0 else
                      ("color: red" if isinstance(v, (int, float)) and v < 0 else ""),
            subset=["Day Change %"],
        ),
        use_container_width=True,
        hide_index=True,
    )

# ===========================================================================
# Chart section
# ===========================================================================
st.divider()
st.subheader("Price Chart")

# Ticker pre-selection (from portfolio/transactions nav)
ticker_from_nav = st.session_state.get("chart_ticker")
all_chart_tickers = watchlist_tickers.copy()
if ticker_from_nav and ticker_from_nav.upper() not in [t.upper() for t in all_chart_tickers]:
    all_chart_tickers = [ticker_from_nav] + all_chart_tickers

if not all_chart_tickers:
    st.info("Add tickers to your watchlist to see charts, or navigate here from the Portfolio page.")
    st.stop()

default_idx = 0
if ticker_from_nav:
    for i, t in enumerate(all_chart_tickers):
        if t.upper() == ticker_from_nav.upper():
            default_idx = i
            break

# Ticker row: selectbox + watchlist button
hdr_cols = st.columns([3, 1])
with hdr_cols[0]:
    selected_ticker = st.selectbox(
        "Ticker", all_chart_tickers, index=default_idx, label_visibility="collapsed"
    )
with hdr_cols[1]:
    if selected_ticker in watchlist_tickers:
        if st.button("Remove from Watchlist", type="secondary", use_container_width=True):
            remove_from_watchlist(conn, selected_ticker)
            if "chart_ticker" in st.session_state:
                del st.session_state["chart_ticker"]
            st.rerun()
    else:
        if st.button("Add to Watchlist", use_container_width=True):
            add_to_watchlist(conn, selected_ticker)
            st.rerun()

# Consume nav ticker
if "chart_ticker" in st.session_state:
    del st.session_state["chart_ticker"]

# Period selector
period = st.radio("Period", PERIODS, horizontal=True, index=PERIODS.index("1Y"), key="chart_period")
cfg = PERIOD_CONFIG[period]

# Control row: Chart Type | Moving Averages | Compare with
positions = get_cached_portfolio(conn)
ticker_pos = next((p for p in positions if p.ticker.upper() == selected_ticker.upper()), None)

portfolio_tickers = [p.ticker for p in positions]
all_available = sorted(set(watchlist_tickers + portfolio_tickers + get_distinct_tickers(conn)) - {selected_ticker})

ctrl_cols = st.columns([1, 2, 3])
with ctrl_cols[0]:
    chart_type = st.radio("Chart Type", ["Candle", "Line"], horizontal=True, key="chart_type")
with ctrl_cols[1]:
    ma_periods = st.multiselect(
        "Moving Averages",
        [20, 50, 100, 200],
        default=[],
        format_func=lambda x: f"{x}-day MA",
        key="ma_select",
    )
with ctrl_cols[2]:
    compare_tickers = st.multiselect(
        "Compare with (% change):",
        all_available,
        default=[],
        key="compare_tickers",
    )

compare_mode = len(compare_tickers) > 0

# In compare mode, line is forced and overlays/MAs don't apply
if not compare_mode:
    ovl_cols = st.columns(2)
    with ovl_cols[0]:
        show_txns = st.checkbox("Show Buy/Sell transactions", value=ticker_pos is not None)
    with ovl_cols[1]:
        has_divs = ticker_pos is not None and bool(ticker_pos.dividend_records)
        show_divs = st.checkbox("Show Dividend dates", value=has_divs)

# ===========================================================================
# Fetch data and build chart
# ===========================================================================

if compare_mode:
    # -----------------------------------------------------------------------
    # COMPARISON MODE — % change from period start, all as lines
    # -----------------------------------------------------------------------
    all_tickers = [selected_ticker] + compare_tickers
    with st.spinner("Loading comparison data..."):
        closes_map = fetch_closes(all_tickers, cfg)

    fig = go.Figure()
    for idx, ticker in enumerate(all_tickers):
        closes = closes_map.get(ticker, pd.Series())
        if closes.empty or closes.iloc[0] == 0:
            continue
        pct = (closes / closes.iloc[0] - 1) * 100
        info = get_ticker_info(conn, ticker)
        name = f"{ticker} ({info.get('name', ticker)[:20]})"
        fig.add_trace(go.Scatter(
            x=pct.index,
            y=pct.values,
            mode="lines",
            name=name,
            line=dict(color=_COMPARE_COLORS[idx % len(_COMPARE_COLORS)], width=2),
        ))

    fig.update_layout(
        title=f"Performance Comparison — % Change ({period})",
        yaxis_title="% Change from Period Start",
        xaxis_rangeslider_visible=False,
        height=520,
        margin=dict(l=0, r=0, t=40, b=0),
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    st.plotly_chart(fig, use_container_width=True)

else:
    # -----------------------------------------------------------------------
    # SINGLE TICKER MODE — candle or line, MAs, buy/sell/div overlays
    # -----------------------------------------------------------------------
    with st.spinner(f"Loading {selected_ticker}..."):
        hist = fetch_single(selected_ticker, cfg)

    if hist.empty:
        st.warning(f"No historical data found for {selected_ticker}.")
        st.stop()

    chart_start = hist.index.min()
    fig = go.Figure()

    if chart_type == "Candle":
        fig.add_trace(go.Candlestick(
            x=hist.index,
            open=hist["Open"],
            high=hist["High"],
            low=hist["Low"],
            close=hist["Close"],
            name=selected_ticker,
            increasing_line_color="#2ca02c",
            decreasing_line_color="#d62728",
        ))
    else:
        fig.add_trace(go.Scatter(
            x=hist.index,
            y=hist["Close"],
            mode="lines",
            name=selected_ticker,
            line=dict(color="#1f77b4", width=2),
        ))

    # Moving averages
    ma_colors = {20: "#ff7f0e", 50: "#9467bd", 100: "#e377c2", 200: "#17becf"}
    for ma in sorted(ma_periods):
        if len(hist) >= ma:
            ma_series = hist["Close"].rolling(window=ma).mean()
            fig.add_trace(go.Scatter(
                x=hist.index,
                y=ma_series,
                mode="lines",
                name=f"{ma}-day MA",
                line=dict(color=ma_colors.get(ma, "#aaaaaa"), width=1.5, dash="dot"),
            ))

    # Overlay: Buy / Sell markers
    if show_txns:
        txns = get_transactions(conn, tickers=[selected_ticker])
        buys_x, buys_y, buys_text = [], [], []
        sells_x, sells_y, sells_text = [], [], []
        for txn in txns:
            ts = pd.Timestamp(txn["date"])
            if ts < chart_start:
                continue
            label = f"{txn['side']} {txn['quantity']}@{txn['price']}<br>{txn['broker']}"
            if txn["side"] == "BUY":
                buys_x.append(ts)
                buys_y.append(txn["price"])
                buys_text.append(label)
            else:
                sells_x.append(ts)
                sells_y.append(txn["price"])
                sells_text.append(label)
        if buys_x:
            fig.add_trace(go.Scatter(
                x=buys_x, y=buys_y, mode="markers", name="Buy",
                marker=dict(symbol="triangle-up", size=14, color="lime",
                            line=dict(color="green", width=1)),
                hovertemplate="%{text}<extra>Buy</extra>",
                text=buys_text,
            ))
        if sells_x:
            fig.add_trace(go.Scatter(
                x=sells_x, y=sells_y, mode="markers", name="Sell",
                marker=dict(symbol="triangle-down", size=14, color="red",
                            line=dict(color="darkred", width=1)),
                hovertemplate="%{text}<extra>Sell</extra>",
                text=sells_text,
            ))

    # Overlay: Dividend date markers
    if show_divs and ticker_pos and ticker_pos.dividend_records:
        div_x, div_y, div_text = [], [], []
        for rec in ticker_pos.dividend_records:
            ts = pd.Timestamp(rec["ex_date"])
            if ts < chart_start:
                continue
            mask = hist.index <= ts
            if not mask.any():
                continue
            y_val = float(hist["Low"].loc[mask].iloc[-1]) * 0.97
            div_x.append(ts)
            div_y.append(y_val)
            div_text.append(
                f"Ex-Date: {rec['ex_date']}<br>"
                f"Div/Share: {rec['div_per_share']:.4f} {rec['currency']}<br>"
                f"Shares: {rec['shares_held']:.0f}<br>"
                f"Net S$: {rec['net_sgd']:.2f}"
            )
        if div_x:
            fig.add_trace(go.Scatter(
                x=div_x, y=div_y, mode="markers", name="Dividend",
                marker=dict(symbol="diamond", size=11, color="gold",
                            line=dict(color="darkorange", width=1)),
                hovertemplate="%{text}<extra>Dividend</extra>",
                text=div_text,
            ))

    ticker_info = get_ticker_info(conn, selected_ticker)
    fig.update_layout(
        title=f"{selected_ticker} — {ticker_info.get('name', selected_ticker)} ({period})",
        yaxis_title=f"Price ({ticker_info.get('currency', '')})",
        xaxis_rangeslider_visible=False,
        height=520,
        margin=dict(l=0, r=0, t=40, b=0),
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Volume chart
    if "Volume" in hist.columns and hist["Volume"].sum() > 0:
        vol_colors = [
            "#2ca02c" if hist["Close"].iloc[i] >= hist["Open"].iloc[i] else "#d62728"
            for i in range(len(hist))
        ]
        fig_vol = go.Figure(go.Bar(
            x=hist.index, y=hist["Volume"], marker_color=vol_colors, name="Volume"
        ))
        fig_vol.update_layout(
            title="Volume",
            height=180,
            margin=dict(l=0, r=0, t=30, b=0),
            xaxis_rangeslider_visible=False,
        )
        st.plotly_chart(fig_vol, use_container_width=True)
