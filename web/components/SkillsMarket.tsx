import type { SkillPrediction } from "@/lib/api/types";
import {
  horizonLabel,
  relativeDifference,
  skillLabel,
  skillsSentence,
  sortSkillsByWeight,
} from "@/lib/derive";
import { formatShare, formatSignedPercent, formatVol } from "@/lib/format";
import { StateMessage } from "./StateMessage";

/** Series colors by position in the original skills[] order (stable per skill). */
const SERIES_BG = [
  "bg-series-1",
  "bg-series-2",
  "bg-series-3",
  "bg-series-4",
  "bg-series-5",
  "bg-series-6",
];

interface SkillsMarketProps {
  skills: SkillPrediction[];
  baselineVol: number;
}

export function SkillsMarket({ skills, baselineVol }: SkillsMarketProps) {
  if (skills.length === 0) {
    return (
      <StateMessage
        title="No skills reported"
        description="The engine returned no skill breakdown for this prediction."
      />
    );
  }

  const colorOf = (skill: SkillPrediction) =>
    SERIES_BG[skills.indexOf(skill) % SERIES_BG.length] ?? "bg-series-1";
  const sentence = skillsSentence(skills, baselineVol);
  const ordered = sortSkillsByWeight(skills);

  return (
    <section aria-labelledby="skills-heading" className="rounded-lg border border-border bg-surface p-5">
      <h2 id="skills-heading" className="text-base font-semibold">
        Skills market
      </h2>
      <p className="mt-1 text-sm text-muted">
        Each skill predicts volatility on its own; the supervisor weights them by recent performance.
      </p>

      <div
        role="img"
        aria-label="Weight of each skill"
        className="mt-4 flex h-3 w-full overflow-hidden rounded-full bg-surface-raised"
      >
        {ordered.map((skill) => (
          <div
            key={skill.name}
            className={colorOf(skill)}
            style={{ width: `${skill.weight * 100}%` }}
            title={`${skillLabel(skill.name)}: ${formatShare(skill.weight)}`}
          />
        ))}
      </div>

      <ul className="mt-5 divide-y divide-border">
        {ordered.map((skill) => {
          const diff = relativeDifference(skill.predicted_vol, baselineVol);
          return (
            <li key={skill.name} className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 py-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <span aria-hidden="true" className={`size-2.5 shrink-0 rounded-sm ${colorOf(skill)}`} />
                <span className="truncate font-medium">{skillLabel(skill.name)}</span>
                <span className="hidden text-xs text-muted sm:inline">{horizonLabel(skill.horizon)}</span>
              </div>
              <div className="text-right font-mono text-sm tabular-nums">
                <span className="font-semibold">{formatVol(skill.predicted_vol)}</span>
                <span className="ml-2 text-xs text-muted">{formatSignedPercent(diff)} vs baseline</span>
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-raised">
                  <div
                    className={`h-full rounded-full ${colorOf(skill)}`}
                    style={{ width: `${skill.weight * 100}%` }}
                  />
                </div>
                <span className="w-10 text-right font-mono text-xs tabular-nums text-muted">
                  {formatShare(skill.weight)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>

      {sentence ? <p className="mt-2 border-t border-border pt-4 text-sm">{sentence}</p> : null}
    </section>
  );
}
