import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ERROR_MESSAGES,
  coalesceParts,
  readSse,
  runAssistant,
  toFunctionDeclarations,
  toGeminiSchema,
  type AssistantEvent,
  type RunOptions,
} from "./gemini.ts";
import { TOOLS, type ToolDef, type ToolResult } from "./tools.ts";

const KEY = "test-key-SECRET-123";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

const sse = (...objects: unknown[]) => objects.map((o) => `data: ${JSON.stringify(o)}\r\n\r\n`).join("");
const textChunk = (text: string, finishReason?: string) => ({
  candidates: [{ content: { role: "model", parts: [{ text }] }, ...(finishReason ? { finishReason } : {}) }],
});

function sseResponse(body: string, status = 200): Response {
  return new Response(body, { status, headers: { "content-type": "text/event-stream" } });
}

interface Recorded {
  url: string;
  headers: Record<string, string>;
  body: any;
}

/** A fetch that answers with the given responses in order and records every request. */
function scripted(responses: (Response | Error)[]) {
  const calls: Recorded[] = [];
  const fetchImpl = (async (input: any, init: any) => {
    calls.push({ url: String(input), headers: init.headers, body: JSON.parse(init.body) });
    const next = responses[calls.length - 1];
    if (!next) throw new Error("no scripted response");
    if (next instanceof Error) throw next;
    return next;
  }) as typeof fetch;
  return { fetchImpl, calls };
}

function options(fetchImpl: typeof fetch, overrides: Partial<RunOptions> = {}): RunOptions {
  return {
    settings: { apiKey: KEY, model: "gemini-test-model" },
    system: "SYSTEM RULES",
    messages: [{ role: "user", text: "How volatile is AAPL?" }],
    tools: TOOLS,
    execute: async () => ({ ok: true, data: { fact: 1 } }),
    fetchImpl,
    retries: 0,
    sleep: async () => undefined,
    ...overrides,
  };
}

async function collect(generator: AsyncGenerator<AssistantEvent>): Promise<AssistantEvent[]> {
  const events: AssistantEvent[] = [];
  for await (const event of generator) events.push(event);
  return events;
}

test("readSse parses events split across chunks, with CRLF, and skips garbage", async () => {
  const whole = sse({ a: 1 }, { b: 2 });
  const cut = 9;
  const parsed: unknown[] = [];
  for await (const item of readSse(streamOf([whole.slice(0, cut), whole.slice(cut, 25), whole.slice(25), "data: {not json}\n\n", "data: [DONE]\n\n", 'data: {"c":3}\n\n']))) {
    parsed.push(item);
  }
  assert.deepEqual(parsed, [{ a: 1 }, { b: 2 }, { c: 3 }]);
});

test("readSse handles a final event without a trailing blank line and LF-only streams", async () => {
  const parsed: unknown[] = [];
  for await (const item of readSse(streamOf(['data: {"x":1}\n\ndata: {"y":2}']))) parsed.push(item);
  assert.deepEqual(parsed, [{ x: 1 }, { y: 2 }]);
});

test("toGeminiSchema upper-cases types recursively and keeps constraints", () => {
  const schema = toGeminiSchema({
    type: "object",
    properties: {
      ticker: { type: "string", description: "A ticker" },
      tickers: { type: "array", items: { type: "string" }, minItems: 2, maxItems: 4 },
      limit: { type: "integer", minimum: 1, maximum: 15 },
      sort_by: { type: "string", enum: ["a", "b"] },
    },
    required: ["ticker"],
  });
  assert.deepEqual(schema, {
    type: "OBJECT",
    properties: {
      ticker: { type: "STRING", description: "A ticker" },
      tickers: { type: "ARRAY", items: { type: "STRING" }, minItems: 2, maxItems: 4 },
      limit: { type: "INTEGER", minimum: 1, maximum: 15 },
      sort_by: { type: "STRING", enum: ["a", "b"] },
    },
    required: ["ticker"],
  });
});

