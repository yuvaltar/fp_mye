"""``python -m tsm.stgnn [--seeds 0 1 2]``: the ST-GNN supervisor experiment, phase A.

Learns the supervisor's weights with ``tsm.models.stgnn`` on the committee's saved
calibrated predictions (``artifacts/predictions.csv``) and the frozen price cache,
then scores it exactly like the report scores the current supervisor (no
recalibration, ``report.scored_rows`` and ``report.validation_rows``).

The procedure, fixed before any result (``docs/superpowers/specs/2026-10-27-stgnn-phase-a-design.md``):

1. Gates: the current supervisor is reproduced from the saved predictions, the
   untrained network is the equal-weight average, and the frozen panel's dates
   match the predictions' positions. A failed gate stops the run.
2. On 2019 only (quarterly refits, as in the test): the error window L for the
   no-graph network; stop if it does not beat equal weight on 2019. Then one or
   two graph layers for the correlation map. The candidate is the variant with
   the lowest mean 2019 QLIKE.
3. The test period, once: four variants, every seed. Go only if the candidate
   beats the current supervisor, the equal-weight average and the best single
   skill on the mean over seeds, and every seed beats equal weight.

Writes only ``docs/experiments.md`` (test rows), ``docs/stgnn-results.md`` and the
git-ignored ``algo/experiments/``. A hash of the engine's artifacts and of the
supervisor, backtest, report and API modules is taken before and after the run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tsm.backtest import TEST_START, apply_supervisor
from tsm.config import ARTIFACTS_DIR, DOCS_DIR
from tsm.data import Panel
from tsm.experiment import EXPERIMENTS_DIR, append_rows, load_frozen_panel
from tsm.models import stgnn
from tsm.models.graph import correlation_adjacency_series, sector_adjacency
from tsm.models.itransformer import _shuffled
from tsm.report import VALIDATION_END, VALIDATION_START, scored_rows, validation_rows
from tsm.supervisor import Supervisor, qlike

ROOT = Path(__file__).resolve().parents[1]
RESULTS_FILE = DOCS_DIR / "stgnn-results.md"
PROTECTED = [
    *sorted(ARTIFACTS_DIR.glob("*")),
    DOCS_DIR / "backtest.md",
    ROOT / "tsm" / "supervisor.py",
    ROOT / "tsm" / "backtest.py",
    ROOT / "tsm" / "report.py",
    ROOT / "tsm" / "api.py",
]

VARIANTS = ("nograph", "corr", "sector", "shuffled")
WINDOWS = (10, 20, 60)
GRAPH_LAYERS = (1, 2)
DESCRIPTIONS = {
    f"stgnn_{v}": text
    for v, text in {
        "nograph": "ST-GNN supervisor, temporal part only: GRU over each skill's last L errors, softmax head from equal weights",
        "corr": "ST-GNN supervisor: GRU + graph layers H + g·A·H·W on the market-adjusted correlation map",
        "sector": "ST-GNN supervisor: GRU + graph layers on the sector map",
        "shuffled": "ST-GNN supervisor: GRU + graph layers on the correlation map with stocks shuffled (control)",
    }.items()
}
# predictions.csv is written with 6 decimals (backtest.py, float_format="%.6f"): recomputing a saved
# column from saved inputs differs by the rounding, about 1e-6. A misread input would differ by ~1e-2.
GATE_TOLERANCE = 2e-6
BASE_COLUMNS = ["date", "ticker", "position", "realized_vol", "supervisor", "equal_weight", "baseline"]


def file_hashes(paths: list[Path] = PROTECTED) -> dict[str, str]:
    return {str(p): hashlib.md5(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


@dataclass
class Experiment:
    frame: pd.DataFrame  # predictions.csv
    skills: list[str]
    meta: dict
    data: stgnn.Arrays
    panel: Panel | None

    @classmethod
    def load(cls, with_panel: bool = True) -> "Experiment":
        meta = json.loads((ARTIFACTS_DIR / "meta.json").read_text())
        skills = [s["name"] for s in meta["skills"]]
        frame = pd.read_csv(ARTIFACTS_DIR / "predictions.csv", parse_dates=["date"])
        data = stgnn.frame_arrays(frame, skills)
        panel = load_frozen_panel() if with_panel else None
        if panel is not None:
            panel = {t: panel[t] for t in data.tickers}
        return cls(frame, skills, meta, data, panel)

    def rows(self, period: str) -> tuple[int, int]:
        """First and last row index of ``"validation"`` (2019) or ``"test"`` (from TEST_START)."""
        dates = self.data.dates
        if period == "validation":
            inside = (dates >= pd.Timestamp(VALIDATION_START)) & (dates < pd.Timestamp(VALIDATION_END))
        elif period == "test":
            inside = dates >= pd.Timestamp(TEST_START)
        else:
            raise ValueError(f"unknown period {period!r}")
        where = np.flatnonzero(inside)
        return int(where[0]), int(where[-1])

    def adjacency(self, variant: str) -> np.ndarray | None:
        if variant == "nograph":
            return None
        if variant == "sector":
            matrix = sector_adjacency(self.data.tickers)
            return np.broadcast_to(matrix, (len(self.data.positions), *matrix.shape))
        corr = correlation_adjacency_series(self.panel)[self.data.positions]
        if variant == "corr":
            return corr
        if variant == "shuffled":
            return _shuffled(corr)
        raise ValueError(f"unknown variant {variant!r}")


# ---------------------------------------------------------------- gates


def gate_supervisor(exp: Experiment) -> float:
    """Gate 1: the saved ``supervisor`` column, recomputed from the saved calibrated predictions."""
    settings = exp.meta["supervisor"]
    supervisor = Supervisor(window=settings["window"], temperature=settings["temperature"])
    base = exp.frame[["date", "ticker", "position", "realized_vol"] + [f"pred_{s}" for s in exp.skills]]
    redone = apply_supervisor(base, supervisor, exp.skills)
    return float(np.nanmax(np.abs(redone["supervisor"].to_numpy() - exp.frame["supervisor"].to_numpy())))


def gate_equal_weight(exp: Experiment, window: int = max(WINDOWS)) -> float:
    """Gate 2: the untrained network against the saved ``equal_weight`` column."""
    idx = np.arange(stgnn.first_usable(window), len(exp.data.positions))
    weights = stgnn.untrained_weights(exp.data, idx, window, graph_layers=1)
    combined = stgnn.combine(weights, exp.data.preds[idx])
    saved = exp.frame.pivot(index="position", columns="ticker", values="equal_weight")
    saved = saved.loc[exp.data.positions[idx], exp.data.tickers].to_numpy()
    return float(np.abs(combined - saved).max())


def gate_dates(exp: Experiment) -> bool:
    """Gate 4: the frozen panel's date at each position is the predictions' date."""
    panel_dates = next(iter(exp.panel.values())).index
    return bool((panel_dates[exp.data.positions] == exp.data.dates).all())


def run_gates(exp: Experiment) -> dict[str, float | bool]:
    gates = {
        "supervisor reproduced (max abs diff)": gate_supervisor(exp),
        "untrained = equal weight (max abs diff)": gate_equal_weight(exp),
        "panel dates = prediction dates": gate_dates(exp),
    }
    failed = []
    if not gates["supervisor reproduced (max abs diff)"] <= GATE_TOLERANCE:
        failed.append("gate 1")
    if not gates["untrained = equal weight (max abs diff)"] <= GATE_TOLERANCE:
        failed.append("gate 2")
    if not gates["panel dates = prediction dates"]:
        failed.append("gate 4")
    if failed:
        raise RuntimeError(f"{', '.join(failed)} failed: {gates}; no result can count")
    return gates


# ---------------------------------------------------------------- runs and scores


@dataclass
class Run:
    label: str
    variant: str
    window: int
    graph_layers: int
    seed: int
    period: str
    output: pd.DataFrame  # date, ticker, position, w_<skill>, prediction, confidence
    gate: float | None
    runtime: int
    qlike: float = float("nan")  # on its own period, set once it is scored


def run(exp: Experiment, variant: str, window: int, graph_layers: int, seed: int, period: str,
        adjacency_cache: dict) -> Run:
    layers = 0 if variant == "nograph" else graph_layers
    label = f"stgnn_{variant}_L{window}" + (f"_g{layers}" if layers else "") + f"_{period}_seed{seed}"
    if variant not in adjacency_cache:
        adjacency_cache[variant] = exp.adjacency(variant)
    start, end = exp.rows(period)
    started = time.time()
    result = stgnn.walk_forward(exp.data, adjacency_cache[variant], start, end, window, layers, seed)
    idx = np.arange(start, end + 1)
    combined = stgnn.combine(result.weights, exp.data.preds[idx])
    conf = stgnn.confidence(combined, exp.data.realized[idx])
    n_tickers = len(exp.data.tickers)
    output = pd.DataFrame(
        {
            "date": np.repeat(exp.data.dates[idx], n_tickers),
            "ticker": np.tile(exp.data.tickers, len(idx)),
            "position": np.repeat(exp.data.positions[idx], n_tickers),
            **{f"w_{s}": result.weights[..., k].ravel() for k, s in enumerate(exp.skills)},
            "prediction": combined.ravel(),
            "confidence": conf.ravel(),
        }
    )
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    output.to_csv(EXPERIMENTS_DIR / f"{label}.csv", index=False, float_format="%.8f")
    gate = result.gates[-1] if result.gates else None
    return Run(label, variant, window, layers, seed, period, output, gate, round(time.time() - started))


def scored(exp: Experiment, run_: Run | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(test rows, 2019 rows) picked by the report's own functions, with the run's prediction as ``stgnn``."""
    frame = exp.frame[BASE_COLUMNS + [f"pred_{s}" for s in exp.skills]]
    if run_ is not None:
        frame = frame.merge(
            run_.output[["date", "ticker", "prediction"]].rename(columns={"prediction": "stgnn"}),
            on=["date", "ticker"], how="left", validate="one_to_one",
        )
    test, val = scored_rows(frame, TEST_START), validation_rows(frame, end=TEST_START)
    if run_ is not None:
        # A row the run did not predict would be dropped from the score silently: refuse instead.
        base = exp.frame[frame.columns.drop("stgnn")]
        expected = scored_rows(base, TEST_START) if run_.period == "test" else validation_rows(base, end=TEST_START)
        got = test if run_.period == "test" else val
        if len(got) != len(expected):
            raise ValueError(f"{run_.label} covers {len(got)} of {len(expected)} scored rows")
    return test, val


