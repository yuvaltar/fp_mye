"""Walk-forward backtest and the pipeline that produces the engine's output.

For every evaluation date the skills only receive the prices known on that
date, predict the next 5 trading days, and are scored later against what
really happened. ``python -m tsm.backtest`` runs it on real data, saves the
predictions the API serves, and writes the report.
"""
from __future__ import annotations

import json
import time
from itertools import product

import numpy as np
import pandas as pd

from tsm.config import ARTIFACTS_DIR, HORIZON_DAYS, MODEL_VERSION
from tsm.data import Panel, load_panel, truncate_panel
from tsm.skills.base import TemporalSkill
from tsm.supervisor import Supervisor, build_skills, qlike
from tsm.target import forward_realized_vol, realized_vol

BACKTEST_START = "2018-01-01"  # first evaluation date (three years of history before it)
TEST_START = "2020-01-01"  # results are reported from here; earlier dates tune the supervisor
BASELINE_SKILL = "short_term"  # the HAR-RV skill doubles as the baseline

WINDOW_GRID = (10, 20, 60, 120)
TEMPERATURE_GRID = (0.02, 0.05, 0.1, 0.25, 1.0)

CALIBRATION_WINDOW = 250  # trading days of already-known outcomes used to calibrate a skill


def run_skills(
    panel: Panel,
    skills: list[TemporalSkill],
    start: str = BACKTEST_START,
    step: int = 1,
    verbose: bool = False,
) -> pd.DataFrame:
    """Walk forward through time and collect every skill's predictions.

    Returns one row per (date, ticker) with columns ``position`` and ``pred_<skill>``.
    """
    dates = next(iter(panel.values())).index
    first = int(dates.searchsorted(pd.Timestamp(start)))
    positions = list(range(len(dates) - 1, first - 1, -step))[::-1]
    last_fit: dict[str, int] = {}
    rows = []
    for count, position in enumerate(positions):
        known = truncate_panel(panel, position)
        row = {ticker: {"date": dates[position], "ticker": ticker, "position": position} for ticker in panel}
        for skill in skills:
            if skill.name not in last_fit or position - last_fit[skill.name] >= skill.refit_every_days:
                skill.fit(known)
                last_fit[skill.name] = position
            for ticker, value in skill.predict(known).items():
                row[ticker][f"pred_{skill.name}"] = value
        rows.extend(row.values())
        if verbose and count % 250 == 0:
            print(f"  {dates[position].date()} ({count + 1}/{len(positions)})", flush=True)
    return pd.DataFrame(rows)


def calibration_factors(
    frame: pd.DataFrame,
    skill_names: list[str],
    window: int = CALIBRATION_WINDOW,
    horizon: int = HORIZON_DAYS,
) -> dict[str, pd.Series]:
    """One scale factor per skill and per evaluation date: ``sqrt(mean((realized / predicted)^2))``.

    Skills trained on log-volatility or with MAE predict too low on average, and
    QLIKE punishes under-prediction, so without this the report would rank models
    by their bias rather than their skill.

    The factor for a date uses only predictions whose 5-day outcome was already
    known on that date (position <= position - ``horizon``), pooled over all
    tickers, limited to the last ``window`` trading days of them. With fewer known
    days it uses all of them; with none the factor is 1.

    Returns one Series per skill, indexed by position.
    """
    realized = frame["realized_vol"].to_numpy(dtype=float)
    positions = frame["position"].to_numpy()
    dates = np.sort(frame["position"].unique())
    # Eligible positions for each date: the known ones, capped at the last ``window`` days.
    hi = np.searchsorted(dates, dates - horizon, side="right")
    lo = np.maximum(0, hi - window)

    factors = {}
    for name in skill_names:
        predicted = frame[f"pred_{name}"].to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio_sq = np.square(realized / predicted)
        valid = np.isfinite(ratio_sq)
        totals = pd.DataFrame(
            {"position": positions, "sum": np.where(valid, ratio_sq, 0.0), "count": valid.astype(float)}
        )
        per_date = totals.groupby("position")[["sum", "count"]].sum().reindex(dates, fill_value=0.0)
        cum_sum = np.concatenate([[0.0], per_date["sum"].to_numpy().cumsum()])
        cum_count = np.concatenate([[0.0], per_date["count"].to_numpy().cumsum()])
        total, count = cum_sum[hi] - cum_sum[lo], cum_count[hi] - cum_count[lo]
        mean = np.divide(total, count, out=np.ones_like(total), where=count > 0)
        factors[name] = pd.Series(np.sqrt(mean), index=dates)
    return factors


