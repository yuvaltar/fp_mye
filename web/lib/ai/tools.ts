/**
 * The assistant's tools, defined once. The same list is exposed to Gemini (as
 * function declarations) and to any MCP client (as MCP tools). Every tool reads
 * the site's own data through the typed client, returns compact JSON with its
 * date and source, and never gives advice: the numbers are facts for the model
 * to explain. Server-only (it reads the engine and mock files).
 */
import {
  NotFoundError,
  NotReadyError,
  getHistory,
  getPerformance,
  getPrediction,
  getPrices,
  getUniverse,
  getWeightsHistory,
  normalizeTicker,
} from "../api/client.ts";
import type { Prediction, TickerInfo } from "../api/types.ts";
import {
  accuracyStats,
  baselineSentence,
  getTrend,
  horizonLabel,
  latestRealizedVol,
  performanceSentence,
  priceChange,
  realizedVolFromCloses,
  relativeDifference,
  skillDescription,
  skillLabel,
  skillSpread,
  skillsSentence,
  sliceByDays,
  sortSkillsByWeight,
  volLevel,
  volPercentile,
  VOL_CALM_BELOW,
  VOL_CRISIS_ABOVE,
  VOL_STORMY_ABOVE,
  VOL_TYPICAL,
} from "../derive.ts";
import { formatDate, formatShare, formatVol } from "../format.ts";
import { loadWatchlist } from "../watchlist.ts";

/** Minimal JSON Schema, enough for tool inputs. */
export interface JsonSchema {
  type: "object" | "string" | "number" | "integer" | "boolean" | "array";
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
}

export type ToolResult =
  | { ok: true; data: unknown }
  | { ok: false; error: string; message: string };

export interface ToolDef {
  name: string;
  description: string;
  inputSchema: JsonSchema & { type: "object" };
  run(args: Record<string, unknown>): Promise<ToolResult>;
}

const TICKER_PATTERN = /^[A-Z][A-Z0-9.-]{0,9}$/;
export const MAX_COMPARE = 4;
export const MAX_LIST = 15;

const fail = (error: string, message: string): ToolResult => ({ ok: false, error, message });
const ok = (data: unknown): ToolResult => ({ ok: true, data });

function readTicker(args: Record<string, unknown>, key = "ticker"): string | ToolResult {
  const raw = args[key];
  if (typeof raw !== "string") return fail("invalid_argument", `"${key}" must be a ticker symbol such as AAPL.`);
  const ticker = normalizeTicker(raw);
  if (!TICKER_PATTERN.test(ticker)) return fail("invalid_argument", `"${raw}" is not a valid ticker symbol.`);
  return ticker;
}

const pct = (value: number | null | undefined) => (value === null || value === undefined ? null : formatVol(value));

/** Maps an engine error to a tool result the model can explain. */
function describeError(error: unknown, ticker?: string): ToolResult {
  if (error instanceof NotFoundError) {
    return fail("not_covered", `The engine has no prediction for ${ticker ?? "this ticker"}. It may be unknown or not covered yet.`);
  }
  if (error instanceof NotReadyError) {
    return fail("engine_not_ready", "The prediction engine has not produced its results yet.");
  }
  return fail("unavailable", "The data is temporarily unavailable.");
}

// ---------------------------------------------------------------------------
// The risk brief: everything the site knows about one stock, as facts
// ---------------------------------------------------------------------------

export interface RiskBrief {
  ticker: string;
  company: string | null;
  sector: string | null;
  as_of_date: string;
  as_of_note: string;
  model_version: string;
  expected_volatility: { value: number; display: string };
  baseline_volatility: { value: number; display: string };
  difference_vs_baseline: string | null;
  difference_vs_baseline_points: string | null;
  level: { name: string; scale: string };
  trend: { name: string; meaning: string };
  latest_realized_volatility: string | null;
  percentile_vs_past_realized: string | null;
  supervisor_recent_accuracy: { value: number; display: string; note: string };
  earnings_date: string | null;
  earnings_note: string | null;
  skills: {
    name: string;
    label: string;
    horizon: string;
    description: string | null;
    weight: string;
    predicted: string;
    vs_baseline: string | null;
    vs_baseline_points: string | null;
  }[];
  skills_summary: string | null;
  skill_agreement: string | null;
  baseline_summary: string | null;
  track_record: {
    scored_dates: number;
    market_mean_abs_error: string;
    baseline_mean_abs_error: string;
    market_closer_share: string;
    error_reduction_vs_baseline: string | null;
  } | null;
  caveats: string[];
}

