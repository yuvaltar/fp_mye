import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  ChatError,
  MAX_SENT_MESSAGES,
  NdjsonParser,
  TOOL_LABELS,
  fetchAssistantStatus,
  streamChat,
  suggestionsFor,
  tickerFromPath,
  toolLabel,
  trimConversation,
  type ChatEvent,
  type ChatTurn,
} from "./chat-client.ts";
import { parseInline, parseMarkdown, toPlainText } from "./markdown.ts";
import { TOOLS } from "./tools.ts";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

// --- markdown ---------------------------------------------------------------

test("inline markdown: bold and code are recognized, everything else stays text", () => {
  assert.deepEqual(parseInline("a **b** c `d` e"), [
    { kind: "text", text: "a " },
    { kind: "bold", text: "b" },
    { kind: "text", text: " c " },
    { kind: "code", text: "d" },
    { kind: "text", text: " e" },
  ]);
  assert.deepEqual(parseInline("plain"), [{ kind: "text", text: "plain" }]);
  assert.deepEqual(parseInline(""), []);
});

test("unfinished markup while streaming stays plain text", () => {
  assert.deepEqual(parseInline("the **key number"), [{ kind: "text", text: "the **key number" }]);
  assert.deepEqual(parseInline("use `code"), [{ kind: "text", text: "use `code" }]);
});

test("paragraphs, bullet lists and numbered lists are separated correctly", () => {
  const blocks = parseMarkdown("Intro line\nsecond line\n\n- one\n- **two**\n* three\n\n1. first\n2) second\n\nDone.");
  assert.deepEqual(
    blocks.map((b) => b.kind),
    ["paragraph", "bullets", "numbered", "paragraph"],
  );
  assert.equal(toPlainText(blocks), "Intro line second line\n\n- one\n- two\n- three\n\n1. first\n2. second\n\nDone.");
});

test("a list directly after a paragraph, CRLF input and indented continuations work", () => {
  const blocks = parseMarkdown("Points:\r\n- alpha\r\n  continued\r\n- beta");
  assert.deepEqual(blocks.map((b) => b.kind), ["paragraph", "bullets"]);
  const list = blocks[1];
  assert.ok(list && list.kind === "bullets");
  if (list?.kind === "bullets") {
    assert.equal(list.items.length, 2);
    assert.equal(list.items[0]?.map((p) => p.text).join(""), "alpha continued");
  }
});

test("markdown output is data: HTML and script text stay inert text", () => {
  const blocks = parseMarkdown('<script>alert("x")</script> **<b>bold</b>** [link](javascript:alert(1)) ![img](x)');
  const text = toPlainText(blocks);
  assert.ok(text.includes("<script>"), "kept as visible text, never turned into markup");
  assert.ok(blocks.every((b) => b.kind === "paragraph" || b.kind === "bullets" || b.kind === "numbered"));
  assert.equal(JSON.stringify(blocks).includes("href"), false, "no links are ever produced");
});

test("empty and whitespace-only input give no blocks", () => {
  assert.deepEqual(parseMarkdown(""), []);
  assert.deepEqual(parseMarkdown("  \n\n  "), []);
});

// --- chat client helpers ----------------------------------------------------

test("NdjsonParser rebuilds events split across chunks and ignores broken lines", () => {
  const parser = new NdjsonParser();
  const events: ChatEvent[] = [];
  const stream = '{"type":"text","text":"Hel"}\n{"type":"te';
  events.push(...parser.push(stream.slice(0, 10)));
  events.push(...parser.push(stream.slice(10)));
  events.push(...parser.push('xt","text":"lo"}\n\nnot json\n{"nope":1}\n{"type":"done"}'));
  events.push(...parser.end());
  assert.deepEqual(events, [
    { type: "text", text: "Hel" },
    { type: "text", text: "lo" },
    { type: "done" },
  ]);
});

test("trimConversation keeps the latest messages and always starts on a user turn", () => {
  const turns: ChatTurn[] = Array.from({ length: 25 }, (_, i) => ({ role: i % 2 === 0 ? "user" : "assistant", text: `m${i}` }));
  const trimmed = trimConversation(turns);
  assert.ok(trimmed.length <= MAX_SENT_MESSAGES);
  assert.equal(trimmed[0]?.role, "user");
  assert.equal(trimmed.at(-1)?.text, "m24");
  assert.deepEqual(trimConversation([{ role: "assistant", text: "orphan" }]), []);
  assert.deepEqual(trimConversation([]), []);
  const short: ChatTurn[] = [{ role: "user", text: "hi" }];
  assert.deepEqual(trimConversation(short), short);
});

