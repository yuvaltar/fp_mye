"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  ACK_STORAGE_KEY,
  ChatError,
  fetchAssistantStatus,
  streamChat,
  suggestionsFor,
  tickerFromPath,
  toolLabel,
  type AssistantStatus,
  type ChatEvent,
  type ChatTurn,
} from "@/lib/ai/chat-client";
import { parseMarkdown, type Block, type Inline } from "@/lib/ai/markdown";
import {
  ACKNOWLEDGEMENT_TEXT,
  DISCLAIMER_SHORT,
  PRIVACY_NOTICE,
  looksLikeAdviceRequest,
} from "@/lib/ai/policy";

const MAX_INPUT_CHARS = 2000;

interface ToolChip {
  name: string;
  done: boolean;
  ok: boolean;
}

interface Message {
  id: number;
  role: "user" | "assistant";
  text: string;
  tools: ToolChip[];
  disclaimer: string | null;
  error: string | null;
  streaming: boolean;
}

/** Reading and writing the accepted terms never breaks the page if storage is blocked. */
function readAcknowledged(): boolean {
  try {
    return window.localStorage.getItem(ACK_STORAGE_KEY) === "yes";
  } catch {
    return false;
  }
}

function writeAcknowledged(): void {
  try {
    window.localStorage.setItem(ACK_STORAGE_KEY, "yes");
  } catch {
    // The terms are asked again next time; nothing else depends on it.
  }
}

