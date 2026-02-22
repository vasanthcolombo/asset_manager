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
    Return the balance of an account in its own currency.

    balance = initial_balance
            + sum(INCOME flowing into this account)
            - sum(EXPENSE flowing out of this account)
            + sum(TRANSFER amounts received)
            - sum(TRANSFER amounts sent)

    FX conversion: amounts are stored with fx_rate_to_default (SGD).
    For native-currency balance we use the raw amount * (account_currency / SGD)
    approximation. Since all transactions store the original currency + amount,
    we sum amounts that match the account's currency directly; foreign-currency
    amounts are converted back via the stored fx_rate.
    """
    account = get_account_by_id(conn, account_id)
    if not account:
        return 0.0

    acc_currency = account["currency"].upper()
    balance = account["initial_balance"]

    date_to = as_of or datetime.now().strftime("%Y-%m-%d")
    txns = get_mm_transactions(conn, date_to=date_to)

    for t in txns:
        # Convert amount to account's native currency
        amount_native = _to_currency(t["amount"], t["currency"], acc_currency, t.get("fx_rate_to_default"))

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


def _to_currency(
    amount: float,
    from_currency: str,
    to_currency: str,
    fx_rate_to_sgd: float | None,
) -> float:
    """Convert amount from from_currency to to_currency using stored or live FX."""
    if from_currency.upper() == to_currency.upper():
        return amount
    # Convert via SGD as base
    # amount_sgd = amount * fx_rate_to_sgd
    # amount_to = amount_sgd / rate_to_currency_in_sgd
    if from_currency.upper() == "SGD":
        amount_sgd = amount
    elif fx_rate_to_sgd and fx_rate_to_sgd > 0:
        amount_sgd = amount * fx_rate_to_sgd
    else:
        live = get_live_fx_rate(from_currency, "SGD")
        amount_sgd = amount * live

    if to_currency.upper() == "SGD":
        return amount_sgd

    rate_out = get_live_fx_rate("SGD", to_currency)
    return amount_sgd * rate_out


def get_account_balance_sgd(conn, account_id: int) -> float:
    """
    Return account balance converted to SGD.
    For Investment accounts with a broker link, adds the portfolio market value
    for that broker from the portfolio engine.
    """
    account = get_account_by_id(conn, account_id)
    if not account:
        return 0.0

    balance_native = get_account_balance(conn, account_id)
    acc_currency = account["currency"].upper()

    if acc_currency == "SGD":
        balance_sgd = balance_native
    else:
        rate = get_live_fx_rate(acc_currency, "SGD")
        balance_sgd = balance_native * rate

    # Add portfolio market value if this is a linked Investment account
    broker = account.get("broker_name")
    if broker:
        try:
            from services.cache import get_cached_portfolio
            positions = get_cached_portfolio(conn)
            broker_upper = broker.upper()
            portfolio_value = sum(
                p.current_value_sgd
                for p in positions
                if p.broker.upper() == broker_upper and p.shares > 0
            )
            balance_sgd += portfolio_value
        except Exception:
            pass

    return balance_sgd


# ── Net Worth ─────────────────────────────────────────────────────────────────

def get_net_worth(conn) -> dict:
    """
    Return net worth summary:
      { total_assets, total_liabilities, net_worth, by_group: [...] }
    """
    groups = get_account_groups(conn)
    accounts = get_accounts(conn, active_only=True)

    group_balances: dict[int, float] = {}
    for acc in accounts:
        bal = get_account_balance_sgd(conn, acc["id"])
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
            "balance_sgd": bal,
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

def get_stats(conn, date_from: str, date_to: str) -> dict:
    """
    Return income/expense stats for the given period.

    Returns:
      {
        income_by_category:  [{"category": str, "amount_sgd": float}],
        expense_by_category: [{"category": str, "amount_sgd": float}],
        by_period: pd.DataFrame  # columns: period(YYYY-MM), income, expense, net
      }
    """
    txns = get_mm_transactions(conn, date_from=date_from, date_to=date_to)

    income_cat: dict[str, float] = {}
    expense_cat: dict[str, float] = {}
    period_rows: dict[str, dict] = {}

    for t in txns:
        if t["type"] == "TRANSFER":
            continue

        # Convert to SGD
        fx = t.get("fx_rate_to_default") or get_live_fx_rate(t["currency"], "SGD")
        amount_sgd = t["amount"] * fx if t["currency"].upper() != "SGD" else t["amount"]

        cat = t.get("category_name") or "Uncategorized"
        period = t["date"][:7]  # YYYY-MM

        if period not in period_rows:
            period_rows[period] = {"period": period, "income": 0.0, "expense": 0.0}

        if t["type"] == "INCOME":
            income_cat[cat] = income_cat.get(cat, 0.0) + amount_sgd
            period_rows[period]["income"] += amount_sgd
        elif t["type"] == "EXPENSE":
            expense_cat[cat] = expense_cat.get(cat, 0.0) + amount_sgd
            period_rows[period]["expense"] += amount_sgd

    income_by_cat = [{"category": k, "amount_sgd": v} for k, v in sorted(income_cat.items(), key=lambda x: -x[1])]
    expense_by_cat = [{"category": k, "amount_sgd": v} for k, v in sorted(expense_cat.items(), key=lambda x: -x[1])]

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