test("the stock page ticker is read from the URL safely", () => {
  assert.equal(tickerFromPath("/stock/AAPL"), "AAPL");
  assert.equal(tickerFromPath("/stock/brk-b"), "BRK-B");
  assert.equal(tickerFromPath("/stock/BRK.B/extra"), "BRK.B");
  for (const path of ["/", "/performance", "/stock/", "/stock/%E0%A4%A", "/stock/<script>", "/stock/" + "A".repeat(20), "/other/AAPL"]) {
    assert.equal(tickerFromPath(path), undefined, path);
  }
});

test("suggestions mention the current stock, or are general", () => {
  const onStock = suggestionsFor("NVDA");
  assert.ok(onStock.length >= 3 && onStock.every((s) => s.includes("NVDA")));
  const general = suggestionsFor(undefined);
  assert.ok(general.length >= 3 && general.every((s) => !s.includes("undefined")));
});

test("every tool has a friendly label for the chips and unknown ones get a neutral one", () => {
  for (const tool of TOOLS) assert.ok(TOOL_LABELS[tool.name], `no label for ${tool.name}`);
  assert.equal(toolLabel("something_new"), "Looked up site data");
});

test("fetchAssistantStatus is enabled only when the server says so, and carries the developer hint", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ enabled: true, model: "m" }), { status: 200 });
  assert.deepEqual(await fetchAssistantStatus(), { enabled: true, setup: null });
  globalThis.fetch = async () => new Response(JSON.stringify({ enabled: false, setup: "add a key" }), { status: 200 });
  assert.deepEqual(await fetchAssistantStatus(), { enabled: false, setup: "add a key" });
  globalThis.fetch = async () => new Response(JSON.stringify({ enabled: false, setup: 5 }), { status: 200 });
  assert.deepEqual(await fetchAssistantStatus(), { enabled: false, setup: null });
  globalThis.fetch = async () => new Response("{}", { status: 500 });
  assert.deepEqual(await fetchAssistantStatus(), { enabled: false, setup: null });
  globalThis.fetch = async () => {
    throw new TypeError("offline");
  };
  assert.deepEqual(await fetchAssistantStatus(), { enabled: false, setup: null });
});

function ndjsonResponse(parts: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const part of parts) controller.enqueue(encoder.encode(part));
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "application/x-ndjson" } },
  );
}

test("streamChat sends a trimmed conversation with the page context and delivers events in order", async () => {
  let sent: any;
  globalThis.fetch = async (_input, init) => {
    sent = JSON.parse(String(init?.body));
    return ndjsonResponse(['{"type":"text","text":"Hi"}\n{"type":"disc', 'laimer","text":"D"}\n{"type":"done"}\n']);
  };
  const events: ChatEvent[] = [];
  const turns: ChatTurn[] = Array.from({ length: 15 }, (_, i) => ({ role: i % 2 === 0 ? "user" : "assistant", text: `m${i}` }));
  await streamChat(turns, "AAPL", (e) => events.push(e));
  assert.ok(sent.messages.length <= MAX_SENT_MESSAGES && sent.messages[0].role === "user");
  assert.deepEqual(sent.context, { ticker: "AAPL" });
  assert.deepEqual(events.map((e) => e.type), ["text", "disclaimer", "done"]);

  await streamChat([{ role: "user", text: "q" }], undefined, () => undefined);
  assert.equal("context" in sent, false);
});

test("streamChat turns server errors into ChatError with the server's friendly message", async () => {
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ error: "rate_limited", message: "Please wait.", retry_after_seconds: 12 }), { status: 429 });
  await assert.rejects(
    streamChat([{ role: "user", text: "q" }], undefined, () => undefined),
    (error: unknown) => {
      assert.ok(error instanceof ChatError);
      assert.equal(error.code, "rate_limited");
      assert.equal(error.message, "Please wait.");
      assert.equal(error.retryAfterSeconds, 12);
      return true;
    },
  );
  globalThis.fetch = async () => new Response("<html>oops</html>", { status: 502 });
  await assert.rejects(streamChat([{ role: "user", text: "q" }], undefined, () => undefined), (error: unknown) => {
    assert.ok(error instanceof ChatError);
    assert.equal(error.code, "upstream");
    assert.doesNotMatch(error.message, /html|oops/);
    return true;
  });
  globalThis.fetch = async () => {
    throw new TypeError("offline");
  };
  await assert.rejects(streamChat([{ role: "user", text: "q" }], undefined, () => undefined), (error: unknown) => {
    assert.ok(error instanceof ChatError && error.code === "network");
    return true;
  });
});
