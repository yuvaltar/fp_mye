import { test } from "node:test";
import assert from "node:assert/strict";
import type { PricePoint } from "./api/extras-types.ts";
import type { HistoryPoint, ModelPerformance, SkillPrediction, WeightsPoint } from "./api/types.ts";
import {
  MIN_SCORED_POINTS,
  accuracyStats,
  bestModels,
  lastN,
  modelLabel,
  performanceSentence,
  priceChange,
  skillSpread,
  sparklinePath,
  tickerImprovement,
  volPercentile,
  weightsToRows,
} from "./derive.ts";
import { formatMetric, formatPrice, historyToCsv } from "./format.ts";

function hp(pred: number, base: number, real: number | null, date = "2026-10-01"): HistoryPoint {
  return { as_of_date: date, predicted_vol: pred, baseline_vol: base, realized_vol: real };
}

function skill(name: string, predicted: number): SkillPrediction {
  return { name, horizon: "short", weight: 0.5, predicted_vol: predicted };
}

test("accuracyStats: market closer than baseline on every scored point", () => {
  const points = Array.from({ length: MIN_SCORED_POINTS }, () => hp(0.2, 0.3, 0.21));
  const stats = accuracyStats(points);
  assert.ok(stats);
  assert.equal(stats.scored, MIN_SCORED_POINTS);
  assert.equal(stats.marketWins, MIN_SCORED_POINTS);
  assert.equal(stats.winRate, 1);
  assert.ok(Math.abs(stats.marketMae - 0.01) < 1e-9);
  assert.ok(Math.abs(stats.baselineMae - 0.09) < 1e-9);
  assert.ok((stats.maeImprovement ?? 0) > 0.8);
});

test("accuracyStats ignores pending points and needs enough data", () => {
  const few = [hp(0.2, 0.2, 0.2), hp(0.2, 0.2, null)];
  assert.equal(accuracyStats(few), null);
  const many = [
    ...Array.from({ length: MIN_SCORED_POINTS }, () => hp(0.3, 0.2, 0.2)),
    hp(9, 9, null),
  ];
  assert.equal(accuracyStats(many)?.scored, MIN_SCORED_POINTS);
});

test("accuracyStats: ties are not wins, worse market gives negative improvement", () => {
  const points = Array.from({ length: MIN_SCORED_POINTS }, () => hp(0.3, 0.21, 0.2));
  const stats = accuracyStats(points);
  assert.equal(stats?.marketWins, 0);
  assert.ok((stats?.maeImprovement ?? 0) < 0);
  const tied = Array.from({ length: MIN_SCORED_POINTS }, () => hp(0.25, 0.15, 0.2));
  assert.equal(accuracyStats(tied)?.marketWins, 0);
});

test("volPercentile ranks a value among past realized volatilities", () => {
  const points = [0.1, 0.2, 0.3, 0.4, 0.5].map((v) => hp(0, 0, v));
  assert.equal(volPercentile(0.35, points), 0.6);
  assert.equal(volPercentile(0.05, points), 0);
  assert.equal(volPercentile(0.9, points), 1);
});

test("volPercentile is null with too little history", () => {
  assert.equal(volPercentile(0.3, [hp(0, 0, 0.2), hp(0, 0, null)]), null);
  assert.equal(volPercentile(0.3, []), null);
});

test("skillSpread finds the lowest and highest skill", () => {
  const spread = skillSpread([skill("a", 0.2), skill("b", 0.3), skill("c", 0.25)]);
  assert.equal(spread?.minSkill.name, "a");
  assert.equal(spread?.maxSkill.name, "b");
  assert.ok(Math.abs((spread?.range ?? 0) - 0.1) < 1e-9);
  assert.equal(skillSpread([skill("a", 0.2)]), null);
  assert.equal(skillSpread([]), null);
});

test("lastN", () => {
  assert.deepEqual(lastN([1, 2, 3, 4], 2), [3, 4]);
  assert.deepEqual(lastN([1, 2, 3], null), [1, 2, 3]);
  assert.deepEqual(lastN([1, 2, 3], 10), [1, 2, 3]);
  assert.deepEqual(lastN([1, 2, 3], 0), []);
});

test("priceChange", () => {
  const points: PricePoint[] = [
    { date: "2026-10-01", close: 100 },
    { date: "2026-10-02", close: 110 },
  ];
  const change = priceChange(points);
  assert.equal(change?.absolute, 10);
  assert.ok(Math.abs((change?.relative ?? 0) - 0.1) < 1e-9);
  assert.equal(priceChange([]), null);
  assert.equal(priceChange([{ date: "2026-10-01", close: 5 }]), null);
  assert.equal(priceChange([{ date: "a", close: 0 }, { date: "b", close: 1 }]), null);
});

test("weightsToRows flattens weights per date", () => {
  const points: WeightsPoint[] = [
    { as_of_date: "2026-10-01", weights: [{ name: "a", weight: 0.4 }, { name: "b", weight: 0.6 }] },
  ];
  assert.deepEqual(weightsToRows(points), [{ as_of_date: "2026-10-01", a: 0.4, b: 0.6 }]);
});

