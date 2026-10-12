"""Project-wide constants shared by the data layer, the skills and the API."""
from pathlib import Path

HORIZON_DAYS = 5
TRADING_DAYS_PER_YEAR = 252

# Stocks covered by the MVP: ticker -> company name shown by GET /tickers.
# Ten GICS sectors, five large US-listed names each, plus TEVA and the market ETF.
TICKERS: dict[str, str] = {
    # Information technology
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "AVGO": "Broadcom Inc.",
    "ORCL": "Oracle Corporation",
    # Communication services
    "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.",
    "NFLX": "Netflix, Inc.",
    "DIS": "The Walt Disney Company",
    "TMUS": "T-Mobile US, Inc.",
    # Consumer discretionary
    "AMZN": "Amazon.com, Inc.",
    "TSLA": "Tesla, Inc.",
    "HD": "The Home Depot, Inc.",
    "MCD": "McDonald's Corporation",
    "LOW": "Lowe's Companies, Inc.",
    # Consumer staples
    "WMT": "Walmart Inc.",
    "COST": "Costco Wholesale Corporation",
    "PG": "The Procter & Gamble Company",
    "KO": "The Coca-Cola Company",
    "PEP": "PepsiCo, Inc.",
    # Health care
    "LLY": "Eli Lilly and Company",
    "JNJ": "Johnson & Johnson",
    "UNH": "UnitedHealth Group Incorporated",
    "ABBV": "AbbVie Inc.",
    "MRK": "Merck & Co., Inc.",
    # Financials
    "JPM": "JPMorgan Chase & Co.",
    "BRK-B": "Berkshire Hathaway Inc.",
    "V": "Visa Inc.",
    "MA": "Mastercard Incorporated",
    "BAC": "Bank of America Corporation",
    # Energy
    "XOM": "Exxon Mobil Corporation",
    "CVX": "Chevron Corporation",
    "COP": "ConocoPhillips",
    "EOG": "EOG Resources, Inc.",
    "SLB": "Schlumberger Limited",
    # Industrials
    "CAT": "Caterpillar Inc.",
    "UNP": "Union Pacific Corporation",
    "DE": "Deere & Company",
    "LMT": "Lockheed Martin Corporation",
    "ETN": "Eaton Corporation plc",
    # Materials
    "SHW": "The Sherwin-Williams Company",
    "APD": "Air Products and Chemicals, Inc.",
    "ECL": "Ecolab Inc.",
    "NEM": "Newmont Corporation",
    "FCX": "Freeport-McMoRan Inc.",
    # Utilities
    "NEE": "NextEra Energy, Inc.",
    "SO": "The Southern Company",
    "DUK": "Duke Energy Corporation",
    "AEP": "American Electric Power Company, Inc.",
    "SRE": "Sempra",
    # Extra: a mid-cap pharma with a very different volatility profile, and the market itself
    "TEVA": "Teva Pharmaceutical Industries Limited",
    "SPY": "SPDR S&P 500 ETF Trust",
}

# GICS sector of every ticker above, for the sector adjacency of the market map
# (and, later, the API's /tickers). TEVA is Health Care; SPY is the market, its own group.
MARKET_SECTOR = "Market"
SECTORS: dict[str, str] = {
    **dict.fromkeys(["AAPL", "MSFT", "NVDA", "AVGO", "ORCL"], "Information Technology"),
    **dict.fromkeys(["GOOGL", "META", "NFLX", "DIS", "TMUS"], "Communication Services"),
    **dict.fromkeys(["AMZN", "TSLA", "HD", "MCD", "LOW"], "Consumer Discretionary"),
    **dict.fromkeys(["WMT", "COST", "PG", "KO", "PEP"], "Consumer Staples"),
    **dict.fromkeys(["LLY", "JNJ", "UNH", "ABBV", "MRK", "TEVA"], "Health Care"),
    **dict.fromkeys(["JPM", "BRK-B", "V", "MA", "BAC"], "Financials"),
    **dict.fromkeys(["XOM", "CVX", "COP", "EOG", "SLB"], "Energy"),
    **dict.fromkeys(["CAT", "UNP", "DE", "LMT", "ETN"], "Industrials"),
    **dict.fromkeys(["SHW", "APD", "ECL", "NEM", "FCX"], "Materials"),
    **dict.fromkeys(["NEE", "SO", "DUK", "AEP", "SRE"], "Utilities"),
    "SPY": MARKET_SECTOR,
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
