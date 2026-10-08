/**
 * SAMPLE data for the proposed endpoints, used only in mock mode and always
 * shown with a "Sample data" label. Deterministic: the same input gives the
 * same output. Not engine output and not real prices.
 */
import type { Prediction } from "./types.ts";
import type {
  PerformanceResponse,
  PricesResponse,
  WeightsHistoryResponse,
} from "./proposed-types.ts";

/** Small seeded generator (mulberry32) so samples are stable between runs. */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashString(text: string): number {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function toIso(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** The last `count` weekdays up to and including `endIso`, oldest first. */
export function weekdaysEndingAt(endIso: string, count: number): string[] {
  const cursor = new Date(`${endIso}T00:00:00Z`);
  const days: string[] = [];
  while (days.length < count) {
    const day = cursor.getUTCDay();
    if (day !== 0 && day !== 6) days.unshift(toIso(cursor));
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  return days;
}

const START_PRICES: Record<string, number> = { AAPL: 225, TEVA: 18, NVDA: 140 };

/** Random-walk closing prices sized by the prediction's own volatility. */
export function samplePrices(prediction: Prediction, days = 90): PricesResponse {
  const random = seededRandom(hashString(`prices:${prediction.ticker}`));
  const dailyVol = prediction.predicted_vol / Math.sqrt(252);
  const dates = weekdaysEndingAt(prediction.as_of_date, days);
  let close = START_PRICES[prediction.ticker] ?? 100;
  const points = dates.map((date) => {
    // Sum of uniforms approximates a bell curve; good enough for a sample.
    const shock = (random() + random() + random() - 1.5) * 2;
    close = Math.max(1, close * (1 + shock * dailyVol));
    return { date, close: Math.round(close * 100) / 100 };
  });
  const last = points[points.length - 1];
  return {
    ticker: prediction.ticker,
    currency: "USD",
    last_close: last?.close ?? close,
    last_close_date: last?.date ?? prediction.as_of_date,
    points,
  };
}

/** Skill weights drifting around today's weights, always summing to 1. */
export function sampleWeightsHistory(
  prediction: Prediction,
  dates: readonly string[],
): WeightsHistoryResponse {
  const random = seededRandom(hashString(`weights:${prediction.ticker}`));
  const base = prediction.skills.map((skill) => skill.weight);
  let current = base.map((weight) => Math.max(0.05, weight + (random() - 0.5) * 0.3));
  const points = dates.map((date, index) => {
    const isLast = index === dates.length - 1;
    current = current.map((weight, i) =>
      Math.max(0.03, weight + (((base[i] ?? weight) - weight) * 0.15 + (random() - 0.5) * 0.08)),
    );
    const source = isLast ? base : current;
    const total = source.reduce((sum, weight) => sum + weight, 0);
    return {
      as_of_date: date,
      weights: prediction.skills.map((skill, i) => ({
        name: skill.name,
        weight: (source[i] ?? 0) / total,
      })),
    };
  });
  return {
    ticker: prediction.ticker,
    skills: prediction.skills.map(({ name, horizon }) => ({ name, horizon })),
    points,
  };
}

/** Example backtest summary. Numbers are illustrative, not measured. */
export function samplePerformance(): PerformanceResponse {
  return {
    generated_at: "2026-10-08",
    period_start: "2025-10-08",
    period_end: "2026-10-07",
    evaluation_dates: 250,
    tickers: ["AAPL", "TEVA", "NVDA"],
    models: [
      { name: "supervisor", kind: "supervisor", rmse: 0.0412, mae: 0.0301, qlike: 0.118 },
      { name: "short_trend", kind: "skill", rmse: 0.0455, mae: 0.0334, qlike: 0.131 },
      { name: "medium_trend", kind: "skill", rmse: 0.0468, mae: 0.0342, qlike: 0.136 },
      { name: "weak_signals", kind: "skill", rmse: 0.0489, mae: 0.0361, qlike: 0.142 },
      { name: "seasonality", kind: "skill", rmse: 0.0521, mae: 0.0389, qlike: 0.151 },
      { name: "equal_weight", kind: "baseline", rmse: 0.0436, mae: 0.0319, qlike: 0.126 },
      { name: "har_rv", kind: "baseline", rmse: 0.0449, mae: 0.0328, qlike: 0.129 },
      { name: "naive", kind: "baseline", rmse: 0.0503, mae: 0.0372, qlike: 0.147 },
    ],
    skill_weights: [
      { name: "short_trend", mean: 0.34, min: 0.12, max: 0.55 },
      { name: "medium_trend", mean: 0.27, min: 0.08, max: 0.44 },
      { name: "weak_signals", mean: 0.22, min: 0.05, max: 0.47 },
      { name: "seasonality", mean: 0.17, min: 0.04, max: 0.31 },
    ],
  };
}
