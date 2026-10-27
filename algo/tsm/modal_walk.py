"""Walk candidate skills forward on Modal, one container per (candidate, seed), all in parallel.

Used by ``python -m tsm.stgnn_skill walk --modal``. Each container gets the same
frozen price cache (``algo/data/``) and ``artifacts/meta.json`` as a local run,
runs ``tsm.backtest.run_skills`` exactly as ``tsm.experiment.run_candidates``
does, and sends the predictions back as CSV text.

Needs the ``modal`` package and a Modal account set up on this machine
(``modal token new``, stored in ``~/.modal.toml``, never in the repository).

Reproducibility: every container pins torch to ``THREADS`` threads, so a run on
Modal reproduces exactly on Modal. A local run of the same seed may differ in
the last digits (another CPU, another thread split), as noted in tsm.experiment.
"""
from __future__ import annotations

import modal

from tsm.config import ARTIFACTS_DIR, DATA_DIR

THREADS = 4
# The versions of algo/.venv, so the containers compute what the local engine computes.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "numpy==2.5.3",
        "pandas==3.0.6",
        "scipy==1.18.1",
        "scikit-learn==1.9.1",
        "arch==8.0.0",
        "yfinance==1.7.0",
        "matplotlib==3.11.2",
    )
    .pip_install("torch==2.14.1", index_url="https://download.pytorch.org/whl/cpu")
    .add_local_dir(DATA_DIR, "/root/data", ignore=["earnings/**"])
    .add_local_file(ARTIFACTS_DIR / "meta.json", "/root/artifacts/meta.json")
    .add_local_python_source("tsm")
)
app = modal.App("tsm-stgnn-skill", image=image)


@app.function(cpu=THREADS, memory=4096, timeout=3 * 3600)
def walk(name: str, seed: int) -> tuple[str, int]:
    """One candidate at one seed, walked forward from BACKTEST_START: (predictions CSV, seconds)."""
    import time

    import torch

    from tsm.backtest import BACKTEST_START, run_skills
    from tsm.experiment import load_frozen_panel
    from tsm.models.stgnn_skill import build_candidate

    torch.set_num_threads(THREADS)
    skill = build_candidate(name, seed=seed)
    started = time.time()
    out = run_skills(load_frozen_panel(), [skill], start=BACKTEST_START)
    column = f"pred_{skill.name}"
    csv = out[["date", "ticker", column]].rename(columns={column: "prediction"}).to_csv(
        index=False, float_format="%.6f"
    )
    return csv, round(time.time() - started)


def walk_all(jobs: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Run every (name, seed) at once on Modal; results in the order of ``jobs``."""
    with modal.enable_output(), app.run():
        return list(walk.starmap(jobs))
