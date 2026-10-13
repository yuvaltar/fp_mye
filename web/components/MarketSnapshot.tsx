import type { PricesResponse } from "@/lib/api/extras-types";
import { realizedVolFromCloses } from "@/lib/derive";
import { formatDateTimeUtc, formatPrice, formatVol, formatVolume } from "@/lib/format";
import { LivePrice } from "./LivePrice";

/**
 * Real market numbers for one stock: price now, day and 52-week ranges, volume,
 * and the volatility that actually occurred, computed here from the real daily
 * closes with the same definition the engine uses.
 */
export function MarketSnapshot({ data }: { data: PricesResponse }) {
  const quote = data.quote;
  if (!quote) return null;

  const closes = data.points.map((p) => p.close);
  const change = quote.previous_close && quote.previous_close > 0 ? quote.price / quote.previous_close - 1 : null;
  const realized5 = realizedVolFromCloses(closes, 5);
  const realized21 = realizedVolFromCloses(closes, 21);

  return (
    <section aria-labelledby="snapshot-heading" className="rounded-lg border border-border bg-surface p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="snapshot-heading" className="text-base font-semibold">
          Market snapshot
        </h2>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-down/40 bg-down/10 px-2 py-0.5 text-[0.7rem] font-medium uppercase tracking-wide text-down">
          <span aria-hidden="true" className="size-1.5 rounded-full bg-down" />
          Live data
        </span>
      </div>

      <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <LivePrice ticker={data.ticker} currency={data.currency} price={quote.price} change={change} />

        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-3">
          <Stat label="Day range" value={rangeText(quote.day_low, quote.day_high, data.currency)} />
          <Stat label="52-week range" value={rangeText(quote.week52_low, quote.week52_high, data.currency)} />
          <Stat label="Volume" value={formatVolume(quote.volume)} />
          <Stat
            label="Realized vol, last 5 days"
            value={formatVol(realized5)}
            hint="From the real closes"
          />
          <Stat
            label="Realized vol, last 21 days"
            value={formatVol(realized21)}
            hint="From the real closes"
          />
          <Stat label="Exchange" value={quote.exchange ?? "—"} />
        </dl>
      </div>

      <p className="mt-4 border-t border-border pt-3 text-xs text-muted">
        Prices from Yahoo Finance, delayed by up to about 15 minutes; latest at {formatDateTimeUtc(quote.time)}.
        The realized volatility is computed by this site from those closes (annualized, same definition as the
        predictions) and is not an engine result.
      </p>
    </section>
  );
}

function rangeText(low: number | null, high: number | null, currency: string): string {
  if (low === null || high === null) return "—";
  return `${formatPrice(low, currency)} – ${formatPrice(high, currency)}`;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-1 font-mono tabular-nums">{value}</dd>
      {hint ? <p className="mt-0.5 text-[0.7rem] text-muted">{hint}</p> : null}
    </div>
  );
}