def reference_scores(exp: Experiment) -> pd.DataFrame:
    """QLIKE on the test period and on 2019 of the models the ST-GNN is compared with."""
    test, val = scored(exp)
    columns = {"supervisor": "supervisor", "equal_weight": "equal_weight", "baseline": "baseline",
               **{s: f"pred_{s}" for s in exp.skills}}
    return pd.DataFrame(
        {
            "QLIKE": {m: qlike(test["realized_vol"], test[c]).mean() for m, c in columns.items()},
            "QLIKE_2019": {m: qlike(val["realized_vol"], val[c]).mean() for m, c in columns.items()},
        }
    )


def run_qlike(exp: Experiment, run_: Run) -> float:
    test, val = scored(exp, run_)
    rows = test if run_.period == "test" else val
    return float(qlike(rows["realized_vol"], rows["stgnn"]).mean())


# ---------------------------------------------------------------- decision


def decide(seed_qlike: dict[int, float], references: pd.DataFrame, skills: list[str]) -> dict:
    """The bar of docs/stgnn-plan.md, section 2, on the test QLIKE of the candidate's seeds."""
    values = np.array(list(seed_qlike.values()))
    mean, spread = float(values.mean()), float(values.max() - values.min())
    best_skill = min(skills, key=lambda s: references.loc[s, "QLIKE"])
    bars = {
        "current supervisor": float(references.loc["supervisor", "QLIKE"]),
        "equal-weight average": float(references.loc["equal_weight", "QLIKE"]),
        f"best single skill ({best_skill})": float(references.loc[best_skill, "QLIKE"]),
    }
    beats = {name: mean < value for name, value in bars.items()}
    every_seed = bool((values < bars["equal-weight average"]).all())
    go = all(beats.values()) and every_seed
    margin = min(bars.values()) - mean
    return {
        "mean": mean,
        "spread": spread,
        "bars": bars,
        "beats": beats,
        "every_seed_beats_equal_weight": every_seed,
        "go": go,
        "settled": abs(margin) > spread,
        "margin": float(margin),
    }


