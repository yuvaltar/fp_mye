"""Daily price loader: downloads from yfinance, cleans, and caches locally as CSV."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from tsm.config import DATA_DIR, HISTORY_START, TICKERS

COLUMNS = ["open", "high", "low", "close", "volume"]
MARKET_TZ = ZoneInfo("America/New_York")


def clean_prices(raw: pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    """Turn a raw yfinance frame into the frame every skill receives.

    Result: one row per completed trading day, oldest first, indexed by a
    timezone-free ``date`` index, with columns open/high/low/close/volume.
    Prices are adjusted for splits and dividends. Today's row is dropped
    because it is incomplete while the market is open.
    """
    if today is None:
        today = datetime.now(MARKET_TZ).date()

    df = raw.rename(columns=str.lower)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"price data is missing columns: {missing}")
    df = df[COLUMNS].copy()

    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    df.index = index.normalize().rename("date")

    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df = df[df.index < pd.Timestamp(today)]
    return df


def _download(ticker: str, start: str) -> pd.DataFrame:
    return yf.Ticker(ticker).history(start=start, auto_adjust=True)


def _cache_path(ticker: str, data_dir: Path) -> Path:
    return data_dir / f"{ticker}.csv"


def _fetched_today(path: Path) -> bool:
    fetched = datetime.fromtimestamp(path.stat().st_mtime, MARKET_TZ).date()
    return fetched == datetime.now(MARKET_TZ).date()


def load_prices(
    ticker: str,
    start: str = HISTORY_START,
    refresh: bool = False,
    data_dir: Path = DATA_DIR,
) -> pd.DataFrame:
    """Return clean daily prices for ``ticker``.

    Uses the local cache if it was fetched today; otherwise downloads again.
    Pass ``refresh=True`` to force a download.
    """
    path = _cache_path(ticker, data_dir)
    if not refresh and path.exists() and _fetched_today(path):
        return pd.read_csv(path, index_col="date", parse_dates=["date"])

    prices = clean_prices(_download(ticker, start))
    if prices.empty:
        raise ValueError(f"no price data returned for ticker {ticker!r}")
    data_dir.mkdir(parents=True, exist_ok=True)
    prices.to_csv(path)
    return prices


Panel = dict[str, pd.DataFrame]


def align_panel(frames: Panel) -> Panel:
    """Keep only the dates every ticker has, so all frames share one index."""
    common = None
    for frame in frames.values():
        common = frame.index if common is None else common.intersection(frame.index)
    return {ticker: frame.loc[common] for ticker, frame in frames.items()}


def load_panel(tickers: list[str] | None = None, refresh: bool = False) -> Panel:
    """Clean prices for several tickers, aligned on their common trading days."""
    tickers = list(TICKERS) if tickers is None else tickers
    return align_panel({t: load_prices(t, refresh=refresh) for t in tickers})


def truncate_panel(panel: Panel, position: int) -> Panel:
    """The panel as it was known at row ``position``: that row and everything before."""
    return {ticker: frame.iloc[: position + 1] for ticker, frame in panel.items()}


def main() -> None:
    """Download every covered ticker and print a one-line summary of each."""
    panel = load_panel(refresh=True)
    for ticker, prices in panel.items():
        print(
            f"{ticker}: {len(prices)} trading days, "
            f"{prices.index[0].date()} to {prices.index[-1].date()}, "
            f"last close {prices['close'].iloc[-1]:.2f}, "
            f"missing values {int(prices.isna().sum().sum())}"
        )


if __name__ == "__main__":
    main()
