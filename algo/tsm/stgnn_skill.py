"""``python -m tsm.stgnn_skill walk [--modal]`` then ``python -m tsm.stgnn_skill score``: a fifth skill?

Asks whether the ST-GNN predictor (``tsm.models.stgnn_skill``) makes the committee
better, not whether it is the best skill alone.

``walk`` walks the three variants (``none``, ``corr``, and the ``shuffled`` control)
forward with seeds 0, 1 and 2 on the frozen price cache, on Modal in parallel or
here one after another, and saves each run to ``algo/experiments/<name>_seed<s>.csv``.

``score`` then rebuilds the committee from the committed artifacts, with and
without the candidate, exactly as the backtest builds it: the earnings jump (from
the saved ``earnings_week`` and ``earnings_J``), the calibration, the equal-weight
average and the supervisor tuned on dates before the test period. Like the
committee's ``itransformer``, the candidate is the mean of its three seeds.

The procedure, fixed before any result (``docs/superpowers/specs/2026-10-27-stgnn-skill-design.md``):

- gates: the rebuild reproduces the saved calibrated predictions, the saved
  supervisor and its settings;
- the candidate is ``none`` or ``corr``, whichever gives the five-skill
  equal-weight average the lower 2019 QLIKE (the supervisor's 2019 is in-sample);
- go only if, on the test period, the five-skill supervisor beats the four-skill
  supervisor and the five-skill equal-weight average beats the four-skill one.

Writes only ``docs/experiments.md``, ``docs/stgnn-skill-results.md`` and the
git-ignored ``algo/experiments/``; the protected engine files are hashed before and after.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date

import numpy as np
import pandas as pd

from tsm.backtest import TEST_START, apply_supervisor, calibrate, run_skills, tune_supervisor, BACKTEST_START
from tsm.config import ARTIFACTS_DIR, DOCS_DIR
from tsm.earnings_jump import add_jump
from tsm.experiment import EXPERIMENTS_DIR, append_rows, load_committee, load_frozen_panel, score
from tsm.models.stgnn_skill import CANDIDATES, build_candidate
from tsm.report import scored_rows, validation_rows
from tsm.stgnn import file_hashes
from tsm.supervisor import qlike

RESULTS_FILE = DOCS_DIR / "stgnn-skill-results.md"
SEEDS = (0, 1, 2)
VARIANTS = tuple(CANDIDATES)  # stgnn_skill_none, stgnn_skill_corr, stgnn_skill_shuffled
CHOICES = ("stgnn_skill_none", "stgnn_skill_corr")  # the control is never the candidate
CONTROL = "stgnn_skill_shuffled"
DESCRIPTIONS = {
    "stgnn_skill_none": "ST-GNN predictor, temporal part only: GRU over 44 days x 4 channels, 5-step path of log vol, MAE",
    "stgnn_skill_corr": "ST-GNN predictor: GRU + one graph layer h + g·A·h·W on the market-adjusted correlation map, MAE",
    "stgnn_skill_shuffled": "ST-GNN predictor: GRU + graph layer on the correlation map with stocks shuffled (control)",
}


def run_path(name: str, seed: int):
    return EXPERIMENTS_DIR / f"{name}_seed{seed}.csv"


# ---------------------------------------------------------------- walk


def walk(use_modal: bool, names=VARIANTS, seeds=SEEDS) -> None:
    jobs = [(n, s) for n in names for s in seeds if not run_path(n, s).exists()]
    if not jobs:
        print("Every run is already saved; delete a file in algo/experiments/ to run it again.")
        return
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Walking {len(jobs)} run(s) {'on Modal in parallel' if use_modal else 'here, one after another'}", flush=True)
    if use_modal:
        from tsm.modal_walk import walk_all

        results = walk_all(jobs)
    else:
        panel, results = load_frozen_panel(), []
        for name, seed in jobs:
            skill, started = build_candidate(name, seed), time.time()
            out = run_skills(panel, [skill], start=BACKTEST_START)
            column = f"pred_{skill.name}"
            csv = out[["date", "ticker", column]].rename(columns={column: "prediction"}).to_csv(
                index=False, float_format="%.6f"
            )
            results.append((csv, round(time.time() - started)))
    runtimes = {}
    for (name, seed), (csv, seconds) in zip(jobs, results):
        run_path(name, seed).write_text(csv)
        runtimes[f"{name}_seed{seed}"] = seconds
        print(f"  {name} seed {seed}: {seconds}s -> {run_path(name, seed).name}", flush=True)
    timing = EXPERIMENTS_DIR / "stgnn_skill_runtimes.json"
    saved = json.loads(timing.read_text()) if timing.exists() else {}
    timing.write_text(json.dumps({**saved, **runtimes}, indent=1))


# ---------------------------------------------------------------- rebuild the committee


def load_frame() -> tuple[pd.DataFrame, list[str], dict]:
    meta = json.loads((ARTIFACTS_DIR / "meta.json").read_text())
    skills = [s["name"] for s in meta["skills"]]
    frame = pd.read_csv(ARTIFACTS_DIR / "predictions.csv", parse_dates=["date"])
    return frame, skills, meta


def load_runs(names=VARIANTS, seeds=SEEDS) -> pd.DataFrame:
    """One ``<name>_seed<s>`` column per saved run, keyed by date and ticker."""
    columns = []
    for name in names:
        for seed in seeds:
            path = run_path(name, seed)
            if not path.exists():
                raise FileNotFoundError(f"{path} is missing; run python -m tsm.stgnn_skill walk first")
            saved = pd.read_csv(path, parse_dates=["date"]).set_index(["date", "ticker"])["prediction"]
            columns.append(saved.rename(f"{name}_seed{seed}"))
    return pd.concat(columns, axis=1).reset_index()


def committee(frame: pd.DataFrame, members: dict[str, pd.Series]) -> tuple[pd.DataFrame, object]:
    """The backtest's steps after the skills: jump, calibration, equal weight, tuned supervisor.

    ``members`` maps each skill name to its raw prediction (aligned with ``frame``).
    """
    names = list(members)
    raw = frame[["date", "ticker", "position", "realized_vol", "earnings_week"]].copy()
    for name, values in members.items():
        raw[f"pred_{name}"] = values.to_numpy()
    jumped = add_jump(raw, names, frame["earnings_J"].to_numpy())
    calibrated = calibrate(jumped, names)
    calibrated["equal_weight"] = calibrated[[f"pred_{n}" for n in names]].mean(axis=1)
    supervisor = tune_supervisor(calibrated, names, before=TEST_START)
    return apply_supervisor(calibrated, supervisor, names), supervisor


def qlikes(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Test and 2019 QLIKE on the report's rows (rows complete in ``columns`` and the outcome)."""
    part = frame[["date", "ticker", "realized_vol"] + columns]
    test, val = scored_rows(part, TEST_START), validation_rows(part, end=TEST_START)
    return pd.DataFrame(
        {
            "QLIKE": {c: qlike(test["realized_vol"], test[c]).mean() for c in columns},
            "QLIKE_2019": {c: qlike(val["realized_vol"], val[c]).mean() for c in columns},
        }
    )


