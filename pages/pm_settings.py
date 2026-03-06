"""Portfolio Manager — Settings page."""

import streamlit as st
from models.pm_broker import get_pm_brokers, add_pm_broker, delete_pm_broker

st.header("Settings")

conn = st.session_state.conn

# ── Brokers ───────────────────────────────────────────────────────────────────
st.subheader("Brokers")
st.caption("Brokers listed here appear as options in the Transactions entry form.")

brokers = get_pm_brokers(conn)

if brokers:
    st.dataframe(
        {"Broker": brokers},
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No brokers configured yet. Add one below.")

st.divider()

col_add, col_del = st.columns(2)

with col_add:
    with st.expander("Add Broker", expanded=not brokers):
        with st.form("pm_add_broker"):
            new_broker = st.text_input("Broker Name", placeholder="e.g. IBKR, Tiger, Moomoo")
            if st.form_submit_button("Add Broker", use_container_width=True):
                if new_broker.strip():
                    try:
                        add_pm_broker(conn, new_broker.strip())
                        st.success(f'Added broker: {new_broker.strip()}')
                        st.rerun()
                    except Exception as e:
                        if "UNIQUE" in str(e):
                            st.error(f'Broker "{new_broker.strip()}" already exists.')
                        else:
                            st.error(str(e))
                else:
                    st.error("Broker name is required.")

with col_del:
    with st.expander("Delete Broker"):
        if brokers:
            sel_broker = st.selectbox("Select broker to remove", brokers, key="pm_del_broker_sel")
            if st.button("Delete Broker", type="secondary", key="pm_del_broker_btn",
                         use_container_width=True):
                delete_pm_broker(conn, sel_broker)
                st.success(f'Removed broker: {sel_broker}')
                st.rerun()
        else:
            st.caption("No brokers to delete.")
