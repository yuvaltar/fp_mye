# Experiments

One row per candidate model, appended by `python -m tsm.experiment`. Do not edit by hand.

Every row is scored the same way as `backtest.md`: the candidate is calibrated with the same
factor rule, scored from 2020-01-01 on the dates whose 5-day outcome is known, and compared with the
calibrated HAR-RV baseline. The committee's own predictions are read back from
`algo/artifacts/predictions.csv` rather than recomputed, so the comparison is against exactly the
numbers in the committed report.

A candidate appearing here is **not** part of the committee. `build_skills` is unchanged until an
experiment earns a place in it.

The four committee rows were seeded from the committed backtest and were not timed individually,
so their runtime reads as a dash.

| Date | Experiment | Description | QLIKE | vs HAR-RV | Mean factor | Runtime |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 2026-10-08 | HAR-RV (short_term) | HAR-RV on realized volatility (the committee baseline) | 0.5460 | +0.0% | 1.220 | — |
| 2026-10-08 | `regime` | GARCH(1,1) on daily returns | 0.5342 | +2.2% | 1.065 | — |
| 2026-10-08 | `weak_signals` | Gradient boosting on volume, range, gap and SPY-correlation features | 0.4885 | +10.5% | 1.307 | — |
| 2026-10-08 | `multivariate` | neuralforecast iTransformer, MAE on log-volatility | 0.5097 | +6.7% | 1.292 | — |
| 2026-10-08 | `itransformer_mae` | Own PyTorch iTransformer, MAE on log-volatility | 0.5244 | +4.0% | 1.319 | 451s |
| 2026-10-08 | `itransformer_qlike` | Own PyTorch iTransformer, QLIKE on log-volatility | 0.5856 | -7.3% | 1.070 | 546s |
| 2026-10-08 | `itransformer_mae` (seed 0) | Own PyTorch iTransformer, MAE on log-volatility | 0.5244 | +4.0% | 1.319 | 410s |
| 2026-10-08 | `itransformer_mae` (seed 1) | Own PyTorch iTransformer, MAE on log-volatility | 0.5247 | +3.9% | 1.304 | 407s |
| 2026-10-08 | `itransformer_mae` (seed 2) | Own PyTorch iTransformer, MAE on log-volatility | 0.5220 | +4.4% | 1.297 | 414s |
| 2026-10-08 | `itransformer_mae_path` (seed 0) | Own PyTorch iTransformer, 5-step path head, MAE over the 5 steps | 0.5026 | +7.9% | 1.292 | 439s |
| 2026-10-08 | `itransformer_mae_path` (seed 1) | Own PyTorch iTransformer, 5-step path head, MAE over the 5 steps | 0.5100 | +6.6% | 1.284 | 411s |
| 2026-10-08 | `itransformer_mae_path` (seed 2) | Own PyTorch iTransformer, 5-step path head, MAE over the 5 steps | 0.5069 | +7.2% | 1.289 | 403s |
| 2026-10-08 | **`itransformer_mae` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.5220 to 0.5247 (width 0.0027) | 0.5237 | +4.1% | 1.307 | 1231s total |
| 2026-10-08 | **`itransformer_mae_path` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.5026 to 0.5100 (width 0.0073) | 0.5065 | +7.2% | 1.288 | 1253s total |
