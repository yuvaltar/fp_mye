import { handleChat, handleStatus } from "@/lib/ai/chat";

export const dynamic = "force-dynamic";

/** GET /api/chat: is the assistant on? */
export function GET() {
  return handleStatus();
}

/** POST /api/chat: one question, answered as a stream of JSON lines. */
export function POST(request: Request) {
  return handleChat(request);
}
