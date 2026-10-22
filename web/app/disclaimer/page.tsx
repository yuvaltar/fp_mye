import Link from "next/link";
import { DISCLAIMER_SECTIONS, DISCLAIMER_SHORT } from "@/lib/ai/policy";

export const metadata = {
  title: "Disclaimer · Temporal Skills Market",
  description: "Legal notice: educational information only, not financial advice.",
};

export default function DisclaimerPage() {
  return (
    <main className="max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">Disclaimer</h1>
      <p className="mt-3 rounded-lg border border-up/40 bg-up/10 px-4 py-3 text-sm font-medium leading-relaxed">
        {DISCLAIMER_SHORT}
      </p>

      {DISCLAIMER_SECTIONS.map((section) => (
        <section key={section.title} className="mt-8" aria-labelledby={`h-${section.title}`}>
          <h2 id={`h-${section.title}`} className="text-lg font-semibold">
            {section.title}
          </h2>
          {section.paragraphs.map((paragraph) => (
            <p key={paragraph} className="mt-2 text-sm leading-relaxed text-muted">
              {paragraph}
            </p>
          ))}
        </section>
      ))}

      <p className="mt-10 text-sm">
        <Link href="/" className="text-accent underline underline-offset-2">
          Back to the watchlist
        </Link>
      </p>
    </main>
  );
}
