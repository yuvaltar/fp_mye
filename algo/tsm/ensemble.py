"""``python -m tsm.ensemble [--seeds 0 1 2]``: combine saved predictions into candidates, no training.

Reads the committee's raw predictions from ``artifacts/predictions.csv`` and the
saved runs of ``itransformer_path_feats`` (``algo/experiments/
itransformer_path_feats_seed<s>.csv``, written by ``python -m tsm.experiment
itransformer_path_feats --seeds 0 1 2``), then builds three combinations, each
fixed before looking at any result:

- ``pair_equal``: the mean of weak_signals and path_feats;
- ``pair_2019``: ``w`` on path_feats and ``1 - w`` on weak_signals, one ``w``
  from 0.0, 0.1, ..., 1.0 chosen on the mean 2019 QLIKE over the seeds (the
  validation year: the test period plays no part in the choice);
- ``committee_v2``: the equal-weight mean of the committee with path_feats in
  place of its iTransformer member (multivariate before Step 11, itransformer
  since), so it is short_term, regime, weak_signals and one path_feats seed
  with either committee.

Every component is calibrated first, a combination is the weighted mean of the
calibrated predictions, and the combination is then calibrated again by the same
rule, so it is scored exactly like any candidate. Each path_feats seed gives its
own combination, so every combination has one row per seed plus a summary row
in ``docs/experiments.md``. Nothing else is written.
"""
from __future__ import annotations

import argparse
import time
import warnings

import pandas as pd

from tsm import experiment
from tsm.backtest import calibrate
from tsm.experiment import append_rows, load_committee, score

COMPONENT = "itransformer_path_feats"
PARTNER = "weak_signals"
# The committee's iTransformer slot, which committee_v2 fills with a single path_feats seed:
# multivariate (neuralforecast) before Step 11, our own itransformer since.
REPLACEABLE = ("itransformer", "multivariate")
SEEDS = (0, 1, 2)
WEIGHTS = tuple(round(0.1 * i, 1) for i in range(11))
COMBINATIONS = ("pair_equal", "pair_2019", "committee_v2")


def component_name(seed: int) -> str:
    return f"{COMPONENT}_seed{seed}"


def load_component(seeds: list[int], experiments_dir=None) -> pd.DataFrame:
    """The saved path_feats predictions, one ``pred_<component>_seed<s>`` column per seed."""
    experiments_dir = experiment.EXPERIMENTS_DIR if experiments_dir is None else experiments_dir
    columns = []
    for seed in seeds:
        path = experiments_dir / f"{component_name(seed)}.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is missing; run python -m tsm.experiment {COMPONENT} "
                f"--seeds {' '.join(str(s) for s in seeds)} first"
            )
        saved = pd.read_csv(path, parse_dates=["date"]).set_index(["date", "ticker"])["prediction"]
        columns.append(saved.rename(f"pred_{component_name(seed)}"))
    return pd.concat(columns, axis=1).reset_index()


def replaced_member(committee: list[str]) -> str:
    """The committee's one iTransformer member, the one committee_v2 swaps for path_feats."""
    present = [name for name in REPLACEABLE if name in committee]
    if len(present) != 1:
        raise ValueError(f"expected exactly one of {', '.join(REPLACEABLE)} in the committee, found {present}")
    return present[0]


