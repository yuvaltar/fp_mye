import Link from "next/link";
import { notFound } from "next/navigation";
import { ConfidenceMeter } from "@/components/ConfidenceMeter";
import { EarningsNotice } from "@/components/EarningsNotice";
import { HistoryChart } from "@/components/HistoryChart";
import { InsightsPanel } from "@/components/InsightsPanel";
import { MarketSnapshot } from "@/components/MarketSnapshot";
import { PredictionVsBaseline } from "@/components/PredictionVsBaseline";
import { PriceChart } from "@/components/PriceChart";
import { SkillsMarket } from "@/components/SkillsMarket";
import { StatCard } from "@/components/StatCard";
import { StateMessage } from "@/components/StateMessage";
import { TrendBadge } from "@/components/TrendBadge";
import { UnavailableNote } from "@/components/UnavailableNote";
import { WeightsChart } from "@/components/WeightsChart";
import { VolatilityGuide } from "@/components/VolatilityGuide";
import {
  NotFoundError,
  NotReadyError,
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
    const notReady = prediction.reason instanceof NotReadyError;
    if (!notReady && !(prediction.reason instanceof NotFoundError)) throw prediction.reason;
    // Listed but not covered by the engine yet (404), or the engine has no
    // results at all yet (503): say so instead of showing an error.
    if (!notReady && !listed) notFound();
    // Real market data does not depend on the engine, so show it meanwhile.
    const market = prices.status === "fulfilled" ? prices.value : null;
    return (
      <main className="space-y-6">
        <Link href="/" className="text-sm text-muted transition-colors hover:text-text">
          ← Watchlist
        </Link>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="font-mono text-3xl font-semibold tracking-tight">{listed?.ticker ?? symbol}</h1>
          {listed ? <span className="text-lg text-muted">{listed.name}</span> : null}
          {listed?.sector ? <span className="text-sm text-muted">· {listed.sector}</span> : null}
        </div>
        <StateMessage
          title={notReady ? "The predictions are not ready yet" : "No prediction yet"}
          description={
            notReady
              ? "The prediction engine has not produced its results yet. Try again in a little while."
              : `The prediction engine does not cover ${listed?.ticker ?? symbol} yet. It will appear here as soon as it does.`
          }
          action={
            <Link href="/" className={actionClassName}>
              Back to the watchlist
            </Link>
          }
        />
        {market?.state === "available" && market.source === "market" ? (
          <>
            <MarketSnapshot data={market.data} />
            <PriceChart data={market.data} sample={false} live />
          </>
        ) : null}
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
          From the engine&apos;s latest run, with prices up to the {formatDate(p.as_of_date)} close.
        </p>
      </div>

      {p.earnings_date ? <EarningsNotice date={p.earnings_date} /> : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Expected volatility"
          hint={`For the ${p.horizon_days} trading days after ${formatDate(p.as_of_date)}`}
        >
          <div className="font-mono text-3xl font-semibold tabular-nums">{formatVol(p.predicted_vol)}</div>
        </StatCard>
        <StatCard
          label="Baseline model"
          hint={diff === null ? "HAR-RV" : `HAR-RV · prediction is ${formatSignedPercent(diff)} vs baseline`}
        >
          <div className="font-mono text-3xl font-semibold tabular-nums text-muted">{formatVol(p.baseline_vol)}</div>
        </StatCard>
        <StatCard label="Supervisor's recent accuracy" hint="A score from 0 to 100%, not a probability">
          <ConfidenceMeter value={p.supervisor_confidence} />
        </StatCard>
        <StatCard label="Volatility trend" hint="Prediction vs latest realized volatility">
          <div className="pt-1">
            <TrendBadge trend={trend} />
          </div>
        </StatCard>
      </div>

      {priceData?.state === "available" && priceData.source === "market" ? (
        <MarketSnapshot data={priceData.data} />
      ) : null}

      {priceData?.state === "available" ? (
        <PriceChart data={priceData.data} sample={priceData.sample} live={priceData.source === "market"} />
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

      <VolatilityGuide predictedVol={p.predicted_vol} />

      <footer className="border-t border-border pt-4 text-xs text-muted">
        <p>For learning purposes only, not investment advice.</p>
        <p className="mt-1">
          Engine version <span className="font-mono">{p.model_version}</span>
        </p>
      </footer>
    </main>
  );
}
