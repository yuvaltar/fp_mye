import type { PerformanceResponse } from "@/lib/api/proposed-types";
import { bestModels, improvementVs, modelLabel, type MetricKey } from "@/lib/derive";
import { formatMetric, formatShare, formatSignedPercent } from "@/lib/format";

const METRICS: { key: MetricKey; label: string }[] = [
  { key: "rmse", label: "RMSE" },
  { key: "mae", label: "MAE" },
  { key: "qlike", label: "QLIKE" },
];

const KIND_LABEL = { supervisor: "Market", skill: "Skill", baseline: "Baseline" } as const;

/** Backtest scores per model, lowest (best) value per column in bold, plus improvement vs HAR-RV. */
export function PerformanceTable({ data }: { data: PerformanceResponse }) {
  const reference = data.models.find((m) => m.name === "har_rv");
  const best = Object.fromEntries(METRICS.map((m) => [m.key, bestModels(data.models, m.key)])) as Record<
    MetricKey,
    string[]
  >;
  const maxRmse = Math.max(...data.models.map((m) => m.rmse), Number.EPSILON);

  return (
    <div className="space-y-6">
      <section aria-labelledby="metrics-heading" className="overflow-hidden rounded-lg border border-border bg-surface">
        <div className="border-b border-border p-5">
          <h2 id="metrics-heading" className="text-base font-semibold">
            Error vs baselines
          </h2>
          <p className="mt-1 text-sm text-muted">
            Lower is better. The best value in each column is in bold. Improvement is the RMSE reduction
            compared with HAR-RV.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-muted">
                <th scope="col" className="px-5 py-2.5 text-left font-medium">Model</th>
                {METRICS.map((m) => (
                  <th key={m.key} scope="col" className="px-3 py-2.5 text-right font-medium">{m.label}</th>
                ))}
                <th scope="col" className="px-3 py-2.5 text-right font-medium">vs HAR-RV</th>
                <th scope="col" className="w-40 px-5 py-2.5 text-left font-medium">RMSE</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.models.map((model) => {
                const improvement = reference ? improvementVs(model, reference, "rmse") : null;
                const isReference = model.name === "har_rv";
                return (
                  <tr key={model.name} className={model.kind === "supervisor" ? "bg-surface-raised" : ""}>
                    <th scope="row" className="px-5 py-3 text-left font-normal">
                      <span className="font-medium">{modelLabel(model.name)}</span>
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
                      {isReference || improvement === null ? "—" : formatSignedPercent(improvement)}
                    </td>
                    <td className="px-5 py-3">
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-raised">
                        <div
                          className={`h-full rounded-full ${model.kind === "supervisor" ? "bg-accent" : "bg-neutral"}`}
                          style={{ width: `${(model.rmse / maxRmse) * 100}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
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
            <li key={skill.name} className="grid grid-cols-[8rem_1fr_auto] items-center gap-x-4 text-sm">
              <span className="truncate font-medium">{modelLabel(skill.name)}</span>
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
    </div>
  );
}
