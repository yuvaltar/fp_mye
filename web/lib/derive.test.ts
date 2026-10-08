import { test } from "node:test";
import assert from "node:assert/strict";
import type { HistoryPoint, SkillPrediction } from "./api/types.ts";
import {
  TREND_THRESHOLD,
  baselineSentence,
  getTrend,
  hasDominantSkill,
  horizonLabel,
  latestRealizedVol,
  relativeDifference,
  skillLabel,
  skillsSentence,
  sortSkillsByWeight,
  topSkill,
} from "./derive.ts";

function point(realized: number | null, date = "2026-10-01"): HistoryPoint {
  return { as_of_date: date, predicted_vol: 0.2, baseline_vol: 0.2, realized_vol: realized };
}

function skill(name: string, weight: number, predicted = 0.2): SkillPrediction {
  return { name, horizon: "short", weight, predicted_vol: predicted };
}

test("latestRealizedVol skips trailing nulls and returns the latest value", () => {
  assert.equal(latestRealizedVol([point(0.2), point(0.3), point(null), point(null)]), 0.3);
});

test("latestRealizedVol is null when there is no realized value", () => {
  assert.equal(latestRealizedVol([]), null);
  assert.equal(latestRealizedVol([point(null), point(null)]), null);
});

test("getTrend: above the threshold is rising", () => {
  assert.equal(getTrend(0.25, [point(0.2)]), "rising");
});

test("getTrend: below the negative threshold is falling", () => {
  assert.equal(getTrend(0.17, [point(0.2)]), "falling");
});

test("getTrend: within the threshold is stable", () => {
  assert.equal(getTrend(0.21, [point(0.2)]), "stable");
  assert.equal(getTrend(0.19, [point(0.2)]), "stable");
});

test("getTrend: exactly on the threshold is stable", () => {
  const latest = 1;
  assert.equal(getTrend(latest * (1 + TREND_THRESHOLD), [point(latest)]), "stable");
  assert.equal(getTrend(latest * (1 - TREND_THRESHOLD), [point(latest)]), "stable");
});

test("getTrend: no data when history has no realized value or it is not positive", () => {
  assert.equal(getTrend(0.2, []), "no-data");
  assert.equal(getTrend(0.2, [point(null)]), "no-data");
  assert.equal(getTrend(0.2, [point(0)]), "no-data");
});

test("getTrend uses the latest non-null realized value, not the first", () => {
  assert.equal(getTrend(0.3, [point(0.3), point(0.2), point(null)]), "rising");
});

test("relativeDifference", () => {
  assert.ok(Math.abs((relativeDifference(0.22, 0.2) ?? 0) - 0.1) < 1e-9);
  assert.equal(relativeDifference(0.2, 0), null);
  assert.equal(relativeDifference(Number.NaN, 0.2), null);
});

test("skillLabel maps known names", () => {
  assert.equal(skillLabel("short_trend"), "Short trend");
  assert.equal(skillLabel("seasonality"), "Seasonality");
});

test("skillLabel auto-formats unknown names", () => {
  assert.equal(skillLabel("garch_forecast"), "Garch forecast");
  assert.equal(skillLabel("momentum"), "Momentum");
  assert.equal(skillLabel("_odd__name_"), "Odd name");
});

test("horizonLabel", () => {
  assert.equal(horizonLabel("long"), "Long horizon");
});

test("sortSkillsByWeight orders by weight and does not mutate the input", () => {
  const skills = [skill("a", 0.2), skill("b", 0.5), skill("c", 0.3)];
  assert.deepEqual(
    sortSkillsByWeight(skills).map((s) => s.name),
    ["b", "c", "a"],
  );
  assert.deepEqual(skills.map((s) => s.name), ["a", "b", "c"]);
});

test("sortSkillsByWeight keeps the original order for equal weights", () => {
  const skills = [skill("a", 0.5), skill("b", 0.5)];
  assert.deepEqual(sortSkillsByWeight(skills).map((s) => s.name), ["a", "b"]);
});

test("topSkill and hasDominantSkill", () => {
  assert.equal(topSkill([]), null);
  assert.equal(hasDominantSkill([]), false);
  assert.equal(hasDominantSkill([skill("a", 0.34), skill("b", 0.33), skill("c", 0.33)]), false);
  assert.equal(hasDominantSkill([skill("a", 0.35), skill("b", 0.65)]), true);
});

test("skillsSentence: dominant skill above the baseline", () => {
  const sentence = skillsSentence(
    [skill("short_trend", 0.41, 0.521), skill("seasonality", 0.59, 0.441)],
    0.468,
  );
  assert.equal(
    sentence,
    "Seasonality dominates with 59% of the weight, predicting 44.1%, below the HAR-RV baseline of 46.8%.",
  );
});

test("skillsSentence: no dominant skill", () => {
  const sentence = skillsSentence(
    [skill("short_trend", 0.34, 0.231), skill("medium_trend", 0.33, 0.219), skill("seasonality", 0.33, 0.205)],
    0.212,
  );
  assert.equal(
    sentence,
    "No single skill dominates: the largest share is Short trend at 34%, predicting 23.1%, above the HAR-RV baseline of 21.2%.",
  );
});

test("skillsSentence: in line with the baseline", () => {
  const sentence = skillsSentence([skill("short_trend", 1, 0.2)], 0.201);
  assert.equal(
    sentence,
    "Short trend dominates with 100% of the weight, predicting 20.0%, in line with the HAR-RV baseline of 20.1%.",
  );
});

test("skillsSentence: nothing to say without skills", () => {
  assert.equal(skillsSentence([], 0.2), null);
});

test("skillsSentence: omits the comparison when the baseline is unusable", () => {
  assert.equal(
    skillsSentence([skill("short_trend", 1, 0.2)], 0),
    "Short trend dominates with 100% of the weight, predicting 20.0%.",
  );
});

test("baselineSentence", () => {
  assert.equal(
    baselineSentence(0.2251, 0.212),
    "The market's prediction is 6.2% higher than the HAR-RV baseline of 21.2%.",
  );
  assert.equal(
    baselineSentence(0.18, 0.2),
    "The market's prediction is 10.0% lower than the HAR-RV baseline of 20.0%.",
  );
  assert.equal(
    baselineSentence(0.2, 0.2),
    "The market's prediction is in line with the HAR-RV baseline of 20.0%.",
  );
  assert.equal(baselineSentence(0.2, 0), null);
});
