/**
 * Real market data from Yahoo Finance's public chart endpoints. Keyless,
 * unofficial and delayed by up to about 15 minutes, so it is opt-in
 * (NEXT_PUBLIC_LIVE_MARKET_DATA=true) and every failure means "no data", never
 * an error page. Server-side only: it is called from client.ts and from the
 * /api/quotes route handler, never from the browser directly.
 */
import type { MarketQuote, PricesResponse } from "./extras-types.ts";

const BASE = "https://query1.finance.yahoo.com/v8/finance";
const HEADERS = { "User-Agent": "Mozilla/5.0 (compatible; TemporalSkillsMarket-educational-project)" };
const TIMEOUT_MS = 6000;
/** Seconds Next may reuse a market response; keeps requests polite. */
const REVALIDATE_SECONDS = 30;
/** Symbols per spark request. */
export const SPARK_BATCH = 20;

export function marketDataEnabled(): boolean {
  return process.env.NEXT_PUBLIC_LIVE_MARKET_DATA === "true";
}

/** Contract tickers use dots (BRK.B); Yahoo uses dashes (BRK-B). */
export function yahooSymbol(ticker: string): string {
  return ticker.trim().toUpperCase().replace(/\./g, "-");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** Exchange-local calendar date (YYYY-MM-DD) of a unix timestamp in seconds. */
function localDate(seconds: number, gmtOffsetSeconds: number): string {
  return new Date((seconds + gmtOffsetSeconds) * 1000).toISOString().slice(0, 10);
}

/** Daily closes as {date, close}, skipping the gaps Yahoo reports as null. */
function readSeries(
  timestamps: unknown,
  closes: unknown,
  gmtOffset: number,
): { date: string; close: number }[] {
  if (!Array.isArray(timestamps) || !Array.isArray(closes)) return [];
  const points: { date: string; close: number }[] = [];
  const count = Math.min(timestamps.length, closes.length);
  for (let i = 0; i < count; i++) {
    const ts = num(timestamps[i]);
    const close = num(closes[i]);
    if (ts === null || close === null || close <= 0) continue;
    points.push({ date: localDate(ts, gmtOffset), close: Math.round(close * 100) / 100 });
  }
  // One bar per date: when the live bar repeats a date, the later one wins.
  const byDate = new Map(points.map((p) => [p.date, p]));
  return [...byDate.values()];
}

/**
 * Turns a v8 chart response into the proposed /prices shape plus a quote.
 * Returns null for anything that does not look like a usable answer.
 */
export function parseChart(json: unknown, ticker: string): PricesResponse | null {
  if (!isRecord(json) || !isRecord(json.chart)) return null;
  const result = Array.isArray(json.chart.result) ? json.chart.result[0] : null;
  if (!isRecord(result) || !isRecord(result.meta)) return null;
  const meta = result.meta;
  const gmtOffset = num(meta.gmtoffset) ?? 0;

  const indicators = isRecord(result.indicators) ? result.indicators : {};
  const quoteList = Array.isArray(indicators.quote) ? indicators.quote : [];
  const quote0 = isRecord(quoteList[0]) ? quoteList[0] : {};
  const points = readSeries(result.timestamp, quote0.close, gmtOffset);
  const last = points[points.length - 1];
  if (!last) return null;

  const price = num(meta.regularMarketPrice) ?? last.close;
  const timeSeconds = num(meta.regularMarketTime);
  const previous = points.length >= 2 ? (points[points.length - 2]?.close ?? null) : null;

  const quote: MarketQuote = {
    price,
    time: new Date((timeSeconds ?? Date.now() / 1000) * 1000).toISOString(),
    // chartPreviousClose is the close before the whole chart range, not
    // yesterday's, so the previous close comes from the series itself.
    previous_close: previous,
    day_high: num(meta.regularMarketDayHigh),
    day_low: num(meta.regularMarketDayLow),
    volume: num(meta.regularMarketVolume),
    week52_high: num(meta.fiftyTwoWeekHigh),
    week52_low: num(meta.fiftyTwoWeekLow),
    exchange: str(meta.fullExchangeName) ?? str(meta.exchangeName),
    name: str(meta.longName) ?? str(meta.shortName),
  };

  return {
    ticker: ticker.trim().toUpperCase(),
    currency: str(meta.currency) ?? "USD",
    last_close: price,
    last_close_date: last.date,
    points,
    quote,
  };
}

export interface QuoteSummary {
  price: number;
  previousClose: number | null;
  /** Relative change vs the previous close, 0.012 = +1.2%; null when unknown. */
  change: number | null;
  currency: string;
}

/** Parses a v8 spark response (many symbols, daily closes) into short quotes. */
export function parseSpark(json: unknown): Map<string, QuoteSummary> {
  const quotes = new Map<string, QuoteSummary>();
  if (!isRecord(json)) return quotes;
  for (const [symbol, entry] of Object.entries(json)) {
    if (!isRecord(entry)) continue;
    const closes = Array.isArray(entry.close)
      ? entry.close.map(num).filter((v): v is number => v !== null && v > 0)
      : [];
    const price = closes[closes.length - 1];
    if (price === undefined) continue;
    const previousClose = closes.length >= 2 ? (closes[closes.length - 2] ?? null) : null;
    quotes.set(symbol.toUpperCase(), {
      price,
      previousClose,
      change: previousClose !== null && previousClose > 0 ? price / previousClose - 1 : null,
      currency: "USD",
    });
  }
  return quotes;
}

async function getJson(url: string): Promise<unknown | null> {
  try {
    const response = await fetch(url, {
      headers: HEADERS,
      signal: AbortSignal.timeout(TIMEOUT_MS),
      next: { revalidate: REVALIDATE_SECONDS },
    });
    if (!response.ok) return null;
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

/** One year of daily prices plus today's quote for one ticker; null on any failure. */
export async function fetchMarketPrices(ticker: string): Promise<PricesResponse | null> {
  const json = await getJson(
    `${BASE}/chart/${encodeURIComponent(yahooSymbol(ticker))}?range=1y&interval=1d`,
  );
  return json === null ? null : parseChart(json, ticker);
}

/**
 * Latest price and day change for many tickers, in batches of SPARK_BATCH.
 * Keys of the result are the caller's tickers (BRK.B), not Yahoo's (BRK-B).
 */
export async function fetchMarketQuotes(tickers: readonly string[]): Promise<Map<string, QuoteSummary>> {
  const unique = [...new Set(tickers.map((t) => t.trim().toUpperCase()))];
  const batches: string[][] = [];
  for (let i = 0; i < unique.length; i += SPARK_BATCH) batches.push(unique.slice(i, i + SPARK_BATCH));

  const results = await Promise.all(
    batches.map((batch) =>
      getJson(
        `${BASE}/spark?symbols=${batch.map((t) => encodeURIComponent(yahooSymbol(t))).join(",")}&range=5d&interval=1d`,
      ),
    ),
  );

  const quotes = new Map<string, QuoteSummary>();
  const byYahoo = new Map(unique.map((t) => [yahooSymbol(t), t]));
  for (const json of results) {
    for (const [symbol, quote] of parseSpark(json)) {
      const original = byYahoo.get(symbol);
      if (original) quotes.set(original, quote);
    }
  }
  return quotes;
}
