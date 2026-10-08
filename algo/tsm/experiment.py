"""``python -m tsm.experiment [names...] [--seeds N ...]``: score candidates, not the committee.

A full backtest re-runs every skill and takes about 40 minutes on 52 tickers.
A candidate does not need that: the committee's raw predictions are already
saved in ``artifacts/predictions.csv``, so this reads them back and only walks
the candidates forward. The candidate then gets exactly the same calibration,
the same scored dates and the same calibrated HAR-RV baseline as the report.

With no names it runs every candidate. With several seeds it runs each
candidate once per seed and adds a summary row with the mean and the spread,
because a single seed says little about a network this small.

This command is read-only except for ``docs/experiments.md`` and the
git-ignored ``algo/experiments/``. It never writes ``artifacts/``, never writes
``docs/backtest.md`` and never changes ``build_skills``.
"""
from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

import pandas as pd

from tsm.backtest import BACKTEST_START, BASELINE_SKILL, TEST_START, calibrate, run_skills
from tsm.config import ARTIFACTS_DIR, DOCS_DIR
from tsm.data import Panel, load_panel
from tsm.models.itransformer import CANDIDATES, build_candidate
from tsm.report import scored_rows
from tsm.skills.base import TemporalSkill
from tsm.supervisor import qlike

EXPERIMENTS_FILE = DOCS_DIR / "experiments.md"
# Per-candidate predictions, kept out of git: they are reproducible from a seed.
EXPERIMENTS_DIR = Path(__file__).resolve().parents[1] / "experiments"

# One line per model, so the table says what was actually run.
DESCRIPTIONS = {
    "short_term": "HAR-RV on realized volatility (the committee baseline)",
    "regime": "GARCH(1,1) on daily returns",
    "weak_signals": "Gradient boosting on volume, range, gap and SPY-correlation features",
    "multivariate": "neuralforecast iTransformer, MAE on log-volatility",
    "itransformer_mae": "Own PyTorch iTransformer, MAE on log-volatility",
    "itransformer_qlike": "Own PyTorch iTransformer, QLIKE on log-volatility",
    "itransformer_mae_path": "Own PyTorch iTransformer, 5-step path head, MAE over the 5 steps",
    "itransformer_qlike_path": "Own PyTorch iTransformer, 5-step path head, QLIKE over the 5 steps",
}
SEED_MODELS = ["short_term", "regime", "weak_signals", "multivariate"]
LABELS = {"short_term": "HAR-RV (short_term)"}

HEADER = """# Experiments

One row per candidate model, appended by `python -m tsm.experiment`. Do not edit by hand.

Every row is scored the same way as `backtest.md`: the candidate is calibrated with the same
factor rule, scored from {test_start} on the dates whose 5-day outcome is known, and compared with the
calibrated HAR-RV baseline. The committee's own predictions are read back from
`algo/artifacts/predictions.csv` rather than recomputed, so the comparison is against exactly the
numbers in the committed report.

A candidate appearing here is **not** part of the committee. `build_skills` is unchanged until an
experiment earns a place in it.

The four committee rows were seeded from the committed backtest and were not timed individually,
so their runtime reads as a dash.

| Date | Experiment | Description | QLIKE | vs HAR-RV | Mean factor | Runtime |
| --- | --- | --- | ---: | ---: | ---: | ---: |
"""


def load_committee(artifacts_dir=ARTIFACTS_DIR) -> tuple[pd.DataFrame, list[str]]:
    """The committee's raw (uncalibrated) predictions, read back from the artifacts.

    Returns the frame with the raw columns renamed to ``pred_<skill>`` so that
    ``calibrate`` treats them as its input, plus the skill names.
    """
    frame = pd.read_csv(artifacts_dir / "predictions.csv", parse_dates=["date"])
    names = [c.removeprefix("raw_pred_") for c in frame.columns if c.startswith("raw_pred_")]
    if not names:
        raise ValueError(
            f"{artifacts_dir / 'predictions.csv'} has no raw_pred_* columns; "
            "re-run python -m tsm.backtest first"
        )
    keep = ["date", "ticker", "position", "realized_vol"] + [f"raw_pred_{n}" for n in names]
    renamed = {f"raw_pred_{n}": f"pred_{n}" for n in names}
    return frame[keep].rename(columns=renamed), names


