"""Money Manager — Stats page: income/expense charts by period."""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta

from models.mm_account import get_account_groups, get_accounts
from models.mm_settings import get_mm_setting
from models.mm_transaction import get_mm_transactions
from services.mm_service import amount_in_default
from services.cache import get_cached_running_balances


# ── Two-level account picker (popover → expanders → checkboxes) ───────────────

def _account_filter_widget(key_prefix: str, all_groups: list, all_accounts: list) -> set[int]:
    """
    Render a two-level account selector:
      Level 1 — Account Groups (collapsible expanders inside a popover)
      Level 2 — Individual accounts (checkboxes inside each group expander)

    Returns the set of selected account IDs (empty set = all accounts).
    """
    # Build group → sorted-accounts map (skip empty groups)
    grp_map: dict[str, list] = {}
    for g in all_groups:
        accs = sorted(
            [a for a in all_accounts if a["group_name"] == g["name"]],
            key=lambda x: x["name"],
        )
        if accs:
            grp_map[g["name"]] = accs

    # Derive current selection from checkbox session-state keys
    sel_ids: set[int] = {
        a["id"]
        for accs in grp_map.values()
        for a in accs
        if st.session_state.get(f"{key_prefix}_{a['id']}", False)
    }

    # Compose the popover button label
    if sel_ids:
        names = [a["name"] for a in all_accounts if a["id"] in sel_ids]
        btn_label = ", ".join(names[:2]) + (f"  +{len(names) - 2} more" if len(names) > 2 else "")
    else:
        btn_label = "All accounts  ▾"

    with st.popover(btn_label, use_container_width=True):
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Clear all", key=f"{key_prefix}_clear", use_container_width=True):
                for accs in grp_map.values():
                    for a in accs:
                        st.session_state[f"{key_prefix}_{a['id']}"] = False
                st.rerun()
        with c2:
            if st.button("Select all", key=f"{key_prefix}_selall", use_container_width=True):
                for accs in grp_map.values():
                    for a in accs:
                        st.session_state[f"{key_prefix}_{a['id']}"] = True
                st.rerun()

        for g_name, accs in grp_map.items():
            n_sel = sum(1 for a in accs if st.session_state.get(f"{key_prefix}_{a['id']}", False))
            exp_label = f"{g_name}  ({n_sel}/{len(accs)} selected)" if n_sel else g_name
            with st.expander(exp_label, expanded=(n_sel > 0)):
                for a in accs:
                    st.checkbox(a["name"], key=f"{key_prefix}_{a['id']}")

    return sel_ids


st.header("Stats")

conn = st.session_state.conn
default_ccy = get_mm_setting(conn, "default_currency", "SGD")

# ── Handle navigation from Accounts page ──────────────────────────────────────
_prefilter_acc_id = st.session_state.pop("mm_stats_prefilter_account_id", None)
if _prefilter_acc_id is not None:
    # Resolve account name for the banner
    _all_accs_tmp = get_accounts(conn, active_only=False)
    _acc_name = next((a["name"] for a in _all_accs_tmp if a["id"] == _prefilter_acc_id), "Account")
    st.session_state["mm_stats_filtered_acc_name"] = _acc_name
    # Pre-set ONLY this account in the table filter (clear all others).
    # Session state is read before widgets render, so no rerun needed.
    for _a in _all_accs_tmp:
        st.session_state[f"tbl_accs_{_a['id']}"] = (_a["id"] == _prefilter_acc_id)
    # Signal scroll-to-transactions on this render
    st.session_state["mm_stats_scroll_to_txns"] = True

# ── Account filter banner (set when navigating from Accounts page) ────────────
_filtered_acc_name = st.session_state.pop("mm_stats_filtered_acc_name", None)
if _filtered_acc_name:
    st.info(f"Filtered to account: **{_filtered_acc_name}**  —  use the Account filter below to change.")

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

# ── Two-level Account Filter ──────────────────────────────────────────────────
all_groups   = get_account_groups(conn)
all_accounts = get_accounts(conn, active_only=False)

st.caption("Account")
sel_acc_ids = _account_filter_widget("top_accs", all_groups, all_accounts)

# ── Fetch & filter transactions ───────────────────────────────────────────────
all_txns = get_mm_transactions(conn, date_from=date_from, date_to=date_to)
txns = [
    t for t in all_txns
    if not sel_acc_ids
    or t["account_id"] in sel_acc_ids
    or t.get("to_account_id") in sel_acc_ids
]

# ── Aggregate for charts ──────────────────────────────────────────────────────
income_cat: dict[str, float] = {}
expense_cat: dict[str, float] = {}
period_rows: dict[str, dict] = {}

for t in txns:
    if t["type"] == "TRANSFER":
        continue
    amt = amount_in_default(
        t["amount"], t["currency"], t.get("fx_rate_to_default"), default_ccy
    )
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
    period_df["net"] = period_df["income"] - period_df["expense"]
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
            title=title,
            height=320,
            margin=dict(l=10, r=10, t=40, b=10),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig
    df = pd.DataFrame(data)
    fig = px.pie(
        df, values="amount", names="category", hole=0.4,
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
                                  name="Income", marker_color="#2ca02c"))
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

# ── Transaction Detail Table ──────────────────────────────────────────────────
st.divider()
st.markdown('<a name="txn-detail"></a>', unsafe_allow_html=True)
st.subheader("Transaction Detail")

