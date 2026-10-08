"""Our own iTransformer for 5-day volatility, in plain PyTorch.

Why not the ``multivariate`` skill: it goes through neuralforecast, which trains
with MAE on log-volatility. MAE aims at the typical week and gives up on the
volatile ones, which is exactly what QLIKE punishes. The library also cannot
take extra per-stock inputs or a graph, which later steps need.

This module is an experiment. The two skills it builds are deliberately NOT in
``build_skills``: the committee is unchanged until an experiment earns a place.

Layout, per date: each stock's last ``input_size`` days of log(volatility of the
last 5 days) is one token. Attention therefore runs across stocks, not across
time, which is what makes it an *inverted* transformer. The output is the log of
the 5-day forward volatility directly, one number per stock, not a 5-step path.
"""
from __future__ import annotations

import random

import numpy as np
import torch
from numpy.lib.stride_tricks import sliding_window_view
from torch import nn

from tsm.config import HORIZON_DAYS
from tsm.data import Panel
from tsm.skills.base import MIN_VOL, TemporalSkill
from tsm.target import realized_vol

LOSSES = ("mae", "qlike")

# exp(u) overflows to inf for a wildly wrong forecast, which would poison the
# gradients. exp(10) = 22026 is far outside any ratio a sane forecast produces,
# so this clamp never binds in normal training; it only stops a blow-up.
U_CLAMP = 10.0


def log_vol_series(panel: Panel) -> np.ndarray:
    """``(days, stocks)`` matrix of log(volatility of the last 5 days).

    The same series the ``multivariate`` skill feeds its model. Row ``t`` uses
    only prices up to and including day ``t``, so it is safe as an input.
    """
    columns = [
        np.log(realized_vol(frame["close"], HORIZON_DAYS).clip(lower=MIN_VOL)).to_numpy()
        for frame in panel.values()
    ]
    return np.column_stack(columns)


def training_positions(
    series: np.ndarray,
    input_size: int,
    horizon: int = HORIZON_DAYS,
    n_targets: int = 1,
) -> np.ndarray:
    """Dates usable for training: full window behind them, targets inside the panel.

    The target of date ``t`` is row ``t + horizon``, so ``t`` is only usable when
    that row exists. This is what keeps ``fit`` from inventing a target it cannot
    know yet. A path head needs the last ``n_targets`` rows up to ``t + horizon``,
    so it requires all of them.
    """
    rows = len(series)
    if rows <= input_size + horizon:
        return np.empty(0, dtype=int)
    valid = ~np.isnan(series).any(axis=1)
    candidates = np.arange(input_size - 1, rows - horizon)
    # Window ending at t starts at t - input_size + 1, so index that start.
    window_ok = sliding_window_view(valid, input_size).all(axis=1)[candidates - input_size + 1]
    if n_targets == 1:
        targets_ok = valid[candidates + horizon]
    else:
        offsets = np.arange(horizon - n_targets + 1, horizon + 1)
        targets_ok = valid[candidates[:, None] + offsets].all(axis=1)
    return candidates[window_ok & targets_ok]


def last_window(series: np.ndarray, input_size: int) -> np.ndarray:
    """The most recent complete ``input_size`` window, as ``(input_size, stocks)``.

    Only ever looks backwards, so it cannot reach past the panel's last row. If
    the panel is too short, the earliest valid row is repeated to pad.
    """
    valid = np.flatnonzero(~np.isnan(series).any(axis=1))
    if len(valid) == 0:
        raise ValueError("no row of the log-volatility series is complete")
    end = int(valid[-1])
    start = end - input_size + 1
    if start >= 0:
        return series[start : end + 1]
    head = np.repeat(series[valid[0]][None], -start, axis=0)
    return np.concatenate([head, series[: end + 1]])


