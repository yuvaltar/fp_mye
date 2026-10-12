/**
 * All derived values (trend badge, dominant skill, generated sentences).
 * Pure functions over contract data. Sentences use only fields that exist in
 * the response and never state a reason the data does not contain.
 * Imports are relative with .ts extensions so node:test can run this file.
 */
import type {
  ModelPerformance,
  PricePoint,
  WeightsPoint,
} from "./api/proposed-types.ts";
import type { HistoryPoint, SkillPrediction } from "./api/types.ts";
import { formatShare, formatVol } from "./format.ts";

/** Relative gap vs the latest realized volatility that counts as a trend. */
export const TREND_THRESHOLD = 0.1;

/** A skill "dominates" when its weight is at least this share. */
export const DOMINANT_WEIGHT_THRESHOLD = 0.35;

/** Relative gap vs the baseline below which a prediction counts as "in line". */
export const IN_LINE_THRESHOLD = 0.02;

/** Keeps a value exactly on a threshold from flipping because of rounding. */
const FLOAT_TOLERANCE = 1e-9;

export type Trend = "rising" | "stable" | "falling" | "no-data";

/** Most recent realized_vol that is not null, or null when there is none. */
export function latestRealizedVol(points: readonly HistoryPoint[]): number | null {
  for (let i = points.length - 1; i >= 0; i--) {
    const value = points[i]?.realized_vol;
    if (value !== null && value !== undefined) return value;
  }
  return null;
}

/**
 * Compares the prediction with the latest realized volatility.
 * Above +TREND_THRESHOLD = rising, below -TREND_THRESHOLD = falling,
 * otherwise stable. "no-data" when there is nothing to compare with.
 */
export function getTrend(predictedVol: number, points: readonly HistoryPoint[]): Trend {
  const latest = latestRealizedVol(points);
  if (latest === null || latest <= 0) return "no-data";
  const change = predictedVol / latest - 1;
  if (change > TREND_THRESHOLD + FLOAT_TOLERANCE) return "rising";
  if (change < -TREND_THRESHOLD - FLOAT_TOLERANCE) return "falling";
  return "stable";
}

/** Relative difference predicted vs baseline: 0.0617 means 6.2% above. */
export function relativeDifference(value: number, reference: number): number | null {
  if (!Number.isFinite(value) || !Number.isFinite(reference) || reference <= 0) {
    return null;
  }
  return value / reference - 1;
}

/**
 * Display names for skills. The engine's real members are short_term (HAR-RV),
 * regime (GARCH), weak_signals (Boosting) and multivariate (iTransformer); the
 * trend/seasonality names come from the contract mocks. Unknown names (for
 * example the coming iTransformer with a relationship map) fall back to
 * auto-formatting, so nothing here is a fixed list.
 */
const KNOWN_SKILL_LABELS: Record<string, string> = {
  short_term: "HAR-RV",
  regime: "GARCH",
  weak_signals: "Boosting",
  multivariate: "iTransformer",
  short_trend: "Short trend",
  medium_trend: "Medium trend",
  seasonality: "Seasonality",
};

/** One-line plain-language description of a known skill; null for unknown ones. */
const KNOWN_SKILL_INFO: Record<string, string> = {
  short_term: "A simple formula from yesterday's, this week's and this month's volatility.",
  regime: "A classic model: storms persist, then volatility drifts back to its average.",
  weak_signals: "Decision trees on trading volume, daily range and opening gaps.",
  multivariate: "A deep network that reads all the stocks together.",
};

export function skillDescription(name: string): string | null {
  return KNOWN_SKILL_INFO[name] ?? null;
}

/**
 * Stable color slot (0-5) per skill so a model keeps its color on every stock
 * and in every chart. Known skills have fixed slots; an unknown name gets one
 * of the two spare slots, deterministically from its name.
 */
const KNOWN_SKILL_COLOR: Record<string, number> = {
  short_term: 0,
  weak_signals: 1,
  regime: 2,
  multivariate: 3,
  short_trend: 0,
  medium_trend: 2,
  seasonality: 3,
};

export function skillColorIndex(name: string): number {
  const known = KNOWN_SKILL_COLOR[name];
  if (known !== undefined) return known;
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return 4 + (hash % 2);
}

