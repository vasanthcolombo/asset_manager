"""Excel upload parsing, validation, and upsert logic."""

import pandas as pd
import numpy as np
import io
from config import EXCEL_COLUMNS
from utils.validators import validate_date, validate_side, validate_positive_number


def parse_excel(file) -> pd.DataFrame:
    """Parse an uploaded Excel or CSV file into a normalized DataFrame."""
    filename = getattr(file, "name", "file.xlsx")
    if filename.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file, engine="openpyxl")

    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = _map_columns(df)
    return df


def _map_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map various column name variants to standard names."""
    rename_map = {}
    for standard_name, variants in EXCEL_COLUMNS.items():
        for variant in variants:
            normalized = variant.strip().lower().replace(" ", "_")
            if normalized in df.columns and standard_name not in df.columns:
                rename_map[normalized] = standard_name
                break
    return df.rename(columns=rename_map)


def validate_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[int]]:
    """
    Validate each row. Imputes missing dates instead of rejecting rows.
    Returns (valid_df, error_messages, list_of_imputed_row_indices).
    """
    required_cols = ["date", "ticker", "side", "price", "quantity", "broker"]
    errors = []

    # Check required columns exist (date is handled specially)
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return pd.DataFrame(), [f"Missing required columns: {', '.join(missing)}"], []

    # --- Phase 1: Impute missing dates ---
    df, imputed_indices = _impute_missing_dates(df)

    # --- Phase 2: Validate non-date fields ---
    valid_mask = pd.Series(True, index=df.index)

    for idx, row in df.iterrows():
        row_num = idx + 2  # Excel row numbers (1-based + header)

        # Side
        ok, msg = validate_side(str(row["side"]))
        if not ok:
            errors.append(f"Row {row_num}: {msg}")
            valid_mask[idx] = False
            continue

        # Price
        ok, msg = validate_positive_number(row["price"], "Price")
        if not ok:
            errors.append(f"Row {row_num}: {msg}")
            valid_mask[idx] = False
            continue

        # Quantity
        ok, msg = validate_positive_number(row["quantity"], "Quantity")
        if not ok:
            errors.append(f"Row {row_num}: {msg}")
            valid_mask[idx] = False
            continue

        # Normalize fields
        df.at[idx, "ticker"] = str(row["ticker"]).upper().strip()
        df.at[idx, "side"] = str(row["side"]).upper().strip()
        df.at[idx, "broker"] = str(row["broker"]).strip()
        df.at[idx, "price"] = float(row["price"])
        df.at[idx, "quantity"] = float(row["quantity"])

    valid_df = df[valid_mask].reset_index(drop=True)

    # Remap imputed indices to new index after filtering
    old_to_new = {old: new for new, old in enumerate(df[valid_mask].index)}
    imputed_in_valid = [old_to_new[i] for i in imputed_indices if i in old_to_new]

    return valid_df, errors, imputed_in_valid


def _impute_missing_dates(df: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    """
    Impute missing/empty dates using linear interpolation between known dates.

    Strategy:
    - Parse all dates; mark empty/invalid as NaT.
    - Convert valid dates to ordinal numbers for interpolation.
    - Linearly interpolate ordinals by row position (spreads undated rows
      evenly between their nearest dated neighbors).
    - Backfill leading NaTs from the earliest known date.
    - Forward-fill trailing NaTs from the latest known date.

    Returns (df_with_dates_filled, list_of_original_indices_that_were_imputed).
    """
    df = df.copy()
    imputed_indices = []

    # Try to parse each date; track which ones are missing
    parsed_dates = pd.Series(pd.NaT, index=df.index)
    for idx, row in df.iterrows():
        raw = row.get("date")
        if pd.isna(raw) or str(raw).strip() in ("", "nan", "NaT", "None", "nat"):
            imputed_indices.append(idx)
            continue
        try:
            parsed_dates[idx] = pd.to_datetime(str(raw).strip())
        except Exception:
            imputed_indices.append(idx)

    # If no dates at all, can't impute - leave them as-is (will fail validation)
    if parsed_dates.dropna().empty:
        return df, []

    # If no missing dates, just format and return
    if not imputed_indices:
        for idx in df.index:
            df.at[idx, "date"] = parsed_dates[idx].strftime("%Y-%m-%d")
        return df, []

    # Convert to ordinals for numeric interpolation
    ordinals = parsed_dates.apply(
        lambda d: d.toordinal() if pd.notna(d) else np.nan
    ).astype(float)

    # Linear interpolation fills gaps between known dates evenly
    ordinals = ordinals.interpolate(method="linear")

    # Backfill leading NaNs (rows before any known date) and forward-fill trailing
    ordinals = ordinals.bfill().ffill()

    # Convert back to dates and write into the dataframe
    for idx in df.index:
        from datetime import date as _date
        imputed_date = _date.fromordinal(int(round(ordinals[idx])))
        df.at[idx, "date"] = imputed_date.strftime("%Y-%m-%d")

    return df, imputed_indices


def upsert_from_dataframe(conn, df: pd.DataFrame) -> dict:
    """Upsert validated rows into the database. Returns summary."""
    from models.transaction import upsert_transaction

    inserted = 0
    updated = 0
    errors = []

    for _, row in df.iterrows():
        txn = {
            "date": row["date"],
            "ticker": row["ticker"],
            "side": row["side"],
            "price": row["price"],
            "quantity": row["quantity"],
            "broker": row["broker"],
            "currency": row.get("currency", "USD"),
        }
        try:
            _, action = upsert_transaction(conn, txn)
            if action == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f"Error on {row['ticker']} {row['date']}: {e}")

    return {"inserted": inserted, "updated": updated, "errors": errors}
