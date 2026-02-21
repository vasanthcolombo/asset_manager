"""Dividends tracker page: view dividends by year, ticker, and country."""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

from services.cache import get_cached_portfolio
from utils.formatters import fmt_currency

st.header("Dividends")

conn = st.session_state.conn

with st.spinner("Loading dividend data..."):
    positions = get_cached_portfolio(conn)

if not positions:
    st.info("No positions found. Add transactions first.")
    st.stop()

# Collect ALL dividend records across all positions and all years
all_records = []
for pos in positions:
    for rec in pos.dividend_records:
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

if not all_records:
    st.info("No dividend records found.")
    st.stop()

df = pd.DataFrame(all_records)
df = df.sort_values(["Ex-Date", "Ticker"], ascending=[False, True])

all_years = sorted(df["Year"].unique(), reverse=True)

# --- Summary metrics by year ---
st.subheader("Summary by Year")
year_totals = df.groupby("Year")["Net (S$)"].sum()
cols = st.columns(min(len(all_years), 6))
for i, year in enumerate(all_years[:6]):
    with cols[i]:
        st.metric(str(year), fmt_currency(year_totals.get(year, 0)))

# --- Dividends by Year bar chart ---
st.subheader("Dividends by Year")
year_div = df.groupby("Year")["Net (S$)"].sum().reset_index().sort_values("Year")
year_div["Year"] = year_div["Year"].astype(str)

fig_year = px.bar(
    year_div,
    x="Year",
    y="Net (S$)",
    title="Net Dividends by Year (S$)",
    color="Year",
)
fig_year.update_layout(
    height=350,
    margin=dict(l=0, r=0, t=40, b=0),
    showlegend=False,
    xaxis=dict(type="category"),
)
st.plotly_chart(fig_year, use_container_width=True)

# --- Per-year breakdown: select year to see per-stock chart ---
st.subheader("Breakdown by Stock")
selected_year = st.selectbox("Select Year", all_years, format_func=str)

year_df = df[df["Year"] == selected_year]
ticker_div = year_df.groupby("Ticker")["Net (S$)"].sum().reset_index()
ticker_div = ticker_div.sort_values("Net (S$)", ascending=False)

if not ticker_div.empty:
    fig_ticker = px.bar(
        ticker_div,
        x="Ticker",
        y="Net (S$)",
        title=f"Net Dividends by Stock — {selected_year}",
        color="Ticker",
    )
    fig_ticker.update_layout(
        height=350,
        margin=dict(l=0, r=0, t=40, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig_ticker, use_container_width=True)
    st.caption(f"Total net dividends in {selected_year}: **{fmt_currency(ticker_div['Net (S$)'].sum())}**")

# --- Detailed table with column filters ---
st.subheader("Dividend Details")

filter_cols = st.columns(3)
with filter_cols[0]:
    ticker_options = sorted(df["Ticker"].unique())
    filter_tickers = st.multiselect("Ticker", ticker_options, default=[])
with filter_cols[1]:
    year_options = sorted(df["Year"].unique(), reverse=True)
    filter_years = st.multiselect("Year", year_options, default=[], format_func=str)
with filter_cols[2]:
    ccy_options = sorted(df["Currency"].unique())
    filter_ccys = st.multiselect("Currency", ccy_options, default=[])

display_df = df.copy()
if filter_tickers:
    display_df = display_df[display_df["Ticker"].isin(filter_tickers)]
if filter_years:
    display_df = display_df[display_df["Year"].isin(filter_years)]
if filter_ccys:
    display_df = display_df[display_df["Currency"].isin(filter_ccys)]

if not display_df.empty:
    st.dataframe(
        display_df.style.format({
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
    total_net_sgd = display_df["Net (S$)"].sum()
    st.markdown(f"**Total Net Dividends (S$): {fmt_currency(total_net_sgd)}**")
else:
    st.info("No dividend records match the selected filters.")