const MODELS: ModelPerformance[] = [
  { name: "supervisor", kind: "supervisor", rmse: 0.04, mae: 0.03, qlike: 0.12, rmse_vs_har_rv: 0.2, mae_vs_har_rv: 0, qlike_vs_har_rv: 0.2 },
  { name: "har_rv", kind: "baseline", rmse: 0.05, mae: 0.03, qlike: 0.15, rmse_vs_har_rv: null, mae_vs_har_rv: null, qlike_vs_har_rv: null },
];

test("bestModels returns the lowest, including ties", () => {
  assert.deepEqual(bestModels(MODELS, "rmse"), ["supervisor"]);
  assert.deepEqual(bestModels(MODELS, "mae"), ["supervisor", "har_rv"]);
  assert.deepEqual(bestModels([], "rmse"), []);
});

test("tickerImprovement is 1 - supervisor / baseline", () => {
  assert.ok(Math.abs((tickerImprovement({ ticker: "AAPL", supervisor_qlike: 0.4267, baseline_qlike: 0.4675 }) ?? 0) - 0.0873) < 1e-3);
  assert.equal(tickerImprovement({ ticker: "X", supervisor_qlike: 0.5, baseline_qlike: 0 }), null);
  assert.ok((tickerImprovement({ ticker: "X", supervisor_qlike: 0.6, baseline_qlike: 0.5 }) ?? 0) < 0);
});

const HEADLINE = { metric: "qlike", supervisor: 0.4862, baseline: 0.546, improvement: 0.1095, tickers_better: 52, tickers_total: 52, t_statistic: 4.75 } as const;

test("performanceSentence: a solid win says so, with the numbers", () => {
  assert.equal(
    performanceSentence(HEADLINE),
    "The supervisor beats the HAR-RV baseline on QLIKE: 0.4862 against 0.5460 (+10.9%), and is better than HAR-RV on 52 of 52 tickers. The difference is statistically solid (t-statistic 4.75; about 2 or more is the usual bar).",
  );
});

test("performanceSentence: a loss or weak evidence is not dressed up", () => {
  const worse = performanceSentence({ ...HEADLINE, supervisor: 0.6, improvement: -0.0989, tickers_better: 10, t_statistic: 1.2 });
  assert.match(worse, /^The supervisor does not beat the HAR-RV baseline on QLIKE: 0\.6000 against 0\.5460 \(-9\.9%\)/);
  assert.match(worse, /better than HAR-RV on 10 of 52 tickers/);
  assert.match(worse, /The evidence is weak \(t-statistic 1\.20, below the usual bar of about 2\), so the difference could be chance\.$/);
  const weakWin = performanceSentence({ ...HEADLINE, t_statistic: 1.5 });
  assert.match(weakWin, /^The supervisor beats/);
  assert.match(weakWin, /could be chance/);
});

test("modelLabel", () => {
  assert.equal(modelLabel("har_rv"), "HAR-RV baseline");
  assert.equal(modelLabel("short_trend"), "Short trend");
  assert.equal(modelLabel("new_thing"), "New thing");
});

test("sparklinePath draws a line and breaks it at nulls", () => {
  const path = sparklinePath([1, 2, 3], 100, 20);
  assert.ok(path.startsWith("M2.0 18.0"));
  assert.equal(path.split("L").length, 3);
  const broken = sparklinePath([1, null, 3], 100, 20);
  assert.equal(broken.split("M").length - 1, 2);
  assert.equal(sparklinePath([], 100, 20), "");
  assert.equal(sparklinePath([null, null], 100, 20), "");
});

test("sparklinePath handles flat and single-value series", () => {
  assert.notEqual(sparklinePath([5, 5, 5], 100, 20), "");
  assert.ok(sparklinePath([7], 100, 20).startsWith("M2.0"));
});

test("formatPrice and formatMetric", () => {
  assert.equal(formatPrice(227.5, "USD"), "$227.50");
  assert.equal(formatPrice(1234567.891, "USD"), "$1,234,567.89");
  assert.equal(formatPrice(10, "CHF"), "10.00 CHF");
  assert.equal(formatPrice(null, "USD"), "—");
  assert.equal(formatMetric(0.04123), "0.0412");
  assert.equal(formatMetric(Number.NaN), "—");
});

test("historyToCsv keeps raw decimals and leaves pending realized empty", () => {
  const csv = historyToCsv("AAPL", [hp(0.2251, 0.212, 0.2013, "2026-09-17"), hp(0.22, 0.23, null, "2026-10-01")]);
  assert.equal(
    csv,
    [
      "ticker,as_of_date,predicted_vol,baseline_vol,realized_vol",
      "AAPL,2026-09-17,0.2251,0.212,0.2013",
      "AAPL,2026-10-01,0.22,0.23,",
      "",
    ].join("\n"),
  );
});
