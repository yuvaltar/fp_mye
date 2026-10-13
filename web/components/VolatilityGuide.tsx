import {
  VOL_REFERENCE_SOURCE,
  VOL_CALM_BELOW,
  VOL_CRISIS_ABOVE,
  VOL_STORMY_ABOVE,
  VOL_TYPICAL,
  volLevel,
  type VolLevel,
} from "@/lib/derive";
import { formatVol } from "@/lib/format";

const LEVEL_LABEL: Record<VolLevel, string> = {
  calm: "Calm",
  typical: "Typical",
  stormy: "Stormy",
  crisis: "Crisis level",
};

/** Scale ends at twice the crisis line; anything above is pinned to the right edge. */
const SCALE_MAX = VOL_CRISIS_ABOVE * 1.2;

const STEPS = [
  { from: 0, label: `Calm: under ${formatVol(VOL_CALM_BELOW)}`, className: "bg-down/60" },
  { from: VOL_CALM_BELOW, label: `Typical: around ${formatVol(VOL_TYPICAL)}`, className: "bg-neutral/60" },
  { from: VOL_STORMY_ABOVE, label: `Stormy: over ${formatVol(VOL_STORMY_ABOVE)}`, className: "bg-up/70" },
  { from: VOL_CRISIS_ABOVE, label: `Crises: over ${formatVol(VOL_CRISIS_ABOVE)}`, className: "bg-up" },
] as const;

/** Plain-language explanation of volatility with the prediction placed on the scale. */
export function VolatilityGuide({ predictedVol }: { predictedVol: number }) {
  const level = volLevel(predictedVol);
  const marker = Math.min(1, predictedVol / SCALE_MAX) * 100;

  return (
    <section aria-labelledby="guide-heading" className="rounded-lg border border-border bg-surface p-5">
      <h2 id="guide-heading" className="text-base font-semibold">
        What is volatility?
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        Volatility measures how hard a stock&apos;s price jumps around, regardless of direction. It is
        shown as an annual rate: 24.0% means the stock is moving as if its yearly volatility were 24%. It
        says how much the price may move, not whether it will go up or down.
      </p>

      <div className="mt-5">
        <div className="relative h-3 w-full overflow-hidden rounded-full bg-surface-raised">
          {STEPS.map((step, i) => {
            const next = STEPS[i + 1]?.from ?? SCALE_MAX;
            return (
              <div
                key={step.from}
                className={`absolute inset-y-0 ${step.className}`}
                style={{ left: `${(step.from / SCALE_MAX) * 100}%`, width: `${((next - step.from) / SCALE_MAX) * 100}%` }}
              />
            );
          })}
          <div
            aria-hidden="true"
            className="absolute inset-y-0 w-1 -translate-x-1/2 rounded-full bg-text"
            style={{ left: `${marker}%` }}
          />
        </div>
        <p className="mt-3 text-sm">
          This prediction, <span className="font-mono font-semibold">{formatVol(predictedVol)}</span>, is{" "}
          <strong>{LEVEL_LABEL[level].toLowerCase()}</strong> on this scale.
        </p>
        <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          {STEPS.map((step) => (
            <li key={step.from} className="flex items-center gap-2">
              <span aria-hidden="true" className={`size-2 rounded-sm ${step.className}`} />
              {step.label}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">
          Typical levels come from {VOL_REFERENCE_SOURCE}.
        </p>
      </div>
    </section>
  );
}
