/**
 * Browser-side helper: the one place a Client Component asks our own
 * /api/quotes route for fresh prices. It never talks to the market data
 * source directly, and any failure means "no quotes", never an error.
 */
import type { QuoteSummary } from "./market.ts";

export type QuoteMap = Record<string, QuoteSummary>;

export interface QuotesResult {
  enabled: boolean;
  quotes: QuoteMap;
}

/** Seconds between automatic refreshes of the prices on screen. */
export const QUOTE_REFRESH_SECONDS = 60;

export async function fetchQuotes(tickers: readonly string[], signal?: AbortSignal): Promise<QuotesResult> {
  if (tickers.length === 0) return { enabled: true, quotes: {} };
  try {
    const url = `/api/quotes?tickers=${encodeURIComponent(tickers.join(","))}`;
    const response = await fetch(url, signal ? { signal, cache: "no-store" } : { cache: "no-store" });
    if (!response.ok) return { enabled: true, quotes: {} };
    const body = (await response.json()) as Partial<QuotesResult>;
    return { enabled: body.enabled === true, quotes: body.quotes ?? {} };
  } catch {
    return { enabled: true, quotes: {} };
  }
}
