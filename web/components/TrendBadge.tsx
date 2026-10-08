import type { Trend } from "@/lib/derive";

const STYLES: Record<Trend, { label: string; glyph: string; className: string }> = {
  rising: { label: "Rising", glyph: "▲", className: "text-up border-up/40 bg-up/10" },
  falling: { label: "Falling", glyph: "▼", className: "text-down border-down/40 bg-down/10" },
  stable: { label: "Stable", glyph: "▬", className: "text-neutral border-border bg-surface-raised" },
  "no-data": { label: "No data", glyph: "–", className: "text-muted border-border bg-transparent" },
};

export function TrendBadge({ trend }: { trend: Trend }) {
  const style = STYLES[trend];
  return (
    <span
      title="Predicted volatility compared with the latest realized volatility"
      aria-label={`Volatility trend: ${style.label.toLowerCase()}`}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${style.className}`}
    >
      <span aria-hidden="true" className="text-[0.65rem] leading-none">
        {style.glyph}
      </span>
      {style.label}
    </span>
  );
}
