import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  NotReadyError,
  getHistory,
  getPrediction,
} from "./api/client.ts";
import {
  VOL_CALM_BELOW,
  VOL_CRISIS_ABOVE,
  VOL_STORMY_ABOVE,
  downsampleWeekly,
  skillColorIndex,
  skillDescription,
  skillLabel,
  sliceByDays,
  volLevel,
} from "./derive.ts";
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
