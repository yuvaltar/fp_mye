# ST-GNN predictor as a fifth skill: design

Owner: Elie, branch `algo-elie`. Written 2026-10-27, after the ST-GNN supervisor's no-go (`docs/stgnn-results.md`).

## Agreed with Elie

- Try the ST-GNN as a fifth skill that predicts volatility itself.
- It joins the committee only if the committee with it beats the committee without it (option a). Otherwise it stays a documented candidate, as `multivariate` does.
- Walks run on Modal (Elie's account, `~/.modal.toml`), every (variant, seed) in parallel. `modal==1.6.1` was installed in `algo/.venv` at Elie's request (same version as the CLI); it is needed only for `walk --modal`, so it is not added to `requirements.txt`.
- Yuval agreed that his files may be touched; nothing here needs it. If it is a go, `add-temporal-skill` changes `supervisor.py` and the report.

## Model (`algo/tsm/models/stgnn_skill.py`)

GRU (32 units) over each stock's last 44 days in the four `path_feats` channels (log 5-day vol, return, range, volume), standardised with the training windows' statistics → optionally one graph layer `h + g·A·h·W` on the market map (`g` starts at 0, learning rate 0.02) → head to the 1..5-day path of log vol as a change from today's, MAE, forecast = 5th step. 300 Adam steps of 32 dates, learning rate 1e-3, refit every 125 trading days, seeds fixed. These settings copy `itransformer_path_feats` and are not tuned.

Variants: `stgnn_skill_none` (no graph), `stgnn_skill_corr`, `stgnn_skill_shuffled` (control). Seeds 0, 1, 2; as in the committee's `itransformer`, the skill is the mean of the three.

## Test (`algo/tsm/stgnn_skill.py`)

1. `walk [--modal]`: every variant and seed walked forward from 2018-01-01 on the frozen cache with `run_skills`, saved to `algo/experiments/`.
2. `score`: the committee is rebuilt from `predictions.csv` as the backtest builds it: the earnings jump from the saved `earnings_week` and `earnings_J`, the calibration, the equal-weight average and the supervisor tuned before 2020.
   - Gates: rebuilding the four-skill committee from its raw predictions reproduces every calibrated prediction within the CSV's rounding, computed per row (in earnings weeks the 6-decimal `earnings_J` alone moves a prediction by up to ~1e-4), the supervisor's settings (120, 0.25), and its QLIKE to 1e-5.
   - Candidate: `none` or `corr`, whichever gives the five-skill equal-weight average the lower 2019 QLIKE.
   - **Go** if, on the test period, the five-skill supervisor beats today's (0.4263) and the five-skill equal-weight average beats today's (0.4300). Committees built with a single seed give the spread; a gain smaller than it is "not settled".
3. Writes `docs/stgnn-skill-results.md` and rows in `docs/experiments.md` (the candidate alone, as every candidate). The protected engine files are hashed before and after.

## If go

`add-temporal-skill`: a committee skill averaging the three seeds, registered in `build_skills`, tested, full `python -m tsm.backtest --cache-only` (about 40 minutes), report and API numbers regenerated, PR `algo-elie` → `algo`.