# ---------------------------------------------------------------- procedure


def mean_2019(exp: Experiment, runs: list[Run]) -> float:
    return float(np.mean([run_qlike(exp, r) for r in runs]))


def procedure(exp: Experiment, seeds: list[int], log=print) -> dict:
    cache: dict = {}
    refs = reference_scores(exp)
    equal_2019 = float(refs.loc["equal_weight", "QLIKE_2019"])
    selection: list[dict] = []
    validation_runs: dict[tuple, list[Run]] = {}

    def on_2019(variant, window, layers, step):
        key = (variant, window, layers)
        runs = [run(exp, variant, window, layers, s, "validation", cache) for s in seeds]
        validation_runs[key] = runs
        q = [run_qlike(exp, r) for r in runs]
        selection.append({"step": step, "variant": variant, "L": window, "graph layers": 0 if variant == "nograph" else layers,
                          "mean QLIKE 2019": float(np.mean(q)), "seeds": q, "runtime": sum(r.runtime for r in runs)})
        log(f"  2019 {variant} L={window} layers={layers}: {np.mean(q):.4f} (seeds {', '.join(f'{x:.4f}' for x in q)})")
        return float(np.mean(q))

    log("Step 2: error window L, no graph, 2019")
    by_window = {w: on_2019("nograph", w, 0, "2: window") for w in WINDOWS}
    window = min(by_window, key=by_window.get)
    result = {"refs": refs, "selection": selection, "window": window, "equal_2019": equal_2019}
    if not by_window[window] < equal_2019:
        result["stopped"] = (
            f"the best no-graph network (L = {window}, {by_window[window]:.4f}) does not beat the "
            f"equal-weight average on 2019 ({equal_2019:.4f})"
        )
        return result

    log("Step 3: graph layers on the correlation map, 2019")
    by_layers = {g: on_2019("corr", window, g, "3: graph layers") for g in GRAPH_LAYERS}
    layers = min(by_layers, key=by_layers.get)
    for variant in ("sector", "shuffled"):
        on_2019(variant, window, layers, "3: candidate choice")
    candidates = {
        "nograph": by_window[window],
        "corr": by_layers[layers],
        **{v: mean_2019(exp, validation_runs[(v, window, layers)]) for v in ("sector", "shuffled")},
    }
    candidate = min(candidates, key=candidates.get)
    result.update(layers=layers, candidates_2019=candidates, candidate=candidate)

    log(f"Test period, once: {', '.join(VARIANTS)} with L={window}, {layers} graph layer(s); candidate {candidate}")
    test_runs = [run(exp, v, window, layers, s, "test", cache) for v in VARIANTS for s in seeds]
    for r in test_runs:
        r.qlike = run_qlike(exp, r)
        log(f"  test {r.label}: {r.qlike:.4f} ({r.runtime}s)")
    result["test_runs"] = test_runs
    result["validation_runs"] = validation_runs
    result["decision"] = decide(
        {r.seed: r.qlike for r in test_runs if r.variant == candidate}, refs, exp.skills
    )
    return result


