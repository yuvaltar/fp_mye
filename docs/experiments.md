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

**QLIKE 2019** scores the same calibrated predictions on 2019 only, before the test
period: choices between candidates are made on it, not on the test QLIKE. **Gate** is how much a
graph model uses the market map after its last refit: `g` for the `gnn` mode, the mean `|λ|` over
heads and layers for the `bias` mode. Rows written before these two columns existed read a dash.

| Date | Experiment | Description | QLIKE | vs HAR-RV | QLIKE 2019 | Mean factor | Gate | Runtime |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-10-08 | HAR-RV (short_term) | HAR-RV on realized volatility (the committee baseline) | 0.5460 | +0.0% | — | 1.220 | — | — |
| 2026-10-08 | `regime` | GARCH(1,1) on daily returns | 0.5342 | +2.2% | — | 1.065 | — | — |
| 2026-10-08 | `weak_signals` | Gradient boosting on volume, range, gap and SPY-correlation features | 0.4885 | +10.5% | — | 1.307 | — | — |
| 2026-10-08 | `multivariate` | neuralforecast iTransformer, MAE on log-volatility | 0.5097 | +6.7% | — | 1.292 | — | — |
| 2026-10-08 | `itransformer_mae` | Own PyTorch iTransformer, MAE on log-volatility | 0.5244 | +4.0% | — | 1.319 | — | 451s |
| 2026-10-08 | `itransformer_qlike` | Own PyTorch iTransformer, QLIKE on log-volatility | 0.5856 | -7.3% | — | 1.070 | — | 546s |
| 2026-10-08 | `itransformer_mae` (seed 0) | Own PyTorch iTransformer, MAE on log-volatility | 0.5244 | +4.0% | — | 1.319 | — | 410s |
| 2026-10-08 | `itransformer_mae` (seed 1) | Own PyTorch iTransformer, MAE on log-volatility | 0.5247 | +3.9% | — | 1.304 | — | 407s |
| 2026-10-08 | `itransformer_mae` (seed 2) | Own PyTorch iTransformer, MAE on log-volatility | 0.5220 | +4.4% | — | 1.297 | — | 414s |
| 2026-10-08 | `itransformer_mae_path` (seed 0) | Own PyTorch iTransformer, 5-step path head, MAE over the 5 steps | 0.5026 | +7.9% | — | 1.292 | — | 439s |
| 2026-10-08 | `itransformer_mae_path` (seed 1) | Own PyTorch iTransformer, 5-step path head, MAE over the 5 steps | 0.5100 | +6.6% | — | 1.284 | — | 411s |
| 2026-10-08 | `itransformer_mae_path` (seed 2) | Own PyTorch iTransformer, 5-step path head, MAE over the 5 steps | 0.5069 | +7.2% | — | 1.289 | — | 403s |
| 2026-10-08 | **`itransformer_mae` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.5220 to 0.5247 (width 0.0027) | 0.5237 | +4.1% | — | 1.307 | — | 1231s total |
| 2026-10-08 | **`itransformer_mae_path` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.5026 to 0.5100 (width 0.0073) | 0.5065 | +7.2% | — | 1.288 | — | 1253s total |
| 2026-10-08 | `itransformer_path_feats` (seed 0) | Own PyTorch iTransformer, 5-step path head, 4 input channels (vol, return, range, volume) | 0.4924 | +9.8% | — | 1.284 | — | 389s |
| 2026-10-08 | `itransformer_path_feats` (seed 1) | Own PyTorch iTransformer, 5-step path head, 4 input channels (vol, return, range, volume) | 0.4974 | +8.9% | — | 1.279 | — | 385s |
| 2026-10-08 | `itransformer_path_feats` (seed 2) | Own PyTorch iTransformer, 5-step path head, 4 input channels (vol, return, range, volume) | 0.4948 | +9.4% | — | 1.278 | — | 394s |
| 2026-10-08 | **`itransformer_path_feats` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4924 to 0.4974 (width 0.0050) | 0.4948 | +9.4% | — | 1.280 | — | 1168s total |
| 2026-10-12 | `itransformer_path_feats` | Own PyTorch iTransformer, 5-step path head, 4 input channels (vol, return, range, volume) | 0.4924 | +9.8% | — | 1.284 | — | 364s |
| 2026-10-12 | `itransformer_graph_gnn_corr` (seed 0) | path_feats + graph layer h + g·A·Linear(h), market-adjusted correlation map | 0.4924 | +9.8% | 0.4927 | 1.284 | -0.044 | 327s |
| 2026-10-12 | `itransformer_graph_gnn_corr` (seed 1) | path_feats + graph layer h + g·A·Linear(h), market-adjusted correlation map | 0.4975 | +8.9% | 0.4971 | 1.280 | 0.019 | 327s |
| 2026-10-12 | `itransformer_graph_gnn_corr` (seed 2) | path_feats + graph layer h + g·A·Linear(h), market-adjusted correlation map | 0.4952 | +9.3% | 0.4987 | 1.278 | 0.076 | 328s |
| 2026-10-12 | `itransformer_graph_bias_corr` (seed 0) | path_feats + attention bias lambda·S per head and layer, market-adjusted correlation map | 0.4924 | +9.8% | 0.4931 | 1.284 | 0.454 | 337s |
| 2026-10-12 | `itransformer_graph_bias_corr` (seed 1) | path_feats + attention bias lambda·S per head and layer, market-adjusted correlation map | 0.4977 | +8.9% | 0.4978 | 1.280 | 0.471 | 338s |
| 2026-10-12 | `itransformer_graph_bias_corr` (seed 2) | path_feats + attention bias lambda·S per head and layer, market-adjusted correlation map | 0.4946 | +9.4% | 0.5004 | 1.277 | 0.563 | 371s |
| 2026-10-12 | **`itransformer_graph_gnn_corr` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4924 to 0.4975 (width 0.0051) | 0.4950 | +9.3% | 0.4961 | 1.281 | 0.017 | 982s total |
| 2026-10-12 | **`itransformer_graph_bias_corr` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4924 to 0.4977 (width 0.0053) | 0.4949 | +9.4% | 0.4971 | 1.280 | 0.496 | 1046s total |
| 2026-10-12 | `itransformer_graph_gnn_sector` (seed 0) | path_feats + graph layer h + g·A·Linear(h), sector map | 0.4926 | +9.8% | 0.4920 | 1.284 | 0.008 | 398s |
| 2026-10-12 | `itransformer_graph_gnn_sector` (seed 1) | path_feats + graph layer h + g·A·Linear(h), sector map | 0.4971 | +9.0% | 0.4975 | 1.279 | 0.014 | 384s |
| 2026-10-12 | `itransformer_graph_gnn_sector` (seed 2) | path_feats + graph layer h + g·A·Linear(h), sector map | 0.4952 | +9.3% | 0.4987 | 1.278 | 0.091 | 382s |
| 2026-10-12 | `itransformer_graph_gnn_shuffled` (seed 0) | path_feats + graph layer h + g·A·Linear(h), shuffled correlation map (control) | 0.4925 | +9.8% | 0.4919 | 1.284 | 0.006 | 397s |
| 2026-10-12 | `itransformer_graph_gnn_shuffled` (seed 1) | path_feats + graph layer h + g·A·Linear(h), shuffled correlation map (control) | 0.4970 | +9.0% | 0.4974 | 1.279 | -0.005 | 408s |
| 2026-10-12 | `itransformer_graph_gnn_shuffled` (seed 2) | path_feats + graph layer h + g·A·Linear(h), shuffled correlation map (control) | 0.4947 | +9.4% | 0.4990 | 1.279 | 0.054 | 402s |
| 2026-10-12 | **`itransformer_graph_gnn_sector` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4926 to 0.4971 (width 0.0044) | 0.4950 | +9.3% | 0.4961 | 1.280 | 0.038 | 1164s total |
| 2026-10-12 | **`itransformer_graph_gnn_shuffled` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4925 to 0.4970 (width 0.0044) | 0.4947 | +9.4% | 0.4961 | 1.280 | 0.018 | 1207s total |
