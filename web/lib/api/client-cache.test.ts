import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import { getPrediction } from "./client.ts";

const originalFetch = globalThis.fetch;
const originalEnv = process.env.NODE_ENV;

/** NODE_ENV is typed read-only by Next; tests need to flip it. */
function setNodeEnv(value: string | undefined): void {
  if (value === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
  else Reflect.set(process.env, "NODE_ENV", value);
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  setNodeEnv(originalEnv);
  delete process.env.NEXT_PUBLIC_USE_MOCKS;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
});

const body = (ticker: string) =>
  JSON.stringify({
    ticker,
    as_of_date: "2026-10-07",
    horizon_days: 5,
    predicted_vol: 0.25,
    baseline_vol: 0.2,
    skills: [],
    supervisor_confidence: 0.5,
    model_version: "t",
  });

test("under the test runner (no NODE_ENV) nothing is cached", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://cache-test-a";
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response(body("AAPL"), { status: 200 });
  };
  await getPrediction("AAPL");
  await getPrediction("AAPL");
  assert.equal(calls, 2);
});

test("in production/development a successful answer is reused, concurrent calls share one request", async () => {
  setNodeEnv("production");
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://cache-test-b";
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return new Response(body("MSFT"), { status: 200 });
  };
  await Promise.all([getPrediction("MSFT"), getPrediction("MSFT"), getPrediction("MSFT")]);
  await getPrediction("MSFT");
  assert.equal(calls, 1);
  await getPrediction("NVDA");
  assert.equal(calls, 2, "a different ticker is a different request");
});

test("a stale answer is served immediately while a refresh runs in the background", async () => {
  setNodeEnv("production");
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://cache-test-d";
  let calls = 0;
  const realNow = Date.now;
  let clock = realNow();
  Date.now = () => clock;
  try {
    globalThis.fetch = async () => {
      calls += 1;
      return new Response(
        body("KO").replace('"predicted_vol":0.25', `"predicted_vol":0.${calls}0`),
        { status: 200 },
      );
    };
    const first = await getPrediction("KO");
    assert.equal(first.predicted_vol, 0.1);

    clock += 31_000; // stale, not expired
    const second = await getPrediction("KO");
    assert.equal(second.predicted_vol, 0.1, "the old answer is returned without waiting");
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(calls, 2, "a refresh ran in the background, once");

    const third = await getPrediction("KO");
    assert.equal(third.predicted_vol, 0.2, "the refreshed answer is now served");
    assert.equal(calls, 2);

    clock += 11 * 60_000; // too old to serve
    const fourth = await getPrediction("KO");
    assert.equal(fourth.predicted_vol, 0.3);
    assert.equal(calls, 3);
  } finally {
    Date.now = realNow;
  }
});

test("a failed background refresh keeps serving the old answer", async () => {
  setNodeEnv("production");
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://cache-test-e";
  const realNow = Date.now;
  let clock = realNow();
  Date.now = () => clock;
  let calls = 0;
  try {
    globalThis.fetch = async () => {
      calls += 1;
      return calls === 1 ? new Response(body("PG"), { status: 200 }) : new Response("{}", { status: 500 });
    };
    await getPrediction("PG");
    clock += 31_000;
    const stale = await getPrediction("PG");
    assert.equal(stale.ticker, "PG");
    await new Promise((resolve) => setTimeout(resolve, 20));
    const again = await getPrediction("PG");
    assert.equal(again.ticker, "PG");
  } finally {
    Date.now = realNow;
  }
});

test("a failed answer is not remembered", async () => {
  setNodeEnv("production");
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_API_BASE_URL = "http://cache-test-c";
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return calls === 1
      ? new Response("{}", { status: 500 })
      : new Response(body("TSLA"), { status: 200 });
  };
  await assert.rejects(getPrediction("TSLA"));
  const second = await getPrediction("TSLA");
  assert.equal(second.ticker, "TSLA");
  assert.equal(calls, 2);
});