test("function declarations omit 'parameters' for a tool without arguments", () => {
  const declarations = toFunctionDeclarations(TOOLS);
  assert.equal(declarations.length, TOOLS.length);
  const accuracy = declarations.find((d) => d.name === "get_engine_accuracy");
  assert.ok(accuracy && !("parameters" in accuracy));
  const brief = declarations.find((d) => d.name === "get_risk_brief");
  assert.ok(brief && "parameters" in brief);
});

test("coalesceParts joins plain text but keeps signed parts and calls untouched", () => {
  const parts = coalesceParts([
    { text: "Hel" },
    { text: "lo" },
    { text: "x", thoughtSignature: "SIG" },
    { functionCall: { name: "f", args: {}, id: "1" } },
    { text: "after" },
  ]);
  assert.deepEqual(parts, [
    { text: "Hello" },
    { text: "x", thoughtSignature: "SIG" },
    { functionCall: { name: "f", args: {}, id: "1" } },
    { text: "after" },
  ]);
});

test("a plain answer is streamed as text events and ends with done", async () => {
  const { fetchImpl, calls } = scripted([sseResponse(sse(textChunk("AAPL is "), textChunk("typical.", "STOP")))]);
  const events = await collect(runAssistant(options(fetchImpl)));
  assert.deepEqual(events, [{ type: "text", text: "AAPL is " }, { type: "text", text: "typical." }, { type: "done" }]);

  const [call] = calls;
  assert.ok(call);
  assert.match(call.url, /\/v1beta\/models\/gemini-test-model:streamGenerateContent\?alt=sse$/);
  assert.equal(call.headers["x-goog-api-key"], KEY);
  assert.ok(!call.url.includes(KEY), "the key must never be in the URL");
  assert.equal(call.body.systemInstruction.parts[0].text, "SYSTEM RULES");
  assert.deepEqual(call.body.contents, [{ role: "user", parts: [{ text: "How volatile is AAPL?" }] }]);
  assert.equal(call.body.tools[0].functionDeclarations.length, TOOLS.length);
  assert.equal(call.body.toolConfig.functionCallingConfig.mode, "AUTO");
});

test("assistant turns in the history are sent as the model role", async () => {
  const { fetchImpl, calls } = scripted([sseResponse(sse(textChunk("ok", "STOP")))]);
  await collect(
    runAssistant(
      options(fetchImpl, {
        messages: [
          { role: "user", text: "q1" },
          { role: "assistant", text: "a1" },
          { role: "user", text: "q2" },
        ],
      }),
    ),
  );
  assert.deepEqual(
    calls[0]?.body.contents.map((c: any) => c.role),
    ["user", "model", "user"],
  );
});

test("a function call runs the tool and sends the result back with the model's parts unchanged", async () => {
  const executed: { name: string; args: unknown }[] = [];
  const { fetchImpl, calls } = scripted([
    sseResponse(
      sse({
        candidates: [
          {
            content: {
              role: "model",
              parts: [{ functionCall: { name: "get_risk_brief", args: { ticker: "AAPL" }, id: "call-1" }, thoughtSignature: "SIGNATURE-ABC" }],
            },
          },
        ],
      }),
    ),
    sseResponse(sse(textChunk("AAPL's expected volatility is 22.5%.", "STOP"))),
  ]);
  const events = await collect(
    runAssistant(
      options(fetchImpl, {
        execute: async (name, args): Promise<ToolResult> => {
          executed.push({ name, args });
          return { ok: true, data: { expected_volatility: "22.5%", as_of_date: "2026-10-07" } };
        },
      }),
    ),
  );

  assert.deepEqual(executed, [{ name: "get_risk_brief", args: { ticker: "AAPL" } }]);
  assert.deepEqual(events, [
    { type: "tool", name: "get_risk_brief" },
    { type: "tool_done", name: "get_risk_brief", ok: true },
    { type: "text", text: "AAPL's expected volatility is 22.5%." },
    { type: "done" },
  ]);

  const second = calls[1]?.body.contents;
  assert.equal(second.length, 3);
  assert.deepEqual(second[1], {
    role: "model",
    parts: [{ functionCall: { name: "get_risk_brief", args: { ticker: "AAPL" }, id: "call-1" }, thoughtSignature: "SIGNATURE-ABC" }],
  });
  assert.equal(second[2].role, "user");
  const response = second[2].parts[0].functionResponse;
  assert.equal(response.name, "get_risk_brief");
  assert.equal(response.id, "call-1", "the call id is echoed back");
  assert.equal(response.response.expected_volatility, "22.5%");
  assert.equal(response.response.ok, true);
});

