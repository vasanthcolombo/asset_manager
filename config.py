"""Application configuration and constants."""

import os

# Database
DB_PATH = os.path.join(os.path.dirname(__file__), "db", "asset_manager.db")

# Base currency
BASE_CURRENCY = "SGD"

# Withholding tax rates on dividends by country
WITHHOLDING_TAX_RATES = {
    "US": 0.30,
    "SG": 0.00,
    "HK": 0.00,
    "GB": 0.00,
    "AU": 0.30,
    "CA": 0.25,
    "JP": 0.15,
    "DEFAULT": 0.30,
}

# Map yfinance exchange codes to country codes for tax purposes
EXCHANGE_TO_COUNTRY = {
    # US exchanges
    "NMS": "US", "NYQ": "US", "NGM": "US", "NCM": "US", "ASE": "US",
    "BTS": "US", "PCX": "US",
    # Singapore
    "SES": "SG",
    # Hong Kong
    "HKG": "HK",
    # UK
    "LSE": "GB",
    # Australia
    "ASX": "AU",
    # Canada
    "TOR": "CA", "VAN": "CA",
    # Japan
    "JPX": "JP",
}

# Ticker suffix to country mapping (fallback)
SUFFIX_TO_COUNTRY = {
    ".SI": "SG",
    ".HK": "HK",
    ".L": "GB",
    ".AX": "AU",
    ".TO": "CA",
    ".T": "JP",
}

# Default benchmarks for performance comparison
DEFAULT_BENCHMARKS = {
    "VOO": "S&P 500 (VOO)",
    "QQQ": "Nasdaq 100 (QQQ)",
    "ES3.SI": "STI ETF (ES3.SI)",
    "IWDA.L": "MSCI World (IWDA)",
}

# Cache TTL in seconds
LIVE_PRICE_TTL = 300  # 5 minutes
LIVE_FX_TTL = 300     # 5 minutes

# Excel upload expected columns (normalized)
EXCEL_COLUMNS = {
    "date": ["date", "trade_date", "trade date"],
    "ticker": ["ticker", "symbol", "stock"],
    "side": ["side", "action", "type", "buy/sell"],
    "price": ["price", "px", "exec_price", "execution price"],
    "quantity": ["quantity", "qty", "shares", "volume"],
    "broker": ["broker", "account", "platform"],
}
