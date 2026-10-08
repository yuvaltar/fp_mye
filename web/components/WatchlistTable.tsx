"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  filterBySector,
  filterRows,
  paginate,
  sectorsOf,
  sortRows,
  type SortDirection,
  type SortKey,
  type WatchlistRow,
} from "@/lib/watchlist-rows";
import { formatDate, formatShare, formatVol } from "@/lib/format";
import { Sparkline } from "./Sparkline";
import { StateMessage } from "./StateMessage";
import { TrendBadge } from "./TrendBadge";

const GRID = "md:grid-cols-[minmax(0,2fr)_6.5rem_1fr_1fr_1fr_7.5rem]";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "predicted", label: "Predicted vol" },
  { key: "baseline", label: "HAR-RV baseline" },
  { key: "confidence", label: "Confidence" },
  { key: "trend", label: "Trend" },
];

const controlClass =
  "rounded-md border border-border bg-surface px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

export function WatchlistTable({ rows }: { rows: WatchlistRow[] }) {
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("");
  const [onlyPredicted, setOnlyPredicted] = useState(false);
  // Rows with a prediction first; the rest follow in ticker order.
  const [sortKey, setSortKey] = useState<SortKey>("predicted");
  const [direction, setDirection] = useState<SortDirection>("desc");
  const [page, setPage] = useState(1);

  const sectors = useMemo(() => sectorsOf(rows), [rows]);
  const predictedCount = useMemo(() => rows.filter((r) => r.status === "ok").length, [rows]);

  const sorted = useMemo(() => {
    const filtered = filterBySector(filterRows(rows, query), sector).filter(
      (row) => !onlyPredicted || row.status === "ok",
    );
    return sortRows(filtered, sortKey, direction);
  }, [rows, query, sector, onlyPredicted, sortKey, direction]);

  const paged = paginate(sorted, page);

  if (rows.length === 0) {
    return (
      <StateMessage
        title="No tickers yet"
        description="The API returned an empty ticker list. Once tickers are available they will show up here."
      />
    );
  }

  /** Any change to the filters or sort goes back to the first page. */
  function change(apply: () => void) {
    apply();
    setPage(1);
  }

  function toggleSort(key: SortKey) {
    change(() => {
      if (key === sortKey) {
        setDirection(direction === "asc" ? "desc" : "asc");
      } else {
        setSortKey(key);
        setDirection(key === "ticker" ? "asc" : "desc");
      }
    });
  }

  const ariaSort = (key: SortKey) =>
    key === sortKey ? (direction === "asc" ? "ascending" : "descending") : "none";

  const hasPredictions = predictedCount > 0;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label className="block w-full sm:w-72">
          <span className="sr-only">Search tickers</span>
          <input
            type="search"
            value={query}
            onChange={(event) => change(() => setQuery(event.target.value))}
            placeholder="Search ticker or company"
            className={`w-full placeholder:text-muted ${controlClass}`}
          />
        </label>
        {sectors.length > 0 ? (
          <label className="flex items-center gap-2 text-xs text-muted">
            Sector
            <select
              value={sector}
              onChange={(event) => change(() => setSector(event.target.value))}
              className={`text-text ${controlClass}`}
            >
              <option value="">All sectors</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {hasPredictions && predictedCount < rows.length ? (
          <label className="flex items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={onlyPredicted}
              onChange={(event) => change(() => setOnlyPredicted(event.target.checked))}
              className="size-4 accent-[var(--color-accent)]"
            />
            Only with a prediction ({predictedCount})
          </label>
        ) : null}
        <div className="flex items-center gap-2 text-xs text-muted md:hidden">
          <label htmlFor="sort-select">Sort by</label>
          <select
            id="sort-select"
            value={sortKey}
            onChange={(event) =>
              change(() => {
                setSortKey(event.target.value as SortKey);
                setDirection(event.target.value === "ticker" ? "asc" : "desc");
              })
            }
            className={`text-text ${controlClass}`}
          >
            <option value="ticker">Ticker</option>
            {COLUMNS.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {paged.total === 0 ? (
        <StateMessage
          title="No matches"
          description="No ticker matches the current search and filters."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          <div
            className={`hidden gap-4 border-b border-border px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-muted md:grid ${GRID}`}
          >
            <SortHeader label="Ticker" sortKey="ticker" ariaSort={ariaSort("ticker")} onSort={toggleSort} align="left" />
            <span className="text-right">Last 20</span>
            {COLUMNS.map((c) => (
              <SortHeader key={c.key} label={c.label} sortKey={c.key} ariaSort={ariaSort(c.key)} onSort={toggleSort} align="right" />
            ))}
          </div>
          <ul className="divide-y divide-border">
            {paged.items.map((row) => (
              <li key={row.ticker}>
                <Link
                  href={`/stock/${encodeURIComponent(row.ticker)}`}
                  className={`grid grid-cols-2 items-center gap-x-4 gap-y-3 px-4 py-3 transition-colors hover:bg-surface-raised focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent ${GRID}`}
                >
                  <span className="col-span-2 flex min-w-0 items-baseline gap-3 md:col-span-1">
                    <span className="font-mono font-semibold">{row.ticker}</span>
                    <span className="truncate text-sm text-muted">{row.name}</span>
                  </span>
                  <RowBody row={row} />
                </Link>
              </li>
            ))}
          </ul>
          <TableFooter page={paged} onPage={setPage} rows={rows} />
        </div>
      )}
    </div>
  );
}

function RowBody({ row }: { row: WatchlistRow }) {
  if (row.status === "ok") {
    return (
      <>
        <span className="col-span-2 flex md:col-span-1 md:justify-end">
          {row.spark.length > 1 ? (
            <Sparkline values={row.spark} label={`Recent predicted volatility for ${row.ticker}`} />
          ) : null}
        </span>
        <Metric label="Predicted vol" value={formatVol(row.predictedVol)} strong />
        <Metric label="HAR-RV baseline" value={formatVol(row.baselineVol)} />
        <Metric label="Confidence" value={formatShare(row.confidence)} />
        <span className="flex flex-col items-start gap-0.5 md:items-end">
          <span className="text-xs text-muted md:hidden">Trend</span>
          <TrendBadge trend={row.trend} />
        </span>
      </>
    );
  }
  return (
    <span className="col-span-2 text-sm text-muted md:col-span-5 md:text-right">
      {row.status === "no-prediction" ? "No prediction yet" : "Prediction unavailable right now"}
    </span>
  );
}

function SortHeader({
  label,
  sortKey,
  ariaSort,
  onSort,
  align,
}: {
  label: string;
  sortKey: SortKey;
  ariaSort: "ascending" | "descending" | "none";
  onSort: (key: SortKey) => void;
  align: "left" | "right";
}) {
  const arrow = ariaSort === "ascending" ? "↑" : ariaSort === "descending" ? "↓" : "";
  return (
    <span aria-sort={ariaSort} className={align === "right" ? "text-right" : "text-left"}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="uppercase tracking-wide transition-colors hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {label}
        <span aria-hidden="true" className="ml-1 inline-block w-3">
          {arrow}
        </span>
      </button>
    </span>
  );
}

function Metric({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <span className="flex flex-col gap-0.5 md:items-end">
      <span className="text-xs text-muted md:hidden">{label}</span>
      <span className={`font-mono tabular-nums ${strong ? "text-base font-semibold" : "text-sm text-muted"}`}>
        {value}
      </span>
    </span>
  );
}

function TableFooter({
  page,
  onPage,
  rows,
}: {
  page: ReturnType<typeof paginate<WatchlistRow>>;
  onPage: (page: number) => void;
  rows: WatchlistRow[];
}) {
  const first = rows.find((row) => row.status === "ok");
  const asOf = first && first.status === "ok" ? first.asOfDate : null;
  const buttonClass =
    "rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors enabled:hover:border-accent enabled:hover:text-accent disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-xs text-muted">
      <p>
        Showing <span className="font-mono">{page.from}–{page.to}</span> of{" "}
        <span className="font-mono">{page.total}</span>. Volatility is the annualized realized volatility
        predicted for the next 5 trading days
        {asOf ? `, data as of ${formatDate(asOf)}` : ""}.
      </p>
      {page.pageCount > 1 ? (
        <nav aria-label="Pagination" className="flex items-center gap-2">
          <button type="button" className={buttonClass} disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>
            Previous
          </button>
          <span className="font-mono tabular-nums">
            {page.page} / {page.pageCount}
          </span>
          <button
            type="button"
            className={buttonClass}
            disabled={page.page >= page.pageCount}
            onClick={() => onPage(page.page + 1)}
          >
            Next
          </button>
        </nav>
      ) : null}
    </div>
  );
}
