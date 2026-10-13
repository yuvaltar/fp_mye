"""itransformer: our own iTransformer, averaged over three seeds.

The plain-PyTorch model of ``tsm.models.itransformer`` in its best tested form,
``itransformer_path_feats`` in docs/experiments.md: each stock's last 44 days in
4 channels (log 5-day volatility, daily return, high-low range, volume) form one
token, attention runs across stocks, and the head predicts the whole 1..5-day
path, trained with MAE. Three copies with seeds 0, 1 and 2 are fitted on the same
panel and their predictions averaged, so the committee does not depend on a
lucky seed.

It replaces ``multivariate`` (the neuralforecast version), which stays in
``tsm/skills/multivariate.py`` so older results can be reproduced.
"""
from __future__ import annotations

import numpy as np

from tsm.data import Panel
from tsm.models.itransformer import CANDIDATES, ITransformerSkill
from tsm.skills.base import TemporalSkill

SEEDS = (0, 1, 2)
CONFIGURATION = "itransformer_path_feats"


class ITransformerCommitteeSkill(TemporalSkill):
    name = "itransformer"
    horizon = "medium"
    refit_every_days = 125

    def __init__(self, seeds: tuple[int, ...] = SEEDS, **overrides) -> None:
        """``overrides`` change the model's settings (the tests shrink the network with them)."""
        settings = {key: value for key, value in CANDIDATES[CONFIGURATION].items() if key != "name"}
        self.members = [ITransformerSkill(seed=seed, **{**settings, **overrides}) for seed in seeds]

    def fit(self, panel: Panel) -> None:
        # Each member seeds torch, numpy and random itself, so the order of fitting does not matter.
        for member in self.members:
            member.fit(panel)

    def predict(self, panel: Panel) -> dict[str, float]:
        predictions = [member.predict(panel) for member in self.members]
        return {ticker: float(np.mean([p[ticker] for p in predictions])) for ticker in panel}
