"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  PolicyConversationSummary,
  PolicyMessage,
  PolicySource,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ChatMarkdown } from "@/components/chat-markdown";
import { ChatActions } from "@/components/chat-actions";
import {
  BookOpenCheck,
  ChevronDown,
  ChevronRight,
  FileCheck2,
  FileText,
  Plus,
  Send,
  Sparkles,
  Trash2,
} from "lucide-react";

import { useStickToBottom } from "@/lib/use-stick-to-bottom";
const SUGGESTIONS = [
  "Give me an overview of our HR policies",
  "How many casual leave days do I get?",
  "What is the resignation notice period?",
  "Which holidays are coming up?",
];

function messageTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function PolicyPage() {
  const [conversations, setConversations] = useState<PolicyConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<PolicyMessage[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null);

  function refreshConversations() {
    api.listPolicyConversations().then(setConversations).catch(() => {});
  }

  useEffect(() => {
    refreshConversations();
  }, []);

  const stick = useStickToBottom();

  async function openConversation(id: string) {
    setActiveId(id);
    setError(null);
    setLastFailedQuestion(null);
    try {
      const detail = await api.getPolicyConversation(id);
      setMessages(detail.messages);
    } catch {
      setError("This conversation could not be loaded. Start a new chat and try again.");
    }
  }

  function startNewConversation() {
    setActiveId(null);
    setMessages([]);
    setError(null);
    setQuery("");
    setLastFailedQuestion(null);
  }

  async function deleteConversation(id: string, event: React.MouseEvent) {
    event.stopPropagation();
    await api.deletePolicyConversation(id).catch(() => {});
    if (activeId === id) startNewConversation();
    refreshConversations();
  }

  async function ask(question: string) {
    if (!question || busy) return;
    stick.pin();

    const now = new Date().toISOString();
    setMessages((previous) => [
      ...previous,
      { role: "user", content: question, sources: null, created_at: now },
    ]);
    setQuery("");
    setBusy(true);
    setError(null);
    setLastFailedQuestion(null);

    try {
      const result = await api.askPolicy(question, activeId ?? undefined);
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: result.answer,
          sources: result.sources,
          created_at: new Date().toISOString(),
        },
      ]);
      if (!activeId) setActiveId(result.conversation_id);
      refreshConversations();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The policy assistant could not answer. Check the connection and try again."
      );
      setLastFailedQuestion(question);
    } finally {
      setBusy(false);
    }
  }

  function retryAnswer(index: number) {
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      if (messages[cursor].role === "user") {
        void ask(messages[cursor].content);
        return;
      }
    }
  }

  return (
    <div className="grid grid-cols-1 h-[calc(100dvh-3.5rem)] min-h-0 w-full overflow-hidden bg-card lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="flex max-h-48 flex-col border-b bg-muted/50 lg:max-h-none lg:border-r lg:border-b-0">
        <div className="border-b px-4 py-4">
          <div className="mb-4 flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-foreground">
              <BookOpenCheck className="h-[18px] w-[18px]" />
            </span>
            <div>
              <p className="text-sm font-semibold text-foreground">Policy desk</p>
              <p className="text-[11px] text-muted-foreground">Bhadra handbook</p>
            </div>
          </div>
          <Button className="w-full justify-start gap-2" size="sm" onClick={startNewConversation}>
            <Plus className="h-3.5 w-3.5" />
            New conversation
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
          <p className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Recent
          </p>
          {conversations.length === 0 && (
            <p className="px-2 py-3 text-xs leading-5 text-muted-foreground">
              Your policy conversations will appear here.
            </p>
          )}
          <div className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                onClick={() => openConversation(conversation.id)}
                className={`group flex min-w-44 items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-left text-xs transition-colors lg:min-w-0 ${
                  activeId === conversation.id
                    ? "bg-card text-foreground shadow-sm ring-1 ring-foreground/10"
                    : "text-muted-foreground hover:bg-card/70 hover:text-foreground"
                }`}
              >
                <span className="truncate">{conversation.title}</span>
                <span
                  role="button"
                  tabIndex={0}
                  aria-label="Delete conversation"
                  onClick={(event) => deleteConversation(conversation.id, event)}
                  className="shrink-0 rounded-md p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 group-focus:opacity-100"
                >
                  <Trash2 className="h-3 w-3" />
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="hidden border-t px-4 py-3 text-[11px] leading-4 text-muted-foreground lg:block">
          Answers use the Employee Handbook and FY 2026–27 Holiday Calendar only.
        </div>
      </aside>

      <section className="flex min-h-0 flex-col bg-muted/50">
        <header className="flex items-center justify-between gap-4 border-b bg-card/85 px-5 py-4 backdrop-blur-sm sm:px-8">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold tracking-tight text-foreground">Ask Bhadra Policy</h1>
              <span className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-foreground">
                <FileCheck2 className="h-3 w-3" /> Grounded
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Leave, attendance, notice periods, IT assets, conduct and holidays
            </p>
          </div>
        </header>

        <div ref={stick.panelRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          <div className="mx-auto flex w-full max-w-[760px] flex-col gap-7">
            {messages.length === 0 && (
              <div className="flex min-h-[420px] flex-col items-center justify-center text-center">
                <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-foreground shadow-sm">
                  <Sparkles className="h-5 w-5" />
                </span>
                <h2 className="text-xl font-semibold tracking-tight text-foreground">
                  What would you like to clarify?
                </h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                  Ask naturally. I’ll answer from approved company documents and show exactly where the answer came from.
                </p>
                <div className="mt-6 grid grid-cols-1 w-full max-w-2xl gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => ask(suggestion)}
                      className="rounded-xl border bg-card px-4 py-3 text-left text-sm text-foreground shadow-sm transition-all hover:-translate-y-0.5 hover:border-border hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((entry, index) =>
              entry.role === "user" ? (
                <div key={index} className="flex max-w-[82%] flex-col items-end self-end">
                  <div className="rounded-[20px] rounded-br-md bg-primary px-4 py-3 text-sm leading-6 text-primary-foreground shadow-sm">
                    <p className="whitespace-pre-wrap">{entry.content}</p>
                  </div>
                  <span className="mt-1.5 pr-1 text-[10px] text-muted-foreground">
                    You · {messageTime(entry.created_at)}
                  </span>
                </div>
              ) : (
                <div key={index} className="flex max-w-[94%] items-start gap-3 self-start">
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent text-foreground">
                    <Sparkles className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="mb-1.5 flex items-center gap-2">
                      <span className="text-xs font-semibold text-foreground">Policy assistant</span>
                      <span className="text-[10px] text-muted-foreground">{messageTime(entry.created_at)}</span>
                    </div>
                    <div className="rounded-[20px] rounded-tl-md border bg-card px-4 py-4 leading-6 shadow-[0_10px_28px_-24px_rgba(15,45,38,0.7)] sm:px-5">
                      <ChatMarkdown content={entry.content} />
                      {entry.sources && entry.sources.length > 0 && (
                        <SourceList sources={entry.sources} />
                      )}
                    </div>
                    <ChatActions content={entry.content} onRetry={() => retryAnswer(index)} />
                  </div>
                </div>
              )
            )}

            {busy && (
              <div className="flex items-center gap-3 self-start">
                <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent text-foreground">
                  <Sparkles className="h-3.5 w-3.5 animate-pulse" />
                </span>
                <div className="rounded-2xl rounded-tl-md border bg-card px-4 py-3 text-sm text-muted-foreground shadow-sm">
                  Reading the policy documents<span className="animate-pulse">…</span>
                </div>
              </div>
            )}

            {error && (
              <div className="flex items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                <span>{error}</span>
                {lastFailedQuestion && (
                  <button type="button" className="shrink-0 font-semibold underline" onClick={() => ask(lastFailedQuestion)}>
                    Try again
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="border-t bg-card px-4 py-4 sm:px-8">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              ask(query.trim());
            }}
            className="mx-auto flex max-w-[760px] items-end gap-2 rounded-2xl border bg-muted/50 p-2 shadow-[0_12px_32px_-24px_rgba(15,45,38,0.7)] focus-within:border-primary/40 focus-within:ring-3 focus-within:ring-primary/10"
          >
            <Textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  ask(query.trim());
                }
              }}
              placeholder="Ask a policy question…"
              rows={2}
              className="min-h-12 resize-none border-0 bg-transparent px-3 py-2 shadow-none focus-visible:ring-0"
            />
            <Button
              type="submit"
              size="icon"
              disabled={busy || !query.trim()}
              aria-label="Send question"
              className="h-10 w-10 shrink-0 rounded-xl"
            >
              <Send className="h-4 w-4" />
            </Button>
          </form>
          <p className="mx-auto mt-2 max-w-[760px] text-center text-[10px] text-muted-foreground">
            For decisions affecting your employment, confirm the answer with People First.
          </p>
        </div>
      </section>
    </div>
  );
}

