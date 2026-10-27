# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

The team is 3 junior developers (B.Sc. Computer Science) who do not write code themselves: Claude writes 100% of the code and the team steers through prompts and skills. Never ask them to edit code by hand, and explain every decision in plain language.

**Temporal Skills Market** is a stock-tracking platform with a multi-agent prediction engine built in.

- Each **skill** is an agent specialized in one time horizon or one signal type (trend, weak signals, seasonality, ...).
- A **supervisor** dynamically assigns a weight to each skill based on its recent performance. This is the "market".
- **MVP:** predict 5-trading-day realized volatility for a list of stocks.
- **Team:** Elie and Yuval share `/algo`; Maor owns `/web`. Elie was away from 2026-10-12 and **returned on 2026-10-22**; Elie works on the supervisor and the ST-GNN on branch `algo-elie`. Yuval built the iTransformer, the market map, the earnings layer and contract v2 on the server side.
- **Trust:** every collaborator may change any file in the repository without asking the others first; the team trusts each other. Changes still go through a PR, so everyone sees them before they reach `main`.
  
- **Timeline:** the 7-day plan in `docs/plan.md` ended on 2026-10-14; `docs/handoff.md` later estimated the real deadline at about 2026-10-22. No newer date is recorded.

## Hard rules

- **A change to the contract in `/contracts` updates the schema, the mocks, the engine and the website in the same PR.** The contract is the exact format the API sends to the site: changed on one side only, it breaks the other without any test failing.
- Stop and ask before installing any dependency outside: pandas, numpy, yfinance, scikit-learn, torch, neuralforecast, arch, fastapi, uvicorn, matplotlib, pytest, jsonschema (Python); next, react, tailwind, recharts (web). TypeScript, `@types/*` and `@tailwindcss/postcss` are already present because the Next.js + TypeScript + Tailwind stack requires them.
- Never write API keys or secrets. Configuration goes through environment variables documented in `.env.example`.
- Code lives only in `/algo`, `/web`, `/contracts` and `/docs`. The root holds config files only.
- Engine work goes through `algo-elie` or `algo-yuval`, then `algo`, then `main`; the website goes through `web-initial-site` or `web-v2-integration`.

## Layout

- `algo/` — Python 3.12 engine and FastAPI server. Package `tsm`; one module per committee skill in `tsm/skills/`, experimental models in `tsm/models/`.
- `web/` — Next.js 16 (App Router) + React 19 + TypeScript + Tailwind 4; charts with recharts.
- `contracts/` — `prediction.schema.json` plus mock responses. The single source of truth for the API; see `contracts/README.md` for the endpoints and the rules the schema cannot express (volatility units, weights summing to 1).
- `docs/` — `plan.md` (7-day plan), `backtest.md` (the committee's results), `experiments.md` (one row per candidate run) and `handoff.md` (Yuval's session notes up to Step 14). The two results files are generated; do not hand-edit them.
- `.claude/skills/` — `add-temporal-skill` and `backtest-report`. Use them rather than improvising those two procedures.

The engine in `algo` is implemented end to end (data, four skills, calibration, supervisor, backtest, report, API, experiment runner). The website (watchlist, stock page, performance, about) and contract v2 were merged into `main` in PR #9; it reads the API, or the mocks with `NEXT_PUBLIC_USE_MOCKS=true`.

## How the engine fits together

