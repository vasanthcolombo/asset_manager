"""Natural language command endpoint powered by Claude."""

import json
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_db, verify_token
from models.mm_account import get_accounts
from models.mm_category import get_categories

router = APIRouter(dependencies=[Depends(verify_token)])

_SYSTEM = """You are an assistant for a personal finance app (Asset Manager).
Parse the user's natural language command and return a JSON action object.

Available action types:
1. record_expense  — fields: account (str), category (str), amount (float), notes (str|null), date (YYYY-MM-DD|null)
2. record_income   — fields: account (str), category (str), amount (float), notes (str|null), date (YYYY-MM-DD|null)
3. transfer        — fields: from_account (str), to_account (str), amount (float), notes (str|null), date (YYYY-MM-DD|null)
4. buy_stock       — fields: ticker (str), quantity (float), price (float), broker (str), date (YYYY-MM-DD|null)
5. sell_stock      — fields: ticker (str), quantity (float), price (float), broker (str), date (YYYY-MM-DD|null)
6. query_balance   — fields: account (str|null)  — null means all accounts
7. query_portfolio — fields: ticker (str|null)    — null means full portfolio
8. unknown         — fields: reason (str)

Respond ONLY with valid JSON: {"action": "<type>", ...fields}

Today's date is {today}. If no date is specified, use today. Use null for optional fields when not provided.
"""


class AICommandRequest(BaseModel):
    message: str


@router.post("/command")
def ai_command(body: AICommandRequest, conn=Depends(get_db)):
    """Parse a natural language command and execute the appropriate action."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    from anthropic import Anthropic
    from datetime import date

    client = Anthropic(api_key=api_key)

    # Give Claude context about available accounts and categories
    accounts = get_accounts(conn)
    account_names = [a["name"] for a in accounts]
    categories = get_categories(conn)
    cat_names = [f"{c['name']} ({c['type']})" for c in categories]

    today = date.today().isoformat()
    system = _SYSTEM.format(today=today)
    context = (
        f"Available accounts: {', '.join(account_names) or 'none'}\n"
        f"Available categories: {', '.join(cat_names) or 'none'}"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=system,
        messages=[
            {"role": "user", "content": f"{context}\n\nCommand: {body.message}"}
        ],
    )

    raw = response.content[0].text.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(422, f"Could not parse AI response: {raw}")

    action = parsed.get("action", "unknown")

    # Execute the action
    if action in ("record_expense", "record_income"):
        from api.routers.mm_transactions import MMTransactionIn, add_mm_transaction
        txn_type = "EXPENSE" if action == "record_expense" else "INCOME"
        txn_in = MMTransactionIn(
            date=parsed.get("date") or today,
            type=txn_type,
            account=parsed["account"],
            amount=parsed["amount"],
            category=parsed.get("category"),
            notes=parsed.get("notes"),
        )
        result = add_mm_transaction(txn_in, conn)
        return {"action": action, "result": result, "parsed": parsed}

    elif action == "transfer":
        from api.routers.mm_transactions import MMTransactionIn, add_mm_transaction
        txn_in = MMTransactionIn(
            date=parsed.get("date") or today,
            type="TRANSFER",
            account=parsed["from_account"],
            to_account=parsed["to_account"],
            amount=parsed["amount"],
            notes=parsed.get("notes"),
        )
        result = add_mm_transaction(txn_in, conn)
        return {"action": action, "result": result, "parsed": parsed}

    elif action in ("buy_stock", "sell_stock"):
        from api.routers.transactions import TransactionIn, add_transaction
        side = "BUY" if action == "buy_stock" else "SELL"
        txn_in = TransactionIn(
            date=parsed.get("date") or today,
            ticker=parsed["ticker"],
            side=side,
            price=parsed["price"],
            quantity=parsed["quantity"],
            broker=parsed["broker"],
        )
        result = add_transaction(txn_in, conn)
        return {"action": action, "result": result, "parsed": parsed}

    elif action == "query_balance":
        from api.routers.mm_accounts import account_balances
        balances = account_balances(conn)
        target = parsed.get("account")
        if target:
            balances = [b for b in balances if b["name"].lower() == target.lower()]
        return {"action": action, "balances": balances}

    elif action == "query_portfolio":
        from api.routers.portfolio import get_portfolio
        positions = get_portfolio(conn)
        target = parsed.get("ticker")
        if target:
            positions = [p for p in positions if p["ticker"].upper() == target.upper()]
        return {"action": action, "positions": positions}

    else:
        return {"action": "unknown", "reason": parsed.get("reason", "Could not understand the command"), "raw": raw}
