import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  hashString,
  samplePerformance,
  samplePrices,
  sampleWeightsHistory,
  seededRandom,
  weekdaysEndingAt,
} from "./fixtures.ts";
import { NotFoundError, getPerformance, getPrices, getWeightsHistory, getPrediction } from "./client.ts";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "true";
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete process.env.NEXT_PUBLIC_USE_MOCKS;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
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

test("sampleWeightsHistory sums to 1 on every date and ends at today's weights", async () => {
  const prediction = await getPrediction("TEVA");
  const dates = ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"];
  const history = sampleWeightsHistory(prediction, dates);
  assert.equal(history.points.length, dates.length);
  for (const point of history.points) {
    const total = point.weights.reduce((sum, w) => sum + w.weight, 0);
    assert.ok(Math.abs(total - 1) < 1e-9);
    assert.ok(point.weights.every((w) => w.weight >= 0 && w.weight <= 1));
  }
  const last = history.points[history.points.length - 1];
  prediction.skills.forEach((skill, i) => {
    assert.ok(Math.abs((last?.weights[i]?.weight ?? -1) - skill.weight) < 1e-9);
  });
});

test("samplePerformance has a supervisor, HAR-RV and sensible weights", () => {
  const perf = samplePerformance();
  assert.ok(perf.models.some((m) => m.kind === "supervisor"));
  assert.ok(perf.models.some((m) => m.name === "har_rv"));
  const total = perf.skill_weights.reduce((sum, w) => sum + w.mean, 0);
  assert.ok(Math.abs(total - 1) < 1e-9);
});

test("mock mode: optional endpoints return sample data flagged as sample", async () => {
  const prices = await getPrices("aapl");
  assert.ok(prices.state === "available" && prices.sample);
  const weights = await getWeightsHistory("NVDA");
  assert.ok(weights.state === "available" && weights.sample);
  const perf = await getPerformance();
  assert.ok(perf.state === "available" && perf.sample);
});

test("mock mode: optional endpoints still reject an unknown ticker", async () => {
  await assert.rejects(getPrices("ZZZZ"), NotFoundError);
  await assert.rejects(getWeightsHistory("ZZZZ"), NotFoundError);
});

test("live mode: a missing endpoint (404) means unavailable, not an error", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => new Response("{}", { status: 404 });
  assert.deepEqual(await getPrices("AAPL"), { state: "unavailable" });
  assert.deepEqual(await getWeightsHistory("AAPL"), { state: "unavailable" });
  assert.deepEqual(await getPerformance(), { state: "unavailable" });
});

test("live mode: network failure also means unavailable", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  assert.deepEqual(await getPerformance(), { state: "unavailable" });
});

test("live mode: a working endpoint returns real, non-sample data", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    urls.push(String(input));
    return new Response(JSON.stringify({ ticker: "AAPL", currency: "USD", last_close: 1, last_close_date: "2026-10-07", points: [] }), { status: 200 });
  };
  const result = await getPrices("aapl");
  assert.ok(result.state === "available" && !result.sample);
  assert.deepEqual(urls, ["http://api.test/prices?ticker=AAPL"]);
});
