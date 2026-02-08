"""Performance page: XIRR, benchmark comparison, charts."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from services.portfolio_engine import compute_portfolio
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

# Compute portfolio
with st.spinner("Loading portfolio data..."):
    positions = compute_portfolio(conn)

if not positions:
    st.info("No positions found. Add transactions first.")
    st.stop()

# --- Benchmark Selection ---
benchmark_options = list(DEFAULT_BENCHMARKS.keys())
selected_benchmarks = st.multiselect(
    "Benchmarks for comparison",
    benchmark_options,
    default=["VOO"],
    format_func=lambda k: DEFAULT_BENCHMARKS[k],
)

# --- XIRR Metrics ---
st.subheader("Returns")

with st.spinner("Calculating XIRR..."):
    portfolio_xirr = calculate_portfolio_xirr(positions)

    benchmark_xirrs = {}
    for bm in selected_benchmarks:
        bm_xirr = calculate_benchmark_xirr(conn, positions, bm)
        benchmark_xirrs[bm] = bm_xirr

# Display metrics
total_investment = sum(p.total_investment_sgd for p in positions)
total_value = sum(p.current_value_sgd for p in positions)
total_pnl = sum(p.total_pnl_sgd for p in positions)
total_return_pct = ((total_value - total_investment) / total_investment * 100) if total_investment > 0 else 0

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
        bm_display = fmt_pct(bm_xirr * 100) if bm_xirr is not None else "N/A"
        st.metric(f"{DEFAULT_BENCHMARKS[bm]} XIRR", bm_display)

# --- Charts ---
st.subheader("Investment Over Time")

inv_df = compute_investment_over_time(positions)
if not inv_df.empty:
    fig_inv = go.Figure()
    fig_inv.add_trace(go.Scatter(
        x=inv_df["date"],
        y=inv_df["cumulative_investment"],
        mode="lines+markers",
        name="Cumulative Investment (S$)",
        fill="tozeroy",
        line=dict(color="#1f77b4"),
    ))
    fig_inv.update_layout(
        yaxis_title="S$",
        xaxis_title="Date",
        height=400,
        margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig_inv, use_container_width=True)

# Portfolio Value Over Time
st.subheader("Portfolio Value Over Time")

freq = st.radio("Frequency", ["Weekly", "Monthly"], horizontal=True, key="value_freq")
freq_code = "W" if freq == "Weekly" else "ME"

with st.spinner("Computing historical portfolio values..."):
    val_df = compute_portfolio_value_over_time(conn, positions, freq=freq_code)

if not val_df.empty:
    fig_val = go.Figure()
    fig_val.add_trace(go.Scatter(
        x=val_df["date"],
        y=val_df["value_sgd"],
        mode="lines",
        name="Portfolio Value (S$)",
        line=dict(color="#2ca02c"),
    ))

    # Add investment line for reference
    if not inv_df.empty:
        # Resample investment to same frequency
        inv_resampled = inv_df.set_index("date").resample(freq_code).last().ffill().reset_index()
        fig_val.add_trace(go.Scatter(
            x=inv_resampled["date"],
            y=inv_resampled["cumulative_investment"],
            mode="lines",
            name="Cost Basis (S$)",
            line=dict(color="#1f77b4", dash="dash"),
        ))

    fig_val.update_layout(
        yaxis_title="S$",
        xaxis_title="Date",
        height=400,
        margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig_val, use_container_width=True)

# Benchmark Comparison Chart
if selected_benchmarks:
    st.subheader("Portfolio vs Benchmark(s)")

    with st.spinner("Computing benchmark values..."):
        fig_bench = go.Figure()

        # Portfolio value
        if not val_df.empty:
            fig_bench.add_trace(go.Scatter(
                x=val_df["date"],
                y=val_df["value_sgd"],
                mode="lines",
                name="Your Portfolio",
                line=dict(color="#2ca02c", width=2),
            ))

        # Benchmark values
        colors = ["#ff7f0e", "#d62728", "#9467bd", "#8c564b"]
        for i, bm in enumerate(selected_benchmarks):
            bm_val_df = compute_benchmark_value_over_time(conn, positions, bm, freq=freq_code)
            if not bm_val_df.empty:
                fig_bench.add_trace(go.Scatter(
                    x=bm_val_df["date"],
                    y=bm_val_df["value_sgd"],
                    mode="lines",
                    name=DEFAULT_BENCHMARKS[bm],
                    line=dict(color=colors[i % len(colors)], dash="dot"),
                ))

        fig_bench.update_layout(
            yaxis_title="Value (S$)",
            xaxis_title="Date",
            height=450,
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        )
        st.plotly_chart(fig_bench, use_container_width=True)