# Auto-scroll here when navigating from Accounts page
if st.session_state.pop("mm_stats_scroll_to_txns", False):
    components.html(
        """<script>
        setTimeout(function() {
            var el = window.parent.document.querySelector('a[name="txn-detail"]');
            if (el) { el.scrollIntoView({behavior: 'smooth', block: 'start'}); }
        }, 300);
        </script>""",
        height=0,
    )

detail_txns = txns  # include TRANSFER rows so balance changes are visible

if not detail_txns:
    st.info("No transactions in the selected period/filter.")
    st.stop()

# Build DataFrame with both display and numeric columns
running_bals = get_cached_running_balances(conn)
_acc_map = {a["id"]: a for a in all_accounts}  # for to-account group lookup

rows = []
for t in detail_txns:
    amt_default = amount_in_default(
        t["amount"], t["currency"], t.get("fx_rate_to_default"), default_ccy
    )

    if t["type"] == "TRANSFER":
        # Determine direction relative to the account filter
        is_out = not sel_acc_ids or t["account_id"] in sel_acc_ids
        if is_out:
            rb = running_bals.get((t["id"], "from"), {})
            cat_display  = f"→ {t.get('to_account_name') or 'External'}"
            acc_group    = t.get("account_group_name") or ""
            acc_name     = t.get("account_name") or ""
        else:
            rb = running_bals.get((t["id"], "to"), {})
            cat_display  = f"← {t.get('account_name') or 'External'}"
            to_acc = _acc_map.get(t.get("to_account_id"))
            acc_group    = to_acc["group_name"] if to_acc else ""
            acc_name     = t.get("to_account_name") or ""
    else:
        rb           = running_bals.get(t["id"], {})
        cat_display  = t.get("category_name") or ""
        acc_group    = t.get("account_group_name") or ""
        acc_name     = t.get("account_name") or ""

    balance_str = f"{rb['currency']} {rb['balance']:,.2f}" if rb else "—"
    rows.append({
        "Date":            t["date"],
        "Type":            t["type"],
        "Account Group":   acc_group,
        "Account":         acc_name,
        "Category":        cat_display,
        "Amount":          f"{t['currency']} {t['amount']:,.2f}",
        default_ccy:       round(amt_default, 2),
        "Account Balance": balance_str,
        "Notes":           t.get("notes") or "",
        # hidden helper columns for filtering
        "_amount_num":     float(t["amount"]),
        "_date":           pd.to_datetime(t["date"]),
    })
df = pd.DataFrame(rows)

# ── Column Filters (inline, no dropdowns above table) ────────────────────────
with st.expander("🔍 Filters", expanded=True):
    # Row 1: Date range | Amount range | Notes search
    f1 = st.columns([2.5, 2.5, 3])
    with f1[0]:
        min_d = df["_date"].min().date()
        max_d = df["_date"].max().date()
        tbl_date = st.date_input(
            "Date range",
            value=[min_d, max_d],
            key="tbl_date",
        )
    with f1[1]:
        amt_lo = float(df["_amount_num"].min())
        amt_hi = float(df["_amount_num"].max())
        tbl_amt = st.slider(
            "Amount range",
            min_value=amt_lo,
            max_value=max(amt_hi, amt_lo + 0.01),
            value=(amt_lo, amt_hi),
            key="tbl_amt",
        )
    with f1[2]:
        _all_notes = sorted(n for n in df["Notes"].unique() if n)
        tbl_notes_sel = st.multiselect(
            "Notes contains",
            _all_notes,
            key="tbl_notes_sel",
            placeholder="Type to search notes…",
        )

    # Row 2: Type | Account | Category
    f2 = st.columns(3)
    with f2[0]:
        tbl_type = st.multiselect(
            "Type",
            sorted(df["Type"].unique().tolist()),
            key="tbl_type",
            placeholder="All",
        )
    with f2[1]:
        st.caption("Account")
        tbl_sel_ids = _account_filter_widget("tbl_accs", all_groups, all_accounts)
    with f2[2]:
        tbl_cat = st.multiselect(
            "Category",
            sorted(df["Category"].unique().tolist()),
            key="tbl_cat",
            placeholder="All",
        )

# ── Apply filters ─────────────────────────────────────────────────────────────
fdf = df.copy()

if len(tbl_date) == 2:
    fdf = fdf[(fdf["_date"].dt.date >= tbl_date[0]) & (fdf["_date"].dt.date <= tbl_date[1])]
fdf = fdf[(fdf["_amount_num"] >= tbl_amt[0]) & (fdf["_amount_num"] <= tbl_amt[1])]
if tbl_type:
    fdf = fdf[fdf["Type"].isin(tbl_type)]
if tbl_sel_ids:
    _tbl_acc_names = {a["name"] for a in all_accounts if a["id"] in tbl_sel_ids}
    fdf = fdf[fdf["Account"].isin(_tbl_acc_names)]
if tbl_cat:
    fdf = fdf[fdf["Category"].isin(tbl_cat)]
if tbl_notes_sel:
    fdf = fdf[fdf["Notes"].isin(tbl_notes_sel)]

st.caption(f"Showing **{len(fdf):,}** of {len(df):,} transactions")

# "Account Balance" is only meaningful for a single-account view.
# When multiple accounts are visible their running balances are independent
# and mixing them in one column is misleading — hide it.
_drop_cols = ["_amount_num", "_date"]
if fdf["Account"].nunique() != 1:
    _drop_cols.append("Account Balance")

st.dataframe(
    fdf.drop(columns=_drop_cols),
    use_container_width=True,
    hide_index=True,
)
