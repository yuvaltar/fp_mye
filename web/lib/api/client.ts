/**
 * The only module that fetches data or reads mocks. Call it from Server
 * Components. Mock mode (NEXT_PUBLIC_USE_MOCKS=true) reads the files in
 * ../contracts at runtime; nothing is copied into web/.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { samplePrices } from "./fixtures.ts";
import {
  fetchMarketPrices,
  fetchMarketQuotes,
  marketDataEnabled,
  type QuoteSummary,
} from "./market.ts";
import type { Optional, PricesResponse } from "./extras-types.ts";
import { SP500 } from "./sp500.ts";
import type {
  HistoryResponse,
  OverviewResponse,
  PerformanceResponse,
  Prediction,
  TickerInfo,
  TickersResponse,
  WeightsHistoryResponse,
} from "./types.ts";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

/**
 * How long to wait for the engine. Generous on purpose: the first /performance
 * after the engine starts takes about 5 seconds (it loads its libraries) and is
 * then served from memory.
 */
const API_TIMEOUT_MS = 30_000;

/** The ticker is not known to the API (HTTP 404). */
export class NotFoundError extends Error {
  readonly ticker: string;
  constructor(ticker: string) {
    super(`Unknown ticker: ${ticker}`);
    this.name = "NotFoundError";
    this.ticker = ticker;
  }
}

/** HTTP 503: the engine has no predictions yet (its results file is missing). */
export class NotReadyError extends Error {
  constructor() {
    super("The predictions are not ready yet");
    this.name = "NotReadyError";
  }
}

/** Any other failure: network down, non-2xx status, unreadable body. */
export class ApiError extends Error {
  readonly status: number | null;
  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function useMocks(): boolean {
  return process.env.NEXT_PUBLIC_USE_MOCKS === "true";
}

function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

/** Normalizes user input like " aapl " to the contract's "AAPL". */
export function normalizeTicker(ticker: string): string {
  return ticker.trim().toUpperCase();
}

function contractsDir(): string {
  return path.resolve(process.cwd(), "..", "contracts");
}

async function readMock(file: string): Promise<unknown> {
  try {
    const text = await readFile(path.join(contractsDir(), file), "utf8");
    return JSON.parse(text) as unknown;
  } catch (cause) {
    throw new ApiError(
      `Could not read mock file ${file}: ${cause instanceof Error ? cause.message : String(cause)}`,
    );
  }
}

async function readMockForTicker<T extends { ticker: string }>(
  file: string,
  ticker: string,
): Promise<T> {
  const data = await readMock(file);
  if (!Array.isArray(data)) {
    throw new ApiError(`Mock file ${file} is not an array`);
  }
  const items = data as T[];
  const match = items.find((item) => item.ticker === ticker);
  if (!match) throw new NotFoundError(ticker);
  return match;
}

/**
 * The engine serves what its last run produced, so answers only change when it
 * runs again. Successful answers are kept in this server's memory for a short
 * time (a watchlist of 50 tickers is ~100 requests, ~10 MB). Off under the
 * test runner, where NODE_ENV is not set by Next.
 */
/** An answer is fresh for this long; older ones are served once more while a refresh runs. */
const API_FRESH_MS = 30_000;
/** Past this age an answer is never served; the caller waits for a new one. */
const API_STALE_MS = 10 * 60_000;
const apiCache = new Map<string, { fetchedAt: number; value: Promise<unknown>; refreshing: boolean }>();

function cacheEnabled(): boolean {
  return process.env.NODE_ENV === "production" || process.env.NODE_ENV === "development";
}

/**
 * Same as fetchJson, with a stale-while-revalidate cache: a stale answer is
 * returned immediately and refreshed in the background, so nobody waits for
 * the ~100 requests of a big watchlist except the very first visitor.
 */
async function fetchJson<T>(pathAndQuery: string, ticker?: string): Promise<T> {
  if (!cacheEnabled()) return fetchJsonUncached<T>(pathAndQuery, ticker);
  const key = `${apiBaseUrl()}${pathAndQuery}`;
  const hit = apiCache.get(key);
  const now = Date.now();

  if (hit && now - hit.fetchedAt < API_FRESH_MS) return hit.value as Promise<T>;

  if (hit && now - hit.fetchedAt < API_STALE_MS) {
    if (!hit.refreshing) {
      hit.refreshing = true;
      const fresh = fetchJsonUncached<T>(pathAndQuery, ticker);
      fresh.then(
        () => apiCache.set(key, { fetchedAt: Date.now(), value: fresh, refreshing: false }),
        () => {
          hit.refreshing = false; // keep serving the old answer, try again next time
        },
      );
    }
    return hit.value as Promise<T>;
  }

  const value = fetchJsonUncached<T>(pathAndQuery, ticker);
  apiCache.set(key, { fetchedAt: now, value, refreshing: false });
  // A failure must not be remembered: the next request tries again.
  value.catch(() => {
    if (apiCache.get(key)?.value === value) apiCache.delete(key);
  });
  return value;
}

async function fetchJsonUncached<T>(pathAndQuery: string, ticker?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${pathAndQuery}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
  } catch (cause) {
    throw new ApiError(
      `Could not reach the API: ${cause instanceof Error ? cause.message : String(cause)}`,
    );
  }
  if (response.status === 404 && ticker !== undefined) {
    throw new NotFoundError(ticker);
  }
  if (response.status === 503) throw new NotReadyError();
  if (!response.ok) {
    throw new ApiError(`The API answered with status ${response.status}`, response.status);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("The API returned a response that is not valid JSON", response.status);
  }
}

