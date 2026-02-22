"""Money Manager — Record Transaction page."""

import streamlit as st
import pandas as pd
from datetime import date

from models.mm_account import get_accounts, get_account_groups, create_account, create_account_group
from models.mm_category import get_categories, create_category, delete_category
from models.mm_transaction import (
    insert_mm_transaction,
    get_mm_transactions,
    delete_mm_transaction,
)
from services.fx_service import get_live_fx_rate

st.header("Record Transaction")

conn = st.session_state.conn

# ── Transaction Type ──────────────────────────────────────────────────────────
txn_type = st.radio(
    "Type",
    ["EXPENSE", "INCOME", "TRANSFER"],
    horizontal=True,
    key="mm_txn_type",
)

# ── Entry Form ────────────────────────────────────────────────────────────────
accounts = get_accounts(conn, active_only=True)
if not accounts:
    st.warning("No accounts found. Create one in the **Accounts** page first.")
    st.stop()

account_labels = {f"{a['name']} ({a['group_name']})": a["id"] for a in accounts}

categories = get_categories(conn, type_=txn_type if txn_type != "TRANSFER" else None)
# Build grouped display: "Parent > Child" or just "Name"
def _cat_label(c: dict) -> str:
    if c["parent_id"]:
        parent = next((p["name"] for p in categories if p["id"] == c["parent_id"]), "")
        return f"{parent} › {c['name']}"
    return c["name"]

cat_options = {_cat_label(c): c["id"] for c in categories if txn_type != "TRANSFER"}

with st.form("mm_record_form", clear_on_submit=True):
    row1 = st.columns([1.5, 2, 2, 1.5, 1.5])

    with row1[0]:
        txn_date = st.date_input("Date", value=date.today())
    with row1[1]:
        from_account_label = st.selectbox(
            "From Account" if txn_type == "TRANSFER" else "Account",
            list(account_labels.keys()),
        )
    with row1[2]:
        if txn_type == "TRANSFER":
            to_account_label = st.selectbox("To Account", list(account_labels.keys()))
        else:
            if cat_options:
                sel_cat_label = st.selectbox("Category", list(cat_options.keys()))
            else:
                sel_cat_label = None
                st.warning("No categories found.")
    with row1[3]:
        amount = st.number_input("Amount", min_value=0.01, step=10.0, format="%.2f")
    with row1[4]:
        currency = st.text_input("Currency", value="SGD").strip().upper() or "SGD"

    notes = st.text_input("Notes (optional)")

    submitted = st.form_submit_button(
        f"Add {txn_type.title()}",
        type="primary",
        use_container_width=True,
    )

    if submitted:
        account_id = account_labels[from_account_label]
        to_account_id = account_labels.get(to_account_label) if txn_type == "TRANSFER" else None
        category_id = cat_options.get(sel_cat_label) if txn_type != "TRANSFER" and sel_cat_label else None

        if txn_type == "TRANSFER" and account_id == to_account_id:
            st.error("From and To accounts must be different.")
        else:
            # Cache FX rate at time of entry
            fx = 1.0 if currency == "SGD" else get_live_fx_rate(currency, "SGD")

            txn = {
                "date": txn_date.strftime("%Y-%m-%d"),
                "type": txn_type,
                "account_id": account_id,
                "to_account_id": to_account_id,
                "category_id": category_id,
                "amount": amount,
                "currency": currency,
                "fx_rate_to_default": fx,
                "notes": notes or None,
            }
            try:
                insert_mm_transaction(conn, txn)
                st.success(f"{txn_type.title()} of {currency} {amount:,.2f} recorded.")
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
        amount_str = f"{t['currency']} {t['amount']:,.2f}"
        if t["currency"] != "SGD" and t.get("fx_rate_to_default"):
            sgd_val = t["amount"] * t["fx_rate_to_default"]
            amount_str += f"  (S${sgd_val:,.2f})"
        rows.append({
            "ID": t["id"],
            "Date": t["date"],
            "Type": t["type"],
            "Account": t["account_name"],
            "To Account": t.get("to_account_name") or "",
            "Category": t.get("category_name") or "",
            "Amount": amount_str,
            "Notes": t.get("notes") or "",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df.drop(columns=["ID"]), use_container_width=True, hide_index=True)

    # Delete row
    with st.expander("Delete a Transaction"):
        labels = [
            f"#{t['id']} | {t['date']} | {t['type']} | {t['account_name']} | {t['currency']} {t['amount']:,.2f}"
            for t in recent
        ]
        sel_label = st.selectbox("Select transaction to delete", labels)
        if sel_label and st.button("Delete", type="secondary"):
            txn_id = recent[labels.index(sel_label)]["id"]
            delete_mm_transaction(conn, txn_id)
            st.success("Deleted.")
            st.rerun()
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
            # Parent categories (top-level only)
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
        groups = get_account_groups(conn)
        grp_opts = {g["name"]: g["id"] for g in groups}
        qa_cols = st.columns([2, 2, 1, 1])
        with qa_cols[0]:
            qa_name = st.text_input("Account Name", key="qa_name")
        with qa_cols[1]:
            qa_group = st.selectbox("Group", list(grp_opts.keys()), key="qa_group")
        with qa_cols[2]:
            qa_currency = st.text_input("Currency", value="SGD", key="qa_currency")
        with qa_cols[3]:
            qa_balance = st.number_input("Opening Balance", value=0.0, step=100.0, key="qa_balance")
        if st.form_submit_button("Create Account"):
            if qa_name.strip():
                try:
                    create_account(conn, grp_opts[qa_group], qa_name.strip(),
                                   qa_currency.strip().upper() or "SGD", qa_balance)
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