def mix(calibrated: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted sum of calibrated ``pred_*`` columns (the weights sum to 1)."""
    return sum(weight * calibrated[column] for column, weight in weights.items())


def build(frame: pd.DataFrame, committee: list[str], seeds: list[int]) -> pd.DataFrame:
    """Add every combination as a ``pred_*`` column, to be calibrated again by ``score``.

    ``frame`` holds the committee's and path_feats's raw predictions. Adds, per
    seed, ``pred_pair_equal_seed<s>``, ``pred_committee_v2_seed<s>`` and one
    ``pred_pair_w<w>_seed<s>`` per weight; pair_2019 is one of the last.
    """
    calibrated = calibrate(frame, committee + [component_name(s) for s in seeds])
    replaced = replaced_member(committee)
    members = [name for name in committee if name != replaced]
    share = 1 / (len(members) + 1)
    added = {}
    for seed in seeds:
        component = f"pred_{component_name(seed)}"
        added[f"pred_pair_equal_seed{seed}"] = mix(calibrated, {f"pred_{PARTNER}": 0.5, component: 0.5})
        added[f"pred_committee_v2_seed{seed}"] = mix(
            calibrated, {**{f"pred_{name}": share for name in members}, component: share}
        )
        for w in WEIGHTS:
            added[f"pred_pair_w{w:.1f}_seed{seed}"] = mix(calibrated, {component: w, f"pred_{PARTNER}": 1 - w})
    return pd.concat([frame, pd.DataFrame(added, index=frame.index)], axis=1)


def choose_weight(table: pd.DataFrame, seeds: list[int]) -> tuple[float, pd.DataFrame]:
    """The ``w`` with the lowest mean 2019 QLIKE over the seeds; a tie goes to the smaller ``w``.

    Also returns the scan, with the test QLIKE alongside for information only.
    """
    scan = pd.DataFrame(
        {
            column: {w: table.loc[[f"pair_w{w:.1f}_seed{s}" for s in seeds], column].mean() for w in WEIGHTS}
            for column in ("QLIKE_2019", "QLIKE")
        }
    )
    return float(scan["QLIKE_2019"].idxmin()), scan


def descriptions(w: float, replaced: str) -> dict[str, str]:
    return {
        "pair_equal": "Mean of calibrated weak_signals and path_feats, calibrated again; no training (seed = path_feats seed)",
        "pair_2019": (
            f"{w:.1f}·path_feats + {1 - w:.1f}·weak_signals, w chosen on mean 2019 QLIKE from 0.0-1.0, "
            "calibrated again; no training"
        ),
        "committee_v2": (
            "Equal-weight mean of short_term, regime, weak_signals and path_feats (in place of "
            f"{replaced}), calibrated again; no training"
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tsm.ensemble",
        description="Combine the committee's and path_feats's saved predictions; no training.",
    )
    parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS), help="path_feats seeds to combine")
    seeds = list(dict.fromkeys(parser.parse_args(argv).seeds))

    started = time.time()
    committee, names = load_committee()
    missing = [n for n in (PARTNER, "short_term") if n not in names]
    if missing:
        raise ValueError(f"the saved committee has no {', '.join(missing)}; re-run python -m tsm.backtest")
    replaced = replaced_member(names)
    frame = committee.merge(load_component(seeds), on=["date", "ticker"], how="inner", validate="one_to_one")
    if len(frame) != len(committee):
        raise ValueError(f"the saved {COMPONENT} runs cover {len(frame)} of {len(committee)} committee rows")

    built = build(frame, names, seeds)
    combos = [c.removeprefix("pred_") for c in built.columns if c.startswith(("pred_pair_", "pred_committee_v2_"))]
    with warnings.catch_warnings():
        # calibrate adds two columns per model, ~90 here; pandas warns about the fragmented frame.
        warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
        table = score(built, names + [component_name(s) for s in seeds] + combos)
    w, scan = choose_weight(table, seeds)
    print("w on path_feats -> mean QLIKE over the seeds (2019 decides; test shown for information):")
    for weight, row in scan.iterrows():
        mark = "  <- chosen" if weight == w else ""
        print(f"  w={weight:.1f}  2019 {row['QLIKE_2019']:.4f}  test {row['QLIKE']:.4f}{mark}")

    for seed in seeds:
        table.loc[f"pair_2019_seed{seed}"] = table.loc[f"pair_w{w:.1f}_seed{seed}"]
    runs = [(f"{name}_seed{seed}", name, seed) for name in COMBINATIONS for seed in seeds]
    print(append_rows(table, runs, {label: None for label, _, _ in runs}, seeds, descriptions(w, replaced)))
    print(f"Wrote {experiment.EXPERIMENTS_FILE} in {round(time.time() - started)}s")


if __name__ == "__main__":
    main()
