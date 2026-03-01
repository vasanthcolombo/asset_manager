"""Money Manager — Record Transaction page."""

import streamlit as st
import pandas as pd
from datetime import date

from models.mm_account import get_accounts, get_account_groups, create_account, create_account_group
from models.mm_category import get_categories, create_category, delete_category
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
        amount = st.number_input("Amount", min_value=0.01, step=10.0, format="%.2f",
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
            sel_cat_label = st.selectbox("Category", list(cat_options.keys()), key=f"mm_cat_{v}")
        else:
            st.warning("No categories found.")
    with cols[3]:
        amount = st.number_input("Amount", min_value=0.01, step=10.0, format="%.2f",
                                 key=f"mm_amt_{v}")
    with cols[4]:
        currency = (st.text_input("Currency", value=default_ccy, key=f"mm_ccy_{v}")
                    .strip().upper() or default_ccy)

notes = st.text_input("Notes (optional)", key=f"mm_notes_{v}")

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
            st.error(f"Error: {e}")

# ── Recent Transactions ───────────────────────────────────────────────────────
st.divider()
st.subheader("Recent Transactions")

recent = get_mm_transactions(conn, limit=20)
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

# ── Management Expanders ──────────────────────────────────────────────────────
st.divider()

with st.expander("Manage Categories"):
    st.markdown("**Add a new category**")
    with st.form("add_category"):
        c_cols = st.columns([2, 1, 2])
        with c_cols[0]:
            new_cat_name = st.text_input("Category Name")
        with c_cols[1]:
            new_cat_type = st.selectbox("Type", ["EXPENSE", "INCOME"])
        with c_cols[2]:
            parent_cats = [c for c in get_categories(conn, type_=new_cat_type) if c["parent_id"] is None]
            parent_opts = {"— None (top-level) —": None} | {c["name"]: c["id"] for c in parent_cats}
            sel_parent = st.selectbox("Parent Category (optional)", list(parent_opts.keys()))
        if st.form_submit_button("Add Category"):
            if new_cat_name.strip():
                try:
                    create_category(conn, new_cat_name.strip(), new_cat_type, parent_opts[sel_parent])
                    st.success(f"Added category: {new_cat_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Category name is required.")

    st.markdown("**Remove a user-defined category**")
    user_cats = [c for c in get_categories(conn) if not c["is_predefined"]]
    if user_cats:
        del_opts = {f"{c['type']} — {_cat_label(c)}": c["id"] for c in user_cats}
        sel_del = st.selectbox("Select category to remove", list(del_opts.keys()), key="del_cat_sel")
        if st.button("Remove Category", type="secondary"):
            delete_category(conn, del_opts[sel_del])
            st.success("Removed.")
            st.rerun()
    else:
        st.caption("No user-defined categories to remove.")

with st.expander("Manage Accounts"):
    st.markdown("Create a new account:")
    with st.form("mm_add_account_quick"):
        grps     = get_account_groups(conn)
        grp_opts = {g["name"]: g["id"] for g in grps}
        qa_cols  = st.columns([2, 2, 1, 1])
        with qa_cols[0]:
            qa_name = st.text_input("Account Name", key="qa_name")
        with qa_cols[1]:
            qa_group = st.selectbox("Group", list(grp_opts.keys()), key="qa_group")
        with qa_cols[2]:
            qa_currency = st.text_input("Currency", value=default_ccy, key="qa_currency")
        with qa_cols[3]:
            qa_balance = st.number_input("Opening Balance", value=0.0, step=100.0, key="qa_balance")
        if st.form_submit_button("Create Account"):
            if qa_name.strip():
                try:
                    create_account(conn, grp_opts[qa_group], qa_name.strip(),
                                   qa_currency.strip().upper() or default_ccy, qa_balance)
                    st.success(f"Created: {qa_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Account name is required.")

with st.expander("Manage Account Groups"):
    st.markdown("Add a custom account group:")
    with st.form("mm_add_group_quick"):
        ag_cols = st.columns(2)
        with ag_cols[0]:
            ag_name = st.text_input("Group Name", key="ag_name")
        with ag_cols[1]:
            ag_type = st.selectbox("Type", ["ASSET", "LIABILITY"], key="ag_type")
        if st.form_submit_button("Create Group"):
            if ag_name.strip():
                try:
                    create_account_group(conn, ag_name.strip(), ag_type)
                    st.success(f"Created group: {ag_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Group name is required.")
