"""short_term: HAR-RV, the standard volatility benchmark.

Predicts next-5-day volatility as a linear mix of the volatility of the last
day, the last 5 days and the last 22 days. One regression per ticker.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tsm.config import HORIZON_DAYS
from tsm.data import Panel
from tsm.skills.base import MIN_VOL, TemporalSkill
from tsm.target import forward_realized_vol, realized_vol

WINDOWS = (1, 5, 22)


def har_features(close: pd.Series) -> pd.DataFrame:
    """Volatility over the last 1, 5 and 22 days, each using data up to its own date."""
    return pd.DataFrame({f"rv_{w}": realized_vol(close, w) for w in WINDOWS})


class ShortTermSkill(TemporalSkill):
    name = "short_term"
    horizon = "short"
    refit_every_days = 5

    def __init__(self) -> None:
        self.coef_: dict[str, np.ndarray] = {}

    def fit(self, panel: Panel) -> None:
        for ticker, frame in panel.items():
            x = har_features(frame["close"])
            y = forward_realized_vol(frame["close"], HORIZON_DAYS)
            known = x.notna().all(axis=1) & y.notna()
            design = np.column_stack([np.ones(known.sum()), x[known].to_numpy()])
            self.coef_[ticker], *_ = np.linalg.lstsq(design, y[known].to_numpy(), rcond=None)

    def predict(self, panel: Panel) -> dict[str, float]:
        out = {}
        for ticker, frame in panel.items():
            last = har_features(frame["close"].iloc[-(max(WINDOWS) + 2):]).iloc[-1].to_numpy()
            out[ticker] = max(float(self.coef_[ticker] @ np.concatenate([[1.0], last])), MIN_VOL)
        return out
