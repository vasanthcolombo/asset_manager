"""Money Manager — Accounts page: net worth, account balances, account management."""

import streamlit as st
from models.mm_account import (
    get_account_groups,
    get_accounts,
    create_account,
    create_account_group,
    delete_account,
    delete_account_group,
    update_account,
)
from models.transaction import get_distinct_brokers
from services.mm_service import get_account_balance, get_account_balance_sgd, get_net_worth
from services.cache import get_cached_portfolio
from utils.formatters import fmt_currency

st.header("Accounts")

conn = st.session_state.conn

# ── Net Worth Banner ──────────────────────────────────────────────────────────
with st.spinner("Computing net worth..."):
    nw = get_net_worth(conn)

nw_cols = st.columns(3)
with nw_cols[0]:
    st.metric(
        "Total Assets",
        fmt_currency(nw["total_assets"]),
        help="Sum of all ASSET account balances converted to SGD.",
    )
with nw_cols[1]:
    st.metric(
        "Total Liabilities",
        fmt_currency(nw["total_liabilities"]),
        help="Sum of all LIABILITY account balances (credit cards, loans, etc.) in SGD.",
    )
with nw_cols[2]:
    st.metric(
        "Net Worth",
        fmt_currency(nw["net_worth"]),
        delta=f"{nw['net_worth']:+,.0f}",
        help="Total Assets minus Total Liabilities, in SGD.",
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
    group_total = sum(get_account_balance_sgd(conn, a["id"]) for a in group_accs if a["is_active"])
    label = f"{'🏦' if group['group_type'] == 'ASSET' else '💳'} {group['name']}  —  {fmt_currency(group_total)}"

    with st.expander(label, expanded=bool(group_accs)):
        if group_accs:
            for acc in group_accs:
                bal_native = get_account_balance(conn, acc["id"])
                bal_sgd = get_account_balance_sgd(conn, acc["id"])
                native_str = f"{acc['currency']} {bal_native:,.2f}" if acc["currency"] != "SGD" else ""

                col_name, col_native, col_sgd, col_del = st.columns([3, 2, 2, 1])
                with col_name:
                    status = "" if acc["is_active"] else " *(inactive)*"
                    broker_tag = f"  🔗 {acc['broker_name']}" if acc.get("broker_name") else ""
                    st.markdown(f"**{acc['name']}**{broker_tag}{status}")
                with col_native:
                    if native_str:
                        st.caption(native_str)
                with col_sgd:
                    st.markdown(fmt_currency(bal_sgd))
                with col_del:
                    if st.button("✕", key=f"del_acc_{acc['id']}", help="Delete account"):
                        delete_account(conn, acc["id"])
                        st.rerun()

                # Portfolio breakdown for linked Investment accounts
                if acc.get("broker_name") and acc["is_active"]:
                    try:
                        positions = get_cached_portfolio(conn)
                        broker_upper = acc["broker_name"].upper()
                        port_val = sum(
                            p.current_value_sgd for p in positions
                            if p.broker.upper() == broker_upper and p.shares > 0
                        )
                        cash_bal = bal_sgd - port_val
                        st.caption(
                            f"  Cash: {fmt_currency(cash_bal)}  |  "
                            f"Portfolio: {fmt_currency(port_val)}"
                        )
                    except Exception:
                        pass
        else:
            st.caption("No accounts in this group yet.")

        # Delete user-defined empty group
        if not group["is_predefined"] and not group_accs:
            if st.button(f"Delete group '{group['name']}'", key=f"del_grp_{group['id']}"):
                delete_account_group(conn, group["id"])
                st.rerun()

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
            acc_currency = st.text_input("Currency", value="SGD")
        with f_cols[3]:
            acc_init_bal = st.number_input("Opening Balance", value=0.0, step=100.0, format="%.2f")

        # Broker link — only relevant for Investment group
        all_brokers = get_distinct_brokers(conn)
        broker_link = st.selectbox(
            "Link to Portfolio Broker (optional)",
            ["— None —"] + all_brokers,
            help="Investment accounts only: links this account to a broker in the Portfolio Manager so the balance includes portfolio market value.",
        )

        if st.form_submit_button("Create Account", use_container_width=True):
            if acc_name.strip():
                try:
                    create_account(
                        conn,
                        group_id=group_opts[sel_group_name],
                        name=acc_name.strip(),
                        currency=acc_currency.strip().upper() or "SGD",
                        initial_balance=acc_init_bal,
                        broker_name=broker_link if broker_link != "— None —" else None,
                    )
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
                    st.success(f"Created group: {grp_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.error("Group name is required.")
