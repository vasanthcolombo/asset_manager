"""Formatting utilities for display."""


def fmt_currency(value: float, currency: str = "S$", decimals: int = 2) -> str:
    """Format a number as currency string."""
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    return f"{sign}{currency}{abs(value):,.{decimals}f}"


def fmt_pct(value: float, decimals: int = 2) -> str:
    """Format a number as percentage string."""
    if value is None:
        return "-"
    return f"{value:+.{decimals}f}%"


def fmt_number(value: float, decimals: int = 2) -> str:
    """Format a plain number."""
    if value is None:
        return "-"
    return f"{value:,.{decimals}f}"


def color_pnl(value: float) -> str:
    """Return CSS color for P&L values."""
    if value is None or value == 0:
        return "gray"
    return "green" if value > 0 else "red"
