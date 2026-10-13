"""``python -m tsm.earnings_layer``: an earnings layer on top of the committee. Experiment only.

Nothing is retrained and nothing in ``build_skills``, ``artifacts/`` or
``docs/backtest.md`` changes: every variant starts from the committee's saved raw
predictions (``artifacts/predictions.csv``) and the frozen price cache, and is
rebuilt downstream exactly as the backtest does (``add_targets_and_baselines``,
``tune_supervisor`` on pre-2020 dates, ``apply_supervisor``).

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
import time
import warnings

import numpy as np
import pandas as pd

from tsm.backtest import (
    BASELINE_SKILL,
    CALIBRATION_WINDOW,
    TEST_START,
    add_targets_and_baselines,
    apply_supervisor,
    calibrate,
    calibration_factors,
    tune_supervisor,
)
from tsm.config import ARTIFACTS_DIR, HORIZON_DAYS, TRADING_DAYS_PER_YEAR
from tsm.data import Panel
from tsm.earnings import load_earnings, to_trading_day
from tsm.experiment import append_rows, load_committee, load_frozen_panel, validation_rows
from tsm.report import scored_rows
from tsm.supervisor import qlike

VARIANTS = ("jump", "split")
SHRINK = 4  # weight n / (n + SHRINK) on a ticker's own reactions
ORDINARY_WINDOW = 250  # trading days of ordinary returns behind each reaction
CALENDAR_EXTENSION = 10  # business days added after the last price day, for releases just after it
DESCRIPTIONS = {
    "jump": "Earnings layer A (jump): + 252/5·J to the variance in earnings weeks, then calibrated",
    "split": "Earnings layer B (split calibration): earnings and ordinary weeks calibrated separately",
}


# ---------------------------------------------------------------- reaction days and earnings weeks

def trading_calendar(days: pd.DatetimeIndex, extra: int = CALENDAR_EXTENSION) -> pd.DatetimeIndex:
    """The price calendar plus a few business days after its end (holidays there are ignored).

    Only the last few forecasts, whose outcome is unknown and never scored, can
    look past the last price day.
    """
    return days.append(pd.bdate_range(days[-1] + pd.offsets.BDay(1), periods=extra))


def reaction_positions(releases: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Per ticker, the sorted calendar positions of its reaction days.

    ``releases`` has ``ticker``, ``date`` (midnight) and ``timing``.
    """
    out = {}
    inside = releases[(releases["date"] >= calendar[0]) & (releases["date"] <= calendar[-1])]
    for ticker, group in inside.groupby("ticker"):
        first = to_trading_day(group["date"], calendar)
        on_trading_day = calendar[np.minimum(first, len(calendar) - 1)] == group["date"].to_numpy()
        after_close = (group["timing"].to_numpy() == "after_close") & on_trading_day
        positions = first + after_close.astype(int)
        out[ticker] = np.unique(positions[positions < len(calendar)])
    return out


def earnings_weeks(frame: pd.DataFrame, reactions: dict[str, np.ndarray], horizon: int = HORIZON_DAYS) -> np.ndarray:
    """True where the forecast made on day p has a reaction day in p+1..p+horizon."""
    flags = np.zeros(len(frame), dtype=bool)
    positions = frame["position"].to_numpy()
    for ticker, rows in frame.groupby("ticker", sort=False).indices.items():
        days = reactions.get(ticker, np.empty(0, dtype=int))
        if days.size == 0:
            continue
        p = positions[rows]
        nxt = np.searchsorted(days, p, side="right")  # first reaction strictly after p
        flags[rows] = (nxt < days.size) & (days[np.minimum(nxt, days.size - 1)] <= p + horizon)
    return flags


# ---------------------------------------------------------------- variant A: the jump

def reaction_excess(close: pd.Series, reactions: np.ndarray, window: int = ORDINARY_WINDOW) -> pd.DataFrame:
    """Per reaction day d: r_d^2 minus the mean r^2 of the ordinary days in d-window..d-1.

    Uses prices up to and including d only. Reactions without ``window`` trading
    days of returns before them are left out.
    """
    squared = np.square(np.log(close / close.shift(1)).to_numpy())
    days = reactions[reactions < len(squared)]
    ordinary = np.ones(len(squared), dtype=bool)
    ordinary[days] = False
    ordinary[0] = False  # no return on the first day
    sums = np.concatenate([[0.0], np.cumsum(np.where(ordinary, squared, 0.0))])
    counts = np.concatenate([[0], np.cumsum(ordinary)])
    days = days[days >= window + 1]  # a full window of returns behind it
    base = (sums[days] - sums[days - window]) / np.maximum(counts[days] - counts[days - window], 1)
    return pd.DataFrame({"day": days, "excess": squared[days] - base})


