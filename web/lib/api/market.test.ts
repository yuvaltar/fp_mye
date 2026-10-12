import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  SPARK_BATCH,
  fetchMarketPrices,
  fetchMarketQuotes,
  marketDataEnabled,
  parseChart,
  parseSpark,
  yahooSymbol,
} from "./market.ts";
import { getPrices, getQuotes } from "./client.ts";
import { realizedVolFromCloses } from "../derive.ts";
import { formatDateTimeUtc, formatVolume } from "../format.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete process.env.NEXT_PUBLIC_LIVE_MARKET_DATA;
  delete process.env.NEXT_PUBLIC_USE_MOCKS;
});

/** 1 Oct .. 7 Oct 2026 (Thu..Wed), NYSE hours: 13:30 UTC open bar, gmtoffset -4h. */
const DAY = 86_400;
const T0 = Date.UTC(2026, 9, 1, 13, 30) / 1000;

function chart(overrides: Record<string, unknown> = {}, closes: (number | null)[] = [100, 101, 102, 103, 104]) {
  return {
    chart: {
      result: [
        {
          meta: {
            currency: "USD",
            symbol: "AAPL",
            exchangeName: "NMS",
            fullExchangeName: "NasdaqGS",
            longName: "Apple Inc.",
            gmtoffset: -14400,
            regularMarketPrice: 104.5,
            regularMarketTime: T0 + 4 * DAY + 23_400,
            chartPreviousClose: 90,
            regularMarketDayHigh: 105,
            regularMarketDayLow: 103,
            regularMarketVolume: 33_380_854,
            fiftyTwoWeekHigh: 120,
            fiftyTwoWeekLow: 80,
            ...overrides,
          },
          timestamp: closes.map((_, i) => T0 + i * DAY),
          indicators: { quote: [{ close: closes }] },
        },
      ],
      error: null,
    },
  };
}

test("yahooSymbol maps dots to dashes and normalizes", () => {
  assert.equal(yahooSymbol("brk.b"), "BRK-B");
  assert.equal(yahooSymbol(" aapl "), "AAPL");
});

test("parseChart builds prices and a quote; previous close comes from the series", () => {
  const parsed = parseChart(chart(), "aapl");
  assert.ok(parsed);
  assert.equal(parsed.ticker, "AAPL");
  assert.equal(parsed.currency, "USD");
  assert.equal(parsed.points.length, 5);
  assert.deepEqual(parsed.points[0], { date: "2026-10-01", close: 100 });
  assert.equal(parsed.last_close, 104.5);
  assert.equal(parsed.last_close_date, "2026-10-05");
  assert.equal(parsed.quote?.previous_close, 103, "yesterday's close, not chartPreviousClose (90)");
  assert.equal(parsed.quote?.day_high, 105);
  assert.equal(parsed.quote?.volume, 33_380_854);
  assert.equal(parsed.quote?.exchange, "NasdaqGS");
  assert.equal(parsed.quote?.name, "Apple Inc.");
  assert.match(parsed.quote?.time ?? "", /^2026-10-05T/);
});

test("parseChart skips null and non-positive closes", () => {
  const parsed = parseChart(chart({}, [100, null, 0, 103, 104]), "AAPL");
  assert.deepEqual(parsed?.points.map((p) => p.close), [100, 103, 104]);
});

test("parseChart keeps one point per date (later bar wins)", () => {
  const json = chart({}, [100, 101]);
  const result = json.chart.result[0];
  assert.ok(result);
  result.timestamp = [T0, T0 + 3600];
  const parsed = parseChart(json, "AAPL");
  assert.equal(parsed?.points.length, 1);
  assert.equal(parsed?.points[0]?.close, 101);
});

test("parseChart returns null for unusable answers", () => {
  assert.equal(parseChart(null, "AAPL"), null);
  assert.equal(parseChart({}, "AAPL"), null);
  assert.equal(parseChart({ chart: { result: null, error: { code: "Not Found" } } }, "AAPL"), null);
  assert.equal(parseChart(chart({}, [null, null]), "AAPL"), null);
});

