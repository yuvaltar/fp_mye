/**
 * Watchlist row types and the pure sort, filter and paging helpers. No data
 * fetching here, so Client Components can import it (lib/watchlist.ts, which
 * loads the data, cannot be bundled for the browser).
 */
import type { Trend } from "./derive.ts";

/** Number of past predictions drawn in a row's sparkline. */
export const SPARKLINE_POINTS = 20;

/** Rows per page in the watchlist table. */
export const PAGE_SIZE = 50;

interface RowBase {
  ticker: string;
  name: string;
  sector?: string;
}

export type WatchlistRow =
  | (RowBase & {
      status: "ok";
      predictedVol: number;
      baselineVol: number;
      confidence: number;
      asOfDate: string;
      trend: Trend;
      /** Recent predicted volatilities, oldest first. Empty when not available. */
      spark: number[];
    })
  /** The ticker is listed but the engine has no prediction for it (yet). */
  | (RowBase & { status: "no-prediction" })
  /** The prediction request failed. */
  | (RowBase & { status: "unavailable" });

export type SortKey = "ticker" | "predicted" | "baseline" | "confidence" | "trend";
export type SortDirection = "asc" | "desc";

const TREND_ORDER: Record<Trend, number> = { rising: 3, stable: 2, falling: 1, "no-data": 0 };

function sortValue(row: WatchlistRow, key: SortKey): number | string | null {
  if (key === "ticker") return row.ticker;
  if (row.status !== "ok") return null;
  switch (key) {
    case "predicted":
      return row.predictedVol;
    case "baseline":
      return row.baselineVol;
    case "confidence":
      return row.confidence;
    case "trend":
      return TREND_ORDER[row.trend];
  }
}

/** Sorted copy. Rows without a value for the key always go last. */
export function sortRows(
  rows: readonly WatchlistRow[],
  key: SortKey,
  direction: SortDirection,
): WatchlistRow[] {
  const sign = direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const av = sortValue(a.row, key);
      const bv = sortValue(b.row, key);
      if (av === null && bv === null) return a.index - b.index;
      if (av === null) return 1;
      if (bv === null) return -1;
      const order =
        typeof av === "string" && typeof bv === "string"
          ? av.localeCompare(bv)
          : Number(av) - Number(bv);
      return order * sign || a.index - b.index;
    })
    .map(({ row }) => row);
}

/** Rows whose ticker or company name contains the query (case-insensitive). */
export function filterRows(rows: readonly WatchlistRow[], query: string): WatchlistRow[] {
  const q = query.trim().toLowerCase();
  if (q === "") return [...rows];
  return rows.filter(
    (row) => row.ticker.toLowerCase().includes(q) || row.name.toLowerCase().includes(q),
  );
}

/** Rows of one sector; null or empty keeps everything. */
export function filterBySector(rows: readonly WatchlistRow[], sector: string | null): WatchlistRow[] {
  if (sector === null || sector === "") return [...rows];
  return rows.filter((row) => row.sector === sector);
}

/** Distinct sectors present in the rows, alphabetically. */
export function sectorsOf(rows: readonly WatchlistRow[]): string[] {
  const sectors = new Set<string>();
  for (const row of rows) if (row.sector) sectors.add(row.sector);
  return [...sectors].sort((a, b) => a.localeCompare(b));
}

export interface Page<T> {
  items: T[];
  /** 1-based, clamped into 1..pageCount. */
  page: number;
  pageCount: number;
  /** 1-based index of the first and last item shown, 0 when empty. */
  from: number;
  to: number;
  total: number;
}

/** One page of a list. An out-of-range page is clamped, never empty by mistake. */
export function paginate<T>(items: readonly T[], page: number, pageSize = PAGE_SIZE): Page<T> {
  const total = items.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(pageCount, Math.max(1, Math.floor(page) || 1));
  const start = (safePage - 1) * pageSize;
  const slice = items.slice(start, start + pageSize);
  return {
    items: slice,
    page: safePage,
    pageCount,
    from: total === 0 ? 0 : start + 1,
    to: start + slice.length,
    total,
  };
}
