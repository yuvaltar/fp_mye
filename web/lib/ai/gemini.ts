/**
 * A small Gemini client over the REST API (generateContent, streamed), with the
 * function-calling loop. No SDK: the surface we need is tiny, and not adding a
 * dependency keeps the project's dependency rule intact.
 *
 * The API key travels only in a request header from the server, and never in a
 * URL, a log line or an error message. Model parts are sent back exactly as
 * received (thought signatures and call ids included), which is what the newer
 * Gemini models require for multi-step function calling.
 * Imports are relative with .ts extensions so node:test can run this file.
 */
import type { JsonSchema, ToolDef, ToolResult } from "./tools.ts";
import { serializeResult } from "./tools.ts";

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

export interface GeminiSettings {
  apiKey: string;
  /** For example "gemini-3.5-flash-lite"; comes from GEMINI_MODEL, never hard-coded in a call. */
  model: string;
  baseUrl?: string;
}

export type AssistantErrorCode =
  | "rate_limited"
  | "bad_key"
  | "bad_model"
  | "blocked"
  | "upstream"
  | "timeout"
  | "network"
  | "too_many_steps";

export type AssistantEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string }
  | { type: "tool_done"; name: string; ok: boolean }
  | { type: "done" }
  | { type: "error"; code: AssistantErrorCode; message: string };

export const DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com";
export const DEFAULT_MAX_ROUNDS = 5;
export const REQUEST_TIMEOUT_MS = 45_000;
const MODEL_PATTERN = /^[a-z0-9][a-z0-9.\-]{0,80}$/;

/** User-facing message per error code (never contains provider details or the key). */
export const ERROR_MESSAGES: Record<AssistantErrorCode, string> = {
  rate_limited: "The assistant is busy right now (the free usage limit was reached). Please try again in a minute.",
  bad_key: "The assistant is not set up correctly (the API key was rejected).",
  bad_model: "The assistant is not set up correctly (the model name was not accepted).",
  blocked: "The assistant could not answer that. Try rephrasing the question.",
  upstream: "The assistant's service had a problem. Please try again.",
  timeout: "The assistant took too long to answer. Please try again.",
  network: "Could not reach the assistant's service. Please try again.",
  too_many_steps: "The assistant needed too many steps to answer. Try a more specific question.",
};

// ---------------------------------------------------------------------------
// Request building
// ---------------------------------------------------------------------------

/** Gemini's schema subset wants upper-case type names. */
export function toGeminiSchema(schema: JsonSchema): Record<string, unknown> {
  const out: Record<string, unknown> = { type: schema.type.toUpperCase() };
  if (schema.description) out.description = schema.description;
  if (schema.enum) out.enum = schema.enum;
  if (schema.minimum !== undefined) out.minimum = schema.minimum;
  if (schema.maximum !== undefined) out.maximum = schema.maximum;
  if (schema.minItems !== undefined) out.minItems = schema.minItems;
  if (schema.maxItems !== undefined) out.maxItems = schema.maxItems;
  if (schema.items) out.items = toGeminiSchema(schema.items);
  if (schema.properties) {
    out.properties = Object.fromEntries(
      Object.entries(schema.properties).map(([key, value]) => [key, toGeminiSchema(value)]),
    );
  }
  if (schema.required && schema.required.length > 0) out.required = schema.required;
  return out;
}

export function toFunctionDeclarations(tools: readonly ToolDef[]): Record<string, unknown>[] {
  return tools.map((tool) => {
    const declaration: Record<string, unknown> = { name: tool.name, description: tool.description };
    // Gemini rejects an OBJECT schema with no properties; a tool without arguments omits "parameters".
    if (tool.inputSchema.properties && Object.keys(tool.inputSchema.properties).length > 0) {
      declaration.parameters = toGeminiSchema(tool.inputSchema);
    }
    return declaration;
  });
}

interface Part {
  text?: string;
  thought?: boolean;
  thoughtSignature?: string;
  functionCall?: { name: string; args?: Record<string, unknown>; id?: string };
  functionResponse?: unknown;
  [key: string]: unknown;
}

interface Content {
  role: "user" | "model";
  parts: Part[];
}

export function toContents(messages: readonly ChatMessage[]): Content[] {
  return messages.map((m) => ({ role: m.role === "assistant" ? "model" : "user", parts: [{ text: m.text }] }));
}

