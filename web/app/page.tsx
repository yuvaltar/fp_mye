import { WatchlistSummary } from "@/components/WatchlistSummary";
import { WatchlistTable } from "@/components/WatchlistTable";
import { loadWatchlist } from "@/lib/watchlist";

// Data comes from the API or the mock files at request time, never at build time.
export const dynamic = "force-dynamic";

export default async function WatchlistPage() {
  const { rows, source } = await loadWatchlist();
  const withPrediction = rows.filter((row) => row.status === "ok").length;

  return (
    <main>
      <h1 className="text-2xl font-semibold tracking-tight">Watchlist</h1>
      <p className="mt-1 mb-6 max-w-2xl text-sm text-muted">
        Predicted volatility for the next 5 trading days, compared with the HAR-RV baseline. The trend
        badge compares the prediction with the latest realized volatility.
      </p>
      {source === "partial" || withPrediction < rows.length ? (
        <p
          role="note"
          className="mb-6 rounded-lg border border-border bg-surface px-4 py-3 text-sm text-muted"
        >
          The engine currently has predictions for{" "}
          <span className="font-mono text-text">{withPrediction}</span> of{" "}
          <span className="font-mono text-text">{rows.length}</span> listed tickers. The others are shown
          without numbers until it covers them.
        </p>
      ) : null}
      <WatchlistSummary rows={rows} />
      <WatchlistTable rows={rows} />
    </main>
  );
}
