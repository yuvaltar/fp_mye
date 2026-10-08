import { baselineSentence } from "@/lib/derive";
import { formatVol } from "@/lib/format";

interface PredictionVsBaselineProps {
  predictedVol: number;
  baselineVol: number;
}

/** The market's prediction next to the HAR-RV baseline, as comparable bars. */
export function PredictionVsBaseline({ predictedVol, baselineVol }: PredictionVsBaselineProps) {
  const scale = Math.max(predictedVol, baselineVol, Number.EPSILON);
  const sentence = baselineSentence(predictedVol, baselineVol);

  return (
    <section aria-labelledby="vs-baseline-heading" className="rounded-lg border border-border bg-surface p-5">
      <h2 id="vs-baseline-heading" className="text-base font-semibold">
        Prediction vs baseline
      </h2>
      <p className="mt-1 text-sm text-muted">
        HAR-RV is a standard volatility model; every result is compared with it.
      </p>
      <dl className="mt-4 space-y-4">
        <Bar label="Market prediction" value={predictedVol} scale={scale} barClassName="bg-accent" />
        <Bar label="HAR-RV baseline" value={baselineVol} scale={scale} barClassName="bg-neutral" />
      </dl>
      {sentence ? <p className="mt-4 text-sm">{sentence}</p> : null}
    </section>
  );
}

function Bar({
  label,
  value,
  scale,
  barClassName,
}: {
  label: string;
  value: number;
  scale: number;
  barClassName: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <dt className="text-muted">{label}</dt>
        <dd className="font-mono font-semibold tabular-nums">{formatVol(value)}</dd>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-surface-raised">
        <div className={`h-full rounded-full ${barClassName}`} style={{ width: `${(value / scale) * 100}%` }} />
      </div>
    </div>
  );
}
