"""Dashboard page: at-a-glance portfolio overview."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from models.transaction import get_transactions
from services.portfolio_engine import compute_portfolio
from utils.formatters import fmt_currency, fmt_pct

st.header("Dashboard")

conn = st.session_state.conn

# Compute portfolio
with st.spinner("Loading portfolio..."):
    positions = compute_portfolio(conn)

if not positions:
    st.info("Welcome! Start by adding transactions in the **Transactions** page.")
    st.stop()

# ---- Key Metrics ----
active_positions = [p for p in positions if p.shares > 0]
total_investment = sum(p.total_investment_sgd for p in active_positions)
total_value = sum(p.current_value_sgd for p in active_positions)
total_realized = sum(p.realized_pnl_sgd for p in positions)
total_unrealized = sum(p.unrealized_pnl_sgd for p in active_positions)
total_pnl = total_realized + total_unrealized
total_return_pct = ((total_value - total_investment) / total_investment * 100) if total_investment > 0 else 0

current_year = datetime.now().year
total_div_current = sum(p.dividends_for_year(current_year) for p in positions)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Portfolio Value", fmt_currency(total_value))
with col2:
    st.metric("Total Investment", fmt_currency(total_investment))
with col3:
    st.metric("Total P&L", fmt_currency(total_pnl), delta=f"{total_return_pct:+.1f}%")
with col4:
    st.metric(f"Dividends {current_year}", fmt_currency(total_div_current))

# ---- Top Gainers / Losers ----
st.divider()
gain_col, loss_col = st.columns(2)

sorted_by_pnl = sorted(active_positions, key=lambda p: p.total_pnl_sgd, reverse=True)

with gain_col:
    st.subheader("Top Gainers")
    gainers = [p for p in sorted_by_pnl if p.total_pnl_sgd > 0][:5]
    if gainers:
        for p in gainers:
            pct = (p.total_pnl_sgd / p.total_investment_sgd * 100) if p.total_investment_sgd > 0 else 0
            st.markdown(f"**{p.ticker}** ({p.name}) — {fmt_currency(p.total_pnl_sgd)} ({pct:+.1f}%)")
    else:
        st.text("No gainers yet.")

with loss_col:
    st.subheader("Top Losers")
    losers = [p for p in reversed(sorted_by_pnl) if p.total_pnl_sgd < 0][:5]
    if losers:
        for p in losers:
            pct = (p.total_pnl_sgd / p.total_investment_sgd * 100) if p.total_investment_sgd > 0 else 0
            st.markdown(f"**{p.ticker}** ({p.name}) — {fmt_currency(p.total_pnl_sgd)} ({pct:+.1f}%)")
    else:
        st.text("No losers!")

# ---- Allocation Charts ----
st.divider()
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Allocation by Stock")
    if active_positions:
        alloc_data = pd.DataFrame([
            {"Ticker": p.ticker, "Value (S$)": p.current_value_sgd}
            for p in active_positions if p.current_value_sgd > 0
        ])
        if not alloc_data.empty:
            fig = px.pie(
                alloc_data,
                values="Value (S$)",
                names="Ticker",
                hole=0.4,
            )
            fig.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

with chart_col2:
    st.subheader("Allocation by Currency")
    if active_positions:
        currency_data = {}
        for p in active_positions:
            c = p.currency
            currency_data[c] = currency_data.get(c, 0) + p.current_value_sgd
        cdf = pd.DataFrame([
            {"Currency": k, "Value (S$)": v} for k, v in currency_data.items()
        ])
        if not cdf.empty:
            fig2 = px.pie(
                cdf,
                values="Value (S$)",
                names="Currency",
                hole=0.4,
            )
            fig2.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig2, use_container_width=True)

# ---- Recent Transactions ----
st.divider()
st.subheader("Recent Transactions")

recent = get_transactions(conn)[:10]
if recent:
    df = pd.DataFrame(recent)[["date", "ticker", "side", "price", "quantity", "broker"]]
    df.columns = ["Date", "Ticker", "Side", "Price", "Quantity", "Broker"]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.text("No transactions yet.")
