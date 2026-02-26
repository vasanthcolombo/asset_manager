"""Money Manager — Settings page."""

import streamlit as st
from models.mm_settings import get_mm_setting, set_mm_setting

st.header("Settings")

conn = st.session_state.conn

# ── Display Settings ───────────────────────────────────────────────────────────
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
