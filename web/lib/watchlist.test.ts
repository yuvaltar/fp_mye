import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { FULL_FETCH_LIMIT, loadWatchlist } from "./watchlist.ts";
import { SPARKLINE_POINTS } from "./watchlist-rows.ts";
import { getUniverse } from "./api/client.ts";
import { SP500 } from "./api/sp500.ts";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "true";
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete process.env.NEXT_PUBLIC_USE_MOCKS;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const prediction = (ticker: string, vol = 0.25) => ({
  ticker,
  as_of_date: "2026-10-07",
  horizon_days: 5,
  predicted_vol: vol,
  baseline_vol: 0.2,
  skills: [],
  supervisor_confidence: 0.5,
  model_version: "t",
});

test("the bundled S&P 500 list is complete and well-formed", () => {
  assert.ok(SP500.length >= 500 && SP500.length <= 510, `unexpected size ${SP500.length}`);
  const tickers = SP500.map((r) => r[0]);
  assert.equal(new Set(tickers).size, tickers.length, "duplicate tickers");
  for (const [ticker, name, sector] of SP500) {
    assert.match(ticker, /^[A-Z][A-Z0-9.-]{0,9}$/);
    assert.ok(name.length > 0 && sector.length > 0);
  }
  assert.ok(tickers.includes("AAPL") && tickers.includes("NVDA"));
});

test("mock mode universe: S&P 500 plus the contract's mock tickers, sorted, with sectors", async () => {
  const universe = await getUniverse();
  assert.ok(universe.length > 500);
  assert.ok(universe.some((u) => u.ticker === "TEVA"), "mock ticker TEVA must stay");
  assert.equal(universe.find((u) => u.ticker === "AAPL")?.sector, "Information Technology");
  const sorted = [...universe].map((u) => u.ticker).sort((a, b) => a.localeCompare(b));
  assert.deepEqual(universe.map((u) => u.ticker), sorted);
});

test("mock mode: 500+ tickers load through the overview; only the mock tickers have numbers", async () => {
  const { rows, source } = await loadWatchlist();
  assert.equal(source, "overview");
  assert.ok(rows.length > 500);
  const withNumbers = rows.filter((r) => r.status === "ok").map((r) => r.ticker).sort();
  assert.deepEqual(withNumbers, ["AAPL", "NVDA", "TEVA"]);
  assert.ok(rows.filter((r) => r.status === "no-prediction").length > 490);
  const aapl = rows.find((r) => r.ticker === "AAPL");
  assert.equal(aapl?.status, "ok");
  if (aapl?.status === "ok") assert.ok(["rising", "stable", "falling", "no-data"].includes(aapl.trend));
});

test("live mode, small universe: per ticker, with sparkline and trend, failures isolated", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.endsWith("/tickers")) {
      return json({
        tickers: [
          { ticker: "AAPL", name: "Apple Inc." },
          { ticker: "BAD", name: "Broken Co." },
          { ticker: "NEW", name: "New Co." },
        ],
      });
    }
    if (url.includes("ticker=BAD")) return json({ detail: "x" }, 500);
    if (url.includes("ticker=NEW")) return json({ detail: "none" }, 404);
    if (url.includes("/predict")) return json(prediction("AAPL"));
    return json({
      ticker: "AAPL",
      horizon_days: 5,
      points: [{ as_of_date: "2026-10-01", predicted_vol: 0.2, baseline_vol: 0.2, realized_vol: 0.2 }],
    });
  };
  const { rows, source } = await loadWatchlist();
  assert.equal(source, "per-ticker");
  assert.deepEqual(rows.map((r) => r.status), ["ok", "unavailable", "no-prediction"]);
  const ok = rows[0];
  if (ok?.status === "ok") {
    assert.equal(ok.trend, "rising");
    assert.ok(ok.spark.length > 1 && ok.spark.length <= SPARKLINE_POINTS);
    assert.equal(ok.spark[ok.spark.length - 1], 0.25);
  }
});

test("live mode, small universe: failing history gives a no-data badge but keeps the row", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.endsWith("/tickers")) return json({ tickers: [{ ticker: "AAPL", name: "Apple" }] });
    if (url.includes("/history")) return json({ detail: "x" }, 500);
    return json(prediction("AAPL"));
  };
  const { rows } = await loadWatchlist();
  assert.equal(rows[0]?.status, "ok");
  if (rows[0]?.status === "ok") assert.equal(rows[0].trend, "no-data");
});

function bigUniverse(count: number) {
  return {
    tickers: Array.from({ length: count }, (_, i) => ({ ticker: `T${String(i).padStart(3, "0")}`, name: `Company ${i}` })),
  };
}

test("live mode, large universe with /overview: one request, no per-ticker calls", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    const url = String(input);
    urls.push(url);
    if (url.endsWith("/tickers")) return json(bigUniverse(200));
    if (url.endsWith("/overview")) {
      return json({
        entries: [
          { ticker: "T001", as_of_date: "2026-10-07", predicted_vol: 0.3, baseline_vol: 0.2, supervisor_confidence: 0.6, latest_realized_vol: 0.2 },
          { ticker: "T002", as_of_date: "2026-10-07", predicted_vol: 0.2, baseline_vol: 0.2, supervisor_confidence: 0.7, latest_realized_vol: null },
        ],
      });
    }
    return json({ detail: "unexpected" }, 500);
  };
  const { rows, source } = await loadWatchlist();
  assert.equal(source, "overview");
  assert.equal(rows.length, 200);
  assert.deepEqual(urls.sort(), ["http://127.0.0.1:8000/overview", "http://127.0.0.1:8000/tickers"]);
  const t1 = rows.find((r) => r.ticker === "T001");
  const t2 = rows.find((r) => r.ticker === "T002");
  assert.ok(t1?.status === "ok" && t1.trend === "rising");
  assert.ok(t2?.status === "ok" && t2.trend === "no-data");
  assert.equal(rows.filter((r) => r.status === "no-prediction").length, 198);
});

test("live mode, large universe without /overview: only the first tickers are loaded", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  const predictCalls: string[] = [];
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.endsWith("/tickers")) return json(bigUniverse(100));
    if (url.endsWith("/overview")) return json({}, 404);
    if (url.includes("/predict")) {
      predictCalls.push(url);
      return json(prediction("X"));
    }
    return json({ ticker: "X", horizon_days: 5, points: [] });
  };
  const { rows, source } = await loadWatchlist();
  assert.equal(source, "partial");
  assert.equal(rows.length, 100);
  assert.equal(predictCalls.length, FULL_FETCH_LIMIT);
  assert.equal(rows.filter((r) => r.status === "ok").length, FULL_FETCH_LIMIT);
  assert.equal(rows.filter((r) => r.status === "no-prediction").length, 100 - FULL_FETCH_LIMIT);
});