export function AssistantPanel() {
  const pathname = usePathname();
  const ticker = tickerFromPath(pathname);

  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const enabled = status === null ? null : status.enabled;
  const [acknowledged, setAcknowledged] = useState(false);
  const [ackChecked, setAckChecked] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const nextId = useRef(1);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Ask once, when the panel first opens, whether the assistant is switched on.
  useEffect(() => {
    if (!open || status !== null) return;
    const controller = new AbortController();
    setAcknowledged(readAcknowledged());
    void fetchAssistantStatus(controller.signal).then((result) => {
      if (!controller.signal.aborted) setStatus(result);
    });
    return () => controller.abort();
  }, [open, status]);

  useEffect(() => {
    const area = scrollRef.current;
    if (area) area.scrollTop = area.scrollHeight;
  }, [messages, open]);

  useEffect(() => {
    if (open && enabled && acknowledged) inputRef.current?.focus();
  }, [open, enabled, acknowledged]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const patchLast = useCallback((patch: (message: Message) => Message) => {
    setMessages((current) => {
      const last = current[current.length - 1];
      return last ? [...current.slice(0, -1), patch(last)] : current;
    });
  }, []);

  const applyEvent = useCallback(
    (event: ChatEvent) => {
      patchLast((message) => {
        switch (event.type) {
          case "text":
            return { ...message, text: message.text + event.text };
          case "tool":
            return { ...message, tools: [...message.tools, { name: event.name, done: false, ok: true }] };
          case "tool_done":
            return {
              ...message,
              tools: message.tools.map((chip) =>
                chip.name === event.name && !chip.done ? { ...chip, done: true, ok: event.ok } : chip,
              ),
            };
          case "disclaimer":
            return { ...message, disclaimer: event.text };
          case "error":
            return { ...message, error: event.message, streaming: false };
          case "done":
            return { ...message, streaming: false };
        }
      });
    },
    [patchLast],
  );

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim().slice(0, MAX_INPUT_CHARS);
      if (text === "" || busy) return;

      const history: ChatTurn[] = messages
        .filter((m) => m.text.trim() !== "" && m.error === null)
        .map((m) => ({ role: m.role, text: m.text }));
      const turns: ChatTurn[] = [...history, { role: "user", text }];

      const userMessage: Message = { id: nextId.current++, role: "user", text, tools: [], disclaimer: null, error: null, streaming: false };
      const reply: Message = { id: nextId.current++, role: "assistant", text: "", tools: [], disclaimer: null, error: null, streaming: true };
      setMessages((current) => [...current, userMessage, reply]);
      setInput("");
      setBusy(true);

      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await streamChat(turns, ticker, applyEvent, controller.signal);
        patchLast((message) => ({ ...message, streaming: false }));
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          patchLast((message) => ({ ...message, streaming: false }));
        } else {
          const message = error instanceof ChatError ? error.message : "Something went wrong. Please try again.";
          patchLast((m) => ({ ...m, error: message, streaming: false }));
        }
      } finally {
        setBusy(false);
        abortRef.current = null;
      }
    },
    [applyEvent, busy, messages, patchLast, ticker],
  );

  function stop() {
    abortRef.current?.abort();
  }

  function newChat() {
    abortRef.current?.abort();
    setMessages([]);
    setInput("");
  }

  function accept() {
    writeAcknowledged();
    setAcknowledged(true);
  }

  return (
    <>
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full border border-accent/50 bg-surface-raised px-4 py-2.5 text-sm font-medium shadow-lg transition-colors hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <span aria-hidden="true" className="size-2 rounded-full bg-accent" />
          Ask the assistant
        </button>
      ) : null}

      {open ? (
        <section
          role="dialog"
          aria-label="AI assistant"
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
          }}
          className="fixed inset-x-3 bottom-3 top-16 z-50 flex flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-2xl sm:inset-x-auto sm:bottom-4 sm:right-4 sm:top-auto sm:h-[36rem] sm:max-h-[calc(100vh-2rem)] sm:w-[26rem]"
        >
          <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">Assistant</h2>
              <span className="rounded-full border border-accent/40 bg-accent/10 px-2 py-px text-[0.65rem] font-medium uppercase tracking-wide text-accent">
                AI
              </span>
            </div>
            <div className="flex items-center gap-1">
              {messages.length > 0 ? (
                <button type="button" onClick={newChat} className={headerButton}>
                  New chat
                </button>
              ) : null}
              <button type="button" onClick={() => setOpen(false)} aria-label="Close the assistant" className={headerButton}>
                Close
              </button>
            </div>
          </header>

          <p className="border-b border-border bg-up/10 px-4 py-2 text-[0.72rem] leading-snug">
            {DISCLAIMER_SHORT}{" "}
            <Link href="/disclaimer" className="underline underline-offset-2 hover:text-accent">
              Full disclaimer
            </Link>
          </p>

          {enabled === null ? (
            <Centered>Checking the assistant…</Centered>
          ) : !enabled ? (
            <Centered>
              <strong className="block text-sm">The assistant is not switched on yet</strong>
              <span className="mt-1 block text-xs text-muted">The site works normally without it.</span>
              {status?.setup ? (
                <span className="mt-3 block rounded-md border border-border bg-surface-raised px-3 py-2 text-left text-xs leading-relaxed text-text">
                  {status.setup}
                </span>
              ) : null}
            </Centered>
          ) : !acknowledged ? (
            <div className="flex-1 overflow-y-auto p-4">
              <h3 className="text-sm font-semibold">Before you start</h3>
              <p className="mt-2 text-sm leading-relaxed">{ACKNOWLEDGEMENT_TEXT}</p>
              <p className="mt-2 text-xs leading-relaxed text-muted">{PRIVACY_NOTICE}</p>
              <label className="mt-4 flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={ackChecked}
                  onChange={(event) => setAckChecked(event.target.checked)}
                  className="mt-0.5 size-4 accent-[var(--color-accent)]"
                />
                <span>I understand and agree</span>
              </label>
              <button
                type="button"
                disabled={!ackChecked}
                onClick={accept}
                className="mt-4 rounded-md bg-accent px-4 py-2 text-sm font-medium text-background transition-opacity disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                Start chatting
              </button>
            </div>
          ) : (
            <>
              <div ref={scrollRef} role="log" aria-live="polite" className="flex-1 space-y-4 overflow-y-auto p-4">
                {messages.length === 0 ? (
                  <Welcome ticker={ticker} onPick={(text) => void send(text)} />
                ) : (
                  messages.map((message) => <MessageView key={message.id} message={message} />)
                )}
              </div>

              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void send(input);
                }}
                className="border-t border-border p-3"
              >
                {looksLikeAdviceRequest(input) ? (
                  <p className="mb-2 text-[0.72rem] text-up">
                    I can&apos;t tell you whether to buy or sell, but I can give you a risk briefing.
                  </p>
                ) : null}
                <div className="flex items-end gap-2">
                  <textarea
                    ref={inputRef}
                    dir="auto"
                    value={input}
                    onChange={(event) => setInput(event.target.value.slice(0, MAX_INPUT_CHARS))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void send(input);
                      }
                    }}
                    rows={2}
                    placeholder="Ask about a stock or the engine…"
                    aria-label="Your question"
                    className="max-h-32 min-h-[2.75rem] flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted focus-visible:outline-2 focus-visible:outline-accent"
                  />
                  {busy ? (
                    <button type="button" onClick={stop} className={sendButton}>
                      Stop
                    </button>
                  ) : (
                    <button type="submit" disabled={input.trim() === ""} className={sendButton}>
                      Send
                    </button>
                  )}
                </div>
                <p className="mt-1.5 text-[0.68rem] text-muted">
                  AI can be wrong. Check numbers on the stock pages.
                </p>
              </form>
            </>
          )}
        </section>
      ) : null}
    </>
  );
}