test("parallel calls are all answered in one turn, in order", async () => {
  const { fetchImpl, calls } = scripted([
    sseResponse(
      sse({
        candidates: [
          {
            content: {
              parts: [
                { functionCall: { name: "get_risk_brief", args: { ticker: "AAPL" }, id: "a" } },
                { functionCall: { name: "get_risk_brief", args: { ticker: "NVDA" }, id: "b" } },
              ],
            },
          },
        ],
      }),
    ),
    sseResponse(sse(textChunk("done", "STOP"))),
  ]);
  const events = await collect(
    runAssistant(options(fetchImpl, { execute: async (_n, args) => ({ ok: true, data: { got: (args as any).ticker } }) })),
  );
  const answers = calls[1]?.body.contents[2].parts;
  assert.deepEqual(
    answers.map((p: any) => [p.functionResponse.id, p.functionResponse.response.got]),
    [["a", "AAPL"], ["b", "NVDA"]],
  );
  assert.deepEqual(events.filter((e) => e.type === "tool").length, 2);
});

test("a failing tool is reported to the model as data and the conversation continues", async () => {
  const { fetchImpl, calls } = scripted([
    sseResponse(sse({ candidates: [{ content: { parts: [{ functionCall: { name: "get_risk_brief", args: { ticker: "ZZZZ" } } }] } }] })),
    sseResponse(sse(textChunk("There is no data for ZZZZ.", "STOP"))),
  ]);
  const events = await collect(
    runAssistant(options(fetchImpl, { execute: async () => ({ ok: false, error: "not_covered", message: "no prediction" }) })),
  );
  assert.deepEqual(events[1], { type: "tool_done", name: "get_risk_brief", ok: false });
  assert.equal(events.at(-1)?.type, "done");
  const response = calls[1]?.body.contents[2].parts[0].functionResponse;
  assert.equal(response.response.ok, false);
  assert.equal(response.response.error, "not_covered");
  assert.ok(!("id" in response), "no id is invented when the call had none");
});

test("the loop stops after the maximum number of rounds", async () => {
  const forever = () =>
    sseResponse(sse({ candidates: [{ content: { parts: [{ functionCall: { name: "search_tickers", args: { query: "a" } } }] } }] }));
  const { fetchImpl, calls } = scripted([forever(), forever(), forever()]);
  const events = await collect(runAssistant(options(fetchImpl, { maxRounds: 3 })));
  assert.equal(calls.length, 3);
  assert.deepEqual(events.at(-1), { type: "error", code: "too_many_steps", message: ERROR_MESSAGES.too_many_steps });
});

test("HTTP errors map to friendly codes and never leak provider text or the key", async () => {
  const cases: [number, string, string][] = [
    [429, "{}", "rate_limited"],
    [403, "{}", "bad_key"],
    [401, "{}", "bad_key"],
    [404, "{}", "bad_model"],
    [400, JSON.stringify({ error: { message: "API key not valid. Please pass a valid API key." } }), "bad_key"],
    [400, JSON.stringify({ error: { message: "Invalid JSON payload received." } }), "upstream"],
    [500, "{}", "upstream"],
    [503, "{}", "upstream"],
  ];
  for (const [status, body, code] of cases) {
    const { fetchImpl } = scripted([new Response(body, { status })]);
    const events = await collect(runAssistant(options(fetchImpl)));
    assert.equal(events.length, 1, `${status}`);
    const event = events[0];
    assert.equal(event?.type, "error");
    if (event?.type === "error") {
      assert.equal(event.code, code, `${status} ${body}`);
      assert.equal(event.message, ERROR_MESSAGES[event.code]);
      assert.ok(!event.message.includes(KEY));
      assert.ok(!/google|generativelanguage|invalid json/i.test(event.message));
    }
  }
});