/** Friendly label for a skill; unknown snake_case names are auto-formatted. */
export function skillLabel(name: string): string {
  const known = KNOWN_SKILL_LABELS[name];
  if (known) return known;
  const words = name.split("_").filter(Boolean).join(" ");
  if (!words) return name;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const HORIZON_LABELS: Record<SkillPrediction["horizon"], string> = {
  short: "Short horizon",
  medium: "Medium horizon",
  long: "Long horizon",
};

export function horizonLabel(horizon: SkillPrediction["horizon"]): string {
  return HORIZON_LABELS[horizon];
}

/** Skills ordered by weight, largest first (stable for equal weights). */
export function sortSkillsByWeight(skills: readonly SkillPrediction[]): SkillPrediction[] {
  return skills
    .map((skill, index) => ({ skill, index }))
    .sort((a, b) => b.skill.weight - a.skill.weight || a.index - b.index)
    .map(({ skill }) => skill);
}

/** The skill with the largest weight, or null when there are no skills. */
export function topSkill(skills: readonly SkillPrediction[]): SkillPrediction | null {
  return sortSkillsByWeight(skills)[0] ?? null;
}

/** True when the top skill's weight reaches DOMINANT_WEIGHT_THRESHOLD. */
export function hasDominantSkill(skills: readonly SkillPrediction[]): boolean {
  const top = topSkill(skills);
  return top !== null && top.weight >= DOMINANT_WEIGHT_THRESHOLD;
}

/**
 * One sentence on which skill carries the most weight, built only from the
 * response. Returns null when there are no skills to talk about.
 */
export function skillsSentence(
  skills: readonly SkillPrediction[],
  baselineVol: number,
): string | null {
  const top = topSkill(skills);
  if (top === null) return null;

  const label = skillLabel(top.name);
  const share = formatShare(top.weight);
  const predicted = formatVol(top.predicted_vol);
  const diff = relativeDifference(top.predicted_vol, baselineVol);

  let comparison = "";
  if (diff !== null) {
    const baseline = formatVol(baselineVol);
    if (Math.abs(diff) < IN_LINE_THRESHOLD) {
      comparison = `, in line with the HAR-RV baseline of ${baseline}`;
    } else {
      comparison = `, ${diff > 0 ? "above" : "below"} the HAR-RV baseline of ${baseline}`;
    }
  }

  if (hasDominantSkill(skills)) {
    return `${label} dominates with ${share} of the weight, predicting ${predicted}${comparison}.`;
  }
  return `No single skill dominates: the largest share is ${label} at ${share}, predicting ${predicted}${comparison}.`;
}

/** One sentence comparing the final prediction with the baseline. */
export function baselineSentence(predictedVol: number, baselineVol: number): string | null {
  const diff = relativeDifference(predictedVol, baselineVol);
  if (diff === null) return null;
  const baseline = formatVol(baselineVol);
  if (Math.abs(diff) < IN_LINE_THRESHOLD) {
    return `The market's prediction is in line with the HAR-RV baseline of ${baseline}.`;
  }
  const percent = formatVol(Math.abs(diff));
  return `The market's prediction is ${percent} ${diff > 0 ? "higher" : "lower"} than the HAR-RV baseline of ${baseline}.`;
}

// ---------------------------------------------------------------------------
// History: accuracy, context and range helpers (all from /history data)
// ---------------------------------------------------------------------------

/** Minimum scored points before accuracy or percentile claims are shown. */
export const MIN_SCORED_POINTS = 5;

export interface AccuracyStats {
  /** Points where realized_vol is known. */
  scored: number;
  marketMae: number;
  baselineMae: number;
  /** Points where the market was closer to realized than the baseline. */
  marketWins: number;
  /** marketWins / scored, 0..1. */
  winRate: number;
  /** 1 - marketMae / baselineMae: positive means the market has the lower error. */
  maeImprovement: number | null;
}

/** How the market and the HAR-RV baseline did against realized volatility. */
export function accuracyStats(points: readonly HistoryPoint[]): AccuracyStats | null {
  const scored = points.filter(
    (p): p is HistoryPoint & { realized_vol: number } => p.realized_vol !== null,
  );
  if (scored.length < MIN_SCORED_POINTS) return null;
  let marketError = 0;
  let baselineError = 0;
  let marketWins = 0;
  for (const p of scored) {
    const m = Math.abs(p.predicted_vol - p.realized_vol);
    const b = Math.abs(p.baseline_vol - p.realized_vol);
    marketError += m;
    baselineError += b;
    if (m < b - FLOAT_TOLERANCE) marketWins += 1;
  }
  const marketMae = marketError / scored.length;
  const baselineMae = baselineError / scored.length;
  return {
    scored: scored.length,
    marketMae,
    baselineMae,
    marketWins,
    winRate: marketWins / scored.length,
    maeImprovement: baselineMae > 0 ? 1 - marketMae / baselineMae : null,
  };
}

/**
 * Share (0..1) of past realized volatilities that are below `value`.
 * null when there is too little history to say anything.
 */
export function volPercentile(value: number, points: readonly HistoryPoint[]): number | null {
  const past = points
    .map((p) => p.realized_vol)
    .filter((v): v is number => v !== null);
  if (past.length < MIN_SCORED_POINTS) return null;
  const below = past.filter((v) => v < value).length;
  return below / past.length;
}

export interface SkillSpread {
  minSkill: SkillPrediction;
  maxSkill: SkillPrediction;
  /** max - min predicted vol across skills (decimal volatility). */
  range: number;
}

/** How far apart the skills' predictions are. null with fewer than two skills. */
export function skillSpread(skills: readonly SkillPrediction[]): SkillSpread | null {
  const first = skills[0];
  if (!first || skills.length < 2) return null;
  let min = first;
  let max = first;
  for (const skill of skills) {
    if (skill.predicted_vol < min.predicted_vol) min = skill;
    if (skill.predicted_vol > max.predicted_vol) max = skill;
  }
  return { minSkill: min, maxSkill: max, range: max.predicted_vol - min.predicted_vol };
}

/**
 * Volatility levels from the project's own data (10 large stocks since 2018):
 * a typical week is about 24%, a calm week is under 11%, a stormy week is over
 * 52% and crises exceed 100%. Decimals, like every volatility in the contract.
 */
export const VOL_CALM_BELOW = 0.11;
export const VOL_TYPICAL = 0.24;
export const VOL_STORMY_ABOVE = 0.52;
export const VOL_CRISIS_ABOVE = 1.0;

export type VolLevel = "calm" | "typical" | "stormy" | "crisis";

/** Where a prediction sits on that scale. */
export function volLevel(value: number): VolLevel {
  if (value < VOL_CALM_BELOW) return "calm";
  if (value > VOL_CRISIS_ABOVE) return "crisis";
  if (value > VOL_STORMY_ABOVE) return "stormy";
  return "typical";
}

const DAY_MS = 86_400_000;

function isoToDay(iso: string): number {
  return Math.floor(Date.parse(`${iso}T00:00:00Z`) / DAY_MS);
}

/**
 * Items from the last `days` calendar days before the latest item (inclusive),
 * judged by the date on each item; all of them when days is null. The range is
 * by date, not by number of points, so it stays right as the history grows.
 */
export function sliceByDays<T>(
  items: readonly T[],
  days: number | null,
  dateOf: (item: T) => string,
): T[] {
  const last = items[items.length - 1];
  if (days === null || last === undefined) return [...items];
  const cutoff = isoToDay(dateOf(last)) - days;
  return items.filter((item) => isoToDay(dateOf(item)) >= cutoff);
}

/**
 * One item per ISO week (the last of each week), so a multi-year history stays
 * light on the chart. Order is kept; the very last item is always included.
 */
export function downsampleWeekly<T>(items: readonly T[], dateOf: (item: T) => string): T[] {
  const result: T[] = [];
  let lastWeek = Number.NaN;
  for (const item of items) {
    // Weeks counted from a Monday (1970-01-05).
    const week = Math.floor((isoToDay(dateOf(item)) - 4) / 7);
    if (week === lastWeek) result[result.length - 1] = item;
    else result.push(item);
    lastWeek = week;
  }
  return result;
}

/** Last `count` items; the whole list when count is null or too large. */
export function lastN<T>(items: readonly T[], count: number | null): T[] {
  if (count === null || count >= items.length) return [...items];
  return items.slice(items.length - Math.max(0, count));
}

// ---------------------------------------------------------------------------
// Prices (proposed endpoint)
// ---------------------------------------------------------------------------

export interface PriceChange {
  absolute: number;
  /** Relative change, 0.012 = +1.2%. */
  relative: number;
}

/** Change between the first and last point. null with fewer than two points. */
export function priceChange(points: readonly PricePoint[]): PriceChange | null {
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last || points.length < 2 || first.close <= 0) return null;
  return { absolute: last.close - first.close, relative: last.close / first.close - 1 };
}

