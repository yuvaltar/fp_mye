import { formatDate } from "@/lib/format";

/**
 * Explains why a prediction may be higher this week: the company reports its
 * quarterly earnings inside the 5 days the prediction covers. Rendered only
 * when the engine reports an earnings_date.
 */
export function EarningsNotice({ date }: { date: string }) {
  return (
    <section
      aria-labelledby="earnings-heading"
      className="rounded-lg border border-up/40 bg-up/10 px-5 py-4"
    >
      <h2 id="earnings-heading" className="text-sm font-semibold text-up">
        Earnings report on {formatDate(date)}
      </h2>
      <p className="mt-1.5 text-sm leading-relaxed">
        This company reports its quarterly results inside the 5 trading days this prediction covers. Prices
        often jump around a report, so in a week like this the engine raises its forecast according to how
        much this stock moved after its earlier reports.
      </p>
    </section>
  );
}

/** Small tag for tables: "Earnings 13 Oct". */
export function EarningsTag({ date }: { date: string }) {
  return (
    <span
      title="Quarterly earnings report inside the prediction window"
      className="shrink-0 rounded-full border border-up/40 bg-up/10 px-2 py-px text-[0.7rem] font-medium text-up"
    >
      Earnings {formatDate(date).replace(/ \d{4}$/, "")}
    </span>
  );
}
