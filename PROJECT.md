# Asset Manager - Capital Markets Transaction Management

A Streamlit-based portfolio management app with FIFO cost basis, multi-currency SGD conversion, XIRR performance analytics, and dividend tracking with withholding tax.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| UI | Streamlit (multipage, `st.navigation`) |
| Database | SQLite (WAL mode) |
| Market Data | yfinance (prices, dividends, FX) |
| Charts | Plotly (candlestick, line, bar, pie) |
| XIRR | pyxirr (Rust-powered) |
| Excel | openpyxl + pandas |

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`. Data persists in `db/asset_manager.db`.

## Project Structure

```
D:\asset_manager\
├── app.py                          # Entry point, navigation setup
├── config.py                       # Tax rates, exchange mappings, constants
├── requirements.txt                # Dependencies
├── db/
│   ├── connection.py               # SQLite connection factory (WAL mode)
│   └── schema.py                   # DDL for all 8 tables
├── models/
│   ├── transaction.py              # Transaction CRUD + upsert + bulk delete
│   ├── portfolio.py                # Custom portfolio CRUD + rules
│   ├── watchlist.py                # Watchlist CRUD
│   └── fx_rate.py                  # FX rate, price, metadata cache ops
├── services/
│   ├── market_data.py              # yfinance wrapper (prices, dividends, ticker info)
│   ├── fx_service.py               # FX rate fetching, caching, triangulation
│   ├── portfolio_engine.py         # FIFO cost basis engine (Lot, ClosedLot, TickerPosition)
│   ├── performance_engine.py       # XIRR, benchmark comparison, value-over-time
│   ├── dividend_service.py         # Dividend calculation with withholding tax
│   └── excel_service.py            # Excel/CSV upload, validation, date imputation
├── pages/
│   ├── dashboard.py                # Overview: metrics, gainers/losers, allocation pies
│   ├── transactions.py             # Entry form, Excel upload, filter/edit/delete
│   ├── portfolio.py                # Entire / by-broker / custom portfolio views
│   ├── performance.py              # XIRR, benchmark XIRR, 3 Plotly charts
│   ├── dividends.py                # Dividend tracker by year with WHT breakdown
│   └── stocks.py                   # Watchlist with candlestick + volume charts
└── utils/
    ├── formatters.py               # Currency/percentage/number formatting
    └── validators.py               # Input validation (date, side, positive number)
