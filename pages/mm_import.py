"""Money Manager — Excel / CSV import page."""

import streamlit as st
import pandas as pd

from models.mm_account import (
    get_accounts,
    get_account_groups,
    get_account_by_name,
    create_account,
)
from models.mm_category import get_categories, create_category
from models.mm_settings import get_mm_setting
from models.mm_transaction import insert_mm_transaction, get_mm_transactions
from services.cache import invalidate_mm_accounts_cache

st.header("Import Transactions")

conn = st.session_state.conn
default_ccy = get_mm_setting(conn, "default_currency", "SGD")

# ── Known FX currency codes (for account currency guessing) ──────────────────
_FX_CODES = {"AED", "LKR", "MYR", "USD", "THB", "VND", "INR", "KHR", "EUR", "GBP",
             "JPY", "AUD", "HKD", "CAD", "CNY", "PHP", "IDR"}

_TYPE_MAP = {"Expense": "EXPENSE", "Income": "INCOME", "Transfer-Out": "TRANSFER"}


def _guess_group(name: str, group_name_to_id: dict) -> str:
    """Return best-guess account group name for a given account name."""
    n = name.lower()
    if any(k in n for k in ("cpf", "srs", "retirement")):
        return "Retirement"
    if any(k in n for k in ("loan", "debt")):
        return "Loan"
    if any(k in n for k in ("card", "cards")):
        return "Card"
    if any(k in n for k in ("ib ", " ib", "saxo", "poems", "moomoo", "tiger",
                             "crypto", "endowment", "t bill", "bond", "fund", "investment")):
        return "Investment"
    if any(k in n for k in ("posb", "uob", "ocbc", "dbs", "hsbc", "citi",
                             "bank", "savings", "boc", "sampath", "seylan")):
        return "Accounts"
    if any(k in n for k in ("condo", "property", "flat", "land")):
        return "Property"
    # Fallback: if the name IS a currency code, it's a cash wallet
    return "Cash"


def _guess_currency(name: str) -> str:
    """Return guessed currency for an account based on its name."""
    upper = name.strip().upper()
    if upper in _FX_CODES:
        return upper
    for code in _FX_CODES:
        if f" {code}" in upper or upper.startswith(code + " "):
            return code
    return default_ccy


def _parse_df(df_raw: pd.DataFrame) -> list[dict]:
    """
    Validate rows from the uploaded DataFrame.
    Returns a list of row dicts with an added 'status' field:
      valid | duplicate | missing_account
    """
    # Build fast lookups
    all_accounts = get_accounts(conn, active_only=False)
    acc_map = {a["name"].lower(): a for a in all_accounts}

    all_cats_exp = {c["name"].lower(): c["id"] for c in get_categories(conn, type_="EXPENSE")}
    all_cats_inc = {c["name"].lower(): c["id"] for c in get_categories(conn, type_="INCOME")}

    # Dedup set from existing transactions
    existing = get_mm_transactions(conn)
    existing_keys = {
        (t["date"], t["account_id"], t["type"],
         round(float(t["amount"]), 4), t["currency"].upper())
        for t in existing
    }

    rows = []
    for _, r in df_raw.iterrows():
        type_raw = str(r.get("Income/Expense", "")).strip()
        txn_type = _TYPE_MAP.get(type_raw)

        acc_name = str(r.get("Account", "")).strip()
        to_acc_name = str(r.get("To Account", "")).strip() if pd.notna(r.get("To Account")) else ""
        cat_name = str(r.get("Category", "")).strip() if pd.notna(r.get("Category")) else ""
        notes = str(r.get("Note", "")).strip() if pd.notna(r.get("Note")) else None

        try:
            amount = float(r.get("Amount", 0) or 0)
        except (ValueError, TypeError):
            amount = 0.0

        currency = str(r.get("Currency", default_ccy) or default_ccy).strip().upper()

        try:
            sgd_val = float(r.get("SGD", amount) or amount)
        except (ValueError, TypeError):
            sgd_val = amount

        # Compute historical FX rate from the pre-calculated default-ccy column
        if currency != default_ccy and amount != 0:
            fx_rate = round(sgd_val / amount, 6)
        else:
            fx_rate = 1.0

        try:
            date_str = pd.to_datetime(r.get("Date")).strftime("%Y-%m-%d")
        except Exception:
            date_str = ""

        # Resolve accounts
        acc = acc_map.get(acc_name.lower())
        to_acc = acc_map.get(to_acc_name.lower()) if to_acc_name else None

        # Determine status
        status = "valid"
        missing = []
        if not txn_type:
            status = "error"
            missing.append(f"Unknown type '{type_raw}'")
        if not acc_name or not acc:
            status = "missing_account"
            missing.append(f"Account '{acc_name}' not found")
        if txn_type == "TRANSFER" and to_acc_name and not to_acc:
            status = "missing_account"
            missing.append(f"To Account '{to_acc_name}' not found")

        if status == "valid":
            key = (date_str, acc["id"], txn_type, round(amount, 4), currency)
            if key in existing_keys:
                status = "duplicate"

        # Category note (informational — will auto-create on import)
        cat_id = None
        if txn_type == "EXPENSE":
            cat_id = all_cats_exp.get(cat_name.lower())
        elif txn_type == "INCOME":
            cat_id = all_cats_inc.get(cat_name.lower())

        rows.append({
            "date": date_str,
            "type": txn_type or type_raw,
            "account_id": acc["id"] if acc else None,
            "account_name": acc_name,
            "to_account_id": to_acc["id"] if to_acc else None,
            "to_account_name": to_acc_name,
            "category_name": cat_name,
            "category_id": cat_id,
            "amount": amount,
            "currency": currency,
            "sgd_col": sgd_val,
            "fx_rate_to_default": fx_rate,
            "notes": notes or None,
            "status": status,
            "issues": "; ".join(missing),
        })
    return rows