/**
 * Optional (proposed) endpoint in live mode: any failure, including a 404
 * because the engine does not offer it yet, means "unavailable". These extras
 * never break the page.
 */
async function fetchOptional<T>(pathAndQuery: string): Promise<Optional<T>> {
  try {
    const response = await fetch(`${apiBaseUrl()}${pathAndQuery}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
    if (!response.ok) return { state: "unavailable" };
    return { state: "available", data: (await response.json()) as T, sample: false };
  } catch {
    return { state: "unavailable" };
  }
}

/**
 * PROPOSED GET /prices?ticker=XXX. Mock mode returns labelled sample data;
 * live mode returns "unavailable" until the engine offers the endpoint.
 */
export async function getPrices(ticker: string): Promise<Optional<PricesResponse>> {
  const symbol = normalizeTicker(ticker);
  if (useMocks()) {
    // Mock mode still needs a known ticker; with live market data on, real
    // prices replace the generated sample for any listed company.
    if (marketDataEnabled()) {
      const real = await fetchMarketPrices(symbol);
      if (real) return { state: "available", data: real, sample: false, source: "market" };
    }
    const prediction = await readMockForTicker<Prediction>("mock_prediction.json", symbol);
    return { state: "available", data: samplePrices(prediction), sample: true };
  }
  // Live mode: the engine does not serve prices (contract v2 has no /prices),
  // so real prices come from the market data source or not at all.
  if (!marketDataEnabled()) return { state: "unavailable" };
  const real = await fetchMarketPrices(symbol);
  return real
    ? { state: "available", data: real, sample: false, source: "market" }
    : { state: "unavailable" };
}

/** Latest price and day change for many tickers from the market data source. */
export async function getQuotes(tickers: readonly string[]): Promise<Map<string, QuoteSummary>> {
  if (!marketDataEnabled()) return new Map();
  return fetchMarketQuotes(tickers);
}

/**
 * GET /weights?ticker=XXX (contract v2): skill weights over time. Mock mode
 * reads mock_weights.json and flags it as sample; with an engine that does not
 * have the endpoint yet the section is "unavailable".
 */
export async function getWeightsHistory(
  ticker: string,
): Promise<Optional<WeightsHistoryResponse>> {
  const symbol = normalizeTicker(ticker);
  if (useMocks()) {
    const data = await readMockForTicker<WeightsHistoryResponse>("mock_weights.json", symbol);
    return { state: "available", data, sample: true };
  }
  return fetchOptional<WeightsHistoryResponse>(`/weights?ticker=${encodeURIComponent(symbol)}`);
}

/** GET /performance (contract v2): the backtest summary. Mock mode reads mock_performance.json. */
export async function getPerformance(): Promise<Optional<PerformanceResponse>> {
  if (useMocks()) {
    const data = (await readMock("mock_performance.json")) as PerformanceResponse;
    return { state: "available", data, sample: true };
  }
  return fetchOptional<PerformanceResponse>("/performance");
}

/**
 * The tickers to list, with the optional sector. Live mode: GET /tickers as
 * served. Mock mode: the S&P 500 constituents plus the contract's mock tickers
 * (TEVA is not in the S&P 500), so the list has real companies even though
 * only the mock tickers have predictions.
 */
export async function getUniverse(): Promise<TickerInfo[]> {
  if (!useMocks()) {
    const { tickers } = await fetchJson<TickersResponse>("/tickers");
    return tickers;
  }
  const mock = ((await readMock("mock_tickers.json")) as TickersResponse).tickers;
  const byTicker = new Map<string, TickerInfo>(
    SP500.map(([ticker, name, sector]) => [ticker, { ticker, name, sector }]),
  );
  for (const t of mock) {
    byTicker.set(t.ticker, { ...byTicker.get(t.ticker), ...t });
  }
  return [...byTicker.values()].sort((a, b) => a.ticker.localeCompare(b.ticker));
}

/**
 * GET /overview (contract v2): the watchlist's numbers for every ticker in one
 * request. Mock mode reads mock_overview.json (only the mock tickers appear);
 * an engine without the endpoint gives "unavailable" and the watchlist falls
 * back to per-ticker requests.
 */
export async function getOverview(): Promise<Optional<OverviewResponse>> {
  if (!useMocks()) {
    const result = await fetchOptional<OverviewResponse>("/overview");
    // Anything that is not shaped like an overview is treated as missing.
    return result.state === "available" && !Array.isArray(result.data?.entries)
      ? { state: "unavailable" }
      : result;
  }
  const data = (await readMock("mock_overview.json")) as OverviewResponse;
  return { state: "available", data, sample: true };
}

/** GET /tickers */
export async function getTickers(): Promise<TickersResponse> {
  if (useMocks()) return (await readMock("mock_tickers.json")) as TickersResponse;
  return fetchJson<TickersResponse>("/tickers");
}

/** GET /predict?ticker=XXX. Throws NotFoundError for an unknown ticker. */
export async function getPrediction(ticker: string): Promise<Prediction> {
  const symbol = normalizeTicker(ticker);
  if (useMocks()) return readMockForTicker<Prediction>("mock_prediction.json", symbol);
  return fetchJson<Prediction>(`/predict?ticker=${encodeURIComponent(symbol)}`, symbol);
}

/** GET /history?ticker=XXX. Throws NotFoundError for an unknown ticker. */
export async function getHistory(ticker: string): Promise<HistoryResponse> {
  const symbol = normalizeTicker(ticker);
  if (useMocks()) return readMockForTicker<HistoryResponse>("mock_history.json", symbol);
  return fetchJson<HistoryResponse>(`/history?ticker=${encodeURIComponent(symbol)}`, symbol);
}
