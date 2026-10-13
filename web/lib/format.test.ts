import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formatDate,
  formatDateShort,
  formatShare,
  formatSignedPercent,
  formatVol,
} from "./format.ts";

test("formatVol converts a decimal to a percentage with one decimal", () => {
  assert.equal(formatVol(0.2251), "22.5%");
  assert.equal(formatVol(0.24), "24.0%");
  assert.equal(formatVol(0.4948), "49.5%");
});

test("formatVol shows a placeholder for missing or invalid values", () => {
  assert.equal(formatVol(null), "—");
  assert.equal(formatVol(undefined), "—");
  assert.equal(formatVol(Number.NaN), "—");
  assert.equal(formatVol(Number.POSITIVE_INFINITY), "—");
});

test("formatShare rounds to whole percents", () => {
  assert.equal(formatShare(0.74), "74%");
  assert.equal(formatShare(0.345), "35%");
  assert.equal(formatShare(0), "0%");
  assert.equal(formatShare(1), "100%");
  assert.equal(formatShare(null), "—");
});

test("formatSignedPercent shows an explicit sign", () => {
  assert.equal(formatSignedPercent(0.0617), "+6.2%");
  assert.equal(formatSignedPercent(-0.031), "-3.1%");
  assert.equal(formatSignedPercent(0), "0.0%");
  assert.equal(formatSignedPercent(0.0001), "0.0%");
  assert.equal(formatSignedPercent(null), "—");
});

test("formatDate renders ISO dates without time zone shifts", () => {
  assert.equal(formatDate("2026-10-07"), "7 Oct 2026");
  assert.equal(formatDate("2026-01-01"), "1 Jan 2026");
  assert.equal(formatDate("2026-12-31"), "31 Dec 2026");
});

test("formatDate returns the input when it is not an ISO date", () => {
  assert.equal(formatDate("not a date"), "not a date");
  assert.equal(formatDate("2026-13-01"), "2026-13-01");
});

test("formatDateShort drops the year", () => {
  assert.equal(formatDateShort("2026-10-07"), "7 Oct");
  assert.equal(formatDateShort("oops"), "oops");
});
