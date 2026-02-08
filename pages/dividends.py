"""Dividends tracker page: view dividends by year, ticker, and country."""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

from services.portfolio_engine import compute_portfolio
from services.dividend_service import get_dividend_summary_by_year
from utils.formatters import fmt_currency

st.header("Dividends")

conn = st.session_state.conn
current_year = datetime.now().year

# Compute portfolio to get dividend data
with st.spinner("Loading dividend data..."):
    positions = compute_portfolio(conn)

if not positions:
    st.info("No positions found. Add transactions first.")
    st.stop()

# Year filter
years = list(range(current_year, current_year - 4, -1))
selected_years = st.multiselect("Filter by Year", years, default=[current_year, current_year - 1])

# --- Summary by Year ---
year_summary = get_dividend_summary_by_year(conn, positions, current_year)

if year_summary:
    st.subheader("Dividend Summary by Year")
    summary_cols = st.columns(len(year_summary))
    for i, (year, total) in enumerate(year_summary.items()):
        with summary_cols[i]:
            st.metric(f"Year {year}", fmt_currency(total))

# --- Detailed Dividend Records ---
st.subheader("Dividend Details")

all_records = []
for pos in positions:
    for rec in pos.dividend_records:
        if not selected_years or rec["year"] in selected_years:
            all_records.append({
                "Ticker": pos.ticker,
                "Ex-Date": rec["ex_date"],
                "Year": rec["year"],
                "Div/Share": rec["div_per_share"],
                "Shares Held": rec["shares_held"],
                "Gross (Native)": rec["gross_native"],
                "Currency": rec["currency"],
                "WHT Rate": rec["wht_rate"],
                "Tax (Native)": rec["tax_native"],
                "Net (Native)": rec["net_native"],
                "FX Rate": rec["fx_rate"],
                "Net (S$)": rec["net_sgd"],
            })

if all_records:
    df = pd.DataFrame(all_records)
    df = df.sort_values(["Ex-Date", "Ticker"], ascending=[False, True])

    st.dataframe(
        df.style.format({
            "Div/Share": "{:.4f}",
            "Shares Held": "{:.2f}",
            "Gross (Native)": "{:,.2f}",
            "WHT Rate": "{:.0%}",
            "Tax (Native)": "{:,.2f}",
            "Net (Native)": "{:,.2f}",
            "FX Rate": "{:.4f}",
            "Net (S$)": "{:,.2f}",
        }),
        use_container_width=True,
        hide_index=True,
    )

    # Totals
    total_net_sgd = df["Net (S$)"].sum()
    total_tax_native = df["Tax (Native)"].sum()
    st.markdown(f"**Total Net Dividends (S$): {fmt_currency(total_net_sgd)}**")

    # Chart: Dividends by ticker
    st.subheader("Dividends by Ticker")
    ticker_div = df.groupby("Ticker")["Net (S$)"].sum().reset_index()
    ticker_div = ticker_div.sort_values("Net (S$)", ascending=False)

    fig = px.bar(
        ticker_div,
        x="Ticker",
        y="Net (S$)",
        title="Net Dividends by Ticker (S$)",
        color="Ticker",
    )
    fig.update_layout(
        height=400,
        margin=dict(l=0, r=0, t=40, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Chart: Dividends by year
    if len(df["Year"].unique()) > 1:
        st.subheader("Dividends by Year")
        year_div = df.groupby("Year")["Net (S$)"].sum().reset_index()
        year_div["Year"] = year_div["Year"].astype(str)

        fig_year = px.bar(
            year_div,
            x="Year",
            y="Net (S$)",
            title="Net Dividends by Year (S$)",
            color="Year",
        )
        fig_year.update_layout(
            height=400,
            margin=dict(l=0, r=0, t=40, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig_year, use_container_width=True)

else:
    st.info("No dividend records found for the selected period.")
