"""ST-GNN supervisor: a small learned network that sets each skill's weight, per stock and day.

It does the same job as ``tsm.supervisor.Supervisor`` (weights summing to 1, then
the weighted mean of the calibrated skill predictions) but learns the rule
instead of fixing it:

- **temporal:** a GRU reads the sequence of each skill's last ``window`` errors,
  ``log(realized / predicted)``, instead of one average;
- **graph:** up to two layers ``H + g·A·H·W`` let stocks that move together share
  that state through the market map (``tsm.models.graph``); ``g`` starts at 0, so
  the graph is off until it lowers the loss;
- **head at zero:** before training every weight is 1/4, exactly the equal-weight
  average, so the network has to earn every move away from it.

An outcome is known ``HORIZON_DAYS`` after its prediction, the current
supervisor's rule: the inputs for a row at index ``t`` use errors of rows up to
``t - HORIZON_DAYS`` only, and a refit at ``r`` trains on rows up to ``r - HORIZON_DAYS``.

Arrays are indexed ``(t, stock, skill)``, with ``t`` the row in ``frame_arrays``
(one row per position of the saved predictions, oldest first).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch import nn

from tsm.config import HORIZON_DAYS

HIDDEN = 16
LEARNING_RATE = 1e-3
# As in tsm.models.itransformer: a gate that starts at 0 needs its own, larger rate.
GATE_LEARNING_RATE = 0.02
STEPS = 300  # Adam steps per refit, fixed before any result
BATCH_DATES = 32  # dates per step; all stocks of a date go together, the graph needs them
REFIT_EVERY = 63  # trading days, one quarter
CONFIDENCE_WINDOW = 120  # the current supervisor's window, so confidence keeps its meaning
PREDICT_CHUNK = 128


@dataclass
class Arrays:
    positions: np.ndarray  # (T,)
    dates: pd.DatetimeIndex  # (T,)
    tickers: list[str]
    preds: np.ndarray  # (T, N, K) calibrated predictions
    realized: np.ndarray  # (T, N), NaN while unknown
    earnings: np.ndarray  # (T, N) 0/1
    errors: np.ndarray  # (T, N, K) log(realized / predicted), NaN while unknown


def frame_arrays(frame: pd.DataFrame, skill_names: list[str], tickers: list[str] | None = None) -> Arrays:
    """Pivot a predictions frame (one row per ticker and date) into ``(t, stock, skill)`` arrays.

    Every ticker must have every position: the network sees all stocks of a date at once.
    """
    tickers = list(dict.fromkeys(frame["ticker"])) if tickers is None else tickers
    wide = frame.set_index(["position", "ticker"]).sort_index()
    positions = np.array(sorted(frame["position"].unique()))
    full = pd.MultiIndex.from_product([positions, tickers], names=["position", "ticker"])
    if len(wide) != len(full) or not wide.index.equals(full.sort_values()):
        raise ValueError("every ticker needs a row at every position")
    wide = wide.reindex(full)
    shape = (len(positions), len(tickers))
    preds = np.stack([wide[f"pred_{s}"].to_numpy(dtype=float).reshape(shape) for s in skill_names], axis=-1)
    realized = wide["realized_vol"].to_numpy(dtype=float, copy=True).reshape(shape)
    earnings = (
        wide["earnings_week"].astype(float).to_numpy().reshape(shape)
        if "earnings_week" in wide
        else np.zeros(shape)
    )
    dates = pd.DatetimeIndex(wide["date"].to_numpy().reshape(shape)[:, 0])
    errors = np.log(realized[:, :, None] / preds)
    return Arrays(positions, dates, tickers, preds, realized, earnings, errors)


def first_usable(window: int, horizon: int = HORIZON_DAYS) -> int:
    """First row with a full window of known errors behind it."""
    return window + horizon - 1


def error_windows(errors: np.ndarray, idx: np.ndarray, window: int, horizon: int = HORIZON_DAYS) -> np.ndarray:
    """``(B, N, window, K)``: for each row ``t`` in ``idx``, the errors of rows ``t-horizon-window+1 .. t-horizon``."""
    idx = np.asarray(idx)
    if idx.min() < first_usable(window, horizon):
        raise ValueError(f"row {idx.min()} has fewer than {window} known errors behind it")
    offsets = np.arange(-horizon - window + 1, -horizon + 1)
    return errors[idx[:, None] + offsets[None, :]].transpose(0, 2, 1, 3)


def spread(preds: np.ndarray) -> np.ndarray:
    """``log pred_k - mean_k log pred_k``: how far each skill is from the others today."""
    logs = np.log(preds)
    return logs - logs.mean(axis=-1, keepdims=True)


def combine(weights: np.ndarray, preds: np.ndarray) -> np.ndarray:
    """The weighted mean of the skill predictions."""
    return (weights * preds).sum(axis=-1)


def qlike_np(realized: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    ratio = np.square(realized) / np.square(predicted)
    return ratio - np.log(ratio) - 1


def confidence(combined: np.ndarray, realized: np.ndarray, window: int = CONFIDENCE_WINDOW,
               horizon: int = HORIZON_DAYS) -> np.ndarray:
    """``exp(-mean QLIKE)`` of the combination's own last ``window`` known outcomes; 0.5 before any.

    The same rule as ``Supervisor.combine``. Arrays are ``(t, stock)``.
    """
    loss = qlike_np(realized, combined)
    out = np.full(combined.shape, 0.5)
    for t in range(combined.shape[0]):
        hi = t - horizon + 1
        lo = max(0, hi - window)
        if hi > lo:
            part = loss[lo:hi]
            known = np.isfinite(part)
            counts = known.sum(axis=0)
            mean = np.where(known, part, 0.0).sum(axis=0) / np.maximum(counts, 1)
            out[t] = np.where(counts > 0, np.exp(-mean), 0.5)
    return out


class STGNN(nn.Module):
    """GRU over each stock's error window, optional graph layers, softmax head initialised at zero."""

    def __init__(self, n_skills: int, graph_layers: int = 0, hidden: int = HIDDEN):
        super().__init__()
        self.gru = nn.GRU(n_skills, hidden, batch_first=True)
        self.mix = nn.Linear(hidden + n_skills + 1, hidden)
        self.graph_w = nn.ModuleList(nn.Linear(hidden, hidden, bias=False) for _ in range(graph_layers))
        self.gates = nn.Parameter(torch.zeros(graph_layers))
        self.head = nn.Linear(hidden, n_skills)
        nn.init.zeros_(self.head.weight)
        nn.init.zeros_(self.head.bias)

    def forward(self, seq: torch.Tensor, static: torch.Tensor, adjacency: torch.Tensor | None) -> torch.Tensor:
        """``seq`` (B, N, L, K), ``static`` (B, N, K+1), ``adjacency`` (B, N, N) -> weights (B, N, K)."""
        b, n, length, k = seq.shape
        _, h = self.gru(seq.reshape(b * n, length, k))
        state = torch.tanh(self.mix(torch.cat([h[-1].reshape(b, n, -1), static], dim=-1)))
        for gate, layer in zip(self.gates, self.graph_w):
            neighbours = layer(state) if adjacency is None else adjacency @ layer(state)
            state = state + gate * neighbours
        return torch.softmax(self.head(state), dim=-1)