def _resolve_or_create_category(conn, name: str, txn_type: str) -> int | None:
    """Return existing category_id or create it, then return new id."""
    if not name:
        return None
    existing = get_categories(conn, type_=txn_type)
    match = next((c for c in existing if c["name"].lower() == name.lower()), None)
    if match:
        return match["id"]
    try:
        return create_category(conn, name, txn_type)
    except Exception:
        return None


# ── File Upload ───────────────────────────────────────────────────────────────
uploaded = st.file_uploader(
    "Upload Excel or CSV file",
    type=["xlsx", "xls", "csv"],
    help="Expected columns: Date, Account, To Account, Category, Note, SGD, Income/Expense, Amount, Currency",
)

if not uploaded:
    st.info("Upload your Money Manager Excel file to get started.")
    st.stop()

# ── Parse file ────────────────────────────────────────────────────────────────
try:
    if uploaded.name.endswith(".csv"):
        df_raw = pd.read_csv(uploaded)
    else:
        df_raw = pd.read_excel(uploaded)
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

# Normalise column names (strip whitespace)
df_raw.columns = [str(c).strip() for c in df_raw.columns]

with st.spinner(f"Validating {len(df_raw):,} rows..."):
    parsed = _parse_df(df_raw)

n_valid     = sum(1 for r in parsed if r["status"] == "valid")
n_duplicate = sum(1 for r in parsed if r["status"] == "duplicate")
n_missing   = sum(1 for r in parsed if r["status"] == "missing_account")
n_error     = sum(1 for r in parsed if r["status"] == "error")

# ── Summary bar ───────────────────────────────────────────────────────────────
s_cols = st.columns(4)
s_cols[0].metric("Ready to Import", n_valid)
s_cols[1].metric("Duplicates (skip)", n_duplicate)
s_cols[2].metric("Missing Accounts", n_missing)
s_cols[3].metric("Errors", n_error)

# ── Missing Accounts Section ──────────────────────────────────────────────────
missing_accs: set[str] = set()
for r in parsed:
    if r["status"] == "missing_account":
        if r["account_name"] and not get_account_by_name(conn, r["account_name"]):
            missing_accs.add(r["account_name"])
        if r["to_account_name"] and not get_account_by_name(conn, r["to_account_name"]):
            missing_accs.add(r["to_account_name"])

if missing_accs:
    st.divider()
    st.subheader(f"Create Missing Accounts ({len(missing_accs)})")
    st.caption("These account names appear in the file but don't exist in Money Manager yet.")

    groups = get_account_groups(conn)
    group_names = [g["name"] for g in groups]
    group_name_to_id = {g["name"]: g["id"] for g in groups}

    # Bulk create button
    if st.button(f"Create all {len(missing_accs)} with suggested settings", type="primary"):
        created = 0
        for acc_name in sorted(missing_accs):
            guessed_group = _guess_group(acc_name, group_name_to_id)
            group_id = group_name_to_id.get(guessed_group, group_name_to_id.get("Cash"))
            guessed_ccy = _guess_currency(acc_name)
            try:
                create_account(conn, group_id, acc_name, guessed_ccy)
                created += 1
            except Exception:
                pass
        st.success(f"Created {created} accounts.")
        st.rerun()

    st.markdown("**Or create individually (adjust group/currency as needed):**")

    for acc_name in sorted(missing_accs):
        guessed_group = _guess_group(acc_name, group_name_to_id)
        guessed_ccy = _guess_currency(acc_name)

        with st.container():
            cols = st.columns([3, 2, 1, 1])
            with cols[0]:
                st.text(acc_name)
            with cols[1]:
                sel_group = st.selectbox(
                    "Group",
                    group_names,
                    index=group_names.index(guessed_group) if guessed_group in group_names else 0,
                    key=f"grp_{acc_name}",
                    label_visibility="collapsed",
                )
            with cols[2]:
                sel_ccy = st.text_input(
                    "Currency",
                    value=guessed_ccy,
                    key=f"ccy_{acc_name}",
                    label_visibility="collapsed",
                )
            with cols[3]:
                if st.button("Create", key=f"create_{acc_name}"):
                    gid = group_name_to_id.get(sel_group, group_name_to_id.get("Cash"))
                    try:
                        create_account(conn, gid, acc_name, sel_ccy.strip().upper() or default_ccy)
                        st.success(f"Created '{acc_name}'")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

