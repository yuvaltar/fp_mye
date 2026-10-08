---
name: backtest-report
description: Run the walk-forward backtest of the Temporal Skills Market engine and regenerate docs/backtest.md with metrics versus baselines, average weight per skill, and charts. Use when the user asks for a backtest, for results or performance numbers, or after a skill is added or changed.
---

# Backtest report

Produces `docs/backtest.md`, the one place the team reads results from. The file is generated: never edit it by hand, and never write a number into it that did not come out of the run.

## 1. Run the backtest

```bash
cd algo && source .venv/bin/activate
python -m tsm.backtest
```

The entry point is `algo/tsm/backtest.py`. If it does not exist yet, build it first to the specification below and tell the user you did.

Specification:

- **Walk-forward only.** For each evaluation date, fit on data up to that date, predict the next 5 trading days, then compare with the volatility realized afterwards. No date may be predicted with data from its future, and the supervisor's weights for a date may only use errors that were already observable on that date.
- **Target:** annualized 5-trading-day realized volatility as defined in `contracts/README.md`.
- **Universe and period:** the tickers served by `GET /tickers`; state the exact tickers and date range in the report.
- **Outputs**, written to `docs/backtest_assets/`: `results.csv` (one row per ticker, date and model with prediction and realized value), `weights.csv` (supervisor weight per skill per date) and the PNG charts below.

## 2. Compute the metrics

For every model — the supervisor's combined prediction, each skill alone, and the baselines — compute over the same dates:

- **RMSE** and **MAE** on volatility;
- **QLIKE**, the standard loss for volatility forecasts;
- **improvement vs HAR-RV** in percent, for each metric.

Baselines: **HAR-RV** (the reference, same as `baseline_vol` in the contract), a **naive** forecast (last observed 5-day realized vol), and an **equal-weight** average of the skills. The equal-weight row is what shows whether the supervisor's dynamic weighting adds anything.

## 3. Write docs/backtest.md

Sections, in this order:

1. **Summary** — two or three plain-language sentences: does the market beat HAR-RV, by how much, and how sure we can be.
2. **Setup** — tickers, date range, number of evaluation dates, `model_version`, date the report was generated.
3. **Metrics vs baselines** — one table, one row per model (supervisor, each skill, HAR-RV, naive, equal-weight), columns RMSE, MAE, QLIKE and improvement vs HAR-RV. Best value per column in bold.
4. **Average weight per skill** — table with mean, min and max weight per skill over the period, plus one row per ticker if weights differ noticeably across tickers.
5. **Charts** — embedded from `docs/backtest_assets/`:
   - predicted vs realized volatility over time, per ticker, with the HAR-RV line;
   - supervisor weights over time (stacked area, one band per skill);
   - error per model (bar chart of RMSE or QLIKE).
6. **Caveats** — anything that weakens the result: short period, few tickers, a skill that failed on some dates, missing data.

Charts need a plotting library. matplotlib is not on the allowed dependency list in `CLAUDE.md`, so ask the user before installing it (or any alternative).

## 4. Check before finishing

- Every skill registered with the supervisor has a row in both tables; a missing row means the report is stale or the skill is not registered.
- All models were scored on exactly the same dates.
- Weights sum to 1 on every date.
- The numbers in the summary match the table.

Then report the headline result to the user honestly. If the market does not beat HAR-RV, say so plainly; a result that looks too good (large improvement on little data) is more likely a look-ahead bug than a discovery, so check for one before presenting it.
