# fp_mye — Temporal Skills Market

A stock-tracking platform with a multi-agent prediction engine. Each "skill" is an agent specialized in one time horizon or signal type; a supervisor (the "market") weights the skills by their recent accuracy. The engine predicts 5-trading-day realized volatility for 52 stocks.

**Where it stands:** five skills (HAR-RV, GARCH, gradient boosting, our own iTransformer, an ST-GNN), each calibrated, plus an earnings layer, combined by a pooled supervisor. Walk-forward test 2020-2026: QLIKE 0.4141 against 0.5460 for the HAR-RV baseline (+24.2%), better on 52 of 52 stocks; full numbers in [`docs/backtest.md`](docs/backtest.md). The website shows a watchlist, a page per stock, the engine's track record, and an AI assistant (Gemini, also served as an MCP server) that gives risk briefings, never advice.

| Folder | What | Owner |
| --- | --- | --- |
| `algo/` | Python 3.12 engine + FastAPI server | Yuval and Elie |
| `web/` | Next.js 16 + TypeScript + Tailwind site | Maor |
| `contracts/` | API contract (JSON Schema) and mock responses | everyone; one PR changes schema, mocks, engine and site together |
| `docs/` | plan, backtest report, experiment log, ST-GNN results, assistant | everyone |

The site reads the engine's API, or the mock files with `NEXT_PUBLIC_USE_MOCKS=true`.

Setup commands, rules and conventions are in [`CLAUDE.md`](CLAUDE.md); the schedule is in [`docs/plan.md`](docs/plan.md).
