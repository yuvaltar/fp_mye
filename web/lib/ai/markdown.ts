/**
 * A tiny, safe Markdown reader for assistant answers: paragraphs, bullet and
 * numbered lists, and **bold** / `code` inside them. It returns data, not HTML,
 * so React renders every character as text and nothing the model writes can
 * become markup or a script. Unfinished syntax while streaming (an open "**")
 * stays plain text until it closes.
 */

export type Inline = { kind: "text" | "bold" | "code"; text: string };

export type Block =
  | { kind: "paragraph"; inlines: Inline[] }
  | { kind: "bullets"; items: Inline[][] }
  | { kind: "numbered"; items: Inline[][] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d{1,2}[.)]\s+(.*)$/;

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const pattern = /\*\*([^*\n]+)\*\*|`([^`\n]+)`/g;
  let last = 0;
  for (let match = pattern.exec(text); match !== null; match = pattern.exec(text)) {
    if (match.index > last) out.push({ kind: "text", text: text.slice(last, match.index) });
    if (match[1] !== undefined) out.push({ kind: "bold", text: match[1] });
    else if (match[2] !== undefined) out.push({ kind: "code", text: match[2] });
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { kind: "bullets" | "numbered"; items: Inline[][] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ kind: "paragraph", inlines: parseInline(paragraph.join(" ")) });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      blocks.push(list);
      list = null;
    }
  };

  for (const line of source.replace(/\r\n?/g, "\n").split("\n")) {
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const kind = bullet ? "bullets" : "numbered";
      if (list && list.kind !== kind) flushList();
      list ??= { kind, items: [] };
      list.items.push(parseInline(((bullet ?? numbered) as RegExpExecArray)[1] ?? ""));
    } else if (line.trim() === "") {
      flushParagraph();
      flushList();
    } else if (list && /^\s{2,}\S/.test(line)) {
      // An indented continuation of the previous list item.
      const items = list.items;
      const previous = items[items.length - 1];
      if (previous) previous.push(...parseInline(` ${line.trim()}`));
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}

/** Plain text of a block list, for tests and for copying. */
export function toPlainText(blocks: readonly Block[]): string {
  const inline = (parts: Inline[]) => parts.map((p) => p.text).join("");
  return blocks
    .map((block) =>
      block.kind === "paragraph"
        ? inline(block.inlines)
        : block.items.map((item, i) => `${block.kind === "numbered" ? `${i + 1}.` : "-"} ${inline(item)}`).join("\n"),
    )
    .join("\n\n");
}
