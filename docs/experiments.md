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
| 2026-10-13 | `pair_equal` (seed 0) | Mean of calibrated weak_signals and path_feats, calibrated again; no training (seed = path_feats seed) | 0.4789 | +12.3% | 0.4570 | 0.992 | — | — |
| 2026-10-13 | `pair_equal` (seed 1) | Mean of calibrated weak_signals and path_feats, calibrated again; no training (seed = path_feats seed) | 0.4842 | +11.3% | 0.4585 | 0.992 | — | — |
| 2026-10-13 | `pair_equal` (seed 2) | Mean of calibrated weak_signals and path_feats, calibrated again; no training (seed = path_feats seed) | 0.4795 | +12.2% | 0.4595 | 0.991 | — | — |
| 2026-10-13 | `pair_2019` (seed 0) | 0.2·path_feats + 0.8·weak_signals, w chosen on mean 2019 QLIKE from 0.0-1.0, calibrated again; no training | 0.4857 | +11.1% | 0.4526 | 0.997 | — | — |
| 2026-10-13 | `pair_2019` (seed 1) | 0.2·path_feats + 0.8·weak_signals, w chosen on mean 2019 QLIKE from 0.0-1.0, calibrated again; no training | 0.4882 | +10.6% | 0.4531 | 0.997 | — | — |
| 2026-10-13 | `pair_2019` (seed 2) | 0.2·path_feats + 0.8·weak_signals, w chosen on mean 2019 QLIKE from 0.0-1.0, calibrated again; no training | 0.4855 | +11.1% | 0.4535 | 0.996 | — | — |
| 2026-10-13 | `committee_v2` (seed 0) | Equal-weight mean of short_term, regime, weak_signals and path_feats (in place of multivariate), calibrated again; no training | 0.4977 | +8.8% | 0.4537 | 0.986 | — | — |
| 2026-10-13 | `committee_v2` (seed 1) | Equal-weight mean of short_term, regime, weak_signals and path_feats (in place of multivariate), calibrated again; no training | 0.5014 | +8.2% | 0.4550 | 0.987 | — | — |
| 2026-10-13 | `committee_v2` (seed 2) | Equal-weight mean of short_term, regime, weak_signals and path_feats (in place of multivariate), calibrated again; no training | 0.4977 | +8.8% | 0.4549 | 0.986 | — | — |
| 2026-10-13 | **`pair_equal` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4789 to 0.4842 (width 0.0052) | 0.4809 | +11.9% | 0.4583 | 0.992 | — | — |
| 2026-10-13 | **`pair_2019` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4855 to 0.4882 (width 0.0027) | 0.4864 | +10.9% | 0.4531 | 0.997 | — | — |
| 2026-10-13 | **`committee_v2` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4977 to 0.5014 (width 0.0037) | 0.4990 | +8.6% | 0.4546 | 0.986 | — | — |
| 2026-10-13 | `itransformer_path_feats6` (seed 0) | path_feats + 2 channels: overnight gap log(open/prev close) and log VIX close (6 channels) | 0.4934 | +9.6% | 0.5120 | 1.292 | — | 318s |
| 2026-10-13 | `itransformer_path_feats6` (seed 1) | path_feats + 2 channels: overnight gap log(open/prev close) and log VIX close (6 channels) | 0.5112 | +6.4% | 0.5029 | 1.290 | — | 319s |
| 2026-10-13 | `itransformer_path_feats6` (seed 2) | path_feats + 2 channels: overnight gap log(open/prev close) and log VIX close (6 channels) | 0.4934 | +9.6% | 0.5090 | 1.276 | — | 319s |
| 2026-10-13 | **`itransformer_path_feats6` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4934 to 0.5112 (width 0.0178) | 0.4993 | +8.5% | 0.5080 | 1.286 | — | 956s total |
| 2026-10-13 | `earnings_jump:supervisor` | Earnings layer A (jump): + 252/5·J to the variance in earnings weeks, then calibrated; supervisor; retuned window 120, temperature 0.25 | 0.4263 | +21.9% | 0.4087 | — | — | — |
| 2026-10-13 | `earnings_jump:equal_weight` | Earnings layer A (jump): + 252/5·J to the variance in earnings weeks, then calibrated; equal-weight | 0.4300 | +21.2% | 0.4109 | — | — | — |
| 2026-10-13 | `earnings_jump:short_term` | Earnings layer A (jump): + 252/5·J to the variance in earnings weeks, then calibrated; short-term | 0.4881 | +10.6% | 0.4314 | 1.142 | — | — |
| 2026-10-13 | `earnings_jump:regime` | Earnings layer A (jump): + 252/5·J to the variance in earnings weeks, then calibrated; regime | 0.4807 | +12.0% | 0.4442 | 1.005 | — | — |
| 2026-10-13 | `earnings_jump:weak_signals` | Earnings layer A (jump): + 252/5·J to the variance in earnings weeks, then calibrated; weak-signals | 0.4338 | +20.5% | 0.4085 | 1.221 | — | — |
| 2026-10-13 | `earnings_jump:itransformer` | Earnings layer A (jump): + 252/5·J to the variance in earnings weeks, then calibrated; itransformer | 0.4275 | +21.7% | 0.4305 | 1.188 | — | — |
| 2026-10-13 | `earnings_split:supervisor` | Earnings layer B (split calibration): earnings and ordinary weeks calibrated separately; supervisor; retuned window 120, temperature 1.0 | 0.4320 | +20.9% | 0.4113 | — | — | — |
| 2026-10-13 | `earnings_split:equal_weight` | Earnings layer B (split calibration): earnings and ordinary weeks calibrated separately; equal-weight | 0.4329 | +20.7% | 0.4121 | — | — | — |
| 2026-10-13 | `earnings_split:short_term` | Earnings layer B (split calibration): earnings and ordinary weeks calibrated separately; short-term | 0.4923 | +9.8% | 0.4341 | 1.200 | — | — |
| 2026-10-13 | `earnings_split:regime` | Earnings layer B (split calibration): earnings and ordinary weeks calibrated separately; regime | 0.4814 | +11.8% | 0.4471 | 1.048 | — | — |
| 2026-10-13 | `earnings_split:weak_signals` | Earnings layer B (split calibration): earnings and ordinary weeks calibrated separately; weak-signals | 0.4379 | +19.8% | 0.4076 | 1.287 | — | — |
| 2026-10-13 | `earnings_split:itransformer` | Earnings layer B (split calibration): earnings and ordinary weeks calibrated separately; itransformer | 0.4342 | +20.5% | 0.4321 | 1.254 | — | — |
| 2026-10-27 | `stgnn_nograph` (seed 0) | ST-GNN supervisor, temporal part only: GRU over each skill's last L errors, softmax head from equal weights; L = 10; quarterly refits; no recalibration | 0.4284 | +21.5% | 0.4038 | — | — | 146s |
| 2026-10-27 | `stgnn_nograph` (seed 1) | ST-GNN supervisor, temporal part only: GRU over each skill's last L errors, softmax head from equal weights; L = 10; quarterly refits; no recalibration | 0.4264 | +21.9% | 0.4035 | — | — | 150s |
| 2026-10-27 | `stgnn_nograph` (seed 2) | ST-GNN supervisor, temporal part only: GRU over each skill's last L errors, softmax head from equal weights; L = 10; quarterly refits; no recalibration | 0.4262 | +21.9% | 0.4034 | — | — | 134s |
| 2026-10-27 | `stgnn_corr` (seed 0) | ST-GNN supervisor: GRU + graph layers H + g·A·H·W on the market-adjusted correlation map; L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4322 | +20.8% | 0.4049 | — | 1.776 | 148s |
| 2026-10-27 | `stgnn_corr` (seed 1) | ST-GNN supervisor: GRU + graph layers H + g·A·H·W on the market-adjusted correlation map; L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4276 | +21.7% | 0.4043 | — | 1.448 | 144s |
| 2026-10-27 | `stgnn_corr` (seed 2) | ST-GNN supervisor: GRU + graph layers H + g·A·H·W on the market-adjusted correlation map; L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4276 | +21.7% | 0.4043 | — | 1.745 | 146s |
| 2026-10-27 | `stgnn_sector` (seed 0) | ST-GNN supervisor: GRU + graph layers on the sector map; L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4345 | +20.4% | 0.4049 | — | 1.770 | 197s |
| 2026-10-27 | `stgnn_sector` (seed 1) | ST-GNN supervisor: GRU + graph layers on the sector map; L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4289 | +21.4% | 0.4042 | — | 1.386 | 227s |
| 2026-10-27 | `stgnn_sector` (seed 2) | ST-GNN supervisor: GRU + graph layers on the sector map; L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4277 | +21.7% | 0.4044 | — | 1.650 | 234s |
| 2026-10-27 | `stgnn_shuffled` (seed 0) | ST-GNN supervisor: GRU + graph layers on the correlation map with stocks shuffled (control); L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4335 | +20.6% | 0.4046 | — | 1.849 | 318s |
| 2026-10-27 | `stgnn_shuffled` (seed 1) | ST-GNN supervisor: GRU + graph layers on the correlation map with stocks shuffled (control); L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4278 | +21.7% | 0.4039 | — | 1.521 | 419s |
| 2026-10-27 | `stgnn_shuffled` (seed 2) | ST-GNN supervisor: GRU + graph layers on the correlation map with stocks shuffled (control); L = 10, 1 graph layer(s); quarterly refits; no recalibration | 0.4277 | +21.7% | 0.4039 | — | 1.824 | 371s |
| 2026-10-27 | **`stgnn_nograph` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4262 to 0.4284 (width 0.0021) | 0.4270 | +21.8% | 0.4036 | — | — | 430s total |
| 2026-10-27 | **`stgnn_corr` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4276 to 0.4322 (width 0.0046) | 0.4291 | +21.4% | 0.4045 | — | 1.656 | 438s total |
| 2026-10-27 | **`stgnn_sector` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4277 to 0.4345 (width 0.0067) | 0.4304 | +21.2% | 0.4045 | — | 1.602 | 658s total |
| 2026-10-27 | **`stgnn_shuffled` mean of 3 seeds** | Mean over seeds 0, 1, 2; QLIKE spread 0.4277 to 0.4335 (width 0.0058) | 0.4296 | +21.3% | 0.4041 | — | 1.731 | 1108s total |
