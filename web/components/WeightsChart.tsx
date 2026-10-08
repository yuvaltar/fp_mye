"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { WeightsHistoryResponse } from "@/lib/api/proposed-types";
import { skillLabel, weightsToRows } from "@/lib/derive";
import { formatDate, formatDateShort, formatShare } from "@/lib/format";
import { SampleDataBadge } from "./SampleDataBadge";
import { StateMessage } from "./StateMessage";

/** Series colors by skill position; classes are literal so Tailwind keeps them. */
const SERIES_BG = ["bg-series-1", "bg-series-2", "bg-series-3", "bg-series-4", "bg-series-5", "bg-series-6"];
const SERIES_VAR = [
  "var(--color-series-1)",
  "var(--color-series-2)",
  "var(--color-series-3)",
  "var(--color-series-4)",
  "var(--color-series-5)",
  "var(--color-series-6)",
];

interface WeightsChartProps {
  data: WeightsHistoryResponse;
  sample: boolean;
}

/** How the supervisor's trust in each skill changed over time (stacked to 100%). */
export function WeightsChart({ data, sample }: WeightsChartProps) {
  if (data.points.length === 0 || data.skills.length === 0) {
    return (
      <StateMessage title="No weight history yet" description="Skill weights over time will appear here." />
    );
  }
  const rows = weightsToRows(data.points);

  return (
    <section aria-labelledby="weights-heading" className="rounded-lg border border-border bg-surface p-5">
      <div className="flex items-center gap-3">
        <h2 id="weights-heading" className="text-base font-semibold">
          Skill weights over time
        </h2>
        {sample ? <SampleDataBadge /> : null}
      </div>
      <p className="mt-1 text-sm text-muted">
        The supervisor shifts weight toward the skills that have been predicting better recently. Each band is
        one skill; together they always add up to 100%.
      </p>

      <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted">
        {data.skills.map((skill, index) => (
          <li key={skill.name} className="flex items-center gap-2">
            <span aria-hidden="true" className={`size-2.5 rounded-sm ${SERIES_BG[index % SERIES_BG.length]}`} />
            {skillLabel(skill.name)}
          </li>
        ))}
      </ul>

      <div
        role="img"
        aria-label="Stacked area chart of the weight of each skill over time"
        className="mt-3 h-64 w-full font-mono text-xs [&_.recharts-cartesian-axis-tick-value]:fill-muted [&_.recharts-cartesian-grid_line]:stroke-border [&_.recharts-cartesian-axis-line]:stroke-border [&_.recharts-cartesian-axis-tick-line]:stroke-border"
      >
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 640, height: 256 }}>
          <AreaChart data={rows} stackOffset="expand" margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="as_of_date" tickFormatter={formatDateShort} minTickGap={24} />
            <YAxis width={44} tickFormatter={(v: number) => formatShare(v)} domain={[0, 1]} />
            <Tooltip content={<WeightsTooltip skills={data.skills.map((s) => s.name)} />} cursor={{ className: "stroke-border" }} />
            {data.skills.map((skill, index) => (
              <Area
                key={skill.name}
                type="linear"
                dataKey={skill.name}
                stackId="weights"
                stroke={SERIES_VAR[index % SERIES_VAR.length]}
                fill={SERIES_VAR[index % SERIES_VAR.length]}
                fillOpacity={0.7}
                strokeWidth={1}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function WeightsTooltip({
  active,
  payload,
  label,
  skills,
}: {
  active?: boolean;
  payload?: readonly { dataKey?: unknown; value?: unknown }[];
  label?: unknown;
  skills: readonly string[];
}) {
  if (!active || !payload || typeof label !== "string") return null;
  return (
    <div className="rounded-md border border-border bg-surface-raised px-3 py-2 text-xs shadow-lg">
      <div className="mb-1.5 font-medium">{formatDate(label)}</div>
      <dl className="space-y-1">
        {skills.map((name, index) => {
          const entry = payload.find((item) => item.dataKey === name);
          const value = typeof entry?.value === "number" ? entry.value : null;
          return (
            <div key={name} className="flex items-center justify-between gap-6">
              <dt className="flex items-center gap-2 text-muted">
                <span aria-hidden="true" className={`size-2 rounded-sm ${SERIES_BG[index % SERIES_BG.length]}`} />
                {skillLabel(name)}
              </dt>
              <dd className="font-mono tabular-nums">{formatShare(value)}</dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
