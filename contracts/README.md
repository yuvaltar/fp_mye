# contracts

The API contract between `/algo` (serves it) and `/web` (consumes it). **Nothing here changes without the agreement of both teams.**

| Endpoint | 200 response | Mock file |
| --- | --- | --- |
| `GET /predict?ticker=XXX` | `Prediction` (the root of the schema) | `mock_prediction.json` (array of 3: AAPL, TEVA, NVDA) |
| `GET /tickers` | `TickersResponse` | `mock_tickers.json` |
| `GET /history?ticker=XXX` | `HistoryResponse` | `mock_history.json` (array of 3, one per ticker) |

An unknown ticker returns HTTP 404 with `{ "detail": "..." }`.

All shapes are defined in `prediction.schema.json` (JSON Schema 2020-12). The mock files hold several example responses each, so each array element is one response body.

## Rules the schema cannot express

- Every volatility is an annualized 5-trading-day realized volatility as a decimal (`0.24` = 24%): `sqrt(252/5 * sum of the 5 squared daily log returns)`.
- The `weight` values of the skills in one prediction sum to 1.
- `realized_vol` in `/history` is `null` until the 5 trading days after `as_of_date` have all passed.

## Re-validating the mocks

```bash
cd algo && pytest tests/test_contract.py
```