function SourceList({ sources }: { sources: PolicySource[] }) {
  return (
    <details className="group/evidence mt-4 border-t pt-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-medium text-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary/20">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-accent text-foreground">
          <FileText className="h-3.5 w-3.5" />
        </span>
        Sources · {sources.length} policy section{sources.length === 1 ? "" : "s"}
        <ChevronDown className="ml-auto h-3.5 w-3.5 transition-transform group-open/evidence:rotate-180" />
      </summary>
      <div className="mt-3 max-h-72 space-y-2 overflow-y-auto rounded-xl border bg-muted/50 p-2">
        {sources.map((source, index) => (
          <details key={`${source.document}-${source.section}-${index}`} className="group/source rounded-lg bg-card ring-1 ring-foreground/10">
            <summary className="flex cursor-pointer list-none items-start gap-2 px-3 py-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/20">
              <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-open/source:rotate-90" />
              <span className="min-w-0">
                <span className="block truncate text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {source.document}
                </span>
                <span className="mt-0.5 block text-xs font-medium leading-5 text-foreground">
                  {source.section}
                </span>
              </span>
            </summary>
            <p className="border-t px-4 py-3 text-xs leading-5 text-muted-foreground">
              {source.text}
            </p>
          </details>
        ))}
      </div>
    </details>
  );
}
