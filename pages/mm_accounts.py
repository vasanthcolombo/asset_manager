"""Money Manager — Accounts page: net worth, account balances, account management."""

import streamlit as st
import pandas as pd
from datetime import date
from models.mm_account import get_account_groups, get_accounts
from models.mm_settings import get_mm_setting
from models.mm_transaction import insert_mm_transaction
from services.cache import get_cached_portfolio, get_cached_accounts_data, invalidate_mm_accounts_cache
from services.fx_service import get_live_fx_rate


@st.dialog("Adjust Account Balance")
def _adjust_balance_dialog():
    conn     = st.session_state.conn
    acc_id   = st.session_state["_adj_acc_id"]
    acc_name = st.session_state["_adj_acc_name"]
    acc_ccy  = st.session_state["_adj_acc_ccy"]
    cur_bal  = st.session_state["_adj_cur_bal"]

    st.write(f"**{acc_name}** — current balance: **{acc_ccy} {cur_bal:,.2f}**")
    new_bal = st.number_input(
        f"New balance ({acc_ccy})",
        value=float(cur_bal),
        format="%.2f",
        step=100.0,
    )
    notes = st.text_input("Notes (optional)", placeholder="e.g. Monthly reconciliation")

    if st.button("Apply Adjustment", type="primary", use_container_width=True):
        delta = new_bal - cur_bal
        if delta == 0:
            st.warning("No change — new balance equals current balance.")
        else:
            try:
                insert_mm_transaction(conn, {
                    "date":     date.today().strftime("%Y-%m-%d"),
                    "type":     "MODIFIED_BALANCE",
                    "account_id": acc_id,
                    "amount":   delta,
                    "currency": acc_ccy,
                    "notes":    notes or f"Balance adjusted to {acc_ccy} {new_bal:,.2f}",
                })
                invalidate_mm_accounts_cache()
                st.rerun()
            except Exception as e:
                st.error(f"Could not adjust balance: {e}")


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
        hdr = st.columns([4, 3, 3, 0.7, 0.7])
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

            row = st.columns([4, 3, 3, 0.7, 0.7])
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
                    help=f"View transactions for {acc['name']}",
                ):
                    st.session_state["mm_stats_prefilter_account_id"] = acc["id"]
                    st.switch_page("pages/mm_transactions.py")
            with row[4]:
                if st.button(
                    "⚖️",
                    key=f"acc_adj_{acc['id']}",
                    help=f"Adjust balance for {acc['name']}",
                ):
                    st.session_state["_adj_acc_id"]   = acc["id"]
                    st.session_state["_adj_acc_name"] = acc["name"]
                    st.session_state["_adj_acc_ccy"]  = acc["currency"]
                    st.session_state["_adj_cur_bal"]  = bal_native
                    _adjust_balance_dialog()

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
st.caption("To add or delete accounts and account groups, go to **Settings**.")
