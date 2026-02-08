"""Transactions page: manual entry, Excel upload, filter/search, edit/delete."""

import streamlit as st
import pandas as pd
from datetime import datetime, date
from models.transaction import (
    insert_transaction,
    get_transactions,
    update_transaction,
    delete_transaction,
    delete_all_transactions,
    get_distinct_brokers,
    get_distinct_tickers,
)
from services.excel_service import parse_excel, validate_rows, upsert_from_dataframe
from services.market_data import get_ticker_info

st.header("Transactions")

conn = st.session_state.conn

# --- Tabs for entry methods ---
entry_tab, upload_tab = st.tabs(["Manual Entry", "Excel Upload"])

# ==============================
# Manual Entry Tab
# ==============================
with entry_tab:
    with st.form("add_transaction", clear_on_submit=True):
        cols = st.columns([1.5, 1.5, 1, 1.5, 1.5, 1.5])
        with cols[0]:
            txn_date = st.date_input("Date", value=date.today())
        with cols[1]:
            txn_ticker = st.text_input("Ticker", placeholder="e.g. AAPL, D05.SI")
        with cols[2]:
            txn_side = st.selectbox("Side", ["BUY", "SELL"])
        with cols[3]:
            txn_price = st.number_input("Price", min_value=0.0, step=0.01, format="%.4f")
        with cols[4]:
            txn_qty = st.number_input("Quantity", min_value=0.0, step=1.0, format="%.2f")
        with cols[5]:
            existing_brokers = get_distinct_brokers(conn)
            txn_broker = st.text_input("Broker", placeholder="e.g. IBKR, Tiger")

        col_extra1, col_extra2 = st.columns(2)
        with col_extra1:
            txn_fx_override = st.number_input(
                "FX Rate Override (optional)", min_value=0.0, step=0.0001, format="%.4f",
                help="Override the auto-fetched FX rate to SGD for this transaction"
            )
        with col_extra2:
            txn_notes = st.text_input("Notes (optional)")

        submitted = st.form_submit_button("Add Transaction", use_container_width=True)

        if submitted:
            if not txn_ticker.strip():
                st.error("Ticker is required.")
            elif txn_price <= 0:
                st.error("Price must be positive.")
            elif txn_qty <= 0:
                st.error("Quantity must be positive.")
            elif not txn_broker.strip():
                st.error("Broker is required.")
            else:
                # Auto-detect currency
                try:
                    info = get_ticker_info(conn, txn_ticker.strip())
                    currency = info.get("currency", "USD")
                except Exception:
                    currency = "USD"

                txn = {
                    "date": txn_date.strftime("%Y-%m-%d"),
                    "ticker": txn_ticker.strip(),
                    "side": txn_side,
                    "price": txn_price,
                    "quantity": txn_qty,
                    "broker": txn_broker.strip(),
                    "currency": currency,
                    "fx_rate_override": txn_fx_override if txn_fx_override > 0 else None,
                    "notes": txn_notes or None,
                }
                try:
                    insert_transaction(conn, txn)
                    st.success(f"Added {txn_side} {txn_qty} {txn_ticker.upper()} @ {txn_price}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

# ==============================
# Excel Upload Tab
# ==============================
with upload_tab:
    st.markdown("Upload an Excel (.xlsx) or CSV file with columns: **Date, Ticker, Side, Px, Qty, Broker**")

    uploaded_file = st.file_uploader("Choose file", type=["xlsx", "csv"], key="excel_upload")

    if uploaded_file is not None:
        try:
            df = parse_excel(uploaded_file)
            valid_df, errors, imputed_indices = validate_rows(df)

            if imputed_indices:
                st.info(
                    f"{len(imputed_indices)} row(s) had missing dates and were imputed "
                    f"by interpolating between neighboring known dates."
                )

            if errors:
                st.warning(f"{len(errors)} validation error(s):")
                for err in errors[:20]:
                    st.text(f"  - {err}")

            if not valid_df.empty:
                st.markdown(f"**{len(valid_df)} valid rows** ready to import:")

                # Highlight imputed-date rows so the user can review
                def _highlight_imputed(row):
                    if row.name in imputed_indices:
                        return ["background-color: #fff3cd"] * len(row)
                    return [""] * len(row)

                st.dataframe(
                    valid_df.style.apply(_highlight_imputed, axis=1),
                    use_container_width=True,
                    hide_index=True,
                )

                if imputed_indices:
                    st.caption("Rows highlighted in yellow had their dates imputed.")

                if st.button("Import Transactions", type="primary"):
                    result = upsert_from_dataframe(conn, valid_df)
                    st.success(
                        f"Inserted: {result['inserted']}, Updated: {result['updated']}"
                    )
                    if result["errors"]:
                        for err in result["errors"]:
                            st.error(err)
                    st.rerun()
            else:
                st.error("No valid rows found in the file.")
        except Exception as e:
            st.error(f"Error reading file: {e}")

# ==============================
# Transaction History with Filters
# ==============================
st.divider()
st.subheader("Transaction History")

# Filters
filter_cols = st.columns(4)
with filter_cols[0]:
    all_tickers = get_distinct_tickers(conn)
    filter_tickers = st.multiselect("Filter by Ticker", all_tickers)
with filter_cols[1]:
    all_brokers = get_distinct_brokers(conn)
    filter_brokers = st.multiselect("Filter by Broker", all_brokers)
with filter_cols[2]:
    filter_side = st.multiselect("Filter by Side", ["BUY", "SELL"])
with filter_cols[3]:
    date_range = st.date_input("Date Range", value=[], key="date_range_filter")

date_from = date_range[0].strftime("%Y-%m-%d") if len(date_range) >= 1 else None
date_to = date_range[1].strftime("%Y-%m-%d") if len(date_range) >= 2 else None

txns = get_transactions(
    conn,
    tickers=filter_tickers or None,
    brokers=filter_brokers or None,
    sides=filter_side or None,
    date_from=date_from,
    date_to=date_to,
)

if txns:
    df = pd.DataFrame(txns)
    display_cols = ["id", "date", "ticker", "side", "price", "quantity", "broker", "currency", "notes"]
    display_cols = [c for c in display_cols if c in df.columns]
    df_display = df[display_cols].copy()
    df_display.columns = [c.replace("_", " ").title() for c in display_cols]

    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # Edit / Delete section
    with st.expander("Edit or Delete a Transaction"):
        txn_ids = [t["id"] for t in txns]
        txn_labels = [f"#{t['id']} | {t['date']} | {t['ticker']} | {t['side']} | {t['quantity']}@{t['price']} | {t['broker']}" for t in txns]

        selected_label = st.selectbox("Select transaction", txn_labels)
        if selected_label:
            selected_idx = txn_labels.index(selected_label)
            selected_txn = txns[selected_idx]

            edit_cols = st.columns(3)
            with edit_cols[0]:
                new_price = st.number_input("New Price", value=float(selected_txn["price"]), format="%.4f", key="edit_price")
            with edit_cols[1]:
                new_qty = st.number_input("New Quantity", value=float(selected_txn["quantity"]), format="%.2f", key="edit_qty")
            with edit_cols[2]:
                new_notes = st.text_input("Notes", value=selected_txn.get("notes") or "", key="edit_notes")

            btn_cols = st.columns(2)
            with btn_cols[0]:
                if st.button("Update", type="primary", use_container_width=True):
                    update_transaction(conn, selected_txn["id"], {
                        "price": new_price,
                        "quantity": new_qty,
                        "notes": new_notes or None,
                    })
                    st.success("Updated.")
                    st.rerun()
            with btn_cols[1]:
                if st.button("Delete", type="secondary", use_container_width=True):
                    delete_transaction(conn, selected_txn["id"])
                    st.success("Deleted.")
                    st.rerun()

    # Delete all transactions
    st.divider()
    with st.expander("Danger Zone"):
        st.markdown("**Delete all transactions** — this cannot be undone.")
        confirm = st.checkbox("I understand this will permanently delete all transactions", key="confirm_delete_all")
        if st.button("Delete All Transactions", type="primary", disabled=not confirm):
            count = delete_all_transactions(conn)
            st.success(f"Deleted {count} transaction(s).")
            st.rerun()
else:
    st.info("No transactions found. Add some above!")
