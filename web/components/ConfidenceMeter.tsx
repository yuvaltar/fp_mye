import { formatShare } from "@/lib/format";

/** Supervisor confidence (0..1) as a labelled bar. */
export function ConfidenceMeter({ value }: { value: number }) {
  const clamped = Math.min(1, Math.max(0, value));
  return (
    <div className="w-full">
      <div className="font-mono text-2xl font-semibold tabular-nums">
        {formatShare(clamped)}
      </div>
      <div
        role="meter"
        aria-label="Supervisor confidence"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped * 100)}
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-raised"
      >
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
    </div>
  );
}