def run_candidates(
    panel: Panel,
    skills: list[TemporalSkill],
    verbose: bool = True,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Walk each candidate forward on the same dates, timing and saving them separately."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    parts, runtimes = [], {}
    for skill in skills:
        print(f"Walking {skill.name} forward...", flush=True)
        started = time.time()
        out = run_skills(panel, [skill], start=BACKTEST_START, verbose=verbose)
        runtimes[skill.name] = round(time.time() - started)
        column = f"pred_{skill.name}"
        path = EXPERIMENTS_DIR / f"{skill.name}.csv"
        out[["date", "ticker", column]].rename(columns={column: "prediction"}).to_csv(
            path, index=False, float_format="%.6f"
        )
        parts.append(out.set_index(["date", "ticker"])[[column]])
        print(f"  {skill.name} done in {runtimes[skill.name]}s -> {path.name}", flush=True)
    return pd.concat(parts, axis=1).reset_index(), runtimes


def score(frame: pd.DataFrame, names: list[str], test_start: str = TEST_START) -> pd.DataFrame:
    """Calibrate every model the same way, then score from ``test_start``."""
    calibrated = calibrate(frame, names)
    rows = scored_rows(calibrated, test_start)
    baseline = qlike(rows["realized_vol"], rows[f"pred_{BASELINE_SKILL}"]).mean()
    table = pd.DataFrame(
        {
            "QLIKE": {n: qlike(rows["realized_vol"], rows[f"pred_{n}"]).mean() for n in names},
            "factor": {n: rows[f"c_{n}"].mean() for n in names},
        }
    )
    table["gain"] = 100 * (1 - table["QLIKE"] / baseline)
    table.attrs["baseline"] = float(baseline)
    table.attrs["scored_rows"] = len(rows)
    table.attrs["scored_dates"] = rows["date"].nunique()
    return table


def _row(label: str, experiment: str, description: str, row, runtime: str, today: str) -> str:
    return (
        f"| {today} | {experiment} | {description} | {row['QLIKE']:.4f} | "
        f"{row['gain']:+.1f}% | {row['factor']:.3f} | {runtime} |"
    )


def _summary_row(name: str, labels: list[str], table: pd.DataFrame, runtimes, seeds, today: str) -> str:
    """Mean QLIKE over the seeds, with the min-to-max spread spelled out."""
    part = table.loc[labels]
    mean_qlike = part["QLIKE"].mean()
    baseline = table.attrs["baseline"]
    row = {
        "QLIKE": mean_qlike,
        "gain": 100 * (1 - mean_qlike / baseline),
        "factor": part["factor"].mean(),
    }
    seed_list = ", ".join(str(s) for s in seeds)
    description = (
        f"Mean over seeds {seed_list}; QLIKE spread {part['QLIKE'].min():.4f} to "
        f"{part['QLIKE'].max():.4f} (width {part['QLIKE'].max() - part['QLIKE'].min():.4f})"
    )
    total = sum(runtimes[label] for label in labels)
    return _row(name, f"**`{name}` mean of {len(labels)} seeds**", description, row, f"{total}s total", today)


def append_rows(
    table: pd.DataFrame,
    runs: list[tuple[str, str, int]],
    runtimes: dict[str, int],
    seeds: list[int],
) -> str:
    """Create the file with the committee rows if missing, then append this run's rows."""
    today = date.today().isoformat()
    EXPERIMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not EXPERIMENTS_FILE.exists():
        seeded = [
            _row(n, LABELS.get(n, f"`{n}`"), DESCRIPTIONS.get(n, ""), table.loc[n], "—", today)
            for n in SEED_MODELS
            if n in table.index
        ]
        EXPERIMENTS_FILE.write_text(
            HEADER.format(test_start=TEST_START) + "\n".join(seeded) + "\n", encoding="utf-8"
        )

    lines = []
    for label, name, seed in runs:
        experiment = f"`{name}` (seed {seed})" if len(seeds) > 1 else f"`{name}`"
        lines.append(_row(label, experiment, DESCRIPTIONS.get(name, ""), table.loc[label], f"{runtimes[label]}s", today))
    if len(seeds) > 1:
        for name in dict.fromkeys(name for _, name, _ in runs):
            labels = [label for label, n, _ in runs if n == name]
            lines.append(_summary_row(name, labels, table, runtimes, seeds, today))

    with EXPERIMENTS_FILE.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tsm.experiment",
        description="Score candidate skills against the committee's saved predictions.",
    )
    parser.add_argument(
        "names", nargs="*", help=f"candidates to run (default: all of {', '.join(CANDIDATES)})"
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[0], help="seeds to run each candidate with"
    )
    args = parser.parse_args(argv)
    names = args.names or list(CANDIDATES)
    seeds = list(dict.fromkeys(args.seeds))

    # Fail on a bad name before spending minutes on the walk-forward.
    runs, skills = [], []
    for name in names:
        for seed in seeds:
            label = name if len(seeds) == 1 else f"{name}_seed{seed}"
            skill = build_candidate(name, seed=seed)
            skill.name = label
            runs.append((label, name, seed))
            skills.append(skill)

    started = time.time()
    committee, committee_names = load_committee()
    print(f"Read {len(committee)} saved committee predictions for {committee_names}", flush=True)
    print(f"Running {len(skills)} run(s): {', '.join(label for label, _, _ in runs)}", flush=True)

    panel = load_panel()
    candidate_frame, runtimes = run_candidates(panel, skills)

    merged = committee.merge(candidate_frame, on=["date", "ticker"], how="inner", validate="one_to_one")
    if len(merged) != len(committee):
        print(
            f"warning: {len(committee) - len(merged)} of {len(committee)} saved rows had no "
            "candidate prediction and were dropped from the comparison",
            flush=True,
        )

    table = score(merged, committee_names + [label for label, _, _ in runs])
    print(f"Scored {table.attrs['scored_rows']} predictions on {table.attrs['scored_dates']} dates")
    print(append_rows(table, runs, runtimes, seeds))
    print(f"Wrote {EXPERIMENTS_FILE} in {round(time.time() - started)}s total")


if __name__ == "__main__":
    main()
