"""``python -m tsm.earnings_layer``: an earnings layer on top of the committee. Experiment only.

Nothing is retrained and nothing in ``build_skills``, ``artifacts/`` or
``docs/backtest.md`` changes: every variant starts from the committee's saved raw
predictions (``artifacts/predictions.csv``, each model's own prediction) and the
frozen price cache, and is rebuilt downstream exactly as the backtest does. Since
Step 13 variant A is the product: "none" and "jump" run the backtest's own
``finish_pipeline``, and the jump itself lives in ``tsm.earnings_jump``.

Reaction day of a release: the release day if it comes before the open (or at an
unknown time, or during the session), the next trading day if after the close; a
release on a non-trading day reacts on the next trading day. A forecast made on
day p is an **earnings week** for a ticker when a reaction day falls in
p+1..p+5. Release dates (from Yahoo, ``tsm.earnings``) are assumed known at least
5 trading days ahead, which is exactly what this flag needs.

Two variants, fixed before looking at any result and judged on 2019:

- **jump**: in an earnings week, add one jump to every skill's predicted
  variance, ``vol_adj = sqrt(vol^2 + 252/5 * J)``, then calibrate as usual. ``J``
  is the ticker's expected excess squared log return on a reaction day: the mean
  over its past reactions of (r^2 minus its mean squared return on ordinary days
  of the 250 trading days before), floored at 0, shrunk toward the mean over all
  tickers with weight n/(n+4), n its number of past reactions. Only reactions on
  or before p count, and only those with 250 trading days of prices before them.
- **split**: calibrate earnings weeks and ordinary weeks separately, each with
  the usual rule (last 250 trading days of known outcomes, pooled over tickers).

Rows go to ``docs/experiments.md``: supervisor, equal-weight and each skill, per
variant, scored against the committee's own HAR-RV like every other row.
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from tsm.backtest import (
    BASELINE_SKILL,
    CALIBRATION_WINDOW,
    TEST_START,
    add_targets_and_baselines,
    apply_supervisor,
    calibration_factors,
    finish_pipeline,
    tune_supervisor,
)
from tsm.config import ARTIFACTS_DIR
from tsm.data import Panel
from tsm.earnings_jump import (  # noqa: F401  (re-exported: the jump lives there since Step 13)
    add_jump,
    earnings_weeks,
    jump_sizes,
    load_reactions,
    reaction_excess,
    reaction_positions,
    trading_calendar,
)
from tsm.experiment import append_rows, load_committee, load_frozen_panel
from tsm.report import scored_rows, week_scores

VARIANTS = ("jump", "split")
DESCRIPTIONS = {
    "jump": "Earnings layer A (jump): + 252/5·J to the variance in earnings weeks, then calibrated",
    "split": "Earnings layer B (split calibration): earnings and ordinary weeks calibrated separately",
}


# ---------------------------------------------------------------- variant B: split calibration

def split_calibrate(frame: pd.DataFrame, skill_names: list[str], window: int = CALIBRATION_WINDOW) -> pd.DataFrame:
    """``calibrate``, but with one factor for earnings weeks and one for ordinary weeks.

    Each factor uses the usual rule, restricted to its own kind of week: the last
    ``window`` trading days of outcomes already known, pooled over tickers.
    """
    frame = frame.copy()
    week = frame["earnings_week"].to_numpy()
    for name in skill_names:
        raw = frame[f"pred_{name}"]
        factors = {
            kind: calibration_factors(frame.assign(**{f"pred_{name}": raw.where(mask)}), [name], window=window)[name]
            for kind, mask in (("earnings", week), ("ordinary", ~week))
        }
        factor = np.where(
            week, frame["position"].map(factors["earnings"]), frame["position"].map(factors["ordinary"])
        )
        frame[f"raw_pred_{name}"] = raw
        frame[f"c_{name}"] = factor
        frame[f"pred_{name}"] = raw * factor
    return frame


# ---------------------------------------------------------------- the variants, end to end

def run_variant(
    raw: pd.DataFrame,
    panel: Panel,
    skill_names: list[str],
    reactions: dict[str, np.ndarray],
    variant: str,
    tune_before: str = TEST_START,
) -> tuple[pd.DataFrame, object]:
    """Rebuild everything downstream of the raw predictions, as the backtest does.

    ``raw`` has ``date``, ``ticker``, ``position`` and the raw ``pred_<skill>``.
    ``variant`` is "none" (the committee without the layer), "jump" (the product
    since Step 13) or "split"; "none" and "jump" are the backtest's own
    ``finish_pipeline``. Every frame carries ``earnings_week`` for scoring.
    """
    if variant not in ("none", *VARIANTS):
        raise ValueError(f"variant must be none, jump or split, got {variant!r}")
    frame = raw[["date", "ticker", "position", *[f"pred_{s}" for s in skill_names]]].copy()
    if variant == "jump":
        return finish_pipeline(frame, panel, skill_names, reactions, tune_before=tune_before)
    frame["earnings_week"] = earnings_weeks(frame, reactions)
    if variant == "none":
        return finish_pipeline(frame, panel, skill_names, tune_before=tune_before)
    frame = add_targets_and_baselines(frame, panel, skill_names, calibrator=split_calibrate)
    supervisor = tune_supervisor(frame, skill_names, before=tune_before)
    return apply_supervisor(frame, supervisor, skill_names), supervisor


def scores(frame: pd.DataFrame, skill_names: list[str]) -> pd.DataFrame:
    """QLIKE per model (test, 2019, test by kind of week) and each skill's mean calibration factor."""
    columns = {name: f"pred_{name}" for name in skill_names} | {"equal_weight": "equal_weight", "supervisor": "supervisor"}
    table = week_scores(frame, columns)
    test = scored_rows(frame, TEST_START)
    table["factor"] = [test[f"c_{m}"].mean() if f"c_{m}" in test else np.nan for m in table.index]
    return table


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tsm.earnings_layer", description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    started = time.time()

    panel = load_frozen_panel()
    committee, names = load_committee()
    if BASELINE_SKILL not in names:
        raise ValueError(f"the saved committee has no {BASELINE_SKILL}; re-run python -m tsm.backtest")
    calendar = trading_calendar(next(iter(panel.values())).index)
    reactions = load_reactions(calendar)

    meta = json.loads((ARTIFACTS_DIR / "meta.json").read_text())
    built_with = "jump" if meta.get("earnings", {}).get("enabled") else "none"
    results, supervisors = {}, {}
    for variant in ("none", *VARIANTS):
        frame, supervisor = run_variant(committee, panel, names, reactions, variant)
        results[variant], supervisors[variant] = scores(frame, names), supervisor
        print(f"{variant}: supervisor window {supervisor.window}, temperature {supervisor.temperature}", flush=True)
        if variant == built_with:
            # The committee as saved: the reuse of the backtest's steps must reproduce it.
            saved = pd.read_csv(ARTIFACTS_DIR / "predictions.csv", usecols=["date", "ticker", "supervisor"], parse_dates=["date"])
            check = frame[["date", "ticker", "supervisor"]].merge(saved, on=["date", "ticker"], suffixes=("", "_saved"))
            print(f"  reproduces the saved supervisor: max diff {np.abs(check['supervisor'] - check['supervisor_saved']).max():.1e}")

    baseline = results["none"].loc[BASELINE_SKILL, "QLIKE"]
    print(f"\nEarnings weeks are {results['none'].attrs['earnings_share']:.1%} of the scored test forecasts.")
    print("| Model | Variant | Test QLIKE | 2019 QLIKE | Test, earnings weeks | Test, ordinary weeks |")
    print("| --- | --- | ---: | ---: | ---: | ---: |")
    for model in ("supervisor", "equal_weight", "weak_signals", "itransformer"):
        for variant, label in (("none", "current"), ("jump", "A jump"), ("split", "B split")):
            if model not in results[variant].index:
                continue
            r = results[variant].loc[model]
            print(
                f"| {model} | {label} | {r['QLIKE']:.4f} | {r['QLIKE_2019']:.4f} | "
                f"{r['QLIKE_earnings']:.4f} | {r['QLIKE_ordinary']:.4f} |"
            )

    rows, runs, descriptions = [], [], {}
    for variant in VARIANTS:
        table = results[variant]
        sup = supervisors[variant]
        for model in ("supervisor", "equal_weight", *names):
            key = f"earnings_{variant}:{model}"
            extra = f"; retuned window {sup.window}, temperature {sup.temperature}" if model == "supervisor" else ""
            descriptions[key] = f"{DESCRIPTIONS[variant]}; {model.replace('_', '-')}{extra}"
            row = table.loc[model].copy()
            row["gain"] = 100 * (1 - row["QLIKE"] / baseline)
            rows.append(row.rename(key))
            runs.append((key, key, 0))
    out = pd.DataFrame(rows)
    print(append_rows(out, runs, {key: None for key, _, _ in runs}, [0], descriptions))
    print(f"Done in {round(time.time() - started)}s")



if __name__ == "__main__":
    main()
