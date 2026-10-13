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
  /** Mirrors $defs/EarningsDate; optional. See EarningsDate. */
  earnings_date?: EarningsDate;
}

/**
 * Mirrors $defs/EarningsDate: the quarterly earnings report date (YYYY-MM-DD)
 * when it falls in the 5 trading days the prediction covers, otherwise null.
 */
export type EarningsDate = string | null;

/** Mirrors $defs/TickersResponse.tickers[] items. */
export interface TickerInfo {
  ticker: Ticker;
  name: string;
  /** Optional GICS sector. */
  sector?: string;
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

/** Mirrors $defs/OverviewEntry. */
export interface OverviewEntry {
  ticker: Ticker;
  as_of_date: string;
  predicted_vol: Volatility;
  baseline_vol: Volatility;
  supervisor_confidence: number;
  /** Latest realized_vol that is not null in that ticker's /history, or null. */
  latest_realized_vol: Volatility | null;
  earnings_date?: EarningsDate;
}

/** Mirrors $defs/OverviewResponse (response of GET /overview). */
export interface OverviewResponse {
  entries: OverviewEntry[];
}

/** Mirrors $defs/SkillRef. */
export interface SkillRef {
  name: string;
  horizon: SkillHorizon;
}

/** Mirrors $defs/WeightsPoint.weights[] items. */
export interface SkillWeight {
  name: string;
  weight: number;
}

/** Mirrors $defs/WeightsPoint: all weights on one date (they sum to 1). */
export interface WeightsPoint {
  as_of_date: string;
  weights: SkillWeight[];
}

/** Mirrors $defs/WeightsHistoryResponse (response of GET /weights). Oldest point first. */
export interface WeightsHistoryResponse {
  ticker: Ticker;
  skills: SkillRef[];
  points: WeightsPoint[];
}

/** Mirrors $defs/ModelPerformance. The *_vs_har_rv fields are decimals, null on the baseline's own row. */
export interface ModelPerformance {
  name: string;
  kind: "supervisor" | "skill" | "baseline";
  rmse: number;
  mae: number;
  qlike: number;
  rmse_vs_har_rv: number | null;
  mae_vs_har_rv: number | null;
  qlike_vs_har_rv: number | null;
}

/** Mirrors $defs/PerformanceResponse.headline. */
export interface PerformanceHeadline {
  metric: "qlike";
  supervisor: number;
  baseline: number;
  /** 1 - supervisor / baseline, a decimal. */
  improvement: number;
  tickers_better: number;
  tickers_total: number;
  t_statistic: number;
}

/** Mirrors $defs/PerformanceResponse.skill_weights[] items. */
export interface SkillWeightSummary {
  name: string;
  horizon: SkillHorizon;
  mean: number;
  min: number;
  max: number;
}

/** Mirrors $defs/PerformanceResponse.per_ticker[] items. */
export interface TickerPerformance {
  ticker: Ticker;
  supervisor_qlike: number;
  baseline_qlike: number;
}

/** Mirrors $defs/PerformanceResponse (response of GET /performance). */
export interface PerformanceResponse {
  generated_at: string;
  model_version: string;
  period_start: string;
  period_end: string;
  evaluation_dates: number;
  scored_predictions: number;
  tickers: Ticker[];
  headline: PerformanceHeadline;
  models: ModelPerformance[];
  skill_weights: SkillWeightSummary[];
  per_ticker: TickerPerformance[];
}

/** Mirrors $defs/Error (body of a non-200 response). */
export interface ApiErrorBody {
  detail: string;
}
