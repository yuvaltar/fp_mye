import type { HistoryPoint, Prediction } from "@/lib/api/types";
import {
  MIN_SCORED_POINTS,
  accuracyStats,
  skillLabel,
  skillSpread,
  volPercentile,
} from "@/lib/derive";
import { formatShare, formatSignedPercent, formatVol } from "@/lib/format";

interface InsightsPanelProps {
  prediction: Prediction;
  points: HistoryPoint[] | null;
}

/**
 * Three plain facts computed from the data already on the page: how the
 * prediction compares with the past, how far apart the skills are, and how
 * the market has done against the baseline so far.
 */
export function InsightsPanel({ prediction, points }: InsightsPanelProps) {
  const percentile = points ? volPercentile(prediction.predicted_vol, points) : null;
  const spread = skillSpread(prediction.skills);
  const accuracy = points ? accuracyStats(points) : null;

  return (
    <section aria-labelledby="insights-heading" className="rounded-lg border border-border bg-surface p-5">
      <h2 id="insights-heading" className="text-base font-semibold">
        Insights
      </h2>
      <ul className="mt-4 space-y-5">
        <Insight title="Compared with the past">
          {percentile === null ? (
            <Muted>Not enough realized history yet (needs {MIN_SCORED_POINTS} points).</Muted>
          ) : (
            <>
              This prediction is higher than{" "}
              <strong className="font-mono">{formatShare(percentile)}</strong> of past realized
              volatilities in the history shown.
            </>
          )}
        </Insight>

        <Insight title="Do the skills agree?">
          {spread === null ? (
            <Muted>At least two skills are needed to compare them.</Muted>
          ) : (
            <>
              Skill predictions range from{" "}
              <strong className="font-mono">{formatVol(spread.minSkill.predicted_vol)}</strong> (
              {skillLabel(spread.minSkill.name)}) to{" "}
              <strong className="font-mono">{formatVol(spread.maxSkill.predicted_vol)}</strong> (
              {skillLabel(spread.maxSkill.name)}), a spread of{" "}
              <strong className="font-mono">{formatVol(spread.range)}</strong>. A wide spread means the skills
              disagree.
            </>
          )}
        </Insight>

        <Insight title="Track record vs HAR-RV">
          {accuracy === null ? (
            <Muted>Not enough realized history yet (needs {MIN_SCORED_POINTS} scored dates).</Muted>
          ) : (
            <>
              Over <strong className="font-mono">{accuracy.scored}</strong> scored dates the market was closer to
              reality than HAR-RV on{" "}
              <strong className="font-mono">
                {accuracy.marketWins} ({formatShare(accuracy.winRate)})
              </strong>
              . Average error: market{" "}
              <strong className="font-mono">{formatVol(accuracy.marketMae)}</strong> vs HAR-RV{" "}
              <strong className="font-mono">{formatVol(accuracy.baselineMae)}</strong>
              {accuracy.maeImprovement !== null ? (
                <>
                  {" "}
                  (<span className="font-mono">{formatSignedPercent(accuracy.maeImprovement)}</span> error
                  reduction)
                </>
              ) : null}
              .
            </>
          )}
        </Insight>
      </ul>
    </section>
  );
}

function Insight({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <li>
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted">{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed">{children}</p>
    </li>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return <span className="text-muted">{children}</span>;
}
