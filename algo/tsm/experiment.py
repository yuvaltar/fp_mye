"""``python -m tsm.experiment``: score candidate skills without touching the committee.

A full backtest re-runs every skill and takes about 40 minutes on 52 tickers.
A candidate does not need that: the committee's raw predictions are already
saved in ``artifacts/predictions.csv``, so this reads them back and only walks
the candidates forward. The candidate then gets exactly the same calibration,
the same scored dates and the same calibrated HAR-RV baseline as the report.

This command is read-only except for ``docs/experiments.md``. It never writes
``artifacts/``, never writes ``docs/backtest.md`` and never changes
``build_skills``.
"""
from __future__ import annotations

import time
from datetime import date

import pandas as pd

from tsm.backtest import BACKTEST_START, BASELINE_SKILL, TEST_START, calibrate, run_skills
from tsm.config import ARTIFACTS_DIR, DOCS_DIR
from tsm.data import Panel, load_panel
from tsm.models.itransformer import build_candidates
from tsm.report import scored_rows
from tsm.skills.base import TemporalSkill
from tsm.supervisor import qlike

EXPERIMENTS_FILE = DOCS_DIR / "experiments.md"

# One line per model, so the table says what was actually run.
DESCRIPTIONS = {
    "short_term": "HAR-RV on realized volatility (the committee baseline)",
    "regime": "GARCH(1,1) on daily returns",
    "weak_signals": "Gradient boosting on volume, range, gap and SPY-correlation features",
    "multivariate": "neuralforecast iTransformer, MAE on log-volatility",
    "itransformer_mae": "Own PyTorch iTransformer, MAE on log-volatility",
    "itransformer_qlike": "Own PyTorch iTransformer, QLIKE on log-volatility",
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
    candidates: list[TemporalSkill],
    verbose: bool = True,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Walk each candidate forward on the same dates, timing them separately."""
    parts, runtimes = [], {}
    for skill in candidates:
        print(f"Walking {skill.name} forward...", flush=True)
        started = time.time()
        out = run_skills(panel, [skill], start=BACKTEST_START, verbose=verbose)
        runtimes[skill.name] = round(time.time() - started)
        parts.append(out.set_index(["date", "ticker"])[[f"pred_{skill.name}"]])
        print(f"  {skill.name} done in {runtimes[skill.name]}s", flush=True)
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
    table.attrs["scored_rows"] = len(rows)
    table.attrs["scored_dates"] = rows["date"].nunique()
    return table


def _row(name: str, table: pd.DataFrame, runtime: str, today: str) -> str:
    row = table.loc[name]
    label = LABELS.get(name, f"`{name}`")
    return (
        f"| {today} | {label} | {DESCRIPTIONS.get(name, '')} | {row['QLIKE']:.4f} | "
        f"{row['gain']:+.1f}% | {row['factor']:.3f} | {runtime} |"
    )


def append_rows(table: pd.DataFrame, candidate_names: list[str], runtimes: dict[str, int]) -> str:
    """Create the file with the committee rows if missing, then append the candidates."""
    today = date.today().isoformat()
    EXPERIMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not EXPERIMENTS_FILE.exists():
        seeded = [_row(n, table, "—", today) for n in SEED_MODELS if n in table.index]
        EXPERIMENTS_FILE.write_text(
            HEADER.format(test_start=TEST_START) + "\n".join(seeded) + "\n", encoding="utf-8"
        )
    lines = [_row(n, table, f"{runtimes[n]}s", today) for n in candidate_names]
    with EXPERIMENTS_FILE.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return "\n".join(lines)


def main() -> None:
    started = time.time()
    committee, committee_names = load_committee()
    print(f"Read {len(committee)} saved committee predictions for {committee_names}", flush=True)

    panel = load_panel()
    candidates = build_candidates()
    candidate_frame, runtimes = run_candidates(panel, candidates)
    candidate_names = [s.name for s in candidates]

    merged = committee.merge(candidate_frame, on=["date", "ticker"], how="inner", validate="one_to_one")
    if len(merged) != len(committee):
        print(
            f"warning: {len(committee) - len(merged)} of {len(committee)} saved rows had no "
            "candidate prediction and were dropped from the comparison",
            flush=True,
        )

    table = score(merged, committee_names + candidate_names)
    print(f"Scored {table.attrs['scored_rows']} predictions on {table.attrs['scored_dates']} dates")
    print(append_rows(table, candidate_names, runtimes))
    print(f"Wrote {EXPERIMENTS_FILE} in {round(time.time() - started)}s total")


if __name__ == "__main__":
    main()
