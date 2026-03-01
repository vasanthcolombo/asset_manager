"""Money Manager — Transactions page: filterable transaction detail table."""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from models.mm_account import get_account_groups, get_accounts
from models.mm_settings import get_mm_setting
from models.mm_transaction import get_mm_transactions
from services.mm_service import amount_in_default
from services.cache import get_cached_running_balances
from utils.mm_ui import account_filter_widget

st.header("Transactions")

conn        = st.session_state.conn
default_ccy = get_mm_setting(conn, "default_currency", "SGD")

# ── Handle navigation from Accounts page (📊 button) ──────────────────────────
_prefilter_id = st.session_state.pop("mm_stats_prefilter_account_id", None)
if _prefilter_id is not None:
    _all_accs_tmp = get_accounts(conn, active_only=False)
    _acc_name = next((a["name"] for a in _all_accs_tmp if a["id"] == _prefilter_id), "")
    # Pre-check only this account in the filter widget
    for _a in _all_accs_tmp:
        st.session_state[f"txn_tbl_accs_{_a['id']}"] = (_a["id"] == _prefilter_id)
    if _acc_name:
        st.info(f"Showing transactions for **{_acc_name}**")

# ── Period Selector ───────────────────────────────────────────────────────────
today = date.today()

period_mode = st.radio(
    "Period",
    ["This Week", "This Month", "This Year", "All Time", "Custom"],
    horizontal=True,
    index=2,
    key="mm_txn_period",
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
elif period_mode == "All Time":
    start = date(2000, 1, 1)
    end   = today
else:
    custom_range = st.date_input(
        "Select date range",
        value=[today.replace(month=1, day=1), today],
        key="mm_txn_custom_range",
    )
    start, end = (custom_range if len(custom_range) == 2 else (today, today))

date_from = start.strftime("%Y-%m-%d")
date_to   = end.strftime("%Y-%m-%d")

# ── Account Filter ────────────────────────────────────────────────────────────
all_groups   = get_account_groups(conn)
all_accounts = get_accounts(conn, active_only=False)

# Derive from the Filters-expander widget state (rendered below)
sel_acc_ids = {
    a["id"] for a in all_accounts
    if st.session_state.get(f"txn_tbl_accs_{a['id']}", False)
}

# ── Fetch & filter transactions ───────────────────────────────────────────────
all_txns = get_mm_transactions(conn, date_from=date_from, date_to=date_to)
txns = [
    t for t in all_txns
    if not sel_acc_ids
    or t["account_id"] in sel_acc_ids
    or t.get("to_account_id") in sel_acc_ids
]

if not txns:
    st.info("No transactions in the selected period/filter.")
    st.stop()

# ── Build DataFrame ───────────────────────────────────────────────────────────
running_bals = get_cached_running_balances(conn)
_acc_map     = {a["id"]: a for a in all_accounts}

rows = []
for t in txns:
    amt_default = amount_in_default(
        t["amount"], t["currency"], t.get("fx_rate_to_default"), default_ccy
    )

    if t["type"] == "TRANSFER":
        is_out = not sel_acc_ids or t["account_id"] in sel_acc_ids
        if is_out:
            rb          = running_bals.get((t["id"], "from"), {})
            cat_display = f"→ {t.get('to_account_name') or 'External'}"
            acc_group   = t.get("account_group_name") or ""
            acc_name    = t.get("account_name") or ""
        else:
            rb          = running_bals.get((t["id"], "to"), {})
            cat_display = f"← {t.get('account_name') or 'External'}"
            to_acc      = _acc_map.get(t.get("to_account_id"))
            acc_group   = to_acc["group_name"] if to_acc else ""
            acc_name    = t.get("to_account_name") or ""
    else:
        rb          = running_bals.get(t["id"], {})
        cat_display = t.get("category_name") or ""
        acc_group   = t.get("account_group_name") or ""
        acc_name    = t.get("account_name") or ""

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
        "_amount_num":     float(t["amount"]),
        "_date":           pd.to_datetime(t["date"]),
    })

df = pd.DataFrame(rows)

# ── Filters ───────────────────────────────────────────────────────────────────
with st.expander("🔍 Filters", expanded=True):
    f1 = st.columns([2.5, 3])
    with f1[0]:
        amt_lo   = float(df["_amount_num"].min())
        amt_hi   = float(df["_amount_num"].max())
        tbl_amt  = st.slider(
            "Amount range",
            min_value=amt_lo,
            max_value=max(amt_hi, amt_lo + 0.01),
            value=(amt_lo, amt_hi),
            key="txn_tbl_amt",
        )
    with f1[1]:
        _all_notes    = sorted(n for n in df["Notes"].unique() if n)
        tbl_notes_sel = st.multiselect(
            "Notes contains",
            _all_notes,
            key="txn_tbl_notes",
            placeholder="Type to search notes…",
        )

    f2 = st.columns(3)
    with f2[0]:
        tbl_type = st.multiselect(
            "Type",
            sorted(df["Type"].unique().tolist()),
            key="txn_tbl_type",
            placeholder="All",
        )
    with f2[1]:
        st.caption("Account")
        tbl_sel_ids = account_filter_widget("txn_tbl_accs", all_groups, all_accounts)
    with f2[2]:
        tbl_cat = st.multiselect(
            "Category",
            sorted(df["Category"].unique().tolist()),
            key="txn_tbl_cat",
            placeholder="All",
        )

# ── Apply filters ─────────────────────────────────────────────────────────────
fdf = df.copy()

fdf = fdf[(fdf["_amount_num"] >= tbl_amt[0]) & (fdf["_amount_num"] <= tbl_amt[1])]
if tbl_type:
    fdf = fdf[fdf["Type"].isin(tbl_type)]
if tbl_sel_ids:
    _names = {a["name"] for a in all_accounts if a["id"] in tbl_sel_ids}
    fdf = fdf[fdf["Account"].isin(_names)]
if tbl_cat:
    fdf = fdf[fdf["Category"].isin(tbl_cat)]
if tbl_notes_sel:
    fdf = fdf[fdf["Notes"].isin(tbl_notes_sel)]

st.caption(f"Showing **{len(fdf):,}** of {len(df):,} transactions")

# Hide Account Balance when multiple accounts are mixed (balances are independent)
_drop = ["_amount_num", "_date"]
if fdf["Account"].nunique() != 1:
    _drop.append("Account Balance")

st.dataframe(fdf.drop(columns=_drop), use_container_width=True, hide_index=True)
