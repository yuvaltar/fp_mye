/**
 * Browser side of the assistant: talks to our own /api/chat route (never to
 * Google), reads the JSON-lines stream, and trims long conversations. This is
 * the only place a Client Component asks the chat endpoint; any failure is a
 * ChatError with a message that is safe to show.
 * No server imports here: this file is bundled for the browser.
 */

export type ChatEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string }
  | { type: "tool_done"; name: string; ok: boolean }
  | { type: "disclaimer"; text: string }
  | { type: "done" }
  | { type: "error"; code: string; message: string };

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

export class ChatError extends Error {
  readonly code: string;
  readonly retryAfterSeconds: number | null;
  constructor(code: string, message: string, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "ChatError";
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** The server accepts at most 20 messages; keep the latest ones and start on a user turn. */
export const MAX_SENT_MESSAGES = 10;

export function trimConversation(turns: readonly ChatTurn[], max = MAX_SENT_MESSAGES): ChatTurn[] {
  const tail = turns.slice(Math.max(0, turns.length - max));
  const firstUser = tail.findIndex((turn) => turn.role === "user");
  return firstUser === -1 ? [] : tail.slice(firstUser);
}

/** Turns arbitrary stream chunks into whole events (a line can be split across chunks). */
export class NdjsonParser {
  private buffer = "";

  push(chunk: string): ChatEvent[] {
    this.buffer += chunk;
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";
    return lines.flatMap((line) => parseLine(line));
  }

  end(): ChatEvent[] {
    const rest = this.buffer;
    this.buffer = "";
    return parseLine(rest);
  }
}

function parseLine(line: string): ChatEvent[] {
  if (line.trim() === "") return [];
  try {
    const value: unknown = JSON.parse(line);
    if (typeof value === "object" && value !== null && typeof (value as { type?: unknown }).type === "string") {
      return [value as ChatEvent];
    }
  } catch {
    // A broken line is dropped; the rest of the answer is still shown.
  }
  return [];
}

export interface AssistantStatus {
  enabled: boolean;
  /** How to switch it on; only sent by a development server. */
  setup: string | null;
}

/** Whether the server has the assistant switched on. Failure counts as "off". */
export async function fetchAssistantStatus(signal?: AbortSignal): Promise<AssistantStatus> {
  try {
    const response = await fetch("/api/chat", signal ? { signal, cache: "no-store" } : { cache: "no-store" });
    if (!response.ok) return { enabled: false, setup: null };
    const body = (await response.json()) as { enabled?: unknown; setup?: unknown };
    return { enabled: body.enabled === true, setup: typeof body.setup === "string" ? body.setup : null };
  } catch {
    return { enabled: false, setup: null };
  }
}

/** Sends the conversation and calls onEvent for every event of the answer, in order. */
export async function streamChat(
  turns: readonly ChatTurn[],
  ticker: string | undefined,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: trimConversation(turns), ...(ticker ? { context: { ticker } } : {}) }),
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ChatError("network", "Could not reach the assistant. Check your connection and try again.");
  }

  if (!response.ok || !response.body) {
    let code = "upstream";
    let message = "The assistant had a problem. Please try again.";
    let retry: number | null = null;
    try {
      const body = (await response.json()) as { error?: string; message?: string; retry_after_seconds?: number };
      if (typeof body.error === "string") code = body.error;
      if (typeof body.message === "string") message = body.message;
      if (typeof body.retry_after_seconds === "number") retry = body.retry_after_seconds;
    } catch {
      // keep the generic message
    }
    throw new ChatError(code, message, retry);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new NdjsonParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const event of parser.push(decoder.decode(value, { stream: true }))) onEvent(event);
  }
  for (const event of parser.push(decoder.decode())) onEvent(event);
  for (const event of parser.end()) onEvent(event);
}

/** Friendly names for the "checked" chips under an answer. */
export const TOOL_LABELS: Record<string, string> = {
  search_tickers: "Searched the stocks",
  get_risk_brief: "Read the engine's prediction",
  compare_tickers: "Compared the stocks",
  rank_stocks: "Ranked the stocks",
  get_market_snapshot: "Looked up the market price",
  get_weights_summary: "Checked the model weights",
  get_engine_accuracy: "Checked the backtest",
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? "Looked up site data";
}

/** The ticker of the stock page the user is on, from the URL path. */
export function tickerFromPath(pathname: string): string | undefined {
  const match = /^\/stock\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) return undefined;
  try {
    const ticker = decodeURIComponent(match[1]).toUpperCase();
    return /^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker) ? ticker : undefined;
  } catch {
    return undefined;
  }
}

/** Starter questions: about the current stock when there is one, general otherwise. */
export function suggestionsFor(ticker: string | undefined): string[] {
  return ticker
    ? [
        `Give me a risk briefing on ${ticker}`,
        `Why is ${ticker}'s prediction different from the baseline?`,
        `Does ${ticker} report earnings this week?`,
        `How accurate has the engine been on ${ticker}?`,
      ]
    : [
        "Which stocks are expected to be the most volatile?",
        "Which companies report earnings this week?",
        "How accurate is the engine?",
        "What does volatility mean?",
      ];
}

/** localStorage key for the accepted terms; bump the version when the terms change. */
export const ACK_STORAGE_KEY = "tsm-assistant-ack-v1";
