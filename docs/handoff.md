# Handoff: Yuval's work in /algo (as of Monday 2026-10-12)

Written for a new Claude Code session that continues Yuval's work on the engine. The root `CLAUDE.md` is still the authority on rules, layout and commands; this file adds everything that happened since it was written and what is not visible from the code alone. Sources: git history, the session transcripts, `docs/backtest.md`, `docs/experiments.md`, and Maor's branch.

---

## 1. State in ten lines

1. The engine works end to end: 52 tickers, four committee skills, per-skill calibration, a tuned supervisor, a 2020–2026 walk-forward backtest, artifacts for the API, and a generated report.
2. **Headline result (since Step 11):** the supervisor beats HAR-RV on QLIKE by 10.9% (0.4862 vs 0.5460), on 52 of 52 tickers, t-statistic 4.75. Committee: `short_term`, `regime`, `weak_signals`, `itransformer` (our own model, mean of 3 seeds, replaced `multivariate`).
3. **Central weakness:** the supervisor is still essentially tied with a plain equal-weight average (0.4862 vs 0.4869; retuned temperature 1.0 gives near-equal weights). The Step 11 gain came from the better member, not from the weighting.
4. We wrote our own PyTorch iTransformer (`tsm/models/itransformer.py`) plus an experiment runner (`python -m tsm.experiment`) that scores candidates without re-running the committee.
5. **`itransformer_path_feats` was promoted in Step 11** as the committee skill `itransformer` (seeds 0, 1, 2 averaged: 0.4888 on test, against 0.4948 for the average single seed).
6. Branch `algo-yuval` is at `b77157a` (Step 12); `origin/algo-yuval` is at `979df92` (later commits not pushed). None of this is **merged into `algo`**, and nothing from the engine or the site is on `main` yet.
7. **Deadline (updated 2026-10-12): the real deadline is about 1.5 weeks away, around 2026-10-22**, not the 2026-10-14 freeze written in `docs/plan.md`. The day-by-day table in the plan still describes the original 7 days.
8. Maor has a full website on branch `web-initial-site` and has sent the algo team a **contract-change proposal that is not yet agreed** (section 9).
9. `pytest` in `algo/`: **200 passed** after Step 12 (2026-10-13).
11. **Steps 8–9 (market map, graph iTransformer): the graph adds nothing measurable** over path_feats; see the end of section 6.
12. **Step 10:** `pair_2019` (0.2·path_feats + 0.8·weak_signals) wins on 2019 and edges weak_signals on test (0.4864 vs 0.4885); two more input channels (gap, VIX) made path_feats worse.
13. **Step 11 (product change):** the API now returns the skill names `short_term`, `regime`, `weak_signals`, `itransformer`. Maor's site labels `multivariate` but shows `itransformer` through its fallback label: tell Maor (not a contract change).
14. **Step 12:** earnings dates collected (Yahoo, checked against SEC); the earnings layer's jump variant takes the supervisor to 0.4263 on test.
15. **Step 13 (product change):** the earnings layer is on in `python -m tsm.backtest`; the supervisor is now 0.4263 (+21.9% vs HAR-RV). The API's shape is unchanged.
10. Working tree clean. No uncommitted work.

---

## 2. Timeline and what the plan expects next

From `docs/plan.md` (day 1 = Thu 2026-10-08). **The real deadline is around 2026-10-22** (note added 2026-10-12), so the dates below have slack; the order of the work still holds.

| Day | Date | Algo, according to the plan | Where we actually are |
| --- | --- | --- | --- |
| 5 | **Mon 12 Oct (today)** | FastAPI with the 3 endpoints, CORS. **Integration checkpoint** with Maor (uvicorn :8000 + `npm run dev` :3000, `NEXT_PUBLIC_USE_MOCKS=false`). | API already built (Elie). Checkpoint not done yet. |
| 6 | Tue 13 Oct | Fix integration issues, tune the supervisor, extend tickers, final `docs/backtest.md`. | Tickers already extended to 52. |
| 7 | Wed 14 Oct | Freeze by midday. Write-up of method and results. Everything merged to `main`, demo runs from a clean clone. | — |

The checkpoint passes when `/tickers`, `/predict?ticker=AAPL` and `/history?ticker=AAPL` return live data that validates against the schema, the site shows AAPL/TEVA/NVDA live, an unknown ticker returns 404 with a clear message on the site, and `pytest` / `npm run build` / `npm run typecheck` all pass.

**Important for integration:** the 52-ticker artifacts exist only on `algo-yuval`. `origin/algo` still serves the 10-ticker artifacts from before step 2. Merge `algo-yuval` into `algo` before integrating, or the site will see 10 tickers.

---

## 3. Git state

GitHub repo: `https://github.com/yuvaltar/fp_mye`. The `gh` CLI is **not installed** on this machine, so PRs are opened in the GitHub web UI.

