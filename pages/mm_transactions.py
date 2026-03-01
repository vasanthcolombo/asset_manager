"""Money Manager — Transactions page: filterable transaction detail table."""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from models.mm_account import get_account_groups, get_accounts
from models.mm_category import get_categories
from models.mm_settings import get_mm_setting
from models.mm_transaction import get_mm_transactions, update_mm_transaction, delete_mm_transaction
from services.mm_service import amount_in_default
from services.fx_service import get_live_fx_rate
from services.cache import get_cached_running_balances, invalidate_mm_accounts_cache
from utils.mm_ui import account_filter_widget

_PAGE_SIZE = 50


@st.dialog("Edit Transaction")
def _edit_dialog():
    conn    = st.session_state.conn
    txn_id  = st.session_state.get("_edit_txn_id")
    default_ccy = get_mm_setting(conn, "default_currency", "SGD")

    row = conn.execute("SELECT * FROM mm_transactions WHERE id = ?", (txn_id,)).fetchone()
    if not row:
        st.error("Transaction not found.")
        return
    txn = dict(row)

    all_accounts = get_accounts(conn, active_only=False)
    acc_labels   = {f"{a['name']} ({a['group_name']})": a["id"] for a in all_accounts}
    acc_ids      = list(acc_labels.values())

    e_date = st.date_input("Date", value=pd.to_datetime(txn["date"]).date())
    e_type = st.selectbox(
        "Type",
        ["EXPENSE", "INCOME", "TRANSFER", "MODIFIED_BALANCE"],
        index=["EXPENSE", "INCOME", "TRANSFER", "MODIFIED_BALANCE"].index(txn["type"])
        if txn["type"] in ["EXPENSE", "INCOME", "TRANSFER", "MODIFIED_BALANCE"] else 0,
    )

    acc_default = acc_ids.index(txn["account_id"]) if txn["account_id"] in acc_ids else 0
    e_acc = st.selectbox("Account", list(acc_labels.keys()), index=acc_default)

    e_to_acc = None
    e_cat_id = None
    if e_type == "TRANSFER":
        to_default = acc_ids.index(txn["to_account_id"]) if txn.get("to_account_id") in acc_ids else 0
        e_to_acc = st.selectbox("To Account", list(acc_labels.keys()), index=to_default)
    elif e_type in ("INCOME", "EXPENSE"):
        cats     = get_categories(conn, type_=e_type)
        cat_opts = {c["name"]: c["id"] for c in cats}
        cat_ids  = list(cat_opts.values())
        cat_default = cat_ids.index(txn["category_id"]) if txn.get("category_id") in cat_ids else 0
        e_cat_name = st.selectbox("Category", list(cat_opts.keys()), index=cat_default)
        e_cat_id   = cat_opts.get(e_cat_name)
    elif e_type == "MODIFIED_BALANCE":
        st.caption("Delta amount: positive to increase balance, negative to decrease.")

    col_amt, col_ccy = st.columns(2)
    with col_amt:
        if e_type == "MODIFIED_BALANCE":
            e_amount = st.number_input("Delta Amount", value=float(txn["amount"]), format="%.2f", step=10.0)
        else:
            e_amount = st.number_input("Amount", min_value=0.01, value=abs(float(txn["amount"])),
                                       format="%.2f", step=10.0)
    with col_ccy:
        e_currency = st.text_input("Currency", value=txn["currency"]).strip().upper()

    e_notes = st.text_input("Notes", value=txn.get("notes") or "")

    if st.button("Save Changes", type="primary", use_container_width=True):
        fx = 1.0 if e_currency == default_ccy else get_live_fx_rate(e_currency, default_ccy)
        update_mm_transaction(conn, txn_id, {
            "date":               e_date.strftime("%Y-%m-%d"),
            "type":               e_type,
            "account_id":         acc_labels[e_acc],
            "to_account_id":      acc_labels.get(e_to_acc) if e_to_acc else None,
            "category_id":        e_cat_id,
            "amount":             e_amount,
            "currency":           e_currency,
            "fx_rate_to_default": fx,
            "notes":              e_notes or None,
        })
        invalidate_mm_accounts_cache()
        st.rerun()


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
    elif t["type"] == "MODIFIED_BALANCE":
        rb          = running_bals.get(t["id"], {})
        cat_display = "Balance Adjustment"
        acc_group   = t.get("account_group_name") or ""
        acc_name    = t.get("account_name") or ""
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
        "_id":             t["id"],
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

total_rows = len(fdf)
st.caption(f"Showing **{total_rows:,}** of {len(df):,} transactions")

if total_rows == 0:
    st.info("No transactions match the current filters.")
    st.stop()

# ── Pagination ────────────────────────────────────────────────────────────────
total_pages = max(1, (total_rows + _PAGE_SIZE - 1) // _PAGE_SIZE)
if "txn_page" not in st.session_state:
    st.session_state.txn_page = 0
st.session_state.txn_page = min(st.session_state.txn_page, total_pages - 1)

page_start = st.session_state.txn_page * _PAGE_SIZE
page_end   = min(page_start + _PAGE_SIZE, total_rows)
page_fdf   = fdf.iloc[page_start:page_end].reset_index(drop=True)

# ── Dataframe ────────────────────────────────────────────────────────────────
_DISPLAY_COLS = ["Date", "Type", "Account Group", "Account", "Category",
                 "Amount", default_ccy, "Account Balance", "Notes"]

selection = st.dataframe(
    page_fdf[_DISPLAY_COLS],
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key=f"txn_df_{st.session_state.txn_page}",
)

# ── Edit / Delete for selected row ───────────────────────────────────────────
selected_rows = selection.selection.rows
if selected_rows:
    sel_row  = page_fdf.iloc[selected_rows[0]]
    txn_id   = int(sel_row["_id"])
    txn_type = sel_row["Type"]

    act_cols = st.columns([1, 1, 8])
    with act_cols[0]:
        if st.button("✏️ Edit", key="txn_edit_btn", use_container_width=True):
            st.session_state["_edit_txn_id"] = txn_id
            _edit_dialog()
    with act_cols[1]:
        with st.popover("🗑️ Delete", use_container_width=True):
            st.caption(f"Delete this {txn_type} transaction?")
            if st.button("Confirm delete", key="txn_del_btn", type="primary",
                         use_container_width=True):
                delete_mm_transaction(conn, txn_id)
                invalidate_mm_accounts_cache()
                st.rerun()

# ── Pagination controls ───────────────────────────────────────────────────────
if total_pages > 1:
    st.divider()
    pg_cols = st.columns([1, 2, 1])
    with pg_cols[0]:
        if st.button("◀ Prev", disabled=(st.session_state.txn_page == 0),
                     use_container_width=True):
            st.session_state.txn_page -= 1
            st.rerun()
    with pg_cols[1]:
        st.caption(
            f"Page {st.session_state.txn_page + 1} of {total_pages}  "
            f"(rows {page_start + 1}–{page_end} of {total_rows})"
        )
    with pg_cols[2]:
        if st.button("Next ▶", disabled=(st.session_state.txn_page >= total_pages - 1),
                     use_container_width=True):
            st.session_state.txn_page += 1
            st.rerun()
