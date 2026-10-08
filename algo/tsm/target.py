"""Realized volatility, in the units fixed by the contract.

Annualized 5-trading-day realized volatility as a decimal (0.24 = 24%):
sqrt(252/5 * sum of the 5 squared daily log returns).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tsm.config import HORIZON_DAYS, TRADING_DAYS_PER_YEAR


def log_returns(close: pd.Series) -> pd.Series:
    """Daily log returns; the first value is NaN."""
    return np.log(close / close.shift(1))


def realized_vol(close: pd.Series, window: int = HORIZON_DAYS) -> pd.Series:
    """Volatility realized over the ``window`` days ending on each date.

    Uses only data up to and including that date, so it is safe as a feature.
    """
    squared = log_returns(close) ** 2
    return np.sqrt(TRADING_DAYS_PER_YEAR / window * squared.rolling(window).sum())


def forward_realized_vol(close: pd.Series, horizon: int = HORIZON_DAYS) -> pd.Series:
    """Prediction target: volatility realized over the ``horizon`` days after each date.

    NaN for the last ``horizon`` dates, whose future is not known yet. This looks
    ahead by design: use it only as the value to predict, never as a feature.
    """
    return realized_vol(close, horizon).shift(-horizon)