```

## Database Schema

### transactions
Core ledger table. Every buy/sell event.
```
id, date, ticker, side (BUY|SELL), price, quantity, broker,
currency, fx_rate_to_sgd, fx_rate_override, notes,
created_at, updated_at
UNIQUE(date, ticker, side, broker, price, quantity)
Indexes: ticker, broker, date
```

### custom_portfolios
User-defined portfolio groupings.
```
id, name (UNIQUE), description, created_at
```

### custom_portfolio_rules
Rules linking brokers/tickers to custom portfolios.
```
id, portfolio_id (FK CASCADE), rule_type (BROKER|TICKER), rule_value
```

### watchlist
```
id, ticker (UNIQUE), added_at, notes
```

### fx_rate_cache
Persistent historical FX rates.
```
id, date, from_currency, to_currency, rate, source, fetched_at
UNIQUE(date, from_currency, to_currency)
```

### ticker_metadata_cache
```
ticker (PK), currency, country, exchange, name, sector, updated_at
```

### dividend_cache
```
id, ticker, ex_date, amount, currency, fetched_at
UNIQUE(ticker, ex_date)
```

### price_cache
Short-lived live price cache (5-min TTL).
```
ticker (PK), price, currency, fetched_at
```

## Pages

### Dashboard
- Portfolio value, total investment, P&L, current-year dividends
- Top 5 gainers and losers
- Allocation pie charts (by stock, by currency)
- Recent 10 transactions

### Transactions
- **Manual Entry**: date, ticker, side, price, qty, broker, optional FX override
- **Excel Upload**: .xlsx/.csv with flexible column names (Px/Price, Qty/Quantity, etc.)
  - Missing dates are imputed via linear interpolation between known dates
  - Imputed rows highlighted in yellow for review before import
  - Upsert logic: matching rows updated, new rows inserted
- **History**: filterable by ticker, broker, side, date range
- **Edit/Delete**: update price/qty/notes, delete single, or delete all (with confirmation)

### Portfolio
- **Entire Portfolio**: all positions across all brokers
- **By Broker**: filter to a single broker
- **Custom Portfolio**: user-defined rules combining brokers and/or tickers
- **Columns**: Ticker, Name, Shares, Market Px (native), Cost Basis/Share (native), Total Investment (S$), Current Value (S$), Realised P&L (S$), Unrealised P&L (S$), P&L (S$), Dividends by year (S$)

### Performance & Charts
- Total Return %, Portfolio XIRR, Benchmark XIRR (per selected benchmark)
- **Chart 1**: Cumulative investment over time (area)
- **Chart 2**: Portfolio value vs cost basis over time (weekly/monthly)
- **Chart 3**: Portfolio vs benchmarks comparison (multi-line)
- Benchmarks: VOO, QQQ, ES3.SI, IWDA.L (selectable)

### Dividends
- Summary by year (metric cards)
- Detailed table: ex-date, ticker, shares held, gross, WHT rate, tax, net (native + S$)
- Bar charts by ticker and by year
- Filterable by year

### Watchlist
- Add/remove tickers
- Live price table with day change %
- Candlestick + volume charts (1M/3M/6M/1Y/5Y periods)

## Core Calculation Logic

### FIFO Cost Basis (`portfolio_engine.py`)
- BUY transactions push `Lot` objects onto a FIFO `deque`
- SELL transactions pop from the front (oldest first), creating `ClosedLot` records
- Partial lot sales split the lot: sold portion becomes ClosedLot, remainder stays
- Cost basis per share = weighted average of remaining open lots (native currency)

### P&L Formulas (all in SGD)
| Metric | Formula |
|--------|---------|
| Total Investment | `sum(lot.qty * lot.price_native * lot.fx_rate)` for open lots |
| Current Value | `shares * live_price * live_fx_rate` |
| Realised P&L | `sum(closed_lot.proceeds - closed_lot.cost) + net_dividends` |
| Unrealised P&L | `current_value - total_investment` |
| Total P&L | `realised + unrealised` |

### FX Rate Priority Chain
1. User manual override (`fx_rate_override`)
2. Stored historical rate (`fx_rate_to_sgd`)
3. Cached rate in `fx_rate_cache`
4. Fetch from yfinance (`USDSGD=X` pairs)
5. Triangulate through USD (e.g., HKD -> USD -> SGD)
6. Fallback: 1.0

### Dividend Withholding Tax
For each ex-dividend date, replay transactions to find shares held:
```
gross = shares_held * div_per_share
tax = gross * wht_rate
net = gross - tax
net_sgd = net * fx_rate_on_ex_date
```

| Country | WHT Rate |
|---------|----------|
| SG | 0% |
| HK | 0% |
| GB | 0% |
| US | 30% |
| AU | 30% |
| CA | 25% |
| JP | 15% |
| Default | 30% |

### XIRR Calculation
Cash flows for `pyxirr.xirr(dates, amounts)`:
- BUY → negative (outflow) on transaction date
- SELL → positive (inflow) on transaction date
- Dividend → positive (inflow) on ex-dividend date
- Terminal value → positive (current portfolio value) on today

### Benchmark Comparison
Simulates investing the same SGD amounts at the same dates into a benchmark (e.g., VOO):
- Converts each buy amount from SGD to benchmark currency using historical FX
- Buys benchmark shares at historical price
- Proportional sells when actual portfolio has sells
- Terminal value = remaining benchmark shares * live price * live FX
- Computes XIRR on these simulated cash flows

### Date Imputation (Excel Upload)
When uploaded rows have missing dates:
1. Parse all dates, mark missing as NaT
2. Convert valid dates to ordinal numbers
3. Linearly interpolate ordinals (spreads gaps evenly)
4. Backfill leading NaTs, forward-fill trailing NaTs
5. Convert back to dates

### Currency Auto-Detection
1. yfinance `ticker.info["currency"]`
2. Fallback: exchange code mapping (SES→SGD, NMS→USD, HKG→HKD)
3. Fallback: ticker suffix (.SI→SGD, .HK→HKD, .L→GBP)
4. Default: USD

### Timezone Handling
yfinance returns tz-aware timestamps (`America/New_York`). All timestamps are normalized to tz-naive immediately after fetching to prevent comparison errors downstream.

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