test("network failures and timeouts are reported without details", async () => {
  const net = scripted([new TypeError("fetch failed: ECONNRESET to generativelanguage.googleapis.com")]);
  const netEvents = await collect(runAssistant(options(net.fetchImpl)));
  assert.deepEqual(netEvents, [{ type: "error", code: "network", message: ERROR_MESSAGES.network }]);

  const timeout = Object.assign(new Error("The operation timed out"), { name: "TimeoutError" });
  const slow = scripted([timeout]);
  const slowEvents = await collect(runAssistant(options(slow.fetchImpl)));
  assert.deepEqual(slowEvents, [{ type: "error", code: "timeout", message: ERROR_MESSAGES.timeout }]);
});

test("a blocked prompt and a blocked answer become a friendly 'blocked' error", async () => {
  const blockedPrompt = scripted([sseResponse(sse({ promptFeedback: { blockReason: "SAFETY" } }))]);
  assert.deepEqual(await collect(runAssistant(options(blockedPrompt.fetchImpl))), [
    { type: "error", code: "blocked", message: ERROR_MESSAGES.blocked },
  ]);
  const blockedAnswer = scripted([sseResponse(sse({ candidates: [{ finishReason: "SAFETY" }] }))]);
  assert.deepEqual(await collect(runAssistant(options(blockedAnswer.fetchImpl))), [
    { type: "error", code: "blocked", message: ERROR_MESSAGES.blocked },
  ]);
});

test("thought parts are never shown to the user", async () => {
  const { fetchImpl } = scripted([
    sseResponse(
      sse({ candidates: [{ content: { parts: [{ text: "secret reasoning", thought: true }, { text: "Visible answer." }] } }] }, { candidates: [{ finishReason: "STOP" }] }),
    ),
  ]);
  const events = await collect(runAssistant(options(fetchImpl)));
  assert.deepEqual(events, [{ type: "text", text: "Visible answer." }, { type: "done" }]);
});

test("an invalid model name never reaches the network (no URL injection)", async () => {
  for (const model of ["", "../admin", "gemini x", "gemini?key=1", "a/b", "A".repeat(100)]) {
    const { fetchImpl, calls } = scripted([]);
    const events = await collect(runAssistant(options(fetchImpl, { settings: { apiKey: KEY, model } })));
    assert.deepEqual(events, [{ type: "error", code: "bad_model", message: ERROR_MESSAGES.bad_model }], model);
    assert.equal(calls.length, 0);
  }
});

test("a custom base URL is used and a trailing slash is tolerated", async () => {
  const { fetchImpl, calls } = scripted([sseResponse(sse(textChunk("hi", "STOP")))]);
  await collect(runAssistant(options(fetchImpl, { settings: { apiKey: KEY, model: "m1", baseUrl: "http://127.0.0.1:9999/" } })));
  assert.equal(calls[0]?.url, "http://127.0.0.1:9999/v1beta/models/m1:streamGenerateContent?alt=sse");
});

test("works without tools: no tool declarations are sent", async () => {
  const { fetchImpl, calls } = scripted([sseResponse(sse(textChunk("hi", "STOP")))]);
  const none: readonly ToolDef[] = [];
  await collect(runAssistant(options(fetchImpl, { tools: none })));
  assert.ok(!("tools" in (calls[0]?.body ?? {})));
});

test("a caller abort stops the stream with a network-style error, not a crash", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetchImpl = (async (_input: any, init: any) => {
    if (init.signal?.aborted) throw Object.assign(new Error("aborted"), { name: "AbortError" });
    return sseResponse("");
  }) as typeof fetch;
  const events = await collect(runAssistant(options(fetchImpl, { signal: controller.signal })));
  assert.equal(events.length, 1);
  assert.equal(events[0]?.type, "error");
});

// --- retries for failures before an answer starts ---------------------------

