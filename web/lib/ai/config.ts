/**
 * Assistant configuration, read from environment variables on the server only.
 * Nothing here is NEXT_PUBLIC_: the API key must never reach the browser.
 */
import type { GeminiSettings } from "./gemini.ts";

/**
 * Used when GEMINI_MODEL is not set. A light, free-tier friendly model from
 * Google's current list; change it with GEMINI_MODEL without touching code.
 */
export const DEFAULT_MODEL = "gemini-3.5-flash-lite";

export interface AssistantConfig {
  enabled: boolean;
  settings: GeminiSettings | null;
}

export function readAssistantConfig(env: Record<string, string | undefined> = process.env): AssistantConfig {
  const key = env.GEMINI_API_KEY?.trim();
  const switchedOff = env.ASSISTANT_ENABLED?.trim().toLowerCase() === "false";
  if (!key || switchedOff) return { enabled: false, settings: null };
  const model = env.GEMINI_MODEL?.trim() || DEFAULT_MODEL;
  const baseUrl = env.GEMINI_BASE_URL?.trim();
  return { enabled: true, settings: { apiKey: key, model, ...(baseUrl ? { baseUrl } : {}) } };
}

/** Shown to the developer (never in production) when the assistant is off because there is no key. */
export const SETUP_HINT =
  "Developer note: add GEMINI_API_KEY=your-free-key (from aistudio.google.com/apikey) to web/.env.local and restart the dev server. See docs/assistant.md.";

/**
 * What the browser may know: whether the assistant is on and, in development
 * only, how to switch it on. Never the key or anything about the account.
 */
export function publicStatus(
  config: AssistantConfig,
  env: Record<string, string | undefined> = process.env,
): { enabled: boolean; model: string | null; setup?: string } {
  const status = { enabled: config.enabled, model: config.settings?.model ?? null };
  return !config.enabled && env.NODE_ENV === "development" ? { ...status, setup: SETUP_HINT } : status;
}
