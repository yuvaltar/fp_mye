"use client";

import { useEffect, useState } from "react";
import { QUOTE_REFRESH_SECONDS, fetchQuotes } from "@/lib/api/quotes-client";
import { formatPrice, formatSignedPercent } from "@/lib/format";

interface LivePriceProps {
  ticker: string;
  currency: string;
  price: number;
  /** Relative change vs the previous close; null when unknown. */
  change: number | null;
}

/** Latest price and day change, refreshed every minute while the tab is visible. */
export function LivePrice({ ticker, currency, price, change }: LivePriceProps) {
  const [quote, setQuote] = useState({ price, change });
  const [updated, setUpdated] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function refresh() {
      if (document.visibilityState !== "visible") return;
      const result = await fetchQuotes([ticker], controller.signal);
      const next = result.quotes[ticker];
      if (cancelled || !next) return;
      setQuote({ price: next.price, change: next.change });
      setUpdated(new Date().toLocaleTimeString("en-GB"));
    }

    const timer = setInterval(refresh, QUOTE_REFRESH_SECONDS * 1000);
    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(timer);
    };
  }, [ticker]);

  const direction = quote.change === null ? "neutral" : quote.change >= 0 ? "up" : "down";
  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-3xl font-semibold tabular-nums">{formatPrice(quote.price, currency)}</span>
        <span
          className={`font-mono text-sm tabular-nums ${direction === "neutral" ? "text-muted" : "text-text"}`}
          aria-label="Change since the previous close"
        >
          {direction === "up" ? "▲ " : direction === "down" ? "▼ " : ""}
          {formatSignedPercent(quote.change)} today
        </span>
      </div>
      <p className="mt-1 text-xs text-muted" aria-live="polite">
        {updated ? `Refreshed ${updated}` : "Refreshes every minute"}
      </p>
    </div>
  );
}
