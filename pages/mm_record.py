"""Money Manager — Record Transaction page."""

import streamlit as st
import pandas as pd
from datetime import date

from models.mm_account import get_accounts, get_account_groups
from models.mm_category import get_categories
from models.mm_settings import get_mm_setting
from models.mm_transaction import insert_mm_transaction, get_mm_transactions
from services.fx_service import get_live_fx_rate
from services.mm_service import amount_in_default
from services.cache import invalidate_mm_accounts_cache
from utils.mm_ui import account_single_select_widget

st.header("Record Transaction")

conn = st.session_state.conn
default_ccy = get_mm_setting(conn, "default_currency", "SGD")

# ── Transaction Type ──────────────────────────────────────────────────────────
txn_type = st.radio(
    "Type",
    ["EXPENSE", "INCOME", "TRANSFER", "MODIFIED_BALANCE"],
    horizontal=True,
    key="mm_txn_type",
)

# ── Account data ──────────────────────────────────────────────────────────────
accounts   = get_accounts(conn, active_only=True)
all_groups = get_account_groups(conn)

if not accounts:
    st.warning("No accounts found. Create one in the **Accounts** page first.")
    st.stop()

# ── Version counter — incrementing resets all keyed inputs ───────────────────
if "mm_rec_v" not in st.session_state:
    st.session_state.mm_rec_v = 0
v = st.session_state.mm_rec_v

# ── Categories ────────────────────────────────────────────────────────────────
categories  = get_categories(conn, type_=txn_type if txn_type in ("INCOME", "EXPENSE") else None)

def _cat_label(c: dict) -> str:
    if c["parent_id"]:
        parent = next((p["name"] for p in categories if p["id"] == c["parent_id"]), "")
        return f"{parent} › {c['name']}"
    return c["name"]

cat_options = {_cat_label(c): c["id"] for c in categories if txn_type in ("INCOME", "EXPENSE")}

# ── Input row ─────────────────────────────────────────────────────────────────
sel_cat_label = None
to_acc_id     = None

if txn_type == "TRANSFER":
    cols = st.columns([1.8, 1.8, 1.2, 1.3, 0.9])
    with cols[0]:
        st.caption("From Account")
        from_acc_id = account_single_select_widget("mm_rec_from", all_groups, accounts)
    with cols[1]:
        st.caption("To Account")
        to_acc_id = account_single_select_widget("mm_rec_to", all_groups, accounts)
    with cols[2]:
        txn_date = st.date_input("Date", value=date.today(), key=f"mm_date_{v}")
    with cols[3]:
        amount = st.number_input("Amount", value=0.0, step=10.0, format="%.2f",
                                 key=f"mm_amt_{v}")
    with cols[4]:
        currency = (st.text_input("Currency", value=default_ccy, key=f"mm_ccy_{v}")
                    .strip().upper() or default_ccy)

elif txn_type == "MODIFIED_BALANCE":
    cols = st.columns([2, 1.2, 1.5, 1.0])
    with cols[0]:
        st.caption("Account")
        from_acc_id = account_single_select_widget("mm_rec_from", all_groups, accounts)
    with cols[1]:
        txn_date = st.date_input("Date", value=date.today(), key=f"mm_date_{v}")
    with cols[2]:
        amount = st.number_input(
            "Delta Amount", step=10.0, format="%.2f", key=f"mm_amt_{v}",
            help="Positive = increase balance, Negative = decrease balance",
        )
    with cols[3]:
        sel_acc = next((a for a in accounts if a["id"] == st.session_state.get("mm_rec_from_sel")), None)
        currency = (st.text_input("Currency", value=sel_acc["currency"] if sel_acc else default_ccy,
                                  key=f"mm_ccy_{v}").strip().upper() or default_ccy)

else:  # EXPENSE / INCOME
    cols = st.columns([2, 1.2, 2, 1.3, 0.9])
    with cols[0]:
        st.caption("Account")
        from_acc_id = account_single_select_widget("mm_rec_from", all_groups, accounts)
    with cols[1]:
        txn_date = st.date_input("Date", value=date.today(), key=f"mm_date_{v}")
    with cols[2]:
        if cat_options:
            sel_cat_label = st.selectbox(
                "Category", list(cat_options.keys()),
                index=None, placeholder="Select category…",
                key=f"mm_cat_{v}",
            )
        else:
            st.warning("No categories found.")
    with cols[3]:
        amount = st.number_input("Amount", value=0.0, step=10.0, format="%.2f",
                                 key=f"mm_amt_{v}")
    with cols[4]:
        currency = (st.text_input("Currency", value=default_ccy, key=f"mm_ccy_{v}")
                    .strip().upper() or default_ccy)

# Transfer any pending suggestion into the widget key BEFORE the widget renders.
# (Streamlit forbids writing to a widget's session-state key after it is instantiated.)
_notes_key = f"mm_notes_{v}"
_notes_pending_key = f"mm_notes_pending_{v}"
if _notes_pending_key in st.session_state:
    st.session_state[_notes_key] = st.session_state.pop(_notes_pending_key)

notes = st.text_input("Notes (optional)", key=_notes_key)

# ── Note suggestions ──────────────────────────────────────────────────────────
# Streamlit text_input only reruns on Enter/blur, not on each keystroke.
# Strategy: show recent notes for the account always; narrow them when text is typed.
_typed             = notes.strip()
_acc_id_for_notes  = st.session_state.get("mm_rec_from_sel")

