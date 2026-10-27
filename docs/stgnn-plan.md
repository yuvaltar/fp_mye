# ST-GNN supervisor: plan

Owner: Elie, branch `algo-elie`. Written 2026-10-22, from the code and the committed artifacts on `main` (`ca186a8`).

## 1. Goal

Replace the supervisor's fixed rule with a small learned **spatio-temporal graph network** that decides each skill's weight, per stock and per day.

Today the supervisor scores each skill by its mean QLIKE over its last 120 known predictions, for one stock at a time, and turns those scores into weights with a softmax. It shares nothing between stocks and sees nothing but that one average. The ST-GNN supervisor keeps the same job and the same output, and adds two things:

- **Temporal:** it reads the *sequence* of each skill's recent errors (is a skill drifting, did it just miss a spike?) instead of one average.
- **Graph:** it lets stocks that move together share that information through the market map Yuval built (`tsm/models/graph.py`). If the skills just missed on JPM, they probably missed on BAC too.

Its output is still one weight per skill per stock and date, summing to 1. The API, the contract and the website do not change.

This is not a new skill. A graph inside the iTransformer was tried in Steps 8–9 and gave no gain (a shuffled map scored the same), so a fifth graph-based predictor is not planned.

## 2. Starting point (verified)

Recomputed on 2026-10-22 from `algo/artifacts/predictions.csv` (52 tickers, as-of dates 2018-01-02 to 2026-10-07), QLIKE, lower is better:

| Model | Test 2020-01 to 2026-09 (88,140 predictions) | 2019 (13,104 predictions) |
| --- | ---: | ---: |
| Supervisor (window 120, temperature 0.25) | 0.4263 | 0.4087 (in-sample: it was tuned on these dates) |
| `itransformer` | 0.4275 | 0.4305 |
| Equal-weight average | 0.4300 | 0.4109 |
| `weak_signals` | 0.4338 | 0.4085 |
| `regime` | 0.4807 | 0.4442 |
| `short_term` | 0.4881 | 0.4314 |
| HAR-RV baseline | 0.5460 | 0.4895 |

These match `docs/backtest.md`. `docs/handoff.md` gives temperature 1.0 for the supervisor (Step 11); the current `meta.json` says 0.25 (retuned when the earnings layer went in, Step 13). The artifacts are what counts.

**The bar.** The ST-GNN supervisor is kept only if, on the test period, the mean of seeds 0, 1 and 2 beats the current supervisor (0.4263), the equal-weight average (0.4300) and the best single skill (0.4275), with every seed better than equal-weight. Every design choice is made on 2019; the test period is looked at once per candidate, at the end.

## 3. Design

### Inputs, for a stock *i* on as-of date *p*

All of them come from columns already in `predictions.csv`, plus the price cache for the graph.

