import numpy as np
import pandas as pd
import pytest

TICKERS = ["AAA", "BBB", "SPY"]


def make_panel(n_days=420, seed=0):
    """Synthetic prices with volatility that changes over time, for three tickers."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2017-01-02", periods=n_days)
    panel = {}
    for i, ticker in enumerate(TICKERS):
        vol = 0.01 * np.exp(np.cumsum(rng.normal(0, 0.05, n_days)) * 0.3) * (1 + 0.3 * i)
        returns = rng.normal(0, 1, n_days) * vol
        close = 100 * np.exp(np.cumsum(returns))
        open_ = close * np.exp(rng.normal(0, 0.003, n_days))
        high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.004, n_days)))
        low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.004, n_days)))
        volume = rng.integers(1_000_000, 5_000_000, n_days).astype(float)
        panel[ticker] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=dates.rename("date"),
        )
    return panel


@pytest.fixture(autouse=True)
def market_ticker(monkeypatch):
    # The synthetic panel has no real SPY; its third ticker plays the market.
    import tsm.skills.weak_signals as weak_signals

    monkeypatch.setattr(weak_signals, "MARKET_TICKER", "SPY")


@pytest.fixture
def panel():
    return make_panel()


def corrupt_after(panel, position, seed=99):
    """Replace every price after ``position`` with garbage. A leak-free engine cannot notice."""
    rng = np.random.default_rng(seed)
    out = {}
    for ticker, frame in panel.items():
        frame = frame.copy()
        n = len(frame) - position - 1
        frame.iloc[position + 1:] = frame.iloc[position + 1:].to_numpy() * rng.uniform(0.2, 5.0, (n, 1))
        out[ticker] = frame
    return out