| Branch | Tip | Contents |
| --- | --- | --- |
| `main` | `238a1db` | Repo foundations only (PR #1). No engine, no site. |
| `algo` | `83e81e6` | Elie's engine + Yuval's calibration step (PR #2 merged `algo-yuval` up to `a0b8f3e`). 10 tickers. |
| **`algo-yuval`** | **`a7713b1`** local, `979df92` on GitHub | `algo` + 4 commits: 52 tickers, own iTransformer + experiment runner, path head, 4 channels. **No PR yet** (none visible from here; check GitHub). |
| `algo-elie` | `0cc9ded` | Elie's original engine commit; nothing newer pushed. |
| `web` | `238a1db` | Untouched. |
| `web-initial-site` | `924d41f` (2026-10-12) | Maor's site: watchlist, stock page, performance, about, optional live Yahoo market data, 107 `node:test` tests. Not merged anywhere. |

Yuval's commits, oldest first:

| Commit | Message | Step |
| --- | --- | --- |
| `a0b8f3e` | Calibrate every skill before scoring it | 1 (merged into `algo` via PR #2) |
| `ecf4ed8` | Expand the universe to 52 tickers in ten sectors | 2 |
| `c286458` | Add own iTransformer and experiment runner (QLIKE loss did not help) | 3 |
| `c3aa776` | Add 5-step path head: matches neuralforecast over 3 seeds | 3b |
| `d572059` | Add 4 input channels per stock: beats the committee over 3 seeds | 4 |
| `50359e7` | Team change, doc refresh, frozen prices for experiments | 7 |
| `92e72c3` | Add the market map: correlation and sector adjacency with leakage tests | 8 (not pushed) |
| `a4e2654` | Feed the market map into the iTransformer: no gain over path_feats | 9 (not pushed) |
| `c909b6b` | Update the handoff after Steps 8 and 9 | docs (not pushed) |
| `979df92` | Combine path_feats with weak_signals; two more channels make it worse | 10 |
| `adf9014` | Update the handoff after Step 10 | docs (not pushed) |
| `a7713b1` | Put our iTransformer in the committee in place of multivariate | 11 (not pushed) |

Each commit message has a long body with the rationale, the results and the verification. `git show <hash>` is the most detailed record of each step.

**Pushing:** the first time, Claude could not push (no credentials) and Yuval ran `git push origin algo-yuval` in their own terminal (Git Credential Manager opens a browser login). Only push when told to.

---

## 4. Environment on this machine (Windows 11)

- **Python:** 3.12.10, installed with winget at `C:\Users\yuval\AppData\Local\Programs\Python\Python312`, next to a 3.13 install. **Do not use the `python3.12` on PATH**: it is an MSYS2/MinGW build with no PyPI wheels (torch and pandas fail to build there).
- **venv:** `algo/.venv`, Windows layout (`Scripts/`, not `bin/`). The simplest option is to call the interpreter directly: `algo/.venv/Scripts/python.exe -m pytest`. Activation: `source .venv/Scripts/activate` (Git Bash) or `.venv\Scripts\Activate.ps1` (PowerShell). CLAUDE.md's `source .venv/bin/activate` is the Unix form.
- Installed versions: torch 2.14.1+cpu, pandas 3.0.6, numpy 2.5.3, neuralforecast 3.3.0. CPU only.
- **Always write text files with `encoding="utf-8"`.** The Windows default (ANSI codepage) is what turned the report's em-dashes into mojibake. `report.py` and `experiment.py` already do this.
- **Price cache:** `algo/data/` (git-ignored) holds 52 CSVs downloaded on 2026-10-08. See the gotcha in section 10: any run on a new day downloads them again.

Runtimes measured here (warm cache):

| Command | Time |
| --- | --- |
| `pytest` (92 tests) | 3 to 4.5 min |
| `python -m tsm.backtest`, 52 tickers | **2320 s ≈ 39 min** (10 tickers: 839 s) |
| `python -m tsm.experiment <one candidate>` | ~320–450 s per seed |
| Same, `--seeds 0 1 2` | ~20 min |

Run long jobs in the background and report progress. When Yuval asks "is it still running?", show the last 20 lines of the log and the elapsed time, and do not stop the job.

---

## 5. The engine in one page (what Elie built + what changed)

`tsm/backtest.py:run_pipeline` is the whole pipeline:

1. `run_skills`: walk forward day by day from 2018-01-02. Each skill receives `truncate_panel(panel, position)`, refits every `refit_every_days`, and predicts every day. Output columns: `pred_<skill>`.
2. `add_targets_and_baselines`: `realized_vol` (forward 5-day), `naive`, then **`calibrate`** (step 1, below), then `equal_weight` = the mean of the calibrated skills, then `baseline` = the calibrated `pred_short_term`.
3. `tune_supervisor`: grid search, `WINDOW_GRID = (10, 20, 60, 120)` × `TEMPERATURE_GRID = (0.02, 0.05, 0.1, 0.25, 1.0)`, on dates whose outcome was known before 2020-01-01. **Current choice (Step 11): window 120, temperature 1.0** (was 0.25 with multivariate).
4. `apply_supervisor`: per ticker, softmax over minus each skill's mean QLIKE on its last `window` predictions whose outcome is known (position ≤ p − 5). `confidence` = exp(−mean QLIKE of the supervisor's own recent predictions), 0.5 before any outcome is known.
5. `main` writes `algo/artifacts/predictions.csv` (~25 MB, committed) and `meta.json`, then `report.write_report` writes `docs/backtest.md`, 3 PNGs, and `docs/backtest_assets/results.csv` / `weights.csv` (git-ignored).

The committee (`build_skills` in `tsm/supervisor.py`): `short_term` (HAR-RV, short, refit every 5 days), `regime` (GARCH(1,1), long, 20), `weak_signals` (HistGradientBoosting on abnormal volume, range, gap and SPY correlation, short, 20), `multivariate` (neuralforecast iTransformer, medium, 125).

`tsm/api.py` serves only the artifacts: `/tickers`, `/predict`, `/history`. It returns 404 for an unknown ticker and **503 when `predictions.csv` is missing** (Maor's site relies on that 503). The API reads only `skills` and `model_version` from `meta.json`. New predictions appear only after re-running the backtest. The current artifacts end on **`last_date` 2026-10-07**.

`predictions.csv` columns: `date, ticker, position, pred_<4 skills>, realized_vol, naive, raw_pred_<skill>, c_<skill>` (×4), `equal_weight, baseline, w_<skill>` (×4), `supervisor, confidence`.

---

## 6. What Yuval did, step by step

### Step 0: environment and first run (2026-10-08)
Installed Python 3.12.10, created the venv, ran 57 tests (all passed), and ran a first backtest on 10 tickers (996 s with a cold cache). Before calibration, `regime` looked best on QLIKE (0.4934) and the supervisor was at 0.5202 (+10.7% vs HAR-RV). Found the em-dash mojibake bug.

### Step 1: fair calibration (`a0b8f3e`, merged via PR #2)
**Problem:** skills trained on log-volatility or with MAE predict too low in the tail, and QLIKE punishes under-prediction, so the report was ranking models by their bias rather than their skill.

**What we built** (`tsm/backtest.py`):
- `calibration_factors(frame, skill_names, window=250, horizon=5)`: per skill and per date, `c = sqrt(mean((realized/predicted)^2))`, pooled over all tickers, over the last `CALIBRATION_WINDOW = 250` trading days of predictions **whose outcome was already known** on that date. The boundary is `np.searchsorted(dates, dates - horizon, side="right")`, the same rule `Supervisor.combine` uses, so the causality rule lives in one place. With fewer than 250 known days it uses all of them; with none, `c = 1`. Non-finite ratios are skipped. Implemented with cumulative sums.
- `calibrate(...)`: keeps `raw_pred_<skill>`, adds `c_<skill>`, and replaces `pred_<skill>` with `raw × c`.
- Order: realized → naive → **calibrate** → equal_weight → baseline. So HAR-RV is calibrated structurally, not through a parallel code path.
- `report.py`: a "Before vs after calibration" section, and `write_text(..., encoding="utf-8")`.
- Tests: the future-corruption test also compares `raw_pred_*` and `c_*`, and asserts that those columns really are in the compared set. Four new tests: the factor recomputed by hand, `c == 1` before any outcome, `pred == raw × c`, and window sensitivity.
- New `tests/test_report.py` (5 smoke tests, ~4 s). The reason: `report.py` is imported inside `main()`, so a `SyntaxError` there passed the entire suite and only failed 14 minutes into a run. Verified that 4 of the 5 tests fail when the UTF-8 fix is reverted.

**Result (10 tickers):** the ranking flipped. `weak_signals` went from worst to best (0.6144 → 0.4554, factor 1.295). `regime` was already calibrated (factor 1.046), gained nothing, and dropped to second-worst. The supervisor reached 0.4714 but **lost to the equal-weight average (0.4694) and to `weak_signals`**. RMSE/MAE got worse across the board, because scaling up trades squared error for coverage of the tail. That makes QLIKE the deliberately chosen metric.

**Important subtlety:** "mean raw bias" (mean of predicted/realized) is above 1 while the factor is also above 1. Both are true: skills read slightly high on a typical day but fall badly short in spikes, and the quadratic mean is dominated by those spikes. A first draft of the report text got this wrong; the committed version explains it.

### Step 2: universe of 52 tickers (`ecf4ed8`)
- `tsm/config.py`: 5 names from each of the 10 GICS sectors, plus TEVA (mid-cap with a different volatility profile) and SPY (also `MARKET_TICKER`). Full list in `config.py`. Note `BRK-B` (Yahoo format, with a dash).
- Diagnostic before the run: all 52 have 2958 rows from 2015-01-02, so `align_panel` cuts nothing. There are 37 days with |log return| > 0.2, all genuine events (COVID 2020-03, oil price war 2020-03-09, NFLX 2022-04-20, META 2022-02-03, ORCL 2025-09-10, TEVA ×4), none a data error.
- `report.py`: `CHART_TICKERS = ["SPY", "AAPL", "NVDA", "TEVA", "JPM", "XOM"]` for the predicted-vs-realized chart (one panel per ticker is unreadable at 52), with a fallback to the first 6 available tickers so the synthetic panel in `test_report.py` does not crash. The caveat now uses the real ticker count, and a **survivorship-bias** caveat was added.
- No model, calibration, grid or test changed.

**Result:** the numbers now in `docs/backtest.md`. 52/52 wins against HAR-RV (median +8.9%, from ABBV +1.2% to SO +18.7%). Calibration factors are stable across universes (weak_signals 1.295 → 1.307, regime 1.046 → 1.065), so they correct a property of each model family, not noise. **But the supervisor is tied with equal-weight** (0.4961 vs 0.4962), and the tuned temperature of 0.25 gives fairly diffuse weights, close to equal weighting by construction.

### Step 3: our own iTransformer + experiment runner (`c286458`)
**Motivation:** `multivariate` goes through neuralforecast, which trains with MAE and **cannot take extra per-stock inputs or a graph**, and later steps need both. The intended direction is a graph-aware iTransformer (the algo team already told Maor that a model "with an unknown name" is coming). It has not been specified or started.

**Architecture** (`tsm/models/itransformer.py`, plain PyTorch):
- Per date, each stock's last 44 days of `log(5-day realized vol)` form **one token**: `Linear(44→64)`, then 2 × `TransformerEncoderLayer(d_model=64, nhead=4, dim_feedforward=128, dropout=0.1)`, then `Linear(64→1)`. Attention runs **across stocks**, not across time (the "inverted" transformer).
- Each stock's window is standardized by its own mean and std inside `forward`, and the output is un-standardized with the same two numbers: the network sees only shape, never level.
- No positional encoding across stocks, so the model is permutation-equivariant.
- Training: one sample = one date with all stocks. Only dates whose target falls inside the panel (`training_positions`). Adam, lr 1e-3, batches of 32 dates, 300 steps, refit every 125 days, all seeds fixed on every fit.
- Losses: `mae` on log-vol, and `qlike` with `u = 2·target − 2·predicted`, `loss = exp(u) − u − 1`, verified numerically identical to `supervisor.qlike`. `U_CLAMP = 10` guards `exp`; checked that it **never binds** (max |u| = 6.478 over 499,200 values).
- The candidates live in `tsm/models/`, **not in `tsm/skills/`**, which is the committee's folder.

**Experiment runner** (`tsm/experiment.py`): reads the committee's `raw_pred_*` columns back from `artifacts/predictions.csv` (renamed to `pred_*`), walks **only the candidates** forward, joins on (date, ticker) with `validate="one_to_one"`, calibrates everything through the same `backtest.calibrate`, and scores through `report.scored_rows` from 2020 against the calibrated HAR-RV. Its seeded committee rows reproduce `backtest.md` to 4 decimals. It writes only `docs/experiments.md` (appends rows) and `algo/experiments/<name>.csv` (git-ignored). It never writes `artifacts/` or `docs/backtest.md`, and never touches `build_skills`. This was verified by md5 after every run.

**Result:** `itransformer_mae` 0.5244 (+4.0%, factor 1.319); `itransformer_qlike` **0.5856 (−7.3%, factor 1.070)**. QLIKE training pushed the predictions up (nearly pre-calibrated), but calibration already provides that level correction for free. Once scale is equalized, only shape is left to compare, and the QLIKE-trained model is worse at shape. **QLIKE training and the calibration factor are substitutes, not complements, and calibration is the cheaper one.** Our model also lost to neuralforecast (0.5097) at that point.

### Step 3b: speed, CLI, seeds, path head (`c3aa776`)
- The training-window build was vectorized with `sliding_window_view`. **Gate:** seed 0 must reproduce 0.5244 exactly. It passed (0.5244379975), and the 2905×52×44 tensor is bit-identical. The speedup is only 9% (451 → 410 s) because that loop was never the bottleneck. Profile: 18 refits × 300 steps ≈ 65%, the 2203 `predict` calls ≈ 35% (pandas overhead).
- CLI: `python -m tsm.experiment [names...] [--seeds 0 1 2]`. Each seed gets its own row, plus a bold summary row with the mean and the min–max spread. Per-run predictions go to `algo/experiments/`.
- **`path=True`**: head `Linear(64→5)` predicts days 1..5 of the daily log-vol series, MAE averaged over the 5 steps, and step 5 is the forecast (like neuralforecast). The 4 extra steps act as auxiliary supervision.

**Result (3 seeds):** `itransformer_mae` mean 0.5237 (spread 0.0027); `itransformer_mae_path` mean **0.5065** (+7.2%, spread 0.0073). The distributions do not overlap. It matches `multivariate` (0.5097) rather than beating it. The path head is less seed-stable.

### Step 4: 4 input channels per stock (`d572059`)
- Speed with no behaviour change: `predict` builds its inputs in numpy (`log_vol_tail` / `feature_tail`) instead of 52 pandas rolling calls, 35× faster per call. **Gate:** `itransformer_mae_path` seed 0 = 0.5026151187, identical to 10 decimals (even though the numpy window sum differs from pandas by up to 6.5e-14 through reassociation). Walk-forward 439 → 323 s. `fit` still uses the pandas `log_vol_series` (18 calls per run, ~1 s total).
- **`features=True`**: 4 channels over the same 44 days: log 5-day vol, signed log return, `log(high/low)` floored at `EPS_RANGE = 1e-6`, and `log1p(volume)`. Each is standardized separately per stock and window, then flattened into `Linear(176→64)`, so there is **still one token per stock**. The output is un-standardized with channel 0 (vol). Registered as `itransformer_path_feats` (path + MAE + features). Every channel for day t uses only data up to t, and the leakage tests confirm it.
- **Defect found and fixed:** the new candidate had no `DESCRIPTIONS` entry, and `.get(name, "")` silently wrote 3 rows with a blank description. Fix: direct `DESCRIPTIONS[name]` lookup, plus `check_descriptions()` in `main()` before the panel loads, with names validated first (so a typo is not reported as a missing description). New `tests/test_experiment.py` (6 tests). **The 3 blank cells in `experiments.md` were patched by script rather than re-run**; this is stated in the commit message. Yuval was offered a 20-minute re-run so the rows are truly generated and did not ask for it.

**Result (3 seeds):** mean **0.4948** (+9.4%, spread 0.4924–0.4974). The distributions do not overlap with `mae_path`. This is the first candidate to beat the supervisor (0.4961). The gap to `weak_signals` (0.0063) is close to the seed spread (0.0050), so the order between those two is **not settled**. The mean factor barely moved (1.288 → 1.280), so the gain is in shape, not level.

---

### Step 8: the market map (`92e72c3`)
`tsm/models/graph.py`: `correlation_adjacency` (market-adjusted residual correlations over 120 days, top k=5 positive neighbours, symmetric support, self-loops, rows sum to 1; SPY isolated), its vectorised `correlation_adjacency_series` (identical to the single-date function), and `sector_adjacency` from `config.SECTORS`. Leakage-tested. `python -m tsm.market_map` checks it on the frozen cache: same-sector share of links 33% vs 8% at random; heatmap in `docs/graph_assets/`. JPM's links (BAC, BRK-B, then oil majors) were accepted: V and MA are payment networks. Settings fixed by Yuval: window 120, k 5, market_adjusted True; do not tune k to pass a check. `tsm.experiment` also refuses a cache whose last date differs from `meta.json` (checked per ticker).

### Step 9: the map inside the iTransformer (`a4e2654`), a negative result
Six candidates `itransformer_graph_{gnn,bias}_{corr,sector,shuffled}` on top of path_feats: `gnn` adds `g * A @ Linear(h)` after the embedding, `bias` adds `lambda_h * S` to attention logits; gates start at 0 and train at lr 0.02. The experiment table gained "QLIKE 2019" (validation year; choices are made on it) and "Gate" columns. **Bug found:** PyTorch's fast inference kernel mishandles additive attention masks; the bias layers switch it off (test: train vs predict paths must match). Results (3 seeds): path_feats 0.4948 test / 0.4964 2019; gnn_corr 0.4950 / 0.4961 (g ≈ 0.02); bias_corr 0.4949 / 0.4971 (|lambda| ≈ 0.5); gnn_sector 0.4950 / 0.4961; **gnn_shuffled (wrong links) 0.4947 / 0.4961**. The map adds nothing; weak_signals (0.4885 / 0.4586) is still best.

### Step 10: ensembles and two more channels (`979df92`)
`python -m tsm.ensemble` combines saved predictions with no training (components calibrated, mixed, calibrated again). It reads `algo/experiments/itransformer_path_feats_seed{0,1,2}.csv`, so those git-ignored files matter: regenerate them one after another if they are ever lost. Results (test / 2019): weak_signals 0.4885 / 0.4586; pair_equal 0.4809 / 0.4583; **pair_2019 (w = 0.2) 0.4864 / 0.4531, the 2019 winner** (its 2019 score is optimistic, w was chosen on 2019); committee_v2 0.4990 / 0.4546. Calibrating twice costs about 0.01 on test (weak_signals twice: 0.4984). `itransformer_path_feats6` (path_feats + overnight gap + log VIX) is worse: 0.4993 / 0.5080, seed spread 0.0178. ^VIX is frozen in the cache (`python -m tsm.experiment --freeze-vix`) and reaches frames as a `vix` column. `--jobs` (parallel runs) was tried and removed: splitting torch threads changed seed 0 from 0.4924 to 0.4925, so **experiments always run one after another**.

### Step 11: `itransformer` replaces `multivariate` in the committee (`a7713b1`)
Added with the `add-temporal-skill` procedure, then `backtest-report`, run as `python -m tsm.backtest --cache-only` (frozen prices, comparable with experiments.md; 2190 s). short_term, regime and weak_signals gave bit-identical raw predictions to the old artifacts. Test / 2019: itransformer 0.4888 / 0.4888 (multivariate was 0.5097 / 0.5162); equal-weight 0.4869 / 0.4670; supervisor 0.4862 / 0.4662 (its 2019 number is in-sample for its tuning); weak_signals 0.4885 / 0.4586. `multivariate` stays in `tsm/skills/` outside the registry, with its leakage tests.

### Step 12 part 1: earnings dates (data only)
`tsm/earnings.py` collects quarterly earnings dates. **Yahoo (yfinance `get_earnings_dates`) is the source**: one date in each of the 47 quarters of 2015Q1-2026Q3 for all 51 companies, the time of day (before the open / after the close, verified: the predicted reaction day moves 0.0368 vs 0.0149 on the other day), and the next scheduled date. **SEC EDGAR (8-K item 2.02) is the check**: 99.6% agreement within one trading day where both have data, but it misses XOM entirely and early TEVA/AVGO/DIS/GOOGL, and adds non-earnings 2.02 filings (TSLA deliveries, ABBV/EOG updates). Saved in the git-ignored `algo/data/earnings/` (`python -m tsm.earnings`, `--refresh` to download again; needs `SEC_USER_AGENT` with a contact email, see `.env.example`). **Assumption: a release date is known at least 5 trading days ahead.**

### Step 12 part 2: earnings layer (`b77157a`), experiment only
`python -m tsm.earnings_layer` adds earnings information on top of the committee's saved raw predictions (no retraining) and rebuilds calibration, equal-weight and the retuned supervisor with the backtest's own steps. Earnings week = a reaction day in p+1..p+5 (7.8% of test forecasts). **Variant A (jump: + 252/5·J to the variance in earnings weeks) wins on 2019**: supervisor 0.4263 test / 0.4087 2019, against 0.4862 / 0.4662 now (+21.9% vs HAR-RV instead of +10.9%); in earnings weeks QLIKE drops from 1.18 to 0.54. Variant B (split calibration) 0.4320 / 0.4113. Placebo with reaction days shifted ±20 trading days: no gain (0.4880 / 0.4865), so the gain comes from the real dates. **Not in the product yet**: putting it there means the API's predictions depend on Yahoo earnings dates (assumed known 5 trading days ahead) and needs its own step (backtest, artifacts, report).

### Step 13: the earnings layer is in the product
`python -m tsm.backtest` applies the jump (variant A) by default, through `tsm/earnings_jump.py`, which `tsm.earnings_layer` also uses. `raw_pred_<skill>` stays each model's own prediction and the HAR-RV baseline stays plain (both bit-identical to before), so every "vs HAR-RV" and every experiments.md row stays comparable. New per-row columns: `earnings_week`, `reaction_date`, `earnings_J`. `--no-earnings` reproduces the old path. Result (frozen cache): supervisor **0.4263** (+21.9% vs HAR-RV, t-statistic 9.34), equal-weight 0.4300, itransformer 0.4275, weak_signals 0.4338. The backtest needs the saved earnings dates (`algo/data/earnings/yahoo.csv`, git-ignored): on a fresh clone run `python -m tsm.earnings` first, or pass `--no-earnings`. Refresh the dates before a live run, or recent releases will be missing (the log names tickers with no scheduled release; on 2026-10-07: HD, LOW).

## 7. Scoreboard (one table)

QLIKE from 2020-01-02 to 2026-09-30, 52 tickers, 88,140 predictions on 1,695 dates, all models calibrated, lower is better.

| Model | QLIKE | vs HAR-RV | In the committee? |
| --- | ---: | ---: | --- |
| **Supervisor** (Step 11: window 120, temperature 1.0) | **0.4862** | +10.9% | this is the output |
| Equal-weight average (Step 11 committee) | 0.4869 | +10.8% | baseline |
| `weak_signals` | 0.4885 | +10.5% | yes |
| `itransformer` (Step 11, mean of 3 seeds) | 0.4888 | +10.5% | yes, since Step 11 |
| `itransformer_path_feats` (mean of 3 seeds) | 0.4948 | +9.4% | **no, candidate** |
| Supervisor before Step 11 (window 120, temperature 0.25) | 0.4961 | +9.1% | superseded |
| Equal-weight before Step 11 | 0.4962 | +9.1% | superseded |
| `itransformer_mae_path` (mean of 3) | 0.5065 | +7.2% | no |
| `multivariate` (neuralforecast) | 0.5097 | +6.7% | no, replaced in Step 11 |
| `itransformer_mae` (mean of 3) | 0.5237 | +4.1% | no |
| `regime` (GARCH) | 0.5342 | +2.2% | yes |
| HAR-RV = `short_term` | 0.5460 | — | yes (and the baseline) |
| `itransformer_qlike` | 0.5856 | −7.3% | no |
| Naive (last 5-day vol) | 1.2482 | −128.6% | baseline |
| Graph candidates (Step 9, 6 runs × 3 seeds) | 0.4947–0.4950 | +9.3% to +9.4% | no: equal to path_feats within seed spread |
| `pair_equal` (Step 10, mean of 3) | 0.4809 | +11.9% | no (combination; not the 2019 winner) |
| `pair_2019` (Step 10, w = 0.2, mean of 3) | 0.4864 | +10.9% | no (combination; 2019 winner) |
| `itransformer_path_feats6` (mean of 3) | 0.4993 | +8.5% | no |

Supervisor RMSE 0.1730 / MAE 0.1165; equal-weight is slightly better on RMSE (0.1727).

---

## 8. The lessons (why things are the way they are)

1. **Calibrate before comparing.** Without calibration you measure scale, not skill. Every comparison here is between calibrated models.
2. **Calibration ate the supervisor's edge.** Before calibration, part of the supervisor's gain came from down-weighting badly scaled skills; calibration now does that more cheaply. Hence the tie with equal-weight.
3. **QLIKE as a training loss is not worth it** when there is calibration (they are substitutes).
4. **The path head works** as auxiliary supervision (+3 points), at the cost of more seed variance.
5. **More inputs per stock work** (+2.2 points), and the gain is in shape.
6. **Speed:** the 18 refits × 300 gradient steps now dominate the cost of a candidate. `predict` is no longer a bottleneck.
7. **Three seeds, non-overlapping distributions:** that is the bar we use to declare a winner. A gap smaller than the spread is "not settled".

---

## 9. The other team members

**Elie** built the original engine (`0cc9ded`: data, target, 4 skills, supervisor, backtest, report, API, tests) and merged PR #2. **Elie has left the project (noted 2026-10-12)** and is not working locally; `algo-elie` is inactive. Yuval now owns all of `/algo` (the iTransformer, the ST-GNN market map and the API), so `backtest.py`, `supervisor.py` and `report.py` can be changed without coordinating with anyone.

**Maor** (web), branch `web-initial-site` (read with `git show origin/web-initial-site:<path>`, do not check out over our branch):
- `web/CLAUDE.md` has a section "What the real engine returns (from the algo team's summary, 2026-10-08)": the site knows the names `short_term`, `regime`, `weak_signals`, `multivariate`, with labels and a stable color per skill, and **falls back for an unknown name**. So adding or renaming a skill does not break the UI. `/history` holds ~2,200 points per ticker. **503 = "predictions are not ready yet"**. `supervisor_confidence` is shown as "recent accuracy", never as a probability. Volatility levels (calm < 11%, typical ~24%, stormy > 52%, crisis > 100%) "come from the engine team's data".
- **Contract proposal, not agreed:** `docs/proposed-contract-additions.md` on `web-initial-site`. It includes a message in Hebrew addressed to Elie and Yuval. It proposes:
  1. `GET /prices?ticker=` (last close + ~90 days of closes). The API currently reads only artifacts; this needs price data in the API.
  2. `GET /weights?ticker=` (weights over time). Easy: the `w_*` columns are already in `predictions.csv`.
  3. `GET /performance` (the backtest summary). Easy from the same data as the report.
  4a. An optional `sector` field on `/tickers` items (a schema change: `additionalProperties: false`).
  4b. `GET /overview` (the whole list in one call, instead of 2 calls per ticker).
  4c. `GET /history?ticker=&days=N` (optional).
  - Scaling to the S&P 500 (503 tickers). Not practical for the engine before the freeze: the backtest takes ~39 min at 52 tickers.
  - Symbol formats: the S&P list writes `BRK.B` while Yahoo and our `config.py` use `BRK-B`; the contract's pattern accepts both.
- **Rule:** a contract change needs agreement from both teams and one PR that updates the schema, the mocks and both sides. Do not edit `/contracts` without that agreement. Do not touch `/web`.

---

**Contract v2 candidate (not agreed, not implemented):** a per-prediction field "earnings in the next 5 trading days" (the reaction date, or null), so the site can show why a forecast jumped. The engine already has it per row (`earnings_week`, `reaction_date` in `predictions.csv`); the API keeps the current contract shape until both teams agree on v2.

## 10. Gotchas

- **The price cache refreshes every day, except for experiments.** `load_prices` downloads again whenever the cache file was not written *today* (New York time), which adds trading days and can shift adjusted closes (dividends). So a full `tsm.backtest` on a new day changes every number in the report slightly. Since Step 7, `tsm.experiment` calls `load_panel(cache_only=True)`: it reads `algo/data/` as it is (the 2026-10-08 cache the artifacts were built from), never downloads, and stops with `FileNotFoundError` if a ticker's file is missing. One remaining hole: `python -m tsm.data` (or a backtest) overwrites the cache, after which the cache and the artifacts only match if the backtest was re-run on the same day.
- **Experiments are scored against the committed artifacts.** After a new `python -m tsm.backtest`, the existing rows in `experiments.md` refer to the old run.
- **`itransformer_qlike_path`** is registered in `CANDIDATES` and `DESCRIPTIONS` but **has never been run and is not in the leakage tests** (the `CANDIDATES` dict in `tests/skills/test_skills.py` and `fast_skills()` in `tests/test_backtest.py`). Add it there before running it.
- **Adding a candidate** = an entry in `CANDIDATES` (`itransformer.py`) + `DESCRIPTIONS` (`experiment.py`) + both leakage tests. `test_experiment.py` fails if the description is missing.
- **Promoting to the committee** = the `add-temporal-skill` skill (a module in `tsm/skills/`, `build_skills`, the `SKILLS` dict in the tests, then `backtest-report`). `test_registry_matches_the_tested_skills` pins the committee to exactly what is registered.
- `docs/backtest.md` and `docs/experiments.md` are **generated**. Never edit them by hand (the one exception so far is the description patch described in step 4).
- `algo/experiments/` contains leftovers (`itransformer_mae.csv`, `gate_mae_path.csv`) from gate runs. They are harmless and ignored.
- **Stale documentation:** the root `CLAUDE.md` says the site is a placeholder and does not mention calibration, `tsm/experiment.py`, `tsm/models/` or `docs/experiments.md`. `algo/README.md` says "Scaffold only". `CLAUDE.md` is shared by the team, so ask before editing it.
- `report.py` is imported inside `backtest.main()`. Without `test_report.py`, an error in it only shows up after ~39 minutes.
- Training targets come only from `tsm.target.forward_realized_vol` on the truncated panel, and prices only from `tsm.data.load_prices`. Never recompute them elsewhere.

---

## 11. Open decisions (for the user to decide, not for Claude to do on its own)

1. **Open a PR `algo-yuval` → `algo`** (4 commits), then `algo` → `main` before the freeze. Without it, integration runs on 10 tickers.
2. **Integration checkpoint with Maor** (today, according to the plan): run `uvicorn`, check that the site is live, write down the gaps.
3. ~~Promote `itransformer_path_feats`?~~ Done in Step 11, as a 3-seed mean replacing `multivariate`.
4. **Respond to Maor's proposal.** `/weights`, `/performance` and `/overview` are cheap from the existing artifacts; `/prices` and `sector` need more. Requires the agreement of both teams.
5. **The supervisor's weakness** (tied with equal-weight). Untested ideas, for discussion only: shrinking the weights toward equal-weight, a window or loss pooled across tickers instead of per ticker, or adding equal-weight as one of the options. Any change must be tuned only on pre-2020 dates.
6. **Re-run the backtest before the demo** so `as_of_date` is recent (currently 2026-10-07). It changes the numbers slightly and takes ~40 min.
7. The graph-aware iTransformer was built and tested in Step 9: no gain, even the shuffled control matches. What to try next is open.

---

## 12. How Yuval works with Claude

- The team does not write code (`CLAUDE.md`): explain decisions in plain language, and never ask them to edit code by hand.
- Tasks arrive as numbered **"Step N"** prompts (usually in English) with explicit constraints. Carry out every item, and **state any deviation explicitly** (e.g. the `CHART_TICKERS` fallback was flagged rather than done silently).
- **Explicit git instructions every time:** "Do not commit" / "Commit with the message X" / "Do not push" / "Do not merge into algo or main". Do not commit, push or merge without an explicit instruction. Use the given message verbatim as the subject; adding a body with rationale, results and verification was accepted.
- **Stop conditions are absolute:** "if X, STOP and show me", or "the gate must reproduce exactly, otherwise stop". Do not proceed past one.
- **Experiment protocol:** the committee stays unchanged, the leakage tests are only extended (never weakened), every new variant goes into both leakage tests, seeds 0/1/2 with mean and spread, and md5 checks that `artifacts/` and `backtest.md` did not change.
- Wants honest reports, bad news included (e.g. "QLIKE loss did not help" went into the commit subject). At the end of a task: the results table, the runtime, and what is uncommitted. Offering optional follow-ups ("say the word and I'll…") works well.
- During long runs Yuval asks for status: show the tail of the log, do not stop the job, start nothing new.
- Test status after Step 12 (2026-10-13): **200 passed** in 227 s (`algo/.venv/Scripts/python.exe -m pytest -q`).

---

## 13. Command cheat sheet (Windows, from `algo/`)

```bash
.venv/Scripts/python.exe -m pytest -q                                   # all tests (~4.5 min)
.venv/Scripts/python.exe -m pytest tests/test_backtest.py tests/skills  # leakage tests
.venv/Scripts/python.exe -m tsm.backtest                                # full pipeline, ~39 min, rewrites artifacts + backtest.md
.venv/Scripts/python.exe -m tsm.experiment itransformer_path_feats --seeds 0 1 2   # ~20 min, appends to experiments.md
.venv/Scripts/python.exe -m uvicorn tsm.api:app --reload --port 8000    # API from the artifacts
git show origin/web-initial-site:docs/proposed-contract-additions.md    # Maor's proposal
git show origin/web-initial-site:web/CLAUDE.md                          # what the site expects from the engine
```
