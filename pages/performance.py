"""Performance page: XIRR, benchmark comparison, combined chart."""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

from services.cache import (
    get_cached_portfolio,
    get_transaction_fingerprint,
    get_db_performance_cache,
    store_db_performance_cache,
)
from services.performance_engine import (
    calculate_portfolio_xirr,
    calculate_benchmark_xirr,
    compute_investment_over_time,
    compute_portfolio_value_over_time,
    compute_benchmark_value_over_time,
)
from config import DEFAULT_BENCHMARKS
from utils.formatters import fmt_currency, fmt_pct

st.header("Performance & Charts")

conn = st.session_state.conn

with st.spinner("Loading portfolio data..."):
    positions = get_cached_portfolio(conn)

if not positions:
    st.info("No positions found. Add transactions first.")
    st.stop()

# --- Benchmark Selection + Frequency ---
top_cols = st.columns([3, 1])
with top_cols[0]:
    benchmark_options = list(DEFAULT_BENCHMARKS.keys())
    selected_benchmarks = st.multiselect(
        "Benchmarks for comparison",
        benchmark_options,
        default=["VOO"],
        format_func=lambda k: DEFAULT_BENCHMARKS[k],
    )
with top_cols[1]:
    freq = st.radio("Frequency", ["Weekly", "Monthly"], horizontal=True, key="value_freq")
    freq_code = "W" if freq == "Weekly" else "ME"

# --- XIRR Metrics ---
st.subheader("Returns")

with st.spinner("Calculating returns..."):
    portfolio_xirr = calculate_portfolio_xirr(positions)
    benchmark_xirrs = {bm: calculate_benchmark_xirr(conn, positions, bm) for bm in selected_benchmarks}

total_investment = sum(p.total_investment_sgd for p in positions)
total_pnl = sum(p.total_pnl_sgd for p in positions)
total_return_pct = (total_pnl / total_investment * 100) if total_investment > 0 else 0

cols = st.columns(3 + len(selected_benchmarks))
with cols[0]:
    st.metric("Total Return", fmt_pct(total_return_pct))
with cols[1]:
    xirr_display = fmt_pct(portfolio_xirr * 100) if portfolio_xirr is not None else "N/A"
    st.metric("Portfolio XIRR", xirr_display)
with cols[2]:
    st.metric("Total P&L (S$)", fmt_currency(total_pnl))
for i, bm in enumerate(selected_benchmarks):
    with cols[3 + i]:
        bm_xirr = benchmark_xirrs.get(bm)
        st.metric(f"{DEFAULT_BENCHMARKS[bm]} XIRR", fmt_pct(bm_xirr * 100) if bm_xirr else "N/A")

# --- Combined Chart ---
st.subheader("Portfolio vs Benchmarks")
st.caption("Cumulative investment (filled), portfolio market value, and behavior-matched benchmark values — all on the same scale.")

# Include today's date in fingerprint so cache refreshes daily (fresh prices each day)
today = datetime.now().strftime("%Y-%m-%d")
fingerprint = get_transaction_fingerprint(conn) + f"_{today}"

# Cumulative investment (fast, no cache needed — pure computation)
inv_df = compute_investment_over_time(positions)

# Live portfolio value — always current (matches portfolio page)
live_value_sgd = sum(p.current_value_sgd for p in positions)

# Portfolio value over time (DB cached, refreshes daily)
val_cache_key = f"portfolio_value_{freq_code}"
with st.spinner("Loading portfolio value history..."):
    val_df = get_db_performance_cache(conn, val_cache_key, fingerprint)
    if val_df is None:
        val_df = compute_portfolio_value_over_time(conn, positions, freq=freq_code)
        if not val_df.empty:
            # Append today's live value as the final data point
            live_row = pd.DataFrame({"date": [pd.Timestamp(today)], "value_sgd": [live_value_sgd]})
            val_df = pd.concat([val_df, live_row], ignore_index=True).drop_duplicates("date", keep="last")
            val_df = val_df.sort_values("date").reset_index(drop=True)
            store_db_performance_cache(conn, val_cache_key, val_df, fingerprint)

# Benchmark values (DB cached per benchmark)
bm_dfs = {}
if selected_benchmarks:
    with st.spinner("Loading benchmark values..."):
        for bm in selected_benchmarks:
            bm_key = f"benchmark_value_{bm}_{freq_code}"
            bm_df = get_db_performance_cache(conn, bm_key, fingerprint)
            if bm_df is None:
                bm_df = compute_benchmark_value_over_time(conn, positions, bm, freq=freq_code)
                if not bm_df.empty:
                    store_db_performance_cache(conn, bm_key, bm_df, fingerprint)
            bm_dfs[bm] = bm_df

# Build combined chart
fig = go.Figure()

# Trace 1: Cumulative investment (light fill behind everything)
if not inv_df.empty:
    inv_resampled = inv_df.set_index("date").resample(freq_code).last().ffill().reset_index()
    fig.add_trace(go.Scatter(
        x=inv_resampled["date"],
        y=inv_resampled["cumulative_investment"],
        mode="lines",
        name="Net Invested (S$)",
        fill="tozeroy",
        fillcolor="rgba(31, 119, 180, 0.10)",
        line=dict(color="#1f77b4", dash="dash", width=1.5),
    ))

# Trace 2: Portfolio market value (solid green)
if not val_df.empty:
    fig.add_trace(go.Scatter(
        x=val_df["date"],
        y=val_df["value_sgd"],
        mode="lines",
        name="Your Portfolio",
        line=dict(color="#2ca02c", width=2.5),
    ))

# Trace 3+: Benchmark values (dotted, cycling colors)
bench_colors = ["#ff7f0e", "#d62728", "#9467bd", "#8c564b"]
for i, bm in enumerate(selected_benchmarks):
    bm_df = bm_dfs.get(bm)
    if bm_df is not None and not bm_df.empty:
        fig.add_trace(go.Scatter(
            x=bm_df["date"],
            y=bm_df["value_sgd"],
            mode="lines",
            name=DEFAULT_BENCHMARKS[bm],
            line=dict(color=bench_colors[i % len(bench_colors)], dash="dot", width=2),
        ))

fig.update_layout(
    yaxis_title="Value (S$)",
    xaxis_title="Date",
    height=520,
    margin=dict(l=0, r=0, t=30, b=0),
    legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)
