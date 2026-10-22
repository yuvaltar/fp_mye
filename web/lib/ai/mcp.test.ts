import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  ERR,
  SERVER_INFO,
  SUPPORTED_PROTOCOL_VERSIONS,
  guardRequest,
  handleMessage,
  handlePayload,
  type JsonRpcResponse,
} from "./mcp.ts";
import { DISCLAIMER_SHORT } from "./policy.ts";
import { TOOLS } from "./tools.ts";

beforeEach(() => {
  process.env.NEXT_PUBLIC_USE_MOCKS = "true";
});

afterEach(() => {
  delete process.env.NEXT_PUBLIC_USE_MOCKS;
});

const rpc = (id: number | string | null, method: string, params?: Record<string, unknown>) => ({
  jsonrpc: "2.0" as const,
  id,
  method,
  ...(params ? { params } : {}),
});

async function call(method: string, params?: Record<string, unknown>): Promise<JsonRpcResponse> {
  const response = await handleMessage(rpc(1, method, params));
  assert.ok(response, `no response to ${method}`);
  return response;
}

test("initialize negotiates a supported protocol version and describes the server", async () => {
  for (const version of SUPPORTED_PROTOCOL_VERSIONS) {
    const response = await call("initialize", { protocolVersion: version, capabilities: {}, clientInfo: { name: "t", version: "1" } });
    assert.equal((response.result as any).protocolVersion, version);
  }
  const unknown = await call("initialize", { protocolVersion: "1999-01-01" });
  assert.equal((unknown.result as any).protocolVersion, SUPPORTED_PROTOCOL_VERSIONS[0]);
  const noVersion = await call("initialize", {});
  assert.equal((noVersion.result as any).protocolVersion, SUPPORTED_PROTOCOL_VERSIONS[0]);

  const result = unknown.result as any;
  assert.deepEqual(result.serverInfo, SERVER_INFO);
  assert.ok(result.capabilities.tools && result.capabilities.resources && result.capabilities.prompts);
  assert.match(result.instructions, /not financial, investment, tax or legal advice/);
  assert.match(result.instructions, /as_of_date/);
});

test("responses carry the request id and the jsonrpc version", async () => {
  for (const id of [1, "abc", 0, null]) {
    const response = await handleMessage(rpc(id, "ping"));
    assert.deepEqual(response, { jsonrpc: "2.0", id, result: {} });
  }
});

test("notifications get no response", async () => {
  assert.equal(await handleMessage({ jsonrpc: "2.0", method: "notifications/initialized" }), null);
  assert.equal(await handleMessage({ jsonrpc: "2.0", method: "notifications/cancelled", params: { requestId: 1 } }), null);
  assert.equal(await handleMessage({ jsonrpc: "2.0", method: "something/unknown" }), null);
});

test("tools/list exposes every tool as read-only with a valid input schema", async () => {
  const { tools } = (await call("tools/list")).result as { tools: any[] };
  assert.equal(tools.length, TOOLS.length);
  for (const tool of tools) {
    assert.match(tool.name, /^[a-z][a-z0-9_]*$/);
    assert.ok(tool.description.length > 20);
    assert.equal(tool.inputSchema.type, "object");
    assert.deepEqual(tool.annotations, { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false });
  }
  assert.ok(tools.some((t) => t.name === "get_risk_brief"));
});

test("tools/call returns the data as text plus the disclaimer, flagged not-an-error", async () => {
  const response = await call("tools/call", { name: "get_risk_brief", arguments: { ticker: "AAPL" } });
  const result = response.result as any;
  assert.equal(result.isError, false);
  assert.equal(result.content.length, 2);
  assert.equal(result.content[0].type, "text");
  const payload = JSON.parse(result.content[0].text);
  assert.equal(payload.ok, true);
  assert.equal(payload.ticker, "AAPL");
  assert.equal(payload.as_of_date, "2026-10-07");
  assert.equal(result.content[1].text, DISCLAIMER_SHORT);
});

test("a tool that cannot answer is an isError result, not a protocol error", async () => {
  const response = await call("tools/call", { name: "get_risk_brief", arguments: { ticker: "ZZZZ" } });
  assert.equal(response.error, undefined);
  const result = response.result as any;
  assert.equal(result.isError, true);
  assert.equal(JSON.parse(result.content[0].text).error, "not_covered");
  const invalid = (await call("tools/call", { name: "get_risk_brief", arguments: { ticker: 5 } })).result as any;
  assert.equal(invalid.isError, true);
  const noArgs = (await call("tools/call", { name: "get_engine_accuracy" })).result as any;
  assert.equal(noArgs.isError, false);
});

test("an unknown tool is an invalid-params protocol error", async () => {
  const response = await call("tools/call", { name: "transfer_money", arguments: {} });
  assert.equal(response.result, undefined);
  assert.equal(response.error?.code, ERR.invalidParams);
  assert.match(response.error?.message ?? "", /Unknown tool/);
  const missing = await call("tools/call", {});
  assert.equal(missing.error?.code, ERR.invalidParams);
});

