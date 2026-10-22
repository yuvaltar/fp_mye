/**
 * A Model Context Protocol server for the site's data, over JSON-RPC 2.0.
 * Stateless: every request stands alone, so it works as a plain POST endpoint
 * (app/api/mcp/route.ts) and over stdio (scripts/mcp-stdio.ts) with the same
 * handler. It exposes the assistant's tools (read-only), a few resources
 * (glossary, methodology, disclaimer) and ready-made prompts.
 *
 * Written without the MCP SDK on purpose (no new dependency); the surface is
 * small and covered by tests. Imports are relative with .ts extensions so
 * node:test and the stdio script can run this file.
 */
import { DISCLAIMER_SECTIONS, DISCLAIMER_SHORT } from "./policy.ts";
import { TOOLS, findTool, runTool, serializeResult } from "./tools.ts";

export const SERVER_INFO = { name: "temporal-skills-market", title: "Temporal Skills Market", version: "0.1.0" } as const;
export const SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"] as const;

export type JsonRpcId = string | number | null;

export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: JsonRpcId;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: JsonRpcId;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

export const ERR = {
  parse: -32700,
  invalidRequest: -32600,
  methodNotFound: -32601,
  invalidParams: -32602,
  internal: -32603,
  resourceNotFound: -32002,
} as const;

const fail = (id: JsonRpcId, code: number, message: string): JsonRpcResponse => ({
  jsonrpc: "2.0",
  id,
  error: { code, message },
});
const succeed = (id: JsonRpcId, result: unknown): JsonRpcResponse => ({ jsonrpc: "2.0", id, result });

// ---------------------------------------------------------------------------
// Resources and prompts
// ---------------------------------------------------------------------------

const GLOSSARY = `# Glossary

- **Volatility**: how hard a stock's price jumps around, regardless of direction. Shown as an annualized rate: 24.0% means the stock moves as if its yearly volatility were 24%. A week's typical move is about the annual figure divided by 7.1.
- **Expected volatility (predicted_vol)**: the engine's prediction of the volatility of the next 5 trading days after as_of_date.
- **HAR-RV baseline**: a standard statistical model for volatility forecasts. The engine is only useful if it does better.
- **Skill**: one prediction model in the committee (HAR-RV with the earnings jump, GARCH, Boosting, iTransformer).
- **Supervisor**: weights the skills by their recent accuracy and combines them into the final prediction.
- **Supervisor recent accuracy (supervisor_confidence)**: a 0 to 100% score of how well the supervisor itself predicted lately. It is not a probability.
- **Realized volatility**: the volatility that actually occurred, measured from daily closes.
- **QLIKE**: the standard error measure for volatility forecasts. Lower is better; it punishes predicting too low more than too high.
- **Earnings week**: a week in which the company reports quarterly results. The engine raises its forecast in such weeks.
- **Walk-forward backtest**: every past date is predicted using only information available on that date.
`;

const METHODOLOGY = `# Methodology

Several separate models each predict the next 5 trading days' volatility on their own. Every day, for every stock, a supervisor scores each model on its last 60 to 120 predictions whose outcome is already known and gives better scorers more weight; the weights add up to 100%. The final prediction is the weighted combination, shown next to the HAR-RV baseline.

Each model's output is calibrated before it is compared. In earnings weeks the engine adds the stock's typical earnings jump, estimated only from earlier reports.

The engine is evaluated with a walk-forward backtest over 2020 to 2026 on 52 large US-listed stocks. Its QLIKE error is lower than HAR-RV's on average and on every ticker; the margin is modest, there is survivorship bias, and consecutive dates overlap. Predictions come from the engine's latest run and can be days old; market prices come from Yahoo Finance and are delayed.
`;

const DISCLAIMER_DOC = [
  "# Disclaimer",
  "",
  ...DISCLAIMER_SECTIONS.flatMap((section) => [`## ${section.title}`, "", ...section.paragraphs, ""]),
].join("\n");

interface Resource {
  uri: string;
  name: string;
  title: string;
  description: string;
  mimeType: string;
  text: string;
}

