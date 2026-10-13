import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  NotReadyError,
  getHistory,
  getOverview,
  getPrediction,
  getTickers,
} from "./api/client.ts";
import {
  AXIS_YEAR_THRESHOLD_DAYS,
  VOL_CALM_BELOW,
  VOL_CRISIS_ABOVE,
  VOL_STORMY_ABOVE,
  downsampleWeekly,
  modelLabel,
  skillColorIndex,
  skillDescription,
  skillLabel,
  sliceByDays,
  spanDays,
  weightsToRows,
  volLevel,
} from "./derive.ts";
import { formatMonthYear, formatWeekday } from "./format.ts";
import { loadWatchlist } from "./watchlist.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete process.env.NEXT_PUBLIC_USE_MOCKS;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
});

test("the engine's real skill names get readable labels", () => {
  assert.equal(skillLabel("short_term"), "HAR-RV");
  assert.equal(skillLabel("regime"), "GARCH");
  assert.equal(skillLabel("weak_signals"), "Boosting");
  assert.equal(skillLabel("multivariate"), "iTransformer");
});

test("a new, unknown skill name still gets a label and no description", () => {
  assert.equal(skillLabel("multivariate_graph"), "Multivariate graph");
  assert.equal(skillDescription("multivariate_graph"), null);
  assert.ok(skillDescription("regime")?.includes("storms"));
});

test("skill colors are stable per name and distinct for the known members", () => {
  const real = ["short_term", "weak_signals", "regime", "multivariate"].map(skillColorIndex);
  assert.equal(new Set(real).size, 4);
  assert.equal(skillColorIndex("short_term"), skillColorIndex("short_term"));
  for (const name of ["brand_new", "another_one", "x"]) {
    const slot = skillColorIndex(name);
    assert.ok(slot === 4 || slot === 5, `${name} -> ${slot}`);
    assert.equal(slot, skillColorIndex(name));
  }
  assert.ok(!real.includes(skillColorIndex("brand_new")));
});

test("volLevel follows the documented scale", () => {
  assert.equal(volLevel(0.05), "calm");
  assert.equal(volLevel(VOL_CALM_BELOW), "typical");
  assert.equal(volLevel(0.24), "typical");
  assert.equal(volLevel(VOL_STORMY_ABOVE), "typical");
  assert.equal(volLevel(0.6), "stormy");
  assert.equal(volLevel(VOL_CRISIS_ABOVE), "stormy");
  assert.equal(volLevel(1.4), "crisis");
});

const dated = (iso: string) => ({ iso });

test("sliceByDays keeps the last N calendar days relative to the latest item", () => {
  const items = ["2026-01-01", "2026-06-01", "2026-09-01", "2026-10-01", "2026-10-07"].map(dated);
  assert.deepEqual(
    sliceByDays(items, 31, (i) => i.iso).map((i) => i.iso),
    ["2026-10-01", "2026-10-07"],
  );
  assert.deepEqual(
    sliceByDays(items, 183, (i) => i.iso).map((i) => i.iso),
    ["2026-06-01", "2026-09-01", "2026-10-01", "2026-10-07"],
  );
  assert.equal(sliceByDays(items, null, (i) => i.iso).length, 5);
  assert.deepEqual(sliceByDays([], 30, (i: { iso: string }) => i.iso), []);
});

test("downsampleWeekly keeps one item per week, the last one, in order", () => {
  // Mon 5 Oct .. Fri 9 Oct 2026, then Mon 12 and Tue 13.
  const days = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"];
  const result = downsampleWeekly(days.map(dated), (i) => i.iso).map((i) => i.iso);
  assert.deepEqual(result, ["2026-10-09", "2026-10-13"]);
  assert.deepEqual(downsampleWeekly([], (i: { iso: string }) => i.iso), []);
});

test("downsampleWeekly turns 2,200 daily points into a few hundred", () => {
  const start = Date.UTC(2018, 0, 2);
  const items: { iso: string }[] = [];
  for (let d = 0; items.length < 2203; d++) {
    const date = new Date(start + d * 86_400_000);
    if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6) items.push({ iso: date.toISOString().slice(0, 10) });
  }
  const weekly = downsampleWeekly(items, (i) => i.iso);
  assert.ok(weekly.length > 400 && weekly.length < 480, `got ${weekly.length}`);
  assert.equal(weekly[weekly.length - 1]?.iso, items[items.length - 1]?.iso);
});

