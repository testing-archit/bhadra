"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  ChatHistoryMessage,
  ChatSource,
  MemoryConversationSummary,
  MeetingSummary,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ChatMarkdown } from "@/components/chat-markdown";
import { CitedMarkdown, ResolvedCitation } from "@/components/cited-markdown";
import { ChatActions } from "@/components/chat-actions";
import { VoiceAskButton } from "@/components/voice-ask-button";
import {
  CalendarDays,
  ChevronDown,
  ExternalLink,
  FileSearch,
  MessagesSquare,
  Plus,
  Search,
  Send,
  Sparkles,
  Trash2,
  Video,
  Check,
} from "lucide-react";

import { useStickToBottom } from "@/lib/use-stick-to-bottom";
const MAX_SCOPE = 10;

interface ChatEntry extends ChatHistoryMessage {
  sources?: ChatSource[];
  createdAt: string;
  /** Answer to a spoken question: read aloud as soon as it arrives. */
  spoken?: boolean;
}

const SUGGESTIONS = [
  "What decisions changed recently?",
  "Which tasks are still open?",
  "Summarize the biggest project risks",
  "What should I follow up on this week?",
];

function messageTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function MemoryPage() {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [conversations, setConversations] = useState<MemoryConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFailedQuestion, setLastFailedQuestion] = useState<string | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [meetingSearch, setMeetingSearch] = useState("");
  // An explicit set of meetings to ask across. Empty means all company memory.
  const [scope, setScope] = useState<MeetingSummary[]>([]);
  const scopedMeeting = scope.length === 1 ? scope[0] : null;
  const router = useRouter();

  useEffect(() => {
    api.listMeetings().then(setMeetings).catch(() => setMeetings([]));
    refreshConversations();
  }, []);

  function refreshConversations() {
    api.listMemoryConversations().then(setConversations).catch(() => {});
  }

  const stick = useStickToBottom();

  const visibleMeetings = useMemo(() => {
    const search = meetingSearch.trim().toLocaleLowerCase();
    return meetings
      .filter((meeting) => !search || meeting.title.toLocaleLowerCase().includes(search))
      .slice(0, 12);
  }, [meetingSearch, meetings]);

  function startNewChat(nextScope: MeetingSummary[] = scope) {
    setActiveId(null);
    setScope(nextScope);
    setEntries([]);
    setQuery("");
    setError(null);
    setLastFailedQuestion(null);
  }

  function chooseScope(meeting: MeetingSummary | null) {
    startNewChat(meeting ? [meeting] : []);
  }

  /** Add or remove a meeting from the scope. Changing scope starts a new
   * chat, since earlier answers were grounded in different meetings. */
  function toggleScope(meeting: MeetingSummary) {
    const selected = scope.some((item) => item.id === meeting.id);
    if (!selected && scope.length >= MAX_SCOPE) {
      setError(`Select at most ${MAX_SCOPE} meetings`);
      return;
    }
    startNewChat(selected ? scope.filter((item) => item.id !== meeting.id) : [...scope, meeting]);
  }

  function openCitation(citation: ResolvedCitation) {
    const meetingId = citation.source.meeting_id;
    if (!meetingId) return;
    const segment = citation.segment;
    const params = new URLSearchParams();
    if (segment?.segment_id) {
      params.set("segment", segment.segment_id);
      if (segment.start_ms !== null) params.set("t", String(segment.start_ms));
    }
    router.push(`/meetings/${meetingId}${params.size ? `?${params}` : ""}`);
  }

  async function openConversation(conversation: MemoryConversationSummary) {
    setActiveId(conversation.id);
    setError(null);
    setLastFailedQuestion(null);
    try {
      const detail = await api.getMemoryConversation(conversation.id);
      setEntries(detail.messages.map((message) => ({
        role: message.role,
        content: message.content,
        sources: message.sources ?? undefined,
        createdAt: message.created_at,
      })));
      const ids = detail.scope_meeting_ids?.length ? detail.scope_meeting_ids : detail.meeting_id ? [detail.meeting_id] : [];
      setScope(meetings.filter((meeting) => ids.includes(meeting.id)));
    } catch {
      setError("This conversation could not be loaded. Start a new chat and try again.");
    }
  }

  async function deleteConversation(id: string, event: React.MouseEvent) {
    event.stopPropagation();
    await api.deleteMemoryConversation(id).catch(() => {});
    if (activeId === id) startNewChat([]);
    refreshConversations();
  }

  async function ask(question: string, spoken = false) {
    if (!question || busy) return;
    stick.pin();
    const history = entries.map(({ role, content }) => ({ role, content }));
    setEntries((previous) => [
      ...previous,
      { role: "user", content: question, createdAt: new Date().toISOString() },
    ]);
    setQuery("");
    setBusy(true);
    setError(null);
    setLastFailedQuestion(null);

    try {
      const result = await api.chat(
        question,
        scope.length === 1 ? scope[0].id : undefined,
        activeId ?? undefined,
        history,
        scope.length > 1 ? scope.map((meeting) => meeting.id) : [],
      );
      setEntries((previous) => [
        ...previous,
        {
          role: "assistant",
          content: result.answer,
          sources: result.sources,
          createdAt: new Date().toISOString(),
          spoken,
        },
      ]);
      if (!activeId) setActiveId(result.conversation_id);
      refreshConversations();
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Company Memory could not answer. Check the connection and try again."
      );
      setLastFailedQuestion(question);
    } finally {
      setBusy(false);
    }
  }

  // A question handed over from the command palette or the Chrome extension
  // (/memory?q=...) is asked straight away, once, then dropped from the URL
  // so a refresh doesn't ask it again.
  const askedFromUrl = useRef(false);
  useEffect(() => {
    if (askedFromUrl.current) return;
    askedFromUrl.current = true;
    const url = new URL(window.location.href);
    const handed = url.searchParams.get("q")?.trim();
    if (!handed) return;
    const spoken = url.searchParams.get("voice") === "1";
    url.searchParams.delete("q");
    url.searchParams.delete("voice");
    window.history.replaceState(null, "", url);
    void ask(handed, spoken);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function retryAnswer(index: number) {
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      if (entries[cursor].role === "user") {
        void ask(entries[cursor].content);
        return;
      }
    }
  }

  return (
    <div className="grid grid-cols-1 h-[calc(100dvh-3.5rem)] min-h-0 w-full overflow-hidden bg-card lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="flex min-h-0 max-h-52 flex-col border-b bg-muted lg:max-h-none lg:border-r lg:border-b-0">
        <div className="border-b px-4 py-4">
          <div className="mb-4 flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-foreground">
              <MessagesSquare className="h-[18px] w-[18px]" />
            </span>
            <div>
              <p className="text-sm font-semibold text-foreground">Company memory</p>
              <p className="text-[11px] text-muted-foreground">Meetings, decisions and work</p>
            </div>
          </div>
          <Button className="w-full justify-start gap-2" size="sm" onClick={() => startNewChat()}>
            <Plus className="h-3.5 w-3.5" /> New chat
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
          <p className="px-2 pb-2 text-xs font-semibold text-muted-foreground">
            Recent chats
          </p>
          {conversations.length === 0 && (
            <p className="px-2 pb-3 text-xs leading-5 text-muted-foreground">Your saved chats will appear here.</p>
          )}
          <div className="mb-4 flex gap-1 overflow-x-auto border-b pb-3 lg:flex-col lg:overflow-visible">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                onClick={() => void openConversation(conversation)}
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
                  aria-label="Delete memory conversation"
                  onClick={(event) => void deleteConversation(conversation.id, event)}
                  className="shrink-0 rounded-md p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 group-focus:opacity-100"
                >
                  <Trash2 className="h-3 w-3" />
                </span>
              </button>
            ))}
          </div>
          <p className="px-2 pb-2 text-xs font-semibold text-muted-foreground">
            Search scope
          </p>
          <button
            type="button"
            onClick={() => chooseScope(null)}
            className={`mb-2 flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-xs transition-colors ${
              scope.length === 0
                ? "bg-card text-foreground shadow-sm ring-1 ring-foreground/10"
                : "text-muted-foreground hover:bg-card/70 hover:text-foreground"
            }`}
          >
            <FileSearch className="h-3.5 w-3.5" /> All company memory
          </button>
          <div className="relative mb-2">
            <Search className="absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={meetingSearch}
              onChange={(event) => setMeetingSearch(event.target.value)}
              placeholder="Find a meeting"
              className="h-8 bg-card pl-8 text-xs"
            />
          </div>
          <p className="px-2 pb-1.5 text-[10px] text-muted-foreground">Pick one meeting, or several to compare them.</p>
          <div className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
            {visibleMeetings.map((meeting) => {
              const selected = scope.some((item) => item.id === meeting.id);
              return (
                <button
                  key={meeting.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => toggleScope(meeting)}
                  className={`flex min-w-48 items-start gap-2 rounded-xl px-3 py-2.5 text-left transition-colors lg:min-w-0 ${
                    selected ? "bg-card shadow-sm ring-1 ring-foreground/10" : "hover:bg-card/70"
                  }`}
                >
                  <span className={`mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border ${selected ? "border-primary bg-primary text-primary-foreground" : "bg-card"}`}>
                    {selected && <Check className="h-2.5 w-2.5" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium text-foreground">{meeting.title}</span>
                    <span className="mt-0.5 block text-[10px] text-muted-foreground">
                      {new Date(meeting.date).toLocaleDateString()}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="hidden border-t px-4 py-3 text-[11px] leading-4 text-muted-foreground lg:block">
          Short follow-ups stay connected to the current conversation and selected scope.
        </div>
      </aside>

      <section className="flex min-h-0 flex-col bg-muted/50">
        <header className="flex items-center justify-between gap-4 border-b bg-card/85 px-5 py-4 backdrop-blur-sm sm:px-8">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-base font-semibold tracking-tight text-foreground">
                {scopedMeeting ? scopedMeeting.title : scope.length > 1 ? `${scope.length} selected meetings` : "Ask Company Memory"}
              </h1>
              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-tint-mint px-2 py-0.5 text-xs font-medium text-tint-mint-foreground">
                <Sparkles className="h-3 w-3" /> Grounded
              </span>
            </div>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {scopedMeeting
                ? "Answers are limited to this meeting’s transcript, tasks and decisions"
                : scope.length > 1
                ? "Answers compare only these meetings, citing the exact lines"
                : "Search across meeting transcripts, decisions, tasks and risks"}
            </p>
          </div>
          {scope.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => chooseScope(null)}>
              Search all
            </Button>
          )}
        </header>

        <div ref={stick.panelRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          <div className="mx-auto flex w-full max-w-[760px] flex-col gap-7">
            {entries.length === 0 && (
              <div className="flex min-h-[420px] flex-col items-center justify-center text-center">
                <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-foreground shadow-sm">
                  {scopedMeeting ? <Video className="h-5 w-5" /> : <Sparkles className="h-5 w-5" />}
                </span>
                <h2 className="text-xl font-semibold tracking-tight text-foreground">
                  {scopedMeeting ? "Ask about this meeting" : "What do you need to remember?"}
                </h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                  {scopedMeeting
                    ? "Ask about its decisions, owners, deadlines, risks, or anything in the transcript."
                    : "Ask naturally, then continue with follow-ups. Every factual answer links back to its meetings."}
                </p>
                <div className="mt-6 grid grid-cols-1 w-full max-w-2xl gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => ask(suggestion)}
                      className="rounded-xl border bg-card px-4 py-3 text-left text-sm text-foreground shadow-sm transition-all hover:-translate-y-0.5 hover:border-border hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {entries.map((entry, index) =>
              entry.role === "user" ? (
                <div key={index} className="flex max-w-[82%] flex-col items-end self-end">
                  <div className="rounded-[20px] rounded-br-md bg-primary px-4 py-3 text-sm leading-6 text-primary-foreground shadow-sm">
                    <p className="whitespace-pre-wrap">{entry.content}</p>
                  </div>
                  <span className="mt-1.5 pr-1 text-[10px] text-muted-foreground">
                    You · {messageTime(entry.createdAt)}
                  </span>
                </div>
              ) : (
                <div key={index} className="flex max-w-[94%] items-start gap-3 self-start">
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent text-foreground">
                    <Sparkles className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="mb-1.5 flex items-center gap-2">
                      <span className="text-xs font-semibold text-foreground">Memory assistant</span>
                      <span className="text-[10px] text-muted-foreground">{messageTime(entry.createdAt)}</span>
                    </div>
                    <div className="rounded-[20px] rounded-tl-md border bg-card px-4 py-4 leading-6 shadow-[0_10px_28px_-24px_rgba(15,45,38,0.7)] sm:px-5">
                      {entry.sources?.some((source) => source.tag) ? (
                        <CitedMarkdown content={entry.content} sources={entry.sources} onCite={openCitation} />
                      ) : (
                        <ChatMarkdown content={entry.content} />
                      )}
                      {entry.sources && entry.sources.length > 0 && <MemorySources sources={entry.sources} />}
                    </div>
                    <ChatActions content={entry.content} onRetry={() => retryAnswer(index)} speak={entry.spoken} />
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
                  Searching company memory<span className="animate-pulse">…</span>
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
              void ask(query.trim());
            }}
            className="mx-auto flex max-w-[760px] items-end gap-2 rounded-2xl border bg-muted/50 p-2 shadow-[0_12px_32px_-24px_rgba(15,45,38,0.7)] focus-within:border-primary/40 focus-within:ring-3 focus-within:ring-primary/10"
          >
            <Textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void ask(query.trim());
                }
              }}
              placeholder={scopedMeeting ? `Ask about “${scopedMeeting.title}”…` : scope.length > 1 ? "Ask across the selected meetings…" : "Ask company memory…"}
              rows={2}
              className="min-h-12 resize-none border-0 bg-transparent px-3 py-2 shadow-none focus-visible:ring-0"
            />
            <VoiceAskButton disabled={busy} onQuestion={(text) => void ask(text, true)} onError={setError} />
            <Button type="submit" size="icon" disabled={busy || !query.trim()} aria-label="Send question" className="h-10 w-10 shrink-0 rounded-xl">
              <Send className="h-4 w-4" />
            </Button>
          </form>
          <p className="mx-auto mt-2 max-w-[760px] text-center text-[10px] text-muted-foreground">
            Type or tap the mic and ask in Hindi, English or both. Wilco answers from captured meeting records and reads spoken questions' answers aloud.
          </p>
        </div>
      </section>
    </div>
  );
}