test("resources: glossary, methodology and disclaimer can be listed and read", async () => {
  const { resources } = (await call("resources/list")).result as { resources: any[] };
  assert.deepEqual(resources.map((r) => r.uri).sort(), ["tsm://disclaimer", "tsm://glossary", "tsm://methodology"]);
  for (const resource of resources) {
    const read = (await call("resources/read", { uri: resource.uri })).result as any;
    assert.equal(read.contents[0].uri, resource.uri);
    assert.equal(read.contents[0].mimeType, "text/markdown");
    assert.ok(read.contents[0].text.length > 100);
  }
  const disclaimer = ((await call("resources/read", { uri: "tsm://disclaimer" })).result as any).contents[0].text;
  assert.match(disclaimer, /Nothing on this site, including the AI assistant, is financial, investment, tax, accounting or legal advice/);
  assert.match(disclaimer, /does not predict whether the price will go up or down/);
  const glossary = ((await call("resources/read", { uri: "tsm://glossary" })).result as any).contents[0].text;
  assert.match(glossary, /not a probability/);
  const missing = await call("resources/read", { uri: "tsm://nope" });
  assert.equal(missing.error?.code, ERR.resourceNotFound);
});

test("prompts: listed, built from arguments, and always carry the no-advice instruction", async () => {
  const { prompts } = (await call("prompts/list")).result as { prompts: any[] };
  assert.deepEqual(prompts.map((p) => p.name).sort(), ["compare_stocks", "earnings_week", "risk_briefing"]);

  const briefing = (await call("prompts/get", { name: "risk_briefing", arguments: { ticker: "NVDA" } })).result as any;
  assert.equal(briefing.messages[0].role, "user");
  assert.match(briefing.messages[0].content.text, /risk briefing for NVDA/);
  assert.match(briefing.messages[0].content.text, /do not give investment advice or say whether to buy or sell/);

  const compare = (await call("prompts/get", { name: "compare_stocks", arguments: { tickers: "AAPL, TEVA" } })).result as any;
  assert.match(compare.messages[0].content.text, /AAPL, TEVA/);
  const week = (await call("prompts/get", { name: "earnings_week" })).result as any;
  assert.match(week.messages[0].content.text, /not give investment advice/);

  assert.equal((await call("prompts/get", { name: "risk_briefing", arguments: {} })).error?.code, ERR.invalidParams);
  assert.equal((await call("prompts/get", { name: "nope" })).error?.code, ERR.invalidParams);
});

test("prompt arguments are trimmed and length-limited", async () => {
  const long = "A".repeat(1000);
  const result = (await call("prompts/get", { name: "risk_briefing", arguments: { ticker: `  ${long}  ` } })).result as any;
  assert.ok(result.messages[0].content.text.length < 800);
});

test("unknown methods and malformed messages return the right JSON-RPC errors", async () => {
  assert.equal((await call("tools/destroy")).error?.code, ERR.methodNotFound);
  for (const bad of [null, "text", 5, {}, { jsonrpc: "1.0", id: 1, method: "ping" }, { jsonrpc: "2.0", id: 1 }, { jsonrpc: "2.0", id: 1, method: 5 }]) {
    const response = await handleMessage(bad);
    assert.equal(response?.error?.code, ERR.invalidRequest, JSON.stringify(bad));
  }
});

test("batches answer every request, skip notifications, and reject an empty batch", async () => {
  const responses = (await handlePayload([
    rpc(1, "ping"),
    { jsonrpc: "2.0", method: "notifications/initialized" },
    rpc(2, "tools/list"),
  ])) as JsonRpcResponse[];
  assert.deepEqual(responses.map((r) => r.id), [1, 2]);
  assert.equal(await handlePayload([{ jsonrpc: "2.0", method: "notifications/initialized" }]), null);
  const empty = (await handlePayload([])) as JsonRpcResponse;
  assert.equal(empty.error?.code, ERR.invalidRequest);
});

// ---------------------------------------------------------------------------
// Who may call the HTTP endpoint
// ---------------------------------------------------------------------------

function http(url: string, headers: Record<string, string> = {}): Request {
  return new Request(url, { method: "POST", headers, body: "{}" });
}

test("without a token the endpoint answers on localhost in development", () => {
  assert.deepEqual(guardRequest(http("http://localhost:3000/api/mcp"), {}), { ok: true });
  assert.deepEqual(guardRequest(http("http://127.0.0.1:3000/api/mcp"), { NODE_ENV: "development" }), { ok: true });
});

test("without a token the endpoint is closed in production and on other hosts", () => {
  const production = guardRequest(http("http://localhost:3000/api/mcp"), { NODE_ENV: "production" });
  assert.equal(production.ok, false);
  const remote = guardRequest(http("https://site.example/api/mcp"), {});
  assert.deepEqual(remote.ok === false && remote.status, 403);
});

test("with a token, only the exact bearer token passes", () => {
  const env = { MCP_AUTH_TOKEN: "s3cret-token", NODE_ENV: "production" };
  const url = "https://site.example/api/mcp";
  assert.deepEqual(guardRequest(http(url, { authorization: "Bearer s3cret-token" }), env), { ok: true });
  for (const authorization of [undefined, "Bearer wrong", "Bearer s3cret-toke", "Bearer s3cret-token2", "s3cret-token", "Basic s3cret-token", "Bearer "]) {
    const result = guardRequest(http(url, authorization ? { authorization } : {}), env);
    assert.equal(result.ok, false, String(authorization));
    assert.equal(result.ok === false && result.status, 401);
  }
});

test("a browser Origin must be this site's own or explicitly allowed (DNS rebinding protection)", () => {
  const url = "http://localhost:3000/api/mcp";
  assert.deepEqual(guardRequest(http(url, { origin: "http://localhost:3000" }), {}), { ok: true });
  const evil = guardRequest(http(url, { origin: "https://evil.example" }), {});
  assert.equal(evil.ok === false && evil.status, 403);
  assert.deepEqual(guardRequest(http(url, { origin: "https://good.example" }), { MCP_ALLOWED_ORIGINS: "https://good.example, https://other.example" }), { ok: true });
  assert.equal(guardRequest(http(url, { origin: "garbage" }), {}).ok, false);
});