def jump_sizes(frame: pd.DataFrame, panel: Panel, reactions: dict[str, np.ndarray]) -> np.ndarray:
    """Shrunk J for every row of ``frame``, from reactions on or before its day p."""
    positions = np.sort(frame["position"].unique())
    tickers = list(panel)
    own = np.full((len(positions), len(tickers)), np.nan)  # floored mean excess per ticker, NaN if none yet
    count = np.zeros((len(positions), len(tickers)))
    for j, ticker in enumerate(tickers):
        excess = reaction_excess(panel[ticker]["close"], reactions.get(ticker, np.empty(0, dtype=int)))
        if excess.empty:
            continue
        known = np.searchsorted(excess["day"].to_numpy(), positions, side="right")  # reactions with day <= p
        running = np.concatenate([[np.nan], np.cumsum(excess["excess"].to_numpy())])
        with np.errstate(invalid="ignore", divide="ignore"):
            own[:, j] = np.maximum(running[known] / known, 0.0)
        count[:, j] = known
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # dates before any reaction: an empty mean, set to 0 below
        overall = np.nanmean(np.where(count > 0, own, np.nan), axis=1)  # mean over tickers with reactions
    overall = np.nan_to_num(overall, nan=0.0)
    weight = count / (count + SHRINK)
    shrunk = weight * np.nan_to_num(own, nan=0.0) + (1 - weight) * overall[:, None]
    rows = np.searchsorted(positions, frame["position"].to_numpy())
    cols = frame["ticker"].map({t: j for j, t in enumerate(tickers)}).to_numpy()
    return shrunk[rows, cols]


def add_jump(frame: pd.DataFrame, skill_names: list[str], jumps: np.ndarray) -> pd.DataFrame:
    """In earnings weeks, ``vol -> sqrt(vol^2 + 252/5 * J)`` for every skill's raw prediction."""
    frame = frame.copy()
    week = frame["earnings_week"].to_numpy()
    for name in skill_names:
        vol = frame[f"pred_{name}"].to_numpy()
        adjusted = np.sqrt(np.square(vol) + TRADING_DAYS_PER_YEAR / HORIZON_DAYS * jumps)
        frame[f"pred_{name}"] = np.where(week, adjusted, vol)
    return frame


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
    ``variant`` is "none" (the committee as it is), "jump" or "split".
    """
    if variant not in ("none", *VARIANTS):
        raise ValueError(f"variant must be none, jump or split, got {variant!r}")
    frame = raw[["date", "ticker", "position", *[f"pred_{s}" for s in skill_names]]].copy()
    frame["earnings_week"] = earnings_weeks(frame, reactions)
    calibrator = calibrate
    if variant == "jump":
        frame = add_jump(frame, skill_names, jump_sizes(frame, panel, reactions))
    elif variant == "split":
        calibrator = split_calibrate
    frame = add_targets_and_baselines(frame, panel, skill_names, calibrator=calibrator)
    supervisor = tune_supervisor(frame, skill_names, before=tune_before)
    return apply_supervisor(frame, supervisor, skill_names), supervisor


def scores(frame: pd.DataFrame, skill_names: list[str]) -> pd.DataFrame:
    """QLIKE per model: test, 2019, and test split into earnings and ordinary weeks."""
    test, val = scored_rows(frame, TEST_START), validation_rows(frame)
    week = test["earnings_week"].astype(bool)
    models = {name: f"pred_{name}" for name in skill_names} | {"equal_weight": "equal_weight", "supervisor": "supervisor"}
    table = {}
    for model, column in models.items():
        loss = qlike(test["realized_vol"], test[column])
        table[model] = {
            "QLIKE": loss.mean(),
            "QLIKE_2019": qlike(val["realized_vol"], val[column]).mean(),
            "QLIKE_earnings": loss[week].mean(),
            "QLIKE_ordinary": loss[~week].mean(),
            "factor": test[f"c_{model}"].mean() if f"c_{model}" in test else np.nan,
        }
    out = pd.DataFrame(table).T
    out.attrs["earnings_share"] = float(week.mean())
    return out


def load_reactions(calendar: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Reaction days from the saved Yahoo dates (``python -m tsm.earnings``)."""
    try:
        releases = load_earnings("yahoo")
    except FileNotFoundError as error:
        raise FileNotFoundError(f"{error}; run python -m tsm.earnings first") from None
    return reaction_positions(releases, calendar)


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

    results, supervisors = {}, {}
    for variant in ("none", *VARIANTS):
        frame, supervisor = run_variant(committee, panel, names, reactions, variant)
        results[variant], supervisors[variant] = scores(frame, names), supervisor
        print(f"{variant}: supervisor window {supervisor.window}, temperature {supervisor.temperature}", flush=True)
        if variant == "none":
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
