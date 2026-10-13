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
``features`` gives each stock 4 channels instead of 1 (``gap_vix`` adds a 5th
and 6th: the overnight gap and the log VIX), and ``path`` makes the head predict
the whole 1..5 day path instead of only the 5th value.

``graph`` feeds the market map (``tsm.models.graph``) in, in one of two ways,
each behind learned gates that start at 0 so the model starts as the plain one
and uses the map only if training finds it helps:

- ``"gnn"``: after the embedding, ``h = h + g * (A @ Linear(h))``, one scalar ``g``.
- ``"bias"``: every encoder layer adds ``lambda_h * S`` to its attention logits,
  ``S`` the 0/1 support of ``A`` (neighbours and self-loops), one ``lambda`` per
  head and layer.

``graph_source`` picks the map: ``"corr"`` (market-adjusted correlations),
``"sector"`` (GICS sectors) or ``"shuffled"`` (the correlation map with its
stocks permuted, a control that keeps the statistics but links the wrong stocks).
"""
from __future__ import annotations

import random

import numpy as np
import torch
from numpy.lib.stride_tricks import sliding_window_view
from torch import nn

from tsm.config import HORIZON_DAYS, TRADING_DAYS_PER_YEAR
from tsm.data import Panel
from tsm.models.graph import correlation_adjacency, correlation_adjacency_series, sector_adjacency
from tsm.skills.base import MIN_VOL, TemporalSkill
from tsm.target import realized_vol

LOSSES = ("mae", "qlike")

# Floor for high/low before taking its log, so a degenerate row cannot produce
# -inf. Cleaned prices are positive and high >= low, so it never binds in practice.
EPS_RANGE = 1e-6

# Channels per stock when features=True: log vol, log return, log range, log1p volume.
N_FEATURES = 4
# With gap_vix: the overnight gap log(open_t / close_t-1) and log VIX close, the same for every stock.
N_FEATURES_GAP_VIX = 6

# exp(u) overflows to inf for a wildly wrong forecast, which would poison the
# gradients. exp(10) = 22026 is far outside any ratio a sane forecast produces,
# so this clamp never binds in normal training; it only stops a blow-up.
U_CLAMP = 10.0

GRAPH_MODES = ("gnn", "bias")
GRAPH_SOURCES = ("corr", "sector", "shuffled")

# The gates start at 0 and Adam moves a parameter by about lr per step, so at the
# network's 1e-3 they could not get past ~0.3 in 300 steps. They get their own rate.
GATE_LEARNING_RATE = 0.02

# The one fixed permutation behind the "shuffled" control.
SHUFFLE_SEED = 0


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


def _vix_tail(panel: Panel, rows: int) -> np.ndarray:
    """``(rows, stocks)`` of the ``vix`` column that ``tsm.experiment`` adds to every frame."""
    try:
        return _tail(panel, "vix", rows)
    except KeyError:
        raise KeyError(
            "gap_vix needs a 'vix' column in every frame; tsm.experiment adds it from the frozen ^VIX cache"
        ) from None


def feature_tail(panel: Panel, rows: int, gap_vix: bool = False) -> np.ndarray:
    """``(rows, stocks, 4)``: log 5-day vol, log return, log range, log1p volume.

    Every channel for day ``t`` uses only data up to and including day ``t``:
    the vol channel spans t-4..t, the return needs t-1, the other two only t.
    With ``gap_vix``, ``(rows, stocks, 6)``: also the overnight gap (open of t,
    close of t-1) and the log VIX close of t.
    """
    vol = log_vol_tail(panel, rows)
    closes = _tail(panel, "close", rows + 1)
    returns = np.log(closes[1:] / closes[:-1])
    highs, lows = _tail(panel, "high", rows), _tail(panel, "low", rows)
    log_range = np.log(np.clip(highs / lows, EPS_RANGE, None))
    log_volume = np.log1p(_tail(panel, "volume", rows))
    if not gap_vix:
        return np.stack([vol, returns, log_range, log_volume], axis=-1)
    gap = np.log(_tail(panel, "open", rows) / closes[:-1])
    log_vix = np.log(_vix_tail(panel, rows))
    return np.stack([vol, returns, log_range, log_volume, gap, log_vix], axis=-1)


def feature_series(panel: Panel, gap_vix: bool = False) -> np.ndarray:
    """``(days, stocks, 4)`` over the whole panel, for ``fit`` (6 channels with ``gap_vix``).

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
    if not gap_vix:
        return np.stack([vol, returns, log_range, log_volume], axis=-1)
    gap = np.full_like(closes, np.nan)
    gap[1:] = np.log(_tail(panel, "open", days)[1:] / closes[:-1])
    log_vix = np.log(_vix_tail(panel, days))
    return np.stack([vol, returns, log_range, log_volume, gap, log_vix], axis=-1)


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


