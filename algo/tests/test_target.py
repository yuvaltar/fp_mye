import numpy as np
import pandas as pd
import pytest

from tsm.target import forward_realized_vol, log_returns, realized_vol


def prices_from_returns(returns):
    dates = pd.bdate_range("2024-01-01", periods=len(returns) + 1)
    return pd.Series(100 * np.exp(np.concatenate([[0], np.cumsum(returns)])), index=dates)


@pytest.fixture
def close():
    rng = np.random.default_rng(0)
    return prices_from_returns(rng.normal(0, 0.02, 60))


def test_log_returns():
    close = prices_from_returns([0.01, -0.02])
    assert log_returns(close).iloc[1:].tolist() == pytest.approx([0.01, -0.02])
    assert np.isnan(log_returns(close).iloc[0])


def test_constant_return_gives_annualized_vol():
    # Every day moves 1%, so the annualized volatility is 1% * sqrt(252).
    close = prices_from_returns([0.01] * 10)
    assert realized_vol(close).iloc[-1] == pytest.approx(0.01 * np.sqrt(252))


def test_matches_contract_formula(close):
    last_five = log_returns(close).iloc[-5:]
    expected = np.sqrt(252 / 5 * (last_five**2).sum())
    assert realized_vol(close).iloc[-1] == pytest.approx(expected)


def test_first_values_are_nan(close):
    # 5 returns are needed, and the first return is itself undefined.
    vol = realized_vol(close)
    assert vol.iloc[:5].isna().all()
    assert vol.iloc[5:].notna().all()


def test_realized_vol_has_no_look_ahead(close):
    cut = close.iloc[:40]
    pd.testing.assert_series_equal(realized_vol(cut), realized_vol(close).iloc[:40])


def test_forward_is_the_future_window(close):
    forward = forward_realized_vol(close)
    trailing = realized_vol(close)
    assert forward.iloc[10] == pytest.approx(trailing.iloc[15])
    future_returns = log_returns(close).iloc[11:16]
    assert forward.iloc[10] == pytest.approx(np.sqrt(252 / 5 * (future_returns**2).sum()))


def test_forward_unknown_for_last_five_days(close):
    forward = forward_realized_vol(close)
    assert forward.iloc[-5:].isna().all()
    assert forward.iloc[5:-5].notna().all()