# ── Preview Table ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("Preview")

# Build display DataFrame
preview_rows = []
for r in parsed:
    native_str = f"{r['currency']} {r['amount']:,.2f}"
    default_str = (
        f"{default_ccy} {r['sgd_col']:,.2f}"
        if r["currency"] != default_ccy else "—"
    )
    preview_rows.append({
        "Status": r["status"],
        "Date": r["date"],
        "Type": r["type"],
        "Account": r["account_name"],
        "To Account": r["to_account_name"],
        "Category": r["category_name"],
        "Amount": native_str,
        default_ccy: default_str,
        "Notes": (r["notes"] or "")[:60],
        "Issues": r["issues"],
    })

preview_df = pd.DataFrame(preview_rows)

# Colour coding via pandas Styler
STATUS_COLORS = {
    "valid":           "background-color: #d4edda",   # green
    "duplicate":       "background-color: #e9ecef",   # grey
    "missing_account": "background-color: #f8d7da",   # red
    "error":           "background-color: #fff3cd",   # yellow
}

def _colour_row(row):
    color = STATUS_COLORS.get(row["Status"], "")
    return [color] * len(row)

# Pagination
page_size = 100
total_pages = max(1, (len(preview_df) + page_size - 1) // page_size)
page_num = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
start = (page_num - 1) * page_size
end = start + page_size
page_df = preview_df.iloc[start:end]

st.caption(f"Showing rows {start + 1}–{min(end, len(preview_df))} of {len(preview_df):,}  |  "
           f"Page {page_num}/{total_pages}")

st.dataframe(
    page_df.style.apply(_colour_row, axis=1),
    use_container_width=True,
    hide_index=True,
)

# ── Import Button ─────────────────────────────────────────────────────────────
st.divider()

if n_valid == 0:
    if n_missing > 0:
        st.warning(f"Create the {n_missing} missing accounts above before importing.")
    elif n_duplicate == len(parsed):
        st.success("All records are already in Money Manager — nothing to import.")
    else:
        st.info("No valid records to import.")
    st.stop()

if st.button(f"Import {n_valid:,} valid records", type="primary"):
    progress = st.progress(0, text="Importing…")
    imported = 0
    errors = 0

    valid_rows = [r for r in parsed if r["status"] == "valid"]

    for i, r in enumerate(valid_rows):
        try:
            # Resolve / auto-create category
            cat_id = r.get("category_id")
            if not cat_id and r["category_name"] and r["type"] in ("EXPENSE", "INCOME"):
                cat_id = _resolve_or_create_category(conn, r["category_name"], r["type"])

            insert_mm_transaction(conn, {
                "date": r["date"],
                "type": r["type"],
                "account_id": r["account_id"],
                "to_account_id": r["to_account_id"],
                "category_id": cat_id,
                "amount": r["amount"],
                "currency": r["currency"],
                "fx_rate_to_default": r["fx_rate_to_default"],
                "notes": r["notes"],
            })
            imported += 1
        except Exception:
            errors += 1

        if (i + 1) % 200 == 0 or (i + 1) == len(valid_rows):
            progress.progress((i + 1) / len(valid_rows), text=f"Imported {i + 1:,}/{len(valid_rows):,}…")

    progress.empty()
    msg = f"Import complete: **{imported:,} records imported**"
    if n_duplicate:
        msg += f", {n_duplicate:,} duplicates skipped"
    if n_missing:
        msg += f", {n_missing:,} rows skipped (missing accounts)"
    if errors:
        msg += f", {errors:,} errors"
    invalidate_mm_accounts_cache()
    st.success(msg)
    st.rerun()
