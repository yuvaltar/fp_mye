/**
 * A live check of the assistant against the REAL Gemini service, for you to run
 * once with your own free key (the automated tests never call Google):
 *
 *   cd web
 *   GEMINI_API_KEY=your-key node --experimental-strip-types scripts/ai-smoke.ts
 *
 * Optional: GEMINI_MODEL=..., and a question as the first argument. The site
 * data comes from the mock files unless NEXT_PUBLIC_USE_MOCKS=false is set.
 * It prints what the model answers and which tools it used; the key is never printed.
 */
import { readAssistantConfig } from "../lib/ai/config.ts";
import { runAssistant } from "../lib/ai/gemini.ts";
import { DISCLAIMER_SHORT, buildSystemPrompt } from "../lib/ai/policy.ts";
import { TOOLS, runTool } from "../lib/ai/tools.ts";

const config = readAssistantConfig();
if (!config.enabled || !config.settings) {
  process.stderr.write("Set GEMINI_API_KEY first (a free key from Google AI Studio).\n");
  process.exit(2);
}

const question = process.argv[2] ?? "Give me a risk briefing on AAPL.";
process.stdout.write(`Model: ${config.settings.model}\nQuestion: ${question}\n\n`);

let failed = false;
let text = "";
for await (const event of runAssistant({
  settings: config.settings,
  system: buildSystemPrompt({ today: new Date().toISOString().slice(0, 10) }),
  messages: [{ role: "user", text: question }],
  tools: TOOLS,
  execute: runTool,
})) {
  if (event.type === "text") {
    text += event.text;
    process.stdout.write(event.text);
  } else if (event.type === "tool") {
    process.stdout.write(`\n[tool] ${event.name}\n`);
  } else if (event.type === "tool_done") {
    process.stdout.write(`[tool done] ${event.name} ok=${event.ok}\n`);
  } else if (event.type === "error") {
    failed = true;
    process.stderr.write(`\n[error] ${event.code}: ${event.message}\n`);
  }
}

process.stdout.write(`\n\n${DISCLAIMER_SHORT}\n`);
if (!failed && text.trim() === "") {
  process.stderr.write("The model returned no text.\n");
  failed = true;
}
process.exit(failed ? 1 : 0);
