"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HistoryPoint } from "@/lib/api/types";
import { AXIS_YEAR_THRESHOLD_DAYS, downsampleWeekly, sliceByDays, spanDays } from "@/lib/derive";
import { formatDate, formatDateShort, formatMonthYear, formatVol, historyToCsv } from "@/lib/format";
import { RangeSelector, type RangeOption } from "./RangeSelector";
import { StateMessage } from "./StateMessage";

interface HistoryChartProps {
  ticker: string;
  points: HistoryPoint[];
}

/** Realized is what actually happened, so it is the boldest line. */
const SERIES = [
  { key: "predicted_vol", label: "Supervisor prediction", line: "var(--color-accent)", swatch: "bg-accent", dash: undefined, width: 2 },
  { key: "baseline_vol", label: "Baseline model (HAR-RV)", line: "var(--color-neutral)", swatch: "bg-neutral", dash: "5 4", width: 1.5 },
  { key: "realized_vol", label: "What actually happened", line: "var(--color-up)", swatch: "bg-up", dash: undefined, width: 3 },
] as const;

type SeriesKey = (typeof SERIES)[number]["key"];

/** By calendar days, so the ranges stay right as the history grows. */
const RANGES: readonly RangeOption[] = [
  { label: "3M", days: 92 },
  { label: "6M", days: 183 },
  { label: "1Y", days: 366 },
  { label: "All", days: null },
];
const DEFAULT_RANGE_DAYS = 183;

/** Predicted vs baseline vs realized volatility. Realized is a gap while null. */
export function HistoryChart({ ticker, points }: HistoryChartProps) {
  const [days, setDays] = useState<number | null>(DEFAULT_RANGE_DAYS);
  const [hidden, setHidden] = useState<ReadonlySet<SeriesKey>>(new Set());

  // "All" can be thousands of daily points: draw one per week to keep it light.
  const shown = useMemo(() => {
    const inRange = sliceByDays(points, days, (p) => p.as_of_date);
    return days === null ? downsampleWeekly(inRange, (p) => p.as_of_date) : inRange;
  }, [points, days]);
  const csvHref = useMemo(
    () => `data:text/csv;charset=utf-8,${encodeURIComponent(historyToCsv(ticker, points))}`,
    [ticker, points],
  );

  if (points.length === 0) {
    return (
      <StateMessage
        title="No history yet"
        description="Past predictions will appear here once the engine has produced some."
      />
    );
  }

  const pending = points.filter((p) => p.realized_vol === null).length;
  const first = shown[0];
  const last = shown[shown.length - 1];
  const longRange =
    first !== undefined &&
    last !== undefined &&
    spanDays(first.as_of_date, last.as_of_date) > AXIS_YEAR_THRESHOLD_DAYS;

  function toggle(key: SeriesKey) {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key);
    else if (next.size < SERIES.length - 1) next.add(key);
    setHidden(next);
  }

  return (
    <section aria-labelledby="history-heading" className="rounded-lg border border-border bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="history-heading" className="text-base font-semibold">
            Prediction history
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Each point is a prediction made on that date for the following 5 trading days.
            {pending > 0
              ? ` The "what actually happened" line stops where the 5 days have not all passed yet (${pending} ${pending === 1 ? "date" : "dates"}): not known yet.`
              : ""}
            {days === null ? " Showing one point per week; the CSV has every day." : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RangeSelector label="History range" options={RANGES} value={days} onChange={setDays} />
          <a
            href={csvHref}
            download={`${ticker}-history.csv`}
            className="rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-muted transition-colors hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
          >
            Download CSV
          </a>
        </div>
      </div>

      <ul className="mt-4 flex flex-wrap gap-x-3 gap-y-2 text-xs">
        {SERIES.map((series) => {
          const off = hidden.has(series.key);
          return (
            <li key={series.key}>
              <button
                type="button"
                aria-pressed={!off}
                onClick={() => toggle(series.key)}
                className={`flex items-center gap-2 rounded-full border px-2.5 py-1 transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent ${
                  off ? "border-border text-muted line-through" : "border-border text-text hover:border-accent"
                }`}
              >
                <span aria-hidden="true" className={`h-0.5 w-5 rounded ${off ? "opacity-30" : ""} ${series.swatch}`} />
                {series.label}
              </button>
            </li>
          );
        })}
      </ul>

      <div
        role="img"
        aria-label="Line chart of predicted, baseline and realized volatility over time"
        className="mt-3 h-72 w-full font-mono text-xs [&_.recharts-cartesian-axis-tick-value]:fill-muted [&_.recharts-cartesian-grid_line]:stroke-border [&_.recharts-cartesian-axis-line]:stroke-border [&_.recharts-cartesian-axis-tick-line]:stroke-border"
      >
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 640, height: 288 }}>
          <LineChart data={shown} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="as_of_date"
              tickFormatter={longRange ? formatMonthYear : formatDateShort}
              minTickGap={longRange ? 48 : 24}
            />
            <YAxis
              width={52}
              tickFormatter={formatVol}
              domain={[(min: number) => Math.max(0, min * 0.9), (max: number) => max * 1.1]}
            />
            <Tooltip content={<ChartTooltip hidden={hidden} />} cursor={{ className: "stroke-border" }} />
            {SERIES.filter((series) => !hidden.has(series.key)).map((series) => (
              <Line
                key={series.key}
                type="linear"
                dataKey={series.key}
                stroke={series.line}
                strokeWidth={series.width}
                strokeDasharray={series.dash}
                dot={false}
                activeDot={{ r: 3 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

interface TooltipEntry {
  dataKey?: unknown;
  value?: unknown;
}

function ChartTooltip({
  active,
  payload,
  label,
  hidden,
}: {
  active?: boolean;
  payload?: readonly TooltipEntry[];
  label?: unknown;
  hidden: ReadonlySet<SeriesKey>;
}) {
  if (!active || !payload || payload.length === 0 || typeof label !== "string") return null;
  const valueOf = (key: SeriesKey): number | null => {
    const entry = payload.find((item) => item.dataKey === key);
    return typeof entry?.value === "number" ? entry.value : null;
  };
  return (
    <div className="rounded-md border border-border bg-surface-raised px-3 py-2 text-xs shadow-lg">
      <div className="mb-1.5 font-medium">{formatDate(label)}</div>
      <dl className="space-y-1">
        {SERIES.filter((series) => !hidden.has(series.key)).map((series) => {
          const value = valueOf(series.key);
          return (
            <div key={series.key} className="flex items-center justify-between gap-6">
              <dt className="flex items-center gap-2 text-muted">
                <span aria-hidden="true" className={`size-2 rounded-sm ${series.swatch}`} />
                {series.label}
              </dt>
              <dd className="font-mono tabular-nums">
                {value === null && series.key === "realized_vol" ? "not known yet" : formatVol(value)}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