/**
 * Annualized realized volatility over the last `windowReturns` daily returns,
 * from closing prices (oldest first). Same definition as the contract:
 * sqrt(252 / n * sum of squared daily log returns), as a decimal. null when
 * there are not enough valid prices.
 */
export function realizedVolFromCloses(
  closes: readonly number[],
  windowReturns: number,
): number | null {
  if (windowReturns < 1 || closes.length < windowReturns + 1) return null;
  const recent = closes.slice(closes.length - windowReturns - 1);
  let sumSquares = 0;
  for (let i = 1; i < recent.length; i++) {
    const previous = recent[i - 1] as number;
    const current = recent[i] as number;
    if (!(previous > 0) || !(current > 0)) return null;
    sumSquares += Math.log(current / previous) ** 2;
  }
  return Math.sqrt((252 / windowReturns) * sumSquares);
}

// ---------------------------------------------------------------------------
// Skill weights over time (proposed endpoint)
// ---------------------------------------------------------------------------

/** One flat row per date ({ as_of_date, short_trend: 0.3, ... }) for stacked charts. */
export function weightsToRows(
  points: readonly WeightsPoint[],
): Record<string, number | string>[] {
  return points.map((point) => {
    const row: Record<string, number | string> = { as_of_date: point.as_of_date };
    for (const { name, weight } of point.weights) row[name] = weight;
    return row;
  });
}

