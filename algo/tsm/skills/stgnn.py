"""stgnn: our ST-GNN predictor, averaged over three seeds.

The model of ``tsm.models.stgnn_skill`` in the form that earned its place
(``stgnn_skill_corr``, docs/stgnn-skill-results.md): a GRU reads each stock's
last 44 days in 4 channels (log 5-day volatility, daily return, high-low range,
volume), one graph layer passes that state between neighbours on the
market-adjusted correlation map, and the head predicts the 1..5-day path of log
volatility, trained with MAE. Three copies with seeds 0, 1 and 2 are fitted on
the same panel and their predictions averaged, as for ``itransformer``.

Alone it is weaker than the other skills; it joined because its errors differ
from theirs, so the committee is better with it than without it.
"""
from __future__ import annotations

import numpy as np

from tsm.data import Panel
from tsm.models.stgnn_skill import CANDIDATES, STGNNSkill
from tsm.skills.base import TemporalSkill

SEEDS = (0, 1, 2)
CONFIGURATION = "stgnn_skill_corr"


class STGNNCommitteeSkill(TemporalSkill):
    name = "stgnn"
    horizon = "short"
    refit_every_days = 125

    def __init__(self, seeds: tuple[int, ...] = SEEDS, **overrides) -> None:
        """``overrides`` change the model's settings (the tests shrink the network with them)."""
        settings = {**CANDIDATES[CONFIGURATION], **overrides}
        self.members = [STGNNSkill(seed=seed, **settings) for seed in seeds]

    def fit(self, panel: Panel) -> None:
        # Each member seeds torch, numpy and random itself, so the order of fitting does not matter.
        for member in self.members:
            member.fit(panel)

    def predict(self, panel: Panel) -> dict[str, float]:
        predictions = [member.predict(panel) for member in self.members]
        return {ticker: float(np.mean([p[ticker] for p in predictions])) for ticker in panel}
