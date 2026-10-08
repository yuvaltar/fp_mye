# web/CLAUDE.md

Rules for working in `/web` (owner: Maor). They add to the root `CLAUDE.md`; where both speak, the stricter one wins. Maor does not write code: you write all of it and explain each decision briefly, in plain language.

## Structure

```
web/
  app/                 routes only (page.tsx, layout.tsx, loading.tsx, error.tsx, not-found.tsx), globals.css
  components/          one component per file, named after the component (WatchlistTable.tsx)
  lib/api/types.ts     hand-written types mirroring contracts/prediction.schema.json
  lib/api/client.ts    the ONLY module that fetches data or reads mocks
  lib/format.ts        ALL number, percent and date formatting
  lib/derive.ts        ALL derived values (trend badge, dominant skill, generated sentences), pure functions
```

- Routes: `/` (watchlist) and `/stock/[ticker]` (stock page).
- Business logic does not live in components. A component receives ready values and renders them; if it needs a computed value, it comes from `lib/derive.ts`.
- `lib/derive.ts` and `lib/format.ts` stay pure: no fetch, no `Date.now()` hidden inside, no React imports. Thresholds are named constants at the top of the file (e.g. `TREND_THRESHOLD = 0.10`), never magic numbers inline.

## Data

- Pages and components never call `fetch` directly; only `lib/api/client.ts` does. It exposes typed functions (`getTickers`, `getPrediction(ticker)`, `getHistory(ticker)`) and hides whether the data is live or mocked.
- `types.ts` mirrors the schema field by field, each type with a comment naming the `$def` it mirrors (`/** Mirrors $defs/SkillPrediction. */`). No codegen and no schema library. When the contract changes, `types.ts` changes in the same PR.
- Mocks are read from `../contracts` at runtime on the server (`node:fs` with a path built from `process.cwd()`), never copied into `web/`. Mock shapes: `mock_tickers.json` is one response object; `mock_prediction.json` and `mock_history.json` are arrays with one response per ticker, so mock mode picks the element whose `ticker` matches and behaves like a 404 when none does.
- Do not add the `server-only` package (it is a new dependency). Keep mock reading inside `client.ts`, which is only imported by Server Components.
- Unknown ticker: the live API returns 404 with `{ "detail": "..." }`. The client turns that into a typed `NotFoundError`; the route then calls `notFound()`. Any other failure becomes a typed `ApiError` that the route's `error.tsx` renders.
- Pages are Server Components that fetch (in parallel with `Promise.all` where the calls are independent). Recharts charts are Client Components (`"use client"`) that receive data as props and never fetch.
- The history chart gets `realized_vol: null` as a gap in the line (no `connectNulls`), never as 0.

### Proposed endpoints (not in the contract yet)

`/prices`, `/weights` and `/performance` are proposals documented in `docs/proposed-contract-additions.md`; their types live in `lib/api/proposed-types.ts`, separate from the contract mirror in `types.ts`.

- In mock mode `client.ts` returns generated sample data from `lib/api/fixtures.ts` and every view that shows it carries the "Sample data" badge. Sample data is never shown without that badge and never in live mode.
- In live mode these calls return `{ state: "unavailable" }` on any failure, and the page shows an `UnavailableNote` instead of crashing. When the algo team agrees and ships an endpoint, it starts working with no UI change; then move its types into `types.ts` and delete its fixture.
- Client Components must not import `lib/watchlist.ts` or `lib/api/client.ts` (server-only: they read files). Pure helpers used by Client Components live in `lib/watchlist-rows.ts`.

## Environment

Exactly as in the root `.env.example`, copied into `web/.env.local` (Next.js reads env files from `web/`, not the repo root):

- `NEXT_PUBLIC_USE_MOCKS` — `true` reads `/contracts` mock files, anything else calls the API.
- `NEXT_PUBLIC_API_BASE_URL` — base URL of the algo API (default `http://127.0.0.1:8000`).

Do not invent other variables. Never write secrets.

## Display

