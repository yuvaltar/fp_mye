"""weak_signals: gradient boosting on signals other than past volatility.

Uses abnormal trading volume, the daily high-low range, overnight opening
gaps and the rolling correlation with the market (SPY). One model for all
tickers, so each ticker learns from the others.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from tsm.config import HORIZON_DAYS, MARKET_TICKER
from tsm.data import Panel
from tsm.skills.base import MIN_VOL, TemporalSkill
from tsm.target import forward_realized_vol, log_returns

# Rows of history needed to compute the features of the last row.
LOOKBACK = 60


def weak_features(frame: pd.DataFrame, market_close: pd.Series) -> pd.DataFrame:
    """Features of each date, computed from that date and earlier only."""
    volume = frame["volume"].clip(lower=1)
    abnormal_volume = np.log(volume / volume.shift(1).rolling(20).mean())
    day_range = np.log(frame["high"] / frame["low"])
    gap = np.log(frame["open"] / frame["close"].shift(1)).abs()
    returns = log_returns(frame["close"])
    market_corr = returns.rolling(22).corr(log_returns(market_close))
    return pd.DataFrame(
        {
            "abnormal_volume_1": abnormal_volume,
            "abnormal_volume_5": abnormal_volume.rolling(5).mean(),
            "range_5": day_range.rolling(5).mean(),
            "range_22": day_range.rolling(22).mean(),
            "gap_5": gap.rolling(5).mean(),
            "gap_22": gap.rolling(22).mean(),
            "market_corr_22": market_corr.clip(-1, 1),
        }
    )


class WeakSignalsSkill(TemporalSkill):
    name = "weak_signals"
    horizon = "short"
    refit_every_days = 20

    def __init__(self) -> None:
        self.model_: HistGradientBoostingRegressor | None = None

    def fit(self, panel: Panel) -> None:
        market = panel[MARKET_TICKER]["close"]
        xs, ys = [], []
        for frame in panel.values():
            x = weak_features(frame, market)
            y = np.log(forward_realized_vol(frame["close"], HORIZON_DAYS))
            known = x.notna().all(axis=1) & y.notna()
            xs.append(x[known])
            ys.append(y[known])
        self.model_ = HistGradientBoostingRegressor(
            max_depth=3, max_iter=150, learning_rate=0.05, random_state=0
        ).fit(pd.concat(xs), pd.concat(ys))

    def predict(self, panel: Panel) -> dict[str, float]:
        market = panel[MARKET_TICKER]["close"].iloc[-LOOKBACK:]
        rows = pd.concat(
            [weak_features(frame.iloc[-LOOKBACK:], market).iloc[[-1]] for frame in panel.values()]
        )
        predicted = np.exp(self.model_.predict(rows))
        return {ticker: max(float(v), MIN_VOL) for ticker, v in zip(panel, predicted)}
