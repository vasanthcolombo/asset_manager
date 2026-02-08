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
    "Overview": [
        st.Page("pages/dashboard.py", title="Dashboard", icon="\U0001f3e0"),
    ],
    "Manage": [
        st.Page("pages/transactions.py", title="Transactions", icon="\U0001f4dd"),
        st.Page("pages/portfolio.py", title="Portfolio", icon="\U0001f4bc"),
    ],
    "Analyze": [
        st.Page("pages/performance.py", title="Performance", icon="\U0001f4c8"),
        st.Page("pages/dividends.py", title="Dividends", icon="\U0001f4b0"),
    ],
    "Research": [
        st.Page("pages/stocks.py", title="Watchlist", icon="\u2b50"),
    ],
}

pg = st.navigation(pages)
pg.run()
