"""Money Manager — balance, net worth, and stats calculations."""

import pandas as pd
from datetime import datetime

from models.mm_account import get_accounts, get_account_by_id, get_account_groups
from models.mm_transaction import get_mm_transactions
from services.fx_service import get_live_fx_rate


# ── Account Balance ───────────────────────────────────────────────────────────

def get_account_balance(
    conn,
    account_id: int,
    as_of: str | None = None,
) -> float:
    """
    Return the balance of an account in its own (native) currency.

    balance = initial_balance
            + sum(INCOME flowing into this account)
            - sum(EXPENSE flowing out of this account)
            + sum(TRANSFER amounts received)
            - sum(TRANSFER amounts sent)

    All transaction amounts are stored in their original currency, so we convert
    using the stored fx_rate_to_default (pivoting through the default/SGD) to the
    account's native currency.
    """
    account = get_account_by_id(conn, account_id)
    if not account:
        return 0.0

    acc_currency = account["currency"].upper()
    balance = float(account["initial_balance"])

    date_to = as_of or datetime.now().strftime("%Y-%m-%d")
    txns = get_mm_transactions(conn, date_to=date_to)

    for t in txns:
        amount_native = _convert(
            t["amount"], t["currency"], acc_currency, t.get("fx_rate_to_default")
        )

        if t["type"] == "INCOME" and t["account_id"] == account_id:
            balance += amount_native
        elif t["type"] == "EXPENSE" and t["account_id"] == account_id:
            balance -= amount_native
        elif t["type"] == "TRANSFER":
            if t["account_id"] == account_id:
                balance -= amount_native
            if t.get("to_account_id") == account_id:
                balance += amount_native

    return balance


def get_account_balance_in(conn, account_id: int, target_currency: str) -> float:
    """
    Return account balance converted to target_currency using live FX rates.
    For Investment accounts with a broker link, adds the portfolio market value
    for that broker (converted from SGD to target_currency).
    """
    account = get_account_by_id(conn, account_id)
    if not account:
        return 0.0

    balance_native = get_account_balance(conn, account_id)
    acc_currency = account["currency"].upper()
    target = target_currency.upper()

    if acc_currency == target:
        balance_out = balance_native
    else:
        rate = get_live_fx_rate(acc_currency, target)
        balance_out = balance_native * rate

    # Add portfolio market value if linked Investment account
    broker = account.get("broker_name")
    if broker:
        try:
            from services.cache import get_cached_portfolio
            positions = get_cached_portfolio(conn)
            broker_upper = broker.upper()
            portfolio_value_sgd = sum(
                p.current_value_sgd
                for p in positions
                if p.broker.upper() == broker_upper and p.shares > 0
            )
            if target == "SGD":
                balance_out += portfolio_value_sgd
            else:
                rate_sgd_to_target = get_live_fx_rate("SGD", target)
                balance_out += portfolio_value_sgd * rate_sgd_to_target
        except Exception:
            pass

    return balance_out


def _convert(
    amount: float,
    from_currency: str,
    to_currency: str,
    fx_rate_to_sgd: float | None,
) -> float:
    """Convert amount between two currencies, pivoting through SGD."""
    from_c = from_currency.upper()
    to_c = to_currency.upper()
    if from_c == to_c:
        return amount

    # Step 1: convert to SGD
    if from_c == "SGD":
        amount_sgd = amount
    elif fx_rate_to_sgd and fx_rate_to_sgd > 0:
        amount_sgd = amount * fx_rate_to_sgd
    else:
        amount_sgd = amount * get_live_fx_rate(from_c, "SGD")

    # Step 2: convert from SGD to target
    if to_c == "SGD":
        return amount_sgd
    return amount_sgd * get_live_fx_rate("SGD", to_c)


def amount_in_default(
    amount: float,
    currency: str,
    fx_rate_to_default: float | None,
    default_currency: str = "SGD",
) -> float:
    """Convert a transaction amount to the default currency using stored or live FX."""
    ccy = currency.upper()
    dccy = default_currency.upper()
    if ccy == dccy:
        return amount
    if fx_rate_to_default and fx_rate_to_default > 0:
        # fx_rate_to_default stored as (default_currency / foreign_currency)
        # e.g. if default=SGD and ccy=AED: rate = SGD per 1 AED
        return amount * fx_rate_to_default
    return amount * get_live_fx_rate(ccy, dccy)


# ── Net Worth ─────────────────────────────────────────────────────────────────

def get_net_worth(conn, default_currency: str = "SGD") -> dict:
    """
    Return net worth summary in the given default currency:
      { total_assets, total_liabilities, net_worth, by_group: [...] }
    """
    groups = get_account_groups(conn)
    accounts = get_accounts(conn, active_only=True)

    group_balances: dict[int, float] = {}
    for acc in accounts:
        bal = get_account_balance_in(conn, acc["id"], default_currency)
        group_balances[acc["group_id"]] = group_balances.get(acc["group_id"], 0.0) + bal

    by_group = []
    total_assets = 0.0
    total_liabilities = 0.0

    for g in groups:
        bal = group_balances.get(g["id"], 0.0)
        by_group.append({
            "id": g["id"],
            "name": g["name"],
            "type": g["group_type"],
            "balance": bal,
        })
        if g["group_type"] == "ASSET":
            total_assets += bal
        else:
            total_liabilities += abs(bal)

    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": total_assets - total_liabilities,
        "by_group": by_group,
    }


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(conn, date_from: str, date_to: str, default_currency: str = "SGD") -> dict:
    """
    Return income/expense stats for the given period, converted to default_currency.

    Returns:
      {
        income_by_category:  [{"category": str, "amount": float}],
        expense_by_category: [{"category": str, "amount": float}],
        by_period: pd.DataFrame  # columns: period(YYYY-MM), income, expense, net, cumulative_net
      }
    """
    txns = get_mm_transactions(conn, date_from=date_from, date_to=date_to)

    income_cat: dict[str, float] = {}
    expense_cat: dict[str, float] = {}
    period_rows: dict[str, dict] = {}

    for t in txns:
        if t["type"] == "TRANSFER":
            continue

        amt = amount_in_default(
            t["amount"], t["currency"], t.get("fx_rate_to_default"), default_currency
        )

        cat = t.get("category_name") or "Uncategorized"
        period = t["date"][:7]  # YYYY-MM

        if period not in period_rows:
            period_rows[period] = {"period": period, "income": 0.0, "expense": 0.0}

        if t["type"] == "INCOME":
            income_cat[cat] = income_cat.get(cat, 0.0) + amt
            period_rows[period]["income"] += amt
        elif t["type"] == "EXPENSE":
            expense_cat[cat] = expense_cat.get(cat, 0.0) + amt
            period_rows[period]["expense"] += amt

    income_by_cat = [{"category": k, "amount": v} for k, v in sorted(income_cat.items(), key=lambda x: -x[1])]
    expense_by_cat = [{"category": k, "amount": v} for k, v in sorted(expense_cat.items(), key=lambda x: -x[1])]

    if period_rows:
        period_df = pd.DataFrame(sorted(period_rows.values(), key=lambda r: r["period"]))
        period_df["net"] = period_df["income"] - period_df["expense"]
        period_df["cumulative_net"] = period_df["net"].cumsum()
    else:
        period_df = pd.DataFrame(columns=["period", "income", "expense", "net", "cumulative_net"])

    return {
        "income_by_category": income_by_cat,
        "expense_by_category": expense_by_cat,
        "by_period": period_df,
    }
