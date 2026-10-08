import Link from "next/link";
import { notFound } from "next/navigation";
import { ConfidenceMeter } from "@/components/ConfidenceMeter";
import { HistoryChart } from "@/components/HistoryChart";
import { InsightsPanel } from "@/components/InsightsPanel";
import { PredictionVsBaseline } from "@/components/PredictionVsBaseline";
import { PriceChart } from "@/components/PriceChart";
import { SkillsMarket } from "@/components/SkillsMarket";
import { StatCard } from "@/components/StatCard";
import { StateMessage } from "@/components/StateMessage";
import { TrendBadge } from "@/components/TrendBadge";
import { UnavailableNote } from "@/components/UnavailableNote";
import { WeightsChart } from "@/components/WeightsChart";
import {
  NotFoundError,
  getHistory,
  getPrediction,
  getPrices,
  getUniverse,
  getWeightsHistory,
  normalizeTicker,
} from "@/lib/api/client";
import { actionClassName } from "@/components/StateMessage";
import { getTrend, relativeDifference } from "@/lib/derive";
import { formatDate, formatSignedPercent, formatVol } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function StockPage({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;

  const [prediction, history, universe, prices, weights] = await Promise.allSettled([
    getPrediction(ticker),
    getHistory(ticker),
    getUniverse(),
    getPrices(ticker),
    getWeightsHistory(ticker),
  ]);

  const symbol = normalizeTicker(ticker);
  const listed =
    universe.status === "fulfilled" ? universe.value.find((t) => t.ticker === symbol) : undefined;

  if (prediction.status === "rejected") {
    if (!(prediction.reason instanceof NotFoundError)) throw prediction.reason;
    // Listed but not covered by the engine yet: say so instead of a 404.
    if (!listed) notFound();
    return (
      <main className="space-y-6">
        <Link href="/" className="text-sm text-muted transition-colors hover:text-text">
          ← Watchlist
        </Link>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="font-mono text-3xl font-semibold tracking-tight">{listed.ticker}</h1>
          <span className="text-lg text-muted">{listed.name}</span>
          {listed.sector ? <span className="text-sm text-muted">· {listed.sector}</span> : null}
        </div>
        <StateMessage
          title="No prediction yet"
          description={`The prediction engine does not cover ${listed.ticker} yet. It will appear here as soon as it does.`}
          action={
            <Link href="/" className={actionClassName}>
              Back to the watchlist
            </Link>
          }
        />
      </main>
    );
  }
  if (history.status === "rejected" && history.reason instanceof NotFoundError) notFound();

  const p = prediction.value;
  // The company name is a nicety: without it the page still works.
  const name = listed?.name;
  const points = history.status === "fulfilled" ? history.value.points : null;
  const trend = points ? getTrend(p.predicted_vol, points) : "no-data";
  const diff = relativeDifference(p.predicted_vol, p.baseline_vol);
  // Optional sections: a failure or a missing endpoint just shows a note.
  const priceData = prices.status === "fulfilled" ? prices.value : null;
  const weightsData = weights.status === "fulfilled" ? weights.value : null;

  return (
    <main className="space-y-6">
      <div>
        <Link href="/" className="text-sm text-muted transition-colors hover:text-text">
          ← Watchlist
        </Link>
        <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="font-mono text-3xl font-semibold tracking-tight">{p.ticker}</h1>
          {name ? <span className="text-lg text-muted">{name}</span> : null}
          {listed?.sector ? <span className="text-sm text-muted">· {listed.sector}</span> : null}
        </div>
        <p className="mt-1 text-xs text-muted">
          As of {formatDate(p.as_of_date)} close · covers the next {p.horizon_days} trading days · model{" "}
          <span className="font-mono">{p.model_version}</span>
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Predicted volatility" hint="Annualized, next 5 trading days">
          <div className="font-mono text-3xl font-semibold tabular-nums">{formatVol(p.predicted_vol)}</div>
        </StatCard>
        <StatCard label="HAR-RV baseline" hint={diff === null ? undefined : `Prediction is ${formatSignedPercent(diff)} vs baseline`}>
          <div className="font-mono text-3xl font-semibold tabular-nums text-muted">{formatVol(p.baseline_vol)}</div>
        </StatCard>
        <StatCard label="Supervisor confidence">
          <ConfidenceMeter value={p.supervisor_confidence} />
        </StatCard>
        <StatCard label="Volatility trend" hint="Prediction vs latest realized volatility">
          <div className="pt-1">
            <TrendBadge trend={trend} />
          </div>
        </StatCard>
      </div>

      {priceData?.state === "available" ? (
        <PriceChart data={priceData.data} sample={priceData.sample} />
      ) : (
        <UnavailableNote
          title="Price chart"
          description="The prediction engine does not provide price data yet. The price and its chart will appear here once it does."
        />
      )}

      <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
        <div className="space-y-6">
          <PredictionVsBaseline predictedVol={p.predicted_vol} baselineVol={p.baseline_vol} />
          <InsightsPanel prediction={p} points={points} />
        </div>
        <SkillsMarket skills={p.skills} baselineVol={p.baseline_vol} />
      </div>

      {points ? (
        <HistoryChart ticker={p.ticker} points={points} />
      ) : (
        <StateMessage
          tone="error"
          title="History unavailable"
          description="The prediction above loaded, but the history could not be fetched. Reload the page to try again."
        />
      )}

      {weightsData?.state === "available" ? (
        <WeightsChart data={weightsData.data} sample={weightsData.sample} />
      ) : (
        <UnavailableNote
          title="Skill weights over time"
          description="The prediction engine does not provide weight history yet. How the supervisor shifts trust between skills will appear here once it does."
        />
      )}
    </main>
  );
}