CSV_ROUNDING = 5e-7  # predictions.csv keeps 6 decimals
# Ordinary weeks: the saved raw inputs and outputs are rounded and the calibration factor (up
# to ~1.3) scales the inputs' rounding; measured 3.5e-6 at most on the committed artifacts.
ORDINARY_TOLERANCE = 5e-6
QLIKE_TOLERANCE = 1e-5


def rounding_bound(rebuilt: pd.DataFrame, name: str) -> np.ndarray:
    """Per row, how far the rounding of the saved inputs can move a rebuilt calibrated prediction.

    In an earnings week the jump adds 252/5·J to the variance, and J (about 0.002) is
    saved with 6 decimals, so ``vol`` can move by ``252/5 · 5e-7 / (2·vol)`` before the
    factor ``c`` scales it.
    """
    c = rebuilt[f"c_{name}"].to_numpy()
    jumped = rebuilt[f"pred_{name}"].to_numpy() / c
    from_jump = np.where(rebuilt["earnings_week"].to_numpy(), 252 / 5 * CSV_ROUNDING / (2 * jumped), 0.0)
    return c * from_jump + ORDINARY_TOLERANCE


def gates(frame: pd.DataFrame, skills: list[str], meta: dict) -> tuple[dict, pd.DataFrame]:
    """The four-skill committee rebuilt from the raw predictions, against the saved columns."""
    four, supervisor = committee(frame, {s: frame[f"raw_pred_{s}"] for s in skills})
    over = sum(
        int(np.nansum(np.abs(four[f"pred_{s}"] - frame[f"pred_{s}"]).to_numpy() > rounding_bound(four, s)))
        for s in skills
    )
    rebuilt = qlikes(four, ["supervisor"]).loc["supervisor"]
    saved = qlikes(frame, ["supervisor"]).loc["supervisor"]
    result = {
        "calibrated predictions beyond the CSV rounding (rows)": over,
        "calibrated predictions (max abs diff)": max(
            float(np.nanmax(np.abs(four[f"pred_{s}"] - frame[f"pred_{s}"]))) for s in skills
        ),
        "supervisor settings reproduced": (supervisor.window, supervisor.temperature)
        == (meta["supervisor"]["window"], meta["supervisor"]["temperature"]),
        "supervisor QLIKE test/2019 (max abs diff)": float(np.abs(rebuilt - saved).max()),
    }
    if not (
        over == 0
        and result["supervisor settings reproduced"]
        and result["supervisor QLIKE test/2019 (max abs diff)"] <= QLIKE_TOLERANCE
    ):
        raise RuntimeError(f"a gate failed: {result}; no result can count")
    return result, four