test("parseChart handles missing optional meta fields", () => {
  const parsed = parseChart(chart({ regularMarketDayHigh: undefined, regularMarketVolume: "x", longName: undefined, shortName: undefined }), "AAPL");
  assert.equal(parsed?.quote?.day_high, null);
  assert.equal(parsed?.quote?.volume, null);
  assert.equal(parsed?.quote?.name, null);
});

test("parseSpark reads closes and computes the day change", () => {
  const quotes = parseSpark({
    AAPL: { close: [330, 333.69, 336.67] },
    "BRK-B": { close: [500, null, 505] },
    BAD: { close: [] },
    NONSENSE: 5,
  });
  assert.equal(quotes.size, 2);
  const aapl = quotes.get("AAPL");
  assert.equal(aapl?.price, 336.67);
  assert.equal(aapl?.previousClose, 333.69);
  assert.ok(Math.abs((aapl?.change ?? 0) - (336.67 / 333.69 - 1)) < 1e-12);
  assert.equal(quotes.get("BRK-B")?.previousClose, 500);
  assert.equal(parseSpark("junk").size, 0);
});

test("parseSpark with a single close has no change", () => {
  const quote = parseSpark({ AAPL: { close: [100] } }).get("AAPL");
  assert.equal(quote?.change, null);
});

test("marketDataEnabled is off unless explicitly turned on", () => {
  assert.equal(marketDataEnabled(), false);
  process.env.NEXT_PUBLIC_LIVE_MARKET_DATA = "true";
  assert.equal(marketDataEnabled(), true);
  process.env.NEXT_PUBLIC_LIVE_MARKET_DATA = "yes";
  assert.equal(marketDataEnabled(), false);
});

test("fetchMarketPrices requests the Yahoo symbol and tolerates failures", async () => {
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    urls.push(String(input));
    return new Response(JSON.stringify(chart()), { status: 200 });
  };
  const ok = await fetchMarketPrices("BRK.B");
  assert.ok(ok);
  assert.match(urls[0] ?? "", /\/chart\/BRK-B\?range=1y&interval=1d$/);

  globalThis.fetch = async () => new Response("nope", { status: 404 });
  assert.equal(await fetchMarketPrices("ZZZZ"), null);
  globalThis.fetch = async () => {
    throw new Error("network down");
  };
  assert.equal(await fetchMarketPrices("AAPL"), null);
  globalThis.fetch = async () => new Response("not json", { status: 200 });
  assert.equal(await fetchMarketPrices("AAPL"), null);
});

test("fetchMarketQuotes batches symbols and maps Yahoo symbols back to the caller's", async () => {
  const tickers = Array.from({ length: SPARK_BATCH + 5 }, (_, i) => `T${i}`);
  tickers[0] = "BRK.B";
  const requested: string[] = [];
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    const symbols = (url.searchParams.get("symbols") ?? "").split(",");
    requested.push(...symbols);
    const body = Object.fromEntries(symbols.map((s) => [s, { close: [10, 11] }]));
    return new Response(JSON.stringify(body), { status: 200 });
  };
  const quotes = await fetchMarketQuotes(tickers);
  assert.equal(quotes.size, tickers.length);
  assert.ok(quotes.has("BRK.B"));
  assert.ok(requested.includes("BRK-B"));
  assert.equal(requested.length, tickers.length);
  assert.ok(Math.abs((quotes.get("T3")?.change ?? 0) - 0.1) < 1e-12);
});

test("fetchMarketQuotes: a failing batch does not lose the others", async () => {
  const tickers = Array.from({ length: SPARK_BATCH * 2 }, (_, i) => `T${i}`);
  let calls = 0;
  globalThis.fetch = async (input) => {
    calls += 1;
    const symbols = (new URL(String(input)).searchParams.get("symbols") ?? "").split(",");
    if (symbols.includes("T0")) return new Response("{}", { status: 500 });
    return new Response(JSON.stringify(Object.fromEntries(symbols.map((s) => [s, { close: [1, 2] }]))), { status: 200 });
  };
  const quotes = await fetchMarketQuotes(tickers);
  assert.equal(calls, 2);
  assert.equal(quotes.size, SPARK_BATCH);
});

