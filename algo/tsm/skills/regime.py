"""regime: GARCH(1,1).

Models volatility as a slowly changing regime: calm days follow calm days,
turbulent days follow turbulent days, and volatility drifts back to its
long-run level. One model per ticker, fitted with the arch library.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from arch import arch_model

from tsm.config import HORIZON_DAYS, TRADING_DAYS_PER_YEAR
from tsm.data import Panel
from tsm.skills.base import MIN_VOL, TemporalSkill
from tsm.target import log_returns


def _model(close: pd.Series):
    # Returns in percent: the optimizer is unstable on very small numbers.
    returns = 100 * log_returns(close).dropna()
    return arch_model(returns, mean="Zero", vol="GARCH", p=1, q=1, rescale=False)


class RegimeSkill(TemporalSkill):
    name = "regime"
    horizon = "long"
    refit_every_days = 20

    def __init__(self) -> None:
        self.params_: dict[str, pd.Series] = {}

    def fit(self, panel: Panel) -> None:
        for ticker, frame in panel.items():
            self.params_[ticker] = _model(frame["close"]).fit(disp="off", show_warning=False).params

    def predict(self, panel: Panel) -> dict[str, float]:
        out = {}
        for ticker, frame in panel.items():
            # Parameters stay those of the last fit; the volatility state is updated with every return seen so far.
            fixed = _model(frame["close"]).fix(self.params_[ticker])
            daily_variance = fixed.forecast(horizon=HORIZON_DAYS).variance.iloc[-1].to_numpy()
            vol = np.sqrt(TRADING_DAYS_PER_YEAR / HORIZON_DAYS * daily_variance.sum()) / 100
            out[ticker] = max(float(vol), MIN_VOL)
        return out
