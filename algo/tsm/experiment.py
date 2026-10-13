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

Prices are frozen: it reads the ``algo/data/`` cache as it is and never
downloads, because the committee it is compared with was built from those
prices. A fresh download adds days and shifts adjusted closes, which would make
a candidate's numbers incomparable with the saved ones. A missing cache file
stops the run, and so does a cache whose last date is not the artifacts'
``last_date``. The VIX (``^VIX``) is part of that frozen cache, checked the same
way; it is frozen once with ``--freeze-vix`` and reaches every stock's frame as
a ``vix`` column.

Runs go one after another, never in parallel: splitting torch's threads between
processes changes the floating-point sums, and the numbers stop reproducing
exactly (seed 0 of path_feats gave 0.4925 instead of 0.4924).
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd

from tsm.backtest import BACKTEST_START, BASELINE_SKILL, TEST_START, calibrate, run_skills
from tsm.config import ARTIFACTS_DIR, DOCS_DIR, TICKERS, VIX_TICKER
from tsm.data import Panel, align_panel, freeze_prices, load_prices
from tsm.models.itransformer import CANDIDATES, build_candidate, summarize_gates
from tsm.report import scored_rows
from tsm.skills.base import TemporalSkill
from tsm.supervisor import qlike

EXPERIMENTS_FILE = DOCS_DIR / "experiments.md"
# Written by the backtest with the committee; its last_date is the last price day the artifacts saw.
META_FILE = ARTIFACTS_DIR / "meta.json"
# Per-candidate predictions, kept out of git: they are reproducible from a seed.
EXPERIMENTS_DIR = Path(__file__).resolve().parents[1] / "experiments"

# The validation year: the last full year before the test period, never used to report results.
# Choices between candidates (e.g. which graph mode wins) are made on it, not on the test QLIKE.
VALIDATION_START = "2019-01-01"

# One line per model, so the table says what was actually run.
DESCRIPTIONS = {
    "short_term": "HAR-RV on realized volatility (the committee baseline)",
    "regime": "GARCH(1,1) on daily returns",
    "weak_signals": "Gradient boosting on volume, range, gap and SPY-correlation features",
    "multivariate": "neuralforecast iTransformer, MAE on log-volatility",
    "itransformer": "Committee skill since Step 11: itransformer_path_feats averaged over seeds 0, 1, 2",
    "itransformer_mae": "Own PyTorch iTransformer, MAE on log-volatility",
    "itransformer_qlike": "Own PyTorch iTransformer, QLIKE on log-volatility",
    "itransformer_mae_path": "Own PyTorch iTransformer, 5-step path head, MAE over the 5 steps",
    "itransformer_qlike_path": "Own PyTorch iTransformer, 5-step path head, QLIKE over the 5 steps",
    "itransformer_path_feats": "Own PyTorch iTransformer, 5-step path head, 4 input channels (vol, return, range, volume)",
    "itransformer_path_feats6": "path_feats + 2 channels: overnight gap log(open/prev close) and log VIX close (6 channels)",
    "itransformer_graph_gnn_corr": "path_feats + graph layer h + g·A·Linear(h), market-adjusted correlation map",
    "itransformer_graph_gnn_sector": "path_feats + graph layer h + g·A·Linear(h), sector map",
    "itransformer_graph_gnn_shuffled": "path_feats + graph layer h + g·A·Linear(h), shuffled correlation map (control)",
    "itransformer_graph_bias_corr": "path_feats + attention bias lambda·S per head and layer, market-adjusted correlation map",
    "itransformer_graph_bias_sector": "path_feats + attention bias lambda·S per head and layer, sector map",
    "itransformer_graph_bias_shuffled": "path_feats + attention bias lambda·S per head and layer, shuffled correlation map (control)",
}
# The committee rows a new experiments.md starts with (the committee since Step 11).
SEED_MODELS = ["short_term", "regime", "weak_signals", "itransformer"]
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

**QLIKE 2019** scores the same calibrated predictions on {validation_year} only, before the test
period: choices between candidates are made on it, not on the test QLIKE. **Gate** is how much a
graph model uses the market map after its last refit: `g` for the `gnn` mode, the mean `|λ|` over
heads and layers for the `bias` mode. Rows written before these two columns existed read a dash.