def _batch(data: Arrays, adjacency: np.ndarray | None, idx: np.ndarray, window: int):
    seq = torch.from_numpy(np.ascontiguousarray(error_windows(data.errors, idx, window)))
    static = torch.from_numpy(np.concatenate([spread(data.preds[idx]), data.earnings[idx][..., None]], axis=-1))
    adj = None if adjacency is None else torch.from_numpy(np.ascontiguousarray(adjacency[idx], dtype=float))
    return seq, static, adj


def predict_weights(model: STGNN, data: Arrays, adjacency: np.ndarray | None, idx: np.ndarray,
                    window: int) -> np.ndarray:
    model.eval()
    parts = []
    with torch.no_grad():
        for start in range(0, len(idx), PREDICT_CHUNK):
            parts.append(model(*_batch(data, adjacency, idx[start : start + PREDICT_CHUNK], window)).numpy())
    return np.concatenate(parts)


def new_model(n_skills: int, graph_layers: int, seed: int) -> STGNN:
    torch.manual_seed(seed)
    return STGNN(n_skills, graph_layers).double()


def untrained_weights(data: Arrays, idx: np.ndarray, window: int, graph_layers: int = 0,
                      adjacency: np.ndarray | None = None) -> np.ndarray:
    """The network's weights before any training: 1/K everywhere (gate 2)."""
    return predict_weights(new_model(data.preds.shape[-1], graph_layers, 0), data, adjacency, np.asarray(idx), window)


def fit(data: Arrays, adjacency: np.ndarray | None, train_idx: np.ndarray, window: int, graph_layers: int,
        seed: int, steps: int = STEPS, batch_dates: int = BATCH_DATES) -> STGNN:
    """Train a fresh network on rows ``train_idx`` (all outcomes known): mean QLIKE of the combination."""
    model = new_model(data.preds.shape[-1], graph_layers, seed)
    rng = np.random.default_rng(seed)
    others = [p for name, p in model.named_parameters() if name != "gates"]
    groups = [{"params": others, "lr": LEARNING_RATE}]
    if graph_layers:
        groups.append({"params": [model.gates], "lr": GATE_LEARNING_RATE})
    optimizer = torch.optim.Adam(groups)
    preds = torch.from_numpy(data.preds)
    realized = torch.from_numpy(data.realized)
    model.train()
    for _ in range(steps):
        idx = np.sort(rng.choice(train_idx, size=min(batch_dates, len(train_idx)), replace=False))
        weights = model(*_batch(data, adjacency, idx, window))
        combined = (weights * preds[idx]).sum(dim=-1)
        ratio = realized[idx].square() / combined.square()
        loss = (ratio - torch.log(ratio) - 1).mean()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    return model


@dataclass
class WalkForward:
    weights: np.ndarray  # (end - start + 1, N, K)
    gates: list[float]  # mean |g| after each refit (empty without graph layers)


def walk_forward(data: Arrays, adjacency: np.ndarray | None, start: int, end: int, window: int,
                 graph_layers: int, seed: int, every: int = REFIT_EVERY, steps: int = STEPS,
                 horizon: int = HORIZON_DAYS) -> WalkForward:
    """Weights for rows ``start .. end``: refit every ``every`` rows on the outcomes known then.

    A refit at row ``r`` trains on rows ``first_usable .. r - horizon`` whose outcomes are
    all known, then predicts rows ``r .. r + every - 1``.
    """
    if start < first_usable(window, horizon):
        raise ValueError(f"start row {start} has fewer than {window} known errors behind it")
    known_rows = np.isfinite(data.realized).all(axis=1)
    weights, gates = [], []
    for refit in range(start, end + 1, every):
        train = np.arange(first_usable(window, horizon), refit - horizon + 1)
        train = train[known_rows[train]]
        if len(train) == 0:
            raise ValueError(f"no known outcome to train on before row {refit}")
        model = fit(data, adjacency, train, window, graph_layers, seed, steps)
        if graph_layers:
            gates.append(float(model.gates.detach().abs().mean()))
        idx = np.arange(refit, min(refit + every, end + 1))
        weights.append(predict_weights(model, data, adjacency, idx, window))
    return WalkForward(np.concatenate(weights), gates)
