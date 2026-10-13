"""Quarterly earnings dates for the covered tickers, from two sources. Data only: no model uses it yet.

- **SEC EDGAR**: every 8-K filing, from ``data.sec.gov/submissions``; an earnings
  release is an 8-K whose items include 2.02 (Results of Operations and Financial
  Condition). Tickers map to CIKs through SEC's ``company_tickers.json``. The SEC
  asks automated clients for a contact email: requests carry the ``SEC_USER_AGENT``
  environment variable and stay under 10 a second.
- **Yahoo Finance**, through yfinance's ``get_earnings_dates``: past and scheduled
  dates, with the time of day (New York) when Yahoo has it, so a release can be
  placed before the open or after the close.

Yahoo is the source of earnings dates; SEC is the independent check (where both
have data, 99.6% of dates agree within one trading day). SEC misses some
companies (XOM files no earnings 8-K; TEVA, AVGO and DIS only from 2018, 2019 and 2020) and
also files non-earnings news under item 2.02 (e.g. Tesla's delivery numbers).

**Assumption:** a release date, and whether it comes before the open or after the
close, is known at least 5 trading days ahead (companies announce them weeks
ahead). Anything that uses a future release date must stay within that horizon.

``python -m tsm.earnings`` downloads both into ``algo/data/earnings/`` (git-ignored,
like the price cache; ``--refresh`` downloads again) and prints the comparison:
dates per source, quarters without a date, agreement between the sources, and
how much prices moved around each date. ``load_earnings`` reads what was saved.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import time
import urllib.request

import numpy as np
import pandas as pd

from tsm.config import DATA_DIR, MARKET_TICKER, TICKERS

EARNINGS_DIR = DATA_DIR / "earnings"
SEC_FILE = EARNINGS_DIR / "sec_8k.csv"  # every 8-K, all items, so the 2.02 filter can be redone
YAHOO_FILE = EARNINGS_DIR / "yahoo.csv"

WINDOW_START = "2015-01-01"
RESULTS_ITEM = "2.02"  # 8-K item "Results of Operations and Financial Condition"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
SEC_PAUSE_SECONDS = 0.15  # about 7 requests a second, under the SEC's limit of 10
YAHOO_PAUSE_SECONDS = 1.0
YAHOO_LIMIT = 100  # Yahoo's cap; about 25 years of quarters

# A release before 9:30 New York time moves that day's close, one at 16:00 or later the next day's.
MARKET_OPEN, MARKET_CLOSE = 9.5, 16.0


def covered_tickers() -> list[str]:
    """Every covered ticker that reports earnings (the market ETF does not)."""
    return [t for t in TICKERS if t != MARKET_TICKER]


# ---------------------------------------------------------------- SEC EDGAR

def _user_agent() -> str:
    agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in agent:
        raise RuntimeError(
            "set SEC_USER_AGENT to a name and a contact email (the SEC requires one for automated "
            "requests), e.g. SEC_USER_AGENT='Temporal Skills Market you@example.com'; see .env.example"
        )
    return agent


def _sec_get(url: str, agent: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    time.sleep(SEC_PAUSE_SECONDS)
    return json.loads(body)


def sec_ciks(company_tickers: dict, tickers: list[str]) -> dict[str, int]:
    """Ticker -> CIK from ``company_tickers.json``; SEC may write BRK-B as BRK.B or the other way."""
    by_ticker = {row["ticker"].upper(): int(row["cik_str"]) for row in company_tickers.values()}
    ciks = {}
    for ticker in tickers:
        for spelling in (ticker, ticker.replace("-", "."), ticker.replace(".", "-")):
            if spelling.upper() in by_ticker:
                ciks[ticker] = by_ticker[spelling.upper()]
                break
    return ciks


def parse_8k(block: dict, ticker: str, cik: int) -> pd.DataFrame:
    """The 8-K rows of one submissions block (``filings.recent`` or one of the older files)."""
    frame = pd.DataFrame(
        {
            "form": block.get("form", []),
            "filing_date": block.get("filingDate", []),
            "report_date": block.get("reportDate", []),
            "acceptance": block.get("acceptanceDateTime", []),
            "items": block.get("items", []),
            "accession": block.get("accessionNumber", []),
        }
    )
    frame = frame[frame["form"].isin(["8-K", "8-K/A"])].copy()
    frame.insert(0, "cik", cik)
    frame.insert(0, "ticker", ticker)
    return frame


def fetch_sec(tickers: list[str], start: str = WINDOW_START) -> tuple[pd.DataFrame, list[str]]:
    """Every 8-K of every ticker since ``start``; also the tickers SEC does not list."""
    agent = _user_agent()
    ciks = sec_ciks(_sec_get(SEC_TICKERS_URL, agent), tickers)
    parts = []
    for ticker in tickers:
        if ticker not in ciks:
            continue
        cik = ciks[ticker]
        submissions = _sec_get(SEC_SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json"), agent)
        parts.append(parse_8k(submissions["filings"]["recent"], ticker, cik))
        # Older filings live in extra files; fetch only those reaching back into the window.
        for extra in submissions["filings"].get("files", []):
            if extra.get("filingTo", "9999") >= start:
                parts.append(parse_8k(_sec_get(SEC_SUBMISSIONS_URL.format(name=extra["name"]), agent), ticker, cik))
        print(f"  SEC {ticker}: CIK {cik}", flush=True)
    frame = pd.concat(parts, ignore_index=True)
    frame = frame[frame["filing_date"] >= start].drop_duplicates("accession")
    return frame.sort_values(["ticker", "filing_date"]).reset_index(drop=True), [t for t in tickers if t not in ciks]


def results_dates(sec: pd.DataFrame) -> pd.DataFrame:
    """One row per (ticker, filing date) of an original 8-K that includes item 2.02.

    Amendments (8-K/A) repeat an earlier release, so they are left out.
    """
    items = sec["items"].fillna("").astype(str).str.split(",")
    picked = sec[(sec["form"] == "8-K") & items.apply(lambda parts: RESULTS_ITEM in [p.strip() for p in parts])]
    out = picked[["ticker", "filing_date"]].drop_duplicates()
    return out.assign(date=pd.to_datetime(out["filing_date"]))[["ticker", "date"]].reset_index(drop=True)


# ---------------------------------------------------------------- Yahoo Finance

def timing_of(moment: pd.Timestamp) -> str:
    """Where a release time (New York) falls: before_open, during, after_close, or unknown (midnight)."""
    local = moment.tz_convert("America/New_York") if moment.tzinfo is not None else moment
    hours = local.hour + local.minute / 60
    if hours == 0:
        return "unknown"
    if hours < MARKET_OPEN:
        return "before_open"
    return "after_close" if hours >= MARKET_CLOSE else "during"


def parse_yahoo(frame: pd.DataFrame | None, ticker: str) -> pd.DataFrame:
    """yfinance's earnings table to plain rows: ticker, datetime (New York), timing, EPS columns."""
    columns = ["ticker", "datetime", "timing", "eps_estimate", "reported_eps", "surprise_pct"]
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    moments = pd.DatetimeIndex(frame.index).tz_convert("America/New_York")
    return pd.DataFrame(
        {
            "ticker": ticker,
            "datetime": moments.strftime("%Y-%m-%d %H:%M"),
            "timing": [timing_of(m) for m in moments],
            "eps_estimate": frame.get("EPS Estimate"),
            "reported_eps": frame.get("Reported EPS"),
            "surprise_pct": frame.get("Surprise(%)"),
        }
    ).reset_index(drop=True)[columns]