# ---------------------------------------------------------------- writing


def experiment_table(exp: Experiment, result: dict) -> tuple[pd.DataFrame, list, dict, dict]:
    """Rows for docs/experiments.md, in the layout ``experiment.append_rows`` expects."""
    window, layers = result["window"], result["layers"]
    baseline = float(result["refs"].loc["baseline", "QLIKE"])
    rows, runs, runtimes = {}, [], {}
    for r in result["test_runs"]:
        val = next(v for v in result["validation_runs"][(r.variant, window, layers if r.variant != "nograph" else 0)]
                   if v.seed == r.seed)
        q = r.qlike
        rows[r.label] = {"QLIKE": q, "gain": 100 * (1 - q / baseline), "QLIKE_2019": run_qlike(exp, val),
                         "factor": np.nan, "gate": r.gate}
        runs.append((r.label, f"stgnn_{r.variant}", r.seed))
        runtimes[r.label] = r.runtime + val.runtime
    table = pd.DataFrame(rows).T.astype(float)
    table.attrs["baseline"] = baseline
    descriptions = {
        name: f"{text}; L = {window}" + ("" if name == "stgnn_nograph" else f", {layers} graph layer(s)")
        + "; quarterly refits; no recalibration"
        for name, text in DESCRIPTIONS.items()
    }
    return table, runs, runtimes, descriptions


