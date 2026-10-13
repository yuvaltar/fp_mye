import type { PerformanceResponse } from "@/lib/api/types";
import {
  bestModels,
  horizonLabel,
  modelLabel,
  performanceSentence,
  tickerImprovement,
  type MetricKey,
} from "@/lib/derive";
import { formatMetric, formatShare, formatSignedPercent } from "@/lib/format";

/** QLIKE first: it is the headline and the metric the supervisor is tuned for. */
const METRICS: { key: MetricKey; label: string }[] = [
  { key: "qlike", label: "QLIKE" },
  { key: "rmse", label: "RMSE" },
  { key: "mae", label: "MAE" },
];

const KIND_LABEL = { supervisor: "Market", skill: "Skill", baseline: "Baseline" } as const;

/** The backtest summary: headline, error table with QLIKE first, weights and a per-ticker table. */
export function PerformanceTable({ data }: { data: PerformanceResponse }) {
  const best = Object.fromEntries(METRICS.map((m) => [m.key, bestModels(data.models, m.key)])) as Record<
    MetricKey,
    string[]
  >;
  const modelNames = data.models.map((m) => m.name);
  const maxQlike = Math.max(...data.models.map((m) => m.qlike), Number.EPSILON);
  const perTicker = [...data.per_ticker].sort(
    (a, b) => (tickerImprovement(b) ?? -Infinity) - (tickerImprovement(a) ?? -Infinity),
  );

  return (
    <div className="space-y-6">
      <section
        aria-labelledby="headline-heading"
        className="rounded-lg border border-border bg-surface p-5"
      >
        <h2 id="headline-heading" className="text-base font-semibold">
          The result in one line
        </h2>
        <div className="mt-3 grid gap-5 sm:grid-cols-[auto_1fr] sm:items-center">
          <div>
            <div className="font-mono text-4xl font-semibold tabular-nums">
              {formatSignedPercent(data.headline.improvement)}
            </div>
            <div className="mt-1 text-xs uppercase tracking-wide text-muted">QLIKE vs HAR-RV</div>
          </div>
          <p className="text-sm leading-relaxed">{performanceSentence(data.headline)}</p>
        </div>
        <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted">
          QLIKE is the standard error measure for volatility forecasts: lower is better, and it punishes
          predicting too low more than too high. That is why it is the headline here and the metric the
          supervisor is tuned for.
        </p>
      </section>

      <section aria-labelledby="metrics-heading" className="overflow-hidden rounded-lg border border-border bg-surface">
        <div className="border-b border-border p-5">
          <h2 id="metrics-heading" className="text-base font-semibold">
            Error vs baselines
          </h2>
          <p className="mt-1 text-sm text-muted">
            Lower is better for all three. The best value in each column is in bold. &quot;vs HAR-RV&quot; is
            the improvement over the baseline (positive means better than HAR-RV).
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <th scope="col" className="px-5 py-2.5 text-left font-medium">Model</th>
                {METRICS.map((m) => (
                  <th key={m.key} scope="col" className="px-3 py-2.5 text-right font-medium">{m.label}</th>
                ))}
                <th scope="col" className="px-3 py-2.5 text-right font-medium">QLIKE vs HAR-RV</th>
                <th scope="col" className="w-36 px-5 py-2.5 text-left font-medium">QLIKE</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.models.map((model) => (
                <tr key={model.name} className={model.kind === "supervisor" ? "bg-surface-raised" : ""}>
                  <th scope="row" className="px-5 py-3 text-left font-normal">
                    <span className="font-medium">{modelLabel(model.name, modelNames)}</span>
                    <span className="ml-2 text-xs text-muted">{KIND_LABEL[model.kind]}</span>
                  </th>
                  {METRICS.map((m) => (
                    <td
                      key={m.key}
                      className={`px-3 py-3 text-right font-mono tabular-nums ${
                        best[m.key].includes(model.name) ? "font-bold text-text" : "text-muted"
                      }`}
                    >
                      {formatMetric(model[m.key])}
                    </td>
                  ))}
                  <td className="px-3 py-3 text-right font-mono tabular-nums text-muted">
                    {model.qlike_vs_har_rv === null ? "—" : formatSignedPercent(model.qlike_vs_har_rv)}
                  </td>
                  <td className="px-5 py-3">
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-raised">
                      <div
                        className={`h-full rounded-full ${model.kind === "supervisor" ? "bg-accent" : "bg-neutral"}`}
                        style={{ width: `${(model.qlike / maxQlike) * 100}%` }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="weights-avg-heading" className="rounded-lg border border-border bg-surface p-5">
        <h2 id="weights-avg-heading" className="text-base font-semibold">
          Average weight per skill
        </h2>
        <p className="mt-1 text-sm text-muted">
          How much the supervisor trusted each skill over the period (mean, with the lowest and highest weight).
        </p>
        <ul className="mt-4 space-y-3">
          {data.skill_weights.map((skill) => (
            <li key={skill.name} className="grid grid-cols-[15rem_1fr_auto] items-center gap-x-4 text-sm">
              <span className="truncate">
                <span className="font-medium">{modelLabel(skill.name, modelNames)}</span>
                <span className="ml-2 hidden text-xs text-muted sm:inline">{horizonLabel(skill.horizon)}</span>
              </span>
              <div className="relative h-2 overflow-hidden rounded-full bg-surface-raised">
                <div
                  className="absolute inset-y-0 rounded-full bg-border"
                  style={{ left: `${skill.min * 100}%`, width: `${Math.max(0, skill.max - skill.min) * 100}%` }}
                />
                <div
                  className="absolute inset-y-0 w-1 rounded-full bg-accent"
                  style={{ left: `calc(${skill.mean * 100}% - 2px)` }}
                />
              </div>
              <span className="font-mono text-xs tabular-nums text-muted">
                {formatShare(skill.mean)} <span className="opacity-70">({formatShare(skill.min)}–{formatShare(skill.max)})</span>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <details className="group rounded-lg border border-border bg-surface">
        <summary className="cursor-pointer list-none px-5 py-4 text-base font-semibold focus-visible:outline-2 focus-visible:outline-accent">
          <span className="mr-2 inline-block text-muted transition-transform group-open:rotate-90" aria-hidden="true">
            ▸
          </span>
          Per ticker ({perTicker.length})
        </summary>
        <div className="max-h-[32rem] overflow-auto border-t border-border">
          <table className="w-full min-w-[28rem] text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <th scope="col" className="px-5 py-2.5 text-left font-medium">Ticker</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Supervisor QLIKE</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">HAR-RV QLIKE</th>
                <th scope="col" className="px-5 py-2.5 text-right font-medium">Improvement</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {perTicker.map((row) => (
                <tr key={row.ticker}>
                  <th scope="row" className="px-5 py-2 text-left font-mono font-semibold">{row.ticker}</th>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{formatMetric(row.supervisor_qlike)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-muted">{formatMetric(row.baseline_qlike)}</td>
                  <td className="px-5 py-2 text-right font-mono tabular-nums">
                    {formatSignedPercent(tickerImprovement(row))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <section aria-labelledby="caveats-heading" className="rounded-lg border border-border bg-surface p-5">
        <h2 id="caveats-heading" className="text-base font-semibold">
          How far to trust this
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-relaxed text-muted">
          <li>
            It covers {data.tickers.length} large, liquid US-listed stocks over one period that includes the
            2020 crash. Results may not carry over to other stocks or to calmer or wilder periods.
          </li>
          <li>
            The stocks were picked by size as of today, so companies that shrank or disappeared are missing
            (survivorship bias). It flatters every model here, the baselines included.
          </li>
          <li>
            Consecutive dates share 4 of their 5 target days, so the {data.scored_predictions.toLocaleString("en-US")}{" "}
            scored predictions are far from independent. The t-statistic corrects for this; the raw count
            overstates the evidence.
          </li>
        </ul>
      </section>
    </div>
  );
}
