"""The supervisor: the "market" that decides how much to trust each skill.

For each ticker and each date it looks at how wrong every skill was on its
most recent predictions whose outcome is already known, and gives more weight
to the skills that were less wrong (softmax over minus the average QLIKE).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tsm.config import HORIZON_DAYS
from tsm.skills.base import TemporalSkill
from tsm.skills.multivariate import MultivariateSkill
from tsm.skills.regime import RegimeSkill
from tsm.skills.short_term import ShortTermSkill
from tsm.skills.weak_signals import WeakSignalsSkill


def build_skills() -> list[TemporalSkill]:
    """The skill registry: every skill listed here takes part in the market."""
    return [ShortTermSkill(), RegimeSkill(), WeakSignalsSkill(), MultivariateSkill()]


def qlike(realized_vol, predicted_vol):
    """QLIKE loss, the standard error measure for volatility forecasts (0 = perfect).

    It works on variances and punishes under-prediction more than over-prediction.
    """
    ratio = np.square(realized_vol) / np.square(predicted_vol)
    return ratio - np.log(ratio) - 1


def softmax_weights(losses: np.ndarray, temperature: float) -> np.ndarray:
    """Weights summing to 1, larger for smaller losses. A low temperature concentrates the weight."""
    scores = -np.asarray(losses, dtype=float) / temperature
    weights = np.exp(scores - scores.max())
    return weights / weights.sum()


@dataclass
class Supervisor:
    window: int = 20  # number of past predictions (with known outcome) used to judge a skill
    temperature: float = 0.1

    def combine(
        self,
        predictions: pd.DataFrame,
        realized: pd.Series,
        positions: np.ndarray,
        horizon: int = HORIZON_DAYS,
    ) -> pd.DataFrame:
        """Weights, combined prediction and confidence for one ticker.

        ``predictions``: one row per evaluation date (oldest first), one column per skill.
        ``realized``: the volatility that followed each date (NaN if not known yet).
        ``positions``: row number of each evaluation date in the price history.

        The outcome of a prediction made at position p is known from position
        p + horizon on. A date only ever uses outcomes known on that date.
        """
        preds = predictions.to_numpy(dtype=float)
        n, k = preds.shape
        losses = qlike(realized.to_numpy(dtype=float)[:, None], preds)
        weights = np.full((n, k), 1.0 / k)
        combined = np.empty(n)
        confidence = np.full(n, 0.5)
        own_loss = np.full(n, np.nan)
        known = np.searchsorted(positions, positions - horizon, side="right")
        for i in range(n):
            lo, hi = max(0, known[i] - self.window), known[i]
            if hi > lo:
                weights[i] = softmax_weights(losses[lo:hi].mean(axis=0), self.temperature)
                confidence[i] = float(np.exp(-own_loss[lo:hi].mean()))
            combined[i] = weights[i] @ preds[i]
            own_loss[i] = qlike(realized.iloc[i], combined[i])
        out = pd.DataFrame(weights, index=predictions.index, columns=[f"w_{c}" for c in predictions.columns])
        out["supervisor"] = combined
        out["confidence"] = confidence
        return out
