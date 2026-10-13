# contracts

The API contract between `/algo` (serves it) and `/web` (consumes it). **Nothing here changes without the agreement of both teams.**

| Endpoint | 200 response | Mock file |
| --- | --- | --- |
| `GET /predict?ticker=XXX` | `Prediction` (the root of the schema) | `mock_prediction.json` (array of 3: AAPL, TEVA, NVDA) |
| `GET /tickers` | `TickersResponse` | `mock_tickers.json` |
| `GET /history?ticker=XXX` | `HistoryResponse` | `mock_history.json` (array of 3, one per ticker) |
| `GET /overview` | `OverviewResponse` | `mock_overview.json` |
| `GET /weights?ticker=XXX` | `WeightsHistoryResponse` | `mock_weights.json` (array of 3, one per ticker) |
| `GET /performance` | `PerformanceResponse` | `mock_performance.json` |

An unknown ticker returns HTTP 404 with `{ "detail": "..." }`.

All shapes are defined in `prediction.schema.json` (JSON Schema 2020-12). The mock files hold several example responses each, so each array element is one response body.

## Agreed decisions

Accepted by both teams on 2026-10-08. Changing any of them is a contract change.

1. **Volatility units.** Every volatility field (`predicted_vol`, `baseline_vol`, `realized_vol`, at top level and per skill) is an annualized 5-trading-day realized volatility written as a decimal: `0.24` means 24%. Formula: `sqrt(252/5 * sum of the 5 squared daily log returns)`. The website multiplies by 100 for display; the API never sends percentages.
2. **Skill horizon.** `skills[].horizon` is one of `short` (about 1-5 trading days of history), `medium` (about 5-22) or `long` (more than 22). Enforced by the schema.
3. **Weights sum to 1.** The `weight` values of the skills in one prediction are each between 0 and 1 and sum to 1. The schema enforces the range; the sum is checked by `algo/tests/test_contract.py`.
4. **Unknown ticker.** `GET /predict` and `GET /history` return HTTP 404 with `{ "detail": "..." }` for a ticker that is not in `GET /tickers`.

## Version 2 additions

Agreed by both teams (see `docs/proposed-contract-additions.md`). Everything below is additive: a v1 server still works with the website, which hides the sections it cannot fill.

5. **`GET /overview`.** One entry per ticker that has a prediction (a ticker without one is absent), with the few numbers the watchlist needs: `predicted_vol`, `baseline_vol`, `supervisor_confidence`, `latest_realized_vol` (the latest non-null `realized_vol` of that ticker's `/history`, or `null`) and `earnings_date`. It replaces two requests per ticker.
6. **`GET /weights?ticker=XXX`.** The supervisor's weights per skill over time, on the same dates as `/history` (oldest first). On every date the weights sum to 1, and the last point equals the weights in `/predict`. Unknown ticker: 404, like `/predict`.
7. **`GET /performance`.** The walk-forward backtest summary, the same numbers as `docs/backtest.md`. QLIKE is the headline (`headline`: supervisor vs HAR-RV, tickers better, t-statistic); `models` lists the supervisor, the HAR-RV baseline `har_rv` (kind `baseline`), every skill (kind `skill`) and the baselines `naive` and `equal_weight`. With the engine's earnings layer on (since 2026-10-13), the skill `short_term` carries the earnings jump while `har_rv` is plain HAR-RV, so both rows appear; without the layer `short_term` is the baseline itself and only `har_rv` appears. The `*_vs_har_rv` fields are decimals (0.109 means 10.9% lower error) and `null` on the baseline's own row. These are error metrics on volatility decimals, not percentages.
8. **`sector` on `/tickers` items.** Optional GICS sector. The site shows a sector filter only when sectors are present.
9. **`earnings_date` on `/predict` and on `/overview` entries.** Optional. The date (`YYYY-MM-DD`) of the company's quarterly earnings report when it falls in the 5 trading days the prediction covers, otherwise `null`; absent means the engine does not report it. The engine raises the prediction in such a week, and the site uses the date to say why.
10. **No `/prices`.** Prices and the price chart come from the website's own market data source (Yahoo Finance), not from the engine.

One more rule the schema cannot express: `realized_vol` in `/history` is `null` until the 5 trading days after `as_of_date` have all passed.

## Re-validating the mocks

```bash
cd algo && pytest tests/test_contract.py
```
