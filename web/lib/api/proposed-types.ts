/**
 * PROPOSED contract additions. NOT part of contracts/prediction.schema.json yet:
 * they become real only after the algo team agrees (see
 * docs/proposed-contract-additions.md). Until then the site shows clearly
 * labelled sample data in mock mode and hides the feature in live mode when
 * the API does not answer.
 */
import type { SkillHorizon, Ticker } from "./types.ts";

/** Proposed GET /prices?ticker=XXX item. */
export interface PricePoint {
  /** YYYY-MM-DD */
  date: string;
  /** Closing price in the listing currency. */
  close: number;
}

/** Proposed GET /prices?ticker=XXX. Points are oldest first. */
export interface PricesResponse {
  ticker: Ticker;
  currency: string;
  last_close: number;
  last_close_date: string;
  points: PricePoint[];
}

/** Proposed GET /weights?ticker=XXX: one skill's weight on one date. */
export interface SkillWeight {
  name: string;
  weight: number;
}

/** Proposed GET /weights?ticker=XXX item: all weights on one date (sum to 1). */
export interface WeightsPoint {
  as_of_date: string;
  weights: SkillWeight[];
}

/** Proposed GET /weights?ticker=XXX. Points are oldest first. */
export interface WeightsHistoryResponse {
  ticker: Ticker;
  skills: { name: string; horizon: SkillHorizon }[];
  points: WeightsPoint[];
}

/** Proposed GET /performance item: one model's backtest scores. */
export interface ModelPerformance {
  name: string;
  kind: "supervisor" | "skill" | "baseline";
  rmse: number;
  mae: number;
  qlike: number;
}

/** Proposed GET /performance: backtest summary. */
export interface PerformanceResponse {
  generated_at: string;
  period_start: string;
  period_end: string;
  evaluation_dates: number;
  tickers: Ticker[];
  models: ModelPerformance[];
  skill_weights: { name: string; mean: number; min: number; max: number }[];
}

/** Proposed: GET /tickers item with an optional GICS sector. */
export interface UniverseEntry {
  ticker: Ticker;
  name: string;
  sector?: string;
}

/**
 * Proposed GET /overview item: the few numbers the watchlist needs for one
 * ticker, so 500 tickers do not take 1000 requests.
 */
export interface OverviewEntry {
  ticker: Ticker;
  as_of_date: string;
  predicted_vol: number;
  baseline_vol: number;
  supervisor_confidence: number;
  /** Latest realized_vol that is not null (the trend badge compares with it). */
  latest_realized_vol: number | null;
}

/** Proposed GET /overview: one entry per ticker that has a prediction. */
export interface OverviewResponse {
  entries: OverviewEntry[];
}

/**
 * Result of an optional (proposed) endpoint. "sample" is true when the data is
 * generated example data rather than engine output.
 */
export type Optional<T> =
  | { state: "available"; data: T; sample: boolean }
  | { state: "unavailable" };
