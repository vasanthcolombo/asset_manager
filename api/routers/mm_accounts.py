"""Money Manager — account and balance query endpoints."""

from fastapi import APIRouter, Depends

from api.deps import get_db, verify_token
from models.mm_account import get_accounts, get_account_groups

router = APIRouter(dependencies=[Depends(verify_token)])


@router.get("/groups")
def list_groups(conn=Depends(get_db)):
    return get_account_groups(conn)


@router.get("")
def list_accounts(group_id: int | None = None, conn=Depends(get_db)):
    return get_accounts(conn, group_id=group_id)


@router.get("/balances")
def account_balances(conn=Depends(get_db)):
    """Return all accounts with their computed running balance."""
    accounts = get_accounts(conn)
    result = []
    for acc in accounts:
        # Compute balance: initial + sum of credits - sum of debits
        rows = conn.execute(
            """
            SELECT
                SUM(CASE
                    WHEN account_id = ? AND type IN ('INCOME','TRANSFER') THEN amount
                    WHEN to_account_id = ? THEN amount
                    ELSE 0
                END) -
                SUM(CASE
                    WHEN account_id = ? AND type IN ('EXPENSE','TRANSFER') THEN amount
                    ELSE 0
                END) AS net
            FROM mm_transactions
            WHERE account_id = ? OR to_account_id = ?
            """,
            (acc["id"], acc["id"], acc["id"], acc["id"], acc["id"]),
        ).fetchone()
        net = rows["net"] or 0.0
        result.append({
            **acc,
            "balance": acc["initial_balance"] + net,
        })
    return result