/** Joins neighbouring plain text parts (keeps parts that carry a signature or a call as they are). */
export function coalesceParts(parts: readonly Part[]): Part[] {
  const out: Part[] = [];
  for (const part of parts) {
    const previous = out[out.length - 1];
    const plain = typeof part.text === "string" && Object.keys(part).every((k) => k === "text");
    const previousPlain =
      previous !== undefined && typeof previous.text === "string" && Object.keys(previous).every((k) => k === "text");
    if (plain && previousPlain && previous) previous.text = `${previous.text}${part.text}`;
    else out.push({ ...part });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Streaming (Server-Sent Events)
// ---------------------------------------------------------------------------

/** Parses an SSE byte stream into JSON objects, one per event. Tolerates split chunks and CRLF. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = function* (event: string): Generator<unknown> {
    const data = event
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n");
    if (data === "" || data === "[DONE]") return;
    try {
      yield JSON.parse(data);
    } catch {
      // A malformed event is skipped; the rest of the stream is still usable.
    }
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.search(/\r?\n\r?\n/);
      while (boundary !== -1) {
        const match = /\r?\n\r?\n/.exec(buffer);
        const length = match ? match[0].length : 2;
        yield* flush(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + length);
        boundary = buffer.search(/\r?\n\r?\n/);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim() !== "") yield* flush(buffer);
  } finally {
    reader.releaseLock();
  }
}

function errorCodeForStatus(status: number): AssistantErrorCode {
  if (status === 429) return "rate_limited";
  if (status === 401 || status === 403) return "bad_key";
  if (status === 404) return "bad_model";
  if (status === 400) return "bad_key"; // Gemini answers 400 for an invalid API key; see below for the body check
  return "upstream";
}

// ---------------------------------------------------------------------------
// The assistant loop
// ---------------------------------------------------------------------------

export interface RunOptions {
  settings: GeminiSettings;
  system: string;
  messages: readonly ChatMessage[];
  tools: readonly ToolDef[];
  execute: (name: string, args: unknown) => Promise<ToolResult>;
  signal?: AbortSignal | undefined;
  maxRounds?: number;
  fetchImpl?: typeof fetch;
  /** Extra attempts for a request that failed before any answer started (default 1). */
  retries?: number;
  /** Pause between attempts; replaced in tests. */
  sleep?: (ms: number) => Promise<void>;
}

interface Chunk {
  candidates?: { content?: { parts?: Part[] }; finishReason?: string }[];
  promptFeedback?: { blockReason?: string };
}

function parseResponseObject(text: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : { result: parsed };
  } catch {
    return { result_text: text };
  }
}

export const DEFAULT_RETRIES = 1;
const RETRY_PAUSE_MS = 1_500;

type RoundStart =
  | { kind: "ok"; response: Response; body: ReadableStream<Uint8Array>; timeout: AbortSignal }
  | { kind: "error"; code: AssistantErrorCode };

/**
 * Sends one request. A failure before any answer started (a network error, a
 * timeout or a 5xx from the service, all common on the free tier) is retried;
 * a rate limit, a rejected key or a bad request is not. Nothing has been shown
 * to the user at this point, so a retry can never repeat or mix up text.
 */
async function startRound(
  doFetch: typeof fetch,
  url: string,
  init: Omit<RequestInit, "signal">,
  callerSignal: AbortSignal | undefined,
  retries: number,
  sleep: (ms: number) => Promise<void>,
): Promise<RoundStart> {
  let last: AssistantErrorCode = "upstream";
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (attempt > 0) await sleep(RETRY_PAUSE_MS * attempt);
    const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
    const signal = callerSignal ? AbortSignal.any([callerSignal, timeout]) : timeout;

    let response: Response;
    try {
      response = await doFetch(url, { ...init, signal });
    } catch (cause) {
      if (callerSignal?.aborted) return { kind: "error", code: "network" };
      const timedOut = timeout.aborted || (cause instanceof Error && cause.name === "TimeoutError");
      last = timedOut ? "timeout" : "network";
      continue;
    }

    if (response.ok && response.body) return { kind: "ok", response, body: response.body, timeout };

    let code = errorCodeForStatus(response.status);
    if (response.status === 400) {
      // A 400 that is not about the key (bad request shape) is our bug, not the user's key.
      const text = await response.text().catch(() => "");
      code = /api key|API_KEY/i.test(text) ? "bad_key" : "upstream";
    }
    last = code;
    if (response.status < 500) return { kind: "error", code };
  }
  return { kind: "error", code: last };
}

