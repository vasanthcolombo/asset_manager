"""Money Manager — Accounts page: net worth, account balances, account management."""

import streamlit as st
from models.mm_account import (
    get_account_groups,
    get_accounts,
    create_account,
    create_account_group,
    delete_account,
    delete_account_group,
)
from models.mm_settings import get_mm_setting, set_mm_setting
from models.transaction import get_distinct_brokers
from services.mm_service import get_account_balance, get_account_balance_in, get_net_worth
from services.cache import get_cached_portfolio
from services.fx_service import get_live_fx_rate

st.header("Accounts")

conn = st.session_state.conn

# ── Default Currency Selector ─────────────────────────────────────────────────
_COMMON_CURRENCIES = ["SGD", "USD", "EUR", "GBP", "AUD", "HKD", "JPY", "MYR", "INR", "AED"]
default_ccy = get_mm_setting(conn, "default_currency", "SGD")

top_row = st.columns([6, 2])
with top_row[1]:
    new_ccy = st.selectbox(
        "Default Currency",
        _COMMON_CURRENCIES,
        index=_COMMON_CURRENCIES.index(default_ccy) if default_ccy in _COMMON_CURRENCIES else 0,
        key="mm_default_ccy_sel",
        help="All balances and stats are shown in this currency.",
    )
    if new_ccy != default_ccy:
        set_mm_setting(conn, "default_currency", new_ccy)
        default_ccy = new_ccy
        st.rerun()

# ── Net Worth Banner ──────────────────────────────────────────────────────────
with st.spinner("Computing net worth..."):
    nw = get_net_worth(conn, default_ccy)

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
        get_account_balance_in(conn, a["id"], default_ccy) for a in active_accs
    )
    icon = "🏦" if group["group_type"] == "ASSET" else "💳"
    label = f"{icon} {group['name']}  —  {default_ccy} {group_total:,.2f}"

    with st.expander(label, expanded=bool(active_accs)):
        if group_accs:
            hdr = st.columns([3, 2, 2, 1])
            hdr[0].markdown("**Account**")
            hdr[1].markdown(f"**Native Balance**")
            hdr[2].markdown(f"**{default_ccy} Equivalent**")

            for acc in group_accs:
                bal_native = get_account_balance(conn, acc["id"])
                bal_default = get_account_balance_in(conn, acc["id"], default_ccy)
                native_str = f"{acc['currency']} {bal_native:,.2f}"

                col_name, col_native, col_default, col_del = st.columns([3, 2, 2, 1])
                with col_name:
                    status = "" if acc["is_active"] else " *(inactive)*"
                    broker_tag = f"  🔗 {acc['broker_name']}" if acc.get("broker_name") else ""
                    st.markdown(f"**{acc['name']}**{broker_tag}{status}")
                with col_native:
                    st.text(native_str)
                with col_default:
                    if acc["currency"] != default_ccy:
                        st.text(f"{default_ccy} {bal_default:,.2f}")
                    else:
                        st.text("—")
                with col_del:
                    if st.button("✕", key=f"del_acc_{acc['id']}", help="Delete account"):
                        delete_account(conn, acc["id"])
                        st.rerun()

                # Portfolio breakdown for linked Investment accounts
                if acc.get("broker_name") and acc["is_active"]:
                    try:
                        positions = get_cached_portfolio(conn)
                        broker_upper = acc["broker_name"].upper()
                        port_val_sgd = sum(
                            p.current_value_sgd for p in positions
                            if p.broker.upper() == broker_upper and p.shares > 0
                        )
                        # Convert portfolio value to default currency
                        if default_ccy == "SGD":
                            port_val = port_val_sgd
                            cash_val = bal_default - port_val
                        else:
                            rate = get_live_fx_rate("SGD", default_ccy)
                            port_val = port_val_sgd * rate
                            cash_val = bal_default - port_val
                        st.caption(
                            f"  Cash: {default_ccy} {cash_val:,.2f}  |  "
                            f"Portfolio: {default_ccy} {port_val:,.2f}"
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