| Date | Experiment | Description | QLIKE | vs HAR-RV | QLIKE 2019 | Mean factor | Gate | Runtime |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
"""
# The table header before the QLIKE 2019 and Gate columns, and where those two columns go.
OLD_TABLE_HEADER = "| Date | Experiment | Description | QLIKE | vs HAR-RV | Mean factor | Runtime |"
NEW_COLUMNS_AT = (5, 7)  # cell positions of QLIKE 2019 and Gate in the new layout


def check_descriptions(names: list[str]) -> None:
    """Refuse to run a model whose row would have a blank description.

    ``DESCRIPTIONS.get(name, "")`` used to fail silently, so a new candidate
    wrote empty cells into the table and the only way to notice was to read the
    file after a 20-minute run. This is checked before the walk-forward starts.
    """
    missing = [n for n in [*names, *SEED_MODELS] if n not in DESCRIPTIONS]
    if missing:
        raise ValueError(
            f"no DESCRIPTIONS entry for {', '.join(sorted(set(missing)))}; "
            f"add one in {__name__} before running, so the table says what was run"
        )


def load_frozen_panel() -> Panel:
    """The prices the committed artifacts were built from: the cache, checked, never a download.

    Every ticker's cache file must end on ``last_date`` in ``artifacts/meta.json``.
    ``python -m tsm.data``, or a backtest on a later day, rewrites the cache with
    more days and re-adjusted closes; candidates walked on that cache would be
    compared with a committee built from other prices, and nothing would fail.
    Each ticker is checked before alignment, because aligning would hide a single
    ticker that was downloaded again.

    The frozen ``^VIX`` series is checked the same way, then added to every
    stock's frame as a ``vix`` column (its close). It does not take part in the
    alignment, so the stocks keep exactly the committee's dates; a stock day
    without a VIX value carries the last known one forward, which only ever uses
    the past.
    """
    last_date = pd.Timestamp(json.loads(META_FILE.read_text())["last_date"])
    frames = {ticker: load_prices(ticker, cache_only=True) for ticker in TICKERS}
    vix = load_prices(VIX_TICKER, cache_only=True)
    mismatched: dict[str, list[str]] = {}
    for ticker, frame in {**frames, VIX_TICKER: vix}.items():
        if frame.index[-1] != last_date:
            mismatched.setdefault(frame.index[-1].date().isoformat(), []).append(ticker)
    if mismatched:
        found = "; ".join(
            f"it ends on {day} for {len(names)} ticker(s) ({', '.join(names[:5])}{', ...' if len(names) > 5 else ''})"
            for day, names in sorted(mismatched.items())
        )
        raise ValueError(
            f"the price cache does not match the committed artifacts: {META_FILE.name} has last_date "
            f"{last_date.date()}, but {found}. Experiments must see the prices the artifacts were "
            "built from: restore that cache, or re-run python -m tsm.backtest to rebuild the "
            "artifacts from the current one."
        )
    panel = align_panel(frames)
    dates = next(iter(panel.values())).index
    vix_close = vix["close"].reindex(vix.index.union(dates)).ffill().reindex(dates)
    if vix_close.isna().any():
        raise ValueError(f"the frozen {VIX_TICKER} series starts after {dates[0].date()}, the first stock day")
    for frame in panel.values():
        frame["vix"] = vix_close.to_numpy()
    return panel


def freeze_vix() -> None:
    """Download ^VIX once into the cache, cut at the artifacts' last_date, and say what it holds."""
    last_date = json.loads(META_FILE.read_text())["last_date"]
    prices = freeze_prices(VIX_TICKER, last_date)
    stocks = align_panel({ticker: load_prices(ticker, cache_only=True) for ticker in TICKERS})
    dates = next(iter(stocks.values())).index
    missing = dates.difference(prices.index)
    print(
        f"Froze {VIX_TICKER}: {len(prices)} days, {prices.index[0].date()} to {prices.index[-1].date()} "
        f"(cut at last_date {last_date}). Stock days without a VIX value, filled from the day before: "
        f"{len(missing)}{' (' + ', '.join(str(d.date()) for d in missing[:10]) + ')' if len(missing) else ''}"
    )


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


