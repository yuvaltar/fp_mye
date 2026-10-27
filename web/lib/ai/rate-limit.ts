/**
 * A small in-memory rate limiter for the chat endpoint, so one visitor cannot
 * burn the shared free quota. Per server instance, which is enough for this
 * project; a hosted deployment with several instances would need a shared store.
 */
export interface Limits {
  perMinute: number;
  perDay: number;
}

export const DEFAULT_LIMITS: Limits = { perMinute: 8, perDay: 120 };

export type Decision = { allowed: true } | { allowed: false; retryAfterSeconds: number; reason: "minute" | "day" };

const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;
const MAX_TRACKED = 5_000;

export class RateLimiter {
  private readonly hits = new Map<string, number[]>();
  private readonly limits: Limits;
  private readonly now: () => number;

  constructor(limits: Limits = DEFAULT_LIMITS, now: () => number = Date.now) {
    this.limits = limits;
    this.now = now;
  }

  /** Records a request for the key when it is allowed. */
  check(key: string): Decision {
    const now = this.now();
    const recent = (this.hits.get(key) ?? []).filter((t) => now - t < DAY_MS);
    const lastMinute = recent.filter((t) => now - t < MINUTE_MS);

    if (lastMinute.length >= this.limits.perMinute) {
      const oldest = lastMinute[0] as number;
      return { allowed: false, reason: "minute", retryAfterSeconds: Math.max(1, Math.ceil((oldest + MINUTE_MS - now) / 1000)) };
    }
    if (recent.length >= this.limits.perDay) {
      const oldest = recent[0] as number;
      return { allowed: false, reason: "day", retryAfterSeconds: Math.max(1, Math.ceil((oldest + DAY_MS - now) / 1000)) };
    }

    recent.push(now);
    this.hits.set(key, recent);
    if (this.hits.size > MAX_TRACKED) this.prune(now);
    return { allowed: true };
  }

  private prune(now: number): void {
    for (const [key, times] of this.hits) {
      if (times.every((t) => now - t >= DAY_MS)) this.hits.delete(key);
    }
  }
}

/** The visitor key: the first forwarded address, else a fixed local key. */
export function clientKey(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded && forwarded.length <= 64 ? forwarded : "local";
}