const headerButton =
  "rounded-md px-2 py-1 text-xs text-muted transition-colors hover:text-text focus-visible:outline-2 focus-visible:outline-accent";
const sendButton =
  "rounded-md bg-accent px-3 py-2 text-sm font-medium text-background transition-opacity disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex flex-1 flex-col items-center justify-center p-6 text-center text-sm text-muted">{children}</div>;
}

function Welcome({ ticker, onPick }: { ticker: string | undefined; onPick: (text: string) => void }) {
  return (
    <div>
      <p className="text-sm leading-relaxed">
        Ask me about the stocks on this site, in English or Hebrew. I give <strong>risk briefings</strong> from the
        engine&apos;s data. I don&apos;t give investment advice.
      </p>
      <ul className="mt-3 space-y-2">
        {suggestionsFor(ticker).map((question) => (
          <li key={question}>
            <button
              type="button"
              onClick={() => onPick(question)}
              className="w-full rounded-md border border-border bg-surface-raised px-3 py-2 text-left text-sm transition-colors hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-accent"
            >
              {question}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MessageView({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p
          dir="auto"
          className="max-w-[85%] whitespace-pre-wrap break-words rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-sm"
        >
          {message.text}
        </p>
      </div>
    );
  }
  return (
    <div className="max-w-full">
      {message.tools.length > 0 ? (
        <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Data the assistant used">
          {message.tools.map((chip, index) => (
            <li
              key={`${chip.name}-${index}`}
              className={`rounded-full border px-2 py-px text-[0.68rem] ${
                chip.done && !chip.ok ? "border-up/40 text-up" : "border-border text-muted"
              }`}
            >
              {chip.done ? (chip.ok ? "✓ " : "! ") : "… "}
              {toolLabel(chip.name)}
            </li>
          ))}
        </ul>
      ) : null}
      {message.text !== "" ? (
        <div dir="auto" className="space-y-2 text-sm leading-relaxed">
          {parseMarkdown(message.text).map((block, index) => (
            <BlockView key={index} block={block} />
          ))}
        </div>
      ) : message.streaming && message.error === null ? (
        <p className="text-sm text-muted">Thinking…</p>
      ) : null}
      {message.streaming && message.text !== "" ? <span aria-hidden="true" className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-accent align-middle" /> : null}
      {message.error ? (
        <p role="alert" className="mt-2 rounded-md border border-up/40 bg-up/10 px-3 py-2 text-xs">
          {message.error}
        </p>
      ) : null}
      {message.disclaimer ? <p className="mt-2 border-t border-border pt-2 text-[0.68rem] leading-snug text-muted">{message.disclaimer}</p> : null}
    </div>
  );
}

function InlineView({ parts }: { parts: Inline[] }) {
  return (
    <>
      {parts.map((part, index) =>
        part.kind === "bold" ? (
          <strong key={index}>{part.text}</strong>
        ) : part.kind === "code" ? (
          <code key={index} className="rounded bg-surface-raised px-1 py-px font-mono text-[0.8em]">
            {part.text}
          </code>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </>
  );
}

function BlockView({ block }: { block: Block }) {
  if (block.kind === "paragraph") {
    return (
      <p>
        <InlineView parts={block.inlines} />
      </p>
    );
  }
  const List = block.kind === "numbered" ? "ol" : "ul";
  return (
    <List className={`space-y-1 ps-5 ${block.kind === "numbered" ? "list-decimal" : "list-disc"}`}>
      {block.items.map((item, index) => (
        <li key={index}>
          <InlineView parts={item} />
        </li>
      ))}
    </List>
  );
}
