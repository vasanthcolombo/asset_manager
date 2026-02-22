"""Money Manager — Stats page: income/expense charts by period."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from calendar import monthrange

from models.mm_account import get_accounts
from services.mm_service import get_stats
from utils.formatters import fmt_currency

st.header("Stats")

conn = st.session_state.conn

# ── Period Selector ───────────────────────────────────────────────────────────
today = date.today()

period_mode = st.radio(
    "Period",
    ["This Week", "This Month", "This Year", "Custom"],
    horizontal=True,
    index=1,  # default: This Month
    key="mm_stats_period",
)

if period_mode == "This Week":
    # Monday–Sunday of current week
    start = today - timedelta(days=today.weekday())
    end = today
elif period_mode == "This Month":
    start = today.replace(day=1)
    end = today
elif period_mode == "This Year":
    start = today.replace(month=1, day=1)
    end = today
else:
    custom_range = st.date_input(
        "Select date range",
        value=[today.replace(day=1), today],
        key="mm_stats_custom_range",
    )
    if len(custom_range) == 2:
        start, end = custom_range
    else:
        start = end = today

date_from = start.strftime("%Y-%m-%d")
date_to   = end.strftime("%Y-%m-%d")

# Optional account filter
accounts = get_accounts(conn, active_only=True)
acc_names = [f"{a['name']} ({a['group_name']})" for a in accounts]
sel_accounts = st.multiselect("Filter by Account (optional)", acc_names, key="mm_stats_accs")

# ── Compute ───────────────────────────────────────────────────────────────────
with st.spinner("Computing stats..."):
    stats = get_stats(conn, date_from, date_to)

income_data  = stats["income_by_category"]
expense_data = stats["expense_by_category"]
period_df    = stats["by_period"]

total_income  = sum(r["amount_sgd"] for r in income_data)
total_expense = sum(r["amount_sgd"] for r in expense_data)
net_flow      = total_income - total_expense

# ── Summary Metrics ───────────────────────────────────────────────────────────
m_cols = st.columns(3)
with m_cols[0]:
    st.metric(
        "Total Income",
        fmt_currency(total_income),
        help="Sum of all INCOME transactions in the selected period, converted to SGD.",
    )
with m_cols[1]:
    st.metric(
        "Total Expenses",
        fmt_currency(total_expense),
        help="Sum of all EXPENSE transactions in the selected period, converted to SGD.",
    )
with m_cols[2]:
    st.metric(
        "Net Cash Flow",
        fmt_currency(net_flow),
        delta=f"{net_flow:+,.0f}",
        help="Income minus Expenses for the selected period.",
    )

st.divider()

# ── Charts ────────────────────────────────────────────────────────────────────
def _make_donut(data: list[dict], title: str, color_seq=None) -> go.Figure:
    if not data:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False, font_size=14)
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10))
        return fig
    df = pd.DataFrame(data)
    fig = px.pie(
        df,
        values="amount_sgd",
        names="category",
        hole=0.4,
        color_discrete_sequence=color_seq,
        title=title,
    )
    fig.update_traces(
        textposition="inside",
        textinfo="percent+label",
        hovertemplate="<b>%{label}</b><br>S$%{value:,.2f}<br>%{percent}<extra></extra>",
    )
    fig.update_layout(
        height=340,
        margin=dict(l=10, r=10, t=40, b=40),
        hoverlabel=dict(bgcolor="white", bordercolor="gray", font_size=13),
        showlegend=False,
    )
    return fig

row1_col1, row1_col2 = st.columns(2)

with row1_col1:
    fig_exp = _make_donut(
        expense_data,
        "Expenses by Category",
        color_seq=px.colors.qualitative.Set2,
    )
    st.plotly_chart(fig_exp, use_container_width=True)

with row1_col2:
    fig_inc = _make_donut(
        income_data,
        "Income by Category",
        color_seq=px.colors.qualitative.Pastel,
    )
    st.plotly_chart(fig_inc, use_container_width=True)

# ── Income vs Expenses Bar Chart ──────────────────────────────────────────────
row2_col1, row2_col2 = st.columns(2)

with row2_col1:
    if not period_df.empty:
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            x=period_df["period"],
            y=period_df["income"],
            name="Income",
            marker_color="#2ca02c",
        ))
        fig_bar.add_trace(go.Bar(
            x=period_df["period"],
            y=period_df["expense"],
            name="Expenses",
            marker_color="#d62728",
        ))
        fig_bar.update_layout(
            title="Income vs Expenses by Month",
            barmode="group",
            height=340,
            margin=dict(l=0, r=0, t=40, b=0),
            yaxis_title="S$",
            xaxis=dict(type="category"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No transactions in selected period.")

with row2_col2:
    if not period_df.empty:
        fig_net = go.Figure()
        fig_net.add_trace(go.Scatter(
            x=period_df["period"],
            y=period_df["cumulative_net"],
            mode="lines+markers",
            name="Cumulative Net",
            fill="tozeroy",
            fillcolor="rgba(31, 119, 180, 0.15)",
            line=dict(color="#1f77b4", width=2),
        ))
        fig_net.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
        fig_net.update_layout(
            title="Cumulative Net Cash Flow",
            height=340,
            margin=dict(l=0, r=0, t=40, b=0),
            yaxis_title="S$",
            xaxis=dict(type="category"),
            showlegend=False,
        )
        st.plotly_chart(fig_net, use_container_width=True)
    else:
        st.info("No transactions in selected period.")

# ── Transaction Detail Table ──────────────────────────────────────────────────
st.divider()
st.subheader("Transaction Detail")

from models.mm_transaction import get_mm_transactions
txns = get_mm_transactions(conn, date_from=date_from, date_to=date_to)

if txns:
    rows = []
    for t in txns:
        if t["type"] == "TRANSFER":
            continue
        fx = t.get("fx_rate_to_default") or 1.0
        amount_sgd = t["amount"] * fx if t["currency"] != "SGD" else t["amount"]
        rows.append({
            "Date": t["date"],
            "Type": t["type"],
            "Account": t["account_name"],
            "Category": t.get("category_name") or "",
            "Amount": f"{t['currency']} {t['amount']:,.2f}",
            "S$": f"{amount_sgd:,.2f}",
            "Notes": t.get("notes") or "",
        })
    if rows:
        df = pd.DataFrame(rows)

        # Filters
        filter_cols = st.columns(2)
        with filter_cols[0]:
            acc_filter = st.multiselect("Account", df["Account"].unique().tolist(), key="stat_acc_filter")
        with filter_cols[1]:
            cat_filter = st.multiselect("Category", df["Category"].unique().tolist(), key="stat_cat_filter")

        if acc_filter:
            df = df[df["Account"].isin(acc_filter)]
        if cat_filter:
            df = df[df["Category"].isin(cat_filter)]

        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No income/expense transactions in selected period.")
else:
    st.info("No transactions in selected period.")