def save_gates(skill: TemporalSkill) -> float | None:
    """Write a graph candidate's gates after every refit; return the last refit's summary.

    Saved as ``algo/experiments/<name>_gates.csv`` (git-ignored), one row per refit.
    Returns None for a model without a graph.
    """
    history = getattr(skill, "gate_history_", [])
    if not history:
        return None
    if skill.graph == "gnn":
        columns = ["g"]
    else:
        columns = [f"lambda_l{layer}_h{head}" for layer in range(skill.n_layers) for head in range(skill.n_heads)]
    frame = pd.DataFrame([entry["gates"] for entry in history], columns=columns)
    frame.insert(0, "refit_date", [entry["refit_date"].date() for entry in history])
    frame.to_csv(EXPERIMENTS_DIR / f"{skill.name}_gates.csv", index=False, float_format="%.6f")
    return summarize_gates(skill.graph, history[-1]["gates"])


def run_candidates(
    panel: Panel,
    skills: list[TemporalSkill],
    verbose: bool = True,
) -> tuple[pd.DataFrame, dict[str, int], dict[str, float]]:
    """Walk each candidate forward on the same dates, timing and saving them separately.

    Also returns, for graph candidates, the summary of the gates after the last refit.
    """
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    parts, runtimes, gates = [], {}, {}
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
        summary = save_gates(skill)
        if summary is not None:
            gates[skill.name] = summary
            last = ", ".join(f"{v:+.3f}" for v in skill.gate_history_[-1]["gates"])
            print(f"  gates after the last refit: {last} (summary {summary:.3f})", flush=True)
    return pd.concat(parts, axis=1).reset_index(), runtimes, gates


def validation_rows(frame: pd.DataFrame, start: str = VALIDATION_START, end: str = TEST_START) -> pd.DataFrame:
    """Rows of the validation year whose outcome is known, picked the way ``scored_rows`` picks the test rows."""
    rows = frame[
        (frame["date"] >= pd.Timestamp(start)) & (frame["date"] < pd.Timestamp(end)) & frame["realized_vol"].notna()
    ]
    return rows.dropna()


def score(frame: pd.DataFrame, names: list[str], test_start: str = TEST_START) -> pd.DataFrame:
    """Calibrate every model the same way, then score from ``test_start`` and on the validation year."""
    calibrated = calibrate(frame, names)
    rows = scored_rows(calibrated, test_start)
    validation = validation_rows(calibrated, end=test_start)
    baseline = qlike(rows["realized_vol"], rows[f"pred_{BASELINE_SKILL}"]).mean()
    table = pd.DataFrame(
        {
            "QLIKE": {n: qlike(rows["realized_vol"], rows[f"pred_{n}"]).mean() for n in names},
            "QLIKE_2019": {n: qlike(validation["realized_vol"], validation[f"pred_{n}"]).mean() for n in names},
            "factor": {n: rows[f"c_{n}"].mean() for n in names},
        }
    )
    table["gain"] = 100 * (1 - table["QLIKE"] / baseline)
    table.attrs["baseline"] = float(baseline)
    table.attrs["scored_rows"] = len(rows)
    table.attrs["scored_dates"] = rows["date"].nunique()
    return table


def _row(label: str, experiment: str, description: str, row, runtime: str, today: str) -> str:
    gate = row.get("gate")
    gate_cell = "—" if gate is None or pd.isna(gate) else f"{gate:.3f}"
    # A combination built from calibrated skills (supervisor, equal-weight) has no factor of its own.
    factor_cell = "—" if pd.isna(row["factor"]) else f"{row['factor']:.3f}"
    return (
        f"| {today} | {experiment} | {description} | {row['QLIKE']:.4f} | "
        f"{row['gain']:+.1f}% | {row['QLIKE_2019']:.4f} | {factor_cell} | {gate_cell} | {runtime} |"
    )


def _summary_row(name: str, labels: list[str], table: pd.DataFrame, runtimes, seeds, today: str) -> str:
    """Mean QLIKE over the seeds, with the min-to-max spread spelled out."""
    part = table.loc[labels]
    mean_qlike = part["QLIKE"].mean()
    baseline = table.attrs["baseline"]
    row = {
        "QLIKE": mean_qlike,
        "gain": 100 * (1 - mean_qlike / baseline),
        "QLIKE_2019": part["QLIKE_2019"].mean(),
        "factor": part["factor"].mean(),
        "gate": part["gate"].mean() if "gate" in part and part["gate"].notna().all() else None,
    }
    seed_list = ", ".join(str(s) for s in seeds)
    description = (
        f"Mean over seeds {seed_list}; QLIKE spread {part['QLIKE'].min():.4f} to "
        f"{part['QLIKE'].max():.4f} (width {part['QLIKE'].max() - part['QLIKE'].min():.4f})"
    )
    times = [runtimes.get(label) for label in labels]
    total = "—" if None in times else f"{sum(times)}s total"
    return _row(name, f"**`{name}` mean of {len(labels)} seeds**", description, row, total, today)


