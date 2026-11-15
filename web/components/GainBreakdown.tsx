import type { GainBreakdown as GainBreakdownData, GainBreakdownRow } from "@/lib/api/types";
import { breakdownBarShare, breakdownSentences } from "@/lib/derive";
import { formatMetric, formatShare, formatSignedPercent } from "@/lib/format";

const LABELS: Record<GainBreakdownRow["name"], { title: string; note: string }> = {
  har_rv: { title: "HAR-RV", note: "The standard model, our baseline" },
  har_rv_earnings: { title: "HAR-RV + earnings dates", note: "The baseline, told when reports come out" },
  committee_no_earnings: { title: "Our skills, no earnings dates", note: "The market of skills on its own" },
  supervisor: { title: "Our skills + earnings dates", note: "The product" },
};

const COLUMNS = [
  { key: "qlike", gain: "qlike_vs_har_rv", label: "All weeks" },
  { key: "qlike_ordinary", gain: "qlike_ordinary_vs_har_rv", label: "Ordinary weeks" },
  { key: "qlike_earnings", gain: "qlike_earnings_vs_har_rv", label: "Earnings weeks" },
] as const;

/** "Where the improvement comes from": earnings dates alone, our models alone, and both. */
export function GainBreakdown({ data }: { data: GainBreakdownData }) {

  return (
    <section aria-labelledby="breakdown-heading" className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="border-b border-border p-5">
        <h2 id="breakdown-heading" className="text-base font-semibold">
          Where the improvement comes from
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Earnings reports make stocks jump, and knowing their dates helps any model. To show what our skills add
          on top of that, the same past forecasts are scored four ways. Earnings weeks, when a report falls in the
          5 days forecast, are {formatShare(data.earnings_week_share)} of all forecasts.
        </p>
      </div>

      <ul className="space-y-3 p-5">
        {data.rows.map((r) => (
          <li key={r.name} className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3 text-sm sm:grid-cols-[16rem_1fr_auto]">
            <div>
              <div className={r.name === "supervisor" ? "font-semibold" : "font-medium"}>{LABELS[r.name].title}</div>
              <div className="text-xs text-muted">{LABELS[r.name].note}</div>
            </div>
            <div className="h-2.5 rounded-full bg-border/60" aria-hidden="true">
              <div
                className={`h-2.5 rounded-full ${r.name === "supervisor" ? "bg-accent" : "bg-muted/60"}`}
                style={{ width: `${breakdownBarShare(data, r) * 100}%` }}
              />
            </div>
            <div className="w-16 text-right font-mono tabular-nums">
              {r.name === "har_rv" ? "—" : formatSignedPercent(r.qlike_vs_har_rv)}
            </div>
          </li>
        ))}
      </ul>

      <div className="overflow-x-auto border-t border-border">
        <table className="w-full min-w-[36rem] text-sm">
          <caption className="sr-only">QLIKE by kind of week, and the improvement over HAR-RV</caption>
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted">
              <th scope="col" className="px-5 py-2.5 text-left font-medium">Model</th>
              {COLUMNS.map((c) => (
                <th key={c.key} scope="col" className="px-3 py-2.5 text-right font-medium">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.rows.map((r) => (
              <tr key={r.name}>
                <th scope="row" className={`px-5 py-2.5 text-left ${r.name === "supervisor" ? "font-semibold" : "font-normal"}`}>
                  {LABELS[r.name].title}
                </th>
                {COLUMNS.map((c) => (
                  <td key={c.key} className="px-3 py-2.5 text-right font-mono tabular-nums">
                    {formatMetric(r[c.key])}
                    <span className="ml-2 inline-block w-12 text-left text-xs text-muted">
                      {r.name === "har_rv" ? "" : formatSignedPercent(r[c.gain])}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-1.5 border-t border-border p-5 text-sm leading-relaxed">
        {breakdownSentences(data).map((sentence) => (
          <p key={sentence}>{sentence}</p>
        ))}
        <p className="pt-1 text-xs text-muted">QLIKE: lower is better. Percentages are the improvement over HAR-RV.</p>
      </div>
    </section>
  );
}