| Input | Built from | Known at *p* because |
| --- | --- | --- |
| The last L = 20 errors of each skill, `log(realized / predicted)` | `pred_<skill>` (calibrated) and `realized_vol` of rows at positions ≤ *p* − 5 | Same rule as today's supervisor: an outcome is known 5 trading days after its prediction. |
| Today's spread between skills, `log(pred_k) − mean_k log(pred_k)` | `pred_<skill>` at *p* | It is the skills' own forecast for *p*. |
| Earnings week flag | `earnings_week` at *p* | Release dates are assumed known 5 trading days ahead (the earnings layer's existing assumption). |
| Market map `A` (52 × 52) | `correlation_adjacency` on returns up to *p* (window 120, k = 5, market-adjusted: Yuval's fixed settings) | `graph.py` is already leakage-tested. |

### Network (about 3,000 parameters)

1. **Temporal encoder:** a GRU with 16 hidden units reads each stock's 20-step error sequence (4 skills = 4 channels). Shared by all stocks.
2. **Graph layer:** `H ← H + g · A · H · W`, with a gate `g` that starts at 0, so the model starts with no graph and only uses it if that lowers the loss. Two such layers at most.
3. **Head:** a linear layer from the stock's state to 4 logits, **initialized at zero**, then a softmax. At the start every weight is 1/4, so the model starts exactly at the equal-weight average and has to earn every move away from it.
4. **Prediction:** `sum_k w_k · pred_k`, the same convex combination as today.
5. **Confidence:** the current formula, `exp(-mean QLIKE)` of the supervisor's own recent known predictions, so `supervisor_confidence` keeps its meaning on the site.

**Loss:** QLIKE of the combined prediction against `realized_vol`. The lesson from Step 3 (QLIKE training substitutes for calibration) does not apply here: the inputs are already calibrated and the network only chooses weights, not a level.

### Training, walk-forward

- **Choosing settings:** fit on outcomes known before 2019-01-01, score 2019. The few choices (L in {10, 20, 60}, graph or not, one or two graph layers) are made on 2019 only.
- **Test:** refit every 63 trading days (one quarter) from 2020-01-02, on every outcome known at the refit date, then predict until the next refit. This is the same discipline as the skills' `refit_every_days`.
- **Seeds:** 0, 1 and 2, fixed on every fit. Report the mean and the min–max spread; a gap smaller than the spread is "not settled".

### Controls, decided now

| Variant | What it shows |
| --- | --- |
| `stgnn_nograph` (A = identity) | What the temporal part alone gives. |
| `stgnn_corr` | The real candidate. |
| `stgnn_sector` (sector map) | Whether a fixed map does as well. |
| `stgnn_shuffled` (map with stocks shuffled) | Whether the graph's gain is real. If shuffled matches corr, the graph is not why it works, as in Step 9. |

## 4. How the integration works

The work goes in two phases. Phase A never touches the production engine, so it cannot break the API or the site and does not collide with Yuval's work. Phase B happens only if phase A clears the bar.

### Phase A: experiment, beside the engine

New files only, all in `algo/`:

| File | Role |
| --- | --- |
| `tsm/models/stgnn.py` | The network and the input builder (pure functions for the inputs). |
| `tsm/stgnn.py` | `python -m tsm.stgnn [variants] --seeds 0 1 2`: reads `artifacts/predictions.csv` and the frozen price cache, walks the supervisor forward, scores it exactly like the report, appends rows to `docs/experiments.md`, saves predictions to `algo/experiments/` (git-ignored). |
| `tests/test_stgnn.py` | Leakage tests and the gates below. |

It reads the existing artifacts and writes nothing in `artifacts/`, `docs/backtest.md`, `supervisor.py`, `backtest.py`, `report.py` or `api.py`. An md5 check before and after each run proves it, as in Yuval's experiments.

**Gates before any result counts:**
1. Re-applying today's `Supervisor(window=120, temperature=0.25)` to the saved calibrated predictions reproduces the `supervisor` column to 1e-9. This proves the runner reads the data the way the backtest does.
2. The ST-GNN with its head at zero (before training) gives exactly the equal-weight column.
3. Leakage: corrupting every `realized_vol` and every price after date *p* leaves all weights up to *p* unchanged, for the trained model and for the inputs alone. Same principle as `tests/test_backtest.py`.
4. The panel's date at each `position` equals the `date` in `predictions.csv`.

### Phase B: into the product, only if phase A wins

| File | Change |
| --- | --- |
| `tsm/supervisor.py` | Add a `GraphSupervisor` class with the same output columns as `Supervisor.combine` (`w_<skill>`, `supervisor`, `confidence`). The current `Supervisor` stays. |
| `tsm/backtest.py` | `finish_pipeline` fits the ST-GNN instead of the grid search, behind a `--supervisor stgnn|softmax` flag, so the old path stays reproducible (like `--no-earnings`). |
| `meta.json` | `"supervisor"` gains a `"kind"` field and the ST-GNN's settings. |
| `tsm/report.py` | The "Supervisor settings" line reads the new fields (it reads `window` and `temperature` today), and a new section compares the ST-GNN with the softmax supervisor, with the shuffled control. |
| `tsm/api.py` | No change: it reads the same columns. |
| `/contracts`, `/web` | No change. Tell Maor if the `/about` page describes the supervisor as a softmax over recent errors. |

Then: `python -m tsm.backtest` (about 40 minutes) regenerates the artifacts and `docs/backtest.md`; `pytest` must pass, including `test_api_published.py`, whose pinned numbers come from the new report; then PR `algo-elie` → `algo` → `main`.

Phase B touches `supervisor.py`, `backtest.py` and `report.py`, which Yuval also works on. Agree on the timing with him before starting it.

## 5. Steps

| # | Step | Produces | Stop if |
| --- | --- | --- | --- |
| 0 | Setup: freeze the missing 42 tickers and `^VIX` up to 2026-10-07 (`freeze_prices`), run `pytest`. | A local cache matching `meta.json`. | Tests fail on a clean checkout. |
| 1 | Input builder + leakage tests + gates 1, 2 and 4. | `tsm/models/stgnn.py` (inputs), `tests/test_stgnn.py`. | A gate does not reproduce exactly. |
| 2 | Network + runner, variant `stgnn_nograph`, settings chosen on 2019. | First rows in `docs/experiments.md`. | It cannot beat equal-weight on 2019: report it and stop before adding the graph. |
| 3 | Graph variants: `corr`, `sector`, `shuffled`, 3 seeds each. | The comparison table. | — |
| 4 | Decision against the bar of section 2. | A go / no-go written in `docs/experiments.md`. | No-go: write the negative result, skip phase B. |
| 5 | Phase B (after agreeing with Yuval). | New artifacts, `docs/backtest.md`, PR. | Any test fails. |
| 6 | Write-up for the defence: what the ST-GNN learned, the controls, and the honest result. | A section in the report. | — |

## 6. Risks

- **Little training data before 2019.** About 250 dates × 52 stocks have known outcomes before 2019 (13,000 rows), which is why the network stays near 3,000 parameters and starts from equal weights.
- **The bar is close.** The current supervisor, the equal-weight average and `itransformer` are within 0.004 of each other. A real gain may be smaller than the seed spread; then the result is "not settled", and it is reported that way.
- **Prices for the graph.** The frozen cache on this machine will be downloaded now, not on 2026-10-08 like Yuval's, so adjusted closes can differ slightly. Log returns barely change under a dividend adjustment, so the map should not move; gate 4 and a check of the map against `docs/graph_assets/adjacency_2024-06-28.png` confirm it. Yuval's own cache files would remove the doubt.
- **Phase B needs the earnings dates** (`python -m tsm.earnings`, needs `SEC_USER_AGENT`) for the full backtest. Phase A does not: the earnings jump is already inside the saved calibrated predictions.