def loss_function(kind: str):
    """MAE or QLIKE, both on the predicted log volatility."""
    if kind not in LOSSES:
        raise ValueError(f"loss must be one of {LOSSES}, got {kind!r}")

    def mae(predicted: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return (predicted - target).abs().mean()

    def qlike(predicted: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        # u = log(realized^2) - 2 * predicted log vol. target is log(realized),
        # so log(realized^2) is 2 * target.
        u = (2.0 * target - 2.0 * predicted).clamp(-U_CLAMP, U_CLAMP)
        return (torch.exp(u) - u - 1.0).mean()

    return mae if kind == "mae" else qlike


class ITransformer(nn.Module):
    """One token per stock, attention across stocks, one log-volatility per stock."""

    def __init__(
        self,
        input_size: int = 44,
        hidden_size: int = 64,
        n_heads: int = 4,
        d_ff: int = 128,
        n_layers: int = 2,
        dropout: float = 0.1,
        n_outputs: int = 1,
    ) -> None:
        super().__init__()
        self.n_outputs = n_outputs
        self.embed = nn.Linear(input_size, hidden_size)
        layer = nn.TransformerEncoderLayer(
            d_model=hidden_size,
            nhead=n_heads,
            dim_feedforward=d_ff,
            dropout=dropout,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers, enable_nested_tensor=False)
        self.head = nn.Linear(hidden_size, n_outputs)

    def forward(self, windows: torch.Tensor) -> torch.Tensor:
        """``windows``: ``(batch, stocks, input_size)`` of log-vol.

        Returns ``(batch, stocks)`` with one output, ``(batch, stocks, n_outputs)``
        with a path head.

        Each stock's window is standardized by its own mean and std, and the
        output is un-standardized with the same two numbers. The network only
        ever sees and predicts shape, never level, so a quiet utility and a wild
        mid-cap look alike to it.
        """
        mean = windows.mean(dim=-1, keepdim=True)
        std = windows.std(dim=-1, keepdim=True).clamp_min(1e-6)
        tokens = self.encoder(self.embed((windows - mean) / std))
        standardized = self.head(tokens)
        if self.n_outputs == 1:
            # Kept exactly as it was, so the single-output model reproduces bit for bit.
            return standardized.squeeze(-1) * std.squeeze(-1) + mean.squeeze(-1)
        return standardized * std + mean


class ITransformerSkill(TemporalSkill):
    """Skill wrapper around :class:`ITransformer`. Not part of the committee."""

    horizon = "medium"
    refit_every_days = 125

    def __init__(
        self,
        loss: str = "mae",
        path: bool = False,
        name: str | None = None,
        input_size: int = 44,
        hidden_size: int = 64,
        n_heads: int = 4,
        d_ff: int = 128,
        n_layers: int = 2,
        dropout: float = 0.1,
        max_steps: int = 300,
        batch_dates: int = 32,
        learning_rate: float = 1e-3,
        seed: int = 0,
    ) -> None:
        if loss not in LOSSES:
            raise ValueError(f"loss must be one of {LOSSES}, got {loss!r}")
        self.loss = loss
        self.path = path
        # A path head predicts the whole 5-step path; a single head only the 5th value.
        self.n_outputs = HORIZON_DAYS if path else 1
        default = f"itransformer_{loss}_path" if path else f"itransformer_{loss}"
        self.name = name if name is not None else default
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.n_heads = n_heads
        self.d_ff = d_ff
        self.n_layers = n_layers
        self.dropout = dropout
        self.max_steps = max_steps
        self.batch_dates = batch_dates
        self.learning_rate = learning_rate
        self.seed = seed
        self.model_: ITransformer | None = None
        self.n_train_ = 0

    def _build(self) -> ITransformer:
        """Seed everything, then build. Called by every fit, so refits are reproducible."""
        random.seed(self.seed)
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)
        return ITransformer(
            input_size=self.input_size,
            hidden_size=self.hidden_size,
            n_heads=self.n_heads,
            d_ff=self.d_ff,
            n_layers=self.n_layers,
            dropout=self.dropout,
            n_outputs=self.n_outputs,
        )

    def _windows(self, series: np.ndarray, positions: np.ndarray) -> np.ndarray:
        """``(samples, stocks, input_size)`` in one strided view, no per-date loop."""
        strided = sliding_window_view(series, self.input_size, axis=0)
        return strided[positions - self.input_size + 1]

    def _targets(self, series: np.ndarray, positions: np.ndarray) -> np.ndarray:
        """The 5th value ahead, or the whole 1..5 path as ``(samples, stocks, 5)``."""
        if not self.path:
            return series[positions + HORIZON_DAYS]
        steps = np.arange(1, HORIZON_DAYS + 1)
        return series[positions[:, None] + steps].transpose(0, 2, 1)

    def fit(self, panel: Panel) -> None:
        model = self._build()
        series = log_vol_series(panel)
        positions = training_positions(series, self.input_size, HORIZON_DAYS, self.n_outputs)
        self.n_train_ = len(positions)
        if self.n_train_ == 0:
            self.model_ = model.eval()
            return

        x = torch.as_tensor(self._windows(series, positions), dtype=torch.float32)
        y = torch.as_tensor(self._targets(series, positions), dtype=torch.float32)

        criterion = loss_function(self.loss)
        optimizer = torch.optim.Adam(model.parameters(), lr=self.learning_rate)
        generator = torch.Generator().manual_seed(self.seed)
        batch = min(self.batch_dates, self.n_train_)
        model.train()
        for _ in range(self.max_steps):
            picked = torch.randint(self.n_train_, (batch,), generator=generator)
            optimizer.zero_grad()
            criterion(model(x[picked]), y[picked]).backward()
            optimizer.step()
        self.model_ = model.eval()

    def predict(self, panel: Panel) -> dict[str, float]:
        if self.model_ is None:
            raise RuntimeError(f"skill {self.name!r} must be fitted before predicting")
        # Only the tail matters, and rebuilding the series over the whole panel on
        # every one of 2203 dates is what makes a walk-forward slow. The extra
        # HORIZON_DAYS rows are what realized_vol needs to fill its first window.
        recent = {
            ticker: frame.iloc[-(self.input_size + 2 * HORIZON_DAYS):]
            for ticker, frame in panel.items()
        }
        window = last_window(log_vol_series(recent), self.input_size)
        x = torch.as_tensor(window.T[None], dtype=torch.float32)
        with torch.no_grad():
            out = self.model_(x).squeeze(0).numpy()
        # With a path head the forecast is the 5th step; the earlier ones only shape training.
        predicted = out[:, -1] if self.path else out
        return {ticker: max(float(np.exp(value)), MIN_VOL) for ticker, value in zip(panel, predicted)}


# Every candidate the experiment runner can be asked for by name on the command line.
CANDIDATES: dict[str, dict] = {
    "itransformer_mae": {"loss": "mae"},
    "itransformer_qlike": {"loss": "qlike"},
    "itransformer_mae_path": {"loss": "mae", "path": True},
    "itransformer_qlike_path": {"loss": "qlike", "path": True},
}


def build_candidate(name: str, seed: int = 0) -> ITransformerSkill:
    """One candidate by name, at a given seed."""
    if name not in CANDIDATES:
        raise ValueError(f"unknown candidate {name!r}; available: {', '.join(CANDIDATES)}")
    return ITransformerSkill(seed=seed, **CANDIDATES[name])


def build_candidates(names: list[str] | None = None, seed: int = 0) -> list[ITransformerSkill]:
    """Several candidates by name; all of them when ``names`` is None."""
    return [build_candidate(n, seed=seed) for n in (names if names is not None else CANDIDATES)]
