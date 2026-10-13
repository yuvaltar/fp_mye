"""The market map: which stocks move together, as adjacency matrices for a graph model.

Every matrix is ``(stocks x stocks)`` in the panel's ticker order, with a
self-loop on every stock and rows summing to 1, so multiplying it with a
per-stock signal averages each stock with its neighbours.

- ``correlation_adjacency`` learns the map from the last ``window`` days of
  returns, so it changes from one day to the next. With ``market_adjusted`` the
  market's move is removed first, so the map shows who moves together *beyond*
  the market rather than everyone being linked to everyone in a sell-off.
- ``sector_adjacency`` links stocks of the same GICS sector; it never changes.

Pure functions: no fitting and no state. The map for a date uses only returns up
to and including that date, so it is as safe as an input as any other feature.
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from tsm.config import MARKET_TICKER, SECTORS
from tsm.data import Panel

# Dates per block in the vectorised series: bounds memory at a few tens of MB.
CHUNK_DATES = 256


def _closes(panel: Panel, rows: int | None = None) -> np.ndarray:
    """``(rows, stocks)`` of closes, newest last; all rows when ``rows`` is None."""
    return np.column_stack(
        [frame["close"].to_numpy(dtype=float)[-rows if rows else None:] for frame in panel.values()]
    )


def _market_index(panel: Panel, market_adjusted: bool) -> int | None:
    if not market_adjusted:
        return None
    tickers = list(panel)
    if MARKET_TICKER not in tickers:
        raise ValueError(f"market_adjusted=True needs the market ticker {MARKET_TICKER} in the panel")
    return tickers.index(MARKET_TICKER)


def _adjacency(windows: np.ndarray, k: int, market: int | None) -> np.ndarray:
    """``(dates, stocks, window)`` of daily log returns -> ``(dates, stocks, stocks)`` adjacency.

    The one place the map is computed, for a single date and for the series alike.
    """
    windows = np.ascontiguousarray(windows, dtype=float)
    dates, n, _ = windows.shape
    x = windows - windows.mean(axis=-1, keepdims=True)
    if market is not None:
        # Residuals of a regression on the market (with intercept, absorbed by the demeaning).
        m = x[:, market : market + 1, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            beta = (x * m).sum(axis=-1, keepdims=True) / (m * m).sum(axis=-1, keepdims=True)
        x = x - beta * m
    norm = np.sqrt((x * x).sum(axis=-1))
    # A stock with a gap in its window (too little history) or a flat series has no
    # usable correlation: it keeps only its self-loop and is nobody's neighbour.
    usable = np.isfinite(norm) & (norm > 0)
    if market is not None:
        usable[:, market] = False  # its residual is zero by construction
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = (x @ x.transpose(0, 2, 1)) / (norm[:, :, None] * norm[:, None, :])

    # Candidates: positive correlations between two usable, different stocks.
    candidates = np.where(usable[:, :, None] & usable[:, None, :], corr, -np.inf)
    candidates[:, np.arange(n), np.arange(n)] = -np.inf
    candidates[~(candidates > 0)] = -np.inf
    keep = np.zeros((dates, n, n), dtype=bool)
    picks = min(k, n - 1)
    if picks > 0:
        top = np.argpartition(-candidates, picks - 1, axis=-1)[..., :picks]
        np.put_along_axis(keep, top, True, axis=-1)
        keep &= np.isfinite(candidates)  # fewer than k positive ones: keep only those

    weights = np.where(keep, corr, 0.0)
    weights = np.maximum(weights, weights.transpose(0, 2, 1))  # symmetric support
    weights[:, np.arange(n), np.arange(n)] = 1.0  # self-loop, the correlation of a stock with itself
    return weights / weights.sum(axis=-1, keepdims=True)


def correlation_adjacency(
    panel: Panel,
    window: int = 120,
    k: int = 5,
    market_adjusted: bool = True,
) -> np.ndarray:
    """``(stocks, stocks)`` correlation map for the panel's last row.

    Uses the daily log returns of the last ``window`` days up to and including
    that row, and nothing else. Each stock keeps its ``k`` most positively
    correlated other stocks (Pearson), weighted by that correlation; the support
    is made symmetric (a link kept by either stock is kept by both), a self-loop
    of weight 1 is added, and each row is divided by its sum.

    With ``market_adjusted`` each stock's returns are first replaced by the
    residuals of a regression on the market's returns over the same window; the
    market itself then gets only a self-loop. With fewer than ``window`` returns
    every stock gets only a self-loop.
    """
    market = _market_index(panel, market_adjusted)
    n = len(panel)
    if len(next(iter(panel.values()))) < window + 1:
        return np.eye(n)
    closes = _closes(panel, window + 1)
    returns = np.log(closes[1:] / closes[:-1])
    return _adjacency(returns.T[None], k, market)[0]


def correlation_adjacency_series(
    panel: Panel,
    window: int = 120,
    k: int = 5,
    market_adjusted: bool = True,
) -> np.ndarray:
    """``(days, stocks, stocks)``: row ``t`` is ``correlation_adjacency`` of the panel cut at ``t``.

    Vectorised over dates for training. Rows with fewer than ``window`` returns
    behind them are the identity (self-loops only).
    """
    market = _market_index(panel, market_adjusted)
    closes = _closes(panel)
    days, n = closes.shape
    out = np.broadcast_to(np.eye(n), (days, n, n)).copy()
    if days <= window:
        return out
    returns = np.log(closes[1:] / closes[:-1])  # returns[i] is the return of day i + 1
    windows = sliding_window_view(returns, window, axis=0)  # windows[j] ends on day j + window
    for start in range(0, len(windows), CHUNK_DATES):
        block = windows[start : start + CHUNK_DATES]
        out[window + start : window + start + len(block)] = _adjacency(block, k, market)
    return out


def sector_adjacency(tickers: list[str]) -> np.ndarray:
    """``(stocks, stocks)``: 1 between stocks of the same GICS sector, self-loops, rows summing to 1.

    Sectors come from ``config.SECTORS``; the market is its own group, so it is
    linked only to itself.
    """
    unknown = [t for t in tickers if t not in SECTORS]
    if unknown:
        raise ValueError(f"no sector in config.SECTORS for {', '.join(unknown)}")
    sectors = np.array([SECTORS[t] for t in tickers])
    same = (sectors[:, None] == sectors[None, :]).astype(float)
    return same / same.sum(axis=1, keepdims=True)