def decide(five: pd.Series, four: pd.Series, per_seed_supervisor: list[float]) -> dict:
    """``five`` and ``four``: test QLIKE of ``supervisor`` and ``equal_weight``."""
    beats_supervisor = five["supervisor"] < four["supervisor"]
    beats_equal = five["equal_weight"] < four["equal_weight"]
    margin = float(four["supervisor"] - five["supervisor"])
    spread = float(max(per_seed_supervisor) - min(per_seed_supervisor))
    return {
        "go": bool(beats_supervisor and beats_equal),
        "beats_supervisor": bool(beats_supervisor),
        "beats_equal": bool(beats_equal),
        "margin": margin,
        "spread": spread,
        "settled": abs(margin) > spread,
    }


def run_score(seeds=SEEDS) -> dict:
    frame, skills, meta = load_frame()
    if "stgnn" in skills:
        raise RuntimeError(
            "stgnn is already a committee skill in artifacts/meta.json, so this would add it twice. "
            "The decision in docs/stgnn-skill-results.md was made on the four-skill artifacts of commit "
            "d3a64bb; check that commit out to reproduce it."
        )
    runs = load_runs(seeds=seeds)
    merged = frame[["date", "ticker"]].merge(runs, on=["date", "ticker"], how="left", validate="one_to_one")
    if merged.drop(columns=["date", "ticker"]).isna().any().any():
        raise ValueError("a saved run has no prediction for some committee rows")
    gate_result, four = gates(frame, skills, meta)
    reference = qlikes(four, ["supervisor", "equal_weight"])
    print(f"Gates passed: {gate_result}", flush=True)

    base = {s: frame[f"raw_pred_{s}"] for s in skills}
    results = {}
    for name in VARIANTS:
        mean = merged[[f"{name}_seed{s}" for s in seeds]].mean(axis=1)
        five, supervisor = committee(frame, {**base, "stgnn_skill": mean})
        results[name] = {"scores": qlikes(five, ["supervisor", "equal_weight"]), "settings": supervisor}
        print(f"  {name}: {results[name]['scores'].round(4).to_dict()}", flush=True)
    candidate = min(CHOICES, key=lambda n: results[n]["scores"].loc["equal_weight", "QLIKE_2019"])

    per_seed = []
    for seed in seeds:
        five, _ = committee(frame, {**base, "stgnn_skill": merged[f"{candidate}_seed{seed}"]})
        per_seed.append(float(qlikes(five, ["supervisor"]).loc["supervisor", "QLIKE"]))
    decision = decide(results[candidate]["scores"]["QLIKE"], reference["QLIKE"], per_seed)

    # The candidate alone, every seed, scored like every other row of docs/experiments.md.
    # score() needs the committee's own raw predictions too: the HAR-RV baseline is one of them.
    alone, committee_names = load_committee()
    for name in VARIANTS:
        for seed in seeds:
            alone[f"pred_{name}_seed{seed}"] = merged[f"{name}_seed{seed}"].to_numpy()
    labels = [f"{n}_seed{s}" for n in VARIANTS for s in seeds]
    table = score(alone, committee_names + labels).loc[labels]
    table.attrs = score(alone, committee_names).attrs
    return {
        "gates": gate_result, "reference": reference, "results": results, "candidate": candidate,
        "per_seed": per_seed, "decision": decision, "alone": table, "seeds": list(seeds),
    }


# ---------------------------------------------------------------- writing