export async function* runAssistant(options: RunOptions): AsyncGenerator<AssistantEvent> {
  const { settings, system, tools, execute } = options;
  const doFetch = options.fetchImpl ?? fetch;
  const maxRounds = options.maxRounds ?? DEFAULT_MAX_ROUNDS;

  if (!MODEL_PATTERN.test(settings.model)) {
    yield { type: "error", code: "bad_model", message: ERROR_MESSAGES.bad_model };
    return;
  }
  const base = (settings.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
  const url = `${base}/v1beta/models/${settings.model}:streamGenerateContent?alt=sse`;
  const declarations = toFunctionDeclarations(tools);
  const contents: Content[] = toContents(options.messages);

  for (let round = 0; round < maxRounds; round++) {
    const started = await startRound(
      doFetch,
      url,
      {
        method: "POST",
        headers: { "content-type": "application/json", "x-goog-api-key": settings.apiKey },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: system }] },
          contents,
          ...(declarations.length > 0
            ? { tools: [{ functionDeclarations: declarations }], toolConfig: { functionCallingConfig: { mode: "AUTO" } } }
            : {}),
          generationConfig: { temperature: 0.3, maxOutputTokens: 1500 },
        }),
      },
      options.signal,
      options.retries ?? DEFAULT_RETRIES,
      options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms))),
    );
    if (started.kind === "error") {
      yield { type: "error", code: started.code, message: ERROR_MESSAGES[started.code] };
      return;
    }
    const { body, timeout } = started;

    const modelParts: Part[] = [];
    const calls: { name: string; args: Record<string, unknown>; id?: string }[] = [];
    let produced = false;
    let finishReason: string | undefined;

    try {
      for await (const raw of readSse(body)) {
        const chunk = raw as Chunk;
        if (chunk.promptFeedback?.blockReason) {
          yield { type: "error", code: "blocked", message: ERROR_MESSAGES.blocked };
          return;
        }
        const candidate = chunk.candidates?.[0];
        if (candidate?.finishReason) finishReason = candidate.finishReason;
        for (const part of candidate?.content?.parts ?? []) {
          modelParts.push(part);
          if (part.functionCall) {
            const call: { name: string; args: Record<string, unknown>; id?: string } = {
              name: part.functionCall.name,
              args: part.functionCall.args ?? {},
            };
            if (part.functionCall.id !== undefined) call.id = part.functionCall.id;
            calls.push(call);
          } else if (typeof part.text === "string" && part.thought !== true && part.text !== "") {
            produced = true;
            yield { type: "text", text: part.text };
          }
        }
      }
    } catch (cause) {
      const timedOut = timeout.aborted || (cause instanceof Error && cause.name === "TimeoutError");
      yield timedOut
        ? { type: "error", code: "timeout", message: ERROR_MESSAGES.timeout }
        : { type: "error", code: "network", message: ERROR_MESSAGES.network };
      return;
    }

    if (calls.length === 0) {
      if (!produced && finishReason !== undefined && finishReason !== "STOP") {
        yield { type: "error", code: "blocked", message: ERROR_MESSAGES.blocked };
        return;
      }
      yield { type: "done" };
      return;
    }

    for (const call of calls) yield { type: "tool", name: call.name };
    const results = await Promise.all(calls.map((call) => execute(call.name, call.args)));
    const responses: Part[] = [];
    for (let i = 0; i < calls.length; i++) {
      const call = calls[i] as { name: string; id?: string };
      const result = results[i] as ToolResult;
      responses.push({
        functionResponse: {
          name: call.name,
          ...(call.id !== undefined ? { id: call.id } : {}),
          response: parseResponseObject(serializeResult(result)),
        },
      });
      yield { type: "tool_done", name: call.name, ok: result.ok };
    }

    // The model's own parts go back unchanged (signatures and ids included), then our answers.
    contents.push({ role: "model", parts: coalesceParts(modelParts) });
    contents.push({ role: "user", parts: responses });
  }

  yield { type: "error", code: "too_many_steps", message: ERROR_MESSAGES.too_many_steps };
}