test("a 503 before any answer is retried once and then succeeds", async () => {
  const { fetchImpl, calls } = scripted([new Response("{}", { status: 503 }), sseResponse(sse(textChunk("recovered", "STOP")))]);
  const events = await collect(runAssistant(options(fetchImpl, { retries: 1 })));
  assert.deepEqual(events, [{ type: "text", text: "recovered" }, { type: "done" }]);
  assert.equal(calls.length, 2);
});

test("a network error and a timeout are retried too", async () => {
  const net = scripted([new TypeError("fetch failed"), sseResponse(sse(textChunk("ok", "STOP")))]);
  assert.deepEqual((await collect(runAssistant(options(net.fetchImpl, { retries: 1 })))).at(-1), { type: "done" });
  const timeout = Object.assign(new Error("timed out"), { name: "TimeoutError" });
  const slow = scripted([timeout, sseResponse(sse(textChunk("ok", "STOP")))]);
  assert.deepEqual((await collect(runAssistant(options(slow.fetchImpl, { retries: 1 })))).at(-1), { type: "done" });
});

test("errors that retrying cannot fix are not retried (rate limit, rejected key, wrong model)", async () => {
  for (const status of [429, 401, 403, 404]) {
    const { fetchImpl, calls } = scripted([new Response("{}", { status }), sseResponse(sse(textChunk("never", "STOP")))]);
    const events = await collect(runAssistant(options(fetchImpl, { retries: 3 })));
    assert.equal(calls.length, 1, String(status));
    assert.equal(events[0]?.type, "error");
  }
});

test("after the retries are used up the user gets the friendly error", async () => {
  const { fetchImpl, calls } = scripted([new Response("{}", { status: 503 }), new Response("{}", { status: 500 })]);
  const events = await collect(runAssistant(options(fetchImpl, { retries: 1 })));
  assert.equal(calls.length, 2);
  assert.deepEqual(events, [{ type: "error", code: "upstream", message: ERROR_MESSAGES.upstream }]);
  const failing = scripted([new TypeError("x"), new TypeError("y")]);
  assert.deepEqual(await collect(runAssistant(options(failing.fetchImpl, { retries: 1 }))), [
    { type: "error", code: "network", message: ERROR_MESSAGES.network },
  ]);
});

test("the pause between attempts grows and is injectable", async () => {
  const pauses: number[] = [];
  const { fetchImpl } = scripted([new Response("{}", { status: 503 }), new Response("{}", { status: 503 }), sseResponse(sse(textChunk("ok", "STOP")))]);
  await collect(runAssistant(options(fetchImpl, { retries: 2, sleep: async (ms) => void pauses.push(ms) })));
  assert.equal(pauses.length, 2);
  assert.ok((pauses[1] ?? 0) > (pauses[0] ?? 0));
});

test("a failure in the middle of an answer is NOT retried, so text is never repeated", async () => {
  const encoder = new TextEncoder();
  let first = true;
  const calls: number[] = [];
  const fetchImpl = (async () => {
    calls.push(1);
    if (!first) return sseResponse(sse(textChunk("SHOULD NOT APPEAR", "STOP")));
    first = false;
    return new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(sse(textChunk("Partial answer "))));
        },
        pull() {
          throw new TypeError("connection dropped");
        },
      }),
      { status: 200 },
    );
  }) as typeof fetch;
  const events = await collect(runAssistant(options(fetchImpl, { retries: 2 })));
  assert.equal(calls.length, 1);
  assert.deepEqual(events[0], { type: "text", text: "Partial answer " });
  assert.equal(events.at(-1)?.type, "error");
  assert.ok(!events.some((e) => e.type === "text" && e.text.includes("SHOULD NOT APPEAR")));
});

test("a caller abort is not retried", async () => {
  const controller = new AbortController();
  controller.abort();
  const calls: number[] = [];
  const fetchImpl = (async (_input: any, init: any) => {
    calls.push(1);
    if (init.signal?.aborted) throw Object.assign(new Error("aborted"), { name: "AbortError" });
    return sseResponse("");
  }) as typeof fetch;
  const events = await collect(runAssistant(options(fetchImpl, { retries: 3, signal: controller.signal })));
  assert.equal(calls.length, 1);
  assert.equal(events[0]?.type, "error");
});