def results_markdown(r: dict) -> str:
    ref, d = r["reference"], r["decision"]
    lines = [
        "# ST-GNN predictor as a fifth skill: results",
        "",
        f"Generated by `python -m tsm.stgnn_skill score` on {date.today().isoformat()}. Do not edit by hand. "
        "Design: `docs/superpowers/specs/2026-10-27-stgnn-skill-design.md`.",
        "",
        "The question is whether the committee is better with the ST-GNN predictor than without it. "
        "Both committees are rebuilt like the backtest (earnings jump, calibration, equal-weight average, "
        "supervisor tuned on dates before 2020) and scored like `docs/backtest.md` (QLIKE, lower is better). "
        f"The candidate is the mean of seeds {', '.join(map(str, r['seeds']))}, as the committee's `itransformer`.",
        "",
        "## Gates",
        "",
        "| Gate | Result |",
        "| --- | --- |",
        *[f"| {k} | {v if isinstance(v, (bool, int)) else f'{v:.2e}'} |" for k, v in r["gates"].items()],
        "| no look-ahead (single fit and walk-forward) | `tests/test_stgnn_skill.py` |",
        "",
        "## Committees",
        "",
        "| Committee | Supervisor settings | Supervisor test | Supervisor 2019 | Equal weight test | Equal weight 2019 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
        f"| four skills (today) | window 120, temperature 0.25 | {ref.loc['supervisor', 'QLIKE']:.4f} | "
        f"{ref.loc['supervisor', 'QLIKE_2019']:.4f} | {ref.loc['equal_weight', 'QLIKE']:.4f} | "
        f"{ref.loc['equal_weight', 'QLIKE_2019']:.4f} |",
    ]
    for name, res in r["results"].items():
        s, sup = res["scores"], res["settings"]
        tag = " (candidate)" if name == r["candidate"] else " (control)" if name == CONTROL else ""
        lines.append(
            f"| four + `{name}`{tag} | window {sup.window}, temperature {sup.temperature} | "
            f"{s.loc['supervisor', 'QLIKE']:.4f} | {s.loc['supervisor', 'QLIKE_2019']:.4f} | "
            f"{s.loc['equal_weight', 'QLIKE']:.4f} | {s.loc['equal_weight', 'QLIKE_2019']:.4f} |"
        )
    lines += [
        "",
        "The supervisor's 2019 numbers are in-sample (it is tuned on dates before 2020). The candidate, "
        f"`{r['candidate']}`, was chosen between `stgnn_skill_none` and `stgnn_skill_corr` on the "
        "equal-weight 2019 QLIKE; the shuffled map is a control only.",
        "",
        "## The candidate alone",
        "",
        "| Run | QLIKE test | QLIKE 2019 | Mean factor |",
        "| --- | ---: | ---: | ---: |",
        *[f"| `{label}` | {row.QLIKE:.4f} | {row.QLIKE_2019:.4f} | {row.factor:.3f} |" for label, row in r["alone"].iterrows()],
        "",
        f"## Decision: {'go' if d['go'] else 'no-go'}",
        "",
        "| Bar | Four skills | With the candidate | Beaten |",
        "| --- | ---: | ---: | --- |",
        f"| supervisor | {ref.loc['supervisor', 'QLIKE']:.4f} | "
        f"{r['results'][r['candidate']]['scores'].loc['supervisor', 'QLIKE']:.4f} | {'yes' if d['beats_supervisor'] else 'no'} |",
        f"| equal-weight average | {ref.loc['equal_weight', 'QLIKE']:.4f} | "
        f"{r['results'][r['candidate']]['scores'].loc['equal_weight', 'QLIKE']:.4f} | {'yes' if d['beats_equal'] else 'no'} |",
        "",
        f"With a single seed of the candidate, the five-skill supervisor scores "
        f"{', '.join(f'{q:.4f}' for q in r['per_seed'])} (spread {d['spread']:.4f}); the gain over today's "
        f"supervisor is {d['margin']:+.4f}: "
        f"{'settled' if d['settled'] else 'not settled (smaller than the seed spread)'}.",
        "",
    ]
    corr, none, shuffled = (
        r["results"][n]["scores"].loc["supervisor", "QLIKE"]
        for n in ("stgnn_skill_corr", "stgnn_skill_none", CONTROL)
    )
    helps = corr < none and corr < shuffled and min(none, shuffled) - corr > d["spread"]
    lines += [
        f"**Graph control.** Five-skill supervisor with the correlation map {corr:.4f}, without a graph "
        f"{none:.4f}, with the shuffled map {shuffled:.4f}. "
        + (
            "The real links beat both, by more than the seed spread: the graph helps."
            if helps
            else "The gaps are smaller than the seed spread, or the model without a graph does as well: "
            "the gain comes from the temporal model, not from the market map."
        ),
        "",
    ]
    return "\n".join(lines)


def write(r: dict) -> None:
    RESULTS_FILE.write_text(results_markdown(r), encoding="utf-8")
    timing = EXPERIMENTS_DIR / "stgnn_skill_runtimes.json"
    runtimes = json.loads(timing.read_text()) if timing.exists() else {}
    runs = [(f"{n}_seed{s}", n, s) for n in VARIANTS for s in r["seeds"]]
    print(append_rows(r["alone"], runs, runtimes, r["seeds"], DESCRIPTIONS))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tsm.stgnn_skill", description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["walk", "score"])
    parser.add_argument("--modal", action="store_true", help="walk on Modal, every run in parallel")
    args = parser.parse_args(argv)
    before = file_hashes()
    if args.step == "walk":
        walk(args.modal)
    else:
        result = run_score()
        write(result)
        print(f"Wrote {RESULTS_FILE}: {'go' if result['decision']['go'] else 'no-go'}")
    if file_hashes() != before:
        raise RuntimeError("a protected engine file changed during the run")


if __name__ == "__main__":
    main()
