"""Streamlit session_state caching for expensive computations."""

import streamlit as st
from datetime import datetime


def get_cached_portfolio(conn, brokers=None, tickers=None, include_dividends=True):
    """
    Get portfolio from session_state cache.
    Cache is valid when: today's date matches AND transaction fingerprint unchanged.
    Recalculates on a new calendar day or after any transaction change.
    """
    cache_key = f"portfolio_{brokers}_{tickers}_{include_dividends}"
    date_key = f"{cache_key}_date"
    fp_key = f"{cache_key}_fp"

    today = datetime.now().strftime("%Y-%m-%d")
    current_fp = get_transaction_fingerprint(conn)

    if (
        cache_key in st.session_state
        and st.session_state.get(date_key) == today
        and st.session_state.get(fp_key) == current_fp
    ):
        return st.session_state[cache_key]

    from services.portfolio_engine import compute_portfolio
    positions = compute_portfolio(
        conn, brokers=brokers, tickers=tickers, include_dividends=include_dividends
    )
    st.session_state[cache_key] = positions
    st.session_state[date_key] = today
    st.session_state[fp_key] = current_fp
    return positions


def invalidate_portfolio_cache():
    """Clear all cached portfolio data (call after transactions change)."""
    keys_to_delete = [k for k in st.session_state if k.startswith("portfolio_")]
    for k in keys_to_delete:
        del st.session_state[k]


# ---------------------------------------------------------------------------
# DB-level performance cache (persists across sessions)
# ---------------------------------------------------------------------------

def get_transaction_fingerprint(conn) -> str:
    """Fast fingerprint of the transactions table — changes on any add/edit/delete."""
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(MAX(updated_at), '') FROM transactions"
    ).fetchone()
    return f"{row[0]}_{row[1]}_{row[2]}"


def get_db_performance_cache(conn, cache_key: str, fingerprint: str):
    """Return cached DataFrame if fingerprint matches, else None."""
    import pandas as pd
    import json
    row = conn.execute(
        "SELECT data_json, transaction_fingerprint FROM performance_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row and row["transaction_fingerprint"] == fingerprint:
        data = json.loads(row["data_json"])
        df = pd.DataFrame(data)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    return None


def store_db_performance_cache(conn, cache_key: str, df, fingerprint: str) -> None:
    """Store a DataFrame in the DB performance cache."""
    import json
    data = df.copy()
    if "date" in data.columns:
        data["date"] = data["date"].astype(str)
    conn.execute(
        "INSERT OR REPLACE INTO performance_cache (cache_key, data_json, transaction_fingerprint) "
        "VALUES (?, ?, ?)",
        (cache_key, json.dumps(data.to_dict(orient="records")), fingerprint),
    )
    conn.commit()


def invalidate_performance_cache(conn) -> None:
    """Delete all performance cache entries (call after any transaction change)."""
    conn.execute("DELETE FROM performance_cache")
    conn.commit()


# ---------------------------------------------------------------------------
# Money Manager — accounts / net-worth cache
# ---------------------------------------------------------------------------

def get_mm_fingerprint(conn) -> str:
    """
    Fast fingerprint covering mm_transactions + mm_accounts.
    Changes on any insert/update/delete in either table.
    """
    t = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM mm_transactions"
    ).fetchone()
    a = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM mm_accounts"
    ).fetchone()
    return f"{t[0]}_{t[1]}_{a[0]}_{a[1]}"


def get_cached_accounts_data(conn, default_currency: str) -> dict:
    """
    Return cached net worth + all account balances in default_currency.
    Recalculates when mm_transactions or mm_accounts change, or currency changes.

    Returns:
      {
        "nw":       { total_assets, total_liabilities, net_worth, by_group },
        "balances": { account_id: { "native": float, "default": float } }
      }

    Uses a single bulk transaction fetch (not one query per account).
    """
    fp = get_mm_fingerprint(conn)
    if (
        "mm_accounts_data" in st.session_state
        and st.session_state.get("mm_accounts_fp") == fp
        and st.session_state.get("mm_accounts_ccy") == default_currency
    ):
        return st.session_state["mm_accounts_data"]

    from services.mm_service import get_all_account_balances_bulk, compute_net_worth_from_balances
    from models.mm_account import get_accounts, get_account_groups

    accounts = get_accounts(conn, active_only=False)
    groups   = get_account_groups(conn)
    balances = get_all_account_balances_bulk(conn, default_currency)
    nw       = compute_net_worth_from_balances(accounts, balances, groups)

    data = {"nw": nw, "balances": balances}
    st.session_state["mm_accounts_data"] = data
    st.session_state["mm_accounts_fp"]   = fp
    st.session_state["mm_accounts_ccy"]  = default_currency
    return data


def get_cached_running_balances(conn) -> dict:
    """
    Return {txn_id: {"balance": float, "currency": str}} for every mm_transaction.
    Recalculates only when mm_transactions or mm_accounts change.
    """
    fp = get_mm_fingerprint(conn)
    if (
        "mm_running_balances" in st.session_state
        and st.session_state.get("mm_running_balances_fp") == fp
    ):
        return st.session_state["mm_running_balances"]

    from services.mm_service import compute_all_running_balances
    result = compute_all_running_balances(conn)
    st.session_state["mm_running_balances"]    = result
    st.session_state["mm_running_balances_fp"] = fp
    return result


def invalidate_mm_accounts_cache() -> None:
    """Clear MM accounts, net-worth and running-balance caches."""
    for key in (
        "mm_accounts_data", "mm_accounts_fp", "mm_accounts_ccy",
        "mm_running_balances", "mm_running_balances_fp",
    ):
        st.session_state.pop(key, None)
