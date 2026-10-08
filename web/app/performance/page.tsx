import { PerformanceTable } from "@/components/PerformanceTable";
import { SampleDataBadge } from "@/components/SampleDataBadge";
import { UnavailableNote } from "@/components/UnavailableNote";
import { getPerformance } from "@/lib/api/client";
import { formatDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function PerformancePage() {
  const result = await getPerformance();

  return (
    <main>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Performance</h1>
        {result.state === "available" && result.sample ? <SampleDataBadge /> : null}
      </div>
      <p className="mt-1 mb-6 max-w-2xl text-sm text-muted">
        Does the market of skills beat a standard model? This page compares the supervisor, each skill and
        the baselines on past data, always predicting each date using only information available then
        (walk-forward backtest).
      </p>

      {result.state === "available" ? (
        <>
          <dl className="mb-6 grid grid-cols-2 gap-3 text-sm lg:grid-cols-4">
            <Fact label="Period" value={`${formatDate(result.data.period_start)} – ${formatDate(result.data.period_end)}`} />
            <Fact label="Evaluation dates" value={String(result.data.evaluation_dates)} />
            <Fact label="Tickers" value={result.data.tickers.join(", ")} />
            <Fact label="Report generated" value={formatDate(result.data.generated_at)} />
          </dl>
          <PerformanceTable data={result.data} />
        </>
      ) : (
        <UnavailableNote
          title="Backtest results not available yet"
          description="The prediction engine does not publish its backtest results yet. Once it does, the comparison of the market against HAR-RV and the individual skills will appear here."
        />
      )}
    </main>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-1.5 font-mono text-sm font-semibold">{value}</dd>
    </div>
  );
}