def _shuffled(matrix: np.ndarray) -> np.ndarray:
    """The map with its stocks relabelled by one fixed permutation (rows and columns alike).

    It keeps every statistic of the real map (weights, degrees, symmetry, rows
    summing to 1) but links the wrong stocks: the control for "any graph helps".
    """
    order = np.random.default_rng(SHUFFLE_SEED).permutation(matrix.shape[-1])
    return matrix[..., order, :][..., :, order]


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
        graph: str | None = None,
    ) -> None:
        super().__init__()
        if graph is not None and graph not in GRAPH_MODES:
            raise ValueError(f"graph must be one of {GRAPH_MODES} or None, got {graph!r}")
        self.n_outputs = n_outputs
        self.n_channels = n_channels
        self.graph = graph
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
        if graph == "gnn":
            # Drawn from a side stream: the weights above and the dropout noise of
            # training then match the plain model at the same seed exactly.
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(torch.initial_seed() + 1)
                self.graph_linear = nn.Linear(hidden_size, hidden_size)
            self.gate = nn.Parameter(torch.zeros(()))
        elif graph == "bias":
            self.attention_bias = nn.Parameter(torch.zeros(n_layers, n_heads))

    def gate_parameters(self) -> list[nn.Parameter]:
        """The scalars that decide how much the map is used: ``g``, or every ``lambda``."""
        if self.graph == "gnn":
            return [self.gate]
        if self.graph == "bias":
            return [self.attention_bias]
        return []

    def gate_values(self) -> list[float]:
        """Current gates as plain numbers; ``lambda`` in layer-major order."""
        return [value for p in self.gate_parameters() for value in p.detach().flatten().tolist()]

    def _encode(self, h: torch.Tensor, adjacency: torch.Tensor | None) -> torch.Tensor:
        """The encoder, with the market map fed in when the model has one."""
        if self.graph is None:
            return self.encoder(h)
        if adjacency is None:
            raise ValueError("this model has a graph: pass each date's adjacency")
        if self.graph == "gnn":
            return self.encoder(h + self.gate * torch.bmm(adjacency, self.graph_linear(h)))
        support = (adjacency > 0).to(h.dtype)  # neighbours and self-loops
        # At prediction time nn.TransformerEncoderLayer switches to a fused kernel that
        # mishandles an additive float mask (NaNs or wrong values; see
        # tests/test_itransformer_graph.py). Turn it off here so predicting runs the same
        # attention as training, then restore it for everything else.
        fast_path = torch.backends.mha.get_fastpath_enabled()
        torch.backends.mha.set_fastpath_enabled(False)
        try:
            for layer, bias in zip(self.encoder.layers, self.attention_bias):
                # One additive mask per (date, head), as attention expects: (batch * heads, stocks, stocks).
                h = layer(h, src_mask=(bias[None, :, None, None] * support[:, None]).flatten(0, 1))
        finally:
            torch.backends.mha.set_fastpath_enabled(fast_path)
        return h

    def forward(self, windows: torch.Tensor, adjacency: torch.Tensor | None = None) -> torch.Tensor:
        """``windows``: ``(batch, stocks, input_size)``, or ``(batch, stocks, channels, input_size)``.
        ``adjacency``: ``(batch, stocks, stocks)``, each date's market map; only with a graph.

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
            tokens = self._encode(self.embed(((windows - mean) / std).flatten(start_dim=2)), adjacency)
            standardized = self.head(tokens)
            vol_mean, vol_std = mean[:, :, 0], std[:, :, 0]
            if self.n_outputs == 1:
                return standardized.squeeze(-1) * vol_std.squeeze(-1) + vol_mean.squeeze(-1)
            return standardized * vol_std + vol_mean

        mean = windows.mean(dim=-1, keepdim=True)
        std = windows.std(dim=-1, keepdim=True).clamp_min(1e-6)
        tokens = self._encode(self.embed((windows - mean) / std), adjacency)
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
        gap_vix: bool = False,
        graph: str | None = None,
        graph_source: str = "corr",
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
        if graph is not None and graph not in GRAPH_MODES:
            raise ValueError(f"graph must be one of {GRAPH_MODES} or None, got {graph!r}")
        if graph_source not in GRAPH_SOURCES:
            raise ValueError(f"graph_source must be one of {GRAPH_SOURCES}, got {graph_source!r}")
        self.loss = loss
        self.path = path
        if gap_vix and not features:
            raise ValueError("gap_vix adds channels to features=True; it cannot be used alone")
        self.features = features
        self.gap_vix = gap_vix
        self.graph = graph
        self.graph_source = graph_source
        # A path head predicts the whole 5-step path; a single head only the 5th value.
        self.n_outputs = HORIZON_DAYS if path else 1
        self.n_channels = (N_FEATURES_GAP_VIX if gap_vix else N_FEATURES) if features else 1
        # Names must differ between variants: the backtest tracks each skill's fits by name.
        channels = ("_feats6" if gap_vix else "_feats") if features else ""
        default = f"itransformer_{loss}" + ("_path" if path else "") + channels
        if graph is not None:
            default = f"itransformer_graph_{graph}_{graph_source}"
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
        # One entry per fit: the date of the panel's last row and the gates after training.
        self.gate_history_: list[dict] = []

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
            graph=self.graph,
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

    def _adjacency_series(self, panel: Panel) -> np.ndarray:
        """``(days, stocks, stocks)`` for training: row ``t`` uses data up to day ``t`` only."""
        if self.graph_source == "sector":
            matrix = sector_adjacency(list(panel))
            return np.broadcast_to(matrix, (len(next(iter(panel.values()))), *matrix.shape))
        series = correlation_adjacency_series(panel)
        return _shuffled(series) if self.graph_source == "shuffled" else series

    def _adjacency_now(self, panel: Panel) -> np.ndarray:
        """``(stocks, stocks)``: the map of the panel's last row, for predicting."""
        if self.graph_source == "sector":
            return sector_adjacency(list(panel))
        matrix = correlation_adjacency(panel)
        return _shuffled(matrix) if self.graph_source == "shuffled" else matrix

    def _record_gates(self, panel: Panel, model: ITransformer) -> None:
        if self.graph is not None:
            last = next(iter(panel.values())).index[-1]
            self.gate_history_.append({"refit_date": last, "gates": model.gate_values()})

    def fit(self, panel: Panel) -> None:
        model = self._build()
        if self.features:
            inputs = feature_series(panel, gap_vix=self.gap_vix)
            vol = inputs[..., 0]
            # A date is usable only when every channel of every stock is there.
            validity = inputs.reshape(len(inputs), -1)
        else:
            inputs = vol = validity = log_vol_series(panel)
        positions = training_positions(validity, self.input_size, HORIZON_DAYS, self.n_outputs)
        self.n_train_ = len(positions)
        if self.n_train_ == 0:
            self.model_ = model.eval()
            self._record_gates(panel, model)
            return

        x = torch.as_tensor(self._windows(inputs, positions), dtype=torch.float32)
        y = torch.as_tensor(self._targets(vol, positions), dtype=torch.float32)
        adjacency = None
        if self.graph is not None:
            # Each training date with its own map, built from data up to that date.
            adjacency = torch.as_tensor(self._adjacency_series(panel)[positions], dtype=torch.float32)

        criterion = loss_function(self.loss)
        gates = model.gate_parameters()
        gate_ids = {id(p) for p in gates}
        groups = [{"params": [p for p in model.parameters() if id(p) not in gate_ids]}]
        if gates:
            groups.append({"params": gates, "lr": GATE_LEARNING_RATE})
        optimizer = torch.optim.Adam(groups, lr=self.learning_rate)
        generator = torch.Generator().manual_seed(self.seed)
        batch = min(self.batch_dates, self.n_train_)
        model.train()
        for _ in range(self.max_steps):
            picked = torch.randint(self.n_train_, (batch,), generator=generator)
            optimizer.zero_grad()
            predicted = model(x[picked]) if adjacency is None else model(x[picked], adjacency[picked])
            criterion(predicted, y[picked]).backward()
            optimizer.step()
        self.model_ = model.eval()
        self._record_gates(panel, model)

    def predict(self, panel: Panel) -> dict[str, float]:
        if self.model_ is None:
            raise RuntimeError(f"skill {self.name!r} must be fitted before predicting")
        # Only the tail matters, and a pandas rolling call per ticker on each of
        # 2203 dates is what made a walk-forward slow. These build the same
        # numbers in numpy, about 35x faster on 52 tickers.
        if self.features:
            tail = feature_tail(panel, self.input_size, gap_vix=self.gap_vix)
            x = torch.as_tensor(tail.transpose(1, 2, 0)[None], dtype=torch.float32)
        else:
            tail = log_vol_tail(panel, self.input_size)
            x = torch.as_tensor(tail.T[None], dtype=torch.float32)
        with torch.no_grad():
            if self.graph is None:
                out = self.model_(x).squeeze(0).numpy()
            else:
                adjacency = torch.as_tensor(self._adjacency_now(panel)[None], dtype=torch.float32)
                out = self.model_(x, adjacency).squeeze(0).numpy()
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
    "itransformer_path_feats6": {
        "loss": "mae",
        "path": True,
        "features": True,
        "gap_vix": True,
        "name": "itransformer_path_feats6",
    },
    # path_feats with the market map: itransformer_graph_{gnn,bias}_{corr,sector,shuffled}.
    **{
        f"itransformer_graph_{mode}_{source}": {
            "loss": "mae",
            "path": True,
            "features": True,
            "graph": mode,
            "graph_source": source,
            "name": f"itransformer_graph_{mode}_{source}",
        }
        for mode in GRAPH_MODES
        for source in GRAPH_SOURCES
    },
}


def summarize_gates(mode: str, values: list[float]) -> float:
    """One number per refit: ``g`` itself for "gnn", the mean ``|lambda|`` for "bias"."""
    return float(values[0]) if mode == "gnn" else float(np.mean(np.abs(values)))


def build_candidate(name: str, seed: int = 0) -> ITransformerSkill:
    """One candidate by name, at a given seed."""
    if name not in CANDIDATES:
        raise ValueError(f"unknown candidate {name!r}; available: {', '.join(CANDIDATES)}")
    return ITransformerSkill(seed=seed, **CANDIDATES[name])


def build_candidates(names: list[str] | None = None, seed: int = 0) -> list[ITransformerSkill]:
    """Several candidates by name; all of them when ``names`` is None."""
    return [build_candidate(n, seed=seed) for n in (names if names is not None else CANDIDATES)]
