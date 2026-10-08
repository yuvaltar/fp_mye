# contracts

The API contract between `/algo` (serves it) and `/web` (consumes it). **Nothing here changes without the agreement of both teams.**

| Endpoint | 200 response | Mock file |
| --- | --- | --- |
| `GET /predict?ticker=XXX` | `Prediction` (the root of the schema) | `mock_prediction.json` (array of 3: AAPL, TEVA, NVDA) |
| `GET /tickers` | `TickersResponse` | `mock_tickers.json` |
| `GET /history?ticker=XXX` | `HistoryResponse` | `mock_history.json` (array of 3, one per ticker) |

An unknown ticker returns HTTP 404 with `{ "detail": "..." }`.

All shapes are defined in `prediction.schema.json` (JSON Schema 2020-12). The mock files hold several example responses each, so each array element is one response body.

## Agreed decisions

Accepted by both teams on 2026-10-08. Changing any of them is a contract change.

1. **Volatility units.** Every volatility field (`predicted_vol`, `baseline_vol`, `realized_vol`, at top level and per skill) is an annualized 5-trading-day realized volatility written as a decimal: `0.24` means 24%. Formula: `sqrt(252/5 * sum of the 5 squared daily log returns)`. The website multiplies by 100 for display; the API never sends percentages.
2. **Skill horizon.** `skills[].horizon` is one of `short` (about 1-5 trading days of history), `medium` (about 5-22) or `long` (more than 22). Enforced by the schema.
3. **Weights sum to 1.** The `weight` values of the skills in one prediction are each between 0 and 1 and sum to 1. The schema enforces the range; the sum is checked by `algo/tests/test_contract.py`.
4. **Unknown ticker.** `GET /predict` and `GET /history` return HTTP 404 with `{ "detail": "..." }` for a ticker that is not in `GET /tickers`.

One more rule the schema cannot express: `realized_vol` in `/history` is `null` until the 5 trading days after `as_of_date` have all passed.

## Re-validating the mocks

```bash
cd algo && pytest tests/test_contract.py
```
