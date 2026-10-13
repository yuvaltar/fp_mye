"""Walk-forward backtest and the pipeline that produces the engine's output.

For every evaluation date the skills only receive the prices known on that
date, predict the next 5 trading days, and are scored later against what
really happened. ``python -m tsm.backtest`` runs it on real data, saves the
predictions the API serves, and writes the report. ``--cache-only`` runs it on
the price cache as it is, without downloading, so its numbers stay comparable
with docs/experiments.md (which is scored on that frozen cache).

Since Step 13 the earnings layer is on (``tsm.earnings_jump``): between the
skills and the calibration, a forecast whose next 5 trading days hold an
earnings reaction gets one expected earnings move added to every skill's
variance. ``raw_pred_<skill>`` stays each model's own prediction and the HAR-RV
baseline stays plain HAR-RV. It needs the saved earnings dates
(``python -m tsm.earnings``); ``--no-earnings`` runs the path from before it.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date
from collections.abc import Callable
from itertools import product

import numpy as np
import pandas as pd

from tsm.config import ARTIFACTS_DIR, HORIZON_DAYS, MODEL_VERSION
from tsm.data import Panel, load_panel, truncate_panel
from tsm.earnings_jump import (
    CALENDAR_EXTENSION,
    add_earnings_jump,
    earnings_artifact,
    load_releases,
    reaction_positions,
    trading_calendar,
    without_next_release,
)
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


def add_targets_and_baselines(
    frame: pd.DataFrame,
    panel: Panel,
    skill_names: list[str],
    calibrator: Callable[[pd.DataFrame, list[str]], pd.DataFrame] = calibrate,
) -> pd.DataFrame:
    """Add what really happened, calibrate the skills, then build the baselines.

    The HAR-RV baseline is ``pred_short_term`` after calibration, so it gets the
    same treatment as every other skill and the comparison stays fair.
    ``calibrator`` is ``calibrate`` for the backtest; experiments (tsm.earnings_layer)
    pass another rule and keep every other step exactly as here.
    """
    frame = frame.copy()
    realized, naive = [], []
    for ticker, group in frame.groupby("ticker", sort=False):
        close = panel[ticker]["close"]
        realized.append(pd.Series(forward_realized_vol(close).to_numpy()[group["position"]], index=group.index))
        naive.append(pd.Series(realized_vol(close).to_numpy()[group["position"]], index=group.index))
    frame["realized_vol"] = pd.concat(realized)
    frame["naive"] = pd.concat(naive)
    frame = calibrator(frame, skill_names)
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


def keep_own_predictions(frame: pd.DataFrame, skill_names: list[str]) -> pd.DataFrame:
    """After the earnings jump and calibration: ``raw_pred_<skill>`` back to each model's own
    prediction, and the HAR-RV baseline back to plain HAR-RV (its own prediction, calibrated by
    the usual rule, without the jump), so "vs HAR-RV" stays comparable with every earlier result.
    """
    frame = frame.copy()
    for name in skill_names:
        frame[f"raw_pred_{name}"] = frame.pop(f"own_pred_{name}")
    plain = calibrate(
        frame[["position", "realized_vol", f"raw_pred_{BASELINE_SKILL}"]].rename(
            columns={f"raw_pred_{BASELINE_SKILL}": f"pred_{BASELINE_SKILL}"}
        ),
        [BASELINE_SKILL],
    )
    frame["baseline"] = plain[f"pred_{BASELINE_SKILL}"]
    return frame


def finish_pipeline(
    raw: pd.DataFrame,
    panel: Panel,
    skill_names: list[str],
    reactions: dict[str, np.ndarray] | None = None,
    tune_before: str = TEST_START,
):
    """Everything after the skills' raw predictions. Returns (frame, supervisor).

    With ``reactions`` (earnings reaction days, ``tsm.earnings_jump``) the earnings
    jump goes in before the calibration; without, this is the path from before Step 13.
    """
    frame = raw if reactions is None else add_earnings_jump(raw, panel, skill_names, reactions)
    frame = add_targets_and_baselines(frame, panel, skill_names)
    if reactions is not None:
        frame = keep_own_predictions(frame, skill_names)
    supervisor = tune_supervisor(frame, skill_names, before=tune_before)
    return apply_supervisor(frame, supervisor, skill_names), supervisor


def run_pipeline(
    panel: Panel,
    skills: list[TemporalSkill],
    step: int = 1,
    verbose: bool = False,
    reactions: dict[str, np.ndarray] | None = None,
):
    """Full backtest: skills, (earnings jump), baselines, tuned supervisor. Returns (frame, supervisor)."""
    names = [s.name for s in skills]
    return finish_pipeline(run_skills(panel, skills, step=step, verbose=verbose), panel, names, reactions)


PLACEBO_SHIFT = 20  # trading days the placebo moves every reaction day


def earnings_comparison(
    raw: pd.DataFrame,
    panel: Panel,
    skill_names: list[str],
    reactions: dict[str, np.ndarray],
    frame: pd.DataFrame,
    test_start: str = TEST_START,
) -> dict:
    """For the report: every model without and with the earnings layer, and the placebo.

    The same raw predictions go through the path without the layer, and through
    the layer with every reaction day moved by +-PLACEBO_SHIFT trading days.
    Nothing is retrained; the supervisor is retuned each time.
    """
    from tsm.report import week_scores

    columns = {"supervisor": "supervisor", "equal_weight": "equal_weight", "baseline": "baseline"}
    columns |= {name: f"pred_{name}" for name in skill_names}
    weeks = frame[["date", "ticker", "earnings_week"]]
    before, _ = finish_pipeline(raw, panel, skill_names, tune_before=test_start)
    before = before.merge(weeks, on=["date", "ticker"], validate="one_to_one")  # the same weeks, no jump
    last = len(next(iter(panel.values()))) + CALENDAR_EXTENSION - 1
    placebo = {}
    for shift in (PLACEBO_SHIFT, -PLACEBO_SHIFT):
        moved = {t: np.unique(np.clip(days + shift, 0, last)) for t, days in reactions.items()}
        shifted, _ = finish_pipeline(raw, panel, skill_names, moved, tune_before=test_start)
        placebo[shift] = float(week_scores(shifted, {"supervisor": "supervisor"}, test_start).loc["supervisor", "QLIKE"])
    return {
        "before": week_scores(before, columns, test_start),
        "after": week_scores(frame, columns, test_start),
        "placebo": placebo,
    }


def main(argv: list[str] | None = None) -> None:
    from tsm.report import write_report

    parser = argparse.ArgumentParser(
        prog="python -m tsm.backtest",
        description="Walk-forward backtest: artifacts for the API and docs/backtest.md.",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="use the price cache as it is and never download (the frozen prices of docs/experiments.md)",
    )
    parser.add_argument(
        "--no-earnings",
        action="store_true",
        help="leave out the earnings layer: the path from before Step 13, to reproduce older results",
    )
    args = parser.parse_args(argv)

    started = time.time()
    panel = load_panel(cache_only=args.cache_only)
    skills = build_skills()
    names = [s.name for s in skills]
    reactions = releases = calendar = None
    if not args.no_earnings:
        days = next(iter(panel.values())).index
        releases = load_releases()
        calendar = trading_calendar(days)
        reactions = reaction_positions(releases, calendar)
        never = [t for t in panel if t not in set(releases["ticker"])]
        no_next = [t for t in without_next_release(releases, list(panel), days[-1]) if t not in never]
        if never:
            print(f"No earnings dates at all for {', '.join(never)}: never an earnings week.", flush=True)
        if no_next:
            print(
                f"No scheduled release after {days[-1].date()} for {', '.join(no_next)}: "
                "their latest forecasts get no earnings week.",
                flush=True,
            )
    print(f"Walk-forward backtest on {len(panel)} tickers...", flush=True)
    raw = run_skills(panel, skills, verbose=True)
    frame, supervisor = finish_pipeline(raw, panel, names, reactions)
    earnings = None
    if reactions is not None:
        print("Earnings layer: scoring without it, and with the dates moved (placebo)...", flush=True)
        earnings = earnings_comparison(raw, panel, names, reactions, frame)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(ARTIFACTS_DIR / "predictions.csv", index=False, float_format="%.6f")
    earnings_file = ARTIFACTS_DIR / "earnings.csv"
    if reactions is not None:
        # The report dates the API needs for earnings_date (predictions.csv only has reaction days).
        earnings_artifact(frame, releases, calendar).to_csv(earnings_file, index=False, date_format="%Y-%m-%d")
    elif earnings_file.exists():
        earnings_file.unlink()  # without the layer there is no earnings week to explain
    meta = {
        "model_version": MODEL_VERSION,
        "skills": [{"name": s.name, "horizon": s.horizon} for s in skills],
        "supervisor": {"window": supervisor.window, "temperature": supervisor.temperature},
        "test_start": TEST_START,
        "calibration_window": CALIBRATION_WINDOW,
        "last_date": str(frame["date"].max().date()),
        "generated_at": date.today().isoformat(),
        "cache_only": args.cache_only,
        "earnings": {"enabled": reactions is not None, "known_days_ahead": HORIZON_DAYS, "source": "Yahoo Finance"}
        if reactions is not None
        else {"enabled": False},
        "runtime_seconds": round(time.time() - started),
    }
    (ARTIFACTS_DIR / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    write_report(frame, meta, earnings=earnings)
    print(f"Done in {meta['runtime_seconds']}s. Supervisor: {meta['supervisor']}")


if __name__ == "__main__":
    main()