def calibrate(
    frame: pd.DataFrame,
    skill_names: list[str],
    window: int = CALIBRATION_WINDOW,
    horizon: int = HORIZON_DAYS,
) -> pd.DataFrame:
    """Scale every skill's prediction by its calibration factor, keeping the raw value.

    Adds ``raw_pred_<skill>`` (what the skill said) and ``c_<skill>`` (the factor
    used on that date) and replaces ``pred_<skill>`` with the calibrated value.
    """
    frame = frame.copy()
    factors = calibration_factors(frame, skill_names, window=window, horizon=horizon)
    for name in skill_names:
        frame[f"raw_pred_{name}"] = frame[f"pred_{name}"]
        frame[f"c_{name}"] = frame["position"].map(factors[name])
        frame[f"pred_{name}"] = frame[f"raw_pred_{name}"] * frame[f"c_{name}"]
    return frame


def add_targets_and_baselines(frame: pd.DataFrame, panel: Panel, skill_names: list[str]) -> pd.DataFrame:
    """Add what really happened, calibrate the skills, then build the baselines.

    The HAR-RV baseline is ``pred_short_term`` after calibration, so it gets the
    same treatment as every other skill and the comparison stays fair.
    """
    frame = frame.copy()
    realized, naive = [], []
    for ticker, group in frame.groupby("ticker", sort=False):
        close = panel[ticker]["close"]
        realized.append(pd.Series(forward_realized_vol(close).to_numpy()[group["position"]], index=group.index))
        naive.append(pd.Series(realized_vol(close).to_numpy()[group["position"]], index=group.index))
    frame["realized_vol"] = pd.concat(realized)
    frame["naive"] = pd.concat(naive)
    frame = calibrate(frame, skill_names)
    frame["equal_weight"] = frame[[f"pred_{s}" for s in skill_names]].mean(axis=1)
    frame["baseline"] = frame[f"pred_{BASELINE_SKILL}"]
    return frame


def apply_supervisor(frame: pd.DataFrame, supervisor: Supervisor, skill_names: list[str]) -> pd.DataFrame:
    """Add the supervisor's weights, combined prediction and confidence, ticker by ticker."""
    parts = []
    for _, group in frame.groupby("ticker", sort=False):
        preds = group[[f"pred_{s}" for s in skill_names]].rename(columns=lambda c: c.removeprefix("pred_"))
        parts.append(supervisor.combine(preds, group["realized_vol"], group["position"].to_numpy()))
    return frame.drop(columns=[c for c in parts[0].columns if c in frame.columns]).join(pd.concat(parts))


def tune_supervisor(frame: pd.DataFrame, skill_names: list[str], before: str = TEST_START) -> Supervisor:
    """Pick the window and temperature with the lowest QLIKE on dates before the test period.

    Only predictions whose 5-day outcome was known before the test period take part.
    """
    cutoff = frame.loc[frame["date"] < pd.Timestamp(before), "position"].max() - HORIZON_DAYS
    tuning = frame[frame["position"] <= cutoff]
    best, best_loss = Supervisor(), np.inf
    for window, temperature in product(WINDOW_GRID, TEMPERATURE_GRID):
        candidate = Supervisor(window=window, temperature=temperature)
        scored = apply_supervisor(tuning, candidate, skill_names)
        loss = qlike(scored["realized_vol"], scored["supervisor"]).mean()
        if loss < best_loss:
            best, best_loss = candidate, loss
    return best


def run_pipeline(panel: Panel, skills: list[TemporalSkill], step: int = 1, verbose: bool = False):
    """Full backtest: skills, baselines, tuned supervisor. Returns (frame, supervisor)."""
    names = [s.name for s in skills]
    frame = add_targets_and_baselines(run_skills(panel, skills, step=step, verbose=verbose), panel, names)
    supervisor = tune_supervisor(frame, names)
    return apply_supervisor(frame, supervisor, names), supervisor


def main() -> None:
    from tsm.report import write_report

    started = time.time()
    panel = load_panel()
    skills = build_skills()
    print(f"Walk-forward backtest on {len(panel)} tickers...", flush=True)
    frame, supervisor = run_pipeline(panel, skills, verbose=True)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(ARTIFACTS_DIR / "predictions.csv", index=False, float_format="%.6f")
    meta = {
        "model_version": MODEL_VERSION,
        "skills": [{"name": s.name, "horizon": s.horizon} for s in skills],
        "supervisor": {"window": supervisor.window, "temperature": supervisor.temperature},
        "test_start": TEST_START,
        "calibration_window": CALIBRATION_WINDOW,
        "last_date": str(frame["date"].max().date()),
        "runtime_seconds": round(time.time() - started),
    }
    (ARTIFACTS_DIR / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    write_report(frame, meta)
    print(f"Done in {meta['runtime_seconds']}s. Supervisor: {meta['supervisor']}")


if __name__ == "__main__":
    main()
