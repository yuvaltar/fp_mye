/**
 * Builds the rows of the watchlist from the API client. Server-only (it uses
 * the client). Pure helpers live in watchlist-rows.ts.
 *
 * With GET /overview (contract v2) the whole list takes one request. Without
 * it (an older engine), small universes (up to FULL_FETCH_LIMIT tickers) fetch
 * prediction and history per ticker, which also gives sparklines; larger ones
 * load only the first FULL_FETCH_LIMIT and list the rest without a prediction.
 */
import {
  NotFoundError,
  NotReadyError,
  getHistory,
  getOverview,
  getPrediction,
  getUniverse,
} from "./api/client.ts";
import type { OverviewEntry, TickerInfo } from "./api/types.ts";
import { getTrend, lastN, type Trend } from "./derive.ts";
import { SPARKLINE_POINTS, type WatchlistRow } from "./watchlist-rows.ts";

/**
 * Without /overview, universes up to this size are fetched ticker by ticker.
 * The engine serves about 50 tickers, so the limit covers that; each history
 * response has about 2,200 points, which is why /overview exists.
 */
export const FULL_FETCH_LIMIT = 60;

export type WatchlistSource = "overview" | "per-ticker" | "partial";

export interface Watchlist {
  rows: WatchlistRow[];
  source: WatchlistSource;
}

function base(entry: TickerInfo) {
  return entry.sector === undefined
    ? { ticker: entry.ticker, name: entry.name }
    : { ticker: entry.ticker, name: entry.name, sector: entry.sector };
}

/** Trend from an overview entry (which carries the latest realized value). */
function overviewTrend(entry: OverviewEntry): Trend {
  return getTrend(
    entry.predicted_vol,
    entry.latest_realized_vol === null
      ? []
      : [
          {
            as_of_date: entry.as_of_date,
            predicted_vol: entry.predicted_vol,
            baseline_vol: entry.baseline_vol,
            realized_vol: entry.latest_realized_vol,
          },
        ],
  );
}

async function loadOne(entry: TickerInfo): Promise<WatchlistRow> {
  const [prediction, history] = await Promise.allSettled([
    getPrediction(entry.ticker),
    getHistory(entry.ticker),
  ]);
  if (prediction.status === "rejected") {
    return prediction.reason instanceof NotFoundError || prediction.reason instanceof NotReadyError
      ? { ...base(entry), status: "no-prediction" }
      : { ...base(entry), status: "unavailable" };
  }
  // Without history the badge says "no data" but the row still shows.
  const points = history.status === "fulfilled" ? history.value.points : [];
  const p = prediction.value;
  return {
    ...base(entry),
    status: "ok",
    predictedVol: p.predicted_vol,
    baselineVol: p.baseline_vol,
    confidence: p.supervisor_confidence,
    asOfDate: p.as_of_date,
    trend: getTrend(p.predicted_vol, points),
    earningsDate: p.earnings_date ?? null,
    spark: [...lastN(points, SPARKLINE_POINTS - 1).map((x) => x.predicted_vol), p.predicted_vol],
  };
}

export async function loadWatchlist(): Promise<Watchlist> {
  const universe = await getUniverse();

  const overview = await getOverview();
  if (overview.state === "available") {
    const byTicker = new Map(overview.data.entries.map((e) => [e.ticker, e]));
    const rows = universe.map((entry): WatchlistRow => {
      const found = byTicker.get(entry.ticker);
      if (!found) return { ...base(entry), status: "no-prediction" };
      return {
        ...base(entry),
        status: "ok",
        predictedVol: found.predicted_vol,
        baselineVol: found.baseline_vol,
        confidence: found.supervisor_confidence,
        asOfDate: found.as_of_date,
        trend: overviewTrend(found),
        earningsDate: found.earnings_date ?? null,
        spark: [],
      };
    });
    return { rows, source: "overview" };
  }

  if (universe.length <= FULL_FETCH_LIMIT) {
    return { rows: await Promise.all(universe.map(loadOne)), source: "per-ticker" };
  }

  // No overview and a big list: load the first tickers, list the rest as-is.
  const head = universe.slice(0, FULL_FETCH_LIMIT);
  const tail = universe.slice(FULL_FETCH_LIMIT);
  const loaded = await Promise.all(head.map(loadOne));
  const rest = tail.map((entry): WatchlistRow => ({ ...base(entry), status: "no-prediction" }));
  return { rows: [...loaded, ...rest], source: "partial" };
}