const LEVEL_SCALE = `calm below ${formatVol(VOL_CALM_BELOW)}, typical around ${formatVol(VOL_TYPICAL)}, stormy above ${formatVol(VOL_STORMY_ABOVE)}, crisis above ${formatVol(VOL_CRISIS_ABOVE)} (from the project's own data)`;

const TREND_MEANING: Record<string, string> = {
  rising: "The prediction is more than 10% above the latest realized volatility.",
  falling: "The prediction is more than 10% below the latest realized volatility.",
  stable: "The prediction is within 10% of the latest realized volatility.",
  "no-data": "There is no realized volatility to compare with.",
};

function universeEntry(universe: TickerInfo[], ticker: string): TickerInfo | undefined {
  return universe.find((entry) => entry.ticker === ticker);
}

/** "+2.7 pts": the gap between two volatilities in percentage points, so the model never has to subtract. */
function signedPoints(value: number, reference: number): string | null {
  if (!Number.isFinite(value) || !Number.isFinite(reference)) return null;
  const points = (value - reference) * 100;
  const text = Math.abs(points).toFixed(1);
  return `${points >= 0 && Number(text) !== 0 ? "+" : points < 0 && Number(text) !== 0 ? "-" : ""}${text} pts`;
}

function signedRelative(value: number, reference: number): string | null {
  const diff = relativeDifference(value, reference);
  if (diff === null) return null;
  const text = (Math.abs(diff) * 100).toFixed(1);
  return `${diff >= 0 ? "+" : "-"}${text}%`;
}

export async function buildRiskBrief(ticker: string): Promise<RiskBrief> {
  const [prediction, history, universe] = await Promise.all([
    getPrediction(ticker),
    getHistory(ticker).catch(() => null),
    getUniverse().catch(() => [] as TickerInfo[]),
  ]);
  return briefFrom(prediction, history?.points ?? null, universeEntry(universe, prediction.ticker));
}

