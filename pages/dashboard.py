"""Dashboard page: at-a-glance portfolio overview."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from collections import defaultdict

from models.transaction import get_transactions
from models.portfolio import get_portfolios, get_portfolio_filters
from services.cache import get_cached_portfolio
from utils.formatters import fmt_currency, fmt_pct

st.header("Dashboard")

conn = st.session_state.conn

# Compute portfolio (cached for 5 min)
with st.spinner("Loading portfolio..."):
    positions = get_cached_portfolio(conn)

if not positions:
    st.info("Welcome! Start by adding transactions in the **Transactions** page.")
    st.stop()

# ---- Key Metrics ----
active_positions = [p for p in positions if p.shares > 0]
total_investment = sum(p.total_investment_sgd for p in positions)  # ALL positions (includes fully sold)
total_cost_basis = sum(p.cost_basis_sgd for p in active_positions)
total_value = sum(p.current_value_sgd for p in active_positions)
total_realized = sum(p.realized_pnl_sgd for p in positions)
total_unrealized = sum(p.unrealized_pnl_sgd for p in active_positions)
total_pnl = total_realized + total_unrealized
total_return_pct = (total_pnl / total_investment * 100) if total_investment > 0 else 0

current_year = datetime.now().year
total_div_current = sum(p.dividends_for_year(current_year) for p in positions)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(
        "Market Value",
        fmt_currency(total_value),
        help="Current live price × shares held, converted to SGD at today's FX rate. Reflects only open (active) positions.",
    )
with col2:
    st.metric(
        "Total Investment",
        fmt_currency(total_investment),
        help="Sum of all BUY costs ever made, converted to SGD at today's FX rate. Includes positions that have since been sold — it never decreases on sells.",
    )
with col3:
    st.metric(
        "Total P&L",
        fmt_currency(total_pnl),
        delta=f"{total_return_pct:+.1f}%",
        help="Realised P&L (closed trades + net dividends after withholding tax) plus Unrealised P&L (Market Value − Exposure) for open positions. The % delta is Total P&L ÷ Total Investment.",
    )
with col4:
    st.metric(
        f"Dividends {current_year}",
        fmt_currency(total_div_current),
        help=f"Net dividends received in {current_year} after withholding tax (US 30%, SG/HK 0%, etc.), converted to SGD at the FX rate on each ex-dividend date.",
    )

# ---- Top Gainers / Losers ----
st.divider()
gain_col, loss_col = st.columns(2)

def _pnl_pct(p) -> float:
    return (p.total_pnl_sgd / p.cost_basis_sgd * 100) if p.cost_basis_sgd > 0 else 0.0

# Sort by P&L % descending (gainers: highest % first; losers: worst % first)
gainers = sorted(
    [p for p in active_positions if p.total_pnl_sgd > 0],
    key=_pnl_pct, reverse=True
)[:5]

losers = sorted(
    [p for p in active_positions if p.total_pnl_sgd < 0],
    key=_pnl_pct  # ascending — most negative first
)[:5]

with gain_col:
    st.subheader("Top Gainers")
    if gainers:
        for p in gainers:
            pct = _pnl_pct(p)
            st.markdown(f"**{p.ticker}** ({p.name}) — {fmt_currency(p.total_pnl_sgd)} ({pct:+.1f}%)")
    else:
        st.text("No gainers yet.")

with loss_col:
    st.subheader("Top Losers")
    if losers:
        for p in losers:
            pct = _pnl_pct(p)
            st.markdown(f"**{p.ticker}** ({p.name}) — {fmt_currency(p.total_pnl_sgd)} ({pct:+.1f}%)")
    else:
        st.text("No losers!")

# ---- Allocation Charts ----
st.divider()

def _make_pie(df, values_col, names_col, height=380):
    fig = px.pie(df, values=values_col, names=names_col, hole=0.4)
    fig.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=20, b=60),  # extra bottom margin prevents tooltip clipping
        hoverlabel=dict(bgcolor="white", bordercolor="gray", font_size=13),
    )
    fig.update_traces(
        textposition="inside",
        textinfo="percent+label",
        hovertemplate="<b>%{label}</b><br>Value (S$): %{value:,.0f}<br>%{percent}<extra></extra>",
    )
    return fig

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Allocation by Stock")
    if active_positions:
        alloc_data = pd.DataFrame([
            {"Ticker": p.ticker, "Value (S$)": p.current_value_sgd}
            for p in active_positions if p.current_value_sgd > 0
        ])
        if not alloc_data.empty:
            st.plotly_chart(_make_pie(alloc_data, "Value (S$)", "Ticker"),
                            use_container_width=True)

with chart_col2:
    st.subheader("Allocation by Currency")
    if active_positions:
        currency_data: dict[str, float] = {}
        for p in active_positions:
            currency_data[p.currency] = currency_data.get(p.currency, 0) + p.current_value_sgd
        cdf = pd.DataFrame([{"Currency": k, "Value (S$)": v}
                             for k, v in currency_data.items()])
        if not cdf.empty:
            st.plotly_chart(_make_pie(cdf, "Value (S$)", "Currency"),
                            use_container_width=True)

# ---- Allocation by Broker + by Custom Portfolio ----
broker_col, portfolio_col = st.columns(2)

with broker_col:
    st.subheader("Allocation by Broker")
    if active_positions:
        # Compute net shares per (ticker, broker) from raw transactions
        all_txns = get_transactions(conn)
        broker_buy_shares: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for txn in all_txns:
            if txn["side"] == "BUY":
                broker_buy_shares[txn["ticker"].upper()][txn["broker"]] += txn["quantity"]

        pos_map = {p.ticker.upper(): p for p in active_positions}
        broker_value: dict[str, float] = defaultdict(float)

        for ticker, brokers in broker_buy_shares.items():
            pos = pos_map.get(ticker)
            if not pos or pos.current_value_sgd <= 0:
                continue
            total_buy = sum(brokers.values())
            if total_buy <= 0:
                continue
            for broker, qty in brokers.items():
                broker_value[broker] += (qty / total_buy) * pos.current_value_sgd

        if broker_value:
            bdf = pd.DataFrame([{"Broker": k, "Value (S$)": v}
                                 for k, v in broker_value.items()])
            st.plotly_chart(_make_pie(bdf, "Value (S$)", "Broker"),
                            use_container_width=True)
        else:
            st.info("No broker data available.")

with portfolio_col:
    custom_portfolios = get_portfolios(conn)
    if custom_portfolios and active_positions:
        st.subheader("Allocation by Portfolio")
        pos_map = {p.ticker.upper(): p for p in active_positions}
        portfolio_value: dict[str, float] = {}
        assigned: set[str] = set()

        for cp in custom_portfolios:
            filters = get_portfolio_filters(conn, cp["id"])
            ticker_rules = set(t.upper() for t in (filters.get("tickers") or []))
            broker_rules = set(b.upper() for b in (filters.get("brokers") or []))

            cp_value = 0.0
            if ticker_rules:
                for ticker in ticker_rules:
                    pos = pos_map.get(ticker)
                    if pos and pos.current_value_sgd > 0:
                        cp_value += pos.current_value_sgd
                        assigned.add(ticker)

            if broker_rules:
                # Allocate market value proportionally for broker-based portfolios
                all_txns_for_broker = get_transactions(conn)
                broker_buy: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
                for txn in all_txns_for_broker:
                    if txn["side"] == "BUY":
                        broker_buy[txn["ticker"].upper()][txn["broker"].upper()] += txn["quantity"]
                for ticker, brokers in broker_buy.items():
                    if any(b in broker_rules for b in brokers):
                        pos = pos_map.get(ticker)
                        if not pos or pos.current_value_sgd <= 0:
                            continue
                        total_buy = sum(brokers.values())
                        matched = sum(qty for b, qty in brokers.items() if b in broker_rules)
                        if total_buy > 0:
                            cp_value += (matched / total_buy) * pos.current_value_sgd
                            assigned.add(ticker)

            if cp_value > 0:
                portfolio_value[cp["name"]] = cp_value

        # Positions not covered by any portfolio
        unassigned = sum(
            p.current_value_sgd for p in active_positions
            if p.ticker.upper() not in assigned and p.current_value_sgd > 0
        )
        if unassigned > 0:
            portfolio_value["Unassigned"] = unassigned

        if portfolio_value:
            pdf = pd.DataFrame([{"Portfolio": k, "Value (S$)": v}
                                 for k, v in portfolio_value.items()])
            st.plotly_chart(_make_pie(pdf, "Value (S$)", "Portfolio"),
                            use_container_width=True)

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
