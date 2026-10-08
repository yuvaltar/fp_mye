/**
 * Hand-written mirror of contracts/prediction.schema.json.
 * When the contract changes, this file changes in the same PR.
 */

/** Mirrors $defs/Ticker: upper-case Yahoo Finance symbol, e.g. "AAPL". */
export type Ticker = string;

/**
 * Mirrors $defs/Volatility: annualized 5-trading-day realized volatility as a
 * decimal (0.24 means 24%). Convert to a percentage only in lib/format.ts.
 */
export type Volatility = number;

/** Mirrors $defs/SkillPrediction.horizon. */
export type SkillHorizon = "short" | "medium" | "long";

/** Mirrors $defs/SkillPrediction. */
export interface SkillPrediction {
  /** snake_case identifier, e.g. "short_trend". */
  name: string;
  horizon: SkillHorizon;
  /** 0..1; the weights of one prediction sum to 1. */
  weight: number;
  predicted_vol: Volatility;
}

/** Mirrors $defs/Prediction (response of GET /predict). */
export interface Prediction {
  ticker: Ticker;
  /** YYYY-MM-DD, last trading day whose close was used. */
  as_of_date: string;
  horizon_days: 5;
  predicted_vol: Volatility;
  baseline_vol: Volatility;
  skills: SkillPrediction[];
  /** 0 (none) to 1 (full). */
  supervisor_confidence: number;
  model_version: string;
}

/** Mirrors $defs/TickersResponse.tickers[] items. */
export interface TickerInfo {
  ticker: Ticker;
  name: string;
}

/** Mirrors $defs/TickersResponse (response of GET /tickers). */
export interface TickersResponse {
  tickers: TickerInfo[];
}

/** Mirrors $defs/HistoryPoint. */
export interface HistoryPoint {
  as_of_date: string;
  predicted_vol: Volatility;
  baseline_vol: Volatility;
  /** null until the 5 trading days after as_of_date have all passed. */
  realized_vol: Volatility | null;
}

/** Mirrors $defs/HistoryResponse (response of GET /history). Oldest point first. */
export interface HistoryResponse {
  ticker: Ticker;
  horizon_days: 5;
  points: HistoryPoint[];
}

/** Mirrors $defs/Error (body of a non-200 response). */
export interface ApiErrorBody {
  detail: string;
}
