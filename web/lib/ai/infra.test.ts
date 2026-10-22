import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { DEFAULT_MODEL, SETUP_HINT, publicStatus, readAssistantConfig } from "./config.ts";
import { RateLimiter, clientKey } from "./rate-limit.ts";

// --- configuration ----------------------------------------------------------

test("the assistant is off without a key, on with one, and can be switched off explicitly", () => {
  assert.deepEqual(readAssistantConfig({}), { enabled: false, settings: null });
  assert.deepEqual(readAssistantConfig({ GEMINI_API_KEY: "   " }), { enabled: false, settings: null });
  const on = readAssistantConfig({ GEMINI_API_KEY: " KEY " });
  assert.equal(on.enabled, true);
  assert.deepEqual(on.settings, { apiKey: "KEY", model: DEFAULT_MODEL });
  assert.equal(readAssistantConfig({ GEMINI_API_KEY: "KEY", ASSISTANT_ENABLED: "false" }).enabled, false);
  assert.equal(readAssistantConfig({ GEMINI_API_KEY: "KEY", ASSISTANT_ENABLED: "FALSE" }).enabled, false);
  assert.equal(readAssistantConfig({ GEMINI_API_KEY: "KEY", ASSISTANT_ENABLED: "true" }).enabled, true);
});

test("the model and the base URL come from the environment", () => {
  const config = readAssistantConfig({ GEMINI_API_KEY: "KEY", GEMINI_MODEL: "gemini-custom", GEMINI_BASE_URL: "http://localhost:1234" });
  assert.deepEqual(config.settings, { apiKey: "KEY", model: "gemini-custom", baseUrl: "http://localhost:1234" });
  assert.match(DEFAULT_MODEL, /^gemini-/);
});

test("the public status exposes only whether the assistant is on", () => {
  const status = publicStatus(readAssistantConfig({ GEMINI_API_KEY: "SECRET" }));
  assert.deepEqual(Object.keys(status).sort(), ["enabled", "model"]);
  assert.ok(!JSON.stringify(status).includes("SECRET"));
});

test("the setup hint is sent only by a development server and only when the assistant is off", () => {
  const off = readAssistantConfig({});
  assert.deepEqual(publicStatus(off, { NODE_ENV: "development" }), { enabled: false, model: null, setup: SETUP_HINT });
  assert.deepEqual(publicStatus(off, { NODE_ENV: "production" }), { enabled: false, model: null });
  assert.deepEqual(publicStatus(off, {}), { enabled: false, model: null });
  const on = readAssistantConfig({ GEMINI_API_KEY: "KEY" });
  assert.deepEqual(Object.keys(publicStatus(on, { NODE_ENV: "development" })).sort(), ["enabled", "model"]);
  assert.match(SETUP_HINT, /GEMINI_API_KEY/);
  assert.ok(!SETUP_HINT.includes("AIza"), "the hint never contains a key");
});

// --- rate limiter -----------------------------------------------------------

test("the limiter allows up to the per-minute limit and reports when to retry", () => {
  let now = 0;
  const limiter = new RateLimiter({ perMinute: 3, perDay: 100 }, () => now);
  for (let i = 0; i < 3; i++) assert.deepEqual(limiter.check("a"), { allowed: true });
  const blocked = limiter.check("a");
  assert.equal(blocked.allowed, false);
  if (!blocked.allowed) {
    assert.equal(blocked.reason, "minute");
    assert.equal(blocked.retryAfterSeconds, 60);
  }
  now += 30_000;
  const still = limiter.check("a");
  assert.equal(still.allowed === false && still.retryAfterSeconds, 30);
  now += 31_000;
  assert.deepEqual(limiter.check("a"), { allowed: true });
});

test("the daily limit applies across minutes", () => {
  let now = 0;
  const limiter = new RateLimiter({ perMinute: 5, perDay: 6 }, () => now);
  for (let i = 0; i < 6; i++) {
    assert.deepEqual(limiter.check("a"), { allowed: true });
    now += 61_000;
  }
  const blocked = limiter.check("a");
  assert.equal(blocked.allowed === false && blocked.reason, "day");
  now += 86_400_000;
  assert.deepEqual(limiter.check("a"), { allowed: true });
});

test("keys are independent and blocked requests are not counted", () => {
  let now = 0;
  const limiter = new RateLimiter({ perMinute: 1, perDay: 10 }, () => now);
  assert.deepEqual(limiter.check("a"), { allowed: true });
  assert.equal(limiter.check("a").allowed, false);
  assert.deepEqual(limiter.check("b"), { allowed: true });
  now += 60_001;
  assert.deepEqual(limiter.check("a"), { allowed: true });
});

test("the visitor key comes from the first forwarded address and falls back safely", () => {
  assert.equal(clientKey(new Headers({ "x-forwarded-for": "1.2.3.4, 10.0.0.1" })), "1.2.3.4");
  assert.equal(clientKey(new Headers()), "local");
  assert.equal(clientKey(new Headers({ "x-forwarded-for": "x".repeat(200) })), "local");
});

// --- the stdio MCP server, run for real -------------------------------------

function runStdio(inputLines: string[]): Promise<{ stdout: string[]; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ["--experimental-strip-types", "--no-warnings", "scripts/mcp-stdio.ts"], {
      cwd: process.cwd(),
      env: { ...process.env, NEXT_PUBLIC_USE_MOCKS: "true", NEXT_PUBLIC_LIVE_MARKET_DATA: "false" },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    child.on("error", reject);
    child.on("close", () => resolve({ stdout: stdout.split("\n").filter(Boolean), stderr }));
    child.stdin.end(inputLines.join("\n") + "\n");
    setTimeout(() => child.kill(), 30_000).unref();
  });
}

test("the stdio server speaks MCP: initialize, list, call, errors and a parse error", async () => {
  const { stdout, stderr } = await runStdio([
    JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18" } }),
    JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
    JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }),
    JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "get_risk_brief", arguments: { ticker: "NVDA" } } }),
    JSON.stringify({ jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "nope" } }),
    "this is not json",
  ]);
  const messages = stdout.map((line) => JSON.parse(line));
  const byId = new Map(messages.map((m) => [m.id, m]));
  assert.equal(messages.length, 5, "one response per request, none for the notification");
  assert.equal(byId.get(1).result.serverInfo.name, "temporal-skills-market");
  assert.ok(byId.get(2).result.tools.length >= 7);
  const brief = JSON.parse(byId.get(3).result.content[0].text);
  assert.equal(brief.ticker, "NVDA");
  assert.equal(brief.as_of_date, "2026-10-07");
  assert.equal(byId.get(4).error.code, -32602);
  assert.equal(byId.get(null).error.code, -32700);
  assert.match(stderr, /ready/);
  for (const line of stdout) assert.ok(line.startsWith("{"), "stdout carries only protocol messages");
});
