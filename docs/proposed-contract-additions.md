# Contract v2: what was agreed, and who builds what

Status: **agreed in principle** between the two teams (message from Yuval, 2026-10-13). The schema, the mocks and the website side are on the branch `contract-v2-web`; the engine side (the endpoints themselves) is built by Yuval. One PR updates the schema, the mocks and both sides, and both teams approve it before it goes to `main`.

The authoritative definitions are in `contracts/prediction.schema.json` and `contracts/README.md` ("Version 2 additions"). This file is the work split and the checklist.

## What v2 adds (all optional for a v1 server: the site hides what it cannot fill)

| Addition | Shape | Why |
| --- | --- | --- |
| `GET /overview` | `OverviewResponse`: one entry per ticker with a prediction (`predicted_vol`, `baseline_vol`, `supervisor_confidence`, `latest_realized_vol`, `earnings_date`) | The watchlist takes one request instead of two per ticker (about 100 requests and 10 MB for 52 tickers) |
| `GET /weights?ticker=` | `WeightsHistoryResponse`: weights per skill per date, same dates as `/history`, summing to 1; the last point equals `/predict` | The "skill weights over time" chart: how the supervisor shifts trust |
| `GET /performance` | `PerformanceResponse`: QLIKE headline (supervisor vs HAR-RV, tickers better, t-statistic), a table of models (RMSE, MAE, QLIKE, `*_vs_har_rv`), average weights, per-ticker QLIKE | The Performance page, with the numbers of `docs/backtest.md` |
| `sector` on `/tickers` items | optional string (GICS sector) | Sector filter in the watchlist |
| `earnings_date` on `/predict` and `/overview` entries | `YYYY-MM-DD` when the company reports inside the 5 days the prediction covers, else `null`; absent = not reported | The site explains why a prediction jumped in an earnings week |
| ~~`GET /prices`~~ | dropped | The site gets prices from Yahoo Finance itself |

## Engine side (Yuval): what the site expects

1. Implement the three endpoints, `sector`, and `earnings_date`, exactly as in the schema. `/performance` and `/overview` can be computed from `artifacts/predictions.csv` (a throw-away harness did this for the site's tests: the QLIKE, RMSE, MAE, 88,140 scored predictions, 1,695 dates and 52/52 tickers all reproduce `docs/backtest.md` exactly).
2. Names in `/performance.models`: `supervisor`, `har_rv` (the plain HAR-RV baseline, kind `baseline`), the skills by their names (`short_term`, `regime`, `weak_signals`, `itransformer`, kind `skill`), and the baselines `naive` and `equal_weight`. Since the earnings layer (Step 13), `short_term` carries the earnings jump and is no longer the same as `har_rv`, so both rows appear. The `*_vs_har_rv` fields are decimals (0.109 = 10.9%), `null` on `har_rv`.
3. `/performance.headline.t_statistic`: the overlap-corrected one the report prints (9.34 since Step 13; it was 4.75 before), computed by the same function.
4. Add tests for the new definitions to `algo/tests/test_contract.py` and `test_api.py` (the existing 17 contract and API tests pass unchanged against the new schema).
5. The earnings layer is in the product since Step 13: `artifacts/` hold that run (supervisor QLIKE 0.4263, +21.9% vs HAR-RV), and `/performance` returns it.

## Website side (Maor): done on this branch

- Types mirror the new definitions; mocks for every new definition (`mock_overview.json`, `mock_weights.json`, `mock_performance.json`; `sector` and `earnings_date` in the existing ones).
- Watchlist uses `/overview` when present (falls back to per-ticker requests); earnings tag and "Earnings this week" filter; sector filter.
- Stock page: earnings notice, real weights chart (range selector, weekly sampling for "All"), unchanged elsewhere.
- Performance page: QLIKE headline sentence, model table with QLIKE first and `vs HAR-RV` from the API, weights, per-ticker table, caveats.
- `itransformer` has a label, a description and a stable color; the volatility scale says "52 large stocks".

## Not part of the contract

- Prices, the price chart, the market snapshot and the realized volatility computed from real closes come from Yahoo Finance (`NEXT_PUBLIC_LIVE_MARKET_DATA=true`), server-side only.
- Scaling to the S&P 500 (503 tickers) is not practical for the engine before the freeze (the backtest takes about 40 minutes at 52 tickers). In mock mode the site lists all 503 with real names and sectors and shows predictions only where the engine has them.
- Symbols: the S&P list writes `BRK.B`; Yahoo and `config.py` use `BRK-B`. The site maps dots to dashes when it asks Yahoo.

## Order of merging

1. Yuval builds his side on his own branch and tells Maor when it is pushed.
2. Maor merges the two (this branch + Yuval's) so that one branch has the schema, the mocks, the engine and the site, and runs the integration checkpoint: all endpoints validate against the schema, the site shows live data for every ticker, an unknown ticker is a 404 with a clear message, `pytest`, `npm run build` and `npm run typecheck` pass.
3. One PR into `main`, approved by both.
