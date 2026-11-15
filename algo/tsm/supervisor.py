"""The supervisor: the "market" that decides how much to trust each skill.

On each date it looks at how wrong every skill was on its most recent
predictions whose outcome is already known, and gives more weight to the skills
that were less wrong (softmax over minus the average QLIKE).

Two modes:

- ``per_ticker`` (until Step 15): each ticker judges the skills on its own past
  predictions only. A few dozen QLIKE values per skill are very noisy, so the
  tuned temperature came out high and the weights near-equal.
- ``pooled`` (Step 15): on each date every skill is judged on the predictions of
  all tickers together, and every ticker gets the same weights. 52 times more
  evidence per date, so the weights can afford to differ.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tsm.config import HORIZON_DAYS
from tsm.skills.base import TemporalSkill
from tsm.skills.itransformer import ITransformerCommitteeSkill
from tsm.skills.regime import RegimeSkill
from tsm.skills.short_term import ShortTermSkill
from tsm.skills.stgnn import STGNNCommitteeSkill
from tsm.skills.weak_signals import WeakSignalsSkill


def build_skills() -> list[TemporalSkill]:
    """The skill registry: every skill listed here takes part in the market.

    ``itransformer`` replaced ``multivariate`` (neuralforecast) in Step 11; that
    module is kept, outside the registry, so older results stay reproducible.
    ``stgnn`` joined as the fifth skill after docs/stgnn-skill-results.md.
    """
    return [ShortTermSkill(), RegimeSkill(), WeakSignalsSkill(), ITransformerCommitteeSkill(), STGNNCommitteeSkill()]


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


MODES = ("per_ticker", "pooled")


def pooled_weights(
    predictions: pd.DataFrame,
    realized: pd.Series,
    positions: pd.Series,
    window: int,
    temperature: float,
    horizon: int = HORIZON_DAYS,
) -> pd.DataFrame:
    """One weight per skill and per evaluation date, judged on all tickers together.

    ``predictions``: one row per (date, ticker), one column per skill.
    ``realized`` and ``positions``: aligned with it.

    For the date at position p, a skill's score is its mean QLIKE over every
    ticker's predictions made at the last ``window`` evaluation dates whose
    outcome is known on p (position <= p - ``horizon``, the rule ``combine``
    uses). Rows with an unknown outcome do not count. With no known outcome
    yet, the weights are equal.

    Returns a frame indexed by position (sorted), one column per skill.
    """
    names = list(predictions.columns)
    losses = qlike(realized.to_numpy(dtype=float)[:, None], predictions.to_numpy(dtype=float))
    valid = np.isfinite(losses).all(axis=1)
    table = pd.DataFrame(np.where(valid[:, None], losses, 0.0), columns=names)
    table["count"] = valid.astype(float)
    table["position"] = np.asarray(positions)
    dates = np.sort(table["position"].unique())
    per_date = table.groupby("position")[names + ["count"]].sum().reindex(dates, fill_value=0.0)
    cumulative = np.vstack([np.zeros((1, len(names) + 1)), per_date.to_numpy().cumsum(axis=0)])
    hi = np.searchsorted(dates, dates - horizon, side="right")
    lo = np.maximum(0, hi - window)
    totals = cumulative[hi] - cumulative[lo]
    counts = totals[:, -1]
    weights = np.full((len(dates), len(names)), 1.0 / len(names))
    for i in np.flatnonzero(counts > 0):
        weights[i] = softmax_weights(totals[i, :-1] / counts[i], temperature)
    return pd.DataFrame(weights, index=dates, columns=names)


@dataclass
class Supervisor:
    window: int = 20  # number of past evaluation dates (with known outcome) used to judge a skill
    temperature: float = 0.1
    mode: str = "per_ticker"  # or "pooled": judge every skill on all tickers together

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown supervisor mode {self.mode!r}; expected one of {MODES}")

    def combine(
        self,
        predictions: pd.DataFrame,
        realized: pd.Series,
        positions: np.ndarray,
        horizon: int = HORIZON_DAYS,
        weights: np.ndarray | None = None,
    ) -> pd.DataFrame:
        """Weights, combined prediction and confidence for one ticker.

        ``predictions``: one row per evaluation date (oldest first), one column per skill.
        ``realized``: the volatility that followed each date (NaN if not known yet).
        ``positions``: row number of each evaluation date in the price history.
        ``weights``: optional, one row per evaluation date; given (pooled mode),
        they replace the ticker's own softmax. Confidence is always the ticker's own.

        The outcome of a prediction made at position p is known from position
        p + horizon on. A date only ever uses outcomes known on that date.
        """
        preds = predictions.to_numpy(dtype=float)
        n, k = preds.shape
        losses = qlike(realized.to_numpy(dtype=float)[:, None], preds)
        given = weights is not None
        weights = np.array(weights, dtype=float) if given else np.full((n, k), 1.0 / k)
        combined = np.empty(n)
        confidence = np.full(n, 0.5)
        own_loss = np.full(n, np.nan)
        known = np.searchsorted(positions, positions - horizon, side="right")
        for i in range(n):
            lo, hi = max(0, known[i] - self.window), known[i]
            if hi > lo:
                if not given:
                    weights[i] = softmax_weights(losses[lo:hi].mean(axis=0), self.temperature)
                confidence[i] = float(np.exp(-own_loss[lo:hi].mean()))
            combined[i] = weights[i] @ preds[i]
            own_loss[i] = qlike(realized.iloc[i], combined[i])
        out = pd.DataFrame(weights, index=predictions.index, columns=[f"w_{c}" for c in predictions.columns])
        out["supervisor"] = combined
        out["confidence"] = confidence
        return out