- `tsm/data.py` downloads and caches prices; a **panel** is a dict of ticker to price frame on common dates. `tsm/target.py` defines realized volatility.
- `tsm/skills/` holds one module per skill, all implementing `TemporalSkill` (`base.py`): `fit(panel)` and `predict(panel) -> {ticker: vol}`. Current skills: `short_term` (HAR-RV, also the baseline), `regime` (GARCH), `weak_signals` (gradient boosting on volume, range, gap and SPY-correlation features), `itransformer` (our own PyTorch iTransformer on all tickers jointly, `itransformer_path_feats` averaged over seeds 0, 1 and 2), `stgnn` (Elie's ST-GNN: a GRU per stock and one graph layer on the correlation map, `stgnn_skill_corr` averaged over seeds 0, 1 and 2; weakest alone, it joined because the committee is better with it). `multivariate` (the neuralforecast iTransformer it replaced) stays in `tsm/skills/` outside the registry, so older results remain reproducible.
- `tsm/supervisor.py` holds the skill registry (`build_skills`) and the supervisor: per ticker and date, softmax over minus each skill's average QLIKE on its last predictions whose outcome is already known.
- `tsm/backtest.py` is the pipeline. It walks forward day by day, handing skills a panel truncated at the as-of date, then **calibrates** every skill: each prediction is multiplied by `c = sqrt(mean((realized / predicted)^2))`, computed per date from the last 250 trading days of outcomes already known on that date, pooled over tickers (raw values kept as `raw_pred_<skill>`, factors as `c_<skill>`). The equal-weight average and the HAR-RV baseline are built from the calibrated predictions. It then tunes the supervisor's window and temperature on dates before 2020, and writes `algo/artifacts/predictions.csv` and `meta.json`. `tsm/report.py` turns that into `docs/backtest.md`.
- `tsm/models/itransformer.py` is our own PyTorch iTransformer (one token per stock, attention across stocks; options for a 5-step path head and 4 input channels). Its variants are **candidates**, not committee members. `tsm/experiment.py` scores candidates without re-running the committee: it reads the committee's saved `raw_pred_*` columns from `algo/artifacts/predictions.csv`, walks only the candidates forward on the frozen price cache (it never downloads, so it sees the prices the artifacts were built from), calibrates and scores every model exactly as the report does, and appends rows to `docs/experiments.md`. A candidate joins the committee only through `add-temporal-skill`.
- **Earnings layer (on since Step 13):** between the skills and the calibration, a forecast whose next 5 trading days hold an earnings reaction gets one expected earnings move added to every skill's variance (`tsm/earnings_jump.py`). `raw_pred_<skill>` stays each model's own prediction and the HAR-RV baseline stays plain HAR-RV. It reads the saved earnings dates (`python -m tsm.earnings`, git-ignored `algo/data/earnings/`), which are assumed known 5 trading days ahead; `python -m tsm.backtest --no-earnings` runs the path from before it.
- `tsm/api.py` serves contract v2 from committed files only: `algo/artifacts/predictions.csv`, `meta.json` and `earnings.csv` (the report dates behind `earnings_date`; `predictions.csv` holds only reaction days). Endpoints: `/tickers` (with `sector` from `config.SECTORS`), `/predict` (with `earnings_date`), `/history`, `/overview`, `/weights` and `/performance`. `/performance` uses `report.backtest_numbers`, the same function that writes `docs/backtest.md`, so the API and the report always agree. Nothing reads `algo/data/` (prices, earnings), which a fresh clone does not have. It trains nothing, so **new predictions appear only after `python -m tsm.backtest` is re-run** (about the time printed at the end of a run); the backtest rewrites all three artifacts. The artifacts are committed so the API works from a fresh clone.

The website reads the live API since contract v2 (PR #9 to #12, 2026-10-13); with `NEXT_PUBLIC_USE_MOCKS=true` it reads the mock files instead.

## ST-GNN status

- Done (Yuval, Steps 8–9): `tsm/models/graph.py` builds the market map (correlation and sector adjacency, leakage-tested). Fed into the iTransformer, it gave no measurable gain, and a shuffled map scored the same (`docs/experiments.md`).
- Done (Elie, 2026-10-27): an ST-GNN **supervisor** (`tsm/models/stgnn.py`, `python -m tsm.stgnn`) was a no-go: 0.4270 on the test period against 0.4263 for the softmax supervisor (`docs/stgnn-results.md`).
- Done (Elie, 2026-10-27): the ST-GNN **predictor** joined the committee as the fifth skill `stgnn` (`tsm/models/stgnn_skill.py`, decision in `docs/stgnn-skill-results.md`): the supervisor went from 0.4263 to 0.4243. The gain is about the seed spread, and the same model without the graph did as well, so it comes from the GRU's different errors, not from the market map. Its walks ran on Modal (`python -m tsm.stgnn_skill walk --modal`, needs `modal` and Elie's account).
- The price cache on Elie's machine was partly re-downloaded on 2026-10-22, so a backtest there moves single skills slightly (weak_signals 0.4338 to 0.4332) but not the four-skill committee (0.4263 either way).

## Notes versus facts

Session notes (`docs/handoff.md`, commit messages, PR descriptions, and the numbers quoted in this file) are leads, not verified facts. Before relying on one, check it against the code, the tests, the git history or the generated reports. When they disagree, the code and the generated reports win: say which note was wrong, and do not repeat its claim.

## Commands

### algo

```bash
cd algo
python3.12 -m venv .venv && source .venv/bin/activate     # Unix
py -3.12 -m venv .venv && source .venv/Scripts/activate   # Windows (Git Bash); or call .venv/Scripts/python.exe directly
pip install -r requirements-dev.txt        # runtime + pytest + jsonschema
pytest                                     # all tests
pytest tests/test_contract.py              # re-validate the mocks against the schema
pytest tests/test_contract.py::test_mock_tickers   # a single test
pytest tests/test_backtest.py              # the future-leakage tests
python -m tsm.data                         # download and cache prices for every covered ticker
python -m tsm.backtest                     # full pipeline: backtest, artifacts for the API, docs/backtest.md
python -m tsm.backtest --cache-only        # the same on the frozen price cache, comparable with docs/experiments.md
python -m tsm.backtest --no-earnings       # without the earnings layer (reproduces results from before Step 13)
python -m tsm.earnings                     # collect earnings dates (Yahoo + SEC check); needs SEC_USER_AGENT
python -m tsm.experiment itransformer_path_feats --seeds 0 1 2   # score a candidate, append to docs/experiments.md
uvicorn tsm.api:app --reload --port 8000   # serve the API (needs the artifacts)
```

On Windows, use the Python 3.12 from python.org or winget (`py -3.12`), not an MSYS2/MinGW build: torch and pandas have no wheels for it.

### web

```bash
cd web
npm install
npm run dev         # http://localhost:3000
npm run build
npm run typecheck   # tsc --noEmit
npm test            # unit tests of lib/ (Node's built-in runner)
```

Next.js reads env files from `web/`, not the repo root: copy the `NEXT_PUBLIC_*` lines of `.env.example` into `web/.env.local`.

## Conventions

- **Volatility** is always annualized 5-trading-day realized volatility as a decimal (`0.24` = 24%). Never mix in percentages or daily values.
- **Price data** comes only from `tsm.data.load_prices` (adjusted daily prices, completed trading days only, cached in the git-ignored `algo/data/`), and realized volatility only from `tsm.target`. Do not recompute either elsewhere.
- **No look-ahead:** anything computed for `as_of_date` may only use data up to and including that day's close. Backtests are walk-forward. A leak is a blocking error: `tests/test_backtest.py` and `tests/skills/test_skills.py` corrupt future prices and require past outputs not to move; never weaken them to make a change pass.
- **Tests call the API functions directly** (no `TestClient`, which would need the unapproved `httpx` dependency).
- **Python:** type hints on public functions, snake_case, one skill per module named after the skill, pure functions for feature computation, fixed random seeds, a pytest test for every skill and for every endpoint (responses validated against the schema).
- **Web:** Tailwind 4 is configured in `app/globals.css` (`@theme`), there is no `tailwind.config` file. TypeScript strict, no `any`; function components; Tailwind utility classes rather than custom CSS; all API access through a single client module whose types mirror the contract; no copies of the contract files inside `web/`.
- **Git:** never commit to `main` directly; branch, then open a PR.
