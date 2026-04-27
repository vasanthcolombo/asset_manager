"""
Telegram bot for Asset Manager.

Commands:
  /start                      — welcome message
  /balance [account]          — show account balances
  /portfolio [ticker]         — show portfolio positions
  /add <amount> <cat> <acct> [note]   — record expense
  /income <amount> <cat> <acct> [note]
  /transfer <amount> <from> <to> [note]
  /buy <ticker> <qty> <price> <broker>
  /sell <ticker> <qty> <price> <broker>
  /ask <text>                 — natural language command via AI endpoint

Set env vars:
  TELEGRAM_BOT_TOKEN   — from @BotFather
  API_BASE_URL         — e.g. https://your-app.run.app
  API_TOKEN            — shared secret for API calls (optional if no auth)
"""

import logging
import os

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
API_BASE = os.environ.get("API_BASE_URL", "http://localhost:80").rstrip("/")
API_TOKEN = os.environ.get("API_TOKEN", "")

_headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api(method: str, path: str, **kwargs) -> dict:
    url = f"{API_BASE}{path}"
    resp = httpx.request(method, url, headers=_headers, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _fmt_sgd(val: float) -> str:
    return f"S${val:,.2f}"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Asset Manager Bot\n\n"
        "/balance [account] — account balances\n"
        "/portfolio [ticker] — portfolio positions\n"
        "/add <amount> <category> <account> [note] — record expense\n"
        "/income <amount> <category> <account> [note] — record income\n"
        "/transfer <amount> <from> <to> [note] — transfer between accounts\n"
        "/buy <ticker> <qty> <price> <broker> — buy stock\n"
        "/sell <ticker> <qty> <price> <broker> — sell stock\n"
        "/ask <anything> — natural language command"
    )


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        balances = _api("GET", "/api/mm/accounts/balances")
        if context.args:
            target = " ".join(context.args).lower()
            balances = [b for b in balances if target in b["name"].lower()]
        if not balances:
            await update.message.reply_text("No accounts found.")
            return
        lines = [f"*Account Balances*"]
        for b in balances:
            lines.append(f"  {b['name']}: {_fmt_sgd(b['balance'])}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        summary = _api("GET", "/api/portfolio/summary")
        positions = _api("GET", "/api/portfolio")
        if context.args:
            ticker = context.args[0].upper()
            positions = [p for p in positions if p["ticker"] == ticker]

        lines = [
            f"*Portfolio*",
            f"Total Value: {_fmt_sgd(summary['total_value_sgd'])}",
            f"Unrealized P&L: {_fmt_sgd(summary['total_unrealized_pnl_sgd'])}",
            f"",
        ]
        for p in positions[:10]:
            pnl_sign = "+" if p["unrealized_pnl_sgd"] >= 0 else ""
            lines.append(
                f"  {p['ticker']}: {p['shares']:.0f} shares | "
                f"{_fmt_sgd(p['current_value_sgd'])} | "
                f"{pnl_sign}{_fmt_sgd(p['unrealized_pnl_sgd'])}"
            )
        if len(positions) > 10:
            lines.append(f"  ... and {len(positions) - 10} more")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _record(update, context, "record_expense")


async def cmd_income(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _record(update, context, "record_income")


async def _record(update, context, action: str) -> None:
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            f"Usage: /{action.split('_')[1]} <amount> <category> <account> [note]"
        )
        return
    try:
        amount = float(args[0])
        category = args[1]
        account = args[2]
        notes = " ".join(args[3:]) if len(args) > 3 else None

        # Use AI endpoint for natural language parsing convenience
        msg = f"{action.replace('_', ' ')} {amount} {category} {account}"
        if notes:
            msg += f" {notes}"
        result = _api("POST", "/api/ai/command", json={"message": msg})
        await update.message.reply_text(f"Recorded! ID: {result.get('result', {}).get('id', '?')}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Usage: /transfer <amount> <from_account> <to_account> [note]")
        return
    try:
        amount = float(args[0])
        from_acc = args[1]
        to_acc = args[2]
        notes = " ".join(args[3:]) if len(args) > 3 else None
        result = _api("POST", "/api/mm/transactions", json={
            "date": None,
            "type": "TRANSFER",
            "account": from_acc,
            "to_account": to_acc,
            "amount": amount,
            "notes": notes,
        })
        await update.message.reply_text(f"Transfer recorded! ID: {result.get('id')}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _trade(update, context, "BUY")


async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _trade(update, context, "SELL")


async def _trade(update, context, side: str) -> None:
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            f"Usage: /{side.lower()} <ticker> <quantity> <price> <broker>"
        )
        return
    try:
        ticker, qty, price, broker = args[0], float(args[1]), float(args[2]), args[3]
        result = _api("POST", "/api/transactions", json={
            "date": None,
            "ticker": ticker,
            "side": side,
            "price": price,
            "quantity": qty,
            "broker": broker,
        })
        await update.message.reply_text(
            f"{side} {qty} {ticker.upper()} @ {price} recorded! ID: {result.get('id')}"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /ask <your question or command>")
        return
    message = " ".join(context.args)
    try:
        result = _api("POST", "/api/ai/command", json={"message": message})
        action = result.get("action", "unknown")

        if action == "unknown":
            await update.message.reply_text(f"Could not understand: {result.get('reason', message)}")
        elif action == "query_balance":
            balances = result.get("balances", [])
            lines = ["*Balances*"] + [f"  {b['name']}: {_fmt_sgd(b['balance'])}" for b in balances]
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        elif action == "query_portfolio":
            positions = result.get("positions", [])
            lines = ["*Portfolio*"] + [
                f"  {p['ticker']}: {_fmt_sgd(p['current_value_sgd'])} ({'+' if p['unrealized_pnl_sgd'] >= 0 else ''}{_fmt_sgd(p['unrealized_pnl_sgd'])})"
                for p in positions
            ]
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        else:
            txn_id = result.get("result", {}).get("id", "?")
            await update.message.reply_text(f"Done! Action: {action}, ID: {txn_id}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("income", cmd_income))
    app.add_handler(CommandHandler("transfer", cmd_transfer))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("ask", cmd_ask))

    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if webhook_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8080)),
            webhook_url=webhook_url,
        )
    else:
        log.info("No WEBHOOK_URL set — running in polling mode")
        app.run_polling()


if __name__ == "__main__":
    main()
