import { getQuotes } from "@/lib/api/client";
import { marketDataEnabled } from "@/lib/api/market";

export const dynamic = "force-dynamic";

const TICKER_PATTERN = /^[A-Z][A-Z0-9.-]{0,9}$/;
const MAX_TICKERS = 60;

/**
 * GET /api/quotes?tickers=AAPL,MSFT: latest price and day change from the
 * market data source, for the browser to refresh without a page reload.
 * Answers { enabled: false } when live market data is switched off.
 */
export async function GET(request: Request) {
  if (!marketDataEnabled()) return Response.json({ enabled: false, quotes: {} });

  const raw = new URL(request.url).searchParams.get("tickers") ?? "";
  const tickers = raw
    .split(",")
    .map((t) => t.trim().toUpperCase())
    .filter((t) => TICKER_PATTERN.test(t))
    .slice(0, MAX_TICKERS);
  if (tickers.length === 0) return Response.json({ enabled: true, quotes: {} });

  const quotes = await getQuotes(tickers);
  return Response.json({ enabled: true, quotes: Object.fromEntries(quotes) });
}