test("HTTP 503 from the engine becomes NotReadyError", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "not ready" }), { status: 503 });
  await assert.rejects(getPrediction("AAPL"), NotReadyError);
  await assert.rejects(getHistory("AAPL"), NotReadyError);
});

test("watchlist: a 503 on predictions lists the tickers without numbers instead of failing", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url.endsWith("/tickers")) {
      return new Response(JSON.stringify({ tickers: [{ ticker: "AAPL", name: "Apple Inc." }] }), { status: 200 });
    }
    return new Response("{}", { status: 503 });
  };
  const { rows } = await loadWatchlist();
  assert.deepEqual(rows.map((r) => r.status), ["no-prediction"]);
});

test("spanDays counts calendar days and AXIS_YEAR_THRESHOLD_DAYS decides when axes need the year", () => {
  assert.equal(spanDays("2026-10-01", "2026-10-08"), 7);
  assert.equal(spanDays("2026-10-08", "2026-10-01"), -7);
  assert.equal(spanDays("2018-01-02", "2026-10-07") > AXIS_YEAR_THRESHOLD_DAYS, true);
  assert.equal(spanDays("2026-04-09", "2026-10-07") > AXIS_YEAR_THRESHOLD_DAYS, false);
});

test("formatMonthYear", () => {
  assert.equal(formatMonthYear("2026-10-07"), "Oct 2026");
  assert.equal(formatMonthYear("2018-01-02"), "Jan 2018");
  assert.equal(formatMonthYear("garbage"), "garbage");
});

test("itransformer, the engine's own model, has a label, a description and a stable color", () => {
  assert.equal(skillLabel("itransformer"), "iTransformer");
  assert.ok(skillDescription("itransformer")?.includes("Our own"));
  assert.equal(skillColorIndex("itransformer"), 3);
  const real = ["short_term", "weak_signals", "regime", "itransformer"].map(skillColorIndex);
  assert.equal(new Set(real).size, 4);
});

test("modelLabel keeps the HAR-RV skill and the HAR-RV baseline apart when both are shown", () => {
  assert.equal(modelLabel("har_rv"), "HAR-RV baseline");
  // Without the baseline row (an engine without the earnings layer) short_term is HAR-RV itself.
  assert.equal(modelLabel("short_term", ["supervisor", "short_term"]), "HAR-RV");
  assert.equal(modelLabel("short_term", ["supervisor", "har_rv", "short_term"]), "HAR-RV + earnings jump");
  assert.notEqual(
    modelLabel("short_term", ["har_rv", "short_term"]),
    modelLabel("har_rv", ["har_rv", "short_term"]),
  );
});

test("formatWeekday names the day, including a Saturday report", () => {
  assert.equal(formatWeekday("2026-10-13"), "Tuesday");
  assert.equal(formatWeekday("2026-10-08"), "Thursday");
  assert.equal(formatWeekday("2026-10-10"), "Saturday");
  assert.equal(formatWeekday("nope"), "nope");
});

test("engine requests carry a generous timeout signal", async () => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "false";
  const signals: (AbortSignal | null | undefined)[] = [];
  globalThis.fetch = async (_input, init) => {
    signals.push(init?.signal);
    return new Response(JSON.stringify({ tickers: [], entries: [] }), { status: 200 });
  };
  await getTickers();
  await getOverview();
  assert.equal(signals.length, 2);
  assert.ok(signals.every((s) => s instanceof AbortSignal && !s.aborted));
});

test("weights that sum to 1 within 1e-6 are fine: the site never compares them exactly", async () => {
  const total = [0.21079, 0.216739, 0.296992, 0.27548].reduce((a, b) => a + b, 0);
  assert.notEqual(total, 1);
  assert.ok(Math.abs(total - 1) < 1e-5);
  const rows = weightsToRows([
    { as_of_date: "2026-10-07", weights: [{ name: "a", weight: 0.21079 }, { name: "b", weight: 0.789211 }] },
  ]);
  assert.equal(rows[0]?.a, 0.21079);
});
