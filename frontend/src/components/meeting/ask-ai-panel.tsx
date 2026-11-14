"use client";

import { FormEvent, useState } from "react";
import { api, ApiError, ChatSource } from "@/lib/api";
import { CitedMarkdown, ResolvedCitation } from "@/components/cited-markdown";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, Send, Sparkles } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources: ChatSource[];
}

const SUGGESTIONS = [
  "What was decided, and why?",
  "List the action items with their stated owners.",
  "What is still unresolved?",
  "Summarize what was said about deadlines.",
];

/** Questions about this one meeting. Answers cite transcript lines; clicking
 * a citation plays (or shows) that exact moment. */
export function AskAiPanel({
  meetingId,
  onCite,
}: {
  meetingId: string;
  onCite: (citation: ResolvedCitation) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(question: string) {
    const query = question.trim();
    if (!query || busy) return;
    setBusy(true);
    setError(null);
    setInput("");
    setMessages((current) => [...current, { role: "user", content: query, sources: [] }]);
    try {
      const response = await api.chat(
        query,
        conversationId ? undefined : meetingId,
        conversationId,
        messages.map(({ role, content }) => ({ role, content })),
      );
      setConversationId(response.conversation_id);
      setMessages((current) => [...current, { role: "assistant", content: response.answer, sources: response.sources }]);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The question could not be answered");
      setMessages((current) => current.slice(0, -1));
      setInput(query);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(input);
  }

  return (
    <div className="flex flex-col gap-4">
      {messages.length === 0 && (
        <div className="rounded-lg border border-dashed p-4">
          <p className="flex items-center gap-2 text-sm font-medium"><Sparkles className="h-4 w-4 text-primary" /> Ask about this meeting</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Answers come only from this meeting&apos;s transcript and notes, with a citation for every claim. If the meeting doesn&apos;t
            say, the answer will say so.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {SUGGESTIONS.map((suggestion) => (
              <Button key={suggestion} size="sm" variant="outline" onClick={() => void ask(suggestion)} disabled={busy}>
                {suggestion}
              </Button>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3" aria-live="polite">
        {messages.map((message, index) =>
          message.role === "user" ? (
            <div key={index} className="self-end rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground sm:max-w-[80%]">
              {message.content}
            </div>
          ) : (
            <div key={index} className="rounded-lg border bg-card px-3 py-2.5 sm:max-w-[90%]">
              <CitedMarkdown content={message.content} sources={message.sources} onCite={onCite} />
            </div>
          ),
        )}
        {busy && (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading the transcript…
          </p>
        )}
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <form onSubmit={submit} className="flex items-end gap-2">
        <Textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void ask(input);
            }
          }}
          placeholder="Ask a question about this meeting"
          aria-label="Question about this meeting"
          rows={2}
          className="min-h-0"
        />
        <Button type="submit" disabled={busy || !input.trim()} aria-label="Ask">
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
