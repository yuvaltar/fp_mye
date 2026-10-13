/**
 * Types for data that is NOT part of the engine contract: prices and the
 * market snapshot come from the website's own market data source (see
 * lib/api/market.ts), and Optional wraps any section that may be missing.
 */
import type { Ticker } from "./types.ts";

/** One daily closing price. */
export interface PricePoint {
  /** YYYY-MM-DD */
  date: string;
  /** Closing price in the listing currency. */
  close: number;
}

/**
 * Real market snapshot, available only when the price comes from a market
 * data source. Delayed by up to about 15 minutes.
 */
export interface MarketQuote {
  price: number;
  /** ISO timestamp (UTC) of the latest price. */
  time: string;
  /** Close of the trading day before the latest bar; null when unknown. */
  previous_close: number | null;
  day_high: number | null;
  day_low: number | null;
  volume: number | null;
  week52_high: number | null;
  week52_low: number | null;
  exchange: string | null;
  /** Company name as reported by the source. */
  name: string | null;
}

/** Daily closes of one ticker. Points are oldest first. */
export interface PricesResponse {
  ticker: Ticker;
  currency: string;
  last_close: number;
  last_close_date: string;
  points: PricePoint[];
  /** Only present when the data comes from the market data source. */
  quote?: MarketQuote;
}

/**
 * Result of an optional section. "sample" is true when the data is generated
 * or mock example data rather than real output.
 */
export type Optional<T> =
  | {
      state: "available";
      data: T;
      sample: boolean;
      /** Where real data came from, when it is not the engine. */
      source?: "market";
    }
  | { state: "unavailable" };
