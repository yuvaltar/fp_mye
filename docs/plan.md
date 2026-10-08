# 7-day plan

Day 1 is Thursday 2026-10-08, the day the repository was set up; day 7 is Wednesday 2026-10-14. Shift the dates if the team starts later.

**Algo** = Elie + Yuval, in `/algo`, branch `algo`. **Web** = Maor, in `/web`, branch `web`.

Until day 5 the two teams are independent: the website runs on the mock files in `/contracts`, the engine is tested against the same schema. The contract is what makes that safe, so it only changes if both teams agree.

| Day | Algo (Elie + Yuval) | Web (Maor) | Done when |
| --- | --- | --- | --- |
| **1** — Thu 8 Oct | Repo foundations (this PR). Install Python 3.11 and the dependencies. Data loader: daily prices from yfinance for the ticker list, cached locally. Realized-volatility target computed as defined in the contract. | Repo foundations. Typed API client mirroring the contract, with a mock mode reading `/contracts`. Page skeleton and navigation. | Both teams have read and accepted the contract. Loader returns clean data for AAPL, TEVA, NVDA. |
| **2** — Fri 9 Oct | HAR-RV baseline. Walk-forward backtest harness with RMSE, MAE, QLIKE. First `backtest-report` run with baselines only. | Ticker list page from `/tickers`. Stock page showing the prediction next to the baseline, from mocks. | `docs/backtest.md` exists with HAR-RV and naive rows. Both pages render the three mock tickers. |
| **3** — Sat 10 Oct | Shared `Skill` interface. First two skills (short trend, medium trend) via `add-temporal-skill`. | Skill breakdown: weight and prediction per skill (table and chart). Supervisor confidence indicator. | Two skills tested and in the report. Stock page shows every field of the `/predict` response. |
| **4** — Sun 11 Oct | Supervisor: weights from recent performance, summing to 1. Two more skills (weak signals, seasonality). Compare against the equal-weight baseline. | History chart from `/history`: predicted vs baseline vs realized, handling `realized_vol: null`. Loading, error and unknown-ticker states. | Report shows the supervisor vs equal-weight vs HAR-RV. Site is complete on mocks. |
| **5** — Mon 12 Oct | FastAPI server with the three endpoints, every response validated against the schema in tests. CORS for the site. | Switch the client from mocks to the live API. | **Integration checkpoint** (below) passes. |
| **6** — Tue 13 Oct | Fix what integration revealed. Tune the supervisor, extend the ticker list, final backtest report. | Fix what integration revealed. Polish: responsive layout, readable charts, empty states. | No open integration bug. Final `docs/backtest.md` generated. |
| **7** — Wed 14 Oct | Freeze the code by midday. Write-up of method and results from the report. | Freeze the code by midday. Demo walkthrough and screenshots. | Everything merged to `main`; the demo runs from a clean clone. |

## Day 5: integration checkpoint

All three team members together, with both parts running locally (`uvicorn` on port 8000, `npm run dev` on port 3000, `NEXT_PUBLIC_USE_MOCKS=false`). The checkpoint passes when:

1. `GET /tickers`, `GET /predict?ticker=AAPL` and `GET /history?ticker=AAPL` return live data that validates against `contracts/prediction.schema.json`.
2. The website shows the ticker list, a prediction with its skill breakdown, and the history chart for at least AAPL, TEVA and NVDA, using the live API.
3. An unknown ticker returns 404 and the site shows a clear message.
4. `pytest` passes in `/algo`; `npm run build` and `npm run typecheck` pass in `/web`.
5. Any mismatch between the two sides is written down and assigned. If the cause is the contract itself, both teams agree on the change before anyone edits `/contracts`.

If the checkpoint fails, day 6 goes to fixing integration before any tuning or polish.

## What gets cut first if time runs short

In this order: extra tickers beyond the three, the seasonality skill, the weak-signals skill, visual polish. Never cut the HAR-RV comparison, the walk-forward (no look-ahead) rule, or the live integration.
