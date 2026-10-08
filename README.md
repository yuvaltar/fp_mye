# fp_mye — Temporal Skills Market

A stock-tracking platform with a multi-agent prediction engine. Each "skill" is an agent specialized in one time horizon or signal type; a supervisor weights the skills by recent performance. The MVP predicts 5-trading-day realized volatility for a list of stocks.

| Folder | What | Owner |
| --- | --- | --- |
| `algo/` | Python 3.11 engine + FastAPI server | Elie, Yuval |
| `web/` | Next.js 14 + TypeScript + Tailwind site | Maor |
| `contracts/` | API contract (JSON Schema) and mock responses | both teams, by agreement only |
| `docs/` | 7-day plan, backtest report | both |

Setup commands, rules and conventions are in [`CLAUDE.md`](CLAUDE.md); the schedule is in [`docs/plan.md`](docs/plan.md).
