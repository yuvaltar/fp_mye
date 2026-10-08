# Proposed contract additions (from /web)

Status: **proposal, not agreed**. Nothing here is in `contracts/prediction.schema.json` yet. The website is already built against these shapes (types in `web/lib/api/proposed-types.ts`) and shows clearly labelled "Sample data" in mock mode. In live mode, if an endpoint answers anything other than 200, the matching section shows a "not available yet" note and the rest of the site works normally.

If both teams agree, the change goes in one PR that updates the schema, adds the mock files and implements the endpoints (per the root `CLAUDE.md`). Unknown ticker returns 404 `{ "detail": "..." }`, like the existing endpoints.

## 1. `GET /prices?ticker=XXX` (price and price chart)

```json
{
  "ticker": "AAPL",
  "currency": "USD",
  "last_close": 227.52,
  "last_close_date": "2026-10-07",
  "points": [{ "date": "2026-07-15", "close": 224.10 }]
}
```

- `points` oldest first, daily closes (about the last 90 trading days is enough), same data the yfinance loader already fetches.
- Prices are plain numbers in the listing currency, not decimals-as-percent.

## 2. `GET /weights?ticker=XXX` (supervisor weights over time)

```json
{
  "ticker": "AAPL",
  "skills": [{ "name": "short_trend", "horizon": "short" }],
  "points": [
    {
      "as_of_date": "2026-09-17",
      "weights": [{ "name": "short_trend", "weight": 0.34 }]
    }
  ]
}
```

- One entry per `as_of_date` that appears in `/history`, oldest first.
- On every date the weights sum to 1 (same rule as `/predict`), and the last point equals the weights in `/predict`.
- A separate endpoint, because `HistoryPoint` has `additionalProperties: false` and adding fields there would break existing validation.

## 3. `GET /performance` (backtest summary)

```json
{
  "generated_at": "2026-10-08",
  "period_start": "2025-10-08",
  "period_end": "2026-10-07",
  "evaluation_dates": 250,
  "tickers": ["AAPL", "TEVA", "NVDA"],
  "models": [
    { "name": "supervisor", "kind": "supervisor", "rmse": 0.0412, "mae": 0.0301, "qlike": 0.118 }
  ],
  "skill_weights": [{ "name": "short_trend", "mean": 0.34, "min": 0.12, "max": 0.55 }]
}
```

- `models`: the supervisor, every skill, and the baselines `har_rv`, `naive`, `equal_weight`. `kind` is `supervisor`, `skill` or `baseline`. All models scored on the same dates.
- Same numbers as the generated `docs/backtest.md`. Errors are on volatility as decimals (like the rest of the contract); the site shows them with 4 decimals.

## 4. Scaling to the S&P 500 (about 500 tickers)

The watchlist now lists the full S&P 500 (503 tickers, 11 sectors; a snapshot of the public dataset `datasets/s-and-p-500-companies`, bundled in `web/lib/api/sp500.ts` for mock mode). In live mode the list comes from `GET /tickers`. Two additions make that practical:

**4a. `GET /tickers` items get an optional `sector`** (GICS sector, e.g. `"Information Technology"`). This is a schema change (`additionalProperties: false` on the item today). The site shows a sector filter only when sectors are present.

**4b. `GET /overview`** so the watchlist does not need 2 requests per ticker (about 1000 for the S&P 500):

```json
{
  "entries": [
    {
      "ticker": "AAPL",
      "as_of_date": "2026-10-07",
      "predicted_vol": 0.2251,
      "baseline_vol": 0.212,
      "supervisor_confidence": 0.74,
      "latest_realized_vol": 0.2106
    }
  ]
}
```

- One entry per ticker that has a prediction; tickers without one are simply absent (the site lists them as "No prediction yet").
- `latest_realized_vol` is the latest non-null `realized_vol` from that ticker's `/history` (or `null`); the trend badge compares the prediction with it.
- Without `/overview` the site loads only the first 30 tickers individually and lists the rest without numbers.

For the engine side (not a contract matter, but it affects everyone):

- **Data coverage:** real predictions for 500 tickers need the loader and backtest to cover them; plan for download time and yfinance rate limits (cache locally, fetch in batches).
- **Ticker symbols:** the S&P list writes `BRK.B` and `BF.B`; Yahoo Finance uses `BRK-B` and `BF-B`. The contract's `Ticker` pattern accepts both; the team should pick one and map the other.
- **TEVA is not in the S&P 500** (it is the project's Israeli example). It stays in the mock files, so mock mode lists the S&P 500 plus TEVA.

## Message to send to Elie and Yuval

> היי, האתר כבר בנוי על ה-mocks ומציג את כל 500 החברות של S&P 500 (שמות וסקטורים). כדי שיהיו גם חיזויים אמיתיים, אנחנו מציעים להוסיף ל-contract: `GET /overview` (נתוני הרשימה לכל המניות בקריאה אחת, במקום 1000 קריאות), שדה אופציונלי `sector` ב-`/tickers`, ועוד שלושה endpoints אופציונליים: מחיר וגרף מחיר, משקלי ה-skills לאורך זמן, ותוצאות ה-backtest. הפירוט המלא והצורות המדויקות ב-`docs/proposed-contract-additions.md`. האתר ממשיך לעבוד גם בלי זה, אז אין לחץ. שימו לב שהמנוע צריך להתמודד עם 500 טיקרים (הורדת נתונים בקבוצות ו-cache), ושב-Yahoo הסימול הוא `BRK-B` ולא `BRK.B`. אם מסכימים, נעשה PR אחד שמעדכן סכמה, mocks ומימוש בשני הצדדים.
