"""Our own iTransformer for 5-day volatility, in plain PyTorch.

Why not the ``multivariate`` skill: it goes through neuralforecast, which trains
with MAE on log-volatility. MAE aims at the typical week and gives up on the
volatile ones, which is exactly what QLIKE punishes. The library also cannot
take extra per-stock inputs or a graph, which later steps need.

This module is an experiment. The skills it builds are deliberately NOT in
``build_skills``: the committee is unchanged until an experiment earns a place.

Layout, per date: each stock's last ``input_size`` days becomes one token, so
attention runs across stocks rather than across time, which is what makes it an
*inverted* transformer. Options widen that token without ever adding tokens:
``features`` gives each stock 4 channels instead of 1, and ``path`` makes the
head predict the whole 1..5 day path instead of only the 5th value.
"""
from __future__ import annotations

import random

import numpy as np
import torch
from numpy.lib.stride_tricks import sliding_window_view
from torch import nn

from tsm.config import HORIZON_DAYS, TRADING_DAYS_PER_YEAR
from tsm.data import Panel
from tsm.skills.base import MIN_VOL, TemporalSkill
from tsm.target import realized_vol

LOSSES = ("mae", "qlike")

# Floor for high/low before taking its log, so a degenerate row cannot produce
# -inf. Cleaned prices are positive and high >= low, so it never binds in practice.
EPS_RANGE = 1e-6

# Channels per stock when features=True: log vol, log return, log range, log1p volume.
N_FEATURES = 4

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


def _tail(panel: Panel, column: str, rows: int) -> np.ndarray:
    """``(rows, stocks)`` of one price column, newest last."""
    return np.column_stack([frame[column].to_numpy()[-rows:] for frame in panel.values()])


def log_vol_tail(panel: Panel, rows: int) -> np.ndarray:
    """``(rows, stocks)`` of log(5-day realized vol), in numpy only.

    Same definition as ``log_vol_series`` but without a pandas rolling call per
    ticker, which is what made ``predict`` cost ~68ms on 52 tickers. Row ``t``
    still uses only prices up to and including day ``t``.
    """
    needed = rows + HORIZON_DAYS + 1
    closes = _tail(panel, "close", needed)
    returns = np.log(closes[1:] / closes[:-1])
    squared = sliding_window_view(returns * returns, HORIZON_DAYS, axis=0).sum(axis=-1)
    vol = np.sqrt(TRADING_DAYS_PER_YEAR / HORIZON_DAYS * squared)
    out = np.log(np.maximum(vol, MIN_VOL))
    if len(out) >= rows:
        return out[-rows:]
    head = np.repeat(out[0][None], rows - len(out), axis=0)
    return np.concatenate([head, out])


def feature_tail(panel: Panel, rows: int) -> np.ndarray:
    """``(rows, stocks, 4)``: log 5-day vol, log return, log range, log1p volume.

    Every channel for day ``t`` uses only data up to and including day ``t``:
    the vol channel spans t-4..t, the return needs t-1, the other two only t.
    """
    vol = log_vol_tail(panel, rows)
    closes = _tail(panel, "close", rows + 1)
    returns = np.log(closes[1:] / closes[:-1])
    highs, lows = _tail(panel, "high", rows), _tail(panel, "low", rows)
    log_range = np.log(np.clip(highs / lows, EPS_RANGE, None))
    log_volume = np.log1p(_tail(panel, "volume", rows))
    return np.stack([vol, returns, log_range, log_volume], axis=-1)