- API volatility is a decimal (`0.24`). Convert to a percentage only in `lib/format.ts`, with 1 decimal (`24.0%`). Nothing else multiplies by 100.
- Numbers use the mono font (`--font-geist-mono`) and tabular figures (`tabular-nums`) so columns align.
- Skill names: a map of known snake_case names to labels (`short_trend` → "Short trend", ...), with a fallback that auto-formats any unknown name (`my_new_skill` → "My new skill"). Never assume a fixed list or a fixed number of skills: render whatever `skills[]` contains. Colors for skills are assigned by position from a token palette, not by name.
- Generated sentences use only fields that exist in the response (weights, predicted vs baseline, confidence). Never state or imply a reason the data does not contain. If the data is not enough for a sentence, show no sentence.
- A permanent banner in the root layout, on every page: "Educational project — not investment advice."
- Trend badge: compare `predicted_vol` with the latest non-null `realized_vol` from `/history`; above `+TREND_THRESHOLD` = rising, below `−TREND_THRESHOLD` = falling, otherwise stable (`TREND_THRESHOLD = 0.10`, relative). If the history has no non-null `realized_vol`, the badge is "no data" (a fourth state), never a guess.
- Current price and price chart are not in the contract yet: build nothing for them and show no number until the contract is agreed (see the gap in the plan).
- Rising/falling volatility is not good or bad news and says nothing about the stock price. Do not use alarm or celebration wording or icons for it.

## Design

- The whole interface is in English (`<html lang="en">`, LTR). All user-facing text is English.
- Dark financial-terminal theme only; no light mode and no theme toggle. All design tokens are defined once in `app/globals.css` inside `@theme`: `background`, `surface`, `border`, `text`, `muted`, `accent`, `up`, `down`, `neutral` (so classes like `bg-surface`, `border-border`, `text-muted`). Replace the scaffold's `prefers-color-scheme` block when the theme is set up.
- No hard-coded colors in components or chart props: use token classes in Tailwind, and read tokens through CSS variables (`var(--color-up)`) where a library needs a color string. No hex values outside `globals.css`.
- Tailwind 4 is configured in CSS only (there is no `tailwind.config` file). Utility classes rather than custom CSS.
- Layout works from phone width up. Keep text readable and contrast sufficient on the dark background.

## States

Every data view has four states, built from the start and not added later:

- **loading** — `loading.tsx` or a Suspense fallback with a skeleton of the same shape;
- **error** — `error.tsx` with a plain message and a retry;
- **empty** — e.g. no tickers, no history points, history with no realized value yet;
- **not-found** — unknown ticker, with a link back to the watchlist.

## Next.js 16

Do not rely on memory of older versions. Before using a Next.js API, check the installed version in `node_modules/next` (docs shipped in the package, type definitions, or the `next --help` output). Known change to verify, not assume: in dynamic routes `params` is a `Promise` and must be awaited (`const { ticker } = await params`). Same care for `searchParams`, caching behavior of `fetch`, and `next/font`.

## TypeScript

Strict mode. No `any` (use `unknown` and narrow). Function components only. No new dependency: stop and ask first, and check the allowed list in the root `CLAUDE.md`.

Tests: the pure functions in `lib/derive.ts` and `lib/format.ts` are tested with Node's built-in runner (`node:test`, Node 22, no dependency), in files `lib/*.test.ts` run through an npm script `test` (`node --experimental-strip-types --test`). Check what the installed Node and `tsconfig.json` require (e.g. explicit `.ts` import extensions) instead of assuming. Everything else is verified by `typecheck` + `build` + running the pages.

## Contract

`/contracts` is read-only from here. If a task seems to need new data, write it down as a gap and propose the minimal change as a message for the algo team; do not edit `/contracts` and do not work around a gap by inventing data in the UI.

## Definition of done (every task)

1. `npm run typecheck` passes.
2. `npm run build` passes.
3. No `any`, no new dependency, no hard-coded colors, no direct `fetch` outside `client.ts`.
4. Pages involved were opened in `npm run dev` with `NEXT_PUBLIC_USE_MOCKS=true` and show the loading, error, empty and not-found states where relevant.
5. A short summary to Maor: what changed, how to check it (exact URL or command), what remains.

Work on the `web` branch and open a PR; never commit to `main`.
