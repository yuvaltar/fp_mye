/**
 * SAMPLE prices, used only in mock mode when real market data is switched
 * off, always shown with a "Sample data" label. Deterministic: the same input
 * gives the same output. Not real prices. (Weights and performance examples
 * live in /contracts as mock files.)
 */
import type { Prediction } from "./types.ts";
import type { PricesResponse } from "./extras-types.ts";

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
