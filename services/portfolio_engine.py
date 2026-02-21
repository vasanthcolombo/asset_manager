"""Average cost basis engine, P&L calculations, and portfolio assembly."""

from dataclasses import dataclass, field
from itertools import groupby
import sqlite3

from models.transaction import get_transactions
from services.market_data import get_ticker_info, get_live_price
from services.fx_service import get_effective_fx_rate, get_live_fx_rate
from services.dividend_service import fetch_dividends_for_ticker, calculate_dividends_received
from config import BASE_CURRENCY


@dataclass
class TickerPosition:
    """Aggregated position for one ticker using average cost method."""
    ticker: str
    name: str
    currency: str
    country: str

    # Running aggregates (updated by compute_position)
    _shares: float = 0.0
    _total_investment_native: float = 0.0   # all buy costs ever, never decreases
    _cost_basis_native: float = 0.0          # remaining open cost, avg-cost method
    _realized_pnl_native: float = 0.0        # realized trade P&L in native currency

    # Transaction events stored for use by performance engine
    txn_events: list = field(default_factory=list)  # list of enriched transaction dicts

    dividends_net_sgd: float = 0.0
    dividend_records: list = field(default_factory=list)

    # Live data (populated after FIFO computation)
    live_price: float = 0.0
    live_fx_rate: float = 1.0

    # ------------------------------------------------------------------ #
    # Core metrics                                                         #
    # ------------------------------------------------------------------ #

    @property
    def shares(self) -> float:
        return self._shares

    @property
    def cost_basis_per_share_native(self) -> float:
        if self._shares == 0:
            return 0.0
        return self._cost_basis_native / self._shares

    @property
    def total_investment_native(self) -> float:
        """Total cash outflow from ALL buys in native currency. Never decreases."""
        return self._total_investment_native

    @property
    def total_investment_sgd(self) -> float:
        """All buy costs converted at current FX rate."""
        return self._total_investment_native * self.live_fx_rate

    @property
    def cost_basis_native(self) -> float:
        """Remaining open position cost (native). Decreases on sells via avg cost."""
        return self._cost_basis_native

    @property
    def cost_basis_sgd(self) -> float:
        """Exposure: remaining open position cost at current FX rate."""
        return self._cost_basis_native * self.live_fx_rate

    @property
    def current_value_sgd(self) -> float:
        """Market value of current holdings."""
        return self._shares * self.live_price * self.live_fx_rate

    @property
    def realized_pnl_from_trades_sgd(self) -> float:
        return self._realized_pnl_native * self.live_fx_rate

    @property
    def realized_pnl_sgd(self) -> float:
        return self.realized_pnl_from_trades_sgd + self.dividends_net_sgd

    @property
    def unrealized_pnl_sgd(self) -> float:
        if self._shares == 0:
            return 0.0
        return self.current_value_sgd - self.cost_basis_sgd

    @property
    def total_pnl_sgd(self) -> float:
        return self.realized_pnl_sgd + self.unrealized_pnl_sgd

    def dividends_for_year(self, year: int) -> float:
        return sum(r["net_sgd"] for r in self.dividend_records if r["year"] == year)


def compute_position(
    ticker: str, name: str, currency: str, country: str, transactions: list[dict]
) -> TickerPosition:
    """
    Average cost basis calculation on sorted transactions for a single ticker.
    transactions must be sorted by date ASC and have 'effective_fx_rate' set.
    """
    position = TickerPosition(
        ticker=ticker, name=name, currency=currency, country=country
    )

    for txn in transactions:
        qty = txn["quantity"]
        price = txn["price"]
        cost = qty * price

        position.txn_events.append(txn)

        if txn["side"] == "BUY":
            position._total_investment_native += cost
            position._cost_basis_native += cost
            position._shares += qty

        elif txn["side"] == "SELL":
            if position._shares > 0:
                sell_qty = min(qty, position._shares)
                avg_cost = position._cost_basis_native / position._shares
                position._realized_pnl_native += (price - avg_cost) * sell_qty
                position._cost_basis_native -= avg_cost * sell_qty
                position._cost_basis_native = max(position._cost_basis_native, 0.0)
            position._shares = max(position._shares - qty, 0.0)

    return position