test("getQuotes returns nothing and does not fetch when live market data is off", async () => {
  globalThis.fetch = async () => {
    throw new Error("must not be called");
  };
  assert.equal((await getQuotes(["AAPL"])).size, 0);
});

test("getPrices in mock mode: real market data when enabled, sample otherwise", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "true";
  const off = await getPrices("AAPL");
  assert.ok(off.state === "available" && off.sample && off.source === undefined);

  process.env.NEXT_PUBLIC_LIVE_MARKET_DATA = "true";
  globalThis.fetch = async () => new Response(JSON.stringify(chart()), { status: 200 });
  const on = await getPrices("AAPL");
  assert.ok(on.state === "available" && !on.sample && on.source === "market");
  assert.ok(on.state === "available" && on.data.quote !== undefined);

  // The market source failing falls back to the labelled sample.
  globalThis.fetch = async () => new Response("{}", { status: 500 });
  const fallback = await getPrices("AAPL");
  assert.ok(fallback.state === "available" && fallback.sample);
});

test("getPrices in live mode prefers the engine's /prices over market data", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_LIVE_MARKET_DATA = "true";
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    urls.push(String(input));
    if (String(input).includes("/prices")) {
      return new Response(
        JSON.stringify({ ticker: "AAPL", currency: "USD", last_close: 1, last_close_date: "2026-10-07", points: [] }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify(chart()), { status: 200 });
  };
  const result = await getPrices("AAPL");
  assert.ok(result.state === "available" && !result.sample && result.source === undefined);
  assert.equal(urls.length, 1);
});

test("getPrices in live mode falls back to market data when the engine has no /prices", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  process.env.NEXT_PUBLIC_LIVE_MARKET_DATA = "true";
  globalThis.fetch = async (input) =>
    String(input).includes("/prices")
      ? new Response("{}", { status: 404 })
      : new Response(JSON.stringify(chart()), { status: 200 });
  const result = await getPrices("AAPL");
  assert.ok(result.state === "available" && result.source === "market");

  delete process.env.NEXT_PUBLIC_LIVE_MARKET_DATA;
  assert.deepEqual(await getPrices("AAPL"), { state: "unavailable" });
});

test("realizedVolFromCloses matches the contract definition", () => {
  // Constant +1% log returns for 5 days: sqrt(252/5 * 5 * 0.01^2) = 0.01 * sqrt(252).
  const closes = [100];
  for (let i = 0; i < 5; i++) closes.push((closes[closes.length - 1] as number) * Math.exp(0.01));
  const vol = realizedVolFromCloses(closes, 5);
  assert.ok(vol !== null && Math.abs(vol - 0.01 * Math.sqrt(252)) < 1e-12);
});

test("realizedVolFromCloses uses only the last window and rejects bad input", () => {
  const closes = [1, 1000, 1000, 1000, 1000, 1000, 1000];
  assert.equal(realizedVolFromCloses(closes, 5), 0);
  assert.equal(realizedVolFromCloses([100, 101, 102], 5), null);
  assert.equal(realizedVolFromCloses([100, 0, 102, 103, 104, 105], 5), null);
  assert.equal(realizedVolFromCloses([100, 101], 0), null);
});

test("formatVolume and formatDateTimeUtc", () => {
  assert.equal(formatVolume(33_380_854), "33.4M");
  assert.equal(formatVolume(912_000), "912K");
  assert.equal(formatVolume(540), "540");
  assert.equal(formatVolume(2_500_000_000), "2.5B");
  assert.equal(formatVolume(null), "—");
  assert.equal(formatVolume(-5), "—");
  assert.equal(formatDateTimeUtc("2026-10-07T20:00:01.000Z"), "7 Oct 2026, 20:00 UTC");
  assert.equal(formatDateTimeUtc("garbage"), "garbage");
});
