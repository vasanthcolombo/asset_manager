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


# ── Bulk balance computation (single transaction fetch for all accounts) ──────

def get_all_account_balances_bulk(conn, default_currency: str) -> dict:
    """
    Compute native + default-currency balances for ALL accounts in ONE pass.
    Returns {account_id: {"native": float, "default": float}}.

    Replaces calling get_account_balance / get_account_balance_in per account
    (which each fetch all transactions individually).
    """
    from datetime import datetime

    accounts  = get_accounts(conn, active_only=False)
    acc_by_id = {a["id"]: a for a in accounts}

    # One DB query for all transactions
    date_to  = datetime.now().strftime("%Y-%m-%d")
    all_txns = get_mm_transactions(conn, date_to=date_to)

    native_bal: dict[int, float] = {
        a["id"]: float(a["initial_balance"]) for a in accounts
    }

    for t in all_txns:
        ttype   = t["type"]
        from_id = t["account_id"]
        to_id   = t.get("to_account_id")
        fx      = t.get("fx_rate_to_default")

        if ttype in ("INCOME", "EXPENSE"):
            if from_id in acc_by_id:
                acc_ccy = acc_by_id[from_id]["currency"]
                amt     = _convert(t["amount"], t["currency"], acc_ccy, fx)
                if ttype == "INCOME":
                    native_bal[from_id] += amt
                else:
                    native_bal[from_id] -= amt

        elif ttype == "TRANSFER":
            if from_id in acc_by_id:
                acc_ccy = acc_by_id[from_id]["currency"]
                native_bal[from_id] -= _convert(t["amount"], t["currency"], acc_ccy, fx)
            if to_id and to_id in acc_by_id:
                acc_ccy = acc_by_id[to_id]["currency"]
                native_bal[to_id] += _convert(t["amount"], t["currency"], acc_ccy, fx)

    target = default_currency.upper()

    # Portfolio value cache (fetch once if any broker-linked accounts exist)
    _portfolio_positions = None

    result: dict[int, dict] = {}
    for acc in accounts:
        acc_id  = acc["id"]
        native  = native_bal[acc_id]
        acc_ccy = acc["currency"].upper()

        if acc_ccy == target:
            default_val = native
        else:
            default_val = native * get_live_fx_rate(acc_ccy, target)

        # Add portfolio market value for broker-linked active accounts
        if acc.get("broker_name") and acc["is_active"]:
            try:
                if _portfolio_positions is None:
                    from services.cache import get_cached_portfolio
                    _portfolio_positions = get_cached_portfolio(conn)
                broker_upper = acc["broker_name"].upper()
                port_sgd = sum(
                    p.current_value_sgd
                    for p in _portfolio_positions
                    if p.broker.upper() == broker_upper and p.shares > 0
                )
                if target == "SGD":
                    default_val += port_sgd
                else:
                    default_val += port_sgd * get_live_fx_rate("SGD", target)
            except Exception:
                pass

        result[acc_id] = {"native": native, "default": default_val}

    return result


def compute_all_running_balances(conn) -> dict:
    """
    Compute each account's running (native-currency) balance after every
    INCOME/EXPENSE transaction, taking ALL transaction types (including
    TRANSFER) into account so the balance accurately reflects real account state.

    Only INCOME/EXPENSE transaction IDs are stored in the result (TRANSFER rows
    are not shown in the detail table), but transfers DO move the running total
    so that consecutive visible rows reflect the real account balance including
    any intervening transfers.

    Returns {txn_id: {"balance": float, "currency": str}}.
    Processes transactions in chronological order (date ASC, id ASC).
    """
    accounts  = get_accounts(conn, active_only=False)
    acc_by_id = {a["id"]: a for a in accounts}

    running: dict[int, float] = {
        a["id"]: float(a["initial_balance"]) for a in accounts
    }

    # Must be ASC so cumulative running totals are correct
    rows = conn.execute(
        "SELECT id, type, account_id, to_account_id, amount, currency, fx_rate_to_default "
        "FROM mm_transactions ORDER BY date ASC, id ASC"
    ).fetchall()

    result: dict[int, dict] = {}
    for r in rows:
        ttype   = r["type"]
        from_id = r["account_id"]
        to_id   = r["to_account_id"]
        fx      = r["fx_rate_to_default"]

        if ttype == "INCOME" and from_id in acc_by_id:
            acc_ccy = acc_by_id[from_id]["currency"]
            running[from_id] += _convert(r["amount"], r["currency"], acc_ccy, fx)

        elif ttype == "EXPENSE" and from_id in acc_by_id:
            acc_ccy = acc_by_id[from_id]["currency"]
            running[from_id] -= _convert(r["amount"], r["currency"], acc_ccy, fx)

        elif ttype == "TRANSFER":
            if from_id in acc_by_id:
                acc_ccy = acc_by_id[from_id]["currency"]
                running[from_id] -= _convert(r["amount"], r["currency"], acc_ccy, fx)
            if to_id and to_id in acc_by_id:
                acc_ccy = acc_by_id[to_id]["currency"]
                running[to_id] += _convert(r["amount"], r["currency"], acc_ccy, fx)

        # Store balance snapshot for INCOME/EXPENSE (int key) and TRANSFER (tuple key)
        if ttype in ("INCOME", "EXPENSE") and from_id in acc_by_id:
            result[r["id"]] = {
                "balance":  running[from_id],
                "currency": acc_by_id[from_id]["currency"],
            }
        elif ttype == "TRANSFER":
            if from_id in acc_by_id:
                result[(r["id"], "from")] = {
                    "balance":  running[from_id],
                    "currency": acc_by_id[from_id]["currency"],
                }
            if to_id and to_id in acc_by_id:
                result[(r["id"], "to")] = {
                    "balance":  running[to_id],
                    "currency": acc_by_id[to_id]["currency"],
                }

    return result


def compute_net_worth_from_balances(
    accounts: list, balances: dict, groups: list
) -> dict:
    """Derive net worth totals from pre-computed balances dict."""
    group_totals: dict[int, float] = {}
    for acc in accounts:
        if not acc["is_active"]:
            continue
        gid = acc["group_id"]
        group_totals[gid] = group_totals.get(gid, 0.0) + balances.get(acc["id"], {}).get("default", 0.0)

    total_assets = 0.0
    total_liabilities = 0.0
    by_group = []
    for g in groups:
        bal = group_totals.get(g["id"], 0.0)
        by_group.append({"id": g["id"], "name": g["name"], "type": g["group_type"], "balance": bal})
        if g["group_type"] == "ASSET":
            total_assets += bal
        else:
            total_liabilities += abs(bal)

    return {
        "total_assets":      total_assets,
        "total_liabilities": total_liabilities,
        "net_worth":         total_assets - total_liabilities,
        "by_group":          by_group,
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
