"""Money Manager — Stats page: income/expense summary + charts."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta

from models.mm_account import get_account_groups, get_accounts
from models.mm_settings import get_mm_setting
from models.mm_transaction import get_mm_transactions
from services.mm_service import amount_in_default
from utils.mm_ui import account_filter_widget

st.header("Stats")

conn        = st.session_state.conn
default_ccy = get_mm_setting(conn, "default_currency", "SGD")

# ── Period Selector ───────────────────────────────────────────────────────────
today = date.today()

period_mode = st.radio(
    "Period",
    ["This Week", "This Month", "This Year", "Custom"],
    horizontal=True,
    index=1,
    key="mm_stats_period",
)

if period_mode == "This Week":
    start = today - timedelta(days=today.weekday())
    end   = today
elif period_mode == "This Month":
    start = today.replace(day=1)
    end   = today
elif period_mode == "This Year":
    start = today.replace(month=1, day=1)
    end   = today
else:
    custom_range = st.date_input(
        "Select date range",
        value=[today.replace(day=1), today],
        key="mm_stats_custom_range",
    )
    start, end = (custom_range if len(custom_range) == 2 else (today, today))

date_from = start.strftime("%Y-%m-%d")
date_to   = end.strftime("%Y-%m-%d")

# ── Account Filter ────────────────────────────────────────────────────────────
all_groups   = get_account_groups(conn)
all_accounts = get_accounts(conn, active_only=False)

st.caption("Account")
sel_acc_ids = account_filter_widget("stats_accs", all_groups, all_accounts)

# ── Fetch & filter transactions ───────────────────────────────────────────────
all_txns = get_mm_transactions(conn, date_from=date_from, date_to=date_to)
txns = [
    t for t in all_txns
    if not sel_acc_ids
    or t["account_id"] in sel_acc_ids
    or t.get("to_account_id") in sel_acc_ids
]

# ── Aggregate for charts (INCOME/EXPENSE only, skip TRANSFER) ────────────────
income_cat:  dict[str, float] = {}
expense_cat: dict[str, float] = {}
period_rows: dict[str, dict]  = {}

for t in txns:
    if t["type"] == "TRANSFER":
        continue
    amt    = amount_in_default(t["amount"], t["currency"], t.get("fx_rate_to_default"), default_ccy)
    cat    = t.get("category_name") or "Uncategorized"
    period = t["date"][:7]
    if period not in period_rows:
        period_rows[period] = {"period": period, "income": 0.0, "expense": 0.0}
    if t["type"] == "INCOME":
        income_cat[cat] = income_cat.get(cat, 0.0) + amt
        period_rows[period]["income"] += amt
    elif t["type"] == "EXPENSE":
        expense_cat[cat] = expense_cat.get(cat, 0.0) + amt
        period_rows[period]["expense"] += amt

income_data  = [{"category": k, "amount": v} for k, v in sorted(income_cat.items(),  key=lambda x: -x[1]) if v > 0]
expense_data = [{"category": k, "amount": v} for k, v in sorted(expense_cat.items(), key=lambda x: -x[1]) if v > 0]

if period_rows:
    period_df = pd.DataFrame(sorted(period_rows.values(), key=lambda r: r["period"]))
    period_df["net"]            = period_df["income"] - period_df["expense"]
    period_df["cumulative_net"] = period_df["net"].cumsum()
else:
    period_df = pd.DataFrame(columns=["period", "income", "expense", "net", "cumulative_net"])

total_income  = sum(r["amount"] for r in income_data)
total_expense = sum(r["amount"] for r in expense_data)
net_flow      = total_income - total_expense

# ── Summary Metrics ───────────────────────────────────────────────────────────
m_cols = st.columns(3)
with m_cols[0]:
    st.metric(
        "Total Income",
        f"{default_ccy} {total_income:,.2f}",
        help=f"Sum of all INCOME transactions in the selected period, converted to {default_ccy}.",
    )
with m_cols[1]:
    st.metric(
        "Total Expenses",
        f"{default_ccy} {total_expense:,.2f}",
        help=f"Sum of all EXPENSE transactions in the selected period, converted to {default_ccy}.",
    )
with m_cols[2]:
    st.metric(
        "Net Cash Flow",
        f"{default_ccy} {net_flow:,.2f}",
        delta=f"{net_flow:+,.0f}",
        help="Income minus Expenses for the selected period.",
    )

st.divider()

# ── Charts ────────────────────────────────────────────────────────────────────
def _make_donut(data: list[dict], title: str, color_seq=None) -> go.Figure:
    if not data:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False, font_size=14)
        fig.update_layout(
            title=title, height=320,
            margin=dict(l=10, r=10, t=40, b=10),
            xaxis=dict(visible=False), yaxis=dict(visible=False),
        )
        return fig
    _df = pd.DataFrame(data)
    fig = px.pie(
        _df, values="amount", names="category", hole=0.4,
        color_discrete_sequence=color_seq, title=title,
    )
    fig.update_traces(
        textposition="inside", textinfo="percent+label",
        hovertemplate=f"<b>%{{label}}</b><br>{default_ccy} %{{value:,.2f}}<br>%{{percent}}<extra></extra>",
    )
    fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=40, b=40),
        hoverlabel=dict(bgcolor="white", bordercolor="gray", font_size=13),
        showlegend=False,
    )
    return fig


row1_col1, row1_col2 = st.columns(2)
with row1_col1:
    st.plotly_chart(
        _make_donut(expense_data, "Expenses by Category", px.colors.qualitative.Set2),
        use_container_width=True,
    )
with row1_col2:
    st.plotly_chart(
        _make_donut(income_data, "Income by Category", px.colors.qualitative.Pastel),
        use_container_width=True,
    )

row2_col1, row2_col2 = st.columns(2)

with row2_col1:
    if not period_df.empty:
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(x=period_df["period"], y=period_df["income"],
                                 name="Income",   marker_color="#2ca02c"))
        fig_bar.add_trace(go.Bar(x=period_df["period"], y=period_df["expense"],
                                 name="Expenses", marker_color="#d62728"))
        fig_bar.update_layout(
            title="Income vs Expenses by Month", barmode="group", height=340,
            margin=dict(l=0, r=0, t=40, b=0), yaxis_title=default_ccy,
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
            x=period_df["period"], y=period_df["cumulative_net"],
            mode="lines+markers", fill="tozeroy",
            fillcolor="rgba(31,119,180,0.15)",
            line=dict(color="#1f77b4", width=2),
        ))
        fig_net.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
        fig_net.update_layout(
            title="Cumulative Net Cash Flow", height=340,
            margin=dict(l=0, r=0, t=40, b=0), yaxis_title=default_ccy,
            xaxis=dict(type="category"), showlegend=False,
        )
        st.plotly_chart(fig_net, use_container_width=True)
    else:
        st.info("No transactions in selected period.")
