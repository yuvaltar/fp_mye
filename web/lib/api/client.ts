/**
 * The only module that fetches data or reads mocks. Call it from Server
 * Components. Mock mode (NEXT_PUBLIC_USE_MOCKS=true) reads the files in
 * ../contracts at runtime; nothing is copied into web/.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { sampleWeightsHistory, samplePerformance, samplePrices } from "./fixtures.ts";
import type {
  OverviewEntry,
  OverviewResponse,
  Optional,
  PerformanceResponse,
  PricesResponse,
  UniverseEntry,
  WeightsHistoryResponse,
} from "./proposed-types.ts";
import { SP500 } from "./sp500.ts";
import type { HistoryResponse, Prediction, TickersResponse } from "./types.ts";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

/** The ticker is not known to the API (HTTP 404). */
export class NotFoundError extends Error {
  readonly ticker: string;
  constructor(ticker: string) {
    super(`Unknown ticker: ${ticker}`);
    this.name = "NotFoundError";
    this.ticker = ticker;
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

async function fetchJson<T>(pathAndQuery: string, ticker?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${pathAndQuery}`, { cache: "no-store" });
  } catch (cause) {
    throw new ApiError(
      `Could not reach the API: ${cause instanceof Error ? cause.message : String(cause)}`,
    );
  }
  if (response.status === 404 && ticker !== undefined) {
    throw new NotFoundError(ticker);
  }
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
    const response = await fetch(`${apiBaseUrl()}${pathAndQuery}`, { cache: "no-store" });
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
    const prediction = await readMockForTicker<Prediction>("mock_prediction.json", symbol);
    return { state: "available", data: samplePrices(prediction), sample: true };
  }
  return fetchOptional<PricesResponse>(`/prices?ticker=${encodeURIComponent(symbol)}`);
}

/** PROPOSED GET /weights?ticker=XXX: skill weights over time. */
export async function getWeightsHistory(
  ticker: string,
): Promise<Optional<WeightsHistoryResponse>> {
  const symbol = normalizeTicker(ticker);
  if (useMocks()) {
    const prediction = await readMockForTicker<Prediction>("mock_prediction.json", symbol);
    const history = await readMockForTicker<HistoryResponse>("mock_history.json", symbol);
    const dates = history.points.map((point) => point.as_of_date);
    return { state: "available", data: sampleWeightsHistory(prediction, dates), sample: true };
  }
  return fetchOptional<WeightsHistoryResponse>(`/weights?ticker=${encodeURIComponent(symbol)}`);
}

/** PROPOSED GET /performance: backtest summary. */
export async function getPerformance(): Promise<Optional<PerformanceResponse>> {
  if (useMocks()) {
    return { state: "available", data: samplePerformance(), sample: true };
  }
  return fetchOptional<PerformanceResponse>("/performance");
}

/**
 * The tickers to list. Live mode: GET /tickers as served (no sector yet).
 * Mock mode: the S&P 500 constituents plus the contract's mock tickers (TEVA
 * is not in the S&P 500), so the list has real companies even though only
 * the mock tickers have predictions.
 */
export async function getUniverse(): Promise<UniverseEntry[]> {
  if (!useMocks()) {
    const { tickers } = await fetchJson<TickersResponse>("/tickers");
    return tickers.map((t) => ({ ticker: t.ticker, name: t.name }));
  }
  const mock = ((await readMock("mock_tickers.json")) as TickersResponse).tickers;
  const byTicker = new Map<string, UniverseEntry>(
    SP500.map(([ticker, name, sector]) => [ticker, { ticker, name, sector }]),
  );
  for (const t of mock) {
    byTicker.set(t.ticker, { ...byTicker.get(t.ticker), ticker: t.ticker, name: t.name });
  }
  return [...byTicker.values()].sort((a, b) => a.ticker.localeCompare(b.ticker));
}

/**
 * PROPOSED GET /overview. Mock mode builds it from the mock prediction and
 * history files (so only the mock tickers appear) and is flagged as sample;
 * live mode returns "unavailable" until the engine offers the endpoint.
 */
export async function getOverview(): Promise<Optional<OverviewResponse>> {
  if (!useMocks()) return fetchOptional<OverviewResponse>("/overview");
  const predictions = (await readMock("mock_prediction.json")) as Prediction[];
  const histories = (await readMock("mock_history.json")) as HistoryResponse[];
  const entries: OverviewEntry[] = predictions.map((p) => {
    const points = histories.find((h) => h.ticker === p.ticker)?.points ?? [];
    let latest: number | null = null;
    for (const point of points) if (point.realized_vol !== null) latest = point.realized_vol;
    return {
      ticker: p.ticker,
      as_of_date: p.as_of_date,
      predicted_vol: p.predicted_vol,
      baseline_vol: p.baseline_vol,
      supervisor_confidence: p.supervisor_confidence,
      latest_realized_vol: latest,
    };
  });
  return { state: "available", data: { entries }, sample: true };
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
