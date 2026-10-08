import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PAGE_SIZE,
  filterBySector,
  filterRows,
  paginate,
  sectorsOf,
  sortRows,
  type WatchlistRow,
} from "./watchlist-rows.ts";

function row(
  ticker: string,
  name: string,
  predicted: number,
  trend: "rising" | "stable" | "falling" | "no-data" = "stable",
  sector?: string,
): WatchlistRow {
  return {
    status: "ok",
    ticker,
    name,
    ...(sector === undefined ? {} : { sector }),
    predictedVol: predicted,
    baselineVol: predicted,
    confidence: predicted,
    asOfDate: "2026-10-07",
    trend,
    spark: [predicted],
  };
}

const broken: WatchlistRow = { status: "unavailable", ticker: "BAD", name: "Broken" };
const none: WatchlistRow = { status: "no-prediction", ticker: "ZED", name: "Zed Corp", sector: "Energy" };
const rows = [
  row("AAPL", "Apple Inc.", 0.2, "stable", "Information Technology"),
  row("TEVA", "Teva Pharma", 0.4, "rising", "Health Care"),
  broken,
  none,
  row("NVDA", "NVIDIA", 0.3, "falling", "Information Technology"),
];

test("sortRows by predicted vol: rows without a value always last", () => {
  assert.deepEqual(sortRows(rows, "predicted", "desc").map((r) => r.ticker), ["TEVA", "NVDA", "AAPL", "BAD", "ZED"]);
  assert.deepEqual(sortRows(rows, "predicted", "asc").map((r) => r.ticker), ["AAPL", "NVDA", "TEVA", "BAD", "ZED"]);
});

test("sortRows by ticker includes every row, by trend puts data first", () => {
  assert.deepEqual(sortRows(rows, "ticker", "asc").map((r) => r.ticker), ["AAPL", "BAD", "NVDA", "TEVA", "ZED"]);
  assert.deepEqual(sortRows(rows, "ticker", "desc").map((r) => r.ticker), ["ZED", "TEVA", "NVDA", "BAD", "AAPL"]);
  assert.deepEqual(sortRows(rows, "trend", "desc").map((r) => r.ticker), ["TEVA", "AAPL", "NVDA", "BAD", "ZED"]);
});

test("sortRows does not mutate its input", () => {
  const before = rows.map((r) => r.ticker);
  sortRows(rows, "predicted", "desc");
  assert.deepEqual(rows.map((r) => r.ticker), before);
});

test("filterRows matches ticker or company name, case-insensitively", () => {
  assert.deepEqual(filterRows(rows, "aap").map((r) => r.ticker), ["AAPL"]);
  assert.deepEqual(filterRows(rows, "PHARMA").map((r) => r.ticker), ["TEVA"]);
  assert.equal(filterRows(rows, "  ").length, rows.length);
  assert.equal(filterRows(rows, "zzz").length, 0);
});

test("filterBySector and sectorsOf", () => {
  assert.deepEqual(sectorsOf(rows), ["Energy", "Health Care", "Information Technology"]);
  assert.deepEqual(filterBySector(rows, "Information Technology").map((r) => r.ticker), ["AAPL", "NVDA"]);
  assert.equal(filterBySector(rows, null).length, rows.length);
  assert.equal(filterBySector(rows, "").length, rows.length);
  assert.equal(filterBySector(rows, "Utilities").length, 0);
  assert.deepEqual(sectorsOf([broken]), []);
});

test("paginate: pages, boundaries and counts", () => {
  const items = Array.from({ length: 120 }, (_, i) => i);
  const first = paginate(items, 1);
  assert.equal(first.items.length, PAGE_SIZE);
  assert.equal(first.pageCount, 3);
  assert.equal(first.from, 1);
  assert.equal(first.to, 50);
  const last = paginate(items, 3);
  assert.equal(last.items.length, 20);
  assert.equal(last.from, 101);
  assert.equal(last.to, 120);
  assert.equal(last.total, 120);
});

test("paginate: out-of-range and invalid pages are clamped, empty list is safe", () => {
  const items = Array.from({ length: 120 }, (_, i) => i);
  assert.equal(paginate(items, 99).page, 3);
  assert.equal(paginate(items, 0).page, 1);
  assert.equal(paginate(items, -4).page, 1);
  assert.equal(paginate(items, Number.NaN).page, 1);
  const empty = paginate([], 1);
  assert.deepEqual([empty.items.length, empty.page, empty.pageCount, empty.from, empty.to], [0, 1, 1, 0, 0]);
});