export function briefFrom(
  p: Prediction,
  points: readonly import("../api/types.ts").HistoryPoint[] | null,
  listed: TickerInfo | undefined,
): RiskBrief {
  const trend = points ? getTrend(p.predicted_vol, points) : "no-data";
  const latest = points ? latestRealizedVol(points) : null;
  const percentile = points ? volPercentile(p.predicted_vol, points) : null;
  const accuracy = points ? accuracyStats(points) : null;
  const spread = skillSpread(p.skills);
  const ordered = sortSkillsByWeight(p.skills);
  const earnings = p.earnings_date ?? null;

  return {
    ticker: p.ticker,
    company: listed?.name ?? null,
    sector: listed?.sector ?? null,
    as_of_date: p.as_of_date,
    as_of_note: `The engine's latest run, using prices up to the close of ${formatDate(p.as_of_date)}. It covers the next ${p.horizon_days} trading days after that date and can be days old.`,
    model_version: p.model_version,
    expected_volatility: { value: p.predicted_vol, display: formatVol(p.predicted_vol) },
    baseline_volatility: { value: p.baseline_vol, display: formatVol(p.baseline_vol) },
    difference_vs_baseline: signedRelative(p.predicted_vol, p.baseline_vol),
    difference_vs_baseline_points: signedPoints(p.predicted_vol, p.baseline_vol),
    level: { name: volLevel(p.predicted_vol), scale: LEVEL_SCALE },
    trend: { name: trend, meaning: TREND_MEANING[trend] ?? "" },
    latest_realized_volatility: pct(latest),
    percentile_vs_past_realized: percentile === null ? null : `higher than ${formatShare(percentile)} of past realized volatilities`,
    supervisor_recent_accuracy: {
      value: p.supervisor_confidence,
      display: formatShare(p.supervisor_confidence),
      note: "A 0 to 100% score of how well the supervisor itself predicted lately. It is not a probability.",
    },
    earnings_date: earnings,
    earnings_note: earnings
      ? `The company reports quarterly earnings on ${formatDate(earnings)}, inside the 5 trading days covered. The engine raises its forecast in such weeks according to how much the stock moved after earlier reports. If the report comes after the close, the stock reacts the next trading day.`
      : null,
    skills: ordered.map((skill) => ({
      name: skill.name,
      label: skillLabel(skill.name),
      horizon: horizonLabel(skill.horizon),
      description: skillDescription(skill.name),
      weight: formatShare(skill.weight),
      predicted: formatVol(skill.predicted_vol),
      vs_baseline: signedRelative(skill.predicted_vol, p.baseline_vol),
      vs_baseline_points: signedPoints(skill.predicted_vol, p.baseline_vol),
    })),
    skills_summary: skillsSentence(p.skills, p.baseline_vol),
    skill_agreement: spread
      ? `Skill predictions range from ${formatVol(spread.minSkill.predicted_vol)} (${skillLabel(spread.minSkill.name)}) to ${formatVol(spread.maxSkill.predicted_vol)} (${skillLabel(spread.maxSkill.name)}), a spread of ${formatVol(spread.range)}. A wide spread means the skills disagree.`
      : null,
    baseline_summary: baselineSentence(p.predicted_vol, p.baseline_vol),
    track_record: accuracy
      ? {
          scored_dates: accuracy.scored,
          market_mean_abs_error: formatVol(accuracy.marketMae),
          baseline_mean_abs_error: formatVol(accuracy.baselineMae),
          market_closer_share: formatShare(accuracy.winRate),
          error_reduction_vs_baseline:
            accuracy.maeImprovement === null ? null : `${(accuracy.maeImprovement * 100).toFixed(1)}%`,
        }
      : null,
    caveats: [
      "Volatility is the size of price moves, not their direction.",
      "The engine is a statistical model and can be wrong on any single stock and week.",
      "Past accuracy does not guarantee future accuracy.",
    ],
  };
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

const searchTickers: ToolDef = {
  name: "search_tickers",
  description:
    "Find stocks on the site by ticker, company name or sector. Use it when the user names a company and you need its ticker, or to list a sector.",
  inputSchema: {
    type: "object",
    properties: { query: { type: "string", description: "Part of a ticker, company name or sector." } },
    required: ["query"],
  },
  async run(args) {
    const query = typeof args.query === "string" ? args.query.trim().toLowerCase() : "";
    if (query.length < 1) return fail("invalid_argument", '"query" must not be empty.');
    try {
      const universe = await getUniverse();
      const matches = universe
        .filter(
          (e) =>
            e.ticker.toLowerCase().includes(query) ||
            e.name.toLowerCase().includes(query) ||
            (e.sector ?? "").toLowerCase().includes(query),
        )
        .slice(0, MAX_LIST)
        .map((e) => ({ ticker: e.ticker, company: e.name, sector: e.sector ?? null }));
      return ok({ matches, note: "These are stocks listed on the site; not all have a prediction." });
    } catch (error) {
      return describeError(error);
    }
  },
};

const getRiskBrief: ToolDef = {
  name: "get_risk_brief",
  description:
    "Everything the site knows about one stock as facts: expected volatility for the next 5 trading days, the baseline, the level, the trend, earnings, each model's view and weight, and the engine's track record on it. Use it for any question about one stock.",
  inputSchema: {
    type: "object",
    properties: { ticker: { type: "string", description: "Ticker symbol, for example AAPL." } },
    required: ["ticker"],
  },
  async run(args) {
    const ticker = readTicker(args);
    if (typeof ticker !== "string") return ticker;
    try {
      return ok(await buildRiskBrief(ticker));
    } catch (error) {
      return describeError(error, ticker);
    }
  },
};

const compareTickers: ToolDef = {
  name: "compare_tickers",
  description: `Compare the expected volatility of 2 to ${MAX_COMPARE} stocks side by side.`,
  inputSchema: {
    type: "object",
    properties: {
      tickers: {
        type: "array",
        items: { type: "string" },
        minItems: 2,
        maxItems: MAX_COMPARE,
        description: "Ticker symbols to compare.",
      },
    },
    required: ["tickers"],
  },
  async run(args) {
    const raw = args.tickers;
    if (!Array.isArray(raw) || raw.length < 2 || raw.length > MAX_COMPARE) {
      return fail("invalid_argument", `"tickers" must list between 2 and ${MAX_COMPARE} ticker symbols.`);
    }
    const tickers: string[] = [];
    for (const item of raw) {
      const ticker = readTicker({ ticker: item });
      if (typeof ticker !== "string") return ticker;
      if (!tickers.includes(ticker)) tickers.push(ticker);
    }
    const results = await Promise.all(
      tickers.map(async (ticker) => {
        try {
          const brief = await buildRiskBrief(ticker);
          return {
            ticker,
            company: brief.company,
            expected_volatility: brief.expected_volatility.display,
            baseline_volatility: brief.baseline_volatility.display,
            difference_vs_baseline: brief.difference_vs_baseline,
            difference_vs_baseline_points: brief.difference_vs_baseline_points,
            level: brief.level.name,
            trend: brief.trend.name,
            earnings_date: brief.earnings_date,
            supervisor_recent_accuracy: brief.supervisor_recent_accuracy.display,
            as_of_date: brief.as_of_date,
          };
        } catch (error) {
          const result = describeError(error, ticker);
          return { ticker, error: result.ok ? "unavailable" : result.error };
        }
      }),
    );
    return ok({ comparison: results, note: "Volatility is the size of moves, not their direction." });
  },
};

const rankStocks: ToolDef = {
  name: "rank_stocks",
  description:
    "List stocks ordered by expected volatility, by how far the prediction is above or below the baseline, or the ones with an earnings report in the week. Use it for questions like 'which stocks are most volatile' or 'who reports earnings this week'.",
  inputSchema: {
    type: "object",
    properties: {
      sort_by: {
        type: "string",
        enum: ["expected_volatility", "vs_baseline", "earnings_this_week"],
        description: "How to order or filter the list.",
      },
      sector: { type: "string", description: "Optional sector to restrict the list to." },
      limit: { type: "integer", minimum: 1, maximum: MAX_LIST, description: `How many rows (default 10, at most ${MAX_LIST}).` },
    },
    required: ["sort_by"],
  },
  async run(args) {
    const sortBy = args.sort_by;
    if (sortBy !== "expected_volatility" && sortBy !== "vs_baseline" && sortBy !== "earnings_this_week") {
      return fail("invalid_argument", '"sort_by" must be expected_volatility, vs_baseline or earnings_this_week.');
    }
    const limit = Math.min(MAX_LIST, Math.max(1, Number.isInteger(args.limit) ? (args.limit as number) : 10));
    const sector = typeof args.sector === "string" && args.sector.trim() !== "" ? args.sector.trim().toLowerCase() : null;
    try {
      const { rows } = await loadWatchlist();
      let items = rows.flatMap((row) => (row.status === "ok" ? [row] : []));
      if (sector) items = items.filter((row) => (row.sector ?? "").toLowerCase() === sector);
      if (sortBy === "earnings_this_week") items = items.filter((row) => row.earningsDate !== null);
      const keyed = items.map((row) => ({
        row,
        key:
          sortBy === "vs_baseline"
            ? Math.abs(relativeDifference(row.predictedVol, row.baselineVol) ?? 0)
            : row.predictedVol,
      }));
      keyed.sort((a, b) => b.key - a.key);
      const out = keyed.slice(0, limit).map(({ row }) => ({
        ticker: row.ticker,
        company: row.name,
        sector: row.sector ?? null,
        expected_volatility: formatVol(row.predictedVol),
        baseline_volatility: formatVol(row.baselineVol),
        difference_vs_baseline: signedRelative(row.predictedVol, row.baselineVol),
        difference_vs_baseline_points: signedPoints(row.predictedVol, row.baselineVol),
        trend: row.trend,
        earnings_date: row.earningsDate,
        as_of_date: row.asOfDate,
      }));
      return ok({
        rows: out,
        returned: out.length,
        matching_stocks: items.length,
        note: "Ordered by size, not by whether a stock is a good or bad investment.",
      });
    } catch (error) {
      return describeError(error);
    }
  },
};

const getMarketSnapshot: ToolDef = {
  name: "get_market_snapshot",
  description:
    "Real market numbers for one stock from Yahoo Finance (delayed): price, change, day and 52-week range, and the volatility that actually occurred over the last 5 and 21 days, computed from real closes. Say when it is sample data.",
  inputSchema: {
    type: "object",
    properties: { ticker: { type: "string", description: "Ticker symbol, for example AAPL." } },
    required: ["ticker"],
  },
  async run(args) {
    const ticker = readTicker(args);
    if (typeof ticker !== "string") return ticker;
    try {
      const prices = await getPrices(ticker);
      if (prices.state !== "available") {
        return ok({ available: false, note: "Market data is not available for this stock right now." });
      }
      const { data } = prices;
      const closes = data.points.map((point) => point.close);
      const month = sliceByDays(data.points, 31, (point) => point.date);
      const change = priceChange(month);
      return ok({
        available: true,
        is_sample_data: prices.sample,
        source: prices.source === "market" ? "Yahoo Finance, delayed by up to about 15 minutes" : "generated sample data, not real prices",
        ticker: data.ticker,
        currency: data.currency,
        last_price: data.last_close,
        last_close_date: data.last_close_date,
        previous_close: data.quote?.previous_close ?? null,
        day_range: data.quote ? [data.quote.day_low, data.quote.day_high] : null,
        week52_range: data.quote ? [data.quote.week52_low, data.quote.week52_high] : null,
        change_over_last_month: change ? `${(change.relative * 100).toFixed(1)}%` : null,
        realized_volatility_last_5_days: pct(realizedVolFromCloses(closes, 5)),
        realized_volatility_last_21_days: pct(realizedVolFromCloses(closes, 21)),
        note: "Realized volatility here is computed by the site from the closes; it is not an engine result.",
      });
    } catch (error) {
      return describeError(error, ticker);
    }
  },
};

const getWeightsSummary: ToolDef = {
  name: "get_weights_summary",
  description:
    "How the supervisor's trust in each model for one stock compares today with its recent average, to explain which models are driving the prediction.",
  inputSchema: {
    type: "object",
    properties: { ticker: { type: "string", description: "Ticker symbol, for example AAPL." } },
    required: ["ticker"],
  },
  async run(args) {
    const ticker = readTicker(args);
    if (typeof ticker !== "string") return ticker;
    try {
      const result = await getWeightsHistory(ticker);
      if (result.state !== "available" || result.data.points.length === 0) {
        return ok({ available: false, note: "Weight history is not available for this stock." });
      }
      const recent = result.data.points.slice(-60);
      const last = recent[recent.length - 1];
      const models = result.data.skills.map((skill) => {
        const values = recent.map((point) => point.weights.find((w) => w.name === skill.name)?.weight ?? 0);
        const now = last?.weights.find((w) => w.name === skill.name)?.weight ?? 0;
        const average = values.reduce((sum, v) => sum + v, 0) / Math.max(1, values.length);
        return {
          name: skill.name,
          label: skillLabel(skill.name),
          weight_now: formatShare(now),
          average_last_60_days: formatShare(average),
        };
      });
      return ok({
        available: true,
        is_sample_data: result.sample,
        as_of_date: last?.as_of_date ?? null,
        models,
        note: "When weights are close to equal, the supervisor has no strong preference between models.",
      });
    } catch (error) {
      return describeError(error, ticker);
    }
  },
};

const getEngineAccuracy: ToolDef = {
  name: "get_engine_accuracy",
  description:
    "The engine's walk-forward backtest result: how the supervisor compares with the HAR-RV baseline and each model (QLIKE, RMSE, MAE), plus the honest caveats.",
  inputSchema: { type: "object", properties: {} },
  async run() {
    try {
      const result = await getPerformance();
      if (result.state !== "available") {
        return ok({ available: false, note: "The backtest summary is not available right now." });
      }
      const { data } = result;
      return ok({
        available: true,
        is_sample_data: result.sample,
        period: `${formatDate(data.period_start)} to ${formatDate(data.period_end)}`,
        tickers: data.tickers.length,
        scored_predictions: data.scored_predictions,
        headline: performanceSentence(data.headline),
        models: data.models.map((m) => ({
          name: m.name,
          kind: m.kind,
          qlike: m.qlike,
          qlike_vs_har_rv: m.qlike_vs_har_rv === null ? null : `${(m.qlike_vs_har_rv * 100).toFixed(1)}%`,
        })),
        how_to_read: "QLIKE is an error measure for volatility forecasts: lower is better and it punishes predicting too low more than too high.",
        caveats: [
          "A limited set of large US-listed stocks over one period that includes the 2020 crash.",
          "Survivorship bias flatters every model, the baselines included.",
          "Consecutive dates overlap, so the scored predictions are not independent.",
        ],
      });
    } catch (error) {
      return describeError(error);
    }
  },
};

export const TOOLS: readonly ToolDef[] = [
  searchTickers,
  getRiskBrief,
  compareTickers,
  rankStocks,
  getMarketSnapshot,
  getWeightsSummary,
  getEngineAccuracy,
];

export function findTool(name: string): ToolDef | undefined {
  return TOOLS.find((tool) => tool.name === name);
}

/** Runs a tool by name; unknown names and bad arguments are results, never exceptions. */
export async function runTool(name: string, args: unknown): Promise<ToolResult> {
  const tool = findTool(name);
  if (!tool) return fail("unknown_tool", `There is no tool called "${name}".`);
  const input = typeof args === "object" && args !== null && !Array.isArray(args) ? (args as Record<string, unknown>) : {};
  try {
    return await tool.run(input);
  } catch {
    return fail("unavailable", "The data is temporarily unavailable.");
  }
}

/** Compact JSON for a model or MCP client; bounded so a tool can never flood the context. */
export const MAX_RESULT_CHARS = 12_000;

export function serializeResult(result: ToolResult): string {
  const json = JSON.stringify(result.ok ? { ok: true, ...(wrap(result.data)) } : { ok: false, error: result.error, message: result.message });
  return json.length <= MAX_RESULT_CHARS ? json : `${json.slice(0, MAX_RESULT_CHARS)}…[truncated]`;
}

function wrap(data: unknown): Record<string, unknown> {
  return typeof data === "object" && data !== null && !Array.isArray(data)
    ? (data as Record<string, unknown>)
    : { data };
}
