# web

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind 4 front end for Temporal Skills Market, with charts in recharts. Owner: Maor.

## Pages

| Route | What |
| --- | --- |
| `/` | Watchlist: every stock's predicted volatility for the next 5 trading days, next to HAR-RV and its recent level, with a market snapshot |
| `/stock/[ticker]` | One stock: the prediction, each skill's own prediction and weight, prediction vs realized history, earnings notice, optional live price |
| `/performance` | The engine's track record (walk-forward backtest): the headline against HAR-RV, where the improvement comes from (earnings dates vs our skills), every model's errors, skill weights, per-stock results |
| `/about` | How the market of skills works, in plain language, and a glossary |
| `/disclaimer` | Educational project, not investment advice |

An **AI assistant** (bottom right on every page) answers questions about the stocks from the site's own data only, in English or Hebrew, through Google's Gemini (`/api/chat`). The same read-only tools are served as an MCP server (`/api/mcp`, and `npm run mcp:stdio`). It gives risk briefings, never buy/sell advice. Setup and legal protections: `../docs/assistant.md`.

## Data

All engine data goes through `lib/api/client.ts`, whose types (`lib/api/types.ts`) mirror `../contracts/prediction.schema.json`.

- `NEXT_PUBLIC_USE_MOCKS=true`: the site reads the mock files in `../contracts` (marked "sample data" on screen).
- `NEXT_PUBLIC_USE_MOCKS=false`: it calls the engine's API at `NEXT_PUBLIC_API_BASE_URL` (start it with `uvicorn tsm.api:app --port 8000` in `../algo`).
- `NEXT_PUBLIC_LIVE_MARKET_DATA=true` (optional): delayed prices from Yahoo Finance's public endpoints.
- `GEMINI_API_KEY` (optional, server-side only): switches the assistant on.

Copy the lines you need from `../.env.example` into `web/.env.local` (Next.js reads env files from `web/`).

## Commands

```bash
npm install
npm run dev         # http://localhost:3000
npm run build
npm run typecheck   # tsc --noEmit
npm test            # unit tests of lib/ (Node's built-in runner)
npm run ai:smoke    # one real call to Gemini (needs GEMINI_API_KEY)
```

Rules and conventions are in the root `CLAUDE.md`.
