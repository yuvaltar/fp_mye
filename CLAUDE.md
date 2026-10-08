# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

The team is 3 junior developers (B.Sc. Computer Science) who do not write code themselves: Claude writes 100% of the code and the team steers through prompts and skills. Never ask them to edit code by hand, and explain every decision in plain language.

**Temporal Skills Market** is a stock-tracking platform with a multi-agent prediction engine built in.

- Each **skill** is an agent specialized in one time horizon or one signal type (trend, weak signals, seasonality, ...).
- A **supervisor** dynamically assigns a weight to each skill based on its recent performance. This is the "market".
- **MVP:** predict 5-trading-day realized volatility for a list of stocks.
- **Team:** Elie + Yuval own `/algo`; Maor owns `/web`. Total deadline: 7 days (plan in `docs/plan.md`).

## Hard rules

- **The contract in `/contracts` only changes with the agreement of both teams.** If a task seems to need a contract change, stop and say so instead of editing it. Any agreed change updates the schema, the mocks and both sides in the same PR.
- Stop and ask before installing any dependency outside: pandas, numpy, yfinance, scikit-learn, torch, neuralforecast, arch, fastapi, uvicorn, matplotlib, pytest, jsonschema (Python); next, react, tailwind, recharts (web). TypeScript, `@types/*` and `@tailwindcss/postcss` are already present because the Next.js + TypeScript + Tailwind stack requires them.
- Never write API keys or secrets. Configuration goes through environment variables documented in `.env.example`.
- Code lives only in `/algo`, `/web`, `/contracts` and `/docs`. The root holds config files only.
- Each team works in its own folder and branch (`algo`, `web`); do not touch the other team's folder.

## Layout

- `algo/` — Python 3.12 engine and FastAPI server. Package `tsm`; one module per skill in `tsm/skills/`.
- `web/` — Next.js 16 (App Router) + React 19 + TypeScript + Tailwind 4; charts with recharts.
- `contracts/` — `prediction.schema.json` plus mock responses. The single source of truth for the API; see `contracts/README.md` for the endpoints and the rules the schema cannot express (volatility units, weights summing to 1).
- `docs/` — `plan.md` (7-day plan) and, later, `backtest.md` (generated; do not hand-edit).
- `.claude/skills/` — `add-temporal-skill` and `backtest-report`. Use them rather than improvising those two procedures.

Only the scaffold exists so far: there is no algorithm, no API server and no real web page yet. Commands marked "planned" below refer to modules that still have to be created at those exact paths.

## How the engine fits together (target design)

Every skill implements one shared interface and returns one number: its predicted annualized 5-day realized volatility for a ticker as of a date. The supervisor keeps a registry of skills, scores each on its recent out-of-sample error, turns the scores into weights that sum to 1, and outputs the weighted prediction. HAR-RV is computed alongside as the baseline every result is compared to. The FastAPI layer only serializes this into the contract shapes; the website only reads those shapes. While the API does not exist, the website reads the mock files instead (`NEXT_PUBLIC_USE_MOCKS=true`).

## Commands

### algo

```bash
cd algo
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt        # runtime + pytest + jsonschema
pytest                                     # all tests
pytest tests/test_contract.py              # re-validate the mocks against the schema
pytest tests/test_contract.py::test_mock_tickers   # a single test
uvicorn tsm.api:app --reload --port 8000   # planned: tsm/api.py does not exist yet
python -m tsm.backtest                     # planned: see the backtest-report skill
```

### web

```bash
cd web
npm install
npm run dev         # http://localhost:3000
npm run build
npm run typecheck   # tsc --noEmit
```

Next.js reads env files from `web/`, not the repo root: copy the `NEXT_PUBLIC_*` lines of `.env.example` into `web/.env.local`.

## Conventions

- **Volatility** is always annualized 5-trading-day realized volatility as a decimal (`0.24` = 24%). Never mix in percentages or daily values.
- **No look-ahead:** anything computed for `as_of_date` may only use data up to and including that day's close. Backtests are walk-forward.
- **Python:** type hints on public functions, snake_case, one skill per module named after the skill, pure functions for feature computation, fixed random seeds, a pytest test for every skill and for every endpoint (responses validated against the schema).
- **Web:** Tailwind 4 is configured in `app/globals.css` (`@theme`), there is no `tailwind.config` file. TypeScript strict, no `any`; function components; Tailwind utility classes rather than custom CSS; all API access through a single client module whose types mirror the contract; no copies of the contract files inside `web/`.
- **Git:** never commit to `main` directly; branch, then open a PR.
