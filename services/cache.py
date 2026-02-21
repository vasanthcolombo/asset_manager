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
