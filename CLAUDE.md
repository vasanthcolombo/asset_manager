# Asset Manager — Claude Code Instructions

## What This App Does
A personal capital markets portfolio tracker built with Streamlit + SQLite. Tracks buy/sell transactions, computes FIFO cost basis P&L, live portfolio value in SGD, XIRR performance vs benchmarks, and dividend income with withholding tax.

## How to Run

```bash
cd d:\asset_manager
streamlit run app.py
# Opens at http://localhost:8501
```

All data persists in `db/asset_manager.db` (SQLite, WAL mode). The DB is auto-initialized on first run via `db/schema.py`.

## Project Structure

```
app.py                  # Entry point — st.navigation setup
config.py               # Constants: BASE_CURRENCY, WHT rates, exchange mappings
db/
  connection.py         # get_connection() — WAL mode, Row factory
  schema.py             # DDL for all 8 tables, called once at startup
models/
  transaction.py        # CRUD + upsert (key: date+ticker+side+broker+price+qty)
  portfolio.py          # Custom portfolio CRUD + rules (BROKER|TICKER type)
  watchlist.py          # Simple watchlist CRUD
  fx_rate.py            # Cache ops: FX rates, ticker metadata, live prices
services/
  market_data.py        # yfinance wrapper — suffix-first currency detection, batch prices
  fx_service.py         # FX resolution: override > stored > cache > fetch > triangulate > 1.0
  portfolio_engine.py   # FIFO engine: Lot, ClosedLot, TickerPosition, compute_portfolio()
  performance_engine.py # XIRR via pyxirr, benchmark simulation, value over time
  dividend_service.py   # Dividend calc: replay txns to find shares at each ex-date + WHT
  excel_service.py      # Excel/CSV upload, validation, date imputation (linear interpolation)
  cache.py              # Session-state portfolio cache with 5-min TTL
pages/
  dashboard.py          # Metrics, gainers/losers, allocation pies, recent transactions
  transactions.py       # Manual entry, Excel upload, filter/edit/delete
  portfolio.py          # Entire / by-broker / custom portfolio views
  performance.py        # XIRR metrics + 3 Plotly charts
  dividends.py          # Dividend tracker by year with WHT breakdown
  stocks.py             # Watchlist with candlestick + volume charts
utils/
  formatters.py         # fmt_currency(), fmt_pct(), etc.
  validators.py         # Input validation helpers
```

## Key Design Decisions

### FIFO Cost Basis
- BUY → appends a `Lot` to a `deque`
- SELL → pops from front (oldest first), creates `ClosedLot` records
- Partial sells split the oldest lot

### All SGD Conversions Use Current Live FX Rate
Everything is converted to SGD using `position.live_fx_rate` (current rate), not historical rates. This matches the reference notebook's approach: `h.investment * fx`.

- `total_investment_sgd` = sum of ALL buy quantities × buy prices (native) × **current** FX rate
- `cost_basis_sgd` = remaining open lot cost (native) × **current** FX rate
- `realized_pnl_from_trades_sgd` = native P&L from closed lots × **current** FX rate
- `unrealized_pnl_sgd` = `current_value_sgd - cost_basis_sgd`

### Investment vs Cost Basis (important distinction)
- **Investment**: total cash ever put in — includes closed lots, never decreases on sells
- **Cost Basis**: cost of the *remaining* open position only — decreases on sells

### Caching Strategy
- Portfolio computation is cached in `st.session_state` with 5-min TTL (`services/cache.py`)
- Any page that mutates transactions calls `invalidate_portfolio_cache()` afterwards
- Live prices fetched in a single `yf.download()` batch call (not per-ticker)
- Live FX rates cached in-memory in `fx_service.py`

### Currency Detection (ticker suffix takes priority)
For tickers with known suffixes, currency is detected instantly without a yfinance API call:
- `.SI` → SGD (SGX)
- `.HK` → HKD
- `.L` → GBP
- `.AX` → AUD
- No suffix → USD

### Dividend Withholding Tax Rates
SG/HK/GB: 0% | JP: 15% | CA: 25% | US/AU/default: 30%

### Timezone Handling
yfinance returns tz-aware timestamps. Always normalize with `.tz_localize(None)` immediately after fetch to prevent comparison errors.

### Transaction Upsert Key
`(date, ticker, side, broker, price, quantity)` — re-uploading the same Excel won't create duplicates.

## DB Tables
`transactions`, `custom_portfolios`, `custom_portfolio_rules`, `watchlist`, `fx_rate_cache`, `ticker_metadata_cache`, `dividend_cache`, `price_cache`

## Common Patterns

### Adding a new page
1. Create `pages/yourpage.py`
2. Register it in `app.py` under the appropriate section in `pages` dict
3. Access DB via `st.session_state.conn`
4. Use `get_cached_portfolio(conn)` to get positions, `invalidate_portfolio_cache()` after mutations

### Getting portfolio positions
```python
from services.cache import get_cached_portfolio
positions = get_cached_portfolio(conn)  # list[TickerPosition]
df = positions_to_dataframe(positions)  # pandas DataFrame
```

### Formatting values
```python
from utils.formatters import fmt_currency, fmt_pct
fmt_currency(1234.5)   # "S$1,234.50"
fmt_pct(12.3)          # "12.30%"
```

## Dependencies
```
streamlit>=1.40.0
yfinance>=0.2.40
pyxirr>=0.10.0
pandas>=2.0.0
numpy>=1.24.0
plotly>=5.18.0
openpyxl>=3.1.0
```
