"use client";

import { useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PricesResponse } from "@/lib/api/proposed-types";
import { lastN, priceChange } from "@/lib/derive";
import { formatDate, formatDateShort, formatPrice, formatSignedPercent } from "@/lib/format";
import { RangeSelector, type RangeOption } from "./RangeSelector";
import { SampleDataBadge } from "./SampleDataBadge";
import { StateMessage } from "./StateMessage";

const RANGES: readonly RangeOption[] = [
  { label: "1M", count: 21 },
  { label: "3M", count: 63 },
  { label: "All", count: null },
];

interface PriceChartProps {
  data: PricesResponse;
  sample: boolean;
}

/** Closing price with the last close, the change over the chosen range and a range selector. */
export function PriceChart({ data, sample }: PriceChartProps) {
  const [count, setCount] = useState<number | null>(63);

  if (data.points.length === 0) {
    return (
      <StateMessage title="No price data yet" description="Closing prices will appear here once they are available." />
    );
  }

  const points = lastN(data.points, count);
  const change = priceChange(points);

  return (
    <section aria-labelledby="price-heading" className="rounded-lg border border-border bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h2 id="price-heading" className="text-base font-semibold">
              Price
            </h2>
            {sample ? <SampleDataBadge /> : null}
          </div>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-mono text-3xl font-semibold tabular-nums">
              {formatPrice(data.last_close, data.currency)}
            </span>
            {change ? (
              <span className="font-mono text-sm tabular-nums text-muted">
                {formatSignedPercent(change.relative)} over range
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-muted">Close on {formatDate(data.last_close_date)}</p>
        </div>
        <RangeSelector label="Price range" options={RANGES} value={count} onChange={setCount} />
      </div>

      <div
        role="img"
        aria-label={`Closing price of ${data.ticker}`}
        className="mt-4 h-60 w-full font-mono text-xs [&_.recharts-cartesian-axis-tick-value]:fill-muted [&_.recharts-cartesian-grid_line]:stroke-border [&_.recharts-cartesian-axis-line]:stroke-border [&_.recharts-cartesian-axis-tick-line]:stroke-border"
      >
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 640, height: 240 }}>
          <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="date" tickFormatter={formatDateShort} minTickGap={32} />
            <YAxis
              width={56}
              tickFormatter={(value: number) => formatPrice(value, data.currency)}
              domain={[(min: number) => min * 0.98, (max: number) => max * 1.02]}
            />
            <Tooltip
              content={<PriceTooltip currency={data.currency} />}
              cursor={{ className: "stroke-border" }}
            />
            <Area
              type="linear"
              dataKey="close"
              stroke="var(--color-accent)"
              fill="var(--color-accent)"
              fillOpacity={0.12}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function PriceTooltip({
  active,
  payload,
  label,
  currency,
}: {
  active?: boolean;
  payload?: readonly { value?: unknown }[];
  label?: unknown;
  currency: string;
}) {
  const value = payload?.[0]?.value;
  if (!active || typeof value !== "number" || typeof label !== "string") return null;
  return (
    <div className="rounded-md border border-border bg-surface-raised px-3 py-2 text-xs shadow-lg">
      <div className="font-medium">{formatDate(label)}</div>
      <div className="mt-1 font-mono tabular-nums">{formatPrice(value, currency)}</div>
    </div>
  );
}
