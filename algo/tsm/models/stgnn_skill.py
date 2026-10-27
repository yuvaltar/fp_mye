"""ST-GNN predictor: a candidate fifth skill that forecasts volatility itself.

Unlike the ST-GNN supervisor (``tsm.models.stgnn``), which only weights the
skills, this one predicts the 5-day volatility from prices, like the other skills:

- **temporal:** a GRU reads each stock's last ``input_size`` days in the same four
  channels as ``itransformer_path_feats`` (log 5-day vol, return, range, volume),
  standardised with the means and spreads of the training window;
- **graph:** one layer ``h + g·A·h·W`` passes that state between neighbours on the
  market map only (the iTransformer lets every stock attend to every other one);
  ``g`` starts at 0, so the graph is off until it lowers the loss;
- **head:** the whole 1..5-day path of log volatility, as a change from today's,
  trained with MAE like ``path_feats``; the forecast is the 5th step.

It is a candidate (``python -m tsm.stgnn_skill``), not a committee member: it joins
``build_skills`` only through the ``add-temporal-skill`` procedure, if the committee
with it beats the committee without it.
"""
from __future__ import annotations

import random

import numpy as np
import torch
from torch import nn

from tsm.config import HORIZON_DAYS
from tsm.data import Panel
from tsm.models.graph import correlation_adjacency, correlation_adjacency_series
from tsm.models.itransformer import (
    GATE_LEARNING_RATE,
    _shuffled,
    feature_series,
    feature_tail,
    training_positions,
)
from tsm.skills.base import MIN_VOL, TemporalSkill

GRAPH_SOURCES = ("none", "corr", "shuffled")


class STGNNPredictor(nn.Module):
    def __init__(self, n_channels: int, hidden: int, graph: bool):
        super().__init__()
        self.gru = nn.GRU(n_channels, hidden, batch_first=True)
        self.head = nn.Linear(hidden, HORIZON_DAYS)
        # Built last, so the GRU and the head start from the same draw with or without a graph.
        self.graph_w = nn.Linear(hidden, hidden, bias=False) if graph else None
        self.gate = nn.Parameter(torch.zeros(1)) if graph else None

    def forward(self, x: torch.Tensor, adjacency: torch.Tensor | None = None) -> torch.Tensor:
        """``x`` (B, N, L, C) standardised -> (B, N, 5) change of log vol from the last day."""
        b, n, length, c = x.shape
        _, h = self.gru(x.reshape(b * n, length, c))
        state = h[-1].reshape(b, n, -1)
        if self.graph_w is not None:
            state = state + self.gate * (adjacency @ self.graph_w(state))
        return self.head(state)


class STGNNSkill(TemporalSkill):
    horizon = "short"
    refit_every_days = 125  # as the iTransformer

    def __init__(
        self,
        graph_source: str = "corr",
        name: str | None = None,
        input_size: int = 44,
        hidden: int = 32,
        max_steps: int = 300,
        batch_dates: int = 32,
        learning_rate: float = 1e-3,
        seed: int = 0,
    ) -> None:
        if graph_source not in GRAPH_SOURCES:
            raise ValueError(f"graph_source must be one of {GRAPH_SOURCES}, got {graph_source!r}")
        self.graph_source = graph_source
        self.name = name if name is not None else f"stgnn_skill_{graph_source}"
        self.input_size = input_size
        self.hidden = hidden
        self.max_steps = max_steps
        self.batch_dates = batch_dates
        self.learning_rate = learning_rate
        self.seed = seed
        self.model_: STGNNPredictor | None = None
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.gate_history_: list[dict] = []

    @property
    def graph(self) -> bool:
        return self.graph_source != "none"

    def _build(self) -> STGNNPredictor:
        random.seed(self.seed)
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)
        return STGNNPredictor(4, self.hidden, self.graph)

    def _adjacency_series(self, panel: Panel) -> np.ndarray:
        series = correlation_adjacency_series(panel)
        return _shuffled(series) if self.graph_source == "shuffled" else series

    def _adjacency_now(self, panel: Panel) -> np.ndarray:
        matrix = correlation_adjacency(panel)
        return _shuffled(matrix) if self.graph_source == "shuffled" else matrix

    def _standardise(self, windows: np.ndarray) -> torch.Tensor:
        return torch.as_tensor((windows - self.mean_) / self.std_, dtype=torch.float32)

    def fit(self, panel: Panel) -> None:
        model = self._build()
        inputs = feature_series(panel)  # (days, N, 4), day t uses data up to t only
        vol = inputs[..., 0]
        positions = training_positions(inputs.reshape(len(inputs), -1), self.input_size, HORIZON_DAYS, HORIZON_DAYS)
        if len(positions) == 0:
            self.mean_, self.std_ = np.zeros(4), np.ones(4)
            self.model_ = model.eval()
            return
        offsets = np.arange(-self.input_size + 1, 1)
        windows = inputs[positions[:, None] + offsets].transpose(0, 2, 1, 3)  # (S, N, L, 4)
        # Channel statistics from the training windows only: everything in them is in the past.
        self.mean_ = windows.mean(axis=(0, 1, 2))
        self.std_ = windows.std(axis=(0, 1, 2)) + 1e-8
        x = self._standardise(windows)
        steps = np.arange(1, HORIZON_DAYS + 1)
        path = vol[positions[:, None] + steps].transpose(0, 2, 1)  # (S, N, 5)
        y = torch.as_tensor(path - vol[positions][:, :, None], dtype=torch.float32)
        adjacency = None
        if self.graph:
            adjacency = torch.as_tensor(self._adjacency_series(panel)[positions], dtype=torch.float32)

        groups = [{"params": [p for n, p in model.named_parameters() if n != "gate"]}]
        if self.graph:
            groups.append({"params": [model.gate], "lr": GATE_LEARNING_RATE})
        optimizer = torch.optim.Adam(groups, lr=self.learning_rate)
        generator = torch.Generator().manual_seed(self.seed)
        batch = min(self.batch_dates, len(positions))
        model.train()
        for _ in range(self.max_steps):
            picked = torch.randint(len(positions), (batch,), generator=generator)
            optimizer.zero_grad()
            out = model(x[picked], None if adjacency is None else adjacency[picked])
            (out - y[picked]).abs().mean().backward()
            optimizer.step()
        self.model_ = model.eval()
        if self.graph:
            last = next(iter(panel.values())).index[-1]
            self.gate_history_.append({"refit_date": last, "gates": [float(model.gate.detach())]})

    def predict(self, panel: Panel) -> dict[str, float]:
        if self.model_ is None:
            raise RuntimeError(f"skill {self.name!r} must be fitted before predicting")
        tail = feature_tail(panel, self.input_size)  # (L, N, 4)
        x = self._standardise(tail.transpose(1, 0, 2)[None])
        adjacency = torch.as_tensor(self._adjacency_now(panel)[None], dtype=torch.float32) if self.graph else None
        with torch.no_grad():
            change = self.model_(x, adjacency).squeeze(0).numpy()[:, -1]
        log_vol = tail[-1, :, 0] + change
        return {ticker: max(float(np.exp(v)), MIN_VOL) for ticker, v in zip(panel, log_vol)}


CANDIDATES = {name: {"graph_source": source} for source in GRAPH_SOURCES for name in [f"stgnn_skill_{source}"]}


def build_candidate(name: str, seed: int = 0) -> STGNNSkill:
    if name not in CANDIDATES:
        raise ValueError(f"unknown candidate {name!r}; available: {', '.join(CANDIDATES)}")
    return STGNNSkill(seed=seed, **CANDIDATES[name])