if _typed:
    # Filter by what was typed (updates on Enter / focus-loss)
    if _acc_id_for_notes:
        _sug_rows = conn.execute(
            "SELECT DISTINCT notes FROM mm_transactions "
            "WHERE notes IS NOT NULL AND notes != '' AND account_id = ? "
            "AND LOWER(notes) LIKE ? ORDER BY notes LIMIT 8",
            (_acc_id_for_notes, f"%{_typed.lower()}%"),
        ).fetchall()
    else:
        _sug_rows = conn.execute(
            "SELECT DISTINCT notes FROM mm_transactions "
            "WHERE notes IS NOT NULL AND notes != '' "
            "AND LOWER(notes) LIKE ? ORDER BY notes LIMIT 8",
            (f"%{_typed.lower()}%",),
        ).fetchall()
    _suggestions = [r[0] for r in _sug_rows if r[0] != _typed]
elif _acc_id_for_notes:
    # Nothing typed yet — show 8 most-recently-used notes for this account
    _sug_rows = conn.execute(
        "SELECT notes FROM mm_transactions "
        "WHERE notes IS NOT NULL AND notes != '' AND account_id = ? "
        "GROUP BY notes ORDER BY MAX(id) DESC LIMIT 8",
        (_acc_id_for_notes,),
    ).fetchall()
    _suggestions = [r[0] for r in _sug_rows]
else:
    _suggestions = []

if _suggestions:
    _ncols = min(len(_suggestions), 4)
    sug_cols = st.columns(_ncols)
    for i, sug in enumerate(_suggestions):
        label = sug[:40] + ("…" if len(sug) > 40 else "")
        with sug_cols[i % _ncols]:
            if st.button(label, key=f"mm_note_sug_{v}_{i}", use_container_width=True):
                st.session_state[_notes_pending_key] = sug
                st.rerun()

# ── Submit ────────────────────────────────────────────────────────────────────
btn_labels = {
    "EXPENSE":          "Add Expense",
    "INCOME":           "Add Income",
    "TRANSFER":         "Record Transfer",
    "MODIFIED_BALANCE": "Adjust Balance",
}
if st.button(btn_labels.get(txn_type, "Submit"), type="primary", use_container_width=True):
    if from_acc_id is None:
        st.error("Please select an account.")
    elif txn_type == "TRANSFER" and to_acc_id is None:
        st.error("Please select a To Account.")
    elif txn_type == "TRANSFER" and from_acc_id == to_acc_id:
        st.error("From and To accounts must be different.")
    elif txn_type in ("EXPENSE", "INCOME") and sel_cat_label is None:
        st.error("Please select a category.")
    elif txn_type in ("EXPENSE", "INCOME", "TRANSFER") and amount == 0:
        st.error("Amount cannot be zero.")
    elif txn_type == "MODIFIED_BALANCE" and amount == 0:
        st.error("Delta amount cannot be zero.")
    else:
        category_id = cat_options.get(sel_cat_label) if sel_cat_label else None
        fx  = 1.0 if currency == default_ccy else get_live_fx_rate(currency, default_ccy)
        txn = {
            "date":               txn_date.strftime("%Y-%m-%d"),
            "type":               txn_type,
            "account_id":         from_acc_id,
            "to_account_id":      to_acc_id,
            "category_id":        category_id,
            "amount":             amount,
            "currency":           currency,
            "fx_rate_to_default": fx,
            "notes":              notes or None,
        }
        try:
            insert_mm_transaction(conn, txn)
            invalidate_mm_accounts_cache()
            if txn_type == "MODIFIED_BALANCE":
                direction = "increased" if amount > 0 else "decreased"
                st.success(f"Balance {direction} by {currency} {abs(amount):,.2f}.")
            else:
                default_eq = abs(amount) * fx
                st.success(
                    f"{txn_type.title()} of {currency} {abs(amount):,.2f}"
                    + (f" ({default_ccy} {default_eq:,.2f})" if currency != default_ccy else "")
                    + " recorded."
                )
            st.session_state.mm_rec_v += 1  # resets date/category/amount/currency/notes
            st.rerun()
        except Exception as e:
            st.error(f"Could not save transaction: {e}")

# ── Recent Transactions ───────────────────────────────────────────────────────
st.divider()
_rec_acc_id = st.session_state.get("mm_rec_from_sel")
_rec_acc    = next((a for a in accounts if a["id"] == _rec_acc_id), None)
if _rec_acc:
    st.subheader(f"Recent Transactions — {_rec_acc['name']}")
else:
    st.subheader("Recent Transactions")

recent = get_mm_transactions(conn, account_id=_rec_acc_id if _rec_acc else None, limit=50)
if recent:
    rows = []
    for t in recent:
        native_str  = f"{t['currency']} {t['amount']:,.2f}"
        default_val = amount_in_default(
            t["amount"], t["currency"], t.get("fx_rate_to_default"), default_ccy
        )
        default_str = f"{default_ccy} {default_val:,.2f}" if t["currency"] != default_ccy else "—"
        rows.append({
            "Date":       t["date"],
            "Type":       t["type"],
            "Account":    t["account_name"],
            "To Account": t.get("to_account_name") or "",
            "Category":   t.get("category_name") or "",
            "Amount":     native_str,
            default_ccy:  default_str,
            "Notes":      t.get("notes") or "",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("No transactions yet. Add one above.")

