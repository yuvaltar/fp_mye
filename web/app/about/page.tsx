import Link from "next/link";
import type { ReactNode } from "react";

export const metadata = {
  title: "How it works · Temporal Skills Market",
  description: "How the market of prediction skills works, and how to read the numbers.",
};

const STEPS = [
  {
    title: "Skills predict",
    text: "Each skill is a small agent that looks at the price history of one stock from its own angle, for example short-term trend, medium-term trend, weak signals or seasonality, and makes its own volatility prediction.",
  },
  {
    title: "The supervisor weighs",
    text: "A supervisor scores every skill on how well it predicted recently, on data it had not seen yet, and gives better-performing skills more weight. The weights always add up to 100%.",
  },
  {
    title: "The market decides",
    text: "The final prediction is the weighted combination of all skills. It is shown next to HAR-RV, a standard volatility model, so you can always see whether the market adds anything.",
  },
] as const;

const GLOSSARY: { term: string; definition: ReactNode }[] = [
  {
    term: "Realized volatility",
    definition:
      "How much a stock's price actually moved over a period, measured from its daily returns. Higher means a bumpier ride, in either direction.",
  },
  {
    term: "Annualized, 5-day",
    definition:
      "The site predicts the volatility of the next 5 trading days and expresses it as a yearly rate so values are easy to compare. 24.0% means the stock is moving as if its yearly volatility were 24%.",
  },
  {
    term: "HAR-RV",
    definition:
      "A well-known statistical model for forecasting volatility. It is the baseline: the market is only useful if it does better.",
  },
  {
    term: "Skill",
    definition: "One prediction agent, specialized in one time horizon (short, medium, long) or one kind of signal.",
  },
  {
    term: "Supervisor",
    definition: "The part that assigns each skill a weight from its recent performance and combines their predictions.",
  },
  {
    term: "Supervisor confidence",
    definition:
      "A number from 0% to 100% reported by the engine for how much it trusts its own final prediction.",
  },
  {
    term: "Volatility trend",
    definition:
      "The prediction compared with the most recent fully realized 5-day volatility: more than 10% above is rising, more than 10% below is falling, otherwise stable. It says nothing about the stock price going up or down.",
  },
  {
    term: "Walk-forward backtest",
    definition:
      "A test where every past date is predicted using only information available on that date, never the future. It is the honest way to check a forecasting method.",
  },
  {
    term: "RMSE, MAE, QLIKE",
    definition:
      "Three ways to measure forecast error. RMSE and MAE measure the typical size of the miss (RMSE punishes big misses more); QLIKE is a standard loss designed for volatility forecasts. Lower is better for all three.",
  },
];

export default function AboutPage() {
  return (
    <main className="max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">How it works</h1>
      <p className="mt-2 text-muted">
        Temporal Skills Market tracks stocks and predicts how volatile each one will be over the next 5 trading
        days. Instead of one model, it runs a small market of specialized skills and lets a supervisor decide how
        much to trust each one.
      </p>

      <section aria-labelledby="steps-heading" className="mt-8">
        <h2 id="steps-heading" className="text-lg font-semibold">
          From data to prediction
        </h2>
        <ol className="mt-4 grid gap-3 sm:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="rounded-lg border border-border bg-surface p-4">
              <span className="font-mono text-xs text-accent">STEP {index + 1}</span>
              <h3 className="mt-1 font-semibold">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{step.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="read-heading" className="mt-10">
        <h2 id="read-heading" className="text-lg font-semibold">
          How to read a stock page
        </h2>
        <ul className="mt-4 list-disc space-y-2 pl-5 text-sm leading-relaxed">
          <li>
            <strong>Predicted volatility</strong> is the market&apos;s final answer; <strong>HAR-RV baseline</strong>{" "}
            is what the standard model says for the same dates.
          </li>
          <li>
            <strong>Skills market</strong> shows each skill&apos;s own prediction and how much weight the supervisor
            gave it.
          </li>
          <li>
            <strong>Prediction history</strong> compares past predictions with what really happened. The realized
            line stops a few days before today because the last 5 days have not all passed yet.
          </li>
          <li>
            <strong>Insights</strong> puts today&apos;s prediction in context using that history.
          </li>
        </ul>
      </section>

      <section aria-labelledby="glossary-heading" className="mt-10">
        <h2 id="glossary-heading" className="text-lg font-semibold">
          Glossary
        </h2>
        <dl className="mt-4 divide-y divide-border rounded-lg border border-border bg-surface">
          {GLOSSARY.map((entry) => (
            <div key={entry.term} className="grid gap-1 px-4 py-3 sm:grid-cols-[11rem_1fr] sm:gap-4">
              <dt className="font-medium">{entry.term}</dt>
              <dd className="text-sm leading-relaxed text-muted">{entry.definition}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="limits-heading" className="mt-10 rounded-lg border border-border bg-surface p-5">
        <h2 id="limits-heading" className="text-lg font-semibold">
          Limits
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          This is an educational project. It predicts how much a stock may move, not in which direction, and no
          forecast is guaranteed. Nothing here is investment advice.
        </p>
        <Link
          href="/"
          className="mt-4 inline-flex items-center rounded-md border border-border bg-surface-raised px-4 py-2 text-sm font-medium transition-colors hover:border-accent hover:text-accent"
        >
          Back to the watchlist
        </Link>
      </section>
    </main>
  );
}
