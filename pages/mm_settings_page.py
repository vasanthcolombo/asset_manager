"""Money Manager — Settings page."""

import streamlit as st
from models.mm_account import (
    get_account_groups,
    get_accounts,
    create_account,
    create_account_group,
    delete_account,
    delete_account_group,
)
from models.mm_category import get_categories, create_category, delete_category
from models.mm_settings import get_mm_setting, set_mm_setting
from models.transaction import get_distinct_brokers
from services.cache import invalidate_mm_accounts_cache

st.header("Settings")

conn = st.session_state.conn

# ── Display ────────────────────────────────────────────────────────────────────
st.subheader("Display")

_COMMON_CURRENCIES = ["SGD", "USD", "EUR", "GBP", "AUD", "HKD", "JPY", "MYR", "INR", "AED"]
default_ccy = get_mm_setting(conn, "default_currency", "SGD")

new_ccy = st.selectbox(
    "Default Currency",
    _COMMON_CURRENCIES,
    index=_COMMON_CURRENCIES.index(default_ccy) if default_ccy in _COMMON_CURRENCIES else 0,
    key="mm_settings_default_ccy",
    help="All balances and stats are shown in this currency.",
)
if new_ccy != default_ccy:
    set_mm_setting(conn, "default_currency", new_ccy)
    st.success(f"Default currency updated to **{new_ccy}**.")
    st.rerun()

st.divider()

# ── Categories ────────────────────────────────────────────────────────────────
st.subheader("Categories")

def _cat_label(c: dict, all_cats: list) -> str:
    if c["parent_id"]:
        parent = next((p["name"] for p in all_cats if p["id"] == c["parent_id"]), "")
        return f"{parent} › {c['name']}"
    return c["name"]

with st.expander("Add Category"):
    with st.form("settings_add_category"):
        c_cols = st.columns([2, 1, 2])
        with c_cols[0]:
            new_cat_name = st.text_input("Category Name")
        with c_cols[1]:
            new_cat_type = st.selectbox("Type", ["EXPENSE", "INCOME"])
        with c_cols[2]:
            parent_cats = [c for c in get_categories(conn, type_=new_cat_type) if c["parent_id"] is None]
            parent_opts = {"— None (top-level) —": None} | {c["name"]: c["id"] for c in parent_cats}
            sel_parent = st.selectbox("Parent Category (optional)", list(parent_opts.keys()))
        if st.form_submit_button("Add Category", use_container_width=True):
            if new_cat_name.strip():
                try:
                    create_category(conn, new_cat_name.strip(), new_cat_type, parent_opts[sel_parent])
                    st.success(f"Added category: {new_cat_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Category name is required.")

with st.expander("Delete Category"):
    all_cats = get_categories(conn)
    user_cats = [c for c in all_cats if not c["is_predefined"]]
    if user_cats:
        del_cat_opts = {f"{c['type']} — {_cat_label(c, all_cats)}": c["id"] for c in user_cats}
        sel_del_cat = st.selectbox("Select category to remove", list(del_cat_opts.keys()),
                                   key="settings_del_cat_sel")
        if st.button("Delete Category", type="secondary", key="settings_del_cat_btn"):
            delete_category(conn, del_cat_opts[sel_del_cat])
            st.success("Category removed.")
            st.rerun()
    else:
        st.caption("No user-defined categories to remove.")

st.divider()

# ── Accounts ──────────────────────────────────────────────────────────────────
st.subheader("Accounts")

groups = get_account_groups(conn)

with st.expander("Add Account"):
    with st.form("settings_add_account"):
        f_cols = st.columns([2, 2, 1, 1])
        with f_cols[0]:
            acc_name = st.text_input("Account Name", placeholder="e.g. DBS Savings")
        with f_cols[1]:
            group_opts = {g["name"]: g["id"] for g in groups}
            sel_group_name = st.selectbox("Account Group", list(group_opts.keys()))
        with f_cols[2]:
            acc_currency = st.text_input("Currency", value=default_ccy)
        with f_cols[3]:
            acc_init_bal = st.number_input("Opening Balance", value=0.0, step=100.0, format="%.2f")

        all_brokers = get_distinct_brokers(conn)
        broker_link = st.selectbox(
            "Link to Portfolio Broker (optional)",
            ["— None —"] + all_brokers,
            help="Investment accounts only: links balance to a portfolio broker.",
        )

        if st.form_submit_button("Create Account", use_container_width=True):
            if acc_name.strip():
                try:
                    create_account(
                        conn,
                        group_id=group_opts[sel_group_name],
                        name=acc_name.strip(),
                        currency=acc_currency.strip().upper() or default_ccy,
                        initial_balance=acc_init_bal,
                        broker_name=broker_link if broker_link != "— None —" else None,
                    )
                    invalidate_mm_accounts_cache()
                    st.success(f"Created account: {acc_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Account name is required.")

with st.expander("Delete Account"):
    all_accs = get_accounts(conn, active_only=False)
    if all_accs:
        del_acc_opts = {
            f"{a['group_name']} / {a['name']}": a["id"]
            for a in sorted(all_accs, key=lambda x: (x["group_name"], x["name"]))
        }
        sel_del_acc = st.selectbox("Select account", list(del_acc_opts.keys()), key="settings_del_acc_sel")
        st.caption("Warning: deleting an account also removes all its transactions.")
        if st.button("Delete Account", type="secondary", key="settings_del_acc_btn"):
            delete_account(conn, del_acc_opts[sel_del_acc])
            invalidate_mm_accounts_cache()
            st.success(f"Deleted '{sel_del_acc}'.")
            st.rerun()
    else:
        st.caption("No accounts to delete.")

st.divider()

# ── Account Groups ────────────────────────────────────────────────────────────
st.subheader("Account Groups")

with st.expander("Add Account Group"):
    with st.form("settings_add_group"):
        g_cols = st.columns(2)
        with g_cols[0]:
            grp_name = st.text_input("Group Name", placeholder="e.g. Crypto")
        with g_cols[1]:
            grp_type = st.selectbox("Type", ["ASSET", "LIABILITY"])
        if st.form_submit_button("Create Group", use_container_width=True):
            if grp_name.strip():
                try:
                    create_account_group(conn, grp_name.strip(), grp_type)
                    invalidate_mm_accounts_cache()
                    st.success(f"Created group: {grp_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Group name is required.")

with st.expander("Delete Account Group"):
    user_groups = [g for g in groups if not g["is_predefined"]]
    if user_groups:
        del_grp_opts = {g["name"]: g["id"] for g in user_groups}
        sel_del_grp = st.selectbox("Select group", list(del_grp_opts.keys()), key="settings_del_grp_sel")
        st.caption("Note: the group must have no accounts before it can be deleted.")
        if st.button("Delete Group", type="secondary", key="settings_del_grp_btn"):
            try:
                delete_account_group(conn, del_grp_opts[sel_del_grp])
                invalidate_mm_accounts_cache()
                st.success(f"Deleted group '{sel_del_grp}'.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    else:
        st.caption("No user-defined groups to delete (built-in groups cannot be deleted).")
