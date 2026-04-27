"""Portfolio Manager — transaction CRUD endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import get_db, verify_token
from models.transaction import (
    delete_transaction,
    get_transactions,
    insert_transaction,
    update_transaction,
)
from services.market_data import get_ticker_info

router = APIRouter(dependencies=[Depends(verify_token)])


class TransactionIn(BaseModel):
    date: str
    ticker: str
    side: str
    price: float
    quantity: float
    broker: str
    currency: str | None = None
    fx_rate_override: float | None = None
    notes: str | None = None


class TransactionUpdate(BaseModel):
    price: float | None = None
    quantity: float | None = None
    notes: str | None = None


@router.get("")
def list_transactions(
    tickers: Annotated[list[str] | None, Query()] = None,
    brokers: Annotated[list[str] | None, Query()] = None,
    sides: Annotated[list[str] | None, Query()] = None,
    date_from: str | None = None,
    date_to: str | None = None,
    conn=Depends(get_db),
):
    return get_transactions(conn, tickers=tickers, brokers=brokers, sides=sides,
                            date_from=date_from, date_to=date_to)


@router.post("", status_code=201)
def add_transaction(body: TransactionIn, conn=Depends(get_db)):
    if not body.currency:
        try:
            info = get_ticker_info(conn, body.ticker.strip())
            currency = info.get("currency", "USD")
        except Exception:
            currency = "USD"
    else:
        currency = body.currency

    txn = body.model_dump()
    txn["currency"] = currency
    row_id = insert_transaction(conn, txn)
    return {"id": row_id}


@router.patch("/{txn_id}")
def edit_transaction(txn_id: int, body: TransactionUpdate, conn=Depends(get_db)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    update_transaction(conn, txn_id, updates)
    return {"ok": True}


@router.delete("/{txn_id}", status_code=204)
def remove_transaction(txn_id: int, conn=Depends(get_db)):
    delete_transaction(conn, txn_id)
