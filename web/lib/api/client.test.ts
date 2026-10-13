import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  ApiError,
  NotFoundError,
  getHistory,
  getPrediction,
  getTickers,
  normalizeTicker,
} from "./client.ts";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "true";
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete process.env.NEXT_PUBLIC_USE_MOCKS;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("normalizeTicker trims and upper-cases", () => {
  assert.equal(normalizeTicker(" aapl "), "AAPL");
});

test("mock mode: getTickers returns the three mock tickers", async () => {
  const { tickers } = await getTickers();
  assert.deepEqual(tickers.map((t) => t.ticker), ["AAPL", "TEVA", "NVDA"]);
});

test("mock mode: getPrediction returns the matching ticker, case-insensitively", async () => {
  const prediction = await getPrediction("teva");
  assert.equal(prediction.ticker, "TEVA");
  assert.equal(prediction.horizon_days, 5);
  const total = prediction.skills.reduce((sum, s) => sum + s.weight, 0);
  assert.ok(Math.abs(total - 1) < 1e-9);
});

test("mock mode: getHistory returns points and allows null realized_vol", async () => {
  const history = await getHistory("AAPL");
  assert.equal(history.ticker, "AAPL");
  assert.ok(history.points.length > 0);
  assert.ok(history.points.some((p) => p.realized_vol === null));
  assert.ok(history.points.some((p) => p.realized_vol !== null));
});

test("mock mode: unknown ticker throws NotFoundError", async () => {
  await assert.rejects(getPrediction("ZZZZ"), NotFoundError);
  await assert.rejects(getHistory("ZZZZ"), NotFoundError);
});

test("mock mode never calls fetch", async () => {
  globalThis.fetch = () => {
    throw new Error("fetch must not be called in mock mode");
  };
  await getTickers();
  await getPrediction("AAPL");
});

test("live mode: requests the right URL and returns the body", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test/";
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    urls.push(String(input));
    return jsonResponse({ tickers: [{ ticker: "AAPL", name: "Apple Inc." }] });
  };
  const result = await getTickers();
  assert.equal(result.tickers[0]?.ticker, "AAPL");
  assert.deepEqual(urls, ["http://api.test/tickers"]);
});

test("live mode: 404 becomes NotFoundError", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => jsonResponse({ detail: "nope" }, 404);
  await assert.rejects(getPrediction("ZZZZ"), NotFoundError);
});

test("live mode: other statuses become ApiError with the status", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => jsonResponse({ detail: "boom" }, 500);
  await assert.rejects(getHistory("AAPL"), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 500);
    return true;
  });
});

test("live mode: network failure becomes ApiError", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  await assert.rejects(getTickers(), ApiError);
});

test("live mode: invalid JSON becomes ApiError", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => new Response("not json", { status: 200 });
  await assert.rejects(getTickers(), ApiError);
});