def results_markdown(result: dict, gates: dict, seeds: list[int]) -> str:
    refs = result["refs"]
    lines = [
        "# ST-GNN supervisor: phase A results",
        "",
        f"Generated by `python -m tsm.stgnn --seeds {' '.join(map(str, seeds))}` on {date.today().isoformat()}. "
        "Do not edit by hand. Design: `docs/superpowers/specs/2026-10-27-stgnn-phase-a-design.md`.",
        "",
        "Every model is scored like `docs/backtest.md`: QLIKE (lower is better) on the rows whose 5-day "
        "outcome is known, from 2020-01-01 for the test and on 2019 for the choices. The ST-GNN combines "
        "the saved calibrated skill predictions and, like the current supervisor, is not recalibrated.",
        "",
        "## Gates",
        "",
        "| Gate | Result |",
        "| --- | --- |",
        *[f"| {name} | {value if isinstance(value, bool) else f'{value:.2e}'} |" for name, value in gates.items()],
        "| no look-ahead (inputs and weights, corrupted future) | `tests/test_stgnn.py::test_no_look_ahead` |",
        "",
        "## Reference models",
        "",
        "| Model | QLIKE test | QLIKE 2019 |",
        "| --- | ---: | ---: |",
        *[f"| {m} | {row.QLIKE:.4f} | {row.QLIKE_2019:.4f} |" for m, row in refs.iterrows()],
        "",
        "The current supervisor's 2019 number is in-sample (it was tuned on those dates), so 2019 choices "
        "are compared with the equal-weight average only.",
        "",
        "## Choices on 2019",
        "",
        "| Step | Variant | L | Graph layers | Mean QLIKE 2019 | Seeds | Runtime |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: |",
        *[
            f"| {s['step']} | `{s['variant']}` | {s['L']} | {s['graph layers']} | {s['mean QLIKE 2019']:.4f} | "
            f"{', '.join(f'{q:.4f}' for q in s['seeds'])} | {s['runtime']}s |"
            for s in result["selection"]
        ],
        "",
    ]
    if "stopped" in result:
        lines += ["## Decision: no-go", "", f"Stopped at step 2: {result['stopped']}. "
                  "The graph variants were not run and the test period was not looked at.", ""]
        return "\n".join(lines)

    lines += [
        f"Chosen: L = {result['window']}, {result['layers']} graph layer(s). Candidate (lowest mean 2019 "
        f"QLIKE among the four variants): `{result['candidate']}`.",
        "",
        "## Test period (looked at once)",
        "",
        "| Variant | Mean QLIKE | Seeds | Spread | Mean 2019 | Gate g (last refit) |",
        "| --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for variant in VARIANTS:
        runs = [r for r in result["test_runs"] if r.variant == variant]
        q = [r.qlike for r in runs]
        gates_ = [r.gate for r in runs if r.gate is not None]
        gate_cell = f"{np.mean(gates_):.3f}" if gates_ else "—"
        lines.append(
            f"| `{variant}`{' (candidate)' if variant == result['candidate'] else ''} | {np.mean(q):.4f} | "
            f"{', '.join(f'{x:.4f}' for x in q)} | {max(q) - min(q):.4f} | "
            f"{result['candidates_2019'][variant]:.4f} | {gate_cell} |"
        )
    d = result["decision"]
    lines += [
        "",
        f"## Decision: {'go' if d['go'] else 'no-go'}",
        "",
        f"Candidate `{result['candidate']}`, mean test QLIKE {d['mean']:.4f} over seeds "
        f"{', '.join(map(str, seeds))} (spread {d['spread']:.4f}).",
        "",
        "| Bar | QLIKE | Beaten |",
        "| --- | ---: | --- |",
        *[f"| {name} | {value:.4f} | {'yes' if d['beats'][name] else 'no'} |" for name, value in d["bars"].items()],
        f"| every seed below the equal-weight average | — | {'yes' if d['every_seed_beats_equal_weight'] else 'no'} |",
        "",
        f"Margin to the strongest bar: {d['margin']:+.4f}; seed spread {d['spread']:.4f}: "
        f"{'settled' if d['settled'] else 'not settled (the margin is smaller than the seed spread)'}.",
        "",
    ]
    corr = np.mean([r.qlike for r in result["test_runs"] if r.variant == "corr"])
    shuffled = [r.qlike for r in result["test_runs"] if r.variant == "shuffled"]
    real_graph = corr < min(shuffled)
    lines += [
        "**Graph control.** " + (
            f"The correlation map ({corr:.4f}) beats every seed of the shuffled map "
            f"({min(shuffled):.4f} to {max(shuffled):.4f}): the links themselves carry information."
            if real_graph else
            f"The correlation map ({corr:.4f}) does not beat every seed of the shuffled map "
            f"({min(shuffled):.4f} to {max(shuffled):.4f}): any gain from the graph is not due to which "
            "stocks it links, as in Step 9."
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tsm.stgnn", description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    args = parser.parse_args(argv)
    seeds = list(dict.fromkeys(args.seeds))
    started = time.time()
    before = file_hashes()

    exp = Experiment.load()
    gates = run_gates(exp)
    print(f"Gates passed: {gates}", flush=True)
    result = procedure(exp, seeds, log=lambda m: print(m, flush=True))

    RESULTS_FILE.write_text(results_markdown(result, gates, seeds), encoding="utf-8")
    if "test_runs" in result:
        table, runs, runtimes, descriptions = experiment_table(exp, result)
        print(append_rows(table, runs, runtimes, seeds, descriptions))
    if file_hashes() != before:
        raise RuntimeError("a protected engine file changed during the run")
    verdict = result.get("stopped") or ("go" if result["decision"]["go"] else "no-go")
    print(f"Wrote {RESULTS_FILE} in {round(time.time() - started)}s: {verdict}")


if __name__ == "__main__":
    main()