const RESOURCES: readonly Resource[] = [
  { uri: "tsm://glossary", name: "glossary", title: "Glossary", description: "What the site's terms mean.", mimeType: "text/markdown", text: GLOSSARY },
  { uri: "tsm://methodology", name: "methodology", title: "Methodology", description: "How the predictions are made and how they are evaluated.", mimeType: "text/markdown", text: METHODOLOGY },
  { uri: "tsm://disclaimer", name: "disclaimer", title: "Disclaimer", description: "Legal notice: educational information, not financial advice.", mimeType: "text/markdown", text: DISCLAIMER_DOC },
];

interface PromptArgument {
  name: string;
  description: string;
  required: boolean;
}

interface PromptDef {
  name: string;
  title: string;
  description: string;
  arguments: PromptArgument[];
  build(args: Record<string, string>): string;
}

const NO_ADVICE = "Use only data from the tools, mention the as_of_date, and do not give investment advice or say whether to buy or sell.";

const PROMPTS: readonly PromptDef[] = [
  {
    name: "risk_briefing",
    title: "Risk briefing",
    description: "A plain-language risk briefing for one stock.",
    arguments: [{ name: "ticker", description: "Ticker symbol, for example AAPL.", required: true }],
    build: (args) =>
      `Write a short risk briefing for ${args.ticker}: expected volatility for the next 5 trading days and how it compares with the baseline and with the stock's past, whether an earnings report falls in the week, whether the models agree, and how accurate the engine has been on this stock. ${NO_ADVICE}`,
  },
  {
    name: "compare_stocks",
    title: "Compare stocks",
    description: "Compare the expected volatility of several stocks.",
    arguments: [{ name: "tickers", description: "Two to four ticker symbols separated by commas.", required: true }],
    build: (args) =>
      `Compare the expected volatility of ${args.tickers} for the next 5 trading days: which is expected to move most, how each compares with its baseline, and any earnings reports in the week. ${NO_ADVICE}`,
  },
  {
    name: "earnings_week",
    title: "Earnings this week",
    description: "Which companies report earnings inside the prediction window, and what that does to their forecasts.",
    arguments: [],
    build: () =>
      `List the companies that report earnings in the week covered by the latest predictions and explain what the earnings effect does to their forecasts. ${NO_ADVICE}`,
  },
];

// ---------------------------------------------------------------------------
// The handler
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function negotiate(requested: unknown): string {
  const supported: readonly string[] = SUPPORTED_PROTOCOL_VERSIONS;
  return typeof requested === "string" && supported.includes(requested)
    ? requested
    : (SUPPORTED_PROTOCOL_VERSIONS[0] as string);
}

