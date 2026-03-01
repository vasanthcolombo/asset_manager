"""Money Manager — Accounts page: net worth, account balances, account management."""

import streamlit as st
import pandas as pd
from models.mm_account import (
    get_account_groups,
    get_accounts,
    create_account,
    create_account_group,
    delete_account,
    delete_account_group,
)
from models.mm_settings import get_mm_setting
from models.transaction import get_distinct_brokers
from services.cache import get_cached_portfolio, get_cached_accounts_data, invalidate_mm_accounts_cache
from services.fx_service import get_live_fx_rate

st.header("Accounts")

conn = st.session_state.conn

# ── Default Currency (from settings) ──────────────────────────────────────────
default_ccy = get_mm_setting(conn, "default_currency", "SGD")

# ── Load all balances from cache (single pass, then cached) ───────────────────
acc_cache = get_cached_accounts_data(conn, default_ccy)
nw       = acc_cache["nw"]
balances = acc_cache["balances"]  # {account_id: {"native": float, "default": float}}

# ── Net Worth Banner ──────────────────────────────────────────────────────────
nw_cols = st.columns(3)
with nw_cols[0]:
    st.metric(
        "Total Assets",
        f"{default_ccy} {nw['total_assets']:,.2f}",
        help="Sum of all ASSET account balances.",
    )
with nw_cols[1]:
    st.metric(
        "Total Liabilities",
        f"{default_ccy} {nw['total_liabilities']:,.2f}",
        help="Sum of all LIABILITY account balances.",
    )
with nw_cols[2]:
    st.metric(
        "Net Worth",
        f"{default_ccy} {nw['net_worth']:,.2f}",
        delta=f"{nw['net_worth']:+,.0f}",
        help="Total Assets minus Total Liabilities.",
    )

st.divider()

# ── Account Groups ────────────────────────────────────────────────────────────
groups = get_account_groups(conn)
accounts = get_accounts(conn, active_only=False)
acc_by_group: dict[int, list] = {}
for a in accounts:
    acc_by_group.setdefault(a["group_id"], []).append(a)

for group in groups:
    group_accs = acc_by_group.get(group["id"], [])
    active_accs = [a for a in group_accs if a["is_active"]]
    group_total = sum(
        balances.get(a["id"], {}).get("default", 0.0) for a in active_accs
    )
    icon = "🏦" if group["group_type"] == "ASSET" else "💳"
    label = f"{icon} {group['name']}  —  {default_ccy} {group_total:,.2f}"

    with st.expander(label, expanded=False):
        if not group_accs:
            st.caption("No accounts in this group yet.")
            continue

        # Table header
        hdr = st.columns([4, 3, 3, 0.7])
        hdr[0].markdown("**Account**")
        hdr[1].markdown("**Native Balance**")
        hdr[2].markdown(f"**{default_ccy} Equivalent**")

        for acc in group_accs:
            bal_native  = balances.get(acc["id"], {}).get("native", 0.0)
            bal_default = balances.get(acc["id"], {}).get("default", 0.0)
            display_name = acc["name"]
            if not acc["is_active"]:
                display_name += " *(inactive)*"
            if acc.get("broker_name"):
                display_name += f"  🔗 {acc['broker_name']}"

            row = st.columns([4, 3, 3, 0.7])
            with row[0]:
                st.markdown(display_name)
            with row[1]:
                st.caption(f"{acc['currency']} {bal_native:,.2f}")
            with row[2]:
                st.caption(
                    f"{default_ccy} {bal_default:,.2f}"
                    if acc["currency"] != default_ccy else "—"
                )
            with row[3]:
                if st.button(
                    "📊",
                    key=f"acc_nav_{acc['id']}",
                    help=f"View transactions for {acc['name']} in Stats",
                ):
                    st.session_state["mm_stats_prefilter_account_id"] = acc["id"]
                    st.switch_page("pages/mm_transactions.py")

        # Portfolio breakdown for linked Investment accounts
        for acc in group_accs:
            if acc.get("broker_name") and acc["is_active"]:
                try:
                    positions = get_cached_portfolio(conn)
                    broker_upper = acc["broker_name"].upper()
                    port_val_sgd = sum(
                        p.current_value_sgd for p in positions
                        if p.broker.upper() == broker_upper and p.shares > 0
                    )
                    acc_bal_default = balances.get(acc["id"], {}).get("default", 0.0)
                    if default_ccy == "SGD":
                        port_val = port_val_sgd
                    else:
                        port_val = port_val_sgd * get_live_fx_rate("SGD", default_ccy)
                    cash_val = acc_bal_default - port_val
                    st.caption(
                        f"**{acc['name']}** — Cash: {default_ccy} {cash_val:,.2f}  |  "
                        f"Portfolio: {default_ccy} {port_val:,.2f}"
                    )
                except Exception:
                    pass

st.divider()

# ── Add Account / Group ───────────────────────────────────────────────────────
with st.expander("Add New Account"):
    with st.form("add_account"):
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
            help="Investment accounts only: balance includes portfolio market value for this broker.",
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

with st.expander("Add New Account Group"):
    with st.form("add_group"):
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

# ── Delete Account ─────────────────────────────────────────────────────────────
with st.expander("Delete Account"):
    all_accs_for_del = get_accounts(conn, active_only=False)
    if all_accs_for_del:
        del_acc_opts = {
            f"{a['group_name']} / {a['name']}": a["id"]
            for a in sorted(all_accs_for_del, key=lambda x: (x["group_name"], x["name"]))
        }
        sel_del_acc = st.selectbox("Select account", list(del_acc_opts.keys()), key="del_acc_sel")
        st.caption("Warning: deleting an account also removes all its transactions.")
        if st.button("Delete Account", type="secondary", key="del_acc_btn"):
            delete_account(conn, del_acc_opts[sel_del_acc])
            invalidate_mm_accounts_cache()
            st.success(f"Deleted '{sel_del_acc}'.")
            st.rerun()
    else:
        st.caption("No accounts to delete.")

# ── Delete Account Group ───────────────────────────────────────────────────────
with st.expander("Delete Account Group"):
    user_groups = [g for g in groups if not g["is_predefined"]]
    if user_groups:
        del_grp_opts = {g["name"]: g["id"] for g in user_groups}
        sel_del_grp = st.selectbox("Select group", list(del_grp_opts.keys()), key="del_grp_sel")
        st.caption("Note: the group must have no accounts before it can be deleted.")
        if st.button("Delete Group", type="secondary", key="del_grp_btn"):
            try:
                delete_account_group(conn, del_grp_opts[sel_del_grp])
                invalidate_mm_accounts_cache()
                st.success(f"Deleted group '{sel_del_grp}'.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    else:
        st.caption("No user-defined groups to delete (built-in groups cannot be deleted).")
