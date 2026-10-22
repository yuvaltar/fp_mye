/**
 * The chat endpoint's logic as a plain function (Request in, Response out), so
 * it is tested without a server. app/api/chat/route.ts only wires it up.
 * Every answer ends with the server-added disclaimer: it does not depend on the
 * model remembering to write it.
 */
import { readAssistantConfig, publicStatus, type AssistantConfig } from "./config.ts";
import { ERROR_MESSAGES, runAssistant, type AssistantEvent, type ChatMessage, type RunOptions } from "./gemini.ts";
import { DISCLAIMER_SHORT, buildSystemPrompt } from "./policy.ts";
import { DEFAULT_LIMITS, RateLimiter, clientKey } from "./rate-limit.ts";
import { TOOLS, runTool } from "./tools.ts";

export const MAX_MESSAGES = 20;
export const MAX_MESSAGE_CHARS = 2_000;
export const MAX_TOTAL_CHARS = 8_000;
export const MAX_BODY_CHARS = 40_000;
const TICKER_PATTERN = /^[A-Z][A-Z0-9.-]{0,9}$/;

export interface ChatRequest {
  messages: ChatMessage[];
  ticker?: string;
}

export type ParseResult = { ok: true; value: ChatRequest } | { ok: false; message: string };

export function parseChatRequest(body: unknown): ParseResult {
  if (typeof body !== "object" || body === null) return { ok: false, message: "The request body must be a JSON object." };
  const { messages, context } = body as { messages?: unknown; context?: unknown };
  if (!Array.isArray(messages) || messages.length === 0) return { ok: false, message: "messages must be a non-empty list." };
  if (messages.length > MAX_MESSAGES) return { ok: false, message: `At most ${MAX_MESSAGES} messages are accepted.` };

  const parsed: ChatMessage[] = [];
  let total = 0;
  for (const item of messages) {
    if (typeof item !== "object" || item === null) return { ok: false, message: "Each message must be an object." };
    const { role, text } = item as { role?: unknown; text?: unknown };
    if (role !== "user" && role !== "assistant") return { ok: false, message: 'Each message needs a role of "user" or "assistant".' };
    if (typeof text !== "string" || text.trim() === "") return { ok: false, message: "Each message needs some text." };
    if (text.length > MAX_MESSAGE_CHARS) return { ok: false, message: `A message can have at most ${MAX_MESSAGE_CHARS} characters.` };
    total += text.length;
    parsed.push({ role, text });
  }
  if (total > MAX_TOTAL_CHARS) return { ok: false, message: "The conversation is too long. Start a new one." };
  if (parsed[0]?.role !== "user") return { ok: false, message: "The conversation must start with a user message." };
  if (parsed[parsed.length - 1]?.role !== "user") return { ok: false, message: "The last message must be from the user." };

  let ticker: string | undefined;
  if (typeof context === "object" && context !== null) {
    const raw = (context as { ticker?: unknown }).ticker;
    if (typeof raw === "string" && TICKER_PATTERN.test(raw.toUpperCase())) ticker = raw.toUpperCase();
  }
  return { ok: true, value: ticker ? { messages: parsed, ticker } : { messages: parsed } };
}

export interface ChatDeps {
  config: AssistantConfig;
  limiter: RateLimiter;
  run: (options: RunOptions) => AsyncGenerator<AssistantEvent>;
  today: () => string;
}

export function defaultDeps(): ChatDeps {
  return {
    config: readAssistantConfig(),
    limiter: sharedLimiter,
    run: runAssistant,
    today: () => new Date().toISOString().slice(0, 10),
  };
}

/** One limiter per server process, shared by every request. */
export const sharedLimiter = new RateLimiter(DEFAULT_LIMITS);

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

function json(status: number, body: unknown, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...JSON_HEADERS, ...extra } });
}

/** GET: is the assistant switched on? Never reveals the key. */
export function handleStatus(config: AssistantConfig = readAssistantConfig()): Response {
  return json(200, publicStatus(config));
}

/** Same-origin only: a page on another site must not spend this site's quota. */
export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (origin === null) return true;
  try {
    return new URL(origin).host === new URL(request.url).host;
  } catch {
    return false;
  }
}

export async function handleChat(request: Request, deps: ChatDeps = defaultDeps()): Promise<Response> {
  if (!deps.config.enabled || !deps.config.settings) {
    return json(503, {
      error: "not_configured",
      message: "The assistant is not switched on for this site yet.",
    });
  }
  if (!isSameOrigin(request)) return json(403, { error: "forbidden", message: "Cross-site requests are not allowed." });

  const decision = deps.limiter.check(clientKey(request.headers));
  if (!decision.allowed) {
    return json(
      429,
      {
        error: "rate_limited",
        message:
          decision.reason === "day"
            ? "You reached today's question limit. Please come back tomorrow."
            : "Too many questions in a short time. Please wait a moment.",
        retry_after_seconds: decision.retryAfterSeconds,
      },
      { "retry-after": String(decision.retryAfterSeconds) },
    );
  }

  let text: string;
  try {
    text = await request.text();
  } catch {
    return json(400, { error: "bad_request", message: "Could not read the request." });
  }
  if (text.length > MAX_BODY_CHARS) return json(413, { error: "too_large", message: "The request is too large." });

  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return json(400, { error: "bad_request", message: "The request body is not valid JSON." });
  }
  const parsed = parseChatRequest(body);
  if (!parsed.ok) return json(400, { error: "bad_request", message: parsed.message });

  const settings = deps.config.settings;
  const system = buildSystemPrompt({ ticker: parsed.value.ticker, today: deps.today() });
  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (event: unknown) => controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
      try {
        for await (const event of deps.run({
          settings,
          system,
          messages: parsed.value.messages,
          tools: TOOLS,
          execute: runTool,
          signal: request.signal,
        })) {
          if (event.type === "done") send({ type: "disclaimer", text: DISCLAIMER_SHORT });
          send(event);
        }
      } catch {
        send({ type: "error", code: "upstream", message: ERROR_MESSAGES.upstream });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "content-type": "application/x-ndjson; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}
