"""The market map: shape and normalisation, the planted structure, and no look-ahead."""
import numpy as np
import pandas as pd
import pytest

from tsm.config import MARKET_TICKER, SECTORS, TICKERS
from tsm.data import truncate_panel
from tsm.models.graph import correlation_adjacency, correlation_adjacency_series, sector_adjacency

from tests.conftest import corrupt_after

# Two hidden sectors of four stocks plus the market, in this panel order.
GROUPS = {"T": ["T1", "T2", "T3", "T4"], "E": ["E1", "E2", "E3", "E4"]}
NAMES = [*GROUPS["T"], *GROUPS["E"], MARKET_TICKER]
WINDOW = 120
CUT = 220  # prices after this row get corrupted


def factor_panel(n_days: int = 300, seed: int = 0) -> dict[str, pd.DataFrame]:
    """Each stock = market + its sector's factor + noise; the market ticker = market alone.

    Correlations: same sector ~0.82, with the market ~0.71, across sectors ~0.5,
    so the right neighbours are known in advance.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2017-01-02", periods=n_days, name="date")
    market = rng.normal(0, 0.010, n_days)
    factors = {group: rng.normal(0, 0.008, n_days) for group in GROUPS}
    panel = {}
    for name in NAMES:
        group = name[0] if name != MARKET_TICKER else None
        returns = market if group is None else market + factors[group] + rng.normal(0, 0.006, n_days)
        close = 100 * np.exp(np.cumsum(returns))
        panel[name] = pd.DataFrame(
            {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6},
            index=dates,
        )
    return panel


@pytest.fixture
def market_panel():
    return factor_panel()


def support(matrix: np.ndarray) -> np.ndarray:
    return matrix > 0


@pytest.mark.parametrize("market_adjusted", [True, False])
def test_shape_rows_symmetry_and_self_loops(market_panel, market_adjusted):
    a = correlation_adjacency(market_panel, window=WINDOW, k=3, market_adjusted=market_adjusted)
    assert a.shape == (len(NAMES), len(NAMES))
    np.testing.assert_allclose(a.sum(axis=1), 1.0)
    assert (a >= 0).all()
    np.testing.assert_array_equal(support(a), support(a).T)
    assert (np.diag(a) > 0).all()


def test_neighbours_are_the_planted_sectors(market_panel):
    a = correlation_adjacency(market_panel, window=WINDOW, k=3, market_adjusted=True)
    for group in GROUPS.values():
        for name in group:
            linked = {NAMES[j] for j in np.flatnonzero(a[NAMES.index(name)])}
            assert linked == set(group), (name, linked)


def test_market_gets_only_a_self_loop_when_adjusted(market_panel):
    m = NAMES.index(MARKET_TICKER)
    adjusted = correlation_adjacency(market_panel, window=WINDOW, k=5, market_adjusted=True)
    np.testing.assert_array_equal(adjusted[m], np.eye(len(NAMES))[m])
    np.testing.assert_array_equal(np.delete(adjusted[:, m], m), 0.0)
    # Without the adjustment the market is everybody's close relative, so the switch matters.
    raw = correlation_adjacency(market_panel, window=WINDOW, k=5, market_adjusted=False)
    assert np.count_nonzero(raw[m]) > 1


def test_too_little_history_gives_self_loops_only(market_panel):
    short = truncate_panel(market_panel, WINDOW - 1)  # WINDOW rows = WINDOW - 1 returns
    np.testing.assert_array_equal(correlation_adjacency(short, window=WINDOW), np.eye(len(NAMES)))
    series = correlation_adjacency_series(market_panel, window=WINDOW)
    np.testing.assert_array_equal(series[:WINDOW], np.broadcast_to(np.eye(len(NAMES)), (WINDOW, len(NAMES), len(NAMES))))
    assert not np.array_equal(series[WINDOW], np.eye(len(NAMES)))

    # One stock with a gap inside the window: only it falls back to a self-loop.
    gappy = {name: frame.copy() for name, frame in market_panel.items()}
    gappy["T1"].iloc[-10, gappy["T1"].columns.get_loc("close")] = np.nan
    a = correlation_adjacency(gappy, window=WINDOW, k=3)
    i = NAMES.index("T1")
    np.testing.assert_array_equal(a[i], np.eye(len(NAMES))[i])
    np.testing.assert_array_equal(np.delete(a[:, i], i), 0.0)
    assert np.count_nonzero(a[NAMES.index("T2")]) > 1


@pytest.mark.parametrize("market_adjusted", [True, False])
def test_series_matches_the_single_date_function(market_panel, market_adjusted):
    series = correlation_adjacency_series(market_panel, window=WINDOW, k=3, market_adjusted=market_adjusted)
    assert series.shape == (len(next(iter(market_panel.values()))), len(NAMES), len(NAMES))
    for position in (WINDOW - 1, WINDOW, WINDOW + 1, 200, 299):
        single = correlation_adjacency(
            truncate_panel(market_panel, position), window=WINDOW, k=3, market_adjusted=market_adjusted
        )
        np.testing.assert_array_equal(support(series[position]), support(single))
        np.testing.assert_allclose(series[position], single, rtol=0, atol=1e-12)


@pytest.mark.parametrize("market_adjusted", [True, False])
def test_no_future_leakage(market_panel, market_adjusted):
    """Garbage prices after the as-of row must not move any matrix up to that row."""
    corrupted = corrupt_after(market_panel, CUT)
    clean = correlation_adjacency_series(market_panel, window=WINDOW, k=3, market_adjusted=market_adjusted)
    dirty = correlation_adjacency_series(corrupted, window=WINDOW, k=3, market_adjusted=market_adjusted)
    np.testing.assert_array_equal(dirty[: CUT + 1], clean[: CUT + 1])
    assert not np.allclose(dirty[CUT + 1 :], clean[CUT + 1 :]), "the corruption should be visible afterwards"
    for position in (CUT - 30, CUT):
        np.testing.assert_array_equal(
            correlation_adjacency(truncate_panel(corrupted, position), window=WINDOW, k=3, market_adjusted=market_adjusted),
            correlation_adjacency(truncate_panel(market_panel, position), window=WINDOW, k=3, market_adjusted=market_adjusted),
        )


def test_market_adjustment_needs_the_market(market_panel):
    without = {name: frame for name, frame in market_panel.items() if name != MARKET_TICKER}
    with pytest.raises(ValueError, match=MARKET_TICKER):
        correlation_adjacency(without, market_adjusted=True)
    assert correlation_adjacency(without, window=WINDOW, market_adjusted=False).shape == (8, 8)


def test_every_ticker_has_a_sector():
    assert set(SECTORS) == set(TICKERS)
    assert SECTORS["TEVA"] == "Health Care"
    assert [t for t, s in SECTORS.items() if s == SECTORS[MARKET_TICKER]] == [MARKET_TICKER]


def test_sector_adjacency():
    tickers = list(TICKERS)
    a = sector_adjacency(tickers)
    assert a.shape == (len(tickers), len(tickers))
    np.testing.assert_allclose(a.sum(axis=1), 1.0)
    np.testing.assert_array_equal(a, a.T)  # sectors are symmetric, and within a sector rows are equal
    assert (np.diag(a) > 0).all()
    at = tickers.index
    assert a[at("AAPL"), at("MSFT")] > 0 and a[at("AAPL"), at("XOM")] == 0
    assert a[at("TEVA"), at("LLY")] == pytest.approx(1 / 6)  # Health Care has six members
    np.testing.assert_array_equal(a[at(MARKET_TICKER)], np.eye(len(tickers))[at(MARKET_TICKER)])
    with pytest.raises(ValueError, match="NOPE"):
        sector_adjacency(["AAPL", "NOPE"])