/** Handles one JSON-RPC message. Returns null for a notification (no response is sent). */
export async function handleMessage(message: unknown): Promise<JsonRpcResponse | null> {
  if (!isRecord(message) || message.jsonrpc !== "2.0" || typeof message.method !== "string") {
    return fail(isRecord(message) && "id" in message ? ((message.id as JsonRpcId) ?? null) : null, ERR.invalidRequest, "Invalid JSON-RPC request.");
  }
  const hasId = "id" in message && message.id !== undefined;
  const id = hasId ? (message.id as JsonRpcId) : null;
  const params = isRecord(message.params) ? message.params : {};
  const method = message.method;

  // Notifications never get a response.
  if (!hasId) return null;

  switch (method) {
    case "initialize":
      return succeed(id, {
        protocolVersion: negotiate(params.protocolVersion),
        capabilities: { tools: { listChanged: false }, resources: { subscribe: false, listChanged: false }, prompts: { listChanged: false } },
        serverInfo: SERVER_INFO,
        instructions: `${DISCLAIMER_SHORT} Volatility is the size of price moves, not their direction. Every prediction carries an as_of_date: always report it.`,
      });

    case "ping":
      return succeed(id, {});

    case "tools/list":
      return succeed(id, {
        tools: TOOLS.map((tool) => ({
          name: tool.name,
          title: tool.name.replace(/_/g, " "),
          description: tool.description,
          inputSchema: tool.inputSchema,
          annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
        })),
      });

    case "tools/call": {
      const name = params.name;
      if (typeof name !== "string" || !findTool(name)) return fail(id, ERR.invalidParams, `Unknown tool: ${String(name)}`);
      const result = await runTool(name, params.arguments);
      return succeed(id, {
        content: [
          { type: "text", text: serializeResult(result) },
          { type: "text", text: DISCLAIMER_SHORT },
        ],
        isError: !result.ok,
      });
    }

    case "resources/list":
      return succeed(id, {
        resources: RESOURCES.map(({ uri, name, title, description, mimeType }) => ({ uri, name, title, description, mimeType })),
      });

    case "resources/read": {
      const resource = RESOURCES.find((r) => r.uri === params.uri);
      if (!resource) return fail(id, ERR.resourceNotFound, `Resource not found: ${String(params.uri)}`);
      return succeed(id, { contents: [{ uri: resource.uri, mimeType: resource.mimeType, text: resource.text }] });
    }

    case "prompts/list":
      return succeed(id, {
        prompts: PROMPTS.map(({ name, title, description, arguments: args }) => ({ name, title, description, arguments: args })),
      });

    case "prompts/get": {
      const prompt = PROMPTS.find((p) => p.name === params.name);
      if (!prompt) return fail(id, ERR.invalidParams, `Unknown prompt: ${String(params.name)}`);
      const given = isRecord(params.arguments) ? params.arguments : {};
      const args: Record<string, string> = {};
      for (const definition of prompt.arguments) {
        const value = given[definition.name];
        if (typeof value === "string" && value.trim() !== "") args[definition.name] = value.trim().slice(0, 200);
        else if (definition.required) return fail(id, ERR.invalidParams, `Missing argument: ${definition.name}`);
      }
      return succeed(id, {
        description: prompt.description,
        messages: [{ role: "user", content: { type: "text", text: prompt.build(args) } }],
      });
    }

    default:
      return fail(id, ERR.methodNotFound, `Method not found: ${method}`);
  }
}

/** A whole POST body: one message or a batch. Returns null when nothing needs to be sent back. */
export async function handlePayload(payload: unknown): Promise<JsonRpcResponse | JsonRpcResponse[] | null> {
  if (Array.isArray(payload)) {
    if (payload.length === 0) return fail(null, ERR.invalidRequest, "An empty batch is not allowed.");
    const responses = (await Promise.all(payload.map(handleMessage))).filter((r): r is JsonRpcResponse => r !== null);
    return responses.length > 0 ? responses : null;
  }
  return handleMessage(payload);
}

// ---------------------------------------------------------------------------
// HTTP guard: who may call the endpoint
// ---------------------------------------------------------------------------

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

export type GuardResult = { ok: true } | { ok: false; status: 401 | 403; message: string };

/**
 * With MCP_AUTH_TOKEN set, a matching "Authorization: Bearer" header is required.
 * Without it the endpoint answers only on localhost and never in production.
 * A browser Origin must be this site's own or listed in MCP_ALLOWED_ORIGINS
 * (protection against DNS rebinding and other sites calling a local server).
 */
export function guardRequest(request: Request, env: Record<string, string | undefined> = process.env): GuardResult {
  const url = new URL(request.url);

  const origin = request.headers.get("origin");
  if (origin !== null) {
    const allowed = (env.MCP_ALLOWED_ORIGINS ?? "").split(",").map((o) => o.trim()).filter(Boolean);
    let sameHost = false;
    try {
      sameHost = new URL(origin).host === url.host;
    } catch {
      sameHost = false;
    }
    if (!sameHost && !allowed.includes(origin)) return { ok: false, status: 403, message: "Origin not allowed." };
  }

  const token = env.MCP_AUTH_TOKEN?.trim();
  if (token) {
    const header = request.headers.get("authorization") ?? "";
    const given = header.startsWith("Bearer ") ? header.slice(7) : "";
    return timingSafeEqual(given, token) ? { ok: true } : { ok: false, status: 401, message: "A valid bearer token is required." };
  }
  if (env.NODE_ENV === "production") {
    return { ok: false, status: 401, message: "The MCP server is disabled: set MCP_AUTH_TOKEN to enable it." };
  }
  if (!LOCAL_HOSTS.has(url.hostname)) {
    return { ok: false, status: 403, message: "Without MCP_AUTH_TOKEN the MCP server answers only on localhost." };
  }
  return { ok: true };
}
