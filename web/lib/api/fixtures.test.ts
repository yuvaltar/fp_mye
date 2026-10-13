import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  hashString,
  samplePrices,
  seededRandom,
  weekdaysEndingAt,
} from "./fixtures.ts";
import {
  NotFoundError,
  getOverview,
  getPerformance,
  getPrediction,
  getPrices,
  getWeightsHistory,
} from "./client.ts";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "true";
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete process.env.NEXT_PUBLIC_USE_MOCKS;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
  delete process.env.NEXT_PUBLIC_LIVE_MARKET_DATA;
});

test("seededRandom is deterministic and within [0, 1)", () => {
  const a = seededRandom(42);
  const b = seededRandom(42);
  for (let i = 0; i < 20; i++) {
    const value = a();
    assert.equal(value, b());
    assert.ok(value >= 0 && value < 1);
  }
  assert.notEqual(seededRandom(1)(), seededRandom(2)());
  assert.equal(hashString("AAPL"), hashString("AAPL"));
});

test("weekdaysEndingAt returns weekdays only, oldest first, ending at the date", () => {
  const days = weekdaysEndingAt("2026-10-07", 10);
  assert.equal(days.length, 10);
  assert.equal(days[days.length - 1], "2026-10-07");
  assert.deepEqual([...days].sort(), days);
  for (const day of days) {
    const weekday = new Date(`${day}T00:00:00Z`).getUTCDay();
    assert.ok(weekday !== 0 && weekday !== 6, `${day} is a weekend`);
  }
});

test("samplePrices is deterministic, positive and ends on the prediction date", async () => {
  const prediction = await getPrediction("AAPL");
  const a = samplePrices(prediction);
  const b = samplePrices(prediction);
  assert.deepEqual(a, b);
  assert.equal(a.points.length, 90);
  assert.equal(a.last_close_date, prediction.as_of_date);
  assert.equal(a.last_close, a.points[a.points.length - 1]?.close);
  assert.ok(a.points.every((p) => p.close > 0));
});

test("mock mode: weights come from the contract mock, sum to 1 and end at /predict", async () => {
  const result = await getWeightsHistory("nvda");
  assert.ok(result.state === "available" && result.sample);
  if (result.state !== "available") return;
  const prediction = await getPrediction("NVDA");
  for (const point of result.data.points) {
    const total = point.weights.reduce((sum, w) => sum + w.weight, 0);
    assert.ok(Math.abs(total - 1) < 1e-3, `${point.as_of_date} sums to ${total}`);
  }
  const last = result.data.points[result.data.points.length - 1];
  assert.deepEqual(
    last?.weights.map((w) => [w.name, w.weight]),
    prediction.skills.map((s) => [s.name, s.weight]),
  );
});

test("mock mode: performance comes from the contract mock with QLIKE as the headline", async () => {
  const result = await getPerformance();
  assert.ok(result.state === "available" && result.sample);
  if (result.state !== "available") return;
  const { headline, models } = result.data;
  assert.equal(headline.metric, "qlike");
  assert.ok(Math.abs(headline.improvement - (1 - headline.supervisor / headline.baseline)) < 1e-3);
  assert.ok(models.some((m) => m.kind === "supervisor"));
  const baseline = models.find((m) => m.name === "har_rv");
  assert.equal(baseline?.qlike_vs_har_rv, null);
});

test("mock mode: overview comes from the contract mock and carries earnings_date", async () => {
  const result = await getOverview();
  assert.ok(result.state === "available" && result.sample);
  if (result.state !== "available") return;
  assert.deepEqual(result.data.entries.map((e) => e.ticker), ["AAPL", "TEVA", "NVDA"]);
  assert.equal(result.data.entries.find((e) => e.ticker === "TEVA")?.earnings_date, "2026-10-13");
  assert.equal(result.data.entries.find((e) => e.ticker === "AAPL")?.earnings_date, null);
});

test("mock mode: prices are labelled sample data unless live market data is on", async () => {
  const prices = await getPrices("aapl");
  assert.ok(prices.state === "available" && prices.sample);
});

test("mock mode: an unknown ticker is rejected where a ticker is needed", async () => {
  await assert.rejects(getPrices("ZZZZ"), NotFoundError);
  await assert.rejects(getWeightsHistory("ZZZZ"), NotFoundError);
});

test("live mode: a missing endpoint (404) means unavailable, not an error", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => new Response("{}", { status: 404 });
  assert.deepEqual(await getWeightsHistory("AAPL"), { state: "unavailable" });
  assert.deepEqual(await getPerformance(), { state: "unavailable" });
  assert.deepEqual(await getOverview(), { state: "unavailable" });
});

test("live mode: network failure also means unavailable", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  assert.deepEqual(await getPerformance(), { state: "unavailable" });
});

test("live mode: an answer that is not shaped like an overview counts as missing", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => new Response(JSON.stringify({ something: "else" }), { status: 200 });
  assert.deepEqual(await getOverview(), { state: "unavailable" });
});

test("live mode: working endpoints return real, non-sample data from the right URL", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    urls.push(String(input));
    return new Response(JSON.stringify({ ticker: "AAPL", skills: [], points: [], entries: [] }), { status: 200 });
  };
  const weights = await getWeightsHistory("aapl");
  assert.ok(weights.state === "available" && !weights.sample);
  const overview = await getOverview();
  assert.ok(overview.state === "available" && !overview.sample);
  assert.deepEqual(urls, ["http://api.test/weights?ticker=AAPL", "http://api.test/overview"]);
});

test("live mode: the engine has no /prices, so prices are unavailable without market data", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => {
    throw new Error("the engine must not be asked for /prices");
  };
  assert.deepEqual(await getPrices("AAPL"), { state: "unavailable" });
});
