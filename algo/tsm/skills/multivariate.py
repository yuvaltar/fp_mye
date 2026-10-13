"""multivariate: iTransformer (neuralforecast), trained on all tickers jointly.

Reads the recent volatility of every ticker at once and forecasts all of them
together, so it can pick up moves that spread from one stock to the others.

The model forecasts the daily series "log of the volatility of the last 5
days". Its value 5 days ahead is exactly the quantity to predict.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd

from tsm.config import HORIZON_DAYS
from tsm.data import Panel
from tsm.skills.base import MIN_VOL, TemporalSkill
from tsm.target import realized_vol


def _long_frame(panel: Panel) -> pd.DataFrame:
    """neuralforecast's input format: one row per (ticker, day), days numbered from 0."""
    parts = []
    for ticker, frame in panel.items():
        y = np.log(realized_vol(frame["close"], HORIZON_DAYS).clip(lower=MIN_VOL))
        parts.append(pd.DataFrame({"unique_id": ticker, "ds": np.arange(len(y)), "y": y.to_numpy()}))
    return pd.concat(parts).dropna().reset_index(drop=True)


class MultivariateSkill(TemporalSkill):
    name = "multivariate"
    horizon = "medium"
    refit_every_days = 125

    def __init__(self, input_size: int = 44, hidden_size: int = 64, max_steps: int = 300) -> None:
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.max_steps = max_steps
        self.nf_ = None

    def fit(self, panel: Panel) -> None:
        # Imported here: neuralforecast takes seconds to import and the other skills do not need it.
        from neuralforecast import NeuralForecast
        from neuralforecast.models import iTransformer

        for noisy in ("pytorch_lightning", "lightning", "lightning.pytorch", "lightning_fabric"):
            logging.getLogger(noisy).setLevel(logging.ERROR)
        model = iTransformer(
            h=HORIZON_DAYS,
            input_size=self.input_size,
            n_series=len(panel),
            hidden_size=self.hidden_size,
            n_heads=4,
            e_layers=2,
            d_ff=2 * self.hidden_size,
            max_steps=self.max_steps,
            batch_size=32,
            learning_rate=1e-3,
            scaler_type="standard",
            random_seed=0,
            accelerator="cpu",
            enable_progress_bar=False,
            enable_model_summary=False,
            enable_checkpointing=False,
            logger=False,
        )
        self.nf_ = NeuralForecast(models=[model], freq=1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.nf_.fit(_long_frame(panel))

    def predict(self, panel: Panel) -> dict[str, float]:
        recent = {ticker: frame.iloc[-(self.input_size + 2 * HORIZON_DAYS):] for ticker, frame in panel.items()}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            forecast = self.nf_.predict(df=_long_frame(recent))
        last_step = forecast.groupby("unique_id")["iTransformer"].last()
        return {ticker: max(float(np.exp(last_step[ticker])), MIN_VOL) for ticker in panel}
