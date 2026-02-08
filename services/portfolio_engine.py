"""FIFO cost basis engine, P&L calculations, and portfolio assembly."""

from dataclasses import dataclass, field
from collections import deque
from itertools import groupby
import sqlite3

from models.transaction import get_transactions
from services.market_data import get_ticker_info, get_live_price
from services.fx_service import get_effective_fx_rate, get_live_fx_rate
from services.dividend_service import fetch_dividends_for_ticker, calculate_dividends_received
from config import BASE_CURRENCY


@dataclass
class Lot:
    """A single purchase lot in the FIFO queue."""
    date: str
    quantity: float
    price_native: float
    currency: str
    fx_rate_to_sgd: float
    broker: str

    @property
    def cost_per_share_sgd(self) -> float:
        return self.price_native * self.fx_rate_to_sgd

    @property
    def total_cost_sgd(self) -> float:
        return self.quantity * self.cost_per_share_sgd


@dataclass
class ClosedLot:
    """Result of selling shares from a FIFO lot."""
    buy_date: str
    sell_date: str
    quantity: float
    buy_price_native: float
    sell_price_native: float
    currency: str
    buy_fx_rate: float
    sell_fx_rate: float
    broker: str

    @property
    def cost_sgd(self) -> float:
        return self.quantity * self.buy_price_native * self.buy_fx_rate

    @property
    def proceeds_sgd(self) -> float:
        return self.quantity * self.sell_price_native * self.sell_fx_rate

    @property
    def realized_pnl_sgd(self) -> float:
        return self.proceeds_sgd - self.cost_sgd


@dataclass
class TickerPosition:
    """Aggregated position for one ticker."""
    ticker: str
    name: str
    currency: str
    country: str
    open_lots: deque = field(default_factory=deque)
    closed_lots: list = field(default_factory=list)
    dividends_net_sgd: float = 0.0
    dividend_records: list = field(default_factory=list)
    # Live data (populated separately)
    live_price: float = 0.0
    live_fx_rate: float = 1.0

    @property
    def shares(self) -> float:
        return sum(lot.quantity for lot in self.open_lots)

    @property
    def market_price_native(self) -> float:
        return self.live_price

    @property
    def cost_basis_per_share_native(self) -> float:
        if self.shares == 0:
            return 0.0
        total_cost = sum(lot.quantity * lot.price_native for lot in self.open_lots)
        return total_cost / self.shares

    @property
    def total_investment_sgd(self) -> float:
        return sum(lot.total_cost_sgd for lot in self.open_lots)

    @property
    def current_value_sgd(self) -> float:
        return self.shares * self.live_price * self.live_fx_rate

    @property
    def realized_pnl_from_trades_sgd(self) -> float:
        return sum(cl.realized_pnl_sgd for cl in self.closed_lots)

    @property
    def realized_pnl_sgd(self) -> float:
        return self.realized_pnl_from_trades_sgd + self.dividends_net_sgd

    @property
    def unrealized_pnl_sgd(self) -> float:
        if self.shares == 0:
            return 0.0
        return self.current_value_sgd - self.total_investment_sgd

    @property
    def total_pnl_sgd(self) -> float:
        return self.realized_pnl_sgd + self.unrealized_pnl_sgd

    def dividends_for_year(self, year: int) -> float:
        """Net dividends in SGD for a specific year."""
        return sum(r["net_sgd"] for r in self.dividend_records if r["year"] == year)


