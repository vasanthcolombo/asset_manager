"""Money Manager — transaction CRUD endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.deps import get_db, verify_token
from models.mm_transaction import (
    delete_mm_transaction,
    get_mm_transactions,
    insert_mm_transaction,
    update_mm_transaction,
)
from models.mm_account import get_account_by_name
from models.mm_category import get_categories

router = APIRouter(dependencies=[Depends(verify_token)])


class MMTransactionIn(BaseModel):
    date: str
    type: str          # EXPENSE | INCOME | TRANSFER
    account: str       # account name (resolved to ID server-side)
    amount: float
    category: str | None = None   # category name (resolved to ID)
    to_account: str | None = None # for TRANSFER
    notes: str | None = None
    currency: str = "SGD"


class MMTransactionUpdate(BaseModel):
    amount: float | None = None
    notes: str | None = None
    date: str | None = None


@router.get("")
def list_mm_transactions(
    account_id: int | None = None,
    type_: Annotated[str | None, Query(alias="type")] = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = 100,
    conn=Depends(get_db),
):
    return get_mm_transactions(conn, account_id=account_id, type_=type_,
                               date_from=date_from, date_to=date_to, limit=limit)


@router.post("", status_code=201)
def add_mm_transaction(body: MMTransactionIn, conn=Depends(get_db)):
    from fastapi import HTTPException

    acc = get_account_by_name(conn, body.account)
    if not acc:
        raise HTTPException(404, f"Account '{body.account}' not found")

    cat_id = None
    if body.category:
        cats = get_categories(conn, type_=body.type.upper())
        match = next((c for c in cats if c["name"].lower() == body.category.lower()), None)
        if match:
            cat_id = match["id"]

    to_acc_id = None
    if body.to_account:
        to_acc = get_account_by_name(conn, body.to_account)
        if not to_acc:
            raise HTTPException(404, f"To-account '{body.to_account}' not found")
        to_acc_id = to_acc["id"]

    txn = {
        "date": body.date,
        "type": body.type.upper(),
        "account_id": acc["id"],
        "to_account_id": to_acc_id,
        "category_id": cat_id,
        "amount": body.amount,
        "currency": body.currency,
        "notes": body.notes,
    }
    row_id = insert_mm_transaction(conn, txn)
    return {"id": row_id}


@router.patch("/{txn_id}")
def edit_mm_transaction(txn_id: int, body: MMTransactionUpdate, conn=Depends(get_db)):
    from fastapi import HTTPException
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    update_mm_transaction(conn, txn_id, updates)
    return {"ok": True}


@router.delete("/{txn_id}", status_code=204)
def remove_mm_transaction(txn_id: int, conn=Depends(get_db)):
    delete_mm_transaction(conn, txn_id)
