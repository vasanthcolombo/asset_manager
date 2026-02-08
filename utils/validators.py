"""Input validation utilities."""

from datetime import datetime


def validate_date(date_str: str) -> tuple[bool, str]:
    """Validate a date string in YYYY-MM-DD format."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True, ""
    except ValueError:
        return False, f"Invalid date format: {date_str}. Expected YYYY-MM-DD."


def validate_ticker(ticker: str) -> tuple[bool, str]:
    if not ticker or not ticker.strip():
        return False, "Ticker cannot be empty."
    return True, ""


def validate_side(side: str) -> tuple[bool, str]:
    if side.upper() not in ("BUY", "SELL"):
        return False, f"Side must be BUY or SELL, got: {side}"
    return True, ""


def validate_positive_number(value, field_name: str) -> tuple[bool, str]:
    try:
        v = float(value)
        if v <= 0:
            return False, f"{field_name} must be positive, got: {v}"
        return True, ""
    except (TypeError, ValueError):
        return False, f"{field_name} must be a number, got: {value}"