// ---------------------------------------------------------------------------
// Performance (proposed endpoint)
// ---------------------------------------------------------------------------

export type MetricKey = "rmse" | "mae" | "qlike";

/** Names of the models with the lowest value for a metric (ties all included). */
export function bestModels(models: readonly ModelPerformance[], metric: MetricKey): string[] {
  if (models.length === 0) return [];
  const lowest = Math.min(...models.map((m) => m[metric]));
  return models.filter((m) => m[metric] === lowest).map((m) => m.name);
}

/** Improvement of a model vs a reference on a metric: 0.08 = 8% lower error. */
export function improvementVs(
  model: ModelPerformance,
  reference: ModelPerformance,
  metric: MetricKey,
): number | null {
  const ref = reference[metric];
  if (!Number.isFinite(ref) || ref <= 0) return null;
  return 1 - model[metric] / ref;
}

const MODEL_LABELS: Record<string, string> = {
  supervisor: "Supervisor (the market)",
  har_rv: "HAR-RV baseline",
  naive: "Naive (last realized)",
  equal_weight: "Equal-weight skills",
};

/** Label for a model row: baselines get fixed labels, skills use skillLabel. */
export function modelLabel(name: string): string {
  return MODEL_LABELS[name] ?? skillLabel(name);
}

// ---------------------------------------------------------------------------
// Sparkline geometry
// ---------------------------------------------------------------------------

/**
 * SVG path for a small line chart. Null values break the line. Returns "" when
 * there is nothing to draw. Padding keeps the stroke inside the box.
 */
export function sparklinePath(
  values: readonly (number | null)[],
  width: number,
  height: number,
  padding = 2,
): string {
  const defined = values.filter((v): v is number => v !== null);
  if (defined.length === 0) return "";
  const min = Math.min(...defined);
  const max = Math.max(...defined);
  const span = max - min || 1;
  const step = values.length > 1 ? (width - padding * 2) / (values.length - 1) : 0;
  let path = "";
  let drawing = false;
  values.forEach((value, index) => {
    if (value === null) {
      drawing = false;
      return;
    }
    const x = padding + index * step;
    const y = padding + (1 - (value - min) / span) * (height - padding * 2);
    path += `${drawing ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)} `;
    drawing = true;
  });
  return path.trim();
}
