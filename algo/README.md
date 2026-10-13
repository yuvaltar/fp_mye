# algo

Python 3.12 prediction engine and FastAPI server for Temporal Skills Market. Owner: Yuval (all of `/algo`: the iTransformer, the ST-GNN market map and the API). Elie has left the project.

It predicts annualized 5-trading-day realized volatility for 52 tickers with a committee of four skills (`short_term` HAR-RV, `regime` GARCH, `weak_signals` gradient boosting, `itransformer` our own PyTorch iTransformer averaged over three seeds; it replaced the neuralforecast `multivariate` in Step 11). Every skill is calibrated before it is scored or combined, and a supervisor weights the skills by their recent QLIKE. Results are in `../docs/backtest.md`; candidate models are scored in `../docs/experiments.md`.

| Path | What |
| --- | --- |
| `tsm/data.py`, `tsm/target.py` | price loader and cache, realized-volatility target |
| `tsm/skills/` | the committee, one module per skill |
| `tsm/supervisor.py` | skill registry (`build_skills`) and the supervisor |
| `tsm/backtest.py` | walk-forward pipeline: skills, calibration, baselines, supervisor, artifacts |
| `tsm/report.py` | writes `../docs/backtest.md` |
| `tsm/models/` | our own PyTorch iTransformer; its variants are candidates, not committee members |
| `tsm/experiment.py` | scores candidates against the saved committee on the frozen price cache |
| `tsm/api.py` | serves `artifacts/` in the shapes of `../contracts` |
| `artifacts/` | output of the last backtest (committed so the API runs from a clone) |

```bash
py -3.12 -m venv .venv                            # Windows (Unix: python3.12 -m venv .venv)
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Unix: .venv/bin/python
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m tsm.backtest          # about 40 minutes on 52 tickers; --cache-only = frozen prices
.venv/Scripts/python.exe -m tsm.experiment itransformer_path_feats --seeds 0 1 2
.venv/Scripts/python.exe -m uvicorn tsm.api:app --reload --port 8000
```

All rules and conventions are in the root `CLAUDE.md`; the API it serves is defined in `../contracts`.