def feature_series(panel: Panel) -> np.ndarray:
    """``(days, stocks, 4)`` over the whole panel, for ``fit``.

    The vol channel comes from ``log_vol_series`` so it matches what the
    single-channel model trains on, NaNs in the first rows included.
    """
    days = len(next(iter(panel.values())))
    vol = log_vol_series(panel)
    closes = _tail(panel, "close", days)
    returns = np.full_like(closes, np.nan)
    returns[1:] = np.log(closes[1:] / closes[:-1])
    log_range = np.log(np.clip(_tail(panel, "high", days) / _tail(panel, "low", days), EPS_RANGE, None))
    log_volume = np.log1p(_tail(panel, "volume", days))
    return np.stack([vol, returns, log_range, log_volume], axis=-1)


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
        n_channels: int = 1,
    ) -> None:
        super().__init__()
        self.n_outputs = n_outputs
        self.n_channels = n_channels
        # One token per stock either way: extra channels widen the token, never add tokens.
        self.embed = nn.Linear(n_channels * input_size, hidden_size)
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
        """``windows``: ``(batch, stocks, input_size)``, or ``(batch, stocks, channels, input_size)``.

        Returns ``(batch, stocks)`` with one output, ``(batch, stocks, n_outputs)``
        with a path head.

        Each stock's window is standardized by its own mean and std, and the
        output is un-standardized with the same two numbers. The network only
        ever sees and predicts shape, never level, so a quiet utility and a wild
        mid-cap look alike to it. With several channels each one is standardized
        separately, and the output is un-standardized with channel 0 (the vol
        channel), which is the only channel the target lives on.
        """
        if windows.dim() == 4:
            mean = windows.mean(dim=-1, keepdim=True)
            std = windows.std(dim=-1, keepdim=True).clamp_min(1e-6)
            tokens = self.encoder(self.embed(((windows - mean) / std).flatten(start_dim=2)))
            standardized = self.head(tokens)
            vol_mean, vol_std = mean[:, :, 0], std[:, :, 0]
            if self.n_outputs == 1:
                return standardized.squeeze(-1) * vol_std.squeeze(-1) + vol_mean.squeeze(-1)
            return standardized * vol_std + vol_mean

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
        features: bool = False,
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
        self.features = features
        # A path head predicts the whole 5-step path; a single head only the 5th value.
        self.n_outputs = HORIZON_DAYS if path else 1
        self.n_channels = N_FEATURES if features else 1
        default = f"itransformer_{loss}" + ("_path" if path else "") + ("_feats" if features else "")
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
            n_channels=self.n_channels,
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
        if self.features:
            inputs = feature_series(panel)
            vol = inputs[..., 0]
            # A date is usable only when every channel of every stock is there.
            validity = inputs.reshape(len(inputs), -1)
        else:
            inputs = vol = validity = log_vol_series(panel)
        positions = training_positions(validity, self.input_size, HORIZON_DAYS, self.n_outputs)
        self.n_train_ = len(positions)
        if self.n_train_ == 0:
            self.model_ = model.eval()
            return

        x = torch.as_tensor(self._windows(inputs, positions), dtype=torch.float32)
        y = torch.as_tensor(self._targets(vol, positions), dtype=torch.float32)

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
        # Only the tail matters, and a pandas rolling call per ticker on each of
        # 2203 dates is what made a walk-forward slow. These build the same
        # numbers in numpy, about 35x faster on 52 tickers.
        if self.features:
            tail = feature_tail(panel, self.input_size)
            x = torch.as_tensor(tail.transpose(1, 2, 0)[None], dtype=torch.float32)
        else:
            tail = log_vol_tail(panel, self.input_size)
            x = torch.as_tensor(tail.T[None], dtype=torch.float32)
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
    "itransformer_path_feats": {
        "loss": "mae",
        "path": True,
        "features": True,
        "name": "itransformer_path_feats",
    },
}


def build_candidate(name: str, seed: int = 0) -> ITransformerSkill:
    """One candidate by name, at a given seed."""
    if name not in CANDIDATES:
        raise ValueError(f"unknown candidate {name!r}; available: {', '.join(CANDIDATES)}")
    return ITransformerSkill(seed=seed, **CANDIDATES[name])


def build_candidates(names: list[str] | None = None, seed: int = 0) -> list[ITransformerSkill]:
    """Several candidates by name; all of them when ``names`` is None."""
    return [build_candidate(n, seed=seed) for n in (names if names is not None else CANDIDATES)]
