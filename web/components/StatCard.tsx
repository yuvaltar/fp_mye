import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  children: ReactNode;
  hint?: string;
}

/** A labelled value block used in the stock page summary row. */
export function StatCard({ label, children, hint }: StatCardProps) {
  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted">{label}</h3>
      <div className="mt-2">{children}</div>
      {hint ? <p className="mt-2 text-xs text-muted">{hint}</p> : null}
    </section>
  );
}
