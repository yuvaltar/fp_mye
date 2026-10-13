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

/** 33380854 -> "33.4M", 912000 -> "912K", 540 -> "540". */
export function formatVolume(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || value < 0) {
    return PLACEHOLDER;
  }
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `${Math.round(value / 1e3)}K`;
  return String(Math.round(value));
}

/** "2026-10-07T20:00:01.000Z" -> "7 Oct 2026, 20:00 UTC". */
export function formatDateTimeUtc(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  const date = formatDate(parsed.toISOString().slice(0, 10));
  const time = parsed.toISOString().slice(11, 16);
  return `${date}, ${time} UTC`;
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

/** "2026-10-13" -> "Tuesday". Pure date arithmetic, no time zone surprises. */
export function formatWeekday(iso: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const day = new Date(`${iso}T00:00:00Z`).getUTCDay();
  const names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  return names[day] ?? iso;
}

/** "2026-10-07" -> "Oct 2026". Axis labels for ranges longer than a year. */
export function formatMonthYear(iso: string): string {
  const full = formatDate(iso);
  if (full === iso) return iso;
  const [, month, year] = full.split(" ");
  return `${month} ${year}`;
}

/** "2026-10-07" -> "7 Oct". Compact form for chart axes. */
export function formatDateShort(iso: string): string {
  const full = formatDate(iso);
  return full === iso ? iso : full.replace(/ \d{4}$/, "");
}
