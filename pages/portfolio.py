"""Portfolio page: entire portfolio, by-broker, and custom portfolio views."""

import streamlit as st
import pandas as pd
from datetime import datetime

from models.transaction import get_distinct_brokers, get_distinct_tickers
from models.portfolio import (
    get_portfolios,
    create_portfolio,
    delete_portfolio,
    add_rule,
    get_rules,
    clear_rules,
    get_portfolio_filters,
)
from services.portfolio_engine import positions_to_dataframe
from services.cache import get_cached_portfolio, invalidate_portfolio_cache
from utils.formatters import fmt_currency

st.header("Portfolio")

conn = st.session_state.conn
current_year = datetime.now().year

# --- View Selector ---
view_mode = st.radio(
    "View",
    ["Entire Portfolio", "By Broker", "Custom Portfolio"],
    horizontal=True,
)

brokers_filter = None
tickers_filter = None

if view_mode == "By Broker":
    all_brokers = get_distinct_brokers(conn)
    if all_brokers:
        selected_broker = st.selectbox("Select Broker", all_brokers)
        brokers_filter = [selected_broker]
    else:
        st.info("No transactions found. Add some in the Transactions page.")
        st.stop()

elif view_mode == "Custom Portfolio":
    portfolios = get_portfolios(conn)

    # Management section
    with st.expander("Manage Custom Portfolios", expanded=not portfolios):
        # Create new
        with st.form("create_portfolio"):
            cp_name = st.text_input("Portfolio Name")
            cp_desc = st.text_input("Description (optional)")
            if st.form_submit_button("Create Portfolio"):
                if cp_name.strip():
                    try:
                        create_portfolio(conn, cp_name.strip(), cp_desc)
                        st.success(f"Created portfolio: {cp_name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        # Edit rules for existing portfolios
        if portfolios:
            st.markdown("---")
            st.markdown("**Add Rules to Portfolio**")
            rule_portfolio = st.selectbox(
                "Select portfolio to edit",
                portfolios,
                format_func=lambda p: p["name"],
                key="rule_portfolio",
            )
            if rule_portfolio:
                existing_rules = get_rules(conn, rule_portfolio["id"])
                if existing_rules:
                    st.markdown("Current rules:")
                    for r in existing_rules:
                        st.text(f"  - {r['rule_type']}: {r['rule_value']}")

                rule_cols = st.columns(3)
                with rule_cols[0]:
                    rule_type = st.selectbox("Rule Type", ["BROKER", "TICKER"])
                with rule_cols[1]:
                    if rule_type == "BROKER":
                        rule_value = st.selectbox("Value", get_distinct_brokers(conn))
                    else:
                        rule_value = st.selectbox("Value", get_distinct_tickers(conn))
                with rule_cols[2]:
                    st.markdown("")
                    st.markdown("")
                    if st.button("Add Rule"):
                        add_rule(conn, rule_portfolio["id"], rule_type, rule_value)
                        st.rerun()

                btn_cols = st.columns(2)
                with btn_cols[0]:
                    if st.button("Clear All Rules"):
                        clear_rules(conn, rule_portfolio["id"])
                        st.rerun()
                with btn_cols[1]:
                    if st.button("Delete Portfolio"):
                        delete_portfolio(conn, rule_portfolio["id"])
                        st.rerun()

    # Select portfolio to view
    if portfolios:
        selected_portfolio = st.selectbox(
            "View Portfolio",
            portfolios,
            format_func=lambda p: p["name"],
            key="view_portfolio",
        )
        if selected_portfolio:
            filters = get_portfolio_filters(conn, selected_portfolio["id"])
            brokers_filter = filters.get("brokers")
            tickers_filter = filters.get("tickers")
            if not brokers_filter and not tickers_filter:
                st.warning("This portfolio has no rules defined. Add some above.")
                st.stop()
    else:
        st.info("Create a custom portfolio above to get started.")
        st.stop()

# --- Compute and Display Portfolio ---
if st.button("Refresh Portfolio Data", type="primary"):
    invalidate_portfolio_cache()

with st.spinner("Computing portfolio..."):
    positions = get_cached_portfolio(conn, brokers=brokers_filter, tickers=tickers_filter)

if not positions:
    st.info("No positions found for the selected view.")
    st.stop()

# Convert to DataFrame
df = positions_to_dataframe(positions, current_year)

# Summary metrics
total_investment = sum(p.total_investment_sgd for p in positions)
total_cost_basis = sum(p.cost_basis_sgd for p in positions)
total_value = sum(p.current_value_sgd for p in positions)
total_realized = sum(p.realized_pnl_sgd for p in positions)
total_unrealized = sum(p.unrealized_pnl_sgd for p in positions)
total_pnl = total_realized + total_unrealized

metric_cols = st.columns(6)
with metric_cols[0]:
    st.metric("Total Investment", fmt_currency(total_investment))
with metric_cols[1]:
    st.metric("Exposure", fmt_currency(total_cost_basis))
with metric_cols[2]:
    st.metric("Market Value", fmt_currency(total_value))
with metric_cols[3]:
    st.metric("Realised P&L", fmt_currency(total_realized),
              delta=f"{total_realized:+,.2f}")
with metric_cols[4]:
    st.metric("Unrealised P&L", fmt_currency(total_unrealized),
              delta=f"{total_unrealized:+,.2f}")
with metric_cols[5]:
    st.metric("Total P&L", fmt_currency(total_pnl),
              delta=f"{total_pnl:+,.2f}")

# Display table
st.dataframe(
    df.style.format({
        "Shares": "{:.2f}",
        "Market Px": "{:.2f}",
        "Avg Cost/Share": "{:.2f}",
        "Investment (S$)": "{:,.2f}",
        "Exposure (S$)": "{:,.2f}",
        "Market Value (S$)": "{:,.2f}",
        "Realised P&L (S$)": "{:+,.2f}",
        "Unrealised P&L (S$)": "{:+,.2f}",
        "P&L (S$)": "{:+,.2f}",
        "P&L %": "{:+.2f}%",
        f"Div {current_year-2} (S$)": "{:,.2f}",
        f"Div {current_year-1} (S$)": "{:,.2f}",
        f"Div {current_year} (S$)": "{:,.2f}",
    }).map(
        lambda v: "color: green" if isinstance(v, (int, float)) and v > 0 else
                  ("color: red" if isinstance(v, (int, float)) and v < 0 else ""),
        subset=["Realised P&L (S$)", "Unrealised P&L (S$)", "P&L (S$)", "P&L %"],
    ),
    use_container_width=True,
    hide_index=True,
)

# Summary row
st.markdown("---")
summary_cols = st.columns(4)
total_div_current = sum(p.dividends_for_year(current_year) for p in positions)
total_div_prev = sum(p.dividends_for_year(current_year - 1) for p in positions)
with summary_cols[0]:
    st.metric(f"Dividends {current_year}", fmt_currency(total_div_current))
with summary_cols[1]:
    st.metric(f"Dividends {current_year - 1}", fmt_currency(total_div_prev))
with summary_cols[2]:
    pct_return = (total_pnl / total_investment * 100) if total_investment > 0 else 0
    st.metric("Return %", f"{pct_return:+.2f}%")
with summary_cols[3]:
    active_positions = sum(1 for p in positions if p.shares > 0)
    st.metric("Active Positions", str(active_positions))

# --- View Chart ---
st.markdown("---")
chart_cols = st.columns([4, 1])
pos_tickers = sorted(p.ticker for p in positions)
with chart_cols[0]:
    chart_sel = st.selectbox("View price chart for:", pos_tickers, key="portfolio_chart_sel")
with chart_cols[1]:
    st.markdown("&nbsp;")
    if st.button("Open Chart →", use_container_width=True, key="portfolio_chart_btn"):
        st.session_state["chart_ticker"] = chart_sel
        st.switch_page("pages/stocks.py")