def compute_portfolio(
    conn: sqlite3.Connection,
    brokers: list[str] | None = None,
    tickers: list[str] | None = None,
    include_dividends: bool = True,
) -> list[TickerPosition]:
    """
    Compute the full portfolio with average cost basis, live prices, FX, and dividends.
    Optionally filter by brokers and/or tickers.
    Uses batch API calls for speed.
    """
    all_txns = get_transactions(conn, tickers=tickers, brokers=brokers)
    if not all_txns:
        return []

    # Sort by ticker, then date ASC
    all_txns.sort(key=lambda t: (t["ticker"], t["date"]))

    # --- Phase 1: Metadata (instant for suffix tickers, cached for others) ---
    ticker_meta = {}
    for ticker, _ in groupby(all_txns, key=lambda t: t["ticker"]):
        info = get_ticker_info(conn, ticker)
        ticker_meta[ticker] = info

    # --- Phase 2: Average cost computation (pure math, no API calls) ---
    positions = []
    ticker_txns_map = {}
    for ticker, txns_iter in groupby(all_txns, key=lambda t: t["ticker"]):
        txns = list(txns_iter)
        ticker_txns_map[ticker] = txns

        meta = ticker_meta[ticker]
        currency = meta.get("currency", "USD")
        country = meta.get("country", "US")
        name = meta.get("name", ticker)

        for txn in txns:
            txn["currency"] = currency
            txn["effective_fx_rate"] = get_effective_fx_rate(conn, txn)

        position = compute_position(ticker, name, currency, country, txns)
        positions.append(position)

    # --- Phase 3: Batch live prices (single yf.download call) ---
    all_tickers = [p.ticker for p in positions]
    from services.market_data import get_live_prices_batch
    live_prices = get_live_prices_batch(conn, all_tickers)

    # --- Phase 4: Live FX rates (one call per unique currency) ---
    fx_cache = {}
    unique_currencies = set(p.currency.upper() for p in positions)
    for ccy in unique_currencies:
        if ccy == BASE_CURRENCY:
            fx_cache[ccy] = 1.0
        elif ccy not in fx_cache:
            fx_cache[ccy] = get_live_fx_rate(ccy, BASE_CURRENCY)

    for pos in positions:
        price_data = live_prices.get(pos.ticker, {})
        pos.live_price = price_data.get("price", 0.0) or 0.0
        pos.live_fx_rate = fx_cache.get(pos.currency.upper(), 1.0)

    # --- Phase 5: Dividends (optional) ---
    if include_dividends:
        for pos in positions:
            try:
                txns = ticker_txns_map[pos.ticker]
                div_history = fetch_dividends_for_ticker(conn, pos.ticker, years_back=3)
                net_div_sgd, div_records = calculate_dividends_received(
                    conn, pos.ticker, txns, div_history, pos.country, pos.currency
                )
                pos.dividends_net_sgd = net_div_sgd
                pos.dividend_records = div_records
            except Exception:
                pass

    return positions


def positions_to_dataframe(positions: list[TickerPosition], current_year: int | None = None) -> "pd.DataFrame":
    """Convert positions to a DataFrame for display."""
    import pandas as pd
    from datetime import datetime

    if current_year is None:
        current_year = datetime.now().year

    rows = []
    for pos in positions:
        pnl_pct = (pos.total_pnl_sgd / pos.total_investment_sgd * 100) if pos.total_investment_sgd > 0 else 0.0
        rows.append({
            "Ticker": pos.ticker,
            "Name": pos.name,
            "Shares": pos.shares,
            "Market Px": pos.live_price,
            "Currency": pos.currency,
            "Avg Cost/Share": pos.cost_basis_per_share_native,
            "Investment (S$)": pos.total_investment_sgd,
            "Exposure (S$)": pos.cost_basis_sgd,
            "Market Value (S$)": pos.current_value_sgd,
            "Realised P&L (S$)": pos.realized_pnl_sgd,
            "Unrealised P&L (S$)": pos.unrealized_pnl_sgd,
            "P&L (S$)": pos.total_pnl_sgd,
            "P&L %": pnl_pct,
            f"Div {current_year-2} (S$)": pos.dividends_for_year(current_year - 2),
            f"Div {current_year-1} (S$)": pos.dividends_for_year(current_year - 1),
            f"Div {current_year} (S$)": pos.dividends_for_year(current_year),
        })

    df = pd.DataFrame(rows)
    return df
