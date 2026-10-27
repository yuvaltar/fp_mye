/**
 * The same MCP server over stdio, for local clients (Claude Desktop, Claude
 * Code, Gemini CLI). One JSON-RPC message per line on stdin, one response per
 * line on stdout; logs go to stderr only, because stdout is the protocol.
 *
 * Run from the web/ folder:
 *   node --experimental-strip-types scripts/mcp-stdio.ts
 * Environment (set in the client's MCP configuration; .env.local is not read here):
 *   NEXT_PUBLIC_USE_MOCKS=false  NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8766
 *   NEXT_PUBLIC_LIVE_MARKET_DATA=true
 */
import { createInterface } from "node:readline";
import { ERR, handlePayload } from "../lib/ai/mcp.ts";

const reader = createInterface({ input: process.stdin, crlfDelay: Infinity });
let pending = 0;
let closed = false;

function send(message: unknown): void {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function maybeExit(): void {
  if (closed && pending === 0) process.exit(0);
}

reader.on("line", (line) => {
  if (line.trim() === "") return;
  pending += 1;
  void (async () => {
    try {
      let payload: unknown;
      try {
        payload = JSON.parse(line);
      } catch {
        send({ jsonrpc: "2.0", id: null, error: { code: ERR.parse, message: "Parse error." } });
        return;
      }
      const response = await handlePayload(payload);
      if (response !== null) send(response);
    } catch (error) {
      process.stderr.write(`mcp-stdio: ${error instanceof Error ? error.message : String(error)}\n`);
    } finally {
      pending -= 1;
      maybeExit();
    }
  })();
});

reader.on("close", () => {
  closed = true;
  maybeExit();
});

process.stderr.write("temporal-skills-market MCP server (stdio) ready\n");
