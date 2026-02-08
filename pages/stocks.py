"""Watchlist page: track stocks, view prices and charts."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from models.watchlist import add_to_watchlist, get_watchlist, remove_from_watchlist
from services.market_data import get_live_price, get_historical_prices, get_ticker_info

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

# Fetch live data for all watchlist tickers
rows = []
for item in watchlist:
    ticker = item["ticker"]
    price_data = get_live_price(conn, ticker)
    info = get_ticker_info(conn, ticker)

    # Get day change
    try:
        hist = get_historical_prices(ticker, start=pd.Timestamp.now() - pd.Timedelta(days=5))
        if len(hist) >= 2:
            prev_close = hist["Close"].iloc[-2]
            curr_close = hist["Close"].iloc[-1]
            day_change_pct = ((curr_close - prev_close) / prev_close * 100) if prev_close else 0
        else:
            day_change_pct = 0
    except Exception:
        day_change_pct = 0

    rows.append({
        "Ticker": ticker,
        "Name": info.get("name", ticker),
        "Price": price_data["price"],
        "Currency": price_data["currency"],
        "Day Change %": day_change_pct,
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