function MemorySources({ sources }: { sources: ChatSource[] }) {
  return (
    <details className="group/sources mt-4 border-t pt-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-medium text-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary/20">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-accent text-foreground">
          <CalendarDays className="h-3.5 w-3.5" />
        </span>
        Sources · {sources.length} meeting{sources.length === 1 ? "" : "s"}
        <ChevronDown className="ml-auto h-3.5 w-3.5 transition-transform group-open/sources:rotate-180" />
      </summary>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {sources.map((source, index) => {
          const body = (
            <>
              <span className="block truncate text-xs font-medium text-foreground">{source.meeting_title}</span>
              <span className="mt-1 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                {new Date(source.meeting_date).toLocaleDateString()}
                {source.segments && source.segments.length > 0 && ` · ${source.segments.length} cited line${source.segments.length === 1 ? "" : "s"}`}
                {source.meeting_id && <ExternalLink className="ml-auto h-3 w-3" />}
              </span>
            </>
          );
          return source.meeting_id ? (
            <Link key={`${source.meeting_id}-${index}`} href={`/meetings/${source.meeting_id}`} className="rounded-lg border bg-muted/50 px-3 py-2.5 transition-colors hover:border-border hover:bg-card">
              {body}
            </Link>
          ) : (
            <div key={`${source.meeting_title}-${index}`} className="rounded-lg border bg-muted/50 px-3 py-2.5">
              {body}
            </div>
          );
        })}
      </div>
    </details>
  );
}
