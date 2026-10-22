import { ERR, guardRequest, handlePayload } from "@/lib/ai/mcp";

export const dynamic = "force-dynamic";

const HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

function json(status: number, body: unknown, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...HEADERS, ...extra } });
}

/**
 * MCP over HTTP (stateless): one JSON-RPC message or batch per POST.
 * Point an MCP client at http://localhost:3000/api/mcp (see web/CLAUDE.md).
 */
export async function POST(request: Request) {
  const guard = guardRequest(request);
  if (!guard.ok) return json(guard.status, { error: guard.message });

  const text = await request.text();
  if (text.length > 200_000) return json(413, { error: "Request too large." });

  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    return json(400, { jsonrpc: "2.0", id: null, error: { code: ERR.parse, message: "Parse error." } });
  }

  const response = await handlePayload(payload);
  // Only notifications were sent: acknowledge without a body.
  if (response === null) return new Response(null, { status: 202 });
  return json(200, response);
}

/** This server has no streaming channel, which the protocol allows. */
export function GET() {
  return json(405, { error: "Use POST." }, { allow: "POST" });
}

export function DELETE() {
  return json(405, { error: "Use POST." }, { allow: "POST" });
}
