import type { HistoryPoint } from "./api/types.ts";

/** All number, percent and date formatting for the site lives here. */

/**
 * History as CSV text: raw decimals (0.2251), ISO dates, empty cell for a
 * realized value that is still pending.
 */
export function historyToCsv(ticker: string, points: readonly HistoryPoint[]): string {
  const header = "ticker,as_of_date,predicted_vol,baseline_vol,realized_vol";
  const rows = points.map(
    (p) =>
      `${ticker},${p.as_of_date},${p.predicted_vol},${p.baseline_vol},${p.realized_vol ?? ""}`,
  );
  return [header, ...rows].join("\n") + "\n";
}

const PLACEHOLDER = "—";

/** 0.2251 -> "22.5%". The only place a volatility decimal becomes a percentage. */
export function formatVol(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return PLACEHOLDER;
  }
  return `${(value * 100).toFixed(1)}%`;
}

/** 0.74 -> "74%". For weights and confidence (0..1), no decimals. */
export function formatShare(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return PLACEHOLDER;
  }
  return `${Math.round(value * 100)}%`;
}

/** 0.0617 -> "+6.2%", -0.031 -> "-3.1%". Relative or absolute differences. */
export function formatSignedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return PLACEHOLDER;
  }
  const text = (Math.abs(value) * 100).toFixed(1);
  if (Number(text) === 0) return `${text}%`;
  return `${value > 0 ? "+" : "-"}${text}%`;
}

const CURRENCY_SYMBOLS: Record<string, string> = { USD: "$", EUR: "€", GBP: "£", ILS: "₪" };

/** 227.5 + "USD" -> "$227.50". Unknown currencies get the code as a suffix. */
export function formatPrice(value: number | null | undefined, currency: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return PLACEHOLDER;
  }
  const amount = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
  const symbol = CURRENCY_SYMBOLS[currency];
  return symbol ? `${symbol}${amount}` : `${amount} ${currency}`;
}

/** Backtest error metrics (RMSE, MAE, QLIKE) with 4 decimals. */
export function formatMetric(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return PLACEHOLDER;
  }
  return value.toFixed(4);
}

/** "2026-10-07" -> "7 Oct 2026". Pure string handling: no time zone surprises. */
export function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  const month = months[Number(match[2]) - 1];
  if (!month) return iso;
  return `${Number(match[3])} ${month} ${match[1]}`;
}

/** "2026-10-07" -> "7 Oct". Compact form for chart axes. */
export function formatDateShort(iso: string): string {
  const full = formatDate(iso);
  return full === iso ? iso : full.replace(/ \d{4}$/, "");
}