def fetch_yahoo(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf

    parts = []
    for ticker in tickers:
        try:
            parts.append(parse_yahoo(yf.Ticker(ticker).get_earnings_dates(limit=YAHOO_LIMIT), ticker))
            print(f"  Yahoo {ticker}: {len(parts[-1])} dates", flush=True)
        except Exception as error:  # one bad ticker must not lose the others
            print(f"  Yahoo {ticker}: failed ({type(error).__name__}: {error})", flush=True)
        time.sleep(YAHOO_PAUSE_SECONDS)
    return pd.concat(parts, ignore_index=True).sort_values(["ticker", "datetime"]).reset_index(drop=True)


# ---------------------------------------------------------------- loading

def load_earnings(source: str) -> pd.DataFrame:
    """What ``python -m tsm.earnings`` saved: ``"sec"`` (every 8-K row) or ``"yahoo"``.

    Release dates come back as a ``date`` column (midnight), Yahoo's time of day in
    ``datetime`` and ``timing``. A date may be used up to 5 trading days before it
    happens, not earlier: that is how far ahead release dates are assumed known.
    """
    if source == "sec":
        frame = pd.read_csv(SEC_FILE, dtype={"items": str})
        return frame.assign(date=pd.to_datetime(frame["filing_date"]))
    if source == "yahoo":
        frame = pd.read_csv(YAHOO_FILE)
        moments = pd.to_datetime(frame["datetime"])
        return frame.assign(datetime=moments, date=moments.dt.normalize())
    raise ValueError(f"source must be 'sec' or 'yahoo', got {source!r}")


# ---------------------------------------------------------------- checks (pure functions)

def to_trading_day(dates: pd.Series | pd.DatetimeIndex, trading_days: pd.DatetimeIndex) -> np.ndarray:
    """Position in ``trading_days`` of the first trading day on or after each date (a Saturday -> Monday)."""
    return np.searchsorted(trading_days.values, pd.DatetimeIndex(dates).normalize().values, side="left")


def quarter_counts(dates: pd.Series, start: str, end: str) -> pd.Series:
    """Number of dates in each calendar quarter that lies wholly between ``start`` and ``end``."""
    first, last = pd.Period(start, "Q"), pd.Period(end, "Q")
    if pd.Timestamp(end) < last.end_time.normalize():
        last -= 1  # the last quarter is not over yet
    quarters = pd.period_range(first, last, freq="Q")
    counts = pd.Series(pd.DatetimeIndex(dates).to_period("Q")).value_counts()
    return counts.reindex(quarters, fill_value=0)


def agreement(dates: pd.Series, other: pd.Series, trading_days: pd.DatetimeIndex, tolerance: int = 1) -> float:
    """Share of ``dates`` with a date of ``other`` within ``tolerance`` trading days.

    Only over the period both cover, so a source that starts later is not
    counted as disagreeing. NaN when they do not overlap.
    """
    dates, other = pd.DatetimeIndex(dates), pd.DatetimeIndex(other)
    if dates.empty or other.empty:
        return float("nan")
    mine, theirs = to_trading_day(dates, trading_days), np.sort(to_trading_day(other, trading_days))
    # The overlap is widened by the tolerance, so a date just outside it can still match.
    low, high = max(mine.min(), theirs.min()) - tolerance, min(mine.max(), theirs.max()) + tolerance
    mine = mine[(mine >= low) & (mine <= high)]
    if mine.size == 0:
        return float("nan")
    nearest = np.abs(mine[:, None] - theirs[None, :]).min(axis=1)
    return float((nearest <= tolerance).mean())


def reaction(close: pd.Series, dates: pd.Series) -> dict[str, float]:
    """How much the stock moved around its release dates, against ordinary days.

    The reaction to a release on trading day t is the larger absolute log return
    of t and t+1 (before the open it shows on t, after the close on t+1). It is
    compared with the mean absolute return of all other days, and, fairly, with
    the same larger-of-two-days statistic on all other days, since the larger of
    two days is bigger than one day even on ordinary dates.
    """
    moves = np.abs(np.log(close / close.shift(1))).to_numpy()
    positions = to_trading_day(dates, close.index)
    positions = positions[(positions >= 1) & (positions < len(close) - 1)]
    pair = np.fmax(moves[:-1], moves[1:])  # pair[t] = larger of day t and day t + 1
    event = np.zeros(len(moves), dtype=bool)
    event[positions] = True
    event[positions + 1] = True
    others = ~event
    others[0] = False
    pair_others = others[:-1] & others[1:]
    return {
        "events": int(len(positions)),
        "event_move": float(np.nanmean(pair[positions])) if len(positions) else float("nan"),
        "ordinary_day": float(np.nanmean(moves[others])),
        "ordinary_pair": float(np.nanmean(pair[pair_others])),
    }


# ---------------------------------------------------------------- report

def main(argv: list[str] | None = None) -> None:
    from tsm.data import load_panel

    parser = argparse.ArgumentParser(prog="python -m tsm.earnings", description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="download both sources again")
    args = parser.parse_args(argv)

    tickers = covered_tickers()
    EARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    if args.refresh or not SEC_FILE.exists():
        print("Downloading SEC EDGAR 8-K filings...", flush=True)
        sec, unlisted = fetch_sec(tickers)
        sec.to_csv(SEC_FILE, index=False)
        print(f"Saved {len(sec)} 8-K rows; not in SEC's ticker list: {unlisted or 'none'}")
    if args.refresh or not YAHOO_FILE.exists():
        print("Downloading Yahoo earnings dates...", flush=True)
        fetch_yahoo(tickers).to_csv(YAHOO_FILE, index=False)

    panel = load_panel(cache_only=True)  # the frozen price cache
    trading_days = next(iter(panel.values())).index
    end = str(trading_days[-1].date())
    sec_dates = results_dates(load_earnings("sec"))
    yahoo = load_earnings("yahoo")
    window = lambda frame: frame[(frame["date"] >= WINDOW_START) & (frame["date"] <= end)]  # noqa: E731

    header = (
        "| Ticker | SEC n | Yahoo n | First | Last | SEC gaps | Yahoo gaps | SEC extra | Agree | Next scheduled "
        "| Timing (BO/AC/?) | Move SEC | Move Yahoo | Ordinary day | Ordinary pair |"
    )
    print("\n" + header + "\n" + "| --- " * 15 + "|")
    for ticker in tickers:
        s = window(sec_dates[sec_dates["ticker"] == ticker])["date"]
        y_all = yahoo[yahoo["ticker"] == ticker]
        y = window(y_all)["date"]
        both = pd.concat([s, y])
        upcoming = y_all.loc[y_all["date"] > pd.Timestamp(end), "datetime"]
        nxt = upcoming.min().strftime("%Y-%m-%d %H:%M") if len(upcoming) else "—"
        timing = window(y_all)["timing"].value_counts()
        sec_q, yahoo_q = quarter_counts(s, WINDOW_START, end), quarter_counts(y, WINDOW_START, end)
        close = panel[ticker]["close"]
        rs, ry = reaction(close, s), reaction(close, y)
        print(
            f"| {ticker} | {len(s)} | {len(y)} | {both.min().date() if len(both) else '—'} | "
            f"{both.max().date() if len(both) else '—'} | {int((sec_q == 0).sum())} | {int((yahoo_q == 0).sum())} | "
            f"{int((sec_q > 1).sum())} | {agreement(s, y, trading_days):.0%} | {nxt} | "
            f"{timing.get('before_open', 0)}/{timing.get('after_close', 0)}/"
            f"{timing.get('unknown', 0) + timing.get('during', 0)} | "
            f"{rs['event_move']:.4f} | {ry['event_move']:.4f} | {ry['ordinary_day']:.4f} | {ry['ordinary_pair']:.4f} |"
        )


if __name__ == "__main__":
    main()
