import type { ReactNode } from "react";

interface StateMessageProps {
  title: string;
  description?: string;
  action?: ReactNode;
  /** "error" is announced to assistive technology right away. */
  tone?: "neutral" | "error";
}

/** Shared look for empty, error and not-found states. */
export function StateMessage({ title, description, action, tone = "neutral" }: StateMessageProps) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-surface px-6 py-12 text-center"
    >
      <h2 className={`text-lg font-semibold ${tone === "error" ? "text-up" : ""}`}>{title}</h2>
      {description ? <p className="max-w-md text-sm text-muted">{description}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

export const actionClassName =
  "inline-flex items-center rounded-md border border-border bg-surface-raised px-4 py-2 text-sm font-medium transition-colors hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
