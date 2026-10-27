import Link from "next/link";

/** Permanent legal footer on every page. */
export function SiteFooter() {
  return (
    <footer className="mt-12 border-t border-border">
      <div className="mx-auto w-full max-w-6xl px-4 py-6 text-xs leading-relaxed text-muted sm:px-6">
        <p>
          Educational project. Nothing on this site, including the AI assistant, is financial, investment, tax
          or legal advice, or a recommendation to buy, sell or hold anything. Volatility is the size of price
          moves, not their direction. Predictions can be wrong; prices are delayed.{" "}
          <Link href="/disclaimer" className="underline underline-offset-2 hover:text-text">
            Read the full disclaimer
          </Link>
          .
        </p>
      </div>
    </footer>
  );
}