def _header() -> str:
    return HEADER.format(test_start=TEST_START, validation_year=VALIDATION_START[:4])


def migrate_table() -> bool:
    """Bring a table written before QLIKE 2019 and Gate existed to the current layout.

    Earlier rows keep every value they had and read a dash in the two new
    columns; the text above the table is regenerated. Returns whether anything
    changed. Rows are written by this module only, so their cells never hold a "|".
    """
    lines = EXPERIMENTS_FILE.read_text(encoding="utf-8").splitlines()
    if OLD_TABLE_HEADER not in lines:
        return False
    start = lines.index(OLD_TABLE_HEADER) + 2  # skip the header and its separator
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        for position in NEW_COLUMNS_AT:
            cells.insert(position, "—")
        rows.append("| " + " | ".join(cells) + " |")
    EXPERIMENTS_FILE.write_text(_header() + "\n".join(rows) + "\n", encoding="utf-8")
    return True


def append_rows(
    table: pd.DataFrame,
    runs: list[tuple[str, str, int]],
    runtimes: dict[str, int | None],
    seeds: list[int],
    descriptions: dict[str, str] | None = None,
) -> str:
    """Create the file with the committee rows if missing, then append this run's rows.

    ``descriptions`` defaults to ``DESCRIPTIONS``; ``tsm.ensemble`` passes its own.
    A runtime of None (nothing was trained) reads as a dash.
    """
    descriptions = DESCRIPTIONS if descriptions is None else descriptions
    today = date.today().isoformat()
    EXPERIMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not EXPERIMENTS_FILE.exists():
        seeded = [
            _row(n, LABELS.get(n, f"`{n}`"), DESCRIPTIONS[n], table.loc[n], "—", today)
            for n in SEED_MODELS
            if n in table.index
        ]
        EXPERIMENTS_FILE.write_text(_header() + "\n".join(seeded) + "\n", encoding="utf-8")
    else:
        migrate_table()

    lines = []
    for label, name, seed in runs:
        experiment = f"`{name}` (seed {seed})" if len(seeds) > 1 else f"`{name}`"
        runtime = "—" if runtimes.get(label) is None else f"{runtimes[label]}s"
        lines.append(_row(label, experiment, descriptions[name], table.loc[label], runtime, today))
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
    parser.add_argument(
        "--freeze-vix", action="store_true", help=f"download {VIX_TICKER} once into the frozen cache, then stop"
    )
    args = parser.parse_args(argv)
    if args.freeze_vix:
        freeze_vix()
        return
    names = args.names or list(CANDIDATES)
    seeds = list(dict.fromkeys(args.seeds))
    # Name first, so an unknown model is not reported as a missing description.
    unknown = [n for n in names if n not in CANDIDATES]
    if unknown:
        raise ValueError(
            f"unknown candidate {', '.join(unknown)}; available: {', '.join(CANDIDATES)}"
        )
    check_descriptions(names)

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
    # The prices the saved committee was built from, checked before anything slow.
    panel = load_frozen_panel()
    committee, committee_names = load_committee()
    print(f"Read {len(committee)} saved committee predictions for {committee_names}", flush=True)
    print(f"Running {len(skills)} run(s): {', '.join(label for label, _, _ in runs)}", flush=True)

    candidate_frame, runtimes, gates = run_candidates(panel, skills)

    merged = committee.merge(candidate_frame, on=["date", "ticker"], how="inner", validate="one_to_one")
    if len(merged) != len(committee):
        print(
            f"warning: {len(committee) - len(merged)} of {len(committee)} saved rows had no "
            "candidate prediction and were dropped from the comparison",
            flush=True,
        )

    table = score(merged, committee_names + [label for label, _, _ in runs])
    table["gate"] = pd.Series(gates, dtype=float)
    print(f"Scored {table.attrs['scored_rows']} predictions on {table.attrs['scored_dates']} dates")
    print(append_rows(table, runs, runtimes, seeds))
    print(f"Wrote {EXPERIMENTS_FILE} in {round(time.time() - started)}s total")


if __name__ == "__main__":
    main()
