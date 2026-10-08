"""Project-wide constants shared by the data layer, the skills and the API."""
from pathlib import Path

HORIZON_DAYS = 5
TRADING_DAYS_PER_YEAR = 252

# Stocks covered by the MVP: ticker -> company name shown by GET /tickers.
TICKERS: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "TEVA": "Teva Pharmaceutical Industries Ltd.",
    "JPM": "JPMorgan Chase & Co.",
    "XOM": "Exxon Mobil Corporation",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.",
    "SPY": "SPDR S&P 500 ETF Trust",
}

# The market index, also used as a feature by the weak_signals skill.
MARKET_TICKER = "SPY"

# First day of price history to download.
HISTORY_START = "2015-01-01"

# Local price cache (git-ignored).
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Output of the backtest pipeline, read by the API (committed so the API runs from a clone).
ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "artifacts"
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"

MODEL_VERSION = "0.1.0"
