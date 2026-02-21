"""Watchlist page: track stocks, view prices and charts."""

import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go

from models.watchlist import add_to_watchlist, get_watchlist, remove_from_watchlist
from services.market_data import get_live_prices_batch, get_historical_prices, get_ticker_info

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
        add_btn = st.form_submit_button("Add to Watchlist", use_container_width=True)

    if add_btn and new_ticker.strip():
        add_to_watchlist(conn, new_ticker.strip())
        st.rerun()

# --- Display watchlist ---
watchlist = get_watchlist(conn)

if not watchlist:
    st.info("Your watchlist is empty. Add tickers above!")
    st.stop()

tickers = [item["ticker"] for item in watchlist]

# Batch fetch all live prices in one yf.download() call
with st.spinner("Fetching prices..."):
    live_prices = get_live_prices_batch(conn, tickers)

    # Batch fetch day change using a single yf.download for 5 days
    day_changes = {}
    try:
        start_5d = (pd.Timestamp.now() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        hist_df = yf.download(tickers, start=start_5d, progress=False, threads=True)
        if not hist_df.empty:
            if len(tickers) == 1:
                closes = hist_df["Close"]
                if len(closes) >= 2:
                    day_changes[tickers[0]] = ((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100)
            else:
                for t in tickers:
                    try:
                        closes = hist_df["Close"][t].dropna()
                        if len(closes) >= 2:
                            day_changes[t] = ((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100)
                    except Exception:
                        pass
    except Exception:
        pass

rows = []
for item in watchlist:
    ticker = item["ticker"]
    price_data = live_prices.get(ticker, {"price": 0.0, "currency": "USD"})
    info = get_ticker_info(conn, ticker)

    rows.append({
        "Ticker": ticker,
        "Name": info.get("name", ticker),
        "Price": price_data.get("price", 0.0),
        "Currency": price_data.get("currency", "USD"),
        "Day Change %": day_changes.get(ticker, 0.0),
    })

df = pd.DataFrame(rows)

st.dataframe(
    df.style.format({
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

# --- Detailed view + chart ---
st.divider()
selected_ticker = st.selectbox(
    "Select ticker for chart",
    [item["ticker"] for item in watchlist],
)

if selected_ticker:
    # Remove button
    if st.button(f"Remove {selected_ticker} from watchlist"):
        remove_from_watchlist(conn, selected_ticker)
        st.rerun()

    # Time range selector
    period = st.radio("Period", ["1M", "3M", "6M", "1Y", "5Y"], horizontal=True)
    period_map = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "5Y": 1825}
    days = period_map[period]

    start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")

    with st.spinner(f"Loading chart for {selected_ticker}..."):
        hist = get_historical_prices(selected_ticker, start=start_date)

    if not hist.empty:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=hist.index,
            open=hist["Open"],
            high=hist["High"],
            low=hist["Low"],
            close=hist["Close"],
            name=selected_ticker,
        ))
        fig.update_layout(
            title=f"{selected_ticker} - {period}",
            yaxis_title="Price",
            xaxis_rangeslider_visible=False,
            height=500,
            margin=dict(l=0, r=0, t=40, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Volume chart
        fig_vol = go.Figure()
        fig_vol.add_trace(go.Bar(
            x=hist.index,
            y=hist["Volume"],
            name="Volume",
            marker_color="#636efa",
        ))
        fig_vol.update_layout(
            title="Volume",
            height=200,
            margin=dict(l=0, r=0, t=30, b=0),
        )
        st.plotly_chart(fig_vol, use_container_width=True)
    else:
        st.warning(f"No historical data available for {selected_ticker}.")
