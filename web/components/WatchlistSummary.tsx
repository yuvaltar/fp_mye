import type { WatchlistRow } from "@/lib/watchlist-rows";
import { formatShare, formatVol } from "@/lib/format";
import { StatCard } from "./StatCard";

/** Headline numbers for the whole watchlist, computed from the rows. */
export function WatchlistSummary({ rows }: { rows: WatchlistRow[] }) {
  const ok = rows.flatMap((row) => (row.status === "ok" ? [row] : []));
  if (ok.length === 0) return null;

  const rising = ok.filter((row) => row.trend === "rising").length;
  const falling = ok.filter((row) => row.trend === "falling").length;
  const avgConfidence = ok.reduce((sum, row) => sum + row.confidence, 0) / ok.length;
  const highest = ok.reduce((best, row) => (row.predictedVol > best.predictedVol ? row : best));

  return (
    <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard label="Tickers" hint={`${ok.length} with a prediction`}>
        <div className="font-mono text-2xl font-semibold tabular-nums">{rows.length}</div>
      </StatCard>
      <StatCard label="Volatility trend" hint="Prediction vs latest realized">
        <div className="font-mono text-2xl font-semibold tabular-nums">
          <span className="text-up">▲ {rising}</span>
          <span className="mx-2 text-muted">·</span>
          <span className="text-down">▼ {falling}</span>
        </div>
      </StatCard>
      <StatCard label="Highest predicted vol" hint={highest.name}>
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-2xl font-semibold tabular-nums">{formatVol(highest.predictedVol)}</span>
          <span className="font-mono text-sm text-muted">{highest.ticker}</span>
        </div>
      </StatCard>
      <StatCard label="Average confidence">
        <div className="font-mono text-2xl font-semibold tabular-nums">{formatShare(avgConfidence)}</div>
      </StatCard>
    </div>
  );
}
