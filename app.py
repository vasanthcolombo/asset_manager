"""Asset Manager - Capital Markets Transaction Management App."""

import streamlit as st
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from db.connection import get_connection
from db.schema import initialize_db, _migrate_add_modified_balance, _migrate_add_pm_brokers

st.set_page_config(
    page_title="Asset Manager",
    page_icon="\U0001f4c8",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Password gate
_app_password = os.environ.get("APP_PASSWORD", "")
if _app_password and not st.session_state.get("authenticated"):
    st.title("Asset Manager")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if pwd == _app_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

# Initialize database connection (cached across reruns)
if "conn" not in st.session_state:
    conn = get_connection()
    initialize_db(conn)
    st.session_state.conn = conn
else:
    # Run pending migrations on already-open connections (safe no-op if done)
    _migrate_add_modified_balance(st.session_state.conn)
    _migrate_add_pm_brokers(st.session_state.conn)

# Define pages
pages = {
    "Portfolio Manager": [
        st.Page("pages/dashboard.py",    title="Dashboard",    icon="🏠"),
        st.Page("pages/transactions.py", title="Transactions", icon="📝"),
        st.Page("pages/portfolio.py",    title="Portfolio",    icon="💼"),
        st.Page("pages/performance.py",  title="Performance",  icon="📈"),
        st.Page("pages/dividends.py",    title="Dividends",    icon="💰"),
        st.Page("pages/stocks.py",       title="Watchlist",    icon="⭐"),
        st.Page("pages/pm_settings.py",  title="Settings",     icon="⚙️"),
    ],
    "Money Manager": [
        st.Page("pages/mm_record.py",        title="Record",       icon="✏️"),
        st.Page("pages/mm_stats.py",         title="Stats",        icon="📊"),
        st.Page("pages/mm_transactions.py",  title="Transactions", icon="📋"),
        st.Page("pages/mm_accounts.py",      title="Accounts",     icon="🏦"),
        st.Page("pages/mm_import.py",        title="Import",       icon="📥"),
        st.Page("pages/mm_settings_page.py", title="Settings",     icon="⚙️"),
    ],
}

pg = st.navigation(pages)
pg.run()