def compute_position(
    ticker: str, name: str, currency: str, country: str, transactions: list[dict]
) -> TickerPosition:
    """
    Run FIFO cost basis calculation on sorted transactions for a single ticker.
    transactions must be sorted by date ASC.
    """
    position = TickerPosition(
        ticker=ticker, name=name, currency=currency, country=country
    )

    for txn in transactions:
        fx_rate = txn["effective_fx_rate"]

        if txn["side"] == "BUY":
            lot = Lot(
                date=txn["date"],
                quantity=txn["quantity"],
                price_native=txn["price"],
                currency=currency,
                fx_rate_to_sgd=fx_rate,
                broker=txn["broker"],
            )
            position.open_lots.append(lot)

        elif txn["side"] == "SELL":
            remaining = txn["quantity"]
            sell_price = txn["price"]
            sell_fx = fx_rate
            sell_date = txn["date"]

            while remaining > 1e-9 and position.open_lots:
                oldest = position.open_lots[0]

                if oldest.quantity <= remaining + 1e-9:
                    closed = ClosedLot(
                        buy_date=oldest.date,
                        sell_date=sell_date,
                        quantity=oldest.quantity,
                        buy_price_native=oldest.price_native,
                        sell_price_native=sell_price,
                        currency=currency,
                        buy_fx_rate=oldest.fx_rate_to_sgd,
                        sell_fx_rate=sell_fx,
                        broker=oldest.broker,
                    )
                    position.closed_lots.append(closed)
                    remaining -= oldest.quantity
                    position.open_lots.popleft()
                else:
                    closed = ClosedLot(
                        buy_date=oldest.date,
                        sell_date=sell_date,
                        quantity=remaining,
                        buy_price_native=oldest.price_native,
                        sell_price_native=sell_price,
                        currency=currency,
                        buy_fx_rate=oldest.fx_rate_to_sgd,
                        sell_fx_rate=sell_fx,
                        broker=oldest.broker,
                    )
                    position.closed_lots.append(closed)
                    oldest.quantity -= remaining
                    remaining = 0

    return position


def compute_portfolio(
    conn: sqlite3.Connection,
    brokers: list[str] | None = None,
    tickers: list[str] | None = None,
) -> list[TickerPosition]:
    """
    Compute the full portfolio with FIFO cost basis, live prices, FX, and dividends.
    Optionally filter by brokers and/or tickers.
    """
    all_txns = get_transactions(conn, tickers=tickers, brokers=brokers)

    # Sort by ticker, then date ASC
    all_txns.sort(key=lambda t: (t["ticker"], t["date"]))

    positions = []
    from datetime import datetime

    for ticker, txns_iter in groupby(all_txns, key=lambda t: t["ticker"]):
        txns = list(txns_iter)

        # Get ticker metadata
        info = get_ticker_info(conn, ticker)
        currency = info.get("currency", "USD")
        country = info.get("country", "US")
        name = info.get("name", ticker)

        # Resolve FX rates for each transaction
        for txn in txns:
            txn["currency"] = currency
            txn["effective_fx_rate"] = get_effective_fx_rate(conn, txn)

        # Run FIFO engine
        position = compute_position(ticker, name, currency, country, txns)

        # Fetch dividends
        try:
            div_history = fetch_dividends_for_ticker(conn, ticker, years_back=3)
            net_div_sgd, div_records = calculate_dividends_received(
                conn, ticker, txns, div_history, country, currency
            )
            position.dividends_net_sgd = net_div_sgd
            position.dividend_records = div_records
        except Exception:
            pass

        # Fetch live price and FX
        try:
            price_data = get_live_price(conn, ticker)
            position.live_price = price_data["price"] or 0.0
            if currency.upper() != BASE_CURRENCY:
                position.live_fx_rate = get_live_fx_rate(currency, BASE_CURRENCY)
            else:
                position.live_fx_rate = 1.0
        except Exception:
            pass

        positions.append(position)

    return positions


def positions_to_dataframe(positions: list[TickerPosition], current_year: int | None = None) -> "pd.DataFrame":
    """Convert positions to a DataFrame for display."""
    import pandas as pd
    from datetime import datetime

    if current_year is None:
        current_year = datetime.now().year

    rows = []
    for pos in positions:
        rows.append({
            "Ticker": pos.ticker,
            "Name": pos.name,
            "Shares": pos.shares,
            "Market Px": pos.live_price,
            "Currency": pos.currency,
            "Cost Basis/Share": pos.cost_basis_per_share_native,
            "Total Investment (S$)": pos.total_investment_sgd,
            "Current Value (S$)": pos.current_value_sgd,
            "Realised P&L (S$)": pos.realized_pnl_sgd,
            "Unrealised P&L (S$)": pos.unrealized_pnl_sgd,
            "P&L (S$)": pos.total_pnl_sgd,
            f"Div {current_year-2} (S$)": pos.dividends_for_year(current_year - 2),
            f"Div {current_year-1} (S$)": pos.dividends_for_year(current_year - 1),
            f"Div {current_year} (S$)": pos.dividends_for_year(current_year),
        })

    df = pd.DataFrame(rows)
    return df
