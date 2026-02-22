"""Asset Manager - Capital Markets Transaction Management App."""

import streamlit as st
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from db.connection import get_connection
from db.schema import initialize_db

st.set_page_config(
    page_title="Asset Manager",
    page_icon="\U0001f4c8",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize database connection (cached across reruns)
if "conn" not in st.session_state:
    conn = get_connection()
    initialize_db(conn)
    st.session_state.conn = conn

# Define pages
pages = {
    "Portfolio Manager": [
        st.Page("pages/dashboard.py",    title="Dashboard",    icon="🏠"),
        st.Page("pages/transactions.py", title="Transactions", icon="📝"),
        st.Page("pages/portfolio.py",    title="Portfolio",    icon="💼"),
        st.Page("pages/performance.py",  title="Performance",  icon="📈"),
        st.Page("pages/dividends.py",    title="Dividends",    icon="💰"),
        st.Page("pages/stocks.py",       title="Watchlist",    icon="⭐"),
    ],
    "Money Manager": [
        st.Page("pages/mm_record.py",   title="Record",   icon="✏️"),
        st.Page("pages/mm_stats.py",    title="Stats",    icon="📊"),
        st.Page("pages/mm_accounts.py", title="Accounts", icon="🏦"),
    ],
}

pg = st.navigation(pages)
pg.run()
